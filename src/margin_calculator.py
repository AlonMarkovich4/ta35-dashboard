"""
margin_calculator.py — "מחשבון המרווחים" ל-Short Iron Condor (מודול טהור, אפס Streamlit).

שלב 1 של מנגנון המרווח האופטימלי. ממפה, לפקיעה נתונה, את *עקומת המרווח* כולה:
לכל מרווח בגריד — אילו strikes נבחרים, כמה פרמיה אמיתית מתקבלת, ומה ה-P&L בכל תרחיש.
זו הליבה שכל השלבים הבאים (הסתברות-החזקה, בחירת מרווח, ולידציה) ייבנו עליה.

עקרונות:
  • אפס שכפול לוגיקה — עוטף את payoff.condor_legs_from_chain (בחירת strikes + פרמיה)
    ואת payoff.payoff_iron_condor (נוסחת ה-P&L). לא ממציא מתמטיקה חדשה.
  • טהור: מקבל DataFrame + base_index, מחזיר נתונים. אפס גישה ל-DB, אפס UI.
  • ₪ לנקודה = payoff.MULTIPLIER (50). פרמיה/הפסד מוחזרים בשקלים.

API ציבורי:
  build_margin_curve(chain_df, base_index, margins=None, wing_pct=DEFAULT_WING_PCT) -> list[dict]
  margin_pnl(curve_row, move_pct) -> float
  summarize_curve(curve, hold_prob_fn=None) -> dict
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import pandas as pd

from payoff import (
    MULTIPLIER,
    condor_legs_from_chain,
    find_breakevens,
    payoff_iron_condor,
    price_range,
)

logger = logging.getLogger(__name__)

# מרחק הכנפיים (long) מעבר ל-short strikes, באחוזים — ברירת המחדל ההיסטורית של
# המערכת (payoff.py: short ±2%, wing ±3%, כלומר רוחב אנכי 1.0%). ראה תיעוד
# condor_legs_from_chain: wing_pct נמדד *מעבר ל-short*, לא מה-anchor.
DEFAULT_WING_PCT = 1.0

# רזולוציית גריד ה-P&L לחישוב max_loss ו-breakevens (טווח ±15% מכסה בבטחה
# כנפיים עד ~4% ומגיע לרמת ההפסד השטוחה שמעבר להן).
_PNL_RANGE_PCT = 0.15
_PNL_POINTS = 2000


def _default_margins() -> list[float]:
    """גריד ברירת המחדל: 1.0% עד 3.0% בקפיצות 0.25% — תשע נקודות."""
    return [round(1.0 + 0.25 * i, 2) for i in range(9)]


def _skipped_row(margin_pct: float, base_index: float, reason: str) -> dict:
    """שורת מרווח שדולגה (strikes לא זמינים/לא סחירים) — לא קורסים, מתעדים סיבה."""
    logger.debug("margin_calculator: דילוג על מרווח %.2f%% — %s", margin_pct, reason)
    return {
        "margin_pct": round(float(margin_pct), 4),
        "base_index": float(base_index),
        "skipped":    True,
        "reason":     reason,
    }


def _build_one_margin(
    chain_df: pd.DataFrame,
    base_index: float,
    margin_pct: float,
    wing_pct: float,
    smin: float,
    smax: float,
) -> dict:
    """בונה שורת עקומה אחת למרווח נתון; מחזיר dict עם skipped=True אם לא ניתן."""
    long_pct = margin_pct + wing_pct

    # שער 1 — "רחוק מדי": הכנף המבוקשת חורגת מטווח ה-strikes הזמינים בשרשרת.
    target_wing_up = base_index * (1 + long_pct / 100.0)
    target_wing_dn = base_index * (1 - long_pct / 100.0)
    if target_wing_up > smax or target_wing_dn < smin:
        return _skipped_row(
            margin_pct, base_index,
            f"כנף ±{long_pct:.2f}% מחוץ לטווח השרשרת ({smin:.0f}–{smax:.0f}) — רחוק מדי",
        )

    legs = condor_legs_from_chain(chain_df, base_index, short_pct=margin_pct,
                                  wing_pct=wing_pct, multiplier=MULTIPLIER)
    K_sp = legs["short_put"]["strike"]
    K_sc = legs["short_call"]["strike"]
    K_lp = legs["long_put"]["strike"]
    K_lc = legs["long_call"]["strike"]
    prices = (legs["short_put"]["price_pts"], legs["short_call"]["price_pts"],
              legs["long_put"]["price_pts"], legs["long_call"]["price_pts"])

    # שער 2 — "לא סחיר": לרגל כלשהי אין מחיר חיובי ב-chain.
    if any(p <= 0 for p in prices):
        return _skipped_row(margin_pct, base_index,
                            "רגל ללא מחיר סחיר (premium=0) — לא ניתן לתמחר")

    # שער 3 — "השרשרת לא נפרשת מספיק": strikes מתמוטטים / לא בסדר תקין.
    if not (K_lp < K_sp < K_sc < K_lc):
        return _skipped_row(
            margin_pct, base_index,
            f"strikes לא בסדר תקין ({K_lp:.0f}<{K_sp:.0f}<{K_sc:.0f}<{K_lc:.0f}) — "
            "השרשרת לא נפרשת מספיק",
        )

    credit_pts   = legs["credit_pts"]
    net_premium  = round(credit_pts * MULTIPLIER, 2)               # ₪ שהתקבלו
    wing_width   = round(K_lc - K_sc, 2)                           # רוחב אנכי (נק')

    # P&L מלא על טווח רחב — max_loss ו-breakevens דרך נוסחת ה-payoff הקיימת (DRY).
    S = price_range(base_index, pct=_PNL_RANGE_PCT, n=_PNL_POINTS)
    y = payoff_iron_condor(S, K_lp, K_sp, K_sc, K_lc, credit_pts, MULTIPLIER)
    max_loss = round(float(y.min()), 2)                            # ₪ (שלילי)

    bes = sorted(find_breakevens(S, y))
    if len(bes) >= 2:
        be_down_price, be_up_price = bes[0], bes[-1]
        breakeven_down_pct = round((base_index - be_down_price) / base_index * 100, 4)
        breakeven_up_pct   = round((be_up_price - base_index) / base_index * 100, 4)
    else:
        # מקרה מנוון (למשל credit ≥ רוחב הכנף → לעולם לא מפסיד) — אין BE ממשי.
        breakeven_down_pct = None
        breakeven_up_pct   = None

    ratio = round(net_premium / abs(max_loss), 4) if abs(max_loss) > 1e-9 else None

    return {
        "margin_pct":                round(float(margin_pct), 4),
        "base_index":                float(base_index),
        "skipped":                   False,
        "short_put_strike":          K_sp,
        "short_call_strike":         K_sc,
        "long_put_strike":           K_lp,
        "long_call_strike":          K_lc,
        "wing_pct":                  round(float(wing_pct), 4),
        "wing_width":                wing_width,
        "credit_pts":                round(credit_pts, 4),
        "net_premium":               net_premium,
        "max_loss":                  max_loss,
        "breakeven_down_pct":        breakeven_down_pct,
        "breakeven_up_pct":          breakeven_up_pct,
        "premium_to_max_loss_ratio": ratio,
    }


def build_margin_curve(
    chain_df: pd.DataFrame,
    base_index: float,
    margins: Optional[list[float]] = None,
    wing_pct: float = DEFAULT_WING_PCT,
) -> list[dict]:
    """
    ממפה את עקומת המרווח המלאה לפקיעה נתונה — שורה לכל מרווח בגריד.

    לכל מרווח (short_pct) נבחרים strikes אמיתיים מה-chain דרך condor_legs_from_chain,
    ומחושבים פרמיה, max_loss ונקודות breakeven — הכל מנתוני השוק בפועל.

    Parameters
    ----------
    chain_df   : שרשרת אופציות עם עמודות strike, call_price, put_price (מחיר ב-₪).
    base_index : רמת המדד הנוכחית — העוגן שממנו נמדדים אחוזי המרחק.
    margins    : רשימת מרחקי short באחוזים; None → גריד ברירת המחדל (1.0..3.0 ב-0.25).
    wing_pct   : מרחק הכנפיים מעבר ל-short, באחוזים (ברירת מחדל DEFAULT_WING_PCT=1.0).

    Returns
    -------
    list[dict], שורה לכל מרווח. שורה תקינה כוללת:
      margin_pct, base_index, skipped=False,
      short_put_strike, short_call_strike, long_put_strike, long_call_strike,
      wing_pct, wing_width (נק'), credit_pts (נק'), net_premium (₪),
      max_loss (₪, שלילי), breakeven_down_pct, breakeven_up_pct (תנועה % ששוברת כל צד),
      premium_to_max_loss_ratio.
    מרווח שאין לו strikes זמינים (רחוק מדי / לא סחיר / השרשרת צרה מדי) מוחזר כשורה
    {margin_pct, base_index, skipped=True, reason} — לא קורסים.
    """
    grid = margins if margins is not None else _default_margins()

    if chain_df is None or len(chain_df) == 0:
        logger.warning("build_margin_curve: שרשרת ריקה — כל המרווחים מדולגים.")
        return [_skipped_row(m, base_index, "שרשרת ריקה") for m in grid]

    smin = float(chain_df["strike"].min())
    smax = float(chain_df["strike"].max())

    return [
        _build_one_margin(chain_df, float(base_index), float(m), float(wing_pct), smin, smax)
        for m in grid
    ]


def margin_pnl(curve_row: dict, move_pct: float) -> float:
    """
    מחזיר את ה-P&L בשקלים של מרווח נתון בהינתן תנועת מדד בפועל (באחוזים, חתומה).

    עוטף את payoff_iron_condor הקיים (אותה נוסחת P&L של מסחר-הנייר) — אינו ממציא חדש.
    move_pct חיובי = עלייה, שלילי = ירידה; מחיר הסגירה = base_index × (1 + move_pct/100).

    בתוך הטווח (בין ה-short strikes) → רווח הפרמיה המלא; פריצה מעבר לכנף → ההפסד
    המקסימלי; בין ה-short לכנף → ערך ביניים לינארי.

    זורק ValueError אם השורה דולגה (אין לה strikes).
    """
    if curve_row.get("skipped"):
        raise ValueError(
            f"margin_pnl: אי אפשר לחשב P&L למרווח שדולג (margin_pct={curve_row.get('margin_pct')})"
        )
    base = float(curve_row["base_index"])
    close_index = base * (1.0 + move_pct / 100.0)
    pnl = payoff_iron_condor(
        close_index,
        curve_row["long_put_strike"], curve_row["short_put_strike"],
        curve_row["short_call_strike"], curve_row["long_call_strike"],
        curve_row["credit_pts"], MULTIPLIER,
    )
    return float(pnl)


def summarize_curve(
    curve: list[dict],
    hold_prob_fn: Optional[Callable[[dict], float]] = None,
) -> dict:
    """
    מסדר את עקומת המרווח ומצרף (אופציונלית) הסתברות-החזקה לכל מרווח.

    שלד לשלב 1: מחזיר את העקומה ממוינת לפי margin_pct עולה. אם ניתנה hold_prob_fn
    (נבנית בשלב 2 — הסתברות שהמדד יישאר בתוך הטווח) — היא מצורפת כשדה hold_prob לכל
    שורה תקינה (None לשורות שדולגו). **אין כאן לוגיקת בחירה** — הבחירה היא שלב 3.

    Returns
    -------
    dict עם:
      curve       — רשימת השורות ממוינת לפי margin_pct עולה (עם hold_prob אם סופקה fn).
      n_margins   — סך המרווחים בעקומה.
      n_available — כמה מרווחים תקינים (לא דולגו).
      n_skipped   — כמה דולגו.
    """
    ordered = sorted(curve, key=lambda r: r["margin_pct"])

    if hold_prob_fn is not None:
        for row in ordered:
            row["hold_prob"] = None if row.get("skipped") else hold_prob_fn(row)

    available = [r for r in ordered if not r.get("skipped")]
    return {
        "curve":       ordered,
        "n_margins":   len(ordered),
        "n_available": len(available),
        "n_skipped":   len(ordered) - len(available),
    }
