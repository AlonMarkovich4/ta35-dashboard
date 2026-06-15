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
    get_portfolio,
    get_portfolios,
    get_trades,
    has_paper_db,
)
from paper_trading import (
    build_equity_curve,
    build_track_record,
    compute_balance,
    open_trades_for_expiry,
)
from strategies import STRATEGIES
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


def _render_portfolio_detail(pid: int) -> None:
    """תצוגה מלאה של תיק בודד."""
    # ── כפתור חזרה ──────────────────────────────────────────────────
    if st.button("← חזור לרשת התיקים"):
        st.session_state["selected_portfolio_id"] = None
        st.rerun()

    # ── טעינת נתונים ────────────────────────────────────────────────
    try:
        portfolio = get_portfolio(pid)
    except Exception:
        st.error("❌ שגיאה בטעינת נתוני התיק.")
        return

    if portfolio is None:
        st.error(f"תיק #{pid} לא נמצא.")
        return

    try:
        trades = get_trades(portfolio_id=pid)
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

    # ── Track record ─────────────────────────────────────────────────
    st.markdown("### 🏆 Track Record לפי אסטרטגיה")
    _render_track_record(trades)

    # ── Footer ───────────────────────────────────────────────────────
    st.divider()
    st.caption("⚠️ כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה היסטורית.")


# ════════════════════════════════════════════════════════════════════════
#  Portfolio card (list view)
# ════════════════════════════════════════════════════════════════════════

def _portfolio_card(p: dict) -> None:
    """מציג כרטיס HTML של תיק + כפתור פתיחה."""
    pid        = p["id"]
    name       = p.get("name") or f"תיק #{pid}"
    initial    = float(p.get("initial_balance") or 0)
    _cpv       = p.get("commission_per_leg")
    commission = float(_cpv if _cpv is not None else 2.5)
    strat_text = _strategy_label(p.get("strategy_ids"))

    trades       = get_trades(portfolio_id=pid)
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

    # engine אחד לכל ההרצה (חוצה כל הפקיעות) — נסגר ב-finally כדי לנקות את ה-pool
    # ולא להשאיר חיבורים פתוחים מול ה-Supabase pooler.
    engine = _make_engine()
    try:
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
    finally:
        # _make_engine מחזיר None אם DATABASE_URL לא מוגדר — הגנה לפני dispose
        if engine is not None:
            engine.dispose()

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

        expiries = get_available_expiries()
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
            st.rerun()


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
                    p_name.strip(), p_balance, p_comm, strategy_ids=p_strategy_ids
                )
                if res:
                    st.success(
                        f"✅ תיק «{res['name']}» נוצר "
                        f"(הון: ₪{p_balance:,.0f} | עמלה: ₪{p_comm:.1f}/רגל | "
                        f"אסטרטגיות: {_strategy_label(p_strategy_ids)})"
                    )
                    st.rerun()
                else:
                    st.error("❌ שגיאה ביצירת התיק — בדוק חיבור DB.")

# ─── רשת תיקים ──────────────────────────────────────────────────────
portfolios = get_portfolios()

if not portfolios:
    st.info("אין תיקים פעילים. צור תיק חדש בעזרת הכפתור למעלה.")
    st.stop()

st.markdown(f"### תיקים פעילים ({len(portfolios)})")

_COLS = 3
for row_start in range(0, len(portfolios), _COLS):
    cols = st.columns(_COLS)
    for col_idx, col in enumerate(cols):
        idx = row_start + col_idx
        if idx >= len(portfolios):
            break
        with col:
            _portfolio_card(portfolios[idx])

# ─── פעולות ידניות (בדיקה) ──────────────────────────────────────────
st.divider()
_render_manual_actions(portfolios)

st.divider()
st.caption("⚠️ כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה היסטורית.")
