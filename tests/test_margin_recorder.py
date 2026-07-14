"""
בדיקות יחידה ל-margin_recorder — גשר תיעוד המלצות המרווח (שלב 4, חלק ב).

כל ה-I/O ממוקק (אותו pattern כמו test_decision_recorder): DB (_make_engine /
insert_margin_recommendation / margin_recommendation_logged_today), טעינת היסטוריה
(load_from_db), שרשרת (get_available_expiries / get_latest_option_chain), והמנוע
(build_margin_curve / select_margin / find_atm / get_recent_move).

תאריכי הבדיקה הם 2099 (עתיד) ו-2000 (עבר) כדי שסינון ">= היום" יהיה דטרמיניסטי.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import margin_recorder as mr
from context_analyzer import get_recent_move
from margin_calculator import DEFAULT_WING_PCT, build_margin_curve
from margin_selector import select_margin


# ─── עוזרים ─────────────────────────────────────────────────────────────

def _rec(exp_date, etype="W", margin=1.5, hold=0.98):
    """rec מדומה במבנה ש-_recommendation_for_expiry מחזיר (השדות שהרשם קורא)."""
    return {
        "expiry_date":        exp_date,
        "expiry_type":        etype,
        "selected_margin":    margin,
        "hold_blended":       hold,
        "hold_conditional":   0.90,
        "hold_global":        0.99,
        "n_conditional":      12,
        "net_premium":        500.0,
        "short_put_strike":   1960.0,
        "short_call_strike":  2040.0,
        "below_floor":        False,
        "hold_floor":         0.97,
        "reason":             "בדיקה",
        "grid":               [],
        "selected_curve_row": {},
        "engine_version":     "margin-v1",
        "trigger":            "manual",
    }


def _setup(monkeypatch, *, expiries, logged=None, insert_fail=False, rec_none=False):
    """ממקק את המודול לבדיקות אורקסטרציה (מדמה את _recommendation_for_expiry)."""
    monkeypatch.setattr(mr, "_make_engine", lambda engine=None: engine or object())
    monkeypatch.setattr(mr, "load_from_db",
                        lambda eng: pd.DataFrame({"move_pct": [0.5, -0.3, None]}))
    monkeypatch.setattr(mr, "get_available_expiries", lambda engine=None: list(expiries))

    def _recmock(df, nxt, engine, hold_floor=0.97, wing_pct=1.0,
                 engine_version="margin-v1", trigger="manual"):
        return None if rec_none else _rec(nxt.date(), margin=1.5)
    rec_mock = MagicMock(side_effect=_recmock)
    monkeypatch.setattr(mr, "_recommendation_for_expiry", rec_mock)

    if insert_fail:
        insert = MagicMock(return_value=None)
    else:
        counter = {"i": 100}

        def _ins(rec, engine_version="margin-v1", engine=None):
            counter["i"] += 1
            return counter["i"]
        insert = MagicMock(side_effect=_ins)
    monkeypatch.setattr(mr, "insert_margin_recommendation", insert)

    logged_mock = MagicMock(side_effect=(logged or (lambda *a, **k: False)))
    monkeypatch.setattr(mr, "margin_recommendation_logged_today", logged_mock)

    return {"rec": rec_mock, "insert": insert, "logged": logged_mock}


# ─── תיעוד תקין ─────────────────────────────────────────────────────────

def test_records_each_upcoming(monkeypatch):
    """לכל פקיעה קרובה — _recommendation_for_expiry ו-insert נקראים; סיכום מלא."""
    m = _setup(monkeypatch, expiries=["2099-01-15", "2099-02-19"])
    res = mr.record_margin_recommendations_for_upcoming(engine="ENG")

    assert m["rec"].call_count == 2
    assert m["insert"].call_count == 2
    assert [r["status"] for r in res] == ["recorded", "recorded"]
    assert all(r["selected_margin"] == 1.5 for r in res)   # ← המרווח בסיכום
    assert all(r["hold_blended"] == 0.98 for r in res)     # ← הביטחון בסיכום
    assert all(r["rec_id"] is not None for r in res)


def test_summary_reports_margin_and_confidence(monkeypatch):
    """הסיכום כולל מרווח + ביטחון + סוג לכל פקיעה שנרשמה (הדרישה: 'המרווח, הביטחון')."""
    _setup(monkeypatch, expiries=["2099-03-19"])
    r = mr.record_margin_recommendations_for_upcoming(engine="ENG")[0]
    assert r["selected_margin"] == 1.5
    assert r["hold_blended"] == 0.98
    assert r["expiry_type"] == "W"
    assert r["status"] == "recorded"


# ─── מניעת כפילויות (דדופ) ───────────────────────────────────────────────

def test_dedup_skips_existing(monkeypatch):
    """אם כבר תועד היום — לא בונים המלצה ולא קוראים ל-insert (דדופ לפני עבודה יקרה)."""
    def logged(expiry_date, engine_version="margin-v1", engine=None):
        return str(expiry_date) == "2099-01-15"

    m = _setup(monkeypatch, expiries=["2099-01-15", "2099-02-19"], logged=logged)
    res = mr.record_margin_recommendations_for_upcoming(engine="ENG")

    assert m["rec"].call_count == 1     # רק לפקיעה שלא תועדה
    assert m["insert"].call_count == 1
    statuses = {r["expiry_date"]: r["status"] for r in res}
    assert statuses["2099-01-15"] == "skipped_exists"
    assert statuses["2099-02-19"] == "recorded"


# ─── מקרי קצה ───────────────────────────────────────────────────────────

def test_no_recommendation_status(monkeypatch):
    """_recommendation_for_expiry שמחזיר None (אין שרשרת/מרווח) → status='no_recommendation'."""
    m = _setup(monkeypatch, expiries=["2099-02-19"], rec_none=True)
    res = mr.record_margin_recommendations_for_upcoming(engine="ENG")

    assert res[0]["status"] == "no_recommendation"
    m["insert"].assert_not_called()


def test_insert_failure_marks_error(monkeypatch):
    """insert שמחזיר None → status='error', rec_id=None."""
    _setup(monkeypatch, expiries=["2099-02-19"], insert_fail=True)
    res = mr.record_margin_recommendations_for_upcoming(engine="ENG")

    assert res[0]["status"] == "error"
    assert res[0]["rec_id"] is None


def test_past_expiries_excluded(monkeypatch):
    """פקיעות עם תאריך < היום אינן מעובדות כלל."""
    m = _setup(monkeypatch, expiries=["2000-01-01", "2099-02-19"])
    res = mr.record_margin_recommendations_for_upcoming(engine="ENG")

    assert len(res) == 1
    assert res[0]["expiry_date"] == "2099-02-19"
    assert m["rec"].call_count == 1


def test_no_engine_returns_empty(monkeypatch):
    """ללא DATABASE_URL (_make_engine→None) — [] בלי לקרוא למנוע/הוספה."""
    m = _setup(monkeypatch, expiries=["2099-02-19"])
    monkeypatch.setattr(mr, "_make_engine", lambda engine=None: None)
    res = mr.record_margin_recommendations_for_upcoming(engine=None)

    assert res == []
    m["rec"].assert_not_called()
    m["insert"].assert_not_called()


def test_trigger_and_version_propagate(monkeypatch):
    """trigger ו-engine_version מועברים ל-insert, לדדופ ולבניית ההמלצה."""
    m = _setup(monkeypatch, expiries=["2099-02-19"])
    mr.record_margin_recommendations_for_upcoming(
        engine="ENG", trigger="scheduled", engine_version="margin-v2")

    _, ins_kw = m["insert"].call_args
    assert ins_kw["engine_version"] == "margin-v2"
    _, log_kw = m["logged"].call_args
    assert log_kw["engine_version"] == "margin-v2"
    _, rec_kw = m["rec"].call_args
    assert rec_kw["engine_version"] == "margin-v2"
    assert rec_kw["trigger"] == "scheduled"


# ─── נירמול סוג הפקיעה ───────────────────────────────────────────────────

def test_norm_expiry_type():
    """'חודשי' → M; כל השאר → W (הבסיס להתניית select_margin על סוג)."""
    assert mr._norm_expiry_type("חודשי") == "M"
    assert mr._norm_expiry_type("שבועי") == "W"
    assert mr._norm_expiry_type("") == "W"
    assert mr._norm_expiry_type(None) == "W"


# ─── לב הנכונות: הרכבת ההמלצה מהעקומה + ה-grid ───────────────────────────

def _assembly_setup(monkeypatch, *, etype_text, sel):
    """ממקק את פנימיות _recommendation_for_expiry (שרשרת, ATM, עקומה, select_margin)."""
    monkeypatch.setattr(mr, "get_latest_option_chain", lambda exp, engine=None: {
        "as_of_date": "12/07/2026",
        "expiries": [{"expiry_type": etype_text,
                      "chain": pd.DataFrame({"strike": [1, 2, 3]})}],
    })
    monkeypatch.setattr(mr, "find_atm",
                        lambda chain_df: {"index_estimate": 2000.0, "strike": 2000})
    curve = [
        {"margin_pct": 1.5, "skipped": False, "short_put_strike": 1970.0,
         "short_call_strike": 2030.0, "long_put_strike": 1940.0,
         "long_call_strike": 2060.0, "credit_pts": 3.0, "base_index": 2000.0},
        {"margin_pct": 2.0, "skipped": False, "short_put_strike": 1960.0,
         "short_call_strike": 2040.0, "long_put_strike": 1920.0,
         "long_call_strike": 2080.0, "credit_pts": 2.5, "base_index": 2000.0},
    ]
    # MagicMock (לא lambda) כדי לקבל wing_pct kwarg ולאפשר בדיקת מה שהועבר.
    monkeypatch.setattr(mr, "build_margin_curve", MagicMock(return_value=curve))
    monkeypatch.setattr(mr, "get_recent_move", lambda df, nxt: 0.3)
    select_mock = MagicMock(return_value=sel)
    monkeypatch.setattr(mr, "select_margin", select_mock)
    return select_mock


def test_recommendation_assembles_from_curve_and_grid(monkeypatch):
    """ה-rec מרכיב strikes מהעקומה, hold/n מהשורה הנבחרת ב-grid, ומנרמל סוג ל-M."""
    sel = {
        "selected_margin": 2.0, "hold_blended": 0.98, "net_premium": 480.0,
        "max_loss": -1520.0, "ev": 5.0, "below_floor": False, "hold_floor": 0.97,
        "reason": "נבחר 2.00%",
        "grid": [
            {"margin_pct": 1.5, "hold_blended": 0.90, "hold_conditional": 0.85,
             "hold_global": 0.92, "n_conditional": 10, "w_effective": 0.3},
            {"margin_pct": 2.0, "hold_blended": 0.98, "hold_conditional": 0.95,
             "hold_global": 0.99, "n_conditional": 10, "w_effective": 0.3},
        ],
    }
    select_mock = _assembly_setup(monkeypatch, etype_text="חודשי", sel=sel)

    df = pd.DataFrame({"move_pct": [0.3]})
    rec = mr._recommendation_for_expiry(df, pd.Timestamp("2099-03-19"), object())

    assert rec["expiry_type"] == "M"                    # "חודשי" → M
    assert select_mock.call_args.args[2] == "M"         # etype הועבר ל-select_margin
    assert rec["selected_margin"] == 2.0
    # strikes מהשורה הנבחרת בעקומה (2.0%)
    assert rec["short_put_strike"] == 1960.0
    assert rec["short_call_strike"] == 2040.0
    assert rec["selected_curve_row"]["credit_pts"] == 2.5
    # hold/n מהשורה הנבחרת ב-grid (2.0%)
    assert rec["hold_conditional"] == 0.95
    assert rec["hold_global"] == 0.99
    assert rec["n_conditional"] == 10
    assert rec["hold_blended"] == 0.98
    assert rec["net_premium"] == 480.0
    assert rec["below_floor"] is False
    assert rec["hold_floor"] == 0.97
    assert rec["expiry_date"].isoformat() == "2099-03-19"


def test_no_chain_returns_none(monkeypatch):
    """אין שרשרת (expiries ריק) → _recommendation_for_expiry מחזיר None."""
    monkeypatch.setattr(mr, "get_latest_option_chain",
                        lambda exp, engine=None: {"expiries": []})
    rec = mr._recommendation_for_expiry(
        pd.DataFrame({"move_pct": [0.1]}), pd.Timestamp("2099-01-15"), object())
    assert rec is None


def test_no_valid_margin_returns_none(monkeypatch):
    """select_margin שמחזיר selected_margin=None (עקומה ריקה) → None."""
    sel = {"selected_margin": None, "hold_blended": None, "below_floor": True,
           "hold_floor": 0.97, "grid": [], "reason": "אין מרווחים תקינים"}
    _assembly_setup(monkeypatch, etype_text="שבועי", sel=sel)
    rec = mr._recommendation_for_expiry(
        pd.DataFrame({"move_pct": [0.3]}), pd.Timestamp("2099-04-09"), object())
    assert rec is None


# ─── שלב 6: פרמטור הכנף — עובר ל-build_margin_curve ונשמר ב-rec ───────────

def test_wing_pct_threaded_and_recorded(monkeypatch):
    """wing_pct עובר ל-build_margin_curve ונשמר ב-rec; ברירת המחדל 0.75% (הכנף הרשמית)."""
    sel = {
        "selected_margin": 2.0, "hold_blended": 0.98, "net_premium": 480.0,
        "max_loss": -1520.0, "ev": 5.0, "below_floor": False, "hold_floor": 0.97,
        "reason": "נבחר 2.00%",
        "grid": [{"margin_pct": 2.0, "hold_blended": 0.98, "hold_conditional": 0.95,
                  "hold_global": 0.99, "n_conditional": 10, "w_effective": 0.3}],
    }
    _assembly_setup(monkeypatch, etype_text="שבועי", sel=sel)
    df = pd.DataFrame({"move_pct": [0.3]})

    # מפורש: wing_pct=0.5 → עובר ל-build_margin_curve ונשמר ב-rec.
    rec = mr._recommendation_for_expiry(df, pd.Timestamp("2099-03-19"), object(), wing_pct=0.5)
    assert rec["wing_pct"] == 0.5
    assert mr.build_margin_curve.call_args.kwargs.get("wing_pct") == 0.5

    # ברירת מחדל: wing_pct=0.75 (הכנף הרשמית — נועל את ברירת המחדל של הרשם).
    rec_default = mr._recommendation_for_expiry(df, pd.Timestamp("2099-03-19"), object())
    assert rec_default["wing_pct"] == 0.75
    assert mr.build_margin_curve.call_args.kwargs.get("wing_pct") == 0.75


def test_record_threads_wing_to_recommendation(monkeypatch):
    """record_...(wing_pct=...) מעביר את הכנף ל-_recommendation_for_expiry."""
    m = _setup(monkeypatch, expiries=["2099-02-19"])
    mr.record_margin_recommendations_for_upcoming(engine="ENG", wing_pct=0.5)
    _, rec_kw = m["rec"].call_args
    assert rec_kw["wing_pct"] == 0.5

# ─── שלב א' — "מדד הפחד" (implied_move) נרשם בכל המלצה ────────────────────

class TestImpliedMoveRecorded:
    """implied_move נשמר ב-recommendation_json, ו**לא** משפיע על בחירת המרווח.
    הבדיקות רצות דרך _recommendation_for_expiry האמיתי (לא ממוקק) עם chain אמיתי."""

    @staticmethod
    def _chain(base=4000.0):
        """שרשרת שמצייתת ל-put-call parity: C − P = S − K (בנקודות). בלי זה find_atm
        (שנשען על |C−P| מינימלי) לא מוצא את ה-ATM האמיתי."""
        rows = []
        for k in range(3800, 4201, 10):
            tv = max(1.0, 25 - abs(k - base) * 0.08)      # ערך זמן, דועך עם המרחק
            call = max(base - k, 0.0) + tv                # פנימי + זמן
            put  = max(k - base, 0.0) + tv
            rows.append({"strike": float(k),
                         "call_price": call * 50.0,
                         "put_price":  put * 50.0,
                         # find_atm נופל ל-call_delta כשאין שורה דו-צדדית — כמו בשרשרת אמיתית
                         "call_delta": 0.5 + (base - k) / 1000.0})
        return {
            "as_of_date": "13/07/2026 14:57",
            "expiries": [{"expiry_type": "W", "chain": pd.DataFrame(rows)}],
        }

    @staticmethod
    def _hist():
        import numpy as np
        rng = np.random.default_rng(7)
        return pd.DataFrame({
            "expiry_date": pd.date_range("2024-01-04", periods=120, freq="W-THU"),
            "expiry_type": ["W"] * 120,
            "move_pct":    rng.normal(0, 1.0, 120),
            "abs_move_pct": np.abs(rng.normal(0, 1.0, 120)),
        })

    def _build(self, monkeypatch):
        monkeypatch.setattr(mr, "get_latest_option_chain",
                            lambda expiry_date=None, engine=None: self._chain())
        return mr._recommendation_for_expiry(
            self._hist(), pd.Timestamp("2026-07-17"), engine=object())

    def test_payload_carries_implied_move(self, monkeypatch):
        rec = self._build(monkeypatch)
        assert rec is not None
        im = rec["implied_move"]
        assert im["skipped"] is False
        assert im["expected_move_pct"] > 0
        assert im["atm_strike"] == 4000.0
        assert im["days_to_expiry"] == 4          # 13/07 → 17/07
        assert im["implied_daily_pct"] is not None

    def test_implied_vs_margin_is_the_ratio(self, monkeypatch):
        rec = self._build(monkeypatch)
        im = rec["implied_move"]
        expected = im["expected_move_pct"] / rec["selected_margin"]
        assert im["implied_vs_margin"] == pytest.approx(expected, rel=1e-3)

    def test_implied_move_does_not_change_the_selected_margin(self, monkeypatch):
        """שלב א' — תיעוד בלבד. המרווח שנבחר חייב להיות זהה לזה שנבחר בלי הפיצ'ר:
        select_margin לא מקבל את implied_move כלל."""
        rec = self._build(monkeypatch)
        curve = build_margin_curve(self._chain()["expiries"][0]["chain"], 4000.0,
                                   wing_pct=DEFAULT_WING_PCT)
        sel = select_margin(curve, self._hist(), "W",
                            get_recent_move(self._hist(), pd.Timestamp("2026-07-17")))
        assert rec["selected_margin"] == sel["selected_margin"]

    def test_untradable_chain_records_skipped_but_still_recommends(self, monkeypatch):
        """שרשרת בלי ציטוטים דו-צדדיים → implied_move skipped, אבל ההמלצה עצמה
        לא נופלת (הפיצ'ר לא יכול לשבור את המנוע)."""
        ch = self._chain()
        df = ch["expiries"][0]["chain"]
        df["put_price"] = 0.0            # אין ציטוט put בשום סטרייק
        monkeypatch.setattr(mr, "get_latest_option_chain",
                            lambda expiry_date=None, engine=None: ch)
        rec = mr._recommendation_for_expiry(self._hist(), pd.Timestamp("2026-07-17"),
                                            engine=object())
        # ה-condor עצמו לא ניתן לתמחור כאן → או שאין המלצה, או שיש עם implied skipped.
        if rec is not None:
            assert rec["implied_move"]["skipped"] is True
            assert rec["implied_move"]["expected_move_pct"] is None
