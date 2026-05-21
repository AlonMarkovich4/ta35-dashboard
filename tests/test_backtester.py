"""
בדיקות יחידה למודול backtester.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from backtester import best_per_strategy, fmt_params, run_backtest
from strategies import STRATEGY_GRID


# ─── fixtures ───────────────────────────────────────────────────────

def _make_df(moves: list[float], expiry_type: str = "W", year: int = 2023) -> pd.DataFrame:
    """בונה DataFrame מינימלי שמחקה expiry_history."""
    return pd.DataFrame(
        {
            "move_pct":    moves,
            "expiry_type": expiry_type,
            "expiry_date": pd.to_datetime([f"{year}-01-01"] * len(moves)),
        }
    )


@pytest.fixture
def mixed_df():
    """DataFrame מגוון: עליות, ירידות, תנועות בגדלים שונים."""
    moves = [-3.0, -1.5, -0.8, -0.3, 0.0, 0.3, 0.8, 1.5, 2.5, 3.5]
    return _make_df(moves)


@pytest.fixture
def typed_df():
    """DataFrame עם שני סוגי פקיעה לבדיקת סינון."""
    rows_w = [{"move_pct": 0.5, "expiry_type": "W",
               "expiry_date": pd.Timestamp("2023-06-01")} for _ in range(6)]
    rows_m = [{"move_pct": -2.0, "expiry_type": "M",
               "expiry_date": pd.Timestamp("2023-06-01")} for _ in range(4)]
    return pd.DataFrame(rows_w + rows_m)


# ─── fmt_params ─────────────────────────────────────────────────────

class TestFmtParams:
    def test_width_pct(self):
        assert fmt_params({"width_pct": 2.0}) == "טווח=2%"

    def test_wing_pct(self):
        assert fmt_params({"wing_pct": 1.5}) == "כנף=1.5%"

    def test_min_move_pct(self):
        assert fmt_params({"min_move_pct": 1.0}) == "סף תנועה=1%"

    def test_width_pts(self):
        assert fmt_params({"width_pts": 30}) == "רוחב=30נק'"

    def test_unknown_key_passes_through(self):
        result = fmt_params({"foo": 5})
        assert "foo" in result
        assert "5" in result


# ─── run_backtest — structure ────────────────────────────────────────

class TestRunBacktestStructure:
    def test_returns_dataframe(self, mixed_df):
        result = run_backtest(mixed_df)
        assert isinstance(result, pd.DataFrame)

    def test_has_required_columns(self, mixed_df):
        result = run_backtest(mixed_df)
        for col in ("strategy_id", "strategy_name", "params_repr",
                    "param_value", "win_rate", "wins", "losses", "total"):
            assert col in result.columns, f"חסרה עמודה: {col}"

    def test_row_count_equals_total_grid_variants(self, mixed_df):
        expected = sum(len(v) for v in STRATEGY_GRID.values())
        assert len(run_backtest(mixed_df)) == expected

    def test_strategy_ids_present(self, mixed_df):
        result = run_backtest(mixed_df)
        assert set(result["strategy_id"].unique()) == {1, 2, 3, 4, 5, 6}

    def test_wins_plus_losses_equals_total(self, mixed_df):
        result = run_backtest(mixed_df)
        assert ((result["wins"] + result["losses"]) == result["total"]).all()

    def test_win_rate_between_zero_and_one(self, mixed_df):
        result = run_backtest(mixed_df)
        assert (result["win_rate"] >= 0.0).all()
        assert (result["win_rate"] <= 1.0).all()

    def test_total_equals_valid_rows(self, mixed_df):
        result = run_backtest(mixed_df)
        # 10 שורות, כולן עם move_pct תקין
        assert (result["total"] == 10).all()

    def test_nan_move_pct_excluded(self):
        df = _make_df([0.5, float("nan"), -0.5])
        result = run_backtest(df)
        # NaN מדולג — total=2
        assert (result["total"] == 2).all()


# ─── run_backtest — correctness ─────────────────────────────────────

class TestRunBacktestCorrectness:
    def test_bull_call_spread_win_rate(self):
        """Bull Call Spread: מנצח בתנועות חיוביות בלבד."""
        df = _make_df([1.0, 1.0, -1.0, -1.0])  # 50% חיוביות
        result = run_backtest(df)
        bcs = result[result["strategy_id"] == 1]
        assert bcs["win_rate"].tolist() == pytest.approx([0.5] * len(bcs))

    def test_iron_condor_narrow_vs_wide(self):
        """Condor רחב מנצח יותר מצר."""
        df = _make_df([0.5, 0.5, 2.5, 2.5])
        result = run_backtest(df)
        condor = result[result["strategy_id"] == 2].set_index("param_value")
        assert condor.loc[1.0, "win_rate"] == pytest.approx(0.5)   # רק ±0.5 בטווח
        assert condor.loc[3.0, "win_rate"] == pytest.approx(1.0)   # כולם בטווח

    def test_straddle_large_moves_win(self):
        """Straddle מנצח בתנועות גדולות."""
        df = _make_df([3.0, -3.0, 0.2, -0.2])
        result = run_backtest(df)
        straddle = result[result["strategy_id"] == 5]
        # עם סף=0.5%: 3.0 ו-3.0 ו-(-3.0) ו-(-3.0) — כל 4 מנצחים? לא, 0.2 ו-0.2-
        # 3.0 > 0.5 ✓, -3.0 > 0.5 ✓, 0.2 < 0.5 ✗, -0.2 < 0.5 ✗ → 2/4 = 0.5
        low_thresh = straddle[straddle["param_value"] == 0.5].iloc[0]
        assert low_thresh["win_rate"] == pytest.approx(0.5)

    def test_all_up_market_bull_call_wins_100pct(self):
        """בשוק עולה לחלוטין — Bull Call Spread מנצח תמיד."""
        df = _make_df([0.1, 0.5, 1.0, 2.0])
        result = run_backtest(df)
        bcs = result[result["strategy_id"] == 1]
        assert bcs["win_rate"].tolist() == pytest.approx([1.0] * len(bcs))

    def test_stagnant_market_condor_wins_100pct(self):
        """שוק קפוא — Condor רחב מנצח תמיד."""
        df = _make_df([0.0, 0.1, -0.1, 0.2])
        result = run_backtest(df)
        wide_condor = result[
            (result["strategy_id"] == 2) & (result["param_value"] == 3.0)
        ].iloc[0]
        assert wide_condor["win_rate"] == pytest.approx(1.0)


# ─── run_backtest — filters ──────────────────────────────────────────

class TestRunBacktestFilters:
    def test_filter_by_expiry_type_W(self, typed_df):
        """סינון ל-W — רק 6 שורות W, כולן move_pct=0.5 (חיובי)."""
        result = run_backtest(typed_df, expiry_type="W")
        assert (result["total"] == 6).all()
        bcs = result[result["strategy_id"] == 1].iloc[0]
        assert bcs["win_rate"] == pytest.approx(1.0)

    def test_filter_by_expiry_type_M(self, typed_df):
        """סינון ל-M — רק 4 שורות M, כולן move_pct=-2.0 (שלילי)."""
        result = run_backtest(typed_df, expiry_type="M")
        assert (result["total"] == 4).all()
        bcs = result[result["strategy_id"] == 1].iloc[0]
        assert bcs["win_rate"] == pytest.approx(0.0)

    def test_filter_by_year_from(self):
        rows = [
            {"move_pct": 1.0, "expiry_type": "W", "expiry_date": pd.Timestamp("2020-01-01")},
            {"move_pct": 1.0, "expiry_type": "W", "expiry_date": pd.Timestamp("2023-01-01")},
            {"move_pct": 1.0, "expiry_type": "W", "expiry_date": pd.Timestamp("2025-01-01")},
        ]
        df = pd.DataFrame(rows)
        result = run_backtest(df, year_from=2023)
        assert (result["total"] == 2).all()

    def test_filter_by_year_range(self):
        rows = [
            {"move_pct": 0.5, "expiry_type": "W", "expiry_date": pd.Timestamp(f"{y}-01-01")}
            for y in [2019, 2020, 2021, 2022, 2023]
        ]
        df = pd.DataFrame(rows)
        result = run_backtest(df, year_from=2020, year_to=2022)
        assert (result["total"] == 3).all()

    def test_no_filter_uses_all_rows(self, typed_df):
        result = run_backtest(typed_df)
        assert (result["total"] == 10).all()

    def test_empty_after_filter_returns_zero_rates(self):
        """סינון שמותיר אפס שורות — win_rate=0, total=0."""
        df = _make_df([1.0, 2.0], expiry_type="W", year=2023)
        result = run_backtest(df, expiry_type="M")
        assert (result["total"] == 0).all()
        assert (result["win_rate"] == 0.0).all()

    def test_custom_grid_subset(self, mixed_df):
        """grid מותאם — רק אסטרטגיה 2 עם פרמטר אחד."""
        mini_grid = {2: [{"width_pct": 2.0}]}
        result = run_backtest(mixed_df, strategy_grid=mini_grid)
        assert len(result) == 1
        assert result.iloc[0]["strategy_id"] == 2


# ─── best_per_strategy ───────────────────────────────────────────────

class TestBestPerStrategy:
    def test_returns_one_row_per_strategy(self, mixed_df):
        results = run_backtest(mixed_df)
        best = best_per_strategy(results)
        assert len(best) == 6
        assert set(best["strategy_id"].unique()) == {1, 2, 3, 4, 5, 6}

    def test_best_win_rate_is_maximum(self, mixed_df):
        results = run_backtest(mixed_df)
        best = best_per_strategy(results)
        for _, row in best.iterrows():
            sid = row["strategy_id"]
            max_wr = results[results["strategy_id"] == sid]["win_rate"].max()
            assert row["win_rate"] == pytest.approx(max_wr)

    def test_sorted_by_win_rate_descending(self, mixed_df):
        best = best_per_strategy(run_backtest(mixed_df))
        rates = best["win_rate"].tolist()
        assert rates == sorted(rates, reverse=True)

    def test_all_have_strategy_name(self, mixed_df):
        best = best_per_strategy(run_backtest(mixed_df))
        assert best["strategy_name"].notna().all()
        assert (best["strategy_name"] != "").all()
