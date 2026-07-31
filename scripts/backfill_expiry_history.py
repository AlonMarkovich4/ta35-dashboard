#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/backfill_expiry_history.py — שחזור פקיעות ל-expiry_history לפי ההגדרה ההיסטורית.

**למה הסקריפט הזה קיים**

`history_updater` הזרים פקיעות עם `base_price ← condor_settled_detail.base_index_value`,
שהוא עוגן של **סדרה חודשית** — אותו ערך חוזר על עצמו עד 4 פקיעות שבועיות רצופות.
כתוצאה מכך `move_pct` בלע את דריפט החודש (ממוצע |תנועה| 1.68% מול 0.49% בקורפוס
ההיסטורי, ובקצה 5.04% ל"פקיעה שבועית"). 27 השורות האלה נמחקו ב-31/07/2026
(גיבוי: `expiry_history_backup_20260731`).

**ההגדרה ההיסטורית — אומתה מול הנתונים**

    base_price[D]   = סגירת המושב הקודם      (אומת: base_price[i] == close_price[i-1], 12/12)
    expiry_price[D] = מחיר הסילוק של יום D
    move_pct[D]     = (expiry_price − base_price) / base_price · 100

**מאיפה מגיע כל רכיב, ולמה מותר לסמוך עליו**

  base_price   ← `condor_settled_detail.actual_index_close`
                 למרות השם, הערך הזה הוא בפועל **סגירת המושב הקודם**, לא סגירת/פתיחת
                 יום הפקיעה. אומת מול Yahoo על 27 פקיעות: 27/27 התאמה מדויקת.
                 (הסיבה: `settle_expiry` ב-tase-pipeline רץ ~10:00 שעון ישראל וקורא
                 `meta.regularMarketOpen` מ-Yahoo לפני שהמושב החדש התעדכן.)

  expiry_price ← Yahoo `TA35.TA` — פתיחת יום הפקיעה.
                 אומת מול מחיר הסילוק הרשמי שב-CSV על 6 ימי חפיפה (30/04–07/05/2026):
                 **6/6 התאמה מדויקת עד האגורה**. כלומר זה אינו קירוב.

⚠️ הבאג המקורי חי ב-repo `tase-pipeline` (`strategy_engine._fetch_settlement_price`),
   ולא כאן. כל עוד הוא לא תוקן שם, `actual_index_close` ימשיך להיות סגירת המושב הקודם,
   ו-`iron_condor_strategies.actual_pnl_ils` מחושב ממנו — כלומר גם ה-P&L מוסט.

הרצה:
    python3 scripts/backfill_expiry_history.py              # dry-run (ברירת מחדל)
    python3 scripts/backfill_expiry_history.py --commit     # כתיבה בפועל
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd                                    # noqa: E402
from sqlalchemy import create_engine, text             # noqa: E402

from data_loader import save_to_db                     # noqa: E402  (אותו נתיב-כתיבה)
from history_updater import is_plausible_move          # noqa: E402

YAHOO_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
             "TA35.TA?interval=1d&range={rng}")
EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2

_SAVE_COLS = ["expiry_date", "expiry_time", "expiry_type", "base_price", "expiry_price",
              "open_pct", "close_price", "daily_pct", "volume", "transactions",
              "points", "abs_move_pct", "move_pct"]


def log(msg: str, level: str = "INFO") -> None:
    """שורת לוג עם חותמת זמן UTC."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}Z] {level:<5}| {msg}", flush=True)


def fetch_yahoo_bars(rng: str = "6mo") -> dict:
    """
    מוריד נרות יומיים של TA35.TA ומחזיר {date_iso: {'open': float|None, 'close': float|None}}.

    משתמש ב-gmtoffset מה-meta כדי למפות חותמות-זמן ליום מסחר בשעון הבורסה.
    זורק RuntimeError אם המבנה אינו כצפוי.
    """
    req = urllib.request.Request(YAHOO_URL.format(rng=rng),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:      # noqa: S310
        raw = json.loads(resp.read().decode("utf-8"))
    try:
        res = raw["chart"]["result"][0]
        off = res["meta"].get("gmtoffset", 0)
        quote = res["indicators"]["quote"][0]
        stamps = res["timestamp"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"מבנה תשובה בלתי-צפוי מ-Yahoo: {exc}") from exc

    bars: dict = {}
    for i, t in enumerate(stamps):
        d = datetime.fromtimestamp(t + off, tz=timezone.utc).date().isoformat()
        o, c = quote["open"][i], quote["close"][i]
        if o is None and c is None:
            continue
        bars[d] = {"open": o, "close": c}
    return bars


def _norm_date(v) -> str | None:
    """מנרמל ערך תאריך ל-'YYYY-MM-DD' (או None)."""
    if v is None:
        return None
    if isinstance(v, date):
        return v.isoformat()
    return str(v)[:10]


def _is_last_friday(d: date) -> bool:
    """האם התאריך הוא השישי האחרון בחודשו — הכלל של פקיעה חודשית.

    זהה ללוגיקה ב-supabase_loader._infer_expiry_type (מקור אמת אחד לכלל).
    """
    last_dt = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    last_friday = last_dt - timedelta(days=(last_dt.weekday() - 4) % 7)
    return d == last_friday


def build_backfill_plan(engine, bars: dict) -> tuple[list[dict], list[dict]]:
    """
    בונה את תוכנית השחזור: לכל פקיעה מסולקת שאינה כבר ב-expiry_history —
    base מ-actual_index_close, expiry_price מפתיחת Yahoo, move_pct מחושב מהם.

    מחזיר (to_insert, skipped) כאשר skipped כולל סיבה מפורשת לכל דילוג.
    """
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        settled = conn.execute(text("""
            SELECT DISTINCT expiry_date, actual_index_close
            FROM condor_settled_detail
            WHERE actual_index_close IS NOT NULL
            ORDER BY expiry_date
        """)).fetchall()
        existing = {_norm_date(r[0]) for r in
                    conn.execute(text("SELECT expiry_date FROM expiry_history")).fetchall()}

    to_insert: list[dict] = []
    skipped: list[dict] = []

    for exp_raw, prev_close in settled:
        d = _norm_date(exp_raw)
        if d in existing:
            continue                                   # אידמפוטנטי
        bar = bars.get(d)
        if not bar or bar.get("open") is None:
            skipped.append({"expiry_date": d, "reason": "אין נר Yahoo ליום הפקיעה"})
            continue
        base = float(prev_close)
        settle = float(bar["open"])
        if base <= 0:
            skipped.append({"expiry_date": d, "reason": f"base לא תקין ({base})"})
            continue
        move = (settle - base) / base * 100.0
        if not is_plausible_move(move):
            skipped.append({"expiry_date": d, "reason": f"תנועה לא סבירה ({move:.2f}%)"})
            continue
        dt = datetime.strptime(d, "%Y-%m-%d").date()
        to_insert.append({
            "expiry_date":  d,
            "expiry_type":  "M" if _is_last_friday(dt) else "W",
            "base_price":   round(base, 4),
            "expiry_price": round(settle, 4),
            "move_pct":     move,
            "abs_move_pct": abs(move),
        })
    return to_insert, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description="שחזור expiry_history לפי ההגדרה ההיסטורית")
    ap.add_argument("--commit", action="store_true",
                    help="כתיבה בפועל (ברירת מחדל: dry-run בלבד)")
    ap.add_argument("--range", default="6mo", help="טווח הנרות מ-Yahoo (ברירת מחדל 6mo)")
    args = ap.parse_args()

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        log("DATABASE_URL לא מוגדר.", level="ERROR")
        return EXIT_CONFIG
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    try:
        bars = fetch_yahoo_bars(args.range)
        log(f"Yahoo: {len(bars)} נרות יומיים.")
    except Exception as exc:  # noqa: BLE001
        log(f"הורדת נרות מ-Yahoo נכשלה: {exc}", level="ERROR")
        return EXIT_ERROR

    engine = create_engine(db_url, pool_pre_ping=True, connect_args={"connect_timeout": 30})
    try:
        to_insert, skipped = build_backfill_plan(engine, bars)
    except Exception as exc:  # noqa: BLE001
        log(f"בניית התוכנית נכשלה: {exc}", level="ERROR")
        return EXIT_ERROR

    log(f"לשחזור: {len(to_insert)} · דולגו: {len(skipped)}")
    for r in to_insert:
        log(f"  {r['expiry_date']} ({r['expiry_type']}): base={r['base_price']} "
            f"settle={r['expiry_price']} move={r['move_pct']:+.3f}%")
    for s in skipped:
        log(f"  דילוג {s['expiry_date']}: {s['reason']}", level="WARN")

    if not to_insert:
        log("אין מה לשחזר.")
        return EXIT_OK

    moves = [abs(r["move_pct"]) for r in to_insert]
    log(f"בקרת שפיות: ממוצע |תנועה| = {sum(moves) / len(moves):.3f}% "
        f"(הקורפוס ההיסטורי: 0.493%), max = {max(moves):.3f}%")

    if not args.commit:
        log("DRY-RUN — לא נכתב דבר. הוסף --commit לכתיבה.")
        return EXIT_OK

    df = pd.DataFrame([{c: None for c in _SAVE_COLS} for _ in to_insert])
    for i, row in enumerate(to_insert):
        for k, v in row.items():
            df.at[i, k] = v
    df["expiry_date"] = pd.to_datetime(df["expiry_date"])
    inserted = save_to_db(df, engine, if_exists="append")
    log(f"✅ נכתבו {inserted} שורות ל-expiry_history.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
