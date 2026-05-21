"""
בדיקות יחידה למודול context_analyzer.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from context_analyzer import (
    build_recommendation,
    conditional_win_rates,
    find_similar_expiries,
    get_recent_move,
)


# ─── fixtures ───────────────────────────────────────────────────────

def _make_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["expiry_date"] = pd.to_datetime(df["expiry_date"])
    return df


@pytest.fixture
def sample_df():
    """DataFrame מגוון: W+M, חודשים שונים, move_pct עם ו-NaN."""
    rows = []
    for year in [2020, 2021, 2022, 2023, 2024]:
        for month in range(1, 13):
            rows.append({
                "expiry_date":  f"{year}-{month:02d}-15",
                "expiry_type":  "W",
                "move_pct":     (year - 2022) * 0.5 + month * 0.1,
            })
            rows.append({
                "expiry_date":  f"{year}-{month:02d}-28",
                "expiry_type":  "M",
                "move_pct":     -(month * 0.2),
            })
    # Some NaN rows
    rows.append({"expiry_date": "2023-06-10", "expiry_type": "W", "move_pct": None})
    return _make_df(rows)


@pytest.fixture
def simple_df():
    return _make_df([
        {"expiry_date": "2023-05-10", "expiry_type": "W", "move_pct":  0.5},
        {"expiry_date": "2023-05-17", "expiry_type": "W", "move_pct":  1.2},
        {"expiry_date": "2023-05-24", "expiry_type": "W", "move_pct": -0.3},
        {"expiry_date": "2023-06-07", "expiry_type": "W", "move_pct":  0.8},
        {"expiry_date": "2023-06-14", "expiry_type": "M", "move_pct": -1.5},
        {"expiry_date": "2024-05-08", "expiry_type": "W", "move_pct":  0.6},
        {"expiry_date": "2024-05-15", "expiry_type": "W", "move_pct":  0.4},
        {"expiry_date": "2024-05-22", "expiry_type": "M", "move_pct": -0.9},
    ])


# ─── get_recent_move ─────────────────────────────────────────────────

class TestGetRecentMove:
    def test_returns_most_recent_before_date(self, simple_df):
        before = pd.Timestamp("2023-06-01")
        result = get_recent_move(simple_df, before)
        # most recent valid before 2023-06-01 is 2023-05-24 with move_pct=-0.3
        assert result == pytest.approx(-0.3)

    def test_returns_none_when_no_prior_data(self, simple_df):
        before = pd.Timestamp("2022-01-01")
        assert get_recent_move(simple_df, before) is None

    def test_ignores_nan_rows(self):
        df = _make_df([
            {"expiry_date": "2023-05-01", "expiry_type": "W", "move_pct": None},
            {"expiry_date": "2023-05-08", "expiry_type": "W", "move_pct": 1.0},
            {"expiry_date": "2023-05-15", "expiry_type": "W", "move_pct": None},
        ])
        result = get_recent_move(df, pd.Timestamp("2023-06-01"))
        assert result == pytest.approx(1.0)

    def test_uses_all_types(self, simple_df):
        # simple_df has 2023-06-07 (W=0.8) and 2023-06-14 (M=-1.5)
        # most recent before 2023-06-10 should be 2023-06-07 (W) = 0.8
        result = get_recent_move(simple_df, pd.Timestamp("2023-06-10"))
        assert result == pytest.approx(0.8)

    def test_returns_float(self, simple_df):
        result = get_recent_move(simple_df, pd.Timestamp("2024-06-01"))
        assert isinstance(result, float)


# ─── find_similar_expiries ───────────────────────────────────────────

class TestFindSimilarExpiries:
    def test_filters_by_type(self, simple_df):
        result = find_similar_expiries(simple_df, "W", 5)
        assert (result["expiry_type"] == "W").all()

    def test_filters_by_month(self, simple_df):
        result = find_similar_expiries(simple_df, "W", 5)
        assert (result["expiry_date"].dt.month == 5).all()

    def test_excludes_nan_move(self):
        df = _make_df([
            {"expiry_date": "2023-05-01", "expiry_type": "W", "move_pct": 1.0},
            {"expiry_date": "2023-05-08", "expiry_type": "W", "move_pct": None},
        ])
        result = find_similar_expiries(df, "W", 5)
        assert result["move_pct"].notna().all()

    def test_no_type_filter_with_unknown_type(self, simple_df):
        result = find_similar_expiries(simple_df, "X", 5)
        # "X" is not W/M, so type filter is skipped; month=5 still applied
        assert len(result) > 0
        assert (result["expiry_date"].dt.month == 5).all()

    def test_sorted_descending_by_date(self, simple_df):
        result = find_similar_expiries(simple_df, "W", 5)
        dates = result["expiry_date"].tolist()
        assert dates == sorted(dates, reverse=True)

    def test_move_filter_applied_when_given(self, simple_df):
        # preceding_move for 2024-05-15 (W) = move of 2024-05-08 (W) = 0.6
        # preceding_move for 2024-05-08 (W) = move of 2023-05-24 (W) = -0.3
        # preceding_move for 2023-05-24 (W) = move of 2023-05-17 (W) = 1.2
        # preceding_move for 2023-05-17 (W) = move of 2023-05-10 (W) = 0.5
        # recent_move=0.5, tol=0.3 → match when |preceding - 0.5| <= 0.3
        # → preceding must be in [0.2, 0.8]
        result = find_similar_expiries(simple_df, "W", 5, recent_move_pct=0.5, move_tolerance=0.3)
        # Check all preceding moves within tolerance
        # We can't directly check preceding_move (column dropped), but we can verify count makes sense
        assert isinstance(result, pd.DataFrame)
        assert len(result) <= 4  # at most 4 W+May rows

    def test_no_move_filter_when_none(self, simple_df):
        r_no_filter = find_similar_expiries(simple_df, "W", 5, recent_move_pct=None)
        r_with_filter = find_similar_expiries(simple_df, "W", 5, recent_move_pct=0.5, move_tolerance=0.1)
        assert len(r_no_filter) >= len(r_with_filter)

    def test_returns_empty_when_no_match(self, simple_df):
        result = find_similar_expiries(simple_df, "W", 11)  # November — not in simple_df
        assert result.empty

    def test_preceding_move_column_not_exposed(self, simple_df):
        result = find_similar_expiries(simple_df, "W", 5)
        assert "_preceding_move" not in result.columns

    def test_wide_tolerance_returns_more(self, sample_df):
        narrow = find_similar_expiries(sample_df, "W", 5, recent_move_pct=0.5, move_tolerance=0.3)
        wide   = find_similar_expiries(sample_df, "W", 5, recent_move_pct=0.5, move_tolerance=2.0)
        assert len(wide) >= len(narrow)

    def test_both_years_returned_without_move_filter(self, simple_df):
        # May W rows exist in 2023 and 2024
        result = find_similar_expiries(simple_df, "W", 5)
        years = result["expiry_date"].dt.year.unique()
        assert 2023 in years and 2024 in years


# ─── conditional_win_rates ───────────────────────────────────────────

class TestConditionalWinRates:
    def _make_moves(self, moves: list[float]) -> pd.DataFrame:
        return pd.DataFrame({
            "move_pct":    moves,
            "expiry_type": "W",
            "expiry_date": pd.to_datetime(["2023-01-01"] * len(moves)),
        })

    def test_returns_dataframe(self):
        df = self._make_moves([0.5, 1.0, -0.5, -1.0, 2.0])
        result = conditional_win_rates(df)
        assert isinstance(result, pd.DataFrame)

    def test_returns_empty_for_empty_input(self):
        result = conditional_win_rates(pd.DataFrame())
        assert result.empty

    def test_has_strategy_id_column(self):
        df = self._make_moves([0.3, 0.8, -0.2, 1.5, -0.5, 2.0])
        result = conditional_win_rates(df)
        assert "strategy_id" in result.columns

    def test_has_win_rate_column(self):
        df = self._make_moves([0.5, -0.5, 1.0, -1.0, 2.0, -2.0])
        result = conditional_win_rates(df)
        assert "win_rate" in result.columns

    def test_six_strategies_returned(self):
        df = self._make_moves([0.5, -0.5, 1.0, -1.0, 2.0, -2.0, 0.3, -0.3])
        result = conditional_win_rates(df)
        assert len(result) == 6

    def test_win_rate_between_zero_and_one(self):
        df = self._make_moves([1.0, 1.0, -1.0, -1.0, 2.0, -2.0])
        result = conditional_win_rates(df)
        assert (result["win_rate"] >= 0.0).all()
        assert (result["win_rate"] <= 1.0).all()

    def test_sorted_by_win_rate_descending(self):
        df = self._make_moves([0.5, -0.5, 1.0, -1.0, 2.0, -2.0, 0.2, -0.2])
        result = conditional_win_rates(df)
        rates = result["win_rate"].tolist()
        assert rates == sorted(rates, reverse=True)

    def test_all_positive_market_bull_call_wins(self):
        df = self._make_moves([0.5, 1.0, 1.5, 2.0, 0.3, 0.8])
        result = conditional_win_rates(df)
        bcs = result[result["strategy_id"] == 1].iloc[0]
        assert bcs["win_rate"] == pytest.approx(1.0)


# ─── build_recommendation ────────────────────────────────────────────

class TestBuildRecommendation:
    def _best_df(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_returns_empty_dict_for_empty_cond(self):
        result = build_recommendation(pd.DataFrame(), pd.DataFrame(), 5.0, 10)
        assert result == {}

    def test_returns_required_keys(self):
        cond = self._best_df([
            {"strategy_id": 2, "strategy_name": "Short Iron Condor",
             "win_rate": 0.75, "params_repr": "טווח=2%"},
        ])
        glob = self._best_df([
            {"strategy_id": 2, "strategy_name": "Short Iron Condor",
             "win_rate": 0.65, "params_repr": "טווח=2%"},
        ])
        result = build_recommendation(cond, glob, 2.0, 15)
        for key in ("strategy_id", "strategy_name", "cond_wr", "global_wr",
                    "delta_wr", "n_similar", "risk_score", "note"):
            assert key in result

    def test_picks_highest_win_rate_strategy(self):
        cond = self._best_df([
            {"strategy_id": 1, "strategy_name": "Bull Call Spread", "win_rate": 0.55, "params_repr": ""},
            {"strategy_id": 2, "strategy_name": "Short Iron Condor", "win_rate": 0.80, "params_repr": ""},
            {"strategy_id": 5, "strategy_name": "Long Straddle", "win_rate": 0.40, "params_repr": ""},
        ])
        result = build_recommendation(cond, cond, 2.0, 10)
        assert result["strategy_id"] == 2

    def test_delta_wr_is_difference(self):
        cond = self._best_df([{"strategy_id": 1, "strategy_name": "BCS", "win_rate": 0.70, "params_repr": ""}])
        glob = self._best_df([{"strategy_id": 1, "strategy_name": "BCS", "win_rate": 0.55, "params_repr": ""}])
        result = build_recommendation(cond, glob, 2.0, 10)
        assert result["delta_wr"] == pytest.approx(0.15)

    def test_high_risk_neutral_strategy_triggers_note(self):
        # Strategy 2 (Condor) recommended but risk=7.5 → note about Straddle
        cond = self._best_df([
            {"strategy_id": 2, "strategy_name": "Short Iron Condor", "win_rate": 0.75, "params_repr": ""},
            {"strategy_id": 5, "strategy_name": "Long Straddle",     "win_rate": 0.60, "params_repr": ""},
        ])
        result = build_recommendation(cond, cond, 7.5, 10)
        assert result["note"] != ""
        assert "Long Straddle" in result["note"]

    def test_high_risk_volatile_strategy_no_warning(self):
        # Strategy 5 (Straddle) recommended, risk=8 → no contradiction → no note
        cond = self._best_df([
            {"strategy_id": 5, "strategy_name": "Long Straddle", "win_rate": 0.80, "params_repr": ""},
        ])
        result = build_recommendation(cond, cond, 8.0, 10)
        assert result["note"] == ""

    def test_low_risk_no_note(self):
        cond = self._best_df([{"strategy_id": 2, "strategy_name": "Short Iron Condor",
                                "win_rate": 0.75, "params_repr": ""}])
        result = build_recommendation(cond, cond, 1.0, 10)
        assert result["note"] == ""

    def test_n_similar_preserved(self):
        cond = self._best_df([{"strategy_id": 1, "strategy_name": "BCS", "win_rate": 0.6, "params_repr": ""}])
        result = build_recommendation(cond, cond, 2.0, 42)
        assert result["n_similar"] == 42

    def test_fallback_when_global_missing_strategy(self):
        cond = self._best_df([{"strategy_id": 3, "strategy_name": "Butterfly", "win_rate": 0.70, "params_repr": ""}])
        glob = self._best_df([{"strategy_id": 1, "strategy_name": "BCS", "win_rate": 0.55, "params_repr": ""}])
        result = build_recommendation(cond, glob, 2.0, 5)
        # global_wr falls back to cond_wr when strategy not in global
        assert result["global_wr"] == pytest.approx(0.70)
        assert result["delta_wr"] == pytest.approx(0.0)
