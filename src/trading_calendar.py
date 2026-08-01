"""
trading_calendar.py — לוח המסחר של הבורסה בתל אביב.

**למה המודול הזה קיים**

עד 31/07/2026 לא הייתה במערכת שום הגדרה של "יום מסחר". ההנחה היחידה הייתה מסנן
יום-בשבוע ב-cron של ה-Actions. בתשעה באב (23/07/2026) הבורסה הייתה סגורה, המערכת
לא ידעה, והמשיכה לרשום החלטות והמלצות לפקיעה שלא יכלה לפקוע — כשכל הריצות ירוקות.

**שני דברים שהמודול הזה יודע**

1. **שבוע המסחר השתנה.** TASE עברה מ-ראשון–חמישי ל-שני–שישי בתחילת 2026.
   אומת משני מקורות בלתי-תלויים:
     • expiry_history — 2025-Q3/Q4: פקיעות בימי ראשון/שלישי/חמישי בלבד;
       מ-2026-Q1: שני..שישי, **אפס** ימי ראשון.
     • Yahoo TA35.TA — אפס ימי ראשון עם מסחר ב-2026.

2. **חגים.** רשימה מפורשת. אין נוסחה — מועדי החגים העבריים לועזיים משתנים משנה לשנה.

**מגבלה מתועדת — לקרוא לפני שסומכים על המודול**

`_HOLIDAYS` מכסה 2026 בלבד, ואומתה עד `HOLIDAYS_VERIFIED_THROUGH`. מעבר לתאריך הזה
המודול **אינו יודע** על חגים ויחזיר True לכל יום חול. לכן `holidays_are_current()`
קיימת: היא הופכת את התיישנות הרשימה לרעש במקום לכשל שקט. זה בדיוק הלקח מהאירוע —
שער שלא יודע שהוא לא יודע גרוע משער שלא קיים.
"""
from __future__ import annotations

from datetime import date, timedelta

# ─── מעבר שבוע המסחר ──────────────────────────────────────────────────────
# לפני: ראשון–חמישי (Python weekday: 6,0,1,2,3). מ-2026: שני–שישי (0,1,2,3,4).
TRADING_WEEK_SWITCH = date(2026, 1, 1)

_WEEK_SUN_THU = frozenset({6, 0, 1, 2, 3})
_WEEK_MON_FRI = frozenset({0, 1, 2, 3, 4})

# ─── חגים ותאריכים ללא מסחר ──────────────────────────────────────────────
# **מאומת** — נגזר מנרות יומיים של TA35.TA: יום חול בלי נר = הבורסה הייתה סגורה.
# הוצלב מול tase_putcall_history.
_HOLIDAYS_VERIFIED: frozenset[date] = frozenset({
    date(2026, 1, 2),    # שישי
    date(2026, 3, 3),    # פורים
    date(2026, 4, 1),    # ערב פסח
    date(2026, 4, 2),    # פסח
    date(2026, 4, 7),    # ערב שביעי-של-פסח
    date(2026, 4, 8),    # שביעי-של-פסח
    date(2026, 4, 21),   # יום הזיכרון
    date(2026, 4, 22),   # יום העצמאות
    date(2026, 5, 21),   # ערב שבועות
    date(2026, 5, 22),   # שבועות
    date(2026, 7, 23),   # תשעה באב — האירוע שהוליד את המודול הזה
})

# **צפוי, טרם אומת** — ימי חול שבהם צפויה סגירה בהמשך 2026, לפי הלוח העברי.
# חוסמים אותם בכוונה למרות שלא אומתו: דילוג על ריצה הוא הפיך (הרושמים
# אידמפוטנטיים והריצה הבאה משלימה), בעוד כתיבה על דאטה של יום סגור אינה הפיכה.
#
# ⚠️ שלושת אלה בלבד רלוונטיים — שאר חגי תשרי 5787 נופלים ממילא על שבת/ראשון
#    שאינם ימי מסחר בשבוע שני–שישי. חול-המועד סוכות (28/09–02/10) הוא כן מסחר,
#    לרוב במסחר מקוצר, ולכן אינו ברשימה.
# ⚠️ יום כיפור ודאי. שני ערבי החג — נוהג TASE משתנה (סגירה מלאה מול מסחר מקוצר),
#    ויש לאמת מול לוח המסחר הרשמי של הבורסה.
_HOLIDAYS_EXPECTED: frozenset[date] = frozenset({
    date(2026, 9, 11),   # ערב ראש השנה (שישי) — לאימות
    date(2026, 9, 21),   # יום כיפור (שני) — ודאי
    date(2026, 9, 25),   # ערב סוכות (שישי) — לאימות
})

_HOLIDAYS: frozenset[date] = _HOLIDAYS_VERIFIED | _HOLIDAYS_EXPECTED

# עד כאן הרשימה **אומתה** מול נרות בפועל.
HOLIDAYS_VERIFIED_THROUGH = date(2026, 7, 31)

# עד כאן הרשימה **מכסה** (מאומת + צפוי). מעבר לזה המודול אינו יודע על חגים.
HOLIDAYS_LISTED_THROUGH = date(2026, 12, 31)


def trading_weekdays(d: date) -> frozenset[int]:
    """ימי השבוע (Python weekday, שני=0) שבהם הבורסה נסחרת בתאריך הנתון."""
    return _WEEK_MON_FRI if d >= TRADING_WEEK_SWITCH else _WEEK_SUN_THU


def is_trading_weekday(d: date) -> bool:
    """האם התאריך נופל על יום-בשבוע שבו הבורסה נסחרת (בלי להתחשב בחגים)."""
    return d.weekday() in trading_weekdays(d)


def is_holiday(d: date) -> bool:
    """האם התאריך ברשימת החגים המפורשת."""
    return d in _HOLIDAYS


def is_trading_day(d: date) -> bool:
    """
    האם הבורסה נסחרת בתאריך — יום-בשבוע מתאים **וגם** לא חג.

    ⚠️ מעבר ל-HOLIDAYS_VERIFIED_THROUGH הרשימה אינה מכסה, ולכן כל יום חול יוחזר
    כיום מסחר. ראה holidays_are_current() לזיהוי המצב הזה.
    """
    return is_trading_weekday(d) and not is_holiday(d)


def holidays_are_current(today: date) -> bool:
    """
    האם רשימת החגים עדיין מכסה את התאריך הנתון.

    False = הרשימה התיישנה, וכל תשובה של is_trading_day מעבר לטווח היא ניחוש.
    הקוראים אמורים להרעיש (WARN) ולא להתעלם.

    נמדד מול HOLIDAYS_LISTED_THROUGH (מאומת + צפוי) ולא מול
    HOLIDAYS_VERIFIED_THROUGH: תאריך צפוי הוא עדיין כיסוי — הוא ייחסם.
    """
    return today <= HOLIDAYS_LISTED_THROUGH


def next_trading_day(d: date) -> date:
    """יום המסחר הבא **אחרי** התאריך הנתון (לא כולל אותו)."""
    nxt = d + timedelta(days=1)
    for _ in range(30):                     # תקרה — חג ארוך לא עולה על כמה ימים
        if is_trading_day(nxt):
            return nxt
        nxt += timedelta(days=1)
    raise ValueError(f"לא נמצא יום מסחר ב-30 הימים שאחרי {d}")


def skip_reason(today: date, force: bool = False) -> str | None:
    """
    סיבה לדילוג על ריצה מתוזמנת, או None אם צריך לרוץ.

    נקודת ההחלטה המשותפת לשלושת ה-Actions. טהורה בכוונה — הקורא הוא זה שקורא
    את משתנה הסביבה ומעביר force, כדי שהמודול יישאר נטול-תלויות וניתן לבדיקה.

    force=True עוקף את הדילוג (להרצה ידנית מ-workflow_dispatch), אבל **לא** מסתיר
    את העובדה — הקורא אמור עדיין לרשום שהיום אינו יום מסחר.
    """
    if force:
        return None
    if not is_trading_day(today):
        why = "חג" if is_holiday(today) else "אינו יום מסחר בשבוע"
        return f"הבורסה סגורה היום ({today}, {why})"
    return None


def is_chain_fresh(fetch_date, today: date, max_age_trading_days: int = 0) -> bool:
    """
    האם שרשרת אופציות שנמשכה ב-fetch_date עדיין טרייה נכון ל-today.

    הגיל נמדד ב**מושבי מסחר שחלפו**, לא בימי לוח: שרשרת מיום חמישי שנבדקת ביום
    שישי שהיה חג היא בת אפס מושבים, לא יום.

    **ברירת המחדל 0 = "נמשכה היום".** זו הרמה הנכונה לכל מי שכותב ל-DB או פותח
    עסקה: האוסף מושך כל 15 דקות מ-09:30, והרושמים רצים ב-10:00/12:00 שעון ישראל,
    ולכן בכל יום מסחר תקין קיימת משיכה של אותו יום. היעדרה = האוסף לא עבד היום,
    וזה בדיוק מה שקרה ב-23–24/07/2026.
    קוראים שרק *מציגים* נתונים יכולים להעביר ערך גדול יותר ולציין את הגיל בתצוגה.

    Parameters
    ----------
    fetch_date           : date | str ('YYYY-MM-DD') | None — תאריך המשיכה.
    today                : תאריך הייחוס.
    max_age_trading_days : כמה מושבי מסחר מותר שיחלפו. 0 = חייב להיות של היום.

    Returns
    -------
    bool — False גם כאשר fetch_date חסר או בלתי-פריק (fail-safe: לא טרי).
    """
    if fetch_date is None:
        return False
    if not isinstance(fetch_date, date):
        try:
            fetch_date = date.fromisoformat(str(fetch_date)[:10])
        except (ValueError, TypeError):
            return False
    if fetch_date > today:
        return True                          # חותמת עתידית — לא מיושנת
    return trading_days_between(fetch_date, today) <= max_age_trading_days


def trading_days_between(start: date, end: date) -> int:
    """
    מספר ימי המסחר בין שני תאריכים — **לא כולל** start, **כולל** end.

    trading_days_between(d, d) == 0. אם end < start מוחזר מספר שלילי, בעל אותו
    גודל מוחלט. זו ההגדרה שנדרשת ל"כמה ימי מסחר נשארו עד הפקיעה": ספירת ימי לוח
    מונה גם חגים וסופי-שבוע, ולכן מגזימה את הזמן שנותר.
    """
    if end == start:
        return 0
    if end < start:
        return -trading_days_between(end, start)
    n, cur = 0, start + timedelta(days=1)
    while cur <= end:
        if is_trading_day(cur):
            n += 1
        cur += timedelta(days=1)
    return n
