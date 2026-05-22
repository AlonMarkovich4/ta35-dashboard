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
    _load_one_expiry,
    _make_engine,
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
    baserate_call: float = 1920.0,
) -> dict:
    """מחזיר שורה לדוגמה ב-DataFrame גולמי (כמו pd.read_sql)."""
    return {
        "strike":        strike,
        "call_price":    call_price,
        "put_price":     put_price,
        "call_delta":    55.0,
        "put_delta":     45.0,
        "call_oi":       1000.0,
        "put_oi":        900.0,
        "call_volume":   200.0,
        "put_volume":    180.0,
        "call_high":     55.0,
        "call_low":      45.0,
        "put_high":      42.0,
        "put_low":       38.0,
        "baserate_call": baserate_call,
        "drvtype":       "W",
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

def _mock_conn_two_calls(first_result, second_result=None):
    """עוזר: mock connection עם שתי קריאות execute עוקבות."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__  = MagicMock(return_value=False)
    results = [MagicMock(), MagicMock()]
    results[0].fetchall.return_value = first_result
    if second_result is not None:
        results[1].fetchall.return_value = second_result
    mock_conn.execute.side_effect = results
    return mock_conn


class TestGetAvailableExpiries:
    def test_returns_empty_without_engine(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_available_expiries() == []

    def test_returns_future_expiries(self):
        """מחזיר רק פקיעות עתידיות כשיש."""
        mock_conn = _mock_conn_two_calls(
            first_result=[("2026-05-29",), ("2026-06-05",)],
        )
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        result = get_available_expiries(engine=mock_engine)
        assert result == ["2026-05-29", "2026-06-05"]

    def test_fallback_to_nearest_past_when_no_future(self):
        """אין פקיעות עתידיות → מחזיר הפקיעה האחרונה."""
        mock_conn = _mock_conn_two_calls(
            first_result=[],
            second_result=[("2026-05-21",)],
        )
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        result = get_available_expiries(engine=mock_engine)
        assert result == ["2026-05-21"]

    def test_returns_empty_on_db_error(self):
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("connection failed")
        assert get_available_expiries(engine=mock_engine) == []

    def test_filters_none_values(self):
        mock_conn = _mock_conn_two_calls(
            first_result=[(None,), ("2026-05-29",)],
        )
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
        """call_pts = call_price(₪) / MULTIPLIER; ערכים >1000 נשארים בₓ ישירות."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        # ערכים > 1000 → כבר ₪ → _to_nis משאיר; call_pts = ₪ / 50
        row = _make_chain_row(1920.0, call_price=5000.0, put_price=3000.0)
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
        assert chain.iloc[0]["call_pts"] == pytest.approx(5000.0 / MULTIPLIER, abs=0.01)
        assert chain.iloc[0]["put_pts"]  == pytest.approx(3000.0 / MULTIPLIER, abs=0.01)

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


# ─── _load_one_expiry — zero-price filter & baserate ──────────────────

class TestLoadOneExpiryFilters:
    """בודק סינון שורות ללא מסחר ושימוש ב-baserate."""

    def _make_mock_conn_for_expiry(self, fetch_ts, df_raw):
        """mock connection המחזיר fetch_ts ואז df_raw ב-pd.read_sql."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)
        return mock_conn

    def test_zero_call_and_put_rows_are_removed(self):
        """שורה שבה call=0 וגם put=0 מסוננת לפני נרמול."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        rows = [
            _make_chain_row(1900.0, call_price=0.0, put_price=0.0),   # יסונן
            _make_chain_row(1920.0, call_price=10.0, put_price=0.0),  # נשאר
        ]
        df_raw = pd.DataFrame(rows)
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)
        mock_engine = MagicMock()

        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(mock_engine, mock_conn, "2026-05-29")

        assert result is not None
        chain_df = result[0]
        assert len(chain_df) == 1
        assert chain_df.iloc[0]["strike"] == pytest.approx(1920.0)

    def test_row_with_only_put_zero_is_kept(self):
        """שורה עם call > 0 נשארת גם אם put = 0."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        df_raw = pd.DataFrame([_make_chain_row(1920.0, call_price=5.0, put_price=0.0)])
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)
        mock_engine = MagicMock()

        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(mock_engine, mock_conn, "2026-05-29")

        assert result is not None
        assert len(result[0]) == 1

    def test_returns_none_when_all_rows_are_zero(self):
        """אם כל השורות הן 0/0 — מחזיר None."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        df_raw = pd.DataFrame([
            _make_chain_row(1900.0, call_price=0.0, put_price=0.0),
            _make_chain_row(1920.0, call_price=0.0, put_price=0.0),
        ])
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)
        mock_engine = MagicMock()

        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(mock_engine, mock_conn, "2026-05-29")

        assert result is None

    def test_baserate_from_baserate_call_column(self):
        """baserate נלקח מ-baserate_call כשהוא זמין."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        df_raw = pd.DataFrame([_make_chain_row(1920.0, baserate_call=1915.0)])
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)
        mock_engine = MagicMock()

        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(mock_engine, mock_conn, "2026-05-29")

        assert result is not None
        baserate = result[3]
        assert baserate == pytest.approx(1915.0, abs=0.01)

    def test_baserate_falls_back_to_mean_strike_when_null(self):
        """baserate_call=None → fallback לממוצע סטרייקים."""
        fetch_ts = datetime(2026, 5, 22, 10, 0)
        rows = [
            _make_chain_row(1900.0, baserate_call=None),
            _make_chain_row(1920.0, baserate_call=None),
        ]
        df_raw = pd.DataFrame(rows)
        df_raw["baserate_call"] = None   # force None column
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)
        mock_engine = MagicMock()

        with patch("supabase_loader.pd.read_sql", return_value=df_raw):
            result = _load_one_expiry(mock_engine, mock_conn, "2026-05-29")

        assert result is not None
        baserate = result[3]
        assert baserate == pytest.approx(1910.0, abs=0.01)  # (1900+1920)/2


# ─── _to_nis ──────────────────────────────────────────────────────────

class TestToNis:
    """כלל סף: ≤ 1000 → נקודות × MULTIPLIER → ₪; > 1000 → כבר ₪."""

    def test_small_value_multiplied_by_multiplier(self):
        """2.0 נקודות × 50 = 100 ₪."""
        assert _to_nis(2.0) == pytest.approx(100.0, abs=0.01)

    def test_large_value_kept_as_is(self):
        """26623.0 > 1000 → כבר ₪, ללא שינוי."""
        assert _to_nis(26623.0) == pytest.approx(26623.0, abs=0.01)

    def test_boundary_exactly_1000_treated_as_points(self):
        """1000.0 (≤ 1000) → 1000 × 50 = 50000 ₪."""
        assert _to_nis(1000.0) == pytest.approx(50000.0, abs=0.01)

    def test_above_boundary_kept_as_nis(self):
        """1001.0 > 1000 → נשאר 1001.0 ₪."""
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
    מתעד את המרת המחיר לפי כלל סף.

    ≤ 1000 → נקודות × 50 → ₪  (call_price); call_pts = ₪ / 50 = ערך מקורי
    > 1000 → כבר ₪             (call_price); call_pts = ₪ / 50
    """

    def _run_with_raw_price(self, raw_db_price: float) -> tuple:
        """מחזיר (call_price_nis, call_pts) לאחר נרמול."""
        fetch_ts     = datetime(2026, 5, 22, 10, 0)
        chain_df_raw = pd.DataFrame([_make_chain_row(1920.0, call_price=raw_db_price)])

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("2026-05-29",)]
        mock_conn.execute.return_value.fetchone.return_value = (fetch_ts,)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("supabase_loader.pd.read_sql", return_value=chain_df_raw):
            result = get_latest_option_chain(expiry_date="2026-05-29", engine=mock_engine)

        row = result["expiries"][0]["chain"].iloc[0]
        return float(row["call_price"]), float(row["call_pts"])

    def test_small_value_treated_as_points(self):
        """2.0 (≤ 1000 נקודות) → 2.0 × 50 = 100 ₪ → call_pts = 2.0."""
        call_price, call_pts = self._run_with_raw_price(2.0)
        assert call_price == pytest.approx(100.0, abs=0.01)
        assert call_pts   == pytest.approx(2.0, abs=0.001)

    def test_large_value_treated_as_nis(self):
        """26623.0 (> 1000 ₪) → נשאר 26623.0 ₪ → call_pts = 532.46."""
        call_price, call_pts = self._run_with_raw_price(26623.0)
        assert call_price == pytest.approx(26623.0, abs=0.01)
        assert call_pts   == pytest.approx(26623.0 / MULTIPLIER, abs=0.01)

    def test_zero_price_stays_zero(self):
        """מחיר 0 ב-DB → 0 ₪ → 0 נקודות."""
        call_price, call_pts = self._run_with_raw_price(0.0)
        assert call_price == pytest.approx(0.0, abs=0.001)
        assert call_pts   == pytest.approx(0.0, abs=0.001)

    def test_boundary_1000_treated_as_points(self):
        """1000.0 (≤ 1000) → 1000 × 50 = 50000 ₪ → call_pts = 1000.0."""
        call_price, call_pts = self._run_with_raw_price(1000.0)
        assert call_price == pytest.approx(50000.0, abs=0.01)
        assert call_pts   == pytest.approx(1000.0, abs=0.01)
