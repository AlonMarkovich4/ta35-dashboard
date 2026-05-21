"""
מודול אסטרטגיות אופציות — 6 אסטרטגיות לניתוח פקיעות TA-35.

כל אסטרטגיה מממשת is_success(move_pct, params) → bool.
STRATEGY_GRID מכיל את כל טווחי הפרמטרים לחקירה (grid search).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# ────────────────────────────────────────────────────────────────────
#  Base class
# ────────────────────────────────────────────────────────────────────

class Strategy(ABC):
    """מחלקת בסיס לאסטרטגיית אופציות."""

    @property
    @abstractmethod
    def name(self) -> str:
        """שם האסטרטגיה באנגלית."""

    @property
    @abstractmethod
    def default_params(self) -> dict[str, Any]:
        """פרמטרים ברירת-מחדל של האסטרטגיה."""

    @abstractmethod
    def is_success(self, move_pct: float, params: dict[str, Any] | None = None) -> bool:
        """
        מחזיר True אם הפקיעה הסתיימה בניצחון עבור האסטרטגיה.

        move_pct — תנועת הפקיעה עם סימן: (פקיעה - בסיס) / בסיס * 100.
        params   — פרמטרים ספציפיים; אם None, משתמש ב-default_params.
        """

    def win_rate(self, moves: list[float], params: dict[str, Any] | None = None) -> float:
        """
        מחשב אחוז הצלחה על רשימת תנועות.

        מחזיר ערך בין 0.0 ל-1.0; 0.0 אם הרשימה ריקה.
        """
        p = params if params is not None else self.default_params
        if not moves:
            return 0.0
        return sum(1 for m in moves if self.is_success(m, p)) / len(moves)


# ────────────────────────────────────────────────────────────────────
#  Strategy 1 — Bull Call Spread
# ────────────────────────────────────────────────────────────────────

class BullCallSpread(Strategy):
    """
    Bull Call Spread — קנייה של Call ATM + מכירה של Call גבוה יותר.

    מנצחת בכל תנועה חיובית (move_pct > 0).
    הרוחב (width_pts) קובע את תקרת הרווח אך אינו משפיע על תנאי הניצחון
    בניתוח הסתברותי זה.
    """

    name = "Bull Call Spread"
    default_params: dict[str, Any] = {"width_pts": 30}

    def is_success(self, move_pct: float, params: dict[str, Any] | None = None) -> bool:
        """מנצחת אם move_pct > 0 (המדד עלה)."""
        return move_pct > 0


# ────────────────────────────────────────────────────────────────────
#  Strategy 2 — Short Iron Condor
# ────────────────────────────────────────────────────────────────────

class ShortIronCondor(Strategy):
    """
    Short Iron Condor — מכירת Call Spread + מכירת Put Spread בו-זמנית.

    מנצחת כאשר המדד נשאר בתוך הטווח: |move_pct| < width_pct.
    """

    name = "Short Iron Condor"
    default_params: dict[str, Any] = {"width_pct": 2.0}

    def is_success(self, move_pct: float, params: dict[str, Any] | None = None) -> bool:
        """מנצחת אם |move_pct| < width_pct (הפקיעה בתוך הטווח)."""
        p = params if params is not None else self.default_params
        return abs(move_pct) < p["width_pct"]


# ────────────────────────────────────────────────────────────────────
#  Strategy 3 — Long Call Butterfly
# ────────────────────────────────────────────────────────────────────

class LongCallButterfly(Strategy):
    """
    Long Call Butterfly — קנייה ATM Call + מכירת 2x Call גבוה + קנייה Call גבוה עוד יותר.

    מנצחת כאשר הפקיעה ממש ליד הסטרייק האמצעי: |move_pct| < wing_pct.
    wing_pct ≈ wing_pts / base_index * 100  (למשל 40 נקודות ≈ 1.0% ב-TA-35 כ-4000)
    """

    name = "Long Call Butterfly"
    default_params: dict[str, Any] = {"wing_pct": 1.0}

    def is_success(self, move_pct: float, params: dict[str, Any] | None = None) -> bool:
        """מנצחת אם |move_pct| < wing_pct (תנועה קטנה מרוחב הכנף)."""
        p = params if params is not None else self.default_params
        return abs(move_pct) < p["wing_pct"]


# ────────────────────────────────────────────────────────────────────
#  Strategy 4 — Long Put Butterfly
# ────────────────────────────────────────────────────────────────────

class LongPutButterfly(Strategy):
    """
    Long Put Butterfly — מבנה מראה של Call Butterfly, בנוי מ-Puts.

    תנאי ניצחון זהה: |move_pct| < wing_pct.
    """

    name = "Long Put Butterfly"
    default_params: dict[str, Any] = {"wing_pct": 1.0}

    def is_success(self, move_pct: float, params: dict[str, Any] | None = None) -> bool:
        """מנצחת אם |move_pct| < wing_pct (תנועה קטנה מרוחב הכנף)."""
        p = params if params is not None else self.default_params
        return abs(move_pct) < p["wing_pct"]


# ────────────────────────────────────────────────────────────────────
#  Strategy 5 — Long Straddle
# ────────────────────────────────────────────────────────────────────

class LongStraddle(Strategy):
    """
    Long Straddle — קנייה של ATM Call + ATM Put.

    מנצחת בתנועה חזקה בכל כיוון: |move_pct| > min_move_pct.
    min_move_pct מייצג את סף שיבור הפרמיה המשולמת.
    """

    name = "Long Straddle"
    default_params: dict[str, Any] = {"min_move_pct": 1.0}

    def is_success(self, move_pct: float, params: dict[str, Any] | None = None) -> bool:
        """מנצחת אם |move_pct| > min_move_pct (תנועה חזקה לכל כיוון)."""
        p = params if params is not None else self.default_params
        return abs(move_pct) > p["min_move_pct"]


# ────────────────────────────────────────────────────────────────────
#  Strategy 6 — Long Strangle
# ────────────────────────────────────────────────────────────────────

class LongStrangle(Strategy):
    """
    Long Strangle — קנייה של OTM Call + OTM Put.

    מנצחת בתנועה חזקה: |move_pct| > min_move_pct.
    הסף בדרך-כלל גבוה יותר מ-Straddle כי האופציות OTM דורשות תנועה גדולה יותר לשבור.
    """

    name = "Long Strangle"
    default_params: dict[str, Any] = {"min_move_pct": 1.5}

    def is_success(self, move_pct: float, params: dict[str, Any] | None = None) -> bool:
        """מנצחת אם |move_pct| > min_move_pct (תנועה גדולה, מרחק OTM)."""
        p = params if params is not None else self.default_params
        return abs(move_pct) > p["min_move_pct"]


# ────────────────────────────────────────────────────────────────────
#  Registry
# ────────────────────────────────────────────────────────────────────

STRATEGIES: dict[int, Strategy] = {
    1: BullCallSpread(),
    2: ShortIronCondor(),
    3: LongCallButterfly(),
    4: LongPutButterfly(),
    5: LongStraddle(),
    6: LongStrangle(),
}

STRATEGY_BY_NAME: dict[str, Strategy] = {s.name: s for s in STRATEGIES.values()}


# ────────────────────────────────────────────────────────────────────
#  Parameter grid
# ────────────────────────────────────────────────────────────────────
# ערכים לפי האפיון: CLAUDE.md + PROJECT_WORKPLAN.md
#
# Butterfly: 20/40/60/80 נקודות ≈ 0.5/1.0/1.5/2.0% ב-TA-35 כ-4000 נקודות

STRATEGY_GRID: dict[int, list[dict[str, Any]]] = {
    1: [{"width_pts": w} for w in (10, 20, 30, 50)],
    2: [{"width_pct": w} for w in (1.0, 1.5, 2.0, 2.5, 3.0)],
    3: [{"wing_pct": w} for w in (0.5, 1.0, 1.5, 2.0)],
    4: [{"wing_pct": w} for w in (0.5, 1.0, 1.5, 2.0)],
    5: [{"min_move_pct": m} for m in (0.5, 1.0, 1.5, 2.0)],
    6: [{"min_move_pct": m} for m in (0.5, 1.0, 1.5, 2.0)],
}


# ────────────────────────────────────────────────────────────────────
#  Public helpers
# ────────────────────────────────────────────────────────────────────

def get_strategy(strategy_id: int) -> Strategy:
    """
    מחזיר מופע אסטרטגיה לפי מספר (1–6).
    זורק ValueError אם המספר אינו חוקי.
    """
    if strategy_id not in STRATEGIES:
        raise ValueError(
            f"אסטרטגיה {strategy_id} לא קיימת. אפשרויות: {sorted(STRATEGIES)}"
        )
    return STRATEGIES[strategy_id]


def run_grid(moves: list[float], strategy_id: int) -> list[dict[str, Any]]:
    """
    מריץ את כל הפרמטרים בגריד עבור אסטרטגיה נתונה על רשימת תנועות.

    מחזיר רשימת dict ממוינת לפי win_rate יורד.
    כל dict מכיל את הפרמטרים + win_count + total + win_rate.
    """
    strategy = get_strategy(strategy_id)
    results: list[dict[str, Any]] = []
    for params in STRATEGY_GRID[strategy_id]:
        wins = sum(1 for m in moves if strategy.is_success(m, params))
        results.append(
            {
                "strategy": strategy.name,
                **params,
                "win_count": wins,
                "total": len(moves),
                "win_rate": wins / len(moves) if moves else 0.0,
            }
        )
    results.sort(key=lambda r: r["win_rate"], reverse=True)
    return results
