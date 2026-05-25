"""
דף פקיעה קרובה — ניתוח שרשרת אופציות TA-35
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from backtester import best_per_strategy, run_backtest
from context_analyzer import (
    build_recommendation,
    conditional_win_rates,
    find_similar_expiries,
    get_recent_move,
)
from data_loader import get_engine, load_from_db
from events import compute_risk_score
from options_parser import MULTIPLIER, find_atm, get_strategy_strikes, parse_putvscall
from payoff import build_payoff_fig, format_legs, strategy_legs_detail, strategy_summary
from styles import inject_global_css
from supabase_loader import (
    get_available_expiries,
    get_latest_option_chain,
    get_sample_row,
    has_db,
)

_PROJECT_ROOT = Path(__file__).parent.parent

# ─── שמות וצבעים לאסטרטגיות ─────────────────────────────────────────
_STRATEGY_META = {
    1: {"name": "Bull Call Spread",    "emoji": "📈", "color": "#27ae60"},
    2: {"name": "Short Iron Condor",   "emoji": "🦅", "color": "#2980b9"},
    3: {"name": "Long Call Butterfly", "emoji": "🦋", "color": "#8e44ad"},
    4: {"name": "Long Put Butterfly",  "emoji": "🦋", "color": "#6c3483"},
    5: {"name": "Long Straddle",       "emoji": "⚡", "color": "#e67e22"},
    6: {"name": "Long Strangle",       "emoji": "🌪️", "color": "#c0392b"},
}

# ─── Page config ────────────────────────────────────────────────────
st.set_page_config(
    page_title="פקיעה קרובה — TA-35",
    page_icon="🎯",
    layout="wide",
)

inject_global_css()

st.title("🎯 פקיעה קרובה — ניתוח שרשרת אופציות")
st.markdown("ניתוח שרשרת Put/Call מהבורסה + המלצות אסטרטגיות לפקיעה הקרובה")


# ─── Cached Supabase loader (TTL 10 min) ────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _load_chain_cached(expiry: str):
    """טוען שרשרת פקיעה מ-Supabase ושומר בcache עד 10 דקות."""
    return get_latest_option_chain(expiry)


# ─── Source section ─────────────────────────────────────────────────
st.subheader("1. מקור שרשרת אופציות")

_HAS_DB = has_db()

if _HAS_DB:
    col_sb, col_up = st.columns([1, 1])

    with col_sb:
        st.markdown("**🌐 Supabase**")
        available = get_available_expiries()
        if available:
            sel_exp = st.selectbox(
                "בחר פקיעה",
                available,
                format_func=lambda d: pd.to_datetime(d).strftime("%d/%m/%Y"),
                key="sb_exp_select",
            )

            # ── רענון אוטומטי בטעינת הדף ──────────────────────────────
            # מתעדכן אוטומטית כשהפקיעה משתנה או בטעינה הראשונה.
            # _load_chain_cached מחזיר מה-cache אם נטען בשעה האחרונה (TTL=10min).
            if (
                "supabase_chain" not in st.session_state
                or st.session_state.get("_supabase_chain_expiry") != sel_exp
            ):
                with st.spinner("טוען נתונים מ-Supabase..."):
                    _auto = _load_chain_cached(sel_exp)
                if _auto:
                    st.session_state["supabase_chain"]         = _auto
                    st.session_state["supabase_loaded_at"]     = pd.Timestamp.now()
                    st.session_state["_supabase_chain_expiry"] = sel_exp

            # ── כפתור רענון ידני + חותמת זמן ────────────────────────
            _col_btn, _col_ts = st.columns([1, 2])
            with _col_btn:
                if st.button("🔄 רענן ידנית", use_container_width=True):
                    _load_chain_cached.clear()
                    with st.spinner("מרענן מ-Supabase..."):
                        _manual = _load_chain_cached(sel_exp)
                    if _manual:
                        st.session_state["supabase_chain"]         = _manual
                        st.session_state["supabase_loaded_at"]     = pd.Timestamp.now()
                        st.session_state["_supabase_chain_expiry"] = sel_exp
                        st.rerun()
                    else:
                        st.error("❌ לא נמצאו נתונים ב-Supabase לפקיעה זו")
            with _col_ts:
                if "supabase_loaded_at" in st.session_state:
                    _lat = st.session_state["supabase_loaded_at"]
                    st.caption(
                        f"עודכן אוטומטית: "
                        f"{pd.to_datetime(_lat).strftime('%H:%M')}"
                    )
        else:
            st.info("אין נתונים ב-Supabase כרגע")

        with st.expander("📊 נתונים גולמיים מ-Supabase"):
            if "supabase_chain" not in st.session_state:
                st.info("טוען אוטומטית — המתן רגע")
            else:
                _sb      = st.session_state["supabase_chain"]
                _sb_exps = _sb.get("expiries", [])
                if not _sb_exps:
                    st.warning("אין פקיעות בנתונים שנטענו")
                else:
                    _sb_chain = _sb_exps[0]["chain"].copy()
                    _sb_date  = _sb_exps[0].get("date", "")
                    st.markdown(
                        f"**פקיעה:** {_sb_date} &nbsp;|&nbsp; "
                        f"**סה\"כ שורות:** {len(_sb_chain)}"
                    )

                    # בחר עמודות לתצוגה
                    _raw_cols = [
                        "strike", "call_pts", "put_pts",
                        "call_delta", "put_delta",
                        "call_price", "put_price",
                    ]
                    _tbl = _sb_chain[
                        [c for c in _raw_cols if c in _sb_chain.columns]
                    ].copy()

                    # זיהוי ATM לפי put-call parity: min |call_price - put_price|
                    if "call_price" in _tbl.columns and "put_price" in _tbl.columns:
                        _both = (_tbl["call_price"] > 0) & (_tbl["put_price"] > 0)
                        _src  = _tbl[_both] if _both.any() else _tbl
                        _atm_idx = (_src["call_price"] - _src["put_price"]).abs().idxmin()
                    else:
                        _atm_idx = _tbl.index[len(_tbl) // 2]

                    _atm_strike_disp = float(_tbl.loc[_atm_idx, "strike"])

                    # שינוי שמות עמודות לתצוגה
                    _tbl = _tbl.rename(columns={
                        "strike":     "Strike",
                        "call_pts":   "Call (נק')",
                        "put_pts":    "Put (נק')",
                        "call_delta": "δ Call",
                        "put_delta":  "δ Put",
                        "call_price": "Call (₪)",
                        "put_price":  "Put (₪)",
                    })

                    # הדגשת שורת ATM בצבע ירוק
                    def _hl_atm(row, atm_i=_atm_idx):
                        if row.name == atm_i:
                            return [
                                "background-color:#0d2e1a; color:#4ade80; font-weight:700"
                            ] * len(row)
                        return [""] * len(row)

                    _fmt = {k: v for k, v in {
                        "Strike":     "{:,.0f}",
                        "Call (נק')": "{:.1f}",
                        "Put (נק')":  "{:.1f}",
                        "δ Call":     "{:.3f}",
                        "δ Put":      "{:.3f}",
                        "Call (₪)":   "{:,.0f}",
                        "Put (₪)":    "{:,.0f}",
                    }.items() if k in _tbl.columns}

                    st.dataframe(
                        _tbl.style.apply(_hl_atm, axis=1).format(_fmt),
                        hide_index=True,
                        use_container_width=True,
                    )

                    # סיכום תחתון: ATM + מדד משוער
                    _c_pts   = float(_sb_chain.loc[_atm_idx, "call_pts"]) \
                               if "call_pts" in _sb_chain.columns else 0.0
                    _p_pts   = float(_sb_chain.loc[_atm_idx, "put_pts"]) \
                               if "put_pts"  in _sb_chain.columns else 0.0
                    _idx_est = _atm_strike_disp + _c_pts - _p_pts
                    st.info(
                        f"🎯 **ATM Strike:** {_atm_strike_disp:,.0f}"
                        f" &nbsp;|&nbsp; "
                        f"📊 **מדד משוער:** {_idx_est:,.1f}"
                        f" &nbsp;|&nbsp; "
                        f"Call: {_c_pts:.1f} נק' &nbsp;|&nbsp; Put: {_p_pts:.1f} נק'"
                    )

        with st.expander("🔍 אבחון — שורה גולמית מהDB"):
            _sample = get_sample_row()
            if _sample:
                _diag_rows = []
                for _k, _v in _sample.items():
                    _diag_rows.append({"עמודה": _k, "ערך גולמי": str(_v)})
                st.dataframe(
                    pd.DataFrame(_diag_rows),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption(
                    "lastrate_call/put, highrate_*, lowrate_* מאוחסנים כ-int×100. "
                    "חלוקה ב-100 מחזירה נקודות; כפל ב-50 מחזיר ₪."
                )
            else:
                st.info("לא ניתן לקרוא שורה — בדוק DATABASE_URL")

    with col_up:
        st.markdown("**📄 העלאה ידנית**")
        uploaded = st.file_uploader(
            "putvscall.csv מ-tase.co.il",
            type=["csv"],
            help="הורד מהבורסה: נגזרים ← Put vs Call ← יצוא CSV",
            label_visibility="collapsed",
        )
        st.caption("הורד מ-tase.co.il → נגזרים → Put vs Call → יצוא CSV")

else:
    col_up, col_info = st.columns([2, 3])
    with col_up:
        uploaded = st.file_uploader(
            "קובץ putvscall.csv מהבורסה (tase.co.il)",
            type=["csv"],
            help="הורד מהבורסה: נגזרים ← Put vs Call ← יצוא CSV",
        )
    with col_info:
        st.info(
            "**איך מורידים את הקובץ:**\n"
            "1. כנס ל-tase.co.il → נגזרים\n"
            "2. בחר Put vs Call (TA-35)\n"
            "3. לחץ יצוא → CSV\n"
            "4. העלה כאן את הקובץ שהורד"
        )

# ─── Parse or use demo file ─────────────────────────────────────────
_DEMO_PATH = (
    _PROJECT_ROOT.parent / "data" / "current" / "putvscall.csv"
    if (_PROJECT_ROOT.parent / "data" / "current" / "putvscall.csv").exists()
    else _PROJECT_ROOT / "data" / "current" / "putvscall.csv"
)
_has_demo = _DEMO_PATH.exists()

source_label = ""
if uploaded is not None:
    # קובץ שהועלה ידנית — עדיפות גבוהה ביותר
    raw_bytes = uploaded.read()
    source_label = f"📄 {uploaded.name}"
    cache_key = f"chain_{uploaded.name}_{len(raw_bytes)}"
    if cache_key not in st.session_state:
        try:
            st.session_state[cache_key] = parse_putvscall(raw_bytes)
        except Exception as exc:
            st.error(f"❌ שגיאה בפרסור הקובץ: {exc}")
            st.stop()
    parsed = st.session_state[cache_key]

elif st.session_state.get("supabase_chain"):
    # נתוני Supabase שנטענו אוטומטית או ידנית
    parsed = st.session_state["supabase_chain"]
    _ft    = parsed.get("fetched_at")
    _ts    = pd.to_datetime(_ft).strftime("%d/%m/%Y %H:%M") if _ft else ""
    source_label = f"🌐 Supabase ({_ts})" if _ts else "🌐 Supabase"

elif _has_demo:
    st.caption(f"⚠️ מוצג קובץ דוגמה: {_DEMO_PATH.name} (העלה קובץ עדכני לניתוח אמיתי)")
    source_label = f"📂 דוגמה: {_DEMO_PATH.name}"
    if "chain_demo" not in st.session_state:
        try:
            st.session_state["chain_demo"] = parse_putvscall(_DEMO_PATH)
        except Exception as exc:
            st.error(f"❌ שגיאה בפרסור קובץ הדוגמה: {exc}")
            st.stop()
    parsed = st.session_state["chain_demo"]

else:
    if _HAS_DB:
        st.info("לחץ **🔄 טען מ-Supabase** כדי לקבל נתונים עדכניים, או העלה קובץ CSV")
    else:
        st.info("העלה קובץ putvscall.csv מהבורסה כדי להתחיל")
    st.stop()

if not parsed.get("expiries"):
    st.error("❌ לא נמצאו פקיעות בקובץ. ודא שהקובץ הוא putvscall.csv תקני מ-TASE.")
    st.stop()

st.markdown("---")

# ─── Expiry selector ────────────────────────────────────────────────
st.subheader("2. בחר פקיעה")

expiry_labels = [
    f"{e['date']} — {e['expiry_type']} ({len(e['chain'])} סטרייקים)"
    for e in parsed["expiries"]
]

col_sel, col_meta = st.columns([2, 3])
with col_sel:
    selected_label = st.selectbox(
        "פקיעה לניתוח",
        expiry_labels,
        index=0,
        label_visibility="collapsed",
    )
expiry_idx = expiry_labels.index(selected_label)
expiry = parsed["expiries"][expiry_idx]
chain = expiry["chain"]

with col_meta:
    st.markdown(
        f"**תאריך נתונים:** {parsed['as_of_date']} &nbsp;|&nbsp; "
        f"**פקיעה:** {expiry['date']} &nbsp;|&nbsp; "
        f"**סוג:** {expiry['expiry_type']} &nbsp;|&nbsp; {source_label}"
    )

# ─── ATM identification ─────────────────────────────────────────────
try:
    atm = find_atm(chain)
except Exception as exc:
    st.error(f"❌ שגיאה בזיהוי ATM: {exc}")
    st.stop()

if not atm:
    st.warning("לא ניתן לזהות ATM — ייתכן שחסרים מחירי Call/Put בקובץ.")
    st.stop()

st.markdown("---")
st.subheader("3. מצב השוק — ATM")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("📊 מדד (משוערך)", f"{atm['index_estimate']:,.1f}")
m2.metric("🎯 ATM Strike",   f"{atm['strike']:,.0f}")
m3.metric("📞 Call ATM",     f"{atm['call_pts']:.1f} נק'",
          help=f"{atm['call_price']:,.0f} ₪ ≈ {atm['call_pts']:.1f} נק' (÷{MULTIPLIER})")
m4.metric("📉 Put ATM",      f"{atm['put_pts']:.1f} נק'",
          help=f"{atm['put_price']:,.0f} ₪ ≈ {atm['put_pts']:.1f} נק' (÷{MULTIPLIER})")
m5.metric("🔀 Straddle",     f"{atm['call_pts'] + atm['put_pts']:.1f} נק'",
          help=f"עלות Straddle ATM (Call+Put) ≈ {(atm['call_pts']+atm['put_pts'])*MULTIPLIER:,.0f} ₪")

st.markdown("---")

# ─── Historical win rates ────────────────────────────────────────────
best_wr: dict[int, float] = {}
df_hist = st.session_state.get("hist_df")

if df_hist is not None and not df_hist.empty:
    try:
        results = run_backtest(df_hist)
        best_df = best_per_strategy(results)
        best_wr = dict(zip(best_df["strategy_id"].astype(int), best_df["win_rate"]))
    except Exception:
        pass

# ─── Strategy strikes ────────────────────────────────────────────────
try:
    strategy_info = get_strategy_strikes(atm["strike"], chain)
except Exception as exc:
    st.error(f"❌ שגיאה בחישוב סטרייקים: {exc}")
    strategy_info = {}

# ─── Section 4: Strategy cards ──────────────────────────────────────
st.subheader("4. המלצות אסטרטגיות")

if not best_wr:
    st.caption(
        "💡 לקבלת Win Rate היסטורי — טען נתונים היסטוריים בדף **📊 ניתוח היסטורי**"
    )

_STATUS_CONF = {
    "profit_zone":    ("🟢", "המדד בתוך טווח הרווח",    "#27ae60"),
    "near_breakeven": ("🟡", "המדד קרוב ל-Breakeven (±1%)", "#e67e22"),
    "loss_zone":      ("🔴", "המדד מחוץ לטווח",          "#e74c3c"),
}

for row in range(3):
    col_a, col_b = st.columns(2, gap="medium")
    for col_obj, sid in zip([col_a, col_b], [row * 2 + 1, row * 2 + 2]):
        meta = _STRATEGY_META[sid]
        wr   = best_wr.get(sid)

        with col_obj:
            # ── Compute values ─────────────────────────────────────────
            summ = strategy_summary(sid, atm, chain)

            wr_str   = f"{wr:.1%}" if wr is not None else "—"
            wr_color = (
                "#27ae60" if wr and wr >= 0.55
                else "#e74c3c" if wr and wr < 0.45
                else "#e67e22"
            ) if wr else "#888"

            if summ:
                s_emoji, s_text, s_border = _STATUS_CONF.get(
                    summ["market_status"], ("⚪", "—", "#444")
                )
                bes         = summ["breakevens"]
                be_str      = " – ".join(f"{b:,.0f}" for b in bes) if bes else "—"
                entry_abs   = abs(summ["entry_cost_nis"])
                entry_label = "קבלת זיכוי" if summ["entry_cost_nis"] < 0 else "עלות כניסה"
                profit_str  = "∞" if summ["is_unlimited_profit"] \
                              else f"{summ['max_profit_nis']:,.0f} ₪"
                loss_str    = f"{summ['max_loss_nis']:,.0f} ₪"
                be_pct      = summ["be_pct_desc"]
                rr_str      = (
                    f"{summ['risk_reward']:.2f}"
                    if summ["risk_reward"] is not None else "ללא הגבלה ∞"
                )
                y_now_color = "#27ae60" if summ["y_now_nis"] >= 0 else "#e74c3c"
            else:
                s_emoji, s_text, s_border = "⚪", "—", "#444"
                entry_abs, entry_label     = 0, "עלות כניסה"
                profit_str, loss_str       = "—", "—"
                be_str, be_pct, rr_str     = "—", "—", "—"
                y_now_color                = "#888"

            # ── Card HTML ──────────────────────────────────────────────
            st.markdown(f"""
<div style="
    background:#1a1f2e;
    border:2px solid {s_border};
    border-radius:12px;
    padding:20px 22px 16px 22px;
    margin-bottom:4px;
    direction:rtl;
">
  <!-- שורה 1: שם + WR + אינדיקטור -->
  <div style="display:flex; justify-content:space-between; align-items:flex-start;
              margin-bottom:18px">
    <div>
      <div style="font-size:1.05em; font-weight:700; color:{meta['color']}">
        {meta['emoji']} #{sid} {meta['name']}
      </div>
      <div style="font-size:0.72em; color:#7a9ab8; margin-top:2px">Win Rate היסטורי</div>
    </div>
    <div style="display:flex; align-items:center; gap:10px">
      <span style="font-size:1.5em; font-weight:800; color:{wr_color};
                   direction:ltr; white-space:nowrap">{wr_str}</span>
      <span style="font-size:1.8em; line-height:1">{s_emoji}</span>
    </div>
  </div>

  <!-- שורה 2: 3 מספרים גדולים -->
  <div style="display:flex; gap:0; margin-bottom:18px; text-align:center">
    <div style="flex:1; padding:0 6px">
      <div style="font-size:0.70em; color:#7a9ab8; margin-bottom:6px;
                  letter-spacing:0.3px">{entry_label}</div>
      <div style="font-size:1.4em; font-weight:800; color:#e67e22;
                  direction:ltr">{entry_abs:,.0f} ₪</div>
    </div>
    <div style="width:1px; background:#2a3548; margin:2px 0; flex-shrink:0"></div>
    <div style="flex:1; padding:0 6px">
      <div style="font-size:0.70em; color:#7a9ab8; margin-bottom:6px;
                  letter-spacing:0.3px">רווח מקסימלי</div>
      <div style="font-size:1.4em; font-weight:800; color:#27ae60;
                  direction:ltr">{profit_str}</div>
    </div>
    <div style="width:1px; background:#2a3548; margin:2px 0; flex-shrink:0"></div>
    <div style="flex:1; padding:0 6px">
      <div style="font-size:0.70em; color:#7a9ab8; margin-bottom:6px;
                  letter-spacing:0.3px">הפסד מקסימלי</div>
      <div style="font-size:1.4em; font-weight:800; color:#e74c3c;
                  direction:ltr">{loss_str}</div>
    </div>
  </div>

  <!-- שורה 3: Breakeven + הסבר -->
  <div style="background:#111827; border-radius:7px; padding:10px 14px">
    <div style="font-size:0.80em; direction:rtl">
      <span style="color:#7a9ab8; font-weight:600">Breakeven:&nbsp;</span>
      <span style="color:#e0e6f0; font-weight:700">{be_str}</span>
    </div>
    <div style="font-size:0.78em; color:#aaa; margin-top:4px">{be_pct}</div>
  </div>
</div>""", unsafe_allow_html=True)

            # ── Expander 1: פרטי עסקה ─────────────────────────────────
            with st.expander("🛒 פרטי עסקה"):
                if not summ:
                    st.info("אין נתוני שרשרת לפירוט")
                else:
                    st.markdown(f"""
<div style="font-size:0.85em; color:#c8d6e8; direction:rtl; margin-bottom:10px">
  <table style="width:100%; border-collapse:collapse">
    <tr style="border-bottom:1px solid #1e2d45">
      <td style="padding:5px 0; color:#7a9ab8">יחס רווח/סיכון</td>
      <td style="text-align:left; font-weight:700; color:#e0e6f0">{rr_str}</td>
    </tr>
    <tr style="border-bottom:1px solid #1e2d45">
      <td style="padding:5px 0; color:#7a9ab8">P&L במחיר הנוכחי</td>
      <td style="text-align:left; font-weight:700;
                 color:{y_now_color}">{summ["y_now_nis"]:+,.0f} ₪</td>
    </tr>
    <tr>
      <td style="padding:5px 0; color:#7a9ab8">Breakeven מדויק</td>
      <td style="text-align:left; font-weight:700; color:#e0e6f0">{be_str}</td>
    </tr>
  </table>
</div>""", unsafe_allow_html=True)

                    legs = strategy_legs_detail(sid, atm, chain)
                    if legs:
                        st.markdown("**מה לקנות בפועל:**")
                        legs_df = pd.DataFrame([{
                            "פעולה":   lg["action"],
                            "סוג":     lg["type"],
                            "סטרייק":  lg["strike"],
                            "מחיר נק'": lg["price_pts"],
                            "עלות ₪":  lg["price_nis"],
                        } for lg in legs])
                        st.dataframe(
                            legs_df,
                            hide_index=True,
                            use_container_width=True,
                            column_config={
                                "סטרייק":   st.column_config.NumberColumn(format="%,.0f"),
                                "מחיר נק'": st.column_config.NumberColumn(format="%.1f"),
                                "עלות ₪":  st.column_config.NumberColumn(format="%,.0f"),
                            },
                        )

            # ── Expander 2: Payoff Diagram ─────────────────────────────
            with st.expander("📈 Payoff Diagram"):
                try:
                    fig_payoff = build_payoff_fig(
                        sid, atm, chain,
                        index_price=float(atm["index_estimate"]),
                        strategy_name=f"#{sid} {meta['name']}",
                    )
                    st.plotly_chart(
                        fig_payoff,
                        use_container_width=True,
                        key=f"payoff_{sid}",
                    )
                except Exception as _exc:
                    st.info(f"לא ניתן לחשב: {_exc}")

st.markdown("---")

# ─── Section 5: Options chain chart ─────────────────────────────────
st.subheader("5. שרשרת אופציות — Call vs Put לפי סטרייק")

atm_s = atm["strike"]
margin = atm_s * 0.06  # ±6% מ-ATM

chart_chain = chain[
    (chain["strike"] >= atm_s - margin)
    & (chain["strike"] <= atm_s + margin)
    & ((chain["call_price"] > 0) | (chain["put_price"] > 0))
].copy()

if chart_chain.empty:
    st.warning("אין נתונים להצגה בתחום הנבחר.")
else:
    # filter scale: remove extreme outliers (deep ITM showing unrealistic prices)
    p95 = chart_chain[["call_pts", "put_pts"]].stack().quantile(0.95)
    chart_chain = chart_chain[
        (chart_chain["call_pts"] <= p95 * 1.5) & (chart_chain["put_pts"] <= p95 * 1.5)
    ]

    fig = go.Figure()

    # Call line
    call_data = chart_chain[chart_chain["call_pts"] > 0].sort_values("strike")
    fig.add_trace(go.Scatter(
        x=call_data["strike"],
        y=call_data["call_pts"],
        mode="lines+markers",
        name="Call",
        line=dict(color="#27ae60", width=2),
        marker=dict(size=5),
        hovertemplate="Strike: %{x:,.0f}<br>Call: %{y:.1f} נק' (%{customdata:,.0f} ₪)<extra></extra>",
        customdata=call_data["call_price"],
    ))

    # Put line
    put_data = chart_chain[chart_chain["put_pts"] > 0].sort_values("strike")
    fig.add_trace(go.Scatter(
        x=put_data["strike"],
        y=put_data["put_pts"],
        mode="lines+markers",
        name="Put",
        line=dict(color="#e74c3c", width=2),
        marker=dict(size=5),
        hovertemplate="Strike: %{x:,.0f}<br>Put: %{y:.1f} נק' (%{customdata:,.0f} ₪)<extra></extra>",
        customdata=put_data["put_price"],
    ))

    # ATM vertical line
    fig.add_vline(
        x=atm_s,
        line_dash="dash",
        line_color="#555",
        line_width=1.5,
        annotation_text=f"ATM {atm_s:,.0f}",
        annotation_position="top right",
    )

    # Index estimate line
    fig.add_vline(
        x=atm["index_estimate"],
        line_dash="dot",
        line_color="#3498db",
        line_width=1,
        annotation_text=f"מדד ~{atm['index_estimate']:,.1f}",
        annotation_position="top left",
    )

    fig.update_layout(
        xaxis_title="מחיר מימוש (Strike)",
        yaxis_title="מחיר (נקודות)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
        height=420,
        margin=dict(t=40),
        xaxis=dict(tickformat=","),
    )

    st.plotly_chart(fig, use_container_width=True, key="chain_chart")

    # volume table
    with st.expander("📋 טבלת שרשרת מפורטת (עמודות נבחרות)"):
        display_cols = {
            "strike":      "Strike",
            "call_pts":    "Call (נק')",
            "call_delta":  "דלתא Call",
            "call_volume": "מחזור Call",
            "put_pts":     "Put (נק')",
            "put_delta":   "דלתא Put",
            "put_volume":  "מחזור Put",
        }
        tbl = chart_chain[list(display_cols.keys())].rename(columns=display_cols)
        st.dataframe(
            tbl.sort_values("Strike"),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Strike":      st.column_config.NumberColumn(format="%,.0f"),
                "Call (נק')":  st.column_config.NumberColumn(format="%.1f"),
                "Put (נק')":   st.column_config.NumberColumn(format="%.1f"),
                "דלתא Call":   st.column_config.NumberColumn(format="%.1f"),
                "דלתא Put":    st.column_config.NumberColumn(format="%.1f"),
            },
        )

# ─── Section 6: Historical context analysis ─────────────────────────
st.markdown("---")
st.subheader("6. ניתוח הקשר היסטורי")

if df_hist is None or df_hist.empty:
    st.info(
        "💡 לניתוח הקשר ההיסטורי — טען נתונים היסטוריים תחילה בדף **📊 ניתוח היסטורי**"
    )
else:
    # ── Parse upcoming expiry metadata ──────────────────────────────
    try:
        upcoming_dt = pd.to_datetime(expiry["date"], dayfirst=True)
    except Exception:
        st.warning("לא ניתן לפרסר את תאריך הפקיעה לניתוח הקשר.")
        upcoming_dt = None

    if upcoming_dt is not None:
        _TYPE_MAP = {"שבועי": "W", "חודשי": "M"}
        exp_type_code  = _TYPE_MAP.get(expiry["expiry_type"], "W")
        target_month   = upcoming_dt.month
        recent_move    = get_recent_move(df_hist, upcoming_dt)

        _MONTH_HE = {
            1:"ינואר", 2:"פברואר", 3:"מרץ", 4:"אפריל", 5:"מאי", 6:"יוני",
            7:"יולי", 8:"אוגוסט", 9:"ספטמבר", 10:"אוקטובר", 11:"נובמבר", 12:"דצמבר",
        }

        # ── Filter controls ─────────────────────────────────────────
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            move_tol = st.slider(
                "סבילות תנועה קודמת (±%)",
                min_value=0.5, max_value=2.5, value=0.5, step=0.5,
                key="ctx_tol",
                help="רוחב החלון סביב תנועת הפקיעה האחרונה לסינון מקרים דומים",
            )
        with col_f2:
            st.markdown(
                f"**קריטריוני החיפוש:**  \n"
                f"סוג: **{'שבועי' if exp_type_code=='W' else 'חודשי'}** &nbsp;|&nbsp; "
                f"חודש: **{_MONTH_HE[target_month]}** &nbsp;|&nbsp; "
                f"תנועה קודמת: **{recent_move:+.2f}%** ±{move_tol}%"
                if recent_move is not None else
                f"**קריטריוני החיפוש:**  \nסוג: **{'שבועי' if exp_type_code=='W' else 'חודשי'}** &nbsp;|&nbsp; "
                f"חודש: **{_MONTH_HE[target_month]}** &nbsp;|&nbsp; תנועה קודמת: לא זמינה"
            )

        # ── Find similar expiries ────────────────────────────────────
        similar = find_similar_expiries(
            df_hist,
            exp_type_code,
            target_month,
            recent_move,
            move_tol,
        )
        n_sim = len(similar)

        # ── Global backtest (for delta comparison) ───────────────────
        global_best = best_per_strategy(
            run_backtest(df_hist, expiry_type=exp_type_code)
        )

        # ── Metrics row ──────────────────────────────────────────────
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("📋 מקרים דומים", f"{n_sim}")
        mc2.metric(
            "📅 פקיעה קרובה",
            upcoming_dt.strftime("%d/%m/%Y"),
        )
        mc3.metric(
            "📈 תנועה אחרונה",
            f"{recent_move:+.2f}%" if recent_move is not None else "—",
        )

        # Risk score (events.py) ─────────────────────────────────────
        try:
            _eng = get_engine(_PROJECT_ROOT / "database" / "ta35.db")
            risk = compute_risk_score(upcoming_dt.date(), _eng, df_hist)
        except Exception:
            risk = {"score": 0.0, "level": "נמוך", "nearby_events": []}

        _risk_color = (
            "#27ae60" if risk["score"] < 3.5
            else "#e74c3c" if risk["score"] >= 6.5
            else "#e67e22"
        )
        mc4.metric(
            "⚠️ ציון סיכון",
            f"{risk['score']:.1f}/10",
            delta=risk["level"],
            delta_color="off",
        )

        st.markdown("")

        if n_sim < 3:
            st.warning(
                f"נמצאו רק **{n_sim}** מקרים דומים — הרחב את סבילות התנועה לקבלת ניתוח אמין."
            )

        col_tbl, col_wr = st.columns([2, 3], gap="large")

        # ── Similar cases table ──────────────────────────────────────
        with col_tbl:
            st.markdown("**מקרים היסטוריים דומים**")
            if similar.empty:
                st.info("לא נמצאו מקרים דומים בקריטריונים הנוכחיים.")
            else:
                disp = similar.head(15)[[
                    "expiry_date", "expiry_type", "move_pct"
                ]].copy()
                disp["expiry_date"] = disp["expiry_date"].dt.strftime("%d/%m/%Y")
                disp["move_pct"]    = disp["move_pct"].round(2)
                disp = disp.rename(columns={
                    "expiry_date":  "תאריך",
                    "expiry_type":  "סוג",
                    "move_pct":     "תנועה (%)",
                })
                st.dataframe(
                    disp,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "תנועה (%)": st.column_config.NumberColumn(format="%+.2f%%"),
                    },
                )
                if n_sim > 15:
                    st.caption(f"מוצגים 15 מתוך {n_sim} מקרים (האחרונים ביותר)")

        # ── Conditional win rate chart ───────────────────────────────
        with col_wr:
            st.markdown("**Win Rate מותנה לעומת כלל ההיסטוריה**")
            cond_best = conditional_win_rates(similar)

            if cond_best.empty:
                st.info("אין מספיק נתונים לחישוב Win Rate מותנה.")
            else:
                _strategies = cond_best["strategy_name"].tolist()
                _cond_wr    = cond_best["win_rate"].tolist()

                # align global WR order to cond_best order
                _global_wr = []
                for sid in cond_best["strategy_id"]:
                    row = global_best[global_best["strategy_id"] == sid]
                    _global_wr.append(float(row["win_rate"].values[0]) if not row.empty else 0.0)

                fig_wr = go.Figure()
                fig_wr.add_trace(go.Bar(
                    name="כלל ההיסטוריה",
                    x=_strategies,
                    y=_global_wr,
                    marker_color="#95a5a6",
                    opacity=0.7,
                    text=[f"{v:.1%}" for v in _global_wr],
                    textposition="outside",
                ))
                fig_wr.add_trace(go.Bar(
                    name=f"מקרים דומים (n={n_sim})",
                    x=_strategies,
                    y=_cond_wr,
                    marker_color="#2980b9",
                    text=[f"{v:.1%}" for v in _cond_wr],
                    textposition="outside",
                ))
                fig_wr.add_hline(
                    y=0.5,
                    line_dash="dash",
                    line_color="#555",
                    line_width=1.5,
                    annotation_text="50%",
                    annotation_position="top right",
                )
                fig_wr.update_layout(
                    barmode="group",
                    yaxis=dict(tickformat=".0%", range=[0, 1.15], title="Win Rate"),
                    xaxis_title="",
                    height=340,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    margin=dict(t=40, r=40),
                    showlegend=True,
                )
                st.plotly_chart(fig_wr, use_container_width=True, key="ctx_wr_chart")

        # ── Risk events note ─────────────────────────────────────────
        if risk["nearby_events"]:
            st.markdown(
                f"📌 **אירועים בחלון 7 ימים:** "
                + " · ".join(risk["nearby_events"])
            )

        st.markdown("---")

        # ── Final recommendation ─────────────────────────────────────
        rec = build_recommendation(cond_best, global_best, risk["score"], n_sim) \
            if not cond_best.empty else {}

        st.markdown("#### 💡 המלצה — בהתחשב בהיסטוריה ובהקשר הנוכחי")

        if not rec:
            st.info("אין מספיק מקרים דומים להמלצה. הרחב את הפרמטרים.")
        else:
            _delta_str = (
                f"{'▲' if rec['delta_wr'] > 0 else '▼'} "
                f"{abs(rec['delta_wr']):.1%} מהממוצע הכולל"
            )
            _rec_color = (
                "#27ae60" if rec["cond_wr"] >= 0.55
                else "#e74c3c" if rec["cond_wr"] < 0.45
                else "#e67e22"
            )
            st.markdown(
                f"""
<div style="border:2px solid {_rec_color}55; border-radius:12px;
            padding:18px 22px; margin-bottom:8px;
            background:linear-gradient(135deg,{_rec_color}10,transparent)">
  <div style="font-size:1.0em; color:#444; margin-bottom:6px">
    האסטרטגיה המומלצת על בסיס <strong>{n_sim} מקרים דומים</strong>:
  </div>
  <div style="font-size:1.5em; font-weight:800; color:{_rec_color}; margin-bottom:4px">
    {rec['strategy_name']}
  </div>
  <div style="font-size:0.95em; color:#555">
    Win Rate מותנה: <strong style="color:{_rec_color}">{rec['cond_wr']:.1%}</strong>
    &nbsp;|&nbsp; {_delta_str}
    &nbsp;|&nbsp; ציון סיכון: <strong>{rec['risk_score']:.1f}/10</strong>
  </div>
</div>""",
                unsafe_allow_html=True,
            )
            if rec["note"]:
                st.warning(rec["note"])

# ─── Disclaimer ─────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "⚠️ **הצהרת אחריות:** כל המידע המוצג הוא לצורך מחקר וניתוח בלבד. "
    "הסטרייקים המומלצים הם הצעה תיאורטית המבוססת על פרמטרים סטנדרטיים — "
    "אין לראות בהם המלצת מסחר. ערכי ה-P&L הם אומדן גס ואינם מביאים בחשבון "
    f"עמלות, רוחב ספרד, ולא כל סיכון נוסף. מכפיל חוזה: {MULTIPLIER} ₪/נקודה. "
    "המסחר באופציות כרוך בסיכון של אובדן מלא של ההשקעה."
)
