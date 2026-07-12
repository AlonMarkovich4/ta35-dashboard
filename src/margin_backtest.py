"""
margin_backtest.py — סימולציה היסטורית (walk-forward) של כלל בחירת המרווח (מודול טהור).

שלב 3, חלק ב — **מבחן הקבלה**. לכל פקיעה היסטורית, מדמה את ההחלטה שהכלל היה מקבל
*באותו רגע* (zero-lookahead מלא — רק העבר שלה), ובודק מול התנועה בפועל: החזיק או נשבר.
המדד המרכזי הוא **hold_rate** — אחוז השבועות שהחזיקו, כלומר העקביות.

מגבלה ידועה — אין פרמיות היסטוריות:
  הסימולציה הגיאומטרית סופרת החזקות/שבירות בלבד (זו העקביות, והיא מדויקת: |move| ≤ margin).
  ה-P&L המשוער מדווח **בנפרד** ובקירוב גלוי — עקומת הפרמיה **הנוכחית** מוחלת על תנועות
  העבר ("אילו הפרמיות היו כמו היום"). זו אינדיקציה לכיוון, לא אמת כספית.

עקרונות:
  • אפס שכפול לוגיקה — הבחירה דרך margin_selector.select_margin, ה-P&L דרך
    margin_calculator.margin_pnl, התנועה הקודמת דרך context_analyzer.get_recent_move.
  • טהור: מקבל DataFrame (+ עקומת ייחוס אופציונלית), מחזיר נתונים. אפס DB, אפס UI.

API ציבורי:
  simulate_rule(df, hold_floor, weight_conditional, expiry_type=None, reference_curve=None,
                tolerance=0.5, min_n=20) -> dict
  simulate_fixed_margin(df, fixed_margin, expiry_type=None, reference_curve=None) -> dict
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Callable, Optional

import pandas as pd

from context_analyzer import get_recent_move
from margin_calculator import _default_margins, margin_pnl
from margin_selector import (
    DEFAULT_MIN_N,
    DEFAULT_WEIGHT_CONDITIONAL,
    select_margin,
)

logger = logging.getLogger(__name__)

_PNL_NOTE = (
    "P&L משוער בקירוב 'אילו הפרמיות היו כמו היום' — עקומת הפרמיה הנוכחית מוחלת על "
    "תנועות העבר. אינדיקציה לעקביות/כיוון, לא אמת כספית."
)


def _nominal_curve(margins: Optional[list[float]] = None) -> list[dict]:
    """גריד מרווחים נומינלי (ללא שרשרת) — לבחירה כשאין עקומת ייחוס אמיתית."""
    grid = margins if margins is not None else _default_margins()
    return [{"margin_pct": float(m), "skipped": False,
             "net_premium": None, "ev": None, "max_loss": None} for m in grid]


def _ref_by_margin(reference_curve: Optional[list[dict]]) -> dict:
    """ממפה margin_pct → שורת עקומה תקינה (ל-margin_pnl של ה-P&L המשוער)."""
    if not reference_curve:
        return {}
    return {round(float(r["margin_pct"]), 4): r
            for r in reference_curve if not r.get("skipped")}


def _summarize(records: list[dict], has_pnl: bool, label: str) -> dict:
    """מסכם רצף החלטות walk-forward למדדי עקביות (+ P&L משוער אם יש עקומת ייחוס)."""
    n = len(records)
    if n == 0:
        return {
            "label": label, "n_expiries": 0, "hold_rate": None, "n_held": 0,
            "n_breaks": 0, "worst_break_move": None, "longest_break_streak": 0,
            "margin_distribution": {}, "est_pnl_total": None,
            "est_pnl_note": _PNL_NOTE if has_pnl else None,
        }

    n_held = sum(1 for r in records if r["held"])
    n_breaks = n - n_held
    breaks = [r for r in records if not r["held"]]
    worst_break_move = (round(max(abs(r["actual_move"]) for r in breaks), 4)
                        if breaks else None)

    # רצף השבירות הרצוף הארוך ביותר (בסדר כרונולוגי)
    longest = cur = 0
    for r in records:
        cur = cur + 1 if not r["held"] else 0
        longest = max(longest, cur)

    dist = dict(sorted(Counter(round(float(r["selected_margin"]), 4) for r in records).items()))

    est_pnl_total = None
    if has_pnl:
        vals = [r["est_pnl"] for r in records if r["est_pnl"] is not None]
        est_pnl_total = round(sum(vals), 2) if vals else None

    return {
        "label":                label,
        "n_expiries":           n,
        "hold_rate":            round(n_held / n, 4),
        "n_held":               n_held,
        "n_breaks":             n_breaks,
        "worst_break_move":     worst_break_move,
        "longest_break_streak": longest,
        "margin_distribution":  dist,
        "est_pnl_total":        est_pnl_total,
        "est_pnl_note":         _PNL_NOTE if has_pnl else None,
    }


def _run_walkforward(
    df: pd.DataFrame,
    expiry_type: str | None,
    choose_margin: Callable[[object, Optional[float]], Optional[float]],
    reference_curve: Optional[list[dict]],
    label: str,
) -> dict:
    """
    מריץ את הכלל כרונולוגית על כל פקיעה תקינה (מהמוקדמת למאוחרת), עם zero-lookahead:
    לכל פקיעה — choose_margin(before_date=תאריכה, recent_move=התנועה שקדמה לה) בוחר מרווח,
    ואז נבדק מול move_pct בפועל (|move| ≤ margin ⇒ החזיק). P&L משוער דרך margin_pnl על
    עקומת הייחוס (אם סופקה). מסכם דרך _summarize.
    """
    gt = expiry_type if expiry_type in ("W", "M") else None
    ref = _ref_by_margin(reference_curve)
    has_pnl = bool(ref)

    valid = df[df["move_pct"].notna()].copy()
    if gt:
        valid = valid[valid["expiry_type"] == gt]
    valid = valid.sort_values("expiry_date")   # כרונולוגי עולה

    records: list[dict] = []
    for _, row in valid.iterrows():
        exp_date = row["expiry_date"]
        actual_move = float(row["move_pct"])
        recent_move = get_recent_move(df, exp_date)     # zero-lookahead: רק לפני exp_date
        margin = choose_margin(exp_date, recent_move)
        if margin is None:
            continue
        margin = float(margin)
        est_pnl = None
        ref_row = ref.get(round(margin, 4))
        if ref_row is not None:
            est_pnl = margin_pnl(ref_row, actual_move)
        records.append({
            "expiry_date":     exp_date,
            "actual_move":     actual_move,
            "selected_margin": margin,
            "held":            abs(actual_move) <= margin,
            "est_pnl":         est_pnl,
        })

    return _summarize(records, has_pnl, label)


def simulate_rule(
    df: pd.DataFrame,
    hold_floor: float,
    weight_conditional: float = DEFAULT_WEIGHT_CONDITIONAL,
    expiry_type: str | None = None,
    reference_curve: Optional[list[dict]] = None,
    tolerance: float = 0.5,
    min_n: int = DEFAULT_MIN_N,
) -> dict:
    """
    סימולציית הכלל החכם: לכל פקיעה, select_margin עם before_date=תאריכה (רק העבר).

    reference_curve (אופציונלי) — עקומת המרווח הנוכחית (build_margin_curve): משמשת גם
    לגריד המרווחים לבחירה (עם פרמיות לשקיפות) וגם ל-P&L המשוער. None → גריד נומינלי
    (בחירה בלבד, ללא P&L).

    Returns — ראה _summarize: n_expiries, hold_rate, n_held, n_breaks, worst_break_move,
    longest_break_streak, margin_distribution, est_pnl_total, est_pnl_note, label.
    """
    grid_curve = reference_curve if reference_curve is not None else _nominal_curve()

    def choose(before_date, recent_move):
        sel = select_margin(
            grid_curve, df, expiry_type, recent_move, hold_floor,
            tolerance, weight_conditional, min_n, before_date,
        )
        return sel["selected_margin"]

    label = f"כלל חכם (floor={hold_floor:.0%}, w={weight_conditional})"
    return _run_walkforward(df, expiry_type, choose, reference_curve, label)


def simulate_fixed_margin(
    df: pd.DataFrame,
    fixed_margin: float,
    expiry_type: str | None = None,
    reference_curve: Optional[list[dict]] = None,
) -> dict:
    """
    בנצ'מרק: אותה סימולציה walk-forward אך עם מרווח קבוע (למשל 2.0% / 2.5% — המצב היום).
    כך אפשר לראות אם הכלל החכם באמת עדיף על "תמיד X%".
    """
    def choose(before_date, recent_move):
        return fixed_margin

    label = f"תמיד {fixed_margin:.2f}%"
    return _run_walkforward(df, expiry_type, choose, reference_curve, label)
