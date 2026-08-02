"""
בדיקות יחידה ל-supabase_loader.py.

משתמש ב-mock engine כדי לא להצריך Supabase אמיתי.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from supabase_loader import (
    MULTIPLIER,
    _ATM_RANGE_PCT,
    _MAX_PRICE_PTS,
    _MIN_CHAIN_ROWS,
    _infer_expiry_type,
    _load_one_expiry,
    _make_engine,
    _raw_to_option_pts,
    _to_nis,
    _to_decimal_delta,
    get_available_expiries,
    get_latest_option_chain,
    get_sample_row,
    has_db,
)


# ─── Fixtures ──────────────────────────────────────────────────────────

def _make_chain_row(
    strike: float,
    call_price: float = 50.0,
    put_price: float = 40.0,
    call_delta: float = 55.0,
    put_delta: float = 45.0,
) -> dict:
    """מחזיר שורה לדוגמה ב-DataFrame גולמי (כמו pd.read_sql של _load_one_expiry)."""
    return {
        "strike":      strike,
        "call_price":  call_price,
        "put_price":   put_price,
        "call_delta":  call_delta,
        "put_delta":   put_delta,
        "call_oi":     1000.0,
        "put_oi":      900.0,
        "call_volume": 200.0,
        "put_volume":  180.0,
        "call_high":   55.0,
        "call_low":    45.0,
        "put_high":    42.0,
        "put_low":     38.0,
        "drvtype":     "W",
    }


def _mock_engine_for_chain(
    expiry_date: str = "2026-05-30",
    fetch_ts: datetime = datetime(2026, 5, 22, 10, 0),
) -> MagicMock:
    """
    יוצר mock engine שמחזיר נתוני שרשרת לפקיעה אחת.
    """
    strikes = [1900.0, 1920.0, 1940.0, 1960.0, 1980.0]
    chain_df = pd.DataFrame([_make_chain_row(s) for s in strikes])

    mock_engine = MagicMock()

    # pd.read_sql patch — מוחזר בכל קריאה ל-_load_one_expiry
    mock_engine._chain_df  = chain_df
    mock_engine._fetch_ts  = fetch_ts
    mock_engine._exp_date  = expiry_date

    return mock_engine


# ─── has_db ────────────────────────────────────────────────────────────

class TestHasDb:
    def test_false_when_no_env(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert has_db() is False

    def test_true_when_env_set(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
        assert has_db() is True


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
        with patch("supabase_loader.create_engine") as mock_ce:
            mock_ce.return_value = MagicMock()
            _make_engine()
            called_url = mock_ce.call_args[0][0]
            assert called_url.startswith("postgresql://")

    def test_keeps_postgresql_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
        with patch("supabase_loader.create_engine") as mock_ce:
            mock_ce.return_value = MagicMock()
            _make_engine()
            called_url = mock_ce.call_args[0][0]
            assert called_url.startswith("postgresql://")


# ─── _infer_expiry_type ────────────────────────────────────────────────

class TestInferExpiryType:
    def test_weekly_from_drvtype_w(self):
        assert _infer_expiry_type("W", None) == "שבועי"

    def test_weekly_from_drvtype_weekly(self):
        assert _infer_expiry_type("weekly", None) == "שבועי"

    def test_monthly_from_drvtype_m(self):
        assert _infer_expiry_type("M", None) == "חודשי"

    def test_monthly_from_drvtype_monthly(self):
        assert _infer_expiry_type("monthly", None) == "חודשי"

    def test_monthly_from_last_friday_of_month(self):
        # 2026-05-29 הוא יום שישי אחרון של מאי 2026 → חודשי
        assert _infer_expiry_type("", date(2026, 5, 29)) == "חודשי"

    def test_weekly_from_non_last_friday(self):
        # 2026-05-22 הוא יום שישי שאינו אחרון → שבועי
        assert _infer_expiry_type("", date(2026, 5, 22)) == "שבועי"

    def test_default_weekly_when_unknown(self):
        assert _infer_expiry_type("", None) == "שבועי"

    def test_case_insensitive(self):
        assert _infer_expiry_type("WEEKLY", None) == "שבועי"
        assert _infer_expiry_type("Monthly", None) == "חודשי"


# ─── get_available_expiries ────────────────────────────────────────────

def _mock_conn_single(rows):
    """עוזר: mock connection עם קריאת execute אחת."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__  = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = rows
    return mock_conn


class TestGetAvailableExpiries:
    def test_returns_empty_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_available_expiries() == []

    def test_returns_expiries_ordered_by_fetched_at(self):
        """מחזיר פקיעות ממוינות לפי MAX(fetched_at) DESC."""
        mock_conn = _mock_conn_single([("2026-05-29",), ("2026-05-21",)])
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        result = get_available_expiries(engine=mock_engine)
        assert result == ["2026-05-29", "2026-05-21"]

    def test_returns_past_expiry_on_weekend(self):
        """בסוף שבוע — מחזיר את הפקיעה האחרונה (כבר עברה) ללא fallback."""
        mock_conn = _mock_conn_single([("2026-05-21",)])
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        result = get_available_expiries(engine=mock_engine)
        assert result == ["2026-05-21"]

    def test_returns_empty_on_db_error(self):
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("connection failed")
        assert get_available_expiries(engine=mock_engine) == []

    def test_filters_none_values(self):
        mock_conn = _mock_conn_single([(None,), ("2026-05-29",)])
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        result = get_available_expiries(engine=mock_engine)
        assert result == ["2026-05-29"]


# ─── get_latest_option_chain ───────────────────────────────────────────

class TestGetLatestOptionChain:
    def test_returns_none_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_latest_option_chain() is None

    def test_returns_none_on_exception(self):
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("DB error")
        assert get_latest_option_chain(engine=mock_engine) is None

    def test_returns_none_when_no_expiries(self):
        fetch_ts = datetime(2026, 5, 22, 10, 0)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)

        # targets query returns nothing
        mock_conn.execute.return_value.fetchall.return_value = []

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        assert get_latest_option_chain(engine=mock_engine) is None

    def test_chain_df_has_correct_columns(self):
        """בדיקה שה-chain מכיל את עמודות options_parser."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        strikes  = [1900.0, 1920.0, 1940.0]
        chain_df_raw = pd.DataFrame([_make_chain_row(s) for s in strikes])

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        # targets query
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-22", "10:00", fetch_ts, "21/05/2026")

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        assert result is not None
        assert "expiries" in result
        assert len(result["expiries"]) == 1

        chain = result["expiries"][0]["chain"]
        expected_cols = {
            "strike", "call_price", "put_price",
            "call_delta", "put_delta",
            "call_oi", "put_oi",
            "call_volume", "put_volume",
            "call_high", "call_low",
            "put_high", "put_low",
            "call_pts", "put_pts",
        }
        assert expected_cols.issubset(set(chain.columns))

    def test_call_pts_and_put_pts_are_divided_by_multiplier(self):
        """call_pts = call_price(₪) / MULTIPLIER; ערכים >1000 נשארים בₓ ישירות."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        # 3 שורות זהות (≥ _MIN_CHAIN_ROWS); בודקים את הערכים של הסטרייק הראשון
        chain_df_raw = pd.DataFrame([
            _make_chain_row(1880.0, call_price=5000.0, put_price=3000.0),
            _make_chain_row(1920.0, call_price=5000.0, put_price=3000.0),
            _make_chain_row(1960.0, call_price=5000.0, put_price=3000.0),
        ])

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-22", "10:00", fetch_ts, "21/05/2026")

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        assert result is not None
        chain = result["expiries"][0]["chain"]
        row = chain.iloc[0]
        assert row["call_pts"] == pytest.approx(5000.0 / MULTIPLIER, abs=0.01)
        assert row["put_pts"]  == pytest.approx(3000.0 / MULTIPLIER, abs=0.01)

    def test_result_has_as_of_date_and_fetched_at(self):
        fetch_ts     = datetime(2026, 5, 22, 10, 30)
        chain_df_raw = pd.DataFrame([_make_chain_row(s) for s in [1900.0, 1920.0, 1940.0]])

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-22", "10:00", fetch_ts, "21/05/2026")

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        # as_of_date כולל שעה בשעון ישראל: 10:30 UTC → 13:30 EEST (UTC+3)
        assert result["as_of_date"] == "22/05/2026 13:30"
        assert result["fetched_at"] == fetch_ts

    def test_strike_below_min_filtered_out(self):
        """שורות עם strike < 100 מסוננות; שאר השורות (≥ _MIN_CHAIN_ROWS) נשארות."""
        chain_df_raw = pd.DataFrame([
            _make_chain_row(50.0),    # ← יסונן (strike < 100)
            _make_chain_row(1900.0),
            _make_chain_row(1920.0),
            _make_chain_row(1940.0),
        ])
        fetch_ts = datetime(2026, 5, 22, 10, 0)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-22", "10:00", fetch_ts, "21/05/2026")

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        assert result is not None
        chain = result["expiries"][0]["chain"]
        assert (chain["strike"] >= 100.0).all()
        assert 50.0 not in chain["strike"].values

    def test_expiry_date_formatted_as_ddmmyyyy(self):
        chain_df_raw = pd.DataFrame([_make_chain_row(s) for s in [1900.0, 1920.0, 1940.0]])
        fetch_ts     = datetime(2026, 5, 22, 9, 0)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-22", "10:00", fetch_ts, "21/05/2026")

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        assert result["expiries"][0]["date"] == "29/05/2026"

    def test_weekly_expiry_type_inferred(self):
        """2026-05-22 הוא יום שישי שאינו אחרון → שבועי."""
        chain_df_raw = pd.DataFrame([_make_chain_row(s) for s in [1900.0, 1920.0, 1940.0]])
        chain_df_raw["drvtype"] = ""  # drvtype ריק → נסיק מהתאריך
        fetch_ts = datetime(2026, 5, 22, 9, 0)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-22",)]
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-22", "10:00", fetch_ts, "21/05/2026")

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-22", engine=mock_engine)

        assert result["expiries"][0]["expiry_type"] == "שבועי"


# ─── get_sample_row ────────────────────────────────────────────────────

def _make_sample_df_row(
    lastrate_call: float = 100.0,
    lastrate_put: float = 100.0,
    expiry_date: str = "2026-05-29",
) -> dict:
    """עוזר: שורה לדוגמה בפורמט SQL של get_sample_row."""
    return {
        "expiry_date":              expiry_date,
        "fetched_at":               datetime(2026, 5, 22, 10, 0),
        "drvtype":                  "W",
        "expirationprice_call":     4300.0,
        "expirationprice_put":      4300.0,
        "baserate_call":            None,
        "lastrate_call":            lastrate_call,
        "lastrate_put":             lastrate_put,
        "highrate_call":            120.0,
        "lowrate_call":             80.0,
        "highrate_put":             120.0,
        "lowrate_put":              80.0,
        "delta_call":               52.0,
        "delta_put":                -48.0,
        "overallturnoverunits_call": 500,
        "overallturnoverunits_put":  480,
        "openpositions_call":        12000,
        "openpositions_put":         11500,
    }


class TestGetSampleRow:
    def test_returns_none_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_sample_row() is None

    def test_returns_none_on_db_error(self):
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("DB down")
        assert get_sample_row(engine=mock_engine) is None

    def test_returns_none_when_table_empty(self):
        empty_df = pd.DataFrame()
        mock_engine = MagicMock()
        with patch("supabase_loader.pd.read_sql", return_value=empty_df):
            assert get_sample_row(engine=mock_engine) is None

    def test_returns_dict_with_raw_columns(self):
        """מחזיר dict עם ערכים גולמיים מה-DB."""
        sample_df = pd.DataFrame([_make_sample_df_row(lastrate_call=100.0, lastrate_put=100.0)])
        mock_engine = MagicMock()
        with patch("supabase_loader.pd.read_sql", return_value=sample_df):
            result = get_sample_row(engine=mock_engine)

        assert result is not None
        assert isinstance(result, dict)
        assert result["lastrate_call"] == 100.0
        assert result["expirationprice_call"] == 4300.0

    def test_parity_atm_selection(self):
        """מחזיר את השורה שבה |call_nis - put_nis| מינימלי — השורה הכי קרובה ל-ATM."""
        sample_df = pd.DataFrame([
            # שורה OTM: call גבוה בהרבה מ-put
            {**_make_sample_df_row(lastrate_call=500.0, lastrate_put=50.0),
             "expirationprice_call": 4600.0, "expirationprice_put": 4600.0},
            # שורה ATM: call ≈ put
            {**_make_sample_df_row(lastrate_call=100.0, lastrate_put=100.0),
             "expirationprice_call": 4300.0, "expirationprice_put": 4300.0},
        ])
        mock_engine = MagicMock()
        with patch("supabase_loader.pd.read_sql", return_value=sample_df):
            result = get_sample_row(engine=mock_engine)

        assert result is not None
        # הפונקציה צריכה להחזיר את שורת ה-ATM
        assert result["expirationprice_call"] == pytest.approx(4300.0)


# ─── _load_one_expiry — multi-layer filters ────────────────────────────

def _mock_conn_fetchone(fetch_ts, fetch_date="2026-05-22", fetch_time="10:00",
                        trade_date="21/05/2026"):
    """
    mock connection עם fetchone שמחזיר
    (fetch_date, fetch_time, fetch_ts, trade_date).

    trade_date בפורמט DD/MM/YYYY והוא T-1 מול fetch_date — כמו בנתונים האמיתיים.
    """
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (
        fetch_date, fetch_time, fetch_ts, trade_date)
    return mock_conn


class TestLoadOneExpiryFilters:
    """בודק את כל שכבות הסינון ב-_load_one_expiry."""

    _TS = datetime(2026, 5, 22, 10, 0)

    # ── סינון 1: call=0 AND put=0 ──────────────────────────────────────

    def test_zero_call_and_put_rows_are_removed(self):
        """שורה שבה call=0 וגם put=0 מסוננת."""
        rows = [
            _make_chain_row(4200.0, call_price=0.0, put_price=0.0),   # יסונן
            _make_chain_row(4300.0, call_price=10.0, put_price=10.0),
            _make_chain_row(4400.0, call_price=10.0, put_price=10.0),
            _make_chain_row(4500.0, call_price=10.0, put_price=10.0),
        ]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is not None
        assert 4200.0 not in result[0]["strike"].values

    def test_row_with_only_put_zero_is_kept(self):
        """שורה עם call > 0 נשארת גם אם put = 0."""
        rows = [
            _make_chain_row(4200.0, call_price=5.0, put_price=0.0),
            _make_chain_row(4300.0, call_price=5.0, put_price=5.0),
            _make_chain_row(4400.0, call_price=5.0, put_price=5.0),
            _make_chain_row(4500.0, call_price=5.0, put_price=5.0),
        ]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is not None
        assert 4200.0 in result[0]["strike"].values

    def test_returns_none_when_all_rows_are_zero(self):
        """כל השורות 0/0 → None."""
        rows = [_make_chain_row(4300.0 + i*100, call_price=0.0, put_price=0.0) for i in range(4)]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is None

    # ── סינון 2: delta_call=0 AND delta_put=0 ──────────────────────────

    def test_zero_delta_rows_are_removed(self):
        """שורה עם delta_call=0 וגם delta_put=0 מסוננת."""
        rows = [
            _make_chain_row(4200.0, call_delta=0.0, put_delta=0.0),   # יסונן
            _make_chain_row(4300.0),
            _make_chain_row(4400.0),
            _make_chain_row(4500.0),
        ]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is not None
        assert 4200.0 not in result[0]["strike"].values

    def test_row_with_only_call_delta_zero_is_kept(self):
        """שורה עם put_delta > 0 נשארת אפילו אם call_delta=0."""
        rows = [
            _make_chain_row(4200.0, call_delta=0.0, put_delta=45.0),  # נשאר
            _make_chain_row(4300.0),
            _make_chain_row(4400.0),
            _make_chain_row(4500.0),
        ]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is not None
        assert 4200.0 in result[0]["strike"].values

    # ── סינון 3: מחיר חריג > _MAX_PRICE_PTS נקודות ────────────────────

    def test_price_outlier_row_is_removed(self):
        """שורה עם call_price > 500 נקודות (raw: > 25000 ₪) מסוננת."""
        rows = [
            _make_chain_row(4200.0, call_price=150000.0, put_price=50.0),  # 3000 pts → יסונן
            _make_chain_row(4300.0),
            _make_chain_row(4400.0),
            _make_chain_row(4500.0),
        ]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is not None
        assert 4200.0 not in result[0]["strike"].values

    def test_normal_price_row_not_removed(self):
        """מחיר סביר (≤ 500 נקודות) נשאר לאחר סינון outlier."""
        rows = [
            _make_chain_row(4300.0, call_price=500.0, put_price=500.0),  # 10 pts → נשאר
            _make_chain_row(4400.0),
            _make_chain_row(4500.0),
            _make_chain_row(4600.0),
        ]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is not None
        assert 4300.0 in result[0]["strike"].values

    # ── סינון 4: ±20% מ-ATM (put-call parity) ──────────────────────────

    def test_atm_range_filter_removes_distant_strikes(self):
        """סטרייק מחוץ ל-±20% מ-ATM מסונן."""
        # ATM יזוהה ב-4300 (parity=0), ±20% = [3440, 5160]
        # סטרייק 3000 < 3440 → יסונן
        rows = [
            _make_chain_row(3000.0, call_price=200.0, put_price=10.0),   # OTM רחוק → יסונן
            _make_chain_row(4200.0, call_price=100.0, put_price=90.0),
            _make_chain_row(4300.0, call_price=100.0, put_price=100.0),  # ATM (parity=0)
            _make_chain_row(4400.0, call_price=90.0,  put_price=100.0),
            _make_chain_row(4500.0, call_price=80.0,  put_price=110.0),
        ]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is not None
        chain = result[0]
        assert 3000.0 not in chain["strike"].values
        assert 4300.0 in chain["strike"].values

    # ── סינון 5: פחות מ-_MIN_CHAIN_ROWS שורות → None ──────────────────

    def test_returns_none_when_fewer_than_min_rows_after_atm_filter(self):
        """פחות מ-3 שורות תקינות לאחר סינון ATM → None עם אזהרה."""
        # ATM ב-4300 (parity=0), ±20% = [3440, 5160]
        # רק 2 שורות בטווח → None
        rows = [
            _make_chain_row(3000.0, call_price=200.0, put_price=10.0),  # מחוץ לטווח
            _make_chain_row(4200.0, call_price=100.0, put_price=90.0),  # בטווח
            _make_chain_row(4300.0, call_price=100.0, put_price=100.0), # ATM — בטווח
        ]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            import warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is None
        assert any("לא תקינים" in str(warning.message) for warning in w)

    # ── ATM level מ-put-call parity ────────────────────────────────────

    def test_atm_level_from_parity(self):
        """atm_level = index_estimate מ-find_atm: סטרייק שבו |call-put| מינימלי."""
        # סטרייק 4300: call=put=100pts → parity=0 → ATM מדויק
        # index_estimate = 4300 + (100-100) = 4300
        rows = [
            _make_chain_row(4100.0, call_price=200.0, put_price=50.0),  # parity גבוה
            _make_chain_row(4300.0, call_price=100.0, put_price=100.0), # ATM
            _make_chain_row(4500.0, call_price=50.0,  put_price=200.0), # parity גבוה
        ]
        df_raw = pd.DataFrame(rows)
        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(MagicMock(), _mock_conn_fetchone(self._TS), "2026-05-29")

        assert result is not None
        atm_level = result[3]
        # _to_nis(100.0) = 100.0₪ (identity); c_pts = 100/50 = 2.0; index_est = 4300 + 2.0 - 2.0 = 4300
        assert atm_level == pytest.approx(4300.0, abs=1.0)

    def test_load_expiry_combines_multi_batch_fetch(self):
        """
        כאשר pipeline כותב שרשרת ב-3 batches עם fetched_at שונה אך fetch_date+fetch_time זהים,
        _load_one_expiry צריך להחזיר את כל השורות מכל ה-batches — לא רק מה-batch האחרון.
        """
        # batch 1: סטרייקים נמוכים (OTM puts)
        batch1 = [_make_chain_row(s, call_price=0.0, put_price=50.0)
                  for s in [4100.0, 4200.0, 4300.0]]
        # batch 2: סטרייקים ATM — כאן שני הצדדים פעילים
        batch2 = [_make_chain_row(s, call_price=100.0, put_price=100.0)
                  for s in [4400.0, 4450.0, 4500.0]]
        # batch 3: סטרייקים גבוהים (OTM calls)
        batch3 = [_make_chain_row(s, call_price=50.0, put_price=0.0)
                  for s in [4600.0, 4700.0, 4800.0]]

        # pd.read_sql מחזיר את כל 9 השורות (כאילו SQL שלף WHERE fetch_date+fetch_time)
        all_rows = pd.DataFrame(batch1 + batch2 + batch3)

        # fetchone מחזיר (fetch_date, fetch_time, max_fetched_at) — כמו הקוד המתוקן
        mock_conn = _mock_conn_fetchone(
            datetime(2026, 5, 27, 11, 38, 2),
            fetch_date="2026-05-27",
            fetch_time="14:37",
        )

        with patch("supabase_loader.pd.read_sql", return_value=all_rows):
            result = _load_one_expiry(MagicMock(), mock_conn, "2026-05-29")

        assert result is not None, "צפוי תוצאה תקינה כשכל ה-batches מאוחדים"
        chain = result[0]
        # כל 9 הסטרייקים צריכים להיות בטווח ה-ATM (4300–4800, ATM≈4450)
        # לפחות 3 שורות צריכות לעבור את כל הסינונים
        assert len(chain) >= 3, f"צפוי לפחות 3 שורות, קיבל {len(chain)}"
        # וודא שסטרייקים מ-batch 2 (ATM) נמצאים בתוצאה
        atm_strikes = set(chain["strike"].values)
        assert any(s in atm_strikes for s in [4400.0, 4450.0, 4500.0]), \
            f"סטרייקי ATM לא נמצאו ב-chain: {sorted(atm_strikes)}"


# ─── _raw_to_option_pts ───────────────────────────────────────────────

class TestRawToOptionPts:
    """ממיר ערך גולמי DB (₪) לנקודות: abs(v) / MULTIPLIER."""

    def test_small_value_divided_by_multiplier(self):
        """2.0 ₪ → 2.0/50 = 0.04 נקודות."""
        assert _raw_to_option_pts(2.0) == pytest.approx(0.04, abs=0.001)

    def test_large_value_divided_by_multiplier(self):
        """29123.0 ₪ → 29123/50 = 582.46 נקודות."""
        assert _raw_to_option_pts(29123.0) == pytest.approx(582.46, abs=0.01)

    def test_outlier_150000_exceeds_threshold(self):
        """150000 ₪ = 3000 נקודות > _MAX_PRICE_PTS (500) → ייסונן."""
        pts = _raw_to_option_pts(150000.0)
        assert pts > _MAX_PRICE_PTS

    def test_29123_exceeds_new_threshold(self):
        """29123 ₪ = 582 נקודות > _MAX_PRICE_PTS (500) — outlier לפי הסף החדש."""
        pts = _raw_to_option_pts(29123.0)
        assert pts > _MAX_PRICE_PTS

    def test_zero_returns_zero(self):
        assert _raw_to_option_pts(0.0) == pytest.approx(0.0, abs=0.001)


# ─── _to_nis ──────────────────────────────────────────────────────────

class TestToNis:
    """פונקציית זהות — כל lastrate_* מאוחסן ב-₪ ומוחזר כפי שהוא."""

    def test_small_value_returned_as_is(self):
        """2.0 ₪ → מוחזר 2.0 ₪ (ללא המרה)."""
        assert _to_nis(2.0) == pytest.approx(2.0, abs=0.01)

    def test_large_value_returned_as_is(self):
        """26623.0 ₪ → מוחזר 26623.0 ₪ ללא שינוי."""
        assert _to_nis(26623.0) == pytest.approx(26623.0, abs=0.01)

    def test_boundary_1000_returned_as_is(self):
        """1000.0 ₪ → מוחזר 1000.0 ₪ (ללא כפל ב-MULTIPLIER)."""
        assert _to_nis(1000.0) == pytest.approx(1000.0, abs=0.01)

    def test_above_boundary_returned_as_is(self):
        """1001.0 ₪ → מוחזר 1001.0 ₪."""
        assert _to_nis(1001.0) == pytest.approx(1001.0, abs=0.01)

    def test_zero_returns_zero(self):
        assert _to_nis(0.0) == pytest.approx(0.0, abs=0.001)


# ─── _to_decimal_delta ────────────────────────────────────────────────

class TestToDecimalDelta:
    """כלל סף: |δ| > 1 → ÷ 100 (סקלת אחוזים → דצימלי); |δ| ≤ 1 → ללא שינוי."""

    def test_minus_100_becomes_minus_1(self):
        """-100.0 → -1.0 (put ATM percent scale)."""
        assert _to_decimal_delta(-100.0) == pytest.approx(-1.0, abs=0.001)

    def test_50_percent_becomes_0_5(self):
        """50.0 → 0.5."""
        assert _to_decimal_delta(50.0) == pytest.approx(0.5, abs=0.001)

    def test_already_decimal_kept(self):
        """0.52 → 0.52 (כבר דצימלי)."""
        assert _to_decimal_delta(0.52) == pytest.approx(0.52, abs=0.001)

    def test_negative_decimal_kept(self):
        """-0.45 → -0.45."""
        assert _to_decimal_delta(-0.45) == pytest.approx(-0.45, abs=0.001)


# ─── Price conversion — threshold-based normalization ─────────────────

class TestPriceConversion:
    """
    מתעד את המרת המחיר — כל lastrate_* הוא ב-₪; call_pts = call_price / MULTIPLIER.

    call_price (₪) = ערך ה-DB (ללא שינוי)
    call_pts       = call_price / 50
    """

    def _run_with_raw_price(self, raw_db_price: float) -> tuple:
        """מחזיר (call_price_nis, call_pts) לאחר נרמול עבור סטרייק 1920."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        # 3 שורות: 1900 ו-1940 הן filler; 1920 עם המחיר הנבדק
        chain_df_raw = pd.DataFrame([
            _make_chain_row(1900.0),                             # filler standard
            _make_chain_row(1920.0, call_price=raw_db_price),   # שורת הבדיקה
            _make_chain_row(1940.0),                             # filler standard
        ])

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-22", "10:00", fetch_ts, "21/05/2026")

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        assert result is not None, "צפוי result תקין עם 3 שורות"
        chain = result["expiries"][0]["chain"]
        target = chain[chain["strike"].round(0) == 1920.0]
        assert not target.empty, "שורת 1920 חסרה מה-chain"
        row = target.iloc[0]
        return float(row["call_price"]), float(row["call_pts"])

    def test_small_value_treated_as_nis(self):
        """2.0 ₪ → call_price=2.0 ₪ → call_pts=0.04."""
        call_price, call_pts = self._run_with_raw_price(2.0)
        assert call_price == pytest.approx(2.0, abs=0.01)
        assert call_pts   == pytest.approx(2.0 / MULTIPLIER, abs=0.001)

    def test_realistic_nis_value_treated_as_nis(self):
        """12500.0 ₪ (250 נקודות — ≤ 500 סף) → call_price=12500 ₪ → call_pts=250."""
        call_price, call_pts = self._run_with_raw_price(12500.0)
        assert call_price == pytest.approx(12500.0, abs=0.01)
        assert call_pts   == pytest.approx(12500.0 / MULTIPLIER, abs=0.01)

    def test_zero_price_stays_zero(self):
        """מחיר 0 ב-DB → 0 ₪ → 0 נקודות."""
        call_price, call_pts = self._run_with_raw_price(0.0)
        assert call_price == pytest.approx(0.0, abs=0.001)
        assert call_pts   == pytest.approx(0.0, abs=0.001)

    def test_boundary_1000_treated_as_nis(self):
        """1000.0 ₪ = 20 נקודות → call_price=1000 ₪ → call_pts=20.0."""
        call_price, call_pts = self._run_with_raw_price(1000.0)
        assert call_price == pytest.approx(1000.0, abs=0.01)
        assert call_pts   == pytest.approx(1000.0 / MULTIPLIER, abs=0.01)
