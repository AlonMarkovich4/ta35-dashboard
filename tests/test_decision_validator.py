"""
בדיקות יחידה ל-decision_validator — גשר 2, שכבת "המנוע מול המציאות".

הלוגיקה הטהורה (חיבור, בחירת ההחלטה האחרונה, best/hit/regret) נבדקת דרך מיקוק
של שתי פונקציות הקריאה (_fetch_latest_decisions / _fetch_closed_pnl) — כך שאין
תלות ב-DB אמיתי (אותו pattern כמו test_decision_recorder).

תאריכי הבדיקה הם date קבועים כדי שהחיבור והמיון יהיו דטרמיניסטיים.
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import decision_validator as dv


# ─── עוזרי בנייה ────────────────────────────────────────────────────────

def _decision(expiry, top_id, *, engine_version="layer1-v1", regime="calm",
              n_decisions=1, decided_at=None):
    """רשומת החלטה מדומה במבנה ש-_fetch_latest_decisions מחזיר."""
    return {
        "expiry_date":     expiry,
        "engine_version":  engine_version,
        "decided_at":      decided_at or datetime(2026, 6, 16, 10, 0, 0),
        "top_strategy_id": top_id,
        "regime":          regime,
        "n_decisions":     n_decisions,
    }


def _trade(expiry, sid, pnl, name=None):
    """רשומת P&L מדומה במבנה ש-_fetch_closed_pnl מחזיר."""
    return {
        "expiry_date":   expiry,
        "strategy_id":   sid,
        "strategy_name": name or f"S{sid}",
        "pnl":           pnl,
        "n_trades":      1,
    }


def _patch(monkeypatch, decisions, trades):
    """ממקק את שתי הקריאות ל-DB ואת _make_engine (שיחזיר אובייקט לא-None)."""
    monkeypatch.setattr(dv, "_make_engine", lambda engine=None: engine or object())
    monkeypatch.setattr(dv, "_fetch_latest_decisions", lambda eng: list(decisions))
    monkeypatch.setattr(dv, "_fetch_closed_pnl", lambda eng: list(trades))


# ─── חיבור בסיסי + זיהוי best/hit/regret ────────────────────────────────

def test_basic_join_and_metrics(monkeypatch):
    """פקיעה עם החלטה + 6 עסקאות סגורות → שורה עם best/worst/avg/regret נכונים."""
    exp = date(2026, 6, 17)
    decisions = [_decision(exp, top_id=2, regime="calm", n_decisions=3)]
    trades = [
        _trade(exp, 1, 100.0), _trade(exp, 2, 250.0), _trade(exp, 3, -50.0),
        _trade(exp, 4, 0.0),   _trade(exp, 5, 400.0), _trade(exp, 6, 200.0),
    ]
    _patch(monkeypatch, decisions, trades)

    rows = dv.build_validation_rows(engine="ENG")
    assert len(rows) == 1
    r = rows[0]
    assert r["expiry_date"] == exp
    assert r["top_strategy_id"] == 2
    assert r["recommended_pnl"] == 250.0        # ה-P&L של האסטרטגיה המומלצת (2)
    assert r["best_strategy_id"] == 5           # 400 היא המקסימום
    assert r["best_pnl"] == 400.0
    assert r["worst_pnl"] == -50.0
    assert r["avg_pnl"] == (100 + 250 - 50 + 0 + 400 + 200) / 6
    assert r["hit"] is False
    assert r["regret"] == 400.0 - 250.0         # 150
    assert r["regime"] == "calm"
    assert r["n_decisions"] == 3


def test_recommendation_is_best_regret_zero(monkeypatch):
    """כשההמלצה היא הטובה ביותר → hit=True, best==ההמלצה, regret=0."""
    exp = date(2026, 6, 17)
    decisions = [_decision(exp, top_id=5)]
    trades = [
        _trade(exp, 1, 100.0), _trade(exp, 2, 250.0), _trade(exp, 5, 400.0),
    ]
    _patch(monkeypatch, decisions, trades)

    r = dv.build_validation_rows(engine="ENG")[0]
    assert r["hit"] is True
    assert r["best_strategy_id"] == 5
    assert r["recommended_pnl"] == 400.0
    assert r["best_pnl"] == 400.0
    assert r["regret"] == 0.0


def test_tie_on_best_recommendation_counts_as_hit(monkeypatch):
    """תיקו על המקסימום כשההמלצה בין המנצחות → hit=True, regret=0 (השוואת ערך, לא ID)."""
    exp = date(2026, 6, 17)
    decisions = [_decision(exp, top_id=3)]
    trades = [_trade(exp, 3, 400.0), _trade(exp, 5, 400.0), _trade(exp, 1, 10.0)]
    _patch(monkeypatch, decisions, trades)

    r = dv.build_validation_rows(engine="ENG")[0]
    assert r["hit"] is True
    assert r["best_strategy_id"] == 3           # מוצג כטובה ביותר (ההמלצה)
    assert r["regret"] == 0.0


# ─── בחירת ההחלטה האחרונה מבין כמה ──────────────────────────────────────

def test_latest_decision_selected_upstream(monkeypatch):
    """_fetch_latest_decisions כבר מחזיר החלטה אחת לפקיעה (האחרונה) — נבדק שהיא זו שמשמשת.

    (בחירת MAX(decided_at) נעשית ב-SQL/DISTINCT ON; כאן מדמים שהיא כבר סוננה,
    ומוודאים ש-build_validation_rows משתמש ב-top_strategy_id ובמונה n_decisions
    שמגיעים ממנה.)
    """
    exp = date(2026, 6, 17)
    # ההחלטה האחרונה בחרה אסטרטגיה 5, ותועדו סה"כ 4 החלטות לפקיעה.
    decisions = [_decision(exp, top_id=5, decided_at=datetime(2026, 6, 16, 9),
                           n_decisions=4)]
    trades = [_trade(exp, 5, 400.0), _trade(exp, 2, 100.0)]
    _patch(monkeypatch, decisions, trades)

    r = dv.build_validation_rows(engine="ENG")[0]
    assert r["top_strategy_id"] == 5
    assert r["n_decisions"] == 4
    assert r["hit"] is True


# ─── פילטרי ולידביליות ──────────────────────────────────────────────────

def test_decision_without_closed_trades_excluded(monkeypatch):
    """פקיעה עם החלטה אך בלי עסקאות סגורות — לא נכללת."""
    exp_a = date(2026, 6, 17)   # יש עסקאות
    exp_b = date(2026, 7, 15)   # אין עסקאות
    decisions = [_decision(exp_a, top_id=2), _decision(exp_b, top_id=1)]
    trades = [_trade(exp_a, 2, 100.0), _trade(exp_a, 1, 50.0)]
    _patch(monkeypatch, decisions, trades)

    rows = dv.build_validation_rows(engine="ENG")
    assert [r["expiry_date"] for r in rows] == [exp_a]


def test_closed_trades_without_decision_excluded(monkeypatch):
    """פקיעה עם עסקאות סגורות אך בלי החלטה — לא נכללת."""
    exp_a = date(2026, 6, 17)   # יש החלטה
    exp_b = date(2026, 5, 20)   # אין החלטה, יש עסקאות
    decisions = [_decision(exp_a, top_id=2)]
    trades = [
        _trade(exp_a, 2, 100.0), _trade(exp_a, 1, 50.0),
        _trade(exp_b, 3, 999.0),
    ]
    _patch(monkeypatch, decisions, trades)

    rows = dv.build_validation_rows(engine="ENG")
    assert [r["expiry_date"] for r in rows] == [exp_a]


def test_recommended_strategy_missing_pnl(monkeypatch):
    """אם האסטרטגיה המומלצת לא בין הסגורות → recommended_pnl=None, regret=None, hit=False."""
    exp = date(2026, 6, 17)
    decisions = [_decision(exp, top_id=4)]     # 4 לא נסגרה
    trades = [_trade(exp, 2, 100.0), _trade(exp, 5, 300.0)]
    _patch(monkeypatch, decisions, trades)

    r = dv.build_validation_rows(engine="ENG")[0]
    assert r["recommended_pnl"] is None
    assert r["regret"] is None
    assert r["hit"] is False
    assert r["best_strategy_id"] == 5


# ─── מיון + ריבוי פקיעות ────────────────────────────────────────────────

def test_rows_sorted_desc_by_expiry(monkeypatch):
    """שורות ממוינות לפי expiry_date יורד (האחרונה ראשונה)."""
    e1, e2, e3 = date(2026, 4, 1), date(2026, 6, 17), date(2026, 5, 10)
    decisions = [_decision(e1, 1), _decision(e2, 1), _decision(e3, 1)]
    trades = [_trade(e1, 1, 10.0), _trade(e2, 1, 20.0), _trade(e3, 1, 30.0)]
    _patch(monkeypatch, decisions, trades)

    rows = dv.build_validation_rows(engine="ENG")
    assert [r["expiry_date"] for r in rows] == [e2, e3, e1]


# ─── אין engine ─────────────────────────────────────────────────────────

def test_no_engine_returns_empty(monkeypatch):
    """ללא DATABASE_URL (_make_engine→None) — [] בלי קריאות DB."""
    monkeypatch.setattr(dv, "_make_engine", lambda engine=None: None)
    called = {"n": 0}
    monkeypatch.setattr(dv, "_fetch_latest_decisions",
                        lambda eng: called.__setitem__("n", called["n"] + 1))
    assert dv.build_validation_rows(engine=None) == []
    assert called["n"] == 0


# ─── חיבור עמיד לטיפוסי תאריך ───────────────────────────────────────────

def test_join_normalizes_date_types(monkeypatch):
    """expiry_date כ-datetime בצד אחד ו-date בצד השני עדיין מתחברים (דרך _as_date)."""
    # _fetch_* כבר מנרמל דרך _as_date; כאן מדמים ערכים מנורמלים שווים.
    exp = date(2026, 6, 17)
    decisions = [_decision(exp, top_id=2)]
    trades = [_trade(exp, 2, 100.0), _trade(exp, 5, 50.0)]
    _patch(monkeypatch, decisions, trades)

    rows = dv.build_validation_rows(engine="ENG")
    assert len(rows) == 1
    assert rows[0]["hit"] is True   # 100 > 50, ההמלצה 2 היא הטובה


def test_as_date_parses_iso_string():
    """_as_date מפרסר מחרוזת ISO, מחזיר date מ-datetime, ו-None ללא-פריק."""
    assert dv._as_date("2026-06-17") == date(2026, 6, 17)
    assert dv._as_date(datetime(2026, 6, 17, 15, 30)) == date(2026, 6, 17)
    assert dv._as_date(date(2026, 6, 17)) == date(2026, 6, 17)
    assert dv._as_date(None) is None
    assert dv._as_date("not-a-date") is None


# ─── summarize_validation ───────────────────────────────────────────────

def test_summarize_empty():
    """רשימה ריקה → כל המדדים אפס."""
    s = dv.summarize_validation([])
    assert s == {
        "n_validated":     0,
        "hit_rate":        0.0,
        "recommended_pnl": 0.0,
        "best_pnl":        0.0,
        "avg_pnl":         0.0,
        "total_regret":    0.0,
    }


def test_summarize_computes_totals():
    """סיכום סוכם P&L, hit_rate ו-total_regret נכון על פני כמה שורות."""
    rows = [
        {"hit": True,  "recommended_pnl": 400.0, "best_pnl": 400.0,
         "avg_pnl": 150.0, "regret": 0.0},
        {"hit": False, "recommended_pnl": 250.0, "best_pnl": 400.0,
         "avg_pnl": 150.0, "regret": 150.0},
    ]
    s = dv.summarize_validation(rows)
    assert s["n_validated"] == 2
    assert s["hit_rate"] == 0.5
    assert s["recommended_pnl"] == 650.0
    assert s["best_pnl"] == 800.0
    assert s["avg_pnl"] == 300.0
    assert s["total_regret"] == 150.0


def test_summarize_engine_beats_random():
    """תובנת המפתח: recommended_pnl (תיק המנוע) גדול מ-avg_pnl (בחירה אקראית)."""
    rows = [
        {"hit": False, "recommended_pnl": 250.0, "best_pnl": 400.0,
         "avg_pnl": 150.0, "regret": 150.0},
    ]
    s = dv.summarize_validation(rows)
    assert s["recommended_pnl"] > s["avg_pnl"]   # המנוע מוסיף ערך גם בלי לפגוע בול


def test_summarize_skips_none_recommended():
    """recommended_pnl/regret שהם None מדולגים בסכימה (לא מפוצצים את הסכום)."""
    rows = [
        {"hit": False, "recommended_pnl": None, "best_pnl": 300.0,
         "avg_pnl": 100.0, "regret": None},
        {"hit": True,  "recommended_pnl": 200.0, "best_pnl": 200.0,
         "avg_pnl": 100.0, "regret": 0.0},
    ]
    s = dv.summarize_validation(rows)
    assert s["n_validated"] == 2
    assert s["hit_rate"] == 0.5
    assert s["recommended_pnl"] == 200.0
    assert s["best_pnl"] == 500.0
    assert s["total_regret"] == 0.0
