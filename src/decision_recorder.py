"""
decision_recorder.py — גשר תיעוד החלטות (Layer 1, שלב B1).

מריץ את מנוע ההחלטה (build_expiry_decision) על כל פקיעה קרובה ושומר את התוצאה
ב-decision_log (append-only). מטרה: להתחיל לצבור החלטות כדי שבעתיד נוכל למדוד
אם המנוע צודק (decision מול P&L בפועל).

מודול טהור-לוגיקה לשימוש חוזר: גם ה-UI (דף 6) וגם סקריפט/GitHub Action עתידי
קוראים לאותה record_decisions_for_upcoming() — אין כאן שום קוד Streamlit.

הקלט זהה למנוע בדף 6 (_current_decision / _detect_next_expiry):
  • load_from_db            — היסטוריית הפקיעות (move_pct) ממסד הנתונים.
  • get_available_expiries  — הפקיעות הזמינות בשרשרת (tase_putcall).
  • get_latest_option_chain — לזיהוי סוג הפקיעה (W/M) מתוך expiry_type.
  • get_recent_move         — תנועת הפקיעה הקודמת (לקלט build_expiry_decision).
  • compute_risk_score      — ציון סיכון מאירועים (אופציונלי).
ואז insert_decision_log שומר, עם מניעת כפילויות (decision_logged_today).

before_date: לא נשלח (=None). הפקיעות כאן הן *עתידיות/חיות* (>= היום), ולכן כל
ההיסטוריה לגיטימית — אין זליגת-עתיד (zero-lookahead שמור ממילא). זהה בדיוק
ל-_current_decision בדף 6. before_date רלוונטי רק ל-backtest על פקיעות שכבר קרו.
"""
from __future__ import annotations

import logging

import pandas as pd

from context_analyzer import build_expiry_decision, get_recent_move
from data_loader import load_from_db
from paper_db import _make_engine, decision_logged_today, insert_decision_log
from supabase_loader import get_available_expiries, get_latest_option_chain

try:
    from events import compute_risk_score
    _HAS_EVENTS = True
except Exception:  # noqa: BLE001
    _HAS_EVENTS = False

logger = logging.getLogger(__name__)


def _detect_expiry_type(expiry_str: str, engine) -> str:
    """מזהה סוג פקיעה (W/M) מתוך שרשרת האופציות — זהה ללוגיקת דף 6.

    expiry_type בשרשרת מגיע בעברית ("שבועי"/"חודשי"); אם מכיל "חודשי" → 'M',
    אחרת 'W'. fallback ל-'W' אם אין שרשרת/שגיאה.
    """
    try:
        chain = get_latest_option_chain(expiry_str, engine=engine)
        ent = (chain or {}).get("expiries", [{}])[0]
        return "M" if "חודשי" in str(ent.get("expiry_type", "")) else "W"
    except Exception:  # noqa: BLE001
        return "W"


def _upcoming_expiries(engine) -> list[pd.Timestamp]:
    """כל הפקיעות הזמינות בשרשרת שתאריכן >= היום, ממוינות עולה (Timestamp)."""
    today = pd.Timestamp.today().normalize()
    try:
        raw = get_available_expiries(engine=engine) or []
    except Exception:  # noqa: BLE001
        logger.warning("_upcoming_expiries: get_available_expiries נכשל.", exc_info=True)
        raw = []
    parsed = sorted(pd.Timestamp(e) for e in raw)
    return [d for d in parsed if d >= today]


def record_decisions_for_upcoming(
    engine=None,
    trigger: str = "manual",
    engine_version: str = "layer1-v1",
) -> list[dict]:
    """מריץ את מנוע ההחלטה על כל פקיעה קרובה ומתעד ל-decision_log.

    לכל פקיעה קרובה (>= היום) ב-tase_putcall:
      1. מזהה סוג (W/M) מהשרשרת (_detect_expiry_type).
      2. מניעת כפילות: אם כבר תועד היום לאותה גרסה (decision_logged_today) — דילוג.
      3. בונה df היסטורי משותף (load_from_db, מסונן ל-move_pct לא-ריק) — כמו דף 6.
      4. build_expiry_decision(before_date=None) → insert_decision_log.

    מחזיר רשימת סיכומים, אחד לכל פקיעה קרובה:
      {expiry_date, expiry_type, top_strategy_id, regime, status, log_id}
      status ∈ {"recorded", "skipped_exists", "error"}.

    שימוש חוזר: ה-UI קורא עם trigger="manual"; GitHub Action עתידי יקרא עם
    trigger="scheduled" — אותה לוגיקה בדיוק.
    """
    eng = _make_engine(engine)
    results: list[dict] = []
    if eng is None:
        logger.warning("record_decisions_for_upcoming: אין engine (DATABASE_URL לא מוגדר).")
        return results

    # היסטוריה נטענת פעם אחת ומשותפת לכל הפקיעות (כמו דף 6).
    try:
        df = load_from_db(eng)
        df = df[df["move_pct"].notna()].copy()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "record_decisions_for_upcoming: טעינת היסטוריה נכשלה: %s", exc, exc_info=True,
        )
        return results

    for nxt in _upcoming_expiries(eng):
        exp_date = nxt.date()
        rec = {
            "expiry_date":     str(exp_date),
            "expiry_type":     None,
            "top_strategy_id": None,
            "regime":          None,
            "status":          "error",
            "log_id":          None,
        }
        try:
            etype = _detect_expiry_type(nxt.strftime("%Y-%m-%d"), eng)
            rec["expiry_type"] = etype

            # מניעת כפילות לפני העבודה היקרה (build_expiry_decision).
            if decision_logged_today(exp_date, engine_version=engine_version, engine=eng):
                rec["status"] = "skipped_exists"
                results.append(rec)
                continue

            recent = get_recent_move(df, nxt)
            risk = None
            if _HAS_EVENTS:
                try:
                    risk = compute_risk_score(exp_date, eng, df).get("score")
                except Exception:  # noqa: BLE001
                    risk = None

            decision = build_expiry_decision(
                df, etype, int(nxt.month), nxt,
                recent_move_pct=recent, risk_score=risk,
            )
            rec["top_strategy_id"] = decision.get("top_strategy_id")
            rec["regime"] = (decision.get("regime") or {}).get("regime")

            log_id = insert_decision_log(
                decision, trigger=trigger, engine_version=engine_version, engine=eng,
            )
            if log_id is not None:
                rec["status"] = "recorded"
                rec["log_id"] = log_id
            else:
                rec["status"] = "error"  # insert_decision_log החזיר None (כשל DB)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "record_decisions_for_upcoming נכשל לפקיעה %s: %s",
                exp_date, exc, exc_info=True,
            )
            rec["status"] = "error"
        results.append(rec)

    return results
