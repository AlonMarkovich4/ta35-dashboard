"""
supabase_loader.py — קריאת שרשרת אופציות מ-Supabase (טבלת tase_putcall).

מחזיר dict בפורמט זהה ל-parse_putvscall() כדי שהדשבורד ישתמש בו ללא שינוי.

### יחידות — מה מגיע מה-DB לעומת מה מצפה options_parser.py

  tase_putcall DB            | options_parser chain
  ────────────────────────── | ─────────────────────────────────────
  lastrate_call  (int×100)   | call_price  [₪]   = lastrate / 100 * MULTIPLIER
  lastrate_put   (int×100)   | put_price   [₪]   = lastrate / 100 * MULTIPLIER
  highrate_call  (int×100)   | call_high   [₪]   = highrate / 100 * MULTIPLIER
  lowrate_call   (int×100)   | call_low    [₪]   = lowrate  / 100 * MULTIPLIER
  highrate_put   (int×100)   | put_high    [₪]   = highrate / 100 * MULTIPLIER
  lowrate_put    (int×100)   | put_low     [₪]   = lowrate  / 100 * MULTIPLIER
  expirationprice_call (int) | strike             = ללא המרה
  delta_call / delta_put     | call_delta / put_delta  = ללא המרה (0–100 scale)
  overallturnoverunits_*     | call_volume / put_volume = ללא המרה
  openpositions_*            | call_oi / put_oi         = ללא המרה

  חישוב: call_pts = call_price / MULTIPLIER
  → (lastrate / 100 * MULTIPLIER) / MULTIPLIER = lastrate / 100  ✓

פונקציות ציבוריות:
  has_db()                             → bool
  get_sample_row(engine)               → dict | None  (אבחון — שורה גולמית אחת)
  get_available_expiries(engine)       → list[str]  (תאריכים YYYY-MM-DD)
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
    מחזיר שורה גולמית אחת מ-tase_putcall לאבחון — ערכים כמו שהם ב-DB.

    שימושי לאימות פורמט מחירים (int×100? float? agorot?).
    מחזיר None אם אין חיבור DB או שהטבלה ריקה.
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
                    lastrate_call, lastrate_put,
                    highrate_call, lowrate_call,
                    highrate_put,  lowrate_put,
                    delta_call, delta_put,
                    overallturnoverunits_call, overallturnoverunits_put,
                    openpositions_call, openpositions_put
                FROM tase_putcall
                ORDER BY fetched_at DESC
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
    מחזיר רשימת תאריכי פקיעה זמינים מ-tase_putcall (פורמט YYYY-MM-DD).
    מחזיר [] אם אין חיבור DB, הטבלה לא קיימת, או שגיאה אחרת.
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

    expiry_date — תאריך פקיעה (YYYY-MM-DD); אם None — מביא את כל הפקיעות הזמינות.
    מחזיר None אם אין חיבור DB, הטבלה ריקה, או אירעה שגיאה.

    מבנה החזרה:
        {
          'as_of_date':  str,       # DD/MM/YYYY (תאריך fetch)
          'fetched_at':  Any,       # timestamp מקורי לתצוגת "עודכן לאחרונה"
          'expiries': [
            {
              'date':        str,   # DD/MM/YYYY
              'expiry_type': str,   # 'שבועי' / 'חודשי'
              'chain':       pd.DataFrame
            }
          ]
        }
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


# המרת מחיר: DB מאחסן lastrate/highrate/lowrate כ-int×100 (centi-points).
# חלוקה ב-100.0 מחזירה נקודות; כפל ב-MULTIPLIER מחזיר ₪ לתאימות options_parser.
# קיצור: lastrate / 100 * MULTIPLIER = lastrate * 0.5
_RATE_TO_NIS = f"/ 100.0 * {MULTIPLIER}"


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

    # המרת מחירים: DB int×100 (centi-points) → נקודות → ₪
    # לדוגמה: lastrate_call=1050 → 10.50 נקודות → 525 ₪
    df_raw = pd.read_sql(
        text(f"""
            SELECT
                COALESCE(expirationprice_call, expirationprice_put)
                                                          AS strike,
                lastrate_call  {_RATE_TO_NIS}             AS call_price,
                lastrate_put   {_RATE_TO_NIS}             AS put_price,
                delta_call                                AS call_delta,
                delta_put                                 AS put_delta,
                openpositions_call                        AS call_oi,
                openpositions_put                         AS put_oi,
                overallturnoverunits_call                 AS call_volume,
                overallturnoverunits_put                  AS put_volume,
                highrate_call  {_RATE_TO_NIS}             AS call_high,
                lowrate_call   {_RATE_TO_NIS}             AS call_low,
                highrate_put   {_RATE_TO_NIS}             AS put_high,
                lowrate_put    {_RATE_TO_NIS}             AS put_low,
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

    df_raw = df_raw.dropna(subset=["strike"])
    df_raw = df_raw[pd.to_numeric(df_raw["strike"], errors="coerce") >= _MIN_STRIKE]

    if df_raw.empty:
        return None

    drvtype_val = (
        df_raw["drvtype"].dropna().iloc[0]
        if not df_raw["drvtype"].dropna().empty
        else ""
    )

    num_cols = [
        "strike",
        "call_price", "put_price",
        "call_delta",  "put_delta",
        "call_oi",     "put_oi",
        "call_volume", "put_volume",
        "call_high",   "call_low",
        "put_high",    "put_low",
    ]
    df = df_raw[num_cols].copy()
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df = (
        df.drop_duplicates("strike")
          .sort_values("strike")
          .reset_index(drop=True)
    )
    df["call_pts"] = (df["call_price"] / MULTIPLIER).round(2)
    df["put_pts"]  = (df["put_price"]  / MULTIPLIER).round(2)

    return df, str(drvtype_val), fetch_ts
