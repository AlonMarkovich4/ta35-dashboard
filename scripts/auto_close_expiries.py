#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/auto_close_expiries.py — סגירה אוטומטית של פקיעות שהבשילו.

מיועד להרצה מתוזמנת (GitHub Action / cron). הטריגר הוא **קיום הסטלמנט ב-DB**,
לא שעה: הסקריפט סוגר רק פקיעות שעברו את שני התנאים —
  (א) יש להן עסקאות status='open' ב-paper_trades,
  (ב) קיים actual_index_close ב-condor_settled_detail.
שניהם נבדקים ב-get_expiries_ready_to_close — אין סגירה מוקדמת.

idempotent: get_expiries_ready_to_close מחזיר רק פקיעות עם עסקאות 'open'.
אחרי סגירה הן 'closed' ולא יחזרו — ריצה חוזרת לא תסגור שוב את אותן עסקאות.

**סגירת לולאת הלמידה:** אחרי הסגירה, מריץ update_expiry_history_from_settlements —
מזרים כל פקיעה שנסגרה (condor_settled_detail) ל-expiry_history (append-only, אידמפוטנטי),
כדי שהמנוע ילמד מהתנועות האחרונות. כישלון שם לא מפיל את הסגירה (רק WARN).

משתמש בקוד הקיים בלבד (close_matured_expiry → close_trades_for_expiry) —
אפס שכפול של לוגיקת P&L.

DATABASE_URL נקרא מהסביבה בלבד — לעולם לא בקוד.

קודי יציאה:
  0  — הצלחה (כולל "אין פקיעות לסגירה" — המצב הרגיל ברוב הריצות).
  1  — שגיאה אמיתית (חיבור DB נכשל / חריגה / עסקאות שלא נסגרו).
  2  — תקלת תצורה (DATABASE_URL חסר).

הרצה:
    DATABASE_URL='postgresql://...' python3 scripts/auto_close_expiries.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# נתיב src — כדי לייבא את הפונקציות האמיתיות של הפרויקט.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sqlalchemy import create_engine, text          # noqa: E402
from paper_db import get_expiries_ready_to_close      # noqa: E402
from paper_trading import close_matured_expiry        # noqa: E402  (לא משכפלים P&L)
from history_updater import update_expiry_history_from_settlements  # noqa: E402  (סגירת לולאת הלמידה)

# ── קודי יציאה ────────────────────────────────────────────────────────────
EXIT_OK     = 0
EXIT_ERROR  = 1
EXIT_CONFIG = 2


def log(msg: str, level: str = "INFO") -> None:
    """מדפיס שורת לוג עם חותמת זמן UTC — לתיעוד ריצות בהיסטוריית ה-CI."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}Z] {level:<5}| {msg}", flush=True)


# ── דגל הזרמת expiry_history ──────────────────────────────────────────────
# ⛔ כבוי כברירת מחדל מ-27/07/2026.
# הסיבה: ההזרמה מחשבת move_pct מ-condor_settled_detail.base_index_value, שהוא
# עוגן *חודשי* — אותו ערך חוזר על עצמו עד 4 פקיעות שבועיות רצופות (אומת ב-DB).
# שורות ה-CSV, לעומת זאת, מודדות תנועת **מושב אחד** (base_price[i] == close_price[i-1],
# אומת 12/12). התוצאה: אותה עמודה מכילה שתי הגדרות — ממוצע |תנועה| 1.45% בשורות
# המוזרמות מול 0.49% בשורות ה-CSV. זהו הקורפוס היחיד שהמנוע לומד ממנו.
# להדלקה מחדש: HISTORY_UPDATER_ENABLED=true, אחרי הכרעה בסמנטיקת base_price.
def _history_updater_enabled() -> bool:
    """מחזיר True רק אם HISTORY_UPDATER_ENABLED=='true' (ברירת מחדל: כבוי)."""
    return os.getenv("HISTORY_UPDATER_ENABLED", "").strip().lower() == "true"


def _build_engine(db_url: str):
    """יוצר engine מ-DATABASE_URL (postgres:// → postgresql://, pool_pre_ping)."""
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, pool_pre_ping=True)


def _verify_connection(engine) -> None:
    """מאמת חיבור חי ל-DB (SELECT 1). זורק חריגה אם נכשל.

    קריטי: get_expiries_ready_to_close בולע שגיאות DB ומחזיר [] — בלי אימות
    מפורש, תקלת DB הייתה נראית כמו "אין פקיעות לסגירה" (exit 0 שגוי).
    """
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def run(engine) -> dict:
    """סוגר את כל הפקיעות הבשלות דרך close_matured_expiry. מחזיר סיכום מובנה.

    אינו זורק על "אין פקיעות" — זה מצב תקין. שגיאות אמיתיות מטופלות ב-main.
    מחזיר: {expiries_processed, expiries_closed, trades_closed, trades_failed,
            total_pnl, results}.
    """
    ready = get_expiries_ready_to_close(engine=engine)

    if not ready:
        log("אין פקיעות לסגירה — אין פקיעה עם עסקאות פתוחות וסטלמנט זמין.")
        return {
            "expiries_processed": 0, "expiries_closed": 0,
            "trades_closed": 0, "trades_failed": 0,
            "total_pnl": 0.0, "results": [],
        }

    names = ", ".join(str(r.get("expiry_date")) for r in ready)
    log(f"נמצאו {len(ready)} פקיעות בשלות לסגירה: {names}")

    results: list[dict] = []
    trades_closed = 0
    trades_failed = 0
    expiries_closed = 0
    total_pnl = 0.0

    for r in ready:
        exp = str(r.get("expiry_date"))   # מחרוזת — בטוח מול date/text (literal coercion)
        res = close_matured_expiry(exp, engine=engine)
        results.append(res)

        closed = int(res.get("closed", 0) or 0)
        errors = int(res.get("errors", 0) or 0)
        pnl    = float(res.get("total_pnl", 0.0) or 0.0)
        si     = res.get("settlement_index")

        trades_closed += closed
        trades_failed += errors
        total_pnl     += pnl
        if closed > 0:
            expiries_closed += 1

        si_txt = f"{si:,.2f}" if si is not None else "—"
        line = f"פקיעה {exp}: נסגרו {closed} עסקאות | סטלמנט {si_txt} | P&L {pnl:,.2f} ₪"
        if errors:
            log(line + f" | ⚠️ {errors} נכשלו (יישארו פתוחות לריצה הבאה)", level="WARN")
        else:
            log(line)

    total_pnl = round(total_pnl, 2)
    summary_line = (
        f"=== סיכום: {expiries_closed}/{len(ready)} פקיעות נסגרו | "
        f"{trades_closed} עסקאות | סך P&L {total_pnl:,.2f} ₪"
    )
    if trades_failed:
        summary_line += f" | {trades_failed} כשלי-סגירה"
    log(summary_line + " ===")

    return {
        "expiries_processed": len(ready),
        "expiries_closed":    expiries_closed,
        "trades_closed":      trades_closed,
        "trades_failed":      trades_failed,
        "total_pnl":          total_pnl,
        "results":            results,
    }


def _safe_dispose(engine) -> None:
    """משחרר את ה-engine בלי לזרוק (ניקוי בסוף הריצה)."""
    try:
        engine.dispose()
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    """נקודת כניסה: קורא env, מאמת חיבור, מריץ סגירה. מחזיר קוד יציאה."""
    log("=== auto_close_expiries: התחלה ===")

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        log("DATABASE_URL לא מוגדר בסביבה — לא ניתן לרוץ. יציאה.", level="ERROR")
        return EXIT_CONFIG

    try:
        engine = _build_engine(db_url)
    except Exception as exc:  # noqa: BLE001
        log(f"יצירת engine נכשלה: {exc}", level="ERROR")
        return EXIT_ERROR

    try:
        _verify_connection(engine)
    except Exception as exc:  # noqa: BLE001
        log(f"חיבור ל-DB נכשל (SELECT 1): {exc}", level="ERROR")
        _safe_dispose(engine)
        return EXIT_ERROR

    try:
        summary = run(engine)
        # לולאת הלמידה: אחרי סגירת הפקיעות, מזרים אותן ל-expiry_history (append-only,
        # אידמפוטנטי). כישלון כאן לא מפיל את הסגירה — העסקאות כבר נסגרו; רק לוג WARN.
        if not _history_updater_enabled():
            log("הזרמת expiry_history מושבתת (HISTORY_UPDATER_ENABLED != 'true') — מדלג. "
                "ראה הערת הדגל בראש הקובץ.", level="WARN")
        else:
            try:
                upd = update_expiry_history_from_settlements(engine, dry_run=False)
                log(f"עדכון expiry_history: נוספו {upd['inserted']} פקיעות "
                    f"(מסולקות {upd['settled_total']}, כבר קיימות {upd['already_present']}, "
                    f"דולגו-בלי-base {len(upd['skipped_no_base'])}).")
                for w in upd.get("warnings", []):
                    log(w, level="WARN")
            except Exception as exc:  # noqa: BLE001
                log(f"עדכון expiry_history נכשל (הסגירה תקינה, ממשיך): {exc}", level="WARN")
    except Exception as exc:  # noqa: BLE001
        log(f"ריצת הסגירה נכשלה: {exc}", level="ERROR")
        return EXIT_ERROR
    finally:
        _safe_dispose(engine)

    # עסקאות שלא נסגרו (כשל אמיתי) → exit 1 כדי ש-CI יסמן. הן נשארו 'open'
    # ויינסו שוב בריצה הבאה (idempotent self-healing).
    if summary.get("trades_failed", 0) > 0:
        log("היו כשלי-סגירה — יציאה עם קוד שגיאה לסימון ב-CI.", level="ERROR")
        return EXIT_ERROR

    log("=== auto_close_expiries: סיום תקין ===")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
