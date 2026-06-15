"""
paper_trading.py — מנוע פתיחה וסגירה של עסקאות Paper Trading.

מודל מזומן (כולל עמלות):
  entry_cost        = עלות/זיכוי בכניסה (חיובי=שולמה פרמיה, שלילי=התקבלה פרמיה)
  entry_commission  = num_legs × commission_per_leg (מהתיק)
  exit_commission   = num_legs × commission_per_leg (בסגירה)

  pnl     = payoff_at_close - entry_cost - entry_commission - exit_commission

מקור אמת אחד ליתרה (single source of truth):
  היתרה אינה נשמרת כשדה נפרד אלא *נגזרת תמיד* מהעסקאות דרך compute_balance():
    balance = initial_balance
              − Σ(entry_cost + entry_commission)  של עסקאות פתוחות
              + Σ(pnl)                            של עסקאות סגורות
  עסקה סגורה: ה-pnl כבר כולל את כל העלויות והעמלות → נספר רק ה-pnl (ללא כפילות).
  כך אי-אפשר שהיתרה תצא מסנכרון אם כתיבה כלשהי תיכשל.

פונקציות ציבוריות:
  compute_balance(portfolio, trades)                                   → float
  open_trades_for_expiry(expiry_date, chain, portfolios, engine=None)  → list[dict]
  close_trades_for_expiry(expiry_date, close_index, engine=None)       → list[dict]
  build_equity_curve(trades, initial_balance)                          → list[dict]
  build_track_record(trades)                                           → list[dict]
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

from options_parser import find_atm
from payoff import (
    MULTIPLIER,
    find_breakevens,
    strategy_legs_detail,
    strategy_payoff_params,
    strategy_summary,
)
from strategies import STRATEGIES
from paper_db import (
    _make_engine,
    close_trade,
    get_open_trades_for_expiry,
    get_portfolio,
    get_trades,
    insert_trade,
)


# ─── Date helpers ──────────────────────────────────────────────────────

def _parse_date(d) -> Optional[date]:
    """ממיר ערך לתאריך; מקבל date, datetime, YYYY-MM-DD, DD/MM/YYYY."""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    s = str(d).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _portfolio_strategy_ids(portfolio: dict) -> list[int]:
    """מחזיר את רשימת מזהי האסטרטגיות שהתיק מוגדר להריץ, לפי הסדר.

    מקבל list[int], list[str] או JSON-string (במקרה ש-strategy_ids לא פורסר).
    מסנן רק מזהים חוקיים הקיימים ב-STRATEGIES ומונע כפילויות.
    שדה חסר / ריק / לא תקין → כל 6 האסטרטגיות (null-safe, תאימות לאחור).
    """
    raw = (portfolio or {}).get("strategy_ids")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raw = None
    if not isinstance(raw, (list, tuple)) or not raw:
        return list(STRATEGIES.keys())
    out: list[int] = []
    for x in raw:
        try:
            sid = int(x)
        except (TypeError, ValueError):
            continue
        if sid in STRATEGIES and sid not in out:
            out.append(sid)
    return out or list(STRATEGIES.keys())


def _find_chain_entry(chain: dict, expiry_date) -> Optional[dict]:
    """מאתר את רשומת הפקיעה ב-chain dict לפי expiry_date."""
    target = _parse_date(expiry_date)
    if target is None:
        return None
    for entry in (chain or {}).get("expiries", []):
        d = _parse_date(entry.get("date", ""))
        if d == target:
            return entry
    return None


# ─── Payoff helpers ────────────────────────────────────────────────────

def _entry_cost_pts(strategy_id: int, params: dict) -> float:
    """מחזיר עלות/זיכוי כניסה בנקודות (חיובי=תשלום, שלילי=קבלה).

    Iron Condor (id=2): מחזיר ערך שלילי כי מתקבלת פרמיה.
    """
    if strategy_id == 2:
        return -float(params.get("credit_pts", 0.0))
    return float(params.get("cost_pts", 0.0))


def _payoff_from_legs(legs: list[dict], close_index: float) -> float:
    """חישוב payoff גולמי (ללא ניכוי עלות) בנקודת close_index לפי רגליים.

    מחזיר ₪ — המשקל (qty) נלקח בחשבון, קנה=+, מכור=−.
    """
    total = 0.0
    for leg in legs:
        strike    = float(leg["strike"])
        qty       = int(leg.get("qty", 1))
        sign      = 1.0 if leg.get("action") == "קנה" else -1.0
        option_type = leg.get("type", "")
        if option_type == "Call":
            intrinsic = max(close_index - strike, 0.0)
        elif option_type == "Put":
            intrinsic = max(strike - close_index, 0.0)
        else:
            intrinsic = 0.0
        total += sign * qty * intrinsic * MULTIPLIER
    return total


# ─── Snapshot builder ──────────────────────────────────────────────────

def _build_snapshot(
    expiry_date,
    expiry_entry: dict,
    atm: dict,
    chain_df: pd.DataFrame,
    engine,
) -> dict:
    """בונה market_snapshot_json עם כל מצב השוק; חסרים → None ולא נכשל."""
    snap: dict = {
        "atm_level":   atm.get("index_estimate", atm.get("strike")),
        "atm_strike":  atm.get("strike"),
        "expiry_type": expiry_entry.get("expiry_type", "שבועי"),
    }

    exp_dt = _parse_date(expiry_date)
    today  = date.today()
    snap["days_to_expiry"] = (exp_dt - today).days if exp_dt else None
    snap["day_of_week"]    = exp_dt.weekday()      if exp_dt else None

    try:
        snap["chain"] = json.loads(
            chain_df.to_json(orient="records", force_ascii=False)
        )
    except Exception:
        snap["chain"] = None

    # תנועת פקיעה אחרונה מנתונים היסטוריים
    try:
        from data_loader import load_expiry_data          # noqa: PLC0415
        from context_analyzer import get_recent_move       # noqa: PLC0415
        df_hist = load_expiry_data()
        snap["recent_move"] = get_recent_move(
            df_hist, pd.Timestamp(str(expiry_date))
        )
    except Exception:
        snap["recent_move"] = None

    # ציון סיכון מאירועים
    try:
        from events import compute_risk_score              # noqa: PLC0415
        risk = compute_risk_score(exp_dt or expiry_date, engine)
        snap["risk_score"]    = risk.get("score")
        snap["risk_level"]    = risk.get("level")
        snap["nearby_events"] = risk.get("nearby_events", [])
    except Exception:
        snap["risk_score"]    = None
        snap["risk_level"]    = None
        snap["nearby_events"] = []

    return snap


# ─── Skipped-trade helper ──────────────────────────────────────────────

def _insert_skipped(
    portfolio_id: int,
    strategy_id: int,
    exp_dt: Optional[date],
    atm: dict,
    snapshot: dict,
    engine,
) -> None:
    """מכניס רשומת עסקה עם status='skipped' לתיעוד ה-snapshot."""
    try:
        insert_trade(
            {
                "portfolio_id":         portfolio_id,
                "strategy_id":          strategy_id,
                "strategy_name":        STRATEGIES[strategy_id].name,
                "expiry_date":          exp_dt,
                "opened_at":            datetime.now(tz=timezone.utc),
                "entry_index":          round(float(atm.get("index_estimate", atm.get("strike", 0))), 2),
                "entry_cost":           0.0,
                "legs_json":            [],
                "max_profit":           None,
                "max_loss":             None,
                "status":               "skipped",
                "closed_at":            None,
                "close_index":          None,
                "pnl":                  None,
                "pnl_pct":              None,
                "market_snapshot_json": snapshot,
                "num_legs":             0,
                "entry_commission":     0.0,
                "exit_commission":      None,
            },
            engine=engine,
        )
    except Exception:
        pass


# ─── Public API ────────────────────────────────────────────────────────

def compute_balance(portfolio: dict, trades: list[dict]) -> float:
    """מחשב את יתרת התיק כנגזרת מהעסקאות — מקור האמת היחיד ליתרה.

    הנוסחה:
        balance = initial_balance
                  − Σ(entry_cost + entry_commission)  של עסקאות פתוחות
                  + Σ(pnl)                            של עסקאות סגורות

    עסקה סגורה: ה-pnl כבר מגלם את כל העלויות והעמלות (כניסה + יציאה),
    לכן עבורה נספר ה-pnl בלבד — לא מנכים שוב את עלות הכניסה (אין כפילות).
    עסקאות בסטטוס אחר (skipped/db_error/error) אינן משפיעות על היתרה.
    ערכי None מטופלים כ-0. מחזיר 0.0 אם portfolio ריק.
    """
    initial = float((portfolio or {}).get("initial_balance") or 0.0)
    balance = initial
    for t in (trades or []):
        status = t.get("status")
        if status == "open":
            entry_cost       = float(t.get("entry_cost") or 0.0)
            entry_commission = float(t.get("entry_commission") or 0.0)
            balance -= entry_cost + entry_commission
        elif status == "closed":
            balance += float(t.get("pnl") or 0.0)
    return round(balance, 4)


def open_trades_for_expiry(
    expiry_date,
    chain: dict,
    portfolios: list[dict],
    engine=None,
) -> list[dict]:
    """פותחת עסקה לכל אחת מהאסטרטגיות שהתיק מוגדר להריץ (portfolio["strategy_ids"]).

    תיק ללא strategy_ids (או ריק) → כל 6 האסטרטגיות (תאימות לאחור).
    מחזיר רשימת תוצאות עם status לכל (portfolio_id, strategy_id).
    """
    if not portfolios:
        return []

    expiry_entry = _find_chain_entry(chain, expiry_date)
    if expiry_entry is None:
        return []

    chain_df = expiry_entry["chain"]
    atm      = find_atm(chain_df)
    if not atm:
        return []

    # engine אחד משותף לכל השאילתות/ההכנסות בריצה — מונע יצירת pool חדש בכל קריאה
    # (מצטבר מול ה-Supabase pooler וגורם לכשלי-חיבור שנבלעים כ-db_error).
    eng = _make_engine(engine)

    snapshot = _build_snapshot(expiry_date, expiry_entry, atm, chain_df, eng)
    exp_dt   = _parse_date(expiry_date)
    results: list[dict] = []

    for portfolio in portfolios:
        portfolio_id       = portfolio["id"]
        _cpv = portfolio.get("commission_per_leg")
        commission_per_leg = float(_cpv if _cpv is not None else 2.5)

        # שאילתה אחת לכל תיק — מניעת כפילויות
        existing = get_trades(
            portfolio_id=portfolio_id,
            expiry_date=str(exp_dt),
            engine=eng,
        )
        existing_sids = {t.get("strategy_id") for t in existing}

        # עוברים רק על האסטרטגיות שהתיק מוגדר להריץ (null-safe → כל ה-6).
        for strategy_id in _portfolio_strategy_ids(portfolio):
            # ─── מניעת כפילות ───────────────────────────────────────
            if strategy_id in existing_sids:
                results.append({
                    "portfolio_id": portfolio_id,
                    "strategy_id":  strategy_id,
                    "status":       "duplicate",
                })
                continue

            try:
                params   = strategy_payoff_params(strategy_id, atm, chain_df)
                cost_pts = _entry_cost_pts(strategy_id, params)

                # ─── בדיקת תקינות מחיר ──────────────────────────────
                if not params or abs(cost_pts) < 0.001:
                    snap_skip = {**snapshot, "skip_reason": "missing price data"}
                    _insert_skipped(portfolio_id, strategy_id, exp_dt, atm, snap_skip, eng)
                    results.append({
                        "portfolio_id": portfolio_id,
                        "strategy_id":  strategy_id,
                        "status":       "skipped",
                    })
                    continue

                entry_cost = round(cost_pts * MULTIPLIER, 2)
                legs       = strategy_legs_detail(strategy_id, atm, chain_df)
                summary    = strategy_summary(strategy_id, atm, chain_df)

                # ─── עמלת כניסה ─────────────────────────────────────
                num_legs         = len(legs)
                entry_commission = round(num_legs * commission_per_leg, 2)

                inserted = insert_trade(
                    {
                        "portfolio_id":         portfolio_id,
                        "strategy_id":          strategy_id,
                        "strategy_name":        STRATEGIES[strategy_id].name,
                        "expiry_date":          exp_dt,
                        "opened_at":            datetime.now(tz=timezone.utc),
                        "entry_index":          round(float(atm.get("index_estimate", atm["strike"])), 2),
                        "entry_cost":           entry_cost,
                        "legs_json":            legs,
                        "max_profit":           summary.get("max_profit_nis"),
                        "max_loss":             summary.get("max_loss_nis"),
                        "status":               "open",
                        "closed_at":            None,
                        "close_index":          None,
                        "pnl":                  None,
                        "pnl_pct":              None,
                        "market_snapshot_json": snapshot,
                        "num_legs":             num_legs,
                        "entry_commission":     entry_commission,
                        "exit_commission":      None,
                    },
                    engine=eng,
                )

                if inserted is None:
                    results.append({
                        "portfolio_id": portfolio_id,
                        "strategy_id":  strategy_id,
                        "status":       "db_error",
                    })
                    continue

                # היתרה אינה מעודכנת כאן — היא נגזרת מהעסקאות (compute_balance).
                results.append(inserted)

            except Exception:
                results.append({
                    "portfolio_id": portfolio_id,
                    "strategy_id":  strategy_id,
                    "status":       "error",
                })

    return results


def close_trades_for_expiry(
    expiry_date,
    close_index: float,
    engine=None,
) -> list[dict]:
    """סוגרת את כל העסקאות הפתוחות לפקיעה לפי מחיר הנעילה.

    מחשב payoff גולמי מהרגליים ו-PnL, ושומר אותם בעסקה (status='closed').
    היתרה אינה מעודכנת ישירות — היא נגזרת מה-pnl דרך compute_balance.
    """
    # engine אחד משותף לכל הסגירות — מונע יצירת pool חדש בכל קריאה.
    eng = _make_engine(engine)

    open_trades = get_open_trades_for_expiry(expiry_date, engine=eng)
    results: list[dict] = []

    for trade in open_trades:
        try:
            legs             = trade.get("legs_json") or []
            payoff           = _payoff_from_legs(legs, float(close_index))
            entry_cost       = float(trade.get("entry_cost") or 0.0)
            entry_commission = float(trade.get("entry_commission") or 0.0)
            num_legs         = int(trade.get("num_legs") or len(legs))

            trade_id     = trade["id"]
            portfolio_id = trade["portfolio_id"]

            # ─── עמלת יציאה מהתיק ────────────────────────────────────
            portfolio          = get_portfolio(portfolio_id, engine=eng)
            _cpv = (portfolio or {}).get("commission_per_leg")
            commission_per_leg = float(_cpv if _cpv is not None else 2.5)
            exit_commission    = round(num_legs * commission_per_leg, 2)

            pnl     = round(payoff - entry_cost - entry_commission - exit_commission, 2)
            pnl_pct = (
                round(pnl / abs(entry_cost), 4)
                if abs(entry_cost) > 0.001
                else None
            )

            ok = close_trade(
                trade_id, float(close_index), pnl, pnl_pct,
                exit_commission, engine=eng,
            )

            # היתרה אינה מעודכנת כאן — היא נגזרת מהעסקאות (compute_balance).
            # ה-pnl נשמר בעסקה (close_trade) ומשם compute_balance גוזר את היתרה.

            results.append({
                "trade_id":       trade_id,
                "strategy_id":    trade.get("strategy_id"),
                "strategy_name":  trade.get("strategy_name"),
                "payoff":         round(payoff, 2),
                "exit_commission": exit_commission,
                "pnl":            pnl,
                "pnl_pct":        pnl_pct,
                "status":         "closed" if ok else "error",
            })

        except Exception:
            results.append({"trade_id": trade.get("id"), "status": "error"})

    return results


# ─── Analytics helpers ─────────────────────────────────────────────────

def _norm_ts(ts) -> datetime:
    """ממיר ערך timestamp מכל פורמט ל-datetime."""
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if hasattr(ts, "to_pydatetime"):
        return ts.to_pydatetime()
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def build_equity_curve(
    trades: list[dict],
    initial_balance: float,
) -> list[dict]:
    """בונה עקומת שווי תיק מעסקאות סגורות.

    מחזיר list[{"ts": datetime, "balance": float}] ממוין כרונולוגית.
    כל נקודה מייצגת את היתרה המצטברת אחרי סגירת עסקה.
    מחזיר [] אם אין עסקאות סגורות תקינות.
    """
    valid = [
        t for t in trades
        if t.get("status") == "closed"
        and t.get("pnl") is not None
        and t.get("closed_at") is not None
    ]
    if not valid:
        return []

    valid_sorted = sorted(valid, key=lambda t: _norm_ts(t["closed_at"]))

    points: list[dict] = []
    balance = initial_balance
    for t in valid_sorted:
        balance = round(balance + float(t["pnl"]), 2)
        points.append({"ts": _norm_ts(t["closed_at"]), "balance": balance})

    return points


def build_track_record(trades: list[dict]) -> list[dict]:
    """מרכז ביצועים לפי אסטרטגיה מעסקאות סגורות.

    מחזיר list[dict] ממוין לפי total_pnl יורד, שדות:
      strategy_name, total, wins, win_rate, total_pnl, avg_pnl
    """
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        if t.get("status") == "closed":
            name = t.get("strategy_name") or "לא ידוע"
            groups[name].append(t)

    rows = []
    for name, group in groups.items():
        pnls = [float(t["pnl"]) for t in group if t.get("pnl") is not None]
        n         = len(pnls)
        wins      = sum(1 for p in pnls if p > 0)
        total_pnl = round(sum(pnls), 2) if pnls else 0.0
        avg_pnl   = round(total_pnl / n, 2) if n > 0 else 0.0
        rows.append({
            "strategy_name": name,
            "total":         len(group),
            "wins":          wins,
            "win_rate":      round(wins / n, 4) if n > 0 else 0.0,
            "total_pnl":     total_pnl,
            "avg_pnl":       avg_pnl,
        })

    return sorted(rows, key=lambda r: r["total_pnl"], reverse=True)


# ─── Trade-detail helpers (תצוגת פירוט לפי פקיעה) ──────────────────────

def group_trades_by_portfolio(trades: list[dict]) -> dict[int, list[dict]]:
    """מקבץ רשימת עסקאות לפי portfolio_id (לשאילתה אחת במקום אחת-לכל-תיק).

    מחזיר dict{portfolio_id: [trades...]} תוך שמירת סדר העסקאות. עסקאות ללא
    portfolio_id מדולגות. מחזיר {} אם הקלט ריק.
    """
    grouped: dict[int, list[dict]] = {}
    for t in (trades or []):
        pid = t.get("portfolio_id")
        if pid is None:
            continue
        grouped.setdefault(pid, []).append(t)
    return grouped


def trade_expiries(trades: list[dict]) -> list[str]:
    """מחזיר תאריכי פקיעה ייחודיים (כמחרוזת) שיש להם עסקה, ממוינים כרונולוגית.

    מתעלם מערכי None. ממיין לפי התאריך המפורסר (לא לקסיקוגרפית).
    """
    uniq = {
        str(t["expiry_date"])
        for t in (trades or [])
        if t.get("expiry_date") is not None
    }
    return sorted(uniq, key=lambda s: (_parse_date(s) or date.max))


def nearest_expiry(expiries: list[str], today: Optional[date] = None) -> Optional[str]:
    """מחזיר את הפקיעה הקרובה ביותר להיום (מרחק ימים מינימלי); None אם הרשימה ריקה.

    תאריך שלא ניתן לפרסור נדחק לסוף (מרחק ענק) כדי לא להיבחר בטעות.
    """
    if not expiries:
        return None
    ref = today or date.today()

    def _dist(s: str) -> int:
        d = _parse_date(s)
        return abs((d - ref).days) if d else 10 ** 9

    return min(expiries, key=_dist)


def build_legs_chart_data(legs: list[dict]) -> list[dict]:
    """ממיר legs_json לנקודות תרשים-מבנה על ציר הסטרייקים.

    לכל רגל: {strike, action, type, qty, y, label}.
    y = +qty לרגל 'קנה' (מעל הציר), −qty לרגל 'מכור' (מתחת לציר) — להמחשה ויזואלית.
    רגל ללא strike תקין מדולגת. מחזיר [] אם אין רגליים.
    """
    out: list[dict] = []
    for leg in (legs or []):
        try:
            strike = float(leg.get("strike"))
        except (TypeError, ValueError):
            continue
        action = leg.get("action", "")
        otype  = leg.get("type", "")
        try:
            qty = int(leg.get("qty", 1) or 1)
        except (TypeError, ValueError):
            qty = 1
        sign = 1 if action == "קנה" else -1
        out.append({
            "strike": strike,
            "action": action,
            "type":   otype,
            "qty":    qty,
            "y":      sign * qty,
            "label":  f"{action} {otype} {strike:,.0f}",
        })
    return out


def build_trade_payoff_curve(
    legs: list[dict],
    entry_cost: float,
    center_index: float,
    pct: float = 0.10,
    n: int = 241,
) -> dict:
    """בונה עקומת P&L נטו לעסקה על טווח ±pct סביב center_index.

    משתמש ב-_payoff_from_legs הקיים (payoff גולמי בש"ח) ומחסיר entry_cost —
    אינו מחשב payoff מאפס. ה-entry_cost כבר בש"ח (חיובי=שולמה פרמיה,
    שלילי=התקבלה פרמיה כמו Iron Condor).

    מחזיר {"x", "y", "max_profit", "max_loss", "breakevens"};
    ריק אם אין רגליים או center_index לא תקין.
    """
    empty = {"x": [], "y": [], "max_profit": None, "max_loss": None, "breakevens": []}
    if not legs or not center_index or center_index <= 0 or n < 2:
        return empty

    lo = center_index * (1 - pct)
    hi = center_index * (1 + pct)
    xs = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    ec = float(entry_cost or 0.0)
    ys = [_payoff_from_legs(legs, x) - ec for x in xs]

    return {
        "x":           xs,
        "y":           ys,
        "max_profit":  max(ys),
        "max_loss":    min(ys),
        "breakevens":  find_breakevens(xs, ys),
    }
