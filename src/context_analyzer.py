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
