#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/reprice_closed_trades.py — תיקון חד-פעמי של עסקאות שנסגרו במחיר סילוק שגוי.

**למה הסקריפט הזה קיים**

עד 06/08/2026 `paper_db.get_settlement_index` קרא מ-`condor_settled_detail.actual_index_close`.
למרות שמו, הערך הזה הוא **סגירת המושב הקודם** — לא מחיר הסילוק. אומת בשלוש
מדידות בלתי תלויות על 28 פקיעות (2026-06-10 → 2026-07-31):

    aic == expiry_history.base_price                      28/28, שגיאה 0.00
    aic == נעילת המדד של המושב הקודם (Yahoo TA35.TA)      28/28
    expiry_history.expiry_price == פתיחת יום הפקיעה       28/28, שגיאה 0.00

סיבת השורש מתועדת ב-`backfill_expiry_history.py`: `settle_expiry` ב-tase-pipeline
רץ ~10:00 שעון ישראל וקורא `meta.regularMarketOpen` מ-Yahoo לפני שהמושב החדש
התעדכן, ולכן שומר את ערך אתמול.

אופציות ה-TA-35 השבועיות מסתלקות ב**מחיר הפתיחה של יום הפקיעה**. ההפרש בין מה
שהשתמשנו בו לבין הסילוק האמיתי הוא בדיוק פער הלילה — 24 נקודות מדד חציונית,
0.59%. על רצועת מרווח של 1.75% זה כשליש מרוחב הרצועה, ולכן די בו כדי להפוך
זכייה להפסד בעסקאות שנסגרו ליד הגבול.

הבאג עצמו תוקן ב-`paper_db`. הסקריפט הזה מתקן את העסקאות שכבר נסגרו.

**מה הוא עושה**

לכל עסקה סגורה: שולף את מחיר הסילוק הנכון, מחשב מחדש payoff מהרגליים
(`_payoff_from_legs` — אותה פונקציה בדיוק שרצה בסגירה), ומעדכן
`close_index`, `pnl`, `pnl_pct`. **`closed_at` ו-`status` אינם נוגעים.**

**מסלול כתיבה חריג — בכוונה**

`AGENTS.md` קובע שמסלול ה-UPDATE היחיד ל-`paper_trades` הוא `close_trade`.
הסקריפט הזה חורג מכך ביודעין, כי הוא מתקן שדות של עסקאות **שכבר סגורות** —
מה ש-`close_trade` אינו יכול לעשות (הוא מניח מעבר open→closed). החריגה
מוגבלת: שלוש עמודות, רק שורות status='closed', וגיבוי מלא באותה טרנזקציה.

**הרצה**

    ./venv/bin/python scripts/reprice_closed_trades.py            # dry-run (ברירת מחדל)
    ./venv/bin/python scripts/reprice_closed_trades.py --apply    # כתיבה, עם גיבוי
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

from paper_db import get_settlement_index          # noqa: E402
from paper_trading import _payoff_from_legs        # noqa: E402

BACKUP_PREFIX = "paper_trades_backup_reprice"
# מעבר לזה זו אינה שגיאת פער-לילה אלא משהו אחר — עוצרים במקום לכתוב.
MAX_PLAUSIBLE_SETTLEMENT_DIFF_PCT = 3.0


def _load_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    env_file = ROOT / "web/.env.local"
    if env_file.exists():
        with open(env_file, encoding="utf-8") as fh:
            for line in fh:
                if line.strip().startswith("DATABASE_URL="):
                    return line.strip().split("=", 1)[1].strip().strip("'\"")
    return ""


def _fetch_closed(engine) -> list[dict]:
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        rows = conn.execute(text("""
            SELECT id, portfolio_id, strategy_name, expiry_date, opened_at,
                   entry_index, close_index, entry_cost, entry_commission,
                   exit_commission, pnl, legs_json
            FROM paper_trades
            WHERE status = 'closed'
            ORDER BY expiry_date, portfolio_id
        """)).fetchall()
    return [dict(r._mapping) for r in rows]


def _recompute(trade: dict, settlement: float) -> dict:
    """מחשב מחדש payoff ו-pnl בסילוק הנכון. אותה נוסחה כמו במסלול הסגירה."""
    legs = trade.get("legs_json") or []
    if isinstance(legs, str):
        import json
        legs = json.loads(legs)

    payoff  = _payoff_from_legs(legs, float(settlement))
    e_cost  = float(trade.get("entry_cost") or 0.0)
    e_comm  = float(trade.get("entry_commission") or 0.0)
    x_comm  = float(trade.get("exit_commission") or 0.0)
    pnl     = round(payoff - e_cost - e_comm - x_comm, 2)
    pnl_pct = round(pnl / abs(e_cost), 4) if abs(e_cost) > 0.001 else None
    return {"payoff": round(payoff, 2), "pnl": pnl, "pnl_pct": pnl_pct}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="כתיבה בפועל (ברירת מחדל: dry-run)")
    args = ap.parse_args()

    url = _load_url()
    if not url:
        print("⛔ אין DATABASE_URL")
        return 1
    os.environ["DATABASE_URL"] = url
    engine = create_engine(url, pool_pre_ping=True,
                           connect_args={"connect_timeout": 30})

    trades = _fetch_closed(engine)
    if not trades:
        print("⛔ לא נמצאו עסקאות סגורות — עצירה (חשד לכשל שאילתה).")
        return 1
    print(f"עסקאות סגורות: {len(trades)}\n")

    # ── מחיר הסילוק הנכון לכל פקיעה, פעם אחת ──────────────────────────
    settlements: dict[str, float | None] = {}
    for t in trades:
        key = str(t["expiry_date"])[:10]
        if key not in settlements:
            settlements[key] = get_settlement_index(key, engine=engine)

    changes: list[dict] = []
    unresolved: list[str] = []
    implausible: list[str] = []

    for t in trades:
        key = str(t["expiry_date"])[:10]
        new_settle = settlements.get(key)
        if new_settle is None:
            unresolved.append(key)
            continue
        old_settle = float(t["close_index"]) if t["close_index"] is not None else None
        if old_settle:
            drift = abs(new_settle - old_settle) / old_settle * 100.0
            if drift > MAX_PLAUSIBLE_SETTLEMENT_DIFF_PCT:
                implausible.append(f"{key}: {old_settle:.2f} → {new_settle:.2f} ({drift:.2f}%)")
                continue
        rec = _recompute(t, new_settle)
        changes.append({
            **t, "new_settle": new_settle, "old_settle": old_settle,
            "new_pnl": rec["pnl"], "new_pnl_pct": rec["pnl_pct"],
            "delta": round(rec["pnl"] - float(t["pnl"] or 0.0), 2),
        })

    if implausible:
        print("⛔ הפרשי סילוק חריגים — לא פער לילה. עצירה:")
        for line in implausible:
            print(f"   {line}")
        return 1
    if unresolved:
        print(f"⚠️  {len(set(unresolved))} פקיעות ללא מחיר סילוק — יידלגו: "
              f"{', '.join(sorted(set(unresolved)))}\n")

    # ── דוח ──────────────────────────────────────────────────────────
    print(f"{'id':>5} {'תיק':>4} {'פקיעה':<12} {'סילוק ישן':>10} {'סילוק נכון':>11} "
          f"{'P&L ישן':>9} {'P&L נכון':>10} {'שינוי':>9}  הפיכה")
    print("-" * 92)
    flips = 0
    for c in changes:
        old_pnl = float(c["pnl"] or 0.0)
        flip = ""
        if (old_pnl > 0) != (c["new_pnl"] > 0):
            flip = "🔄 זכייה→הפסד" if old_pnl > 0 else "🔄 הפסד→זכייה"
            flips += 1
        print(f"{c['id']:>5} {c['portfolio_id']:>4} {str(c['expiry_date'])[:10]:<12} "
              f"{c['old_settle'] or 0:>10.2f} {c['new_settle']:>11.2f} "
              f"{old_pnl:>+9.0f} {c['new_pnl']:>+10.0f} {c['delta']:>+9.0f}  {flip}")

    print("-" * 92)
    old_tot = sum(float(c["pnl"] or 0.0) for c in changes)
    new_tot = sum(c["new_pnl"] for c in changes)
    print(f"  עסקאות שישתנו: {len(changes)}   הפיכות סימן: {flips}")
    print(f"  P&L כולל:  {old_tot:>+10,.0f}  →  {new_tot:>+10,.0f}   "
          f"({new_tot - old_tot:>+,.0f})")

    by_pf: dict[int, list[float]] = {}
    for c in changes:
        by_pf.setdefault(c["portfolio_id"], []).append(c["new_pnl"] - float(c["pnl"] or 0))
    print("\n  לפי תיק:")
    for pid in sorted(by_pf):
        print(f"    תיק {pid}:  {sum(by_pf[pid]):>+9,.0f}  ({len(by_pf[pid])} עסקאות)")

    if not args.apply:
        print("\n⚠️  DRY-RUN — אפס כתיבה ל-DB. להרצה בפועל: --apply")
        return 0

    # ── כתיבה, עם גיבוי באותה טרנזקציה ────────────────────────────────
    stamp  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = f"{BACKUP_PREFIX}_{stamp}"
    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE TABLE {backup} AS SELECT * FROM paper_trades WHERE status='closed'"
        ))
        n_backup = conn.execute(text(f"SELECT count(*) FROM {backup}")).scalar()
        if n_backup != len(trades):
            raise SystemExit(
                f"⛔ הגיבוי מכיל {n_backup} שורות במקום {len(trades)} — ביטול."
            )
        for c in changes:
            conn.execute(text("""
                UPDATE paper_trades
                   SET close_index = :ci, pnl = :pnl, pnl_pct = :pct
                 WHERE id = :id AND status = 'closed'
            """), {"ci": c["new_settle"], "pnl": c["new_pnl"],
                   "pct": c["new_pnl_pct"], "id": c["id"]})
    print(f"\n✅ עודכנו {len(changes)} עסקאות. גיבוי: {backup} ({n_backup} שורות)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
