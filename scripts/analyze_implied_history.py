#!/usr/bin/env python3
"""
analyze_implied_history.py — המבט הראשון: האם השוק מנבא טוב?

קריאה בלבד (SELECT). אפס כתיבה ל-DB.

לכל snapshot יומי בארכיון (tase_putcall_history) ולכל פקיעה שנסגרה, מחשב מה היה
ה-expected move *אז* (מחיר ה-ATM straddle באותו יום) — ומשווה לתנועה שקרתה בפועל.

התנועה בפועל נלקחת מ-expiry_history (המקור הקנוני), ובגיבוי מ-condor_settled_detail
(base_index_value → actual_index_close). נכון להיום החפיפה היא רק דרך ה-settlement:
expiry_history מסתיים 2026-05-07 והארכיון מתחיל 2026-05-22.

פלט: טבלה (snapshot × פקיעה) + מתאם + פילוח לפי ימים-לפקיעה.

הרצה:
    DATABASE_URL="..." python scripts/analyze_implied_history.py
    DATABASE_URL="..." python scripts/analyze_implied_history.py --last-only
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from implied_move import expected_move_pct  # noqa: E402
from options_parser import find_atm         # noqa: E402


def _engine():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        sys.exit("DATABASE_URL לא מוגדר. הרץ:  DATABASE_URL=\"...\" python scripts/analyze_implied_history.py")
    return create_engine(url.replace("postgres://", "postgresql://", 1), pool_pre_ping=True)


def _load_chain_history(eng) -> pd.DataFrame:
    """כל הארכיון, בפורמט ה-chain של המנוע (strike/call_price/put_price/call_delta)."""
    q = text("""
        SELECT fetch_date, expiry_date,
               COALESCE(expirationprice_call, expirationprice_put)::float AS strike,
               lastrate_call::float AS call_price,
               lastrate_put::float  AS put_price,
               delta_call::float    AS call_delta,
               delta_put::float     AS put_delta
        FROM tase_putcall_history
    """)
    df = pd.read_sql(q, eng)
    return df.fillna({"call_price": 0.0, "put_price": 0.0})


def _load_expiry_closes(eng) -> dict:
    """פקיעה(date) → מחיר הנעילה בפקיעה.

    **קריטי לנכונות ההשוואה:** התנועה בפועל נמדדת מהמדד *בזמן ה-snapshot* ועד
    הנעילה — בדיוק החלון שה-expected move מתמחר. אסור להשתמש ב-move_pct המוכן
    (או ב-base_index_value של הסטלמנט): הם נמדדים מבסיס שנקבע בזמן אחר, ולכן
    השוואה מולם היא תפוחים מול תפוזים (implied ליום אחד מול תנועה של כמה ימים).
    """
    closes: dict = {}

    st = pd.read_sql(text("""
        SELECT expiry_date::date AS d, MAX(actual_index_close) AS close
        FROM condor_settled_detail
        WHERE actual_index_close IS NOT NULL
        GROUP BY expiry_date::date
    """), eng)
    for _, r in st.iterrows():
        closes[r["d"]] = float(r["close"])

    # גיבוי לפקיעות ישנות (expiry_history מסתיים 2026-05-07 — כרגע אין חפיפה).
    hist = pd.read_sql(text(
        "SELECT expiry_date::date AS d, expiry_price FROM expiry_history "
        "WHERE expiry_price IS NOT NULL"
    ), eng)
    for _, r in hist.iterrows():
        closes.setdefault(r["d"], float(r["expiry_price"]))
    return closes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last-only", action="store_true",
                    help="רק ה-snapshot האחרון לפני כל פקיעה (החלטה אחת לפקיעה)")
    args = ap.parse_args()

    eng = _engine()
    chain = _load_chain_history(eng)
    closes = _load_expiry_closes(eng)

    rows = []
    for (fd, exp), g in chain.groupby(["fetch_date", "expiry_date"]):
        exp_d = pd.to_datetime(exp).date()
        fd_d = pd.to_datetime(fd).date()
        days = (exp_d - fd_d).days
        if days <= 0:
            continue                      # snapshot ביום/אחרי הפקיעה — לא החלטה
        close = closes.get(exp_d)
        if close is None:
            continue                      # לא נסגרה → אין מול מה להשוות

        atm = find_atm(g)
        if not atm:
            continue
        base = float(atm.get("index_estimate") or atm.get("strike") or 0)
        if base <= 0:
            continue

        im = expected_move_pct(g, base, expiry_date=exp_d, as_of_date=fd_d)
        if im["skipped"]:
            continue

        # התנועה בפועל *מאותו snapshot* ועד הנעילה — אותו חלון בדיוק שה-straddle מתמחר.
        actual = (close - base) / base * 100.0

        rows.append({
            "snapshot": fd_d,
            "expiry": exp_d,
            "days": days,
            "index": round(base, 1),
            "close": round(close, 1),
            "expected_%": im["expected_move_pct"],
            "actual_abs_%": round(abs(actual), 4),
            "actual_%": round(actual, 4),
            "error": round(im["expected_move_pct"] - abs(actual), 4),
        })

    if not rows:
        print("אין זוגות (expected, actual) — אין חפיפה בין הארכיון לפקיעות שנסגרו.")
        return 1

    df = pd.DataFrame(rows).sort_values(["expiry", "days"])
    if args.last_only:
        df = df.sort_values("days").groupby("expiry", as_index=False).first().sort_values("expiry")

    pd.set_option("display.width", 160)
    print("=" * 96)
    print("מה השוק ציפה (ATM straddle) מול מה שקרה בפועל")
    print("=" * 96)
    print(df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    exp_v, act_v = df["expected_%"], df["actual_abs_%"]
    n = len(df)
    print("\n" + "=" * 96)
    print(f"n = {n} זוגות | {df['expiry'].nunique()} פקיעות | {df['snapshot'].nunique()} ימי snapshot")
    print(f"ציפייה ממוצעת : {exp_v.mean():.2f}%   (חציון {exp_v.median():.2f}%)")
    print(f"בפועל ממוצע   : {act_v.mean():.2f}%   (חציון {act_v.median():.2f}%)")
    bias = (exp_v - act_v).mean()
    print(f"הטיה ממוצעת   : {bias:+.2f} נק' אחוז  "
          f"({'השוק מתמחר יותר תנועה מהמציאות — פרמיית פחד' if bias > 0 else 'השוק מופתע — מתמחר פחות מדי'})")
    print(f"MAE           : {(exp_v - act_v).abs().mean():.2f} נק' אחוז")

    if n >= 3 and exp_v.std() > 0 and act_v.std() > 0:
        pear = exp_v.corr(act_v)
        # Spearman = Pearson על הדירוגים (בלי scipy — אינו מותקן).
        spear = exp_v.rank().corr(act_v.rank())
        print(f"\nמתאם Pearson  : {pear:+.3f}   ← האם ציפייה גבוהה מנבאת תנועה גדולה?")
        print(f"מתאם Spearman : {spear:+.3f}   (דירוגי — עמיד לחריגים)")
    else:
        print("\nמתאם: אין מספיק שונות/תצפיות.")

    print("\nפילוח לפי ימים-לפקיעה:")
    by = df.groupby("days").agg(n=("expiry", "size"), expected=("expected_%", "mean"),
                                actual=("actual_abs_%", "mean"), bias=("error", "mean"))
    print(by.to_string(float_format=lambda v: f"{v:.2f}"))

    print("\n" + "-" * 96)
    print("אזהרה: המדגם קטן ומכסה משטר-שוק אחד (5 שבועות). זה מבט ראשון, לא ולידציה.")
    print("אל תבנה כלל מסחר על הדאטה הזה — שלב א' נועד לצבור אותו.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
