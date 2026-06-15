"""
בדיקות יחידה ל-paper_db.py.

משתמש ב-mock engine כדי לא להצריך Supabase אמיתי.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from unittest.mock import MagicMock, call, patch

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from paper_db import (
    _dumps,
    _loads,
    _make_engine,
    _parse_strategy_ids,
    _row_to_dict,
    close_trade,
    create_portfolio,
    get_open_trades_for_expiry,
    get_portfolio,
    get_portfolios,
    get_trades,
    has_paper_db,
    insert_trade,
    update_balance,
)


# ─── Fixtures helpers ──────────────────────────────────────────────────

def _make_row(**kwargs) -> MagicMock:
    """מחזיר mock שורת DB עם _mapping כ-dict."""
    row = MagicMock()
    row._mapping = kwargs
    return row


def _mock_conn(fetchone=None, fetchall=None) -> MagicMock:
    """מחזיר mock connection עם תוצאות מוגדרות."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__  = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.return_value  = fetchone
    conn.execute.return_value.fetchall.return_value  = fetchall or []
    return conn


def _mock_engine(fetchone=None, fetchall=None) -> MagicMock:
    """מחזיר mock engine עם connection מוגדר."""
    eng = MagicMock()
    eng.connect.return_value = _mock_conn(fetchone=fetchone, fetchall=fetchall)
    return eng


# ─── has_paper_db ──────────────────────────────────────────────────────

class TestHasPaperDb:
    def test_false_when_no_env(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert has_paper_db() is False

    def test_true_when_env_set(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
        assert has_paper_db() is True

    def test_false_when_empty_string(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "")
        assert has_paper_db() is False


# ─── _make_engine ──────────────────────────────────────────────────────

class TestMakeEngine:
    def test_returns_none_without_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert _make_engine() is None

    def test_passes_through_existing_engine(self):
        mock = MagicMock()
        assert _make_engine(mock) is mock

    def test_rewrites_postgres_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host/db")
        with patch("paper_db.create_engine") as mock_ce:
            mock_ce.return_value = MagicMock()
            _make_engine()
            called_url = mock_ce.call_args[0][0]
            assert called_url.startswith("postgresql://")

    def test_keeps_postgresql_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
        with patch("paper_db.create_engine") as mock_ce:
            mock_ce.return_value = MagicMock()
            _make_engine()
            called_url = mock_ce.call_args[0][0]
            assert called_url.startswith("postgresql://")


# ─── _dumps / _loads ───────────────────────────────────────────────────

class TestDumps:
    def test_dict_serialized_to_json_string(self):
        result = _dumps({"key": "value"})
        assert isinstance(result, str)
        assert json.loads(result) == {"key": "value"}

    def test_hebrew_not_escaped(self):
        result = _dumps({"שם": "בדיקה"})
        assert "שם" in result
        assert "בדיקה" in result

    def test_none_returns_none(self):
        assert _dumps(None) is None

    def test_string_returned_as_is(self):
        s = '{"already": "serialized"}'
        assert _dumps(s) is s

    def test_nested_dict_serialized(self):
        d = {"legs": [{"strike": 4300, "side": "call"}]}
        result = _dumps(d)
        assert json.loads(result) == d


class TestLoads:
    def test_dict_returned_as_is(self):
        d = {"key": "val"}
        assert _loads(d) is d

    def test_json_string_parsed_to_dict(self):
        s = '{"key": "val"}'
        assert _loads(s) == {"key": "val"}

    def test_none_returns_none(self):
        assert _loads(None) is None

    def test_invalid_json_returns_string(self):
        bad = "not json"
        assert _loads(bad) == "not json"

    def test_hebrew_string_parsed(self):
        s = json.dumps({"שם": "ערך"}, ensure_ascii=False)
        result = _loads(s)
        assert result == {"שם": "ערך"}


# ─── _parse_strategy_ids ───────────────────────────────────────────────

class TestParseStrategyIds:
    _DEFAULT = [1, 2, 3, 4, 5, 6]

    def test_none_returns_default(self):
        assert _parse_strategy_ids(None) == self._DEFAULT

    def test_list_of_ints_passthrough(self):
        assert _parse_strategy_ids([2, 3]) == [2, 3]

    def test_single_element(self):
        assert _parse_strategy_ids([2]) == [2]

    def test_json_string_parsed(self):
        assert _parse_strategy_ids("[2, 3]") == [2, 3]

    def test_list_of_strings_coerced_to_int(self):
        assert _parse_strategy_ids(["1", "2"]) == [1, 2]

    def test_empty_list_returns_default(self):
        assert _parse_strategy_ids([]) == self._DEFAULT

    def test_empty_json_string_returns_default(self):
        assert _parse_strategy_ids("[]") == self._DEFAULT

    def test_invalid_string_returns_default(self):
        assert _parse_strategy_ids("not json") == self._DEFAULT

    def test_non_list_scalar_returns_default(self):
        assert _parse_strategy_ids(5) == self._DEFAULT

    def test_duplicates_removed_order_preserved(self):
        assert _parse_strategy_ids([2, 2, 3]) == [2, 3]

    def test_non_numeric_elements_skipped(self):
        assert _parse_strategy_ids([1, "x", 3]) == [1, 3]

    def test_default_is_a_fresh_copy(self):
        """החזרת ברירת המחדל אינה משתפת רפרנס שניתן לשנות בטעות."""
        a = _parse_strategy_ids(None)
        a.append(99)
        assert _parse_strategy_ids(None) == self._DEFAULT


# ─── _row_to_dict ──────────────────────────────────────────────────────

class TestRowToDict:
    def test_converts_mapping_to_dict(self):
        row = _make_row(id=1, name="Test")
        result = _row_to_dict(row)
        assert result == {"id": 1, "name": "Test"}

    def test_parses_legs_json_string(self):
        legs = [{"strike": 4300, "side": "call"}]
        row  = _make_row(id=1, legs_json=json.dumps(legs))
        result = _row_to_dict(row)
        assert result["legs_json"] == legs

    def test_keeps_legs_json_dict_as_is(self):
        legs = {"strike": 4300}
        row  = _make_row(id=1, legs_json=legs)
        result = _row_to_dict(row)
        assert result["legs_json"] == legs

    def test_parses_market_snapshot_json(self):
        snap = {"index": 4300.0, "note": "בדיקה"}
        row  = _make_row(id=1, market_snapshot_json=json.dumps(snap, ensure_ascii=False))
        result = _row_to_dict(row)
        assert result["market_snapshot_json"] == snap

    def test_none_jsonb_fields_stay_none(self):
        row = _make_row(id=1, legs_json=None, market_snapshot_json=None)
        result = _row_to_dict(row)
        assert result["legs_json"] is None
        assert result["market_snapshot_json"] is None


# ─── create_portfolio ──────────────────────────────────────────────────

class TestCreatePortfolio:
    def test_returns_none_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert create_portfolio("Test", 10000) is None

    def test_returns_dict_on_success(self):
        row = _make_row(id=1, name="Test", initial_balance=10000,
                        current_balance=10000, commission_per_leg=2.5, is_active=True)
        eng = _mock_engine(fetchone=row)
        result = create_portfolio("Test", 10000, commission_per_leg=2.5, engine=eng)
        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "Test"
        assert result["commission_per_leg"] == 2.5

    def test_returns_none_on_db_error(self):
        eng = MagicMock()
        eng.connect.side_effect = Exception("DB error")
        assert create_portfolio("Test", 10000, engine=eng) is None

    def test_returns_none_when_fetchone_is_none(self):
        eng = _mock_engine(fetchone=None)
        assert create_portfolio("Test", 10000, engine=eng) is None

    def test_default_commission_is_2_5(self):
        """ברירת מחדל של עמלה: 2.5₪."""
        conn = _mock_conn(fetchone=_make_row(id=1, name="T", initial_balance=1000,
                                             current_balance=1000, commission_per_leg=2.5,
                                             is_active=True))
        eng = MagicMock()
        eng.connect.return_value = conn
        create_portfolio("T", 1000, engine=eng)
        params = conn.execute.call_args[0][1]
        assert params["commission_per_leg"] == pytest.approx(2.5)

    def test_commit_called(self):
        row = _make_row(id=1, name="X", initial_balance=5000,
                        current_balance=5000, commission_per_leg=1.0, is_active=True)
        conn = _mock_conn(fetchone=row)
        eng  = MagicMock()
        eng.connect.return_value = conn
        create_portfolio("X", 5000, commission_per_leg=1.0, engine=eng)
        conn.commit.assert_called_once()

    def test_strategy_ids_stored_as_json(self):
        """(א) strategy_ids נשמר כ-JSON string בפרמטרים של ה-INSERT."""
        conn = _mock_conn(fetchone=_make_row(id=1, name="T", initial_balance=1000,
                                             current_balance=1000, commission_per_leg=2.5,
                                             strategy_ids="[2]", is_active=True))
        eng = MagicMock()
        eng.connect.return_value = conn
        create_portfolio("T", 1000, strategy_ids=[2], engine=eng)
        params = conn.execute.call_args[0][1]
        assert isinstance(params["strategy_ids"], str)
        assert json.loads(params["strategy_ids"]) == [2]

    def test_strategy_ids_default_all_when_none(self):
        """(ד) strategy_ids=None → נשמרות כל 6 האסטרטגיות (ברירת מחדל)."""
        conn = _mock_conn(fetchone=_make_row(id=1, name="T", initial_balance=1000,
                                             current_balance=1000, commission_per_leg=2.5,
                                             strategy_ids="[1,2,3,4,5,6]", is_active=True))
        eng = MagicMock()
        eng.connect.return_value = conn
        create_portfolio("T", 1000, engine=eng)
        params = conn.execute.call_args[0][1]
        assert json.loads(params["strategy_ids"]) == [1, 2, 3, 4, 5, 6]

    def test_returned_strategy_ids_parsed_to_list(self):
        """התיק שחוזר מ-create_portfolio כולל strategy_ids כ-list[int]."""
        row = _make_row(id=1, name="T", initial_balance=1000, current_balance=1000,
                        commission_per_leg=2.5, strategy_ids="[2, 3]", is_active=True)
        eng = _mock_engine(fetchone=row)
        result = create_portfolio("T", 1000, strategy_ids=[2, 3], engine=eng)
        assert result["strategy_ids"] == [2, 3]

    def test_sql_inserts_strategy_ids_column(self):
        conn = _mock_conn(fetchone=_make_row(id=1, name="T", initial_balance=1000,
                                             current_balance=1000, commission_per_leg=2.5,
                                             strategy_ids="[1,2,3,4,5,6]", is_active=True))
        eng = MagicMock()
        eng.connect.return_value = conn
        create_portfolio("T", 1000, engine=eng)
        sql_text = str(conn.execute.call_args[0][0])
        assert "strategy_ids" in sql_text


# ─── get_portfolios ────────────────────────────────────────────────────

class TestGetPortfolios:
    def test_returns_empty_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_portfolios() == []

    def test_returns_list_of_dicts(self):
        rows = [
            _make_row(id=1, name="P1", is_active=True),
            _make_row(id=2, name="P2", is_active=True),
        ]
        eng = _mock_engine(fetchall=rows)
        result = get_portfolios(engine=eng)
        assert len(result) == 2
        assert result[0]["name"] == "P1"
        assert result[1]["name"] == "P2"

    def test_returns_empty_on_db_error(self):
        eng = MagicMock()
        eng.connect.side_effect = Exception("connection failed")
        assert get_portfolios(engine=eng) == []

    def test_returns_empty_when_no_active_portfolios(self):
        eng = _mock_engine(fetchall=[])
        assert get_portfolios(engine=eng) == []

    def test_strategy_ids_parsed_to_list(self):
        """(ב) strategy_ids שחוזר כ-JSON string מ-JSONB מפורסר ל-list[int]."""
        rows = [_make_row(id=1, name="P1", is_active=True, strategy_ids="[2]")]
        eng = _mock_engine(fetchall=rows)
        result = get_portfolios(engine=eng)
        assert result[0]["strategy_ids"] == [2]

    def test_strategy_ids_as_native_list_kept(self):
        """JSONB שחוזר כבר כ-list נשמר כ-list[int]."""
        rows = [_make_row(id=1, name="P1", is_active=True, strategy_ids=[3, 4])]
        eng = _mock_engine(fetchall=rows)
        result = get_portfolios(engine=eng)
        assert result[0]["strategy_ids"] == [3, 4]

    def test_missing_strategy_ids_defaults_to_all(self):
        """(ד) שורה ללא strategy_ids → כל 6 (תאימות לאחור)."""
        rows = [_make_row(id=1, name="P1", is_active=True)]
        eng = _mock_engine(fetchall=rows)
        result = get_portfolios(engine=eng)
        assert result[0]["strategy_ids"] == [1, 2, 3, 4, 5, 6]


# ─── get_portfolio ─────────────────────────────────────────────────────

class TestGetPortfolio:
    def test_returns_none_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_portfolio(1) is None

    def test_returns_dict_when_found(self):
        row = _make_row(id=5, name="MyPortfolio", current_balance=9500.0)
        eng = _mock_engine(fetchone=row)
        result = get_portfolio(5, engine=eng)
        assert result is not None
        assert result["id"] == 5
        assert result["name"] == "MyPortfolio"

    def test_returns_none_when_not_found(self):
        eng = _mock_engine(fetchone=None)
        assert get_portfolio(999, engine=eng) is None

    def test_returns_none_on_db_error(self):
        eng = MagicMock()
        eng.connect.side_effect = Exception("timeout")
        assert get_portfolio(1, engine=eng) is None

    def test_strategy_ids_parsed_as_list(self):
        row = _make_row(id=5, name="P", strategy_ids="[3, 4]")
        eng = _mock_engine(fetchone=row)
        result = get_portfolio(5, engine=eng)
        assert result["strategy_ids"] == [3, 4]

    def test_strategy_ids_default_when_missing(self):
        row = _make_row(id=5, name="P")
        eng = _mock_engine(fetchone=row)
        result = get_portfolio(5, engine=eng)
        assert result["strategy_ids"] == [1, 2, 3, 4, 5, 6]


# ─── update_balance ────────────────────────────────────────────────────

class TestUpdateBalance:
    def test_returns_false_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert update_balance(1, 9000.0) is False

    def test_returns_true_on_success(self):
        eng = _mock_engine()
        assert update_balance(1, 9000.0, engine=eng) is True

    def test_returns_false_on_db_error(self):
        eng = MagicMock()
        eng.connect.side_effect = Exception("write error")
        assert update_balance(1, 9000.0, engine=eng) is False

    def test_commit_called(self):
        conn = _mock_conn()
        eng  = MagicMock()
        eng.connect.return_value = conn
        update_balance(1, 9000.0, engine=eng)
        conn.commit.assert_called_once()


# ─── insert_trade ──────────────────────────────────────────────────────

_SAMPLE_TRADE = {
    "portfolio_id":          1,
    "strategy_id":           2,
    "strategy_name":         "Bull Call Spread",
    "expiry_date":           date(2026, 5, 29),
    "opened_at":             datetime(2026, 5, 22, 10, 0),
    "entry_index":           4300.0,
    "entry_cost":            200.0,
    "legs_json":             [{"strike": 4300, "side": "call", "qty": 1}],
    "max_profit":            300.0,
    "max_loss":              200.0,
    "status":                "open",
    "closed_at":             None,
    "close_index":           None,
    "pnl":                   None,
    "pnl_pct":               None,
    "market_snapshot_json":  {"index": 4300.0, "note": "פקיעה בדיקה"},
    "num_legs":              2,
    "entry_commission":      5.0,
    "exit_commission":       None,
}


class TestInsertTrade:
    def test_returns_none_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert insert_trade(_SAMPLE_TRADE) is None

    def test_returns_dict_on_success(self):
        returned_row = _make_row(
            id=10,
            **{k: v for k, v in _SAMPLE_TRADE.items()
               if k not in ("legs_json", "market_snapshot_json")},
            legs_json=_SAMPLE_TRADE["legs_json"],
            market_snapshot_json=_SAMPLE_TRADE["market_snapshot_json"],
        )
        eng = _mock_engine(fetchone=returned_row)
        result = insert_trade(_SAMPLE_TRADE, engine=eng)
        assert result is not None
        assert result["id"] == 10
        assert result["strategy_name"] == "Bull Call Spread"

    def test_returns_none_on_db_error(self):
        eng = MagicMock()
        eng.connect.side_effect = Exception("insert failed")
        assert insert_trade(_SAMPLE_TRADE, engine=eng) is None

    def test_legs_json_dict_serialized_before_insert(self):
        """legs_json dict ממוקם ב-params כ-JSON string לפני שליחה ל-DB."""
        conn = _mock_conn(fetchone=_make_row(id=1, **{k: None for k in _SAMPLE_TRADE}))
        eng  = MagicMock()
        eng.connect.return_value = conn

        insert_trade(_SAMPLE_TRADE, engine=eng)

        # בדוק שה-params שנשלחו ל-execute מכילים string ב-legs_json
        call_kwargs = conn.execute.call_args
        params_arg  = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("parameters", {})
        assert isinstance(params_arg.get("legs_json"), str)
        parsed = json.loads(params_arg["legs_json"])
        assert parsed == _SAMPLE_TRADE["legs_json"]

    def test_market_snapshot_with_hebrew_serialized(self):
        """market_snapshot_json עם עברית נשמר עם ensure_ascii=False."""
        conn = _mock_conn(fetchone=_make_row(id=1, **{k: None for k in _SAMPLE_TRADE}))
        eng  = MagicMock()
        eng.connect.return_value = conn

        insert_trade(_SAMPLE_TRADE, engine=eng)

        call_kwargs = conn.execute.call_args
        params_arg  = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("parameters", {})
        snap_str = params_arg.get("market_snapshot_json", "")
        assert isinstance(snap_str, str)
        assert "פקיעה" in snap_str

    def test_commit_called(self):
        conn = _mock_conn(fetchone=_make_row(id=1, **{k: None for k in _SAMPLE_TRADE}))
        eng  = MagicMock()
        eng.connect.return_value = conn
        insert_trade(_SAMPLE_TRADE, engine=eng)
        conn.commit.assert_called_once()

    def test_returns_none_when_fetchone_is_none(self):
        eng = _mock_engine(fetchone=None)
        assert insert_trade(_SAMPLE_TRADE, engine=eng) is None

    def test_jsonb_fields_parsed_in_returned_dict(self):
        """כאשר DB מחזיר legs_json כ-string, הוא מפוענח ל-dict."""
        legs_str = json.dumps([{"strike": 4300}])
        snap_str = json.dumps({"index": 4300.0})
        returned_row = _make_row(id=5, legs_json=legs_str, market_snapshot_json=snap_str,
                                 status="open")
        eng    = _mock_engine(fetchone=returned_row)
        result = insert_trade(_SAMPLE_TRADE, engine=eng)
        assert result is not None
        assert result["legs_json"] == [{"strike": 4300}]
        assert result["market_snapshot_json"] == {"index": 4300.0}


# ─── get_trades ────────────────────────────────────────────────────────

class TestGetTrades:
    def test_returns_empty_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_trades() == []

    def test_returns_all_trades_without_filters(self):
        rows = [
            _make_row(id=1, status="open",   portfolio_id=1),
            _make_row(id=2, status="closed", portfolio_id=1),
        ]
        eng = _mock_engine(fetchall=rows)
        result = get_trades(engine=eng)
        assert len(result) == 2

    def test_returns_empty_on_db_error(self):
        eng = MagicMock()
        eng.connect.side_effect = Exception("query failed")
        assert get_trades(engine=eng) == []

    def test_filter_by_portfolio_id(self):
        row = _make_row(id=3, portfolio_id=7, status="open")
        conn = _mock_conn(fetchall=[row])
        eng  = MagicMock()
        eng.connect.return_value = conn
        result = get_trades(portfolio_id=7, engine=eng)
        sql_text = str(conn.execute.call_args[0][0])
        assert "portfolio_id" in sql_text

    def test_filter_by_status(self):
        conn = _mock_conn(fetchall=[])
        eng  = MagicMock()
        eng.connect.return_value = conn
        get_trades(status="closed", engine=eng)
        sql_text = str(conn.execute.call_args[0][0])
        assert "status" in sql_text

    def test_filter_by_expiry_date(self):
        conn = _mock_conn(fetchall=[])
        eng  = MagicMock()
        eng.connect.return_value = conn
        get_trades(expiry_date="2026-05-29", engine=eng)
        sql_text = str(conn.execute.call_args[0][0])
        assert "expiry_date" in sql_text

    def test_multiple_filters_combined(self):
        conn = _mock_conn(fetchall=[])
        eng  = MagicMock()
        eng.connect.return_value = conn
        get_trades(portfolio_id=1, status="open", expiry_date="2026-05-29", engine=eng)
        sql_text = str(conn.execute.call_args[0][0])
        assert "portfolio_id" in sql_text
        assert "status" in sql_text
        assert "expiry_date" in sql_text

    def test_jsonb_fields_parsed_in_results(self):
        legs_str = json.dumps([{"strike": 4300}])
        row  = _make_row(id=1, legs_json=legs_str, market_snapshot_json=None, status="open")
        eng  = _mock_engine(fetchall=[row])
        result = get_trades(engine=eng)
        assert result[0]["legs_json"] == [{"strike": 4300}]


# ─── get_open_trades_for_expiry ────────────────────────────────────────

class TestGetOpenTradesForExpiry:
    def test_returns_empty_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_open_trades_for_expiry("2026-05-29") == []

    def test_returns_open_trades(self):
        rows = [
            _make_row(id=1, status="open", expiry_date="2026-05-29"),
            _make_row(id=2, status="open", expiry_date="2026-05-29"),
        ]
        eng = _mock_engine(fetchall=rows)
        result = get_open_trades_for_expiry("2026-05-29", engine=eng)
        assert len(result) == 2
        assert all(r["status"] == "open" for r in result)

    def test_returns_empty_on_db_error(self):
        eng = MagicMock()
        eng.connect.side_effect = Exception("read error")
        assert get_open_trades_for_expiry("2026-05-29", engine=eng) == []

    def test_returns_empty_when_no_open_trades(self):
        eng = _mock_engine(fetchall=[])
        assert get_open_trades_for_expiry("2026-06-05", engine=eng) == []

    def test_sql_filters_by_status_open_and_expiry(self):
        conn = _mock_conn(fetchall=[])
        eng  = MagicMock()
        eng.connect.return_value = conn
        get_open_trades_for_expiry("2026-05-29", engine=eng)
        sql_text = str(conn.execute.call_args[0][0])
        assert "open" in sql_text
        assert "expiry_date" in sql_text


# ─── close_trade ───────────────────────────────────────────────────────

class TestCloseTrade:
    def test_returns_false_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert close_trade(1, 4310.0, 150.0, 7.5, exit_commission=5.0) is False

    def test_returns_true_on_success(self):
        eng = _mock_engine()
        assert close_trade(1, 4310.0, 150.0, 7.5, exit_commission=5.0, engine=eng) is True

    def test_returns_false_on_db_error(self):
        eng = MagicMock()
        eng.connect.side_effect = Exception("update failed")
        assert close_trade(1, 4310.0, 150.0, 7.5, exit_commission=5.0, engine=eng) is False

    def test_commit_called(self):
        conn = _mock_conn()
        eng  = MagicMock()
        eng.connect.return_value = conn
        close_trade(1, 4310.0, 150.0, 7.5, exit_commission=5.0, engine=eng)
        conn.commit.assert_called_once()

    def test_sql_sets_closed_status(self):
        conn = _mock_conn()
        eng  = MagicMock()
        eng.connect.return_value = conn
        close_trade(42, 4310.0, 150.0, 7.5, exit_commission=5.0, engine=eng)
        sql_text = str(conn.execute.call_args[0][0])
        assert "closed" in sql_text
        assert "closed_at" in sql_text
        assert "exit_commission" in sql_text

    def test_correct_params_passed_to_execute(self):
        conn = _mock_conn()
        eng  = MagicMock()
        eng.connect.return_value = conn
        close_trade(42, 4310.0, 150.0, 7.5, exit_commission=10.0, engine=eng)
        params = conn.execute.call_args[0][1]
        assert params["id"]              == 42
        assert params["close_index"]     == 4310.0
        assert params["pnl"]             == 150.0
        assert params["pnl_pct"]         == 7.5
        assert params["exit_commission"] == 10.0

    def test_default_exit_commission_is_zero(self):
        """exit_commission ברירת מחדל = 0.0."""
        conn = _mock_conn()
        eng  = MagicMock()
        eng.connect.return_value = conn
        close_trade(1, 4300.0, 100.0, 0.5, engine=eng)
        params = conn.execute.call_args[0][1]
        assert params["exit_commission"] == pytest.approx(0.0)
