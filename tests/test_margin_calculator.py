"""
בדיקות יחידה למחשבון המרווחים (margin_calculator).
"""
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from margin_calculator import (
    DEFAULT_WING_PCT,
    _default_margins,
    build_margin_curve,
    margin_pnl,
    summarize_curve,
)


# ─── fixtures ─────────────────────────────────────────────────────────────

def _realistic_chain(base=2000.0, span_pct=0.10, step=10):
    """
    שרשרת סינתטית ריאליסטית: פרמיה (בנקודות) דועכת אקספוננציאלית עם המרחק מ-ATM.
    כך short קרוב (מרווח צר) שווה יותר מ-short רחוק — כמו בשוק אמיתי.
    """
    lo = int(round(base * (1 - span_pct)))
    hi = int(round(base * (1 + span_pct)))
    rows = []
    for k in range(lo, hi + 1, step):
        prem_pts = max(0.5, 40.0 * math.exp(-abs(k - base) / 100.0))
        rows.append({
            "strike":     float(k),
            "call_price": round(prem_pts * 50, 2),   # ₪
            "put_price":  round(prem_pts * 50, 2),   # ₪
        })
    return pd.DataFrame(rows)


def _exact_chain(base=2000.0):
    """
    שרשרת עם פרמיות עגולות בארבעת ה-strikes של מרווח 2.0% (wing 1.0%),
    כדי לבדוק ערכי P&L מדויקים:
        short_put 1960 = 10 נק' | short_call 2040 = 12 נק'
        long_put  1940 =  4 נק' | long_call  2060 =  3 נק'
        credit = (10+12) − (4+3) = 15 נק' → 750 ₪
    """
    rows = []
    for k in range(1900, 2101, 10):
        generic = max(1.0, 30 - abs(k - base) * 0.1)   # נק' חיוביות גנריות
        rows.append({
            "strike":     float(k),
            "call_price": round(generic * 50, 2),
            "put_price":  round(generic * 50, 2),
        })
    df = pd.DataFrame(rows)

    def setp(strike, col, pts):
        df.loc[df["strike"] == strike, col] = pts * 50.0

    setp(1960, "put_price", 10.0)    # short put
    setp(2040, "call_price", 12.0)   # short call
    setp(1940, "put_price", 4.0)     # long put (wing)
    setp(2060, "call_price", 3.0)    # long call (wing)
    return df, base


# ─── גריד ברירת המחדל ─────────────────────────────────────────────────────

class TestDefaultGrid:
    def test_default_margins_are_nine_values(self):
        m = _default_margins()
        assert m == [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0]

    def test_build_curve_uses_default_grid(self):
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0)
        assert len(curve) == 9
        margins = [r["margin_pct"] for r in curve]
        assert margins == [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0]

    def test_custom_margins_respected(self):
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0, margins=[1.5, 2.5])
        assert [r["margin_pct"] for r in curve] == [1.5, 2.5]


# ─── פרמיה: צר > רחב ──────────────────────────────────────────────────────

class TestPremiumMonotonicity:
    def test_narrow_pays_more_than_wide(self):
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0)
        avail = [r for r in curve if not r["skipped"]]
        first, last = avail[0], avail[-1]           # 1.0% מול 3.0%
        assert first["margin_pct"] < last["margin_pct"]
        assert first["net_premium"] > last["net_premium"]

    def test_premium_trends_down_overall(self):
        """המגמה יורדת (חצי-צר משלם יותר מחצי-רחב) — תכונה חסרת-תלות-בכנף. נבדק ב-wing_pct=1.0
        מפורש: השרשרת הסינתטית על גריד 10-נק' בבסיס 2000, והכנף הרשמית 0.75% = 15 נק' שם
        (לא כפולה של 10) → aliasing שמעוות את הסכום — ארטיפקט פיקסצ'ר, לא רגרסיה (בבסיס אמיתי
        ~4050 הכנף 0.75%≈30 נק' מיושרת, והפרמיות חלקות). כנף 1.0%=20 נק' מיושרת לגריד."""
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0, wing_pct=1.0)
        prems = [r["net_premium"] for r in curve if not r["skipped"]]
        mid = len(prems) // 2
        assert sum(prems[:mid]) > sum(prems[mid:])

    def test_all_available_have_positive_premium(self):
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0)
        for r in curve:
            if not r["skipped"]:
                assert r["net_premium"] > 0


# ─── מבנה שורה + max_loss + breakeven + יחס ───────────────────────────────

class TestRowFields:
    def test_row_has_all_required_fields(self):
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0)
        row = next(r for r in curve if not r["skipped"])
        for k in ("margin_pct", "short_put_strike", "short_call_strike",
                  "wing_width", "net_premium", "max_loss",
                  "breakeven_down_pct", "breakeven_up_pct",
                  "premium_to_max_loss_ratio"):
            assert k in row

    def test_max_loss_is_negative(self):
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0)
        for r in curve:
            if not r["skipped"]:
                assert r["max_loss"] < 0

    def test_ratio_matches_premium_over_abs_loss(self):
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0)
        for r in curve:
            if not r["skipped"] and r["premium_to_max_loss_ratio"] is not None:
                assert r["premium_to_max_loss_ratio"] == pytest.approx(
                    r["net_premium"] / abs(r["max_loss"]), rel=1e-3
                )

    def test_exact_values_on_clean_chain(self):
        chain, base = _exact_chain()
        curve = build_margin_curve(chain, base, margins=[2.0], wing_pct=1.0)
        row = curve[0]
        assert not row["skipped"]
        assert row["short_put_strike"] == 1960.0
        assert row["short_call_strike"] == 2040.0
        assert row["long_put_strike"] == 1940.0
        assert row["long_call_strike"] == 2060.0
        assert row["credit_pts"] == pytest.approx(15.0)
        assert row["net_premium"] == pytest.approx(750.0)
        assert row["wing_width"] == pytest.approx(20.0)
        assert row["max_loss"] == pytest.approx(-250.0)        # (20−15)×50
        assert row["premium_to_max_loss_ratio"] == pytest.approx(3.0)
        # BE: מעלה 2040+15=2055 → +2.75% ; מטה 1960−15=1945 → −2.75%
        assert row["breakeven_up_pct"] == pytest.approx(2.75, abs=0.05)
        assert row["breakeven_down_pct"] == pytest.approx(2.75, abs=0.05)


# ─── margin_pnl: בתוך הטווח / פריצת כנף / ביניים ─────────────────────────

class TestLegPrices:
    """מחיר כל רגל נשמר בשורת העקומה — ומשם ל-recommendation_json ול-legs_json של
    העסקה. בלי זה, מחירי האופציות הבודדות אובדים לתמיד בכל פקיעה (ה-chain נדרס)."""

    _KEYS = ("short_put_price_pts", "short_call_price_pts",
             "long_put_price_pts", "long_call_price_pts")

    def test_row_exposes_all_four_leg_prices(self):
        chain, base = _exact_chain()
        curve = build_margin_curve(chain, base, wing_pct=1.0, margins=[2.0])
        row = curve[0]
        assert not row["skipped"]
        for k in self._KEYS:
            assert k in row, f"חסר {k} בשורת העקומה"

    def test_leg_prices_are_the_actual_chain_prices(self):
        chain, base = _exact_chain()
        row = build_margin_curve(chain, base, wing_pct=1.0, margins=[2.0])[0]
        assert row["short_put_price_pts"]  == pytest.approx(10.0)
        assert row["short_call_price_pts"] == pytest.approx(12.0)
        assert row["long_put_price_pts"]   == pytest.approx(4.0)
        assert row["long_call_price_pts"]  == pytest.approx(3.0)

    def test_leg_prices_reconcile_to_credit_pts(self):
        """האינווריאנטה שמחזיקה את הכל: (shorts) − (longs) == credit_pts.
        אם היא נשברת, מחירי הרגליים לא מסבירים את הפרמיה שנרשמה בעסקה."""
        chain, base = _exact_chain()
        for row in build_margin_curve(chain, base, wing_pct=1.0):
            if row["skipped"]:
                continue
            shorts = row["short_put_price_pts"] + row["short_call_price_pts"]
            longs  = row["long_put_price_pts"] + row["long_call_price_pts"]
            assert (shorts - longs) == pytest.approx(row["credit_pts"], abs=1e-3)

    def test_leg_prices_are_positive(self):
        """רגל לא סחירה (price<=0) נפסלת בשער 2, ולכן שורה תקינה לעולם לא נושאת 0."""
        chain = _realistic_chain()
        for row in build_margin_curve(chain, 2000.0):
            if row["skipped"]:
                continue
            for k in self._KEYS:
                assert row[k] > 0

    def test_leg_prices_survive_dataframe_roundtrip(self):
        """מפתחות שטוחים (ולא dict מקונן) — כדי ש-pd.DataFrame(curve) לא יישבר."""
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0)
        df = pd.DataFrame(curve)
        for k in self._KEYS:
            assert k in df.columns


class TestMarginPnl:
    def _row(self):
        chain, base = _exact_chain()
        return build_margin_curve(chain, base, margins=[2.0], wing_pct=1.0)[0]

    def test_inside_range_returns_full_premium(self):
        row = self._row()
        # תנועה 0 → המדד נשאר ב-2000, בין ה-short strikes → רווח הפרמיה המלא.
        assert margin_pnl(row, 0.0) == pytest.approx(750.0)

    def test_break_above_upper_wing_is_max_loss(self):
        row = self._row()
        # +5% → 2100, מעבר ל-long_call 2060 → ההפסד המקסימלי.
        assert margin_pnl(row, 5.0) == pytest.approx(-250.0)

    def test_break_below_lower_wing_is_max_loss(self):
        row = self._row()
        # −5% → 1900, מתחת ל-long_put 1940 → ההפסד המקסימלי.
        assert margin_pnl(row, -5.0) == pytest.approx(-250.0)

    def test_midway_between_short_and_wing_is_intermediate(self):
        row = self._row()
        # +2.5% → 2050, בין short_call 2040 לכנף 2060 → ביניים.
        pnl = margin_pnl(row, 2.5)
        assert pnl == pytest.approx(250.0)                     # (−10+15)×50
        assert row["max_loss"] < pnl < row["net_premium"]

    def test_at_short_strike_still_full_premium(self):
        row = self._row()
        # בדיוק ב-short_call 2040 (+2.0%) → עדיין רווח הפרמיה המלא (הקצה של הפלטו).
        assert margin_pnl(row, 2.0) == pytest.approx(750.0)

    def test_skipped_row_raises(self):
        skipped = {"margin_pct": 3.0, "base_index": 2000.0, "skipped": True, "reason": "x"}
        with pytest.raises(ValueError):
            margin_pnl(skipped, 0.0)


# ─── שרשרת חסרת strikes → skipped, לא קורס ────────────────────────────────

class TestSkipping:
    def _narrow_chain(self, base=2000.0):
        """שרשרת צרה שמשתרעת רק ±2% (1960–2040) — מרווחים רחבים חורגים ממנה."""
        rows = []
        for k in range(1960, 2041, 10):
            rows.append({"strike": float(k), "call_price": 100.0, "put_price": 100.0})
        return pd.DataFrame(rows), base

    def test_wide_margin_skipped_not_crash(self):
        chain, base = self._narrow_chain()
        curve = build_margin_curve(chain, base, margins=[1.0, 3.0], wing_pct=1.0)
        by_margin = {r["margin_pct"]: r for r in curve}
        # 3.0% דורש כנף ב-±4% (2080/1920) — מחוץ ל-1960–2040 → מדולג.
        assert by_margin[3.0]["skipped"] is True
        assert "reason" in by_margin[3.0]
        # 1.0% (כנף ±2% = 2040/1960) בדיוק בטווח → תקין.
        assert by_margin[1.0]["skipped"] is False

    def test_empty_chain_all_skipped(self):
        empty = pd.DataFrame(columns=["strike", "call_price", "put_price"])
        curve = build_margin_curve(empty, 2000.0)
        assert len(curve) == 9
        assert all(r["skipped"] for r in curve)

    def test_zero_price_leg_skipped(self):
        # שרשרת רחבה אך עם מחירים אפסיים → אין רגל סחירה → מדולג.
        rows = [{"strike": float(k), "call_price": 0.0, "put_price": 0.0}
                for k in range(1800, 2201, 10)]
        curve = build_margin_curve(pd.DataFrame(rows), 2000.0, margins=[2.0])
        assert curve[0]["skipped"] is True


# ─── summarize_curve ──────────────────────────────────────────────────────

class TestSummarizeCurve:
    def test_orders_by_margin_and_counts(self):
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0)
        summary = summarize_curve(curve)
        margins = [r["margin_pct"] for r in summary["curve"]]
        assert margins == sorted(margins)
        assert summary["n_margins"] == len(curve)
        assert summary["n_available"] + summary["n_skipped"] == summary["n_margins"]

    def test_hold_prob_fn_attached_to_available_only(self):
        chain, base = self._mixed()
        curve = build_margin_curve(chain, base, margins=[1.0, 3.0], wing_pct=1.0)
        summary = summarize_curve(curve, hold_prob_fn=lambda row: 0.9)
        for r in summary["curve"]:
            if r["skipped"]:
                assert r["hold_prob"] is None
            else:
                assert r["hold_prob"] == 0.9

    def _mixed(self, base=2000.0):
        rows = [{"strike": float(k), "call_price": 100.0, "put_price": 100.0}
                for k in range(1960, 2041, 10)]
        return pd.DataFrame(rows), base

    def test_no_hold_prob_fn_leaves_no_field(self):
        chain = _realistic_chain()
        curve = build_margin_curve(chain, 2000.0)
        summary = summarize_curve(curve)
        assert all("hold_prob" not in r for r in summary["curve"])


def test_default_wing_pct_is_official_075():
    """נועל את הכנף הרשמית = 0.75% (נקודת-האיזון מסריקת הכנפיים) — הקבוע *והשפעתו* על
    עקומה שנבנית ללא wing מפורש (הנתיב שההמלצות ו-select_margin מקבלים)."""
    assert DEFAULT_WING_PCT == 0.75
    # עקומה ללא wing מפורש → כנף 0.75 (מה שהרשם/select_margin עובדים עליו).
    row = build_margin_curve(_realistic_chain(2000.0), 2000.0, margins=[2.0])[0]
    assert row["wing_pct"] == 0.75


# ─── שלב 6: פרמטור הכנף — כיוון כלכלי + רגרסיית ברירת מחדל ────────────────

class TestWingParametric:
    _chain = _realistic_chain(2000.0)

    def _row(self, wing):
        return build_margin_curve(self._chain, 2000.0, margins=[2.0], wing_pct=wing)[0]

    def test_wider_wing_raises_premium_and_max_loss(self):
        narrow, wide = self._row(0.5), self._row(1.5)
        assert not narrow["skipped"] and not wide["skipped"]
        # כנף רחבה → long רחוק וזול יותר → פרמיה נטו גבוהה יותר
        assert wide["net_premium"] > narrow["net_premium"]
        # כנף רחבה → רוחב אנכי גדול → הפסד-מקס עמוק יותר (בערך מוחלט)
        assert abs(wide["max_loss"]) > abs(narrow["max_loss"])
        assert wide["wing_width"] > narrow["wing_width"]

    def test_narrow_wing_has_better_risk_ratio(self):
        # יחס פרמיה/הפסד טוב יותר לכנף צרה (יעילות סיכון)
        assert (self._row(0.5)["premium_to_max_loss_ratio"]
                > self._row(1.5)["premium_to_max_loss_ratio"])

    def test_default_wing_equals_official_075(self):
        # ברירת המחדל (ללא wing_pct) == wing_pct=0.75 מפורש — נועל את הכנף הרשמית בעקומה.
        default_row = build_margin_curve(self._chain, 2000.0, margins=[2.0])[0]
        explicit_row = build_margin_curve(self._chain, 2000.0, margins=[2.0], wing_pct=0.75)[0]
        assert default_row == explicit_row
