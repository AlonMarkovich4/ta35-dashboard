#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_record_margins.py — תיעוד אוטומטי של המלצות המרווח (מנגנון המרווח, שלב 5א).

מיועד להרצה מתוזמנת (GitHub Action / cron). התאום של auto_record_decisions.py, למנגנון
המרווח: קורא ל-record_margin_recommendations_for_upcoming שמריץ את המנוע (שלב 1–3,
floor=0.97) על כל פקיעה קרובה (>= היום) עם שרשרת, ושומר ב-margin_recommendations
(append-only).

idempotent: record_margin_recommendations_for_upcoming מדלג על פקיעה שכבר תועדה היום
לאותה גרסה (margin_recommendation_logged_today) — ריצה חוזרת באותו יום לא תיצור כפילות.
לכן בטוח להריץ יומית גם כשפקיעות נכנסות ל-chain בהדרגה, ולכן ה-Action תופס גם פקיעות
שנכנסות מאוחר.

גשר 3 (אופציונלי, מאחורי kill-switch): אחרי הרישום, אם RECO_TRADING_ENABLED=='true', פותח
עסקת Iron Condor דמו בתיק ההמלצות לכל פקיעה שיש לה המלצה היום (_open_reco_trades →
recommendation_trader.open_recommended_condor, עם דדופ). **ברירת מחדל כבוי** — אפס פתיחה.

exit codes (כמו auto_record_decisions.py):
  0  הצלחה — כולל "אין מה לתעד", "הכל כבר תועד היום", ו"אין שרשרת מלאה" (מצבים רגילים).
  1  שגיאה אמיתית — חיבור DB נכשל, תיעוד נכשל (status='error'), או שגיאת פתיחת עסקה.
  2  קונפיגורציה חסרה — DATABASE_URL לא מוגדר בסביבה.

הטריגר הוא הזמן (cron); מניעת הכפילויות היא מה שהופך את ההרצה היומית לבטוחה.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# הוספת src ל-path (כמו auto_record_decisions.py)
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2


def log(msg: str, level: str = "INFO") -> None:
    """מדפיס שורת לוג עם חותמת זמן UTC ורמה — קריא ב-CI."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def _fmt_margin(v) -> str:
    return "—" if v is None else f"{v:.2f}%"


def _fmt_hold(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _open_reco_trades(engine, results) -> int:
    """גשר 3: אם ה-kill-switch דלוק (RECO_TRADING_ENABLED=true), פותח עסקת Iron Condor בתיק
    ההמלצות לכל פקיעה שנרשמה/קיימת היום ואין לה עסקה. מחזיר מספר שגיאות פתיחה (משפיע על קוד
    היציאה). כשהמתג כבוי — אפס כתיבה, אפס פתיחה. הפתיחה עצמה דרך open_recommended_condor
    (דדופ + kill-switch פנימיים)."""
    try:
        from recommendation_trader import (
            RECO_PORTFOLIO_NAME,
            get_reco_portfolio_id,
            open_recommended_condor,
            reco_trading_enabled,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"ייבוא recommendation_trader נכשל: {exc}", level="ERROR")
        return 1

    if not reco_trading_enabled():
        log("מסחר-לפי-המלצות כבוי (RECO_TRADING_ENABLED != true) — לא נפתחו עסקאות (מצב רגיל).")
        return 0

    pid = get_reco_portfolio_id(engine)
    if pid is None:
        log(f"⚠️ תיק ההמלצות '{RECO_PORTFOLIO_NAME}' לא נמצא — צור אותו לפני הדלקת המתג. דילוג.",
            level="ERROR")
        return 1

    log(f"⚠️ מסחר-לפי-המלצות דלוק — פותח עסקאות בתיק {pid} ('{RECO_PORTFOLIO_NAME}')...")
    # פקיעות עם המלצה היום: recorded (חדשה) או skipped_exists (כבר קיימת) — לשתיהן יש המלצה.
    expiries = [r.get("expiry_date") for r in results
                if r.get("status") in ("recorded", "skipped_exists")]
    counts: dict = {}
    errs = 0
    for exp in expiries:
        res = open_recommended_condor(exp, engine=engine, portfolio_id=pid)
        st = res.get("status")
        counts[st] = counts.get(st, 0) + 1
        if st in ("error", "db_error"):
            errs += 1
        detail = (f"trade_id={res.get('trade_id')}" if st == "opened"
                  else res.get("reason", ""))
        log(f"  פקיעה {exp}: {st} — {detail}")

    log(f"סיכום מסחר: {counts.get('opened', 0)} נפתחו · {counts.get('duplicate', 0)} כפולות · "
        f"{counts.get('skipped', 0)} דולגו · {errs} שגיאות.")
    return errs


def _trading_day_guard() -> int | None:
    """
    שער יום-מסחר: מדלג על הריצה כשהבורסה סגורה.

    מחזיר EXIT_OK לדילוג, None להמשך רגיל. FORCE_RUN=true עוקף (להרצה ידנית
    מ-workflow_dispatch) אך עדיין מרעיש בלוג.

    נוסף אחרי אירוע תשעה באב (23/07/2026): ה-cron לבדו אינו יודע על חגים, והמערכת
    רשמה החלטות והמלצות לפקיעה ביום שהבורסה הייתה סגורה — כשכל הריצות ירוקות.
    """
    from zoneinfo import ZoneInfo

    from trading_calendar import holidays_are_current, is_trading_day, skip_reason

    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    force = os.getenv("FORCE_RUN", "").strip().lower() == "true"

    if not holidays_are_current(today):
        log(f"רשימת החגים ב-trading_calendar אינה מכסה את {today} — יש לעדכן אותה. "
            f"עד אז חגים חדשים לא ייחסמו.", level="WARN")

    reason = skip_reason(today, force=force)
    if reason is not None:
        log(f"{reason} — אין ריצה. (FORCE_RUN=true לעקיפה.)")
        return EXIT_OK

    if force and not is_trading_day(today):
        log(f"FORCE_RUN=true — רץ למרות ש-{today} אינו יום מסחר.", level="WARN")
    return None


def main() -> int:
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        log("DATABASE_URL לא מוגדר בסביבה — לא ניתן לרוץ. יציאה.", level="ERROR")
        return EXIT_CONFIG

    if (rc := _trading_day_guard()) is not None:
        return rc

    # ייבוא אחרי בדיקת ה-env, כדי שכשל env ייתן הודעה ברורה לפני כל טעינה כבדה.
    try:
        from sqlalchemy import text
        from paper_db import _make_engine
        from margin_recorder import record_margin_recommendations_for_upcoming
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

    log("מריץ record_margin_recommendations_for_upcoming "
        "(trigger=scheduled, engine_version=margin-v1.1)...")
    try:
        results = record_margin_recommendations_for_upcoming(
            engine=engine, trigger="scheduled", engine_version="margin-v1.1",
        )
    except Exception as exc:  # noqa: BLE001
        log(f"תיעוד המלצות המרווח נכשל: {exc}", level="ERROR")
        return EXIT_ERROR

    if not results:
        log("אין פקיעות קרובות לתיעוד — אין מה לעשות (מצב רגיל).")
        return EXIT_OK

    recorded = skipped = no_rec = errored = 0
    for r in results:
        status = r.get("status")
        if status == "recorded":
            recorded += 1
        elif status == "skipped_exists":
            skipped += 1
        elif status == "no_recommendation":
            no_rec += 1
        else:  # "error"
            errored += 1
        log(
            f"פקיעה {r.get('expiry_date')} (סוג {r.get('expiry_type')}): "
            f"מרווח={_fmt_margin(r.get('selected_margin'))} "
            f"hold={_fmt_hold(r.get('hold_blended'))} → {status}"
        )

    log(f"סיכום: נרשמו {recorded} · דולגו {skipped} · "
        f"ללא-המלצה {no_rec} · שגיאות {errored}.")

    # ── גשר 3: פתיחת עסקאות לפי המלצה (רק אם ה-kill-switch דלוק; אחרת אפס כתיבה) ──
    trade_errors = _open_reco_trades(engine, results)

    if errored or trade_errors:
        log("היו שגיאות (תיעוד/מסחר) — יציאה עם קוד שגיאה.", level="ERROR")
        return EXIT_ERROR
    if recorded == 0 and (skipped or no_rec):
        log("לא נרשמו המלצות חדשות (הכל כבר תועד היום / אין שרשרת מלאה) — מצב רגיל.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
