"""
index_series.py — סדרת המדד היומית של TA-35.

**למה המודול הזה קיים**

`expiry_history` מחזיק שורה לכל פקיעה, ו-`move_pct` שבו הוא תנועת **מושב אחד**
(סגירת המושב הקודם → סילוק). כדי לחשב hold לאופק אמיתי — פוזיציה שנפתחת מספר
מושבים לפני הפקיעה — צריך את סדרת המדד היומית עצמה, לא רק את ימי הפקיעה.

מ-`expiry_history` אי אפשר לגזור אותה: בעידן הפקיעות השבועיות השורות מרוחקות
שבוע זו מזו, כך שאין מושבים מתווכים. לכן מקור חיצוני.

**המקור:** Yahoo `TA35.TA` — אותו מקור שממנו `tase-pipeline` לוקח את מחיר
הסילוק. ה-API הישיר של TASE חסום ב-WAF. ה-`open` היומי אומת מול מחיר הסילוק
הרשמי שב-CSV על 6 ימי חפיפה: **6/6 התאמה מדויקת עד האגורה.**

**שימוש:** קריאה אחת ליום בריצת ההמלצות. אין cache — התלות היא רשת אחת,
וכישלון מוחזר כרשימה ריקה (הקורא מחליט אם זו שגיאה).
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

SYMBOL = "TA35.TA"
_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
        "{sym}?interval=1d&range={rng}")
_UA = "Mozilla/5.0"


def fetch_index_sessions(
    rng: str = "2y",
    symbol: str = SYMBOL,
    timeout: int = 30,
) -> list[dict]:
    """
    מוריד את סדרת המושבים היומית ומחזיר [{"date": date, "open": float, "close": float}]
    **ממוין עולה**.

    מושב בלי open **וגם** בלי close מדולג (חג / יום ללא מסחר). מושב עם חלק
    מהערכים נשמר כמות שהוא — הקורא (horizon_move_distribution) מדלג עליו.

    כישלון רשת / מבנה בלתי-צפוי → [] + logging.error. לא זורק, כדי שכשל
    ברשת לא יפיל ריצת המלצות שכל השאר בה תקין.
    """
    url = _URL.format(sym=symbol, rng=rng)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error("index_series: הורדת %s נכשלה: %s", symbol, exc)
        return []

    try:
        res = raw["chart"]["result"][0]
        offset = res["meta"].get("gmtoffset", 0)
        quote = res["indicators"]["quote"][0]
        stamps = res["timestamp"]
        opens, closes = quote["open"], quote["close"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("index_series: מבנה תשובה בלתי-צפוי מ-Yahoo: %s", exc)
        return []

    out: list[dict] = []
    for i, ts in enumerate(stamps):
        o, c = opens[i], closes[i]
        if o is None and c is None:
            continue                      # יום ללא מסחר
        d = datetime.fromtimestamp(ts + offset, tz=timezone.utc).date()
        out.append({"date": d,
                    "open": None if o is None else float(o),
                    "close": None if c is None else float(c)})

    out.sort(key=lambda s: s["date"])
    logger.info("index_series: נטענו %d מושבים (%s → %s).",
                len(out), out[0]["date"] if out else "—", out[-1]["date"] if out else "—")
    return out


# ── ספירת האופק קדימה ────────────────────────────────────────────────────
# מכוון: **אין כאן** פונקציה שסופרת מושבים עד הפקיעה. הפקיעה בעתיד, ולסדרה
# ההיסטורית אין ימים אחריה — ספירה ממנה תמיד תחזיר 0.
# לספירה קדימה: trading_calendar.trading_days_between, שגם יודע לדלג על חגים.
