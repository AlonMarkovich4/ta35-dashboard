"""
בדיקות ל-implied_move — התנועה שהשוק מתמחר (ATM straddle).

מודול טהור: כל הבדיקות על chain מדומה, אפס DB.
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from implied_move import expected_move_pct, implied_vs_margin

MULT = 50.0


def _chain(base=4000.0, step=10, span=200, call_pts=None, put_pts=None):
    """שרשרת מדומה. call_pts/put_pts — dict {strike: נקודות} לדריסה נקודתית;
    ברירת מחדל: מחיר גנרי חיובי שיורד עם המרחק מה-ATM."""
    rows = []
    for k in range(int(base - span), int(base + span) + 1, step):
        generic = max(1.0, 30 - abs(k - base) * 0.1)
        c = (call_pts or {}).get(k, generic)
        p = (put_pts or {}).get(k, generic)
        rows.append({"strike": float(k), "call_price": c * MULT, "put_price": p * MULT})
    return pd.DataFrame(rows)


# ─── החישוב הבסיסי ───────────────────────────────────────────────────────

class TestBasicCalculation:
    def test_atm_straddle_is_the_expected_move(self):
        """ATM=4000, call=12 נק' + put=8 נק' → straddle=20 נק' → 20/4000 = 0.5%."""
        chain = _chain(base=4000.0, call_pts={4000: 12.0}, put_pts={4000: 8.0})
        r = expected_move_pct(chain, 4000.0)
        assert r["skipped"] is False
        assert r["atm_strike"] == 4000.0
        assert r["straddle_price_pts"] == pytest.approx(20.0)
        assert r["expected_move_pct"] == pytest.approx(0.5)
        assert r["expected_move_pts"] == pytest.approx(20.0)

    def test_atm_is_the_strike_nearest_the_index(self):
        """המדד 4047 → ה-ATM הוא 4050, לא 4000."""
        chain = _chain(base=4050.0)
        r = expected_move_pct(chain, 4047.0)
        assert r["atm_strike"] == 4050.0
        assert r["atm_tradable"] is True

    def test_prices_are_shekels_converted_to_points(self):
        """המנוע כולו מחזיק מחיר ב-₪; נקודות = ₪ ÷ 50 (MULTIPLIER)."""
        chain = pd.DataFrame([{"strike": 4000.0, "call_price": 500.0, "put_price": 500.0}])
        r = expected_move_pct(chain, 4000.0)
        assert r["straddle_price_pts"] == pytest.approx(20.0)   # 1000₪ / 50
        assert r["expected_move_pct"] == pytest.approx(0.5)

    def test_bigger_straddle_means_bigger_expected_move(self):
        calm  = expected_move_pct(_chain(call_pts={4000: 5.0},  put_pts={4000: 5.0}),  4000.0)
        storm = expected_move_pct(_chain(call_pts={4000: 40.0}, put_pts={4000: 40.0}), 4000.0)
        assert storm["expected_move_pct"] > calm["expected_move_pct"]


# ─── implied יומי (נורמליזציית √זמן) ─────────────────────────────────────

class TestImpliedDaily:
    def test_daily_scales_by_sqrt_of_days(self):
        """4 ימים, תנועה צפויה 2% → יומי = 2/√4 = 1%."""
        chain = _chain(base=4000.0, call_pts={4000: 40.0}, put_pts={4000: 40.0})  # 80 נק' = 2%
        r = expected_move_pct(chain, 4000.0, expiry_date=date(2026, 7, 18),
                              as_of_date=date(2026, 7, 14))
        assert r["days_to_expiry"] == 4
        assert r["expected_move_pct"] == pytest.approx(2.0)
        assert r["implied_daily_pct"] == pytest.approx(1.0)

    def test_no_dates_means_no_daily(self):
        r = expected_move_pct(_chain(), 4000.0)
        assert r["implied_daily_pct"] is None
        assert r["days_to_expiry"] is None

    def test_same_day_expiry_has_no_daily(self):
        """0 ימים → אין חלוקה ב-√0."""
        r = expected_move_pct(_chain(), 4000.0, expiry_date=date(2026, 7, 14),
                              as_of_date=date(2026, 7, 14))
        assert r["implied_daily_pct"] is None
        assert r["expected_move_pct"] is not None   # התנועה עצמה עדיין מחושבת

    def test_accepts_string_dates(self):
        r = expected_move_pct(_chain(), 4000.0, expiry_date="2026-07-18",
                              as_of_date="2026-07-14")
        assert r["days_to_expiry"] == 4


# ─── ATM לא סחיר ─────────────────────────────────────────────────────────

class TestUntradableAtm:
    def test_falls_back_to_nearest_tradable_and_flags_it(self):
        """ה-ATM (4000) בלי ציטוט call → נבחר הסחיר הקרוב, ומסומן atm_tradable=False."""
        chain = _chain(base=4000.0, call_pts={4000: 0.0})
        r = expected_move_pct(chain, 4000.0)
        assert r["skipped"] is False
        assert r["atm_strike"] != 4000.0
        assert r["atm_tradable"] is False
        assert r["atm_distance_pts"] > 0

    def test_zero_price_leg_is_not_treated_as_free(self):
        """מחיר 0 = "אין ציטוט", לא "אופציה חינם". אילו ספרנו אותו, ה-straddle היה
        יוצא קטן מדי וה-expected move היה מציג שוק רגוע מהמציאות."""
        chain = _chain(base=4000.0, put_pts={4000: 0.0})
        r = expected_move_pct(chain, 4000.0)
        assert r["atm_strike"] != 4000.0          # לא השתמשנו בסטרייק הפגום
        assert r["straddle_price_pts"] > 0

    def test_atm_tradable_true_when_atm_itself_is_quoted(self):
        r = expected_move_pct(_chain(base=4000.0), 4000.0)
        assert r["atm_tradable"] is True
        assert r["atm_distance_pts"] == 0.0


# ─── קצוות ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_chain_skips(self):
        r = expected_move_pct(pd.DataFrame(), 4000.0)
        assert r["skipped"] is True
        assert "ריק" in r["reason"]
        assert r["expected_move_pct"] is None

    def test_none_chain_skips(self):
        assert expected_move_pct(None, 4000.0)["skipped"] is True

    def test_missing_columns_skips_with_reason(self):
        bad = pd.DataFrame([{"strike": 4000.0}])
        r = expected_move_pct(bad, 4000.0)
        assert r["skipped"] is True
        assert "call_price" in r["reason"] and "put_price" in r["reason"]

    def test_no_tradable_strike_skips(self):
        """כל השרשרת ללא ציטוטים → אין straddle, לא ממציאים אחד."""
        chain = pd.DataFrame([
            {"strike": 4000.0, "call_price": 0.0, "put_price": 0.0},
            {"strike": 4010.0, "call_price": 0.0, "put_price": None},
        ])
        r = expected_move_pct(chain, 4000.0)
        assert r["skipped"] is True
        assert "סחיר" in r["reason"]

    @pytest.mark.parametrize("bad_base", [0, -100, None, "abc", float("nan")])
    def test_invalid_base_index_skips(self, bad_base):
        r = expected_move_pct(_chain(), bad_base)
        assert r["skipped"] is True
        assert r["expected_move_pct"] is None

    def test_never_raises_on_garbage(self):
        chain = pd.DataFrame([{"strike": "לא-מספר", "call_price": "x", "put_price": None}])
        r = expected_move_pct(chain, 4000.0)   # לא זורק
        assert r["skipped"] is True


# ─── implied_vs_margin ───────────────────────────────────────────────────

class TestImpliedVsMargin:
    def test_above_one_means_market_expects_more_than_the_margin(self):
        """השוק מתמחר 2.1% והמרווח 1.75% → 1.2 (דגל אזהרה עתידי)."""
        assert implied_vs_margin(2.1, 1.75) == pytest.approx(1.2)

    def test_below_one_means_calm_market(self):
        assert implied_vs_margin(1.0, 2.0) == pytest.approx(0.5)

    def test_none_inputs_yield_none(self):
        assert implied_vs_margin(None, 1.75) is None
        assert implied_vs_margin(2.0, None) is None

    def test_zero_margin_yields_none_not_division_error(self):
        assert implied_vs_margin(2.0, 0) is None
        assert implied_vs_margin(2.0, -1) is None
