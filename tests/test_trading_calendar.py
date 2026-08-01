"""
בדיקות ל-src/trading_calendar.py — לוח המסחר של הבורסה בתל אביב.

מכסה: מעבר שבוע המסחר (א'-ה' → ב'-ו' ב-2026), חגים מאומתים, ספירת ימי מסחר
(שהיא הסיבה שהמודול קיים — ספירת ימי לוח מגזימה את הזמן שנותר לפקיעה),
והתיישנות רשימת החגים.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trading_calendar import (
    HOLIDAYS_VERIFIED_THROUGH,
    holidays_are_current,
    is_chain_fresh,
    is_holiday,
    is_trading_day,
    is_trading_weekday,
    next_trading_day,
    skip_reason,
    trading_days_between,
)


class TestTradingWeekSwitch:
    """TASE עברה מ-ראשון–חמישי ל-שני–שישי בתחילת 2026."""

    def test_sunday_traded_before_2026(self):
        assert is_trading_weekday(date(2025, 11, 2)) is True     # ראשון

    def test_friday_did_not_trade_before_2026(self):
        assert is_trading_weekday(date(2025, 11, 7)) is False    # שישי

    def test_sunday_does_not_trade_in_2026(self):
        """אומת מול Yahoo: אפס ימי ראשון עם מסחר ב-2026."""
        assert is_trading_weekday(date(2026, 7, 26)) is False    # ראשון
        assert is_trading_day(date(2026, 7, 26)) is False

    def test_friday_trades_in_2026(self):
        assert is_trading_weekday(date(2026, 7, 31)) is True     # שישי
        assert is_trading_day(date(2026, 7, 31)) is True

    def test_saturday_never_trades(self):
        assert is_trading_weekday(date(2025, 11, 8)) is False
        assert is_trading_weekday(date(2026, 7, 25)) is False


class TestHolidays:
    """רשימת החגים — נגזרה מנרות TA35.TA בפועל."""

    def test_tisha_bav_is_not_a_trading_day(self):
        """האירוע שהוליד את המודול: 23/07/2026, חמישי, הבורסה סגורה."""
        d = date(2026, 7, 23)
        assert d.weekday() == 3               # חמישי — יום חול לכל דבר
        assert is_trading_weekday(d) is True  # מסנן יום-בשבוע לבדו לא היה תופס
        assert is_holiday(d) is True
        assert is_trading_day(d) is False     # ← השער שהיה חסר

    def test_day_after_tisha_bav_did_trade(self):
        """24/07 כן נסחר — חסימת האוסף באותו יום הייתה תקלה שלו, לא סגירת בורסה."""
        assert is_trading_day(date(2026, 7, 24)) is True

    @pytest.mark.parametrize("d", [
        date(2026, 3, 3),    # פורים
        date(2026, 4, 1), date(2026, 4, 2),    # פסח
        date(2026, 4, 21), date(2026, 4, 22),  # יום הזיכרון / העצמאות
        date(2026, 5, 21), date(2026, 5, 22),  # שבועות
    ])
    def test_known_holidays(self, d):
        assert is_trading_day(d) is False

    def test_ordinary_weekday_trades(self):
        assert is_trading_day(date(2026, 7, 22)) is True   # רביעי רגיל


class TestTradingDaysBetween:
    """הסיבה שהמודול קיים — ספירת ימי לוח מגזימה את הזמן שנותר לפקיעה."""

    def test_same_day_is_zero(self):
        assert trading_days_between(date(2026, 7, 22), date(2026, 7, 22)) == 0

    def test_consecutive_trading_days(self):
        assert trading_days_between(date(2026, 7, 21), date(2026, 7, 22)) == 1

    def test_holiday_is_not_counted(self):
        """22/07 (ד') → 24/07 (ו'): 2 ימי לוח, אבל רק יום מסחר אחד — 23/07 חג."""
        assert (date(2026, 7, 24) - date(2026, 7, 22)).days == 2
        assert trading_days_between(date(2026, 7, 22), date(2026, 7, 24)) == 1

    def test_weekend_is_not_counted(self):
        """31/07 (ו') → 03/08 (ב'): 3 ימי לוח, יום מסחר אחד (שבת+ראשון סגורים)."""
        assert trading_days_between(date(2026, 7, 31), date(2026, 8, 3)) == 1

    def test_span_across_tisha_bav_week(self):
        """22/07 (ד') → 28/07 (ג'): 6 ימי לוח → 3 ימי מסחר (24, 27, 28)."""
        assert trading_days_between(date(2026, 7, 22), date(2026, 7, 28)) == 3

    def test_reversed_range_is_negative(self):
        a, b = date(2026, 7, 22), date(2026, 7, 28)
        assert trading_days_between(b, a) == -trading_days_between(a, b)


class TestNextTradingDay:
    def test_skips_holiday(self):
        """מ-22/07 (ד') הבא הוא 24/07 (ו') — 23/07 הוא תשעה באב."""
        assert next_trading_day(date(2026, 7, 22)) == date(2026, 7, 24)

    def test_skips_weekend(self):
        """משישי 31/07 הבא הוא שני 03/08 — אין מסחר בשבת ובראשון."""
        assert next_trading_day(date(2026, 7, 31)) == date(2026, 8, 3)

    def test_strictly_after(self):
        """יום מסחר תקין → מחזיר את **הבא**, לא את עצמו."""
        assert next_trading_day(date(2026, 7, 22)) > date(2026, 7, 22)


class TestHolidayListStaleness:
    """
    השער שהופך "אני לא יודע" לרעש. הלקח מהאירוע: שער שלא יודע שהוא לא יודע
    מסוכן יותר משער שלא קיים.
    """

    def test_current_within_range(self):
        assert holidays_are_current(HOLIDAYS_VERIFIED_THROUGH) is True
        assert holidays_are_current(date(2026, 7, 1)) is True
        assert holidays_are_current(date(2026, 12, 31)) is True

    def test_stale_beyond_range(self):
        assert holidays_are_current(date(2027, 1, 1)) is False

    def test_yom_kippur_is_blocked(self):
        """21/09/2026 — יום שני. ודאי סגור, ולכן חייב להיחסם."""
        d = date(2026, 9, 21)
        assert d.weekday() == 0
        assert is_trading_day(d) is False

    def test_chol_hamoed_sukkot_still_trades(self):
        """חול-המועד סוכות הוא ימי מסחר (לרוב מקוצרים) — לא לחסום אותם."""
        for day in (28, 29, 30):
            assert is_trading_day(date(2026, 9, day)) is True
        for day in (1, 2):
            assert is_trading_day(date(2026, 10, day)) is True

    def test_rosh_hashana_falls_on_weekend(self):
        """ר"ה 5787 נופל שבת–ראשון — כבר לא ימי מסחר, בלי צורך ברשומת חג."""
        assert is_trading_day(date(2026, 9, 12)) is False   # שבת
        assert is_trading_day(date(2026, 9, 13)) is False   # ראשון

    def test_unknown_future_holiday_is_reported_as_trading(self):
        """
        מתעד את המגבלה במפורש: פסח 2027 אינו ברשימה ולכן ייחשב יום מסחר.
        זו בדיוק הסיבה ש-holidays_are_current חייבת להיבדק ע"י הקוראים.
        """
        far = date(2027, 4, 22)
        assert is_trading_day(far) is True
        assert holidays_are_current(far) is False


class TestSkipReason:
    """נקודת ההחלטה המשותפת לרושמים המתוזמנים."""

    def test_trading_day_runs(self):
        assert skip_reason(date(2026, 7, 22)) is None

    def test_holiday_is_skipped_and_named(self):
        r = skip_reason(date(2026, 7, 23))
        assert r is not None and "חג" in r

    def test_weekend_is_skipped_with_different_reason(self):
        r = skip_reason(date(2026, 7, 26))          # ראשון
        assert r is not None and "יום מסחר בשבוע" in r

    def test_force_overrides_everything(self):
        assert skip_reason(date(2026, 7, 23), force=True) is None
        assert skip_reason(date(2026, 7, 25), force=True) is None


class TestChainFreshness:
    """
    השער שהיה חסר ב-23/07/2026: המערכת רצה על שרשרת מ-22/07 ולא ידעה.
    ברירת המחדל (0) = "נמשכה היום" — הרמה הנכונה לכל מי שכותב ל-DB.
    """

    def test_same_day_is_fresh(self):
        assert is_chain_fresh(date(2026, 7, 22), date(2026, 7, 22)) is True

    def test_the_tisha_bav_chain_is_caught(self):
        """
        רגרסיה לאירוע. ב-24/07 (שישי, יום מסחר מלא) השרשרת עדיין הייתה מ-22/07,
        כי האוסף נחסם. עם ה-cron המתוקן הרושמים ירוצו בשישי — והשער חייב לעצור.
        """
        assert is_chain_fresh(date(2026, 7, 22), date(2026, 7, 24)) is False

    def test_yesterday_is_not_fresh_enough_to_write(self):
        """
        משיכה של אתמול אינה מספיקה לכתיבה: ביום מסחר תקין האוסף מושך כל 15 דקות
        מ-09:30, והרושמים רצים ב-10:00/12:00 — היעדר משיכה של היום = האוסף לא עבד.
        """
        assert is_chain_fresh(date(2026, 7, 21), date(2026, 7, 22)) is False

    def test_monday_needs_a_monday_fetch(self):
        """שרשרת של שישי 31/07 אינה מספיקה ביום שני 03/08 — חלף מושב."""
        assert is_chain_fresh(date(2026, 7, 31), date(2026, 8, 3)) is False

    def test_holiday_does_not_age_the_chain(self):
        """
        22/07 (ד') נבדקת ב-23/07 — שהוא תשעה באב. לא חלף שום מושב, ולכן השרשרת
        עדיין 'טרייה'. זה תקין: ביום שאין בו מסחר גם אין מה לרענן — ומי שחוסם
        ריצה ביום כזה הוא skip_reason, לא שער הטריות.
        """
        assert is_chain_fresh(date(2026, 7, 22), date(2026, 7, 23)) is True

    def test_accepts_iso_string(self):
        assert is_chain_fresh("2026-07-22", date(2026, 7, 22)) is True
        assert is_chain_fresh("2026-07-22", date(2026, 7, 24)) is False

    @pytest.mark.parametrize("bad", [None, "", "not-a-date", "31/07/2026"])
    def test_unparseable_is_not_fresh(self, bad):
        """fail-safe: מה שלא ניתן לפרש נחשב לא-טרי, לא לטרי."""
        assert is_chain_fresh(bad, date(2026, 7, 22)) is False

    def test_future_stamp_is_fresh(self):
        assert is_chain_fresh(date(2026, 8, 5), date(2026, 8, 3)) is True

    def test_tolerance_allows_older_chain_for_display(self):
        """קוראים שרק מציגים יכולים להתיר גיל — הכתיבה לא."""
        d, today = date(2026, 7, 22), date(2026, 7, 24)
        assert is_chain_fresh(d, today) is False
        assert is_chain_fresh(d, today, max_age_trading_days=1) is True
