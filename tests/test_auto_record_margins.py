"""
בדיקות יחידה ל-scripts/auto_record_margins.py.

כל ה-I/O ממוקק: בניית engine (_make_engine), בדיקת החיבור (SELECT 1), והלוגיקה
(record_margin_recommendations_for_upcoming). אין DB אמיתי. נבדקים קודי היציאה והחוזה:
  env חסר → 2 · שגיאת DB → 1 · אין פקיעות → 0 · תיעוד → 0 ·
  idempotency (הכל דולג) → 0 · אין-שרשרת (no_recommendation) → 0 · שגיאת תיעוד → 1.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))

import paper_db
import margin_recorder
import auto_record_margins as arm


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
    """ממקק את record_margin_recommendations_for_upcoming; ברירת מחדל: ללא פקיעות ([])."""
    mock = MagicMock(return_value=[])
    monkeypatch.setattr(margin_recorder,
                        "record_margin_recommendations_for_upcoming", mock)
    return mock


def _row(expiry, status, margin=1.75, hold=0.978, etype="W"):
    recorded = status == "recorded"
    return {"expiry_date": expiry, "expiry_type": etype,
            "selected_margin": margin if recorded else None,
            "hold_blended": hold if recorded else None,
            "status": status, "rec_id": 1 if recorded else None}


# ─── env חסר → EXIT_CONFIG (2) ──────────────────────────────────────────

def test_missing_env_returns_config(monkeypatch, patch_record):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert arm.main() == arm.EXIT_CONFIG
    patch_record.assert_not_called()


# ─── שגיאת חיבור DB → EXIT_ERROR (1) ────────────────────────────────────

def test_db_connection_error_returns_error(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine",
                        lambda *_a, **_k: _mock_engine(execute_raises=True))
    assert arm.main() == arm.EXIT_ERROR
    patch_record.assert_not_called()       # לא הגענו לתיעוד


def test_engine_none_returns_error(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: None)
    assert arm.main() == arm.EXIT_ERROR
    patch_record.assert_not_called()


# ─── אין פקיעות → EXIT_OK (0) ───────────────────────────────────────────

def test_no_upcoming_returns_ok(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
    patch_record.return_value = []
    assert arm.main() == arm.EXIT_OK
    patch_record.assert_called_once()


# ─── תיעוד תקין → EXIT_OK (0) + טריגר scheduled + גרסה margin-v1.1 ───────

def test_records_and_uses_scheduled_trigger(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    eng = _mock_engine()
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: eng)
    patch_record.return_value = [_row("2099-01-15", "recorded", margin=1.75),
                                 _row("2099-01-16", "recorded", margin=2.0)]
    assert arm.main() == arm.EXIT_OK

    _, kwargs = patch_record.call_args
    assert kwargs["trigger"] == "scheduled"
    assert kwargs["engine_version"] == "margin-v1.1"
    assert kwargs["engine"] is eng        # מועבר אותו engine שנבדק ב-SELECT 1


# ─── idempotency: הכל כבר תועד היום → EXIT_OK (0) ───────────────────────

def test_idempotent_all_skipped_returns_ok(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
    patch_record.return_value = [_row("2099-01-15", "skipped_exists"),
                                 _row("2099-01-16", "skipped_exists")]
    assert arm.main() == arm.EXIT_OK


# ─── אין שרשרת מלאה (no_recommendation) → EXIT_OK (0), לא שגיאה ─────────

def test_no_recommendation_is_ok(monkeypatch, patch_record):
    """פקיעה בלי שרשרת/מרווח תקין היא מצב רגיל — לא מפילה את ה-Action."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
    patch_record.return_value = [_row("2099-01-15", "recorded"),
                                 _row("2099-01-16", "no_recommendation")]
    assert arm.main() == arm.EXIT_OK


# ─── שגיאת תיעוד (status=error) → EXIT_ERROR (1) ────────────────────────

def test_record_error_returns_error(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
    patch_record.return_value = [_row("2099-01-15", "recorded"),
                                 _row("2099-01-16", "error")]
    assert arm.main() == arm.EXIT_ERROR


# ─── חריגה בתוך record → EXIT_ERROR (1) ─────────────────────────────────

def test_record_raises_returns_error(monkeypatch, patch_record):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(paper_db, "_make_engine", lambda *_a, **_k: _mock_engine())
    patch_record.side_effect = RuntimeError("boom")
    assert arm.main() == arm.EXIT_ERROR
