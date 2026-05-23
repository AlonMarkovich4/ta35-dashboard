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

from options_parser import find_atm

_TODAY = date.today  # callable — evaluated at call time, not import time

MULTIPLIER       = 50      # ₪ לנקודה — זהה ל-options_parser
_MIN_STRIKE      = 100.0
_MAX_PRICE_PTS   = 2000.0  # מחיר אופציה מקסימלי סביר בנקודות
_ATM_RANGE_PCT   = 0.20    # ±20% מרמת ה-ATM — מסנן OTM/ITM עמוק
_MIN_CHAIN_ROWS  = 3       # מינימום שורות תקינות כדי להחזיר שרשרת

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


def _raw_to_option_pts(v: float) -> float:
    """
    ממיר ערך גולמי מה-DB לנקודות — לשימוש בסינון outliers לפני נרמול מלא.

    ≤ 1000 → כבר בנקודות → ללא המרה
    > 1000 → כבר ₪        → ÷ MULTIPLIER → נקודות
    """
    abs_v = abs(v)
    if abs_v > 1000:
        return abs_v / MULTIPLIER
    return abs_v


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

    ATM נקבע לפי put-call parity: השורה שבה |call_price_nis - put_price_nis| מינימלי.
    מחזיר None אם אין חיבור DB, הטבלה ריקה, או שגיאה.
    """
    eng = _make_engine(engine)
    if eng is None:
        return None
    try:
        df_all = pd.read_sql(
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
                  AND (lastrate_call <> 0 OR lastrate_put <> 0)
            """),
            con=eng,
        )
        if df_all.empty:
            return None

        # נרמל לₓ כדי לזהות ATM לפי put-call parity
        call_nis = pd.to_numeric(df_all["lastrate_call"], errors="coerce").fillna(0.0).apply(_to_nis)
        put_nis  = pd.to_numeric(df_all["lastrate_put"],  errors="coerce").fillna(0.0).apply(_to_nis)

        # בחר שורות שבהן שני הצדדים פעילים; fallback לצד אחד
        both_active = (call_nis > 0) & (put_nis > 0)
        df_active = df_all[both_active] if both_active.any() else df_all[(call_nis > 0) | (put_nis > 0)]

        if df_active.empty:
            return None

        parity_dist = (call_nis.loc[df_active.index] - put_nis.loc[df_active.index]).abs()
        atm_idx = parity_dist.idxmin()

        return df_all.loc[atm_idx].to_dict()
    except Exception:
        return None


# ─── Public API ────────────────────────────────────────────────────────

def get_available_expiries(engine=None) -> list[str]:
    """
    מחזיר רשימת תאריכי פקיעה זמינים מ-tase_putcall (YYYY-MM-DD).

    מחזיר רק פקיעות עתידיות (expiry_date >= היום).
    אם אין פקיעות עתידיות — מחזיר את הפקיעה הכי קרובה לתאריך הנוכחי (fallback).
    מחזיר [] אם אין חיבור DB, הטבלה לא קיימת, או שגיאה.
    """
    eng = _make_engine(engine)
    if eng is None:
        return []
    try:
        today_str = _TODAY().isoformat()
        with eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT expiry_date FROM tase_putcall"
                " WHERE expiry_date >= :today ORDER BY expiry_date"
            ), {"today": today_str}).fetchall()
            future = [str(r[0]) for r in rows if r[0] is not None]
            if future:
                return future
            # fallback — nearest past expiry
            rows = conn.execute(text(
                "SELECT DISTINCT expiry_date FROM tase_putcall"
                " ORDER BY expiry_date DESC LIMIT 1"
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
            today_str = _TODAY().isoformat()
            rows = conn.execute(text(
                "SELECT DISTINCT expiry_date FROM tase_putcall"
                " WHERE expiry_date >= :today ORDER BY expiry_date"
            ), {"today": today_str}).fetchall()
            targets = [str(r[0]) for r in rows if r[0] is not None]
            if not targets:
                # fallback — nearest past expiry
                rows = conn.execute(text(
                    "SELECT DISTINCT expiry_date FROM tase_putcall"
                    " ORDER BY expiry_date DESC LIMIT 1"
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

            chain_df, drvtype_val, fetch_ts, baserate = result

            if latest_ts is None or fetch_ts > latest_ts:
                latest_ts = fetch_ts

            exp_dt   = pd.to_datetime(target)
            date_str = exp_dt.strftime("%d/%m/%Y")
            exp_type = _infer_expiry_type(drvtype_val, exp_dt.date())

            expiries.append({
                "date":        date_str,
                "expiry_type": exp_type,
                "chain":       chain_df,
                "baserate":    baserate,
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
    טוען שרשרת פקיעה אחת ומחיל סינון רב-שכבתי.

    מחזיר (DataFrame, drvtype, fetched_at, atm_level) או None אם הנתונים לא תקינים.
    None מוחזר גם אם נותרות פחות מ-_MIN_CHAIN_ROWS שורות לאחר הסינון.
    """
    latest_row = conn.execute(
        text("SELECT MAX(fetched_at) FROM tase_putcall WHERE expiry_date = :exp"),
        {"exp": target},
    ).fetchone()

    if not latest_row or latest_row[0] is None:
        return None

    fetch_ts = latest_row[0]

    # שלב 1: קרא ערכים גולמיים מה-DB — ללא המרה ב-SQL
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

    # סינון 1: שורות ללא מסחר — גם call וגם put אפס
    call_raw = pd.to_numeric(df_raw["call_price"], errors="coerce").fillna(0.0)
    put_raw  = pd.to_numeric(df_raw["put_price"],  errors="coerce").fillna(0.0)
    df_raw = df_raw[~((call_raw == 0.0) & (put_raw == 0.0))]

    if df_raw.empty:
        return None

    # סינון 2: שורות ללא דלתא — גם call_delta וגם put_delta אפס (אין מסחר אמיתי)
    cdelta_raw = pd.to_numeric(df_raw["call_delta"], errors="coerce").fillna(0.0)
    pdelta_raw = pd.to_numeric(df_raw["put_delta"],  errors="coerce").fillna(0.0)
    df_raw = df_raw[~((cdelta_raw == 0.0) & (pdelta_raw == 0.0))]

    if df_raw.empty:
        return None

    # סינון 3: ערכי מחיר חריגים — מעל _MAX_PRICE_PTS נקודות
    call_raw_u = pd.to_numeric(df_raw["call_price"], errors="coerce").fillna(0.0)
    put_raw_u  = pd.to_numeric(df_raw["put_price"],  errors="coerce").fillna(0.0)
    call_pts_raw = call_raw_u.apply(_raw_to_option_pts)
    put_pts_raw  = put_raw_u.apply(_raw_to_option_pts)
    df_raw = df_raw[~((call_pts_raw > _MAX_PRICE_PTS) | (put_pts_raw > _MAX_PRICE_PTS))]

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

    # שלב 3: זיהוי ATM לפי put-call parity (ייבוא מ-options_parser)
    atm_info = find_atm(df)
    if atm_info:
        atm_level = float(atm_info.get("index_estimate", atm_info.get("strike", df["strike"].mean())))
    else:
        atm_level = float(df["strike"].mean())

    # סינון 4: סטרייקים מחוץ ל-±_ATM_RANGE_PCT מרמת ה-ATM
    df = df[((df["strike"] - atm_level).abs() / atm_level) <= _ATM_RANGE_PCT]

    if len(df) < _MIN_CHAIN_ROWS:
        import warnings
        warnings.warn(
            f"נתוני Supabase לא תקינים לפקיעה {target} — "
            f"נותרו {len(df)} שורות בלבד (מינימום {_MIN_CHAIN_ROWS})",
            stacklevel=2,
        )
        return None

    df = df.reset_index(drop=True)
    df["call_pts"] = (df["call_price"] / MULTIPLIER).round(2)
    df["put_pts"]  = (df["put_price"]  / MULTIPLIER).round(2)

    return df, str(drvtype_val), fetch_ts, atm_level
