"""
בדיקות יחידה למודול data_loader.
"""

import io
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_loader import (
    _clean_numeric,
    load_market_csv,
    get_engine,
    init_db,
    save_to_db,
    load_from_db,
    run_full_load,
)

# -----------------------------------------------------------------------
# CSV מינימלי לבדיקות
# -----------------------------------------------------------------------
SAMPLE_CSV = textwrap.dedent("""\
    תאריך,שעה,סוג,בסיס,פקיעה,פתיחה%,נעילה,יומי%,מחזור,עסקאות,נקודות,אחוז
    7.5.2026,10:06:21,W,"4,505.61","4,531.18",0.57%,"4,469.69",0.80%,198.1,"2,616",28.97,0.64%
    1.4.2026,09:59:00,M,"4,000.00","3,960.00",0.50%,"3,980.00",0.80%,150.0,"1,000",40.00,1.00%
    30.3.2026,,-, 0,"4,081.34",0.00%,0,0.00%,0,0,81.45,1.96%
    28.1.2010,09:48:28,M,"1,125.04","1,134.92",0.88%,"1,135.79",0.96%,"1,214.90","3,181",פקיעה ראשונה,פקיעה ראשונה
""")


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """קובץ CSV זמני לבדיקות."""
    p = tmp_path / "market_data.csv"
    p.write_text(SAMPLE_CSV, encoding="utf-8-sig")
    return p


@pytest.fixture
def memory_engine():
    """SQLite engine בזיכרון לבדיקות."""
    return create_engine("sqlite:///:memory:", echo=False)


# -----------------------------------------------------------------------
# _clean_numeric
# -----------------------------------------------------------------------

def test_clean_numeric_removes_commas():
    """בדיקה שהסרת פסיקות עובדת."""
    s = pd.Series(["4,505.61", "1,000"])
    result = _clean_numeric(s)
    assert result.tolist() == pytest.approx([4505.61, 1000.0])


def test_clean_numeric_removes_percent():
    """בדיקה שהסרת סימן % עובדת."""
    s = pd.Series(["0.57%", "1.96%"])
    result = _clean_numeric(s)
    assert result.tolist() == pytest.approx([0.57, 1.96])


def test_clean_numeric_coerces_text_to_nan():
    """ערך טקסטואלי שאינו מספר הופך ל-NaN."""
    s = pd.Series(["פקיעה ראשונה", "123"])
    result = _clean_numeric(s)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == pytest.approx(123.0)


# -----------------------------------------------------------------------
# load_market_csv
# -----------------------------------------------------------------------

def test_load_skips_first_expiry_row(sample_csv):
    """שורת 'פקיעה ראשונה' בסוף הקובץ מדולגת."""
    df = load_market_csv(sample_csv)
    assert len(df) == 3  # 4 שורות מינוס שורת פקיעה ראשונה


def test_load_expiry_type_unknown(sample_csv):
    """שורות עם סוג '-' הופכות ל-unknown."""
    df = load_market_csv(sample_csv)
    assert "unknown" in df["expiry_type"].values
    assert "-" not in df["expiry_type"].values


def test_load_move_pct_positive_expiry(sample_csv):
    """move_pct חיובי כשהפקיעה גדולה מהבסיס."""
    df = load_market_csv(sample_csv)
    weekly = df[df["expiry_type"] == "W"].iloc[0]
    expected = (4531.18 - 4505.61) / 4505.61 * 100
    assert weekly["move_pct"] == pytest.approx(expected, rel=1e-4)


def test_load_move_pct_negative_expiry(sample_csv):
    """move_pct שלילי כשהפקיעה קטנה מהבסיס."""
    df = load_market_csv(sample_csv)
    monthly = df[df["expiry_type"] == "M"].iloc[0]
    expected = (3960.0 - 4000.0) / 4000.0 * 100
    assert monthly["move_pct"] == pytest.approx(expected, rel=1e-4)


def test_load_unknown_move_pct_is_nan(sample_csv):
    """שורות unknown ללא בסיס → move_pct=NaN."""
    df = load_market_csv(sample_csv)
    unknown = df[df["expiry_type"] == "unknown"]
    assert unknown["move_pct"].isna().all()


def test_load_abs_move_pct_always_positive(sample_csv):
    """עמודת abs_move_pct אינה שלילית."""
    df = load_market_csv(sample_csv)
    valid = df["abs_move_pct"].dropna()
    assert (valid >= 0).all()


def test_load_file_not_found():
    """FileNotFoundError כשהקובץ לא קיים."""
    with pytest.raises(FileNotFoundError):
        load_market_csv(Path("/no/such/file.csv"))


def test_load_date_parsed(sample_csv):
    """תאריכים מפורסרים כ-datetime."""
    df = load_market_csv(sample_csv)
    assert pd.api.types.is_datetime64_any_dtype(df["expiry_date"])


# -----------------------------------------------------------------------
# init_db + save_to_db + load_from_db
# -----------------------------------------------------------------------

def test_init_db_creates_table(memory_engine):
    """init_db יוצר טבלת expiry_history."""
    init_db(memory_engine)
    with memory_engine.connect() as conn:
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='expiry_history'")
        )
        assert result.fetchone() is not None


def test_save_and_load_roundtrip(sample_csv, memory_engine):
    """שמירה וקריאה חזרה מחזירות את אותן שורות."""
    df = load_market_csv(sample_csv)
    count = save_to_db(df, memory_engine)
    assert count == len(df)

    loaded = load_from_db(memory_engine)
    assert len(loaded) == len(df)
    assert set(loaded["expiry_type"].unique()) == {"W", "M", "unknown"}


def test_save_replace_resets_table(sample_csv, memory_engine):
    """if_exists='replace' מאפס את הטבלה לפני שמירה חדשה."""
    df = load_market_csv(sample_csv)
    save_to_db(df, memory_engine, if_exists="replace")
    save_to_db(df, memory_engine, if_exists="replace")
    loaded = load_from_db(memory_engine)
    assert len(loaded) == len(df)  # לא כפול


# -----------------------------------------------------------------------
# run_full_load
# -----------------------------------------------------------------------

def test_run_full_load(sample_csv, tmp_path):
    """run_full_load מחזיר מספר שורות תקין ויוצר DB."""
    db_path = tmp_path / "test.db"
    count = run_full_load(csv_path=sample_csv, db_path=db_path)
    assert count == 3
    assert db_path.exists()
