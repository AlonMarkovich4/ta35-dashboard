"""
בדיקות יחידה ל-scripts/auto_record_decisions.py.

כל ה-I/O ממוקק: בניית engine (_make_engine), בדיקת החיבור (SELECT 1), והלוגיקה
(record_decisions_for_upcoming). אין DB אמיתי. נבדקים קודי היציאה והחוזה:
  env חסר → 2 · שגיאת DB → 1 · אין פקיעות → 0 · תיעוד → 0 ·
  idempotency (הכל דולג) → 0 · שגיאת תיעוד → 1.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))

import paper_db
import decision_recorder
import auto_record_decisions as ard


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
