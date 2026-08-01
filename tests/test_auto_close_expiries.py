"""
בדיקות ל-scripts/auto_close_expiries.py.

mock לכל קריאות ה-DB — לא מצריך Supabase אמיתי, ולא סוגר עסקאות אמיתיות.
מאמת: אין-בשלות→0, יש-בשלות→סוגר ומסכם, idempotency, שגיאות→1, חוסר env.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# scripts/ ו-src/ ל-path כדי לייבא את הסקריפט ואת התלויות שלו
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "src"))

import auto_close_expiries as ace  # noqa: E402


def _ok_engine() -> MagicMock:
    """engine שעובר את _verify_connection (SELECT 1 מצליח)."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__  = MagicMock(return_value=False)
    eng = MagicMock()
    eng.connect.return_value = conn
    return eng


def _ready(expiry: str, settlement: float = 4258.3, open_trades: int = 6) -> dict:
    return {"expiry_date": expiry, "settlement_index": settlement, "open_trades": open_trades}


def _close_result(expiry: str, closed: int = 6, errors: int = 0,
                  pnl: float = 1000.0, settlement: float = 4258.3) -> dict:
    return {
        "expiry_date": expiry, "settlement_index": settlement,
        "closed": closed, "errors": errors, "total_pnl": pnl, "results": [],
    }


# ─── run() ─────────────────────────────────────────────────────────────

class TestRun:
    def test_no_ready_does_not_close(self):
        """אין פקיעות בשלות → close_matured_expiry לא נקרא, סיכום אפסי."""
        with patch.object(ace, "get_expiries_ready_to_close", return_value=[]), \
             patch.object(ace, "close_matured_expiry") as cme:
            summary = ace.run(MagicMock())
        cme.assert_not_called()
        assert summary["expiries_processed"] == 0
        assert summary["trades_closed"] == 0
        assert summary["total_pnl"] == 0.0

    def test_ready_closes_each_and_summarizes(self):
        ready = [_ready("2026-06-16"), _ready("2026-06-17", settlement=4260.0)]
        with patch.object(ace, "get_expiries_ready_to_close", return_value=ready), \
             patch.object(ace, "close_matured_expiry",
                          side_effect=lambda exp, engine=None: _close_result(exp)) as cme:
            summary = ace.run(MagicMock())
        assert cme.call_count == 2
        assert summary["expiries_processed"] == 2
        assert summary["expiries_closed"] == 2
        assert summary["trades_closed"] == 12
        assert summary["trades_failed"] == 0
        assert summary["total_pnl"] == pytest.approx(2000.0)

    def test_expiry_passed_as_string(self):
        """התאריך מועבר ל-close_matured_expiry כמחרוזת (בטוח מול date/text)."""
        with patch.object(ace, "get_expiries_ready_to_close", return_value=[_ready("2026-06-16")]), \
             patch.object(ace, "close_matured_expiry",
                          side_effect=lambda exp, engine=None: _close_result(exp)) as cme:
            ace.run(MagicMock())
        arg = cme.call_args[0][0]
        assert arg == "2026-06-16"
        assert isinstance(arg, str)

    def test_partial_errors_counted(self):
        """כשל-סגירה חלקי נספר ב-trades_failed (ומשפיע על קוד היציאה ב-main)."""
        with patch.object(ace, "get_expiries_ready_to_close", return_value=[_ready("2026-06-16")]), \
             patch.object(ace, "close_matured_expiry",
                          return_value=_close_result("2026-06-16", closed=4, errors=2)):
            summary = ace.run(MagicMock())
        assert summary["trades_closed"] == 4
        assert summary["trades_failed"] == 2

    def test_idempotent_second_run_closes_nothing(self):
        """ריצה ראשונה סוגרת; שנייה — אין בשלות ([]) → לא סוגר שוב.

        משקף את המציאות: get_expiries_ready_to_close מסנן status='open' בלבד,
        ואחרי סגירה העסקאות 'closed' ולא חוזרות (ה-SQL נבדק ב-test_paper_db).
        """
        with patch.object(ace, "get_expiries_ready_to_close",
                          side_effect=[[_ready("2026-06-16")], []]), \
             patch.object(ace, "close_matured_expiry",
                          return_value=_close_result("2026-06-16", pnl=500.0)) as cme:
            first  = ace.run(MagicMock())
            second = ace.run(MagicMock())
        assert cme.call_count == 1            # נסגר רק בריצה הראשונה
        assert first["trades_closed"] == 6
        assert second["trades_closed"] == 0
        assert second["expiries_processed"] == 0


# ─── main() — env + קודי יציאה ─────────────────────────────────────────

class TestMain:
    def test_missing_database_url_exits_config(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert ace.main() == ace.EXIT_CONFIG

    def test_happy_path_no_ready_exits_ok(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        with patch.object(ace, "_build_engine", return_value=_ok_engine()), \
             patch.object(ace, "get_expiries_ready_to_close", return_value=[]) as g, \
             patch.object(ace, "close_matured_expiry") as cme:
            rc = ace.main()
        assert rc == ace.EXIT_OK
        g.assert_called_once()
        cme.assert_not_called()

    def test_ready_all_closed_exits_ok(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        with patch.object(ace, "_build_engine", return_value=_ok_engine()), \
             patch.object(ace, "get_expiries_ready_to_close", return_value=[_ready("2026-06-16")]), \
             patch.object(ace, "close_matured_expiry",
                          return_value=_close_result("2026-06-16", closed=6, errors=0)):
            assert ace.main() == ace.EXIT_OK

    def test_db_connection_error_exits_1(self, monkeypatch):
        """חיבור DB נכשל (SELECT 1 זורק) → exit 1, ולא נראה כמו 'אין פקיעות'."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        bad = MagicMock()
        bad.connect.side_effect = Exception("connection refused")
        with patch.object(ace, "_build_engine", return_value=bad):
            assert ace.main() == ace.EXIT_ERROR

    def test_trade_failures_exit_1(self, monkeypatch):
        """עסקאות שלא נסגרו (errors>0) → exit 1 לסימון ב-CI."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        with patch.object(ace, "_build_engine", return_value=_ok_engine()), \
             patch.object(ace, "get_expiries_ready_to_close", return_value=[_ready("2026-06-16")]), \
             patch.object(ace, "close_matured_expiry",
                          return_value=_close_result("2026-06-16", closed=4, errors=2)):
            assert ace.main() == ace.EXIT_ERROR

    def test_unexpected_exception_exits_1(self, monkeypatch):
        """חריגה בלתי-צפויה בריצה → exit 1 (לא קורס בלי קוד שגיאה)."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        with patch.object(ace, "_build_engine", return_value=_ok_engine()), \
             patch.object(ace, "get_expiries_ready_to_close", side_effect=Exception("boom")):
            assert ace.main() == ace.EXIT_ERROR


# ─── דגל הזרמת expiry_history (אירוע 23/07/2026) ───────────────────────

class TestHistoryUpdaterFlag:
    """
    הדגל שמגן על קורפוס הלמידה. ברירת מחדל **כבוי** — כל עוד סמנטיקת
    base_price לא הוכרעה, ההזרמה מערבבת תנועת-חודש עם תנועת-מושב באותה עמודה.
    """

    @pytest.mark.parametrize("value,expected", [
        (None,     False),   # לא מוגדר כלל → ברירת המחדל הבטוחה
        ("",       False),
        ("false",  False),
        ("0",      False),
        ("yes",    False),   # רק 'true' מדליק — לא כל ערך "חיובי"
        ("true",   True),
        ("True",   True),    # case-insensitive
        ("  true ", True),   # רווחים נסבלים
    ])
    def test_flag_parsing(self, monkeypatch, value, expected):
        if value is None:
            monkeypatch.delenv("HISTORY_UPDATER_ENABLED", raising=False)
        else:
            monkeypatch.setenv("HISTORY_UPDATER_ENABLED", value)
        assert ace._history_updater_enabled() is expected

    def test_disabled_by_default_does_not_write(self, monkeypatch):
        """ברירת מחדל: הסגירה רצה כרגיל, אבל expiry_history לא נגעת כלל."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        monkeypatch.delenv("HISTORY_UPDATER_ENABLED", raising=False)
        with patch.object(ace, "_build_engine", return_value=_ok_engine()), \
             patch.object(ace, "get_expiries_ready_to_close", return_value=[_ready("2026-06-16")]), \
             patch.object(ace, "close_matured_expiry",
                          return_value=_close_result("2026-06-16", closed=6, errors=0)), \
             patch.object(ace, "update_expiry_history_from_settlements") as upd:
            rc = ace.main()
        assert rc == ace.EXIT_OK      # כיבוי הדגל אינו כישלון
        upd.assert_not_called()       # ← העיקר: אין כתיבה לקורפוס הלמידה

    def test_enabled_writes_with_commit(self, monkeypatch):
        """עם הדגל דלוק — ההזרמה נקראת כרגיל, ובמפורש עם dry_run=False."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        monkeypatch.setenv("HISTORY_UPDATER_ENABLED", "true")
        with patch.object(ace, "_build_engine", return_value=_ok_engine()), \
             patch.object(ace, "get_expiries_ready_to_close", return_value=[_ready("2026-06-16")]), \
             patch.object(ace, "close_matured_expiry",
                          return_value=_close_result("2026-06-16", closed=6, errors=0)), \
             patch.object(ace, "update_expiry_history_from_settlements",
                          return_value={"inserted": 1, "settled_total": 1,
                                        "already_present": 0, "skipped_no_base": [],
                                        "warnings": []}) as upd:
            rc = ace.main()
        assert rc == ace.EXIT_OK
        upd.assert_called_once()
        assert upd.call_args.kwargs.get("dry_run") is False


# ─── גילוי יתומות (אירוע 19/06 — שישה שבועות בשקט) ────────────────────────

def _orphan_engine(rows):
    """engine שמחזיר את השורות הנתונות לשאילתת היתומות."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchall.return_value = rows
    eng = MagicMock()
    eng.connect.return_value = conn
    return eng


class TestOrphanDetection:
    """
    שש עסקאות benchmark לפקיעת 19/06 נשארו פתוחות שישה שבועות. הסטלמנט היה
    קיים, אבל is_valid=false הפיל אותו מה-VIEW — וההתראה היחידה הושתקה ברשימה.
    כישלון לסגור חייב להיות רועש.
    """

    def _run(self, monkeypatch, rows, today=date(2026, 8, 1)):
        import datetime as _dt

        class _Now:
            def now(self, tz=None):
                return _dt.datetime(today.year, today.month, today.day, 12, 0, tzinfo=tz)

        monkeypatch.setattr(ace, "datetime", _Now())
        return ace._report_orphans(_orphan_engine(rows))

    def test_no_open_trades_is_clean(self, monkeypatch):
        assert self._run(monkeypatch, []) == 0

    def test_within_grace_is_not_flagged(self, monkeypatch):
        """פקיעה של אתמול — עדיין בחלון הסגירה הרגיל."""
        rows = [(50, 8, date(2026, 7, 31), -1240.0)]
        assert self._run(monkeypatch, rows) == 0

    def test_old_orphan_is_flagged(self, monkeypatch):
        """רגרסיה ל-19/06: פקיעה מלפני שבועות שעדיין פתוחה ⇒ נספרת."""
        rows = [(11, 2, date(2026, 6, 19), -580.0)]
        assert self._run(monkeypatch, rows) == 1

    def test_acknowledged_orphan_is_reported_but_not_counted(self, monkeypatch):
        """23/07 מוכרת — מדווחת בכל ריצה, אך אינה מפילה את הריצה."""
        rows = [(36, 8, date(2026, 7, 23), -1240.0)]
        assert self._run(monkeypatch, rows) == 0

    def test_mixed_counts_only_unacknowledged(self, monkeypatch):
        rows = [
            (36, 8, date(2026, 7, 23), -1240.0),   # מוכרת
            (11, 2, date(2026, 6, 19), -580.0),    # לא מוכרת
            (50, 8, date(2026, 7, 31), -1240.0),   # בתוך החלון
        ]
        assert self._run(monkeypatch, rows) == 1

    def test_db_error_does_not_break_the_run(self, monkeypatch):
        """בדיקת היתומות היא דיווח — כשל בה לא יפיל סגירה שכבר הצליחה."""
        eng = MagicMock()
        eng.connect.side_effect = Exception("DB down")
        import datetime as _dt

        class _Now:
            def now(self, tz=None):
                return _dt.datetime(2026, 8, 1, 12, 0, tzinfo=tz)

        monkeypatch.setattr(ace, "datetime", _Now())
        assert ace._report_orphans(eng) == 0

    def test_main_exits_error_on_unacknowledged_orphan(self, monkeypatch):
        """היתומה מפילה את הריצה לאדום — זה כל העניין."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        with patch.object(ace, "_build_engine", return_value=_ok_engine()), \
             patch.object(ace, "get_expiries_ready_to_close", return_value=[]), \
             patch.object(ace, "_report_orphans", return_value=1):
            assert ace.main() == ace.EXIT_ERROR

    def test_main_ok_when_orphans_all_acknowledged(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        with patch.object(ace, "_build_engine", return_value=_ok_engine()), \
             patch.object(ace, "get_expiries_ready_to_close", return_value=[]), \
             patch.object(ace, "_report_orphans", return_value=0):
            assert ace.main() == ace.EXIT_OK
