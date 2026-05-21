"""
דף ניתוח היסטורי — פקיעות TA-35
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from data_loader import get_engine, load_from_db, run_full_load
from styles import inject_global_css

_PROJECT_ROOT = Path(__file__).parent.parent

# ------------------------------------------------------------------ #
#  Page config
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="ניתוח היסטורי — TA-35",
    page_icon="📊",
    layout="wide",
)

inject_global_css()

st.title("📊 ניתוח היסטורי — פקיעות TA-35")
st.markdown("ניתוח סטטיסטי של 965+ פקיעות מדד TA-35 בין השנים 2010–2026")

# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #

def _find_csv() -> Path:
    """מאתר את market_data.csv — בודק תחילה בתוך הפרויקט, אחר כך בתיקיית-אב."""
    for candidate in [
        _PROJECT_ROOT / "data" / "uploads" / "market_data.csv",
        _PROJECT_ROOT.parent / "data" / "uploads" / "market_data.csv",
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "market_data.csv לא נמצא. הנח את הקובץ ב-data/uploads/"
    )


def _db_engine():
    """מחזיר engine ל-ta35.db."""
    return get_engine(_PROJECT_ROOT / "database" / "ta35.db")


# ------------------------------------------------------------------ #
#  Load button
# ------------------------------------------------------------------ #

col_btn, col_status = st.columns([1, 4])
with col_btn:
    load_clicked = st.button("⬇️ טען נתונים", use_container_width=True, type="primary")

if load_clicked:
    with col_status:
        with st.spinner("טוען, מנקה ושומר לבסיס הנתונים..."):
            try:
                csv_path = _find_csv()
                count = run_full_load(
                    csv_path=csv_path,
                    db_path=_PROJECT_ROOT / "database" / "ta35.db",
                )
                st.success(f"✅ נטענו {count:,} פקיעות בהצלחה מ-{csv_path.name}")
                st.session_state.pop("hist_df", None)
            except FileNotFoundError as exc:
                st.error(f"❌ {exc}")
                st.stop()
            except Exception as exc:
                st.error(f"❌ שגיאה בטעינה: {exc}")
                st.stop()

# ------------------------------------------------------------------ #
#  Load from DB (cached in session_state)
# ------------------------------------------------------------------ #

if "hist_df" not in st.session_state:
    try:
        _df = load_from_db(_db_engine())
        if not _df.empty:
            st.session_state["hist_df"] = _df
    except Exception:
        pass

df_all: pd.DataFrame | None = st.session_state.get("hist_df")

if df_all is None or df_all.empty:
    st.info("לחץ **⬇️ טען נתונים** כדי לטעון את הפקיעות ההיסטוריות מה-CSV")
    st.stop()

# ------------------------------------------------------------------ #
#  Sidebar filters
# ------------------------------------------------------------------ #

with st.sidebar:
    st.header("🔍 סינון")

    _type_map = {"הכל": None, "W — שבועי": "W", "M — חודשי": "M"}
    selected_label = st.radio("סוג פקיעה", list(_type_map.keys()), index=0)
    type_filter: str | None = _type_map[selected_label]

    years_all = sorted(df_all["expiry_date"].dt.year.dropna().unique().astype(int))
    year_from, year_to = st.slider(
        "טווח שנים",
        min_value=years_all[0],
        max_value=years_all[-1],
        value=(years_all[0], years_all[-1]),
    )

# Apply filters
df_work = df_all[
    (df_all["expiry_date"].dt.year >= year_from)
    & (df_all["expiry_date"].dt.year <= year_to)
].copy()
if type_filter:
    df_work = df_work[df_work["expiry_type"] == type_filter]

df_valid = df_work[df_work["move_pct"].notna()].copy()

if df_valid.empty:
    st.warning("אין נתונים לסינון הנבחר.")
    st.stop()

# ------------------------------------------------------------------ #
#  Summary cards
# ------------------------------------------------------------------ #

total = len(df_valid)
pct_up = (df_valid["move_pct"] > 0).mean() * 100
pct_down = (df_valid["move_pct"] < 0).mean() * 100
avg_abs = df_valid["abs_move_pct"].mean()
median_abs = df_valid["abs_move_pct"].median()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("📋 סה״כ פקיעות", f"{total:,}")
c2.metric("⬆️ עליות", f"{pct_up:.1f}%")
c3.metric("⬇️ ירידות", f"{pct_down:.1f}%")
c4.metric("📏 תנועה ממוצעת", f"{avg_abs:.2f}%")
c5.metric("📏 חציון תנועה", f"{median_abs:.2f}%")

st.markdown("---")

# ------------------------------------------------------------------ #
#  Histogram — move_pct distribution
# ------------------------------------------------------------------ #

st.subheader("התפלגות תנועות פקיעה")

df_valid["כיוון"] = df_valid["move_pct"].apply(lambda x: "עלייה" if x >= 0 else "ירידה")

fig_hist = px.histogram(
    df_valid,
    x="move_pct",
    color="כיוון",
    color_discrete_map={"עלייה": "#27ae60", "ירידה": "#e74c3c"},
    nbins=60,
    opacity=0.85,
    barmode="overlay",
    labels={"move_pct": "תנועה (%)", "count": "מספר פקיעות"},
    title=f"התפלגות תנועות — {total:,} פקיעות ({year_from}–{year_to})",
)
fig_hist.add_vline(
    x=0, line_dash="dash", line_color="#555", line_width=1.5,
    annotation_text="אפס", annotation_position="top right",
)
fig_hist.update_layout(
    bargap=0.03,
    xaxis_title="תנועה (%)",
    yaxis_title="מספר פקיעות",
    legend_title="כיוון",
)
st.plotly_chart(fig_hist, use_container_width=True)

# ------------------------------------------------------------------ #
#  Breakdown table — W vs M
# ------------------------------------------------------------------ #

st.subheader("פירוט לפי סוג פקיעה")

_breakdown_src = df_all[
    (df_all["expiry_date"].dt.year >= year_from)
    & (df_all["expiry_date"].dt.year <= year_to)
    & df_all["move_pct"].notna()
].copy()

breakdown = (
    _breakdown_src.groupby("expiry_type")
    .agg(
        פקיעות=("move_pct", "count"),
        ממוצע_תנועה=("move_pct", "mean"),
        ממוצע_מוחלט=("abs_move_pct", "mean"),
        חציון_מוחלט=("abs_move_pct", "median"),
        עליות_pct=("move_pct", lambda s: round((s > 0).mean() * 100, 1)),
        ירידות_pct=("move_pct", lambda s: round((s < 0).mean() * 100, 1)),
        מקסימום=("move_pct", "max"),
        מינימום=("move_pct", "min"),
    )
    .round(2)
    .rename(index={"W": "שבועי (W)", "M": "חודשי (M)", "unknown": "לא ידוע"})
)
breakdown.index.name = "סוג"

st.dataframe(
    breakdown,
    use_container_width=True,
    column_config={
        "ממוצע_תנועה": st.column_config.NumberColumn("ממוצע תנועה (%)", format="%.2f"),
        "ממוצע_מוחלט": st.column_config.NumberColumn("ממוצע מוחלט (%)", format="%.2f"),
        "חציון_מוחלט": st.column_config.NumberColumn("חציון מוחלט (%)", format="%.2f"),
        "עליות_pct": st.column_config.NumberColumn("% עליות", format="%.1f"),
        "ירידות_pct": st.column_config.NumberColumn("% ירידות", format="%.1f"),
        "מקסימום": st.column_config.NumberColumn("מקסימום (%)", format="%.2f"),
        "מינימום": st.column_config.NumberColumn("מינימום (%)", format="%.2f"),
    },
)

st.markdown("---")

# ------------------------------------------------------------------ #
#  Yearly charts
# ------------------------------------------------------------------ #

st.subheader("תנועות לפי שנה")

df_valid["שנה"] = df_valid["expiry_date"].dt.year

tab_box, tab_avg = st.tabs(["📦 התפלגות שנתית (Box Plot)", "📊 ממוצע שנתי"])

with tab_box:
    fig_box = px.box(
        df_valid.sort_values("שנה"),
        x="שנה",
        y="move_pct",
        color_discrete_sequence=["#3498db"],
        labels={"שנה": "שנה", "move_pct": "תנועה (%)"},
        title="התפלגות תנועות לפי שנה",
    )
    fig_box.add_hline(y=0, line_dash="dash", line_color="#aaa", line_width=1)
    fig_box.update_layout(
        xaxis=dict(tickmode="linear", dtick=1, tickangle=-45),
        yaxis_title="תנועה (%)",
        xaxis_title="שנה",
        showlegend=False,
    )
    st.plotly_chart(fig_box, use_container_width=True)

with tab_avg:
    yearly = (
        df_valid.groupby("שנה")
        .agg(
            ממוצע_תנועה=("move_pct", "mean"),
            ממוצע_מוחלט=("abs_move_pct", "mean"),
            פקיעות=("move_pct", "count"),
        )
        .reset_index()
        .round(3)
    )
    yearly["צבע"] = yearly["ממוצע_תנועה"].apply(lambda x: "עלייה" if x >= 0 else "ירידה")
    yearly["label"] = yearly["ממוצע_תנועה"].apply(lambda x: f"{x:+.2f}%")

    fig_avg = px.bar(
        yearly,
        x="שנה",
        y="ממוצע_תנועה",
        color="צבע",
        text="label",
        color_discrete_map={"עלייה": "#27ae60", "ירידה": "#e74c3c"},
        labels={"שנה": "שנה", "ממוצע_תנועה": "תנועה ממוצעת (%)"},
        title="תנועה ממוצעת לפי שנה",
        hover_data={"פקיעות": True, "ממוצע_מוחלט": ":.2f", "label": False, "צבע": False},
    )
    fig_avg.update_traces(textposition="outside", cliponaxis=False)
    fig_avg.update_layout(
        xaxis=dict(tickmode="linear", dtick=1, tickangle=-45),
        yaxis_title="תנועה ממוצעת (%)",
        xaxis_title="שנה",
        showlegend=True,
        legend_title="כיוון",
    )
    fig_avg.add_hline(y=0, line_dash="dot", line_color="#888", line_width=1)
    st.plotly_chart(fig_avg, use_container_width=True)

# ------------------------------------------------------------------ #
#  Disclaimer
# ------------------------------------------------------------------ #

st.markdown("---")
st.caption(
    "⚠️ **הצהרת אחריות:** מערכת זו היא כלי מחקר בלבד. "
    "הנתונים המוצגים הם לצורך ניתוח סטטיסטי היסטורי בלבד ואינם מהווים המלצת מסחר, "
    "ייעוץ השקעות, או כל תחזית לביצועי עתיד. "
    "מסחר באופציות כרוך בסיכון גבוה, לרבות אובדן מלא של ההשקעה. "
    "אין להסתמך על נתונים אלה לצורך קבלת החלטות השקעה."
)
