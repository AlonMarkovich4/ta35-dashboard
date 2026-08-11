#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/archive_intraday_chain.py — שמירת צילום השרשרת הנוכחי.

**למה**

`tase_putcall` מתעדכנת כל ~15 דקות; `tase_putcall_history` שומרת ממנה צילום
אחד ביום ב-~17:15. ההתפתחות התוך-יומית נזרקת — ואיתה התשובה לשאלה "כמה
מהמחזור היומי כבר עבר בשעה שאני נכנס". ראה `src/intraday_archive.py`.

**הסקריפט הזה אינו מייצר מסקנות ואינו סוחר.** הוא רק שומר. הניתוח יבוא
אחרי שיצטברו נתונים — ובכוונה לא לפני, כי עקומת מחזור על יומיים היא רעש.

**בטיחות**
  • `tase_putcall` — SELECT בלבד (בבעלות המתכנת השני).
  • אידמפוטנטי: המפתח הוא הצילום של **המקור**. Action שנדחה או רץ פעמיים
    אינו מייצר כפילות.
  • `--create-table` יוצר את הטבלה (IF NOT EXISTS) — ריצה חד-פעמית.

קודי יציאה: 0 = הצלחה או דילוג לגיטימי · 1 = שגיאה.

    python scripts/archive_intraday_chain.py                 # dry-run
    python scripts/archive_intraday_chain.py --create-table  # יצירת הטבלה
    python scripts/archive_intraday_chain.py --commit        # שמירה
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

EXIT_OK, EXIT_ERR = 0, 1


def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def _trading_day_guard() -> int | None:
    """אין מסחר ⇒ אין צילום חדש ⇒ אין מה לארכב. FORCE_RUN=true עוקף.

    ⚠️ `FORCE_RUN` הוא להרצת אופרטור, **לא לבדיקות** — הוא כותב ל-DB האמיתי.
    """
    from trading_calendar import holidays_are_current, is_trading_day, skip_reason

    today = datetime.now(timezone.utc).date()
    force = os.getenv("FORCE_RUN", "").strip().lower() == "true"
    if not holidays_are_current(today):
        log("רשימת החגים מתיישנת — יש לעדכן את trading_calendar.", level="WARN")
    reason = skip_reason(today, force=force)
    if reason:
        log(f"{reason} — אין ריצה. (FORCE_RUN=true לעקיפה.)")
        return EXIT_OK
    if force and not is_trading_day(today):
        log(f"FORCE_RUN=true — רץ למרות ש-{today} אינו יום מסחר.", level="WARN")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="שמירה בפועל")
    ap.add_argument("--create-table", action="store_true",
                    help="יוצר את טבלת הארכוב (IF NOT EXISTS) ויוצא")
    args = ap.parse_args()

    from intraday_archive import (
        INTRADAY_TABLE,
        archive_current_snapshot,
        create_table_sql,
        table_exists,
    )

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        log("אין DATABASE_URL.", level="ERROR")
        return EXIT_ERR
    engine = create_engine(db_url, pool_pre_ping=True,
                           connect_args={"connect_timeout": 30})

    if args.create_table:
        if table_exists(engine):
            log(f"טבלת {INTRADAY_TABLE} כבר קיימת — לא נוצרה שוב.")
            return EXIT_OK
        try:
            with engine.begin() as conn:
                conn.execute(text(create_table_sql()))
        except Exception as exc:  # noqa: BLE001
            log(f"יצירת הטבלה נכשלה: {exc}", level="ERROR")
            return EXIT_ERR
        log(f"✅ נוצרה טבלת {INTRADAY_TABLE}.")
        return EXIT_OK

    # השער נבדק רק בריצה רגילה — יצירת טבלה מותרת בכל יום.
    if (rc := _trading_day_guard()) is not None:
        return rc

    res = archive_current_snapshot(engine, dry_run=not args.commit)
    snap = res.get("snapshot") or {}
    label = (f"{snap.get('fetch_date')} {snap.get('fetch_time')} "
             f"(trade_date {snap.get('trade_date')})") if snap else "—"

    if res["status"] == "archived":
        log(f"✅ {label} — נשמרו {res['inserted']} שורות "
            f"(מקור: {res['source_rows']}).")
    elif res["status"] == "duplicate":
        log(f"↩︎  {label} — {res['reason']}")
    elif res["status"] == "dry-run":
        log(f"⚠️  DRY-RUN · {label} — {res['reason']}. להרצה: --commit")
    elif res["status"] == "error":
        log(f"שגיאה: {res['reason']}", level="ERROR")
        return EXIT_ERR
    else:
        # דילוג — תמיד עם סיבה מפורשת. דילוג שקט הוא הבאג החוזר בפרויקט הזה.
        log(f"דילוג: {res['reason']}", level="WARN")

    try:
        engine.dispose()
    except Exception:  # noqa: BLE001
        pass
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
