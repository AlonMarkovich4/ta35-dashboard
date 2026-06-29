"""
דף מנוע ההחלטה — TA-35 Expiry Intelligence (Layer 1, shadow mode).

מציג את ההחלטה הנוכחית לפקיעה הקרובה (build_expiry_decision) ואת היסטוריית
ההחלטות שנשמרו (decision_log). קריאה בלבד — הדף אינו פותח עסקאות ואינו כותב ל-DB.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from context_analyzer import build_expiry_decision, get_recent_move
from data_loader import get_engine, load_from_db
from decision_recorder import record_decisions_for_upcoming
from paper_db import get_decision_logs, has_paper_db
from strategies import STRATEGIES
from styles import inject_global_css
from supabase_loader import get_available_expiries, get_latest_option_chain

try:
    from events import compute_risk_score
    _HAS_EVENTS = True
except Exception:  # noqa: BLE001
    _HAS_EVENTS = False

# ─── צבעים (זהה לשאר הדפים) ─────────────────────────────────────────
_DARK_BG = "#0e1117"
_GRID    = "#1e2d45"
_AXIS    = "#7a9ab8"
_GREEN   = "#27ae60"
_RED     = "#e74c3c"
_GOLD    = "#c9a84c"
_BLUE    = "#4a9fd4"

_REGIME_VIS = {
    "calm":     ("🟢", "רגוע",     _GREEN),
    "normal":   ("🔵", "רגיל",     _BLUE),
    "volatile": ("🔴", "תנודתי",   _RED),
    "unknown":  ("⚪", "לא ידוע",  _AXIS),
}

_CACHE_TTL = 300   # שניות

st.set_page_config(page_title="מנוע ההחלטה — TA-35", page_icon="🧭", layout="wide")
inject_global_css()


# ════════════════════════════════════════════════════════════════════════
#  שכבת DB מ-cached (engine יחיד; קריאות עם ttl)
# ════════════════════════════════════════════════════════════════════════

@st.cache_resource(show_spinner=False)
def _engine():
    return get_engine()


def _detect_next_expiry(eng):
    """מזהה את הפקיעה הקרובה (tase_putcall) + סוג; fallback לסימולציה."""
    today = pd.Timestamp.today().normalize()
    try:
        expiries = get_available_expiries(engine=eng) or []
    except Exception:  # noqa: BLE001
        expiries = []
    parsed = sorted(pd.Timestamp(e) for e in expiries) if expiries else []
    upcoming = [d for d in parsed if d >= today]
    if upcoming:
        nxt, src = upcoming[0], "פקיעה קרובה אמיתית"
    elif parsed:
        nxt, src = parsed[-1], "האחרונה הזמינה"
    else:
        nxt, src = today + pd.Timedelta(days=3), "סימולציה (אין שרשרת)"

    etype = "W"
    if expiries:
        try:
            chain = get_latest_option_chain(nxt.strftime("%Y-%m-%d"), engine=eng)
            ent = (chain or {}).get("expiries", [{}])[0]
            etype = "M" if "חודשי" in str(ent.get("expiry_type", "")) else "W"
        except Exception:  # noqa: BLE001
            pass
    return nxt, etype, src


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _current_decision() -> dict:
    """מריץ את מנוע ההחלטה על הפקיעה הקרובה (before_date=None — פקיעה חיה)."""
    eng = _engine()
    df = load_from_db(eng)
    df = df[df["move_pct"].notna()].copy()
    nxt, etype, src = _detect_next_expiry(eng)
    recent = get_recent_move(df, nxt)
    risk = None
    if _HAS_EVENTS:
        try:
            risk = compute_risk_score(nxt.date(), eng, df).get("score")
        except Exception:  # noqa: BLE001
            risk = None
    decision = build_expiry_decision(
        df, etype, int(nxt.month), nxt, recent_move_pct=recent, risk_score=risk,
    )
    return {"decision": decision, "expiry": str(nxt.date()),
            "expiry_type": etype, "source": src}


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _logs(limit: int = 50) -> list[dict]:
    return get_decision_logs(limit=limit, engine=_engine())


# ════════════════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════════════════

def _pct(v) -> str:
    return f"{v * 100:.0f}%" if isinstance(v, (int, float)) else "—"


def _signed_pct(v) -> str:
    return f"{v * 100:+.1f}%" if isinstance(v, (int, float)) else "—"


def _strategy_name(sid) -> str:
    return STRATEGIES[sid].name if sid in STRATEGIES else (str(sid) if sid is not None else "—")


def _disclaimer() -> None:
    st.markdown(
        f"""
        <div style='background:#1a2744;border:2px solid {_GOLD};border-radius:8px;
                    padding:10px 16px;margin-bottom:14px;text-align:right'>
        🧭 <strong style='color:{_GOLD}'>Shadow Mode — המנוע ממליץ ומתעד, לא פותח עסקאות</strong>
        <span style='color:#c8d6e8;font-size:0.88rem'> — כל 6 התיקים נפתחים בכל מקרה.
        כלי מחקר בלבד, לא ייעוץ השקעות.</span></div>
        """,
        unsafe_allow_html=True,
    )


# ════════════════════════════════════════════════════════════════════════
#  חלק א — ההחלטה הנוכחית
# ════════════════════════════════════════════════════════════════════════

def _render_current_decision() -> None:
    st.markdown("## 🧭 ההחלטה הנוכחית")
    try:
        bundle = _current_decision()
    except Exception:  # noqa: BLE001
        st.error("❌ שגיאה בחישוב ההחלטה — בדוק חיבור DB / נתוני פקיעות.")
        return

    dec   = bundle["decision"]
    regime = dec["regime"]["regime"]
    icon, regime_he, color = _REGIME_VIS.get(regime, _REGIME_VIS["unknown"])

    st.caption(f"פקיעה קרובה: {bundle['expiry']} ({bundle['expiry_type']}) — {bundle['source']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("פקיעה", f"{bundle['expiry']}", help=f"סוג {bundle['expiry_type']}")
    c2.markdown(
        f"<div style='text-align:center'><div style='color:{_AXIS};font-size:0.85rem'>משטר תנודתיות</div>"
        f"<div style='font-size:1.4rem;font-weight:700;color:{color}'>{icon} {regime_he}</div></div>",
        unsafe_allow_html=True,
    )
    rs = dec["risk_score"]
    c3.metric("ציון סיכון", f"{rs:.1f}/10" if isinstance(rs, (int, float)) else "—")
    c4.metric("מקרים דומים", dec["n_similar"])

    if dec.get("note"):
        st.warning(dec["note"])

    # ── טבלת הדירוג ─────────────────────────────────────────────────
    rows = []
    for r in dec["ranking"]:
        rows.append({
            "#":            r["rank"],
            "אסטרטגיה":     r["strategy_name"],
            "WR מותנה":     _pct(r["cond_wr"]),
            "WR גלובלי":    _pct(r["global_wr"]),
            "Δ":            _signed_pct(r["delta_wr"]),
            "עוצמה":        f"{r['cond_intensity']:.2f}" if isinstance(r["cond_intensity"], (int, float)) else "—",
        })
    df = pd.DataFrame(rows)

    def _highlight_top(row):
        if row["#"] == 1:
            return [f"background-color: rgba(201,168,76,0.18); font-weight: 700"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.style.apply(_highlight_top, axis=1),
        hide_index=True, use_container_width=True,
    )

    # ── נימוקים ─────────────────────────────────────────────────────
    with st.expander("📝 נימוקי הדירוג", expanded=False):
        for r in dec["ranking"]:
            st.markdown(f"**#{r['rank']} · {r['strategy_name']}** — {r['reason']}")


# ════════════════════════════════════════════════════════════════════════
#  חלק ב — הסבר המדדים
# ════════════════════════════════════════════════════════════════════════

def _render_explanation() -> None:
    with st.expander("ℹ️ מה כל מדד אומר (שקיפות)", expanded=False):
        st.markdown(
            """
- **Win Rate (WR מותנה / גלובלי):** באיזו תדירות, היסטורית, תנועת הפקיעה נפלה
  בטווח שבו האסטרטגיה "מנצחת". **מותנה** = על פקיעות *דומות* (אותו סוג/חודש/תנועה
  קודמת); **גלובלי** = על כל ההיסטוריה. ⚠️ זו **הסתברות-טווח**, לא רווח כספי ממשי.
- **Δ:** ההפרש בין ה-WR המותנה לגלובלי — כמה ההקשר הנוכחי משפר/מרע את הסיכוי.
- **עוצמה (cond_intensity):** כמה *עמוק* בתוך אזור הרווח נפלה התנועה בממוצע על
  הפקיעות הדומות. מבדיל בין אסטרטגיות עם אותו Win Rate (Iron Condor מול Butterfly).
  **1.0** = אופטימלי, **0** = בדיוק בקצה אזור הרווח. משמש כשובר-שוויון בדירוג.
- **משטר תנודתיות (regime):** התנודתיות האחרונה מול הממוצע ההיסטורי של אותו סוג —
  🟢 רגוע / 🔵 רגיל / 🔴 תנודתי.
- **Shadow Mode:** בשלב זה המנוע **ממליץ ומתעד בלבד** — כל 6 התיקים נפתחים בכל מקרה.
            """
        )


# ════════════════════════════════════════════════════════════════════════
#  חלק ג — תיעוד החלטות (כתיבה ל-decision_log)
# ════════════════════════════════════════════════════════════════════════

_RECORD_STATUS_HE = {
    "recorded":       "🟢 נרשם",
    "skipped_exists": "🟡 כבר תועד היום",
    "error":          "🔴 שגיאה",
}


def _show_record_results(results: list[dict]) -> None:
    """מציג טבלת תוצאות של תיעוד אחרון (נרשם/דולג/שגיאה לכל פקיעה)."""
    if not results:
        st.warning("לא נמצאו פקיעות קרובות בשרשרת לתיעוד.")
        return
    n_rec  = sum(1 for r in results if r["status"] == "recorded")
    n_skip = sum(1 for r in results if r["status"] == "skipped_exists")
    n_err  = sum(1 for r in results if r["status"] == "error")

    if n_rec == 0 and n_err == 0 and n_skip > 0:
        st.info("✅ כל הפקיעות הקרובות כבר תועדו היום.")

    rows = [{
        "פקיעה":           r["expiry_date"],
        "סוג":             r["expiry_type"] or "—",
        "אסטרטגיה מובילה": _strategy_name(r["top_strategy_id"]),
        "משטר":            r["regime"] or "—",
        "סטטוס":           _RECORD_STATUS_HE.get(r["status"], r["status"]),
    } for r in results]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption(f"נרשמו {n_rec} · דולגו {n_skip} · שגיאות {n_err}.")


def _render_recorder() -> None:
    st.markdown("## 📝 תיעוד החלטות")
    st.caption(
        "מריץ את מנוע ההחלטה על כל הפקיעות הקרובות ושומר ל-decision_log "
        "(append-only). מתעד פעם אחת ביום לכל פקיעה — לחיצה חוזרת לא תיצור כפילות."
    )
    if st.button("📝 תעד החלטות לפקיעות הקרובות", type="primary", key="record_decisions"):
        with st.spinner("מריץ את המנוע ומתעד..."):
            try:
                results = record_decisions_for_upcoming(engine=_engine(), trigger="manual")
            except Exception:  # noqa: BLE001
                st.error("❌ שגיאה בתיעוד ההחלטות — בדוק חיבור DB ונתוני פקיעות.")
                return
        st.session_state["record_results"] = results
        _logs.clear()          # נכתבו רשומות — לרענן את תצוגת ההיסטוריה
        st.rerun()

    results = st.session_state.get("record_results")
    if results is not None:
        _show_record_results(results)


# ════════════════════════════════════════════════════════════════════════
#  חלק ד — היסטוריית ההחלטות (decision_log)
# ════════════════════════════════════════════════════════════════════════

def _render_history() -> None:
    st.markdown("## 🗂️ היסטוריית ההחלטות")
    try:
        logs = _logs(50)
    except Exception:  # noqa: BLE001
        st.warning("⚠️ שגיאה בטעינת היסטוריית ההחלטות.")
        return

    if not logs:
        st.info("עדיין לא נשמרו החלטות ב-decision_log.")
        return

    rows = []
    for d in logs:
        rs = d.get("risk_score")
        rows.append({
            "מתי":             str(d.get("decided_at"))[:19],
            "פקיעה":           str(d.get("expiry_date")),
            "סוג":             d.get("expiry_type"),
            "משטר":            d.get("regime"),
            "אסטרטגיה מובילה": _strategy_name(d.get("top_strategy_id")),
            "מקרים דומים":     d.get("n_similar"),
            "סיכון":           f"{float(rs):.1f}" if rs is not None else "—",
            "טריגר":           d.get("trigger"),
            "גרסה":            d.get("engine_version"),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption(f"מוצגות {len(logs)} ההחלטות האחרונות (append-only; decided_at מבדיל בין הרצות).")


# ════════════════════════════════════════════════════════════════════════
#  Entry point
# ════════════════════════════════════════════════════════════════════════

st.title("🧭 מנוע ההחלטה")
_disclaimer()

if not has_paper_db():
    st.warning("⚠️ DATABASE_URL לא מוגדר — מנוע ההחלטה אינו זמין בסביבה זו.")
    st.stop()

_render_current_decision()
_render_explanation()
st.divider()
_render_recorder()
st.divider()
_render_history()

st.divider()
st.caption("⚠️ כלי מחקר בלבד — לא ייעוץ השקעות. Shadow mode: המנוע מציג ומתעד, לא מבצע.")
