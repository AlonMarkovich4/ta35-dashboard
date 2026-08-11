"""
בדיקות יחידה ל-vwap_trader — התיק התאום הממולא במחירי עסקה.

מודגש כאן במיוחד **הבידוד**: strategy_id=103, kill-switch נפרד, ואפס כתיבה
כשאין מחיר עסקה לכל 4 הרגליים.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import vwap_trader  # noqa: E402
from vwap_trader import (  # noqa: E402
    LIQUIDITY_SPEC,
    VWAP_PORTFOLIO_NAME,
    VWAP_SPEC,
    TRADE_FIELDS,
    VWAP_STRATEGY_ID,
    build_vwap_legs,
    get_vwap_portfolio_id,
    max_loss_from_legs,
    open_vwap_condor,
    vwap_trading_enabled,
)

CURVE = {"long_put_strike": 4030, "short_put_strike": 4060,
         "short_call_strike": 4200, "long_call_strike": 4230,
         "base_index": 4130.0, "net_premium": 265.0}

QUOTES = {("Put", 4030.0): 245.29, ("Put", 4060.0): 424.25,
          ("Call", 4200.0): 165.85, ("Call", 4230.0): 72.84}

CHAIN = {"fetch_date": "2026-08-11", "fetch_time": "16:01",
         "trade_date": "10/08/2026"}


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("VWAP_TRADING_ENABLED", "true")


def _eng() -> MagicMock:
    return MagicMock()


def _patch(quotes=QUOTES, rec=None, trades=None):
    """מרכיב את כל התלויות החיצוניות של open_vwap_condor."""
    rec = rec if rec is not None else {"margin_pct": 1.75, "curve_row": CURVE, "full": {}}
    return (
        patch.object(vwap_trader, "get_portfolio_id", return_value=9),
        patch.object(vwap_trader, "get_portfolio", return_value={"commission_per_leg": 2.5}),
        patch.object(vwap_trader, "get_trades", return_value=trades or []),
        patch.object(vwap_trader, "_latest_recommendation", return_value=rec),
        patch.object(vwap_trader, "fetch_traded_quotes", return_value=quotes),
        patch.object(vwap_trader, "chain_asof", return_value=CHAIN),
        patch.object(vwap_trader, "available_capital", return_value=100000.0),
    )


def _run(**kw):
    ps = _patch(**{k: v for k, v in kw.items() if k in ("quotes", "rec", "trades")})
    for p in ps:
        p.start()
    try:
        return open_vwap_condor("2026-08-11", engine=_eng(),
                                as_of="2026-08-07",
                                dry_run=kw.get("dry_run", True))
    finally:
        for p in ps:
            p.stop()


# ─── kill-switch ובידוד ─────────────────────────────────────────────────

class TestIsolation:
    def test_kill_switch_defaults_off(self, monkeypatch):
        monkeypatch.delenv("VWAP_TRADING_ENABLED", raising=False)
        assert vwap_trading_enabled() is False

    def test_kill_switch_is_separate_from_reco(self, monkeypatch):
        """הדלקת תיק ההמלצות אינה מדליקה את התיק הזה."""
        monkeypatch.delenv("VWAP_TRADING_ENABLED", raising=False)
        monkeypatch.setenv("RECO_TRADING_ENABLED", "true")
        assert vwap_trading_enabled() is False

    def test_disabled_opens_nothing(self, monkeypatch):
        monkeypatch.setenv("VWAP_TRADING_ENABLED", "false")
        r = _run()
        assert r["status"] == "skipped"
        assert r["trade"] is None

    def test_strategy_id_is_outside_the_benchmark_range(self):
        """1–6 הם ה-benchmark ו-102 הוא תיק ההמלצות. כל האגרגציות
        חוצות-התיקים חסומות ל-1..6, ולכן 103 שקוף להן."""
        assert VWAP_STRATEGY_ID == 103
        assert not (1 <= VWAP_STRATEGY_ID <= 6)
        assert VWAP_STRATEGY_ID != 102

    def test_trade_carries_the_isolated_strategy_id(self):
        assert _run()["trade"]["strategy_id"] == 103

    def test_portfolio_resolved_by_its_own_name(self):
        with patch.object(vwap_trader, "get_portfolios",
                          return_value=[{"id": 8, "name": "המלצות המערכת — Iron Condor"},
                                        {"id": 9, "name": VWAP_PORTFOLIO_NAME},
                                        {"id": 10, "name": LIQUIDITY_SPEC.portfolio_name}]):
            assert get_vwap_portfolio_id(_eng()) == 9
            assert vwap_trader.get_portfolio_id(LIQUIDITY_SPEC, _eng()) == 10

    def test_missing_portfolio_opens_nothing(self):
        with patch.object(vwap_trader, "get_portfolios", return_value=[]):
            with patch.object(vwap_trader, "_make_engine", return_value=_eng()):
                r = open_vwap_condor("2026-08-11", engine=_eng())
        assert r["status"] == "skipped"
        assert r["trade"] is None


# ─── הכלל המרכזי: אין מחיר עסקה ⇒ אין עסקה ─────────────────────────────

class TestSkipsWithoutTradedPrices:
    def test_one_untraded_leg_blocks_the_trade(self):
        q = dict(QUOTES)
        del q[("Call", 4200.0)]
        r = _run(quotes=q)
        assert r["status"] == "skipped"
        assert r["trade"] is None
        assert len(r["missing"]) == 1

    def test_no_quotes_at_all_blocks_the_trade(self):
        r = _run(quotes={})
        assert r["status"] == "skipped"
        assert len(r["missing"]) == 4

    def test_skip_reason_names_the_chain_snapshot(self):
        """דילוג שקט הוא הבאג שהפרויקט הזה כבר שילם עליו. "4/4 ללא מחיר" לבדו
        נקרא כמו ממצא נזילות — הסיבה חייבת לנקוב בצילום שעליו נבדק."""
        r = _run(quotes={})
        assert "2026-08-11" in r["reason"]        # fetch_date
        assert "10/08/2026" in r["reason"]        # trade_date
        assert "0 סטרייקים" in r["reason"]

    def test_missing_chain_is_reported_not_silent(self):
        ps = _patch()
        for p_ in ps:
            p_.start()
        try:
            with patch.object(vwap_trader, "chain_asof", return_value=None):
                r = open_vwap_condor("2026-08-11", engine=_eng(), dry_run=True)
        finally:
            for p_ in ps:
                p_.stop()
        assert r["trade"] is None
        assert "אין שרשרת" in r["reason"]

    def test_all_four_traded_produces_a_trade(self):
        r = _run()
        assert r["status"] == "dry-run"
        assert r["trade"] is not None
        assert len(r["trade"]["legs_json"]) == 4


# ─── תמחור ───────────────────────────────────────────────────────────────

class TestPricing:
    def test_entry_cost_is_the_vwap_credit(self):
        t = _run()["trade"]
        assert t["entry_cost"] == pytest.approx(245.29 + 72.84 - 424.25 - 165.85)
        assert t["entry_cost"] < 0

    def test_legs_are_marked_as_vwap_priced(self):
        t = _run()["trade"]
        assert {l["price_source"] for l in t["legs_json"]} == {"vwap"}

    def test_snapshot_keeps_the_lastrate_credit_for_comparison(self):
        """זו הסיבה שהתיק קיים — חייב להישמר מה היה מתקבל בשיטה הישנה."""
        assert _run()["trade"]["market_snapshot_json"]["net_premium_lastrate"] == 265.0

    def test_json_fields_are_serializable(self):
        """רגרסיה: `margin_pct` חוזר מה-DB כ-Decimal, ו-`paper_db._dumps` מסדר
        את השדות האלה ב-`json.dumps` **בלי** `default` — בכוונה, כדי לא לשנות
        התנהגות לתיקים הקיימים. Decimal בתוכם הפיל את ה-INSERT.

        רק שני השדות האלה עוברים JSON; השאר נשלחים כפרמטרי SQL.
        """
        rec = {"margin_pct": Decimal("1.75"),
               "curve_row": {**CURVE, "base_index": Decimal("4130.6"),
                             "net_premium": Decimal("265")},
               "full": {}}
        t = _run(rec=rec)["trade"]
        json.dumps(t["legs_json"], ensure_ascii=False)            # אסור שיזרוק
        json.dumps(t["market_snapshot_json"], ensure_ascii=False)  # אסור שיזרוק
        assert t["market_snapshot_json"]["margin_pct"] == pytest.approx(1.75)
        assert t["entry_index"] == pytest.approx(4130.6)
        assert isinstance(t["entry_index"], float)

    def test_bad_numeric_becomes_none_not_a_crash(self):
        rec = {"margin_pct": "לא מספר", "curve_row": CURVE, "full": {}}
        assert _run(rec=rec)["trade"]["market_snapshot_json"]["margin_pct"] is None

    def test_trade_carries_every_field_insert_trade_binds(self):
        """רגרסיה: `insert_trade` קושר 19 שדות, כולל NULL-ים (`closed_at`,
        `pnl`...). שדה חסר נכשל ב-"A value is required for bind parameter" —
        וזה נראה כמו כשל DB, לא כמו שדה שנשכח. נועל את הסט המלא."""
        assert set(_run()["trade"]) == TRADE_FIELDS

    def test_entry_commission_from_the_portfolio(self):
        with patch.object(vwap_trader, "get_portfolio",
                          return_value={"commission_per_leg": 2.5}):
            assert _run()["trade"]["entry_commission"] == pytest.approx(4 * 2.5)

    def test_commission_falls_back_when_portfolio_has_none(self):
        with patch.object(vwap_trader, "get_portfolio", return_value={}):
            assert _run()["trade"]["entry_commission"] == pytest.approx(4 * 2.5)

    def test_opened_at_is_now_not_the_chain_date(self):
        """רגרסיה כפולה: `insert_trade` דורש `opened_at`, **וגם** — הוא חייב
        להיות רגע הפתיחה ולא `as_of` (שהוא T-1 לפי מבנה הפיד). ערבוב השניים
        הוא מה שייצר `expiry_date − opened_at` שלילי ב-132 עסקאות משוחזרות."""
        before = datetime.now(tz=timezone.utc)
        t = _run()["trade"]
        after = datetime.now(tz=timezone.utc)
        assert t["opened_at"].tzinfo is not None
        assert before <= t["opened_at"] <= after      # "עכשיו", לא תאריך השרשרת
        assert t["market_snapshot_json"]["chain_fetch_date"] == "2026-08-11"
        assert t["market_snapshot_json"]["chain_trade_date"] == "10/08/2026"
        assert t["market_snapshot_json"]["min_units"] == 0.0

    def test_max_loss_comes_from_strikes_not_from_the_recommendation(self):
        """max_loss שבהמלצה חושב על קרדיט של lastrate ואינו תקף כאן."""
        legs = build_vwap_legs(CURVE)
        # רוחב כנף 30 נק' × 50 ₪ = 1,500; קרדיט 271.97 ⇒ הפסד מרבי 1,228.03
        assert max_loss_from_legs(legs, -271.97) == pytest.approx(-1228.03)

    def test_max_loss_is_negative_by_convention(self):
        assert _run()["trade"]["max_loss"] < 0

    def test_credit_plus_max_loss_equals_the_wing_width(self):
        t = _run()["trade"]
        assert -t["entry_cost"] + abs(t["max_loss"]) == pytest.approx(30 * 50)


# ─── דדופ וכתיבה ────────────────────────────────────────────────────────

class TestDedupAndWrite:
    def test_existing_trade_blocks_a_second_one(self):
        r = _run(trades=[{"id": 1}])
        assert r["status"] == "skipped"
        assert r["trade"] is None

    def test_dry_run_writes_nothing(self):
        with patch.object(vwap_trader, "insert_trade") as ins:
            _run(dry_run=True)
        ins.assert_not_called()

    def test_commit_calls_insert_once(self):
        ps = _patch()
        for p in ps:
            p.start()
        try:
            with patch.object(vwap_trader, "insert_trade",
                              return_value={"id": 77}) as ins:
                r = open_vwap_condor("2026-08-11", engine=_eng(),
                                     as_of="2026-08-07", dry_run=False)
            assert ins.call_count == 1
            assert r["status"] == "opened"
        finally:
            for p in ps:
                p.stop()


# ─── helpers טהורים ─────────────────────────────────────────────────────

class TestPureHelpers:
    def test_build_legs_returns_four_in_condor_order(self):
        legs = build_vwap_legs(CURVE)
        assert [(l["action"], l["type"]) for l in legs] == [
            ("קנה", "Put"), ("מכור", "Put"), ("מכור", "Call"), ("קנה", "Call")]

    def test_build_legs_none_when_a_strike_is_missing(self):
        bad = {k: v for k, v in CURVE.items() if k != "short_call_strike"}
        assert build_vwap_legs(bad) is None

    def test_build_legs_none_on_bad_strike(self):
        assert build_vwap_legs({**CURVE, "long_put_strike": "לא מספר"}) is None

    def test_max_loss_uses_the_wider_wing(self):
        legs = [{"type": "Put", "strike": 4000}, {"type": "Put", "strike": 4060},
                {"type": "Call", "strike": 4200}, {"type": "Call", "strike": 4230}]
        # כנפיים 60 ו-30 — הרחבה קובעת
        assert max_loss_from_legs(legs, -100) == pytest.approx(-(60 * 50 - 100))

    def test_max_loss_none_on_incomplete_legs(self):
        assert max_loss_from_legs([{"type": "Put", "strike": 4000}], -100) is None


# ─── ההבדל בין תיק 9 לתיק 10 ────────────────────────────────────────────

class TestPortfolioSpecs:
    """שני התיקים רצים על אותו מסלול קוד. ההבדל היחיד הוא `min_units` —
    וזה בדיוק מה שההשוואה ביניהם אמורה למדוד."""

    def test_specs_differ_only_where_intended(self):
        assert VWAP_SPEC.min_units == 0.0
        assert LIQUIDITY_SPEC.min_units == 50.0
        assert VWAP_SPEC.strategy_id != LIQUIDITY_SPEC.strategy_id
        assert VWAP_SPEC.env_flag != LIQUIDITY_SPEC.env_flag
        assert VWAP_SPEC.portfolio_name != LIQUIDITY_SPEC.portfolio_name

    def test_liquidity_strategy_id_is_isolated(self):
        """1–6 benchmark · 102 תיק 8 · 103 תיק 9. כל האגרגציות חסומות ל-1..6."""
        assert LIQUIDITY_SPEC.strategy_id == 104
        assert LIQUIDITY_SPEC.strategy_id not in (102, 103)
        assert not (1 <= LIQUIDITY_SPEC.strategy_id <= 6)

    def test_each_kill_switch_is_independent(self, monkeypatch):
        monkeypatch.delenv("VWAP_TRADING_ENABLED", raising=False)
        monkeypatch.setenv("LIQUIDITY_TRADING_ENABLED", "true")
        assert vwap_trader.trading_enabled(LIQUIDITY_SPEC) is True
        assert vwap_trader.trading_enabled(VWAP_SPEC) is False

    def test_min_units_reaches_the_quote_fetcher(self, monkeypatch):
        """זו כל המכניקה של תיק 10 — אם הסף לא מגיע לשאילתה, אין הבדל."""
        monkeypatch.setenv("LIQUIDITY_TRADING_ENABLED", "true")
        seen = {}

        def _spy(expiry, as_of=None, engine=None, min_units=0.0, **kw):
            seen["min_units"] = min_units
            return QUOTES

        ps = _patch()
        for p_ in ps:
            p_.start()
        try:
            with patch.object(vwap_trader, "fetch_traded_quotes", _spy):
                open_vwap_condor("2026-08-12", engine=_eng(), dry_run=True,
                                 spec=LIQUIDITY_SPEC)
        finally:
            for p_ in ps:
                p_.stop()
        assert seen["min_units"] == 50.0

    def test_trade_carries_the_spec_identity(self, monkeypatch):
        monkeypatch.setenv("LIQUIDITY_TRADING_ENABLED", "true")
        ps = _patch()
        for p_ in ps:
            p_.start()
        try:
            r = open_vwap_condor("2026-08-12", engine=_eng(), dry_run=True,
                                 spec=LIQUIDITY_SPEC)
        finally:
            for p_ in ps:
                p_.stop()
        t = r["trade"]
        assert t["strategy_id"] == 104
        assert t["strategy_name"] == LIQUIDITY_SPEC.strategy_name
        assert t["market_snapshot_json"]["min_units"] == 50.0

    def test_skip_reason_names_the_threshold(self):
        """דילוג ב-104 חייב להבדיל בין 'לא נסחר' ל'נסחר רזה מדי'."""
        ps = _patch(quotes={})
        for p_ in ps:
            p_.start()
        try:
            import os as _os
            _os.environ["LIQUIDITY_TRADING_ENABLED"] = "true"
            r = open_vwap_condor("2026-08-12", engine=_eng(), dry_run=True,
                                 spec=LIQUIDITY_SPEC)
        finally:
            for p_ in ps:
                p_.stop()
        assert "min_units=50" in r["reason"]


# ─── שער ההון ───────────────────────────────────────────────────────────

class TestCapitalGate:
    """תיק של 20,000 ₪ שפותח בלי לבדוק ביטחונות אינו מדמה מציאות."""

    def _eng_capital(self, initial, realized, committed):
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        row = MagicMock()
        row._mapping = {"initial_balance": initial, "realized": realized,
                        "committed": committed}
        conn.execute.return_value.fetchone.return_value = row
        eng = MagicMock()
        eng.connect.return_value = conn
        return eng

    def test_formula_is_initial_plus_realized_minus_committed(self):
        eng = self._eng_capital(20000, -1500, 6000)
        assert vwap_trader.available_capital(9, eng) == pytest.approx(12500.0)

    def test_none_on_db_error(self):
        eng = MagicMock()
        eng.connect.side_effect = Exception("db down")
        assert vwap_trader.available_capital(9, eng) is None
        assert vwap_trader.available_capital(9, None) is None

    def _run_with_capital(self, avail):
        ps = [p_ for p_ in _patch()
              if "available_capital" not in str(p_)]
        for p_ in ps:
            p_.start()
        try:
            with patch.object(vwap_trader, "available_capital", return_value=avail):
                return open_vwap_condor("2026-08-12", engine=_eng(), dry_run=True)
        finally:
            for p_ in ps:
                p_.stop()

    def test_blocks_when_collateral_exceeds_available(self):
        # max_loss של הקונדור בפיקסטורה הוא 1,228.03 ₪
        r = self._run_with_capital(500.0)
        assert r["trade"] is None
        assert "אין הון פנוי" in r["reason"]
        assert r["capital"]["required"] == pytest.approx(1228.03)

    def test_opens_when_capital_suffices(self):
        assert self._run_with_capital(20000.0)["trade"] is not None

    def test_boundary_exactly_enough_opens(self):
        assert self._run_with_capital(1228.03)["trade"] is not None

    def test_unknown_capital_blocks(self):
        """fail-safe: לא לדעת כמה הון יש אינו סיבה לפתוח."""
        r = self._run_with_capital(None)
        assert r["trade"] is None
        assert "לא ניתן לחשב הון פנוי" in r["reason"]

    def test_snapshot_records_the_capital_state(self):
        """בלי זה אי אפשר לשחזר בדיעבד למה עסקה נפתחה או לא."""
        t = self._run_with_capital(20000.0)["trade"]
        assert t["market_snapshot_json"]["capital_available_before"] == 20000.0
        assert t["market_snapshot_json"]["collateral_required"] == pytest.approx(1228.03)
