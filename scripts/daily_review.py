#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_review.py — "סיכום יום" מקיף למערכת TA-35 (קריאה בלבד, SELECT בלבד).

מריץ שישה חתכים מול ה-DB החי ומדפיס דוח מסודר:
  1. תיק ההמלצות (id=8): עסקאות, שינויי 24 שעות, סה"כ ממומש.
  2. המלצות היום (margin_recommendations): כולל אימות שהשדה implied_move נשמר + דגלי אזהרה.
  3. ולידציית מרווח: המלצה מול תנועה בפועל (החזיק/נשבר, פער מהאופטימום).
  4. ולידציית אסטרטגיות: hit/regret עדכני.
  5. סטטוס אוטומציה: הרשומה האחרונה מכל סוג (scheduled) — לוודא שהכל רץ היום.
  6. דגלים ואנומליות.

אפס כתיבה: משתמש רק ב-SELECT (ישירות) ובפונקציות הולידציה הטהורות (read-only).
לא נוגע ב-kill-switch, לא פותח/סוגר עסקאות, לא מריץ recorder.

הרצה:  DATABASE_URL='<postgres-url>' python3 scripts/daily_review.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

RECO_PORTFOLIO_ID = 8
# יתומות מוכרות — מדווחות אך אינן נספרות כדגל. **חייבות סיבה ותאריך.**
#
# 2026-06-19 הוסרה מכאן ב-31/07/2026. הסיבה שנרשמה לה ("ללא סטלמנט") הייתה
# **שגויה**: הסטלמנט היה קיים (actual_index_close=4182.02), אבל כל שורותיו
# סומנו is_valid=false ולכן נפלו מה-VIEW condor_settled_detail. שש העסקאות
# נסגרו ידנית לפי מחיר הסילוק האמיתי (4173.07 = פתיחת 19/06).
# הלקח: רשומה כאן משתיקה התראה — אז היא חייבת להיות נכונה, לא נוחה.
KNOWN_UNSETTLED = {
    "2026-07-23": "תשעה באב — הבורסה לא נפתחה, אין ולא יהיה סילוק. "
                  "ממתין לבירור מול TASE (נרשם 31/07/2026).",
}

# ── הוספת src ל-path — נגזר ממיקום הקובץ (scripts/ → ../src), עם fallback לנתיבים ידועים ──
_CANDIDATES = [
    str(Path(__file__).resolve().parent.parent / "src"),
    os.path.expanduser("~/Projects/ta35-dashboard/ta35-dashboard/src"),
    os.path.expanduser("~/Desktop/ta35-dashboard/ta35-dashboard/src"),
]
for _p in _CANDIDATES:
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from sqlalchemy import text
    from paper_db import _make_engine, get_portfolio
except Exception as exc:  # noqa: BLE001
    print(f"❌ ייבוא מודולים נכשל (בדוק שהנתיב ל-src נכון ושהתלויות מותקנות): {exc}")
    sys.exit(2)


# ─── formatting helpers ──────────────────────────────────────────────────

def _f(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def money(v):
    f = _f(v)
    return "—" if f is None else f"{f:,.2f} ₪"


def pct(v, mult=1.0, dec=2):
    f = _f(v)
    return "—" if f is None else f"{f * mult:.{dec}f}%"


def num(v, dec=2):
    f = _f(v)
    return "—" if f is None else f"{f:.{dec}f}"


def ts(v):
    return "—" if v is None else str(v)[:19]


def as_dict(v):
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


def fetch(engine, sql, **params):
    """SELECT קצר → list[Row]. פתיחת חיבור לכל שאילתה (קריאה בלבד)."""
    with engine.connect() as conn:
        return conn.execute(text(sql), params).fetchall()


def hr(char="─", n=78):
    print(char * n)


def section(num_, title):
    print()
    hr("━")
    print(f"  {num_}. {title}")
    hr("━")


# מצב גלובלי — התאריך של ה-DB (שעון השרת, כמו שהאוטומציה מגדירה "היום").
_TODAY = None  # str 'YYYY-MM-DD'


def _today_flag(t):
    """מוסיף חיווי אם חותמת הזמן היא מהיום (שעון ה-DB), אחרת אזהרה."""
    if t is None:
        return " ⚠️ אין רשומה"
    return " ✅ היום" if str(t)[:10] == _TODAY else f" ⚠️ לא היום ({str(t)[:10]})"


# ─── 1. תיק ההמלצות ──────────────────────────────────────────────────────

def section1(engine):
    pf = get_portfolio(RECO_PORTFOLIO_ID, engine=engine)
    if pf:
        print(f"  תיק #{RECO_PORTFOLIO_ID}: {pf.get('name')}")
        print(f"    הון התחלתי {money(pf.get('initial_balance'))} · "
              f"יתרה נוכחית {money(pf.get('current_balance'))} · "
              f"עמלה/רגל {num(pf.get('commission_per_leg'))}")
    else:
        print(f"  ⚠️ תיק #{RECO_PORTFOLIO_ID} לא נמצא ב-paper_portfolios.")

    rows = fetch(engine, """
        SELECT id, expiry_date, status, opened_at, closed_at,
               entry_cost, pnl, pnl_pct, max_profit, max_loss, close_index,
               (opened_at >= NOW() - INTERVAL '24 hours') AS opened_recent,
               (closed_at IS NOT NULL AND closed_at >= NOW() - INTERVAL '24 hours') AS closed_recent
        FROM paper_trades
        WHERE portfolio_id = :pid
        ORDER BY expiry_date, opened_at
    """, pid=RECO_PORTFOLIO_ID)

    if not rows:
        print("  אין עסקאות בתיק עדיין (kill-switch כבוי, או טרם נפתחו).")
        return

    opens = [r._mapping for r in rows if r._mapping["status"] == "open"]
    closed = [r._mapping for r in rows if r._mapping["status"] == "closed"]
    new24 = [r._mapping for r in rows if r._mapping["opened_recent"]]
    cls24 = [r._mapping for r in rows if r._mapping["closed_recent"]]

    print(f"  סה\"כ עסקאות: {len(rows)} · פתוחות: {len(opens)} · סגורות: {len(closed)}")

    print("  — שינויי 24 השעות האחרונות —")
    if not new24 and not cls24:
        print("    אין שינוי (לא נפתחו ולא נסגרו עסקאות).")
    for m in new24:
        print(f"    🟢 נפתחה #{m['id']} · פקיעה {m['expiry_date']} · "
              f"פרמיה {money(m['max_profit'])} · max_loss {money(m['max_loss'])} · "
              f"{ts(m['opened_at'])}")
    for m in cls24:
        print(f"    🔴 נסגרה #{m['id']} · פקיעה {m['expiry_date']} · "
              f"P&L {money(m['pnl'])} · מדד נעילה {num(m['close_index'])} · "
              f"{ts(m['closed_at'])}")

    print("  — כל העסקאות —")
    for r in rows:
        m = r._mapping
        pnl = money(m["pnl"]) if m["status"] == "closed" else "(פתוחה)"
        print(f"    #{m['id']:>4} · פקיעה {m['expiry_date']} · {m['status']:<6} · "
              f"נפתחה {str(m['opened_at'])[:10]} · P&L {pnl}")

    realized = sum((_f(m["pnl"]) or 0.0) for m in closed)
    print(f"  💰 סה\"כ ממומש עד היום (סגורות): {money(realized)}"
          + (f"  ·  {len(opens)} פתוחות ממתינות לפקיעה" if opens else ""))


# ─── 2. המלצות היום ──────────────────────────────────────────────────────

def section2(engine):
    rows = fetch(engine, """
        SELECT id, expiry_date, engine_version, margin_pct, hold_blended, premium_ils,
               below_floor, recommended_at, recommendation_json
        FROM margin_recommendations
        WHERE recommended_at::date = CURRENT_DATE
        ORDER BY expiry_date, id
    """)
    if not rows:
        print("  לא נרשמו המלצות מרווח היום.")
        print("  (ריצת ה-Action טרם רצה היום / אין שרשרת מלאה / הכל דולג כ-skipped_exists).")
        return

    print(f"  נרשמו היום {len(rows)} המלצות:")
    for r in rows:
        m = r._mapping
        rj = as_dict(m["recommendation_json"])
        im = rj.get("implied_move")
        print(f"  • פקיעה {m['expiry_date']}  (v{m['engine_version']}, המלצה #{m['id']})")
        print(f"      מרווח {pct(m['margin_pct'])} · hold {pct(m['hold_blended'], 100, 1)} · "
              f"פרמיה {money(m['premium_ils'])}"
              + ("  ⚠️ below_floor" if m["below_floor"] else ""))
        # ההוכחה שהפיצ'ר מאתמול חי — implied_move נשמר בתוך recommendation_json.
        if im is None:
            print("      implied_move: ❌ לא נשמר (המלצה ישנה מלפני הפיצ'ר / באג — דגל!)")
        elif im.get("skipped"):
            print(f"      implied_move: ⚪ נשמר אך לא חושב · סיבה: {im.get('reason')}")
        else:
            ivm = _f(im.get("implied_vs_margin"))
            warn = "  🚩 השוק מתמחר תנועה גדולה מהמרווח!" if (ivm is not None and ivm > 1) else ""
            print(f"      implied_move: ✅ נשמר · השוק צופה {pct(im.get('expected_move_pct'))} "
                  f"(יומי {pct(im.get('implied_daily_pct'))}) · "
                  f"implied/margin = {num(ivm)}{warn}")


# ─── 3. ולידציית מרווח ───────────────────────────────────────────────────

def section3(engine):
    from margin_validator import build_margin_validation_rows, summarize_margin_validation
    rows = build_margin_validation_rows(engine=engine)
    s = summarize_margin_validation(rows)
    print(f"  פקיעות שנוולדו: {s['n_validated']} · "
          f"hold_rate בפועל: {pct(s['hold_rate'], 100, 1)} ({s['n_held']}/{s['n_validated']}) · "
          f"פער ממוצע מהאופטימום: {num(s['avg_margin_gap'], 3)}% · "
          f"P&L~ מצטבר: {money(s['est_pnl_total'])}")
    if not rows:
        print("  אין פקיעות ולידביליות עדיין (צריך גם המלצה וגם סטלמנט).")
        return
    print("  — שורה לפקיעה (האחרונה ראשונה) —")
    for r in rows:
        held = "✅ החזיק" if r["held"] else "❌ נשבר"
        gap = num(r["margin_gap"], 3) if r["margin_gap"] is not None else "—"
        print(f"    {r['expiry_date']} · המלצה {num(r['recommended_margin'])}% · "
              f"תנועה {num(r['actual_abs_move_pct'])}% · {held} · "
              f"פער {gap} · P&L~ {money(r['est_pnl'])} · [{r['move_source']}]")


# ─── 4. ולידציית אסטרטגיות ──────────────────────────────────────────────

def section4(engine):
    from decision_validator import build_validation_rows, summarize_validation
    rows = build_validation_rows(engine=engine)
    s = summarize_validation(rows)
    print(f"  פקיעות שנוולדו: {s['n_validated']} · "
          f"hit_rate: {pct(s['hit_rate'], 100, 1)} · "
          f"regret מצטבר: {money(s['total_regret'])}")
    print(f"    'לפי המנוע' {money(s['recommended_pnl'])} · "
          f"'מושלם' {money(s['best_pnl'])} · "
          f"'אקראי' {money(s['avg_pnl'])}")
    if not rows:
        print("  אין פקיעות ולידביליות עדיין (צריך החלטה מתועדת + עסקאות סגורות של האסטרטגיות 1–6).")
        return
    print("  — שורה לפקיעה (האחרונה ראשונה) —")
    for r in rows:
        hit = "🎯 פגע" if r["hit"] else "✗ החטיא"
        print(f"    {r['expiry_date']} · המליץ {r['top_strategy_name']} "
              f"(P&L {money(r['recommended_pnl'])}) · "
              f"הכי טוב {r['best_strategy_name']} ({money(r['best_pnl'])}) · "
              f"{hit} · regret {money(r['regret'])}")


# ─── 5. סטטוס אוטומציה ───────────────────────────────────────────────────

def section5(engine):
    d_last = fetch(engine,
                   "SELECT MAX(decided_at) AS t FROM decision_log WHERE trigger='scheduled'"
                   )[0]._mapping["t"]
    d_today = fetch(engine,
                    "SELECT COUNT(*) AS c FROM decision_log "
                    "WHERE trigger='scheduled' AND decided_at::date = CURRENT_DATE"
                    )[0]._mapping["c"]

    m_last = fetch(engine,
                   "SELECT MAX(recommended_at) AS t FROM margin_recommendations "
                   "WHERE recommendation_json->>'trigger' = 'scheduled'"
                   )[0]._mapping["t"]
    m_today = fetch(engine,
                    "SELECT COUNT(*) AS c FROM margin_recommendations "
                    "WHERE recommendation_json->>'trigger'='scheduled' "
                    "AND recommended_at::date = CURRENT_DATE"
                    )[0]._mapping["c"]

    o_last = fetch(engine,
                   "SELECT MAX(opened_at) AS t FROM paper_trades WHERE portfolio_id=:pid",
                   pid=RECO_PORTFOLIO_ID)[0]._mapping["t"]
    c_rows = fetch(engine,
                   "SELECT closed_at, expiry_date, pnl FROM paper_trades "
                   "WHERE portfolio_id=:pid AND status='closed' "
                   "ORDER BY closed_at DESC NULLS LAST LIMIT 1",
                   pid=RECO_PORTFOLIO_ID)

    print(f"  decision_log (scheduled):            אחרון {ts(d_last)}{_today_flag(d_last)} · נרשמו היום {d_today}")
    print(f"  margin_recommendations (scheduled):  אחרון {ts(m_last)}{_today_flag(m_last)} · נרשמו היום {m_today}")
    print(f"  עסקה אחרונה שנפתחה (תיק {RECO_PORTFOLIO_ID}):        {ts(o_last)}{_today_flag(o_last)}")
    if c_rows and c_rows[0]._mapping["closed_at"] is not None:
        cm = c_rows[0]._mapping
        print(f"  עסקה אחרונה שנסגרה (תיק {RECO_PORTFOLIO_ID}):        {ts(cm['closed_at'])} · "
              f"פקיעה {cm['expiry_date']} · P&L {money(cm['pnl'])}")
    else:
        print(f"  עסקה אחרונה שנסגרה (תיק {RECO_PORTFOLIO_ID}):        — (אין עדיין עסקאות סגורות)")


# ─── 6. דגלים ואנומליות ─────────────────────────────────────────────────

def section6(engine):
    flags = 0

    # א. עסקאות open שעברו פקיעה — עם/בלי סטלמנט.
    past = fetch(engine, """
        SELECT pt.id, pt.portfolio_id, pt.expiry_date, pt.opened_at,
               (SELECT MAX(c.actual_index_close) FROM condor_settled_detail c
                 WHERE c.expiry_date::date = pt.expiry_date::date) AS settlement
        FROM paper_trades pt
        WHERE pt.status = 'open' AND pt.expiry_date::date < CURRENT_DATE
        ORDER BY pt.expiry_date, pt.portfolio_id
    """)
    for r in past:
        m = r._mapping
        exp = str(m["expiry_date"])
        if m["settlement"] is not None:
            flags += 1
            print(f"  🔴 עסקה פתוחה #{m['id']} (תיק {m['portfolio_id']}) פקיעה {exp} — "
                  f"קיים סטלמנט ({num(m['settlement'])}) אך לא נסגרה! (מנגנון הסגירה החמיץ)")
        elif exp in KNOWN_UNSETTLED:
            print(f"  ⚪ עסקה פתוחה #{m['id']} (תיק {m['portfolio_id']}) פקיעה {exp} — "
                  f"{KNOWN_UNSETTLED[exp]}")
        else:
            flags += 1
            print(f"  🟠 עסקה פתוחה #{m['id']} (תיק {m['portfolio_id']}) פקיעה {exp} — "
                  f"עברה בלי סטלמנט ולא ברשימת הידועים (דגל)")

    # ב+ג. המלצות היום — חסרות implied_move / דגל implied>margin.
    today_recs = fetch(engine, """
        SELECT id, expiry_date, margin_pct, recommendation_json
        FROM margin_recommendations
        WHERE recommended_at::date = CURRENT_DATE
    """)
    for r in today_recs:
        m = r._mapping
        im = as_dict(m["recommendation_json"]).get("implied_move")
        if im is None:
            flags += 1
            print(f"  🚩 המלצה #{m['id']} (פקיעה {m['expiry_date']}) מהיום — ללא implied_move")
            continue
        ivm = _f(im.get("implied_vs_margin"))
        if ivm is not None and ivm > 1:
            flags += 1
            print(f"  🚩 המלצה #{m['id']} (פקיעה {m['expiry_date']}): implied/margin={num(ivm)} > 1 — "
                  f"השוק מתמחר תנועה גדולה מהמרווח שנבחר")

    if flags == 0:
        print("  ✅ אין אנומליות קריטיות (הדגל היחיד המותר: פקיעת 19/06 הידועה ללא סטלמנט).")
    else:
        print(f"  ── סה\"כ {flags} דגלים דורשי-תשומת-לב ──")


# ─── main ────────────────────────────────────────────────────────────────

def _run(name, fn, engine):
    try:
        fn(engine)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ שגיאה בסעיף '{name}': {exc}")
        traceback.print_exc(file=sys.stderr)


def main() -> int:
    global _TODAY
    if not os.environ.get("DATABASE_URL", "").strip():
        print("❌ DATABASE_URL לא מוגדר בסביבה. הרץ:")
        print("   DATABASE_URL='<postgres-url>' python3 scripts/daily_review.py")
        return 2

    engine = _make_engine(None)
    if engine is None:
        print("❌ לא ניתן לבנות engine מ-DATABASE_URL.")
        return 2

    try:
        meta = fetch(engine, "SELECT CURRENT_DATE AS d, NOW() AS n")[0]._mapping
        _TODAY = str(meta["d"])[:10]
        db_now = ts(meta["n"])
    except Exception as exc:  # noqa: BLE001
        print(f"❌ בדיקת חיבור DB נכשלה: {exc}")
        return 1

    hr("═")
    print(f"  📊  סיכום יום — TA-35 Expiry Intelligence")
    print(f"      תאריך DB (שעון שרת): {_TODAY}  ·  שעה: {db_now}  ·  קריאה בלבד (SELECT)")
    hr("═")

    section(1, "תיק ההמלצות (id=8) — עסקאות ושינויי 24 שעות")
    _run("1", section1, engine)

    section(2, "המלצות היום — implied_move + דגלי אזהרה")
    _run("2", section2, engine)

    section(3, "ולידציית מרווח — המלצה מול המציאות")
    _run("3", section3, engine)

    section(4, "ולידציית אסטרטגיות — hit / regret")
    _run("4", section4, engine)

    section(5, "סטטוס אוטומציה — האם הכל רץ היום")
    _run("5", section5, engine)

    section(6, "דגלים ואנומליות")
    _run("6", section6, engine)

    print()
    hr("═")
    print("  ✔ הדוח הושלם.")
    hr("═")
    return 0


if __name__ == "__main__":
    sys.exit(main())
