#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/auto_open_vwap_trades.py — פתיחה יומית של התיק הממולא במחירי עסקה.

**למה הסקריפט הזה קיים**

תיק 8 ("המלצות המערכת") ממולא לפי `lastrate`. `lastrate` אינו מחיר עסקה: הוא
נופל מחוץ לטווח `[lowrate, highrate]` של אותו יום ב-45% מה-CALL ו-40% מה-PUT,
ודווקא בסטרייקים שכן נסחרו (HANDOFF 11.2). כלומר ה-track record של תיק 8 —
ושל כל התיקים — נשען על מחיר שלא ניתן לסחור בו.

הסקריפט הזה פותח את **אותן המלצות בדיוק** בתיק נפרד, אבל ממלא ב-VWAP
(`OverallTurnOverValue_Shekel / OverallTurnOverUnits`) — מחיר עסקה משוקלל,
מאומת בתוך טווח הנסחר ב-100.0% מהמקרים (2,697/2,697 CALL · 2,995/2,995 PUT).

**דילוג הוא התוצאה, לא תקלה.** כשאין מחיר עסקה לכל 4 הרגליים — אין עסקה.
נמדד ב-07/08/2026: 1 מתוך 4 המלצות עברה. הנזילות מרוכזת בפקיעה הקרובה
(אופק 1 מושב → 100% מהרגליים, אופק 5 → 18%), ולכן התיק יתכנס מעצמו לאופק
הקצר. **זה בדיוק המידע שחסר לנו**, ולכן אין להרחיב את הקריטריון כדי "לפתוח יותר".

**בידוד מוחלט מהתיקים הקיימים** — הסקריפט אינו נוגע בתיקים 2–8:
  • `strategy_id = 103`; כל האגרגציות חוצות-התיקים חסומות ל-1..6.
  • kill-switch משלו (`VWAP_TRADING_ENABLED`), נפרד מ-`RECO_TRADING_ENABLED`.
  • תיק משלו, ודדופ ברמת הפקיעה בתוכו בלבד.

קודי יציאה: 0 = הצלחה או דילוג לגיטימי · 1 = שגיאה.

    python scripts/auto_open_vwap_trades.py                     # תיק 9, dry-run
    python scripts/auto_open_vwap_trades.py --spec liquidity   # תיק 10
    python scripts/auto_open_vwap_trades.py --commit            # כתיבה
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
    """אין מסחר ⇒ אין שרשרת חדשה ⇒ אין מה לפתוח. FORCE_RUN=true עוקף.

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
    ap.add_argument("--commit", action="store_true",
                    help="כתיבה בפועל (ברירת מחדל: dry-run)")
    ap.add_argument("--spec", choices=("vwap", "liquidity"), default="vwap",
                    help="איזה תיק להריץ: vwap (תיק 9) או liquidity (תיק 10)")
    args = ap.parse_args()

    if (rc := _trading_day_guard()) is not None:
        return rc

    from vwap_trader import SPECS, get_portfolio_id, open_vwap_condor, trading_enabled

    spec = SPECS[args.spec]
    if not trading_enabled(spec):
        log(f"{spec.env_flag} != 'true' — kill-switch כבוי, אין ריצה.")
        return EXIT_OK

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        log("אין DATABASE_URL.", level="ERROR")
        return EXIT_ERR
    engine = create_engine(db_url, pool_pre_ping=True,
                           connect_args={"connect_timeout": 30})

    pid = get_portfolio_id(spec, engine)
    if pid is None:
        log(f"התיק '{spec.portfolio_name}' אינו קיים — יש ליצור אותו פעם אחת.",
            level="ERROR")
        return EXIT_ERR

    # הפקיעות שיש להן המלצה **מהיום**. אין המלצה ⇒ אין מה לשקף.
    #
    # ⚠️ תוקן 01/09/2026. הגרסה הקודמת בחרה
    #     recommended_at::date = (SELECT max(recommended_at::date) ...)
    # כלומר "ההמלצה האחרונה שקיימת", **בלי השוואה ל-today** — ההערה מעליה כבר
    # אמרה "מהיום", והקוד אמר משהו אחר. ביום שבו שלב 2 לא רשם המלצות (האוסף
    # נפל, שרשרת ישנה, כשל DB) הסקריפט היה נופל אחורה להמלצה של אתמול ופותח
    # לפיה. הסטרייקים של קונדור נבחרים ביחס לרמת המדד של אותו יום; שימוש
    # בסטרייקים של אתמול עם מחירי היום אינו המרווח שהמנוע בחר.
    #
    # `CURRENT_DATE` הוא תאריך ה-DB. השרת ב-UTC, וההרצות ב-09:00/13:00 UTC =
    # 12:00/16:00 בישראל — אותו יום קלנדרי בשני האזורים, ולכן אין כאן פער.
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        expiries = [r[0] for r in conn.execute(text("""
            SELECT DISTINCT expiry_date FROM margin_recommendations
            WHERE recommended_at::date = CURRENT_DATE
            ORDER BY expiry_date
        """)).fetchall()]

    if not expiries:
        # לא "אין מה לפתוח" סתם — זה עלול להיות שלב 2 שנכשל, וזו תקלה.
        log("אין המלצות מהיום — לא נפתח כלום. אם שלב 2 (auto_record_margins) "
            "רץ היום ולא רשם, זו תקלה ולא יום שקט.", level="WARN")
        return EXIT_OK

    log(f"'{spec.portfolio_name}' (תיק {pid}, strategy {spec.strategy_id}) · "
        f"{len(expiries)} פקיעות · סף מחזור {spec.min_units:g} · "
        f"{'כתיבה' if args.commit else 'DRY-RUN'}")

    opened = skipped = errors = 0
    for exp in expiries:
        try:
            r = open_vwap_condor(exp, engine=engine, portfolio_id=pid,
                                 dry_run=not args.commit, spec=spec)
        except Exception as exc:                      # noqa: BLE001
            errors += 1
            log(f"{str(exp)[:10]}  חריגה: {exc}", level="ERROR")
            continue

        if r["status"] in ("opened", "dry-run"):
            opened += 1
            t = r["trade"]
            log(f"{r['expiry_date']}  ✅ קרדיט {-float(t['entry_cost']):.2f} ₪ · "
                f"max_loss {float(t['max_loss']):.2f} ₪ · "
                f"lastrate היה {t['market_snapshot_json'].get('net_premium_lastrate')}")
        elif r["status"] == "error":
            errors += 1
            log(f"{r['expiry_date']}  שגיאה: {r['reason']}", level="ERROR")
        else:
            skipped += 1
            log(f"{r['expiry_date']}  ⛔ {r['reason']}")

    log(f"סיכום: נפתחו {opened} · דולגו {skipped} · שגיאות {errors}")
    if not args.commit:
        log("⚠️  DRY-RUN — אפס כתיבה ל-DB. להרצה בפועל: --commit")
    try:
        engine.dispose()
    except Exception:                                  # noqa: BLE001
        pass
    return EXIT_ERR if errors else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
