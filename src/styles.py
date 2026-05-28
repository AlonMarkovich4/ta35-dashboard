"""
עיצוב גלובלי — CSS משותף לכל דפי הדשבורד.
"""
import streamlit as st

_CSS = """
<style>
/* ── No horizontal scroll ── */
body {
    overflow-x: hidden;
    max-width: 100%;
}
.main {
    overflow-x: hidden;
    max-width: 100%;
}
*, *::before, *::after {
    max-width: 100%;
    box-sizing: border-box;
}

/* ── RTL ── */
.main, [data-testid="stSidebar"], .block-container {
    direction: rtl;
    text-align: right;
}
.stDataFrame, .stTable {
    direction: rtl;
}
h1, h2, h3, p, label, .stMarkdown {
    direction: rtl;
    text-align: right;
}
/* Plotly charts inherit body direction — keep charts LTR */
.js-plotly-plot {
    direction: ltr;
}

/* ── Brand palette ── */
:root {
    --brand-blue: #1a2744;
    --brand-gold: #c9a84c;
}

/* ── Sidebar: narrower + accent ── */
[data-testid="stSidebar"] {
    min-width: 200px !important;
    max-width: 200px !important;
    width: 200px !important;
    border-right: 3px solid var(--brand-gold);
    background-color: #0f1a30;
}
[data-testid="stSidebar"] > div:first-child {
    width: 200px !important;
}
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span {
    color: #e0e6f0;
}

/* ── Sliders: contained, no overflow ── */
[data-testid="stSlider"] {
    max-width: 100%;
    overflow: hidden;
    padding-left: 20px;
    padding-right: 20px;
    box-sizing: border-box;
}
[data-testid="stSlider"] > div {
    max-width: 100%;
    overflow: hidden;
}

/* ── Block containers with padding guard ── */
.block-container {
    padding-left: 2rem;
    padding-right: 2rem;
    max-width: 100%;
    overflow-x: hidden;
}

/* ── Buttons ── */
.stButton > button {
    background-color: var(--brand-blue);
    color: var(--brand-gold);
    border: 2px solid var(--brand-gold);
    border-radius: 8px;
    font-weight: bold;
    transition: background-color 0.2s, color 0.2s;
}
.stButton > button:hover {
    background-color: var(--brand-gold);
    color: var(--brand-blue);
}

/* ── Rounded metric / info cards ── */
[data-testid="stMetric"] {
    background: #f0f4fa;
    border-radius: 10px;
    padding: 12px;
    border-top: 3px solid var(--brand-gold);
}
[data-testid="stMetricValue"] {
    color: var(--brand-blue);
    font-weight: 700;
}

/* ── Expanders ── */
details {
    border: 1px solid #d0d9e8;
    border-radius: 8px;
    margin-bottom: 6px;
}
details summary {
    padding: 10px 14px;
    font-weight: 600;
    color: #e8edf5;
    font-size: 1.05rem;
}
</style>
"""


def inject_global_css() -> None:
    """מזריק CSS גלובלי של מותג + RTL לכל הדפים."""
    st.markdown(_CSS, unsafe_allow_html=True)
