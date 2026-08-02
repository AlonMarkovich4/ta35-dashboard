#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/auto_open_benchmark_trades.py — פתיחה אוטומטית של עסקאות ה-benchmark (תיקים 2–7).

**למה הסקריפט הזה קיים**

עד 01/08/2026 לא הייתה שום אוטומציה לתיקי ה-benchmark. `open_trades_for_expiry`
נקראה ממקום אחד בלבד — `pages/5_paper_trading.py`, ממשק Streamlit **שאינו פרוס**
(render.yaml מרים רק את Next.js ואת ה-webhook). התוצאה: 24 עסקאות נפתחו ידנית
ב-15/06/2026, ומאז כלום — **132 עסקאות חסרות** על פני 22 פקיעות.

נזק משני: `decision_validator` משווה את החלטות המנוע מול ה-P&L של תיקי ה-benchmark.
בלי עסקאות חדשות, 19 מתוך 23 החלטות מנוע נשארו בלי מול-מה-להשוות — גשר 2 היה משותק.

**המדיניות — זהה לתיק ההמלצות (8), בכוונה**

פותח ביום המסחר הראשון שבו הפקיעה מופיעה בשרשרת, בתנאי `min_days_to_expiry=1`.
זהה ל-`open_recommended_condor`, כדי ששתי הקבוצות ייכנסו באותו רגע ובאותו מחיר —
אחרת ההשוואה בגשר 2 חסרת ערך.

הדדופ עצמו הוא ברמת ה-DB: UNIQUE (portfolio_id, strategy_id, expiry_date),
ו-`open_trades_for_expiry` בודק אותו לפני כל הכנסה. לכן ריצה יומית בטוחה.

קודי יציאה:
  0  הצלחה (כולל "אין מה לפתוח" ו"הכל כבר פתוח" — מצבים רגילים).
  1  שגיאה אמיתית, או שרשרת לא טרייה ביום מסחר.
  2  תקלת תצורה (DATABASE_URL חסר).

הרצה:
    DATABASE_URL='postgresql://...' python3 scripts/auto_open_benchmark_trades.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2

BENCHMARK_PORTFOLIO_IDS = (2, 3, 4, 5, 6, 7)
MIN_DAYS_TO_EXPIRY = 1          # זהה לתיק 8 — לא פותחים על פקיעת אותו-יום


def log(msg: str, level: str = "INFO") -> None:
    """מדפיס שורת לוג עם חותמת זמן UTC ורמה — קריא ב-CI."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def benchmark_trading_enabled() -> bool:
    """kill-switch. ברירת מחדל **דלוק** — בניגוד ל-RECO, כאן אין תלות במנוע.

    האסטרטגיות רצות על פרמטרים מוקפאים (`strategy_payoff_params`) ישירות מהשרשרת,
    בלי `expiry_history`, בלי `hold_probability` ובלי הכיול שנמצא בבדיקה. לכן אין
    סיבה להשאיר אותן כבויות — הן ה-benchmark שמולו נמדד כל השאר.
    """
    return os.getenv("BENCHMARK_TRADING_ENABLED", "true").strip().lower() != "false"


def _trading_day_guard() -> int | None:
    """
    שער יום-מסחר: מדלג על הריצה כשהבורסה סגורה.

    מחזיר EXIT_OK לדילוג, None להמשך רגיל. FORCE_RUN=true עוקף (להרצה ידנית
    מ-workflow_dispatch) אך עדיין מרעיש בלוג.
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

    if not benchmark_trading_enabled():
        log("פתיחת benchmark כבויה (BENCHMARK_TRADING_ENABLED=false) — אפס כתיבה.")
        return EXIT_OK

    try:
        from zoneinfo import ZoneInfo

        from paper_db import _make_engine, get_portfolios
        from paper_trading import open_trades_for_expiry
        from supabase_loader import get_available_expiries, get_latest_option_chain
        from trading_calendar import is_chain_fresh
    except Exception as exc:  # noqa: BLE001
        log(f"ייבוא מודולים נכשל: {exc}", level="ERROR")
        return EXIT_ERROR

    engine = _make_engine(None)
    if engine is None:
        log("לא ניתן לבנות engine מ-DATABASE_URL.", level="ERROR")
        return EXIT_ERROR

    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()

    portfolios = [p for p in (get_portfolios(engine=engine) or [])
                  if p.get("id") in BENCHMARK_PORTFOLIO_IDS]
    if not portfolios:
        log(f"לא נמצאו תיקי benchmark ({BENCHMARK_PORTFOLIO_IDS}) — דילוג.", level="ERROR")
        return EXIT_ERROR
    log(f"תיקי benchmark: {sorted(p['id'] for p in portfolios)}")

    try:
        raw = get_available_expiries(engine=engine) or []
    except Exception as exc:  # noqa: BLE001
        log(f"קריאת הפקיעות הזמינות נכשלה: {exc}", level="ERROR")
        return EXIT_ERROR

    counts: dict = {}
    errors = stale = 0

    for exp_str in sorted(set(str(e)[:10] for e in raw)):
        try:
            exp_d = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        days = (exp_d - today).days
        if days < MIN_DAYS_TO_EXPIRY:
            log(f"  פקיעה {exp_str}: דילוג — נותרו {days} ימים (נדרש ≥ {MIN_DAYS_TO_EXPIRY}).")
            continue

        chain = get_latest_option_chain(exp_str, engine=engine)
        entries = (chain or {}).get("expiries") or []
        if not entries:
            log(f"  פקיעה {exp_str}: אין שרשרת — דילוג.", level="WARN")
            continue

        # שער טריות — פר-פקיעה, זהה ל-margin_recorder.
        fetch_date = entries[0].get("fetch_date")
        if not is_chain_fresh(fetch_date, today):
            stale += 1
            log(f"  פקיעה {exp_str}: שרשרת לא טרייה (נמשכה {fetch_date}) — לא נפתחות עסקאות.",
                level="ERROR")
            continue

        try:
            results = open_trades_for_expiry(exp_str, chain, portfolios, engine=engine)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log(f"  פקיעה {exp_str}: פתיחה נכשלה: {exc}", level="ERROR")
            continue

        for r in results:
            st = r.get("status")
            counts[st] = counts.get(st, 0) + 1
            if st in ("error", "db_error"):
                errors += 1
        summary = " · ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "אין תוצאות"
        log(f"  פקיעה {exp_str}: {len(results)} תוצאות ({summary})")

    total = " · ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "אפס"
    log(f"סיכום: {total} · שגיאות {errors} · שרשרת-ישנה {stale}")

    if errors:
        log("היו שגיאות פתיחה — יציאה עם קוד שגיאה.", level="ERROR")
        return EXIT_ERROR
    if stale:
        log(f"{stale} פקיעות עם שרשרת לא טרייה ביום מסחר — האוסף לא סיפק נתונים היום.",
            level="ERROR")
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
