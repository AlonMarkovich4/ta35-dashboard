"""
בדיקות יחידה ל-vwap_pricing — תמחור רגליים במחיר עסקה אמיתי.

כל בדיקות ה-IO משתמשות ב-mock engine; אין גישה לרשת או ל-DB.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vwap_pricing import fetch_traded_quotes, price_legs, vwap  # noqa: E402


def _row(**kw) -> MagicMock:
    r = MagicMock()
    r._mapping = kw
    return r


def _engine(rows=None, raises=False) -> MagicMock:
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchall.return_value = rows or []
    eng = MagicMock()
    if raises:
        eng.connect.side_effect = Exception("db down")
    else:
        eng.connect.return_value = conn
    return eng


def _leg(action, typ, strike, qty=1) -> dict:
    return {"action": action, "type": typ, "strike": strike, "qty": qty}


# ─── vwap ───────────────────────────────────────────────────────────────

class TestVwap:
    def test_divides_value_by_units(self):
        # דוגמה אמיתית מהארכיון: 80 יחידות, 345,800 ₪ → 4,322.5
        assert vwap(80, 345800) == pytest.approx(4322.5)

    def test_no_turnover_is_none_not_zero(self):
        """אופציה שלא נסחרה אין לה מחיר עסקה. 0 היה מחיר מומצא."""
        assert vwap(0, 0) is None
        assert vwap(None, None) is None
        assert vwap(0, 5000) is None

    def test_zero_value_is_none(self):
        assert vwap(10, 0) is None

    def test_negative_is_none(self):
        assert vwap(-5, 100) is None
        assert vwap(10, -100) is None

    def test_non_numeric_is_none(self):
        assert vwap("שלום", 100) is None
        assert vwap(10, object()) is None


# ─── price_legs ─────────────────────────────────────────────────────────

class TestPriceLegs:
    QUOTES = {("Put", 4030.0): 100.0, ("Put", 4060.0): 250.0,
              ("Call", 4200.0): 240.0, ("Call", 4230.0): 90.0}

    def _condor(self):
        return [_leg("קנה", "Put", 4030.0), _leg("מכור", "Put", 4060.0),
                _leg("מכור", "Call", 4200.0), _leg("קנה", "Call", 4230.0)]

    def test_complete_condor_prices_all_four(self):
        r = price_legs(self._condor(), self.QUOTES)
        assert r.complete is True
        assert r.missing == []
        assert len(r.legs) == 4

    def test_entry_cost_is_credit_for_a_short_condor(self):
        """קונים 100+90, מוכרים 250+240 ⇒ זיכוי 300 ⇒ entry_cost שלילי."""
        r = price_legs(self._condor(), self.QUOTES)
        assert r.entry_cost == pytest.approx(100 + 90 - 250 - 240)
        assert r.entry_cost < 0

    def test_one_untraded_leg_blocks_the_whole_trade(self):
        """זו כל הנקודה: 3/4 רגליים אינן עסקה מדידה."""
        quotes = dict(self.QUOTES)
        del quotes[("Call", 4200.0)]
        r = price_legs(self._condor(), quotes)
        assert r.complete is False
        assert r.entry_cost is None
        assert [m["strike"] for m in r.missing] == [4200.0]

    def test_missing_carries_a_reason(self):
        r = price_legs(self._condor(), {})
        assert len(r.missing) == 4
        assert all(m["reason"] for m in r.missing)

    def test_price_source_is_marked(self):
        """כדי שאפשר יהיה להבדיל בארכיון בין מילוי VWAP למילוי ישן."""
        r = price_legs(self._condor(), self.QUOTES)
        assert {l["price_source"] for l in r.legs} == {"vwap"}

    def test_original_leg_fields_are_preserved(self):
        legs = [dict(_leg("קנה", "Put", 4030.0), note="שמור אותי")]
        r = price_legs(legs, self.QUOTES)
        assert r.legs[0]["note"] == "שמור אותי"

    def test_quantity_multiplies_the_cost(self):
        r = price_legs([_leg("קנה", "Put", 4030.0, qty=3)], self.QUOTES)
        assert r.entry_cost == pytest.approx(300.0)

    def test_empty_legs_is_not_complete(self):
        """אפס רגליים אינו 'עסקה מתומחרת במלואה'."""
        r = price_legs([], self.QUOTES)
        assert r.complete is False
        assert r.entry_cost is None

    def test_bad_strike_becomes_missing_not_a_crash(self):
        r = price_legs([{"action": "קנה", "type": "Put", "strike": "לא מספר"}],
                       self.QUOTES)
        assert r.complete is False
        assert len(r.missing) == 1

    def test_int_and_float_strikes_match(self):
        r = price_legs([_leg("קנה", "Put", 4030)], self.QUOTES)
        assert r.complete is True


# ─── fetch_traded_quotes ────────────────────────────────────────────────

class TestFetchTradedQuotes:
    def test_maps_both_sides(self):
        eng = _engine([_row(strike=4030.0,
                            overallturnoverunits_call=10, overallturnovervalue_shekel_call=2000,
                            overallturnoverunits_put=5,  overallturnovervalue_shekel_put=500)])
        q = fetch_traded_quotes("2026-08-11", "2026-08-07", eng)
        assert q[("Call", 4030.0)] == pytest.approx(200.0)
        assert q[("Put", 4030.0)] == pytest.approx(100.0)

    def test_untraded_side_is_absent(self):
        eng = _engine([_row(strike=4030.0,
                            overallturnoverunits_call=10, overallturnovervalue_shekel_call=2000,
                            overallturnoverunits_put=0,  overallturnovervalue_shekel_put=0)])
        q = fetch_traded_quotes("2026-08-11", "2026-08-07", eng)
        assert ("Call", 4030.0) in q
        assert ("Put", 4030.0) not in q

    def test_db_error_returns_empty_not_raise(self):
        """כשל DB ⇒ אין ציטוטים ⇒ הקורא לא יפתח. עדיף מלסחור על מחיר מומצא."""
        assert fetch_traded_quotes("2026-08-11", "2026-08-07", _engine(raises=True)) == {}

    def test_no_engine_returns_empty(self):
        assert fetch_traded_quotes("2026-08-11", "2026-08-07", None) == {}

    def test_rejects_unknown_source_table(self):
        """שם הטבלה נכנס ל-SQL — whitelist, לא קלט חופשי."""
        with pytest.raises(ValueError):
            fetch_traded_quotes("2026-08-11", "2026-08-07", _engine(), source_table="users")

    def test_empty_result_is_logged_not_silent(self, caplog):
        with caplog.at_level(logging.INFO, logger="vwap_pricing"):
            assert fetch_traded_quotes("2026-08-11", "2026-08-07", _engine([])) == {}
        assert "2026-08-11" in caplog.text

    def test_null_strike_row_is_skipped(self):
        eng = _engine([_row(strike=None,
                            overallturnoverunits_call=10, overallturnovervalue_shekel_call=2000,
                            overallturnoverunits_put=None, overallturnovervalue_shekel_put=None)])
        assert fetch_traded_quotes("2026-08-11", "2026-08-07", eng) == {}

    def test_dates_are_truncated_to_day(self):
        eng = _engine([])
        fetch_traded_quotes("2026-08-11T09:30:00", "2026-08-07T14:00:00", eng)
        params = eng.connect.return_value.execute.call_args[0][1]
        assert params == {"exp": "2026-08-11", "asof": "2026-08-07"}
