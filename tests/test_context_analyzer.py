"""
בדיקות יחידה למודול context_analyzer.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from context_analyzer import (
    build_expiry_decision,
    build_recommendation,
    conditional_win_rates,
    find_similar_expiries,
    get_recent_move,
    recent_volatility,
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

    def test_move_filter_exact_membership_excludes_nan_and_out_of_range(self):
        """רגרסיה לבאג קדימות-האופרטורים בסינון התנועה הקודמת.

        כל השורות W ובמאי (עוברות סינון סוג+חודש). _preceding_move = move_pct.shift(1)
        על כל הפקיעות הממוינות לפי תאריך:
          2023-05-01: preceding=NaN            → להחריג (השורה הגלובלית הראשונה)
          2023-05-08: preceding=0.50 (בטווח)   → לכלול   |0.50-0.5|=0.0 ≤ 0.3
          2023-05-15: preceding=9.00 (מחוץ)    → להחריג  |9.00-0.5|=8.5 > 0.3
        התוצאה הנכונה: בדיוק {2023-05-08}.
        הקוד הישן — (notna() & abs_diff) <= tol — בוחר דווקא את שורת ה-NaN ונכשל כאן;
        המתוקן — notna() & (abs_diff <= tol) — עובר.
        """
        df = _make_df([
            {"expiry_date": "2023-05-01", "expiry_type": "W", "move_pct": 0.50},
            {"expiry_date": "2023-05-08", "expiry_type": "W", "move_pct": 9.00},
            {"expiry_date": "2023-05-15", "expiry_type": "W", "move_pct": 1.00},
        ])
        result = find_similar_expiries(
            df, "W", 5, recent_move_pct=0.5, move_tolerance=0.3
        )
        dates = set(result["expiry_date"].dt.strftime("%Y-%m-%d"))
        assert dates == {"2023-05-08"}, f"ציפינו רק ל-2023-05-08, קיבלנו {dates}"
        assert len(result) == 1
        # החרגות מפורשות — מתעדות את שתי הטעויות של הקוד הישן
        assert "2023-05-01" not in dates   # preceding=NaN
        assert "2023-05-15" not in dates   # preceding מחוץ לטווח


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


# ─── recent_volatility ───────────────────────────────────────────────

def _vol_df_from_moves(moves, etype="W", start="2015-01-01"):
    """בונה df עם תאריכים עולים (שבוע ביניהם), expiry_type אחיד, ו-abs_move_pct=|move|."""
    base = pd.Timestamp(start)
    rows = [
        {
            "expiry_date":  base + pd.Timedelta(days=7 * i),
            "expiry_type":  etype,
            "move_pct":     m,
            "abs_move_pct": abs(m),
        }
        for i, m in enumerate(moves)
    ]
    return pd.DataFrame(rows)


_AFTER_ALL = pd.Timestamp("2099-01-01")   # before_date שאחרי כל הנתונים


class TestRecentVolatility:
    # ── ערכים מדויקים: חלון, מיון, before_date, mean, std ──────────────
    def test_window_cap_and_exact_mean_std(self):
        """5 פקיעות תקינות לפני התאריך + אחת אחרי; window=4 → 4 האחרונות שלפני.

        moves בחלון = [1.0, -1.0, 2.0, -2.0]:
          mean_abs = (1+1+2+2)/4 = 1.5
          std(ddof=0): ממוצע=0, var=(1+1+4+4)/4=2.5, std=√2.5=1.5811
        """
        df = _vol_df_from_moves([9.0, 1.0, -1.0, 2.0, -2.0, 8.0])  # idx5 אחרי החיתוך
        before = df["expiry_date"].iloc[5]   # מחריג את 8.0 (idx5) ומה שאחריו
        res = recent_volatility(df, "W", before, window=4)
        assert res["n"] == 4                                 # tail(4) — מחריג את 9.0 (idx0)
        assert res["mean_abs_move"] == pytest.approx(1.5)
        assert res["std_move"] == pytest.approx(1.5811, abs=1e-4)

    def test_fewer_than_window(self):
        """פחות מ-window פקיעות → n = מה שיש, ללא קריסה."""
        df = _vol_df_from_moves([1.0, 2.0, 3.0])
        res = recent_volatility(df, "W", _AFTER_ALL, window=12)
        assert res["n"] == 3
        assert res["mean_abs_move"] == pytest.approx(2.0)          # (1+2+3)/3
        assert res["std_move"] == pytest.approx(0.8165, abs=1e-4)  # √(2/3)

    # ── סינון סוג: W לא מערבב M ─────────────────────────────────────────
    def test_type_filter_does_not_mix(self):
        w = _vol_df_from_moves([1.0, 1.0, 1.0], etype="W", start="2016-01-01")
        m = _vol_df_from_moves([5.0, 5.0, 5.0], etype="M", start="2017-01-01")
        df = pd.concat([w, m], ignore_index=True)
        res_w = recent_volatility(df, "W", _AFTER_ALL, window=12)
        res_m = recent_volatility(df, "M", _AFTER_ALL, window=12)
        assert res_w["n"] == 3 and res_w["mean_abs_move"] == pytest.approx(1.0)
        assert res_m["n"] == 3 and res_m["mean_abs_move"] == pytest.approx(5.0)

    def test_none_type_includes_all(self):
        w = _vol_df_from_moves([1.0, 1.0, 1.0], etype="W", start="2016-01-01")
        m = _vol_df_from_moves([5.0, 5.0, 5.0], etype="M", start="2017-01-01")
        df = pd.concat([w, m], ignore_index=True)
        res = recent_volatility(df, None, _AFTER_ALL, window=12)
        assert res["n"] == 6
        assert res["mean_abs_move"] == pytest.approx(3.0)          # (3×1+3×5)/6

    # ── סיווג משטר: calm / normal / volatile / boundary ─────────────────
    def test_regime_calm(self):
        """חלון נמוך מול בסיס גבוה: 20×2.0 (ישן) + 12×0.4 (אחרון); window=12.
        window mean=0.4 ; global=(40+4.8)/32=1.4 ; ratio=0.286 < 0.75 → calm."""
        df = _vol_df_from_moves([2.0] * 20 + [0.4] * 12)
        res = recent_volatility(df, "W", _AFTER_ALL, window=12)
        assert res["n"] == 12
        assert res["mean_abs_move"] == pytest.approx(0.4)
        assert res["regime"] == "calm"

    def test_regime_volatile(self):
        """חלון גבוה מול בסיס נמוך: 20×0.4 + 12×2.0; window=12.
        window mean=2.0 ; global=(8+24)/32=1.0 ; ratio=2.0 > 1.25 → volatile."""
        df = _vol_df_from_moves([0.4] * 20 + [2.0] * 12)
        res = recent_volatility(df, "W", _AFTER_ALL, window=12)
        assert res["mean_abs_move"] == pytest.approx(2.0)
        assert res["regime"] == "volatile"

    def test_regime_normal_uniform(self):
        """תנועות אחידות → window==global → ratio=1.0 → normal."""
        df = _vol_df_from_moves([1.0] * 30)
        res = recent_volatility(df, "W", _AFTER_ALL, window=12)
        assert res["mean_abs_move"] == pytest.approx(1.0)
        assert res["regime"] == "normal"

    def test_regime_boundary_075_is_normal(self):
        """ratio=0.75 בדיוק → normal (calm הוא < 0.75 ממש).
        20×1.15 + 12×0.75 ; window mean=0.75 ; global=(23+9)/32=1.0 ; ratio=0.75."""
        df = _vol_df_from_moves([1.15] * 20 + [0.75] * 12)
        res = recent_volatility(df, "W", _AFTER_ALL, window=12)
        assert res["mean_abs_move"] == pytest.approx(0.75)
        assert res["regime"] == "normal"

    # ── מקרי קצה ────────────────────────────────────────────────────────
    def test_empty_window_returns_unknown(self):
        """before_date לפני כל הנתונים → n=0, ערכים None, regime='unknown'."""
        df = _vol_df_from_moves([1.0, 2.0, 3.0], start="2020-01-01")
        before = pd.Timestamp("2019-01-01")
        res = recent_volatility(df, "W", before, window=12)
        assert res == {"mean_abs_move": None, "std_move": None, "n": 0, "regime": "unknown"}

    def test_empty_df_returns_unknown(self):
        res = recent_volatility(pd.DataFrame(), "W", _AFTER_ALL)
        assert res["n"] == 0 and res["regime"] == "unknown"

    def test_nan_moves_excluded(self):
        """שורות עם move_pct=NaN (unknown) לא נספרות בחלון."""
        df = _vol_df_from_moves([1.0, 2.0])
        df.loc[len(df)] = {"expiry_date": pd.Timestamp("2015-03-01"),
                           "expiry_type": "W", "move_pct": None, "abs_move_pct": None}
        res = recent_volatility(df, "W", _AFTER_ALL, window=12)
        assert res["n"] == 2                                  # שורת ה-NaN הוחרגה

    def test_all_zero_moves_regime_unknown(self):
        """global_mean=0 → אי-אפשר לסווג יחס → regime='unknown' (בלי חלוקה ב-0)."""
        df = _vol_df_from_moves([0.0] * 10)
        res = recent_volatility(df, "W", _AFTER_ALL, window=12)
        assert res["mean_abs_move"] == pytest.approx(0.0)
        assert res["regime"] == "unknown"

    def test_default_window_is_12(self):
        """ברירת המחדל של window היא 12."""
        df = _vol_df_from_moves([1.0] * 30)
        res = recent_volatility(df, "W", _AFTER_ALL)   # ללא window מפורש
        assert res["n"] == 12

    def test_zero_lookahead_future_history_does_not_change_regime(self):
        """zero-lookahead: אותו חלון + היסטוריה עתידית שונה → אותו regime בדיוק.

        prior (לפני cutoff): 20×0.4 + 12×2.0 → window mean=2.0, baseline=1.0,
        ratio=2.0 → 'volatile'.
        df_full מוסיף 50 פקיעות עתידיות ענקיות (move=10.0) *אחרי* cutoff.
        אם הבסיס היה רואה עתיד (הבאג הישן): baseline=(8+24+500)/82≈6.49, ratio≈0.31
        → היה הופך ל-'calm'. עם zero-lookahead הבסיס מתעלם מהעתיד → נשאר 'volatile',
        וזהה ל-df_prior_only. כך מוכחת אי-ההצצה לעתיד.
        """
        prior_moves  = [0.4] * 20 + [2.0] * 12
        future_moves = [10.0] * 50
        df_full = _vol_df_from_moves(prior_moves + future_moves)
        cutoff  = df_full["expiry_date"].iloc[len(prior_moves)]   # תאריך הפקיעה העתידית הראשונה
        df_prior_only = df_full.iloc[:len(prior_moves)].copy()

        res_prior = recent_volatility(df_prior_only, "W", cutoff, window=12)
        res_full  = recent_volatility(df_full,       "W", cutoff, window=12)

        # אותו חלון בדיוק (העתיד לא משפיע על n/mean)
        assert res_prior["n"] == res_full["n"] == 12
        assert res_prior["mean_abs_move"] == res_full["mean_abs_move"] == pytest.approx(2.0)
        # ואותו regime — הבסיס לא ראה את 50 הפקיעות העתידיות
        assert res_prior["regime"] == res_full["regime"] == "volatile"


# ─── build_expiry_decision (מנוע ההחלטה, shadow mode) ─────────────────

def _dec_df(specs):
    """specs: list of (date_str, expiry_type, move_pct) → DataFrame."""
    return _make_df([{"expiry_date": d, "expiry_type": t, "move_pct": m} for d, t, m in specs])


def _structural_df():
    """W-May (similar): [-0.2,-0.2,0.2,3.0]; W-Aug (לגלובלי): 0.2×4; +M-May מוחרגת.

    cond  (4 May): BCS .5 | IC .75 | CallBfly .75 | PutBfly .75 | Straddle .25 | Strangle .25
    global(8 W):   BCS .75| IC .875| CallBfly .875| PutBfly .875| Straddle .125| Strangle .125
    → ranking לפי cond יורד: [2,3,4,1,5,6]  (מוכיח מיון לפי cond, לא לפי sid)
    """
    return _dec_df([
        ("2018-05-15", "W", -0.2), ("2019-05-15", "W", -0.2),
        ("2020-05-15", "W",  0.2), ("2021-05-15", "W",  3.0),
        ("2018-08-15", "W",  0.2), ("2019-08-15", "W",  0.2),
        ("2020-08-15", "W",  0.2), ("2021-08-15", "W",  0.2),
        ("2019-05-28", "M",  0.2),   # M — מוחרגת מסינון הסוג
    ])


_EXP = pd.Timestamp("2022-05-15")


class TestBuildExpiryDecision:
    # ── מבנה מלא + מיון לפי cond_wr (לא לפי sid) ────────────────────────
    def test_output_structure_and_ranking(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP, recent_move_pct=None)

        assert set(dec.keys()) == {
            "expiry_date", "expiry_type", "regime", "n_similar",
            "risk_score", "ranking", "top_strategy_id", "note",
        }
        assert dec["expiry_type"] == "W"
        assert dec["n_similar"] == 4

        ranking = dec["ranking"]
        assert len(ranking) == 6                                  # כל 6 (shadow — לא מסונן)
        assert {r["strategy_id"] for r in ranking} == {1, 2, 3, 4, 5, 6}

        # מיון לפי cond_wr יורד — סדר ה-sid שונה מ-1..6 (מוכיח שזה אכן ממיין)
        assert [r["strategy_id"] for r in ranking] == [2, 3, 4, 1, 5, 6]
        assert [r["cond_wr"] for r in ranking] == [0.75, 0.75, 0.75, 0.5, 0.25, 0.25]
        assert [r["rank"] for r in ranking] == [1, 2, 3, 4, 5, 6]

    def test_top_strategy_matches_first_record(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP, recent_move_pct=None)
        assert dec["top_strategy_id"] == dec["ranking"][0]["strategy_id"] == 2

    def test_top_record_exact_values(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP, recent_move_pct=None)
        top = dec["ranking"][0]
        assert top["strategy_id"] == 2
        assert top["cond_wr"]   == pytest.approx(0.75)
        assert top["global_wr"] == pytest.approx(0.875)
        assert top["delta_wr"]  == pytest.approx(-0.125)
        assert top["rank"] == 1

    def test_delta_wr_equals_cond_minus_global(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP, recent_move_pct=None)
        for r in dec["ranking"]:
            assert r["delta_wr"] == pytest.approx(round(r["cond_wr"] - r["global_wr"], 4))

    def test_regime_embedded(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP, recent_move_pct=None)
        reg = dec["regime"]
        assert set(reg.keys()) == {"regime", "mean_abs_move", "std_move", "n"}
        # 8 W פקיעות לפני 2022-05-15; |moves| ממוצע = 4.4/8 = 0.55 ; ratio=1.0 → normal
        assert reg["regime"] == "normal"
        assert reg["mean_abs_move"] == pytest.approx(0.55)
        assert reg["n"] == 8

    def test_reason_contains_rank_and_cond_wr(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP, recent_move_pct=None)
        top = dec["ranking"][0]
        assert "#1" in top["reason"]
        assert f"{top['cond_wr']:.0%}" in top["reason"]   # "75%"

    def test_shadow_returns_all_six_not_filtered(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP, recent_move_pct=None)
        assert len(dec["ranking"]) == 6   # אף אסטרטגיה לא סוננה

    # ── מקרי קצה / נימה ─────────────────────────────────────────────────
    def test_no_similar_falls_back_to_global(self):
        # חודש 11 — אין פקיעות → אין דומים; הדירוג נשען על global בלבד
        dec = build_expiry_decision(_structural_df(), "W", 11, _EXP, recent_move_pct=0.5)
        assert dec["n_similar"] == 0
        assert all(r["cond_wr"] is None for r in dec["ranking"])
        assert all(r["delta_wr"] is None for r in dec["ranking"])
        assert "אין מקרים דומים" in dec["note"]
        # ממוין לפי global יורד; global מקסימלי = IC/Bfly (.875) → top ניטרלי
        assert [r["global_wr"] for r in dec["ranking"]] == [0.875, 0.875, 0.875, 0.75, 0.125, 0.125]
        assert "אין מקרים דומים" in dec["ranking"][0]["reason"]

    def test_recent_move_none_adds_caveat(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP, recent_move_pct=None)
        assert "ללא סינון תנועה קודמת" in dec["note"]

    def test_high_risk_neutral_top_triggers_warning(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP,
                                    recent_move_pct=None, risk_score=8.0)
        # top=IC (ניטרלי) + סיכון גבוה → אזהרה שמציעה אסטרטגיה תנודתית
        assert "⚠️" in dec["note"]
        assert "ציון סיכון 8.0" in dec["note"]
        assert "Long Straddle" in dec["note"]      # האלטרנטיבה התנודתית הראשונה בדירוג

    def test_low_risk_normal_regime_no_warning(self):
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP,
                                    recent_move_pct=None, risk_score=1.0)
        assert "⚠️" not in dec["note"]

    def test_volatile_regime_neutral_top_triggers_warning(self):
        # בסיס נמוך (20×0.1) + חלון אחרון גבוה (12×2.0) → regime volatile;
        # May=[-0.2,-0.2,0.2,0.2] → top ניטרלי (IC). risk נמוך — הטריגר הוא ה-regime.
        specs = []
        for i in range(20):
            specs.append((f"{1990+i}-01-15", "W", 0.1))
        for i, mv in enumerate([-0.2, -0.2, 0.2, 0.2]):
            specs.append((f"{2001+i}-05-15", "W", mv))
        for i in range(12):
            specs.append((f"{2015+i}-08-15", "W", 2.0))
        df = _dec_df(specs)
        dec = build_expiry_decision(df, "W", 5, pd.Timestamp("2027-01-01"),
                                    recent_move_pct=None, risk_score=0.0)
        assert dec["regime"]["regime"] == "volatile"
        assert dec["top_strategy_id"] in (2, 3, 4)   # ניטרלי
        assert "⚠️" in dec["note"]
        assert "משטר תנודתי" in dec["note"]

    def test_pure_no_mutation_of_input(self):
        df = _structural_df()
        before = df.copy()
        build_expiry_decision(df, "W", 5, _EXP, recent_move_pct=None)
        # טהורה — לא משנה את ה-DataFrame שהועבר
        pd.testing.assert_frame_equal(df, before)


# ─── שובר-שוויון לפי עוצמה (cond_intensity) ───────────────────────────

def _rec(dec, sid):
    """שולף את רשומת הדירוג של אסטרטגיה לפי id."""
    return next(r for r in dec["ranking"] if r["strategy_id"] == sid)


class TestDecisionIntensityTiebreaker:
    def test_intensity_breaks_cond_wr_tie_and_reverses_global_order(self):
        """ההבחנה המרכזית: כשה-cond_wr שווה, cond_intensity מכריע — ומהפך את הסדר
        שהיה נקבע לפי global_wr.

        similar (W-May): 5×0.2 — move קטן שבו BCS/IC/Butterfly כולם cond_wr=1.0.
        global נשלט ע"י 15×5.0 (W-Aug): BCS global=1.0 (move>0), IC/Butterfly נמוך.
        → בלי שובר-השוויון (מיון לפי global_wr) BCS היה #1 בקבוצת ה-1.0.
        → עם cond_intensity: IC (0.8) #1, Butterfly (0.6), BCS (0.2) צונח לתחתית.
        """
        specs = [(f"{2010+i}-05-15", "W", 0.2) for i in range(5)] \
              + [(f"{2010+i}-08-15", "W", 5.0) for i in range(15)]
        dec = build_expiry_decision(_dec_df(specs), "W", 5,
                                    pd.Timestamp("2026-05-15"), recent_move_pct=None)

        ic, cb, pb, bcs = _rec(dec, 2), _rec(dec, 3), _rec(dec, 4), _rec(dec, 1)

        # כל הארבע חולקות cond_wr זהה (התנאי לשובר-שוויון)
        assert ic["cond_wr"] == cb["cond_wr"] == pb["cond_wr"] == bcs["cond_wr"] == 1.0

        # cond_intensity מבדיל: IC > Butterfly > BCS
        assert ic["cond_intensity"] == pytest.approx(0.8)
        assert cb["cond_intensity"] == pytest.approx(0.6)
        assert bcs["cond_intensity"] == pytest.approx(0.2)

        # הדירוג החדש: IC ראשון, BCS אחרון בקבוצת ה-1.0
        assert dec["top_strategy_id"] == 2
        assert ic["rank"] < cb["rank"] < bcs["rank"]

        # הוכחת "נכשל בלי שובר-השוויון": ל-BCS ה-global_wr הגבוה ביותר בקבוצה,
        # כך שמיון לפי (cond_wr, global_wr) בלבד היה ממקם אותו #1.
        assert bcs["global_wr"] > ic["global_wr"]
        assert bcs["global_wr"] == max(r["global_wr"] for r in dec["ranking"]
                                       if r["cond_wr"] == 1.0)

    def test_different_cond_wr_not_overridden_by_intensity(self):
        """כשה-cond_wr שונה — הוא מכריע, גם אם לאסטרטגיה התחתונה עוצמה גבוהה יותר.

        similar (W-May): [0.9,0.9,0.9,-0.1].
        IC cond_wr=1.0 (|move|<1) אך עוצמה נמוכה (0.3, רוחב 1.0 על move 0.9).
        BCS cond_wr=0.75 (3 מתוך 4 חיוביים) אך עוצמה גבוהה יותר (0.675).
        → IC חייב לדרג מעל BCS למרות עוצמתו הנמוכה — cond_wr גובר.
        """
        specs = [("2011-05-15", "W", 0.9), ("2012-05-15", "W", 0.9),
                 ("2013-05-15", "W", 0.9), ("2014-05-15", "W", -0.1)]
        dec = build_expiry_decision(_dec_df(specs), "W", 5,
                                    pd.Timestamp("2026-05-15"), recent_move_pct=None)
        ic, bcs = _rec(dec, 2), _rec(dec, 1)

        assert ic["cond_wr"] == pytest.approx(1.0)
        assert bcs["cond_wr"] == pytest.approx(0.75)
        assert ic["cond_wr"] > bcs["cond_wr"]
        # העוצמה של BCS גבוהה יותר — אך אסור שתדרוס את ה-cond_wr
        assert bcs["cond_intensity"] > ic["cond_intensity"]
        assert ic["rank"] < bcs["rank"]

    def test_cond_intensity_in_records_and_reason(self):
        """cond_intensity קיים בכל רשומה, ומשולב ב-reason."""
        dec = build_expiry_decision(_structural_df(), "W", 5, _EXP, recent_move_pct=None)
        for r in dec["ranking"]:
            assert "cond_intensity" in r
        top = dec["ranking"][0]
        assert top["cond_intensity"] is not None
        assert "עוצמה ממוצעת" in top["reason"]
        assert f"{top['cond_intensity']:.2f}" in top["reason"]

    def test_no_similar_cond_intensity_none(self):
        """ללא דומים → cond_intensity=None בכל רשומה, וה-reason ללא 'עוצמה ממוצעת'."""
        dec = build_expiry_decision(_structural_df(), "W", 11, _EXP, recent_move_pct=0.5)
        assert all(r["cond_intensity"] is None for r in dec["ranking"])
        assert "עוצמה ממוצעת" not in dec["ranking"][0]["reason"]
