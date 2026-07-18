#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weekly_summary.py — סיכום שבוע ההרצה הראשון + חקירת פקיעת 17/7 שלא נסגרה.

**קריאה בלבד (SELECT בלבד).** אפס INSERT/UPDATE/DELETE. אפס כתיבה ל-DB.
DATABASE_URL נקרא מהסביבה בלבד — לעולם לא בקוד ולא בפלט.

5 חלקים:
  1. חקירת 17/7 (הדחוף) — עסקה #33: תקין-ומחכה או תקלה? (סטלמנט? cron של auto_close?)
  2. סיכום השבוע — תיק ההמלצות (פקיעות 14–17/7): P&L, ממומש, Win Rate, מול 537₪/שבוע.
  3. ולידציית מרווח שבועית — לכל פקיעה: המלצה, תנועה בפועל, החזיק/נשבר, implied מול בפועל.
  4. מבט קדימה — עסקאות פתוחות (21–23/7) + ה-implied העדכני לכל אחת.
  5. Benchmark — תיק ה-IC הקבוע (תיק 3) על אותן פקיעות: "דינמי מול קבוע".

הרצה (הזרקת הסוד inline, לא נשמר בהיסטוריית shell אם מקדימים ברווח):
    DATABASE_URL="postgresql://..." python3 scripts/weekly_summary.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, text

# ─── קבועים ────────────────────────────────────────────────────────────────
RECO_STRATEGY_ID   = 102                 # תיק ההמלצות (מבודד מ-decision_validator)
BENCH_PORTFOLIO_ID = 3                   # תיק ה-IC הקבוע (2.0/1.0) — "הקבוע"
FEAR_TRADE_ID      = 33                  # העסקה הדחופה (פקיעה 17/7)
TARGET_EXPIRY      = date(2026, 7, 17)   # פקיעת שישי שלא נסגרה
WEEK_START         = date(2026, 7, 14)   # פקיעות השבוע: 14–17/7
WEEK_END           = date(2026, 7, 17)
SIM_WEEKLY_AVG     = 537.0               # ממוצע ארוך-טווח מהסימולציה (₪/שבוע)

# cron של auto_close: '0 7-13 * * 0-4' — DOW 0–4 (ראשון–חמישי), שעות 07–13 UTC.
CRON_DOWS  = {0, 1, 2, 3, 4}             # pg-style: ראשון=0 ... חמישי=4 (שישי=5, שבת=6)
CRON_HOURS = set(range(7, 14))           # 07:00–13:00 UTC
_DOW_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]  # אינדקס pg-DOW


def _pg_dow(d: date) -> int:
    """DOW בסגנון Postgres: ראשון=0 ... שבת=6 (Python weekday: שני=0 ... ראשון=6)."""
    return (d.weekday() + 1) % 7


def _engine():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        sys.exit('DATABASE_URL לא מוגדר. הרץ:  DATABASE_URL="postgresql://..." python3 scripts/weekly_summary.py')
    return create_engine(url.replace("postgres://", "postgresql://", 1), pool_pre_ping=True)


def _loads(v):
    """JSONB → dict. psycopg2 בד"כ כבר מחזיר dict; מטפל גם ב-str/None להגנה."""
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v, nd=2, suf=""):
    return "—" if v is None else f"{v:,.{nd}f}{suf}"


def _hr(ch="─", n=78):
    print(ch * n)


def _title(txt):
    print()
    _hr("═")
    print(txt)
    _hr("═")


# ─── cron: מתי auto_close רץ לאחרונה ומתי הבא ────────────────────────────────

def _prev_next_cron(now: datetime):
    """הריצה המתוזמנת הקודמת והבאה של auto_close לפי ה-cron (DOW 0–4, שעות 07–13 UTC).

    לא ניגש ל-GitHub — משחזר מהספֵק. מחזיר (prev_dt, next_dt) ב-UTC.
    """
    base = now.replace(minute=0, second=0, microsecond=0)

    prev = None
    t = base if now.minute == 0 and now.second == 0 else base  # נתחיל מהשעה הנוכחית ונרד
    for _ in range(24 * 14):
        t -= timedelta(hours=1)
        if _pg_dow(t.date()) in CRON_DOWS and t.hour in CRON_HOURS:
            prev = t
            break

    nxt = None
    t = base
    for _ in range(24 * 14):
        t += timedelta(hours=1)
        if _pg_dow(t.date()) in CRON_DOWS and t.hour in CRON_HOURS:
            nxt = t
            break
    return prev, nxt


# ─── מפות עזר משותפות ──────────────────────────────────────────────────────

def _settlement_map(eng) -> dict:
    """{פקיעה(date) → actual_index_close} מ-condor_settled_detail. expiry_date הוא TEXT → ::date."""
    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT expiry_date::date AS d, MAX(actual_index_close) AS c
            FROM condor_settled_detail
            WHERE actual_index_close IS NOT NULL
            GROUP BY expiry_date::date
        """)).fetchall()
    out = {}
    for r in rows:
        m = r._mapping
        if m["d"] is not None and m["c"] is not None:
            out[m["d"]] = float(m["c"])
    return out


def _latest_recs(eng, d_from: date, d_to: date) -> dict:
    """ההמלצה האחרונה (MAX recommended_at) לכל פקיעה בטווח. {date → dict}."""
    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (expiry_date::date)
                   expiry_date::date          AS exp,
                   margin_pct, hold_blended, premium_ils,
                   short_put_strike, short_call_strike,
                   engine_version, recommended_at, recommendation_json
            FROM margin_recommendations
            WHERE expiry_date::date BETWEEN :a AND :b
            ORDER BY expiry_date::date, recommended_at DESC
        """), {"a": d_from, "b": d_to}).fetchall()
    out = {}
    for r in rows:
        m = dict(r._mapping)
        rj = _loads(m.get("recommendation_json"))
        im = rj.get("implied_move") or {}
        m["rj"] = rj
        m["base_index"] = _num(rj.get("base_index")) or _num((rj.get("selected_curve_row") or {}).get("base_index"))
        m["implied_expected_pct"] = _num(im.get("expected_move_pct"))
        m["implied_expected_pts"] = _num(im.get("expected_move_pts"))
        m["implied_daily_pct"]    = _num(im.get("implied_daily_pct"))
        m["implied_vs_margin"]    = _num(im.get("implied_vs_margin"))
        m["implied_present"]      = bool(im) and not im.get("skipped", False)
        out[m["exp"]] = m
    return out


# ─── חלק 1: חקירת 17/7 ──────────────────────────────────────────────────────

def part1_investigate(eng, settlements: dict):
    _title("① חקירת 17/7 (הדחוף) — עסקה #33, פקיעה 2026-07-17")

    # 1a. עסקה #33
    with eng.connect() as conn:
        row = conn.execute(text("""
            SELECT id, portfolio_id, strategy_id, strategy_name,
                   expiry_date::date::text AS exp, status, opened_at, closed_at,
                   entry_index, close_index, entry_cost, pnl, pnl_pct, max_loss, max_profit
            FROM paper_trades WHERE id = :tid
        """), {"tid": FEAR_TRADE_ID}).fetchone()

    if row is None:
        print(f"⚠️  עסקה #{FEAR_TRADE_ID} לא נמצאה. בודק לפי פקיעה במקום…")
        trade = None
    else:
        trade = dict(row._mapping)
        print(f"עסקה #{trade['id']}: תיק {trade['portfolio_id']} | strategy_id {trade['strategy_id']} "
              f"| {trade['strategy_name']}")
        print(f"  פקיעה: {trade['exp']} | סטטוס: {trade['status'].upper()} "
              f"| נפתחה: {trade['opened_at']} | נסגרה: {trade['closed_at'] or '—'}")
        print(f"  entry_index: {_fmt(trade['entry_index'])} | close_index: {_fmt(trade['close_index'])} "
              f"| P&L: {_fmt(trade['pnl'])} ₪")

    # כל עסקאות ההמלצות לפקיעה זו (הצלבה)
    with eng.connect() as conn:
        others = conn.execute(text("""
            SELECT id, portfolio_id, strategy_id, status, pnl
            FROM paper_trades
            WHERE expiry_date::date = :exp AND strategy_id = :sid
            ORDER BY id
        """), {"exp": TARGET_EXPIRY, "sid": RECO_STRATEGY_ID}).fetchall()
    if others:
        print(f"  עסקאות המלצה לפקיעה {TARGET_EXPIRY}: "
              + ", ".join(f"#{o._mapping['id']}({o._mapping['status']})" for o in others))

    # 1b. סטלמנט ל-17/7?
    stl = settlements.get(TARGET_EXPIRY)
    print()
    if stl is not None:
        print(f"סטלמנט ב-condor_settled_detail ל-{TARGET_EXPIRY}: קיים ✅  (actual_index_close = {_fmt(stl)})")
    else:
        print(f"סטלמנט ב-condor_settled_detail ל-{TARGET_EXPIRY}: לא קיים ❌")

    # 1c. cron של auto_close
    now = datetime.now(tz=timezone.utc)
    prev, nxt = _prev_next_cron(now)
    dow_he = _DOW_HE[_pg_dow(TARGET_EXPIRY)]
    print()
    print(f"יום הפקיעה 17/7 = {dow_he} (pg-DOW={_pg_dow(TARGET_EXPIRY)}).")
    print("cron של auto_close:  '0 7-13 * * 0-4'  →  ראשון–חמישי בלבד, 07–13 UTC.")
    print("  ⇒ שישי (DOW 5) ושבת (DOW 6) — אין ריצה כלל.")
    print(f"  ריצה קודמת (משוחזר מה-cron):  {prev}  ({_DOW_HE[_pg_dow(prev.date())]})" if prev else "  ריצה קודמת: —")
    print(f"  ריצה הבאה  (משוחזר מה-cron):  {nxt}   ({_DOW_HE[_pg_dow(nxt.date())]})" if nxt else "  ריצה הבאה: —")
    print(f"  כעת (UTC): {now:%Y-%m-%d %H:%M} ({_DOW_HE[_pg_dow(now.date())]})")

    # 1d. פקיעות שישי היסטוריות ב-condor_settled_detail — האם סטלמנט שישי נורמלי?
    with eng.connect() as conn:
        dow_rows = conn.execute(text("""
            SELECT EXTRACT(DOW FROM expiry_date::date)::int AS dow,
                   COUNT(DISTINCT expiry_date::date)        AS n
            FROM condor_settled_detail
            WHERE actual_index_close IS NOT NULL
            GROUP BY 1 ORDER BY 1
        """)).fetchall()
    print()
    print("התפלגות פקיעות מסולקות ב-condor_settled_detail לפי יום-בשבוע:")
    fri_n = 0
    for r in dow_rows:
        m = r._mapping
        tag = "  ← שישי" if m["dow"] == 5 else ""
        if m["dow"] == 5:
            fri_n = m["n"]
        print(f"    {_DOW_HE[m['dow']]:<6} (DOW {m['dow']}): {m['n']:>3} פקיעות{tag}")

    # אם קיים בטבלה עמוד timestamp — נחשב מתי סטלמנטים של שישי נכנסו היסטורית
    ts_col = _settlement_ts_column(eng)
    if ts_col and fri_n:
        _friday_settlement_lag(eng, ts_col)

    # 1e. אבחנה
    print()
    _hr("─")
    is_open = (trade is not None and trade["status"] == "open") or \
              any(o._mapping["status"] == "open" for o in others)
    if is_open and stl is not None:
        print("🩺 אבחנה: תקין-ומחכה. הסטלמנט קיים והעסקה פתוחה — אבל auto_close לא רץ בשישי/שבת")
        print("   (cron ראשון–חמישי). הריצה הבאה תסגור אותה. אין תקלה — יש פער-מבנה של פקיעת-שישי.")
        print(f"   ✅ אימות נדרש: ודא שהריצה הבאה ({nxt:%Y-%m-%d %H:%M} UTC) אכן סוגרת את #{FEAR_TRADE_ID}." if nxt else "")
    elif is_open and stl is None:
        print("🩺 אבחנה: תקין-ומחכה (סביר) — פקיעת שישי, הסטלמנט עדיין לא נכנס. ראה התפלגות ה-DOW למעלה:")
        print("   אם היסטורית יש מעט/אין פקיעות-שישי, סטלמנט שישי נכנס מאוחר (ראשון) — לא תקלה.")
        print(f"   ✅ אימות נדרש: ודא שהסטלמנט נכנס ושהריצה הבאה ({nxt:%Y-%m-%d} UTC) סוגרת." if nxt else "")
    elif not is_open:
        print("🩺 אבחנה: העסקה כבר סגורה — אין בעיה פתוחה. (ראה P&L למעלה.)")
    else:
        print("🩺 אבחנה: מצב לא-שגרתי — בדוק ידנית את הפלט למעלה.")
    _hr("─")


def _settlement_ts_column(eng):
    """מאתר עמודת timestamp ב-condor_settled_detail (created_at/inserted_at/...) אם קיימת."""
    with eng.connect() as conn:
        cols = conn.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'condor_settled_detail'
        """)).fetchall()
    candidates = ("created_at", "inserted_at", "recorded_at", "updated_at",
                  "fetched_at", "snapshot_date", "as_of_date", "fetch_date", "scraped_at")
    by_name = {c._mapping["column_name"]: c._mapping["data_type"] for c in cols}
    for name in candidates:
        if name in by_name:
            return name
    # כל עמודת timestamp אחרת
    for name, dt in by_name.items():
        if "timestamp" in dt or dt == "date":
            if name not in ("expiry_date",):
                return name
    return None


def _friday_settlement_lag(eng, ts_col: str):
    """לכל פקיעה מסולקת: פער בין תאריך-הפקיעה למועד-כניסת-הסטלמנט, בדגש על פקיעות שישי."""
    with eng.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT expiry_date::date AS exp,
                   EXTRACT(DOW FROM expiry_date::date)::int AS dow,
                   MIN({ts_col}) AS first_seen
            FROM condor_settled_detail
            WHERE actual_index_close IS NOT NULL
            GROUP BY expiry_date::date
            ORDER BY expiry_date::date DESC
            LIMIT 40
        """)).fetchall()
    print()
    print(f"מתי נכנס הסטלמנט (עמודת '{ts_col}') — פקיעות אחרונות, בדגש על שישי:")
    for r in rows:
        m = r._mapping
        fs = m["first_seen"]
        fs_d = fs.date() if hasattr(fs, "date") else None
        lag = (fs_d - m["exp"]).days if fs_d else None
        fs_dow = _DOW_HE[_pg_dow(fs_d)] if fs_d else "—"
        star = "  ← שישי" if m["dow"] == 5 else ""
        if m["dow"] == 5 or star:
            print(f"    פקיעה {m['exp']} ({_DOW_HE[m['dow']]}) → נכנס {fs_d} ({fs_dow}), "
                  f"פער {lag} ימים{star}")


# ─── חלק 2: סיכום השבוע — תיק ההמלצות ───────────────────────────────────────

def part2_week(eng):
    _title("② סיכום השבוע — תיק ההמלצות (פקיעות 14–17/7)")

    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, portfolio_id, expiry_date::date::text AS exp, status,
                   opened_at, closed_at, entry_index, close_index,
                   entry_cost, pnl, pnl_pct, max_profit, max_loss
            FROM paper_trades
            WHERE strategy_id = :sid AND expiry_date::date BETWEEN :a AND :b
            ORDER BY expiry_date::date, id
        """), {"sid": RECO_STRATEGY_ID, "a": WEEK_START, "b": WEEK_END}).fetchall()

    if not rows:
        print("אין עסקאות המלצה לשבוע זה.")
        return

    pid = rows[0]._mapping["portfolio_id"]
    with eng.connect() as conn:
        p = conn.execute(text("""
            SELECT name, initial_balance, current_balance, commission_per_leg
            FROM paper_portfolios WHERE id = :id
        """), {"id": pid}).fetchone()
    if p:
        pm = p._mapping
        print(f"תיק #{pid}: {pm['name']} | הון התחלתי {_fmt(pm['initial_balance'],0)} "
              f"| יתרה {_fmt(pm['current_balance'])} | עמלה/רגל {_fmt(pm['commission_per_leg'])}")
    print()
    print(f"{'פקיעה':<12}{'סטטוס':<9}{'פרמיה':>10}{'max_loss':>11}{'P&L':>11}{'תשואה%':>9}")
    _hr("─")

    realized = 0.0
    wins = 0
    closed_n = 0
    open_n = 0
    for r in rows:
        m = r._mapping
        premium = -m["entry_cost"] if m["entry_cost"] is not None else None  # זיכוי = -entry_cost
        pnl = m["pnl"]
        if m["status"] == "closed" and pnl is not None:
            realized += float(pnl)
            closed_n += 1
            if float(pnl) > 0:
                wins += 1
            pnl_txt = _fmt(pnl)
        else:
            open_n += 1
            pnl_txt = "פתוחה"
        print(f"{m['exp']:<12}{m['status']:<9}{_fmt(premium):>10}{_fmt(m['max_loss']):>11}"
              f"{pnl_txt:>11}{_fmt(m['pnl_pct']):>9}")

    _hr("─")
    win_rate = (wins / closed_n * 100) if closed_n else None
    print(f"סה\"כ עסקאות: {len(rows)}  |  סגורות: {closed_n}  |  פתוחות: {open_n}")
    print(f"ממומש שבועי (סגורות בלבד): {_fmt(realized)} ₪")
    print(f"Win Rate (סגורות): {wins}/{closed_n} = {_fmt(win_rate,1,'%')}")
    print()
    print(f"מול הסימולציה (ממוצע ארוך-טווח {SIM_WEEKLY_AVG:,.0f} ₪/שבוע):")
    diff = realized - SIM_WEEKLY_AVG
    ratio = (realized / SIM_WEEKLY_AVG * 100) if SIM_WEEKLY_AVG else None
    verdict = "מעל" if diff > 0 else "מתחת"
    print(f"  השבוע {_fmt(realized)} ₪  →  {verdict} לממוצע ב-{_fmt(abs(diff))} ₪ "
          f"({_fmt(ratio,0,'%')} מהממוצע).")
    if open_n:
        print(f"  שים לב: {open_n} עסקאות עדיין פתוחות (כולל 17/7) — הממומש יעודכן כשייסגרו.")
    return {"realized": realized, "closed_n": closed_n, "wins": wins, "open_n": open_n}


# ─── חלק 3: ולידציית מרווח שבועית ────────────────────────────────────────────

def part3_margin_validation(eng, settlements: dict):
    _title("③ ולידציית מרווח שבועית — המלצה מול מציאות (14–17/7)")

    recs = _latest_recs(eng, WEEK_START, WEEK_END)
    if not recs:
        print("אין המלצות מרווח לשבוע זה.")
        return

    print(f"{'פקיעה':<12}{'מרווח%':>8}{'implied%':>10}{'im/מרווח':>10}{'דגל':>5}"
          f"{'בפועל%':>9}{'תוצאה':>10}{'קלע?':>7}")
    _hr("─")

    hits = 0
    scored = 0
    for exp in sorted(recs):
        m = recs[exp]
        margin = m["margin_pct"]
        base = m["base_index"]
        close = settlements.get(exp)
        imp_pct = m["implied_expected_pct"]
        ivm = m["implied_vs_margin"]
        flag = (ivm is not None and ivm > 1.0)
        flag_txt = "🚩" if flag else "—"

        if close is not None and base:
            actual_pct = (close - base) / base * 100.0
            abs_move = abs(actual_pct)
            # החזיק/נשבר לפי הסטרייקים הקצרים (מבחן פריצה מדויק)
            sp, sc = m["short_put_strike"], m["short_call_strike"]
            if sp is not None and sc is not None:
                held = (float(sp) <= close <= float(sc))
            else:
                held = (margin is not None and abs_move < float(margin))
            outcome = "החזיק ✅" if held else "נשבר ❌"
            # "קלע?" — הדגל צדק אם: (דגל + נשבר) או (אין דגל + החזיק)
            broke = not held
            correct = (flag and broke) or (not flag and held)
            scored += 1
            if correct:
                hits += 1
            if flag and broke:
                hit_txt = "צדק 🎯"
            elif not flag and held:
                hit_txt = "צדק ✓"
            elif flag and held:
                hit_txt = "אזעק"   # false alarm
            else:
                hit_txt = "פספס"   # miss
            actual_txt = _fmt(actual_pct, 3)
        else:
            outcome = "טרם נסגר"
            hit_txt = "—"
            actual_txt = "—"

        print(f"{str(exp):<12}{_fmt(margin,2):>8}{_fmt(imp_pct,3):>10}{_fmt(ivm,2):>10}"
              f"{flag_txt:>5}{actual_txt:>9}{outcome:>10}{hit_txt:>7}")

    _hr("─")
    if scored:
        print(f"דגלי 🚩 שקלעו נכון: {hits}/{scored} פקיעות מסולקות.")
    else:
        print("אין עדיין פקיעות מסולקות לניקוד הדגלים השבוע.")
    n_impl = sum(1 for m in recs.values() if m["implied_present"])
    if n_impl < len(recs):
        print(f"הערה: implied_move נרשם ב-{n_impl}/{len(recs)} מההמלצות "
              "(הפיצ'ר 'מדד הפחד' חדש — פקיעות מוקדמות ייתכן בלי implied).")


# ─── חלק 4: מבט קדימה — עסקאות פתוחות ────────────────────────────────────────

def part4_lookahead(eng):
    _title("④ מבט קדימה — עסקאות המלצה פתוחות + ה-implied העדכני")

    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, expiry_date::date AS exp, opened_at, entry_index, entry_cost, max_loss
            FROM paper_trades
            WHERE strategy_id = :sid AND status = 'open'
            ORDER BY expiry_date::date, id
        """), {"sid": RECO_STRATEGY_ID}).fetchall()

    if not rows:
        print("אין עסקאות המלצה פתוחות.")
        return

    exps = [r._mapping["exp"] for r in rows]
    recs = _latest_recs(eng, min(exps), max(exps))

    print(f"{'עסקה':<7}{'פקיעה':<12}{'מרווח%':>8}{'implied%':>10}{'im/מרווח':>10}{'דגל':>5}{'נרשם':>13}")
    _hr("─")
    for r in rows:
        m = r._mapping
        exp = m["exp"]
        rec = recs.get(exp, {})
        ivm = rec.get("implied_vs_margin")
        flag = "🚩" if (ivm is not None and ivm > 1.0) else "—"
        ra = rec.get("recommended_at")
        ra_txt = ra.strftime("%m-%d %H:%M") if hasattr(ra, "strftime") else "—"
        print(f"#{m['id']:<6}{str(exp):<12}{_fmt(rec.get('margin_pct'),2):>8}"
              f"{_fmt(rec.get('implied_expected_pct'),3):>10}{_fmt(ivm,2):>10}{flag:>5}{ra_txt:>13}")
    _hr("─")
    flagged = [r._mapping["exp"] for r in rows
               if (recs.get(r._mapping["exp"], {}).get("implied_vs_margin") or 0) > 1.0]
    if flagged:
        print(f"🚩 פקיעות עם דגל פחד פעיל (השוק מתמחר תנועה > המרווח): "
              + ", ".join(str(e) for e in flagged))
    else:
        print("אין דגל פחד פעיל בעסקאות הפתוחות — השוק מתמחר תנועה בתוך המרווח.")


# ─── חלק 5: Benchmark — תיק ה-IC הקבוע (תיק 3) ───────────────────────────────

def part5_benchmark(eng, week_reco: dict | None):
    _title("⑤ Benchmark — תיק ה-IC הקבוע (תיק 3, 2.0/1.0) מול הדינמי")

    with eng.connect() as conn:
        p = conn.execute(text("""
            SELECT name, strategy_ids, commission_per_leg
            FROM paper_portfolios WHERE id = :id
        """), {"id": BENCH_PORTFOLIO_ID}).fetchone()
        rows = conn.execute(text("""
            SELECT id, strategy_id, strategy_name, expiry_date::date::text AS exp,
                   status, pnl, pnl_pct
            FROM paper_trades
            WHERE portfolio_id = :pid AND expiry_date::date BETWEEN :a AND :b
            ORDER BY expiry_date::date, id
        """), {"pid": BENCH_PORTFOLIO_ID, "a": WEEK_START, "b": WEEK_END}).fetchall()

    if p:
        pm = p._mapping
        print(f"תיק #{BENCH_PORTFOLIO_ID}: {pm['name']} | strategy_ids {pm['strategy_ids']}")
    if not rows:
        print("אין עסקאות benchmark לשבוע זה בתיק 3.")
        return

    print()
    print(f"{'פקיעה':<12}{'אסטרטגיה':<28}{'סטטוס':<9}{'P&L':>11}")
    _hr("─")
    bench_realized = 0.0
    bench_closed = 0
    for r in rows:
        m = r._mapping
        if m["status"] == "closed" and m["pnl"] is not None:
            bench_realized += float(m["pnl"])
            bench_closed += 1
            pnl_txt = _fmt(m["pnl"])
        else:
            pnl_txt = "פתוחה"
        name = (m["strategy_name"] or "")[:27]
        print(f"{m['exp']:<12}{name:<28}{m['status']:<9}{pnl_txt:>11}")

    _hr("─")
    print(f"Benchmark (תיק 3) ממומש שבועי: {_fmt(bench_realized)} ₪  ({bench_closed} סגורות)")
    if week_reco:
        reco_realized = week_reco["realized"]
        print(f"תיק ההמלצות (דינמי) ממומש שבועי: {_fmt(reco_realized)} ₪  ({week_reco['closed_n']} סגורות)")
        diff = reco_realized - bench_realized
        lead = "הדינמי לפני" if diff > 0 else "הקבוע לפני"
        print(f"⚖️  ההשוואה הראשונה 'דינמי מול קבוע': {lead} ב-{_fmt(abs(diff))} ₪ (השבוע).")
    print("הערה: פקיעות שעדיין פתוחות (כולל 17/7) לא נכללות בממומש — ההשוואה תתעדכן כשייסגרו.")


# ─── main ───────────────────────────────────────────────────────────────────

def _section(fn, *a):
    try:
        return fn(*a)
    except Exception as exc:  # noqa: BLE001
        print(f"\n⚠️  שגיאה בחלק {fn.__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return None


def main() -> int:
    eng = _engine()
    print("=" * 78)
    print("סיכום שבוע ההרצה הראשון — TA-35 | תיק המלצות מול קבוע | קריאה בלבד")
    print(f"נוצר: {datetime.now(tz=timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("=" * 78)

    settlements = _section(_settlement_map, eng) or {}

    _section(part1_investigate, eng, settlements)
    week_reco = _section(part2_week, eng)
    _section(part3_margin_validation, eng, settlements)
    _section(part4_lookahead, eng)
    _section(part5_benchmark, eng, week_reco)

    print()
    _hr("═")
    print("⚠️  כלי מחקר בלבד — לא המלצת מסחר, לא ביצוע עסקאות. דמו/paper בלבד.")
    print("    מדגם קטן (שבוע אחד, משטר-שוק אחד) — מבט ראשון, לא ולידציה סטטיסטית.")
    _hr("═")
    eng.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
