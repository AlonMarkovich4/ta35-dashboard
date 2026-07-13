"""
דף Paper Trading — ניהול תיקי דמו
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from paper_db import (
    _make_engine,
    create_portfolio,
    get_expiries_ready_to_close,
    get_portfolio,
    get_portfolios,
    get_trades,
    has_paper_db,
)
from paper_trading import (
    build_equity_curve,
    build_legs_chart_data,
    build_track_record,
    build_trade_payoff_curve,
    close_matured_expiry,
    compute_balance,
    group_trades_by_portfolio,
    nearest_expiry,
    open_trades_for_expiry,
    summarize_closed_pnl,
    trade_expiries,
)
from strategies import BENCHMARK_STRATEGY_IDS, STRATEGIES
from supabase_loader import get_available_expiries, get_latest_option_chain
from styles import inject_global_css

# ─── Plotly dark theme constants (זהה ל-payoff.py) ──────────────────
_DARK_BG  = "#0e1117"
_PLOT_BG  = "#111827"
_GRID     = "#1e2d45"
_AXIS     = "#7a9ab8"
_GREEN    = "#27ae60"
_RED      = "#e74c3c"
_GOLD     = "#c9a84c"
_BLUE     = "#4a9fd4"

_STATUS_HE = {"open": "פתוח", "closed": "סגור", "skipped": "דולג"}

# מיפוי מזהה→שם אסטרטגיה + תווית בחירה לטופס (לפי הסדר 1..6)
_ALL_SIDS        = set(STRATEGIES.keys())
_STRATEGY_LABELS = {f"{sid}. {STRATEGIES[sid].name}": sid for sid in sorted(STRATEGIES)}


def _strategy_label(strategy_ids) -> str:
    """תיאור קריא של אסטרטגיות התיק: 'כל האסטרטגיות' או רשימת שמות.

    null-safe: ערך חסר/ריק → נחשב ככל האסטרטגיות.
    """
    ids = [s for s in (strategy_ids or []) if s in STRATEGIES]
    if not ids or set(ids) >= _ALL_SIDS:
        return "כל האסטרטגיות"
    return ", ".join(STRATEGIES[s].name for s in sorted(ids))

st.set_page_config(
    page_title="תיקי דמו — TA-35",
    page_icon="📊",
    layout="wide",
)
inject_global_css()


# ════════════════════════════════════════════════════════════════════════
#  Cached DB layer
# ════════════════════════════════════════════════════════════════════════
# engine יחיד משותף לכל הריצה (cache_resource — אובייקט חי עם connection pool,
# לא דאטה). הקריאות ל-DB עוברות דרך cache_data (ttl) כדי לא לרוץ בכל אינטראקציה.
# חשוב: ה-wrappers המ-cached *אינם* מקבלים engine כפרמטר — הם שולפים אותו פנימית
# מ-_engine(), כדי שלא לשבור את ה-hashing של cache_data על אובייקט ה-engine.
_CACHE_TTL = 60   # שניות — איזון בין רענון לבין מספר השאילתות


@st.cache_resource(show_spinner=False)
def _engine():
    """engine יחיד ומשותף לכל הריצה — נוצר פעם אחת ומשותף בין כל ה-reruns/sessions."""
    return _make_engine()


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _cached_portfolios() -> list[dict]:
    """רשימת התיקים, cached ל-_CACHE_TTL שניות (engine נשלף פנימית)."""
    return get_portfolios(engine=_engine())


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _cached_portfolio(pid: int) -> dict | None:
    """תיק בודד לפי id, cached."""
    return get_portfolio(pid, engine=_engine())


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _cached_trades(portfolio_id: int | None = None) -> list[dict]:
    """עסקאות (לכל התיקים, או לתיק יחיד), cached. portfolio_id ניתן ל-hash."""
    return get_trades(portfolio_id=portfolio_id, engine=_engine())


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _cached_expiries() -> list[str]:
    """פקיעות זמינות, cached (משתמש ב-engine המשותף)."""
    return get_available_expiries(engine=_engine())


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _cached_ready_to_close() -> list[dict]:
    """פקיעות שבשלו לסגירה (עסקאות פתוחות + סטלמנט זמין), cached."""
    return get_expiries_ready_to_close(engine=_engine())


def _clear_db_cache() -> None:
    """מנקה את cache הדאטה אחרי פעולת כתיבה כדי שהשינוי יופיע מיד.

    מנקה רק cache_data (הקריאות) — לא את cache_resource (ה-engine נשאר חי).
    """
    st.cache_data.clear()


# ════════════════════════════════════════════════════════════════════════
#  Helper renderers
# ════════════════════════════════════════════════════════════════════════

def _disclaimer_banner() -> None:
    st.markdown(
        """
        <div style='background:#1a2744;border:2px solid #c9a84c;border-radius:8px;
                    padding:10px 16px;margin-bottom:14px;text-align:right'>
        ⚠️ <strong style='color:#c9a84c'>כלי מחקר בלבד — לא ייעוץ השקעות</strong>
        <span style='color:#c8d6e8;font-size:0.88rem'>
         — כל הנתונים הם סימולציה היסטורית בלבד.
        </span></div>
        """,
        unsafe_allow_html=True,
    )


def _pnl_color(v: float) -> str:
    return _GREEN if v > 0 else (_RED if v < 0 else _AXIS)


def _sign(v: float) -> str:
    return "+" if v > 0 else ""


# ════════════════════════════════════════════════════════════════════════
#  Portfolio detail view
# ════════════════════════════════════════════════════════════════════════

def _render_summary_cards(
    trades: list[dict],
    initial: float,
    current: float,
    commission: float,
) -> None:
    """שורת כרטיסי סיכום (5 עמודות)."""
    pnl      = current - initial
    pnl_pct  = (pnl / initial * 100) if initial > 0 else 0.0
    total_t  = len(trades)
    closed   = [t for t in trades if t.get("status") == "closed"]
    wins     = sum(1 for t in closed if (t.get("pnl") or 0) > 0)
    win_rate = (wins / len(closed) * 100) if closed else None

    sign = _sign(pnl)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("שווי נוכחי", f"₪{current:,.0f}")
    c2.metric(
        "תשואה כוללת",
        f"{sign}₪{abs(pnl):,.0f}",
        delta=f"{sign}{pnl_pct:.1f}%",
        delta_color="normal",
    )
    c3.metric("עסקאות סה״כ", total_t)
    c4.metric(
        "Win Rate בפועל",
        f"{win_rate:.0f}%" if win_rate is not None else "—",
        help=f"{wins} רווחיות מתוך {len(closed)} סגורות",
    )
    c5.metric("עמלה לרגל", f"₪{commission:.1f}")


def _render_equity_curve(trades: list[dict], initial: float) -> None:
    """גרף עקומת שווי תיק (Plotly, dark theme)."""
    curve = build_equity_curve(trades, initial)

    fig = go.Figure()

    if not curve:
        # קו ישר ב-initial_balance עם הערה
        fig.add_trace(go.Scatter(
            x=[0, 1], y=[initial, initial],
            mode="lines",
            line=dict(color=_GOLD, width=2, dash="dot"),
            name=f"הון התחלתי ₪{initial:,.0f}",
        ))
        fig.add_annotation(
            text="טרם נסגרו עסקאות",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False,
            font=dict(color=_AXIS, size=15),
        )
    else:
        # נקודת פתיחה — יום לפני הסגירה הראשונה
        start_ts = curve[0]["ts"] - timedelta(days=1)
        xs = [start_ts] + [p["ts"] for p in curve]
        ys = [initial]  + [p["balance"] for p in curve]

        final_color = _GREEN if ys[-1] >= initial else _RED
        fill_color  = (
            "rgba(39,174,96,0.15)"  if ys[-1] >= initial
            else "rgba(231,76,60,0.15)"
        )

        # baseline (invisible) — target for fill
        fig.add_trace(go.Scatter(
            x=xs, y=[initial] * len(xs),
            mode="lines",
            line=dict(color=_GOLD, width=1.5, dash="dot"),
            showlegend=True,
            name=f"הון התחלתי ₪{initial:,.0f}",
            hoverinfo="skip",
        ))

        # equity curve עם fill לקו הבסיס
        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode="lines+markers",
            line=dict(color=_BLUE, width=2.5),
            marker=dict(size=7, color=_GOLD, symbol="circle"),
            fill="tonexty",
            fillcolor=fill_color,
            name="שווי תיק",
            hovertemplate="תאריך: %{x|%d/%m/%Y %H:%M}<br>שווי: ₪%{y:,.0f}<extra></extra>",
        ))

        # סמן יתרה סופית
        fig.add_annotation(
            x=xs[-1], y=ys[-1],
            text=f"₪{ys[-1]:,.0f}",
            showarrow=True, arrowhead=2,
            arrowcolor=final_color,
            font=dict(color=final_color, size=13),
            bgcolor="rgba(0,0,0,0.6)",
            bordercolor=final_color,
            ax=0, ay=-36,
        )

    fig.update_layout(
        paper_bgcolor=_DARK_BG,
        plot_bgcolor=_PLOT_BG,
        font=dict(color="#c8d6e8", family="Arial", size=12),
        height=340,
        margin=dict(t=30, b=50, l=80, r=25),
        xaxis=dict(
            title="תאריך סגירה",
            gridcolor=_GRID, linecolor=_GRID, zeroline=False, color=_AXIS,
        ),
        yaxis=dict(
            title='שווי תיק (₪)',
            tickformat=",.0f",
            gridcolor=_GRID, linecolor=_GRID, zeroline=False, color=_AXIS,
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color="#c8d6e8", size=11),
            orientation="h", yanchor="bottom", y=1.02,
        ),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_trade_table(trades: list[dict]) -> None:
    """טבלת עסקאות עם סינון לפי סטטוס."""
    if not trades:
        st.info("עדיין אין עסקאות בתיק זה — יתחילו להיפתח אוטומטית בימי שני.")
        return

    status_opts = {"הכל": None, "פתוח": "open", "סגור": "closed", "דולג": "skipped"}
    chosen_label = st.radio(
        "סינון לפי סטטוס:", list(status_opts.keys()),
        horizontal=True, index=0,
    )
    status_filter = status_opts[chosen_label]
    filtered = trades if status_filter is None else [
        t for t in trades if t.get("status") == status_filter
    ]

    if not filtered:
        st.info("אין עסקאות התואמות את הסינון.")
        return

    rows = []
    for t in filtered:
        ec   = t.get("entry_commission") or 0
        xc   = t.get("exit_commission")  or 0
        pnl  = t.get("pnl")
        pnlp = t.get("pnl_pct")
        rows.append({
            "אסטרטגיה":     t.get("strategy_name") or "—",
            "פקיעה":         str(t.get("expiry_date") or "—"),
            "סטטוס":         _STATUS_HE.get(t.get("status", ""), t.get("status", "—")),
            "עלות כניסה (₪)": t.get("entry_cost"),
            "עמלות (₪)":     round(ec + xc, 2),
            "PnL (₪)":       pnl,
            "PnL%":          f"{pnlp*100:+.1f}%" if pnlp is not None else "—",
        })

    df = pd.DataFrame(rows)

    def _color_pnl(v):
        if v is None or not isinstance(v, (int, float)):
            return ""
        return f"color: {_GREEN}" if v > 0 else (f"color: {_RED}" if v < 0 else "")

    styled = (
        df.style
        .map(_color_pnl, subset=["PnL (₪)"])
        .format(
            {
                "עלות כניסה (₪)": lambda v: f"₪{v:,.0f}" if v is not None else "—",
                "עמלות (₪)":     lambda v: f"₪{v:,.1f}" if v is not None else "—",
                "PnL (₪)":       lambda v: f"₪{v:+,.0f}" if v is not None else "—",
            }
        )
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_track_record(trades: list[dict]) -> None:
    """טבלת ביצועים מרוכזת לפי אסטרטגיה."""
    record = build_track_record(trades)
    if not record:
        st.info("עדיין אין עסקאות סגורות לניתוח.")
        return

    rows = []
    for r in record:
        sign = _sign(r["total_pnl"])
        rows.append({
            "אסטרטגיה":      r["strategy_name"],
            "עסקאות":         r["total"],
            "רווחיות":        r["wins"],
            "Win Rate":       f"{r['win_rate']*100:.0f}%",
            "סה״כ PnL (₪)":  r["total_pnl"],
            "ממוצע PnL (₪)": r["avg_pnl"],
        })

    df = pd.DataFrame(rows)

    def _color_total(v):
        if not isinstance(v, (int, float)):
            return ""
        return f"color: {_GREEN}" if v > 0 else (f"color: {_RED}" if v < 0 else "")

    styled = (
        df.style
        .map(_color_total, subset=["סה״כ PnL (₪)", "ממוצע PnL (₪)"])
        .format({
            "סה״כ PnL (₪)":  lambda v: f"₪{v:+,.0f}",
            "ממוצע PnL (₪)": lambda v: f"₪{v:+,.0f}",
        })
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_legs_table(legs: list[dict]) -> None:
    """טבלת רגליים צבעונית (קנה ירוק / מכור אדום)."""
    rows = []
    for lg in legs:
        rows.append({
            "פעולה":        lg.get("action") or "—",
            "סוג":          lg.get("type") or "—",
            "סטרייק":       lg.get("strike"),
            "כמות":         lg.get("qty", 1),
            "מחיר (נק׳)":   lg.get("price_pts"),
            "מחיר (₪)":     lg.get("price_nis"),
        })
    df = pd.DataFrame(rows)

    def _color_action(v):
        if v == "קנה":
            return f"color: {_GREEN}; font-weight: 700"
        if v == "מכור":
            return f"color: {_RED}; font-weight: 700"
        return ""

    styled = (
        df.style
        .map(_color_action, subset=["פעולה"])
        .format({
            "סטרייק":     lambda v: f"{v:,.0f}" if v is not None else "—",
            "מחיר (נק׳)": lambda v: f"{v:,.1f}" if v is not None else "—",
            "מחיר (₪)":   lambda v: f"₪{v:,.0f}" if v is not None else "—",
        })
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_legs_structure_chart(legs: list[dict], entry_index: float | None) -> None:
    """תרשים מבנה: כל רגל כסמן על ציר הסטרייקים (קנה למעלה / מכור למטה)."""
    data = build_legs_chart_data(legs)
    if not data:
        st.info("אין נתונים לתרשים מבנה.")
        return

    fig = go.Figure()
    for d in data:
        is_buy = d["y"] > 0
        color  = _GREEN if d["action"] == "קנה" else _RED
        fig.add_trace(go.Scatter(
            x=[d["strike"]], y=[d["y"]],
            mode="markers+text",
            marker=dict(
                size=20, color=color,
                symbol="triangle-up" if is_buy else "triangle-down",
                line=dict(color=_DARK_BG, width=1.5),
            ),
            text=[f"{d['type']} {d['strike']:,.0f}"],
            textposition="top center" if is_buy else "bottom center",
            textfont=dict(color="#c8d6e8", size=11),
            hovertext=[f"{d['action']} {d['qty']}× {d['type']} @ {d['strike']:,.0f}"],
            hoverinfo="text",
            showlegend=False,
        ))

    fig.add_hline(y=0, line_color=_AXIS, line_width=1)
    if entry_index:
        fig.add_vline(
            x=float(entry_index), line_dash="dash", line_color=_GOLD, line_width=2,
            annotation_text=f"מדד בכניסה {float(entry_index):,.0f}",
            annotation_font=dict(color=_GOLD, size=12),
            annotation_position="top right",
        )

    fig.update_layout(
        paper_bgcolor=_DARK_BG, plot_bgcolor=_PLOT_BG,
        font=dict(color="#c8d6e8", family="Arial", size=12),
        height=300, margin=dict(t=30, b=40, l=30, r=30),
        xaxis=dict(title="סטרייק", gridcolor=_GRID, linecolor=_GRID,
                   zeroline=False, color=_AXIS, tickformat=","),
        yaxis=dict(
            showgrid=False, zeroline=False, color=_AXIS,
            tickvals=[-2, -1, 0, 1, 2],
            ticktext=["מכור ×2", "מכור", "", "קנה", "קנה ×2"],
            range=[-2.6, 2.6],
        ),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_trade_payoff_chart(trade: dict, legs: list[dict]) -> None:
    """גרף payoff (P&L לפי מחיר המדד בפקיעה) בסגנון הכהה — מבוסס על הרגליים."""
    entry_cost   = float(trade.get("entry_cost") or 0.0)
    entry_index  = trade.get("entry_index")
    center       = float(entry_index or 0.0)
    if center <= 0:
        strikes = [float(l["strike"]) for l in legs if l.get("strike") is not None]
        center  = sum(strikes) / len(strikes) if strikes else 0.0

    curve = build_trade_payoff_curve(legs, entry_cost, center)
    if not curve["x"]:
        st.info("אין מספיק נתונים לגרף payoff.")
        return

    xs, ys = curve["x"], curve["y"]

    fig = go.Figure()
    # אזור רווח (ירוק) ואזור הפסד (אדום) — אותו סגנון כמו payoff.py
    fig.add_trace(go.Scatter(
        x=xs, y=[v if v >= 0 else 0 for v in ys],
        fill="tozeroy", fillcolor="rgba(39,174,96,0.20)",
        line=dict(color=_GREEN, width=2.5), name="רווח",
        hovertemplate="מדד: %{x:,.0f}<br>P&L: %{y:+,.0f} ₪<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=xs, y=[v if v <= 0 else 0 for v in ys],
        fill="tozeroy", fillcolor="rgba(231,76,60,0.20)",
        line=dict(color=_RED, width=2.5), name="הפסד",
        hovertemplate="מדד: %{x:,.0f}<br>P&L: %{y:+,.0f} ₪<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="#666", line_width=1.5)

    # קו מדד בכניסה
    if center > 0:
        fig.add_vline(
            x=center, line_dash="dash", line_color=_GOLD, line_width=2,
            annotation_text=f"מדד בכניסה {center:,.0f}",
            annotation_font=dict(color=_GOLD, size=12),
            annotation_position="top right",
        )

    # תוויות רווח/הפסד מרבי (על הטווח המוצג)
    mp, ml = curve["max_profit"], curve["max_loss"]
    if mp is not None and mp > 0:
        x_mp = xs[ys.index(mp)]
        fig.add_annotation(x=x_mp, y=mp, text=f"רווח מקס׳<br>{mp:+,.0f} ₪",
                           showarrow=True, arrowhead=2, arrowcolor=_GREEN,
                           font=dict(color=_GREEN, size=12),
                           bgcolor="rgba(0,0,0,0.55)", bordercolor=_GREEN, ax=0, ay=-38)
    if ml is not None and ml < 0:
        x_ml = xs[ys.index(ml)]
        fig.add_annotation(x=x_ml, y=ml, text=f"הפסד מקס׳<br>{ml:+,.0f} ₪",
                           showarrow=True, arrowhead=2, arrowcolor=_RED,
                           font=dict(color=_RED, size=12),
                           bgcolor="rgba(0,0,0,0.55)", bordercolor=_RED, ax=0, ay=38)

    fig.update_layout(
        paper_bgcolor=_DARK_BG, plot_bgcolor=_PLOT_BG,
        font=dict(color="#c8d6e8", family="Arial", size=12),
        height=300, margin=dict(t=30, b=40, l=70, r=25),
        xaxis=dict(title="מחיר מדד בפקיעה", gridcolor=_GRID, linecolor=_GRID,
                   zeroline=False, color=_AXIS, tickformat=","),
        yaxis=dict(title='רווח/הפסד (₪)', gridcolor=_GRID, linecolor=_GRID,
                   zeroline=False, color=_AXIS, tickformat=",.0f"),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#c8d6e8", size=11),
                    orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_single_trade_detail(trade: dict) -> None:
    """פירוט עסקה בודדת: כותרת + טבלת רגליים + תרשים מבנה + גרף payoff."""
    name   = trade.get("strategy_name") or "—"
    status = _STATUS_HE.get(trade.get("status", ""), trade.get("status", "—"))
    st.markdown(f"#### {name} — {status}")

    legs = trade.get("legs_json") or []
    if not legs:
        st.info("לעסקה זו אין פירוט רגליים (ייתכן שדולגה — לא היו נתוני מחיר).")
        return

    _render_legs_table(legs)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**מבנה הרגליים**")
        _render_legs_structure_chart(legs, trade.get("entry_index"))
    with c2:
        st.markdown("**גרף Payoff**")
        _render_trade_payoff_chart(trade, legs)


def _render_expiry_breakdown(trades: list[dict]) -> None:
    """אזור '🔍 פירוט לפי פקיעה' — בורר פקיעה + פירוט העסקה/ות שלה."""
    st.markdown("### 🔍 פירוט לפי פקיעה")

    expiries = trade_expiries(trades)
    if not expiries:
        st.info("אין עסקאות להצגה לפי פקיעה.")
        return

    default = nearest_expiry(expiries)
    idx     = expiries.index(default) if default in expiries else 0
    chosen  = st.selectbox("בחר פקיעה:", expiries, index=idx)

    day_trades = [t for t in trades if str(t.get("expiry_date")) == str(chosen)]
    if not day_trades:
        st.info("אין עסקה לפקיעה שנבחרה.")
        return

    for trade in day_trades:
        _render_single_trade_detail(trade)


def _render_portfolio_detail(pid: int) -> None:
    """תצוגה מלאה של תיק בודד."""
    # ── כפתור חזרה ──────────────────────────────────────────────────
    if st.button("← חזור לרשת התיקים"):
        st.session_state["selected_portfolio_id"] = None
        st.rerun()

    # ── טעינת נתונים (cached) ───────────────────────────────────────
    try:
        portfolio = _cached_portfolio(pid)
    except Exception:
        st.error("❌ שגיאה בטעינת נתוני התיק.")
        return

    if portfolio is None:
        st.error(f"תיק #{pid} לא נמצא.")
        return

    try:
        trades = _cached_trades(portfolio_id=pid)
    except Exception:
        trades = []
        st.warning("⚠️ שגיאה בטעינת עסקאות — מוצגים נתוני תיק בלבד.")

    name       = portfolio.get("name") or f"תיק #{pid}"
    initial    = float(portfolio.get("initial_balance") or 0)
    # היתרה נגזרת מהעסקאות — מקור אמת אחד (לא נקראת מ-current_balance שב-DB).
    current    = compute_balance(portfolio, trades)
    _cpv       = portfolio.get("commission_per_leg")
    commission = float(_cpv if _cpv is not None else 2.5)

    # ── כותרת ───────────────────────────────────────────────────────
    st.markdown(f"## 📁 {name}")
    st.caption(f"🎯 אסטרטגיות התיק: {_strategy_label(portfolio.get('strategy_ids'))}")
    _disclaimer_banner()

    # ── כרטיסי סיכום ────────────────────────────────────────────────
    st.markdown("---")
    _render_summary_cards(trades, initial, current, commission)

    # ── עקומת שווי ──────────────────────────────────────────────────
    st.markdown("### 📈 עקומת שווי התיק")
    _render_equity_curve(trades, initial)

    # ── טבלת עסקאות ─────────────────────────────────────────────────
    st.markdown("### 📋 עסקאות")
    _render_trade_table(sorted(trades, key=lambda t: str(t.get("opened_at") or ""), reverse=True))

    # ── פירוט לפי פקיעה (רגליים + מבנה + payoff) ─────────────────────
    _render_expiry_breakdown(trades)

    # ── Track record ─────────────────────────────────────────────────
    st.markdown("### 🏆 Track Record לפי אסטרטגיה")
    _render_track_record(trades)

    # ── Footer ───────────────────────────────────────────────────────
    st.divider()
    st.caption("⚠️ כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה היסטורית.")


# ════════════════════════════════════════════════════════════════════════
#  Portfolio card (list view)
# ════════════════════════════════════════════════════════════════════════

def _portfolio_card(p: dict, trades: list[dict]) -> None:
    """מציג כרטיס HTML של תיק + כפתור פתיחה.

    trades — עסקאות התיק (מתקבלות מבחוץ, משאילתה אחת לכל הרשת — לא שאילתה לכל כרטיס).
    """
    pid        = p["id"]
    name       = p.get("name") or f"תיק #{pid}"
    initial    = float(p.get("initial_balance") or 0)
    _cpv       = p.get("commission_per_leg")
    commission = float(_cpv if _cpv is not None else 2.5)
    strat_text = _strategy_label(p.get("strategy_ids"))

    open_count   = sum(1 for t in trades if t.get("status") == "open")
    closed_count = sum(1 for t in trades if t.get("status") == "closed")

    # היתרה נגזרת מהעסקאות — מקור אמת אחד (לא נקראת מ-current_balance שב-DB).
    current   = compute_balance(p, trades)
    pnl       = current - initial
    pnl_pct   = (pnl / initial * 100) if initial > 0 else 0.0
    pnl_color = _pnl_color(pnl)
    sign      = _sign(pnl)

    st.markdown(
        f"""
        <div style='background:#1a2744;border:1px solid #2a3d6b;border-radius:12px;
                    padding:18px;margin-bottom:8px;border-top:3px solid #c9a84c'>
          <div style='font-size:1.1rem;font-weight:700;color:#e0e6f0;margin-bottom:12px'>
            {name}
          </div>
          <div style='display:flex;justify-content:space-between;margin-bottom:6px'>
            <span style='color:#7a9ab8;font-size:0.85rem'>שווי נוכחי</span>
            <span style='color:#e0e6f0;font-weight:600'>₪{current:,.0f}</span>
          </div>
          <div style='display:flex;justify-content:space-between;margin-bottom:6px'>
            <span style='color:#7a9ab8;font-size:0.85rem'>שווי התחלתי</span>
            <span style='color:#c8d6e8'>₪{initial:,.0f}</span>
          </div>
          <div style='display:flex;justify-content:space-between;margin-bottom:6px'>
            <span style='color:#7a9ab8;font-size:0.85rem'>תשואה</span>
            <span style='color:{pnl_color};font-weight:700'>
              {sign}₪{abs(pnl):,.0f}&nbsp;({sign}{pnl_pct:.1f}%)
            </span>
          </div>
          <div style='display:flex;justify-content:space-between;margin-bottom:6px'>
            <span style='color:#7a9ab8;font-size:0.85rem'>עסקאות פתוחות / סגורות</span>
            <span style='color:#c8d6e8'>{open_count} / {closed_count}</span>
          </div>
          <div style='display:flex;justify-content:space-between;margin-bottom:8px'>
            <span style='color:#7a9ab8;font-size:0.85rem'>עמלה לרגל</span>
            <span style='color:#c9a84c'>₪{commission:.1f}</span>
          </div>
          <div style='margin-bottom:6px'>
            <span style='color:#7a9ab8;font-size:0.85rem'>אסטרטגיות</span>
            <div style='color:#c8d6e8;font-size:0.82rem;margin-top:3px;line-height:1.45'>
              {strat_text}
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("פתח →", key=f"open_p_{pid}"):
        st.session_state["selected_portfolio_id"] = pid
        st.rerun()


# ════════════════════════════════════════════════════════════════════════
#  Manual actions (testing) — open trades for current expiries
# ════════════════════════════════════════════════════════════════════════

_STATUS_SUMMARY_HE = {
    "open":      "נפתחו",
    "skipped":   "דולגו — אין נתוני מחיר",
    "duplicate": "כפילות — כבר קיימות",
    "error":     "שגיאות",
    "db_error":  "שגיאות DB",
}


def _run_manual_open(expiries: list[str], portfolios: list[dict]) -> dict:
    """מריץ פתיחת עסקאות לכל הפקיעות הזמינות בכל התיקים הפעילים.

    לכל פקיעה: טוען שרשרת (get_latest_option_chain) וקורא ל-open_trades_for_expiry.
    אם טעינת שרשרת או הפתיחה נכשלות לפקיעה — מדווח ומדלג בלי לקרוס.
    מחזיר dict סיכום מובנה לשמירה ב-session_state ולתצוגה אחרי rerun.
    """
    pid_to_name = {p["id"]: (p.get("name") or f"תיק #{p['id']}") for p in portfolios}
    summary: dict = {
        "ran_at":   datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "expiries": [],
    }

    # engine המשותף (cache_resource) — לא יוצרים חדש ו*לא* קוראים dispose:
    # זהו ה-engine החי של כל האפליקציה, סגירתו תשבור שאילתות עתידיות.
    engine = _engine()

    for expiry in expiries:
        exp_rec: dict = {
            "expiry":       expiry,
            "chain_error":  None,
            "counts":       {},
            "by_portfolio": {},
        }

        # ── טעינת שרשרת — כישלון מדווח ומדלג ──────────────────────────
        try:
            chain = get_latest_option_chain(expiry, engine=engine)
        except Exception as exc:  # noqa: BLE001
            exp_rec["chain_error"] = f"חריגה בטעינת השרשרת: {exc}"
            summary["expiries"].append(exp_rec)
            continue

        if not chain:
            exp_rec["chain_error"] = (
                "לא נטענה שרשרת אופציות (נתונים חסרים או לא תקינים)."
            )
            summary["expiries"].append(exp_rec)
            continue

        # ── פתיחת עסקאות — engine משותף לכל ההרצה ─────────────────────
        try:
            results = open_trades_for_expiry(expiry, chain, portfolios, engine=engine)
        except Exception as exc:  # noqa: BLE001
            exp_rec["chain_error"] = f"חריגה בפתיחת עסקאות: {exc}"
            summary["expiries"].append(exp_rec)
            continue

        # ── ספירת תוצאות לפי סטטוס + פירוט לכל תיק ─────────────────────
        counts: dict = {}
        by_pf: dict = {}
        for r in results:
            status = r.get("status", "error")
            pid    = r.get("portfolio_id")
            counts[status] = counts.get(status, 0) + 1
            if pid is not None:
                name = pid_to_name.get(pid, f"תיק #{pid}")
                by_pf.setdefault(pid, {"name": name, "counts": {}})
                by_pf[pid]["counts"][status] = by_pf[pid]["counts"].get(status, 0) + 1

        exp_rec["counts"]       = counts
        exp_rec["by_portfolio"] = by_pf
        summary["expiries"].append(exp_rec)

    return summary


def _render_manual_summary(summary: dict) -> None:
    """מציג סיכום ברור של ההרצה הידנית האחרונה (success/warning לפי התוצאה)."""
    st.markdown(f"#### 📋 תוצאות ההרצה האחרונה — {summary.get('ran_at', '')}")

    for exp_rec in summary.get("expiries", []):
        expiry = exp_rec["expiry"]

        if exp_rec.get("chain_error"):
            st.warning(f"⚠️ פקיעה {expiry}: {exp_rec['chain_error']} — דולגה.")
            continue

        counts = exp_rec.get("counts", {})
        opened = counts.get("open", 0)
        total  = sum(counts.values())
        parts  = [
            f"{_STATUS_SUMMARY_HE.get(k, k)}: {v}"
            for k, v in counts.items() if v
        ]
        line = f"פקיעה {expiry} — {total} ניסיונות | " + " · ".join(parts)

        if opened > 0:
            st.success("✅ " + line)
        else:
            st.warning("⚠️ " + line)

        # ── פירוט לכל תיק ──────────────────────────────────────────────
        for info in exp_rec.get("by_portfolio", {}).values():
            pf_parts = [
                f"{_STATUS_SUMMARY_HE.get(k, k)}: {v}"
                for k, v in info["counts"].items() if v
            ]
            st.caption(f"• {info['name']}: " + " · ".join(pf_parts))


def _render_manual_actions(portfolios: list[dict]) -> None:
    """אזור פעולות ידניות לבדיקה — פתיחת עסקאות לפקיעות הזמינות.

    אינו פותח עסקאות אוטומטית — דורש לחיצה מפורשת על כפתור האישור.
    """
    st.markdown("### 🔧 פעולות ידניות (בדיקה)")

    # ── תוצאות הרצה קודמת (נשמרות מעבר ל-rerun) ───────────────────────
    last_summary = st.session_state.get("manual_open_summary")
    if last_summary:
        _render_manual_summary(last_summary)
        if st.button("✖️ נקה תוצאות", key="clear_manual_summary"):
            st.session_state["manual_open_summary"] = None
            st.rerun()

    with st.expander("📂 פתח עסקאות לפקיעות השבוע", expanded=False):
        st.info(
            "פעולה זו פותחת עסקאות וירטואליות בפועל ומעדכנת את יתרת התיקים — "
            "לבדיקה בלבד."
        )

        expiries = _cached_expiries()
        if not expiries:
            st.warning("אין פקיעות זמינות כרגע (טבלת tase_putcall ריקה או לא נגישה).")
            return

        st.markdown("**פקיעות זמינות כרגע:**")
        for e in expiries:
            st.markdown(f"- `{e}`")

        st.markdown(f"**ייפתח עבור {len(portfolios)} תיקים פעילים:**")
        for p in portfolios:
            pname = p.get("name") or f"תיק #{p['id']}"
            st.markdown(f"- {pname} — _{_strategy_label(p.get('strategy_ids'))}_")

        st.caption(
            "לכל תיק ייפתחו רק האסטרטגיות שהוגדרו לו, לכל פקיעה. "
            "עסקאות שכבר קיימות יסומנו ככפילות וידולגו."
        )

        if st.button("▶️ פתח עסקאות עכשיו", key="confirm_manual_open", type="primary"):
            with st.spinner("פותח עסקאות..."):
                summary = _run_manual_open(expiries, portfolios)
            st.session_state["manual_open_summary"] = summary
            _clear_db_cache()   # כתיבה בוצעה — לרענן את הדאטה כדי שהעסקאות יופיעו מיד
            st.rerun()


# ════════════════════════════════════════════════════════════════════════
#  Global performance (P&L מצטבר — תצוגה ללקוחות)
# ════════════════════════════════════════════════════════════════════════

def _render_global_performance(portfolios: list[dict], all_trades: list[dict]) -> None:
    """ביצועים מצטברים חוצי-תיקים — ה-benchmark בלבד (6 האסטרטגיות המקוריות): סך P&L נטו,
    Win Rate, עקומת שווי, ופילוח. תיק ההמלצות (strategy_id=102) מוחרג כדי לא לזהם את ה-benchmark
    — ביצועיו מוצגים בכרטיס/עמוד התיק שלו בנפרד."""
    st.markdown("### 💰 ביצועים מצטברים — כל התיקים")

    # מחריגים את תיק ההמלצות (102): עסקאותיו וההון ההתחלתי שלו לא נספרים במצטבר ה-benchmark.
    all_trades = [t for t in all_trades if t.get("strategy_id") in BENCHMARK_STRATEGY_IDS]
    portfolios = [p for p in portfolios
                  if not (set(p.get("strategy_ids") or []) - BENCHMARK_STRATEGY_IDS)]

    summary = summarize_closed_pnl(all_trades)
    n       = summary["closed_count"]

    if n == 0:
        st.info("עדיין אין עסקאות סגורות — הביצועים יוצגו כאן לאחר סגירת פקיעה ראשונה.")
        return

    total   = summary["total_pnl"]
    avg     = summary["avg_pnl"]
    color   = _pnl_color(total)
    sign    = _sign(total)

    # ── סך רווח/הפסד נטו — כרטיס בולט ───────────────────────────────
    st.markdown(
        f"""
        <div style='background:#1a2744;border:1px solid #2a3d6b;border-radius:12px;
                    border-top:3px solid {color};padding:16px 20px;margin-bottom:12px;
                    text-align:center'>
          <div style='color:#7a9ab8;font-size:0.9rem'>סך רווח/הפסד נטו (כל העסקאות הסגורות)</div>
          <div style='color:{color};font-size:2.1rem;font-weight:800;margin-top:4px'>
            {sign}₪{abs(total):,.0f}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("עסקאות סגורות", n)
    c2.metric("Win Rate", f"{summary['win_rate']*100:.0f}%",
              help=f"{summary['wins']} רווחיות מתוך {n} סגורות")
    c3.metric("ממוצע לעסקה", f"{_sign(avg)}₪{abs(avg):,.0f}")

    # ── עקומת שווי כוללת (סכום ההון ההתחלתי של כל התיקים) ───────────
    total_initial = sum(float(p.get("initial_balance") or 0) for p in portfolios)
    st.markdown("#### 📈 עקומת שווי כוללת")
    _render_equity_curve(all_trades, total_initial)

    # ── ביצועים לפי אסטרטגיה (חוצה תיקים) ───────────────────────────
    st.markdown("#### 🏆 ביצועים לפי אסטרטגיה")
    _render_track_record(all_trades)


# ════════════════════════════════════════════════════════════════════════
#  Close matured expiries (סגירה אמיתית — כתיבה בלתי-הפיכה)
# ════════════════════════════════════════════════════════════════════════

def _do_close(ready_items: list[dict]) -> None:
    """סוגר רשימת פקיעות בשלות דרך close_matured_expiry, שומר סיכום ומרענן.

    מעביר את התאריך כמחרוזת (str) — בטוח מול שני טיפוסי העמודה (date/text),
    כי literal מסוג unknown מומר אוטומטית לטיפוס העמודה. קורא ל-close_matured_expiry
    הקיים — לא משכפל לוגיקת P&L.
    """
    results = []
    with st.spinner("סוגר עסקאות..."):
        for r in ready_items:
            results.append(
                close_matured_expiry(str(r["expiry_date"]), engine=_engine())
            )
    st.session_state["close_matured_summary"] = {
        "ran_at":  datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "results": results,
    }
    _clear_db_cache()   # כתיבה בוצעה — לרענן עסקאות + ready-to-close
    st.rerun()


def _render_close_summary(summary: dict) -> None:
    """מציג סיכום פעולת הסגירה האחרונה (נשמר מעבר ל-rerun)."""
    st.markdown(f"#### 🧾 תוצאות הסגירה האחרונה — {summary.get('ran_at', '')}")

    for res in summary.get("results", []):
        exp    = res.get("expiry_date", "—")
        closed = res.get("closed", 0)
        errors = res.get("errors", 0)
        total  = res.get("total_pnl", 0.0)
        si     = res.get("settlement_index")
        si_txt = f"{si:,.2f}" if si is not None else "—"

        if closed == 0:
            st.warning(f"⚠️ פקיעה {exp}: {res.get('message', 'לא נסגרו עסקאות')}")
            continue

        color = _pnl_color(total)
        sign  = _sign(total)
        st.success(
            f"✅ פקיעה {exp} — נסגרו {closed} עסקאות (סטלמנט {si_txt})"
            + (f" · {errors} נכשלו" if errors else "")
        )
        st.markdown(
            f"<div style='font-size:1.05rem;margin-bottom:6px'>סך P&L לפקיעה: "
            f"<strong style='color:{color}'>{sign}₪{abs(total):,.0f}</strong></div>",
            unsafe_allow_html=True,
        )

        rows = []
        for t in res.get("results", []):
            pnlp = t.get("pnl_pct")
            rows.append({
                "אסטרטגיה":   t.get("strategy_name") or "—",
                "Payoff (₪)": t.get("payoff"),
                "PnL (₪)":    t.get("pnl"),
                "PnL%":       f"{pnlp*100:+.1f}%" if pnlp is not None else "—",
                "סטטוס":      _STATUS_HE.get(t.get("status", ""), t.get("status", "—")),
            })
        if rows:
            df = pd.DataFrame(rows)

            def _color_pnl(v):
                if not isinstance(v, (int, float)):
                    return ""
                return f"color: {_GREEN}" if v > 0 else (f"color: {_RED}" if v < 0 else "")

            styled = (
                df.style
                .map(_color_pnl, subset=["PnL (₪)"])
                .format({
                    "Payoff (₪)": lambda v: f"₪{v:,.0f}" if v is not None else "—",
                    "PnL (₪)":    lambda v: f"₪{v:+,.0f}" if v is not None else "—",
                })
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_close_matured() -> None:
    """אזור 'סגירת פקיעות שהבשילו' — סגירה אמיתית (בלתי-הפיכה) של עסקאות בפקיעה.

    מציג כל פקיעה בשלה (עסקאות פתוחות + סטלמנט זמין) עם כפתור סגירה. הסגירה
    דורשת אישור מפורש (checkbox) כי היא כותבת ל-DB ואינה הפיכה. הכפתור קורא
    ל-close_matured_expiry הקיים — לא משכפל לוגיקה.
    """
    st.markdown("### 🔔 סגירת פקיעות שהבשילו")

    # ── תוצאת סגירה אחרונה (נשמרת מעבר ל-rerun) ───────────────────────
    last = st.session_state.get("close_matured_summary")
    if last:
        _render_close_summary(last)
        if st.button("✖️ נקה תוצאות", key="clear_close_summary"):
            st.session_state["close_matured_summary"] = None
            st.rerun()

    try:
        ready = _cached_ready_to_close()
    except Exception:
        st.error("❌ שגיאה בשליפת הפקיעות הבשלות.")
        return

    if not ready:
        st.info("אין פקיעות שהבשילו לסגירה — אין פקיעה עם עסקאות פתוחות ומחיר סטלמנט זמין.")
        return

    st.warning(
        "⚠️ סגירת פקיעה היא פעולה **בלתי-הפיכה**: היא מעדכנת את העסקאות הפתוחות "
        "ל'סגור' עם P&L סופי לפי מחיר הסטלמנט. ודא/י את הנתונים לפני הסגירה."
    )
    confirm = st.checkbox(
        "✅ אני מאשר/ת סגירה אמיתית של עסקאות בפקיעות שייבחרו",
        key="confirm_close_matured",
    )

    for r in ready:
        exp    = str(r["expiry_date"])
        si     = r.get("settlement_index")
        n      = r.get("open_trades", 0)
        si_txt = f"{si:,.2f}" if si is not None else "—"
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown(f"**פקיעה {exp}** — סטלמנט `{si_txt}` · {n} עסקאות פתוחות")
        with c2:
            if st.button(f"🔒 סגור {exp}", key=f"close_exp_{exp}",
                         type="primary", disabled=not confirm):
                _do_close([r])

    if len(ready) > 1:
        st.markdown("")
        if st.button("🔒 סגור את כל הבשלות", key="close_all_ready",
                     disabled=not confirm):
            _do_close(ready)


# ════════════════════════════════════════════════════════════════════════
#  Page entry point
# ════════════════════════════════════════════════════════════════════════

st.title("📊 תיקי דמו")
_disclaimer_banner()

if not has_paper_db():
    st.warning("⚠️ DATABASE_URL לא מוגדר — paper trading אינו זמין בסביבה זו.")
    st.stop()

if "selected_portfolio_id" not in st.session_state:
    st.session_state["selected_portfolio_id"] = None

# ─── תצוגה פנימית ───────────────────────────────────────────────────
if st.session_state["selected_portfolio_id"] is not None:
    _render_portfolio_detail(st.session_state["selected_portfolio_id"])
    st.stop()

# ─── טופס יצירת תיק ─────────────────────────────────────────────────
with st.expander("➕ צור תיק חדש", expanded=False):
    with st.form("create_portfolio_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            p_name = st.text_input("שם התיק", placeholder="תיק ראשי")
        with col2:
            p_balance = st.number_input(
                "הון התחלתי (₪)", min_value=1_000.0, value=100_000.0, step=1_000.0
            )
        with col3:
            p_comm = st.number_input("עמלה לכל רגל (₪)", min_value=0.0, value=2.5, step=0.5)

        p_strat_labels = st.multiselect(
            "אסטרטגיות שהתיק יריץ",
            options=list(_STRATEGY_LABELS.keys()),
            default=list(_STRATEGY_LABELS.keys()),
            help="בחר אילו אסטרטגיות ייפתחו אוטומטית בתיק זה. ברירת מחדל: כולן.",
        )

        if st.form_submit_button("✅ צור תיק"):
            p_strategy_ids = [_STRATEGY_LABELS[lbl] for lbl in p_strat_labels]
            if not p_name.strip():
                st.error("נא להזין שם לתיק.")
            elif not p_strategy_ids:
                st.error("נא לבחור לפחות אסטרטגיה אחת לתיק.")
            else:
                res = create_portfolio(
                    p_name.strip(), p_balance, p_comm,
                    strategy_ids=p_strategy_ids, engine=_engine(),
                )
                if res:
                    st.success(
                        f"✅ תיק «{res['name']}» נוצר "
                        f"(הון: ₪{p_balance:,.0f} | עמלה: ₪{p_comm:.1f}/רגל | "
                        f"אסטרטגיות: {_strategy_label(p_strategy_ids)})"
                    )
                    _clear_db_cache()   # כתיבה בוצעה — לרענן כדי שהתיק החדש יופיע מיד
                    st.rerun()
                else:
                    st.error("❌ שגיאה ביצירת התיק — בדוק חיבור DB.")

# ─── רשת תיקים ──────────────────────────────────────────────────────
portfolios = _cached_portfolios()

if not portfolios:
    st.info("אין תיקים פעילים. צור תיק חדש בעזרת הכפתור למעלה.")
    st.stop()

# שאילתה אחת לכל העסקאות, ואז קיבוץ לפי תיק ב-Python — במקום שאילתה לכל כרטיס.
all_trades    = _cached_trades()
trades_by_pid = group_trades_by_portfolio(all_trades)

st.markdown(f"### תיקים פעילים ({len(portfolios)})")

_COLS = 3
for row_start in range(0, len(portfolios), _COLS):
    cols = st.columns(_COLS)
    for col_idx, col in enumerate(cols):
        idx = row_start + col_idx
        if idx >= len(portfolios):
            break
        with col:
            p = portfolios[idx]
            _portfolio_card(p, trades_by_pid.get(p["id"], []))

# ─── ביצועים מצטברים (כל התיקים) ────────────────────────────────────
st.divider()
_render_global_performance(portfolios, all_trades)

# ─── סגירת פקיעות שהבשילו (סגירה אמיתית) ────────────────────────────
st.divider()
_render_close_matured()

# ─── פעולות ידניות (בדיקה) ──────────────────────────────────────────
st.divider()
_render_manual_actions(portfolios)

st.divider()
st.caption("⚠️ כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה היסטורית.")
