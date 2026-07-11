"""
בדיקות יחידה להתפלגות התנועות + הסתברות-החזקה ותוחלת הרווח (move_distribution) — שלב 2.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from context_analyzer import find_similar_expiries
from margin_calculator import build_margin_curve, margin_pnl, summarize_curve
from move_distribution import (
    build_move_distribution,
    conditioned_move_distribution,
    expected_value_curve,
    hold_probability,
    hold_probability_curve,
)


# ─── fixtures ─────────────────────────────────────────────────────────────

def _history(records: list[dict]) -> pd.DataFrame:
    """
    בונה DataFrame של expiry_history. כל רשומה: (date, type, move_pct).
    abs_move_pct נגזר כ-|move_pct| (כמו ב-data_loader).
    """
    rows = []
    for date, etype, move in records:
        rows.append({
            "expiry_date":  pd.Timestamp(date),
            "expiry_type":  etype,
            "move_pct":     move,
            "abs_move_pct": None if move is None else abs(move),
        })
    return pd.DataFrame(rows)


# condor קונקרטי: base=2000, short ±2% (1960/2040), כנפיים ±3% (1940/2060), credit=15 נק'.
# net premium = 15·50 = 750 ₪ ; max_loss = (15 − 20)·50 = −250 ₪ (רוחב כנף 20 נק').
_ROW = {
    "skipped":            False,
    "margin_pct":         2.0,
    "base_index":         2000.0,
    "short_put_strike":   1960.0,
    "short_call_strike":  2040.0,
    "long_put_strike":    1940.0,
    "long_call_strike":   2060.0,
    "credit_pts":         15.0,
    "net_premium":        750.0,
    "max_loss":           -250.0,
}


def _realistic_chain(base=2000.0, span_pct=0.10, step=10):
    """שרשרת סינתטית ריאליסטית — פרמיה דועכת אקספוננציאלית עם המרחק מ-ATM (כמו ב-margin_calculator)."""
    lo = int(round(base * (1 - span_pct)))
    hi = int(round(base * (1 + span_pct)))
    rows = []
    for k in range(lo, hi + 1, step):
        prem_pts = max(0.5, 40.0 * math.exp(-abs(k - base) / 100.0))
        rows.append({"strike": float(k), "call_price": round(prem_pts * 50, 2),
                     "put_price": round(prem_pts * 50, 2)})
    return pd.DataFrame(rows)


# ─── TestBuildMoveDistribution ────────────────────────────────────────────

class TestBuildMoveDistribution:
    _hist = _history([
        ("2020-01-15", "M",  1.0),
        ("2020-02-15", "M", -2.0),
        ("2020-03-15", "W",  0.5),
        ("2020-04-15", "W", -0.5),
    ])

    def test_sample_and_stats(self):
        d = build_move_distribution(self._hist)
        assert d["n"] == 4
        np.testing.assert_array_equal(d["moves"], np.array([-2.0, -0.5, 0.5, 1.0]))
        assert d["mean"] == pytest.approx((1.0 - 2.0 + 0.5 - 0.5) / 4)   # -0.25
        assert d["abs_mean"] == pytest.approx((1.0 + 2.0 + 0.5 + 0.5) / 4)  # 1.0
        # std מוחזר מעוגל ל-4 ספרות → משווים לערך המעוגל.
        assert d["std"] == pytest.approx(round(float(np.std([1.0, -2.0, 0.5, -0.5])), 4))

    def test_moves_sorted_ascending(self):
        d = build_move_distribution(self._hist)
        assert list(d["moves"]) == sorted(d["moves"])

    def test_drops_nan_moves(self):
        hist = _history([("2020-01-15", "M", 1.0), ("2020-02-15", "M", None)])
        d = build_move_distribution(hist)
        assert d["n"] == 1
        assert d["moves"].tolist() == [1.0]

    def test_filter_by_type(self):
        d = build_move_distribution(self._hist, expiry_type="M")
        assert d["n"] == 2
        assert set(d["moves"].tolist()) == {1.0, -2.0}
        assert d["expiry_type"] == "M"

    def test_before_date_zero_lookahead(self):
        # רק פקיעות שלפני 2020-03-01 → שתי ה-M
        d = build_move_distribution(self._hist, before_date="2020-03-01")
        assert d["n"] == 2
        assert set(d["moves"].tolist()) == {1.0, -2.0}

    def test_empty_df_returns_empty_dist(self):
        d = build_move_distribution(pd.DataFrame())
        assert d["n"] == 0 and d["moves"].size == 0
        assert d["mean"] is None and d["std"] is None and d["abs_mean"] is None

    def test_missing_move_pct_column(self):
        d = build_move_distribution(pd.DataFrame({"x": [1, 2]}))
        assert d["n"] == 0

    def test_filter_leaving_nothing_is_empty(self):
        d = build_move_distribution(self._hist, expiry_type="M", before_date="2019-01-01")
        assert d["n"] == 0 and d["mean"] is None


# ─── TestHoldProbability ──────────────────────────────────────────────────

class TestHoldProbability:
    def test_fraction_within_short_band(self):
        # band = [−2%, +2%] (1960/2040 על 2000). מתוך 5 תנועות, 3 בפנים.
        dist = {"moves": np.array([-3.0, -1.0, 0.0, 1.0, 3.0])}
        assert hold_probability(dist, _ROW) == pytest.approx(3 / 5)

    def test_boundary_is_inclusive(self):
        # תנועות בדיוק על ±2% נספרות כ"בתוך הטווח".
        dist = {"moves": np.array([-2.0, 2.0, 2.01, -2.01])}
        assert hold_probability(dist, _ROW) == pytest.approx(2 / 4)

    def test_uses_actual_strikes_not_margin_pct(self):
        # strikes אסימטריים: short_put ב-−1% (1980), short_call ב-+3% (2060).
        row = dict(_ROW, short_put_strike=1980.0, short_call_strike=2060.0)
        dist = {"moves": np.array([-2.0, -0.5, 0.0, 2.0, 4.0])}
        # טווח [−1%, +3%]: בפנים −0.5, 0, 2 → 3 מתוך 5
        assert hold_probability(dist, row) == pytest.approx(3 / 5)

    def test_skipped_row_returns_none(self):
        assert hold_probability({"moves": np.array([0.0])}, {"skipped": True}) is None

    def test_empty_distribution_returns_none(self):
        assert hold_probability({"moves": np.array([])}, _ROW) is None


# ─── TestHoldProbabilityCurve ─────────────────────────────────────────────

class TestHoldProbabilityCurve:
    _dist = {"moves": np.array([-3.0, -1.0, 0.0, 1.0, 3.0])}
    _curve = [_ROW, {"skipped": True, "margin_pct": 5.0, "reason": "רחוק מדי"}]

    def test_attaches_hold_prob(self):
        out = hold_probability_curve(self._dist, self._curve)
        assert out[0]["hold_prob"] == pytest.approx(3 / 5)

    def test_skipped_row_gets_none(self):
        out = hold_probability_curve(self._dist, self._curve)
        assert out[1]["hold_prob"] is None

    def test_does_not_mutate_input(self):
        hold_probability_curve(self._dist, self._curve)
        assert "hold_prob" not in _ROW

    def test_equivalent_to_summarize_curve_fn(self):
        # hold_probability_curve שקול ל-summarize_curve עם hold_prob_fn קשור.
        via_fn = summarize_curve(
            [dict(r) for r in self._curve],
            hold_prob_fn=lambda r: hold_probability(self._dist, r),
        )["curve"]
        via_curve = hold_probability_curve(self._dist, self._curve)
        assert [r.get("hold_prob") for r in via_fn] == [r.get("hold_prob") for r in via_curve]


# ─── TestExpectedValueCurve ───────────────────────────────────────────────
#
# מדגם ידני על ה-condor של _ROW (base=2000). ה-P&L (דרך margin_pnl) חושב ידנית:
#   move   0.0 → S=2000 → 750 ₪ (פרמיה מלאה, בתוך ה-short band)
#   move  +1.0 → S=2020 → 750 ₪
#   move  −1.0 → S=1980 → 750 ₪
#   move  +2.2 → S=2044 → +550 ₪ (רווח *חלקי*: מחוץ ל-short band אך לפני breakeven)
#   move  +2.9 → S=2058 → −150 ₪ (הפסד *חלקי*: בין short לכנף, לא max_loss)
#   move  −2.9 → S=1942 → −150 ₪
#   move  +3.5 → S=2070 → −250 ₪ (max_loss, מעבר לכנף)
#   move  −3.5 → S=1930 → −250 ₪

class TestExpectedValueCurve:
    _MOVES = np.array([0.0, 1.0, -1.0, 2.2, 2.9, -2.9, 3.5, -3.5])
    _dist = {"moves": _MOVES}

    def test_pnl_values_match_margin_pnl(self):
        # מאמת שהחישוב הידני שעליו נשען הטסט תואם ל-margin_pnl בפועל.
        got = [round(margin_pnl(_ROW, float(m)), 2) for m in self._MOVES]
        assert got == [750, 750, 750, 550, -150, -150, -250, -250]

    def test_ev_and_splits_exact(self):
        out = expected_value_curve(self._dist, [_ROW])[0]
        # wins = [750,750,750,550] avg=700 ; losses = [−150,−150,−250,−250] avg=−200
        assert out["p_win"] == pytest.approx(4 / 8)
        assert out["p_loss"] == pytest.approx(4 / 8)
        assert out["avg_win"] == pytest.approx(700.0)
        assert out["avg_loss"] == pytest.approx(-200.0)
        assert out["ev"] == pytest.approx((2800 - 800) / 8)   # 250.0

    def test_identity_ev_equals_weighted_split(self):
        out = expected_value_curve(self._dist, [_ROW])[0]
        recon = out["p_win"] * out["avg_win"] + out["p_loss"] * out["avg_loss"]
        assert out["ev"] == pytest.approx(recon)

    def test_avg_loss_is_real_not_max_loss(self):
        # הלב של השלב: ההפסד הממוצע האמיתי (−200) קטן (בערכו המוחלט) מ-max_loss (−250).
        out = expected_value_curve(self._dist, [_ROW])[0]
        assert out["avg_loss"] > _ROW["max_loss"]
        assert out["avg_loss"] == pytest.approx(-200.0)

    def test_all_moves_inside_no_loss(self):
        out = expected_value_curve({"moves": np.array([0.0, 0.5, -0.5])}, [_ROW])[0]
        assert out["p_loss"] == 0.0
        assert out["avg_loss"] is None
        assert out["ev"] == pytest.approx(750.0)

    def test_skipped_row_none_fields(self):
        out = expected_value_curve(self._dist, [{"skipped": True}])[0]
        for k in ("ev", "avg_win", "avg_loss", "p_win", "p_loss"):
            assert out[k] is None

    def test_empty_distribution_none_fields(self):
        out = expected_value_curve({"moves": np.array([])}, [_ROW])[0]
        assert out["ev"] is None and out["p_win"] is None

    def test_does_not_mutate_input(self):
        expected_value_curve(self._dist, [_ROW])
        assert "ev" not in _ROW


# ─── TestConditionedMoveDistribution ──────────────────────────────────────
#
# מנגנון ההתניה עוטף את find_similar_expiries — הטסט מוכיח שהמדגם המותנה זהה
# בדיוק להפעלת ההתפלגות על פלט מנגנון הדמיון הקיים (ולא ממציא מתמטיקת דמיון חדשה).

class TestConditionedMoveDistribution:
    _hist = _history([
        ("2019-06-20", "M",  0.8),   # יוני — עונתי
        ("2020-06-18", "M",  1.1),   # יוני
        ("2021-06-17", "M", -1.5),   # יוני
        ("2020-07-16", "M",  2.0),   # יולי (חודש אחר)
        ("2020-06-25", "W",  0.3),   # יוני אבל W
    ])

    def test_wraps_find_similar_expiries(self):
        similar = find_similar_expiries(self._hist, "M", 6, recent_move_pct=None)
        dist = conditioned_move_distribution(self._hist, "M", 6, recent_move_pct=None)
        assert dist["n_similar"] == len(similar)
        np.testing.assert_array_equal(
            dist["moves"], np.sort(similar["move_pct"].to_numpy(dtype=float))
        )

    def test_conditioned_flag_and_metadata(self):
        dist = conditioned_move_distribution(self._hist, "M", 6, recent_move_pct=None)
        assert dist["conditioned"] is True
        assert dist["expiry_type"] == "M"
        assert dist["n_similar"] >= 1

    def test_conditions_narrow_the_sample(self):
        # המדגם המותנה (M ביוני) קטן מכלל ההיסטוריה.
        full = build_move_distribution(self._hist)
        cond = conditioned_move_distribution(self._hist, "M", 6, recent_move_pct=None)
        assert cond["n"] < full["n"]
        assert cond["n"] == 3   # שלוש פקיעות M ביוני

    def test_no_similar_returns_empty(self):
        # חודש בלי פקיעות → אין דומים.
        dist = conditioned_move_distribution(self._hist, "M", 12, recent_move_pct=None)
        assert dist["n_similar"] == 0 and dist["n"] == 0
        assert dist["mean"] is None

    def test_before_date_zero_lookahead(self):
        # רק פקיעות M ביוני שלפני 2021 → 2019, 2020 (לא 2021).
        dist = conditioned_move_distribution(
            self._hist, "M", 6, recent_move_pct=None, before_date="2021-01-01"
        )
        assert dist["n"] == 2
        assert set(np.round(dist["moves"], 2)) == {0.8, 1.1}


# ─── TestIntegrationRealisticChain ────────────────────────────────────────
#
# צנרת מלאה: build_margin_curve (שלב 1) → hold_probability_curve → expected_value_curve.

class TestIntegrationRealisticChain:
    _chain = _realistic_chain(2000.0)
    _curve = build_margin_curve(_chain, 2000.0)
    _dist = build_move_distribution(_history([
        ("2020-01-15", "M",  0.4), ("2020-02-15", "M", -1.2), ("2020-03-15", "M", 2.3),
        ("2020-04-15", "M", -0.7), ("2020-05-15", "M",  1.6), ("2020-06-15", "M", -3.1),
    ]))

    def test_hold_prob_monotonic_in_margin(self):
        # מרווח רחב יותר → טווח short רחב יותר → hold_prob לא-יורד.
        rows = [r for r in hold_probability_curve(self._dist, self._curve)
                if not r.get("skipped")]
        probs = [r["hold_prob"] for r in rows]
        assert probs == sorted(probs)

    def test_ev_fields_present_and_consistent(self):
        rows = [r for r in expected_value_curve(self._dist, self._curve)
                if not r.get("skipped")]
        assert rows, "צריך לפחות מרווח תקין אחד"
        for r in rows:
            assert r["ev"] is not None
            recon = (r["p_win"] * (r["avg_win"] or 0.0)
                     + r["p_loss"] * (r["avg_loss"] or 0.0))
            # הזהות מדויקת על הערכים הגולמיים; השדות המאוחסנים מעוגלים (p ל-4 ספרות,
            # avg ל-2), אז השחזור סוטה עד ~0.1 ₪. הזהות המדויקת נבדקת ב-
            # TestExpectedValueCurve.test_identity_ev_equals_weighted_split.
            assert r["ev"] == pytest.approx(recon, abs=0.1)
            if r["avg_loss"] is not None:
                assert r["avg_loss"] >= r["max_loss"] - 1e-6
