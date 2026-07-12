"""
paper_db.py — שכבת DB לתיקי Paper Trading.

מנהל שתי טבלאות: paper_portfolios ו-paper_trades.
מתחבר דרך DATABASE_URL (אותו pattern כמו supabase_loader.py).

פונקציות ציבוריות:
  has_paper_db()                                                        → bool
  create_portfolio(name, initial_balance, commission_per_leg, strategy_ids, engine) → dict | None
  get_portfolios(engine=None)                                           → list[dict]
  get_portfolio(portfolio_id, engine=None)                              → dict | None
  update_balance(portfolio_id, new_balance, engine=None)                → bool
  insert_trade(trade, engine=None)                                      → dict | None
  get_trades(portfolio_id, status, expiry_date, engine=None)            → list[dict]
  get_open_trades_for_expiry(expiry_date, engine=None)                  → list[dict]
  get_settlement_index(expiry_date, engine=None)                        → float | None
  get_expiries_ready_to_close(engine=None)                              → list[dict]
  close_trade(trade_id, close_index, pnl, pnl_pct, exit_commission, engine) → bool
  insert_decision_log(decision, trigger, engine_version, engine)        → int | None
  get_decision_logs(limit, engine)                                      → list[dict]
  decision_logged_today(expiry_date, engine_version, engine)            → bool
  insert_margin_recommendation(rec, engine_version, engine)             → int | None
  margin_recommendation_logged_today(expiry_date, engine_version, engine) → bool
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


# רשימת מזהי כל האסטרטגיות — ברירת מחדל לתיק שמריץ את כולן.
DEFAULT_STRATEGY_IDS: list[int] = [1, 2, 3, 4, 5, 6]


# ─── DB connection ─────────────────────────────────────────────────────

def has_paper_db() -> bool:
    """מחזיר True אם DATABASE_URL מוגדר בסביבה."""
    return bool(os.getenv("DATABASE_URL", ""))


def _make_engine(engine=None):
    """מחזיר engine קיים או יוצר חדש מ-DATABASE_URL; None אם לא מוגדר.

    pool_pre_ping — בודק שהחיבור חי לפני שימוש (עמידות מול ה-Supabase pooler,
    שעלול לסגור חיבורים בצד השרת). pool_recycle — ממחזר חיבורים ישנים מ-30 דק'.
    """
    if engine is not None:
        return engine
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return None
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(
        db_url, echo=False, pool_pre_ping=True, pool_recycle=1800,
    )


# ─── JSONB helpers ─────────────────────────────────────────────────────

def _dumps(v) -> Optional[str]:
    """ממיר dict ל-JSON string לשמירה ב-JSONB (ensure_ascii=False לתמיכה בעברית)."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def _json_default(o):
    """serializer לטיפוסים שאינם JSON-native בתוך decision_json.

    Timestamp/datetime/date → isoformat; numpy scalars (np.int64/float64/bool_)
    → סקלר Python דרך .item(); כל השאר → str (גיבוי שלא יקרוס).
    """
    if hasattr(o, "isoformat"):          # pd.Timestamp / datetime / date
        return o.isoformat()
    if hasattr(o, "item"):               # numpy scalars
        return o.item()
    return str(o)


def _dumps_decision(v) -> Optional[str]:
    """ממיר את ה-decision dict ל-JSON ל-JSONB — כמו _dumps אך עם default ל-Timestamp/numpy.

    נפרד מ-_dumps כדי לא לשנות את התנהגותו לשימושים הקיימים (legs/snapshot).
    """
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, default=_json_default)


def _loads(v):
    """ממיר ערך JSONB חוזר מ-DB ל-dict; מטפל ב-dict/string/None."""
    if v is None:
        return None
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return v
    return v


def _row_to_dict(row) -> dict:
    """ממיר שורת DB ל-dict ומפרש שדות JSONB."""
    d = dict(row._mapping)
    for field in ("legs_json", "market_snapshot_json"):
        if field in d:
            d[field] = _loads(d[field])
    return d


def _parse_strategy_ids(v) -> list[int]:
    """ממיר ערך strategy_ids מ-JSONB ל-list[int].

    מקבל list, JSON-string או None (JSONB עשוי לחזור כ-list או כ-string).
    שדה חסר / ריק / לא תקין → כל 6 האסטרטגיות (null-safe, תאימות לאחור).
    """
    if v is None:
        return list(DEFAULT_STRATEGY_IDS)
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return list(DEFAULT_STRATEGY_IDS)
    if not isinstance(v, (list, tuple)):
        return list(DEFAULT_STRATEGY_IDS)
    ids: list[int] = []
    for x in v:
        try:
            sid = int(x)
        except (TypeError, ValueError):
            continue
        if sid not in ids:
            ids.append(sid)
    return ids or list(DEFAULT_STRATEGY_IDS)


def _portfolio_to_dict(row) -> dict:
    """ממיר שורת paper_portfolios ל-dict ומפרש strategy_ids ל-list[int]."""
    d = dict(row._mapping)
    d["strategy_ids"] = _parse_strategy_ids(d.get("strategy_ids"))
    return d


# ─── Portfolios ─────────────────────────────────────────────────────────

def create_portfolio(
    name: str,
    initial_balance: float,
    commission_per_leg: float = 2.5,
    strategy_ids: Optional[list[int]] = None,
    engine=None,
) -> Optional[dict]:
    """יוצר תיק paper trading חדש ומחזיר אותו כ-dict; None בכישלון.

    strategy_ids — רשימת מזהי האסטרטגיות שהתיק מריץ; None → כל 6 האסטרטגיות.
    נשמר כ-JSONB (אותו pattern כמו legs_json דרך _dumps).
    """
    eng = _make_engine(engine)
    if eng is None:
        return None
    sids = _parse_strategy_ids(strategy_ids)
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO paper_portfolios
                        (name, initial_balance, current_balance, commission_per_leg,
                         strategy_ids, is_active)
                    VALUES (:name, :initial_balance, :initial_balance, :commission_per_leg,
                            CAST(:strategy_ids AS JSONB), TRUE)
                    RETURNING *
                """),
                {
                    "name":               name,
                    "initial_balance":    initial_balance,
                    "commission_per_leg": commission_per_leg,
                    "strategy_ids":       _dumps(sids),
                },
            ).fetchone()
            conn.commit()
        return _portfolio_to_dict(row) if row else None
    except Exception:
        return None


def get_portfolios(engine=None) -> list[dict]:
    """מחזיר רשימת כל התיקים הפעילים; [] בכישלון."""
    eng = _make_engine(engine)
    if eng is None:
        return []
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM paper_portfolios"
                    " WHERE is_active = TRUE ORDER BY created_at DESC"
                )
            ).fetchall()
        return [_portfolio_to_dict(r) for r in rows]
    except Exception:
        return []


def get_portfolio(portfolio_id: int, engine=None) -> Optional[dict]:
    """מחזיר תיק לפי ID; None אם לא קיים או בכישלון."""
    eng = _make_engine(engine)
    if eng is None:
        return None
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM paper_portfolios WHERE id = :id"),
                {"id": portfolio_id},
            ).fetchone()
        return _portfolio_to_dict(row) if row else None
    except Exception:
        return None


def update_balance(portfolio_id: int, new_balance: float, engine=None) -> bool:
    """מעדכן את current_balance של תיק; False בכישלון."""
    eng = _make_engine(engine)
    if eng is None:
        return False
    try:
        with eng.connect() as conn:
            conn.execute(
                text("""
                    UPDATE paper_portfolios
                    SET current_balance = :balance
                    WHERE id = :id
                """),
                {"balance": new_balance, "id": portfolio_id},
            )
            conn.commit()
        return True
    except Exception:
        return False


# ─── Trades ────────────────────────────────────────────────────────────

def insert_trade(trade: dict, engine=None) -> Optional[dict]:
    """מכניס עסקת paper trading חדשה; legs_json/market_snapshot_json מתקבלים כ-dict.

    מחזיר את השורה שנוצרה כ-dict, או None בכישלון.
    """
    eng = _make_engine(engine)
    if eng is None:
        return None
    try:
        params = {**trade}
        params["legs_json"]            = _dumps(params.get("legs_json"))
        params["market_snapshot_json"] = _dumps(params.get("market_snapshot_json"))
        with eng.connect() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO paper_trades (
                        portfolio_id, strategy_id, strategy_name, expiry_date,
                        opened_at, entry_index, entry_cost, legs_json,
                        max_profit, max_loss, status,
                        closed_at, close_index, pnl, pnl_pct, market_snapshot_json,
                        num_legs, entry_commission, exit_commission
                    ) VALUES (
                        :portfolio_id, :strategy_id, :strategy_name, :expiry_date,
                        :opened_at, :entry_index, :entry_cost, CAST(:legs_json AS JSONB),
                        :max_profit, :max_loss, :status,
                        :closed_at, :close_index, :pnl, :pnl_pct,
                        CAST(:market_snapshot_json AS JSONB),
                        :num_legs, :entry_commission, :exit_commission
                    )
                    RETURNING *
                """),
                params,
            ).fetchone()
            conn.commit()
        return _row_to_dict(row) if row else None
    except Exception as exc:
        # חושפים את הסיבה האמיתית ללוגים (Render) במקום לנחש — הערך המוחזר נשאר None.
        logger.warning(
            "insert_trade נכשל (portfolio_id=%s, strategy_id=%s): %s",
            trade.get("portfolio_id"), trade.get("strategy_id"), exc,
            exc_info=True,
        )
        return None


def get_trades(
    portfolio_id: Optional[int] = None,
    status: Optional[str] = None,
    expiry_date=None,
    engine=None,
) -> list[dict]:
    """מחזיר עסקאות עם פילטרים אופציונליים; [] בכישלון."""
    eng = _make_engine(engine)
    if eng is None:
        return []
    try:
        conditions: list[str] = []
        params: dict = {}
        if portfolio_id is not None:
            conditions.append("portfolio_id = :portfolio_id")
            params["portfolio_id"] = portfolio_id
        if status is not None:
            conditions.append("status = :status")
            params["status"] = status
        if expiry_date is not None:
            conditions.append("expiry_date = :expiry_date")
            params["expiry_date"] = expiry_date

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with eng.connect() as conn:
            rows = conn.execute(
                text(f"SELECT * FROM paper_trades {where} ORDER BY opened_at DESC"),
                params,
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def get_open_trades_for_expiry(expiry_date, engine=None) -> list[dict]:
    """מחזיר כל העסקאות הפתוחות לפקיעה נתונה; [] בכישלון."""
    eng = _make_engine(engine)
    if eng is None:
        return []
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT * FROM paper_trades
                    WHERE status = 'open' AND expiry_date = :expiry_date
                    ORDER BY opened_at
                """),
                {"expiry_date": expiry_date},
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def close_trade(
    trade_id: int,
    close_index: float,
    pnl: float,
    pnl_pct: float,
    exit_commission: float = 0.0,
    engine=None,
) -> bool:
    """סוגר עסקה: מעדכן status='closed', closed_at=NOW(), close_index, pnl, pnl_pct, exit_commission.

    מחזיר False בכישלון.
    """
    eng = _make_engine(engine)
    if eng is None:
        return False
    try:
        with eng.connect() as conn:
            conn.execute(
                text("""
                    UPDATE paper_trades
                    SET status          = 'closed',
                        closed_at       = NOW(),
                        close_index     = :close_index,
                        pnl             = :pnl,
                        pnl_pct         = :pnl_pct,
                        exit_commission = :exit_commission
                    WHERE id = :id
                """),
                {
                    "id":              trade_id,
                    "close_index":     close_index,
                    "pnl":             pnl,
                    "pnl_pct":         pnl_pct,
                    "exit_commission": exit_commission,
                },
            )
            conn.commit()
        return True
    except Exception:
        return False


# ─── Settlement source (read-only) ──────────────────────────────────────

def get_settlement_index(expiry_date, engine=None) -> Optional[float]:
    """מחזיר את מחיר הסטלמנט (actual_index_close) של פקיעה מ-condor_settled_detail.

    קריאה בלבד. מחזיר float אם קיים מחיר נעילה קובע לפקיעה, אחרת None
    (למשל פקיעה שטרם נקבע לה סטלמנט — כמו 2026-06-19 כרגע).

    טבלת ה-detail עשויה להחזיק כמה שורות לפקיעה (פירוט לפי סטרייק), אך מחיר
    הנעילה הקובע זהה לכולן — לכן נשלפת שורה תקפה אחת (LIMIT 1).
    """
    eng = _make_engine(engine)
    if eng is None:
        return None
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT actual_index_close
                    FROM condor_settled_detail
                    WHERE expiry_date = :expiry_date
                      AND actual_index_close IS NOT NULL
                    LIMIT 1
                """),
                {"expiry_date": expiry_date},
            ).fetchone()
        if row is None:
            return None
        val = row._mapping.get("actual_index_close")
        return float(val) if val is not None else None
    except Exception as exc:
        logger.warning(
            "get_settlement_index נכשל (expiry_date=%s): %s",
            expiry_date, exc, exc_info=True,
        )
        return None


def get_expiries_ready_to_close(engine=None) -> list[dict]:
    """מחזיר פקיעות שבשלו לסגירה: יש להן עסקאות פתוחות *וגם* מחיר סטלמנט זמין.

    קריאה בלבד. פקיעה "בשלה" = קיימות לה שורות status='open' ב-paper_trades,
    וגם קיים actual_index_close ב-condor_settled_detail. פקיעה עם עסקאות
    פתוחות אך ללא סטלמנט (כמו 2026-06-19) לא תיכלל — זה התנאי שמגן מסגירה
    מוקדמת.

    לכל פקיעה: {expiry_date, settlement_index, open_trades}, ממוין לפי תאריך.

    ה-condor_settled_detail מצומצם לשורה-אחת-לפקיעה בתת-שאילתה *לפני* ה-JOIN,
    כדי שספירת העסקאות הפתוחות (COUNT) לא תוכפל ע"י ריבוי שורות הפירוט.

    ה-JOIN ממיר את שני צידי expiry_date ל-::date: העמודות בשתי הטבלאות אינן
    מאותו טיפוס (אחת date ואחת text בפורמט 'YYYY-MM-DD'), ו-Postgres מסרב
    להשוות text=date בלי המרה מפורשת. השוואה כ-date היא נכונה סמנטית, היא
    no-op על עמודת date אמיתית, מפרסרת נכון מחרוזת ISO, ועמידה בפני הבדלי
    פורמט-מחרוזת (רכיב שעה/רווחים) שהשוואת ::text הייתה נכשלת עליהם.
    """
    eng = _make_engine(engine)
    if eng is None:
        return []
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT pt.expiry_date     AS expiry_date,
                           COUNT(*)           AS open_trades,
                           s.settlement_index AS settlement_index
                    FROM paper_trades pt
                    JOIN (
                        SELECT expiry_date,
                               MAX(actual_index_close) AS settlement_index
                        FROM condor_settled_detail
                        WHERE actual_index_close IS NOT NULL
                        GROUP BY expiry_date
                    ) s ON s.expiry_date::date = pt.expiry_date::date
                    WHERE pt.status = 'open'
                    GROUP BY pt.expiry_date, s.settlement_index
                    ORDER BY pt.expiry_date
                """),
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            m  = r._mapping
            si = m.get("settlement_index")
            out.append({
                "expiry_date":      m.get("expiry_date"),
                "settlement_index": float(si) if si is not None else None,
                "open_trades":      int(m.get("open_trades") or 0),
            })
        return out
    except Exception as exc:
        logger.warning("get_expiries_ready_to_close נכשל: %s", exc, exc_info=True)
        return []


# ─── Decision log (append-only) ─────────────────────────────────────────

def insert_decision_log(
    decision: dict,
    trigger: str = "manual",
    engine_version: str = "layer1-v1",
    engine=None,
) -> Optional[int]:
    """מכניס רשומת decision_log אחת (append-only); מחזיר id חדש (RETURNING) או None בכישלון.

    decision — הפלט המלא של build_expiry_decision. השדות השטוחים נשלפים ממנו,
    וה-decision כולו נשמר ב-decision_json (JSONB) דרך _dumps_decision
    (ensure_ascii=False + טיפול ב-Timestamp/numpy).

    decided_at אינו נשלח — DEFAULT now() בטבלה קובע את חותמת הזמן בצד ה-DB:
    מקור אמת אחד, ושעון שרת אחיד לכל ההרצות (לא תלוי בשעון המקומי של הקורא).
    """
    eng = _make_engine(engine)
    if eng is None:
        return None
    try:
        # expiry_date עשוי להגיע כ-pd.Timestamp/datetime → ממירים ל-date לעמודת DATE
        exp = decision.get("expiry_date")
        if exp is not None and hasattr(exp, "date") and callable(exp.date):
            exp = exp.date()

        params = {
            "expiry_date":     exp,
            "expiry_type":     decision.get("expiry_type"),
            "regime":          (decision.get("regime") or {}).get("regime"),
            "risk_score":      decision.get("risk_score"),
            "n_similar":       decision.get("n_similar"),
            "top_strategy_id": decision.get("top_strategy_id"),
            "trigger":         trigger,
            "engine_version":  engine_version,
            "decision_json":   _dumps_decision(decision),
        }
        with eng.connect() as conn:
            new_id = conn.execute(
                text("""
                    INSERT INTO decision_log (
                        expiry_date, expiry_type, regime, risk_score,
                        n_similar, top_strategy_id, trigger,
                        decision_json, engine_version
                    ) VALUES (
                        :expiry_date, :expiry_type, :regime, :risk_score,
                        :n_similar, :top_strategy_id, :trigger,
                        CAST(:decision_json AS JSONB), :engine_version
                    )
                    RETURNING id
                """),
                params,
            ).scalar()
            conn.commit()
        return int(new_id) if new_id is not None else None
    except Exception as exc:
        logger.warning(
            "insert_decision_log נכשל (expiry_date=%s): %s",
            decision.get("expiry_date"), exc, exc_info=True,
        )
        return None


def get_decision_logs(limit: int = 50, engine=None) -> list[dict]:
    """מחזיר רשומות decision_log ממוינות לפי decided_at יורד (האחרונה ראשונה).

    קריאה בלבד (append-only) — מחזיר עד limit רשומות; [] בכישלון.
    decision_json (JSONB) חוזר כ-dict מהדרייבר.
    """
    eng = _make_engine(engine)
    if eng is None:
        return []
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM decision_log"
                    " ORDER BY decided_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []


def decision_logged_today(
    expiry_date,
    engine_version: str = "layer1-v1",
    engine=None,
) -> bool:
    """מחזיר True אם כבר קיימת רשומת decision_log לפקיעה הזו מאותה גרסה *היום*.

    משמש למניעת כפילויות בתיעוד (לחיצה חוזרת/הרצה חוזרת באותו יום לא תיצור
    רשומה כפולה). "היום" נקבע לפי שעון השרת (decided_at::date = CURRENT_DATE) —
    אותו עיקרון של מקור-זמן אחיד כמו ב-insert_decision_log.

    expiry_date ב-decision_log הוא DATE; ערך נכנס עשוי להיות Timestamp/datetime —
    ממירים ל-date לפני ההשוואה. בכישלון DB מחזיר False (best-effort: לא חוסם
    תיעוד עתידי בגלל תקלה רגעית) ומתעד warning.
    """
    eng = _make_engine(engine)
    if eng is None:
        return False
    exp = expiry_date
    if exp is not None and hasattr(exp, "date") and callable(exp.date):
        exp = exp.date()
    try:
        with eng.connect() as conn:
            found = conn.execute(
                text("""
                    SELECT 1 FROM decision_log
                     WHERE expiry_date = :expiry_date
                       AND engine_version = :engine_version
                       AND decided_at::date = CURRENT_DATE
                     LIMIT 1
                """),
                {"expiry_date": exp, "engine_version": engine_version},
            ).first()
        return found is not None
    except Exception as exc:
        logger.warning(
            "decision_logged_today נכשל (expiry_date=%s): %s",
            expiry_date, exc, exc_info=True,
        )
        return False


# ─── Margin recommendations (append-only) ───────────────────────────────

def insert_margin_recommendation(
    rec: dict,
    engine_version: str = "margin-v1",
    engine=None,
) -> Optional[int]:
    """מכניס רשומת margin_recommendations אחת (append-only); מחזיר id חדש או None בכישלון.

    rec — פלט מנגנון המרווח (margin_recorder._recommendation_for_expiry): select_margin
    (שלב 3) מועשר בפרטי הפקיעה + שורת העקומה הנבחרת. השדות השטוחים נשלפים לעמודות,
    וה-rec כולו נשמר ב-recommendation_json (JSONB, כולל grid + selected_curve_row מלאים
    לשקיפות ולשחזור P&L בולידציה) דרך _dumps_decision (ensure_ascii=False + Timestamp/numpy).

    recommended_at אינו נשלח — DEFAULT now() בטבלה קובע חותמת זמן בצד ה-DB: מקור-זמן אחיד
    לכל ההרצות, זהה בדיוק ל-decision_log.
    """
    eng = _make_engine(engine)
    if eng is None:
        return None
    try:
        # expiry_date עשוי להגיע כ-pd.Timestamp/datetime → ל-date לעמודת DATE.
        exp = rec.get("expiry_date")
        if exp is not None and hasattr(exp, "date") and callable(exp.date):
            exp = exp.date()

        params = {
            "expiry_date":         exp,
            "margin_pct":          rec.get("selected_margin"),
            "hold_blended":        rec.get("hold_blended"),
            "hold_conditional":    rec.get("hold_conditional"),
            "hold_global":         rec.get("hold_global"),
            "n_conditional":       rec.get("n_conditional"),
            "premium_ils":         rec.get("net_premium"),
            "short_put_strike":    rec.get("short_put_strike"),
            "short_call_strike":   rec.get("short_call_strike"),
            "below_floor":         rec.get("below_floor"),
            "floor_used":          rec.get("hold_floor"),
            "engine_version":      engine_version,
            "reason":              rec.get("reason"),
            "recommendation_json": _dumps_decision(rec),
        }
        with eng.connect() as conn:
            new_id = conn.execute(
                text("""
                    INSERT INTO margin_recommendations (
                        expiry_date, margin_pct, hold_blended, hold_conditional,
                        hold_global, n_conditional, premium_ils,
                        short_put_strike, short_call_strike, below_floor,
                        floor_used, engine_version, reason, recommendation_json
                    ) VALUES (
                        :expiry_date, :margin_pct, :hold_blended, :hold_conditional,
                        :hold_global, :n_conditional, :premium_ils,
                        :short_put_strike, :short_call_strike, :below_floor,
                        :floor_used, :engine_version, :reason,
                        CAST(:recommendation_json AS JSONB)
                    )
                    RETURNING id
                """),
                params,
            ).scalar()
            conn.commit()
        return int(new_id) if new_id is not None else None
    except Exception as exc:
        logger.warning(
            "insert_margin_recommendation נכשל (expiry_date=%s): %s",
            rec.get("expiry_date"), exc, exc_info=True,
        )
        return None


def margin_recommendation_logged_today(
    expiry_date,
    engine_version: str = "margin-v1",
    engine=None,
) -> bool:
    """מחזיר True אם כבר קיימת המלצת מרווח לפקיעה הזו מאותה גרסה *היום* (שעון השרת).

    זהה בדיוק ל-decision_logged_today: מונע כפילות כשמריצים את הרשם פעמיים באותו יום.
    "היום" = recommended_at::date = CURRENT_DATE (מקור-זמן אחיד עם insert). בכישלון DB
    מחזיר False (best-effort — לא חוסם תיעוד עתידי בגלל תקלה רגעית) ומתעד warning.
    """
    eng = _make_engine(engine)
    if eng is None:
        return False
    exp = expiry_date
    if exp is not None and hasattr(exp, "date") and callable(exp.date):
        exp = exp.date()
    try:
        with eng.connect() as conn:
            found = conn.execute(
                text("""
                    SELECT 1 FROM margin_recommendations
                     WHERE expiry_date = :expiry_date
                       AND engine_version = :engine_version
                       AND recommended_at::date = CURRENT_DATE
                     LIMIT 1
                """),
                {"expiry_date": exp, "engine_version": engine_version},
            ).first()
        return found is not None
    except Exception as exc:
        logger.warning(
            "margin_recommendation_logged_today נכשל (expiry_date=%s): %s",
            expiry_date, exc, exc_info=True,
        )
        return False
