"""
פרסור שרשרת אופציות Put/Call מקובץ TASE (putvscall.csv).

מבנה הקובץ:
  שורה 0: כותרת מטא
  שורה 1: תאריך הנתונים ("נכון ל- DD/MM/YYYY")
  שורה 2: כותרות עמודות (Call בצד שמאל, Strike באמצע, Put בצד ימין)
  שורה 3+: שורות מפריד (תאריך פקיעה) + שורות נתונים לסירוגין

מחירי האופציות מוצגים ב-₪ ליחידה; מכפיל חוזה: 50 ₪/נקודה.
הפרסר מזהה אוטומטית את מיקומי העמודות מתוך שורת הכותרת,
כך שהוא עמיד בפני שינויי פורמט של TASE.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Union

import pandas as pd

MULTIPLIER = 50  # ₪ לנקודה

# מיפוי ברירת-מחדל לפי אינדקס (0-based) — משמש כ-fallback אם זיהוי הכותרת נכשל
_C: dict[str, int] = {
    "call_oi":     0,
    "call_high":   2,
    "call_low":    3,
    "call_volume": 7,
    "call_price":  8,   # שער אחרון Call [₪]
    "call_delta":  10,
    "call_name":   11,
    "strike":      13,  # מחיר מימוש
    "put_name":    15,
    "put_delta":   16,
    "put_price":   18,  # שער אחרון Put [₪]
    "put_volume":  19,
    "put_low":     23,
    "put_high":    24,
    "put_oi":      26,
}

_EXPIRY_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s*-\s*(שבועי|חודשי)")
_DATE_RE   = re.compile(r"\d{2}/\d{2}/\d{4}")

# סף מינימלי לסטרייק תקין (מסנן שורות מיוחדות/אגרגטיביות שמגיעות מ-TASE)
_MIN_VALID_STRIKE = 100.0


def parse_putvscall(source: Union[str, Path, bytes, object]) -> dict:
    """
    מפרסר קובץ putvscall.csv מ-TASE.

    source — נתיב לקובץ, bytes, או file-like object (מ-st.file_uploader).

    מחזיר:
        {
          'as_of_date': str,                # תאריך הנתונים
          'expiries': [                     # רשימת פקיעות
            {
              'date': str,                  # DD/MM/YYYY
              'expiry_type': str,           # 'שבועי' / 'חודשי'
              'chain': pd.DataFrame         # שרשרת האופציות (ראה עמודות בהמשך)
            }
          ]
        }

    עמודות ה-DataFrame chain:
        strike, call_price, put_price, call_delta, put_delta,
        call_oi, put_oi, call_volume, put_volume,
        call_high, call_low, put_high, put_low,
        call_pts, put_pts          ← מחיר בנקודות (price / MULTIPLIER)
    """
    lines = _read_lines(source)

    as_of_date = ""
    if len(lines) > 1:
        m = _DATE_RE.search(lines[1])
        if m:
            as_of_date = m.group(0)

    # זיהוי אוטומטי של מיקומי עמודות מתוך שורת הכותרת
    col_map = _detect_columns(lines)

    # זיהוי שורות מפריד (תאריך פקיעה) ופילוח לסקציות
    sections: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = _EXPIRY_RE.search(line)
        if m:
            sections.append((i, m.group(1), m.group(2).strip()))

    expiries = []
    for sec_i, (start, date_str, exp_type) in enumerate(sections):
        end = sections[sec_i + 1][0] if sec_i + 1 < len(sections) else len(lines)
        chain = _parse_section(lines[start + 1: end], col_map)
        if chain is not None and not chain.empty:
            expiries.append({"date": date_str, "expiry_type": exp_type, "chain": chain})

    return {"as_of_date": as_of_date, "expiries": expiries}


def find_atm(chain: pd.DataFrame) -> dict:
    """
    מאתר את הסטרייק הקרוב ביותר ל-ATM לפי put-call parity.

    משתמש ב-|call_price - put_price| מינימלי (רק בשורות עם שני הצדדים).
    מחזיר רמת המדד המשוערת: S ≈ strike + (call_price - put_price) / MULTIPLIER
    """
    active = chain[(chain["call_price"] > 0) & (chain["put_price"] > 0)].copy()
    if active.empty:
        # נפילה לדלתא אם אין מחיר משני הצדדים
        active = chain[chain["call_price"] > 0].copy()
        if active.empty:
            return {}
        # call_delta מגיע בסקלה דצימלית (-1, 1) — ATM call delta ≈ 0.5
        active["parity_dist"] = (active["call_delta"] - 0.5).abs()
    else:
        # כיוון put-call parity: |C - P| → 0 ב-ATM
        active["parity_dist"] = (active["call_price"] - active["put_price"]).abs()

    atm = active.loc[active["parity_dist"].idxmin()]

    # שיערוך רמת מדד מ-parity
    c_pts = float(atm["call_price"]) / MULTIPLIER
    p_pts = float(atm["put_price"])  / MULTIPLIER
    index_est = float(atm["strike"]) + c_pts - p_pts

    return {
        "strike":        float(atm["strike"]),
        "call_price":    float(atm["call_price"]),
        "put_price":     float(atm["put_price"]),
        "call_pts":      round(c_pts, 2),
        "put_pts":       round(p_pts, 2),
        "call_delta":    float(atm.get("call_delta", 50)),
        "index_estimate": round(index_est, 1),
    }


def get_strategy_strikes(atm_strike: float, chain: pd.DataFrame) -> dict[int, dict]:
    """
    מחשב סטרייקים מומלצים ומבנה P&L תיאורטי לכל אחת מ-6 האסטרטגיות.

    atm_strike — הסטרייק הקרוב ביותר ל-ATM
    chain      — שרשרת האופציות המפורסרת

    מחזיר dict[strategy_id → dict עם: strikes_desc, structure, max_loss_desc, max_profit_desc, cost_pts]
    """
    def nearest(target: float, side: str) -> tuple[float, float]:
        """מחזיר (actual_strike, price_in_pts) הקרוב ביותר לסטרייק יעד."""
        col = f"{side}_price"
        sub = chain[chain[col] > 0].copy()
        if sub.empty:
            return target, 0.0
        idx = (sub["strike"] - target).abs().idxmin()
        row = sub.loc[idx]
        return float(row["strike"]), float(row[col]) / MULTIPLIER

    atm_c_strike, atm_c_pts = nearest(atm_strike, "call")
    atm_p_strike, atm_p_pts = nearest(atm_strike, "put")

    # ─── כלים לחישוב ─────────────────────────────────────────────────
    def pct_strike(pct: float) -> float:
        return round(atm_strike * (1 + pct / 100) / 10) * 10

    out: dict[int, dict] = {}

    # 1 — Bull Call Spread (width=30pts)
    width = 30
    sell_c_strike, sell_c_pts = nearest(atm_strike + width, "call")
    cost = atm_c_pts - sell_c_pts
    out[1] = {
        "strikes_desc": f"קנה Call {atm_c_strike:.0f} | מכור Call {sell_c_strike:.0f}",
        "structure": f"Buy {atm_c_strike:.0f}C / Sell {sell_c_strike:.0f}C",
        "cost_pts":   round(cost, 1),
        "max_loss_desc":   f"פרמיה נטו: {cost:.1f} נק' = {cost*MULTIPLIER:,.0f} ₪",
        "max_profit_desc": f"רוחב: {width} נק' − פרמיה = {width - cost:.1f} נק' = {(width-cost)*MULTIPLIER:,.0f} ₪",
    }

    # 2 — Short Iron Condor (width=2%)
    sc = pct_strike(+2.0);  sp = pct_strike(-2.0)
    wc = pct_strike(+3.0);  wp = pct_strike(-3.0)
    _, sc_pts = nearest(sc, "call");  _, sp_pts = nearest(sp, "put")
    _, wc_pts = nearest(wc, "call");  _, wp_pts = nearest(wp, "put")
    premium = (sc_pts + sp_pts) - (wc_pts + wp_pts)
    out[2] = {
        "strikes_desc": f"מכור Put {sp:.0f} / מכור Call {sc:.0f} | קנה Put {wp:.0f} / קנה Call {wc:.0f}",
        "structure":    f"Sell {sp:.0f}P/{sc:.0f}C  |  Buy {wp:.0f}P/{wc:.0f}C",
        "cost_pts":     round(-premium, 1),
        "max_loss_desc":   f"רוחב כנף − פרמיה = {(sp-wp) - premium:.1f} נק'",
        "max_profit_desc": f"פרמיה נטו: {premium:.1f} נק' = {premium*MULTIPLIER:,.0f} ₪",
    }

    # 3 — Long Call Butterfly (wing=1%)
    wing_c = pct_strike(+1.0);  wing_p_c = pct_strike(-1.0)
    _, lo_c = nearest(wing_p_c, "call")
    _, hi_c = nearest(wing_c,   "call")
    cost_bf = lo_c + hi_c - 2 * atm_c_pts
    out[3] = {
        "strikes_desc": f"קנה Call {wing_p_c:.0f} | מכור 2× Call {atm_c_strike:.0f} | קנה Call {wing_c:.0f}",
        "structure":    f"Buy {wing_p_c:.0f}C / Sell 2×{atm_c_strike:.0f}C / Buy {wing_c:.0f}C",
        "cost_pts":     round(cost_bf, 1),
        "max_loss_desc":   f"פרמיה נטו: {cost_bf:.1f} נק' = {cost_bf*MULTIPLIER:,.0f} ₪",
        "max_profit_desc": f"כנף − פרמיה: {(wing_c-atm_c_strike) - cost_bf:.1f} נק'",
    }

    # 4 — Long Put Butterfly (wing=1%)
    _, lo_p = nearest(wing_c,   "put")
    _, hi_p = nearest(wing_p_c, "put")
    cost_pb = lo_p + hi_p - 2 * atm_p_pts
    out[4] = {
        "strikes_desc": f"קנה Put {wing_c:.0f} | מכור 2× Put {atm_p_strike:.0f} | קנה Put {wing_p_c:.0f}",
        "structure":    f"Buy {wing_c:.0f}P / Sell 2×{atm_p_strike:.0f}P / Buy {wing_p_c:.0f}P",
        "cost_pts":     round(cost_pb, 1),
        "max_loss_desc":   f"פרמיה נטו: {cost_pb:.1f} נק' = {cost_pb*MULTIPLIER:,.0f} ₪",
        "max_profit_desc": f"כנף − פרמיה: {(atm_p_strike-wing_p_c) - cost_pb:.1f} נק'",
    }

    # 5 — Long Straddle
    straddle_cost = atm_c_pts + atm_p_pts
    out[5] = {
        "strikes_desc": f"קנה Call {atm_c_strike:.0f} + Put {atm_p_strike:.0f}",
        "structure":    f"Buy {atm_c_strike:.0f}C + {atm_p_strike:.0f}P",
        "cost_pts":     round(straddle_cost, 1),
        "max_loss_desc":   f"פרמיה: {straddle_cost:.1f} נק' = {straddle_cost*MULTIPLIER:,.0f} ₪",
        "max_profit_desc": "בלתי מוגבל (לכל כיוון)",
    }

    # 6 — Long Strangle (1.5% OTM each side)
    otm_c = pct_strike(+1.5);  otm_p = pct_strike(-1.5)
    _, otm_c_pts = nearest(otm_c, "call")
    _, otm_p_pts = nearest(otm_p, "put")
    strangle_cost = otm_c_pts + otm_p_pts
    out[6] = {
        "strikes_desc": f"קנה Call {otm_c:.0f} + Put {otm_p:.0f} (OTM ×1.5%)",
        "structure":    f"Buy {otm_c:.0f}C + {otm_p:.0f}P",
        "cost_pts":     round(strangle_cost, 1),
        "max_loss_desc":   f"פרמיה: {strangle_cost:.1f} נק' = {strangle_cost*MULTIPLIER:,.0f} ₪",
        "max_profit_desc": "בלתי מוגבל (לכל כיוון)",
    }

    return out


# ── Internal helpers ─────────────────────────────────────────────────

def _detect_columns(lines: list[str]) -> dict[str, int]:
    """
    מזהה אוטומטית את מיקומי העמודות מתוך שורת הכותרת של הקובץ.

    סורק את השורות הראשונות לאיתור השורה המכילה "מחיר מימוש".
    ממפה Call/Put לפי מיקומן יחסית לעמודת הסטרייק (שמאל = Call, ימין = Put).
    מחזיר את _C הסטטי כ-fallback אם הזיהוי נכשל.
    """
    header_parts: list[str] | None = None
    for line in lines[:6]:
        if "מחיר מימוש" in line:
            header_parts = [p.strip() for p in line.split(",")]
            break

    if header_parts is None:
        return _C.copy()

    strike_col = next(
        (i for i, p in enumerate(header_parts) if "מחיר מימוש" in p), None
    )
    if strike_col is None:
        return _C.copy()

    call_side = header_parts[:strike_col]
    put_side  = header_parts[strike_col + 1:]

    def _find(parts: list[str], *keywords: str, offset: int = 0) -> int | None:
        """מחזיר אינדקס גלובלי של הפריט הראשון המכיל את כל המילות המפתח."""
        for i, p in enumerate(parts):
            if all(kw in p for kw in keywords):
                return i + offset
        return None

    off = strike_col + 1

    def _c(detected: int | None, fallback: int) -> int:
        return detected if detected is not None else fallback

    return {
        "strike":      strike_col,
        # Call side (before strike)
        "call_price":  _c(_find(call_side, "שער אחרון"),       _C["call_price"]),
        "call_delta":  _c(_find(call_side, "דלת"),              _C["call_delta"]),
        "call_volume": _c(_find(call_side, "מחזור ביחידות"),   _C["call_volume"]),
        "call_oi":     _c(_find(call_side, "פוז"),              _C["call_oi"]),
        "call_high":   _c(_find(call_side, "שער גבוה"),        _C["call_high"]),
        "call_low":    _c(_find(call_side, "שער נמוך"),        _C["call_low"]),
        "call_name":   _c(_find(call_side, "שם נייר"),         _C["call_name"]),
        # Put side (after strike)
        "put_price":   _c(_find(put_side, "שער אחרון",  offset=off), _C["put_price"]),
        "put_delta":   _c(_find(put_side, "דלת",         offset=off), _C["put_delta"]),
        "put_volume":  _c(_find(put_side, "מחזור ביחידות", offset=off), _C["put_volume"]),
        "put_oi":      _c(_find(put_side, "פוז",          offset=off), _C["put_oi"]),
        "put_high":    _c(_find(put_side, "שער גבוה",    offset=off), _C["put_high"]),
        "put_low":     _c(_find(put_side, "שער נמוך",    offset=off), _C["put_low"]),
        "put_name":    _c(_find(put_side, "שם נייר",     offset=off), _C["put_name"]),
    }


def _read_lines(source) -> list[str]:
    """קורא את תוכן המקור ומחזיר שורות; מנסה מספר encodings."""
    _ENCODINGS = ("utf-8-sig", "utf-16", "windows-1255", "utf-8")

    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
        for enc in _ENCODINGS:
            try:
                return raw.decode(enc).splitlines()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return raw.decode("utf-8", errors="replace").splitlines()

    elif hasattr(source, "read"):
        raw = source.read()
        if isinstance(raw, (bytes, bytearray)):
            for enc in _ENCODINGS:
                try:
                    return raw.decode(enc).splitlines()
                except (UnicodeDecodeError, UnicodeError):
                    continue
            return raw.decode("utf-8", errors="replace").splitlines()
        return raw.splitlines()

    else:
        for enc in _ENCODINGS:
            try:
                with open(source, encoding=enc) as f:
                    return f.read().splitlines()
            except (UnicodeDecodeError, UnicodeError):
                continue
        with open(source, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()


def _safe_float(parts: list[str], idx: int, default: float = 0.0) -> float:
    try:
        v = parts[idx].strip()
        return float(v) if v else default
    except (ValueError, IndexError):
        return default


def _parse_section(data_lines: list[str], col_map: dict[str, int]) -> pd.DataFrame | None:
    """מפרסר שורות נתונים של פקיעה אחת לתוך DataFrame."""
    strike_col = col_map["strike"]
    min_cols   = strike_col + 1  # חייב להיות לפחות עמודת סטרייק

    rows = []
    for line in data_lines:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) <= min_cols:
            continue

        try:
            strike = float(parts[strike_col].strip())
        except (ValueError, IndexError):
            continue
        # סינון שורות מיוחדות: סטרייק קטן מהסף (שורות אגרגט/ייחוס של TASE)
        if strike < _MIN_VALID_STRIKE:
            continue

        sf = lambda idx: _safe_float(parts, idx)
        rows.append({
            "strike":      strike,
            "call_price":  sf(col_map["call_price"]),
            "put_price":   sf(col_map["put_price"]),
            "call_delta":  sf(col_map["call_delta"]),
            "put_delta":   sf(col_map["put_delta"]),
            "call_oi":     sf(col_map["call_oi"]),
            "put_oi":      sf(col_map["put_oi"]),
            "call_volume": sf(col_map["call_volume"]),
            "put_volume":  sf(col_map["put_volume"]),
            "call_high":   sf(col_map["call_high"]),
            "call_low":    sf(col_map["call_low"]),
            "put_high":    sf(col_map["put_high"]),
            "put_low":     sf(col_map["put_low"]),
        })

    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)
    df["call_pts"] = (df["call_price"] / MULTIPLIER).round(2)
    df["put_pts"]  = (df["put_price"]  / MULTIPLIER).round(2)
    return df
