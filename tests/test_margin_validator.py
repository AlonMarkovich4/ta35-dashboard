"""
בדיקות יחידה ל-margin_validator — שכבת הולידציה קדימה למרווח (שלב 4, חלק ג).

הלוגיקה הטהורה (held, optimal_hindsight, gap, est_pnl, מקור התנועה, מיון) נבדקת דרך
מיקוק שלוש קריאות ה-DB (_fetch_latest_recommendations / _fetch_settlements /
_fetch_history_moves) — אין תלות ב-DB אמיתי (אותו pattern כמו test_decision_validator).

בנוסף: בדיקת ה-CAST ::date על ה-TEXT ב-condor_settled_detail דרך engine מדומה שלוכד
את ה-SQL ומאמת שמחרוזת-תאריך מנורמלת נכון.
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import margin_validator as mv
from margin_calculator import margin_pnl


# ─── עוזרי בנייה ────────────────────────────────────────────────────────

_GRID = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0)


def _rec(expiry, margin, *, base_index=2000.0, premium=500.0, below_floor=False,
         grid_margins=_GRID, curve_row=None, n=1, recommended_at=None):
    """רשומת המלצה מדומה במבנה ש-_fetch_latest_recommendations מחזיר."""
    return {
        "expiry_date":         expiry,
        "recommended_at":      recommended_at or datetime(2026, 6, 16, 10, 0, 0),
        "margin_pct":          margin,
        "premium_ils":         premium,
        "below_floor":         below_floor,
        "floor_used":          0.97,
        "recommendation_json": {
            "base_index":         base_index,
            "grid":               [{"margin_pct": m} for m in grid_margins],
            "selected_curve_row": curve_row,
        },
        "n_recommendations":   n,
    }


def _curve_row(base_index=2000.0):
    """שורת עקומה תקינה (לשחזור margin_pnl) — short ±2%, wing ±3%."""
    return {
        "skipped": False, "base_index": base_index,
        "long_put_strike":  1920.0, "short_put_strike": 1960.0,
        "short_call_strike": 2040.0, "long_call_strike": 2080.0,
        "credit_pts": 2.5,
    }


def _patch(monkeypatch, recs, settlements, hist_moves):
    """ממקק את שלוש קריאות ה-DB + _make_engine (מחזיר אובייקט לא-None)."""
    monkeypatch.setattr(mv, "_make_engine", lambda engine=None: engine or object())
    monkeypatch.setattr(mv, "_fetch_latest_recommendations", lambda eng: list(recs))
    monkeypatch.setattr(mv, "_fetch_settlements", lambda eng: dict(settlements))
    monkeypatch.setattr(mv, "_fetch_history_moves", lambda eng: dict(hist_moves))


# ─── שורת ולידציה בסיסית ────────────────────────────────────────────────

def test_basic_validation_row(monkeypatch):
    """פקיעה עם המלצה + settlement + move היסטורי → held/optimal/gap נכונים."""
    exp = date(2026, 6, 19)
    _patch(monkeypatch, [_rec(exp, 2.0)], {exp: 2010.0}, {exp: 0.5})

    rows = mv.build_margin_validation_rows(engine="ENG")
    assert len(rows) == 1
    r = rows[0]
    assert r["recommended_margin"] == 2.0
    assert r["actual_abs_move_pct"] == 0.5
    assert r["held"] is True
    assert r["move_source"] == "expiry_history"
    assert r["margin_optimal_hindsight"] == 1.0        # הצר ביותר ≥ 0.5
    assert r["margin_gap"] == 1.0                       # 2.0 − 1.0 (מרווח שבוזבז)
    assert r["premium_ils"] == 500.0
    assert r["n_recommendations"] == 1


# ─── held ────────────────────────────────────────────────────────────────

def test_held_true_within_margin(monkeypatch):
    exp = date(2026, 6, 19)
    _patch(monkeypatch, [_rec(exp, 2.0)], {exp: 2000.0}, {exp: 1.9})
    assert mv.build_margin_validation_rows(engine="ENG")[0]["held"] is True


def test_held_false_on_break(monkeypatch):
    """|move| מעל המרווח → held=False; gap שלילי (המרווח לא הספיק)."""
    exp = date(2026, 6, 19)
    _patch(monkeypatch, [_rec(exp, 1.5)], {exp: 2000.0}, {exp: 2.3})
    r = mv.build_margin_validation_rows(engine="ENG")[0]
    assert r["held"] is False
    assert r["margin_optimal_hindsight"] == 2.5        # הצר ביותר ≥ 2.3
    assert r["margin_gap"] == 1.5 - 2.5                # -1.0 (חסר)


# ─── optimal_hindsight ──────────────────────────────────────────────────

def test_optimal_hindsight_narrowest_holding(monkeypatch):
    """התנועה 1.3% → האופטימום הוא 1.5% (הצר ביותר בגריד שמחזיק)."""
    exp = date(2026, 6, 19)
    _patch(monkeypatch, [_rec(exp, 2.5)], {exp: 2000.0}, {exp: 1.3})
    r = mv.build_margin_validation_rows(engine="ENG")[0]
    assert r["margin_optimal_hindsight"] == 1.5
    assert r["held"] is True
    assert r["margin_gap"] == 2.5 - 1.5                # 1.0 בוזבז


def test_optimal_hindsight_none_when_move_exceeds_grid(monkeypatch):
    """תנועה מעבר לכל הגריד (>3.0%) → optimal=None, gap=None."""
    exp = date(2026, 6, 19)
    _patch(monkeypatch, [_rec(exp, 2.0)], {exp: 2000.0}, {exp: 3.5})
    r = mv.build_margin_validation_rows(engine="ENG")[0]
    assert r["margin_optimal_hindsight"] is None
    assert r["margin_gap"] is None
    assert r["held"] is False


def test_optimal_uses_recommendation_grid(monkeypatch):
    """האופטימום נגזר מהגריד של ההמלצה עצמה (מרווחים שבאמת הוצעו)."""
    exp = date(2026, 6, 19)
    # גריד מצומצם: רק 2.0 ו-3.0 הוצעו. תנועה 1.2% → אין 1.5 → האופטימום הזמין הוא 2.0.
    _patch(monkeypatch, [_rec(exp, 3.0, grid_margins=(2.0, 3.0))],
           {exp: 2000.0}, {exp: 1.2})
    r = mv.build_margin_validation_rows(engine="ENG")[0]
    assert r["margin_optimal_hindsight"] == 2.0


# ─── מקור התנועה: expiry_history קודם, settlement כגיבוי ─────────────────

def test_prefers_expiry_history_over_settlement(monkeypatch):
    """כשיש move היסטורי — משתמשים בו (לא בחישוב מה-settlement)."""
    exp = date(2026, 6, 19)
    # settlement רומז ל-+5% אך ההיסטוריה אומרת 0.4% — ההיסטוריה גוברת.
    _patch(monkeypatch, [_rec(exp, 2.0, base_index=2000.0)], {exp: 2100.0}, {exp: 0.4})
    r = mv.build_margin_validation_rows(engine="ENG")[0]
    assert r["move_source"] == "expiry_history"
    assert r["actual_abs_move_pct"] == 0.4
    assert r["held"] is True


def test_fallback_to_settlement_move(monkeypatch):
    """אין move היסטורי → חישוב מ-(actual_index_close − base_index)/base_index."""
    exp = date(2026, 6, 19)
    _patch(monkeypatch, [_rec(exp, 2.0, base_index=2000.0)], {exp: 2030.0}, {})
    r = mv.build_margin_validation_rows(engine="ENG")[0]
    assert r["move_source"] == "settlement"
    assert r["actual_move_pct"] == 1.5                 # (2030-2000)/2000*100
    assert r["held"] is True


# ─── est_pnl דרך margin_pnl (שחזור) ──────────────────────────────────────

def test_est_pnl_via_margin_pnl(monkeypatch):
    """P&L המשוער = margin_pnl(selected_curve_row, move בפועל) — שחזור מדויק."""
    exp = date(2026, 6, 19)
    crow = _curve_row(base_index=2000.0)
    _patch(monkeypatch, [_rec(exp, 2.0, curve_row=crow)], {exp: 2010.0}, {exp: 0.5})
    r = mv.build_margin_validation_rows(engine="ENG")[0]
    assert r["est_pnl"] == round(margin_pnl(crow, 0.5), 2)   # תנועה חתומה


def test_est_pnl_none_without_curve_row(monkeypatch):
    """אין selected_curve_row → est_pnl=None (לא קורסים)."""
    exp = date(2026, 6, 19)
    _patch(monkeypatch, [_rec(exp, 2.0, curve_row=None)], {exp: 2010.0}, {exp: 0.5})
    assert mv.build_margin_validation_rows(engine="ENG")[0]["est_pnl"] is None


# ─── פילטרי ולידביליות ──────────────────────────────────────────────────

def test_recommendation_without_settlement_excluded(monkeypatch):
    """המלצה בלי settlement (לא נסגרה) — לא נכללת."""
    exp = date(2026, 6, 19)
    _patch(monkeypatch, [_rec(exp, 2.0)], {}, {exp: 0.5})
    assert mv.build_margin_validation_rows(engine="ENG") == []


def test_settlement_without_recommendation_excluded(monkeypatch):
    """settlement בלי המלצה — לא נכלל (איטרציה על המלצות בלבד)."""
    exp_a, exp_b = date(2026, 6, 19), date(2026, 5, 15)
    _patch(monkeypatch, [_rec(exp_a, 2.0)],
           {exp_a: 2000.0, exp_b: 1800.0}, {exp_a: 0.5, exp_b: 0.2})
    rows = mv.build_margin_validation_rows(engine="ENG")
    assert [r["expiry_date"] for r in rows] == [exp_a]


# ─── בחירת ההמלצה האחרונה + מיון ─────────────────────────────────────────

def test_latest_recommendation_used_upstream(monkeypatch):
    """_fetch_latest_recommendations כבר בורר את האחרונה (MAX recommended_at) —
    נבדק שה-margin ו-n_recommendations ממנה משמשים."""
    exp = date(2026, 6, 19)
    _patch(monkeypatch, [_rec(exp, 1.75, n=4)], {exp: 2000.0}, {exp: 1.6})
    r = mv.build_margin_validation_rows(engine="ENG")[0]
    assert r["recommended_margin"] == 1.75
    assert r["n_recommendations"] == 4
    assert r["held"] is True


def test_rows_sorted_desc_by_expiry(monkeypatch):
    """שורות ממוינות לפי expiry_date יורד (האחרונה ראשונה)."""
    e1, e2, e3 = date(2026, 4, 1), date(2026, 6, 19), date(2026, 5, 10)
    recs = [_rec(e1, 2.0), _rec(e2, 2.0), _rec(e3, 2.0)]
    settle = {e1: 2000.0, e2: 2000.0, e3: 2000.0}
    hist = {e1: 0.3, e2: 0.4, e3: 0.5}
    _patch(monkeypatch, recs, settle, hist)
    rows = mv.build_margin_validation_rows(engine="ENG")
    assert [r["expiry_date"] for r in rows] == [e2, e3, e1]


def test_no_engine_returns_empty(monkeypatch):
    """ללא DATABASE_URL (_make_engine→None) — [] בלי קריאות DB."""
    monkeypatch.setattr(mv, "_make_engine", lambda engine=None: None)
    called = {"n": 0}
    monkeypatch.setattr(mv, "_fetch_latest_recommendations",
                        lambda eng: called.__setitem__("n", called["n"] + 1))
    assert mv.build_margin_validation_rows(engine=None) == []
    assert called["n"] == 0


# ─── CAST ::date על ה-TEXT (condor_settled_detail) ───────────────────────

class _FakeRow:
    def __init__(self, mapping):
        self._mapping = mapping


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows, captured):
        self._rows, self._captured = rows, captured

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, *a, **k):
        self._captured.append(str(stmt))
        return _FakeResult(self._rows)


class _FakeEngine:
    def __init__(self, rows, captured):
        self._rows, self._captured = rows, captured

    def connect(self):
        return _FakeConn(self._rows, self._captured)


def test_fetch_settlements_casts_text_date():
    """_fetch_settlements עושה CAST ::date ומנרמל מחרוזת-תאריך TEXT ל-date key."""
    captured: list = []
    rows = [_FakeRow({"expiry_date": "2026-06-19", "actual_index_close": 2010.5})]
    out = mv._fetch_settlements(_FakeEngine(rows, captured))

    assert "::date" in captured[0]                     # ה-CAST קיים ב-SQL
    assert out == {date(2026, 6, 19): 2010.5}          # ה-TEXT נורמל ל-date


def test_fetch_settlements_error_returns_empty():
    """כשל DB → {} (best-effort, קריאה בלבד)."""
    class _Boom:
        def connect(self):
            raise RuntimeError("db down")
    assert mv._fetch_settlements(_Boom()) == {}


# ─── _as_date ────────────────────────────────────────────────────────────

def test_as_date_parses_types():
    """_as_date: מחרוזת ISO / datetime / date / None / לא-פריק."""
    assert mv._as_date("2026-06-19") == date(2026, 6, 19)
    assert mv._as_date(datetime(2026, 6, 19, 15, 30)) == date(2026, 6, 19)
    assert mv._as_date(date(2026, 6, 19)) == date(2026, 6, 19)
    assert mv._as_date(None) is None
    assert mv._as_date("not-a-date") is None


# ─── summarize_margin_validation ─────────────────────────────────────────

def test_summarize_empty():
    assert mv.summarize_margin_validation([]) == {
        "n_validated": 0, "hold_rate": 0.0, "n_held": 0,
        "hold_rate_1session": 0.0,
        "avg_margin_gap": 0.0, "est_pnl_total": 0.0,
    }


def test_summarize_computes_totals():
    """hold_rate, פער ממוצע ו-P&L מצטבר על פני כמה שורות."""
    rows = [
        {"held": True,  "margin_gap": 1.0,  "est_pnl": 125.0},
        {"held": False, "margin_gap": -0.5, "est_pnl": -300.0},
    ]
    s = mv.summarize_margin_validation(rows)
    assert s["n_validated"] == 2
    assert s["hold_rate"] == 0.5
    assert s["n_held"] == 1
    assert s["avg_margin_gap"] == round((1.0 - 0.5) / 2, 4)
    assert s["est_pnl_total"] == -175.0


def test_summarize_skips_none():
    """gap/est_pnl שהם None מדולגים בממוצע/סכימה."""
    rows = [
        {"held": True,  "margin_gap": None, "est_pnl": None},
        {"held": True,  "margin_gap": 2.0,  "est_pnl": 100.0},
    ]
    s = mv.summarize_margin_validation(rows)
    assert s["hold_rate"] == 1.0
    assert s["avg_margin_gap"] == 2.0        # רק הערך היחיד שאינו None
    assert s["est_pnl_total"] == 100.0
