"""
vwap_pricing.py — תמחור רגליים במחיר עסקה אמיתי.

**למה המודול הזה קיים**

עד 07/08/2026 כל עסקה במערכת מולאה לפי `lastrate` מהשרשרת. `lastrate` **אינו
מחיר עסקה**: הוא נופל מחוץ לטווח `[lowrate, highrate]` של אותו יום ב-45%
מה-CALL ו-40% מה-PUT — ודווקא בסטרייקים שכן נסחרו. מחיר עסקה אחרון אינו יכול
ליפול מחוץ לטווח העסקאות של אותו יום, ולכן `lastrate` הוא ציטוט או שער תיאורטי.

הפיד **אינו** מספק bid/ask (נבדק מול ה-endpoint: 36 שדות, אפס רלוונטיים,
`curr_Hour="סוף יום"` בכל השורות). אבל הוא כן מספק מחזור, ומהמחזור נגזר מחיר
עסקה משוקלל:

    VWAP = OverallTurnOverValue_Shekel / OverallTurnOverUnits

אומת על כל הארכיון: **בתוך `[lowrate, highrate]` ב-100.0% מהמקרים** —
2,697/2,697 CALL ו-2,995/2,995 PUT. זו הוכחה שהערך הוא מחיר שנסחר.
הפער מ-`lastrate`: 51.5% חציונית ממחיר האופציה.

**מגבלה שאסור לשכוח:** VWAP הוא ממוצע יומי, לא מילוי בנקודת זמן. הוא מחיר
ש**נסחר**, לא מחיר ש**מובטח**. הוא הופך את המדידה לכנה, לא לוודאית.

**כיסוי:** רק ~20% מהסטרייקים נסחרים ביום נתון, והנזילות מרוכזת בפקיעה הקרובה
(אופק 1 מושב → 100% מהרגליים, אופק 5 → 18%). לכן `price_legs` מחזירה
`missing` ולא ממציאה מחיר — הקורא מחליט אם לדלג.

פירוט מלא: HANDOFF סעיף 11.2ב–ד.

API ציבורי:
  vwap(units, value)                      -> float | None      (טהור)
  price_legs(legs, quotes)                -> PricedLegs        (טהור)
  fetch_traded_quotes(expiry, as_of, eng) -> dict[(type,strike) -> float]
"""
from __future__ import annotations

import logging
from typing import Iterable, NamedTuple, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# מקור השרשרת. whitelist — השם נכנס ל-SQL, ולכן אסור לקבל אותו מקלט חופשי.
_ALLOWED_SOURCES = frozenset({"tase_putcall", "tase_putcall_history"})


def vwap(units, value) -> Optional[float]:
    """מחיר עסקה משוקלל, או None אם לא נסחר.

    `units` = OverallTurnOverUnits, `value` = OverallTurnOverValue_Shekel.
    מחזיר None כשאין מחזור — זו התשובה הנכונה, לא 0. אופציה שלא נסחרה אין לה
    מחיר עסקה, ולהמציא לה אחד זו בדיוק הטעות שהמודול הזה בא לתקן.
    """
    try:
        u = float(units) if units is not None else 0.0
        v = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return None
    if u <= 0 or v <= 0:
        return None
    px = v / u
    # מחיר לא-סופי או שלילי אינו מחיר. נופל לאותו טיפול כמו "לא נסחר".
    return px if px > 0 and px == px and px not in (float("inf"), float("-inf")) else None


class PricedLegs(NamedTuple):
    """תוצאת תמחור. `complete` הוא התנאי היחיד שמצדיק פתיחת עסקה."""
    legs: list[dict]            # הרגליים עם price_nis מעודכן (רק אלה שנמצאו)
    missing: list[dict]         # רגליים ללא מחיר עסקה — {type, strike}
    entry_cost: Optional[float] # Σ(קנייה) − Σ(מכירה). None אם חסרה רגל.
    complete: bool


def price_legs(legs: Iterable[dict], quotes: dict) -> PricedLegs:
    """מתמחר רגליים לפי מחירי עסקה. אינו ממציא מחיר לרגל שלא נסחרה.

    `legs`   — [{action: "קנה"/"מכור", type: "Call"/"Put", strike: float, ...}]
    `quotes` — {("Call"|"Put", strike) -> vwap}, מ-`fetch_traded_quotes`.

    `entry_cost` בקונבנציה של `paper_trades`: חיובי = שולם (דביט),
    שלילי = התקבל (קרדיט). זהה ל-`Σ(קנייה) − Σ(מכירה)`, כמו ב-legs_json הקיים.
    """
    priced: list[dict] = []
    missing: list[dict] = []
    cost = 0.0

    for leg in legs or []:
        typ = str(leg.get("type") or "")
        try:
            strike = float(leg.get("strike"))
        except (TypeError, ValueError):
            missing.append({"type": typ, "strike": leg.get("strike"),
                            "reason": "strike לא תקין"})
            continue

        px = quotes.get((typ, strike))
        if px is None:
            missing.append({"type": typ, "strike": strike,
                            "reason": "לא נסחר באותו יום"})
            continue

        qty = float(leg.get("qty") or 1)
        buy = str(leg.get("action") or "") == "קנה"
        cost += (px if buy else -px) * qty
        priced.append({**leg, "price_nis": round(px, 2), "price_source": "vwap"})

    complete = bool(priced) and not missing
    return PricedLegs(
        legs=priced,
        missing=missing,
        entry_cost=round(cost, 2) if complete else None,
        complete=complete,
    )


def chain_asof(engine, source_table: str = "tase_putcall") -> Optional[dict]:
    """זהות הצילום האחרון בטבלה: {fetch_date, fetch_time, trade_date}.

    נועד לתיעוד ולשער טריות — הקורא רושם ביומן **על איזה צילום** הוא פעל.
    None אם אין נתונים או בכשל DB.
    """
    if source_table not in _ALLOWED_SOURCES:
        raise ValueError(f"source_table לא מורשה: {source_table!r}")
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(f"""
                    SELECT fetch_date, fetch_time, trade_date
                    FROM {source_table}
                    ORDER BY fetched_at DESC
                    LIMIT 1
                """),  # noqa: S608 — source_table עבר whitelist למעלה
            ).fetchone()
    except Exception as exc:
        logger.warning("chain_asof נכשל (%s): %s", source_table, exc, exc_info=True)
        return None
    if row is None:
        return None
    m = row._mapping
    return {"fetch_date": str(m.get("fetch_date"))[:10],
            "fetch_time": m.get("fetch_time"),
            "trade_date": m.get("trade_date")}


def fetch_traded_quotes(expiry_date, as_of=None, engine=None,
                        source_table: str = "tase_putcall",
                        min_units: float = 0.0) -> dict:
    """מחירי עסקה לכל הסטרייקים בפקיעה. קריאה בלבד.

    `min_units` — מחזור מינימלי ביחידות שהסטרייק חייב להציג כדי להיחשב סחיר.
    **0 (ברירת המחדל) = "נסחר בכלל"**, וזה מה שתיק 9 משתמש בו.
    ערך גבוה יותר שואל "נסחר **בעומק**", וזו שאלה אחרת: נמדד 11/08/2026 על
    44 ימי ארכיון, ברגליים 1–2 ימים לפקיעה ועד 4% מהכסף —

        חציון 128 יחידות ליום · אחוזון 25 = 28 · אחוזון 10 = 6
        20% מהרגליים שנסחרו הציגו פחות מ-20 יחידות

    כלומר "נסחר" אינו "אפשר לצאת". רגל עם 2 יחידות ביום נסחרה, אבל פקודה
    אחת היא 50% מהמחזור היומי שלה.

    `as_of=None` (ברירת המחדל) ⇒ **הצילום האחרון בטבלה**. `tase_putcall` מחזיקה
    צילום אחד בלבד, ולכן זה בדיוק מה שרוצים בזמן אמת.

    ⚠️ **למה `tase_putcall` ולא `tase_putcall_history`.** הארכיון נכתב פעם ביום
    בסוף המסחר (~17:15 שעון ישראל), בעוד שהפותחים רצים ב-09:00 UTC = 12:00
    שעון ישראל. קריאה מהארכיון בשעה הזו מוצאת רק את **אתמול**, ובימים מסוימים
    לא מוצאת כלום — ואז כל פקיעה מדולגת ב"אין מחיר עסקה", מה שנראה כמו ממצא
    נזילות ולא כמו היעדר נתונים. נמדד 11/08/2026: מהארכיון 0 עסקאות, מהטבלה
    החיה 2. השאר את הארכיון ל-backtest, שם `as_of` מפורש הוא הנכון.

    מחזיר {("Call"|"Put", strike) -> vwap} — **רק** סטרייקים שנסחרו.
    כשל DB או היעדר נתונים ⇒ מילון ריק, לא חריגה. הקורא יראה `missing` מלא
    ויימנע מפתיחה; זו ההתנהגות הרצויה — עדיף לא לסחור מאשר לסחור על מחיר מומצא.
    """
    if source_table not in _ALLOWED_SOURCES:
        raise ValueError(f"source_table לא מורשה: {source_table!r}")
    if engine is None:
        return {}

    where = "expiry_date::date = CAST(:exp AS date)"
    params = {"exp": str(expiry_date)[:10]}
    if as_of is not None:
        where += " AND fetch_date::date = CAST(:asof AS date)"
        params["asof"] = str(as_of)[:10]

    out: dict = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT COALESCE(expirationprice_call, expirationprice_put) AS strike,
                           overallturnoverunits_call,  overallturnovervalue_shekel_call,
                           overallturnoverunits_put,   overallturnovervalue_shekel_put
                    FROM {source_table}
                    WHERE {where}
                """),  # noqa: S608 — source_table עבר whitelist, where נבנה מקבועים
                params,
            ).fetchall()
    except Exception as exc:
        logger.warning(
            "fetch_traded_quotes נכשל (expiry=%s as_of=%s): %s",
            expiry_date, as_of, exc, exc_info=True,
        )
        return {}

    def _deep_enough(units) -> bool:
        """מחזור מספיק כדי שנחשיב את הרגל סחירה."""
        if min_units <= 0:
            return True
        try:
            return float(units or 0) >= float(min_units)
        except (TypeError, ValueError):
            return False

    for r in rows:
        m = r._mapping
        strike = m.get("strike")
        if strike is None:
            continue
        try:
            k = float(strike)
        except (TypeError, ValueError):
            continue
        uc = m.get("overallturnoverunits_call")
        up = m.get("overallturnoverunits_put")
        c = vwap(uc, m.get("overallturnovervalue_shekel_call"))
        p = vwap(up, m.get("overallturnovervalue_shekel_put"))
        if c is not None and _deep_enough(uc):
            out[("Call", k)] = c
        if p is not None and _deep_enough(up):
            out[("Put", k)] = p

    if not out:
        logger.info(
            "fetch_traded_quotes: אין אף סטרייק שנסחר (expiry=%s as_of=%s טבלה=%s).",
            expiry_date, as_of if as_of is not None else "אחרון", source_table,
        )
    return out
