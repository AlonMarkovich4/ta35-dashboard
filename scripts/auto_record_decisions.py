#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_record_decisions.py — תיעוד אוטומטי של החלטות המנוע (shadow mode, Layer 1).

מיועד להרצה מתוזמנת (GitHub Action / cron). הופך את הכפתור הידני בדף 6 לאוטומטי:
קורא ל-record_decisions_for_upcoming שמריץ את מנוע ההחלטה על כל פקיעה קרובה
(>= היום) ושומר את התוצאה ב-decision_log (append-only).

idempotent: record_decisions_for_upcoming מדלג על פקיעה שכבר תועדה היום
(decision_logged_today) — ריצה חוזרת באותו יום לא תיצור כפילות. לכן בטוח להריץ
את ה-Action יומית גם אם פקיעות נכנסות ל-chain בהדרגה.

exit codes (כמו auto_close_expiries.py):
  0  הצלחה — כולל "אין מה לתעד" ו"הכל כבר תועד היום" (מצבים רגילים).
  1  שגיאה אמיתית — חיבור DB נכשל, או תיעוד של פקיעה כלשהי נכשל.
  2  קונפיגורציה חסרה — DATABASE_URL לא מוגדר בסביבה.

הטריגר הוא הזמן (cron), בניגוד ל-auto_close שהטריגר שלו הוא קיום הסטלמנט ב-DB.
מניעת הכפילויות (decision_logged_today) היא מה שהופך את ההרצה היומית לבטוחה.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# הוספת src ל-path (כמו auto_close_expiries.py)
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2


def log(msg: str, level: str = "INFO") -> None:
    """מדפיס שורת לוג עם חותמת זמן UTC ורמה — קריא ב-CI."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def main() -> int:
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        log("DATABASE_URL לא מוגדר בסביבה — לא ניתן לרוץ. יציאה.", level="ERROR")
        return EXIT_CONFIG

    # ייבוא אחרי בדיקת ה-env, כדי שכשל env ייתן הודעה ברורה לפני כל טעינה כבדה.
    try:
        from sqlalchemy import text
        from paper_db import _make_engine
        from decision_recorder import record_decisions_for_upcoming
    except Exception as exc:  # noqa: BLE001
        log(f"ייבוא מודולים נכשל: {exc}", level="ERROR")
        return EXIT_ERROR

    engine = _make_engine(None)
    if engine is None:
        log("לא ניתן לבנות engine מ-DATABASE_URL.", level="ERROR")
        return EXIT_ERROR

    # אימות חיבור: SELECT 1 — כך ששגיאת DB תיתן exit 1 ולא תיראה כמו "אין מה לתעד".
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        log(f"בדיקת חיבור DB (SELECT 1) נכשלה: {exc}", level="ERROR")
        return EXIT_ERROR

    log("מריץ record_decisions_for_upcoming (trigger=scheduled, engine_version=layer1-v1)...")
    try:
        results = record_decisions_for_upcoming(
            engine=engine, trigger="scheduled", engine_version="layer1-v1",
        )
    except Exception as exc:  # noqa: BLE001
        log(f"תיעוד ההחלטות נכשל: {exc}", level="ERROR")
        return EXIT_ERROR

    if not results:
        log("אין פקיעות קרובות לתיעוד — אין מה לעשות (מצב רגיל).")
        return EXIT_OK

    recorded = skipped = errored = 0
    for r in results:
        status = r.get("status")
        if status == "recorded":
            recorded += 1
        elif status == "skipped_exists":
            skipped += 1
        else:
            errored += 1
        log(
            f"פקיעה {r.get('expiry_date')} (סוג {r.get('expiry_type')}): "
            f"top_strategy={r.get('top_strategy_id')} "
            f"regime={r.get('regime')} → {status}"
        )

    log(f"סיכום: נרשמו {recorded} · דולגו {skipped} · שגיאות {errored}.")

    if errored:
        log("היו שגיאות תיעוד — יציאה עם קוד שגיאה.", level="ERROR")
        return EXIT_ERROR
    if recorded == 0 and skipped > 0:
        log("כל הפקיעות הקרובות כבר תועדו היום (idempotent) — מצב רגיל.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
