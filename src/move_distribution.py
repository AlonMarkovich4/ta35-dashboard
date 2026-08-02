"""
move_distribution.py — התפלגות תנועות היסטורית + הסתברות-החזקה ותוחלת רווח למרווחי Condor.

שלב 2 של מנגנון המרווח האופטימלי. מעל עקומת המרווח (margin_calculator, שלב 1),
מלביש את ההתפלגות האמפירית של תנועות הפקיעה ההיסטוריות כדי לגזור, לכל מרווח:
  • hold_probability — ההסתברות שהמדד יישאר בתוך טווח ה-short strikes (שומר פרמיה מלאה).
  • expected_value   — תוחלת ה-P&L האמיתית, עם avg_loss אמיתי דרך margin_pnl (לא max_loss).

עקרונות:
  • אפס שכפול לוגיקה — ה-P&L מגיע אך ורק דרך margin_calculator.margin_pnl (שעוטף את
    payoff_iron_condor), ומנגנון ההתניה עוטף את context_analyzer.find_similar_expiries.
  • טהור: מקבל DataFrame/dict, מחזיר נתונים. אפס גישה ל-DB, אפס UI.
  • אמפירי: כל ההסתברויות והתוחלות נמדדות ישירות על מדגם התנועות ההיסטורי — ללא הנחת
    התפלגות פרמטרית.
  • null-safe: מדגם ריק / שורה שדולגה → None, לא קריסה (עקבי עם margin_calculator).

API ציבורי:
  build_move_distribution(df, expiry_type=None, before_date=None) -> dict
  horizon_move_distribution(sessions, horizon_sessions, before_date=None) -> dict
  hold_probability(dist, curve_row) -> float | None
  hold_probability_curve(dist, curve) -> list[dict]
  expected_value_curve(dist, curve) -> list[dict]
  conditioned_move_distribution(df, expiry_type, target_month, recent_move_pct,
                                move_tolerance=0.5, before_date=None) -> dict

⚠️ **אופק הזמן — קראו לפני שמסתמכים על hold_probability.**

`build_move_distribution` בונה את ההתפלגות מ-`expiry_history.move_pct`, שהוא
תנועת **מושב אחד** (סגירת המושב הקודם → מחיר הסילוק). אבל פוזיציה נפתחת מספר
ימים לפני הפקיעה — תיק ההמלצות מחזיק בממוצע ~5 ימי לוח.

הפער נמדד על 1,993 מושבי מסחר (TA-35, 10 שנים), במרווח 2.25%:
    מושב אחד  97.5%   ·   3 מושבים  84.1%   ·   5 מושבים  72.2%   ·   7 מושבים  64.8%

כלומר המספר שהמנוע מדווח היום נכון רק למי שנכנס במושב האחרון לפני הפקיעה.
`horizon_move_distribution` מחשב את ההתפלגות הנכונה לאופק אמיתי.

**√t אינו תחליף:** סטיית התקן בפועל גדולה ב-16%–29% מתחזית √t (מגמתיות),
כלומר קנה-מידה פרמטרי היה מקטין את הסיכון בכ-30%.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from context_analyzer import find_similar_expiries
from margin_calculator import margin_pnl

logger = logging.getLogger(__name__)


def _abs_move_series(frame: pd.DataFrame) -> pd.Series:
    """סדרת התנועה המוחלטת — abs_move_pct אם קיים, אחרת |move_pct| (עקבי עם context_analyzer)."""
    if "abs_move_pct" in frame.columns:
        return frame["abs_move_pct"]
    return frame["move_pct"].abs()


def _empty_distribution(expiry_type: str | None) -> dict:
    """מדגם ריק — null-safe: אפס תנועות, כל הסטטיסטיקות None (לא קורסים)."""
    return {
        "moves":       np.array([], dtype=float),
        "n":           0,
        "mean":        None,
        "std":         None,
        "abs_mean":    None,
        "expiry_type": expiry_type,
    }


def build_move_distribution(
    df: pd.DataFrame,
    expiry_type: str | None = None,
    before_date=None,
) -> dict:
    """
    בונה את ההתפלגות האמפירית של תנועות הפקיעה ההיסטוריות (move_pct חתום, באחוזים).

    מסנן ל-move_pct תקין (לא NaN), אופציונלית לפי סוג פקיעה (W/M) ולפי חלון-זמן
    (zero-lookahead — רק פקיעות שלפני before_date), ומחזיר את מדגם התנועות + סטטיסטיקות.

    Parameters
    ----------
    df          : DataFrame של expiry_history עם עמודת move_pct (חתום, %),
                  ואופציונלית abs_move_pct, expiry_type, expiry_date.
    expiry_type : "W"/"M" לסינון סוג; None (או ערך אחר) = ללא סינון סוג — כדי לא
                  לערבב שבועי/חודשי שטווחי התנועה שלהם שונים מטבעם.
    before_date : אם מסופק — נשמרות רק פקיעות עם expiry_date < before_date
                  (zero-lookahead, חיוני ל-backtest). None = כל ההיסטוריה.

    Returns
    -------
    dict:
      moves       : np.ndarray — מדגם ה-move_pct החתום (%), ממוין עולה.
      n           : int        — גודל המדגם.
      mean        : float|None — ממוצע התנועה החתומה (הטיה כיוונית).
      std         : float|None — סטיית תקן (אוכלוסייה, ddof=0).
      abs_mean    : float|None — ממוצע התנועה המוחלטת (עוצמה טיפוסית).
      expiry_type : str|None   — הסוג שסונן (לשקיפות).
    מדגם ריק (df ריק / ללא move_pct / הסינון לא הותיר שורות) → n=0, moves=[], השאר None.
    """
    if df is None or len(df) == 0 or "move_pct" not in df.columns:
        return _empty_distribution(expiry_type)

    frame = df
    if expiry_type in ("W", "M") and "expiry_type" in frame.columns:
        frame = frame[frame["expiry_type"] == expiry_type]

    if before_date is not None and "expiry_date" in frame.columns:
        frame = frame[frame["expiry_date"] < pd.Timestamp(before_date)]

    frame = frame[frame["move_pct"].notna()]
    if frame.empty:
        return _empty_distribution(expiry_type)

    moves = np.sort(frame["move_pct"].to_numpy(dtype=float))
    return {
        "moves":       moves,
        "n":           int(moves.size),
        "mean":        round(float(moves.mean()), 4),
        "std":         round(float(moves.std(ddof=0)), 4),
        "abs_mean":    round(float(_abs_move_series(frame).mean()), 4),
        "expiry_type": expiry_type,
    }


def horizon_move_distribution(
    sessions,
    horizon_sessions: int,
    before_date=None,
) -> dict:
    """
    התפלגות התנועות לאופק של k **מושבי מסחר** — ההתפלגות שרלוונטית לפוזיציה
    שנפתחת k מושבים לפני הפקיעה.

    לכל מושב i ≥ k:
        entry  = close[i − k]     — המדד ברגע הכניסה
        settle = open[i]          — מחיר הסילוק (אומת 6/6 מול הסילוק הרשמי)
        move   = (settle − entry) / entry · 100

    זו בדיוק החשיפה של Iron Condor שמוחזק עד פקיעה: ה-strikes נקבעים לפי המדד
    בכניסה, והתוצאה נקבעת לפי הסילוק. המסלול בין לבין אינו משנה.

    Parameters
    ----------
    sessions : רצף מושבי מסחר **ממוין עולה**, כל אחד
               {"date": date, "open": float, "close": float}.
    horizon_sessions : k ≥ 1. k=1 מחזיר את תנועת המושב-הבודד (מה שהמנוע מחשב היום).
    before_date : אם מסופק — רק מושבים עם date < before_date (zero-lookahead).

    Returns
    -------
    dict באותו מבנה כמו build_move_distribution, ולכן משתלב ישירות עם
    hold_probability_at_margin ו-hold_probability. מדגם ריק → n=0.
    """
    if horizon_sessions is None or int(horizon_sessions) < 1:
        raise ValueError(f"horizon_sessions חייב להיות ≥ 1 (התקבל {horizon_sessions!r})")
    k = int(horizon_sessions)

    rows = list(sessions or [])
    if before_date is not None:
        cutoff = pd.Timestamp(before_date)
        rows = [s for s in rows if pd.Timestamp(s.get("date")) < cutoff]

    if len(rows) <= k:
        return _empty_distribution(None)

    moves: list[float] = []
    for i in range(k, len(rows)):
        entry = rows[i - k].get("close")
        settle = rows[i].get("open")
        if entry is None or settle is None:
            continue
        entry = float(entry)
        if entry <= 0:
            continue
        moves.append((float(settle) - entry) / entry * 100.0)

    if not moves:
        return _empty_distribution(None)

    arr = np.sort(np.asarray(moves, dtype=float))
    return {
        "moves":            arr,
        "n":                int(arr.size),
        "mean":             round(float(arr.mean()), 4),
        "std":              round(float(arr.std(ddof=0)), 4),
        "abs_mean":         round(float(np.abs(arr).mean()), 4),
        "expiry_type":      None,
        "horizon_sessions": k,
    }


def daily_volatility(
    sessions,
    window: int = 10,
    before_date=None,
) -> dict:
    """
    תנודתיות יומית — סטיית התקן של N המושבים האחרונים, **ומיקומה בהתפלגות
    ההיסטורית**. האות עצמו חסר משמעות בלי המיקום: 0.9% הוא שקט או סערה תלוי
    בתקופה.

    **למה זה קיים:** `context_analyzer.get_recent_move` מזין את המנוע בתנועת
    **הפקיעה האחרונה**. נמדד על 1,967 נקודות (10 שנים, אופק 5 מושבים, סף כאוס
    2.5%) שהאות הזה חלש:

        recent_move (התנועה האחרונה) : AUC 0.600 · הפרדה +16.0 נק'
        סטיית תקן 10 מושבים          : AUC 0.657 · הפרדה +29.2 נק'

    בחמישון התחתון P(כאוס)=8.6% ובעליון 37.8%, מול בסיס 24%. שלושת גרסאות
    האות היומי (std5/std10/mean|r|5) נתנו כמעט אותו דבר — התוצאה יציבה ואינה
    תלויה בבחירת הפרמטר.

    ⚠️ **AUC 0.657 הוא הטיה, לא מתג.** גם בחמישון העליון המרווח מנצח ב-62%
    מהמקרים. האות מזיז הסתברות; הוא אינו קובע תוצאה.

    Parameters
    ----------
    sessions    : רצף מושבים ממוין עולה, {"date","open","close"} — כמו
                  ב-horizon_move_distribution.
    window      : כמה מושבים אחרונים בחלון (ברירת מחדל 10).
    before_date : zero-lookahead — רק מושבים עם date < before_date.

    Returns
    -------
    dict: std, abs_mean, window, n_history, percentile (0–100), quintile (1–5).
    מדגם קטן מדי → כל השדות None (לא קורס).
    """
    if window is None or int(window) < 2:
        raise ValueError(f"window חייב להיות ≥ 2 (התקבל {window!r})")
    window = int(window)

    rows = list(sessions or [])
    if before_date is not None:
        cutoff = pd.Timestamp(before_date)
        rows = [s for s in rows if pd.Timestamp(s.get("date")) < cutoff]

    closes = [float(s["close"]) for s in rows
              if s.get("close") is not None and float(s["close"]) > 0]
    empty = {"std": None, "abs_mean": None, "window": window,
             "n_history": 0, "percentile": None, "quintile": None}
    if len(closes) < window + 2:
        return empty

    arr = np.asarray(closes, dtype=float)
    rets = np.diff(arr) / arr[:-1] * 100.0
    if rets.size < window:
        return empty

    cur_std = float(np.std(rets[-window:], ddof=0))
    cur_absmean = float(np.mean(np.abs(rets[-window:])))

    # ההתפלגות ההיסטורית של אותו מדד — כדי לדעת אם זה שקט או סערה
    hist = np.array([np.std(rets[i - window:i], ddof=0)
                     for i in range(window, rets.size + 1)], dtype=float)
    pct = float((hist < cur_std).mean() * 100.0) if hist.size else None
    quint = int(min(5, max(1, pct // 20 + 1))) if pct is not None else None

    return {
        "std":        round(cur_std, 4),
        "abs_mean":   round(cur_absmean, 4),
        "window":     window,
        "n_history":  int(hist.size),
        "percentile": None if pct is None else round(pct, 1),
        "quintile":   quint,
    }


def hold_probability(dist: dict, curve_row: dict) -> Optional[float]:
    """
    ההסתברות האמפירית שהמדד "יחזיק" בתוך טווח ה-short strikes של המרווח — כלומר
    שהפקיעה נופלת בין ה-short put ל-short call, והמרווח שומר את *מלוא* הפרמיה.

    "הטווח" מוגדר ע"י ה-strikes שנבחרו בפועל (ולא ה-margin_pct הנומינלי) — כדי לשקף
    את ההצמדה לגריד:
        lower = (short_put_strike / base − 1) · 100
        upper = (short_call_strike / base − 1) · 100
    ההסתברות = שיעור התנועות במדגם שנופלות ב-[lower, upper] (כולל הקצוות).

    מחזיר None אם המדגם ריק (n=0) או אם השורה דולגה (אין לה strikes).
    """
    moves = dist.get("moves")
    if moves is None or len(moves) == 0 or curve_row.get("skipped"):
        return None

    base = float(curve_row["base_index"])
    lower = (float(curve_row["short_put_strike"]) / base - 1.0) * 100.0
    upper = (float(curve_row["short_call_strike"]) / base - 1.0) * 100.0

    m = np.asarray(moves, dtype=float)
    held = int(np.count_nonzero((m >= lower) & (m <= upper)))
    return round(held / m.size, 4)


def hold_probability_at_margin(dist: dict, margin_pct: float) -> Optional[float]:
    """
    ההסתברות האמפירית שהמדד יישאר בתוך טווח ±margin_pct **נומינלי** — שיעור התנועות
    במדגם עם |move_pct| ≤ margin_pct.

    בניגוד ל-hold_probability (שנשען על ה-strikes שנבחרו בפועל מהשרשרת), פונקציה זו
    נשענת על ה-margin_pct הנומינלי בלבד. לכן היא הבסיס לשלב 3 (בחירת מרווח + סימולציה
    היסטורית walk-forward), שבו אין שרשרת אופציות לפקיעות עבר — רק התנועות עצמן.

    מחזיר None אם המדגם ריק (n=0).
    """
    moves = dist.get("moves")
    if moves is None or len(moves) == 0:
        return None
    m = np.asarray(moves, dtype=float)
    held = int(np.count_nonzero(np.abs(m) <= float(margin_pct)))
    return round(held / m.size, 4)


def hold_probability_curve(dist: dict, curve: list[dict]) -> list[dict]:
    """
    מצרף hold_prob לכל שורה בעקומת המרווח (None לשורות שדולגו / מדגם ריק).

    מחזיר עותק חדש של העקומה — אינו משנה את שורות הקלט במקום. שקול לקריאה
    summarize_curve(curve, hold_prob_fn=lambda r: hold_probability(dist, r)), אך מחזיר
    את השורות ישירות לנוחות שלב הבחירה (שלב 3).
    """
    out: list[dict] = []
    for row in curve:
        new_row = dict(row)
        new_row["hold_prob"] = None if row.get("skipped") else hold_probability(dist, row)
        out.append(new_row)
    return out


def expected_value_curve(dist: dict, curve: list[dict]) -> list[dict]:
    """
    מחשב את תוחלת ה-P&L האמיתית לכל מרווח, על מדגם התנועות ההיסטורי.

    לכל שורה תקינה מחושב P&L אמיתי לכל תנועה במדגם דרך margin_calculator.margin_pnl
    (שעוטף את payoff_iron_condor — אותה נוסחה בדיוק של מסחר-הנייר). מכאן:
      • ev       — ממוצע ה-P&L על *כל* התנועות (₪). זו התוחלת האמפירית.
      • avg_win / avg_loss — ממוצע ה-P&L על התנועות המרוויחות (>0) / המפסידות (<0) בנפרד.
        avg_loss הוא ההפסד *האמיתי* הממוצע (דרך margin_pnl) — לא max_loss השטוח: רוב
        התנועות שמחוץ לטווח נוחתות *בין* ה-short לכנף (הפסד חלקי), לא מעבר לכנף.
      • p_win / p_loss — שיעור התנועות המרוויחות / המפסידות (מתוך כלל המדגם).

    זהות: ev == p_win·avg_win + p_loss·avg_loss (תנועות ב-0 בדיוק, אם יש, תורמות 0).

    מצרף ev, avg_win, avg_loss, p_win, p_loss לכל שורה תקינה (כולן None לשורות שדולגו /
    מדגם ריק). מחזיר עותק חדש של העקומה — אינו משנה את הקלט במקום.
    """
    moves = dist.get("moves")
    have_sample = moves is not None and len(moves) > 0

    out: list[dict] = []
    for row in curve:
        new_row = dict(row)
        if row.get("skipped") or not have_sample:
            new_row.update(ev=None, avg_win=None, avg_loss=None, p_win=None, p_loss=None)
            out.append(new_row)
            continue

        pnls = np.array([margin_pnl(row, float(m)) for m in moves], dtype=float)
        n = pnls.size
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        new_row.update(
            ev=round(float(pnls.mean()), 2),
            avg_win=round(float(wins.mean()), 2) if wins.size else None,
            avg_loss=round(float(losses.mean()), 2) if losses.size else None,
            p_win=round(int(wins.size) / n, 4),
            p_loss=round(int(losses.size) / n, 4),
        )
        out.append(new_row)
    return out


def conditioned_move_distribution(
    df: pd.DataFrame,
    expiry_type: str | None,
    target_month: int,
    recent_move_pct: Optional[float],
    move_tolerance: float = 0.5,
    before_date=None,
) -> dict:
    """
    מתנה את התפלגות התנועות על "פקיעות דומות" — עוטף את מנגנון הדמיון הקיים
    (context_analyzer.find_similar_expiries): סוג + עונתיות (חודש) + תנועה קודמת דומה.

    במקום כלל ההיסטוריה, ההתפלגות נבנית רק על הפקיעות שהמערכת כבר מזהה כדומות לפקיעה
    הקרובה — כך hold_probability / expected_value משקפים את המשטר הנוכחי ולא ממוצע-על.

    Parameters זהים ל-find_similar_expiries, בתוספת before_date (zero-lookahead) שמסנן
    את df *לפני* חישוב הדמיון — עקבי עם build_expiry_decision.

    Returns
    -------
    dict כמו build_move_distribution, בתוספת:
      conditioned = True,
      n_similar   = מספר הפקיעות הדומות שנמצאו.
    אם אין פקיעות דומות → moves ריק, n=0 (הקורא מחליט על fallback לכלל-ההיסטוריה).
    """
    gt = expiry_type if expiry_type in ("W", "M") else None

    work_df = df
    if before_date is not None and df is not None and "expiry_date" in df.columns:
        work_df = df[df["expiry_date"] < pd.Timestamp(before_date)]

    similar = find_similar_expiries(work_df, gt, target_month, recent_move_pct, move_tolerance)

    # similar כבר מסונן לפי סוג ו-move_pct תקין → לא מסננים סוג פעם שנייה.
    dist = build_move_distribution(similar, expiry_type=None)
    dist["expiry_type"] = expiry_type
    dist["conditioned"] = True
    dist["n_similar"] = int(len(similar))
    return dist
