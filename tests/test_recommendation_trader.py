"""
בדיקות יחידה ל-recommendation_trader — גשר 3 (פתיחת IC אוטומטית לפי המלצה).

כל ה-I/O ממוקק (DB + קריאת ההמלצה). נבדק: פתיחה עם ה-strikes המדויקים מההמלצה; דדופ;
kill-switch כבוי → לא פותח; המלצה ישנה בלי רגליים → skipped; והתאמה למנגנון הסגירה
(ה-P&L שנוצר מהרגליים + entry_cost תואם למקסימום-הפסד/רווח של ההמלצה).
"""
import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import recommendation_trader as rt


# ─── עוזרים ─────────────────────────────────────────────────────────────

def _rec():
    """המלצה מדומה (מה ש-_fetch_latest_recommendation מחזיר) — 4 רגליים מלאות."""
    return {
        "expiry_date":       date(2026, 7, 14),
        "recommended_at":    datetime(2026, 7, 13, 9, 0, 0),
        "margin_pct":        1.75,
        "hold_blended":      0.978,
        "premium_ils":       431.0,
        "short_put_strike":  3980.0,
        "short_call_strike": 4120.0,
        "long_put_strike":   3950.0,
        "long_call_strike":  4150.0,
        "max_loss":          -1069.0,   # −(רוחב 30נק'×50 − 431)
        "base_index":        4050.0,
        "wing_pct":          0.75,
        # מחירי הרגליים מה-chain. אינווריאנטה: (shorts) − (longs) == credit_pts,
        # כאן (6.5+5.4) − (1.6+1.68) = 8.62 נק' × 50 = 431 ₪ = premium_ils.
        "leg_prices": {
            "long_put":   1.6,
            "short_put":  6.5,
            "short_call": 5.4,
            "long_call":  1.68,
        },
    }


def _setup(monkeypatch, *, enabled=True, existing=None, rec=None):
    """ממקק את המודול; enabled=ה-kill-switch; existing=עסקאות קיימות (לדדופ); rec=ההמלצה."""
    if enabled:
        monkeypatch.setenv("RECO_TRADING_ENABLED", "true")
    else:
        monkeypatch.setenv("RECO_TRADING_ENABLED", "false")
    monkeypatch.setattr(rt, "_make_engine", lambda engine=None: engine or object())
    # מקבע את "היום" ל-13/07 כך ש-14/07 (פקיעת ברירת המחדל של _rec) הוא "מחר" — עובר את שער
    # מרחק-הפקיעה (days=1 ≥ min=1). בלי זה הבדיקות היו נשברות כשהשעון האמיתי חולף את 13/07.
    monkeypatch.setattr(rt, "_today", lambda: date(2026, 7, 13))
    monkeypatch.setattr(rt, "get_trades", lambda **kw: list(existing or []))
    monkeypatch.setattr(rt, "get_portfolio", lambda pid, engine=None: {"commission_per_leg": 2.5})
    monkeypatch.setattr(rt, "_fetch_latest_recommendation",
                        lambda eng, exp: (rec if rec is not None else _rec()))
    insert = MagicMock(return_value={"id": 555})
    monkeypatch.setattr(rt, "insert_trade", insert)
    return insert


# ─── פתיחה עם ה-strikes המדויקים מההמלצה ─────────────────────────────────

def test_opens_with_exact_recommendation_strikes(monkeypatch):
    insert = _setup(monkeypatch)
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)

    assert res["status"] == "opened"
    assert res["trade_id"] == 555
    insert.assert_called_once()
    trade = insert.call_args.args[0]

    # 4 רגליים בפורמט המדויק, עם ה-strikes *וגם המחירים* מההמלצה (buy long, sell short).
    # price_pts היה 0.0 עד שנסגר פער הדאטה — ראה TestLegPrices.
    assert trade["legs_json"] == [
        {"action": "קנה",  "type": "Put",  "qty": 1, "strike": 3950.0, "price_pts": 1.6,  "price_nis": 80.0},
        {"action": "מכור", "type": "Put",  "qty": 1, "strike": 3980.0, "price_pts": 6.5,  "price_nis": 325.0},
        {"action": "מכור", "type": "Call", "qty": 1, "strike": 4120.0, "price_pts": 5.4,  "price_nis": 270.0},
        {"action": "קנה",  "type": "Call", "qty": 1, "strike": 4150.0, "price_pts": 1.68, "price_nis": 84.0},
    ]
    assert trade["strategy_id"] == rt.RECO_STRATEGY_ID       # ייעודי (102), לא 2
    assert trade["strategy_name"] == rt.RECO_STRATEGY_NAME
    assert trade["entry_cost"] == -431.0                     # זיכוי (שלילי)
    assert trade["max_profit"] == 431.0
    assert trade["max_loss"] == -1069.0
    assert trade["status"] == "open"
    assert trade["num_legs"] == 4
    assert trade["entry_commission"] == 10.0                 # 4 × 2.5
    assert trade["portfolio_id"] == 99
    assert trade["market_snapshot_json"]["source"] == "margin_recommendation"


# ─── דדופ ────────────────────────────────────────────────────────────────

def test_dedup_skips_if_open_trade_exists(monkeypatch):
    insert = _setup(monkeypatch, existing=[{"status": "open", "strategy_id": 102}])
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "duplicate"
    insert.assert_not_called()


def test_dedup_skips_if_closed_trade_exists(monkeypatch):
    insert = _setup(monkeypatch, existing=[{"status": "closed", "strategy_id": 102}])
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "duplicate"
    insert.assert_not_called()


# ─── kill-switch כבוי → לא פותח ──────────────────────────────────────────

def test_kill_switch_off_does_not_open(monkeypatch):
    insert = _setup(monkeypatch, enabled=False)
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "skipped"
    assert "kill-switch" in res["reason"]
    insert.assert_not_called()


def test_kill_switch_missing_env_defaults_off(monkeypatch):
    monkeypatch.delenv("RECO_TRADING_ENABLED", raising=False)
    insert = MagicMock()
    monkeypatch.setattr(rt, "insert_trade", insert)
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "skipped"
    insert.assert_not_called()


# ─── שער מרחק-לפקיעה (min_days_to_expiry) ────────────────────────────────

def test_same_day_expiry_skipped(monkeypatch):
    """פקיעת אותו-יום (0 ימים) → skipped, בלי INSERT (הפגם שהגארד סוגר)."""
    insert = _setup(monkeypatch)
    monkeypatch.setattr(rt, "_today", lambda: date(2026, 7, 14))   # הפקיעה היא היום
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "skipped"
    assert "קרובה מדי" in res["reason"]
    insert.assert_not_called()


def test_past_expiry_skipped(monkeypatch):
    """פקיעה שכבר עברה (ימים שליליים) → skipped."""
    insert = _setup(monkeypatch)
    monkeypatch.setattr(rt, "_today", lambda: date(2026, 7, 15))   # הפקיעה כבר הייתה אתמול
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "skipped"
    assert "קרובה מדי" in res["reason"]
    insert.assert_not_called()


def test_tomorrow_expiry_opens_by_default(monkeypatch):
    """פקיעת מחר (1 יום) עוברת את שער ברירת המחדל (min=1) ונפתחת."""
    insert = _setup(monkeypatch)
    monkeypatch.setattr(rt, "_today", lambda: date(2026, 7, 13))   # מחר = 14/07
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "opened"
    insert.assert_called_once()


def test_min_days_parametric_skips_tomorrow(monkeypatch):
    """הפרמטר: min_days_to_expiry=2 מדלג גם על מחר (1 יום < 2)."""
    insert = _setup(monkeypatch)
    monkeypatch.setattr(rt, "_today", lambda: date(2026, 7, 13))
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99,
                                     min_days_to_expiry=2)
    assert res["status"] == "skipped"
    assert "קרובה מדי" in res["reason"]
    insert.assert_not_called()


# ─── מקרי קצה ────────────────────────────────────────────────────────────

def test_old_recommendation_without_legs_skipped(monkeypatch):
    old = {**_rec(), "long_put_strike": None, "long_call_strike": None}
    insert = _setup(monkeypatch, rec=old)
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "skipped"
    assert "רגליים" in res["reason"]
    insert.assert_not_called()


def test_no_recommendation_skipped(monkeypatch):
    insert = _setup(monkeypatch)
    monkeypatch.setattr(rt, "_fetch_latest_recommendation", lambda eng, exp: None)
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "skipped"
    insert.assert_not_called()


def test_non_positive_premium_skipped(monkeypatch):
    insert = _setup(monkeypatch, rec={**_rec(), "premium_ils": 0.0})
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "skipped"
    insert.assert_not_called()


def test_insert_failure_returns_db_error(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(rt, "insert_trade", MagicMock(return_value=None))
    res = rt.open_recommended_condor("2026-07-14", engine="ENG", portfolio_id=99)
    assert res["status"] == "db_error"


# ─── מחירי הרגליים — שקיפות + דאטה ל-ML ─────────────────────────────────

class TestLegPrices:
    """הפער שנסגר: _reco_legs כתב price_pts=0.0/price_nis=0.0 לכל רגל, ולכן מחירי
    האופציות הבודדות אבדו בכל פקיעה (ה-chain ההיסטורי נדרס ואי-אפשר לשחזר)."""

    def test_legs_carry_real_prices_from_recommendation(self):
        legs = rt._reco_legs(_rec())
        by = {(l["action"], l["type"]): l for l in legs}
        assert by[("קנה",  "Put")]["price_pts"]  == pytest.approx(1.6)
        assert by[("מכור", "Put")]["price_pts"]  == pytest.approx(6.5)
        assert by[("מכור", "Call")]["price_pts"] == pytest.approx(5.4)
        assert by[("קנה",  "Call")]["price_pts"] == pytest.approx(1.68)

    def test_price_nis_is_pts_times_multiplier(self):
        legs = rt._reco_legs(_rec())
        for lg in legs:
            assert lg["price_nis"] == pytest.approx(lg["price_pts"] * 50)

    def test_legs_reconcile_to_the_recorded_premium(self):
        """הבדיקה שסוגרת את הלולאה: סכום הרגליים חייב להסתדר עם entry_cost של העסקה.
        (מכירות − קניות) × 50 == premium_ils == −entry_cost."""
        rec = _rec()
        legs = rt._reco_legs(rec)
        shorts = sum(l["price_pts"] for l in legs if l["action"] == "מכור")
        longs  = sum(l["price_pts"] for l in legs if l["action"] == "קנה")
        assert (shorts - longs) * 50 == pytest.approx(rec["premium_ils"])

    def test_old_recommendation_without_prices_yields_none_not_zero(self):
        """המלצה ישנה (בלי leg_prices) → מחיר None, לא 0.0. אפס הוא שקר: הוא אומר
        "האופציה לא שווה כלום", וזה מזהם דאטה ש-ML ילמד ממנו."""
        rec = {**_rec()}
        rec.pop("leg_prices")
        legs = rt._reco_legs(rec)
        assert len(legs) == 4
        for lg in legs:
            assert lg["price_pts"] is None
            assert lg["price_nis"] is None
            assert lg["strike"] is not None      # ה-strikes עדיין נשמרים

    def test_partial_leg_prices_only_fill_what_exists(self):
        rec = {**_rec(), "leg_prices": {"short_put": 6.5, "long_put": None,
                                        "short_call": None, "long_call": None}}
        legs = rt._reco_legs(rec)
        by = {(l["action"], l["type"]): l for l in legs}
        assert by[("מכור", "Put")]["price_pts"] == pytest.approx(6.5)
        assert by[("מכור", "Call")]["price_pts"] is None

    def test_prices_reach_the_persisted_trade(self, monkeypatch):
        """מקצה לקצה: ההמלצה → build_reco_trade → legs_json שנכתב ל-DB."""
        trade = rt.build_reco_trade(8, _rec(), rt._reco_legs(_rec()), commission_per_leg=2.5)
        pts = [l["price_pts"] for l in trade["legs_json"]]
        assert all(p is not None and p > 0 for p in pts)
        assert trade["entry_cost"] == pytest.approx(-431.0)


# ─── התאמה למנגנון הסגירה (הרגליים + entry_cost → P&L נכון) ───────────────

def test_close_pnl_roundtrip_matches_recommendation():
    """הרגליים שאנחנו בונים + entry_cost מייצרים, דרך פונקציית ה-payoff של הסגירה, בדיוק
    את max_profit (בטווח) ו-max_loss (שבירה עמוקה) של ההמלצה."""
    from paper_trading import _payoff_from_legs   # מנגנון הסגירה הקיים

    rec = _rec()
    legs = rt._reco_legs(rec)
    entry_cost = round(-rec["premium_ils"], 2)   # -431
    comm = 4 * 2.5                                # עמלת כניסה/יציאה: 10 כל אחת

    # בתוך הטווח (המדד בין ה-shorts) → כל האופציות פוקעות חסרות-ערך → שומרים את הפרמיה.
    payoff_in = _payoff_from_legs(legs, 4050.0)
    assert payoff_in == 0.0
    pnl_in = payoff_in - entry_cost - comm - comm
    assert pnl_in == pytest.approx(431.0 - 20.0)          # פרמיה − עמלות

    # שבירה עמוקה מעל long_call → ה-P&L הגולמי (לפני עמלות) == max_loss של ההמלצה.
    payoff_up = _payoff_from_legs(legs, 4300.0)
    assert (payoff_up - entry_cost) == pytest.approx(rec["max_loss"])   # -1069

    # שבירה עמוקה מתחת ל-long_put → סימטרי, אותו max_loss גולמי.
    payoff_dn = _payoff_from_legs(legs, 3700.0)
    assert (payoff_dn - entry_cost) == pytest.approx(rec["max_loss"])


# ─── kill-switch + פתרון תיק (עוזרים) ────────────────────────────────────

def test_reco_trading_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("RECO_TRADING_ENABLED", "true")
    assert rt.reco_trading_enabled() is True
    monkeypatch.setenv("RECO_TRADING_ENABLED", "TRUE")
    assert rt.reco_trading_enabled() is True
    monkeypatch.setenv("RECO_TRADING_ENABLED", "false")
    assert rt.reco_trading_enabled() is False
    monkeypatch.delenv("RECO_TRADING_ENABLED", raising=False)
    assert rt.reco_trading_enabled() is False


def test_get_reco_portfolio_id_by_name(monkeypatch):
    monkeypatch.setattr(rt, "get_portfolios", lambda engine=None: [
        {"id": 3, "name": "Short Iron Condor Portfolio"},
        {"id": 8, "name": rt.RECO_PORTFOLIO_NAME},
    ])
    assert rt.get_reco_portfolio_id("ENG") == 8
    monkeypatch.setattr(rt, "get_portfolios", lambda engine=None: [{"id": 3, "name": "x"}])
    assert rt.get_reco_portfolio_id("ENG") is None
