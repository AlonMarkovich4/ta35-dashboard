"""
מודול אסטרטגיות אופציות — 6 אסטרטגיות לניתוח פקיעות TA-35.

כל אסטרטגיה מממשת is_success(move_pct, params) → bool.
STRATEGY_GRID מכיל את כל טווחי הפרמטרים לחקירה (grid search).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# ────────────────────────────────────────────────────────────────────
#  profit_intensity — מדד עוצמה משלים ל-is_success
# ────────────────────────────────────────────────────────────────────
# is_success הוא בינארי; profit_intensity ∈ [0,1] מבחין בין אסטרטגיות
# שחולקות אותו תנאי ניצחון (למשל Iron Condor מול Butterfly — שתיהן
# "abs(move) < X" אך עוצמתן שונה). מבוסס move_pct בלבד, לינארי, clamp ל-[0,1].

# Bull Call Spread מגיע לעוצמה מלאה (1.0) בעלייה של +1.0%. נבחר כי תנועות
# פקיעה ב-TA-35 הן בדרך-כלל תת-1% (calm ≈0.6%, normal ≈1.4%), כך ש-+1% הוא
# מהלך שורי חזק שבו ה-spread קרוב לתקרת הרווח. ערך יחיד מכוונן.
_BCS_FULL_UP_PCT = 1.0


def _clamp01(x: float) -> float:
    """כולא ערך לטווח [0.0, 1.0]."""
    return max(0.0, min(1.0, float(x)))


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

    @abstractmethod
    def profit_intensity(self, move_pct: float, params: dict[str, Any] | None = None) -> float:
        """
        עוצמת רווח ב-[0,1] לפי move_pct — "כמה עמוק בתוך אזור הרווח" היה המהלך.

        מדד *משלים* ל-is_success (אינו מחליף אותו): is_success בינארי, ואילו
        profit_intensity מבחין בין אסטרטגיות בעלות תנאי ניצחון זהה. תמיד מוחזר [0,1].
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

    def profit_intensity(self, move_pct: float, params: dict[str, Any] | None = None) -> float:
        """0 בירידה או 0; עולה לינארית ל-1.0 בעלייה של _BCS_FULL_UP_PCT%."""
        if move_pct <= 0:
            return 0.0
        return _clamp01(move_pct / _BCS_FULL_UP_PCT)


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

    def profit_intensity(self, move_pct: float, params: dict[str, Any] | None = None) -> float:
        """1.0 ב-move=0, יורד לינארית ל-0 ב-|move|=width_pct (רחב → צונח לאט)."""
        p = params if params is not None else self.default_params
        width = p["width_pct"]
        if width <= 0:
            return 1.0 if move_pct == 0 else 0.0
        return _clamp01(1.0 - abs(move_pct) / width)


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

    def profit_intensity(self, move_pct: float, params: dict[str, Any] | None = None) -> float:
        """1.0 ב-move=0, יורד לינארית ל-0 ב-|move|=wing_pct (צר מ-IC → צונח מהר)."""
        p = params if params is not None else self.default_params
        wing = p["wing_pct"]
        if wing <= 0:
            return 1.0 if move_pct == 0 else 0.0
        return _clamp01(1.0 - abs(move_pct) / wing)


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

    def profit_intensity(self, move_pct: float, params: dict[str, Any] | None = None) -> float:
        """זהה ל-Call Butterfly (סימטרי על move_pct): 1.0 ב-0, 0 ב-|move|=wing_pct."""
        p = params if params is not None else self.default_params
        wing = p["wing_pct"]
        if wing <= 0:
            return 1.0 if move_pct == 0 else 0.0
        return _clamp01(1.0 - abs(move_pct) / wing)


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

    def profit_intensity(self, move_pct: float, params: dict[str, Any] | None = None) -> float:
        """0 עד |move|=min_move_pct, עולה לינארית ל-1.0 ב-|move|=2×min_move_pct."""
        p = params if params is not None else self.default_params
        m = p["min_move_pct"]
        if m <= 0:
            return 1.0 if abs(move_pct) > 0 else 0.0
        return _clamp01((abs(move_pct) - m) / m)   # 0 ב-m, 1.0 ב-2m


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

    def profit_intensity(self, move_pct: float, params: dict[str, Any] | None = None) -> float:
        """0 עד |move|=min_move_pct, עולה לינארית ל-1.0 ב-|move|=2.5×min_move_pct.

        מגיע לעוצמה מלאה רחוק יותר מ-Straddle (2.5× מול 2×) — כי האופציות OTM
        דורשות תנועה גדולה יותר כדי להגיע לרווח מלא.
        """
        p = params if params is not None else self.default_params
        m = p["min_move_pct"]
        if m <= 0:
            return 1.0 if abs(move_pct) > 0 else 0.0
        return _clamp01((abs(move_pct) - m) / (1.5 * m))   # 0 ב-m, 1.0 ב-2.5m


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
