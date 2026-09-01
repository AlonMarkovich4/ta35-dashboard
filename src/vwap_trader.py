"""
vwap_trader.py — תיק תאום למסלול ההמלצות, ממולא במחירי עסקה אמיתיים.

**מה זה, ולמה בתיק נפרד**

תיק 8 ("המלצות המערכת") ממולא לפי `lastrate`, שאינו מחיר עסקה (HANDOFF 11.2).
המודול הזה פותח את **אותן המלצות בדיוק**, אבל ממלא ב-VWAP — מחיר עסקה משוקלל,
מאומת בתוך טווח הנסחר ב-100.0% מהמקרים.

התיק נפרד **בכוונה** ולא מחליף את תיק 8:
  • תיק 8 הוא track record רץ. שינוי שיטת התמחור באמצע היה שובר את ההשוואה.
  • התיק הזה יפתח **פחות** עסקאות — הוא מדלג כשאין מחיר עסקה לכל 4 הרגליים.
    נמדד 07/08/2026: 1 מתוך 4 המלצות. הדילוג הוא נתון, לא תקלה.
  • בעוד מספר חודשים ההשוואה ביניהם היא המדידה: כמה מהתוצאה של תיק 8 הייתה
    אמיתית וכמה הייתה מחיר מומצא.

**בידוד — אומת 07/08/2026**
  • `strategy_id = 103`. כל האגרגציות חוצות-התיקים (decision_validator,
    `web/src/lib/data.ts`) חסומות ב-`strategy_id BETWEEN 1 AND 6` ⇒ 103 שקוף להן.
  • kill-switch משלו (`VWAP_TRADING_ENABLED`), נפרד מ-`RECO_TRADING_ENABLED`.
  • אינו קורא לשום פונקציה שמשנה התנהגות בתיקים 2–8, ואינו כותב אליהם.

**דילוג הוא התנהגות תקינה.** עסקה שלא ניתן לתמחר במחיר עסקה אמיתי לא תיפתח —
זו כל מטרת התיק. הסיבה נרשמת בכל ריצה (ראה `_SKIP_*`).

API ציבורי:
  vwap_trading_enabled()                          -> bool
  get_vwap_portfolio_id(engine)                   -> int | None
  build_vwap_legs(rec_row)                        -> list[dict] | None   (טהור)
  max_loss_from_legs(legs, entry_cost)            -> float | None        (טהור)
  open_vwap_condor(expiry_date, ...)              -> dict
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import text

from paper_db import (
    _make_engine,
    get_portfolio,
    get_portfolios,
    get_trades,
    insert_trade,
)
from payoff import MULTIPLIER          # ₪ לנקודה — מקור אמת אחד
from trading_calendar import is_chain_fresh
from vwap_pricing import chain_asof, fetch_traded_quotes, price_legs

logger = logging.getLogger(__name__)

# שעון ישראל, כמו ב-`margin_recorder` — ולא UTC. ב-23:30 UTC כבר מחר בישראל,
# ושרשרת שנמשכה "היום" הייתה נראית בת יום. מקור אמת אחד לשאלה "מה התאריך".
TZ_IL = ZoneInfo("Asia/Jerusalem")


def _today_il() -> date:
    """התאריך בישראל. פונקציה נפרדת כדי שבדיקות יוכלו לקבע 'היום'."""
    return datetime.now(TZ_IL).date()

VWAP_ENGINE_VERSION = "margin-v1.1"
VWAP_STRATEGY_ID = 103
VWAP_STRATEGY_NAME = "Short Iron Condor (VWAP)"
VWAP_PORTFOLIO_NAME = "המלצות המערכת — תמחור VWAP"


class PortfolioSpec(NamedTuple):
    """הגדרת תיק. שני התיקים רצים על **אותו מסלול קוד** ונבדלים רק כאן.

    זה מכוון: ההבדל היחיד שרוצים למדוד הוא `min_units`, וקוד כפול היה
    נסחף עם הזמן והופך את ההשוואה לחסרת ערך.
    """
    portfolio_name: str
    strategy_id: int
    strategy_name: str
    env_flag: str
    min_units: float


#: תיק 9 — "נסחר בכלל". `min_units=0`.
VWAP_SPEC = PortfolioSpec(
    portfolio_name=VWAP_PORTFOLIO_NAME,
    strategy_id=VWAP_STRATEGY_ID,
    strategy_name=VWAP_STRATEGY_NAME,
    env_flag="VWAP_TRADING_ENABLED",
    min_units=0.0,
)

#: תיק 10 — "נסחר **בעומק**". הסף נקבע מהמדידה של 11/08/2026: ברגליים
#: 1–2 ימים לפקיעה ועד 4% מהכסף, חציון המחזור 128 יחידות ואחוזון 25 הוא 28.
#: 50 חותך את ה-34% הרזים ביותר ומשאיר רגל שבה פקודה אחת היא ≤2% מהמחזור.
LIQUIDITY_MIN_UNITS = 50.0
LIQUIDITY_SPEC = PortfolioSpec(
    portfolio_name="המלצות המערכת — סינון נזילות",
    strategy_id=104,
    strategy_name="Short Iron Condor (נזילות)",
    env_flag="LIQUIDITY_TRADING_ENABLED",
    min_units=LIQUIDITY_MIN_UNITS,
)

SPECS = {"vwap": VWAP_SPEC, "liquidity": LIQUIDITY_SPEC}

_SKIP_DISABLED = "VWAP_TRADING_ENABLED != 'true' (kill-switch כבוי)"
_SKIP_NO_PORTFOLIO = f"תיק '{VWAP_PORTFOLIO_NAME}' אינו קיים"
_SKIP_DUPLICATE = "כבר קיימת עסקה לפקיעה הזו בתיק"
_SKIP_NO_REC = "אין המלצה תקפה לפקיעה"
_SKIP_NO_STRIKES = "ההמלצה חסרה סטרייקים"


def trading_enabled(spec: PortfolioSpec = VWAP_SPEC) -> bool:
    """kill-switch לפי התיק. ברירת מחדל: כבוי.

    לכל תיק דגל משלו — הדלקת אחד אינה מדליקה את השני, וגם לא את תיק 8.
    """
    return os.getenv(spec.env_flag, "").strip().lower() == "true"


def vwap_trading_enabled() -> bool:
    """תאימות לאחור — ה-kill-switch של תיק 9."""
    return trading_enabled(VWAP_SPEC)


def get_portfolio_id(spec: PortfolioSpec = VWAP_SPEC, engine=None) -> int | None:
    """מזהה התיק לפי שמו. None אם טרם נוצר."""
    for p in get_portfolios(engine=engine) or []:
        if p.get("name") == spec.portfolio_name:
            return int(p["id"])
    return None


def get_vwap_portfolio_id(engine=None) -> int | None:
    """תאימות לאחור — מזהה תיק 9."""
    return get_portfolio_id(VWAP_SPEC, engine=engine)


def available_capital(portfolio_id: int, engine) -> float | None:
    """הון פנוי לפתיחת פוזיציה נוספת, בשקלים.

        הון פנוי = הון התחלתי + Σ P&L(סגורות) − Σ |max_loss|(פתוחות)

    **למה `max_loss` הוא הביטחונות.** בקונדור מוגדר-סיכון הברוקר מקפיא את
    ההפסד המרבי עד הפקיעה — לא את הקרדיט ולא את המרווח הנומינלי. פוזיציה
    פתוחה תופסת את הסכום הזה גם אם היא בכיוון הנכון.

    מחזיר None בכשל DB — והקורא **אינו פותח**. fail-safe: לא לדעת כמה הון
    יש אינו סיבה לפתוח, במיוחד בתיק שכל מטרתו לדמות אילוץ הון אמיתי.
    """
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT p.initial_balance,
                       COALESCE(SUM(t.pnl) FILTER (WHERE t.status = 'closed'), 0)
                           AS realized,
                       COALESCE(SUM(ABS(t.max_loss)) FILTER (WHERE t.status = 'open'), 0)
                           AS committed
                FROM paper_portfolios p
                LEFT JOIN paper_trades t ON t.portfolio_id = p.id
                WHERE p.id = :pid
                GROUP BY p.initial_balance
            """), {"pid": portfolio_id}).fetchone()
    except Exception as exc:
        logger.warning("available_capital נכשל (portfolio_id=%s): %s",
                       portfolio_id, exc, exc_info=True)
        return None
    if row is None:
        return None
    m = row._mapping
    return round(float(m["initial_balance"]) + float(m["realized"])
                 - float(m["committed"]), 2)


def _loads(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return {}
    return v or {}


def _as_float(v):
    """מספר JSON-native, או None.

    `margin_pct` חוזר מ-`margin_recommendations` כ-`Decimal`, ו-`paper_db._dumps`
    מסדר את ה-snapshot ב-`json.dumps` **בלי** `default` — בכוונה, כדי לא לשנות
    התנהגות לתיקים הקיימים. Decimal בתוך ה-snapshot מפיל את ה-INSERT.
    ה-payload חייב לצאת מכאן JSON-native; זה לא תפקידה של שכבת הכתיבה לנחש.
    """
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_vwap_legs(rec_row: dict) -> list[dict] | None:
    """בונה 4 רגליים מהסטרייקים של ההמלצה. **בלי מחירים** — הם יגיעו מ-VWAP.

    מחזיר None אם חסר ולו סטרייק אחד; המלצה חלקית אינה עסקה.
    הפורמט זהה ל-`strategy_legs_detail` כדי שמנגנון הסגירה הקיים
    (`paper_trading._payoff_from_legs`) יחשב P&L נכון בלי שינוי.
    """
    spec = [("קנה", "Put", "long_put_strike"), ("מכור", "Put", "short_put_strike"),
            ("מכור", "Call", "short_call_strike"), ("קנה", "Call", "long_call_strike")]
    legs: list[dict] = []
    for action, typ, key in spec:
        v = rec_row.get(key)
        if v is None:
            return None
        try:
            legs.append({"action": action, "type": typ, "strike": float(v), "qty": 1})
        except (TypeError, ValueError):
            return None
    return legs


def max_loss_from_legs(legs: list[dict], entry_cost: float) -> float | None:
    """ההפסד המרבי של הקונדור, מחושב **מהסטרייקים** ולא מההמלצה.

    רוחב הכנף נקבע ע"י הסטרייקים בלבד ואינו תלוי במחיר, ולכן:
        max_loss = רוחב_הכנף_הרחבה · MULTIPLIER + entry_cost
    (`entry_cost` שלילי בקרדיט, ולכן החיבור מקטין את ההפסד.)

    מחושב כאן ולא נלקח מההמלצה, כי ה-`max_loss` שם חושב על קרדיט של `lastrate`
    ואינו תקף לקרדיט של VWAP. מוחזר כערך **שלילי**, בקונבנציה של `paper_trades`.
    """
    puts = sorted(float(l["strike"]) for l in legs if l.get("type") == "Put")
    calls = sorted(float(l["strike"]) for l in legs if l.get("type") == "Call")
    if len(puts) != 2 or len(calls) != 2:
        return None
    width = max(puts[1] - puts[0], calls[1] - calls[0])
    if width <= 0:
        return None
    loss = width * MULTIPLIER + float(entry_cost)
    return -round(abs(loss), 2)


#: כל השדות ש-`paper_db.insert_trade` קושר. שדה חסר ⇒ הכתיבה נכשלת.
TRADE_FIELDS = frozenset({
    "portfolio_id", "strategy_id", "strategy_name", "expiry_date",
    "opened_at", "entry_index", "entry_cost", "legs_json",
    "max_profit", "max_loss", "status",
    "closed_at", "close_index", "pnl", "pnl_pct", "market_snapshot_json",
    "num_legs", "entry_commission", "exit_commission",
})


def build_vwap_trade(portfolio_id: int, expiry_date: str, legs: list[dict],
                     entry_cost: float, max_loss: float, entry_index,
                     commission_per_leg: float, snapshot: dict,
                     spec: PortfolioSpec = VWAP_SPEC) -> dict:
    """בונה את מילון העסקה. טהור — ללא DB, ללא זמן חיצוני פרט ל-`opened_at`.

    מחזיר את **הסט המלא** של `TRADE_FIELDS`, כולל שדות ה-NULL: `insert_trade`
    קושר את כולם, ושדה חסר נכשל ב-"A value is required for bind parameter".
    """
    return {
        "portfolio_id":         portfolio_id,
        "strategy_id":          spec.strategy_id,
        "strategy_name":        spec.strategy_name,
        "expiry_date":          expiry_date,
        # **רגע הפתיחה, לא `as_of`** — ה-snapshot הוא T-1 לפי מבנה הפיד, אבל
        # ההחלטה והכניסה קורות עכשיו. ערבוב השניים הוא מה שייצר
        # `expiry_date − opened_at` שלילי ב-132 העסקאות המשוחזרות (HANDOFF 0).
        "opened_at":            datetime.now(tz=timezone.utc),
        "entry_index":          entry_index,
        "entry_cost":           round(float(entry_cost), 2),
        "legs_json":            legs,
        "max_profit":           round(-float(entry_cost), 2) if entry_cost < 0 else 0.0,
        "max_loss":             max_loss,
        "status":               "open",
        "closed_at":            None,
        "close_index":          None,
        "pnl":                  None,
        "pnl_pct":              None,
        "market_snapshot_json": snapshot,
        "num_legs":             len(legs),
        "entry_commission":     round(len(legs) * float(commission_per_leg), 2),
        "exit_commission":      None,
    }


def _latest_recommendation(eng, expiry_date, today=None) -> dict | None:
    """ההמלצה של **היום** לפקיעה, בגרסת המנוע הרשמית בלבד. קריאה בלבד.

    ⚠️ הגבול `recommended_at::date = today` נוסף 01/09/2026. קודם היה כאן
    `ORDER BY recommended_at DESC LIMIT 1` בלי גבול תאריך — כלומר ההמלצה
    האחרונה שקיימת, גם אם היא בת ימים. הסטרייקים של קונדור נבחרים ביחס לרמת
    המדד של אותו יום, ולכן המלצה ישנה אינה "קצת פחות עדכנית" אלא מרווח אחר.

    הגבול קיים גם בבורר הפקיעות ב-`auto_open_vwap_trades.py`, ובכוונה בשני
    המקומות: התיקון בפונקציה מגן על **כל** קורא, כולל אוטומציה עתידית שלא
    תעבור דרך הסקריפט.
    """
    today = today or _today_il()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT margin_pct, recommendation_json
                    FROM margin_recommendations
                    WHERE expiry_date::date = CAST(:exp AS date)
                      AND engine_version = :ver
                      AND recommended_at::date = CAST(:today AS date)
                    ORDER BY recommended_at DESC
                    LIMIT 1
                """),
                {"exp": str(expiry_date)[:10], "ver": VWAP_ENGINE_VERSION,
                 "today": str(today)[:10]},
            ).fetchone()
    except Exception as exc:
        logger.warning("_latest_recommendation נכשל (%s): %s", expiry_date, exc,
                       exc_info=True)
        return None
    if row is None:
        return None
    rj = _loads(row._mapping.get("recommendation_json"))
    scr = _loads(rj.get("selected_curve_row"))
    if not scr:
        return None
    return {"margin_pct": row._mapping.get("margin_pct"), "curve_row": scr, "full": rj}


def open_vwap_condor(expiry_date, engine=None, portfolio_id: int | None = None,
                     as_of=None, dry_run: bool = True,
                     spec: PortfolioSpec = VWAP_SPEC) -> dict:
    """פותח קונדור בתיק ה-VWAP — **רק** אם כל 4 הרגליים נסחרו באמת.

    `as_of` — יום שרשרת מפורש, ל-backtest בלבד. **ברירת המחדל None = הצילום
    האחרון בטבלה החיה**, וזה הנכון בזמן אמת: `tase_putcall_history` נכתב בסוף
    המסחר, שעות אחרי שהפותחים רצים.
    `dry_run=True` (ברירת מחדל) מחשב הכל ואינו כותב כלום.
    """
    result: dict = {"expiry_date": str(expiry_date)[:10], "status": "skipped",
                    "reason": None, "trade": None, "missing": []}

    if not trading_enabled(spec):
        result["reason"] = f"{spec.env_flag} != 'true' (kill-switch כבוי)"
        return result

    eng = _make_engine(engine)
    if eng is None:
        result["reason"] = "אין חיבור ל-DB"
        return result

    pid = portfolio_id if portfolio_id is not None else get_portfolio_id(spec, eng)
    if pid is None:
        result["reason"] = f"תיק '{spec.portfolio_name}' אינו קיים"
        return result

    # דדופ — עסקה אחת לכל פקיעה בתיק הזה, בכל סטטוס.
    existing = get_trades(portfolio_id=pid, expiry_date=str(expiry_date)[:10], engine=eng)
    if existing:
        result["reason"] = _SKIP_DUPLICATE
        return result

    # תאריך אחד לכל הריצה. שתי קריאות נפרדות ל-`_today_il` יכולות ליפול משני
    # צדדיו של חצות ולתת תשובות סותרות — המלצה תיפסל כישנה בעוד השרשרת תיחשב
    # טרייה, או להפך.
    today = _today_il()

    rec = _latest_recommendation(eng, expiry_date, today=today)
    if rec is None:
        result["reason"] = _SKIP_NO_REC
        return result

    legs = build_vwap_legs(rec["curve_row"])
    if legs is None:
        result["reason"] = _SKIP_NO_STRIKES
        return result

    # `as_of=None` ⇒ הצילום האחרון בטבלה החיה. ראה את ההערה ב-`fetch_traded_quotes`:
    # הארכיון נכתב בסוף המסחר, שעות אחרי שהפותחים רצים.
    snap = chain_asof(eng)
    if snap is None:
        result["reason"] = "אין שרשרת כלל — לא נסחר, לא נדלג בשקט"
        logger.warning("vwap_trader: %s — אין שרשרת.", result["expiry_date"])
        return result
    result["chain"] = snap

    # ─── שער טריות ────────────────────────────────────────────────────
    # ⚠️ נוסף 01/09/2026. **המודול הזה נכתב אחרי שהשער כבר קיים במקומות
    # האחרים** (`margin_recorder:212`, `auto_open_benchmark_trades:160`,
    # שנוספו בעקבות תשעה באב 23/07) — ופשוט לא קיבל אותו. תיקים 9 ו-10 היו
    # היחידים שיכלו לפתוח על שרשרת בת ימים.
    #
    # למה זה לא התפוצץ עד שהתגלה: כל עוד האוסף עובד `fetch_date == today`
    # ממילא. השער נדרש בדיוק ביום שבו האוסף נופל — 01/09/2026, שבו
    # `tase_putcall` נשארה קפואה על 31/08 17:16 (trade_date 28/08).
    #
    # **חייב להיות כאן, לפני `fetch_traded_quotes`.** באותו יום התמחור נכשל
    # ממילא ("4/4 רגליים ללא מחיר") ולכן לא נפתחה עסקה — אבל זה `priced.complete`,
    # שהוא **הסתברות ולא שער**. ביום שבו שרשרת ישנה כן תתמחר במלואה, הייתה
    # נפתחת פוזיציה על מחירים בני ימים. בדיקה נועלת שאין פנייה לתמחור כאן.
    if not is_chain_fresh(snap.get("fetch_date"), today):
        result["reason"] = (
            f"שרשרת אינה טרייה — נמשכה {snap.get('fetch_date')} "
            f"{snap.get('fetch_time') or ''} (trade_date {snap.get('trade_date')}), "
            f"היום {today}. לא נפתחת עסקה."
        )
        # ERROR ולא INFO: ביום מסחר תקין קיימת משיכה של אותו יום. הגעה לכאן
        # פירושה שהאוסף לא עבד — תקלה, לא דילוג שגרתי.
        logger.error("vwap_trader: %s — %s", result["expiry_date"], result["reason"])
        return result

    quotes = fetch_traded_quotes(expiry_date, as_of, eng,
                                 min_units=spec.min_units)
    priced = price_legs(legs, quotes)

    if not priced.complete:
        result["missing"] = priced.missing
        # ⚠️ הסיבה חייבת לנקוב **בצילום** ולא רק במספר הרגליים. "4/4 ללא מחיר"
        # נקרא כמו ממצא נזילות, בעוד שהוא עלול להיות היעדר נתונים לגמרי —
        # וזה בדיוק ההבדל שהפרויקט הזה כבר שילם עליו (סעיף 10, לקח 1).
        result["reason"] = (
            f"{len(priced.missing)}/{len(legs)} רגליים ללא מחיר עסקה · "
            f"שרשרת {snap['fetch_date']} {snap.get('fetch_time') or ''} "
            f"(trade_date {snap.get('trade_date')}) · {len(quotes)} סטרייקים עברו "
            f"את הסף (min_units={spec.min_units:g})"
        )
        logger.info("vwap_trader: %s דילוג — %s", result["expiry_date"], result["reason"])
        return result

    max_loss = max_loss_from_legs(priced.legs, priced.entry_cost)
    if max_loss is None:
        result["reason"] = "לא ניתן לחשב max_loss מהסטרייקים"
        return result

    # ─── שער הון ──────────────────────────────────────────────────────
    # תיק עם 20,000 ₪ שפותח פוזיציה חמישית בלי לבדוק ביטחונות אינו מדמה
    # מציאות. הבדיקה נכונה לכל תיק; בתיק עם 100,000 היא פשוט לא תיגע.
    avail = available_capital(pid, eng)
    need = abs(float(max_loss))
    if avail is None:
        result["reason"] = "לא ניתן לחשב הון פנוי — לא נפתחת פוזיציה"
        logger.warning("vwap_trader: %s — %s", result["expiry_date"], result["reason"])
        return result
    if need > avail:
        result["capital"] = {"available": avail, "required": need}
        result["reason"] = (f"אין הון פנוי — נדרשים {need:,.0f} ₪ ביטחונות "
                            f"ופנויים {avail:,.0f} ₪")
        logger.info("vwap_trader: %s דילוג — %s", result["expiry_date"], result["reason"])
        return result

    portfolio = get_portfolio(pid, engine=eng) or {}
    cpl = portfolio.get("commission_per_leg")
    commission_per_leg = float(cpl if cpl is not None else 2.5)

    # ⚠️ `insert_trade` מחייב את **כל** 19 השדות כפרמטרי bind, כולל אלה שמותר
    # להם להיות NULL. שדה חסר נכשל ב-"A value is required for bind parameter".
    # `build_vwap_trade` מוודא את הסט המלא, ויש בדיקה שנועלת אותו.
    trade = build_vwap_trade(
        portfolio_id=pid,
        expiry_date=str(expiry_date)[:10],
        legs=priced.legs,
        entry_cost=priced.entry_cost,
        max_loss=max_loss,
        entry_index=_as_float(rec["curve_row"].get("base_index")),
        commission_per_leg=commission_per_leg,
        spec=spec,
        snapshot={
            "source": "vwap_trader",
            "price_source": "vwap",
            # הצילום שממנו נלקחו המחירים בפועל — לא "היום". בלי זה אי אפשר
            # לשחזר בדיעבד על מה העסקה נפתחה.
            "chain_fetch_date": snap["fetch_date"],
            "chain_fetch_time": snap.get("fetch_time"),
            "chain_trade_date": snap.get("trade_date"),
            "engine_version": VWAP_ENGINE_VERSION,
            "margin_pct": _as_float(rec["margin_pct"]),
            "tradeable_strikes": len(quotes),
            "min_units": spec.min_units,
            "capital_available_before": avail,
            "collateral_required": need,
            # הקרדיט לפי lastrate, לשם ההשוואה שבגללה התיק קיים.
            "net_premium_lastrate": _as_float(rec["curve_row"].get("net_premium")),
        },
    )
    result["trade"] = trade

    if dry_run:
        result["status"] = "dry-run"
        result["reason"] = "dry-run — לא נכתב"
        return result

    inserted = insert_trade(trade, engine=eng)
    if not inserted:
        result["status"] = "error"
        result["reason"] = "insert_trade נכשל"
        return result
    result["status"] = "opened"
    result["trade"] = inserted
    logger.info("vwap_trader: נפתחה עסקה לפקיעה %s (קרדיט %.2f ₪).",
                result["expiry_date"], -priced.entry_cost)
    return result
