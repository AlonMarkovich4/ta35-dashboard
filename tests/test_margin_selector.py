"""
בדיקות יחידה לבחירת המרווח (margin_selector) — שלב 3, חלק א.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from context_analyzer import find_similar_expiries
from margin_selector import (
    DEFAULT_HOLD_FLOOR,
    _blend,
    blended_hold_probability,
    select_margin,
)
from move_distribution import build_move_distribution, hold_probability_at_margin


# ─── fixtures ─────────────────────────────────────────────────────────────

def _history(records: list[tuple]) -> pd.DataFrame:
    """(date, type, move) → DataFrame של expiry_history עם abs_move_pct נגזר."""
    rows = [{
        "expiry_date":  pd.Timestamp(d),
        "expiry_type":  t,
        "move_pct":     m,
        "abs_move_pct": None if m is None else abs(m),
    } for d, t, m in records]
    return pd.DataFrame(rows)


def _weekly(moves: list[float], start="2020-01-06") -> pd.DataFrame:
    """סדרת פקיעות W שבועיות עם התנועות הנתונות (תאריכים עולים)."""
    base = pd.Timestamp(start)
    return _history([(base + pd.Timedelta(weeks=i), "W", mv) for i, mv in enumerate(moves)])


def _curve(margins, premium_by_margin=None) -> list[dict]:
    """עקומת מרווח מינימלית (margin_pct + net_premium) לבדיקת select_margin."""
    prem = premium_by_margin or {}
    return [{"margin_pct": float(m), "skipped": False,
             "net_premium": prem.get(m), "ev": None, "max_loss": None} for m in margins]


# מדגם ש-hold הגלובלי שלו ידוע: 16×0.5, 2×1.3, 2×1.8 (n=20).
#   hold@1.0 = 16/20 = 0.80 ; hold@1.5 = 18/20 = 0.90 ; hold@2.0 = 20/20 = 1.00
_MONO_MOVES = [0.5] * 16 + [1.3] * 2 + [1.8] * 2


# ─── TestBlendMath (מתמטיקת השקלול הטהורה) ────────────────────────────────

class TestBlendMath:
    def test_full_weight_when_sample_large(self):
        # n_conditional ≥ min_n → w_effective = weight_conditional
        hb, w = _blend(0.80, 0.95, n_conditional=25, weight_conditional=0.6, min_n=20)
        assert w == pytest.approx(0.6)
        assert hb == pytest.approx(0.6 * 0.80 + 0.4 * 0.95)   # 0.86

    def test_weight_shrinks_on_small_sample(self):
        # n=10 < min_n=20 → w_effective = 0.6 × 10/20 = 0.30
        hb, w = _blend(0.80, 0.95, n_conditional=10, weight_conditional=0.6, min_n=20)
        assert w == pytest.approx(0.30)
        assert hb == pytest.approx(0.30 * 0.80 + 0.70 * 0.95)   # 0.905

    def test_no_conditional_falls_back_to_global(self):
        hb, w = _blend(None, 0.95, n_conditional=0, weight_conditional=0.6, min_n=20)
        assert (hb, w) == (0.95, 0.0)

    def test_no_global_uses_conditional(self):
        hb, w = _blend(0.80, None, n_conditional=25, weight_conditional=0.6, min_n=20)
        assert (hb, w) == (0.80, 1.0)

    def test_both_none(self):
        assert _blend(None, None, 0, 0.6, 20) == (None, 0.0)


# ─── TestBlendedHoldProbability (חיווט על דאטה אמיתי) ──────────────────────

class TestBlendedHoldProbability:
    def test_wires_global_and_conditional(self):
        # שבועות שאחרי תנועה ~3.0 נוטים לתנועה גדולה; גלובלית התנועות קטנות.
        moves = [0.5, 3.0, 2.5, 0.5, 3.0, 2.8] + [0.5] * 14
        df = _weekly(moves)
        R, T, w, min_n, margin = 3.0, 0.5, 0.6, 2, 2.0

        b = blended_hold_probability(df, margin, "W", R, tolerance=T,
                                     weight_conditional=w, min_n=min_n)

        # שחזור עצמאי דרך אותם primitives ציבוריים
        g = build_move_distribution(df, expiry_type="W")
        similar = find_similar_expiries(df, "W", None, R, T)
        c = build_move_distribution(similar)
        assert b["hold_global"] == hold_probability_at_margin(g, margin)
        assert b["hold_conditional"] == hold_probability_at_margin(c, margin)
        assert b["n_conditional"] == len(similar)
        assert b["n_global"] == g["n"]

    def test_small_conditional_sample_reduces_weight(self):
        # 4 שבועות עם תנועה-קודמת ב-[2.5,3.5] (מדגם קטן) → w_effective מוקטן פרופורציונלית.
        moves = [0.5, 3.0, 2.5, 0.5, 3.0, 2.8] + [0.5] * 14
        df = _weekly(moves)
        b = blended_hold_probability(df, 2.0, "W", 3.0, tolerance=0.5,
                                     weight_conditional=0.6, min_n=20)
        # n_conditional=4 → w_effective = 0.6 × 4/20 = 0.12
        assert b["n_conditional"] == 4
        assert b["w_effective"] == pytest.approx(0.12)

    def test_recent_move_none_conditional_equals_global(self):
        df = _weekly(_MONO_MOVES)
        b = blended_hold_probability(df, 1.5, "W", None)
        assert b["hold_conditional"] == b["hold_global"]
        assert b["hold_blended"] == b["hold_global"]


# ─── TestSelectMargin ─────────────────────────────────────────────────────

class TestSelectMargin:
    _margins = [1.0, 1.5, 2.0, 2.5, 3.0]
    _prem = {1.0: 900, 1.5: 700, 2.0: 500, 2.5: 350, 3.0: 250}

    def _df(self):
        return _weekly(_MONO_MOVES)

    def test_picks_narrowest_meeting_floor(self):
        # holds: 1.0→0.80, 1.5→0.90, 2.0→1.0. floor 0.90 → הצר-שעומד = 1.5.
        sel = select_margin(_curve(self._margins, self._prem), self._df(),
                            "W", None, hold_floor=0.90)
        assert sel["selected_margin"] == 1.5
        assert sel["below_floor"] is False
        assert sel["hold_blended"] == pytest.approx(0.90)
        assert sel["net_premium"] == 700   # פרמיה מהעקומה עוברת לשקיפות

    def test_higher_floor_picks_wider(self):
        sel = select_margin(_curve(self._margins, self._prem), self._df(),
                            "W", None, hold_floor=0.95)
        assert sel["selected_margin"] == 2.0   # 1.5 נותן 0.90 < 0.95

    def test_below_floor_returns_widest_with_flag(self):
        # מדגם ש-hold שלו 0.50 בכל מרווח (חצי מהתנועות = 4.0, שוברות הכל).
        df = _weekly([0.5] * 10 + [4.0] * 10)
        sel = select_margin(_curve(self._margins), df, "W", None, hold_floor=0.90)
        assert sel["below_floor"] is True
        assert sel["selected_margin"] == 3.0            # הרחב ביותר
        assert sel["hold_blended"] == pytest.approx(0.50)
        assert "אף מרווח לא עמד" in sel["reason"]

    def test_grid_has_full_transparency(self):
        sel = select_margin(_curve(self._margins, self._prem), self._df(),
                            "W", None, hold_floor=0.90)
        assert [g["margin_pct"] for g in sel["grid"]] == self._margins  # ממוין עולה
        for g in sel["grid"]:
            for k in ("hold_blended", "hold_conditional", "hold_global",
                      "n_conditional", "n_global", "w_effective", "net_premium"):
                assert k in g

    def test_reason_mentions_selected_and_floor(self):
        sel = select_margin(_curve(self._margins, self._prem), self._df(),
                            "W", None, hold_floor=0.90)
        assert "1.50%" in sel["reason"] and "90%" in sel["reason"]

    def test_skipped_rows_excluded_from_selection(self):
        curve = _curve(self._margins, self._prem)
        curve[0]["skipped"] = True   # 1.0% מדולג
        curve[0]["reason"] = "רחוק מדי"
        sel = select_margin(curve, self._df(), "W", None, hold_floor=0.80)
        # 1.0 (0.80) דולג → הצר-שעומד-בסף-0.80 הבא הוא 1.5 (0.90)
        assert 1.0 not in [g["margin_pct"] for g in sel["grid"]]
        assert sel["selected_margin"] == 1.5

    def test_empty_curve_returns_none_decision(self):
        sel = select_margin([], self._df(), "W", None)
        assert sel["selected_margin"] is None and sel["below_floor"] is True


# ─── TestZeroLookaheadAndMonthNone ────────────────────────────────────────

class TestZeroLookahead:
    def test_before_date_ignores_future(self):
        # e0..e5 קטנים + e6 קיצוני מאוחר יותר. before_date אחרי e5 ולפני e6 →
        # הבחירה זהה עם/בלי e6 בדאטה (zero-lookahead).
        moves = [0.5, 0.6, 0.4, 0.5, 0.7, 0.5]
        df_prefix = _weekly(moves)                 # e0..e5
        df_full = _weekly(moves + [9.0])           # + e6 קיצוני, מאוחר יותר
        cutoff = df_prefix["expiry_date"].max() + pd.Timedelta(days=1)  # אחרי e5, לפני e6
        curve = _curve([1.0, 1.5, 2.0, 2.5, 3.0])

        sel_full = select_margin(curve, df_full, "W", None, before_date=cutoff)
        sel_prefix = select_margin(curve, df_prefix, "W", None, before_date=cutoff)
        assert sel_full["selected_margin"] == sel_prefix["selected_margin"]
        assert sel_full["grid"] == sel_prefix["grid"]

    def test_find_similar_month_none_skips_month_filter(self):
        # ההכללה שהוספנו: target_month=None → ללא סינון חודש (כל השבועות מאותו סוג).
        df = _history([
            ("2020-01-06", "W", 0.5), ("2020-06-06", "W", 1.0), ("2020-11-06", "W", 1.5),
        ])
        no_month = find_similar_expiries(df, "W", None, recent_move_pct=None)
        assert len(no_month) == 3   # כל שלושת החודשים
        jan_only = find_similar_expiries(df, "W", 1, recent_move_pct=None)
        assert len(jan_only) == 1   # ינואר בלבד


# ─── TestDefaultFloorLocked (נועל את ברירת המחדל הרשמית) ───────────────────

class TestDefaultFloorLocked:
    """ברירת המחדל הרשמית של hold_floor היא 0.97 — נקודת-הברך מסריקת הספים (768 פקיעות,
    walk-forward). הבדיקות ננעלות על הערך כדי שלא יזוז בטעות בעתיד."""

    _margins = [1.0, 1.5, 2.0, 2.5, 3.0]

    def test_constant_is_097(self):
        assert DEFAULT_HOLD_FLOOR == 0.97

    def test_select_margin_default_uses_097(self):
        df = _weekly(_MONO_MOVES)                        # holds: 1.5→0.90, 2.0→1.00
        implicit = select_margin(_curve(self._margins), df, "W", None)
        explicit = select_margin(_curve(self._margins), df, "W", None, hold_floor=0.97)
        # ברירת המחדל מדווחת 0.97 ומתנהגת בדיוק כמו קריאה מפורשת ל-0.97
        assert implicit["hold_floor"] == 0.97
        assert implicit["selected_margin"] == explicit["selected_margin"]
        # 1.5 נותן 0.90 < 0.97 → נדחה; 2.0 (1.00) הוא הצר-שעומד-בסף הרשמי.
        # אילו ברירת המחדל הייתה חוזרת ל-0.90 — הבחירה הייתה 1.5, והבדיקה תיפול.
        assert implicit["selected_margin"] == 2.0


# ─── שער כלכלי (נוסף 02/08/2026) ─────────────────────────────────────────

from margin_selector import binary_ev, required_hold  # noqa: E402


class TestRequiredHold:
    """
    ה-hold שהמבנה **דורש** כדי לא להפסיד — ללא תלות בשום מודל.
    נמדד על 49 המלצות: credit/width ממוצע 0.21 ⇒ required ≈ 0.79,
    בעוד המנוע טוען 0.977 וה-hold הכן ~0.70.
    """

    def test_symmetric_structure_needs_half(self):
        """קרדיט = הפסד ⇒ צריך 50%."""
        assert required_hold(100, -100) == 0.5

    def test_the_real_ratio(self):
        """credit/width = 0.21 ⇒ required = 0.79. זה המצב בפועל."""
        assert required_hold(210, -790) == 0.79

    def test_thin_credit_needs_near_certainty(self):
        assert required_hold(19, -1481) == 0.9873

    def test_zero_or_negative_credit_is_impossible(self):
        """מבנה short בדביט — שום hold לא מציל אותו."""
        assert required_hold(0, -1000) == 1.0
        assert required_hold(-2.0, -1502.0) == 1.0     # ההמלצה שנצפתה בפועל

    @pytest.mark.parametrize("c,ml", [(None, -100), (100, None), ("x", -100), (0, 0)])
    def test_bad_input_returns_none(self, c, ml):
        assert required_hold(c, ml) is None

    def test_sign_of_max_loss_is_irrelevant(self):
        assert required_hold(100, -300) == required_hold(100, 300)


class TestBinaryEv:
    def test_breakeven_at_required_hold(self):
        """בדיוק ב-required_hold ה-EV אפס — זו ההגדרה."""
        c, ml = 210, -790
        assert abs(binary_ev(c, ml, required_hold(c, ml))) < 0.01

    def test_positive_above_negative_below(self):
        c, ml = 210, -790
        rh = required_hold(c, ml)
        assert binary_ev(c, ml, rh + 0.10) > 0
        assert binary_ev(c, ml, rh - 0.10) < 0

    def test_the_actual_gap(self):
        """המנוע טוען 0.977 → EV חיובי; ב-0.70 הכן → שלילי. זה הממצא."""
        c, ml = 210, -790
        assert binary_ev(c, ml, 0.977) > 0
        assert binary_ev(c, ml, 0.70) < 0


class TestEconomicGate:
    """
    שתי דחיות שונות: פרמיה≤0 תמיד, ו-required>ev_hold רק כשסופק.
    ev_hold=None משמר את ההתנהגות הקיימת במלואה.
    """

    @staticmethod
    def _curve(rows):
        return [{"margin_pct": m, "skipped": False, "net_premium": c,
                 "max_loss": ml, "ev": None} for m, c, ml in rows]

    @staticmethod
    def _hist():
        import numpy as np
        rng = np.random.default_rng(5)
        n = 400
        return pd.DataFrame({
            "expiry_date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "expiry_type": ["W"] * n,
            "move_pct": rng.normal(0, 0.5, n),
        })

    def test_negative_premium_always_rejected(self):
        """גם בלי ev_hold — מבנה בדביט נדחה."""
        curve = self._curve([(1.5, -2.0, -1502.0), (2.0, 300.0, -700.0)])
        out = select_margin(curve, self._hist(), "W", 0.3)
        assert out["selected_margin"] == 2.0
        assert len(out["rejected"]) == 1
        assert "פרמיה" in out["rejected"][0]["reject_reason"]

    def test_ev_hold_none_preserves_behaviour(self):
        """ברירת המחדל אינה חוסמת שום מבנה רזה."""
        curve = self._curve([(1.5, 19.0, -1481.0), (2.0, 300.0, -700.0)])
        out = select_margin(curve, self._hist(), "W", 0.3)
        assert out["ev_hold"] is None
        assert all("דורש hold" not in r["reject_reason"] for r in out["rejected"])

    def test_ev_hold_rejects_thin_credit(self):
        """אותה עקומה עם ev_hold=0.70 — המבנה הרזה נדחה."""
        curve = self._curve([(1.5, 19.0, -1481.0), (2.0, 300.0, -700.0)])
        out = select_margin(curve, self._hist(), "W", 0.3, ev_hold=0.70)
        assert out["selected_margin"] == 2.0
        assert any("דורש hold" in r["reject_reason"] for r in out["rejected"])

    def test_all_rejected_says_no_trade(self):
        """
        כשכל המבנים נדחים — התשובה היא "אין עסקה", ונבדלת מ"אין עקומה".
        זו תשובה לגיטימית, לא כשל.
        """
        curve = self._curve([(1.5, 19.0, -1481.0), (2.0, 25.0, -1975.0)])
        out = select_margin(curve, self._hist(), "W", 0.3, ev_hold=0.70)
        assert out["selected_margin"] is None
        assert len(out["rejected"]) == 2
        assert "נדחו כלכלית" in out["reason"]

    def test_required_hold_exposed_on_grid(self):
        curve = self._curve([(2.0, 210.0, -790.0)])
        out = select_margin(curve, self._hist(), "W", 0.3, ev_hold=0.70)
        row = (out["grid"] or out["rejected"])[0]
        assert row["required_hold"] == 0.79
