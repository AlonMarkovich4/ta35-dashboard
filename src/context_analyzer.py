"""
ניתוח הקשר היסטורי — TA-35 Expiry Intelligence.

מאתר פקיעות היסטוריות דומות לפקיעה הקרובה לפי שלושה קריטריונים:
  1. סוג פקיעה (W/M)
  2. עונתיות — אותו חודש בשנה
  3. תנועת הפקיעה הקודמת — דומה לתנועה האחרונה שנצפתה (±move_tolerance%)

ומחשב Win Rate מותנה לכל אסטרטגיה על אותם מקרים בלבד.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from backtester import best_per_strategy, run_backtest
from strategies import STRATEGIES


def get_recent_move(df: pd.DataFrame, before_date: pd.Timestamp) -> float | None:
    """
    מחזיר את ה-move_pct של הפקיעה האחרונה שהושלמה לפני before_date.

    משתמש בכל הפקיעות (W+M) עם move_pct תקין.
    מחזיר None אם אין פקיעות קודמות בנתונים.
    """
    valid = df[df["move_pct"].notna()].sort_values("expiry_date")
    before = valid[valid["expiry_date"] < before_date]
    if before.empty:
        return None
    return float(before.iloc[-1]["move_pct"])


# ─── תנודתיות אחרונה (building block למנוע ההחלטה) ──────────────────────

# ספי סיווג משטר תנודתיות — יחס בין תנודתיות החלון לממוצע ההיסטורי של אותו סוג.
# נבחר באנד מכפלי סימטרי של ±25% סביב הבסיס ארוך-הטווח:
#   ratio < 0.75  → "calm"      (תנודתיות נמוכה מהרגיל)
#   ratio > 1.25  → "volatile"  (תנודתיות גבוהה מהרגיל)
#   אחרת          → "normal"
# יחס מכפלי (ולא הפרש מוחלט) כי הוא חסר-יחידות ועובד גם ל-W וגם ל-M (לבסיסים
# שונים מטבעם); ±25% רחב מספיק כדי לא להגיב לרעש, וצר מספיק כדי לסמן סטייה אמיתית.
_REGIME_CALM_RATIO     = 0.75
_REGIME_VOLATILE_RATIO = 1.25


def _abs_move_series(frame: pd.DataFrame) -> pd.Series:
    """מחזיר את סדרת התנועה המוחלטת — abs_move_pct אם קיים, אחרת |move_pct|."""
    if "abs_move_pct" in frame.columns:
        return frame["abs_move_pct"]
    return frame["move_pct"].abs()


def _classify_regime(mean_abs_move: float | None, global_mean: float | None) -> str:
    """מסווג משטר תנודתיות לפי יחס תנודתיות-החלון לממוצע ההיסטורי הכללי."""
    if mean_abs_move is None or global_mean is None or global_mean <= 0:
        return "unknown"
    ratio = mean_abs_move / global_mean
    if ratio < _REGIME_CALM_RATIO:
        return "calm"
    if ratio > _REGIME_VOLATILE_RATIO:
        return "volatile"
    return "normal"


def recent_volatility(
    df: pd.DataFrame,
    expiry_type: str | None,
    before_date,
    window: int = 12,
) -> dict:
    """
    מטריקת תנודתיות אחרונה — פונקציה טהורה על expiry_history (ללא גישה ל-DB).

    1. מסננת לאותו expiry_type (W/M); None או ערך אחר = ללא סינון סוג (כדי לא
       לערבב שבועי/חודשי, שמטבעם בעלי טווחי תנועה שונים).
    2. שומרת רק פקיעות תקינות (move_pct לא NaN) לפני before_date, ממוינות.
    3. לוקחת את החלון — window הפקיעות האחרונות (ברירת מחדל 12).
    4. מסווגת משטר תנודתיות מול הממוצע ההיסטורי של אותו סוג, *מבוסס רק על פקיעות
       שלפני before_date* (zero-lookahead — לא רואה את העתיד, לחיוניות ב-backtest).

    מחזיר dict:
      mean_abs_move : float | None — ממוצע abs_move_pct בחלון
      std_move      : float | None — סטיית תקן (אוכלוסייה, ddof=0) של move_pct בחלון
      n             : int          — מספר הפקיעות בפועל בחלון (≤ window)
      regime        : str          — "calm" / "normal" / "volatile" / "unknown"

    null-safe: אם אין נתונים (n=0) → mean/std=None, n=0, regime="unknown".
    """
    empty = {"mean_abs_move": None, "std_move": None, "n": 0, "regime": "unknown"}
    if df is None or df.empty or "move_pct" not in df.columns:
        return empty

    before = pd.Timestamp(before_date)

    typed = df
    if expiry_type in ("W", "M"):
        typed = df[df["expiry_type"] == expiry_type]

    valid = typed[typed["move_pct"].notna()].sort_values("expiry_date")
    # zero-lookahead: רק פקיעות שהיו ידועות לפני before_date — גם לחלון וגם לבסיס.
    prior = valid[valid["expiry_date"] < before]

    window_df = prior.tail(window)
    n = len(window_df)
    if n == 0:
        return empty

    mean_abs_move = round(float(_abs_move_series(window_df).mean()), 4)
    std_move      = round(float(window_df["move_pct"].std(ddof=0)), 4)

    # בסיס ה-regime: כל הפקיעות מאותו סוג *שלפני* before_date (ללא הצצה לעתיד)
    global_mean = float(_abs_move_series(prior).mean())
    regime = _classify_regime(mean_abs_move, global_mean)

    return {
        "mean_abs_move": mean_abs_move,
        "std_move":      std_move,
        "n":             n,
        "regime":        regime,
    }


def find_similar_expiries(
    df: pd.DataFrame,
    expiry_type: str,
    target_month: int,
    recent_move_pct: Optional[float] = None,
    move_tolerance: float = 0.5,
) -> pd.DataFrame:
    """
    מאתר פקיעות היסטוריות דומות לפקיעה הקרובה.

    קריטריונים מצטברים:
      1. expiry_type — "W"/"M". ערך אחר = ללא סינון סוג.
      2. target_month — אותו חודש (1–12) לעונתיות.
      3. recent_move_pct — |preceding_move − recent_move_pct| ≤ move_tolerance.
                          הפקיעה ה"קודמת" נמדדת על כלל הפקיעות הממוינות לפי תאריך,
                          ללא תלות בסוג. None = ללא סינון תנועה קודמת.

    מחזיר DataFrame עם move_pct תקין בלבד, ממוין לפי תאריך יורד.
    """
    # Step 1: preceding_move מחושב על כלל הפקיעות הממוינות
    df_valid = df[df["move_pct"].notna()].sort_values("expiry_date").copy()
    df_valid["_preceding_move"] = df_valid["move_pct"].shift(1)

    # Step 2: סינון סוג + חודש
    mask = pd.Series(True, index=df_valid.index)
    if expiry_type in ("W", "M"):
        mask &= df_valid["expiry_type"] == expiry_type
    mask &= df_valid["expiry_date"].dt.month == target_month

    filtered = df_valid[mask].copy()

    # Step 3: סינון תנועה קודמת
    if recent_move_pct is not None and not filtered.empty:
        # סוגריים סביב תנאי ההפרש חיוניים: & קושר חזק מ-<=, ובלעדיהם הביטוי
        # מתפרש כ-(notna() & abs_diff) <= move_tolerance — לוגיקה שבורה.
        prec_mask = (
            filtered["_preceding_move"].notna()
            & ((filtered["_preceding_move"] - recent_move_pct).abs() <= move_tolerance)
        )
        filtered = filtered[prec_mask]

    return (
        filtered
        .drop(columns=["_preceding_move"])
        .sort_values("expiry_date", ascending=False)
        .reset_index(drop=True)
    )


def conditional_win_rates(
    similar_df: pd.DataFrame,
    strategy_grid: Optional[dict] = None,
) -> pd.DataFrame:
    """
    מחשב Win Rate מותנה לכל אסטרטגיה על קבוצת הפקיעות הדומות.

    מחזיר DataFrame ממוין לפי win_rate יורד (שורה אחת לאסטרטגיה — הפרמטר המיטבי).
    מחזיר DataFrame ריק אם similar_df ריק.
    """
    if similar_df.empty or similar_df["move_pct"].notna().sum() == 0:
        return pd.DataFrame()
    results = run_backtest(similar_df, strategy_grid=strategy_grid)
    if results.empty:
        return pd.DataFrame()
    return best_per_strategy(results)


def build_recommendation(
    cond_best: pd.DataFrame,
    global_best: pd.DataFrame,
    risk_score: float,
    n_similar: int,
) -> dict:
    """
    בונה המלצה סופית מבוססת Win Rate מותנה + ציון סיכון.

    מחזיר:
      {
        'strategy_id':   int,
        'strategy_name': str,
        'cond_wr':       float,   # Win Rate על מקרים דומים
        'global_wr':     float,   # Win Rate כלל-היסטורי
        'delta_wr':      float,   # הפרש
        'n_similar':     int,
        'risk_score':    float,
        'note':          str,     # הערה אם הסיכון סותר את ההמלצה
      }
    """
    if cond_best.empty:
        return {}

    # אסטרטגיה עם Win Rate מותנה גבוה ביותר (ממיין למקרה שהקלט לא ממוין)
    _sorted = cond_best.sort_values("win_rate", ascending=False)
    top = _sorted.iloc[0]
    sid  = int(top["strategy_id"])
    name = top["strategy_name"]
    cwr  = float(top["win_rate"])

    # Win Rate גלובלי לאותה אסטרטגיה
    gwr_row = global_best[global_best["strategy_id"] == sid] if not global_best.empty else pd.DataFrame()
    gwr = float(gwr_row.iloc[0]["win_rate"]) if not gwr_row.empty else cwr

    # בדיקת סתירה: סיכון גבוה אך ממליצים על ניטרלי
    _NEUTRAL = {2, 3, 4}   # Condor, Butterfly
    _VOLATILE = {5, 6}     # Straddle, Strangle
    note = ""
    if risk_score >= 6.5 and sid in _NEUTRAL:
        # ציון סיכון גבוה — שקול אסטרטגיה תנודתית
        vol_best = cond_best[cond_best["strategy_id"].isin(_VOLATILE)]
        if not vol_best.empty:
            alt = vol_best.iloc[0]
            note = (
                f"⚠️ ציון סיכון גבוה ({risk_score:.1f}/10) — "
                f"שקול {alt['strategy_name']} (Win Rate {alt['win_rate']:.1%}) "
                f"שמנצח בתנועות חזקות."
            )

    return {
        "strategy_id":   sid,
        "strategy_name": name,
        "cond_wr":       round(cwr, 4),
        "global_wr":     round(gwr, 4),
        "delta_wr":      round(cwr - gwr, 4),
        "n_similar":     n_similar,
        "risk_score":    risk_score,
        "note":          note,
    }


# ─── מנוע ההחלטה (shadow mode) — חיבור אבני הבניין ─────────────────────

_NEUTRAL_IDS   = frozenset({2, 3, 4})   # Iron Condor, Call/Put Butterfly
_VOLATILE_IDS  = frozenset({5, 6})      # Straddle, Strangle
_RISK_HIGH     = 6.5                    # סף ציון סיכון "גבוה" (עקבי עם compute_risk_score)
_MIN_SIMILAR_FOR_CONFIDENCE = 5         # מתחת לזה — נימה מסתייגת על אמינות הדירוג המותנה


def _decision_reason(rec: dict, n_similar: int, regime: str) -> str:
    """בונה נימוק עברי קצר לרשומת דירוג בודדת (כולל rank, cond_wr, regime)."""
    rank, cwr, gwr, dwr = rec["rank"], rec["cond_wr"], rec["global_wr"], rec["delta_wr"]
    if cwr is not None:
        s = f"מדורגת #{rank} — Win Rate מותנה {cwr:.0%} על {n_similar} מקרים דומים"
        if gwr is not None:
            s += f" (גלובלי {gwr:.0%}, Δ{dwr:+.0%})"
    elif gwr is not None:
        s = f"מדורגת #{rank} — אין מקרים דומים; Win Rate גלובלי {gwr:.0%}"
    else:
        s = f"מדורגת #{rank} — אין נתונים היסטוריים מספיקים"
    return s + f"; משטר נוכחי: {regime}"


def _decision_note(
    records: list[dict],
    n_similar: int,
    recent_move_pct: Optional[float],
    risk_score: Optional[float],
    regime: str,
) -> str:
    """בונה הסתייגות/אזהרה משולבת להחלטה (ריק אם אין)."""
    parts: list[str] = []
    if recent_move_pct is None:
        parts.append("ללא סינון תנועה קודמת (recent_move_pct חסר)")
    if n_similar == 0:
        parts.append("אין מקרים דומים — הדירוג מבוסס על Win Rate גלובלי בלבד")
    elif n_similar < _MIN_SIMILAR_FOR_CONFIDENCE:
        parts.append(f"מעט מקרים דומים (n={n_similar}) — אמינות הדירוג המותנה מוגבלת")

    # אזהרת סתירה: המדורגת ראשונה ניטרלית בעוד הסיכון/התנודתיות גבוהים
    top = records[0]
    high_risk = risk_score is not None and risk_score >= _RISK_HIGH
    if top["strategy_id"] in _NEUTRAL_IDS and (high_risk or regime == "volatile"):
        vol_alt = next((r for r in records if r["strategy_id"] in _VOLATILE_IDS), None)
        if vol_alt is not None:
            trig = []
            if high_risk:
                trig.append(f"ציון סיכון {risk_score:.1f}")
            if regime == "volatile":
                trig.append("משטר תנודתי")
            parts.append(
                f"⚠️ {' + '.join(trig)} אך המדורגת ראשונה ניטרלית — "
                f"שקול {vol_alt['strategy_name']} (מנצח בתנועות חזקות)"
            )
    return " | ".join(parts)


def build_expiry_decision(
    df: pd.DataFrame,
    expiry_type: str | None,
    target_month: int,
    expiry_date,
    recent_move_pct: Optional[float],
    risk_score: Optional[float] = None,
    move_tolerance: float = 0.5,
    vol_window: int = 12,
) -> dict:
    """
    מנוע ההחלטה (shadow mode) — מחבר את אבני הבניין לכדי החלטה מנומקת אחת.

    טהורה: מחשבת ומחזירה בלבד — אינה פותחת עסקאות, אינה כותבת ל-DB, ואינה
    מסננת אסטרטגיות (מחזירה את כל 6 מדורגות לפי Win Rate מותנה יורד). ה-regime
    מתועד אך אינו משנה את הדירוג בשלב זה (יטויב בעתיד).

    משתמשת אך ורק בפונקציות הקיימות: recent_volatility, find_similar_expiries,
    conditional_win_rates, best_per_strategy + run_backtest.

    מחזיר dict:
      expiry_date, expiry_type,
      regime: {regime, mean_abs_move, std_move, n},
      n_similar, risk_score,
      ranking: [{rank, strategy_id, strategy_name, cond_wr, global_wr, delta_wr, reason} ×6],
      top_strategy_id, note
    """
    # סוג מנורמל — W/M בלבד מסננים; כל ערך אחר (None/לא ידוע) = ללא סינון, עקבי
    # בין recent_volatility / find_similar_expiries / run_backtest.
    gt = expiry_type if expiry_type in ("W", "M") else None

    # 1. משטר תנודתיות (zero-lookahead — לפני expiry_date)
    vol = recent_volatility(df, gt, expiry_date, vol_window)
    regime = vol["regime"]

    # 2. דירוג Win Rate מותנה על מקרים דומים
    similar = find_similar_expiries(df, gt, target_month, recent_move_pct, move_tolerance)
    n_similar = len(similar)
    cond_best = conditional_win_rates(similar)
    cond_wr_by_id = (
        {int(r["strategy_id"]): float(r["win_rate"]) for _, r in cond_best.iterrows()}
        if not cond_best.empty else {}
    )

    # 3. Win Rate גלובלי (כל ההיסטוריה מאותו סוג) ל-delta
    global_best = best_per_strategy(run_backtest(df, expiry_type=gt))
    global_wr_by_id = (
        {int(r["strategy_id"]): float(r["win_rate"]) for _, r in global_best.iterrows()}
        if not global_best.empty else {}
    )

    # 4. רשומת דירוג לכל 6 האסטרטגיות
    records: list[dict] = []
    for sid in sorted(STRATEGIES):
        cwr = cond_wr_by_id.get(sid)
        gwr = global_wr_by_id.get(sid)
        cwr = round(cwr, 4) if cwr is not None else None
        gwr = round(gwr, 4) if gwr is not None else None
        dwr = round(cwr - gwr, 4) if (cwr is not None and gwr is not None) else None
        records.append({
            "rank":          None,             # נקבע אחרי המיון
            "strategy_id":   sid,
            "strategy_name": STRATEGIES[sid].name,
            "cond_wr":       cwr,
            "global_wr":     gwr,
            "delta_wr":      dwr,
            "reason":        "",               # נבנה אחרי המיון
        })

    # מיון יורד לפי cond_wr (None→אחרון), שובר שוויון לפי global_wr; מיון יציב
    records.sort(
        key=lambda r: (
            r["cond_wr"]   if r["cond_wr"]   is not None else -1.0,
            r["global_wr"] if r["global_wr"] is not None else -1.0,
        ),
        reverse=True,
    )
    for i, r in enumerate(records, start=1):
        r["rank"]   = i
        r["reason"] = _decision_reason(r, n_similar, regime)

    note = _decision_note(records, n_similar, recent_move_pct, risk_score, regime)

    return {
        "expiry_date":     expiry_date,
        "expiry_type":     expiry_type,
        "regime": {
            "regime":        vol["regime"],
            "mean_abs_move": vol["mean_abs_move"],
            "std_move":      vol["std_move"],
            "n":             vol["n"],
        },
        "n_similar":       n_similar,
        "risk_score":      risk_score,
        "ranking":         records,
        "top_strategy_id": records[0]["strategy_id"],
        "note":            note,
    }
