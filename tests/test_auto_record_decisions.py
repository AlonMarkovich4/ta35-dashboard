"""
בדיקות יחידה ל-scripts/auto_record_decisions.py.

כל ה-I/O ממוקק: בניית engine (_make_engine), בדיקת החיבור (SELECT 1), והלוגיקה
(record_decisions_for_upcoming). אין DB אמיתי. נבדקים קודי היציאה והחוזה:
  env חסר → 2 · שגיאת DB → 1 · אין פקיעות → 0 · תיעוד → 0 ·
  idempotency (הכל דולג) → 0 · שגיאת תיעוד → 1.
"""
import datetime as _dt
import sys
from datetime import date as _date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))

import paper_db
import decision_recorder
import auto_record_decisions as ard


@pytest.fixture(autouse=True)
def _bypass_trading_day_guard(monkeypatch):
    """
    הבדיקות במודול הזה בודקות את לוגיקת התיעוד, לא את שער יום-המסחר.
    בלי העקיפה התוצאה הייתה תלויה ביום שבו במקרה רץ ה-CI (הסקריפט מדלג
    בסופי שבוע ובחגים). השער עצמו נבדק ב-test_trading_calendar.py
    וב-TestTradingDayGuard למטה.
    """
    monkeypatch.setenv("FORCE_RUN", "true")


def _mock_engine(execute_raises=False):
    """engine מדומה שתומך ב-`with engine.connect() as conn: conn.execute(...)`."""
    engine = MagicMock()
    conn = MagicMock()
    if execute_raises:
        conn.execute.side_effect = Exception("DB down")
    cm = engine.connect.return_value
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    return engine


@pytest.fixture
def patch_record(monkeypatch):
    """ממקק את record_decisions_for_upcoming; ברירת מחדל: ללא פקיעות ([])."""
    mock = MagicMock(return_value=[])
    monkeypatch.setattr(decision_recorder, "record_decisions_for_upcoming", mock)
    return mock


def _row(expiry, status, sid=2, regime="calm", etype="W"):
    return {"expiry_date": expiry, "expiry_type": etype, "top_strategy_id": sid,
            "regime": regime, "status": status, "log_id": 1 if status == "recorded" else None}


# ─── env חסר → EXIT_CONFIG (2) ──────────────────────────────────────────

def test_missing_env_returns_config(monkeypatch, patch_record):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert ard.main() == ard.EXIT_CONFIG
    patch_record.assert_not_called()


# ─── שגיאת חיבור DB → EXIT_ERROR (1) ────────────────────────────────────

def test_db_connection_error_returns_error(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine",
                        lambda *_a, **_k: _mock_engine(execute_raises=True))
    assert ard.main() == ard.EXIT_ERROR
    patch_record.assert_not_called()       # לא הגענו לתיעוד


def test_engine_none_returns_error(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: None)
    assert ard.main() == ard.EXIT_ERROR
    patch_record.assert_not_called()


# ─── אין פקיעות → EXIT_OK (0) ───────────────────────────────────────────

def test_no_upcoming_returns_ok(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
    patch_record.return_value = []
    assert ard.main() == ard.EXIT_OK
    patch_record.assert_called_once()


# ─── תיעוד תקין → EXIT_OK (0) + טריגר scheduled ─────────────────────────

def test_records_and_uses_scheduled_trigger(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    eng = _mock_engine()
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: eng)
    patch_record.return_value = [_row("2099-01-15", "recorded", sid=2),
                                 _row("2099-01-16", "recorded", sid=5)]
    assert ard.main() == ard.EXIT_OK

    _, kwargs = patch_record.call_args
    assert kwargs["trigger"] == "scheduled"
    assert kwargs["engine_version"] == "layer1-v1"
    assert kwargs["engine"] is eng        # מועבר אותו engine שנבדק ב-SELECT 1


# ─── idempotency: הכל כבר תועד היום → EXIT_OK (0) ───────────────────────

def test_idempotent_all_skipped_returns_ok(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
    patch_record.return_value = [_row("2099-01-15", "skipped_exists"),
                                 _row("2099-01-16", "skipped_exists")]
    assert ard.main() == ard.EXIT_OK


# ─── שגיאת תיעוד (status=error) → EXIT_ERROR (1) ────────────────────────

def test_record_error_returns_error(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
    patch_record.return_value = [_row("2099-01-15", "recorded"),
                                 _row("2099-01-16", "error", sid=None, regime=None)]
    assert ard.main() == ard.EXIT_ERROR


# ─── חריגה בתוך record → EXIT_ERROR (1) ─────────────────────────────────

def test_record_raises_returns_error(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
    patch_record.side_effect = RuntimeError("boom")
    assert ard.main() == ard.EXIT_ERROR


# ─── שער יום-המסחר (אירוע תשעה באב, 23/07/2026) ──────────────────────────

class _FixedNow:
    """datetime מזויף — now() מחזיר תמיד את התאריך שנבחר, בכל אזור-זמן."""

    def __init__(self, d):
        self._d = d

    def now(self, tz=None):
        return _dt.datetime(self._d.year, self._d.month, self._d.day, 12, 0, tzinfo=tz)


class TestTradingDayGuard:
    """
    לפני התיקון: ה-cron לבדו הכריע מתי לרוץ, ולכן בתשעה באב נרשמו החלטות
    והמלצות לפקיעה ביום שהבורסה הייתה סגורה — עם ריצה ירוקה.
    """

    def _run_on(self, monkeypatch, day, force):
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        monkeypatch.setattr(ard, "datetime", _FixedNow(day))
        if force:
            monkeypatch.setenv("FORCE_RUN", "true")
        else:
            monkeypatch.delenv("FORCE_RUN", raising=False)
        return ard.main()

    def test_tisha_bav_is_skipped(self, monkeypatch, patch_record):
        """23/07/2026 — חמישי, יום חול לכל דבר, אבל הבורסה סגורה."""
        assert self._run_on(monkeypatch, _date(2026, 7, 23), force=False) == ard.EXIT_OK
        patch_record.assert_not_called()

    def test_sunday_is_skipped(self, monkeypatch, patch_record):
        """ראשון אינו יום מסחר מאז שהבורסה עברה לשבוע שני–שישי."""
        assert self._run_on(monkeypatch, _date(2026, 7, 26), force=False) == ard.EXIT_OK
        patch_record.assert_not_called()

    def test_friday_runs(self, monkeypatch, patch_record):
        """שישי הוא יום מסחר מלא — ה-cron הישן ('0-4') דילג עליו."""
        monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
        assert self._run_on(monkeypatch, _date(2026, 7, 24), force=False) == ard.EXIT_OK
        patch_record.assert_called_once()

    def test_ordinary_trading_day_runs(self, monkeypatch, patch_record):
        monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
        assert self._run_on(monkeypatch, _date(2026, 7, 22), force=False) == ard.EXIT_OK
        patch_record.assert_called_once()

    def test_force_run_overrides_holiday(self, monkeypatch, patch_record):
        """הרצה ידנית מ-workflow_dispatch חייבת לעבוד גם בחג."""
        monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
        assert self._run_on(monkeypatch, _date(2026, 7, 23), force=True) == ard.EXIT_OK
        patch_record.assert_called_once()
