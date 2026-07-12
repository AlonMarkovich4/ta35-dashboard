"""
בדיקות יחידה לסימולציה ההיסטורית (margin_backtest) — שלב 3, חלק ב.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from margin_backtest import simulate_fixed_margin, simulate_rule
from margin_calculator import margin_pnl


# ─── fixtures ─────────────────────────────────────────────────────────────

def _weekly(moves: list[float], start="2020-01-06") -> pd.DataFrame:
    base = pd.Timestamp(start)
    rows = [{
        "expiry_date":  base + pd.Timedelta(weeks=i),
        "expiry_type":  "W",
        "move_pct":     mv,
        "abs_move_pct": abs(mv),
    } for i, mv in enumerate(moves)]
    return pd.DataFrame(rows)


# עקומת ייחוס אמיתית למרווח 2.0% (base=2000, כנפיים ±3%, credit=15 → max_loss −250).
_REF_2PCT = {
    "margin_pct": 2.0, "skipped": False, "base_index": 2000.0,
    "short_put_strike": 1960.0, "short_call_strike": 2040.0,
    "long_put_strike": 1940.0, "long_call_strike": 2060.0,
    "credit_pts": 15.0, "net_premium": 750.0, "max_loss": -250.0,
}


# ─── TestSimulateFixedMargin (בנצ'מרק — דטרמיניסטי) ────────────────────────

class TestSimulateFixedMargin:
    # [T, F, T, F, F, T] מול מרווח 2.0%: 0.5,3.0,0.5,4.0,4.5,0.5
    _df = _weekly([0.5, 3.0, 0.5, 4.0, 4.5, 0.5])

    def test_hold_rate_and_breaks(self):
        r = simulate_fixed_margin(self._df, 2.0, "W")
        assert r["n_expiries"] == 6
        assert r["n_held"] == 3
        assert r["n_breaks"] == 3
        assert r["hold_rate"] == pytest.approx(0.5)

    def test_worst_break_and_streak(self):
        r = simulate_fixed_margin(self._df, 2.0, "W")
        assert r["worst_break_move"] == pytest.approx(4.5)   # התנועה הגדולה ביותר ששברה
        assert r["longest_break_streak"] == 2                 # 4.0 ואז 4.5 ברצף

    def test_margin_distribution_is_all_fixed(self):
        r = simulate_fixed_margin(self._df, 2.0, "W")
        assert r["margin_distribution"] == {2.0: 6}

    def test_no_reference_curve_no_pnl(self):
        r = simulate_fixed_margin(self._df, 2.0, "W")
        assert r["est_pnl_total"] is None
        assert r["est_pnl_note"] is None

    def test_reference_curve_gives_estimated_pnl(self):
        r = simulate_fixed_margin(self._df, 2.0, "W", reference_curve=[_REF_2PCT])
        expected = round(sum(margin_pnl(_REF_2PCT, m) for m in [0.5, 3.0, 0.5, 4.0, 4.5, 0.5]), 2)
        assert r["est_pnl_total"] == pytest.approx(expected)
        assert "אילו הפרמיות היו כמו היום" in r["est_pnl_note"]

    def test_wider_margin_holds_more(self):
        # אותו דאטה, מרווח 5.0% → הכל מחזיק (max move 4.5 < 5.0).
        r = simulate_fixed_margin(self._df, 5.0, "W")
        assert r["hold_rate"] == pytest.approx(1.0)
        assert r["n_breaks"] == 0
        assert r["worst_break_move"] is None


# ─── TestSimulateRule ─────────────────────────────────────────────────────

class TestSimulateRule:
    def test_runs_and_reports_consistency_metrics(self):
        df = _weekly([0.5, 0.8, 1.2, 0.4, 2.5, 0.6, 0.5, 3.5, 0.7, 0.5] * 4)
        r = simulate_rule(df, hold_floor=0.90, weight_conditional=0.6, expiry_type="W")
        assert r["n_expiries"] == 40
        assert 0.0 <= r["hold_rate"] <= 1.0
        assert r["n_held"] + r["n_breaks"] == r["n_expiries"]
        assert sum(r["margin_distribution"].values()) == r["n_expiries"]

    def test_high_floor_is_more_conservative_than_low(self):
        # סף גבוה → נוטה למרווחים רחבים יותר → hold_rate לא נמוך יותר.
        df = _weekly([0.5, 0.8, 1.2, 0.4, 2.5, 0.6, 0.5, 3.5, 0.7, 0.5] * 4)
        strict = simulate_rule(df, hold_floor=0.98, weight_conditional=0.6, expiry_type="W")
        loose = simulate_rule(df, hold_floor=0.70, weight_conditional=0.6, expiry_type="W")
        assert strict["hold_rate"] >= loose["hold_rate"] - 1e-9


# ─── TestZeroLookahead (מבחן הקריטי — walk-forward) ────────────────────────

class TestZeroLookahead:
    def test_future_expiry_does_not_change_prefix_decisions(self):
        # הוספת פקיעה קיצונית *מאוחרת* אסור שתשנה את החלטות ה-prefix.
        # → סך ההחזקות/שבירות ב-prefix נשמר; ההפרש הוא בדיוק הפקיעה הנוספת (0/1).
        moves = [0.5, 0.8, 1.2, 0.4, 2.5, 0.6, 0.5, 0.7, 0.5, 0.9] * 3
        df_prefix = _weekly(moves)
        df_full = _weekly(moves + [9.0])   # פקיעה קיצונית מאוחרת יותר

        a = simulate_rule(df_prefix, 0.90, 0.6, "W")
        b = simulate_rule(df_full, 0.90, 0.6, "W")

        assert b["n_expiries"] == a["n_expiries"] + 1
        # ה-prefix נשמר: כל רכיב גדל ב-0 או 1 בלבד, והסך גדל בדיוק ב-1.
        assert (b["n_held"] - a["n_held"]) in (0, 1)
        assert (b["n_breaks"] - a["n_breaks"]) in (0, 1)
        assert (b["n_held"] + b["n_breaks"]) == (a["n_held"] + a["n_breaks"]) + 1
