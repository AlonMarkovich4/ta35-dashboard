#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/backfill_benchmark_trades.py — שחזור עסקאות ה-benchmark שהוחמצו.

**הרקע:** לתיקים 2–7 מעולם לא הייתה אוטומציה (ראה auto_open_benchmark_trades.py).
24 עסקאות נפתחו ידנית ב-15/06/2026 ואז כלום, כך שנוצר חור של 22 פקיעות.
הסקריפט הזה משחזר אותן מהארכיון `tase_putcall_history`.

**איך:** לכל פקיעה חסרה, נטענת השרשרת מיום המסחר הראשון שבו הפקיעה הופיעה
בארכיון (עם ≥1 יום לפקיעה), ומורצת עליה `open_trades_for_expiry` — **אותו
נתיב פרודקשן** שפותח עסקאות בזמן אמת, כולל דדופ, בדיקות מחיר ועמלות.
אפס שכפול לוגיקה.

⚠️ **פקיעות ללא סילוק מוחרגות** (`_NO_SETTLEMENT`). פתיחת עסקה לפקיעה שלא
התרחשה יוצרת יתומה קבועה שלא תיסגר לעולם — בדיוק כמו paper_trades.id=36.

הדדופ מבטיח שהרצה חוזרת לא תיצור כפילות, ושפקיעות שכבר יש להן עסקאות
(למשל 04–07/08) יידלגו.

הרצה:
    DATABASE_URL='...' python3 scripts/backfill_benchmark_trades.py            # dry-run
    DATABASE_URL='...' python3 scripts/backfill_benchmark_trades.py --commit   # כתיבה
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sqlalchemy import create_engine, text     # noqa: E402

EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2

BENCHMARK_PORTFOLIO_IDS = (2, 3, 4, 5, 6, 7)
LAST_COVERED_EXPIRY = "2026-06-19"   # הפקיעה האחרונה שכן קיבלה עסקאות benchmark
ARCHIVE_TABLE = "tase_putcall_history"

# פקיעות שלא התרחשו — אין ולא יהיה להן סילוק, ולכן עסקה עליהן היא יתומה קבועה.
_NO_SETTLEMENT = {
    "2026-07-23": "תשעה באב — הבורסה לא נפתחה",
}


def log(msg: str, level: str = "INFO") -> None:
    """שורת לוג עם חותמת זמן UTC."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def _first_seen_map(engine) -> list[tuple[str, str]]:
    """[(expiry, first_fetch_date)] — היום הראשון בארכיון שבו הפקיעה נראתה,
    עם לפחות יום אחד עד הפקיעה. ממוין לפי פקיעה."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT expiry_date, min(fetch_date) AS first_seen
            FROM {ARCHIVE_TABLE}
            WHERE expiry_date > :last
              AND fetch_date::date <= (expiry_date::date - INTERVAL '1 day')
            GROUP BY expiry_date ORDER BY expiry_date
        """), {"last": LAST_COVERED_EXPIRY}).fetchall()  # noqa: S608 — קבוע
    return [(str(r[0]), str(r[1])) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description="שחזור עסקאות benchmark מהארכיון")
    ap.add_argument("--commit", action="store_true",
                    help="כתיבה בפועל (ברירת מחדל: dry-run)")
    args = ap.parse_args()

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        log("DATABASE_URL לא מוגדר.", level="ERROR")
        return EXIT_CONFIG
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    os.environ["DATABASE_URL"] = db_url

    import paper_trading as pt
    from paper_db import get_portfolios
    from supabase_loader import get_latest_option_chain

    engine = create_engine(db_url, pool_pre_ping=True,
                           connect_args={"connect_timeout": 30})

    # get_portfolios בולע חריגות ומחזיר [] — בלי השער הזה הריצה מסתיימת
    # ירוקה בלי לפתוח כלום, וזה נראה כמו "אין מה לשחזר".
    all_p = get_portfolios(engine=engine) or []
    portfolios = [p for p in all_p if p.get("id") in BENCHMARK_PORTFOLIO_IDS]
    if len(portfolios) != len(BENCHMARK_PORTFOLIO_IDS):
        log(f"נטענו {len(portfolios)} תיקי benchmark במקום "
            f"{len(BENCHMARK_PORTFOLIO_IDS)} (get_portfolios החזיר {len(all_p)}). "
            f"ייתכן כשל DB שנבלע — עצירה.", level="ERROR")
        return EXIT_ERROR
    log(f"תיקי benchmark: {sorted(p['id'] for p in portfolios)}")

    if not args.commit:
        # dry-run: חוסמים את שתי פונקציות הכתיבה היחידות.
        pt.insert_trade = lambda trade, engine=None: {"id": -1, **trade}
        pt._insert_skipped = lambda *a, **k: None
        log("DRY-RUN — לא ייכתב דבר. הוסף --commit לכתיבה.", level="WARN")

    counts: Counter = Counter()
    errors = 0

    for expiry, first_seen in _first_seen_map(engine):
        if expiry in _NO_SETTLEMENT:
            log(f"  {expiry}: מוחרגת — {_NO_SETTLEMENT[expiry]}. "
                f"פתיחה הייתה יוצרת יתומה קבועה.", level="WARN")
            counts["excluded"] += 1
            continue

        chain = get_latest_option_chain(
            expiry, engine=engine,
            source_table=ARCHIVE_TABLE, fetch_date=first_seen,
        )
        if not chain or not chain.get("expiries"):
            log(f"  {expiry}: אין שרשרת בארכיון ל-{first_seen} — דילוג.", level="WARN")
            counts["no_chain"] += 1
            continue

        try:
            results = pt.open_trades_for_expiry(expiry, chain, portfolios, engine=engine)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log(f"  {expiry}: נכשל: {exc}", level="ERROR")
            continue

        per = Counter(r.get("status") for r in results)
        counts.update(per)
        errors += per.get("error", 0) + per.get("db_error", 0)
        log(f"  {expiry} (שרשרת {first_seen}): "
            + " · ".join(f"{k}={v}" for k, v in sorted(per.items())))

    log("סיכום: " + " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if errors:
        log(f"{errors} שגיאות.", level="ERROR")
        return EXIT_ERROR
    if not args.commit:
        log("DRY-RUN הסתיים — לא נכתב דבר.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
