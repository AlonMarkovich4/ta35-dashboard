"""
margin_selector.py — בחירת רוחב ה-Short Iron Condor האופטימלי (מודול טהור, אפס UI/DB).

שלב 3 של מנגנון המרווח האופטימלי. מעל עקומת המרווח (שלב 1) והתפלגות התנועות (שלב 2),
מיישם את **עיקרון הבחירה**:

    "המרווח הצר ביותר שעומד בסף ביטחון — לא ה-EV המרבי, אלא עקביות."

כלומר: מרווח צר משלם פרמיה גבוהה יותר אך נשבר לעתים קרובות יותר; מרווח רחב עקבי אך
זול. הבחירה היא הצר-ביותר שה-hold המשוקלל שלו עדיין ≥ hold_floor. הגנה סטטיסטית
מהמדגם הקטן: ה-hold המותנה (מעט "שבועות דומים") משוקלל עם ה-hold הגלובלי (כל
ההיסטוריה מאותו סוג, שכולל את הימים הקיצוניים) — ומשקל המותנה מוקטן כשהמדגם קטן.

עקרונות:
  • אפס שכפול לוגיקה — ה-hold מגיע מ-move_distribution (התפלגות אמפירית + ±margin
    נומינלי), וההתניה עוטפת את context_analyzer.find_similar_expiries (ללא עונתיות).
  • טהור: מקבל DataFrame/עקומה, מחזיר נתונים. אפס גישה ל-DB, אפס UI.
  • ה-hold נמדד על **±margin_pct נומינלי** (לא על ה-strikes בפועל) — כדי שהבחירה תהיה
    עקבית עם הסימולציה ההיסטורית (margin_backtest), שבה אין שרשרת לפקיעות עבר.

API ציבורי:
  blended_hold_probability(df, margin_pct, expiry_type, recent_move_pct, tolerance=0.5,
                           weight_conditional=0.6, min_n=20, before_date=None) -> dict
  select_margin(margin_curve, df, expiry_type, recent_move_pct, hold_floor=0.97,
                tolerance=0.5, weight_conditional=0.6, min_n=20, before_date=None) -> dict
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from context_analyzer import find_similar_expiries
from move_distribution import build_move_distribution, hold_probability_at_margin

logger = logging.getLogger(__name__)

DEFAULT_WEIGHT_CONDITIONAL = 0.6   # משקל ברירת המחדל ל-hold המותנה בשקלול.
DEFAULT_MIN_N = 20                 # גודל מדגם מותנה שמתחתיו מקטינים את המשקל.
# סף הביטחון המשוקלל — ברירת המחדל הרשמית לבחירת המרווח.
# 0.97 נבחר מסריקת ספים על 768 פקיעות שבועיות (walk-forward, zero-lookahead): נקודת-הברך
# בין עקביות (שבירות ורצף-שבירות נמוכים) לרווח (פרמיה/שבוע) — סף גבוה יותר קונה עקביות
# בפרמיה מיותרת, נמוך יותר סופג שבירות. שחזור: margin_backtest.simulate_rule פר-סף.
DEFAULT_HOLD_FLOOR = 0.97


def _regime_conditioned_distribution(
    df: pd.DataFrame,
    expiry_type: str | None,
    recent_move_pct: Optional[float],
    tolerance: float,
    before_date=None,
) -> dict:
    """
    התפלגות תנועות מותנית-משטר: אותו סוג פקיעה, שהתנועה שקדמה להן דומה ל-recent_move_pct
    (±tolerance). וריאנט של find_similar_expiries **ללא רכיב העונתיות (החודש)** — למרווח
    (טווח) משטר התנודתיות רלוונטי יותר מהחודש הקלנדרי. zero-lookahead: אם before_date
    מסופק, נכללות רק פקיעות שלפניו (מסונן לפני חישוב הדמיון, עקבי עם build_expiry_decision).
    """
    gt = expiry_type if expiry_type in ("W", "M") else None
    work = df
    if before_date is not None and df is not None and "expiry_date" in df.columns:
        work = df[df["expiry_date"] < pd.Timestamp(before_date)]

    similar = find_similar_expiries(
        work, gt, target_month=None, recent_move_pct=recent_move_pct, move_tolerance=tolerance
    )
    return build_move_distribution(similar, expiry_type=None)   # similar כבר מסונן לפי סוג


def _blend(
    hold_conditional: Optional[float],
    hold_global: Optional[float],
    n_conditional: int,
    weight_conditional: float,
    min_n: int,
) -> tuple[Optional[float], float]:
    """
    מתמטיקת השקלול (טהורה) — מקור-אמת יחיד ל-blended_hold_probability ול-select_margin.

    w_effective = weight_conditional · min(1, n_conditional / min_n) — משקל המותנה מוקטן
    פרופורציונלית מתחת ל-min_n (הגנה מהמדגם הקטן). מקרי-קצה: אין מותנה → גלובלי בלבד
    (w=0); אין גלובלי → מותנה בלבד (w=1); שניהם None → (None, 0).
    מחזיר (hold_blended, w_effective).
    """
    shrink = min(1.0, n_conditional / min_n) if min_n > 0 else 0.0
    w_effective = round(weight_conditional * shrink, 4)

    if hold_conditional is None:
        return hold_global, 0.0
    if hold_global is None:
        return hold_conditional, 1.0
    hb = round(w_effective * hold_conditional + (1.0 - w_effective) * hold_global, 4)
    return hb, w_effective


def blended_hold_probability(
    df: pd.DataFrame,
    margin_pct: float,
    expiry_type: str | None,
    recent_move_pct: Optional[float],
    tolerance: float = 0.5,
    weight_conditional: float = DEFAULT_WEIGHT_CONDITIONAL,
    min_n: int = DEFAULT_MIN_N,
    before_date=None,
) -> dict:
    """
    הסתברות-החזקה משוקללת למרווח נתון — משלבת ראייה מותנית (משטר נוכחי) עם ראייה גלובלית.

    שני מקורות:
      • מותנה — hold על "שבועות דומים" (אותו סוג + תנועה קודמת דומה ל-recent_move_pct).
        רלוונטי למשטר הנוכחי, אך n קטן ולכן רועש.
      • גלובלי — hold על כל ההיסטוריה מאותו סוג. n גדול ויציב, כולל את הימים הקיצוניים.

    השקלול (ראה _blend):
        hold_blended = w_effective · hold_conditional + (1 − w_effective) · hold_global
        w_effective  = weight_conditional · min(1, n_conditional / min_n)

    כלומר n_conditional ≥ min_n → משקל מלא; n_conditional=10, min_n=20 → חצי משקל;
    n_conditional=0 → נשענים לגמרי על הגלובלי. ככל שיש פחות עדות מותנית — פחות אמון בה.

    Returns
    -------
    dict: margin_pct, hold_blended, hold_conditional, hold_global,
          n_conditional, n_global, w_effective.
    """
    global_dist = build_move_distribution(df, expiry_type=expiry_type, before_date=before_date)
    cond_dist = _regime_conditioned_distribution(
        df, expiry_type, recent_move_pct, tolerance, before_date
    )

    hold_global = hold_probability_at_margin(global_dist, margin_pct)
    hold_conditional = hold_probability_at_margin(cond_dist, margin_pct)
    n_conditional = int(cond_dist["n"])
    hold_blended, w_effective = _blend(
        hold_conditional, hold_global, n_conditional, weight_conditional, min_n
    )

    return {
        "margin_pct":       round(float(margin_pct), 4),
        "hold_blended":     hold_blended,
        "hold_conditional": hold_conditional,
        "hold_global":      hold_global,
        "n_conditional":    n_conditional,
        "n_global":         int(global_dist["n"]),
        "w_effective":      w_effective,
    }


def _build_reason(sel: dict, hold_floor: float, below_floor: bool) -> str:
    """נימוק עברי קצר לבחירה (או לאזהרה כשאף מרווח לא עמד בסף)."""
    hb = sel.get("hold_blended")
    hb_txt = "—" if hb is None else f"{hb:.0%}"
    if below_floor:
        return (
            f"⚠️ אף מרווח לא עמד בסף {hold_floor:.0%} — נבחר הרחב ביותר "
            f"({sel['margin_pct']:.2f}%, ביטחון משוקלל {hb_txt}) כהמלצה שמרנית מקסימלית. "
            f"שבוע חריג — שקול להימנע."
        )
    return (
        f"נבחר {sel['margin_pct']:.2f}% — הצר ביותר עם ביטחון משוקלל {hb_txt} "
        f"מעל סף {hold_floor:.0%}."
    )


def select_margin(
    margin_curve: list[dict],
    df: pd.DataFrame,
    expiry_type: str | None,
    recent_move_pct: Optional[float],
    hold_floor: float = DEFAULT_HOLD_FLOOR,
    tolerance: float = 0.5,
    weight_conditional: float = DEFAULT_WEIGHT_CONDITIONAL,
    min_n: int = DEFAULT_MIN_N,
    before_date=None,
) -> dict:
    """
    בוחר את המרווח האופטימלי מהגריד: **הצר ביותר שה-hold המשוקלל שלו ≥ hold_floor**.

    לכל מרווח תקין בעקומה מחושב hold משוקלל על ה-±margin הנומינלי. הבחירה: המרווח הצר
    ביותר (margin_pct נמוך) שעובר את הסף. אם **אף** מרווח לא עובר (שבוע חריג) — מוחזר
    הרחב ביותר עם below_floor=True (המלצה שמרנית מקסימלית + אזהרה).

    יעילות: שתי ההתפלגויות (גלובלית + מותנית) אינן תלויות ב-margin_pct, ולכן נבנות פעם
    אחת ומשמשות את כל הגריד (מתמטיקת השקלול משותפת דרך _blend).

    Parameters
    ----------
    margin_curve : פלט build_margin_curve (ואופציונלית מועשר ב-expected_value_curve כדי
                   ש-ev יעבור לשקיפות). שורות skipped=True מדולגות מהבחירה.
    df           : היסטוריית expiry_history (למקור ה-hold).
    hold_floor   : סף הביטחון המשוקלל (ברירת מחדל DEFAULT_HOLD_FLOOR=0.97 — נקודת-הברך
                   מסריקת ספים walk-forward על 768 פקיעות; ראה ההערה ליד הקבוע).
    (יתר הפרמטרים — כמו blended_hold_probability; before_date ל-zero-lookahead בסימולציה.)

    Returns
    -------
    dict:
      selected_margin — ה-margin_pct הנבחר (None אם אין מרווחים תקינים כלל).
      hold_blended, net_premium, ev, max_loss — של הנבחר (פרמיה/EV מהעקומה, לשקיפות).
      below_floor     — True אם אף מרווח לא עמד בסף (נבחר הרחב ביותר).
      hold_floor      — הסף ששימש.
      grid            — רשומת שקיפות לכל מרווח תקין: margin_pct, hold_blended,
                        hold_conditional, hold_global, n_conditional, n_global,
                        w_effective, net_premium, ev, max_loss.
      reason          — נימוק עברי.
    """
    # שתי ההתפלגויות — פעם אחת, לא פר-מרווח (חוסך ×len(grid) בנייה בסימולציה).
    global_dist = build_move_distribution(df, expiry_type=expiry_type, before_date=before_date)
    cond_dist = _regime_conditioned_distribution(
        df, expiry_type, recent_move_pct, tolerance, before_date
    )
    n_global = int(global_dist["n"])
    n_conditional = int(cond_dist["n"])

    grid: list[dict] = []
    for row in margin_curve:
        if row.get("skipped"):
            continue
        m = float(row["margin_pct"])
        hg = hold_probability_at_margin(global_dist, m)
        hc = hold_probability_at_margin(cond_dist, m)
        hb, w_eff = _blend(hc, hg, n_conditional, weight_conditional, min_n)
        grid.append({
            "margin_pct":       round(m, 4),
            "hold_blended":     hb,
            "hold_conditional": hc,
            "hold_global":      hg,
            "n_conditional":    n_conditional,
            "n_global":         n_global,
            "w_effective":      w_eff,
            "net_premium":      row.get("net_premium"),
            "ev":               row.get("ev"),
            "max_loss":         row.get("max_loss"),
        })

    grid.sort(key=lambda g: g["margin_pct"])   # הצר ביותר קודם

    if not grid:
        logger.warning("select_margin: אין מרווחים תקינים בעקומה — אין החלטה.")
        return {
            "selected_margin": None, "hold_blended": None, "net_premium": None,
            "ev": None, "max_loss": None, "below_floor": True, "hold_floor": hold_floor,
            "grid": [], "reason": "אין מרווחים תקינים בעקומה — לא ניתן לבחור.",
        }

    qualifying = [g for g in grid if g["hold_blended"] is not None and g["hold_blended"] >= hold_floor]
    if qualifying:
        sel, below_floor = qualifying[0], False    # grid ממוין עולה → הצר ביותר
    else:
        sel, below_floor = grid[-1], True          # הרחב ביותר

    return {
        "selected_margin": sel["margin_pct"],
        "hold_blended":    sel["hold_blended"],
        "net_premium":     sel["net_premium"],
        "ev":              sel["ev"],
        "max_loss":        sel["max_loss"],
        "below_floor":     below_floor,
        "hold_floor":      hold_floor,
        "grid":            grid,
        "reason":          _build_reason(sel, hold_floor, below_floor),
    }
