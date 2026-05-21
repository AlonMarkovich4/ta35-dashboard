"""
בדיקות יחידה למודול events.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from events import (
    _SEED_EVENTS,
    add_event,
    compute_risk_score,
    delete_event,
    enrich_expiries_with_events,
    get_events_for_expiry,
    init_events_db,
    load_all_events,
    seed_events,
)


# ─── fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def engine():
    """מנוע SQLite זמני בזכרון לכל בדיקה."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    init_events_db(eng)
    return eng


@pytest.fixture
def seeded_engine(engine):
    """מנוע עם אירועי ברירת מחדל מוזרעים."""
    seed_events(engine, force=True)
    return engine


@pytest.fixture
def simple_expiries():
    """DataFrame פקיעות מינימלי לבדיקות."""
    return pd.DataFrame({
        "expiry_date": pd.to_datetime([
            "2020-03-19",  # ליד קורונה מרץ 2020
            "2021-06-17",  # לא ליד אירוע
            "2023-10-12",  # ליד מתקפת חמאס
            "2024-01-15",  # לא ליד אירוע
        ]),
        "expiry_type": ["W", "W", "W", "M"],
        "move_pct":    [-4.5, 0.3, -6.2, 0.8],
    })


# ─── init_events_db ──────────────────────────────────────────────────

class TestInitEventsDb:
    def test_creates_events_table(self, engine):
        from sqlalchemy import text
        with engine.connect() as conn:
            tables = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
            ).fetchall()
        assert len(tables) == 1

    def test_idempotent(self, engine):
        init_events_db(engine)  # second call should not raise
        init_events_db(engine)


# ─── seed_events ─────────────────────────────────────────────────────

class TestSeedEvents:
    def test_seeds_all_events(self, engine):
        n = seed_events(engine, force=True)
        assert n == len(_SEED_EVENTS)

    def test_does_not_seed_twice_without_force(self, engine):
        seed_events(engine)
        n = seed_events(engine)  # second call without force
        assert n == 0

    def test_force_reseeds(self, engine):
        seed_events(engine)
        n = seed_events(engine, force=True)
        assert n == len(_SEED_EVENTS)
        df = load_all_events(engine)
        assert len(df) == len(_SEED_EVENTS)

    def test_seed_events_have_required_fields(self, seeded_engine):
        df = load_all_events(seeded_engine)
        assert df["name"].notna().all()
        assert df["category"].notna().all()
        assert df["event_date"].notna().all()


# ─── load_all_events ─────────────────────────────────────────────────

class TestLoadAllEvents:
    def test_returns_dataframe(self, seeded_engine):
        df = load_all_events(seeded_engine)
        assert isinstance(df, pd.DataFrame)

    def test_has_required_columns(self, seeded_engine):
        df = load_all_events(seeded_engine)
        for col in ("id", "event_date", "name", "category", "description"):
            assert col in df.columns

    def test_sorted_by_date_ascending(self, seeded_engine):
        df = load_all_events(seeded_engine)
        dates = df["event_date"].tolist()
        assert dates == sorted(dates)

    def test_empty_engine_returns_empty_df(self, engine):
        df = load_all_events(engine)
        assert df.empty

    def test_event_date_is_datetime(self, seeded_engine):
        df = load_all_events(seeded_engine)
        assert pd.api.types.is_datetime64_any_dtype(df["event_date"])


# ─── add_event / delete_event ─────────────────────────────────────────

class TestAddDeleteEvent:
    def test_add_returns_id(self, engine):
        ev_id = add_event(engine, "2024-06-01", "בדיקה", "אחר")
        assert isinstance(ev_id, int)
        assert ev_id > 0

    def test_added_event_appears_in_load(self, engine):
        add_event(engine, "2024-06-01", "אירוע בדיקה", "ריבית", "תיאור")
        df = load_all_events(engine)
        assert len(df) == 1
        assert df.iloc[0]["name"] == "אירוע בדיקה"
        assert df.iloc[0]["category"] == "ריבית"

    def test_add_with_date_object(self, engine):
        add_event(engine, date(2024, 6, 1), "בדיקה", "פוליטי")
        df = load_all_events(engine)
        assert not df.empty

    def test_delete_removes_event(self, engine):
        ev_id = add_event(engine, "2024-06-01", "למחיקה", "אחר")
        delete_event(engine, ev_id)
        df = load_all_events(engine)
        assert df.empty

    def test_delete_nonexistent_does_not_raise(self, engine):
        delete_event(engine, 9999)  # should not raise

    def test_multiple_events(self, engine):
        add_event(engine, "2024-01-01", "אחד", "מלחמה")
        add_event(engine, "2024-02-01", "שניים", "ריבית")
        add_event(engine, "2024-03-01", "שלושה", "משבר")
        df = load_all_events(engine)
        assert len(df) == 3


# ─── get_events_for_expiry ───────────────────────────────────────────

class TestGetEventsForExpiry:
    def test_finds_event_within_window(self, engine):
        add_event(engine, "2024-06-01", "אירוע", "מלחמה")
        result = get_events_for_expiry(date(2024, 6, 5), engine, window_days=7)
        assert len(result) == 1
        assert result.iloc[0]["name"] == "אירוע"

    def test_excludes_event_outside_window(self, engine):
        add_event(engine, "2024-05-20", "ישן מדי", "מלחמה")
        result = get_events_for_expiry(date(2024, 6, 5), engine, window_days=7)
        assert result.empty

    def test_includes_event_on_same_day(self, engine):
        add_event(engine, "2024-06-05", "ביום", "ריבית")
        result = get_events_for_expiry(date(2024, 6, 5), engine, window_days=7)
        assert len(result) == 1

    def test_accepts_timestamp(self, engine):
        add_event(engine, "2024-06-01", "אירוע", "פוליטי")
        result = get_events_for_expiry(pd.Timestamp("2024-06-05"), engine, window_days=7)
        assert len(result) == 1

    def test_multiple_events_in_window(self, engine):
        add_event(engine, "2024-06-01", "א", "מלחמה")
        add_event(engine, "2024-06-03", "ב", "ריבית")
        add_event(engine, "2024-05-25", "מחוץ לטווח", "משבר")
        result = get_events_for_expiry(date(2024, 6, 5), engine, window_days=7)
        assert len(result) == 2

    def test_empty_events_returns_empty_df(self, engine):
        result = get_events_for_expiry(date(2024, 6, 5), engine)
        assert result.empty

    def test_window_days_respected(self, engine):
        add_event(engine, "2024-05-29", "שלושה ימים לפני", "ריבית")
        r3 = get_events_for_expiry(date(2024, 6, 1), engine, window_days=3)
        r7 = get_events_for_expiry(date(2024, 6, 1), engine, window_days=7)
        assert len(r3) == 1
        assert len(r7) == 1  # still found

    def test_event_after_expiry_excluded(self, engine):
        add_event(engine, "2024-06-10", "אחרי הפקיעה", "מלחמה")
        result = get_events_for_expiry(date(2024, 6, 5), engine, window_days=7)
        assert result.empty


# ─── enrich_expiries_with_events ─────────────────────────────────────

class TestEnrichExpiries:
    def test_adds_has_event_column(self, seeded_engine, simple_expiries):
        enriched = enrich_expiries_with_events(simple_expiries, seeded_engine)
        assert "has_event" in enriched.columns

    def test_adds_event_names_column(self, seeded_engine, simple_expiries):
        enriched = enrich_expiries_with_events(simple_expiries, seeded_engine)
        assert "event_names" in enriched.columns

    def test_adds_event_categories_column(self, seeded_engine, simple_expiries):
        enriched = enrich_expiries_with_events(simple_expiries, seeded_engine)
        assert "event_categories" in enriched.columns

    def test_known_event_near_corona_detected(self, seeded_engine, simple_expiries):
        enriched = enrich_expiries_with_events(simple_expiries, seeded_engine)
        corona_row = enriched[enriched["expiry_date"] == pd.Timestamp("2020-03-19")]
        assert corona_row["has_event"].values[0]

    def test_known_event_near_hamas_detected(self, seeded_engine, simple_expiries):
        enriched = enrich_expiries_with_events(simple_expiries, seeded_engine)
        hamas_row = enriched[enriched["expiry_date"] == pd.Timestamp("2023-10-12")]
        assert hamas_row["has_event"].values[0]

    def test_quiet_expiry_has_no_event(self, engine, simple_expiries):
        # engine without events
        enriched = enrich_expiries_with_events(simple_expiries, engine)
        assert not enriched["has_event"].any()

    def test_preserves_original_columns(self, seeded_engine, simple_expiries):
        enriched = enrich_expiries_with_events(simple_expiries, seeded_engine)
        for col in simple_expiries.columns:
            assert col in enriched.columns

    def test_does_not_mutate_input(self, seeded_engine, simple_expiries):
        original_cols = list(simple_expiries.columns)
        enrich_expiries_with_events(simple_expiries, seeded_engine)
        assert list(simple_expiries.columns) == original_cols


# ─── compute_risk_score ──────────────────────────────────────────────

class TestComputeRiskScore:
    def test_returns_required_keys(self, seeded_engine, simple_expiries):
        result = compute_risk_score(date(2023, 10, 10), seeded_engine, simple_expiries)
        for key in ("score", "level", "nearby_events", "avg_abs_move_event", "avg_abs_move_normal"):
            assert key in result

    def test_score_in_range(self, seeded_engine, simple_expiries):
        result = compute_risk_score(date(2023, 10, 10), seeded_engine, simple_expiries)
        assert 0.0 <= result["score"] <= 10.0

    def test_high_risk_near_war_event(self, seeded_engine, simple_expiries):
        # 2023-10-10 is 3 days after the Hamas attack (10/07)
        result = compute_risk_score(date(2023, 10, 10), seeded_engine, simple_expiries)
        assert result["score"] > 0

    def test_no_event_gives_low_score(self, seeded_engine, simple_expiries):
        # far future date with no events
        result = compute_risk_score(date(2030, 6, 15), seeded_engine, simple_expiries)
        assert result["score"] < 3.5
        assert result["level"] == "נמוך"

    def test_level_matches_score(self, seeded_engine, simple_expiries):
        result = compute_risk_score(date(2030, 6, 15), seeded_engine, simple_expiries)
        if result["score"] < 3.5:
            assert result["level"] == "נמוך"
        elif result["score"] >= 6.5:
            assert result["level"] == "גבוה"
        else:
            assert result["level"] == "בינוני"

    def test_works_without_expiries(self, seeded_engine):
        result = compute_risk_score(date(2023, 10, 10), seeded_engine, df_expiries=None)
        assert "score" in result
        assert result["avg_abs_move_event"] is None

    def test_nearby_events_list_populated(self, seeded_engine, simple_expiries):
        # date right after Hamas attack
        result = compute_risk_score(date(2023, 10, 10), seeded_engine, simple_expiries)
        assert isinstance(result["nearby_events"], list)
