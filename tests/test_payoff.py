"""
בדיקות יחידה למודול payoff.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from payoff import (
    MULTIPLIER,
    build_payoff_fig,
    find_breakevens,
    format_legs,
    payoff_bull_call_spread,
    payoff_call_butterfly,
    payoff_iron_condor,
    payoff_put_butterfly,
    payoff_straddle,
    payoff_strangle,
    price_range,
    strategy_legs_detail,
    strategy_payoff_params,
    strategy_summary,
)


# ─── fixtures ────────────────────────────────────────────────────────────

def _S(*vals): return np.array(vals, dtype=float)

def _atm(strike=2000.0, call_pts=20.0, put_pts=18.0):
    return {
        "strike":         strike,
        "call_price":     call_pts * MULTIPLIER,
        "put_price":      put_pts  * MULTIPLIER,
        "call_pts":       call_pts,
        "put_pts":        put_pts,
        "index_estimate": strike,
    }

def _make_chain(atm=2000.0):
    """שרשרת סינתטית סביב ATM לבדיקות strategy_payoff_params."""
    strikes = np.arange(atm * 0.90, atm * 1.10 + 1, 10)
    rows = []
    for k in strikes:
        dist = abs(k - atm)
        call_price = max(atm - k, 0) + 20 - dist * 0.4   # ATM call ≈ 20 נק'
        put_price  = max(k - atm, 0) + 18 - dist * 0.4
        call_price = max(call_price, 0.5)
        put_price  = max(put_price,  0.5)
        rows.append({
            "strike":     float(k),
            "call_price": round(call_price * MULTIPLIER, 1),
            "put_price":  round(put_price  * MULTIPLIER, 1),
            "call_pts":   round(call_price, 2),
            "put_pts":    round(put_price,  2),
            "call_delta": 50.0,
            "put_delta":  50.0,
            "call_volume": 100.0,
            "put_volume":  100.0,
            "call_oi": 0.0, "put_oi": 0.0,
            "call_high": 0.0, "call_low": 0.0,
            "put_high": 0.0, "put_low": 0.0,
        })
    return pd.DataFrame(rows)


# ─── TestPriceRange ───────────────────────────────────────────────────────

class TestPriceRange:
    def test_length(self):
        assert len(price_range(2000.0, n=50)) == 50

    def test_bounds(self):
        S = price_range(2000.0, pct=0.10)
        assert S[0]  == pytest.approx(1800.0)
        assert S[-1] == pytest.approx(2200.0)

    def test_monotone(self):
        S = price_range(2000.0)
        assert (np.diff(S) > 0).all()


# ─── TestBullCallSpread ───────────────────────────────────────────────────

class TestBullCallSpread:
    K1, K2, COST = 2000.0, 2030.0, 5.0

    def test_max_loss_below_lower(self):
        y = payoff_bull_call_spread(_S(1900.0), self.K1, self.K2, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_max_profit_above_upper(self):
        y = payoff_bull_call_spread(_S(2100.0), self.K1, self.K2, self.COST)
        assert y[0] == pytest.approx((self.K2 - self.K1 - self.COST) * MULTIPLIER)

    def test_at_lower_strike(self):
        y = payoff_bull_call_spread(_S(self.K1), self.K1, self.K2, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_at_upper_strike(self):
        y = payoff_bull_call_spread(_S(self.K2), self.K1, self.K2, self.COST)
        assert y[0] == pytest.approx((self.K2 - self.K1 - self.COST) * MULTIPLIER)

    def test_midpoint_linear(self):
        mid = (self.K1 + self.K2) / 2
        y = payoff_bull_call_spread(_S(mid), self.K1, self.K2, self.COST)
        expected = ((mid - self.K1) - self.COST) * MULTIPLIER
        assert y[0] == pytest.approx(expected)

    def test_returns_array(self):
        S = _S(1950.0, 2000.0, 2015.0, 2030.0, 2050.0)
        y = payoff_bull_call_spread(S, self.K1, self.K2, self.COST)
        assert y.shape == S.shape


# ─── TestIronCondor ──────────────────────────────────────────────────────

class TestIronCondor:
    K_LP, K_SP, K_SC, K_LC = 1940.0, 1960.0, 2040.0, 2060.0
    CREDIT = 3.0  # pts

    def test_max_profit_inside_zone(self):
        y = payoff_iron_condor(_S(2000.0), self.K_LP, self.K_SP, self.K_SC, self.K_LC, self.CREDIT)
        assert y[0] == pytest.approx(self.CREDIT * MULTIPLIER)

    def test_max_loss_below_long_put(self):
        protection = self.K_SP - self.K_LP
        y = payoff_iron_condor(_S(1900.0), self.K_LP, self.K_SP, self.K_SC, self.K_LC, self.CREDIT)
        assert y[0] == pytest.approx(-(protection - self.CREDIT) * MULTIPLIER)

    def test_max_loss_above_long_call(self):
        protection = self.K_LC - self.K_SC
        y = payoff_iron_condor(_S(2100.0), self.K_LP, self.K_SP, self.K_SC, self.K_LC, self.CREDIT)
        assert y[0] == pytest.approx(-(protection - self.CREDIT) * MULTIPLIER)

    def test_loss_increases_below_short_put(self):
        y_mid = payoff_iron_condor(_S(self.K_SP), self.K_LP, self.K_SP, self.K_SC, self.K_LC, self.CREDIT)
        y_below = payoff_iron_condor(_S(1950.0), self.K_LP, self.K_SP, self.K_SC, self.K_LC, self.CREDIT)
        assert y_below[0] < y_mid[0]

    def test_symmetric_losses(self):
        protection = self.K_SP - self.K_LP
        y_low  = payoff_iron_condor(_S(1900.0), self.K_LP, self.K_SP, self.K_SC, self.K_LC, self.CREDIT)
        y_high = payoff_iron_condor(_S(2100.0), self.K_LP, self.K_SP, self.K_SC, self.K_LC, self.CREDIT)
        assert y_low[0] == pytest.approx(y_high[0])


# ─── TestCallButterfly ────────────────────────────────────────────────────

class TestCallButterfly:
    K_LO, K_MID, K_HI, COST = 1980.0, 2000.0, 2020.0, 2.0

    def test_max_profit_at_mid(self):
        wing = self.K_MID - self.K_LO
        y = payoff_call_butterfly(_S(self.K_MID), self.K_LO, self.K_MID, self.K_HI, self.COST)
        assert y[0] == pytest.approx((wing - self.COST) * MULTIPLIER)

    def test_max_loss_at_lower_wing(self):
        y = payoff_call_butterfly(_S(self.K_LO), self.K_LO, self.K_MID, self.K_HI, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_max_loss_at_upper_wing(self):
        y = payoff_call_butterfly(_S(self.K_HI), self.K_LO, self.K_MID, self.K_HI, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_max_loss_far_below(self):
        y = payoff_call_butterfly(_S(1900.0), self.K_LO, self.K_MID, self.K_HI, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_max_loss_far_above(self):
        y = payoff_call_butterfly(_S(2100.0), self.K_LO, self.K_MID, self.K_HI, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)


# ─── TestPutButterfly ─────────────────────────────────────────────────────

class TestPutButterfly:
    K_LO, K_MID, K_HI, COST = 1980.0, 2000.0, 2020.0, 2.0

    def test_max_profit_at_mid(self):
        wing = self.K_HI - self.K_MID
        y = payoff_put_butterfly(_S(self.K_MID), self.K_LO, self.K_MID, self.K_HI, self.COST)
        assert y[0] == pytest.approx((wing - self.COST) * MULTIPLIER)

    def test_max_loss_at_lower_wing(self):
        y = payoff_put_butterfly(_S(self.K_LO), self.K_LO, self.K_MID, self.K_HI, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_max_loss_at_upper_wing(self):
        y = payoff_put_butterfly(_S(self.K_HI), self.K_LO, self.K_MID, self.K_HI, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_max_loss_far_above(self):
        y = payoff_put_butterfly(_S(2100.0), self.K_LO, self.K_MID, self.K_HI, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_call_and_put_butterfly_same_shape(self):
        """Call ו-Put Butterfly עם כנפיים שווים מייצרים אותו פרופיל P&L."""
        S = price_range(2000.0, n=50)
        yc = payoff_call_butterfly(S, self.K_LO, self.K_MID, self.K_HI, self.COST)
        yp = payoff_put_butterfly( S, self.K_LO, self.K_MID, self.K_HI, self.COST)
        np.testing.assert_allclose(yc, yp, atol=1e-8)


# ─── TestStraddle ─────────────────────────────────────────────────────────

class TestStraddle:
    K, COST = 2000.0, 8.0

    def test_max_loss_at_strike(self):
        y = payoff_straddle(_S(self.K), self.K, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_profit_far_up(self):
        y = payoff_straddle(_S(2100.0), self.K, self.COST)
        assert y[0] == pytest.approx((100 - self.COST) * MULTIPLIER)

    def test_profit_far_down(self):
        y = payoff_straddle(_S(1900.0), self.K, self.COST)
        assert y[0] == pytest.approx((100 - self.COST) * MULTIPLIER)

    def test_symmetric(self):
        above = 2000.0 + 50
        below = 2000.0 - 50
        y_above = payoff_straddle(_S(above), self.K, self.COST)
        y_below = payoff_straddle(_S(below), self.K, self.COST)
        assert y_above[0] == pytest.approx(y_below[0])

    def test_breakeven_upper(self):
        S = price_range(self.K, pct=0.05, n=1000)
        y = payoff_straddle(S, self.K, self.COST)
        bes = find_breakevens(S, y)
        # upper breakeven ≈ K + COST
        upper = [be for be in bes if be > self.K]
        assert len(upper) >= 1
        assert upper[0] == pytest.approx(self.K + self.COST, abs=1.0)


# ─── TestStrangle ─────────────────────────────────────────────────────────

class TestStrangle:
    K_PUT, K_CALL, COST = 1970.0, 2030.0, 4.0

    def test_max_loss_inside_zone(self):
        y = payoff_strangle(_S(2000.0), self.K_PUT, self.K_CALL, self.COST)
        assert y[0] == pytest.approx(-self.COST * MULTIPLIER)

    def test_flat_loss_between_strikes(self):
        y1 = payoff_strangle(_S(1975.0), self.K_PUT, self.K_CALL, self.COST)
        y2 = payoff_strangle(_S(2025.0), self.K_PUT, self.K_CALL, self.COST)
        assert y1[0] == pytest.approx(y2[0])

    def test_profit_above_call(self):
        y = payoff_strangle(_S(self.K_CALL + self.COST + 10), self.K_PUT, self.K_CALL, self.COST)
        assert y[0] > 0

    def test_profit_below_put(self):
        y = payoff_strangle(_S(self.K_PUT - self.COST - 10), self.K_PUT, self.K_CALL, self.COST)
        assert y[0] > 0


# ─── TestFindBreakevens ───────────────────────────────────────────────────

class TestFindBreakevens:
    def test_straddle_two_breakevens(self):
        S = price_range(2000.0, pct=0.08, n=1000)
        y = payoff_straddle(S, 2000.0, 8.0)
        bes = find_breakevens(S, y)
        assert len(bes) == 2

    def test_call_spread_one_breakeven(self):
        S = price_range(2000.0, pct=0.05, n=1000)
        y = payoff_bull_call_spread(S, 2000.0, 2030.0, 5.0)
        bes = find_breakevens(S, y)
        assert len(bes) == 1
        assert bes[0] == pytest.approx(2000.0 + 5.0, abs=1.0)

    def test_condor_two_breakevens(self):
        S = price_range(2000.0, pct=0.08, n=2000)
        y = payoff_iron_condor(S, 1940.0, 1960.0, 2040.0, 2060.0, 3.0)
        bes = find_breakevens(S, y)
        assert len(bes) == 2

    def test_always_in_profit_no_breakeven(self):
        # degenerate case: all positive
        S = price_range(2000.0, n=100)
        y = np.ones_like(S) * 100
        assert find_breakevens(S, y) == []


# ─── TestStrategyPayoffParams ─────────────────────────────────────────────

class TestStrategyPayoffParams:
    _atm   = _atm(2000.0, call_pts=20.0, put_pts=18.0)
    _chain = _make_chain(2000.0)

    def test_strategy_1_has_required_keys(self):
        p = strategy_payoff_params(1, self._atm, self._chain)
        for k in ("K_long", "K_short", "cost_pts"):
            assert k in p

    def test_strategy_2_has_required_keys(self):
        p = strategy_payoff_params(2, self._atm, self._chain)
        for k in ("K_lp", "K_sp", "K_sc", "K_lc", "credit_pts"):
            assert k in p

    def test_strategy_3_has_required_keys(self):
        p = strategy_payoff_params(3, self._atm, self._chain)
        for k in ("K_lo", "K_mid", "K_hi", "cost_pts"):
            assert k in p

    def test_strategy_4_has_required_keys(self):
        p = strategy_payoff_params(4, self._atm, self._chain)
        for k in ("K_lo", "K_mid", "K_hi", "cost_pts"):
            assert k in p

    def test_strategy_5_has_required_keys(self):
        p = strategy_payoff_params(5, self._atm, self._chain)
        for k in ("K", "cost_pts"):
            assert k in p

    def test_strategy_6_has_required_keys(self):
        p = strategy_payoff_params(6, self._atm, self._chain)
        for k in ("K_put", "K_call", "cost_pts"):
            assert k in p

    def test_unknown_strategy_returns_empty(self):
        p = strategy_payoff_params(99, self._atm, self._chain)
        assert p == {}

    def test_strategy_1_k_long_near_atm(self):
        p = strategy_payoff_params(1, self._atm, self._chain)
        assert abs(p["K_long"] - 2000.0) < 20

    def test_strategy_2_strike_ordering(self):
        p = strategy_payoff_params(2, self._atm, self._chain)
        assert p["K_lp"] < p["K_sp"] < p["K_sc"] < p["K_lc"]

    def test_strategy_3_strike_ordering(self):
        p = strategy_payoff_params(3, self._atm, self._chain)
        assert p["K_lo"] < p["K_mid"] < p["K_hi"]

    def test_strategy_6_k_put_below_k_call(self):
        p = strategy_payoff_params(6, self._atm, self._chain)
        assert p["K_put"] < p["K_call"]

    def test_empty_chain_returns_something(self):
        import pandas as pd
        empty = pd.DataFrame(columns=["strike", "call_price", "put_price"])
        # should not raise
        p = strategy_payoff_params(1, self._atm, empty)
        assert isinstance(p, dict)


# ─── TestBuildPayoffFig ───────────────────────────────────────────────────

class TestBuildPayoffFig:
    _atm   = _atm(2000.0)
    _chain = _make_chain(2000.0)

    def test_returns_figure(self):
        import plotly.graph_objects as go
        fig = build_payoff_fig(1, self._atm, self._chain)
        assert isinstance(fig, go.Figure)

    def test_figure_has_traces(self):
        fig = build_payoff_fig(1, self._atm, self._chain)
        assert len(fig.data) >= 2  # profit + loss traces

    def test_all_six_strategies_produce_figure(self):
        import plotly.graph_objects as go
        for sid in range(1, 7):
            fig = build_payoff_fig(sid, self._atm, self._chain)
            assert isinstance(fig, go.Figure), f"strategy {sid} failed"

    def test_dark_background(self):
        fig = build_payoff_fig(5, self._atm, self._chain)
        assert fig.layout.paper_bgcolor == "#0e1117"

    def test_index_price_param_accepted(self):
        import plotly.graph_objects as go
        fig = build_payoff_fig(1, self._atm, self._chain, index_price=1980.0)
        assert isinstance(fig, go.Figure)

    def test_index_price_annotation_present(self):
        fig = build_payoff_fig(3, self._atm, self._chain, index_price=1990.0)
        texts = [a.text for a in fig.layout.annotations]
        assert any("מדד עכשיו" in (t or "") for t in texts)

    def test_unknown_strategy_returns_figure(self):
        import plotly.graph_objects as go
        fig = build_payoff_fig(99, self._atm, self._chain)
        assert isinstance(fig, go.Figure)


# ─── TestStrategyLegsDetail ───────────────────────────────────────────────

class TestStrategyLegsDetail:
    _atm   = _atm(2000.0)
    _chain = _make_chain(2000.0)

    _LEG_KEYS = {"action", "type", "qty", "strike", "price_pts", "price_nis"}

    def test_strategy_1_has_two_legs(self):
        legs = strategy_legs_detail(1, self._atm, self._chain)
        assert len(legs) == 2

    def test_strategy_2_has_four_legs(self):
        legs = strategy_legs_detail(2, self._atm, self._chain)
        assert len(legs) == 4

    def test_strategy_3_has_three_legs(self):
        legs = strategy_legs_detail(3, self._atm, self._chain)
        assert len(legs) == 3

    def test_strategy_4_has_three_legs(self):
        legs = strategy_legs_detail(4, self._atm, self._chain)
        assert len(legs) == 3

    def test_strategy_5_has_two_legs(self):
        legs = strategy_legs_detail(5, self._atm, self._chain)
        assert len(legs) == 2

    def test_strategy_6_has_two_legs(self):
        legs = strategy_legs_detail(6, self._atm, self._chain)
        assert len(legs) == 2

    def test_unknown_strategy_returns_empty(self):
        legs = strategy_legs_detail(99, self._atm, self._chain)
        assert legs == []

    def test_all_legs_have_required_keys(self):
        for sid in range(1, 7):
            legs = strategy_legs_detail(sid, self._atm, self._chain)
            for leg in legs:
                assert self._LEG_KEYS <= leg.keys(), f"strategy {sid} leg missing keys"

    def test_action_is_buy_or_sell(self):
        for sid in range(1, 7):
            for leg in strategy_legs_detail(sid, self._atm, self._chain):
                assert leg["action"] in ("קנה", "מכור")

    def test_type_is_call_or_put(self):
        for sid in range(1, 7):
            for leg in strategy_legs_detail(sid, self._atm, self._chain):
                assert leg["type"] in ("Call", "Put")

    def test_price_nis_consistent_with_pts_and_qty(self):
        for sid in range(1, 7):
            for leg in strategy_legs_detail(sid, self._atm, self._chain):
                expected = round(leg["price_pts"] * MULTIPLIER * leg["qty"], 0)
                assert leg["price_nis"] == pytest.approx(expected, abs=1.0)

    def test_strategy_1_first_leg_is_call(self):
        legs = strategy_legs_detail(1, self._atm, self._chain)
        assert legs[0]["type"] == "Call"

    def test_strategy_5_has_call_and_put(self):
        legs = strategy_legs_detail(5, self._atm, self._chain)
        types = {lg["type"] for lg in legs}
        assert types == {"Call", "Put"}

    def test_strategy_3_middle_leg_qty_two(self):
        legs = strategy_legs_detail(3, self._atm, self._chain)
        # the ATM short call has qty=2
        short_legs = [lg for lg in legs if lg["action"] == "מכור"]
        assert any(lg["qty"] == 2 for lg in short_legs)


# ─── TestFormatLegs ───────────────────────────────────────────────────────

class TestFormatLegs:
    _atm   = _atm(2000.0)
    _chain = _make_chain(2000.0)

    def test_returns_string(self):
        legs = strategy_legs_detail(1, self._atm, self._chain)
        assert isinstance(format_legs(legs), str)

    def test_nonempty_for_valid_strategy(self):
        legs = strategy_legs_detail(1, self._atm, self._chain)
        assert format_legs(legs) != ""

    def test_pipe_separator_between_legs(self):
        legs = strategy_legs_detail(2, self._atm, self._chain)  # 4 legs → 3 pipes
        result = format_legs(legs)
        assert result.count("|") == 3

    def test_contains_strike_value(self):
        legs = strategy_legs_detail(1, self._atm, self._chain)
        result = format_legs(legs)
        assert "2,000" in result or "2000" in result

    def test_empty_legs_returns_empty_string(self):
        assert format_legs([]) == ""

    def test_contains_shekel_symbol(self):
        legs = strategy_legs_detail(5, self._atm, self._chain)
        assert "₪" in format_legs(legs)


# ─── TestStrategySummary ──────────────────────────────────────────────────

class TestStrategySummary:
    _atm   = _atm(2000.0)
    _chain = _make_chain(2000.0)

    _KEYS = {
        "entry_cost_nis", "max_profit_nis", "max_loss_nis",
        "risk_reward", "breakevens", "market_status",
        "be_pct_desc", "y_now_nis", "is_unlimited_profit",
    }

    def test_returns_dict_for_all_strategies(self):
        for sid in range(1, 7):
            result = strategy_summary(sid, self._atm, self._chain)
            assert isinstance(result, dict), f"strategy {sid} returned non-dict"

    def test_has_all_required_keys(self):
        for sid in range(1, 7):
            result = strategy_summary(sid, self._atm, self._chain)
            assert self._KEYS <= result.keys(), f"strategy {sid} missing keys"

    def test_unknown_strategy_returns_empty(self):
        assert strategy_summary(99, self._atm, self._chain) == {}

    def test_max_profit_positive(self):
        for sid in range(1, 7):
            result = strategy_summary(sid, self._atm, self._chain)
            assert result["max_profit_nis"] > 0, f"strategy {sid} max_profit not positive"

    def test_max_loss_negative(self):
        for sid in range(1, 7):
            result = strategy_summary(sid, self._atm, self._chain)
            assert result["max_loss_nis"] < 0, f"strategy {sid} max_loss not negative"

    def test_iron_condor_entry_is_credit(self):
        result = strategy_summary(2, self._atm, self._chain)
        assert result["entry_cost_nis"] < 0  # receiving credit

    def test_non_condor_entry_is_debit(self):
        for sid in (1, 3, 4, 5, 6):
            result = strategy_summary(sid, self._atm, self._chain)
            assert result["entry_cost_nis"] > 0, f"strategy {sid} should be debit"

    def test_straddle_is_unlimited_profit(self):
        assert strategy_summary(5, self._atm, self._chain)["is_unlimited_profit"] is True

    def test_strangle_is_unlimited_profit(self):
        assert strategy_summary(6, self._atm, self._chain)["is_unlimited_profit"] is True

    def test_non_volatile_not_unlimited(self):
        for sid in (1, 2, 3, 4):
            result = strategy_summary(sid, self._atm, self._chain)
            assert result["is_unlimited_profit"] is False

    def test_risk_reward_none_for_unlimited(self):
        for sid in (5, 6):
            result = strategy_summary(sid, self._atm, self._chain)
            assert result["risk_reward"] is None

    def test_breakevens_is_list(self):
        for sid in range(1, 7):
            result = strategy_summary(sid, self._atm, self._chain)
            assert isinstance(result["breakevens"], list)

    def test_market_status_valid_value(self):
        valid = {"profit_zone", "near_breakeven", "loss_zone"}
        for sid in range(1, 7):
            result = strategy_summary(sid, self._atm, self._chain)
            assert result["market_status"] in valid, f"strategy {sid} bad status"

    def test_be_pct_desc_is_string(self):
        for sid in range(1, 7):
            result = strategy_summary(sid, self._atm, self._chain)
            assert isinstance(result["be_pct_desc"], str)

    def test_y_now_nis_is_float(self):
        for sid in range(1, 7):
            result = strategy_summary(sid, self._atm, self._chain)
            assert isinstance(result["y_now_nis"], (int, float))

    def test_iron_condor_two_breakevens(self):
        result = strategy_summary(2, self._atm, self._chain)
        assert len(result["breakevens"]) == 2

    def test_straddle_two_breakevens(self):
        result = strategy_summary(5, self._atm, self._chain)
        assert len(result["breakevens"]) == 2
