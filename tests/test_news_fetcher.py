"""
בדיקות יחידה למודול news_fetcher.
"""
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from events import init_events_db, load_all_events, seed_events
from news_fetcher import (
    classify_event,
    fetch_all_feeds,
    is_market_relevant,
    save_new_events,
)


# ─── helpers ─────────────────────────────────────────────────────────────

def _mem_engine():
    """מנוע SQLite זיכרון לבדיקות — נקי בכל קריאה."""
    eng = create_engine("sqlite:///:memory:")
    init_events_db(eng)
    return eng


class _MockEntry:
    """מחקה FeedParserDict entry."""
    def __init__(self, data: dict):
        self._data = data

    def get(self, key, default=""):
        return self._data.get(key, default)


def _mock_feed(entries: list[dict]):
    feed = MagicMock()
    feed.entries = [_MockEntry(e) for e in entries]
    return feed


# ─── TestClassifyEvent ───────────────────────────────────────────────────

class TestClassifyEvent:
    def test_war_keywords_title(self):
        assert classify_event("תקיפה על עזה", "") == "מלחמה"

    def test_war_keyword_in_summary(self):
        assert classify_event("עדכון שוטף", "טיל שוגר לישראל") == "מלחמה"

    def test_interest_rate(self):
        assert classify_event("הורדת ריבית צפויה", "") == "ריבית"

    def test_crisis(self):
        assert classify_event("מיתון בכלכלה", "") == "משבר"

    def test_political(self):
        assert classify_event("ממשלה מחליטה", "ישיבת קואליציה") == "פוליטי"

    def test_pandemic(self):
        assert classify_event("גל קורונה חדש", "") == "מגפה"

    def test_returns_none_for_irrelevant(self):
        assert classify_event("מחיר הגבינה עלה", "סופרמרקט מוכר") is None

    def test_returns_none_for_empty(self):
        assert classify_event("", "") is None

    def test_central_bank_interest(self):
        assert classify_event("בנק מרכזי מכריז", "") == "ריבית"

    def test_hamas_war(self):
        assert classify_event("חמאס משגר רקטות", "") == "מלחמה"

    def test_iran_war(self):
        assert classify_event("איראן מאיימת", "") == "מלחמה"

    def test_hezbollah_war(self):
        assert classify_event("חיזבאללה ממשיך", "") == "מלחמה"

    def test_crisis_collapse(self):
        assert classify_event("קריסה של הבנק", "") == "משבר"

    def test_pandemic_virus(self):
        assert classify_event("נגיף חדש התגלה", "") == "מגפה"


# ─── TestIsMarketRelevant ────────────────────────────────────────────────

class TestIsMarketRelevant:
    def test_war_title_relevant(self):
        assert is_market_relevant("מלחמה פורצת", "") is True

    def test_economy_term_relevant(self):
        assert is_market_relevant("כלכלה ישראל", "") is True

    def test_stock_market_relevant(self):
        assert is_market_relevant("בורסה תל אביב", "") is True

    def test_boring_news_not_relevant(self):
        assert is_market_relevant("מזג האוויר מחר", "גשם צפוי בצפון") is False

    def test_summary_can_make_relevant(self):
        assert is_market_relevant("כתבה רגילה", "מניות עולות") is True

    def test_empty_not_relevant(self):
        assert is_market_relevant("", "") is False

    def test_dollar_relevant(self):
        assert is_market_relevant("שקל מול דולר", "") is True

    def test_inflation_relevant(self):
        assert is_market_relevant("אינפלציה זינקה", "") is True

    def test_pandemic_relevant(self):
        assert is_market_relevant("מגפה חדשה", "") is True

    def test_interest_relevant(self):
        assert is_market_relevant("ריבית עולה", "") is True


# ─── TestFetchAllFeeds ───────────────────────────────────────────────────

class TestFetchAllFeeds:
    _ENTRY_DATA = {
        "title":            "העלאת ריבית מפתיעה",
        "summary":          "הפד הכריז על העלאה",
        "published_parsed": (2024, 5, 15, 10, 0, 0, 2, 136, 0),
    }

    def test_returns_list(self):
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([self._ENTRY_DATA])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert isinstance(result, list)

    def test_correct_source_name(self):
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([self._ENTRY_DATA])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert result[0]["source"] == "גלובס"

    def test_title_stripped_of_html(self):
        entry = {**self._ENTRY_DATA, "title": "<b>ריבית</b> עולה"}
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([entry])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert result[0]["title"] == "ריבית עולה"

    def test_summary_stripped_of_html(self):
        entry = {**self._ENTRY_DATA, "summary": "<p>הפד הכריז</p>"}
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([entry])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert result[0]["summary"] == "הפד הכריז"

    def test_date_parsed_from_published_parsed(self):
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([self._ENTRY_DATA])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert result[0]["published"] == date(2024, 5, 15)

    def test_uses_today_when_no_date(self):
        entry = {**self._ENTRY_DATA, "published_parsed": None}
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([entry])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert result[0]["published"] == date.today()

    def test_skips_entry_without_title(self):
        entry = {**self._ENTRY_DATA, "title": ""}
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([entry])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert result == []

    def test_empty_feed_returns_empty(self):
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert result == []

    def test_network_error_silently_skipped(self):
        with patch("news_fetcher.feedparser.parse", side_effect=Exception("timeout")):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert result == []

    def test_multiple_sources_combined(self):
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([self._ENTRY_DATA])):
            result = fetch_all_feeds(feeds={"A": "http://a", "B": "http://b"})
        assert len(result) == 2

    def test_result_has_required_keys(self):
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([self._ENTRY_DATA])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        for key in ("published", "title", "summary", "source"):
            assert key in result[0]

    def test_uses_description_as_fallback_for_summary(self):
        entry = {
            "title": "כותרת",
            "description": "תיאור",
            "published_parsed": None,
        }
        with patch("news_fetcher.feedparser.parse", return_value=_mock_feed([entry])):
            result = fetch_all_feeds(feeds={"גלובס": "http://x"})
        assert result[0]["summary"] == "תיאור"


# ─── TestSaveNewEvents ───────────────────────────────────────────────────

class TestSaveNewEvents:
    _RELEVANT_ENTRY = {
        "published": date(2024, 6, 1),
        "title":     "מלחמה בצפון מתגברת",
        "summary":   "תנועת חיזבאללה תוקפת",
        "source":    "גלובס",
    }

    def _patch_fetch(self, articles):
        return patch("news_fetcher.fetch_all_feeds", return_value=articles)

    def test_saves_relevant_classified_article(self):
        eng = _mem_engine()
        with self._patch_fetch([self._RELEVANT_ENTRY]):
            n = save_new_events(eng)
        assert n == 1
        ev_df = load_all_events(eng)
        assert len(ev_df) == 1

    def test_skips_irrelevant_article(self):
        eng = _mem_engine()
        art = {**self._RELEVANT_ENTRY, "title": "ספורט — כדורגל", "summary": "משחק אמש"}
        with self._patch_fetch([art]):
            n = save_new_events(eng)
        assert n == 0

    def test_skips_unclassified_article(self):
        # relevant market terms but no category keyword
        eng = _mem_engine()
        art = {**self._RELEVANT_ENTRY, "title": "בורסה עולה", "summary": "מדד מניות"}
        with self._patch_fetch([art]):
            n = save_new_events(eng)
        assert n == 0

    def test_avoids_duplicate_names(self):
        eng = _mem_engine()
        with self._patch_fetch([self._RELEVANT_ENTRY]):
            n1 = save_new_events(eng)
        with self._patch_fetch([self._RELEVANT_ENTRY]):
            n2 = save_new_events(eng)
        assert n1 == 1
        assert n2 == 0
        assert len(load_all_events(eng)) == 1

    def test_returns_count_of_saved(self):
        eng = _mem_engine()
        arts = [
            {**self._RELEVANT_ENTRY, "title": "מלחמה א"},
            {**self._RELEVANT_ENTRY, "title": "מלחמה ב"},
        ]
        with self._patch_fetch(arts):
            n = save_new_events(eng)
        assert n == 2

    def test_empty_feed_returns_zero(self):
        eng = _mem_engine()
        with self._patch_fetch([]):
            n = save_new_events(eng)
        assert n == 0

    def test_saved_article_has_correct_category(self):
        eng = _mem_engine()
        with self._patch_fetch([self._RELEVANT_ENTRY]):
            save_new_events(eng)
        ev_df = load_all_events(eng)
        assert ev_df.iloc[0]["category"] == "מלחמה"

    def test_saved_article_includes_source_in_description(self):
        eng = _mem_engine()
        with self._patch_fetch([self._RELEVANT_ENTRY]):
            save_new_events(eng)
        ev_df = load_all_events(eng)
        assert "גלובס" in ev_df.iloc[0]["description"]

    def test_does_not_override_existing_seed_events(self):
        eng = _mem_engine()
        seed_events(eng)
        count_before = len(load_all_events(eng))
        with self._patch_fetch([self._RELEVANT_ENTRY]):
            save_new_events(eng)
        count_after = len(load_all_events(eng))
        assert count_after == count_before + 1

    def test_interest_rate_article_classified(self):
        eng = _mem_engine()
        art = {**self._RELEVANT_ENTRY, "title": "הפד מעלה ריבית", "summary": "העלאה של 0.5%"}
        with self._patch_fetch([art]):
            save_new_events(eng)
        ev_df = load_all_events(eng)
        assert ev_df.iloc[0]["category"] == "ריבית"
