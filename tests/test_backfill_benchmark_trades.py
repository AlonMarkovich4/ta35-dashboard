"""
בדיקות ל-scripts/backfill_benchmark_trades.py.

הליבה (open_trades_for_expiry) מכוסה ב-test_paper_trading. כאן נבדק מה שייחודי
לשחזור: החרגת פקיעות ללא סילוק, ברירת המחדל dry-run, והשער על טעינת התיקים.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "src"))

import backfill_benchmark_trades as bf  # noqa: E402


def _portfolios(ids=(2, 3, 4, 5, 6, 7)):
    return [{"id": i, "strategy_ids": [i - 1], "commission_per_leg": 2.5} for i in ids]


class TestNoSettlementExclusion:
    """
    פקיעה שלא התרחשה חייבת להיות מוחרגת. פתיחת עסקה עליה יוצרת יתומה שלא
    תיסגר לעולם — בדיוק כמו paper_trades.id=36 מתשעה באב.
    """

    def test_tisha_bav_is_listed(self):
        assert "2026-07-23" in bf._NO_SETTLEMENT
        assert "תשעה באב" in bf._NO_SETTLEMENT["2026-07-23"]

    def test_excluded_expiry_is_never_opened(self, monkeypatch):
        """הפקיעה המוחרגת לא מגיעה ל-open_trades_for_expiry בכלל."""
        import paper_db
        import paper_trading
        import supabase_loader

        opened = []
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        monkeypatch.setattr(bf, "create_engine", lambda *a, **k: MagicMock())
        monkeypatch.setattr(paper_db, "get_portfolios", lambda engine=None: _portfolios())
        monkeypatch.setattr(bf, "_first_seen_map", lambda eng: [
            ("2026-07-22", "2026-07-15"),
            ("2026-07-23", "2026-07-16"),   # ← תשעה באב
            ("2026-07-28", "2026-07-21"),
        ])
        monkeypatch.setattr(supabase_loader, "get_latest_option_chain",
                            lambda exp, **k: {"expiries": [{"chain": [1]}]})
        monkeypatch.setattr(paper_trading, "open_trades_for_expiry",
                            lambda exp, ch, ports, engine=None: (
                                opened.append(exp) or
                                [{"status": "opened"} for _ in ports]))

        with patch.object(sys, "argv", ["backfill", "--commit"]):
            rc = bf.main()

        assert rc == bf.EXIT_OK
        assert opened == ["2026-07-22", "2026-07-28"]     # 23/07 לא נפתחה
        assert "2026-07-23" not in opened


class TestDryRunDefault:
    def test_dry_run_blocks_writes(self, monkeypatch):
        """בלי --commit, שתי פונקציות הכתיבה מוחלפות ואף שורה לא נכתבת."""
        import paper_db
        import paper_trading
        import supabase_loader

        real_insert = paper_trading.insert_trade
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        monkeypatch.setattr(bf, "create_engine", lambda *a, **k: MagicMock())
        monkeypatch.setattr(paper_db, "get_portfolios", lambda engine=None: _portfolios())
        monkeypatch.setattr(bf, "_first_seen_map", lambda eng: [("2026-07-22", "2026-07-15")])
        monkeypatch.setattr(supabase_loader, "get_latest_option_chain",
                            lambda exp, **k: {"expiries": [{"chain": [1]}]})
        monkeypatch.setattr(paper_trading, "open_trades_for_expiry",
                            lambda *a, **k: [{"status": "opened"}])

        with patch.object(sys, "argv", ["backfill"]):
            rc = bf.main()

        assert rc == bf.EXIT_OK
        assert paper_trading.insert_trade is not real_insert   # הוחלף
        paper_trading.insert_trade = real_insert               # ניקוי


class TestPortfolioGuard:
    @pytest.mark.parametrize("ids", [(), (2, 3), (2, 3, 4, 5, 6)])
    def test_incomplete_portfolios_is_an_error(self, monkeypatch, ids):
        """
        get_portfolios בולע חריגות ומחזיר [] — בלי השער הזה השחזור היה
        מסתיים ירוק בלי לשחזר דבר.
        """
        import paper_db
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        monkeypatch.setattr(bf, "create_engine", lambda *a, **k: MagicMock())
        monkeypatch.setattr(paper_db, "get_portfolios", lambda engine=None: _portfolios(ids))
        with patch.object(sys, "argv", ["backfill"]):
            assert bf.main() == bf.EXIT_ERROR

    def test_missing_env_exits_config(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch.object(sys, "argv", ["backfill"]):
            assert bf.main() == bf.EXIT_CONFIG
