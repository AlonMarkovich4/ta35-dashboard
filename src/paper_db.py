"""
paper_db.py — שכבת DB לתיקי Paper Trading.

מנהל שתי טבלאות: paper_portfolios ו-paper_trades.
מתחבר דרך DATABASE_URL (אותו pattern כמו supabase_loader.py).

פונקציות ציבוריות:
  has_paper_db()                                                        → bool
  create_portfolio(name, initial_balance, commission_per_leg, engine)   → dict | None
  get_portfolios(engine=None)                                           → list[dict]
  get_portfolio(portfolio_id, engine=None)                              → dict | None
  update_balance(portfolio_id, new_balance, engine=None)                → bool
  insert_trade(trade, engine=None)                                      → dict | None
  get_trades(portfolio_id, status, expiry_date, engine=None)            → list[dict]
  get_open_trades_for_expiry(expiry_date, engine=None)                  → list[dict]
  close_trade(trade_id, close_index, pnl, pnl_pct, exit_commission, engine) → bool
"""
from __future__ import annotations

import json
import os
from typing import Optional

from sqlalchemy import create_engine, text


# ─── DB connection ─────────────────────────────────────────────────────

def has_paper_db() -> bool:
    """מחזיר True אם DATABASE_URL מוגדר בסביבה."""
    return bool(os.getenv("DATABASE_URL", ""))


def _make_engine(engine=None):
    """מחזיר engine קיים או יוצר חדש מ-DATABASE_URL; None אם לא מוגדר."""
    if engine is not None:
        return engine
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return None
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, echo=False)


# ─── JSONB helpers ─────────────────────────────────────────────────────

def _dumps(v) -> Optional[str]:
    """ממיר dict ל-JSON string לשמירה ב-JSONB (ensure_ascii=False לתמיכה בעברית)."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


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


# ─── Portfolios ─────────────────────────────────────────────────────────

def create_portfolio(
    name: str,
    initial_balance: float,
    commission_per_leg: float = 2.5,
    engine=None,
) -> Optional[dict]:
    """יוצר תיק paper trading חדש ומחזיר אותו כ-dict; None בכישלון."""
    eng = _make_engine(engine)
    if eng is None:
        return None
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO paper_portfolios
                        (name, initial_balance, current_balance, commission_per_leg, is_active)
                    VALUES (:name, :initial_balance, :initial_balance, :commission_per_leg, TRUE)
                    RETURNING *
                """),
                {
                    "name":               name,
                    "initial_balance":    initial_balance,
                    "commission_per_leg": commission_per_leg,
                },
            ).fetchone()
            conn.commit()
        return dict(row._mapping) if row else None
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
        return [dict(r._mapping) for r in rows]
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
        return dict(row._mapping) if row else None
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
    except Exception:
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
