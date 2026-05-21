"""
בדיקות יחידה ל-webhook_server.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi.testclient import TestClient

from webhook_server import app

client = TestClient(app, raise_server_exceptions=False)

# ─── helpers ─────────────────────────────────────────────────────────────

_WAR   = {"source": "interactiveil", "text": "מלחמה: תקיפה ישירה של חיזבאללה על הצפון", "source_msg_id": 101, "has_media": False}
_RATE  = {"source": "interactiveil", "text": "בנק מרכזי מכריז על הורדת ריבית בהפתעה", "source_msg_id": 102, "has_media": False}
_IRREL = {"source": "interactiveil", "text": "מזג האוויר מחר: גשם בצפון ושמש בדרום",  "source_msg_id": 103, "has_media": False}
_UNCLS = {"source": "interactiveil", "text": "בורסה עולה, מדד המניות שבר שיא",         "source_msg_id": 104, "has_media": False}


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["id", "event_date", "name", "category", "description", "source"])


def _df_with(names: list[str]) -> pd.DataFrame:
    return pd.DataFrame([
        {"id": i + 1, "name": n, "event_date": "2024-01-01",
         "category": "מלחמה", "description": "", "source": "interactiveil"}
        for i, n in enumerate(names)
    ])


# ─── TestReceiveTelegramSaved ─────────────────────────────────────────────

class TestReceiveTelegramSaved:
    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events", return_value=_empty_df())
    @patch("webhook_server.add_event",       return_value=42)
    def test_war_returns_saved(self, *_):
        resp = client.post("/webhook/telegram", json=_WAR)
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"

    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events", return_value=_empty_df())
    @patch("webhook_server.add_event",       return_value=7)
    def test_interest_rate_returns_saved(self, *_):
        resp = client.post("/webhook/telegram", json=_RATE)
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"

    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events", return_value=_empty_df())
    @patch("webhook_server.add_event",       return_value=42)
    def test_response_includes_category(self, *_):
        resp = client.post("/webhook/telegram", json=_WAR)
        assert "category" in resp.json()
        assert resp.json()["category"] == "מלחמה"

    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events", return_value=_empty_df())
    @patch("webhook_server.add_event",       return_value=99)
    def test_response_includes_event_id(self, *_):
        resp = client.post("/webhook/telegram", json=_WAR)
        assert resp.json()["event_id"] == 99

    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events", return_value=_empty_df())
    @patch("webhook_server.add_event",       return_value=5)
    def test_add_event_called_once(self, mock_add, *_):
        client.post("/webhook/telegram", json=_WAR)
        mock_add.assert_called_once()

    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events", return_value=_empty_df())
    @patch("webhook_server.add_event",       return_value=5)
    def test_has_media_flag_recorded(self, mock_add, *_):
        payload = {**_WAR, "has_media": True}
        client.post("/webhook/telegram", json=payload)
        call_desc = mock_add.call_args[0][4]  # description positional arg
        assert "מדיה" in call_desc

    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events", return_value=_empty_df())
    @patch("webhook_server.add_event",       return_value=5)
    def test_source_msg_id_in_description(self, mock_add, *_):
        client.post("/webhook/telegram", json=_WAR)
        call_desc = mock_add.call_args[0][4]
        assert "101" in call_desc

    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events", return_value=_empty_df())
    @patch("webhook_server.add_event",       return_value=5)
    def test_source_field_passed_to_add_event(self, mock_add, *_):
        client.post("/webhook/telegram", json=_WAR)
        call_kwargs = mock_add.call_args[1]
        assert call_kwargs.get("source") == "interactiveil"


# ─── TestReceiveTelegramSkipped ───────────────────────────────────────────

class TestReceiveTelegramSkipped:
    def test_irrelevant_text_skipped(self):
        resp = client.post("/webhook/telegram", json=_IRREL)
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        assert resp.json()["reason"] == "not_market_relevant"

    def test_unclassified_relevant_skipped(self):
        resp = client.post("/webhook/telegram", json=_UNCLS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        assert resp.json()["reason"] == "unclassified"

    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events")
    def test_duplicate_skipped(self, mock_load, *_):
        # existing event with same name prefix
        existing_name = _WAR["text"][:80]
        mock_load.return_value = _df_with([existing_name])
        resp = client.post("/webhook/telegram", json=_WAR)
        assert resp.json()["status"] == "skipped"
        assert resp.json()["reason"] == "duplicate"

    def test_add_event_not_called_for_irrelevant(self):
        with patch("webhook_server.add_event") as mock_add:
            client.post("/webhook/telegram", json=_IRREL)
            mock_add.assert_not_called()

    def test_add_event_not_called_for_unclassified(self):
        with patch("webhook_server.add_event") as mock_add:
            client.post("/webhook/telegram", json=_UNCLS)
            mock_add.assert_not_called()


# ─── TestWebhookAuth ──────────────────────────────────────────────────────

class TestWebhookAuth:
    def test_no_secret_env_accepts_all(self):
        """ללא WEBHOOK_SECRET — כל בקשה מתקבלת (לפי is_market_relevant)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WEBHOOK_SECRET", None)
            resp = client.post("/webhook/telegram", json=_IRREL)
            assert resp.status_code == 200  # skipped but not 403

    def test_secret_set_rejects_missing_header(self):
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "s3cr3t"}):
            resp = client.post("/webhook/telegram", json=_IRREL)
            assert resp.status_code == 403

    def test_secret_set_rejects_wrong_token(self):
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "s3cr3t"}):
            resp = client.post(
                "/webhook/telegram", json=_IRREL,
                headers={"Authorization": "Bearer wrong"},
            )
            assert resp.status_code == 403

    @patch("webhook_server.get_engine",     return_value=MagicMock())
    @patch("webhook_server.init_events_db")
    @patch("webhook_server.load_all_events", return_value=_empty_df())
    @patch("webhook_server.add_event",       return_value=1)
    def test_secret_set_accepts_valid_bearer(self, *_):
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "s3cr3t"}):
            resp = client.post(
                "/webhook/telegram", json=_WAR,
                headers={"Authorization": "Bearer s3cr3t"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "saved"

    def test_bearer_prefix_required(self):
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "s3cr3t"}):
            resp = client.post(
                "/webhook/telegram", json=_IRREL,
                headers={"Authorization": "s3cr3t"},  # missing "Bearer "
            )
            assert resp.status_code == 403


# ─── TestWebhookValidation ────────────────────────────────────────────────

class TestWebhookValidation:
    def test_missing_source_returns_422(self):
        resp = client.post("/webhook/telegram", json={"text": "מלחמה"})
        assert resp.status_code == 422

    def test_missing_text_returns_422(self):
        resp = client.post("/webhook/telegram", json={"source": "test"})
        assert resp.status_code == 422

    def test_empty_body_returns_422(self):
        resp = client.post("/webhook/telegram", json={})
        assert resp.status_code == 422

    def test_optional_fields_have_defaults(self):
        """source_msg_id ו-has_media הם אופציונליים."""
        resp = client.post("/webhook/telegram",
                           json={"source": "test", "text": _IRREL["text"]})
        assert resp.status_code == 200  # processed (skipped for irrelevant)

    def test_non_json_returns_422(self):
        resp = client.post("/webhook/telegram", content=b"not-json",
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 422
