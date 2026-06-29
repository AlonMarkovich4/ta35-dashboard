"""
בדיקות יחידה ל-decision_recorder — גשר תיעוד ההחלטות (שלב B1).

כל ה-I/O ממוקק: DB (_make_engine / insert_decision_log / decision_logged_today),
טעינת היסטוריה (load_from_db), שרשרת (get_available_expiries / get_latest_option_chain),
והמנוע (build_expiry_decision). ה-UI אינו נבדק כאן (לקח Styler — חזות מאמתים בדפדפן).

תאריכי הבדיקה הם 2099 (עתיד) ו-2000 (עבר) כדי שסינון ">= היום" יהיה דטרמיניסטי
ללא תלות בתאריך ההרצה.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import decision_recorder as dr


def _decision(nxt, etype, risk_score=None):
    """החלטה מדומה במבנה build_expiry_decision (השדות שהגשר קורא)."""
    return {
        "expiry_date":     nxt,
        "expiry_type":     etype,
        "top_strategy_id": 2,
        "regime":          {"regime": "calm"},
        "n_similar":       10,
        "risk_score":      risk_score,
        "ranking":         [],
    }


def _setup(monkeypatch, *, expiries, logged=None, insert_fail=False, etype_text="שבועי"):
    """מתקין מוקים סטנדרטיים על מודול decision_recorder; מחזיר את המוקים העיקריים."""
    monkeypatch.setattr(dr, "_HAS_EVENTS", False)
    monkeypatch.setattr(dr, "_make_engine", lambda engine=None: engine or object())
    monkeypatch.setattr(dr, "load_from_db",
                        lambda eng: pd.DataFrame({"move_pct": [0.5, -0.3, None]}))
    monkeypatch.setattr(dr, "get_available_expiries", lambda engine=None: list(expiries))
    monkeypatch.setattr(dr, "get_latest_option_chain",
                        lambda exp, engine=None: {"expiries": [{"expiry_type": etype_text}]})
    monkeypatch.setattr(dr, "get_recent_move", lambda df, nxt: 0.4)

    build = MagicMock(side_effect=lambda df, etype, month, nxt, **kw:
                      _decision(nxt, etype, kw.get("risk_score")))
    monkeypatch.setattr(dr, "build_expiry_decision", build)

    if insert_fail:
        insert = MagicMock(return_value=None)
    else:
        counter = {"i": 100}

        def _ins(decision, trigger="manual", engine_version="layer1-v1", engine=None):
            counter["i"] += 1
            return counter["i"]

        insert = MagicMock(side_effect=_ins)
    monkeypatch.setattr(dr, "insert_decision_log", insert)

    logged_mock = MagicMock(side_effect=(logged or (lambda *a, **k: False)))
    monkeypatch.setattr(dr, "decision_logged_today", logged_mock)

    return {"build": build, "insert": insert, "logged": logged_mock}


# ─── תיעוד תקין ─────────────────────────────────────────────────────────

def test_records_each_upcoming(monkeypatch):
    """לכל פקיעה קרובה — build_expiry_decision ו-insert_decision_log נקראים."""
    m = _setup(monkeypatch, expiries=["2099-01-15", "2099-02-19"])
    res = dr.record_decisions_for_upcoming(engine="ENG")

    assert m["build"].call_count == 2
    assert m["insert"].call_count == 2
    assert [r["status"] for r in res] == ["recorded", "recorded"]
    assert all(r["top_strategy_id"] == 2 for r in res)
    assert all(r["regime"] == "calm" for r in res)
    assert all(r["log_id"] is not None for r in res)


# ─── מניעת כפילויות ─────────────────────────────────────────────────────

def test_dedup_skips_existing(monkeypatch):
    """אם כבר תועד היום לאותה פקיעה+גרסה — לא קוראים ל-insert (ולא בונים החלטה)."""
    def logged(expiry_date, engine_version="layer1-v1", engine=None):
        return str(expiry_date) == "2099-01-15"

    m = _setup(monkeypatch, expiries=["2099-01-15", "2099-02-19"], logged=logged)
    res = dr.record_decisions_for_upcoming(engine="ENG")

    assert m["build"].call_count == 1      # רק לפקיעה שלא תועדה
    assert m["insert"].call_count == 1
    statuses = {r["expiry_date"]: r["status"] for r in res}
    assert statuses["2099-01-15"] == "skipped_exists"
    assert statuses["2099-02-19"] == "recorded"


def test_summary_counts_mixed(monkeypatch):
    """הסיכום סופר נכון נרשם מול דולג."""
    def logged(expiry_date, engine_version="layer1-v1", engine=None):
        return str(expiry_date) == "2099-02-19"

    _setup(monkeypatch, expiries=["2099-01-15", "2099-02-19", "2099-03-19"], logged=logged)
    res = dr.record_decisions_for_upcoming(engine="ENG")

    n_rec  = sum(1 for r in res if r["status"] == "recorded")
    n_skip = sum(1 for r in res if r["status"] == "skipped_exists")
    assert (n_rec, n_skip) == (2, 1)


# ─── טיפול בכשל הוספה ───────────────────────────────────────────────────

def test_insert_failure_marks_error(monkeypatch):
    """insert_decision_log שמחזיר None → status='error', log_id=None."""
    _setup(monkeypatch, expiries=["2099-02-19"], insert_fail=True)
    res = dr.record_decisions_for_upcoming(engine="ENG")

    assert res[0]["status"] == "error"
    assert res[0]["log_id"] is None


# ─── סינון פקיעות עבר ───────────────────────────────────────────────────

def test_past_expiries_excluded(monkeypatch):
    """פקיעות עם תאריך < היום אינן מעובדות כלל."""
    m = _setup(monkeypatch, expiries=["2000-01-01", "2099-02-19"])
    res = dr.record_decisions_for_upcoming(engine="ENG")

    assert len(res) == 1
    assert res[0]["expiry_date"] == "2099-02-19"
    assert m["build"].call_count == 1


# ─── אין engine ─────────────────────────────────────────────────────────

def test_no_engine_returns_empty(monkeypatch):
    """ללא DATABASE_URL (_make_engine→None) — מחזיר [] בלי לקרוא למנוע/הוספה."""
    m = _setup(monkeypatch, expiries=["2099-02-19"])
    monkeypatch.setattr(dr, "_make_engine", lambda engine=None: None)
    res = dr.record_decisions_for_upcoming(engine=None)

    assert res == []
    m["build"].assert_not_called()
    m["insert"].assert_not_called()


# ─── לב הנכונות: קלט המנוע לפקיעה חיה (W/M, חודש, ללא before_date) ───────

def test_build_called_for_live_expiry_no_lookahead(monkeypatch):
    """מאמת שהמנוע נקרא עם סוג+חודש נכונים וללא before_date (פקיעה חיה)."""
    m = _setup(monkeypatch, expiries=["2099-03-19"], etype_text="חודשי")
    res = dr.record_decisions_for_upcoming(engine="ENG")

    assert res[0]["expiry_type"] == "M"      # "חודשי" → M
    assert m["build"].call_count == 1
    call = m["build"].call_args
    assert call.args[1] == "M"               # etype
    assert call.args[2] == 3                 # int(nxt.month)
    assert "before_date" not in call.kwargs  # חי → כל ההיסטוריה לגיטימית
    assert isinstance(call.kwargs.get("recent_move_pct"), float)


def test_weekly_type_detection(monkeypatch):
    """expiry_type שאינו 'חודשי' → W."""
    _setup(monkeypatch, expiries=["2099-04-09"], etype_text="שבועי")
    res = dr.record_decisions_for_upcoming(engine="ENG")
    assert res[0]["expiry_type"] == "W"


# ─── הפצת trigger / engine_version ──────────────────────────────────────

def test_trigger_and_version_propagate(monkeypatch):
    """trigger ו-engine_version מועברים גם ל-insert וגם לבדיקת הדדופ."""
    m = _setup(monkeypatch, expiries=["2099-02-19"])
    dr.record_decisions_for_upcoming(engine="ENG", trigger="scheduled",
                                     engine_version="layer1-v2")

    _, ins_kw = m["insert"].call_args
    assert ins_kw["trigger"] == "scheduled"
    assert ins_kw["engine_version"] == "layer1-v2"

    _, log_kw = m["logged"].call_args
    assert log_kw["engine_version"] == "layer1-v2"
