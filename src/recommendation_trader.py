"""
recommendation_trader.py — גשר 3 (גרסה בטוחה): פתיחת Iron Condor אוטומטית לפי המלצת המרווח.

מודול טהור-לוגיקה. **הפעם הראשונה שקוד פותח עסקה אוטומטית** (בדמו בלבד) — לכן זהירות מרבית:

  • kill-switch: RECO_TRADING_ENABLED חייב להיות "true" (ברירת מחדל: כבוי → לא פותח כלום).
  • דדופ: עסקה אחת לכל פקיעה בתיק ההמלצות (open או closed → דילוג).
  • העסקה נפתחת עם ה-strikes **המדויקים מההמלצה** (recommendation_json), לא עם ברירות המחדל
    של payoff.py. 4 רגליים בפורמט של strategy_legs_detail (כדי שמנגנון הסגירה הקיים יחשב P&L
    נכון), entry_cost = −פרמיה (זיכוי), max_loss מההמלצה.
  • strategy_id ייעודי (RECO_STRATEGY_ID=102, מחוץ ל-1–6) — כדי לא לזהם את decision_validator
    שמצרף P&L לפי strategy_id על פני תיקים. ראה ההערה למטה.

זהות מול מנגנון הסגירה (paper_trading.close_trades_for_expiry): P&L = payoff_from_legs(strikes)
− entry_cost − עמלות. הרגליים נבנות עם action="קנה"/"מכור" + type="Call"/"Put" + strike, בדיוק
כמו strategy_legs_detail — כך שהחישוב בסגירה נכון. מחירי הרגליים הבודדים אינם נשמרים בהמלצה
(רק הזיכוי הכולל) ולכן price_pts=0 (תצוגה בלבד; אינו משפיע על ה-P&L).

⚠️ אינטראקציה ידועה — decision_validator: הוא מצרף paper_trades לפי (expiry, strategy_id) על פני
כל התיקים. strategy_id=102 לא מזהם את SUM של אסטרטגיה 2, אך *כן* יופיע כאופציה נוספת בחישוב
ה-best/hit הפר-פקיעתי שלו כשעסקאות ההמלצות ייסגרו. מומלץ, לפני הדלקת ה-kill-switch, להוסיף
ל-decision_validator._fetch_closed_pnl סינון strategy_id BETWEEN 1 AND 6 (מגן על ה-benchmark,
לא נוגע ב-6 התיקים). לא מיושם כאן — ה-kill-switch כבוי, אין עדיין עסקאות.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from paper_db import (
    _make_engine,
    get_portfolio,
    get_portfolios,
    get_trades,
    insert_trade,
)

logger = logging.getLogger(__name__)

RECO_ENGINE_VERSION = "margin-v1.1"          # אך ורק הגרסה הרשמית (v1 שגוי).
RECO_STRATEGY_ID = 102                        # ייעודי, מחוץ ל-1–6 (בידוד מ-decision_validator).
RECO_STRATEGY_NAME = "Short Iron Condor (המלצת מרווח)"
RECO_PORTFOLIO_NAME = "המלצות המערכת — Iron Condor"


# ─── kill-switch + פתרון תיק ─────────────────────────────────────────────

def reco_trading_enabled() -> bool:
    """ה-kill-switch: פותח עסקאות רק אם RECO_TRADING_ENABLED == 'true' (ברירת מחדל: כבוי)."""
    return os.getenv("RECO_TRADING_ENABLED", "").strip().lower() == "true"


def get_reco_portfolio_id(engine=None) -> int | None:
    """מזהה תיק ההמלצות לפי שם (RECO_PORTFOLIO_NAME); None אם לא קיים (יש ליצור אותו קודם)."""
    for p in get_portfolios(engine):
        if p.get("name") == RECO_PORTFOLIO_NAME:
            return int(p["id"])
    return None


# ─── קריאת ההמלצה + בניית הרגליים (טהור) ─────────────────────────────────

def _as_date(v):
    """מנרמל expiry_date ל-datetime.date; None אם לא-פריק."""
    try:
        return pd.Timestamp(str(v)).date()
    except Exception:  # noqa: BLE001
        return None


def _today():
    """התאריך של היום (UTC) — עטוף בפונקציה כדי שבדיקות יוכלו למקק אותו. ה-Action רץ בצהריים
    (שעון ישראל UTC+3), כך שתאריך ה-UTC בצהריים זהה לתאריך המקומי."""
    return datetime.now(tz=timezone.utc).date()


def _loads(v):
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _fetch_latest_recommendation(eng, exp_dt) -> dict | None:
    """ההמלצה האחרונה (MAX recommended_at) לפקיעה, גרסה margin-v1.1. קריאה בלבד; None אם אין."""
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT expiry_date, recommended_at, margin_pct, hold_blended, premium_ils,
                           short_put_strike, short_call_strike, recommendation_json
                    FROM margin_recommendations
                    WHERE engine_version = :ver AND expiry_date = :exp
                    ORDER BY recommended_at DESC
                    LIMIT 1
                """),
                {"ver": RECO_ENGINE_VERSION, "exp": exp_dt},
            ).fetchone()
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_latest_recommendation נכשל (%s): %s", exp_dt, exc, exc_info=True)
        return None
    if row is None:
        return None
    m = row._mapping
    rj = _loads(m.get("recommendation_json"))
    scr = rj.get("selected_curve_row") or {}
    num = lambda a, b=None: (float(a) if a is not None else (float(b) if b is not None else None))  # noqa: E731
    return {
        "expiry_date":       _as_date(m.get("expiry_date")),
        "recommended_at":    m.get("recommended_at"),
        "margin_pct":        num(m.get("margin_pct")),
        "hold_blended":      num(m.get("hold_blended")),
        "premium_ils":       num(m.get("premium_ils")),
        "short_put_strike":  num(m.get("short_put_strike"), scr.get("short_put_strike")),
        "short_call_strike": num(m.get("short_call_strike"), scr.get("short_call_strike")),
        "long_put_strike":   num(rj.get("long_put_strike"), scr.get("long_put_strike")),
        "long_call_strike":  num(rj.get("long_call_strike"), scr.get("long_call_strike")),
        "max_loss":          num(rj.get("max_loss"), scr.get("max_loss")),
        "base_index":        num(rj.get("base_index"), scr.get("base_index")),
        "wing_pct":          num(rj.get("wing_pct"), scr.get("wing_pct")),
    }


def _reco_legs(rec: dict) -> list[dict] | None:
    """4 רגלי ה-condor בפורמט strategy_legs_detail, מה-strikes של ההמלצה. None אם חסרות רגליים
    (המלצה ישנה בלי long strikes) → אין עסקה. price_pts=0 (לא נשמר בהמלצה; תצוגה בלבד)."""
    lp, sp = rec.get("long_put_strike"), rec.get("short_put_strike")
    sc, lc = rec.get("short_call_strike"), rec.get("long_call_strike")
    if any(v is None for v in (lp, sp, sc, lc)):
        return None

    def leg(action: str, typ: str, strike: float) -> dict:
        return {"action": action, "type": typ, "qty": 1,
                "strike": float(strike), "price_pts": 0.0, "price_nis": 0.0}

    return [
        leg("קנה",  "Put",  lp),   # long put (הגנה תחתונה)
        leg("מכור", "Put",  sp),   # short put (מכור)
        leg("מכור", "Call", sc),   # short call (מכור)
        leg("קנה",  "Call", lc),   # long call (הגנה עליונה)
    ]


def _snapshot(rec: dict) -> dict:
    """market_snapshot_json — פרובננס מלא של ההמלצה (מסלול C, דאטה לעתיד)."""
    ra = rec.get("recommended_at")
    return {
        "source":          "margin_recommendation",
        "engine_version":  RECO_ENGINE_VERSION,
        "margin_pct":      rec.get("margin_pct"),
        "wing_pct":        rec.get("wing_pct"),
        "hold_blended":    rec.get("hold_blended"),
        "base_index":      rec.get("base_index"),
        "net_premium":     rec.get("premium_ils"),
        "max_loss":        rec.get("max_loss"),
        "recommended_at":  str(ra) if ra is not None else None,
        "strikes": {
            "long_put":   rec.get("long_put_strike"),
            "short_put":  rec.get("short_put_strike"),
            "short_call": rec.get("short_call_strike"),
            "long_call":  rec.get("long_call_strike"),
        },
        "note": "עסקה נפתחה אוטומטית לפי המלצת המרווח (Bridge 3, shadow — דמו בלבד).",
    }


def build_reco_trade(portfolio_id: int, rec: dict, legs: list[dict],
                     commission_per_leg: float) -> dict:
    """בונה את מילון העסקה (open) מההמלצה — טהור, ללא כתיבה. משמש גם את open_recommended_condor
    וגם את ה-dry-run. entry_cost = −פרמיה (זיכוי), max_loss מההמלצה, strategy_id ייעודי."""
    premium = float(rec["premium_ils"])
    base_index = rec.get("base_index")
    max_loss = rec.get("max_loss")
    return {
        "portfolio_id":         portfolio_id,
        "strategy_id":          RECO_STRATEGY_ID,
        "strategy_name":        RECO_STRATEGY_NAME,
        "expiry_date":          rec["expiry_date"],
        "opened_at":            datetime.now(tz=timezone.utc),
        "entry_index":          round(float(base_index), 2) if base_index is not None else None,
        "entry_cost":           round(-premium, 2),          # זיכוי שהתקבל (שלילי)
        "legs_json":            legs,
        "max_profit":           round(premium, 2),           # רווח מקס גולמי = הפרמיה
        "max_loss":             round(float(max_loss), 2) if max_loss is not None else None,
        "status":               "open",
        "closed_at":            None,
        "close_index":          None,
        "pnl":                  None,
        "pnl_pct":              None,
        "market_snapshot_json": _snapshot(rec),
        "num_legs":             len(legs),
        "entry_commission":     round(len(legs) * commission_per_leg, 2),
        "exit_commission":      None,
    }


# ─── הפתיחה הראשית ────────────────────────────────────────────────────────

def open_recommended_condor(expiry_date, engine=None, portfolio_id: int | None = None,
                            min_days_to_expiry: int = 1) -> dict:
    """פותח Short Iron Condor בתיק ההמלצות לפי ההמלצה האחרונה לפקיעה.

    שרשרת ההגנות: kill-switch → engine/portfolio → מרחק-לפקיעה → דדופ → המלצה → רגליים → פרמיה → INSERT.
    מחזיר {status, reason, expiry_date, trade_id?, ...}:
      status ∈ {"opened", "duplicate", "skipped", "db_error", "error"}.
      "skipped": kill-switch כבוי / פקיעה קרובה מדי / אין המלצה / המלצה ישנה בלי רגליים / אין פרמיה חיובית.

    min_days_to_expiry (ברירת מחדל 1): מספר הימים המינימלי שנדרש עד הפקיעה כדי לפתוח. עם 1 —
    פקיעת אותו-יום (0 ימים) מדולגת, ופקיעת מחר (יום 1) עדיין נפתחת. 2 ידלג גם על מחר.
    """
    result: dict = {"expiry_date": str(expiry_date), "status": "error", "reason": None, "trade_id": None}

    # 1. kill-switch — לפני כל גישה ל-DB.
    if not reco_trading_enabled():
        result.update(status="skipped", reason="RECO_TRADING_ENABLED != 'true' (kill-switch כבוי)")
        return result

    eng = _make_engine(engine)
    if eng is None:
        result.update(reason="אין engine (DATABASE_URL לא מוגדר)")
        return result
    if portfolio_id is None:
        result.update(reason="portfolio_id חסר")
        return result

    exp_dt = _as_date(expiry_date)
    if exp_dt is None:
        result.update(reason=f"expiry_date לא תקין: {expiry_date!r}")
        return result

    # שער מרחק-לפקיעה (טהור, לפני DB): לא פותחים על פקיעה קרובה מדי. ברירת מחדל — מדלג על
    # פקיעת אותו-יום (days<1); פקיעת מחר עדיין נפתחת (הפרש להתנהגות ה-dry-run, שהריץ רק >= היום).
    days_to_expiry = (exp_dt - _today()).days
    if days_to_expiry < min_days_to_expiry:
        result.update(status="skipped",
                      reason=f"פקיעה קרובה מדי (נותרו {days_to_expiry} ימים, נדרש ≥ {min_days_to_expiry})")
        return result

    try:
        # 2. דדופ — עסקה אחת לפקיעה בתיק (open או closed → דילוג).
        existing = get_trades(portfolio_id=portfolio_id, expiry_date=str(exp_dt), engine=eng)
        if any(t.get("status") in ("open", "closed") for t in existing):
            result.update(status="duplicate", reason="כבר קיימת עסקה לפקיעה זו בתיק")
            return result

        # 3. ההמלצה + הרגליים.
        rec = _fetch_latest_recommendation(eng, exp_dt)
        if rec is None:
            result.update(status="skipped", reason="אין המלצה לפקיעה")
            return result
        legs = _reco_legs(rec)
        if legs is None:
            result.update(status="skipped", reason="להמלצה אין 4 רגליים מלאות (המלצה ישנה)")
            return result
        premium = rec.get("premium_ils")
        if premium is None or premium <= 0:
            result.update(status="skipped", reason="להמלצה אין פרמיה חיובית")
            return result

        # 4. בניית העסקה + INSERT דרך המנגנון הקיים.
        portfolio = get_portfolio(portfolio_id, engine=eng)
        _cpv = (portfolio or {}).get("commission_per_leg")
        commission_per_leg = float(_cpv if _cpv is not None else 2.5)
        trade = build_reco_trade(portfolio_id, rec, legs, commission_per_leg)

        inserted = insert_trade(trade, engine=eng)
        if inserted is None:
            result.update(status="db_error", reason="insert_trade החזיר None (כשל DB)")
            return result

        result.update(
            status="opened", reason=None, trade_id=inserted.get("id"),
            margin_pct=rec.get("margin_pct"), premium=premium, max_loss=rec.get("max_loss"),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("open_recommended_condor נכשל (%s): %s", exp_dt, exc, exc_info=True)
        result.update(status="error", reason=str(exc))
        return result
