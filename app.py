"""
TA-35 Expiry Intelligence Dashboard — דף בית
"""
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from styles import inject_global_css

_PROJECT_ROOT = Path(__file__).parent

# ─── Page config ────────────────────────────────────────────────────
st.set_page_config(
    page_title="TA-35 Expiry Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_global_css()

# ─── Hero header ────────────────────────────────────────────────────
st.markdown(
    """
    <div style="
        background: linear-gradient(135deg, #1a2744 0%, #0f1a30 100%);
        border-radius: 16px;
        padding: 40px 32px;
        margin-bottom: 28px;
        border-bottom: 4px solid #c9a84c;
        text-align: center;
    ">
        <div style="font-size: 3.2em; margin-bottom: 8px;">📊</div>
        <h1 style="
            color: #c9a84c;
            font-size: 2.2em;
            margin: 0 0 8px 0;
            direction: rtl;
        ">TA-35 Expiry Intelligence</h1>
        <p style="
            color: #c8d6e8;
            font-size: 1.1em;
            margin: 0;
            direction: rtl;
        ">מערכת ניתוח הסתברותי של פקיעות מדד TA-35 — 965+ פקיעות היסטוריות, 6 אסטרטגיות אופציות</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ─── Navigation cards ────────────────────────────────────────────────
_PAGES = [
    {
        "emoji": "📊",
        "title": "ניתוח היסטורי",
        "desc": "התפלגות תנועות, % עליות/ירידות, פירוט לפי שנה וסוג פקיעה",
        "color": "#27ae60",
    },
    {
        "emoji": "📈",
        "title": "השוואת אסטרטגיות",
        "desc": "Win Rate של 6 אסטרטגיות על 25 וריאנטים — grid search על כל הפרמטרים",
        "color": "#2980b9",
    },
    {
        "emoji": "🎯",
        "title": "פקיעה קרובה",
        "desc": "שרשרת אופציות עדכנית, זיהוי ATM, המלצה מבוססת הקשר היסטורי",
        "color": "#c9a84c",
    },
    {
        "emoji": "📅",
        "title": "אירועים והקשר",
        "desc": "22 אירועים היסטוריים (מלחמות, ריבית, מגפות) ו-ציון הסיכון לפקיעה",
        "color": "#e74c3c",
    },
]

st.markdown("### ניווט מהיר")
cols = st.columns(4)
for col, page in zip(cols, _PAGES):
    with col:
        st.markdown(
            f"""
            <div style="
                background: #1a2744;
                border-radius: 12px;
                padding: 24px 16px;
                text-align: center;
                border-top: 4px solid {page['color']};
                height: 170px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 8px;
            ">
                <div style="font-size: 2.4em;">{page['emoji']}</div>
                <div style="color: {page['color']}; font-weight: 700; font-size: 1em; direction: rtl;">{page['title']}</div>
                <div style="color: #c8d6e8; font-size: 0.8em; direction: rtl; line-height: 1.4;">{page['desc']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# ─── System status ──────────────────────────────────────────────────
st.markdown("### סטטוס מערכת")

_s1, _s2, _s3, _s4 = st.columns(4)

# 1. Historical data
with _s1:
    try:
        from data_loader import get_engine, load_from_db
        _engine = get_engine(_PROJECT_ROOT / "database" / "ta35.db")
        _df = load_from_db(_engine)
        _n = len(_df)
        _last_date = str(_df["expiry_date"].max().date()) if _n else "—"
        st.metric("פקיעות היסטוריות", f"{_n:,}", f"עד {_last_date}")
    except Exception:
        st.metric("פקיעות היסטוריות", "לא טעון", "")

# 2. Options chain
with _s2:
    _chain_path = _PROJECT_ROOT / "data" / "current" / "putvscall.csv"
    _chain_outer = _PROJECT_ROOT.parent / "data" / "current" / "putvscall.csv"
    for _p in [_chain_path, _chain_outer]:
        if _p.exists():
            _mtime = datetime.fromtimestamp(_p.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            st.metric("שרשרת אופציות", "טעונה", f"עודכן {_mtime}")
            break
    else:
        st.metric("שרשרת אופציות", "לא נמצאה", "העלה putvscall.csv")

# 3. Events
with _s3:
    try:
        from events import load_all_events
        _ev_engine = get_engine(_PROJECT_ROOT / "database" / "ta35.db")
        _ev = load_all_events(_ev_engine)
        st.metric("אירועים במסד", f"{len(_ev)}", "")
    except Exception:
        st.metric("אירועים במסד", "—", "")

# 4. Last update
with _s4:
    st.metric("תאריך עדכון", "19/05/2026", "")

# ─── Description ────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    """
    <div style="direction: rtl; text-align: right; line-height: 1.9;">
    <b>מה המערכת עושה:</b><br>
    • מנתחת 965+ פקיעות היסטוריות של מדד TA-35 מ-2010 עד היום<br>
    • מלבישה 6 אסטרטגיות אופציות (Iron Condor, Butterfly, Straddle ועוד) על כל פקיעה<br>
    • מחשבת Win Rate לכל אסטרטגיה עם grid search על הפרמטרים המיטביים<br>
    • מאתרת מקרים היסטוריים דומים לפקיעה הקרובה (סוג + עונתיות + תנועה אחרונה)<br>
    • מצליבה עם 22 אירועים היסטוריים וחישוב ציון סיכון לפקיעה הקרובה<br>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("---")
st.caption("⚠️ כלי מחקר בלבד — אינו מהווה המלצת מסחר. אין אחריות לדיוק הנתונים.")
