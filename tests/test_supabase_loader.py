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
    _infer_expiry_type,
    _make_engine,
    get_available_expiries,
    get_latest_option_chain,
    get_sample_row,
    has_db,
)


# ─── Fixtures ──────────────────────────────────────────────────────────

def _make_chain_row(strike: float, call_price: float = 50.0, put_price: float = 40.0) -> dict:
    """מחזיר שורה לדוגמה ב-DataFrame גולמי (כמו pd.read_sql)."""
    return {
        "strike":      strike,
        "call_price":  call_price,
        "put_price":   put_price,
        "call_delta":  55.0,
        "put_delta":   45.0,
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

class TestGetAvailableExpiries:
    def test_returns_empty_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_available_expiries() == []

    def test_returns_list_from_mock_engine(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("2026-05-22",),
            ("2026-05-29",),
        ]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        result = get_available_expiries(engine=mock_engine)
        assert result == ["2026-05-22", "2026-05-29"]

    def test_returns_empty_on_db_error(self):
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("connection failed")
        assert get_available_expiries(engine=mock_engine) == []

    def test_filters_none_values(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            (None,),
            ("2026-05-22",),
        ]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        result = get_available_expiries(engine=mock_engine)
        assert result == ["2026-05-22"]


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
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)

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
        """call_pts = call_price / MULTIPLIER."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        row = _make_chain_row(1920.0, call_price=100.0, put_price=200.0)
        chain_df_raw = pd.DataFrame([row])

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        chain = result["expiries"][0]["chain"]
        assert chain.iloc[0]["call_pts"] == pytest.approx(100.0 / MULTIPLIER, abs=0.01)
        assert chain.iloc[0]["put_pts"]  == pytest.approx(200.0 / MULTIPLIER, abs=0.01)

    def test_result_has_as_of_date_and_fetched_at(self):
        fetch_ts     = datetime(2026, 5, 22, 10, 30)
        chain_df_raw = pd.DataFrame([_make_chain_row(1920.0)])

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        assert result["as_of_date"] == "22/05/2026"
        assert result["fetched_at"] == fetch_ts

    def test_strike_below_min_filtered_out(self):
        """שורות עם strike < 100 מסוננות."""
        chain_df_raw = pd.DataFrame([
            _make_chain_row(50.0),    # ← יסונן
            _make_chain_row(1920.0),  # ← יישאר
        ])
        fetch_ts = datetime(2026, 5, 22, 10, 0)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        chain = result["expiries"][0]["chain"]
        assert (chain["strike"] >= 100.0).all()
        assert len(chain) == 1

    def test_expiry_date_formatted_as_ddmmyyyy(self):
        chain_df_raw = pd.DataFrame([_make_chain_row(1920.0)])
        fetch_ts     = datetime(2026, 5, 22, 9, 0)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        assert result["expiries"][0]["date"] == "29/05/2026"

    def test_weekly_expiry_type_inferred(self):
        """2026-05-22 הוא יום שישי שאינו אחרון → שבועי."""
        chain_df_raw = pd.DataFrame([_make_chain_row(1920.0)])
        chain_df_raw["drvtype"] = ""  # drvtype ריק → נסיק מהתאריך
        fetch_ts = datetime(2026, 5, 22, 9, 0)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-22",)]
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-22", engine=mock_engine)

        assert result["expiries"][0]["expiry_type"] == "שבועי"


# ─── get_sample_row ────────────────────────────────────────────────────

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
        sample_df = pd.DataFrame([{
            "expiry_date":             "2026-05-29",
            "fetched_at":              datetime(2026, 5, 22, 10, 0),
            "drvtype":                 "W",
            "expirationprice_call":    1920,
            "expirationprice_put":     1920,
            "lastrate_call":           1050,
            "lastrate_put":            980,
            "highrate_call":           1100,
            "lowrate_call":            980,
            "highrate_put":            1020,
            "lowrate_put":             940,
            "delta_call":              52.0,
            "delta_put":               48.0,
            "overallturnoverunits_call": 500,
            "overallturnoverunits_put":  480,
            "openpositions_call":       12000,
            "openpositions_put":        11500,
        }])
        mock_engine = MagicMock()
        with patch("supabase_loader.pd.read_sql", return_value=sample_df):
            result = get_sample_row(engine=mock_engine)

        assert result is not None
        assert isinstance(result, dict)
        assert result["lastrate_call"] == 1050
        assert result["expirationprice_call"] == 1920


# ─── Price conversion documentation ───────────────────────────────────

class TestPriceConversion:
    """
    מתעד את המרת המחיר: DB int×100 (centi-points) → ₪ → נקודות.

    מוסכמה: lastrate_call=1050 פירושו 10.50 נקודות.
      1. SQL: 1050 / 100.0 * 50 = 525 ₪  → call_price
      2. Python: 525 / 50 = 10.5          → call_pts
    """

    def _run_with_raw_price(self, raw_price_nis: float) -> float:
        """מחשב call_pts עבור call_price שכבר עבר המרת SQL."""
        fetch_ts     = datetime(2026, 5, 22, 10, 0)
        chain_df_raw = pd.DataFrame([_make_chain_row(1920.0, call_price=raw_price_nis)])

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        return float(result["expiries"][0]["chain"].iloc[0]["call_pts"])

    def test_525_nis_gives_10_5_pts(self):
        """lastrate_call=1050 centi-pts → SQL → 525 ₪ → 10.5 נקודות."""
        assert self._run_with_raw_price(525.0) == pytest.approx(10.5, abs=0.01)

    def test_250_nis_gives_5_pts(self):
        """lastrate_call=500 centi-pts → SQL → 250 ₪ → 5.0 נקודות."""
        assert self._run_with_raw_price(250.0) == pytest.approx(5.0, abs=0.01)

    def test_zero_price_stays_zero(self):
        """מחיר 0 ב-DB נשמר כ-0 ב-chain."""
        assert self._run_with_raw_price(0.0) == pytest.approx(0.0, abs=0.001)

    def test_centi_points_formula(self):
        """ממיר: int×100 → ÷100 → נקודות; ×50 → ₪ → ÷50 = נקודות שוב."""
        db_val = 1050           # int×100 (centi-points)
        pts    = db_val / 100.0  # 10.5
        nis    = pts * MULTIPLIER  # 525
        assert nis / MULTIPLIER == pytest.approx(pts, abs=0.001)
