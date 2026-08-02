"""
margin_validator.py — שכבת ולידציה קדימה למנגנון המרווח: "המנוע מול המציאות" (קריאה בלבד).

שלב 4, חלק ג — התאום של decision_validator, למנגנון המרווח. לכל פקיעה שגם *תועדה*
המלצת מרווח (margin_recommendations) וגם *נסגרה* (יש settlement ב-condor_settled_detail),
המודול משווה: מה המנוע המליץ (רוחב המרווח), מול מה שהתנועה בפועל עשתה — האם המרווח
החזיק (|move| ≤ margin), וכמה מרווח "בוזבז" מול האופטימום בדיעבד.

מודול טהור-לוגיקה, אפס Streamlit (כמו decision_validator): גם UI וגם סקריפט/Action
עתידי קוראים לאותה build_margin_validation_rows().

קריאה בלבד מה-DB (SELECT בלבד) — אפס כתיבה. שלוש קריאות:
  • _fetch_latest_recommendations — ההמלצה האחרונה (MAX recommended_at) לכל פקיעה,
    עם n_recommendations = כמה נרשמו לאותה פקיעה, ו-recommendation_json המלא (grid +
    selected_curve_row) לשחזור האופטימום וה-P&L.
  • _fetch_settlements — מחיר הנעילה (actual_index_close) לכל פקיעה שנסגרה.
  • _fetch_history_moves — move_pct הקנוני מ-expiry_history.

### 🔴 מקור התנועה — תוקן 02/08/2026. קרא לפני שינוי.

**מה שהיה כאן קודם, ולמה זה היה שגוי.** המודול העדיף `expiry_history.move_pct`
כדי ש-`held` יימדד באותה הגדרה כמו הבקטסט. הכוונה לגיטימית — אבל התוצאה תויגה
"hold בפועל", וזה לא נכון: `move_pct` הוא תנועת **מושב אחד**
(`base_price[i] == close_price[i-1]`), בעוד ההמלצה חשופה **5–7 מושבים**.
הבקטסט עצמו סובל מאותה שגיאה (`margin_backtest.py:130`).

התוצאה: הדשבורד הציג `hold בפועל = 100%` (10/10) בזמן שההמלצות באמת החזיקו
בכ-40%. דוגמה — פקיעת 30/07: הישן דיווח תנועה 0.63% מול מרווח 3.0% → HELD;
בפועל הפוזיציה נעה ‎-3.6%, נסגרה מתחת ל-short put, והפסידה.

**ההגדרה הנכונה, לפי סדר עדיפות:**
  1. `_held_at_strikes` — הסילוק נפל בין ה-short strikes בפועל. הטובה ביותר,
     כי היא מתחשבת בהצמדה לגריד.
  2. `|(expiry_price − base_index)/base_index| ≤ margin_pct` — נומינלי, אך על
     האופק הנכון ומהעוגן שממנו נבנו ה-strikes.
  3. ההגדרה הישנה — רק כשאין סילוק. נשמרת תמיד כ-`held_1session` להשוואה לבקטסט.

⚠️ **מחיר הסילוק מגיע מ-`expiry_history.expiry_price`, לא מ-`condor_settled_detail`.**
`actual_index_close` הוא בפועל סגירת המושב הקודם (באג ב-`tase-pipeline`, אומת
27/27) — ראה HANDOFF סעיף 2.

`held_source` בכל שורה מתעד באיזו מהשלוש נעשה שימוש.

טיפוסי expiry_date: margin_recommendations.expiry_date הוא DATE, אך
condor_settled_detail.expiry_date הוא **TEXT** — לכן _fetch_settlements עושה CAST ::date
(כמו כל גישה לטבלה הזו). החיבור עצמו נעשה ב-Python דרך _as_date (מנרמל date/datetime/
Timestamp/מחרוזת-ISO למפתח date אחיד), עמיד לכל טיפוס שהדרייבר יחזיר.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy import text

from data_loader import load_from_db
from margin_calculator import _default_margins, margin_pnl
from paper_db import _make_engine

logger = logging.getLogger(__name__)


# ─── helpers ────────────────────────────────────────────────────────────

def _as_date(v):
    """מנרמל ערך expiry_date (date/datetime/Timestamp/מחרוזת-ISO) ל-datetime.date אחיד.

    שקול ל-CAST ::date אך בצד Python — עמיד לכל טיפוס שהדרייבר עשוי להחזיר (בפרט
    condor_settled_detail.expiry_date שהוא TEXT). None/לא-פריק → None.
    """
    if v is None:
        return None
    if isinstance(v, datetime):     # datetime הוא תת-מחלקה של date — לבדוק ראשון
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.Timestamp(v).date()
    except Exception:  # noqa: BLE001
        logger.warning("_as_date: לא ניתן לפרסר expiry_date=%r", v)
        return None


def _f(v):
    """ממיר NUMERIC/Decimal/None לצף Python (או None) — הדרייבר מחזיר NUMERIC כ-Decimal."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _loads_json(v):
    """מפרש ערך JSONB חוזר מ-DB ל-dict (dict/string/None)."""
    if v is None:
        return None
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return None
    return v


def _actual_move(exp, close, base, hist_moves: dict):
    """מחזיר (move_pct, source) — מעדיף expiry_history הקנוני, נופל ל-settlement.

    ראה נימוק מלא ב-docstring המודול. None,None אם אין אף מקור בר-חישוב.
    """
    hm = hist_moves.get(exp)
    if hm is not None:
        return float(hm), "expiry_history"
    if base is not None and float(base) != 0.0 and close is not None:
        return (float(close) - float(base)) / float(base) * 100.0, "settlement"
    return None, None


def _optimal_hindsight(abs_move: float, grid):
    """המרווח הצר ביותר בגריד שהיה מחזיק את התנועה (m ≥ |move|); None אם חרגה מכל הגריד.

    משתמש בגריד של ההמלצה עצמה (המרווחים שבאמת הוצעו לאותה פקיעה, מ-recommendation_json);
    נופל לגריד הנומינלי (_default_margins) אם לא נשמר.
    """
    margins = sorted({round(float(g["margin_pct"]), 4)
                      for g in (grid or []) if g.get("margin_pct") is not None})
    if not margins:
        margins = _default_margins()
    holders = [m for m in margins if m >= abs_move]
    return min(holders) if holders else None


def _est_pnl(curve_row, move_pct):
    """P&L משוער של ההמלצה על התנועה בפועל, דרך margin_pnl (שחזור מ-selected_curve_row).

    None אם אין שורת עקומה תקינה (לא נשמרה / דולגה). אותה נוסחת payoff של הבקטסט.
    """
    if not curve_row or curve_row.get("skipped"):
        return None
    try:
        return round(margin_pnl(curve_row, move_pct), 2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("_est_pnl נכשל: %s", exc, exc_info=True)
        return None


# ─── DB reads (read-only) ───────────────────────────────────────────────

def _fetch_latest_recommendations(eng) -> list[dict]:
    """ההמלצה האחרונה (MAX recommended_at) לכל פקיעה, עם n_recommendations ו-JSON מלא.

    DISTINCT ON (expiry_date) בורר את הרשומה עם recommended_at המקסימלי (append-only →
    כמה רשומות לפקיעה מימים שונים; האחרונה = "לפני הפקיעה", כי הרשם רץ רק על עתיד).
    COUNT(*) OVER מונה את *כל* הרשומות לפקיעה לפני הבירור. מחזיר [] בכישלון.
    """
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT DISTINCT ON (expiry_date)
                           expiry_date,
                           recommended_at,
                           margin_pct,
                           premium_ils,
                           below_floor,
                           floor_used,
                           recommendation_json,
                           COUNT(*) OVER (PARTITION BY expiry_date) AS n_recommendations
                    FROM margin_recommendations
                    ORDER BY expiry_date, recommended_at DESC
                """),
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            m = r._mapping
            out.append({
                "expiry_date":         _as_date(m.get("expiry_date")),
                "recommended_at":      m.get("recommended_at"),
                "margin_pct":          _f(m.get("margin_pct")),
                "premium_ils":         _f(m.get("premium_ils")),
                "below_floor":         m.get("below_floor"),
                "floor_used":          _f(m.get("floor_used")),
                "recommendation_json": _loads_json(m.get("recommendation_json")),
                "n_recommendations":   int(m.get("n_recommendations") or 0),
            })
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_latest_recommendations נכשל: %s", exc, exc_info=True)
        return []


def _fetch_settlements(eng) -> dict:
    """מפת פקיעה(date)→actual_index_close מ-condor_settled_detail (קריאה בלבד).

    expiry_date שם **TEXT** → CAST ::date (בשני מקומות: ה-SELECT וה-GROUP BY). MAX על
    actual_index_close לכל פקיעה (שורות הפירוט לפי סטרייק חולקות אותו מחיר נעילה).
    מחזיר {} בכישלון.
    """
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT expiry_date::date        AS expiry_date,
                           MAX(actual_index_close)  AS actual_index_close
                    FROM condor_settled_detail
                    WHERE actual_index_close IS NOT NULL
                    GROUP BY expiry_date::date
                """),
            ).fetchall()
        out: dict = {}
        for r in rows:
            m = r._mapping
            d = _as_date(m.get("expiry_date"))
            c = m.get("actual_index_close")
            if d is not None and c is not None:
                out[d] = float(c)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_settlements נכשל: %s", exc, exc_info=True)
        return {}


def _fetch_history_moves(eng) -> dict:
    """מפת פקיעה(date)→move_pct מ-expiry_history (תנועת **מושב אחד**). {} בכישלון."""
    try:
        df = load_from_db(eng)
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_history_moves נכשל: %s", exc, exc_info=True)
        return {}
    if df is None or len(df) == 0 or "move_pct" not in df.columns:
        return {}
    out: dict = {}
    for _, row in df.iterrows():
        d = _as_date(row.get("expiry_date"))
        mv = row.get("move_pct")
        if d is not None and mv is not None and pd.notna(mv):
            out[d] = float(mv)
    return out


def _fetch_settlement_prices(eng) -> dict:
    """
    מפת פקיעה(date)→expiry_price מ-`expiry_history` — **מחיר הסילוק האמיתי**.

    זהו המקור הנכון לוולידציה, ולא `condor_settled_detail.actual_index_close`:
    האחרון הוא בפועל **סגירת המושב הקודם** (באג ב-`tase-pipeline`, אומת 27/27 מול
    Yahoo — ראה HANDOFF סעיף 2). `expiry_history.expiry_price` אומת 6/6 מול מחיר
    הסילוק הרשמי, עד האגורה.

    {} בכישלון — הקורא נופל למקורות הישנים.
    """
    try:
        df = load_from_db(eng)
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_settlement_prices נכשל: %s", exc, exc_info=True)
        return {}
    if df is None or len(df) == 0 or "expiry_price" not in df.columns:
        return {}
    out: dict = {}
    for _, row in df.iterrows():
        d = _as_date(row.get("expiry_date"))
        px = row.get("expiry_price")
        if d is not None and px is not None and pd.notna(px) and float(px) > 0:
            out[d] = float(px)
    return out


def _held_at_strikes(curve_row, settlement):
    """
    האם הסילוק נפל **בין ה-short strikes בפועל** — הבדיקה האמיתית.

    עדיף על `|move| <= margin_pct` הנומינלי, כי ה-strikes מוצמדים לגריד ולכן
    הטווח בפועל נבדל מהמרווח המבוקש. None אם אין strikes או אין סילוק.
    """
    if not curve_row or settlement is None or curve_row.get("skipped"):
        return None
    sp, sc = curve_row.get("short_put_strike"), curve_row.get("short_call_strike")
    if sp is None or sc is None:
        return None
    return bool(float(sp) <= float(settlement) <= float(sc))


# ─── public API ─────────────────────────────────────────────────────────

def build_margin_validation_rows(engine=None) -> list[dict]:
    """מחבר המלצות מרווח (margin_recommendations) למציאות (settlement) — שורה לפקיעה ולידבילית.

    "ולידבילית" = יש לה גם המלצה וגם settlement (condor_settled_detail). פקיעה עם המלצה
    אך בלי settlement — או להפך — לא נכללת.

    לכל פקיעה כזו מחשב:
      • recommended_margin — רוחב המרווח שהומלץ.
      • actual_move_pct / actual_abs_move_pct + move_source — התנועה בפועל ומקורה
        (expiry_history קנוני / settlement כגיבוי; ראה docstring המודול).
      • held — האם המרווח החזיק (|move| ≤ margin) — אותה הגדרה כמו הבקטסט.
      • margin_optimal_hindsight — המרווח הצר ביותר בגריד שהיה מחזיק בדיעבד.
      • margin_gap — recommended − optimal (חתום): חיובי = מרווח "בוזבז" (רחב מהנדרש,
        פרמיה שהוותרנו); שלילי = המרווח לא הספיק (התנועה שברה). None אם התנועה חרגה מהגריד.
      • premium_ils — הפרמיה שנרשמה. est_pnl — P&L משוער של ההמלצה על התנועה בפועל
        (margin_pnl, שחזור מ-selected_curve_row).
      • below_floor, n_recommendations — לשקיפות.

    מחזיר רשימה ממוינת לפי expiry_date יורד (האחרונה ראשונה). [] אם אין engine
    (DATABASE_URL לא מוגדר) או אין פקיעות ולידביליות.
    """
    eng = _make_engine(engine)
    if eng is None:
        logger.warning("build_margin_validation_rows: אין engine (DATABASE_URL לא מוגדר).")
        return []

    recs        = _fetch_latest_recommendations(eng)
    settlements = _fetch_settlements(eng)
    hist_moves  = _fetch_history_moves(eng)
    settle_px   = _fetch_settlement_prices(eng)   # מחיר הסילוק האמיתי

    rows: list[dict] = []
    for rec in recs:
        exp = rec["expiry_date"]
        if exp is None:
            continue
        close = settlements.get(exp)
        if close is None:
            continue   # לא נסגרה (אין settlement) — לא ולידבילית

        rj   = rec.get("recommendation_json") or {}
        base = rj.get("base_index")

        move, source = _actual_move(exp, close, base, hist_moves)
        if move is None:
            continue

        rmargin = rec.get("margin_pct")
        if rmargin is None:
            continue
        rmargin  = float(rmargin)
        abs_move = abs(move)
        # ההגדרה הישנה — תנועת מושב אחד. נשמרת **רק** לשם השוואה לבקטסט.
        held_1session = abs_move <= rmargin

        # ── התנועה האמיתית: מהעוגן של ההמלצה ועד הסילוק ──────────────────
        # base_index הוא הבסיס שממנו נבנו ה-strikes; expiry_price הוא הסילוק
        # האמיתי. זו החשיפה בפועל של ההמלצה — 5–7 מושבים, לא אחד.
        crow      = rj.get("selected_curve_row")
        settle    = settle_px.get(exp)
        real_move = None
        if settle is not None and base is not None and float(base) != 0.0:
            real_move = (float(settle) - float(base)) / float(base) * 100.0

        held_strikes = _held_at_strikes(crow, settle)
        if held_strikes is not None:
            held = held_strikes                      # הבדיקה הטובה ביותר
        elif real_move is not None:
            held = abs(real_move) <= rmargin         # נומינלי, אך על האופק הנכון
        else:
            held = held_1session                     # אין סילוק — נופלים לישן

        # האופטימום והפער נמדדים על התנועה האמיתית כשהיא זמינה.
        opt_move = abs(real_move) if real_move is not None else abs_move
        optimal = _optimal_hindsight(opt_move, rj.get("grid"))
        gap     = round(rmargin - optimal, 4) if optimal is not None else None
        # ה-P&L המשוער — על התנועה האמיתית. עם התנועה הישנה הקונדור כמעט לעולם
        # לא נפרץ, ולכן est_pnl יצא שווה למלוא הקרדיט בכל שורה.
        est_pnl = _est_pnl(crow, real_move if real_move is not None else move)

        # "מדד הפחד" — מה השוק ציפה בזמן ההמלצה (None בהמלצות שנרשמו לפני שלב א').
        # מאפשר את ההשוואה שתכריע בשלב ג': השוק ציפה X%, ההיסטוריה אמרה Y% (=המרווח
        # שנבחר), בפועל זז Z% (=actual_abs_move_pct) — מי ניבא טוב יותר.
        im = rj.get("implied_move") or {}
        implied = _f(im.get("expected_move_pct")) if not im.get("skipped") else None

        rows.append({
            "expiry_date":              exp,
            "recommended_at":           rec.get("recommended_at"),
            "recommended_margin":       round(rmargin, 4),
            "actual_move_pct":          round(move, 4),
            "actual_abs_move_pct":      round(abs_move, 4),
            "move_source":              source,
            "held":                     held,
            # ── שקיפות: שתי ההגדרות זו לצד זו ────────────────────────────
            "held_1session":            held_1session,   # להשוואה לבקטסט בלבד
            "settlement_price":         round(settle, 2) if settle is not None else None,
            "real_move_pct":            round(real_move, 4) if real_move is not None else None,
            "held_source":              ("strikes" if held_strikes is not None
                                         else "real_move" if real_move is not None
                                         else "1session"),
            "margin_optimal_hindsight": optimal,
            "margin_gap":               gap,
            "premium_ils":              _f(rec.get("premium_ils")),
            "est_pnl":                  est_pnl,
            "below_floor":              rec.get("below_floor"),
            "n_recommendations":        rec.get("n_recommendations"),
            # ציפיית השוק (%) והשגיאה שלה מול המציאות. implied_error > 0 = השוק ציפה
            # ליותר תנועה משהייתה (over-priced fear); < 0 = השוק הופתע.
            "implied_move_pct":         round(implied, 4) if implied is not None else None,
            "implied_vs_margin":        _f(im.get("implied_vs_margin")),
            "implied_error":            (round(implied - abs_move, 4)
                                         if implied is not None else None),
        })

    rows.sort(key=lambda r: str(r["expiry_date"]), reverse=True)
    return rows


def summarize_margin_validation(rows: list[dict]) -> dict:
    """מסכם שורות ולידציה למדדי-על.

    מחזיר dict עם:
      • n_validated    — מספר הפקיעות שנוולדו.
      • hold_rate      — אחוז הפקיעות שההמלצה החזיקה **בפועל** (0..1): הסילוק
        האמיתי נפל בין ה-short strikes. זהו המספר האמיתי.
      • n_held         — כמה החזיקו.
      • hold_rate_1session — אותה שאלה תחת **הגדרת הבקטסט** (תנועת מושב אחד).
        נשמר לשם השוואה ל-margin_backtest בלבד. ⚠️ הוא **אינו** "hold בפועל":
        הבקטסט עצמו מודד מושב אחד בעוד הפוזיציה חשופה 5–7. הפער עצום —
        1.00 מול ~0.40 על אותן 10 פקיעות.
      • avg_margin_gap — הפער הממוצע מהאופטימום (recommended − optimal). חיובי = בממוצע
        מרווח רחב מהנדרש (פרמיה שהוותרנו לטובת עקביות). None-ים מדולגים.
      • est_pnl_total  — סך ה-P&L המשוער של ההמלצות (indicative). None-ים מדולגים.
    """
    n = len(rows)
    if n == 0:
        return {
            "n_validated":        0,
            "hold_rate":          0.0,
            "n_held":             0,
            "hold_rate_1session": 0.0,
            "avg_margin_gap":     0.0,
            "est_pnl_total":      0.0,
        }
    n_held  = sum(1 for r in rows if r.get("held"))
    n_1sess = sum(1 for r in rows if r.get("held_1session"))
    gaps    = [r["margin_gap"] for r in rows if r.get("margin_gap") is not None]
    pnls    = [r["est_pnl"] for r in rows if r.get("est_pnl") is not None]
    return {
        "n_validated":        n,
        "hold_rate":          round(n_held / n, 4),
        "n_held":             n_held,
        "hold_rate_1session": round(n_1sess / n, 4),
        "avg_margin_gap":     round(sum(gaps) / len(gaps), 4) if gaps else 0.0,
        "est_pnl_total":      round(sum(pnls), 2) if pnls else 0.0,
    }
