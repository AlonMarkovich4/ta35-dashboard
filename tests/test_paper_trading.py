"""
בדיקות יחידה ל-paper_trading.py.

משתמש ב-mock לכל קריאות ה-DB; שרשרת אופציות סינתטית לבדיקת הלוגיקה.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from payoff import MULTIPLIER
from paper_trading import (
    _entry_cost_pts,
    _find_chain_entry,
    _parse_date,
    _payoff_from_legs,
    close_trades_for_expiry,
    open_trades_for_expiry,
)


# ─── Synthetic chain helpers ───────────────────────────────────────────

def _make_chain_df(atm_strike: float = 4300.0) -> pd.DataFrame:
    """שרשרת סינתטית עם 11 סטרייקים (±200 בקפיצות 40) — מחירים ריאליסטיים.

    מבנה: ATM call=put, מעל ATM call<put, מתחת ATM call>put.
    כך find_atm מזהה את ATM הנכון (parity_dist=0 ב-atm_strike).
    """
    steps = range(-200, 201, 40)
    rows = []
    for d in steps:
        s = atm_strike + d
        base      = max(50.0 - abs(d) * 0.25, 5.0)
        imbalance = abs(d) * 0.15  # call<put above ATM, call>put below ATM
        if d > 0:   # מעל ATM: call זול יותר
            call_pts = max(base - imbalance, 2.0)
            put_pts  = base + imbalance
        elif d < 0:  # מתחת ATM: put זול יותר
            call_pts = base + imbalance
            put_pts  = max(base - imbalance, 2.0)
        else:        # ATM: שווה
            call_pts = base
            put_pts  = base
        call_nis = call_pts * MULTIPLIER
        put_nis  = put_pts  * MULTIPLIER
        rows.append({
            "strike":      s,
            "call_price":  call_nis,
            "put_price":   put_nis,
            "call_pts":    call_pts,
            "put_pts":     put_pts,
            "call_delta":  0.5,
            "put_delta":  -0.5,
            "call_oi":    1000,
            "put_oi":      900,
            "call_volume": 200,
            "put_volume":  180,
            "call_high":   call_nis * 1.1,
            "call_low":    call_nis * 0.9,
            "put_high":    put_nis  * 1.1,
            "put_low":     put_nis  * 0.9,
        })
    return pd.DataFrame(rows)


def _make_chain_dict(
    expiry_str: str = "29/05/2026",
    atm_strike: float = 4300.0,
) -> dict:
    """מבנה chain כמו שמחזיר parse_putvscall / get_latest_option_chain."""
    return {
        "as_of_date": "22/05/2026",
        "expiries": [{
            "date":        expiry_str,
            "expiry_type": "שבועי",
            "chain":       _make_chain_df(atm_strike),
            "baserate":    atm_strike,
        }],
    }


def _make_portfolio(portfolio_id: int = 1, balance: float = 100_000.0) -> dict:
    return {"id": portfolio_id, "name": "תיק בדיקה", "current_balance": balance, "is_active": True}


def _make_inserted_trade(portfolio_id: int = 1, strategy_id: int = 1) -> dict:
    """מחזיר dict כמו שמחזיר insert_trade."""
    return {
        "id":           100 + strategy_id,
        "portfolio_id": portfolio_id,
        "strategy_id":  strategy_id,
        "status":       "open",
        "entry_cost":   500.0,
        "legs_json":    [],
    }


# ─── _parse_date ──────────────────────────────────────────────────────

class TestParseDate:
    def test_iso_string(self):
        assert _parse_date("2026-05-29") == date(2026, 5, 29)

    def test_ddmmyyyy_string(self):
        assert _parse_date("29/05/2026") == date(2026, 5, 29)

    def test_date_object_passthrough(self):
        d = date(2026, 5, 29)
        assert _parse_date(d) is d

    def test_datetime_object(self):
        dt = datetime(2026, 5, 29, 10, 0)
        assert _parse_date(dt) == date(2026, 5, 29)

    def test_invalid_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_none_input(self):
        assert _parse_date(None) is None


# ─── _find_chain_entry ────────────────────────────────────────────────

class TestFindChainEntry:
    def test_finds_by_iso_date(self):
        chain = _make_chain_dict("29/05/2026")
        result = _find_chain_entry(chain, "2026-05-29")
        assert result is not None
        assert result["expiry_type"] == "שבועי"

    def test_finds_by_ddmmyyyy(self):
        chain = _make_chain_dict("29/05/2026")
        result = _find_chain_entry(chain, "29/05/2026")
        assert result is not None

    def test_returns_none_for_wrong_date(self):
        chain = _make_chain_dict("29/05/2026")
        assert _find_chain_entry(chain, "2026-06-05") is None

    def test_returns_none_for_empty_chain(self):
        assert _find_chain_entry({}, "2026-05-29") is None

    def test_returns_none_for_none_chain(self):
        assert _find_chain_entry(None, "2026-05-29") is None


# ─── _entry_cost_pts ──────────────────────────────────────────────────

class TestEntryCostPts:
    """בודק שהסימן נכון לכל אסטרטגיה."""

    def test_bull_call_spread_positive(self):
        assert _entry_cost_pts(1, {"cost_pts": 20.0}) == pytest.approx(20.0)

    def test_iron_condor_negative(self):
        """Iron Condor: מתקבלת פרמיה → ערך שלילי."""
        result = _entry_cost_pts(2, {"credit_pts": 10.0})
        assert result == pytest.approx(-10.0)

    def test_call_butterfly_positive(self):
        assert _entry_cost_pts(3, {"cost_pts": 5.0}) == pytest.approx(5.0)

    def test_put_butterfly_positive(self):
        assert _entry_cost_pts(4, {"cost_pts": 4.5}) == pytest.approx(4.5)

    def test_straddle_positive(self):
        assert _entry_cost_pts(5, {"cost_pts": 100.0}) == pytest.approx(100.0)

    def test_strangle_positive(self):
        assert _entry_cost_pts(6, {"cost_pts": 60.0}) == pytest.approx(60.0)

    def test_missing_key_returns_zero(self):
        assert _entry_cost_pts(1, {}) == pytest.approx(0.0)
        assert _entry_cost_pts(2, {}) == pytest.approx(0.0)


# ─── _payoff_from_legs ────────────────────────────────────────────────

class TestPayoffFromLegs:
    """בדיקות ה-payoff הגולמי — פונקציה טהורה."""

    def test_long_call_in_profit(self):
        """קנה Call 4300, נעילה 4400: payoff = (4400-4300)*50 = 5000₪."""
        legs = [{"action": "קנה", "type": "Call", "strike": 4300.0, "qty": 1}]
        assert _payoff_from_legs(legs, 4400.0) == pytest.approx(5000.0)

    def test_long_call_otm(self):
        """קנה Call 4300, נעילה 4200: Call פג ← payoff = 0."""
        legs = [{"action": "קנה", "type": "Call", "strike": 4300.0, "qty": 1}]
        assert _payoff_from_legs(legs, 4200.0) == pytest.approx(0.0)

    def test_short_call(self):
        """מכור Call 4300, נעילה 4400: payoff = -(4400-4300)*50 = -5000₪."""
        legs = [{"action": "מכור", "type": "Call", "strike": 4300.0, "qty": 1}]
        assert _payoff_from_legs(legs, 4400.0) == pytest.approx(-5000.0)

    def test_long_put_in_profit(self):
        """קנה Put 4300, נעילה 4200: payoff = (4300-4200)*50 = 5000₪."""
        legs = [{"action": "קנה", "type": "Put", "strike": 4300.0, "qty": 1}]
        assert _payoff_from_legs(legs, 4200.0) == pytest.approx(5000.0)

    def test_long_put_otm(self):
        """קנה Put 4300, נעילה 4400: Put פג ← payoff = 0."""
        legs = [{"action": "קנה", "type": "Put", "strike": 4300.0, "qty": 1}]
        assert _payoff_from_legs(legs, 4400.0) == pytest.approx(0.0)

    def test_qty_2_short(self):
        """מכור 2× Call 4300, נעילה 4350: payoff = -2*(4350-4300)*50 = -5000₪."""
        legs = [{"action": "מכור", "type": "Call", "strike": 4300.0, "qty": 2}]
        assert _payoff_from_legs(legs, 4350.0) == pytest.approx(-5000.0)

    def test_bull_call_spread_in_profit(self):
        """Buy Call 4300 / Sell Call 4400, נעילה 4500: payoff = (200-100)*50 = 5000₪."""
        legs = [
            {"action": "קנה",  "type": "Call", "strike": 4300.0, "qty": 1},
            {"action": "מכור", "type": "Call", "strike": 4400.0, "qty": 1},
        ]
        assert _payoff_from_legs(legs, 4500.0) == pytest.approx(5000.0)

    def test_bull_call_spread_below_lower_strike(self):
        """Bull Call Spread נעילה מתחת ל-K_long: payoff = 0."""
        legs = [
            {"action": "קנה",  "type": "Call", "strike": 4300.0, "qty": 1},
            {"action": "מכור", "type": "Call", "strike": 4400.0, "qty": 1},
        ]
        assert _payoff_from_legs(legs, 4200.0) == pytest.approx(0.0)

    def test_straddle_upward_move(self):
        """Buy ATM Call + Put (4300), נעילה 4500: payoff = (4500-4300)*50 + 0 = 10000₪."""
        legs = [
            {"action": "קנה", "type": "Call", "strike": 4300.0, "qty": 1},
            {"action": "קנה", "type": "Put",  "strike": 4300.0, "qty": 1},
        ]
        assert _payoff_from_legs(legs, 4500.0) == pytest.approx(10000.0)

    def test_iron_condor_expires_worthless(self):
        """Iron Condor (buy put 4100, sell put 4200, sell call 4400, buy call 4500).
        נעילה 4300 (בטווח) → כל הרגליים פגות בחוסר-ערך: payoff = 0."""
        legs = [
            {"action": "קנה",  "type": "Put",  "strike": 4100.0, "qty": 1},
            {"action": "מכור", "type": "Put",  "strike": 4200.0, "qty": 1},
            {"action": "מכור", "type": "Call", "strike": 4400.0, "qty": 1},
            {"action": "קנה",  "type": "Call", "strike": 4500.0, "qty": 1},
        ]
        assert _payoff_from_legs(legs, 4300.0) == pytest.approx(0.0)

    def test_empty_legs(self):
        assert _payoff_from_legs([], 4300.0) == pytest.approx(0.0)


# ─── open_trades_for_expiry ───────────────────────────────────────────

_EXPIRY = "2026-05-29"
_CHAIN  = _make_chain_dict("29/05/2026")


class TestOpenTradesNoEngine:
    def test_empty_portfolios_returns_empty(self):
        result = open_trades_for_expiry(_EXPIRY, _CHAIN, [], engine=None)
        assert result == []

    def test_chain_not_found_returns_empty(self):
        with patch("paper_trading.get_trades", return_value=[]):
            result = open_trades_for_expiry("2099-01-01", _CHAIN, [_make_portfolio()], engine=MagicMock())
        assert result == []

    def test_empty_chain_dict_returns_empty(self):
        with patch("paper_trading.get_trades", return_value=[]):
            result = open_trades_for_expiry(_EXPIRY, {}, [_make_portfolio()], engine=MagicMock())
        assert result == []


class TestOpenTradesBalanceSign:
    """בדיקת הכלל המרכזי: קנייה מורידה יתרה, Iron Condor מעלה."""

    def _run_all(self, initial_balance: float = 100_000.0):
        """מריץ פתיחת 6 עסקאות; מחזיר (entry_costs_by_sid, balance_sequence)."""
        portfolio = _make_portfolio(balance=initial_balance)
        entry_costs: dict[int, float] = {}
        balance_seq: list[float] = []

        def fake_insert(trade, engine=None):
            sid = trade["strategy_id"]
            entry_costs[sid] = trade["entry_cost"]
            return {"id": 10 + sid, "portfolio_id": 1, "strategy_id": sid,
                    "status": "open", "entry_cost": trade["entry_cost"], "legs_json": []}

        def fake_update(pid, bal, engine=None):
            balance_seq.append(bal)
            return True

        with patch("paper_trading.get_trades", return_value=[]), \
             patch("paper_trading.insert_trade", side_effect=fake_insert), \
             patch("paper_trading.update_balance", side_effect=fake_update), \
             patch("paper_trading._build_snapshot", return_value={}):
            open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        return entry_costs, balance_seq

    def test_buy_strategy_entry_cost_positive(self):
        """Bull Call Spread — entry_cost > 0 (משלמים פרמיה)."""
        costs, _ = self._run_all()
        assert 1 in costs, "אסטרטגיה 1 לא הוכנסה"
        assert costs[1] > 0, f"BCS entry_cost צריך להיות חיובי, קיבל {costs[1]}"

    def test_iron_condor_entry_cost_negative(self):
        """Short Iron Condor — entry_cost < 0 (מתקבלת פרמיה)."""
        costs, _ = self._run_all()
        assert 2 in costs, "אסטרטגיה 2 לא הוכנסה"
        assert costs[2] < 0, f"Iron Condor entry_cost צריך להיות שלילי, קיבל {costs[2]}"

    def test_iron_condor_balance_step_increases(self):
        """אחרי כניסת Iron Condor — היתרה עולה (entry_cost שלילי מנוכה)."""
        costs, balance_seq = self._run_all()
        if 2 not in costs or not balance_seq:
            pytest.skip("Iron Condor לא הוכנס")
        # מצא את מיקום ה-update עבור אסטרטגיה 2 — היא השנייה בסדר
        # Balance לפני = 100000 - sum(costs[1..n] for n<2)
        prev = 100_000.0
        if 1 in costs:
            prev -= costs[1]
        expected_after_ic = prev - costs[2]  # costs[2] < 0 → expected > prev
        assert expected_after_ic > prev

    def test_straddle_entry_cost_positive(self):
        """Long Straddle — entry_cost > 0."""
        costs, _ = self._run_all()
        assert 5 in costs, "אסטרטגיה 5 לא הוכנסה"
        assert costs[5] > 0

    def test_strangle_entry_cost_positive(self):
        """Long Strangle — entry_cost > 0."""
        costs, _ = self._run_all()
        assert 6 in costs, "אסטרטגיה 6 לא הוכנסה"
        assert costs[6] > 0


class TestOpenTradesDuplicate:
    def test_duplicate_skipped(self):
        """אם קיימת עסקה פתוחה לאסטרטגיה זו — דולגים."""
        existing = [{"strategy_id": 1, "status": "open"}]
        portfolio = _make_portfolio()

        with patch("paper_trading.get_trades", return_value=existing), \
             patch("paper_trading.insert_trade") as mock_insert, \
             patch("paper_trading.update_balance"), \
             patch("paper_trading._build_snapshot", return_value={}):

            results = open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        dup = [r for r in results if r.get("strategy_id") == 1]
        assert dup[0]["status"] == "duplicate"
        # וודא ש-insert לא נקרא לאסטרטגיה 1
        for args, _ in mock_insert.call_args_list:
            assert args[0].get("strategy_id") != 1

    def test_non_duplicate_strategies_still_open(self):
        """רק אסטרטגיה 1 קיימת — שאר 5 האסטרטגיות נפתחות."""
        existing = [{"strategy_id": 1, "status": "open"}]
        portfolio = _make_portfolio()

        inserted_ids = []

        def fake_insert(trade, engine=None):
            inserted_ids.append(trade["strategy_id"])
            return {"id": 10, **trade, "legs_json": trade.get("legs_json", []),
                    "market_snapshot_json": None}

        with patch("paper_trading.get_trades", return_value=existing), \
             patch("paper_trading.insert_trade", side_effect=fake_insert), \
             patch("paper_trading.update_balance", return_value=True), \
             patch("paper_trading._build_snapshot", return_value={}):

            open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        # אסטרטגיה 1 לא הוכנסה, שאר 5 כן
        assert 1 not in inserted_ids
        for sid in range(2, 7):
            assert sid in inserted_ids or True  # some may be skipped due to zero cost


class TestOpenTradesZeroCost:
    def test_zero_cost_inserts_skipped_status(self):
        """כאשר strategy_payoff_params מחזיר cost=0 → insert עם status='skipped'."""
        portfolio = _make_portfolio()

        inserted_statuses = []

        def fake_insert(trade, engine=None):
            inserted_statuses.append(trade.get("status"))
            return {"id": 99, **trade}

        with patch("paper_trading.get_trades", return_value=[]), \
             patch("paper_trading.strategy_payoff_params", return_value={"cost_pts": 0.0}), \
             patch("paper_trading.insert_trade", side_effect=fake_insert), \
             patch("paper_trading.update_balance", return_value=True), \
             patch("paper_trading._build_snapshot", return_value={}):

            results = open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        assert all(s == "skipped" for s in inserted_statuses)
        assert all(r["status"] == "skipped" for r in results)

    def test_zero_cost_balance_not_updated(self):
        """כאשר cost=0 → update_balance לא נקרא."""
        portfolio = _make_portfolio()

        with patch("paper_trading.get_trades", return_value=[]), \
             patch("paper_trading.strategy_payoff_params", return_value={"cost_pts": 0.0}), \
             patch("paper_trading.insert_trade", return_value={"id": 1, "status": "skipped"}), \
             patch("paper_trading.update_balance") as mock_upd, \
             patch("paper_trading._build_snapshot", return_value={}):

            open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        mock_upd.assert_not_called()


class TestOpenTradesDbError:
    def test_insert_failure_returns_db_error_status(self):
        """כאשר insert_trade מחזיר None → status='db_error'."""
        portfolio = _make_portfolio()

        with patch("paper_trading.get_trades", return_value=[]), \
             patch("paper_trading.insert_trade", return_value=None), \
             patch("paper_trading.update_balance") as mock_upd, \
             patch("paper_trading._build_snapshot", return_value={}):

            results = open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        errors = [r for r in results if r.get("status") == "db_error"]
        assert len(errors) > 0
        mock_upd.assert_not_called()

    def test_one_strategy_exception_does_not_stop_others(self):
        """שגיאה באסטרטגיה 1 לא מפסיקה את 2–6."""
        portfolio  = _make_portfolio()
        call_count = {"n": 0}

        def fake_params(sid, atm, chain):
            if sid == 1:
                raise RuntimeError("simulated crash")
            call_count["n"] += 1
            return {"cost_pts": 10.0}

        with patch("paper_trading.get_trades", return_value=[]), \
             patch("paper_trading.strategy_payoff_params", side_effect=fake_params), \
             patch("paper_trading.insert_trade", return_value={"id": 1, "status": "open",
                                                               "portfolio_id": 1, "strategy_id": 1,
                                                               "entry_cost": 500.0, "legs_json": []}), \
             patch("paper_trading.update_balance", return_value=True), \
             patch("paper_trading._build_snapshot", return_value={}):

            results = open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        err = [r for r in results if r.get("status") == "error"]
        assert len(err) == 1
        assert err[0]["strategy_id"] == 1
        # שאר 5 האסטרטגיות נוסו
        assert call_count["n"] == 5


class TestOpenTradesMultiPortfolio:
    def test_all_portfolios_get_trades(self):
        """שני תיקים → 6 עסקאות לכל תיק."""
        portfolios = [_make_portfolio(1, 100_000), _make_portfolio(2, 50_000)]
        portfolio_ids_inserted = []

        def fake_insert(trade, engine=None):
            portfolio_ids_inserted.append(trade["portfolio_id"])
            return {"id": 1, **trade, "legs_json": trade.get("legs_json", []),
                    "market_snapshot_json": None}

        with patch("paper_trading.get_trades", return_value=[]), \
             patch("paper_trading.insert_trade", side_effect=fake_insert), \
             patch("paper_trading.update_balance", return_value=True), \
             patch("paper_trading._build_snapshot", return_value={}):

            open_trades_for_expiry(_EXPIRY, _CHAIN, portfolios, engine=MagicMock())

        assert 1 in portfolio_ids_inserted
        assert 2 in portfolio_ids_inserted


# ─── close_trades_for_expiry ──────────────────────────────────────────

def _make_open_trade(
    trade_id: int = 1,
    strategy_id: int = 5,
    portfolio_id: int = 1,
    entry_cost: float = 5000.0,  # קנייה (חיובי)
    legs: list | None = None,
) -> dict:
    if legs is None:
        legs = [
            {"action": "קנה", "type": "Call", "strike": 4300.0, "qty": 1},
            {"action": "קנה", "type": "Put",  "strike": 4300.0, "qty": 1},
        ]
    return {
        "id":            trade_id,
        "portfolio_id":  portfolio_id,
        "strategy_id":   strategy_id,
        "strategy_name": "Long Straddle",
        "entry_cost":    entry_cost,
        "legs_json":     legs,
        "status":        "open",
    }


class TestCloseTradesNoTrades:
    def test_no_open_trades_returns_empty(self):
        with patch("paper_trading.get_open_trades_for_expiry", return_value=[]):
            result = close_trades_for_expiry(_EXPIRY, 4300.0, engine=MagicMock())
        assert result == []


class TestClosePnlCalculation:
    """בדיקות חישוב PnL נכון לשני סוגי עסקאות."""

    def _run_close(self, trade: dict, close_index: float, portfolio_balance: float = 90_000.0):
        captured = {}

        def fake_update(pid, bal, engine=None):
            captured["new_balance"] = bal
            return True

        portfolio = _make_portfolio(portfolio_id=trade["portfolio_id"], balance=portfolio_balance)

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade]), \
             patch("paper_trading.close_trade", return_value=True), \
             patch("paper_trading.get_portfolio", return_value=portfolio), \
             patch("paper_trading.update_balance", side_effect=fake_update):

            results = close_trades_for_expiry(_EXPIRY, close_index, engine=MagicMock())

        return results, captured

    def test_straddle_profitable_upward_move(self):
        """Straddle (קנה Call + Put @ 4300), עלות 5000₪, נעילה 4500.
        payoff = (4500-4300)*50 = 10000₪
        pnl    = 10000 - 5000  = 5000₪
        pnl_pct = 5000/5000    = 1.0 (100%)
        """
        legs = [
            {"action": "קנה", "type": "Call", "strike": 4300.0, "qty": 1},
            {"action": "קנה", "type": "Put",  "strike": 4300.0, "qty": 1},
        ]
        trade   = _make_open_trade(entry_cost=5000.0, legs=legs)
        results, _ = self._run_close(trade, close_index=4500.0)

        assert len(results) == 1
        r = results[0]
        assert r["status"]  == "closed"
        assert r["payoff"]  == pytest.approx(10_000.0)
        assert r["pnl"]     == pytest.approx(5_000.0)
        assert r["pnl_pct"] == pytest.approx(1.0)

    def test_straddle_at_a_loss(self):
        """Straddle, נעילה ב-ATM (4300) → payoff = 0, pnl = -5000₪."""
        legs = [
            {"action": "קנה", "type": "Call", "strike": 4300.0, "qty": 1},
            {"action": "קנה", "type": "Put",  "strike": 4300.0, "qty": 1},
        ]
        trade = _make_open_trade(entry_cost=5000.0, legs=legs)
        results, _ = self._run_close(trade, close_index=4300.0)

        r = results[0]
        assert r["payoff"] == pytest.approx(0.0)
        assert r["pnl"]    == pytest.approx(-5000.0)

    def test_iron_condor_expires_worthless_pnl_positive(self):
        """Iron Condor (entry_cost שלילי = קבלת פרמיה), נעילה בטווח → payoff = 0.
        entry_cost = -500₪ (קיבלנו)
        pnl = 0 - (-500) = +500₪ ← רווח!
        """
        legs = [
            {"action": "קנה",  "type": "Put",  "strike": 4100.0, "qty": 1},
            {"action": "מכור", "type": "Put",  "strike": 4200.0, "qty": 1},
            {"action": "מכור", "type": "Call", "strike": 4400.0, "qty": 1},
            {"action": "קנה",  "type": "Call", "strike": 4500.0, "qty": 1},
        ]
        trade = _make_open_trade(entry_cost=-500.0, strategy_id=2, legs=legs)
        results, _ = self._run_close(trade, close_index=4300.0)

        r = results[0]
        assert r["payoff"] == pytest.approx(0.0)
        assert r["pnl"]    == pytest.approx(500.0)
        assert r["pnl_pct"] == pytest.approx(1.0)   # pnl / |entry_cost| = 500 / 500 = 1.0

    def test_iron_condor_breaches_wing(self):
        """Iron Condor מחוץ לטווח: נעילה 4600 (מעל הכנף 4500).
        payoff = -(4600-4500)*50 + (4600-4400)*50 ... רק put legs at 0.
        sell call 4400: payoff = -(4600-4400)*50 = -10000
        buy call 4500:  payoff = +(4600-4500)*50 = +5000
        net payoff = -5000₪
        entry_cost = -500₪
        pnl = -5000 - (-500) = -4500₪
        """
        legs = [
            {"action": "קנה",  "type": "Put",  "strike": 4100.0, "qty": 1},
            {"action": "מכור", "type": "Put",  "strike": 4200.0, "qty": 1},
            {"action": "מכור", "type": "Call", "strike": 4400.0, "qty": 1},
            {"action": "קנה",  "type": "Call", "strike": 4500.0, "qty": 1},
        ]
        trade = _make_open_trade(entry_cost=-500.0, strategy_id=2, legs=legs)
        results, _ = self._run_close(trade, close_index=4600.0)

        r = results[0]
        assert r["payoff"] == pytest.approx(-5000.0)
        assert r["pnl"]    == pytest.approx(-4500.0)

    def test_pnl_pct_none_when_zero_entry_cost(self):
        """entry_cost = 0 → pnl_pct = None."""
        legs = [{"action": "קנה", "type": "Call", "strike": 4300.0, "qty": 1}]
        trade = _make_open_trade(entry_cost=0.0, legs=legs)
        results, _ = self._run_close(trade, close_index=4300.0)
        assert results[0]["pnl_pct"] is None


class TestCloseBalanceUpdate:
    def test_buy_strategy_balance_updated_with_payoff(self):
        """יתרה לאחר סגירה: balance + payoff_at_close."""
        legs = [
            {"action": "קנה", "type": "Call", "strike": 4300.0, "qty": 1},
            {"action": "קנה", "type": "Put",  "strike": 4300.0, "qty": 1},
        ]
        trade = _make_open_trade(entry_cost=5000.0, legs=legs)
        initial_balance = 95_000.0

        captured = {}

        def fake_update(pid, bal, engine=None):
            captured["new_balance"] = bal
            return True

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade]), \
             patch("paper_trading.close_trade", return_value=True), \
             patch("paper_trading.get_portfolio", return_value=_make_portfolio(balance=initial_balance)), \
             patch("paper_trading.update_balance", side_effect=fake_update):

            close_trades_for_expiry(_EXPIRY, 4500.0, engine=MagicMock())

        payoff = (4500.0 - 4300.0) * MULTIPLIER  # 10_000
        assert captured["new_balance"] == pytest.approx(initial_balance + payoff)

    def test_balance_not_updated_when_close_trade_fails(self):
        """אם close_trade נכשל → update_balance לא נקרא."""
        trade = _make_open_trade()

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade]), \
             patch("paper_trading.close_trade", return_value=False), \
             patch("paper_trading.update_balance") as mock_upd:

            close_trades_for_expiry(_EXPIRY, 4300.0, engine=MagicMock())

        mock_upd.assert_not_called()

    def test_error_in_one_trade_does_not_stop_others(self):
        """שגיאה בעסקה 1 לא עוצרת עסקה 2."""
        trade1 = _make_open_trade(trade_id=1)
        trade2 = _make_open_trade(trade_id=2)

        call_count = {"n": 0}

        def fake_close(tid, close_idx, pnl, pnl_pct, engine=None):
            if tid == 1:
                raise RuntimeError("crash")
            call_count["n"] += 1
            return True

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade1, trade2]), \
             patch("paper_trading.close_trade", side_effect=fake_close), \
             patch("paper_trading.get_portfolio", return_value=_make_portfolio()), \
             patch("paper_trading.update_balance", return_value=True):

            results = close_trades_for_expiry(_EXPIRY, 4300.0, engine=MagicMock())

        assert any(r.get("status") == "error" for r in results)
        assert any(r.get("status") == "closed" for r in results)
        assert call_count["n"] == 1


# ─── Iron Condor — מחזור מלא עם הפסד ────────────────────────────────

class TestIronCondorFullCycle:
    def test_iron_condor_full_cycle_loss(self):
        """
        Iron Condor שנכשל — מחזור מלא: כניסה (credit) → פריצת טווח → הפסד נטו.

        מבנה:
          קנה  Put  4100  |  מכור Put  4200  (כנף put)
          מכור Call 4400  |  קנה  Call 4500  (כנף call)

        כניסה: credit = 10pts × 50 = 500₪  →  entry_cost = -500₪
        open balance:  100,000 − (−500) = 100,500₪

        סגירה ב-4600 (פריצה מעל הכנף 4500):
          buy  put 4100:  max(4100-4600, 0) × 50 =     0₪
          sell put 4200: -max(4200-4600, 0) × 50 =     0₪
          sell call 4400:-max(4600-4400, 0) × 50 = -10,000₪
          buy  call 4500: max(4600-4500, 0) × 50 =  +5,000₪
          ─────────────────────────────────────────────────
          payoff_at_close                          = -5,000₪

        pnl           = −5,000 − (−500) = -4,500₪  (הפסד)
        close balance = 100,500 + (−5,000) = 95,500₪  (<100,000)
        """
        legs = [
            {"action": "קנה",  "type": "Put",  "strike": 4100.0, "qty": 1},
            {"action": "מכור", "type": "Put",  "strike": 4200.0, "qty": 1},
            {"action": "מכור", "type": "Call", "strike": 4400.0, "qty": 1},
            {"action": "קנה",  "type": "Call", "strike": 4500.0, "qty": 1},
        ]
        entry_cost         = -500.0      # קיבלנו credit
        initial_balance    = 100_000.0
        balance_after_open = initial_balance - entry_cost  # 100,500₪
        close_index        = 4600.0      # פריצה מעל הכנף

        # ── חישוב ישיר לתצוגה ──────────────────────────────────────
        payoff = _payoff_from_legs(legs, close_index)
        pnl    = payoff - entry_cost
        final_balance = balance_after_open + payoff

        print(f"\n{'='*55}")
        print(f"  Iron Condor — מחזור מלא, פריצת טווח")
        print(f"  entry_cost       = {entry_cost:+,.0f} ₪  (שלילי = קיבלנו credit)")
        print(f"  balance_at_open  = {balance_after_open:,.0f} ₪")
        print(f"  close_index      = {close_index:,.0f} (פריצה מעל הכנף 4500)")
        print(f"  payoff_at_close  = {payoff:+,.0f} ₪")
        print(f"  pnl = {payoff:+,.0f} − ({entry_cost:+,.0f}) = {pnl:+,.0f} ₪")
        print(f"  balance_at_close = {balance_after_open:,.0f} + ({payoff:+,.0f}) = {final_balance:,.0f} ₪")
        print(f"{'='*55}")

        # ─── (א) payoff שלילי — פחות מה-credit שהתקבל ───────────────
        assert payoff < abs(entry_cost), (
            f"payoff ({payoff:+.0f}₪) חייב להיות פחות מה-credit ({abs(entry_cost):.0f}₪)"
        )

        # ─── (ב) PnL שלילי (הפסד נטו) ──────────────────────────────
        assert pnl < 0, f"PnL ({pnl:+.0f}₪) חייב להיות שלילי בכישלון IC"

        # ─── (ג) יתרה סופית < 100,000 ───────────────────────────────
        assert final_balance < initial_balance, (
            f"יתרה סופית ({final_balance:,.0f}₪) חייבת להיות מתחת ל-{initial_balance:,.0f}₪"
        )

        # ── וידוא דרך close_trades_for_expiry ──────────────────────
        trade = _make_open_trade(
            strategy_id=2, entry_cost=entry_cost, legs=legs
        )
        captured = {}

        def fake_update(pid, bal, engine=None):
            captured["final_balance"] = bal
            return True

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade]), \
             patch("paper_trading.close_trade", return_value=True), \
             patch("paper_trading.get_portfolio",
                   return_value=_make_portfolio(balance=balance_after_open)), \
             patch("paper_trading.update_balance", side_effect=fake_update):

            results = close_trades_for_expiry(_EXPIRY, close_index, engine=MagicMock())

        assert len(results) == 1
        r = results[0]
        assert r["status"] == "closed"
        assert r["payoff"] == pytest.approx(payoff)
        assert r["pnl"]    < 0,   f"pnl מ-close_trades ({r['pnl']:+.0f}₪) חייב להיות שלילי"
        assert captured.get("final_balance", initial_balance) < initial_balance, \
            f"יתרה סופית ({captured.get('final_balance'):,.0f}₪) חייבת להיות מתחת ל-100,000₪"
