"""
supabase_loader.py — קריאת שרשרת אופציות מ-Supabase (טבלת tase_putcall).

מחזיר dict בפורמט זהה ל-parse_putvscall() כדי שהדשבורד ישתמש בו ללא שינוי.

### יחידות — DB vs options_parser

  עמודה DB (lastrate/highrate/lowrate)
  ├─ ערך ≤ 1000 → כבר בנקודות  → × MULTIPLIER  → ₪  (call_price)
  └─ ערך > 1000 → כבר בשקלים   → ללא המרה      → ₪  (call_price)

  עמודת delta (delta_call / delta_put)
  ├─ |δ| > 1   → סקלת אחוזים (0–100 / -100–0) → ÷ 100 → (-1, 1)
  └─ |δ| ≤ 1   → כבר דצימלי                   → ללא המרה

  calc: call_pts = call_price / MULTIPLIER  (₪ ÷ 50 → נקודות)

פונקציות ציבוריות:
  has_db()                             → bool
  get_sample_row(engine)               → dict | None  (שורה גולמית ATM לאבחון)
  get_available_expiries(engine)       → list[str]   (YYYY-MM-DD)
  get_latest_option_chain(expiry_date) → dict | None
"""
from __future__ import annotations

import calendar
import os
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

MULTIPLIER  = 50       # ₪ לנקודה — זהה ל-options_parser
_MIN_STRIKE = 100.0

# ─── DB connection ─────────────────────────────────────────────────────

def has_db() -> bool:
    """מחזיר True אם DATABASE_URL מוגדר בסביבה."""
    return bool(os.getenv("DATABASE_URL", ""))


def _make_engine(engine=None):
    """מחזיר engine קיים או יוצר חדש מ-DATABASE_URL; None אם לא מוגדר."""
    if engine is not None:
        return engine
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return None
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, echo=False)


# ─── Price / delta normalisation ───────────────────────────────────────

def _to_nis(v: float) -> float:
    """
    ממיר מחיר גולמי מה-DB ל-₪ לתאימות עם options_parser.

    ≤ 1000 → נקודות  → × MULTIPLIER → ₪
    > 1000 → כבר ₪   → ללא המרה
    """
    abs_v = abs(v)
    if abs_v > 1000:
        return float(v)           # already ₪
    return float(v) * MULTIPLIER  # points → ₪


def _to_decimal_delta(v: float) -> float:
    """
    ממיר דלתא גולמית ל-(-1, 1).

    |δ| > 1 → סקלת אחוזים → ÷ 100
    |δ| ≤ 1 → כבר דצימלי   → ללא המרה
    """
    if abs(v) > 1:
        return float(v) / 100.0
    return float(v)


def _norm_price_series(s: pd.Series) -> pd.Series:
    """מחיל _to_nis על Series, מטפל ב-NaN."""
    return pd.to_numeric(s, errors="coerce").fillna(0.0).apply(_to_nis)


def _norm_delta_series(s: pd.Series) -> pd.Series:
    """מחיל _to_decimal_delta על Series, מטפל ב-NaN."""
    return pd.to_numeric(s, errors="coerce").fillna(0.0).apply(_to_decimal_delta)


# ─── Expiry type inference ─────────────────────────────────────────────

def _infer_expiry_type(drvtype_val: str, expiry_dt: Optional[date]) -> str:
    """
    קובע אם פקיעה שבועית או חודשית.

    מנסה לקרוא מעמודת drvtype; אם לא ברור — מחשב לפי יום בחודש.
    יום שישי אחרון בחודש → חודשי; אחרת → שבועי.
    """
    v = str(drvtype_val or "").lower().strip()
    if any(k in v for k in ("weekly", "שבועי")) or v == "w":
        return "שבועי"
    if any(k in v for k in ("monthly", "חודשי")) or v == "m":
        return "חודשי"

    if expiry_dt:
        last_day    = calendar.monthrange(expiry_dt.year, expiry_dt.month)[1]
        last_dt     = date(expiry_dt.year, expiry_dt.month, last_day)
        days_back   = (last_dt.weekday() - 4) % 7  # 4 = Friday
        last_friday = last_dt - timedelta(days=days_back)
        if expiry_dt == last_friday:
            return "חודשי"

    return "שבועי"


# ─── Diagnostics ──────────────────────────────────────────────────────

def get_sample_row(engine=None) -> Optional[dict]:
    """
    מחזיר שורה גולמית ATM אחת מ-tase_putcall לאבחון — ערכים כמו שהם ב-DB.

    בוחר מה-fetch האחרון את השורה שה-strike שלה הכי קרוב ל-baserate_call.
    מחזיר None אם אין חיבור DB, הטבלה ריקה, או שגיאה.
    """
    eng = _make_engine(engine)
    if eng is None:
        return None
    try:
        df = pd.read_sql(
            text("""
                SELECT
                    expiry_date, fetched_at, drvtype,
                    expirationprice_call, expirationprice_put,
                    baserate_call,
                    lastrate_call,  lastrate_put,
                    highrate_call,  lowrate_call,
                    highrate_put,   lowrate_put,
                    delta_call,     delta_put,
                    overallturnoverunits_call, overallturnoverunits_put,
                    openpositions_call,        openpositions_put
                FROM tase_putcall
                WHERE fetched_at = (SELECT MAX(fetched_at) FROM tase_putcall)
                ORDER BY ABS(
                    COALESCE(expirationprice_call, expirationprice_put)
                    - COALESCE(baserate_call, 4500)
                )
                LIMIT 1
            """),
            con=eng,
        )
        if df.empty:
            return None
        return df.iloc[0].to_dict()
    except Exception:
        return None


# ─── Public API ────────────────────────────────────────────────────────

def get_available_expiries(engine=None) -> list[str]:
    """
    מחזיר רשימת תאריכי פקיעה זמינים מ-tase_putcall (YYYY-MM-DD).
    מחזיר [] אם אין חיבור DB, הטבלה לא קיימת, או שגיאה.
    """
    eng = _make_engine(engine)
    if eng is None:
        return []
    try:
        with eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT expiry_date FROM tase_putcall ORDER BY expiry_date"
            )).fetchall()
        return [str(r[0]) for r in rows if r[0] is not None]
    except Exception:
        return []


def get_latest_option_chain(
    expiry_date: Optional[str] = None,
    engine=None,
) -> Optional[dict]:
    """
    קורא שרשרת אופציות מ-Supabase ומחזיר dict בפורמט זהה ל-parse_putvscall().

    expiry_date — תאריך פקיעה (YYYY-MM-DD); None → כל הפקיעות הזמינות.
    מחזיר None אם אין חיבור DB, הטבלה ריקה, או שגיאה.
    """
    eng = _make_engine(engine)
    if eng is None:
        return None
    try:
        return _load_chains(eng, expiry_date)
    except Exception:
        return None


# ─── Internal helpers ──────────────────────────────────────────────────

def _load_chains(eng, expiry_date: Optional[str]) -> Optional[dict]:
    """מבצע את שאילתות ה-DB ובונה את ה-dict המוחזר."""
    with eng.connect() as conn:
        if expiry_date:
            targets = [expiry_date]
        else:
            rows    = conn.execute(text(
                "SELECT DISTINCT expiry_date FROM tase_putcall ORDER BY expiry_date"
            )).fetchall()
            targets = [str(r[0]) for r in rows if r[0] is not None]

        if not targets:
            return None

        expiries  = []
        latest_ts = None

        for target in targets:
            result = _load_one_expiry(eng, conn, target)
            if result is None:
                continue

            chain_df, drvtype_val, fetch_ts = result

            if latest_ts is None or fetch_ts > latest_ts:
                latest_ts = fetch_ts

            exp_dt   = pd.to_datetime(target)
            date_str = exp_dt.strftime("%d/%m/%Y")
            exp_type = _infer_expiry_type(drvtype_val, exp_dt.date())

            expiries.append({
                "date":        date_str,
                "expiry_type": exp_type,
                "chain":       chain_df,
            })

    if not expiries:
        return None

    try:
        as_of_str = pd.to_datetime(latest_ts).strftime("%d/%m/%Y")
    except Exception:
        as_of_str = str(latest_ts)[:10] if latest_ts else ""

    return {
        "as_of_date": as_of_str,
        "fetched_at": latest_ts,
        "expiries":   expiries,
    }


def _load_one_expiry(eng, conn, target: str):
    """
    טוען שרשרת פקיעה אחת.
    מחזיר (DataFrame, drvtype, fetched_at) או None אם אין נתונים.
    """
    latest_row = conn.execute(
        text("SELECT MAX(fetched_at) FROM tase_putcall WHERE expiry_date = :exp"),
        {"exp": target},
    ).fetchone()

    if not latest_row or latest_row[0] is None:
        return None

    fetch_ts = latest_row[0]

    # שלב 1: קרא ערכים גולמיים מה-DB — ללא המרה בSQL
    df_raw = pd.read_sql(
        text("""
            SELECT
                COALESCE(expirationprice_call, expirationprice_put) AS strike,
                lastrate_call   AS call_price,
                lastrate_put    AS put_price,
                delta_call      AS call_delta,
                delta_put       AS put_delta,
                openpositions_call          AS call_oi,
                openpositions_put           AS put_oi,
                overallturnoverunits_call   AS call_volume,
                overallturnoverunits_put    AS put_volume,
                highrate_call   AS call_high,
                lowrate_call    AS call_low,
                highrate_put    AS put_high,
                lowrate_put     AS put_low,
                drvtype
            FROM tase_putcall
            WHERE expiry_date = :exp AND fetched_at = :fetch
            ORDER BY COALESCE(expirationprice_call, expirationprice_put)
        """),
        con=eng,
        params={"exp": target, "fetch": fetch_ts},
    )

    if df_raw.empty:
        return None

    df_raw["strike"] = pd.to_numeric(df_raw["strike"], errors="coerce")
    df_raw = df_raw.dropna(subset=["strike"])
    df_raw = df_raw[df_raw["strike"] >= _MIN_STRIKE]

    if df_raw.empty:
        return None

    drvtype_val = (
        df_raw["drvtype"].dropna().iloc[0]
        if not df_raw["drvtype"].dropna().empty
        else ""
    )

    # שלב 2: נרמול — מחירים לₓ, דלתא לדצימלי
    price_cols = ["call_price", "put_price", "call_high", "call_low", "put_high", "put_low"]
    delta_cols = ["call_delta", "put_delta"]
    other_cols = ["call_oi", "put_oi", "call_volume", "put_volume"]

    df = df_raw[["strike"] + price_cols + delta_cols + other_cols].copy()

    for col in price_cols:
        df[col] = _norm_price_series(df[col])

    for col in delta_cols:
        df[col] = _norm_delta_series(df[col])

    for col in ["strike"] + other_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df = (
        df.drop_duplicates("strike")
          .sort_values("strike")
          .reset_index(drop=True)
    )
    df["call_pts"] = (df["call_price"] / MULTIPLIER).round(2)
    df["put_pts"]  = (df["put_price"]  / MULTIPLIER).round(2)

    return df, str(drvtype_val), fetch_ts
