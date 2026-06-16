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
