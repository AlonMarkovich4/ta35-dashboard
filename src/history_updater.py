"""
history_updater.py — סוגר את לולאת הלמידה של המנוע.

**הבעיה שזה פותר:** expiry_history (ההתפלגות שהמנוע לומד ממנה) מסתיים ב-2026-05-07,
ופקיעות שנסגרות (condor_settled_detail) לא הוזרמו אליו. התוצאה: select_margin בחר
recent_move ממאי — המנוע "עיוור" לשבועות האחרונים. המודול הזה מזרים כל פקיעה שנסגרה
בחזרה ל-expiry_history, כך שההתפלגות מתעדכנת אוטומטית.

**דפוס מוכר, טהור-לוגיקה:** קריאה בלבד לחישוב + reuse של data_loader.save_to_db
(if_exists='append') לכתיבה — אותו נתיב-כתיבה היסטורי בדיוק, ללא שכפול. append-only,
אידמפוטנטי (פקיעה שכבר קיימת → דילוג), dry_run כברירת מחדל. **אפס מחיקה/דריסה** —
הדאטה קדוש (paper_trades/expiry_history append-only).

### move_pct — עקביות עם ההגדרה ההיסטורית (קריטי)

expiry_history.move_pct מוגדר ב-data_loader כ:  (expiry_price − base_price) / base_price · 100
כאשר base_price = "בסיס" (הבסיס הרשמי) ו-expiry_price = "פקיעה" (מחיר הנעילה). זו ההגדרה
שעליה נבנו כל התפלגויות התנועה וה-backtest (held = |move_pct| ≤ margin). המיפוי מ-settlement:

    base_price   ← condor_settled_detail.base_index_value   (הבסיס הרשמי — "בסיס")
    expiry_price ← condor_settled_detail.actual_index_close  (הנעילה — "פקיעה")
    move_pct     = (actual_index_close − base_index_value) / base_index_value · 100   (חתום!)

**הפער 5.04% מול 2.50% (מהפוסט-מורטם) — מוסבר:** ה-5.04% חושב מ-base_index_value (הבסיס
הרשמי, 3,994.6) — *אותו סוג בסיס* כמו expiry_history.base_price, ולכן זו התנועה העקבית
היסטורית. ה-2.50% הוא נתיב-הגיבוי של margin_validator, שמחשב מ-recommendation_json.base_index
(אומדן ATM מרגע ההמלצה, בסיס שנקבע *בזמן אחר* — מתועד שם כנושא שגיאת-עיגול). לכן המודול הזה
משתמש ב-base_index_value: הוא מייצר move_pct באותה הגדרה בדיוק של הדאטה ההיסטורי. הרציונל
מאושש ב-analyze_implied_history (שם base_index_value ו-move_pct מקובצים כ"בסיס שנקבע בזמן
הרשמי", בניגוד לתנועה יחסית-ל-snapshot).

API ציבורי:
  compute_move_pct(base_price, expiry_price) -> (move_pct, abs_move_pct) | (None, None)
  update_expiry_history_from_settlements(engine, dry_run=True) -> dict
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime

import pandas as pd
from sqlalchemy import inspect as sa_inspect, text

from data_loader import save_to_db
from supabase_loader import _infer_expiry_type

logger = logging.getLogger(__name__)

# העמודות ש-expiry_history דורש (זהה ל-data_loader.save_to_db). נגזרות → ערך; השאר → None.
_SAVE_COLS = [
    "expiry_date", "expiry_time", "expiry_type",
    "base_price", "expiry_price", "open_pct", "close_price", "daily_pct",
    "volume", "transactions", "points", "abs_move_pct", "move_pct",
]

# מועמדי-שם לעמודות ה-settlement (עמידות לשינויי-שם קלים). מיפוי סמנטי קבוע.
_BASE_CANDIDATES  = ("base_index_value", "base_index", "base_value", "base_price")
_CLOSE_CANDIDATES = ("actual_index_close", "index_close", "settlement_index", "close_price")
_TYPE_CANDIDATES  = ("drvtype", "derivative_type", "expiry_type", "type")


# ─── helpers טהורים ─────────────────────────────────────────────────────────

def _as_date(v):
    """date/datetime/Timestamp/מחרוזת-ISO → datetime.date אחיד (זהה ל-margin_validator).

    שקול ל-CAST ::date אך בצד Python — עמיד ל-TEXT של condor_settled_detail, וללא
    תלות-דיאלקט (עובד ב-SQLite לבדיקות וב-Postgres בפרודקשן). None אם לא-פריק.
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.Timestamp(v).date()   # ISO 'YYYY-MM-DD' חד-משמעי
    except Exception:  # noqa: BLE001
        logger.warning("history_updater._as_date: expiry_date לא פריק: %r", v)
        return None


def _f(v):
    """NUMERIC/Decimal/None → float|None (הדרייבר מחזיר NUMERIC כ-Decimal)."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_type(raw) -> str:
    """סוג פקיעה → 'W'/'M' (זהה ל-margin_recorder._norm_expiry_type). '_infer_expiry_type'
    מחזיר עברית ('שבועי'/'חודשי') — כאן מנרמלים לאות בודדת כמו ב-expiry_history."""
    return "M" if "חודשי" in str(raw or "") else "W"


def compute_move_pct(base_price, expiry_price):
    """התנועה החתומה *בדיוק כמו data_loader*: (expiry − base) / base · 100.

    מחזיר (move_pct, abs_move_pct) — **ללא עיגול**, כדי להיות זהה-לביט ל-load_market_csv
    (שמאחסן דיוק-מלא). (None, None) אם אין בסיס תקין (base None/0/שלילי) — בדיוק תנאי
    ה-valid ב-load_market_csv (base_price > 0).
    """
    b, e = _f(base_price), _f(expiry_price)
    if b is None or e is None or b <= 0:
        return None, None
    mv = (e - b) / b * 100.0
    return mv, abs(mv)


# ─── שערי שפיות על הבסיס (אירוע 31/07/2026) ─────────────────────────────────
# הרקע: condor_settled_detail.base_index_value הוא עוגן של **סדרה חודשית** — אותו
# ערך חוזר על עצמו עד 4 פקיעות שבועיות רצופות. expiry_history.base_price, לעומת
# זאת, הוא סגירת **המושב הקודם** (אומת: base_price[i] == close_price[i-1], 27/27).
# הזרמה מהעוגן החודשי בולעת את כל דריפט החודש: ממוצע |תנועה| 1.68% מול 0.49%
# בקורפוס ההיסטורי, ובקצה 5.04% ל"פקיעה שבועית".
#
# הבדיקה הקיימת (base_varies) בודקת שוני *בתוך* פקיעה אחת ולכן לא תפסה את זה —
# העוגן החודשי עקבי לחלוטין בתוך כל פקיעה. החתימה האמיתית היא שיתוף *בין* פקיעות.
_MAX_PLAUSIBLE_ABS_MOVE = 8.0   # אחוז; מעבר לזה — כמעט ודאי בעיית עוגן, לא תנועה


def find_shared_bases(settled: dict) -> dict:
    """
    מזהה ערכי base שמשותפים ליותר מפקיעה אחת — החתימה של עוגן חודשי.

    בסיס תקין נקבע לכל פקיעה בנפרד (סגירת המושב הקודם), ולכן שני תאריכי פקיעה
    שונים כמעט לעולם לא יחלקו את אותו ערך. שיתוף כזה מוכיח שהערך אינו בסיס-מושב.

    Parameters
    ----------
    settled : מפת פקיעה(date) → {"base": float|None, ...} כפי ש-_fetch_settled מחזיר.

    Returns
    -------
    dict: {base_value: [dates ממוינים]} — רק ערכים שמופיעים ביותר מפקיעה אחת.
          מפה ריקה = הבסיסים ייחודיים לכל פקיעה (תקין).
    """
    by_base: dict = {}
    for d, rec in (settled or {}).items():
        b = _f((rec or {}).get("base"))
        if b is None or b <= 0:
            continue
        by_base.setdefault(round(b, 4), []).append(d)
    return {b: sorted(ds) for b, ds in by_base.items() if len(ds) > 1}


def is_plausible_move(move_pct) -> bool:
    """
    האם התנועה סבירה כתנועת מושב-אחד. חוסם ערכים שמסגירים בעיית עוגן.

    None או |move| > _MAX_PLAUSIBLE_ABS_MOVE → False. השיא ההיסטורי בקורפוס
    (768 פקיעות שבועיות) הוא 5.92%, ולכן 8% הוא סף שמרני שלא חוסם תנועות אמיתיות.
    """
    v = _f(move_pct)
    return v is not None and abs(v) <= _MAX_PLAUSIBLE_ABS_MOVE


# ─── קריאות DB (קריאה בלבד, ללא CAST תלוי-דיאלקט) ────────────────────────────

def _table_columns(engine, table: str) -> set[str]:
    """שמות העמודות של טבלה (lowercase) דרך SQLAlchemy Inspector — חוצה-דיאלקט."""
    try:
        return {c["name"].lower() for c in sa_inspect(engine).get_columns(table)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("history_updater: introspection נכשל לטבלה %s: %s", table, exc)
        return set()


def _pick(cols: set[str], candidates) -> str | None:
    return next((c for c in candidates if c in cols), None)


def _fetch_settled(engine) -> tuple[dict, str, str, str | None]:
    """מפת פקיעה(date) → {base, close, type_raw, base_varies} מ-condor_settled_detail.

    קורא raw ומקבץ ב-Python (בלי expiry_date::date — עמיד לדיאלקט). base/close אמורים
    להיות קבועים לכל פקיעה (שורות הפירוט לפי סטרייק חולקות אותם); base_varies מסמן אם
    נצפו ערכי-בסיס שונים לאותה פקיעה (חריגת-דאטה לתשומת-לב).

    מחזיר (map, base_col, close_col, type_col). זורק ValueError אם חסרה עמודת בסיס/נעילה.
    """
    cols = _table_columns(engine, "condor_settled_detail")
    base_col  = _pick(cols, _BASE_CANDIDATES)
    close_col = _pick(cols, _CLOSE_CANDIDATES)
    type_col  = _pick(cols, _TYPE_CANDIDATES)
    if base_col is None or close_col is None:
        raise ValueError(
            f"condor_settled_detail חסרה עמודת בסיס/נעילה. עמודות שנמצאו: {sorted(cols)}"
        )

    sel_type = f", {type_col} AS type_raw" if type_col else ""
    sql = text(f"""
        SELECT expiry_date AS exp, {base_col} AS base, {close_col} AS close{sel_type}
        FROM condor_settled_detail
        WHERE {close_col} IS NOT NULL
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()

    agg: dict = {}
    for r in rows:
        m = r._mapping
        d = _as_date(m.get("exp"))
        if d is None:
            continue
        base, close = _f(m.get("base")), _f(m.get("close"))
        cur = agg.setdefault(d, {"bases": set(), "close": None, "type_raw": None})
        if base is not None:
            cur["bases"].add(round(base, 4))
        if close is not None and cur["close"] is None:
            cur["close"] = close
        if type_col and cur["type_raw"] is None:
            cur["type_raw"] = m.get("type_raw")

    out: dict = {}
    for d, v in agg.items():
        bases = v["bases"]
        out[d] = {
            "base":        max(bases) if bases else None,
            "close":       v["close"],
            "type_raw":    v["type_raw"],
            "base_varies": len(bases) > 1,
        }
    return out, base_col, close_col, type_col


def _existing_expiries(engine) -> set:
    """קבוצת תאריכי-הפקיעה שכבר קיימים ב-expiry_history (מנורמלים ל-date)."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT expiry_date FROM expiry_history")).fetchall()
    return {d for d in (_as_date(r._mapping.get("expiry_date")) for r in rows) if d is not None}


# ─── ה-API הראשי ────────────────────────────────────────────────────────────

def update_expiry_history_from_settlements(engine, dry_run: bool = True) -> dict:
    """מזרים פקיעות שנסגרו (condor_settled_detail) שחסרות ב-expiry_history — append-only.

    לכל פקיעה עם actual_index_close שאינה כבר ב-expiry_history:
      • move_pct = compute_move_pct(base_index_value, actual_index_close)  — ההגדרה ההיסטורית.
      • expiry_type = _infer_expiry_type(...) מנורמל ל-W/M (העקבי עם המנוע החי).
      • שאר עמודות expiry_history (open_pct, volume, ...) = NULL (אינן זמינות מה-settlement).
    פקיעה בלי base תקין → מדולגת (אין move_pct משמעותי) ומדווחת ב-skipped_no_base.

    dry_run=True (ברירת מחדל): מחשב הכל ומחזיר את התוכנית **בלי לכתוב**. dry_run=False:
    כותב דרך data_loader.save_to_db(if_exists='append'). אידמפוטנטי: הרצה חוזרת מדלגת
    על מה שכבר נכנס.

    מחזיר dict: {dry_run, settled_total, already_present, to_insert:[...], skipped_no_base:[...],
                 warnings:[...], inserted}.
    """
    settled, base_col, close_col, type_col = _fetch_settled(engine)
    existing = _existing_expiries(engine)

    to_insert: list[dict] = []
    skipped_no_base: list[dict] = []
    warnings: list[str] = []

    # שער שורש: בסיס שמשותף למספר פקיעות אינו בסיס-מושב אלא עוגן חודשי.
    # חוסמים *לפני* הלולאה — כל הפקיעות שחולקות בסיס נפסלות, ולא נכנסת אף שורה
    # מזוהמת. ראה הערת _MAX_PLAUSIBLE_ABS_MOVE.
    shared = find_shared_bases(settled)
    blocked = {d for dates in shared.values() for d in dates}
    if shared:
        for b, dates in sorted(shared.items()):
            warnings.append(
                f"בסיס {b} משותף ל-{len(dates)} פקיעות ({dates[0]}…{dates[-1]}) — "
                f"עוגן חודשי, לא בסיס-מושב. הפקיעות נחסמו."
            )
        logger.error(
            "history_updater: %d פקיעות נחסמו — base_index_value משותף בין פקיעות "
            "(עוגן חודשי). לא הוזרמה אף שורה עבורן.", len(blocked)
        )

    for d in sorted(settled):
        if d in existing:
            continue                                  # אידמפוטנטי — כבר בהיסטוריה
        rec = settled[d]
        base, close = rec["base"], rec["close"]
        if d in blocked:
            skipped_no_base.append({"expiry_date": str(d),
                                    "reason": "base משותף בין פקיעות (עוגן חודשי)",
                                    "close": close})
            continue
        move_pct, abs_move = compute_move_pct(base, close)
        if move_pct is None:
            skipped_no_base.append({"expiry_date": str(d),
                                    "reason": f"base לא תקין ({base!r})", "close": close})
            continue
        if not is_plausible_move(move_pct):
            skipped_no_base.append({"expiry_date": str(d),
                                    "reason": f"תנועה לא סבירה ({move_pct:.2f}%) — חשד לבעיית עוגן",
                                    "close": close})
            logger.error("history_updater: %s נחסמה — move_pct=%.2f%% חורג מ-%.1f%%.",
                         d, move_pct, _MAX_PLAUSIBLE_ABS_MOVE)
            continue
        if rec["base_varies"]:
            warnings.append(f"{d}: נצפו ערכי base_index_value שונים לאותה פקיעה — נבחר המקסימלי.")
        etype = _norm_type(_infer_expiry_type(rec["type_raw"], d))
        to_insert.append({
            "expiry_date":  d,
            "expiry_type":  etype,
            "base_price":   round(float(base), 4),
            "expiry_price": round(float(close), 4),
            "move_pct":     move_pct,
            "abs_move_pct": abs_move,
        })

    inserted = 0
    if to_insert and not dry_run:
        df = pd.DataFrame([{c: None for c in _SAVE_COLS} for _ in to_insert])
        for i, row in enumerate(to_insert):
            for k, v in row.items():
                df.at[i, k] = v
        df["expiry_date"] = pd.to_datetime(df["expiry_date"])
        inserted = save_to_db(df, engine, if_exists="append")
        logger.info("history_updater: נוספו %d פקיעות ל-expiry_history (loop closed).", inserted)

    return {
        "dry_run":         dry_run,
        "settled_total":   len(settled),
        "already_present": sum(1 for d in settled if d in existing),
        "to_insert":       to_insert,
        "skipped_no_base": skipped_no_base,
        "warnings":        warnings,
        "inserted":        inserted,
        "columns_used":    {"base": base_col, "close": close_col, "type": type_col},
    }


# ─── CLI (backfill / dry-run) ────────────────────────────────────────────────

def _print_report(res: dict) -> None:
    """דוח קריא של תוצאת ההרצה (dry או commit)."""
    mode = "DRY-RUN (לא נכתב כלום)" if res["dry_run"] else f"COMMIT — נכתבו {res['inserted']} שורות"
    print("=" * 78)
    print(f"history_updater — סגירת לולאת הלמידה   [{mode}]")
    print("=" * 78)
    cu = res["columns_used"]
    print(f"עמודות settlement: base={cu['base']} · close={cu['close']} · type={cu['type'] or '—'}")
    print(f"פקיעות מסולקות ב-condor_settled_detail: {res['settled_total']} · "
          f"כבר ב-expiry_history: {res['already_present']} · "
          f"מועמדות להוספה: {len(res['to_insert'])} · דולגו (בלי base): {len(res['skipped_no_base'])}")
    if res["to_insert"]:
        print("\nפקיעות שייכנסו ל-expiry_history (move_pct בהגדרה ההיסטורית):")
        print(f"  {'פקיעה':<12}{'סוג':>4}{'base':>12}{'פקיעה':>12}{'move_pct':>11}{'|move|':>9}")
        for r in res["to_insert"]:
            print(f"  {r['expiry_date']!s:<12}{r['expiry_type']:>4}{r['base_price']:>12.2f}"
                  f"{r['expiry_price']:>12.2f}{r['move_pct']:>+11.4f}{r['abs_move_pct']:>9.4f}")
    if res["skipped_no_base"]:
        print("\nדולגו (אין base תקין — לא ניתן לחשב move_pct):")
        for s in res["skipped_no_base"]:
            print(f"  {s['expiry_date']} — {s['reason']} (close={s['close']})")
    for w in res["warnings"]:
        print(f"  ⚠️  {w}")
    print("=" * 78)


def main() -> int:
    """CLI: dry-run כברירת מחדל; --commit כדי לכתוב בפועל. DATABASE_URL מהסביבה בלבד."""
    import argparse

    from paper_db import _make_engine

    ap = argparse.ArgumentParser(description="סגירת לולאת הלמידה: settlement → expiry_history")
    ap.add_argument("--commit", action="store_true",
                    help="כתיבה בפועל (append). בלי הדגל — dry-run בלבד.")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL", "").strip():
        print("❌ DATABASE_URL לא מוגדר. הרץ:")
        print('   DATABASE_URL="postgresql://..." python3 src/history_updater.py            # dry')
        print('   DATABASE_URL="postgresql://..." python3 src/history_updater.py --commit   # כתיבה')
        return 2

    engine = _make_engine(None)
    if engine is None:
        print("❌ לא ניתן לבנות engine מ-DATABASE_URL.")
        return 2

    res = update_expiry_history_from_settlements(engine, dry_run=not args.commit)
    _print_report(res)
    try:
        engine.dispose()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
