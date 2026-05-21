"""
בדיקות יחידה למודול strategies.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strategies import (
    BullCallSpread,
    LongCallButterfly,
    LongPutButterfly,
    LongStraddle,
    LongStrangle,
    ShortIronCondor,
    STRATEGIES,
    STRATEGY_BY_NAME,
    STRATEGY_GRID,
    get_strategy,
    run_grid,
)


# ────────────────────────────────────────────────────────────────────
#  Strategy 1 — Bull Call Spread
# ────────────────────────────────────────────────────────────────────

class TestBullCallSpread:
    s = BullCallSpread()

    def test_positive_move_wins(self):
        assert self.s.is_success(0.5) is True

    def test_large_positive_wins(self):
        assert self.s.is_success(3.76) is True

    def test_negative_move_loses(self):
        assert self.s.is_success(-0.5) is False

    def test_zero_move_loses(self):
        """תנועה אפס אינה עלייה — הפסד."""
        assert self.s.is_success(0.0) is False

    def test_params_ignored(self):
        """רוחב הספרד לא משפיע על תוצאה."""
        assert self.s.is_success(0.1, {"width_pts": 10}) is True
        assert self.s.is_success(0.1, {"width_pts": 50}) is True

    def test_default_params_keys(self):
        assert "width_pts" in self.s.default_params


# ────────────────────────────────────────────────────────────────────
#  Strategy 2 — Short Iron Condor
# ────────────────────────────────────────────────────────────────────

class TestShortIronCondor:
    s = ShortIronCondor()
    params_2 = {"width_pct": 2.0}

    def test_inside_range_wins(self):
        assert self.s.is_success(1.5, self.params_2) is True

    def test_negative_inside_range_wins(self):
        assert self.s.is_success(-1.5, self.params_2) is True

    def test_outside_range_loses(self):
        assert self.s.is_success(2.5, self.params_2) is False

    def test_exactly_at_boundary_loses(self):
        """גבול הטווח — strict inequality, לא ניצחון."""
        assert self.s.is_success(2.0, self.params_2) is False

    def test_zero_move_wins(self):
        assert self.s.is_success(0.0, self.params_2) is True

    def test_narrow_range(self):
        assert self.s.is_success(0.8, {"width_pct": 1.0}) is True
        assert self.s.is_success(1.1, {"width_pct": 1.0}) is False

    def test_default_params_used(self):
        assert self.s.is_success(1.9) is True  # < 2.0 default

    def test_default_params_keys(self):
        assert "width_pct" in self.s.default_params


# ────────────────────────────────────────────────────────────────────
#  Strategy 3 — Long Call Butterfly
# ────────────────────────────────────────────────────────────────────

class TestLongCallButterfly:
    s = LongCallButterfly()
    params_1 = {"wing_pct": 1.0}

    def test_tiny_move_wins(self):
        assert self.s.is_success(0.3, self.params_1) is True

    def test_negative_tiny_move_wins(self):
        assert self.s.is_success(-0.3, self.params_1) is True

    def test_large_move_loses(self):
        assert self.s.is_success(1.5, self.params_1) is False

    def test_exactly_at_wing_loses(self):
        """גבול הכנף — strict inequality."""
        assert self.s.is_success(1.0, self.params_1) is False

    def test_zero_move_wins(self):
        assert self.s.is_success(0.0, self.params_1) is True

    def test_wider_wing_allows_larger_moves(self):
        assert self.s.is_success(1.3, {"wing_pct": 1.5}) is True
        assert self.s.is_success(1.3, {"wing_pct": 1.0}) is False

    def test_default_params_keys(self):
        assert "wing_pct" in self.s.default_params


# ────────────────────────────────────────────────────────────────────
#  Strategy 4 — Long Put Butterfly
# ────────────────────────────────────────────────────────────────────

class TestLongPutButterfly:
    s = LongPutButterfly()
    params_1 = {"wing_pct": 1.0}

    def test_tiny_move_wins(self):
        assert self.s.is_success(0.4, self.params_1) is True

    def test_large_move_loses(self):
        assert self.s.is_success(2.0, self.params_1) is False

    def test_zero_move_wins(self):
        assert self.s.is_success(0.0, self.params_1) is True

    def test_call_and_put_butterfly_agree(self):
        """Call ו-Put Butterfly מניבים תוצאה זהה לאותם פרמטרים."""
        call_b = LongCallButterfly()
        put_b = LongPutButterfly()
        for move in (-2.0, -0.5, 0.0, 0.5, 1.0, 2.0):
            assert call_b.is_success(move, self.params_1) == put_b.is_success(move, self.params_1)

    def test_default_params_keys(self):
        assert "wing_pct" in self.s.default_params


# ────────────────────────────────────────────────────────────────────
#  Strategy 5 — Long Straddle
# ────────────────────────────────────────────────────────────────────

class TestLongStraddle:
    s = LongStraddle()
    params_1 = {"min_move_pct": 1.0}

    def test_large_positive_wins(self):
        assert self.s.is_success(2.0, self.params_1) is True

    def test_large_negative_wins(self):
        assert self.s.is_success(-2.0, self.params_1) is True

    def test_small_move_loses(self):
        assert self.s.is_success(0.5, self.params_1) is False

    def test_exactly_at_threshold_loses(self):
        """בדיוק בסף — strict inequality, לא ניצחון."""
        assert self.s.is_success(1.0, self.params_1) is False

    def test_zero_move_loses(self):
        assert self.s.is_success(0.0, self.params_1) is False

    def test_higher_threshold_harder_to_win(self):
        assert self.s.is_success(1.2, {"min_move_pct": 1.0}) is True
        assert self.s.is_success(1.2, {"min_move_pct": 1.5}) is False

    def test_default_params_keys(self):
        assert "min_move_pct" in self.s.default_params


# ────────────────────────────────────────────────────────────────────
#  Strategy 6 — Long Strangle
# ────────────────────────────────────────────────────────────────────

class TestLongStrangle:
    s = LongStrangle()
    params_15 = {"min_move_pct": 1.5}

    def test_large_move_wins(self):
        assert self.s.is_success(2.0, self.params_15) is True

    def test_large_negative_wins(self):
        assert self.s.is_success(-2.0, self.params_15) is True

    def test_small_move_loses(self):
        assert self.s.is_success(1.0, self.params_15) is False

    def test_exactly_at_threshold_loses(self):
        assert self.s.is_success(1.5, self.params_15) is False

    def test_strangle_threshold_gte_straddle_default(self):
        """Strangle דורש תנועה גדולה יותר מ-Straddle בברירת מחדל."""
        straddle = LongStraddle()
        strangle = LongStrangle()
        assert strangle.default_params["min_move_pct"] >= straddle.default_params["min_move_pct"]

    def test_default_params_keys(self):
        assert "min_move_pct" in self.s.default_params


# ────────────────────────────────────────────────────────────────────
#  win_rate helper
# ────────────────────────────────────────────────────────────────────

class TestWinRate:
    def test_all_wins(self):
        s = BullCallSpread()
        assert s.win_rate([0.5, 1.0, 2.0]) == pytest.approx(1.0)

    def test_all_losses(self):
        s = BullCallSpread()
        assert s.win_rate([-0.5, -1.0]) == pytest.approx(0.0)

    def test_half_wins(self):
        s = ShortIronCondor()
        moves = [0.5, 0.5, 3.0, 3.0]
        assert s.win_rate(moves, {"width_pct": 2.0}) == pytest.approx(0.5)

    def test_empty_list_returns_zero(self):
        s = LongStraddle()
        assert s.win_rate([]) == pytest.approx(0.0)

    def test_uses_default_params_when_none(self):
        s = ShortIronCondor()
        # default width_pct=2.0 → מנצח ב-1.0, מפסיד ב-3.0
        assert s.win_rate([1.0, 3.0]) == pytest.approx(0.5)


# ────────────────────────────────────────────────────────────────────
#  Registry
# ────────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_strategies_has_six_entries(self):
        assert len(STRATEGIES) == 6

    def test_all_ids_present(self):
        assert set(STRATEGIES.keys()) == {1, 2, 3, 4, 5, 6}

    def test_strategy_by_name_populated(self):
        assert len(STRATEGY_BY_NAME) == 6

    def test_names_match(self):
        for sid, strategy in STRATEGIES.items():
            assert strategy.name in STRATEGY_BY_NAME

    def test_get_strategy_returns_correct_type(self):
        assert isinstance(get_strategy(1), BullCallSpread)
        assert isinstance(get_strategy(2), ShortIronCondor)
        assert isinstance(get_strategy(3), LongCallButterfly)
        assert isinstance(get_strategy(4), LongPutButterfly)
        assert isinstance(get_strategy(5), LongStraddle)
        assert isinstance(get_strategy(6), LongStrangle)

    def test_get_strategy_invalid_raises(self):
        with pytest.raises(ValueError):
            get_strategy(0)
        with pytest.raises(ValueError):
            get_strategy(7)


# ────────────────────────────────────────────────────────────────────
#  STRATEGY_GRID
# ────────────────────────────────────────────────────────────────────

class TestStrategyGrid:
    def test_grid_has_six_strategies(self):
        assert set(STRATEGY_GRID.keys()) == {1, 2, 3, 4, 5, 6}

    def test_iron_condor_grid_count(self):
        assert len(STRATEGY_GRID[2]) == 5  # 1.0, 1.5, 2.0, 2.5, 3.0

    def test_butterfly_grid_count(self):
        assert len(STRATEGY_GRID[3]) == 4  # 0.5, 1.0, 1.5, 2.0
        assert len(STRATEGY_GRID[4]) == 4

    def test_straddle_strangle_grid_count(self):
        assert len(STRATEGY_GRID[5]) == 4
        assert len(STRATEGY_GRID[6]) == 4

    def test_grid_params_have_correct_keys(self):
        for params in STRATEGY_GRID[2]:
            assert "width_pct" in params
        for params in STRATEGY_GRID[3]:
            assert "wing_pct" in params
        for params in STRATEGY_GRID[5]:
            assert "min_move_pct" in params

    def test_iron_condor_widths_ascending(self):
        widths = [p["width_pct"] for p in STRATEGY_GRID[2]]
        assert widths == sorted(widths)

    def test_straddle_thresholds_ascending(self):
        thresholds = [p["min_move_pct"] for p in STRATEGY_GRID[5]]
        assert thresholds == sorted(thresholds)


# ────────────────────────────────────────────────────────────────────
#  run_grid
# ────────────────────────────────────────────────────────────────────

class TestRunGrid:
    # נתוני בדיקה: 10 תנועות מגוונות
    MOVES = [-3.0, -1.5, -0.8, -0.3, 0.0, 0.3, 0.8, 1.5, 2.5, 3.5]

    def test_returns_correct_number_of_results(self):
        results = run_grid(self.MOVES, 2)
        assert len(results) == len(STRATEGY_GRID[2])

    def test_result_has_required_keys(self):
        result = run_grid(self.MOVES, 2)[0]
        assert "strategy" in result
        assert "win_rate" in result
        assert "win_count" in result
        assert "total" in result

    def test_win_rate_between_zero_and_one(self):
        for sid in range(1, 7):
            for result in run_grid(self.MOVES, sid):
                assert 0.0 <= result["win_rate"] <= 1.0

    def test_win_count_consistent_with_win_rate(self):
        for result in run_grid(self.MOVES, 2):
            expected = result["win_count"] / result["total"]
            assert result["win_rate"] == pytest.approx(expected)

    def test_results_sorted_by_win_rate_descending(self):
        for sid in range(1, 7):
            rates = [r["win_rate"] for r in run_grid(self.MOVES, sid)]
            assert rates == sorted(rates, reverse=True)

    def test_bull_call_spread_win_rate_correct(self):
        # מתוך MOVES: חיוביים הם 0.3, 0.8, 1.5, 2.5, 3.5 → 5/10
        results = run_grid(self.MOVES, 1)
        for r in results:
            assert r["win_rate"] == pytest.approx(0.5)

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError):
            run_grid(self.MOVES, 99)

    def test_empty_moves_returns_zero_win_rate(self):
        results = run_grid([], 2)
        for r in results:
            assert r["win_rate"] == pytest.approx(0.0)
            assert r["win_count"] == 0

    def test_strategy_name_in_result(self):
        results = run_grid(self.MOVES, 3)
        assert all(r["strategy"] == "Long Call Butterfly" for r in results)
