"""
דף אירועים — השפעת אירועים על פקיעות TA-35
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from data_loader import get_engine, load_from_db
from events import (
    add_event,
    compute_risk_score,
    delete_event,
    enrich_expiries_with_events,
    load_all_events,
    seed_events,
)
from styles import inject_global_css

_PROJECT_ROOT = Path(__file__).parent.parent

_CATEGORIES = ["מלחמה", "מגפה", "ריבית", "משבר", "פוליטי", "אחר"]

_CAT_COLORS = {
    "מלחמה":  "#e74c3c",
    "מגפה":   "#8e44ad",
    "ריבית":  "#2980b9",
    "משבר":   "#e67e22",
    "פוליטי": "#27ae60",
    "אחר":    "#95a5a6",
}

st.set_page_config(
    page_title="אירועים — TA-35",
    page_icon="📅",
    layout="wide",
)

inject_global_css()

st.title("📅 אירועים — השפעה על פקיעות TA-35")
st.markdown(
    "ניתוח כיצד אירועים היסטוריים (מלחמות, ריבית, משברים) "
    "משפיעים על תנודתיות פקיעות המדד"
)


# ─── DB engine ───────────────────────────────────────────────────────
def _db():
    return get_engine(_PROJECT_ROOT / "database" / "ta35.db")


# ─── Load / seed events ──────────────────────────────────────────────
engine = _db()

if "events_seeded" not in st.session_state:
    n = seed_events(engine, force=False)
    st.session_state["events_seeded"] = True
    if n:
        st.toast(f"✅ הוזרעו {n} אירועים היסטוריים")

# ─── Section 1: Events management ───────────────────────────────────
st.subheader("1. ניהול אירועים")

ev_df = load_all_events(engine)

col_tbl, col_actions = st.columns([3, 2], gap="large")

with col_tbl:
    if ev_df.empty:
        st.info("אין אירועים בטבלה. לחץ **הזרע אירועים** כדי להוסיף ברירת מחדל.")
    else:
        display = ev_df.copy()
        display["event_date"] = display["event_date"].dt.strftime("%d/%m/%Y")
        display = display.rename(columns={
            "id":          "#",
            "event_date":  "תאריך",
            "name":        "שם",
            "category":    "קטגוריה",
            "description": "תיאור",
        })
        st.dataframe(
            display[["#", "תאריך", "קטגוריה", "שם", "תיאור"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "#":       st.column_config.NumberColumn(width="small"),
                "תאריך":   st.column_config.TextColumn(width="small"),
                "קטגוריה": st.column_config.TextColumn(width="small"),
            },
        )

with col_actions:
    # ── הזרעה מחדש ──
    st.markdown("**פעולות מהירות**")
    if st.button("🌱 הזרע אירועים (ברירת מחדל)", use_container_width=True):
        n = seed_events(engine, force=True)
        st.success(f"הוזרעו {n} אירועים מחדש")
        st.rerun()

    # ── רענון חדשות ──
    if st.button("📰 רענן חדשות (RSS)", use_container_width=True, key="fetch_news_btn"):
        with st.spinner("מושך חדשות רלוונטיות..."):
            try:
                from news_fetcher import save_new_events as _save_news
                n_new = _save_news(engine)
                if n_new:
                    st.success(f"נוספו {n_new} אירועים חדשים מחדשות")
                    st.rerun()
                else:
                    st.info("אין חדשות חדשות רלוונטיות")
            except Exception as _exc:
                st.error(f"שגיאה בטעינת חדשות: {_exc}")

    # ── מחיקת אירוע ──
    if not ev_df.empty:
        with st.expander("🗑️ מחק אירוע"):
            del_id = st.selectbox(
                "בחר אירוע למחיקה",
                ev_df["id"].tolist(),
                format_func=lambda i: ev_df.loc[ev_df["id"] == i, "name"].values[0],
                key="del_event_select",
            )
            if st.button("מחק", type="primary", key="del_event_btn"):
                delete_event(engine, del_id)
                st.rerun()

    # ── הוספת אירוע חדש ──
    with st.expander("➕ הוסף אירוע חדש"):
        with st.form("add_event_form", clear_on_submit=True):
            new_date = st.date_input("תאריך", value=date.today(), key="new_ev_date")
            new_name = st.text_input("שם האירוע", key="new_ev_name")
            new_cat  = st.selectbox("קטגוריה", _CATEGORIES, key="new_ev_cat")
            new_desc = st.text_area("תיאור (אופציונלי)", key="new_ev_desc", height=70)
            submitted = st.form_submit_button("הוסף", use_container_width=True)
            if submitted:
                if not new_name.strip():
                    st.error("חובה להכניס שם לאירוע.")
                else:
                    add_event(engine, new_date, new_name.strip(), new_cat, new_desc.strip())
                    st.success(f"האירוע **{new_name}** נוסף בהצלחה!")
                    st.rerun()

st.markdown("---")

# ─── Load historical expiries ────────────────────────────────────────
if "hist_df" not in st.session_state:
    try:
        _df = load_from_db(engine)
        if not _df.empty:
            st.session_state["hist_df"] = _df
    except Exception:
        pass

df_hist: pd.DataFrame | None = st.session_state.get("hist_df")

if df_hist is None or df_hist.empty:
    st.info(
        "לניתוח מלא — טען נתונים היסטוריים בדף **📊 ניתוח היסטורי** תחילה."
    )
    st.stop()

if ev_df.empty:
    st.warning("אין אירועים בטבלה — הזרע אירועים כדי לראות את הניתוח.")
    st.stop()

# ─── Enrich expiries ─────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _enriched(ev_hash: int, exp_hash: int):
    return enrich_expiries_with_events(
        st.session_state["hist_df"], _db()
    )

enriched = _enriched(len(ev_df), len(df_hist))
valid     = enriched["move_pct"].notna()
with_ev   = enriched[valid & enriched["has_event"]]
without_ev = enriched[valid & ~enriched["has_event"]]

# ─── Section 2: Summary cards ────────────────────────────────────────
st.subheader("2. השפעה על תנודתיות")

c1, c2, c3, c4, c5 = st.columns(5)

def _pct_big(df: pd.DataFrame, threshold: float) -> float:
    return (df["move_pct"].abs() > threshold).mean() * 100 if not df.empty else 0.0

c1.metric("📅 פקיעות עם אירוע",   f"{len(with_ev):,}")
c2.metric("📅 פקיעות ללא אירוע",  f"{len(without_ev):,}")
c3.metric(
    "📈 תנועה ממוצעת — עם אירוע",
    f"{with_ev['move_pct'].abs().mean():.2f}%" if not with_ev.empty else "—",
    delta=f"{with_ev['move_pct'].abs().mean() - without_ev['move_pct'].abs().mean():.2f}% vs. רגיל"
    if not with_ev.empty and not without_ev.empty else None,
)
c4.metric(
    "⚡ פקיעות >2% — עם אירוע",
    f"{_pct_big(with_ev, 2):.1f}%",
    delta=f"{_pct_big(with_ev, 2) - _pct_big(without_ev, 2):.1f}% vs. רגיל",
)
c5.metric(
    "🔒 פקיעות <1% — עם אירוע",
    f"{(with_ev['move_pct'].abs() < 1).mean() * 100:.1f}%" if not with_ev.empty else "—",
)

st.markdown("---")

# ─── Section 3: Timeline chart ───────────────────────────────────────
st.subheader("3. ציר זמן — פקיעות ואירועים")

scatter_df = enriched[valid].copy()
scatter_df["צבע"] = scatter_df["has_event"].map({True: "עם אירוע", False: "רגיל"})
scatter_df["hover_text"] = scatter_df.apply(
    lambda r: (
        f"{r['expiry_date'].strftime('%d/%m/%Y')} | {r['expiry_type']}<br>"
        f"תנועה: {r['move_pct']:+.2f}%<br>"
        + (f"אירוע: {r['event_names']}" if r["has_event"] else "")
    ),
    axis=1,
)

fig_scatter = go.Figure()

for label, color, subset in [
    ("רגיל",     "#95a5a6", scatter_df[~scatter_df["has_event"]]),
    ("עם אירוע", "#e74c3c",  scatter_df[scatter_df["has_event"]]),
]:
    fig_scatter.add_trace(go.Scatter(
        x=subset["expiry_date"],
        y=subset["move_pct"],
        mode="markers",
        name=label,
        marker=dict(color=color, size=5 if label == "רגיל" else 9, opacity=0.7),
        hovertext=subset["hover_text"],
        hoverinfo="text",
    ))

# event vlines
for _, ev in ev_df.iterrows():
    cat_color = _CAT_COLORS.get(ev["category"], "#aaa")
    fig_scatter.add_vline(
        x=ev["event_date"].timestamp() * 1000,
        line_dash="dot",
        line_color=cat_color,
        line_width=1,
        opacity=0.5,
    )

fig_scatter.add_hline(y=0, line_dash="dash", line_color="#555", line_width=1)
fig_scatter.update_layout(
    xaxis_title="תאריך",
    yaxis_title="תנועה (%)",
    yaxis=dict(tickformat=".1f", ticksuffix="%"),
    hovermode="closest",
    height=420,
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    margin=dict(t=40),
)
st.plotly_chart(fig_scatter, use_container_width=True, key="timeline_scatter")

st.markdown("---")

# ─── Section 4: By-category breakdown ───────────────────────────────
st.subheader("4. פירוט לפי קטגוריית אירוע")

col_cat_chart, col_cat_table = st.columns([3, 2], gap="large")

cat_rows = []
for cat in _CATEGORIES:
    cat_mask = with_ev["event_categories"].str.contains(cat, regex=False)
    cat_df   = with_ev[cat_mask]
    if cat_df.empty:
        continue
    cat_rows.append({
        "קטגוריה":       cat,
        "פקיעות":        len(cat_df),
        "תנועה ממוצעת":  cat_df["move_pct"].abs().mean(),
        "מקסימום |move|": cat_df["move_pct"].abs().max(),
        ">2%":           (cat_df["move_pct"].abs() > 2).mean() * 100,
    })

if cat_rows:
    cat_summary = pd.DataFrame(cat_rows).sort_values("תנועה ממוצעת", ascending=False)

    with col_cat_chart:
        colors = [_CAT_COLORS.get(c, "#aaa") for c in cat_summary["קטגוריה"]]
        fig_cat = go.Figure(go.Bar(
            x=cat_summary["קטגוריה"],
            y=cat_summary["תנועה ממוצעת"].round(2),
            marker_color=colors,
            text=cat_summary["תנועה ממוצעת"].apply(lambda v: f"{v:.2f}%"),
            textposition="outside",
            hovertemplate="קטגוריה: %{x}<br>תנועה ממוצעת: %{y:.2f}%<extra></extra>",
        ))
        # baseline: avg without events
        baseline = without_ev["move_pct"].abs().mean() if not without_ev.empty else 0
        fig_cat.add_hline(
            y=baseline,
            line_dash="dash",
            line_color="#555",
            line_width=1.5,
            annotation_text=f"בסיס (ללא אירוע): {baseline:.2f}%",
            annotation_position="top right",
        )
        fig_cat.update_layout(
            yaxis_title="תנועה ממוצעת |move_pct| (%)",
            xaxis_title="",
            height=360,
            margin=dict(t=30, r=40),
            showlegend=False,
        )
        st.plotly_chart(fig_cat, use_container_width=True, key="cat_bar")

    with col_cat_table:
        tbl = cat_summary.copy()
        tbl["תנועה ממוצעת"] = tbl["תנועה ממוצעת"].round(2)
        tbl["מקסימום |move|"] = tbl["מקסימום |move|"].round(2)
        tbl[">2%"] = tbl[">2%"].round(1)
        st.dataframe(
            tbl,
            hide_index=True,
            use_container_width=True,
            column_config={
                "תנועה ממוצעת":  st.column_config.NumberColumn(format="%.2f%%"),
                "מקסימום |move|": st.column_config.NumberColumn(format="%.2f%%"),
                ">2%":            st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

st.markdown("---")

# ─── Section 5: Upcoming expiry risk score ───────────────────────────
st.subheader("5. ציון סיכון לפקיעה הקרובה")

col_risk_in, col_risk_out = st.columns([1, 2], gap="large")

with col_risk_in:
    upcoming = st.date_input(
        "תאריך פקיעה קרובה",
        value=date.today() + timedelta(days=7),
        key="upcoming_date_input",
    )
    risk_window = st.slider("חלון חיפוש (ימים לפני פקיעה)", 3, 14, 7, key="risk_window")

risk = compute_risk_score(upcoming, engine, df_hist, window_days=risk_window)

with col_risk_out:
    score_color = (
        "#27ae60" if risk["score"] < 3.5
        else "#e74c3c" if risk["score"] >= 6.5
        else "#e67e22"
    )
    level_emoji = {"נמוך": "🟢", "בינוני": "🟡", "גבוה": "🔴"}.get(risk["level"], "⚪")

    st.markdown(
        f"""
<div style="border:1px solid {score_color}44; border-radius:12px; padding:16px 22px;
            background:linear-gradient(135deg,{score_color}10,transparent)">
  <div style="font-size:0.9em; color:#666; margin-bottom:4px">
    ציון סיכון תנודתיות — פקיעה {upcoming.strftime('%d/%m/%Y')}
  </div>
  <div style="font-size:2.4em; font-weight:800; color:{score_color}; margin-bottom:4px">
    {risk['score']:.1f} / 10 &nbsp; {level_emoji} {risk['level']}
  </div>
  <div style="font-size:0.85em; color:#555">
""",
        unsafe_allow_html=True,
    )

    if risk["nearby_events"]:
        st.markdown(
            "**אירועים בחלון:** " + " · ".join(risk["nearby_events"]),
        )
    else:
        st.markdown("**אין אירועים מוכרים בחלון הזמן הנבחר.**")

    if risk["avg_abs_move_event"] and risk["avg_abs_move_normal"]:
        st.markdown(
            f"תנועה ממוצעת עם אירוע: **{risk['avg_abs_move_event']:.2f}%** "
            f"לעומת ללא אירוע: **{risk['avg_abs_move_normal']:.2f}%**"
        )

    st.markdown("</div>", unsafe_allow_html=True)

    # ── strategy recommendation based on risk ──
    st.markdown("")
    if risk["score"] >= 6.5:
        st.info(
            "💡 **סיכון גבוה** — תנאי שוק עם אירועים מגדילים תנודתיות. "
            "שקול **Long Straddle / Strangle** (מנצחים בתנועות חזקות). "
            "הימנע מ-Iron Condor ו-Butterfly בקרבת אירועים."
        )
    elif risk["score"] >= 3.5:
        st.info(
            "💡 **סיכון בינוני** — בדוק את אופי האירוע. "
            "אירועי ריבית לרוב מניעים שוק מכוון; "
            "אירועי מלחמה מוסיפים אי-ודאות. "
            "שמור על גמישות בין Condor ל-Straddle."
        )
    else:
        st.info(
            "💡 **סיכון נמוך** — ללא אירועים מוכרים בחלון. "
            "**Short Iron Condor / Butterfly** מתאימים לתנועות קטנות. "
            "Win Rate היסטורי גבוה לאסטרטגיות ניטרליות."
        )

st.markdown("---")

# ─── Section 6: Expiries near events ────────────────────────────────
st.subheader("6. פקיעות קיצוניות — מוסברות על-ידי אירועים")

extreme_thresh = st.slider(
    "סף קיצוניות |move_pct| (%)",
    min_value=1.0, max_value=5.0, value=2.5, step=0.5,
    key="extreme_slider",
)

extreme = enriched[valid & (enriched["move_pct"].abs() >= extreme_thresh)].copy()
extreme_sorted = extreme.sort_values("move_pct", key=abs, ascending=False)

if extreme_sorted.empty:
    st.info("אין פקיעות מעל הסף הנבחר.")
else:
    pct_explained = (extreme_sorted["has_event"].mean() * 100)
    st.caption(
        f"נמצאו **{len(extreme_sorted):,}** פקיעות מעל {extreme_thresh:.1f}% | "
        f"**{pct_explained:.1f}%** מהן מוסברות על-ידי אירוע מוכר בחלון 7 ימים"
    )

    disp = extreme_sorted.head(30)[[
        "expiry_date", "expiry_type", "move_pct", "has_event", "event_names"
    ]].copy()
    disp["expiry_date"] = disp["expiry_date"].dt.strftime("%d/%m/%Y")
    disp["move_pct"]    = disp["move_pct"].round(2)
    disp = disp.rename(columns={
        "expiry_date":  "תאריך",
        "expiry_type":  "סוג",
        "move_pct":     "תנועה (%)",
        "has_event":    "אירוע?",
        "event_names":  "אירועים",
    })
    st.dataframe(
        disp,
        hide_index=True,
        use_container_width=True,
        column_config={
            "תנועה (%)": st.column_config.NumberColumn(format="%+.2f%%"),
            "אירוע?":    st.column_config.CheckboxColumn(),
        },
    )

# ─── Section 7: Telegram news ────────────────────────────────────────
st.markdown("---")
st.subheader("7. 📡 חדשות מטלגרם אחרונות")

try:
    from events import load_events_by_source as _load_tg
    _tg_df = _load_tg(engine, source="interactiveil", limit=10)
    if _tg_df.empty:
        st.info(
            "אין חדשות מטלגרם עדיין. "
            "הגדר Telegram Bot שישלח POST ל-`http://<server>:8502/webhook/telegram`."
        )
    else:
        _tg_disp = _tg_df.copy()
        _tg_disp["event_date"] = _tg_disp["event_date"].dt.strftime("%d/%m/%Y")
        _tg_disp = _tg_disp.rename(columns={
            "event_date": "תאריך",
            "name":       "כותרת",
            "category":   "קטגוריה",
        })
        st.dataframe(
            _tg_disp[["תאריך", "קטגוריה", "כותרת"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "תאריך":    st.column_config.TextColumn(width="small"),
                "קטגוריה":  st.column_config.TextColumn(width="small"),
            },
        )
except Exception as _tg_exc:
    st.warning(f"לא ניתן לטעון חדשות טלגרם: {_tg_exc}")

# ─── Disclaimer ──────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "⚠️ **הצהרת אחריות:** הניתוח מבוסס על קישור סטטיסטי בין פקיעות לאירועים — "
    "לא קשר סיבתי מוכח. ציון הסיכון הוא אינדיקטור תיאורטי בלבד. "
    "אין לראות בניתוח זה המלצת מסחר. מסחר באופציות כרוך בסיכון של אובדן מלא."
)
