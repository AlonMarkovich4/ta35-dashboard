"""
מודול backtest הסתברותי — מריץ את כל וריאנטי האסטרטגיות על פקיעות היסטוריות.

זרימת עבודה:
  DataFrame (expiry_history) → run_backtest() → DataFrame תוצאות
  results → best_per_strategy() → שורה אחת לכל אסטרטגיה (הפרמטר המיטבי)
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from strategies import STRATEGY_GRID, get_strategy

# תוויות עבריות לפרמטרים
_PARAM_LABELS: dict[str, tuple[str, str]] = {
    "width_pts": ("רוחב", "נק'"),
    "width_pct": ("טווח", "%"),
    "wing_pct":  ("כנף",  "%"),
    "min_move_pct": ("סף תנועה", "%"),
}


def fmt_params(params: dict[str, Any]) -> str:
    """
    מפרמט dict פרמטרים לתצוגה עברית קצרה.

    לדוגמה: {'width_pct': 2.0} → 'טווח=2.0%'
    """
    parts = []
    for k, v in params.items():
        label, unit = _PARAM_LABELS.get(k, (k, ""))
        val = int(v) if isinstance(v, float) and v == int(v) else v
        parts.append(f"{label}={val}{unit}")
    return ", ".join(parts)


def run_backtest(
    df: pd.DataFrame,
    strategy_grid: dict[int, list[dict[str, Any]]] | None = None,
    expiry_type: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> pd.DataFrame:
    """
    מריץ backtest הסתברותי על כל וריאנטי הפרמטרים לכל האסטרטגיות.

    Parameters
    ----------
    df           : DataFrame מ-expiry_history (חייב להכיל move_pct, expiry_type, expiry_date)
    strategy_grid: dict[strategy_id → list[params]]; None = STRATEGY_GRID המלא
    expiry_type  : "W" | "M" | None (הכל, כולל unknown)
    year_from    : שנה מינימלית (כולל); None = ללא הגבלה
    year_to      : שנה מקסימלית (כולל); None = ללא הגבלה

    Returns
    -------
    DataFrame עם שורה לכל וריאנט פרמטר:
      strategy_id | strategy_name | params_repr | param_value |
      win_rate | wins | losses | total
    ממוין לפי strategy_id, ואז לפי param_value.
    """
    grid = strategy_grid if strategy_grid is not None else STRATEGY_GRID

    # סינון שורות תקינות בלבד
    mask = df["move_pct"].notna()
    if expiry_type:
        mask &= df["expiry_type"] == expiry_type
    if year_from is not None:
        mask &= df["expiry_date"].dt.year >= year_from
    if year_to is not None:
        mask &= df["expiry_date"].dt.year <= year_to

    moves: list[float] = df.loc[mask, "move_pct"].tolist()
    total = len(moves)

    rows: list[dict[str, Any]] = []
    for strategy_id in sorted(grid):
        strategy = get_strategy(strategy_id)
        for params in grid[strategy_id]:
            wins = sum(1 for m in moves if strategy.is_success(m, params))
            # ערך מספרי ראשון לציר ה-X בגרפים
            param_value = float(next(iter(params.values()))) if params else 0.0
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": strategy.name,
                    "params_repr": fmt_params(params),
                    "param_value": param_value,
                    "win_rate": wins / total if total else 0.0,
                    "wins": wins,
                    "losses": total - wins,
                    "total": total,
                }
            )

    return pd.DataFrame(rows)


def best_per_strategy(results: pd.DataFrame) -> pd.DataFrame:
    """
    מחלץ את הוריאנט בעל ה-win_rate הגבוה ביותר לכל אסטרטגיה.

    בקשרת שוויון — שומר את השורה הראשונה (פרמטר קטן יותר, שמרני יותר).
    מחזיר DataFrame ממוין לפי win_rate יורד.
    """
    idx = results.groupby("strategy_id")["win_rate"].idxmax()
    return (
        results.loc[idx]
        .sort_values("win_rate", ascending=False)
        .reset_index(drop=True)
    )
