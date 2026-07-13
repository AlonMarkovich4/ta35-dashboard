"""
decision_validator.py — גשר 2, שכבת ולידציה: "המנוע מול המציאות" (קריאה בלבד).

השכבה שחיברה בין תחזיות המנוע (decision_log) לבין הרווח האמיתי (paper_trades).
לכל פקיעה שגם *תועדה* ב-decision_log וגם *נסגרה* עם P&L ב-paper_trades, המודול
משווה: מה המנוע המליץ, מול מה שבאמת הניב הכי הרבה כסף. מכיוון שאנו פותחים את
כל 6 האסטרטגיות לכל פקיעה, יש לנו P&L לכולן — ואפשר למקם את ההמלצה בדיוק ביחס
לאופטימום (הטובה ביותר), לרצפה (הגרועה), ולבנצ'מרק של "בחירה אקראית" (ממוצע).

מודול טהור-לוגיקה, אפס Streamlit (כמו decision_recorder): גם ה-UI (דף 6) וגם
סקריפט/Action עתידי קוראים לאותה build_validation_rows().

קריאה בלבד מה-DB (SELECT בלבד) — אפס כתיבה. שתי שאילתות:
  • _fetch_latest_decisions — ההחלטה האחרונה (MAX(decided_at)) לכל
    (expiry_date, engine_version), עם n_decisions = כמה החלטות נרשמו לאותה קבוצה.
  • _fetch_closed_pnl — P&L מצטבר של עסקאות סגורות (status='closed') לכל
    (expiry_date, strategy_id).

טיפוסי expiry_date: decision_log.expiry_date ו-paper_trades.expiry_date שניהם
DATE (בניגוד ל-condor_settled_detail שהוא text). עם זאת, החיבור נעשה ב-Python
דרך _as_date שמנרמל date/datetime/Timestamp/מחרוזת-ISO למפתח date אחיד — כך
החיבור עמיד גם אם דרייבר כלשהו יחזיר טיפוס שונה (שקול ל-CAST ::date, בצד Python).
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy import text

from paper_db import _make_engine
from strategies import BENCHMARK_STRATEGY_IDS, STRATEGIES

logger = logging.getLogger(__name__)


# ─── helpers ────────────────────────────────────────────────────────────

def _as_date(v):
    """מנרמל ערך expiry_date (date/datetime/Timestamp/מחרוזת-ISO) ל-datetime.date אחיד.

    משמש כמפתח חיבור בין decision_log ל-paper_trades בצד Python — שקול ל-CAST ::date
    ב-SQL, אך עמיד לכל טיפוס שהדרייבר עשוי להחזיר. None/לא-פריק → None.
    """
    if v is None:
        return None
    if isinstance(v, datetime):     # datetime הוא תת-מחלקה של date — לבדוק ראשון
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.Timestamp(v).date()
    except Exception:  # noqa: BLE001
        logger.warning("_as_date: לא ניתן לפרסר expiry_date=%r", v)
        return None


def _strategy_name(sid, trade_names: dict) -> str:
    """שם אסטרטגיה לתצוגה: קודם השם שנשמר בעסקה (authoritative), אחרת מה-registry.

    trade_names — מיפוי {strategy_id: strategy_name} מ-paper_trades לאותה פקיעה.
    נופל ל-STRATEGIES[sid].name אם אין עסקה למזהה (למשל האסטרטגיה המומלצת לא
    נפתחה), ולבסוף ל-str(sid) / "—".
    """
    nm = trade_names.get(sid)
    if nm:
        return nm
    if sid in STRATEGIES:
        return STRATEGIES[sid].name
    return str(sid) if sid is not None else "—"


# ─── DB reads (read-only) ───────────────────────────────────────────────

def _fetch_latest_decisions(eng) -> list[dict]:
    """שולף מ-decision_log את ההחלטה האחרונה לכל (expiry_date, engine_version).

    DISTINCT ON בוחר את הרשומה עם decided_at המקסימלי בכל קבוצה (האחרונה =
    המושכלת ביותר, כי decision_log הוא append-only ולאותה פקיעה יש כמה רשומות
    מימים שונים). COUNT(*) OVER (PARTITION BY ...) מחשב את מספר ההחלטות הכולל
    באותה קבוצה (n_decisions) לפני שה-DISTINCT ON בורר שורה אחת — כך שהספירה
    מכסה את *כל* הרשומות, לא רק את הנבחרת.

    כל ההחלטות נרשמות לפקיעות עתידיות (recorder רץ רק על expiry >= היום), ולכן
    decided_at תמיד לפני הפקיעה — MAX(decided_at) הוא "האחרונה לפני הפקיעה".
    מחזיר [] בכישלון (best-effort, קריאה בלבד).
    """
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT DISTINCT ON (expiry_date, engine_version)
                           expiry_date,
                           engine_version,
                           decided_at,
                           top_strategy_id,
                           regime,
                           COUNT(*) OVER (
                               PARTITION BY expiry_date, engine_version
                           ) AS n_decisions
                    FROM decision_log
                    ORDER BY expiry_date, engine_version, decided_at DESC
                """),
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            m = r._mapping
            tsid = m.get("top_strategy_id")
            out.append({
                "expiry_date":     _as_date(m.get("expiry_date")),
                "engine_version":  m.get("engine_version"),
                "decided_at":      m.get("decided_at"),
                "top_strategy_id": int(tsid) if tsid is not None else None,
                "regime":          m.get("regime"),
                "n_decisions":     int(m.get("n_decisions") or 0),
            })
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_latest_decisions נכשל: %s", exc, exc_info=True)
        return []


def _fetch_closed_pnl(eng) -> list[dict]:
    """שולף P&L מצטבר של עסקאות סגורות לכל (expiry_date, strategy_id).

    status='closed' + pnl IS NOT NULL. SUM(pnl) מצטבר על פני עסקאות (במקרה הרגיל
    של תיק יחיד עם 6 אסטרטגיות — עסקה אחת לכל אסטרטגיה, כך שה-SUM שקול לערך
    הבודד; אם ריצה עתידית תפתח את אותה אסטרטגיה בכמה תיקים, הצבירה נשמרת עקבית).
    strategy_name נשלף כ-MAX (זהה לכל השורות של אותו strategy_id).

    מחזיר [] בכישלון (best-effort, קריאה בלבד).
    """
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT expiry_date,
                           strategy_id,
                           MAX(strategy_name) AS strategy_name,
                           SUM(pnl)           AS pnl,
                           COUNT(*)           AS n_trades
                    FROM paper_trades
                    WHERE status = 'closed' AND pnl IS NOT NULL
                      AND strategy_id = ANY(:benchmark_ids)   -- benchmark בלבד (מחריג תיק ההמלצות, 102)
                    GROUP BY expiry_date, strategy_id
                """),
                {"benchmark_ids": sorted(BENCHMARK_STRATEGY_IDS)},
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            m = r._mapping
            sid  = m.get("strategy_id")
            pnl  = m.get("pnl")
            out.append({
                "expiry_date":   _as_date(m.get("expiry_date")),
                "strategy_id":   int(sid) if sid is not None else None,
                "strategy_name": m.get("strategy_name"),
                "pnl":           float(pnl) if pnl is not None else None,
                "n_trades":      int(m.get("n_trades") or 0),
            })
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_closed_pnl נכשל: %s", exc, exc_info=True)
        return []


# ─── public API ─────────────────────────────────────────────────────────

def build_validation_rows(engine=None) -> list[dict]:
    """מחבר תחזיות המנוע (decision_log) לרווח האמיתי (paper_trades) — שורה לפקיעה ולידבילית.

    "ולידבילית" = יש לה גם החלטה (decision_log) וגם עסקאות סגורות (paper_trades).
    פקיעה עם החלטה אך בלי עסקאות סגורות — או להפך — לא נכללת.

    לכל פקיעה כזו מחשב:
      • ההמלצה: top_strategy_id + top_strategy_name.
      • recommended_pnl — ה-P&L בפועל של האסטרטגיה המומלצת (None אם, בניגוד לצפוי,
        לא נפתחה/נסגרה לה עסקה).
      • best_strategy_id + best_strategy_name + best_pnl — מי באמת הרוויח הכי הרבה.
      • worst_pnl — הגרוע ביותר (קונטקסט). avg_pnl — ממוצע כל האסטרטגיות שנסגרו
        (בנצ'מרק "בחירה אקראית").
      • hit — האם ההמלצה הניבה את ה-P&L המקסימלי (עמיד לתיקו: משווה ערך, לא רק ID).
      • regret — best_pnl - recommended_pnl (כמה "עלתה" הטעות; 0 אם פגע;
        None אם אין P&L להמלצה).
      • regime — משטר התנודתיות שהמנוע חשב. n_decisions — כמה החלטות נרשמו לפקיעה.

    מחזיר רשימה ממוינת לפי expiry_date יורד (האחרונה ראשונה). [] אם אין engine
    (DATABASE_URL לא מוגדר) או אין פקיעות ולידביליות.
    """
    eng = _make_engine(engine)
    if eng is None:
        logger.warning("build_validation_rows: אין engine (DATABASE_URL לא מוגדר).")
        return []

    decisions = _fetch_latest_decisions(eng)
    trades    = _fetch_closed_pnl(eng)

    # אינדוקס עסקאות סגורות לפי פקיעה → {strategy_id: {"pnl", "name"}}
    by_expiry: dict = {}
    for t in trades:
        exp = t["expiry_date"]
        sid = t["strategy_id"]
        if exp is None or sid is None or t["pnl"] is None:
            continue
        if sid not in BENCHMARK_STRATEGY_IDS:
            continue   # תיק ההמלצות (strategy_id=102) לא נספר ל-best/hit/regret של ה-benchmark
        by_expiry.setdefault(exp, {})[sid] = {"pnl": t["pnl"], "name": t["strategy_name"]}

    rows: list[dict] = []
    for dec in decisions:
        exp = dec["expiry_date"]
        strat_map = by_expiry.get(exp)
        if not strat_map:
            continue  # החלטה קיימת אך אין עסקאות סגורות — לא ולידבילית

        pnls        = {sid: v["pnl"] for sid, v in strat_map.items()}
        trade_names = {sid: v["name"] for sid, v in strat_map.items()}

        best_pnl  = max(pnls.values())
        worst_pnl = min(pnls.values())
        avg_pnl   = sum(pnls.values()) / len(pnls)

        top_id  = dec["top_strategy_id"]
        rec_pnl = pnls.get(top_id)   # None אם האסטרטגיה המומלצת לא בין הסגורות

        if rec_pnl is not None and rec_pnl == best_pnl:
            # פגיעה (כולל תיקו על המקסימום): מציגים את המומלצת כטובה ביותר, regret=0
            hit      = True
            best_id  = top_id
            best_val = rec_pnl
            regret   = 0.0
        else:
            hit      = False
            # שובר-תיקו דטרמיניסטי: מבין בעלי ה-P&L המקסימלי, ה-strategy_id הנמוך
            best_id  = min(sid for sid, p in pnls.items() if p == best_pnl)
            best_val = best_pnl
            regret   = (best_pnl - rec_pnl) if rec_pnl is not None else None

        rows.append({
            "expiry_date":        exp,
            "decided_at":         dec.get("decided_at"),
            "top_strategy_id":    top_id,
            "top_strategy_name":  _strategy_name(top_id, trade_names),
            "recommended_pnl":    rec_pnl,
            "best_strategy_id":   best_id,
            "best_strategy_name": _strategy_name(best_id, trade_names),
            "best_pnl":           best_val,
            "worst_pnl":          worst_pnl,
            "avg_pnl":            avg_pnl,
            "hit":                hit,
            "regret":             regret,
            "regime":             dec.get("regime"),
            "n_decisions":        dec.get("n_decisions"),
        })

    rows.sort(key=lambda r: str(r["expiry_date"]), reverse=True)
    return rows


def summarize_validation(rows: list[dict]) -> dict:
    """מסכם שורות ולידציה לכדי מדדי-על להצגה.

    מחזיר dict עם:
      • n_validated   — מספר הפקיעות שנוולדו.
      • hit_rate      — אחוז הפעמים שההמלצה הייתה הטובה ביותר (0..1). רשימה ריקה → 0.
      • recommended_pnl — סך ה-P&L של "תיק לפי המנוע" (עסקה מומלצת אחת לכל פקיעה).
      • best_pnl      — סך ה-P&L של "התיק המושלם" (התקרה — תמיד לבחור את הטובה ביותר).
      • avg_pnl       — סך ה-P&L של "בחירה אקראית" (הרצפה — ממוצע כל האסטרטגיות).
      • total_regret  — סך הפערים (best - recommended); best_pnl - recommended_pnl.

    תובנת המפתח: אם recommended_pnl > avg_pnl, המנוע מוסיף ערך גם כשאינו פוגע בול —
    הוא בוחר טוב יותר מבחירה אקראית. None ב-recommended_pnl/regret מדולג בסכימה.
    """
    n = len(rows)
    if n == 0:
        return {
            "n_validated":     0,
            "hit_rate":        0.0,
            "recommended_pnl": 0.0,
            "best_pnl":        0.0,
            "avg_pnl":         0.0,
            "total_regret":    0.0,
        }
    hits = sum(1 for r in rows if r.get("hit"))
    return {
        "n_validated":     n,
        "hit_rate":        hits / n,
        "recommended_pnl": sum(r["recommended_pnl"] for r in rows if r.get("recommended_pnl") is not None),
        "best_pnl":        sum(r["best_pnl"] for r in rows if r.get("best_pnl") is not None),
        "avg_pnl":         sum(r["avg_pnl"] for r in rows if r.get("avg_pnl") is not None),
        "total_regret":    sum(r["regret"] for r in rows if r.get("regret") is not None),
    }
