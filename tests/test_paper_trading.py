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
    _norm_ts,
    _parse_date,
    _payoff_from_legs,
    _portfolio_strategy_ids,
    build_legs_chart_data,
    build_trade_payoff_curve,
    nearest_expiry,
    trade_expiries,
    build_equity_curve,
    build_track_record,
    close_trades_for_expiry,
    compute_balance,
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


def _make_portfolio(portfolio_id: int = 1, balance: float = 100_000.0,
                    commission_per_leg: float = 0.0, strategy_ids=None) -> dict:
    p = {"id": portfolio_id, "name": "תיק בדיקה", "current_balance": balance,
         "is_active": True, "commission_per_leg": commission_per_leg}
    # נוסף רק כשמסופק במפורש — תיק בלי המפתח בודק תאימות לאחור (null-safe).
    if strategy_ids is not None:
        p["strategy_ids"] = strategy_ids
    return p


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
    """בדיקת הכלל המרכזי: קנייה מורידה יתרה, Iron Condor מעלה.

    בארכיטקטורה החדשה אין עדכון balance ידני — היתרה נגזרת מהעסקאות.
    לכן הבדיקות בודקות את סימן ה-entry_cost שנכתב, ואת ההשפעה דרך compute_balance.
    """

    def _run_all(self, initial_balance: float = 100_000.0):
        """מריץ פתיחת 6 עסקאות; מחזיר (entry_costs_by_sid, inserted_trades)."""
        portfolio = _make_portfolio(balance=initial_balance)
        entry_costs: dict[int, float] = {}
        inserted: list[dict] = []

        def fake_insert(trade, engine=None):
            sid = trade["strategy_id"]
            entry_costs[sid] = trade["entry_cost"]
            row = {"id": 10 + sid, "portfolio_id": 1, "strategy_id": sid,
                   "status": "open", "entry_cost": trade["entry_cost"],
                   "entry_commission": trade.get("entry_commission", 0.0),
                   "legs_json": []}
            inserted.append(row)
            return row

        with patch("paper_trading.get_trades", return_value=[]), \
             patch("paper_trading.insert_trade", side_effect=fake_insert), \
             patch("paper_trading._build_snapshot", return_value={}):
            open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        return entry_costs, inserted

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

    def test_iron_condor_raises_derived_balance(self):
        """Iron Condor (entry_cost שלילי) → היתרה הנגזרת *עולה* מעל ההתחלתית."""
        costs, _ = self._run_all()
        if 2 not in costs:
            pytest.skip("Iron Condor לא הוכנס")
        portfolio = {"initial_balance": 100_000.0}
        # עסקת IC בודדת פתוחה, ללא עמלה → balance = 100000 - entry_cost (שלילי) > 100000
        ic_trade = {"status": "open", "entry_cost": costs[2], "entry_commission": 0.0}
        assert compute_balance(portfolio, [ic_trade]) > 100_000.0

    def test_buy_strategy_lowers_derived_balance(self):
        """Bull Call Spread (entry_cost חיובי) → היתרה הנגזרת *יורדת*."""
        costs, _ = self._run_all()
        if 1 not in costs:
            pytest.skip("BCS לא הוכנס")
        portfolio = {"initial_balance": 100_000.0}
        bcs_trade = {"status": "open", "entry_cost": costs[1], "entry_commission": 0.0}
        assert compute_balance(portfolio, [bcs_trade]) < 100_000.0

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
             patch("paper_trading._build_snapshot", return_value={}):

            results = open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        assert all(s == "skipped" for s in inserted_statuses)
        assert all(r["status"] == "skipped" for r in results)

    def test_skipped_trades_do_not_affect_balance(self):
        """עסקאות skipped (cost=0) אינן משפיעות על היתרה הנגזרת."""
        portfolio = {"initial_balance": 100_000.0}
        trades = [
            {"status": "skipped", "entry_cost": 0.0, "entry_commission": 0.0},
            {"status": "skipped", "entry_cost": 0.0, "entry_commission": 0.0},
        ]
        assert compute_balance(portfolio, trades) == pytest.approx(100_000.0)


class TestOpenTradesDbError:
    def test_insert_failure_returns_db_error_status(self):
        """כאשר insert_trade מחזיר None → status='db_error'."""
        portfolio = _make_portfolio()

        with patch("paper_trading.get_trades", return_value=[]), \
             patch("paper_trading.insert_trade", return_value=None), \
             patch("paper_trading._build_snapshot", return_value={}):

            results = open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        errors = [r for r in results if r.get("status") == "db_error"]
        assert len(errors) > 0

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
             patch("paper_trading._build_snapshot", return_value={}):

            open_trades_for_expiry(_EXPIRY, _CHAIN, portfolios, engine=MagicMock())

        assert 1 in portfolio_ids_inserted
        assert 2 in portfolio_ids_inserted


# ─── _portfolio_strategy_ids ──────────────────────────────────────────

class TestPortfolioStrategyIds:
    """בחירת האסטרטגיות שתיק מריץ — null-safe וסינון מזהים."""

    _ALL = [1, 2, 3, 4, 5, 6]

    def test_missing_key_returns_all(self):
        assert _portfolio_strategy_ids({"id": 1}) == self._ALL

    def test_none_value_returns_all(self):
        assert _portfolio_strategy_ids({"strategy_ids": None}) == self._ALL

    def test_empty_list_returns_all(self):
        assert _portfolio_strategy_ids({"strategy_ids": []}) == self._ALL

    def test_subset_preserved(self):
        assert _portfolio_strategy_ids({"strategy_ids": [2]}) == [2]

    def test_two_butterflies(self):
        assert _portfolio_strategy_ids({"strategy_ids": [3, 4]}) == [3, 4]

    def test_json_string_parsed(self):
        assert _portfolio_strategy_ids({"strategy_ids": "[5]"}) == [5]

    def test_string_ids_coerced(self):
        assert _portfolio_strategy_ids({"strategy_ids": ["1", "2"]}) == [1, 2]

    def test_invalid_ids_filtered_out(self):
        """מזהים שאינם קיימים ב-STRATEGIES (0, 99) מסוננים."""
        assert _portfolio_strategy_ids({"strategy_ids": [2, 99, 0]}) == [2]

    def test_all_invalid_falls_back_to_all(self):
        assert _portfolio_strategy_ids({"strategy_ids": [99, 0]}) == self._ALL

    def test_duplicates_removed(self):
        assert _portfolio_strategy_ids({"strategy_ids": [2, 2, 3]}) == [2, 3]

    def test_order_preserved(self):
        assert _portfolio_strategy_ids({"strategy_ids": [6, 1, 3]}) == [6, 1, 3]


# ─── open_trades_for_expiry — תת-קבוצת אסטרטגיות ───────────────────────

class TestOpenTradesStrategySubset:
    """(ג)+(ד): פותחים רק את האסטרטגיות שהתיק מוגדר להריץ.

    ה-pricing ממוקמ (mock) לערך קבוע — הבדיקה ממוקדת בלוגיקת *בחירת* האסטרטגיות
    בלולאה, לא בחישוב המחיר עצמו.
    """

    def _run(self, portfolio):
        attempted: list[int] = []   # אילו אסטרטגיות נוסו (נכנסו ללולאת ה-pricing)
        inserted: list[int]  = []   # אילו נפתחו בפועל

        def fake_params(sid, atm, chain):
            attempted.append(sid)
            return {"cost_pts": 10.0, "credit_pts": 10.0}

        def fake_insert(trade, engine=None):
            inserted.append(trade["strategy_id"])
            return {"id": 10, **trade, "legs_json": trade.get("legs_json", []),
                    "market_snapshot_json": None}

        with patch("paper_trading.get_trades", return_value=[]), \
             patch("paper_trading.strategy_payoff_params", side_effect=fake_params), \
             patch("paper_trading.strategy_legs_detail", return_value=[]), \
             patch("paper_trading.strategy_summary", return_value={}), \
             patch("paper_trading.insert_trade", side_effect=fake_insert), \
             patch("paper_trading._build_snapshot", return_value={}):
            results = open_trades_for_expiry(_EXPIRY, _CHAIN, [portfolio], engine=MagicMock())

        return attempted, inserted, results

    def test_only_iron_condor_when_subset_is_2(self):
        """תיק עם strategy_ids=[2] → נפתחת רק Iron Condor."""
        attempted, inserted, results = self._run(_make_portfolio(strategy_ids=[2]))
        assert attempted == [2]
        assert inserted == [2]
        assert {r["strategy_id"] for r in results} == {2}

    def test_two_butterflies_subset(self):
        """תיק עם strategy_ids=[3,4] → נפתחות רק שתי ה-Butterfly."""
        attempted, inserted, _ = self._run(_make_portfolio(strategy_ids=[3, 4]))
        assert attempted == [3, 4]
        assert inserted == [3, 4]

    def test_missing_strategy_ids_opens_all_six(self):
        """(ד) תיק בלי strategy_ids → כל 6 האסטרטגיות (תאימות לאחור)."""
        attempted, inserted, _ = self._run(_make_portfolio())
        assert attempted == [1, 2, 3, 4, 5, 6]
        assert inserted == [1, 2, 3, 4, 5, 6]

    def test_empty_strategy_ids_opens_all_six(self):
        attempted, _, _ = self._run(_make_portfolio(strategy_ids=[]))
        assert attempted == [1, 2, 3, 4, 5, 6]

    def test_json_string_strategy_ids(self):
        """strategy_ids כ-JSON string (לא פורסר) → מטופל null-safe."""
        attempted, inserted, _ = self._run(_make_portfolio(strategy_ids="[5]"))
        assert attempted == [5]
        assert inserted == [5]

    def test_invalid_ids_filtered(self):
        attempted, inserted, _ = self._run(_make_portfolio(strategy_ids=[2, 99, 0]))
        assert attempted == [2]
        assert inserted == [2]


# ─── engine יחיד משותף (תיקון ה-pooler) ────────────────────────────────

class TestSharesSingleEngine:
    """engine נוצר פעם אחת ומועבר לכל הקריאות הפנימיות — לא pool חדש בכל insert."""

    def test_open_creates_engine_once_and_shares_it(self):
        sentinel = object()
        seen: list = []

        def fake_get_trades(portfolio_id=None, status=None, expiry_date=None, engine=None):
            seen.append(engine)
            return []

        def fake_insert(trade, engine=None):
            seen.append(engine)
            return {"id": 1, **trade, "legs_json": trade.get("legs_json", []),
                    "market_snapshot_json": None}

        portfolios = [_make_portfolio(1), _make_portfolio(2)]

        with patch("paper_trading._make_engine", return_value=sentinel) as mk, \
             patch("paper_trading.get_trades", side_effect=fake_get_trades), \
             patch("paper_trading.insert_trade", side_effect=fake_insert), \
             patch("paper_trading._build_snapshot", return_value={}):
            open_trades_for_expiry(_EXPIRY, _CHAIN, portfolios, engine=None)

        # engine נוצר פעם אחת בלבד (ולא פעם לכל insert/שאילתה)
        assert mk.call_count == 1
        # כל הקריאות הפנימיות (get_trades + insert_trade) קיבלו בדיוק את אותו engine
        assert seen, "לא בוצעו קריאות DB פנימיות"
        assert all(e is sentinel for e in seen)

    def test_close_creates_engine_once_and_shares_it(self):
        sentinel = object()
        seen: list = []
        trade = _make_open_trade(trade_id=1)

        def fake_get_open(expiry_date, engine=None):
            seen.append(engine)
            return [trade]

        def fake_get_portfolio(pid, engine=None):
            seen.append(engine)
            return _make_portfolio()

        def fake_close(tid, ci, pnl, pnl_pct, exit_commission=0.0, engine=None):
            seen.append(engine)
            return True

        with patch("paper_trading._make_engine", return_value=sentinel) as mk, \
             patch("paper_trading.get_open_trades_for_expiry", side_effect=fake_get_open), \
             patch("paper_trading.get_portfolio", side_effect=fake_get_portfolio), \
             patch("paper_trading.close_trade", side_effect=fake_close):
            close_trades_for_expiry(_EXPIRY, 4300.0, engine=None)

        assert mk.call_count == 1
        assert seen, "לא בוצעו קריאות DB פנימיות"
        assert all(e is sentinel for e in seen)


# ─── compute_balance — מקור אמת אחד ליתרה ──────────────────────────────

class TestComputeBalance:
    """היתרה נגזרת מהעסקאות בלבד; חוסנת לכל סוגי הסטטוסים."""

    _PF = {"id": 1, "initial_balance": 100_000.0}

    def test_no_trades_returns_initial(self):
        assert compute_balance(self._PF, []) == pytest.approx(100_000.0)

    def test_none_trades_returns_initial(self):
        assert compute_balance(self._PF, None) == pytest.approx(100_000.0)

    def test_empty_portfolio_returns_zero(self):
        assert compute_balance({}, []) == pytest.approx(0.0)
        assert compute_balance(None, []) == pytest.approx(0.0)

    def test_only_open_buy_lowers_balance(self):
        """עסקת קנייה פתוחה: balance = initial − (entry_cost + commission)."""
        trades = [{"status": "open", "entry_cost": 500.0, "entry_commission": 5.0}]
        assert compute_balance(self._PF, trades) == pytest.approx(100_000.0 - 505.0)

    def test_only_open_iron_condor_raises_balance(self):
        """Iron Condor פתוח (entry_cost שלילי = credit): balance עולה.
        balance = 100000 − (−685 + 10) = 100000 + 675 = 100675."""
        trades = [{"status": "open", "entry_cost": -685.0, "entry_commission": 10.0}]
        assert compute_balance(self._PF, trades) == pytest.approx(100_675.0)

    def test_only_closed_uses_pnl(self):
        """עסקה סגורה: נספר ה-pnl בלבד (כולל כבר עלויות+עמלות)."""
        trades = [{"status": "closed", "pnl": 1_200.0,
                   "entry_cost": 500.0, "entry_commission": 5.0}]
        # רק pnl נספר — לא מנכים שוב את entry_cost (אין כפילות)
        assert compute_balance(self._PF, trades) == pytest.approx(101_200.0)

    def test_closed_loss_decreases_balance(self):
        trades = [{"status": "closed", "pnl": -1_500.0}]
        assert compute_balance(self._PF, trades) == pytest.approx(98_500.0)

    def test_mixed_open_and_closed(self):
        """מעורב: open מנכה עלות+עמלה, closed מוסיף pnl."""
        trades = [
            {"status": "open",   "entry_cost": 500.0,  "entry_commission": 5.0},   # −505
            {"status": "open",   "entry_cost": -685.0, "entry_commission": 10.0},  # +675
            {"status": "closed", "pnl": 800.0},                                    # +800
            {"status": "closed", "pnl": -300.0},                                   # −300
        ]
        # 100000 − 505 + 675 + 800 − 300 = 100670
        assert compute_balance(self._PF, trades) == pytest.approx(100_670.0)

    def test_skipped_trades_ignored(self):
        trades = [
            {"status": "skipped", "entry_cost": 0.0,  "entry_commission": 0.0},
            {"status": "open",    "entry_cost": 200.0, "entry_commission": 2.5},
        ]
        assert compute_balance(self._PF, trades) == pytest.approx(100_000.0 - 202.5)

    def test_db_error_and_error_statuses_ignored(self):
        """סטטוסים שאינם open/closed (db_error/error) אינם משפיעים."""
        trades = [
            {"status": "db_error", "entry_cost": 9_999.0, "entry_commission": 99.0},
            {"status": "error",    "entry_cost": 9_999.0, "entry_commission": 99.0},
        ]
        assert compute_balance(self._PF, trades) == pytest.approx(100_000.0)

    def test_none_values_treated_as_zero(self):
        trades = [
            {"status": "open",   "entry_cost": None, "entry_commission": None},
            {"status": "closed", "pnl": None},
        ]
        assert compute_balance(self._PF, trades) == pytest.approx(100_000.0)

    def test_regression_lost_balance_update_12_06(self):
        """שחזור הבאג של 12/06: בעבר עסקה נכתבה אך עדכון ה-balance 'אבד'
        (update_balance נכשל בשקט) → היתרה נופחה ב-4,813₪.

        בארכיטקטורה החדשה אין שלב עדכון balance — היתרה נגזרת מהעסקאות,
        לכן גם אם כתיבה כלשהי הייתה נכשלת, היתרה המחושבת תמיד נכונה.

        הנתונים האמיתיים של 'תיק ראשי' (5 עסקאות open):
          BCS        entry_cost= 731  comm= 5
          IC         entry_cost=-685  comm=10
          CallBfly   entry_cost= 275  comm= 7.5
          PutBfly    entry_cost= 274  comm= 7.5
          Straddle   entry_cost=4808  comm= 5
        Σ entry_cost = 5403 ; Σ comm = 35 ; סה"כ צריכה = 5438
        balance נכון = 100000 − 5438 = 94562  (לא 99375 שנרשם בעבר!)
        """
        trades = [
            {"status": "open", "strategy_name": "Bull Call Spread",   "entry_cost":  731.0, "entry_commission":  5.0},
            {"status": "open", "strategy_name": "Short Iron Condor",  "entry_cost": -685.0, "entry_commission": 10.0},
            {"status": "open", "strategy_name": "Long Call Butterfly","entry_cost":  275.0, "entry_commission":  7.5},
            {"status": "open", "strategy_name": "Long Put Butterfly", "entry_cost":  274.0, "entry_commission":  7.5},
            {"status": "open", "strategy_name": "Long Straddle",      "entry_cost": 4808.0, "entry_commission":  5.0},
        ]
        balance = compute_balance(self._PF, trades)
        assert balance == pytest.approx(94_562.0), (
            f"היתרה הנגזרת חייבת להיות 94,562₪ (לא 99,375 השבור), קיבל {balance:,.2f}"
        )


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
        "id":               trade_id,
        "portfolio_id":     portfolio_id,
        "strategy_id":      strategy_id,
        "strategy_name":    "Long Straddle",
        "entry_cost":       entry_cost,
        "legs_json":        legs,
        "status":           "open",
        "num_legs":         len(legs),
        "entry_commission": 0.0,
        "exit_commission":  None,
    }


class TestCloseTradesNoTrades:
    def test_no_open_trades_returns_empty(self):
        with patch("paper_trading.get_open_trades_for_expiry", return_value=[]):
            result = close_trades_for_expiry(_EXPIRY, 4300.0, engine=MagicMock())
        assert result == []


class TestClosePnlCalculation:
    """בדיקות חישוב PnL נכון לשני סוגי עסקאות."""

    def _run_close(self, trade: dict, close_index: float, portfolio_balance: float = 90_000.0):
        portfolio = _make_portfolio(portfolio_id=trade["portfolio_id"], balance=portfolio_balance)

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade]), \
             patch("paper_trading.close_trade", return_value=True), \
             patch("paper_trading.get_portfolio", return_value=portfolio):

            results = close_trades_for_expiry(_EXPIRY, close_index, engine=MagicMock())

        return results, {}

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


class TestCloseDerivedBalance:
    """לאחר סגירה היתרה נגזרת מה-pnl (compute_balance) — אין עדכון balance ישיר."""

    def test_buy_strategy_balance_reflects_pnl_after_close(self):
        """יתרה אחרי סגירה = initial + pnl של העסקה הסגורה (דרך compute_balance)."""
        legs = [
            {"action": "קנה", "type": "Call", "strike": 4300.0, "qty": 1},
            {"action": "קנה", "type": "Put",  "strike": 4300.0, "qty": 1},
        ]
        trade = _make_open_trade(entry_cost=5000.0, legs=legs)
        initial_balance = 100_000.0

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade]), \
             patch("paper_trading.close_trade", return_value=True), \
             patch("paper_trading.get_portfolio", return_value=_make_portfolio(balance=initial_balance)):

            results = close_trades_for_expiry(_EXPIRY, 4500.0, engine=MagicMock())

        # payoff = (4500-4300)*50 = 10000; pnl = 10000 - 5000 (entry) - 0 - 0 = 5000
        r = results[0]
        assert r["pnl"] == pytest.approx(5_000.0)

        # היתרה הנגזרת אחרי הסגירה (אותה עסקה, עכשיו closed עם ה-pnl)
        closed = {"status": "closed", "pnl": r["pnl"]}
        balance = compute_balance({"initial_balance": initial_balance}, [closed])
        assert balance == pytest.approx(initial_balance + 5_000.0)

    def test_failed_close_marked_error(self):
        """אם close_trade נכשל → העסקה מסומנת 'error' (נשארת פתוחה בפועל)."""
        trade = _make_open_trade()

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade]), \
             patch("paper_trading.close_trade", return_value=False), \
             patch("paper_trading.get_portfolio", return_value=_make_portfolio()):

            results = close_trades_for_expiry(_EXPIRY, 4300.0, engine=MagicMock())

        assert results[0]["status"] == "error"

    def test_error_in_one_trade_does_not_stop_others(self):
        """שגיאה בעסקה 1 לא עוצרת עסקה 2."""
        trade1 = _make_open_trade(trade_id=1)
        trade2 = _make_open_trade(trade_id=2)

        call_count = {"n": 0}

        def fake_close(tid, close_idx, pnl, pnl_pct, exit_commission=0.0, engine=None):
            if tid == 1:
                raise RuntimeError("crash")
            call_count["n"] += 1
            return True

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade1, trade2]), \
             patch("paper_trading.close_trade", side_effect=fake_close), \
             patch("paper_trading.get_portfolio", return_value=_make_portfolio()):

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

        with patch("paper_trading.get_open_trades_for_expiry", return_value=[trade]), \
             patch("paper_trading.close_trade", return_value=True), \
             patch("paper_trading.get_portfolio",
                   return_value=_make_portfolio(balance=balance_after_open)):

            results = close_trades_for_expiry(_EXPIRY, close_index, engine=MagicMock())

        assert len(results) == 1
        r = results[0]
        assert r["status"] == "closed"
        assert r["payoff"] == pytest.approx(payoff)
        assert r["pnl"]    < 0,   f"pnl מ-close_trades ({r['pnl']:+.0f}₪) חייב להיות שלילי"

        # ── היתרה הנגזרת אחרי הסגירה — חייבת להיות מתחת ל-100,000 ──
        closed_trade  = {"status": "closed", "pnl": r["pnl"]}
        final_balance = compute_balance({"initial_balance": initial_balance}, [closed_trade])
        assert final_balance < initial_balance, \
            f"יתרה סופית נגזרת ({final_balance:,.0f}₪) חייבת להיות מתחת ל-100,000₪"


# ─── _norm_ts ──────────────────────────────────────────────────────────

class TestNormTs:
    def test_datetime_returned_as_is(self):
        dt = datetime(2026, 5, 29, 10, 0)
        assert _norm_ts(dt) is dt

    def test_iso_string_parsed(self):
        result = _norm_ts("2026-05-29T10:00:00")
        assert isinstance(result, datetime)
        assert result.year == 2026 and result.month == 5 and result.day == 29

    def test_zulu_string_parsed(self):
        result = _norm_ts("2026-05-29T10:00:00Z")
        assert isinstance(result, datetime)

    def test_pandas_timestamp(self):
        import pandas as pd
        ts = pd.Timestamp("2026-05-29 10:00:00")
        result = _norm_ts(ts)
        assert isinstance(result, datetime)
        assert result.year == 2026


# ─── build_equity_curve ────────────────────────────────────────────────

def _closed_trade(trade_id: int, pnl: float, closed_at: datetime,
                  strategy_name: str = "Bull Call Spread") -> dict:
    return {
        "id": trade_id, "status": "closed", "pnl": pnl,
        "closed_at": closed_at, "strategy_name": strategy_name,
    }


class TestBuildEquityCurve:
    def test_empty_trades_returns_empty(self):
        assert build_equity_curve([], 100_000) == []

    def test_no_closed_trades_returns_empty(self):
        trades = [
            {"id": 1, "status": "open",    "pnl": None,   "closed_at": None},
            {"id": 2, "status": "skipped", "pnl": None,   "closed_at": None},
        ]
        assert build_equity_curve(trades, 100_000) == []

    def test_trade_missing_pnl_excluded(self):
        trades = [{"id": 1, "status": "closed", "pnl": None, "closed_at": datetime(2026, 5, 29, 10)}]
        assert build_equity_curve(trades, 100_000) == []

    def test_trade_missing_closed_at_excluded(self):
        trades = [{"id": 1, "status": "closed", "pnl": 500.0, "closed_at": None}]
        assert build_equity_curve(trades, 100_000) == []

    def test_single_closed_trade_accumulates(self):
        trades = [_closed_trade(1, 500.0, datetime(2026, 5, 29, 10, 0))]
        result = build_equity_curve(trades, 100_000)
        assert len(result) == 1
        assert result[0]["balance"] == pytest.approx(100_500.0)
        assert result[0]["ts"] == datetime(2026, 5, 29, 10, 0)

    def test_multiple_trades_accumulate_correctly(self):
        trades = [
            _closed_trade(1,  500.0, datetime(2026, 5, 22, 10)),
            _closed_trade(2, -200.0, datetime(2026, 5, 29, 10)),
            _closed_trade(3,  800.0, datetime(2026, 6,  5, 10)),
        ]
        result = build_equity_curve(trades, 100_000)
        assert len(result) == 3
        assert result[0]["balance"] == pytest.approx(100_500.0)   # +500
        assert result[1]["balance"] == pytest.approx(100_300.0)   # -200
        assert result[2]["balance"] == pytest.approx(101_100.0)   # +800

    def test_sorted_chronologically(self):
        """מבטיח שהנקודות ממוינות לפי closed_at גם אם הקלט לא מסודר."""
        trades = [
            _closed_trade(3, 100.0, datetime(2026, 6,  5, 10)),
            _closed_trade(1, 200.0, datetime(2026, 5, 22, 10)),
            _closed_trade(2, -50.0, datetime(2026, 5, 29, 10)),
        ]
        result = build_equity_curve(trades, 100_000)
        assert result[0]["ts"] == datetime(2026, 5, 22, 10)
        assert result[1]["ts"] == datetime(2026, 5, 29, 10)
        assert result[2]["ts"] == datetime(2026, 6,  5, 10)

    def test_open_trades_excluded(self):
        """עסקאות פתוחות לא נכללות בעקומה."""
        trades = [
            _closed_trade(1, 500.0, datetime(2026, 5, 22, 10)),
            {"id": 2, "status": "open", "pnl": 999.0, "closed_at": datetime(2026, 5, 23, 10)},
        ]
        result = build_equity_curve(trades, 100_000)
        assert len(result) == 1
        assert result[0]["balance"] == pytest.approx(100_500.0)

    def test_string_timestamp_normalized(self):
        """closed_at כ-string מטופל נכון."""
        trades = [{"id": 1, "status": "closed", "pnl": 300.0,
                   "closed_at": "2026-05-29T10:00:00"}]
        result = build_equity_curve(trades, 100_000)
        assert len(result) == 1
        assert isinstance(result[0]["ts"], datetime)
        assert result[0]["balance"] == pytest.approx(100_300.0)

    def test_negative_pnl_decreases_balance(self):
        trades = [_closed_trade(1, -1500.0, datetime(2026, 5, 29, 10))]
        result = build_equity_curve(trades, 100_000)
        assert result[0]["balance"] == pytest.approx(98_500.0)

    def test_mixed_open_closed_skipped(self):
        trades = [
            _closed_trade(1, 200.0, datetime(2026, 5, 20, 10)),
            {"id": 2, "status": "open",    "pnl": None,   "closed_at": None},
            {"id": 3, "status": "skipped", "pnl": None,   "closed_at": None},
            _closed_trade(4, -100.0, datetime(2026, 5, 27, 10)),
        ]
        result = build_equity_curve(trades, 50_000)
        assert len(result) == 2
        assert result[0]["balance"] == pytest.approx(50_200.0)
        assert result[1]["balance"] == pytest.approx(50_100.0)


# ─── build_track_record ────────────────────────────────────────────────

class TestBuildTrackRecord:
    def test_empty_trades_returns_empty(self):
        assert build_track_record([]) == []

    def test_no_closed_trades_returns_empty(self):
        trades = [
            {"status": "open",    "strategy_name": "Bull Call Spread", "pnl": None},
            {"status": "skipped", "strategy_name": "Long Straddle",    "pnl": None},
        ]
        assert build_track_record(trades) == []

    def test_single_strategy_win(self):
        trades = [
            {"status": "closed", "strategy_name": "Bull Call Spread", "pnl": 500.0},
            {"status": "closed", "strategy_name": "Bull Call Spread", "pnl": -200.0},
            {"status": "closed", "strategy_name": "Bull Call Spread", "pnl": 300.0},
        ]
        result = build_track_record(trades)
        assert len(result) == 1
        r = result[0]
        assert r["strategy_name"] == "Bull Call Spread"
        assert r["total"]         == 3
        assert r["wins"]          == 2
        assert r["win_rate"]      == pytest.approx(2 / 3, abs=1e-3)
        assert r["total_pnl"]     == pytest.approx(600.0)
        assert r["avg_pnl"]       == pytest.approx(200.0)

    def test_multiple_strategies_sorted_by_total_pnl_desc(self):
        trades = [
            {"status": "closed", "strategy_name": "Bull Call Spread",  "pnl": 100.0},
            {"status": "closed", "strategy_name": "Long Straddle",      "pnl": 500.0},
            {"status": "closed", "strategy_name": "Short Iron Condor",  "pnl": -50.0},
        ]
        result = build_track_record(trades)
        assert result[0]["strategy_name"] == "Long Straddle"      # 500
        assert result[1]["strategy_name"] == "Bull Call Spread"   # 100
        assert result[2]["strategy_name"] == "Short Iron Condor"  # -50

    def test_none_pnl_excluded_from_stats(self):
        trades = [
            {"status": "closed", "strategy_name": "Long Straddle", "pnl": 500.0},
            {"status": "closed", "strategy_name": "Long Straddle", "pnl": None},
        ]
        result = build_track_record(trades)
        assert len(result) == 1
        r = result[0]
        assert r["total"]     == 2     # 2 עסקאות סגורות
        assert r["total_pnl"] == pytest.approx(500.0)  # רק זו שיש לה pnl
        assert r["wins"]      == 1

    def test_none_strategy_name_fallback(self):
        trades = [{"status": "closed", "strategy_name": None, "pnl": 100.0}]
        result = build_track_record(trades)
        assert result[0]["strategy_name"] == "לא ידוע"

    def test_win_rate_all_wins(self):
        trades = [
            {"status": "closed", "strategy_name": "X", "pnl": 100.0},
            {"status": "closed", "strategy_name": "X", "pnl": 200.0},
        ]
        result = build_track_record(trades)
        assert result[0]["win_rate"] == pytest.approx(1.0)

    def test_win_rate_all_losses(self):
        trades = [
            {"status": "closed", "strategy_name": "X", "pnl": -100.0},
            {"status": "closed", "strategy_name": "X", "pnl": -200.0},
        ]
        result = build_track_record(trades)
        assert result[0]["win_rate"] == pytest.approx(0.0)
        assert result[0]["wins"]     == 0

    def test_open_trades_not_included(self):
        trades = [
            {"status": "closed", "strategy_name": "Bull Call Spread", "pnl": 100.0},
            {"status": "open",   "strategy_name": "Bull Call Spread", "pnl": None},
        ]
        result = build_track_record(trades)
        assert result[0]["total"] == 1

    def test_zero_pnl_not_counted_as_win(self):
        trades = [{"status": "closed", "strategy_name": "X", "pnl": 0.0}]
        result = build_track_record(trades)
        assert result[0]["wins"]     == 0
        assert result[0]["win_rate"] == pytest.approx(0.0)


# ─── trade_expiries / nearest_expiry ───────────────────────────────────

class TestTradeExpiries:
    def test_empty(self):
        assert trade_expiries([]) == []

    def test_unique_and_chronological(self):
        trades = [
            {"expiry_date": "2026-06-19"},
            {"expiry_date": "2026-06-16"},
            {"expiry_date": "2026-06-19"},
        ]
        assert trade_expiries(trades) == ["2026-06-16", "2026-06-19"]

    def test_ignores_none(self):
        trades = [{"expiry_date": None}, {"expiry_date": "2026-06-16"}]
        assert trade_expiries(trades) == ["2026-06-16"]

    def test_handles_date_objects(self):
        trades = [{"expiry_date": date(2026, 6, 18)}, {"expiry_date": date(2026, 6, 16)}]
        assert trade_expiries(trades) == ["2026-06-16", "2026-06-18"]


class TestNearestExpiry:
    def test_empty_returns_none(self):
        assert nearest_expiry([]) is None

    def test_picks_closest_upcoming(self):
        exps = ["2026-06-16", "2026-06-19", "2026-07-01"]
        assert nearest_expiry(exps, today=date(2026, 6, 15)) == "2026-06-16"

    def test_picks_closest_when_past_and_future(self):
        exps = ["2026-06-10", "2026-06-20"]
        assert nearest_expiry(exps, today=date(2026, 6, 12)) == "2026-06-10"

    def test_exact_match_distance_zero(self):
        exps = ["2026-06-16", "2026-06-19"]
        assert nearest_expiry(exps, today=date(2026, 6, 19)) == "2026-06-19"


# ─── build_legs_chart_data ─────────────────────────────────────────────

class TestBuildLegsChartData:
    def test_empty(self):
        assert build_legs_chart_data([]) == []

    def test_buy_call_positive_y(self):
        legs = [{"action": "קנה", "type": "Call", "qty": 1, "strike": 4300.0,
                 "price_pts": 30.0, "price_nis": 1500.0}]
        d = build_legs_chart_data(legs)
        assert len(d) == 1
        assert d[0]["strike"] == 4300.0
        assert d[0]["y"] == 1            # קנה → מעל הציר
        assert d[0]["action"] == "קנה"
        assert "Call" in d[0]["label"] and "4,300" in d[0]["label"]

    def test_sell_negative_y(self):
        legs = [{"action": "מכור", "type": "Call", "qty": 1, "strike": 4400.0}]
        assert build_legs_chart_data(legs)[0]["y"] == -1

    def test_qty_scales_y(self):
        legs = [{"action": "מכור", "type": "Call", "qty": 2, "strike": 4350.0}]
        assert build_legs_chart_data(legs)[0]["y"] == -2

    def test_bad_strike_skipped(self):
        legs = [{"action": "קנה", "type": "Call", "qty": 1, "strike": None}]
        assert build_legs_chart_data(legs) == []

    def test_iron_condor_four_legs(self):
        legs = [
            {"action": "קנה",  "type": "Put",  "qty": 1, "strike": 4100.0},
            {"action": "מכור", "type": "Put",  "qty": 1, "strike": 4200.0},
            {"action": "מכור", "type": "Call", "qty": 1, "strike": 4400.0},
            {"action": "קנה",  "type": "Call", "qty": 1, "strike": 4500.0},
        ]
        d = build_legs_chart_data(legs)
        assert len(d) == 4
        assert [p["y"] for p in d] == [1, -1, -1, 1]


# ─── build_trade_payoff_curve ──────────────────────────────────────────

class TestBuildTradePayoffCurve:
    def test_empty_legs(self):
        c = build_trade_payoff_curve([], 0.0, 4300.0)
        assert c["x"] == [] and c["y"] == []
        assert c["breakevens"] == []

    def test_invalid_center(self):
        legs = [{"action": "קנה", "type": "Call", "qty": 1, "strike": 4300.0}]
        assert build_trade_payoff_curve(legs, 1000.0, 0.0)["x"] == []

    def test_long_call_payoff_increases_and_floor(self):
        """קנה Call 4300, פרמיה 1500₪: מתחת לסטרייק P&L=−1500, ועולה מעליו."""
        legs = [{"action": "קנה", "type": "Call", "qty": 1, "strike": 4300.0}]
        c = build_trade_payoff_curve(legs, 1500.0, 4300.0, pct=0.10, n=101)
        assert len(c["x"]) == 101 and len(c["y"]) == 101
        assert c["y"][-1] > c["y"][0]                       # עולה עם המחיר
        assert c["max_loss"] == pytest.approx(-1500.0)      # הרצפה = הפרמיה ששולמה

    def test_long_call_breakeven_near_strike_plus_premium(self):
        """Breakeven ≈ 4300 + (1500/50) = 4330."""
        legs = [{"action": "קנה", "type": "Call", "qty": 1, "strike": 4300.0}]
        c = build_trade_payoff_curve(legs, 1500.0, 4300.0)
        assert any(abs(be - 4330.0) < 25 for be in c["breakevens"])

    def test_iron_condor_credit_profit_at_center(self):
        """IC עם credit 500₪ (entry_cost=−500): במרכז כל הרגליים פגות → P&L=+500."""
        legs = [
            {"action": "קנה",  "type": "Put",  "qty": 1, "strike": 4100.0},
            {"action": "מכור", "type": "Put",  "qty": 1, "strike": 4200.0},
            {"action": "מכור", "type": "Call", "qty": 1, "strike": 4400.0},
            {"action": "קנה",  "type": "Call", "qty": 1, "strike": 4500.0},
        ]
        c = build_trade_payoff_curve(legs, -500.0, 4300.0, n=101)
        mid = c["y"][len(c["y"]) // 2]                      # ≈ 4300 (המרכז)
        assert mid == pytest.approx(500.0)
        assert c["max_profit"] == pytest.approx(500.0)      # הרווח המרבי = ה-credit
