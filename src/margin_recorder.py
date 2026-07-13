"""
margin_recorder.py — גשר תיעוד המלצות המרווח (שלב 4, חלק ב).

מריץ את מנגנון המרווח האופטימלי (שלב 1–3) על כל פקיעה קרובה ושומר את ההמלצה
ב-margin_recommendations (append-only). מטרה זהה ל-decision_recorder: לצבור המלצות
*לפני* הפקיעה כדי שבעתיד נמדוד אם המנוע צדק (ההמלצה מול התנועה בפועל — שלב 4, חלק ג).

מודול טהור-לוגיקה לשימוש חוזר (אפס Streamlit): גם ה-UI וגם סקריפט/Action עתידי
קוראים לאותה record_margin_recommendations_for_upcoming().

הליבה הקריאה-בלבד — _recommendation_for_expiry — אינה כותבת דבר: היא מושכת שרשרת
(tase_putcall) + היסטוריה (expiry_history), בונה margin_curve (שלב 1) ומריצה
select_margin (שלב 3, floor=0.97 — ברירת המחדל הנעולה). לכן אותו קוד משמש גם את
ה-dry-run (שמראה מה *היה* נרשם, בלי לכתוב) וגם את הרשם האמיתי (שמוסיף דדופ + INSERT).

before_date: לא נשלח (=None). הפקיעות כאן *חיות* (>= היום) ולכן כל ההיסטוריה
לגיטימית — אין זליגת-עתיד. זהה בדיוק ל-decision_recorder (before_date רלוונטי רק
ל-backtest על פקיעות עבר).
"""
from __future__ import annotations

import logging

import pandas as pd

from context_analyzer import get_recent_move
from data_loader import load_from_db
from margin_calculator import DEFAULT_WING_PCT, build_margin_curve
from margin_selector import DEFAULT_HOLD_FLOOR, select_margin
from options_parser import find_atm
from paper_db import (
    _make_engine,
    insert_margin_recommendation,
    margin_recommendation_logged_today,
)
from supabase_loader import get_available_expiries, get_latest_option_chain

logger = logging.getLogger(__name__)


def _norm_expiry_type(raw) -> str:
    """מנרמל את סוג הפקיעה מהשרשרת (עברית) ל-'W'/'M' — כמו decision_recorder._detect_expiry_type.

    get_latest_option_chain מחזיר expiry_type בעברית ("שבועי"/"חודשי"); select_margin
    מסנן היסטוריה רק על 'W'/'M' (ערך אחר → ללא סינון סוג). לכן חובה לנרמל כאן, אחרת
    ההתניה על סוג הפקיעה מושבתת בשקט.
    """
    return "M" if "חודשי" in str(raw or "") else "W"


def _upcoming_expiries(engine) -> list[pd.Timestamp]:
    """כל הפקיעות הזמינות בשרשרת שתאריכן >= היום, ממוינות עולה (זהה ל-decision_recorder)."""
    today = pd.Timestamp.today().normalize()
    try:
        raw = get_available_expiries(engine=engine) or []
    except Exception:  # noqa: BLE001
        logger.warning("_upcoming_expiries: get_available_expiries נכשל.", exc_info=True)
        raw = []
    parsed = sorted(pd.Timestamp(e) for e in raw)
    return [d for d in parsed if d >= today]


def _recommendation_for_expiry(
    df_hist: pd.DataFrame,
    exp_ts: pd.Timestamp,
    engine,
    hold_floor: float = DEFAULT_HOLD_FLOOR,
    wing_pct: float = DEFAULT_WING_PCT,
    engine_version: str = "margin-v1",
    trigger: str = "manual",
) -> dict | None:
    """בונה את המלצת המרווח לפקיעה נתונה — הליבה **הקריאה-בלבד** (אפס כתיבה ל-DB).

    שלבים:
      1. שרשרת הפקיעה (get_latest_option_chain) → chain_df + ATM (find_atm) → base_index.
      2. סוג הפקיעה מנורמל ל-'W'/'M' (_norm_expiry_type).
      3. עקומת המרווח (build_margin_curve, שלב 1) על ה-strikes האמיתיים, ברוחב כנף wing_pct
         (ברירת מחדל DEFAULT_WING_PCT=0.75% — הכנף הרשמית מסריקת הכנפיים). כל השדות הנגזרים
         (max_loss, breakevens, פרמיה) מחושבים מהכנף שהועברה, וה-wing_pct נשמר ב-rec.
      4. select_margin (שלב 3, hold_floor הנעול) עם before_date=None (פקיעה חיה).
      5. הרכבת ה-rec: שדות הבחירה + hold מותנה/גלובלי/n מהשורה הנבחרת ב-grid, ו-strikes
         מהשורה המתאימה בעקומה. grid + selected_curve_row המלאים נשמרים לשקיפות ולשחזור
         P&L בולידציה.

    מחזיר None אם אין שרשרת מלאה / ATM / מרווח תקין (הרשם ידווח no_recommendation).
    אינו כותב דבר — נשען רק על SELECT (שרשרת + היסטוריה כבר בזיכרון).
    """
    exp_str = exp_ts.strftime("%Y-%m-%d")
    chain = get_latest_option_chain(exp_str, engine=engine)
    entries = (chain or {}).get("expiries") or []
    entry = entries[0] if entries else {}
    chain_df = entry.get("chain")
    if chain_df is None or len(chain_df) == 0:
        return None

    atm = find_atm(chain_df)
    if not atm:
        return None
    base_index = float(atm.get("index_estimate", atm.get("strike")))
    etype = _norm_expiry_type(entry.get("expiry_type"))

    curve = build_margin_curve(chain_df, base_index, wing_pct=wing_pct)
    recent = get_recent_move(df_hist, exp_ts)
    sel = select_margin(curve, df_hist, etype, recent, hold_floor=hold_floor)

    sm = sel.get("selected_margin")
    if sm is None:
        return None

    # שורת ה-grid הנבחרת (hold מותנה/גלובלי/n) ושורת העקומה הנבחרת (strikes).
    grow = next((g for g in sel.get("grid", [])
                 if round(float(g["margin_pct"]), 4) == round(float(sm), 4)), {})
    crow = next((r for r in curve if not r.get("skipped")
                 and round(float(r["margin_pct"]), 4) == round(float(sm), 4)), {})

    return {
        "expiry_date":        exp_ts.date(),
        "expiry_type":        etype,
        "as_of_date":         (chain or {}).get("as_of_date", ""),
        "base_index":         base_index,
        "recent_move_pct":    recent,
        "selected_margin":    sm,
        "hold_blended":       sel.get("hold_blended"),
        "hold_conditional":   grow.get("hold_conditional"),
        "hold_global":        grow.get("hold_global"),
        "n_conditional":      grow.get("n_conditional"),
        "w_effective":        grow.get("w_effective"),
        "net_premium":        sel.get("net_premium"),
        "max_loss":           sel.get("max_loss"),
        "ev":                 sel.get("ev"),
        "short_put_strike":   crow.get("short_put_strike"),
        "short_call_strike":  crow.get("short_call_strike"),
        "long_put_strike":    crow.get("long_put_strike"),
        "long_call_strike":   crow.get("long_call_strike"),
        "credit_pts":         crow.get("credit_pts"),
        "below_floor":        sel.get("below_floor"),
        "hold_floor":         sel.get("hold_floor"),
        "wing_pct":           wing_pct,          # הכנף שהונחה (שקיפות — נשמר ב-recommendation_json)
        "reason":             sel.get("reason"),
        "grid":               sel.get("grid"),
        "selected_curve_row": crow,       # לשחזור margin_pnl בולידציה (שלב 4, חלק ג)
        "engine_version":     engine_version,
        "trigger":            trigger,
    }


def record_margin_recommendations_for_upcoming(
    engine=None,
    trigger: str = "manual",
    engine_version: str = "margin-v1",
    wing_pct: float = DEFAULT_WING_PCT,
) -> list[dict]:
    """מריץ את מנגנון המרווח על כל פקיעה קרובה ומתעד ל-margin_recommendations (append-only).

    לכל פקיעה קרובה (>= היום) עם שרשרת ב-tase_putcall:
      1. דדופ יומי (margin_recommendation_logged_today) — אם כבר תועד היום לאותה גרסה, דילוג
         *לפני* העבודה היקרה (שרשרת + עקומה), כמו decision_recorder.
      2. _recommendation_for_expiry (הליבה הקריאה-בלבד) → insert_margin_recommendation.

    מחזיר סיכום לכל פקיעה קרובה:
      {expiry_date, expiry_type, selected_margin, hold_blended, status, rec_id}
      status ∈ {"recorded", "skipped_exists", "no_recommendation", "error"}.

    wing_pct — רוחב הכנף (ברירת מחדל DEFAULT_WING_PCT=0.75% — הכנף הרשמית מסריקת הכנפיים)
    שמועבר ל-build_margin_curve ונשמר ב-recommendation_json. אפשר לעקוף לניתוח/אופטימיזציה.

    שימוש חוזר: UI/סקריפט קורא עם trigger="manual"; Action עתידי עם trigger="scheduled".
    """
    eng = _make_engine(engine)
    results: list[dict] = []
    if eng is None:
        logger.warning(
            "record_margin_recommendations_for_upcoming: אין engine (DATABASE_URL לא מוגדר)."
        )
        return results

    # היסטוריה נטענת פעם אחת ומשותפת לכל הפקיעות (כמו decision_recorder).
    try:
        df = load_from_db(eng)
        df = df[df["move_pct"].notna()].copy()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "record_margin_recommendations_for_upcoming: טעינת היסטוריה נכשלה: %s",
            exc, exc_info=True,
        )
        return results

    for nxt in _upcoming_expiries(eng):
        exp_date = nxt.date()
        rec_summary = {
            "expiry_date":     str(exp_date),
            "expiry_type":     None,
            "selected_margin": None,
            "hold_blended":    None,
            "status":          "error",
            "rec_id":          None,
        }
        try:
            # דדופ לפני העבודה היקרה.
            if margin_recommendation_logged_today(
                exp_date, engine_version=engine_version, engine=eng
            ):
                rec_summary["status"] = "skipped_exists"
                results.append(rec_summary)
                continue

            rec = _recommendation_for_expiry(
                df, nxt, eng, wing_pct=wing_pct,
                engine_version=engine_version, trigger=trigger,
            )
            if rec is None:
                rec_summary["status"] = "no_recommendation"  # אין שרשרת/מרווח תקין
                results.append(rec_summary)
                continue

            rec_summary["expiry_type"]     = rec["expiry_type"]
            rec_summary["selected_margin"] = rec["selected_margin"]
            rec_summary["hold_blended"]    = rec["hold_blended"]

            rec_id = insert_margin_recommendation(
                rec, engine_version=engine_version, engine=eng,
            )
            if rec_id is not None:
                rec_summary["status"] = "recorded"
                rec_summary["rec_id"] = rec_id
            else:
                rec_summary["status"] = "error"  # insert החזיר None (כשל DB)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "record_margin_recommendations_for_upcoming נכשל לפקיעה %s: %s",
                exp_date, exc, exc_info=True,
            )
            rec_summary["status"] = "error"
        results.append(rec_summary)

    return results
