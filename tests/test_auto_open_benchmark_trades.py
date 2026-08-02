"""
בדיקות ל-scripts/auto_open_benchmark_trades.py.

הסקריפט נוסף 01/08/2026 אחרי שהתגלה שלתיקי ה-benchmark (2–7) מעולם לא הייתה
אוטומציה — 132 עסקאות חסרות על פני 22 פקיעות. הבדיקות מכסות את המדיניות
(זהה לתיק 8), את שני השערים, ואת קודי היציאה.
"""
from __future__ import annotations

import datetime as _dt
import sys
from datetime import date as _date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "src"))

import auto_open_benchmark_trades as aob  # noqa: E402


class _FixedNow:
    """datetime מזויף — now() קפוא על תאריך נבחר; שאר ה-API מואצל לאמיתי."""

    def __init__(self, d):
        self._d = d

    def now(self, tz=None):
        return _dt.datetime(self._d.year, self._d.month, self._d.day, 12, 0, tzinfo=tz)

    def __getattr__(self, name):          # strptime, timezone וכו' — כרגיל
        return getattr(_dt.datetime, name)


def _portfolios(ids=(2, 3, 4, 5, 6, 7)):
    return [{"id": i, "strategy_ids": [i - 1], "commission_per_leg": 2.5} for i in ids]


def _chain(fetch_date):
    return {"expiries": [{"expiry_type": "W", "chain": [1, 2, 3], "fetch_date": fetch_date}]}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.delenv("FORCE_RUN", raising=False)
    monkeypatch.delenv("BENCHMARK_TRADING_ENABLED", raising=False)
    monkeypatch.setattr(aob, "datetime", _FixedNow(_date(2026, 8, 3)))   # שני, יום מסחר


class TestKillSwitch:
    """ברירת המחדל **דלוקה** — אין כאן תלות במנוע או בכיול שנמצא בבדיקה."""

    @pytest.mark.parametrize("value,expected", [
        (None, True), ("", True), ("true", True), ("TRUE", True), ("anything", True),
        ("false", False), ("FALSE", False), ("  false  ", False),
    ])
    def test_parsing(self, monkeypatch, value, expected):
        if value is None:
            monkeypatch.delenv("BENCHMARK_TRADING_ENABLED", raising=False)
        else:
            monkeypatch.setenv("BENCHMARK_TRADING_ENABLED", value)
        assert aob.benchmark_trading_enabled() is expected

    def test_disabled_writes_nothing(self, monkeypatch):
        """כבוי ⇒ יוצא מוקדם, בלי לגעת ב-DB בכלל."""
        monkeypatch.setenv("BENCHMARK_TRADING_ENABLED", "false")
        import paper_db
        monkeypatch.setattr(paper_db, "_make_engine",
                            lambda *a, **k: pytest.fail("נגע ב-DB למרות שהמתג כבוי"))
        assert aob.main() == aob.EXIT_OK


class TestGuards:
    def test_missing_env_exits_config(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert aob.main() == aob.EXIT_CONFIG

    def test_holiday_is_skipped(self, monkeypatch):
        """תשעה באב — יום חול, אבל הבורסה סגורה."""
        monkeypatch.setattr(aob, "datetime", _FixedNow(_date(2026, 7, 23)))
        assert aob.main() == aob.EXIT_OK

    def test_sunday_is_skipped(self, monkeypatch):
        monkeypatch.setattr(aob, "datetime", _FixedNow(_date(2026, 7, 26)))
        assert aob.main() == aob.EXIT_OK


def _run_main(monkeypatch, *, expiries, chain_fetch, portfolios=None, results=None):
    """מריץ main() עם כל תלויות ה-DB/שרשרת ממוקקות. מחזיר (rc, פתיחות שנקראו)."""
    import paper_db
    import paper_trading
    import supabase_loader

    calls = []

    def _open(exp, chain, ports, engine=None):
        calls.append(exp)
        return results if results is not None else [
            {"portfolio_id": p["id"], "strategy_id": p["strategy_ids"][0], "status": "opened"}
            for p in ports
        ]

    monkeypatch.setattr(paper_db, "_make_engine", lambda *a, **k: MagicMock())
    monkeypatch.setattr(paper_db, "get_portfolios",
                        lambda engine=None: portfolios if portfolios is not None
                        else _portfolios())
    monkeypatch.setattr(supabase_loader, "get_available_expiries",
                        lambda engine=None: expiries)
    monkeypatch.setattr(supabase_loader, "get_latest_option_chain",
                        lambda exp, engine=None, **k: _chain(chain_fetch))
    monkeypatch.setattr(paper_trading, "open_trades_for_expiry", _open)
    return aob.main(), calls


class TestPolicy:
    """המדיניות זהה לתיק 8: פותח מיד כשרואה פקיעה, עם min_days_to_expiry=1."""

    def test_opens_for_future_expiry(self, monkeypatch):
        rc, calls = _run_main(monkeypatch, expiries=["2026-08-06"],
                              chain_fetch=_date(2026, 8, 3))
        assert rc == aob.EXIT_OK
        assert calls == ["2026-08-06"]

    def test_tomorrow_still_opens(self, monkeypatch):
        """גבול השער: פקיעת מחר נפתחת — בדיוק כמו בתיק 8."""
        rc, calls = _run_main(monkeypatch, expiries=["2026-08-04"],
                              chain_fetch=_date(2026, 8, 3))
        assert rc == aob.EXIT_OK
        assert calls == ["2026-08-04"]

    def test_same_day_expiry_is_skipped(self, monkeypatch):
        """פקיעת אותו יום — נדחית, כמו בתיק 8."""
        rc, calls = _run_main(monkeypatch, expiries=["2026-08-03"],
                              chain_fetch=_date(2026, 8, 3))
        assert rc == aob.EXIT_OK
        assert calls == []

    def test_past_expiry_is_skipped(self, monkeypatch):
        rc, calls = _run_main(monkeypatch, expiries=["2026-07-31"],
                              chain_fetch=_date(2026, 8, 3))
        assert calls == []


class TestFreshnessGate:
    def test_stale_chain_blocks_and_exits_error(self, monkeypatch):
        """שרשרת של אתמול ביום מסחר ⇒ אפס פתיחות + exit!=0."""
        rc, calls = _run_main(monkeypatch, expiries=["2026-08-06"],
                              chain_fetch=_date(2026, 7, 31))
        assert calls == []
        assert rc == aob.EXIT_ERROR

    def test_missing_fetch_date_is_stale(self, monkeypatch):
        rc, calls = _run_main(monkeypatch, expiries=["2026-08-06"], chain_fetch=None)
        assert calls == []
        assert rc == aob.EXIT_ERROR


class TestPortfolios:
    def test_no_benchmark_portfolios_is_an_error(self, monkeypatch):
        """
        get_portfolios בולע חריגות ומחזיר [] — בלי השער הזה הריצה הייתה
        מסתיימת ירוקה בלי לפתוח כלום, בדיוק הכשל השקט שהוליד את הסקריפט.
        """
        rc, _ = _run_main(monkeypatch, expiries=["2026-08-06"],
                          chain_fetch=_date(2026, 8, 3), portfolios=[])
        assert rc == aob.EXIT_ERROR

    def test_only_benchmark_ids_are_used(self, monkeypatch):
        """תיק 8 (ההמלצות) לא נכלל — הוא נפתח ע"י auto_record_margins."""
        import paper_db
        import paper_trading
        import supabase_loader
        seen = {}

        monkeypatch.setattr(paper_db, "_make_engine", lambda *a, **k: MagicMock())
        monkeypatch.setattr(paper_db, "get_portfolios",
                            lambda engine=None: _portfolios() + [{"id": 8, "strategy_ids": [102]}])
        monkeypatch.setattr(supabase_loader, "get_available_expiries",
                            lambda engine=None: ["2026-08-06"])
        monkeypatch.setattr(supabase_loader, "get_latest_option_chain",
                            lambda exp, engine=None, **k: _chain(_date(2026, 8, 3)))

        def _open(exp, chain, ports, engine=None):
            seen["ids"] = sorted(p["id"] for p in ports)
            return []

        monkeypatch.setattr(paper_trading, "open_trades_for_expiry", _open)
        aob.main()
        assert seen["ids"] == [2, 3, 4, 5, 6, 7]


class TestExitCodes:
    def test_open_error_exits_error(self, monkeypatch):
        rc, _ = _run_main(monkeypatch, expiries=["2026-08-06"],
                          chain_fetch=_date(2026, 8, 3),
                          results=[{"portfolio_id": 2, "strategy_id": 1, "status": "error"}])
        assert rc == aob.EXIT_ERROR

    def test_duplicates_are_normal(self, monkeypatch):
        """ריצה שנייה באותו יום — הכל duplicate, וזה מצב תקין."""
        rc, _ = _run_main(monkeypatch, expiries=["2026-08-06"],
                          chain_fetch=_date(2026, 8, 3),
                          results=[{"portfolio_id": i, "strategy_id": i - 1,
                                    "status": "duplicate"} for i in range(2, 8)])
        assert rc == aob.EXIT_OK
