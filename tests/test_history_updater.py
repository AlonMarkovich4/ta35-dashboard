"""
בדיקות יחידה ל-history_updater — סגירת לולאת הלמידה (settlement → expiry_history).

הבדיקות רצות מול SQLite בזיכרון (כמו test_data_loader) — נתיב-הכתיבה האמיתי
(data_loader.save_to_db, append), לא מוקים. מכסה: עקביות move_pct להגדרה ההיסטורית,
אידמפוטנטיות, dry_run לא כותב, דילוג בלי-base, גזירת W/M, ושימוש ב-base_index_value.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_loader import load_from_db, load_market_csv, save_to_db
from history_updater import (
    compute_move_pct,
    update_expiry_history_from_settlements,
)


# ─── fixtures + עוזרי בנייה ──────────────────────────────────────────────

@pytest.fixture
def engine():
    """SQLite בזיכרון (SingletonThreadPool → DB יציב בין connects, כמו test_data_loader)."""
    return create_engine("sqlite:///:memory:", echo=False)


def _seed_history(eng, dates, types=None):
    """זורע expiry_history עם פקיעות קיימות (דרך נתיב-הכתיבה ההיסטורי)."""
    n = len(dates)
    df = pd.DataFrame({
        "expiry_date":  pd.to_datetime(dates),
        "expiry_time":  [None] * n,
        "expiry_type":  types or ["W"] * n,
        "base_price":   [4000.0] * n,
        "expiry_price": [4010.0] * n,
        "open_pct":     [None] * n,
        "close_price":  [None] * n,
        "daily_pct":    [None] * n,
        "volume":       [None] * n,
        "transactions": [None] * n,
        "points":       [None] * n,
        "abs_move_pct": [0.25] * n,
        "move_pct":     [0.25] * n,
    })
    save_to_db(df, eng, if_exists="replace")


def _seed_settled(eng, rows):
    """זורע condor_settled_detail (expiry_date TEXT, base_index_value, actual_index_close, [drvtype])."""
    pd.DataFrame(rows).to_sql("condor_settled_detail", eng, if_exists="replace", index=False)


# ─── compute_move_pct — עקביות עם ההגדרה ההיסטורית ───────────────────────

def test_compute_move_pct_signed_and_abs():
    """(פקיעה−בסיס)/בסיס·100 — חתום, ו-abs תמיד חיובי."""
    mv, ab = compute_move_pct(3994.6, 4196.0)
    expected = (4196.0 - 3994.6) / 3994.6 * 100
    assert mv == pytest.approx(expected, rel=1e-9)
    assert ab == pytest.approx(abs(expected), rel=1e-9)


def test_compute_move_pct_negative():
    """פקיעה מתחת לבסיס → move_pct שלילי."""
    mv, ab = compute_move_pct(4000.0, 3960.0)
    assert mv == pytest.approx(-1.0)
    assert ab == pytest.approx(1.0)


def test_compute_move_pct_invalid_base():
    """base None/0/שלילי → (None, None) — כמו תנאי ה-valid ב-load_market_csv."""
    assert compute_move_pct(0, 4000) == (None, None)
    assert compute_move_pct(None, 4000) == (None, None)
    assert compute_move_pct(-5, 4000) == (None, None)
    assert compute_move_pct(4000, None) == (None, None)


def test_move_pct_identical_to_data_loader(tmp_path):
    """הוכחת עקביות: אותו base/expiry דרך load_market_csv נותן אותו move_pct בדיוק."""
    csv = (
        "תאריך,שעה,סוג,בסיס,פקיעה,פתיחה%,נעילה,יומי%,מחזור,עסקאות,נקודות,אחוז\n"
        '16.7.2026,10:00,M,"3,994.60","4,196.00",0%,0,0%,0,0,0,5.04%\n'
    )
    p = tmp_path / "m.csv"
    p.write_text(csv, encoding="utf-8-sig")
    hist_move = load_market_csv(p).iloc[0]["move_pct"]
    mv, _ = compute_move_pct(3994.60, 4196.00)
    assert mv == pytest.approx(hist_move, rel=1e-9)


# ─── dry_run לא כותב ─────────────────────────────────────────────────────

def test_dry_run_does_not_write(engine):
    """dry_run=True מחשב תוכנית אך לא נוגע ב-expiry_history."""
    _seed_history(engine, ["2026-05-07"])
    _seed_settled(engine, [
        {"expiry_date": "2026-07-16", "base_index_value": 3994.6, "actual_index_close": 4196.0},
        {"expiry_date": "2026-07-16", "base_index_value": 3994.6, "actual_index_close": 4196.0},  # שורות פירוט
    ])
    before = len(load_from_db(engine))
    res = update_expiry_history_from_settlements(engine, dry_run=True)
    assert res["dry_run"] is True
    assert res["inserted"] == 0
    assert len(res["to_insert"]) == 1                 # קובצו ל-פקיעה אחת
    assert len(load_from_db(engine)) == before        # לא נכתב דבר


# ─── commit — הכנסה עם move_pct היסטורי מ-base_index_value ────────────────

def test_commit_inserts_with_historical_move(engine):
    """dry_run=False מוסיף שורה עם base=base_index_value ו-move_pct בהגדרה ההיסטורית."""
    _seed_history(engine, ["2026-05-07"])
    _seed_settled(engine, [
        {"expiry_date": "2026-07-16", "base_index_value": 3994.6, "actual_index_close": 4196.0},
    ])
    res = update_expiry_history_from_settlements(engine, dry_run=False)
    assert res["inserted"] == 1
    df = load_from_db(engine)
    row = df[df["expiry_date"] == pd.Timestamp("2026-07-16")].iloc[0]
    assert float(row["base_price"]) == pytest.approx(3994.6)     # base_index_value ← base_price
    assert float(row["expiry_price"]) == pytest.approx(4196.0)   # actual_index_close ← expiry_price
    assert float(row["move_pct"]) == pytest.approx((4196.0 - 3994.6) / 3994.6 * 100, rel=1e-6)


# ─── אידמפוטנטיות ─────────────────────────────────────────────────────────

def test_idempotent_second_run_inserts_nothing(engine):
    """הרצה חוזרת לא מכניסה שוב — append-only, ללא כפילות."""
    _seed_history(engine, ["2026-05-07"])
    _seed_settled(engine, [
        {"expiry_date": "2026-07-16", "base_index_value": 3994.6, "actual_index_close": 4196.0},
    ])
    r1 = update_expiry_history_from_settlements(engine, dry_run=False)
    assert r1["inserted"] == 1
    n_after_first = len(load_from_db(engine))

    r2 = update_expiry_history_from_settlements(engine, dry_run=False)
    assert r2["inserted"] == 0
    assert r2["already_present"] >= 1
    assert len(load_from_db(engine)) == n_after_first    # לא כפול


def test_existing_expiry_is_skipped(engine):
    """פקיעה שכבר ב-expiry_history לא מסומנת להוספה."""
    _seed_history(engine, ["2026-07-16"])                # כבר קיימת
    _seed_settled(engine, [
        {"expiry_date": "2026-07-16", "base_index_value": 3994.6, "actual_index_close": 4196.0},
    ])
    res = update_expiry_history_from_settlements(engine, dry_run=True)
    assert res["already_present"] == 1
    assert res["to_insert"] == []


# ─── דילוג בלי base תקין ─────────────────────────────────────────────────

def test_skipped_when_base_missing_or_zero(engine):
    """base_index_value NULL/0 → לא ניתן לחשב move_pct → מדולג, לא מוכנס."""
    _seed_history(engine, ["2026-05-07"])
    _seed_settled(engine, [
        {"expiry_date": "2026-07-16", "base_index_value": None, "actual_index_close": 4196.0},
        {"expiry_date": "2026-07-23", "base_index_value": 0.0,  "actual_index_close": 4200.0},
    ])
    res = update_expiry_history_from_settlements(engine, dry_run=False)
    assert res["inserted"] == 0
    assert len(res["skipped_no_base"]) == 2


# ─── גזירת סוג הפקיעה W/M ─────────────────────────────────────────────────

def test_expiry_type_derived_from_date(engine):
    """בלי עמודת-סוג: 31/07/2026 (שישי אחרון בחודש) → M; 16/07 (חמישי) → W."""
    _seed_history(engine, ["2026-05-07"])
    _seed_settled(engine, [
        {"expiry_date": "2026-07-31", "base_index_value": 4000.0, "actual_index_close": 4040.0},
        {"expiry_date": "2026-07-16", "base_index_value": 4000.0, "actual_index_close": 4040.0},
    ])
    res = update_expiry_history_from_settlements(engine, dry_run=True)
    types = {str(r["expiry_date"]): r["expiry_type"] for r in res["to_insert"]}
    assert types["2026-07-31"] == "M"
    assert types["2026-07-16"] == "W"


def test_type_column_used_when_present(engine):
    """עמודת drvtype='monthly' גוברת על הגזירה-מהתאריך → M, ומדווחת ב-columns_used."""
    _seed_history(engine, ["2026-05-07"])
    _seed_settled(engine, [
        {"expiry_date": "2026-07-16", "base_index_value": 4000.0,
         "actual_index_close": 4040.0, "drvtype": "monthly"},
    ])
    res = update_expiry_history_from_settlements(engine, dry_run=True)
    assert res["to_insert"][0]["expiry_type"] == "M"
    assert res["columns_used"]["type"] == "drvtype"


# ─── ריבוי שורות-פירוט לפקיעה (base קבוע) → מקובצות לשורה אחת ─────────────

def test_multiple_strike_rows_collapse_to_one(engine):
    """כמה שורות פירוט (לפי סטרייק) לאותה פקיעה → פקיעה אחת בהיסטוריה."""
    _seed_history(engine, ["2026-05-07"])
    _seed_settled(engine, [
        {"expiry_date": "2026-07-16", "base_index_value": 3994.6, "actual_index_close": 4196.0},
        {"expiry_date": "2026-07-16", "base_index_value": 3994.6, "actual_index_close": 4196.0},
        {"expiry_date": "2026-07-16", "base_index_value": 3994.6, "actual_index_close": 4196.0},
    ])
    res = update_expiry_history_from_settlements(engine, dry_run=False)
    assert res["inserted"] == 1
    df = load_from_db(engine)
    assert len(df[df["expiry_date"] == pd.Timestamp("2026-07-16")]) == 1
