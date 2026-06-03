"""
דף Paper Trading — ניהול תיקי דמו
"""
import sys
from pathlib import Path

import streamlit as st

_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from paper_db import create_portfolio, get_portfolios, get_trades, has_paper_db
from styles import inject_global_css

st.set_page_config(
    page_title="תיקי דמו — TA-35",
    page_icon="📊",
    layout="wide",
)

inject_global_css()

# ─── כותרת + disclaimer בולט ────────────────────────────────────────
st.title("📊 תיקי דמו")
st.markdown(
    """
    <div style='background:#1a2744; border:2px solid #c9a84c; border-radius:8px;
                padding:12px 18px; margin-bottom:16px; text-align:right'>
    ⚠️ <strong style='color:#c9a84c'>כלי מחקר בלבד — לא ייעוץ השקעות</strong><br>
    <span style='color:#c8d6e8; font-size:0.9rem'>
    כל הנתונים והתוצאות הן סימולציה היסטורית בלבד. אין להסתמך עליהם לצורך מסחר אמיתי.
    </span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ─── בדיקת DB ───────────────────────────────────────────────────────
if not has_paper_db():
    st.warning("⚠️ DATABASE_URL לא מוגדר — paper trading אינו זמין בסביבה זו.")
    st.stop()

# ─── Session state ───────────────────────────────────────────────────
if "selected_portfolio_id" not in st.session_state:
    st.session_state["selected_portfolio_id"] = None

# ─── תצוגת תיק נבחר (placeholder) ──────────────────────────────────
if st.session_state["selected_portfolio_id"] is not None:
    pid = st.session_state["selected_portfolio_id"]
    if st.button("← חזור לכל התיקים"):
        st.session_state["selected_portfolio_id"] = None
        st.rerun()
    st.subheader(f"📁 תצוגה מפורטת — תיק #{pid}")
    st.info("תצוגת עסקאות מפורטת תיבנה בשלב הבא.")
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
            p_comm = st.number_input(
                "עמלה לכל רגל (₪)", min_value=0.0, value=2.5, step=0.5
            )
        submitted = st.form_submit_button("✅ צור תיק")
        if submitted:
            if not p_name.strip():
                st.error("נא להזין שם לתיק.")
            else:
                result = create_portfolio(p_name.strip(), p_balance, p_comm)
                if result:
                    st.success(
                        f"✅ תיק «{result['name']}» נוצר (הון: ₪{p_balance:,.0f} | עמלה: ₪{p_comm:.1f}/רגל)"
                    )
                    st.rerun()
                else:
                    st.error("❌ שגיאה ביצירת התיק — בדוק חיבור DB.")

# ─── טעינת תיקים ────────────────────────────────────────────────────
portfolios = get_portfolios()

if not portfolios:
    st.info("אין תיקים פעילים. צור תיק חדש בעזרת הכפתור למעלה.")
    st.stop()

st.markdown(f"### תיקים פעילים ({len(portfolios)})")

# ─── כרטיסי תיקים ───────────────────────────────────────────────────

_COLS = 3


def _portfolio_card(p: dict) -> None:
    """מציג כרטיס HTML של תיק + כפתור פתיחה."""
    pid        = p["id"]
    name       = p.get("name") or f"תיק #{pid}"
    initial    = float(p.get("initial_balance") or 0)
    current    = float(p.get("current_balance") or 0)
    commission = float(p.get("commission_per_leg") or 2.5)

    pnl     = current - initial
    pnl_pct = (pnl / initial * 100) if initial > 0 else 0.0
    pnl_color = "#27ae60" if pnl >= 0 else "#e74c3c"
    sign      = "+" if pnl >= 0 else ""

    trades       = get_trades(portfolio_id=pid)
    open_count   = sum(1 for t in trades if t.get("status") == "open")
    closed_count = sum(1 for t in trades if t.get("status") == "closed")

    st.markdown(
        f"""
        <div style='background:#1a2744; border:1px solid #2a3d6b; border-radius:12px;
                    padding:18px; margin-bottom:8px; border-top:3px solid #c9a84c'>
          <div style='font-size:1.1rem; font-weight:700; color:#e0e6f0; margin-bottom:12px'>
            {name}
          </div>
          <div style='display:flex; justify-content:space-between; margin-bottom:6px'>
            <span style='color:#7a9ab8; font-size:0.85rem'>שווי נוכחי</span>
            <span style='color:#e0e6f0; font-weight:600'>₪{current:,.0f}</span>
          </div>
          <div style='display:flex; justify-content:space-between; margin-bottom:6px'>
            <span style='color:#7a9ab8; font-size:0.85rem'>שווי התחלתי</span>
            <span style='color:#c8d6e8'>₪{initial:,.0f}</span>
          </div>
          <div style='display:flex; justify-content:space-between; margin-bottom:6px'>
            <span style='color:#7a9ab8; font-size:0.85rem'>תשואה</span>
            <span style='color:{pnl_color}; font-weight:700'>
              {sign}₪{pnl:,.0f}&nbsp;({sign}{pnl_pct:.1f}%)
            </span>
          </div>
          <div style='display:flex; justify-content:space-between; margin-bottom:6px'>
            <span style='color:#7a9ab8; font-size:0.85rem'>עסקאות פתוחות / סגורות</span>
            <span style='color:#c8d6e8'>{open_count} / {closed_count}</span>
          </div>
          <div style='display:flex; justify-content:space-between; margin-bottom:14px'>
            <span style='color:#7a9ab8; font-size:0.85rem'>עמלה לרגל</span>
            <span style='color:#c9a84c'>₪{commission:.1f}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("פתח →", key=f"open_p_{pid}"):
        st.session_state["selected_portfolio_id"] = pid
        st.rerun()


for row_start in range(0, len(portfolios), _COLS):
    cols = st.columns(_COLS)
    for col_idx, col in enumerate(cols):
        idx = row_start + col_idx
        if idx >= len(portfolios):
            break
        with col:
            _portfolio_card(portfolios[idx])

# ─── Disclaimer footer ───────────────────────────────────────────────
st.divider()
st.caption("⚠️ כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה היסטורית.")
