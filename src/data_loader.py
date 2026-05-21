"""
מודול לטעינה, ניקוי ושמירת נתוני פקיעות TA-35.

זרימת עבודה:
  CSV → load_market_csv() → DataFrame נקי → save_to_db() → expiry_history ב-SQLite
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "ta35.db"
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "uploads" / "market_data.csv"

COLUMN_MAP = {
    "תאריך": "expiry_date",
    "שעה": "expiry_time",
    "סוג": "expiry_type",
    "בסיס": "base_price",
    "פקיעה": "expiry_price",
    "פתיחה%": "open_pct",
    "נעילה": "close_price",
    "יומי%": "daily_pct",
    "מחזור": "volume",
    "עסקאות": "transactions",
    "נקודות": "points",
    "אחוז": "abs_move_pct",
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS expiry_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expiry_date DATE NOT NULL,
    expiry_time TEXT,
    expiry_type TEXT NOT NULL,
    base_price REAL,
    expiry_price REAL,
    open_pct REAL,
    close_price REAL,
    daily_pct REAL,
    volume REAL,
    transactions INTEGER,
    points REAL,
    abs_move_pct REAL,
    move_pct REAL
)
"""


def _clean_numeric(series: pd.Series) -> pd.Series:
    """מנקה עמודת מספרים: מסיר פסיקות, סימן אחוז, ורווחים."""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False).str.strip(),
        errors="coerce",
    )


def load_market_csv(csv_path: Optional[Path] = None) -> pd.DataFrame:
    """
    טוען וממנקה את קובץ הפקיעות ההיסטוריות market_data.csv.

    מחשב move_pct עם סימן מעמודות בסיס ופקיעה.
    שורות עם סוג '-' מסומנות כ-unknown (move_pct יהיה NaN כי base_price=0).
    שורת 'פקיעה ראשונה' בסוף הקובץ מדולגת אוטומטית.

    מחזיר DataFrame עם עמודות באנגלית, מוכן לשמירה ב-DB.
    """
    path = Path(csv_path) if csv_path else DEFAULT_CSV_PATH
    if not path.exists():
        raise FileNotFoundError(f"קובץ CSV לא נמצא: {path}")

    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    logger.info("נטענו %d שורות מ-%s", len(df), path)

    # דילוג על שורה אחרונה אם מכילה "פקיעה ראשונה"
    if df.iloc[-1].astype(str).str.contains("פקיעה ראשונה", na=False).any():
        df = df.iloc[:-1].copy()
        logger.info("דולגה שורת 'פקיעה ראשונה' בסוף הקובץ")

    df = df.rename(columns=COLUMN_MAP)

    # תאריך: D.M.YYYY (יום/חודש חד או דו-ספרתיים)
    df["expiry_date"] = pd.to_datetime(df["expiry_date"].str.strip(), dayfirst=True, errors="coerce")

    # עמודות מספריות עם פסיקות
    for col in ("base_price", "expiry_price", "close_price", "volume", "points", "transactions"):
        df[col] = _clean_numeric(df[col])

    # עמודות אחוז עם סימן %
    for col in ("open_pct", "daily_pct", "abs_move_pct"):
        df[col] = _clean_numeric(df[col])

    # סוג פקיעה: '-' → 'unknown'
    df["expiry_type"] = df["expiry_type"].str.strip().replace("-", "unknown")

    # move_pct עם סימן: (פקיעה - בסיס) / בסיס * 100
    # שורות עם base_price=0 (סוג unknown) יישארו NaN
    valid = (df["base_price"] > 0) & df["base_price"].notna() & df["expiry_price"].notna()
    df["move_pct"] = np.nan
    df.loc[valid, "move_pct"] = (
        (df.loc[valid, "expiry_price"] - df.loc[valid, "base_price"])
        / df.loc[valid, "base_price"]
        * 100
    )

    logger.info(
        "חושב move_pct עבור %d פקיעות; %d שורות ללא בסיס תקין (unknown)",
        valid.sum(),
        (~valid).sum(),
    )
    return df


def get_engine(db_path: Optional[Path] = None):
    """
    מחזיר SQLAlchemy engine לחיבור ל-SQLite.
    יוצר תיקיית database אם אינה קיימת.
    """
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False)


def init_db(engine=None) -> None:
    """יוצר טבלת expiry_history ב-SQLite אם אינה קיימת."""
    eng = engine or get_engine()
    with eng.connect() as conn:
        conn.execute(text(CREATE_TABLE_SQL))
        conn.commit()
    logger.info("טבלת expiry_history אותחלה")


def save_to_db(df: pd.DataFrame, engine=None, if_exists: str = "replace") -> int:
    """
    שומר DataFrame של פקיעות לטבלת expiry_history ב-SQLite.

    if_exists='replace' מאפס את הטבלה לפני שמירה (ברירת מחדל).
    if_exists='append' מוסיף שורות לטבלה קיימת.
    מחזיר את מספר השורות שנשמרו.
    """
    eng = engine or get_engine()
    init_db(eng)

    save_cols = [
        "expiry_date", "expiry_time", "expiry_type",
        "base_price", "expiry_price", "open_pct", "close_price", "daily_pct",
        "volume", "transactions", "points", "abs_move_pct", "move_pct",
    ]
    out = df[save_cols].copy()
    out["expiry_date"] = out["expiry_date"].dt.strftime("%Y-%m-%d")

    out.to_sql("expiry_history", eng, if_exists=if_exists, index=False)
    logger.info("נשמרו %d שורות לטבלת expiry_history", len(out))
    return len(out)


def load_from_db(engine=None) -> pd.DataFrame:
    """
    טוען את כל פקיעות ההיסטוריה מטבלת expiry_history לתוך DataFrame.
    ממוין לפי תאריך פקיעה בסדר יורד (החדש ביותר קודם).
    """
    eng = engine or get_engine()
    with eng.connect() as conn:
        result = conn.execute(text("SELECT * FROM expiry_history ORDER BY expiry_date DESC"))
        rows = result.fetchall()
        cols = list(result.keys())
    df = pd.DataFrame(rows, columns=cols)
    df["expiry_date"] = pd.to_datetime(df["expiry_date"])
    logger.info("נטענו %d שורות מבסיס הנתונים", len(df))
    return df


def run_full_load(csv_path: Optional[Path] = None, db_path: Optional[Path] = None) -> int:
    """
    פונקציה ראשית: טוען CSV, מנקה נתונים, מחשב move_pct, שומר ל-SQLite.
    מחזיר מספר השורות שנשמרו.
    """
    df = load_market_csv(csv_path)
    engine = get_engine(db_path)
    return save_to_db(df, engine, if_exists="replace")
