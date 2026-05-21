"""
Payoff Diagrams לאסטרטגיות אופציות — TA-35 Expiry Intelligence.

מחשב רווח/הפסד תיאורטי בפקיעה לפי מחיר המדד, ובונה גרף Plotly.

API ציבורי:
  payoff_*           — חישוב P&L נקי (numpy, ניתן לבדיקה)
  find_breakevens    — מאתר נקודות Breakeven
  strategy_payoff_params  — חילוץ סטרייקים/פרמיות מה-chain
  strategy_legs_detail    — פירוט רגליים לתצוגה
  strategy_summary        — סיכום עסקה מלא
  build_payoff_fig        — גרף Plotly מלא
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import plotly.graph_objects as go

MULTIPLIER = 50  # ₪ לנקודה — זהה ל-options_parser

_DARK_BG = "#0e1117"
_PLOT_BG = "#111827"
_GRID    = "#1e2d45"
_AXIS    = "#7a9ab8"
_GREEN   = "#27ae60"
_RED     = "#e74c3c"
_GOLD    = "#c9a84c"

# קטגוריות אסטרטגיה לחישוב Breakeven description
_NEUTRAL_IDS  = frozenset({2, 3, 4})
_VOLATILE_IDS = frozenset({5, 6})
_BULLISH_IDS  = frozenset({1})
_UNLIMITED_PROFIT_IDS = frozenset({5, 6})


# ─── טווח מחירים ─────────────────────────────────────────────────────────

def price_range(atm: float, pct: float = 0.10, n: int = 400) -> np.ndarray:
    """מחזיר מערך מחירים ±pct% מסביב ל-ATM."""
    return np.linspace(atm * (1 - pct), atm * (1 + pct), n)


# ─── פונקציות Payoff (טהורות) ────────────────────────────────────────────

def payoff_bull_call_spread(
    S: np.ndarray,
    K_long: float,
    K_short: float,
    cost_pts: float,
    multiplier: int = MULTIPLIER,
) -> np.ndarray:
    """
    רווח/הפסד Bull Call Spread לפי מחיר S.

    K_long  — Call שנקנה (ATM)
    K_short — Call שנמכר (ATM + width)
    cost_pts — פרמיה נטו ששולמה (נקודות)
    """
    expiry = np.maximum(S - K_long, 0) - np.maximum(S - K_short, 0)
    return (expiry - cost_pts) * multiplier


def payoff_iron_condor(
    S: np.ndarray,
    K_lp: float,
    K_sp: float,
    K_sc: float,
    K_lc: float,
    credit_pts: float,
    multiplier: int = MULTIPLIER,
) -> np.ndarray:
    """
    רווח/הפסד Short Iron Condor לפי מחיר S.

    K_lp < K_sp  — Long/Short Put
    K_sc < K_lc  — Short/Long Call
    credit_pts   — פרמיה נטו שהתקבלה
    """
    expiry = (
        np.maximum(K_lp - S, 0)
        - np.maximum(K_sp - S, 0)
        - np.maximum(S - K_sc, 0)
        + np.maximum(S - K_lc, 0)
    )
    return (expiry + credit_pts) * multiplier


def payoff_call_butterfly(
    S: np.ndarray,
    K_lo: float,
    K_mid: float,
    K_hi: float,
    cost_pts: float,
    multiplier: int = MULTIPLIER,
) -> np.ndarray:
    """
    רווח/הפסד Long Call Butterfly לפי מחיר S.

    K_lo < K_mid < K_hi — קנה K_lo, מכור 2× K_mid, קנה K_hi
    cost_pts — פרמיה נטו ששולמה
    """
    expiry = (
        np.maximum(S - K_lo, 0)
        - 2 * np.maximum(S - K_mid, 0)
        + np.maximum(S - K_hi, 0)
    )
    return (expiry - cost_pts) * multiplier


def payoff_put_butterfly(
    S: np.ndarray,
    K_lo: float,
    K_mid: float,
    K_hi: float,
    cost_pts: float,
    multiplier: int = MULTIPLIER,
) -> np.ndarray:
    """
    רווח/הפסד Long Put Butterfly לפי מחיר S.

    K_lo < K_mid < K_hi — קנה K_hi, מכור 2× K_mid, קנה K_lo
    cost_pts — פרמיה נטו ששולמה
    """
    expiry = (
        np.maximum(K_hi - S, 0)
        - 2 * np.maximum(K_mid - S, 0)
        + np.maximum(K_lo - S, 0)
    )
    return (expiry - cost_pts) * multiplier


def payoff_straddle(
    S: np.ndarray,
    K: float,
    cost_pts: float,
    multiplier: int = MULTIPLIER,
) -> np.ndarray:
    """
    רווח/הפסד Long Straddle לפי מחיר S.

    K — סטרייק ATM (קנה Call + Put)
    cost_pts — סכום הפרמיות
    """
    expiry = np.maximum(S - K, 0) + np.maximum(K - S, 0)
    return (expiry - cost_pts) * multiplier


def payoff_strangle(
    S: np.ndarray,
    K_put: float,
    K_call: float,
    cost_pts: float,
    multiplier: int = MULTIPLIER,
) -> np.ndarray:
    """
    רווח/הפסד Long Strangle לפי מחיר S.

    K_put < K_call — Put OTM + Call OTM
    cost_pts — סכום הפרמיות
    """
    expiry = np.maximum(K_put - S, 0) + np.maximum(S - K_call, 0)
    return (expiry - cost_pts) * multiplier


# ─── Breakeven ────────────────────────────────────────────────────────────

def find_breakevens(S: np.ndarray, y: np.ndarray) -> list[float]:
    """
    מאתר נקודות ה-Breakeven בקירוב לינארי (שינוי סימן ב-y).

    אזורים שטוחים ב-y>0 (Iron Condor) אינם מפעילים את התנאי
    כי מכפלת שני ערכים חיוביים אינה שלילית.
    """
    breakevens: list[float] = []
    for i in range(len(y) - 1):
        y0, y1 = float(y[i]), float(y[i + 1])
        if y0 * y1 < 0:
            x_be = S[i] + (S[i + 1] - S[i]) * (-y0) / (y1 - y0)
            breakevens.append(float(x_be))
    return breakevens


# ─── חילוץ פרמטרים מה-chain ──────────────────────────────────────────────

def strategy_payoff_params(
    strategy_id: int,
    atm: dict,
    chain: "pd.DataFrame",
) -> dict:
    """
    מחזיר פרמטרי סטרייקים ופרמיות נטו לאסטרטגיה מה-chain.

    משקף את לוגיקת הבחירה ב-options_parser.get_strategy_strikes.
    מחזיר dict ריק אם הנתונים חסרים.
    """
    def nearest(target: float, side: str) -> tuple[float, float]:
        col = f"{side}_price"
        sub = chain[chain[col] > 0].copy()
        if sub.empty:
            return target, 0.0
        idx = (sub["strike"] - target).abs().idxmin()
        row = sub.loc[idx]
        return float(row["strike"]), float(row[col]) / MULTIPLIER

    def pct_k(pct: float) -> float:
        return round(atm_s * (1 + pct / 100) / 10) * 10

    atm_s = atm["strike"]
    K_atm_c, P_atm_c = nearest(atm_s, "call")
    K_atm_p, P_atm_p = nearest(atm_s, "put")

    if strategy_id == 1:
        K_short, P_short = nearest(atm_s + 30, "call")
        return {"K_long": K_atm_c, "K_short": K_short,
                "cost_pts": max(P_atm_c - P_short, 0.01)}

    if strategy_id == 2:
        K_sc, P_sc = nearest(pct_k(+2.0), "call")
        K_sp, P_sp = nearest(pct_k(-2.0), "put")
        K_wc, P_wc = nearest(pct_k(+3.0), "call")
        K_wp, P_wp = nearest(pct_k(-3.0), "put")
        return {"K_lp": K_wp, "K_sp": K_sp, "K_sc": K_sc, "K_lc": K_wc,
                "credit_pts": (P_sp + P_sc) - (P_wp + P_wc)}

    if strategy_id == 3:
        K_lo, P_lo = nearest(pct_k(-1.0), "call")
        K_hi, P_hi = nearest(pct_k(+1.0), "call")
        return {"K_lo": K_lo, "K_mid": K_atm_c, "K_hi": K_hi,
                "cost_pts": P_lo + P_hi - 2 * P_atm_c}

    if strategy_id == 4:
        K_hi_put, P_hi_put = nearest(pct_k(+1.0), "put")
        K_lo_put, P_lo_put = nearest(pct_k(-1.0), "put")
        return {"K_lo": K_lo_put, "K_mid": K_atm_p, "K_hi": K_hi_put,
                "cost_pts": P_hi_put + P_lo_put - 2 * P_atm_p}

    if strategy_id == 5:
        return {"K": K_atm_c, "cost_pts": P_atm_c + P_atm_p}

    if strategy_id == 6:
        K_otm_c, P_otm_c = nearest(pct_k(+1.5), "call")
        K_otm_p, P_otm_p = nearest(pct_k(-1.5), "put")
        return {"K_call": K_otm_c, "K_put": K_otm_p,
                "cost_pts": P_otm_c + P_otm_p}

    return {}


# ─── פירוט רגליים ─────────────────────────────────────────────────────────

def strategy_legs_detail(
    strategy_id: int,
    atm: dict,
    chain: "pd.DataFrame",
    multiplier: int = MULTIPLIER,
) -> list[dict]:
    """
    מחזיר רשימת רגליים לאסטרטגיה עם פרטי פעולה, סוג, סטרייק ומחיר.

    כל רגל: {"action": str, "type": str, "qty": int, "strike": float,
              "price_pts": float, "price_nis": float}
    """
    def nearest(target: float, side: str) -> tuple[float, float]:
        col = f"{side}_price"
        sub = chain[chain[col] > 0].copy()
        if sub.empty:
            return target, 0.0
        idx = (sub["strike"] - target).abs().idxmin()
        row = sub.loc[idx]
        return float(row["strike"]), float(row[col]) / multiplier

    def pct_k(pct: float) -> float:
        return round(atm_s * (1 + pct / 100) / 10) * 10

    def _leg(action: str, side: str, strike: float, price_pts: float, qty: int = 1) -> dict:
        return {
            "action":    action,
            "type":      "Call" if side == "call" else "Put",
            "qty":       qty,
            "strike":    strike,
            "price_pts": round(price_pts, 1),
            "price_nis": round(price_pts * multiplier * qty, 0),
        }

    atm_s = atm["strike"]
    K_atm_c, P_atm_c = nearest(atm_s, "call")
    K_atm_p, P_atm_p = nearest(atm_s, "put")

    if strategy_id == 1:
        K_sh, P_sh = nearest(atm_s + 30, "call")
        return [_leg("קנה",  "call", K_atm_c, P_atm_c),
                _leg("מכור", "call", K_sh,    P_sh)]

    if strategy_id == 2:
        K_sc, P_sc = nearest(pct_k(+2.0), "call")
        K_sp, P_sp = nearest(pct_k(-2.0), "put")
        K_wc, P_wc = nearest(pct_k(+3.0), "call")
        K_wp, P_wp = nearest(pct_k(-3.0), "put")
        return [_leg("קנה",  "put",  K_wp, P_wp),
                _leg("מכור", "put",  K_sp, P_sp),
                _leg("מכור", "call", K_sc, P_sc),
                _leg("קנה",  "call", K_wc, P_wc)]

    if strategy_id == 3:
        K_lo, P_lo = nearest(pct_k(-1.0), "call")
        K_hi, P_hi = nearest(pct_k(+1.0), "call")
        return [_leg("קנה",  "call", K_lo,    P_lo),
                _leg("מכור", "call", K_atm_c, P_atm_c, qty=2),
                _leg("קנה",  "call", K_hi,    P_hi)]

    if strategy_id == 4:
        K_hi_p, P_hi_p = nearest(pct_k(+1.0), "put")
        K_lo_p, P_lo_p = nearest(pct_k(-1.0), "put")
        return [_leg("קנה",  "put", K_hi_p,  P_hi_p),
                _leg("מכור", "put", K_atm_p, P_atm_p, qty=2),
                _leg("קנה",  "put", K_lo_p,  P_lo_p)]

    if strategy_id == 5:
        return [_leg("קנה", "call", K_atm_c, P_atm_c),
                _leg("קנה", "put",  K_atm_p, P_atm_p)]

    if strategy_id == 6:
        K_oc, P_oc = nearest(pct_k(+1.5), "call")
        K_op, P_op = nearest(pct_k(-1.5), "put")
        return [_leg("קנה", "call", K_oc, P_oc),
                _leg("קנה", "put",  K_op, P_op)]

    return []


def format_legs(legs: list[dict]) -> str:
    """מייצר מחרוזת "מה לקנות בפועל" מרשימת הרגליים."""
    parts = []
    for lg in legs:
        qty = f"×{lg['qty']}" if lg["qty"] > 1 else "1"
        parts.append(
            f"{lg['action']} {qty} {lg['type']} {lg['strike']:,.0f} "
            f"@ {lg['price_pts']:.1f} נק' ({lg['price_nis']:,.0f} ₪)"
        )
    return " | ".join(parts)


# ─── תיאור Breakeven באחוזים ──────────────────────────────────────────────

def _breakeven_pct_desc(
    strategy_id: int,
    bes: list[float],
    atm_s: float,
    index_now: float,
) -> str:
    """מחזיר תיאור עברי של תנועה נדרשת ל-Breakeven."""
    if not bes:
        return "—"

    bes_sorted = sorted(bes)

    if strategy_id in _NEUTRAL_IDS:
        if len(bes_sorted) >= 2:
            lo, hi = bes_sorted[0], bes_sorted[-1]
            if lo <= index_now <= hi:
                pct_lo = (index_now - lo) / atm_s * 100
                pct_hi = (hi - index_now) / atm_s * 100
                max_move = min(pct_lo, pct_hi)
                return f"המדד צריך לזוז פחות מ-{max_move:.1f}% כדי להרוויח"
            return "המדד מחוץ לטווח הרווח"
        return "—"

    if strategy_id in _VOLATILE_IDS:
        if len(bes_sorted) >= 2:
            lo, hi = bes_sorted[0], bes_sorted[-1]
            pct_up   = (hi - index_now) / atm_s * 100
            pct_down = (index_now - lo) / atm_s * 100
            min_move = min(pct_up, pct_down)
            return f"המדד צריך לזוז יותר מ-{min_move:.1f}% לכל כיוון"
        return "—"

    if strategy_id in _BULLISH_IDS:
        be = bes_sorted[0]
        up_pct = (be - index_now) / atm_s * 100
        if up_pct > 0:
            return f"המדד צריך לעלות מעל {up_pct:.1f}% כדי להרוויח"
        return "המדד כבר מעל נקודת ה-Breakeven"

    return "—"


# ─── סיכום עסקה ──────────────────────────────────────────────────────────

def strategy_summary(
    strategy_id: int,
    atm: dict,
    chain: "pd.DataFrame",
    multiplier: int = MULTIPLIER,
) -> dict:
    """
    מחזיר סיכום עסקה מלא לאסטרטגיה.

    {
      entry_cost_nis      — עלות/זיכוי כניסה בש"ח (חיובי=תשלום, שלילי=קבלה)
      max_profit_nis      — רווח מקסימלי בש"ח (על טווח ±10%)
      max_loss_nis        — הפסד מקסימלי בש"ח (שלילי)
      risk_reward         — יחס רווח/סיכון (None אם ללא הגבלה)
      breakevens          — רשימת מחירי Breakeven
      market_status       — "profit_zone" | "near_breakeven" | "loss_zone"
      be_pct_desc         — תיאור עברי של תנועה נדרשת
      y_now_nis           — P&L נוכחי (בנקודת המדד הנוכחית) בש"ח
      is_unlimited_profit — True לStraddle/Strangle
    }
    מחזיר dict ריק אם אין נתוני שרשרת.
    """
    params = strategy_payoff_params(strategy_id, atm, chain)
    if not params:
        return {}

    atm_s     = atm["strike"]
    index_now = float(atm.get("index_estimate", atm_s))
    S         = price_range(atm_s, pct=0.12, n=1000)

    dispatch = {
        1: lambda: payoff_bull_call_spread(S, params["K_long"],  params["K_short"],  params["cost_pts"],   multiplier),
        2: lambda: payoff_iron_condor(     S, params["K_lp"],    params["K_sp"],     params["K_sc"],       params["K_lc"], params["credit_pts"], multiplier),
        3: lambda: payoff_call_butterfly(  S, params["K_lo"],    params["K_mid"],    params["K_hi"],       params["cost_pts"], multiplier),
        4: lambda: payoff_put_butterfly(   S, params["K_lo"],    params["K_mid"],    params["K_hi"],       params["cost_pts"], multiplier),
        5: lambda: payoff_straddle(        S, params["K"],       params["cost_pts"], multiplier),
        6: lambda: payoff_strangle(        S, params["K_put"],   params["K_call"],   params["cost_pts"],   multiplier),
    }
    if strategy_id not in dispatch:
        return {}

    y = dispatch[strategy_id]()

    max_profit_nis = float(y.max())
    max_loss_nis   = float(y.min())
    bes            = sorted(find_breakevens(S, y))

    # עלות כניסה: Iron Condor מקבל פרמיה (שלילי = קבלה)
    if strategy_id == 2:
        entry_cost_nis = -params["credit_pts"] * multiplier
    else:
        entry_cost_nis = params["cost_pts"] * multiplier

    is_unlimited = strategy_id in _UNLIMITED_PROFIT_IDS

    # יחס רווח/סיכון
    if is_unlimited or max_loss_nis >= 0:
        risk_reward: Optional[float] = None
    else:
        risk_reward = round(max_profit_nis / abs(max_loss_nis), 2) if max_profit_nis > 0 else None

    # מצב נוכחי
    y_now = float(np.interp(index_now, S, y))
    near_thr = atm_s * 0.01  # 1% of ATM in absolute points
    if y_now > 0:
        status = "profit_zone"
    elif bes and min(abs(index_now - be) for be in bes) <= near_thr:
        status = "near_breakeven"
    else:
        status = "loss_zone"

    return {
        "entry_cost_nis":      round(entry_cost_nis, 0),
        "max_profit_nis":      round(max_profit_nis, 0),
        "max_loss_nis":        round(max_loss_nis, 0),
        "risk_reward":         risk_reward,
        "breakevens":          bes,
        "market_status":       status,
        "be_pct_desc":         _breakeven_pct_desc(strategy_id, bes, atm_s, index_now),
        "y_now_nis":           round(y_now, 0),
        "is_unlimited_profit": is_unlimited,
    }


# ─── בניית גרף Payoff ────────────────────────────────────────────────────

def build_payoff_fig(
    strategy_id: int,
    atm: dict,
    chain: "pd.DataFrame",
    multiplier: int = MULTIPLIER,
    index_price: Optional[float] = None,
    strategy_name: str = "",
) -> go.Figure:
    """
    בונה גרף Plotly של Payoff Diagram לאסטרטגיה.

    index_price    — מחיר המדד הנוכחי להצגה (ברירת מחדל: atm["index_estimate"]).
    strategy_name  — כותרת הגרף (שם האסטרטגיה).
    מחזיר Figure ריק עם הודעה אם הנתונים חסרים.
    """
    params = strategy_payoff_params(strategy_id, atm, chain)
    atm_s  = atm["strike"]
    idx_px = index_price if index_price is not None else float(atm.get("index_estimate", atm_s))
    S      = price_range(atm_s, pct=0.10)

    dispatch = {
        1: lambda: payoff_bull_call_spread(S, params["K_long"],  params["K_short"],  params["cost_pts"],   multiplier),
        2: lambda: payoff_iron_condor(     S, params["K_lp"],    params["K_sp"],     params["K_sc"],       params["K_lc"], params["credit_pts"], multiplier),
        3: lambda: payoff_call_butterfly(  S, params["K_lo"],    params["K_mid"],    params["K_hi"],       params["cost_pts"], multiplier),
        4: lambda: payoff_put_butterfly(   S, params["K_lo"],    params["K_mid"],    params["K_hi"],       params["cost_pts"], multiplier),
        5: lambda: payoff_straddle(        S, params["K"],       params["cost_pts"], multiplier),
        6: lambda: payoff_strangle(        S, params["K_put"],   params["K_call"],   params["cost_pts"],   multiplier),
    }

    if not params or strategy_id not in dispatch:
        fig = go.Figure()
        fig.add_annotation(text="אין נתוני שרשרת מספיקים לחישוב Payoff", showarrow=False,
                           font=dict(color="#aaa", size=16))
        return _apply_dark_layout(fig, atm_s, strategy_name)

    y = dispatch[strategy_id]()
    fig = go.Figure()

    # ── אזור רווח (ירוק שקוף) ─────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=S, y=np.where(y >= 0, y, 0),
        fill="tozeroy",
        fillcolor="rgba(39,174,96,0.20)",
        line=dict(color=_GREEN, width=2.5),
        name="רווח",
        hovertemplate="מדד: %{x:,.0f} נק'<br>רווח/הפסד: %{y:+,.0f} ₪<extra></extra>",
    ))

    # ── אזור הפסד (אדום שקוף) ────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=S, y=np.where(y <= 0, y, 0),
        fill="tozeroy",
        fillcolor="rgba(231,76,60,0.20)",
        line=dict(color=_RED, width=2.5),
        name="הפסד",
        hovertemplate="מדד: %{x:,.0f} נק'<br>רווח/הפסד: %{y:+,.0f} ₪<extra></extra>",
    ))

    # ── קו Breakeven ב-0 ──────────────────────────────────────────────
    fig.add_hline(y=0, line_dash="dash", line_color="#666", line_width=1.5)

    # ── ATM Strike (קו עדין) ─────────────────────────────────────────
    if abs(atm_s - idx_px) > atm_s * 0.002:  # הצג רק אם שונה מספיק ממחיר המדד
        fig.add_vline(
            x=atm_s,
            line_dash="dot",
            line_color="#4a6080",
            line_width=1,
            annotation_text=f"ATM {atm_s:,.0f}",
            annotation_font=dict(color="#4a6080", size=12),
            annotation_position="top left",
        )

    # ── מחיר המדד הנוכחי (זהב, בולט) ────────────────────────────────
    fig.add_vline(
        x=idx_px,
        line_dash="dash",
        line_color=_GOLD,
        line_width=2,
        annotation_text=f"מדד עכשיו: {idx_px:,.1f}",
        annotation_font=dict(color=_GOLD, size=13, family="Arial"),
        annotation_position="top right",
    )

    # ── תוויות מקסימום / מינימום ──────────────────────────────────────
    max_profit = float(y.max())
    max_loss   = float(y.min())
    idx_max    = int(np.argmax(y))
    idx_min    = int(np.argmin(y))

    if max_profit > 0:
        fig.add_annotation(
            x=S[idx_max], y=max_profit,
            text=f"רווח מקס'<br>{max_profit:+,.0f} ₪",
            showarrow=True, arrowhead=2,
            arrowcolor=_GREEN,
            font=dict(color=_GREEN, size=13),
            bgcolor="rgba(0,0,0,0.55)", bordercolor=_GREEN,
            ax=0, ay=-42,
        )

    if max_loss < 0:
        fig.add_annotation(
            x=S[idx_min], y=max_loss,
            text=f"הפסד מקס'<br>{max_loss:+,.0f} ₪",
            showarrow=True, arrowhead=2,
            arrowcolor=_RED,
            font=dict(color=_RED, size=13),
            bgcolor="rgba(0,0,0,0.55)", bordercolor=_RED,
            ax=0, ay=42,
        )

    # ── תוויות Breakeven (בולטות) ────────────────────────────────────
    for be in find_breakevens(S, y):
        fig.add_vline(
            x=be,
            line_dash="dash",
            line_color="white",
            line_width=2,
            annotation_text=f"BE {be:,.0f}",
            annotation_font=dict(color="white", size=12),
            annotation_position="bottom right",
        )

    return _apply_dark_layout(fig, atm_s, strategy_name)


def _apply_dark_layout(fig: go.Figure, atm_s: float, title: str = "") -> go.Figure:
    """מחיל עיצוב רקע כהה ותוויות עבריות על הגרף."""
    title_cfg = dict(
        text=title,
        font=dict(size=17, color="#e0e6f0", family="Arial"),
        x=0.5, xanchor="center",
    ) if title else None
    fig.update_layout(
        title=title_cfg,
        paper_bgcolor=_DARK_BG,
        plot_bgcolor=_PLOT_BG,
        font=dict(color="#c8d6e8", family="Arial", size=13),
        xaxis=dict(
            title=dict(text="מחיר מדד בפקיעה (נקודות)", font=dict(size=14)),
            tickformat=",",
            gridcolor=_GRID, linecolor=_GRID,
            zeroline=False, color=_AXIS,
        ),
        yaxis=dict(
            title=dict(text='רווח/הפסד (ש"ח)', font=dict(size=14)),
            tickformat=",.0f",
            gridcolor=_GRID, linecolor=_GRID,
            zeroline=False, color=_AXIS,
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color="#c8d6e8", size=13),
            orientation="h", yanchor="bottom", y=1.02,
        ),
        height=500,
        margin=dict(t=75 if title else 55, b=55, l=80, r=25),
        hovermode="x unified",
    )
    return fig
