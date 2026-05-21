"""
דף השוואת אסטרטגיות — TA-35 Expiry Intelligence
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from backtester import best_per_strategy, run_backtest
from data_loader import get_engine, load_from_db, run_full_load
from styles import inject_global_css

_PROJECT_ROOT = Path(__file__).parent.parent

# ─── תיאורים קצרים לכל אסטרטגיה (שכבת תצוגה) ──────────────────────
_STRATEGY_DESC: dict[int, str] = {
    1: "מנצחת כשהמדד **עולה** (move_pct > 0). רוחב הספרד קובע תקרת רווח.",
    2: "מנצחת כשהמדד **נשאר בתוך ±טווח%** מהבסיס. מוכר טווח רחב.",
    3: "מנצחת כשהפקיעה **ממש ליד ATM** — תנועה קטנה מרוחב הכנף.",
    4: "מבנה מראה של Call Butterfly. אותו תנאי ניצחון — תנועה קטנה.",
    5: "מנצחת בתנועה **חזקה לכל כיוון** (מעל סף שבירת פרמיה).",
    6: "קנייה OTM — דורשת תנועה **גדולה יותר** מ-Straddle לשביר.",
}

# ─── Page config ────────────────────────────────────────────────────
st.set_page_config(
    page_title="השוואת אסטרטגיות — TA-35",
    page_icon="📈",
    layout="wide",
)

inject_global_css()

st.title("📈 השוואת אסטרטגיות — TA-35")
st.markdown("Win Rate של 6 אסטרטגיות אופציות על פקיעות היסטוריות — grid search על כל פרמטרי האפיון")


# ─── Load helpers ───────────────────────────────────────────────────
def _find_csv() -> Path:
    for p in [
        _PROJECT_ROOT / "data" / "uploads" / "market_data.csv",
        _PROJECT_ROOT.parent / "data" / "uploads" / "market_data.csv",
    ]:
        if p.exists():
            return p
    raise FileNotFoundError("market_data.csv לא נמצא ב-data/uploads/")


def _db_engine():
    return get_engine(_PROJECT_ROOT / "database" / "ta35.db")


# ─── Load button ────────────────────────────────────────────────────
col_btn, col_msg = st.columns([1, 4])
with col_btn:
    load_clicked = st.button("⬇️ טען נתונים", use_container_width=True, type="primary")

if load_clicked:
    with col_msg:
        with st.spinner("טוען..."):
            try:
                count = run_full_load(
                    csv_path=_find_csv(),
                    db_path=_PROJECT_ROOT / "database" / "ta35.db",
                )
                st.success(f"✅ {count:,} פקיעות נטענו")
                st.session_state.pop("hist_df", None)
            except Exception as exc:
                st.error(f"❌ {exc}")
                st.stop()

# ─── Load from DB ───────────────────────────────────────────────────
if "hist_df" not in st.session_state:
    try:
        _df = load_from_db(_db_engine())
        if not _df.empty:
            st.session_state["hist_df"] = _df
    except Exception:
        pass

df_all: pd.DataFrame | None = st.session_state.get("hist_df")

if df_all is None or df_all.empty:
    st.info("לחץ **⬇️ טען נתונים** כדי לטעון את הפקיעות ההיסטוריות")
    st.stop()

# ─── Sidebar filters ────────────────────────────────────────────────
with st.sidebar:
    st.header("🔍 סינון")

    _type_map = {"הכל": None, "W — שבועי": "W", "M — חודשי": "M"}
    type_label = st.radio("סוג פקיעה", list(_type_map.keys()), index=0)
    type_filter: str | None = _type_map[type_label]

    years = sorted(df_all["expiry_date"].dt.year.dropna().unique().astype(int))
    year_from, year_to = st.slider(
        "טווח שנים",
        min_value=years[0],
        max_value=years[-1],
        value=(years[0], years[-1]),
    )

    st.markdown("---")
    st.caption(f"נטענו {len(df_all):,} פקיעות בסה״כ")

# ─── Run backtest ───────────────────────────────────────────────────
results = run_backtest(
    df_all,
    expiry_type=type_filter,
    year_from=year_from,
    year_to=year_to,
)

if results.empty or results["total"].iloc[0] == 0:
    st.warning("אין פקיעות לסינון הנבחר.")
    st.stop()

best = best_per_strategy(results)
n_expiries = results["total"].iloc[0]

st.caption(
    f"מבוסס על **{n_expiries:,}** פקיעות | "
    f"סוג: **{type_label}** | שנים: **{year_from}–{year_to}**"
)
st.markdown("---")


# ─── Section 1: Summary table + bar chart ───────────────────────────
st.subheader("סיכום — הפרמטר המיטבי לכל אסטרטגיה")

col_tbl, col_chart = st.columns([2, 3], gap="large")

with col_tbl:
    display = best[["strategy_id", "strategy_name", "params_repr", "win_rate", "wins", "losses"]].copy()
    display["win_rate_pct"] = (display["win_rate"] * 100).round(1)
    display = display.rename(columns={
        "strategy_id":   "#",
        "strategy_name": "אסטרטגיה",
        "params_repr":   "פרמטר מיטבי",
        "wins":          "ניצחונות",
        "losses":        "הפסדות",
    }).drop(columns=["win_rate"])

    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "win_rate_pct": st.column_config.ProgressColumn(
                "Win Rate %",
                format="%.1f%%",
                min_value=0,
                max_value=100,
            ),
        },
    )

with col_chart:
    bar_df = best.sort_values("win_rate").copy()
    bar_df["label"] = bar_df["win_rate"].apply(lambda x: f"{x:.1%}")
    bar_df["צבע"] = bar_df["win_rate"].apply(
        lambda x: "מעל 50%" if x >= 0.5 else "מתחת 50%"
    )

    fig_bar = px.bar(
        bar_df,
        x="win_rate",
        y="strategy_name",
        orientation="h",
        color="צבע",
        color_discrete_map={"מעל 50%": "#27ae60", "מתחת 50%": "#e74c3c"},
        text="label",
        hover_data={"params_repr": True, "wins": True, "losses": True,
                    "win_rate": False, "צבע": False},
        labels={"win_rate": "Win Rate", "strategy_name": "אסטרטגיה"},
        title="Win Rate לפי אסטרטגיה (פרמטר מיטבי)",
    )
    fig_bar.add_vline(
        x=0.5, line_dash="dash", line_color="#555", line_width=1.5,
        annotation_text="50%", annotation_position="top",
    )
    fig_bar.update_traces(textposition="outside", cliponaxis=False)
    fig_bar.update_layout(
        xaxis=dict(tickformat=".0%", range=[0, 1.05], title="Win Rate"),
        yaxis_title="",
        showlegend=True,
        legend_title="",
        legend=dict(orientation="h", yanchor="bottom", y=-0.25),
        coloraxis_showscale=False,
        height=380,
        margin=dict(r=60),
    )
    st.plotly_chart(fig_bar, use_container_width=True, key="chart_summary_bar")

st.markdown("---")


# ─── Section 2: Per-strategy expanders ─────────────────────────────
st.subheader("פירוט וריאנטים לפי אסטרטגיה")

for _, best_row in best.iterrows():
    sid = int(best_row["strategy_id"])
    sname = best_row["strategy_name"]
    best_wr = best_row["win_rate"]

    with st.expander(
        f"**#{sid} — {sname}** &nbsp;&nbsp; Win Rate מיטבי: **{best_wr:.1%}**",
        expanded=False,
    ):
        # תיאור האסטרטגיה
        st.markdown(_STRATEGY_DESC.get(sid, ""))
        st.markdown("")

        variants = (
            results[results["strategy_id"] == sid]
            .sort_values("win_rate", ascending=False)
            .reset_index(drop=True)
        )

        col_v_tbl, col_v_chart = st.columns([1, 1], gap="medium")

        # --- טבלת וריאנטים ---
        with col_v_tbl:
            v_display = variants[["params_repr", "win_rate", "wins", "losses"]].copy()
            v_display["win_rate_pct"] = (v_display["win_rate"] * 100).round(1)
            v_display = v_display.drop(columns=["win_rate"]).rename(columns={
                "params_repr":  "פרמטר",
                "wins":         "ניצחונות",
                "losses":       "הפסדות",
            })
            st.dataframe(
                v_display,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "win_rate_pct": st.column_config.ProgressColumn(
                        "Win Rate %",
                        format="%.1f%%",
                        min_value=0,
                        max_value=100,
                    ),
                },
            )

        # --- גרף mini: win_rate לפי פרמטר ---
        with col_v_chart:
            wr_range = variants["win_rate"].max() - variants["win_rate"].min()

            if wr_range < 0.001:
                # כל הוריאנטים זהים (למשל Bull Call Spread — win_rate לא תלוי ברוחב)
                st.info(
                    f"Win Rate זהה לכל הוריאנטים: **{best_wr:.1%}**\n\n"
                    "רוחב הספרד משפיע על גובה הרווח, לא על הסתברות הניצחון."
                )
            else:
                mini_df = variants.sort_values("param_value")
                mini_df["label"] = mini_df["win_rate"].apply(lambda x: f"{x:.1%}")

                fig_mini = px.bar(
                    mini_df,
                    x="params_repr",
                    y="win_rate",
                    text="label",
                    color="win_rate",
                    color_continuous_scale=["#e74c3c", "#f39c12", "#27ae60"],
                    range_color=[
                        max(0, variants["win_rate"].min() - 0.05),
                        min(1, variants["win_rate"].max() + 0.05),
                    ],
                    labels={"params_repr": "פרמטר", "win_rate": "Win Rate"},
                )
                fig_mini.add_hline(
                    y=0.5, line_dash="dash", line_color="#555", line_width=1,
                    annotation_text="50%", annotation_position="right",
                )
                fig_mini.update_traces(textposition="outside", cliponaxis=False)
                fig_mini.update_layout(
                    height=280,
                    coloraxis_showscale=False,
                    yaxis=dict(
                        tickformat=".0%",
                        range=[0, min(1.1, variants["win_rate"].max() + 0.15)],
                        title="Win Rate",
                    ),
                    xaxis_title="",
                    showlegend=False,
                    margin=dict(t=10, b=10, l=10, r=40),
                )
                st.plotly_chart(fig_mini, use_container_width=True, key=f"chart_mini_{sid}")


# ─── Disclaimer ─────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "⚠️ **הצהרת אחריות:** Win Rate הסטורי אינו מבטיח תוצאות עתידיות. "
    "הניתוח מבוסס על כיוון התנועה בלבד — אינו מחשב פרמיות אופציות, עלויות עסקה, "
    "או סיכון אמיתי. מסחר באופציות כרוך בסיכון של אובדן מלא. "
    "מערכת זו היא כלי מחקר בלבד ואינה מהווה המלצת מסחר."
)
