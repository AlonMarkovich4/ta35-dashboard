"""
implied_move.py — "מדד הפחד" פר-פקיעה: התנועה שהשוק מתמחר, מתוך ה-straddle.

הרציונל: מנוע המרווח נשען על ההיסטוריה (מבט אחורה). מחיר ה-ATM straddle הוא מבט
קדימה — כמה תנועה השוק מתמחר *עד הפקיעה הזו*. זה יתרון על VTA35 החיצוני, שהוא
מדד יחיד ל-30 יום קבוע, בעוד שההחלטה שלנו היא פר-פקיעה (לרוב 1–7 ימים).

המודל: ב-ATM, מחיר ה-straddle ≈ התנועה המוחלטת הצפויה עד הפקיעה.
    expected_move_pct = (call + put) / index × 100
זו הקירוב הסטנדרטי ("straddle rule"): ה-straddle הוא בדיוק מה שמשלמים כדי לקבל
את |התנועה| בפקיעה, ולכן מחירו הוא ציפיית השוק ל-|התנועה| (בניכוי פרמיית סיכון).

**שלב א' — חישוב ותיעוד בלבד.** המודול לא משפיע על בחירת המרווח; הוא רק מחשב,
נשמר בכל המלצה, ומוצג. הכלל המשפיע ייבנה על הדאטה שיצטבר (היום יש 16 פקיעות עם
גם expected-move וגם תוצאה — רחוק מלהספיק).

מודול טהור: אפס DB, אפס UI. מקבל chain_df ומחזיר dict.

פונקציות ציבוריות:
  expected_move_pct(chain_df, base_index, expiry_date=None, as_of_date=None) → dict
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime

import pandas as pd

from payoff import MULTIPLIER

logger = logging.getLogger(__name__)

# עמודות ה-chain (אותו חוזה כמו margin_calculator / condor_legs_from_chain):
# strike, call_price, put_price — מחיר ב-₪ (נקודות = ₪ ÷ MULTIPLIER).
_REQUIRED = ("strike", "call_price", "put_price")


def _skipped(reason: str) -> dict:
    """תוצאה ריקה עם סיבה — לא קורסים, מתעדים למה אין expected move."""
    logger.debug("implied_move: דילוג — %s", reason)
    return {
        "skipped": True,
        "reason": reason,
        "atm_strike": None,
        "straddle_price_pts": None,
        "expected_move_pct": None,
        "expected_move_pts": None,
        "implied_daily_pct": None,
        "days_to_expiry": None,
        "atm_tradable": None,
        "atm_distance_pts": None,
    }


def _as_date(v):
    """date | datetime | 'YYYY-MM-DD' → date; None אם לא ניתן."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.to_datetime(v).date()
    except Exception:  # noqa: BLE001
        return None


def expected_move_pct(
    chain_df: "pd.DataFrame",
    base_index: float,
    expiry_date=None,
    as_of_date=None,
) -> dict:
    """התנועה שהשוק מתמחר לפקיעה, מתוך מחיר ה-ATM straddle.

    Parameters
    ----------
    chain_df   : שרשרת עם strike, call_price, put_price (מחיר ב-₪, כמו בכל המנוע).
    base_index : רמת המדד (מ-find_atm — put-call parity; ב-DB אין baserate).
    expiry_date, as_of_date : אופציונליים. כששניהם קיימים ו-expiry > as_of, מחושב
                 גם implied_daily_pct = expected_move / √days (scaling של √זמן).

    Returns
    -------
    dict:
      skipped            — True כשאי-אפשר לחשב (אז reason מסביר, השאר None).
      atm_strike         — הסטרייק ששימש (הקרוב ביותר למדד מבין ה*סחירים*).
      atm_tradable       — False אם ה-ATM הקרוב ביותר לא היה סחיר ונבחר אחר.
      atm_distance_pts   — |atm_strike − base_index| (נק'): כמה רחוק ה-ATM שנבחר.
      straddle_price_pts — (call + put) בנקודות.
      expected_move_pct  — straddle / index × 100. **התנועה הצפויה עד הפקיעה.**
      expected_move_pts  — אותה תנועה בנקודות מדד.
      implied_daily_pct  — expected_move / √days (None בלי תאריכים תקינים).
      days_to_expiry     — ימים קלנדריים (None בלי תאריכים).

    לא זורק: קלט פגום → dict עם skipped=True.
    """
    if chain_df is None or len(chain_df) == 0:
        return _skipped("שרשרת ריקה")

    missing = [c for c in _REQUIRED if c not in chain_df.columns]
    if missing:
        return _skipped(f"חסרות עמודות בשרשרת: {', '.join(missing)}")

    try:
        base = float(base_index)
    except (TypeError, ValueError):
        return _skipped("base_index לא מספרי")
    if not math.isfinite(base) or base <= 0:
        return _skipped("base_index לא חוקי (<= 0)")

    df = chain_df.copy()
    for c in _REQUIRED:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["strike"])
    if df.empty:
        return _skipped("אין strikes תקינים בשרשרת")

    # ה-straddle דורש *שני* הצדדים סחירים. סטרייק שבו רגל אחת חסרת מחיר אינו
    # שמיש: מחיר 0 אינו "אופציה חינם" אלא "אין ציטוט" — לספור אותו יעוות את
    # ה-straddle כלפי מטה ויציג שוק רגוע מהמציאות.
    tradable = df[(df["call_price"] > 0) & (df["put_price"] > 0)]
    if tradable.empty:
        return _skipped("אין סטרייק עם מחיר סחיר משני הצדדים (call ו-put)")

    # ה-ATM התיאורטי מול ה-ATM הסחיר בפועל — מתעדים אם נאלצנו להתרחק.
    nearest_any = df.iloc[(df["strike"] - base).abs().argmin()]
    row = tradable.iloc[(tradable["strike"] - base).abs().argmin()]

    atm_strike = float(row["strike"])
    atm_tradable = bool(float(nearest_any["strike"]) == atm_strike)

    straddle_nis = float(row["call_price"]) + float(row["put_price"])
    straddle_pts = straddle_nis / MULTIPLIER
    if straddle_pts <= 0:
        return _skipped("straddle לא חיובי")

    exp_move_pct = straddle_pts / base * 100.0

    # implied יומי — נורמליזציה ב-√זמן, כדי להשוות פקיעות באורכים שונים.
    days = None
    daily = None
    exp_d, asof_d = _as_date(expiry_date), _as_date(as_of_date)
    if exp_d is not None and asof_d is not None:
        d = (exp_d - asof_d).days
        if d > 0:
            days = d
            daily = exp_move_pct / math.sqrt(d)

    return {
        "skipped": False,
        "reason": None,
        "atm_strike": round(atm_strike, 2),
        "atm_tradable": atm_tradable,
        "atm_distance_pts": round(abs(atm_strike - base), 2),
        "straddle_price_pts": round(straddle_pts, 4),
        "expected_move_pct": round(exp_move_pct, 4),
        "expected_move_pts": round(straddle_pts, 4),
        "implied_daily_pct": round(daily, 4) if daily is not None else None,
        "days_to_expiry": days,
    }


def implied_vs_margin(expected_move: float | None, margin_pct: float | None) -> float | None:
    """היחס expected_move / margin_pct.

    > 1 → השוק מתמחר תנועה *גדולה מהמרווח* שנבחר: דגל אזהרה (המרווח עלול להישבר).
    < 1 → השוק שקט יחסית למרווח.
    None כשחסר נתון או margin=0 (אין חלוקה באפס).
    """
    if expected_move is None or margin_pct is None:
        return None
    try:
        m = float(margin_pct)
        e = float(expected_move)
    except (TypeError, ValueError):
        return None
    if m <= 0:
        return None
    return round(e / m, 4)
