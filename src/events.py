"""
שכבת אירועים — TA-35 Expiry Intelligence.

מנהל טבלת events ב-SQLite: אירועים היסטוריים שמשפיעים על פקיעות.
מספק קישור בין כל פקיעה לאירועים שקרו סמוך לה (±7 ימים לפני).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import Column, Date, Integer, MetaData, Table, Text, text

_EVENTS_METADATA = MetaData()
_EVENTS_TABLE = Table(
    "events", _EVENTS_METADATA,
    Column("id",          Integer, primary_key=True),
    Column("event_date",  Date,    nullable=False),
    Column("name",        Text,    nullable=False),
    Column("category",    Text,    nullable=False),
    Column("description", Text,    server_default="''"),
    Column("source",      Text,    server_default="''"),
)

# ─── אירועים היסטוריים להזרעה ─────────────────────────────────────
# קטגוריות: מלחמה | מגפה | ריבית | משבר | פוליטי

_SEED_EVENTS: list[dict] = [
    # ─── קורונה ───
    {"event_date": "2020-02-24", "name": "קריסת שווקים — קורונה מתפשטת",
     "category": "מגפה",
     "description": "שווקים העולמיים צנחו כשקורונה הפכה מגפה גלובלית; TA-35 ירד ~30% בחודש"},
    {"event_date": "2020-03-18", "name": "סגר ראשון — ישראל",
     "category": "מגפה",
     "description": "ממשלת ישראל הכריזה על סגר לאומי ראשון; תנודתיות גבוהה מאוד"},
    {"event_date": "2020-11-09", "name": "הכרזת חיסון פייזר",
     "category": "מגפה",
     "description": "פייזר הודיעה על חיסון יעיל ב-90%; ראלי חד בשווקים גלובליים"},
    {"event_date": "2021-01-05", "name": "סגר שלישי — ישראל",
     "category": "מגפה",
     "description": "סגר שלישי עם גל אומיקרון מוקדם; חוסר ודאות גבוה"},

    # ─── מלחמות ───
    {"event_date": "2021-05-10", "name": "מבצע שומר החומות",
     "category": "מלחמה",
     "description": "לחימה בעזה 11 ימים; TA-35 ירד בחדות בפתיחה ואז התאושש חלקית"},
    {"event_date": "2022-02-24", "name": "פלישת רוסיה לאוקראינה",
     "category": "מלחמה",
     "description": "פלישה יבשתית מלאה; גז, נפט ואינפלציה זינקו; שווקים ירדו חדות"},
    {"event_date": "2023-10-07", "name": "מתקפת חמאס — תחילת מלחמת חרבות ברזל",
     "category": "מלחמה",
     "description": "מתקפה חסרת תקדים על ישראל; TA-35 פתח בירידות קשות ב-8/10"},
    {"event_date": "2023-10-27", "name": "כניסת כוחות יבשה לרצועה",
     "category": "מלחמה",
     "description": "פתיחת מבצע יבשתי בעזה; אי-ודאות ביטחונית ממושכת"},
    {"event_date": "2024-04-01", "name": "תקיפת הקונסוליה האיראנית בדמשק",
     "category": "מלחמה",
     "description": "ישראל תקפה מבנה קונסולרי איראני; הסלמה עם איראן"},
    {"event_date": "2024-04-13", "name": "מתקפת טילים איראנית על ישראל",
     "category": "מלחמה",
     "description": "מאות כטב\"מים וטילים בליסטיים; TA-35 ירד חדות ביום המסחר שאחריה"},
    {"event_date": "2024-10-01", "name": "מתקפת טילים איראנית — סבב שני",
     "category": "מלחמה",
     "description": "מנשר טילים בליסטיים על ישראל; שווקים בתנודתיות גבוהה"},

    # ─── ריבית ───
    {"event_date": "2022-03-16", "name": "העלאת ריבית Fed — ראשונה מזה שנים",
     "category": "ריבית",
     "description": "פד העלה ריבית 0.25% — תחילת מחזור הידוק; שווקים ירדו לאחר מכן"},
    {"event_date": "2022-06-15", "name": "העלאת ריבית Fed — 0.75% (ג'מבו)",
     "category": "ריבית",
     "description": "העלאה חריגה של 75 נקודות בסיס; אחת הגדולות מאז 1994"},
    {"event_date": "2022-11-02", "name": "העלאת ריבית Fed — 0.75% רביעית ברציפות",
     "category": "ריבית",
     "description": "פד ממשיך בהידוק אגרסיבי; שיא ריבית מאז 2007"},
    {"event_date": "2023-07-26", "name": "העלאת ריבית Fed — האחרונה במחזור",
     "category": "ריבית",
     "description": "העלאה ל-5.5%; שיא 22 שנים, לאחר מכן הפסקה"},
    {"event_date": "2024-09-18", "name": "הורדת ריבית Fed — ראשונה מזה 4 שנים",
     "category": "ריבית",
     "description": "Fed הוריד 0.5% — תחילת מחזור הקלה; ראלי בשווקים"},
    {"event_date": "2023-04-03", "name": "בנק ישראל: הפסקת העלאות ריבית",
     "category": "ריבית",
     "description": "בנק ישראל השאיר ריבית על 4.75% לאחר 10 העלאות רצופות"},

    # ─── משבר פיננסי ───
    {"event_date": "2023-03-10", "name": "קריסת SVB — בנק הסיליקון ואלי",
     "category": "משבר",
     "description": "ריצה על הבנק וסגירתו תוך 48 שעות; חשש ממשבר בנקאי רחב"},
    {"event_date": "2025-04-02", "name": "הטלת מכסים — טראמפ: יום השחרור",
     "category": "משבר",
     "description": "ארה\"ב הכריזה על מכסי ייבוא נרחבים; נפילות חדות בשווקים גלובליים"},
    {"event_date": "2025-04-09", "name": "השעיית מכסים ל-90 יום",
     "category": "משבר",
     "description": "טראמפ השעה מכסים לרוב המדינות; ראלי חריף בשווקים"},

    # ─── פוליטי / ישראל ───
    {"event_date": "2023-01-04", "name": "הקמת ממשלת נתניהו ו-6 + רפורמה משפטית",
     "category": "פוליטי",
     "description": "הכרזות על שינוי שיטת מינוי שופטים; מחאות וחוסר ודאות"},
    {"event_date": "2023-07-24", "name": "חקיקת סבירות — כנסת",
     "category": "פוליטי",
     "description": "קריאה ראשונה ושנייה בכנסת; מחאות המוניות, חשש להזרמת הון"},
]


# ─── פונקציות DB ──────────────────────────────────────────────────────

def init_events_db(engine) -> None:
    """יוצר טבלת events אם אינה קיימת — תומך ב-SQLite ו-PostgreSQL."""
    _EVENTS_METADATA.create_all(engine, checkfirst=True)
    # migration: add source column for existing SQLite DBs that predate it
    if engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE events ADD COLUMN source TEXT DEFAULT ''"))
                conn.commit()
            except Exception:
                pass  # column already exists


def seed_events(engine, force: bool = False) -> int:
    """
    מזריע את טבלת events באירועים היסטוריים מוגדרים-מראש.

    force=False — מדלג אם הטבלה כבר מכילה נתונים.
    force=True  — מוחק ומזריע מחדש.
    מחזיר מספר הרשומות שנוספו.
    """
    init_events_db(engine)
    with engine.connect() as conn:
        if force:
            conn.execute(text("DELETE FROM events"))
            conn.commit()
        count = conn.execute(text("SELECT COUNT(*) FROM events")).scalar()
        if count and not force:
            return 0
        for ev in _SEED_EVENTS:
            conn.execute(
                text(
                    "INSERT INTO events (event_date, name, category, description) "
                    "VALUES (:event_date, :name, :category, :description)"
                ),
                ev,
            )
        conn.commit()
    return len(_SEED_EVENTS)


def load_all_events(engine) -> pd.DataFrame:
    """
    טוען את כל האירועים מהטבלה לתוך DataFrame.
    ממוין לפי תאריך בסדר עולה.
    """
    init_events_db(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, event_date, name, category, description, source "
                 "FROM events ORDER BY event_date")
        ).fetchall()
    df = pd.DataFrame(rows, columns=["id", "event_date", "name", "category", "description", "source"])
    if not df.empty:
        df["event_date"] = pd.to_datetime(df["event_date"])
    return df


def load_events_by_source(engine, source: str, limit: int = 10) -> pd.DataFrame:
    """
    טוען אירועים לפי מקור, ממוין לפי ID יורד (החדשים קודם).

    source — שם המקור (לדוגמה: 'interactiveil' לטלגרם)
    limit  — מספר שורות מקסימלי (ברירת מחדל: 10)
    """
    init_events_db(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, event_date, name, category, description "
                "FROM events WHERE source = :src ORDER BY id DESC LIMIT :lim"
            ),
            {"src": source, "lim": limit},
        ).fetchall()
    df = pd.DataFrame(rows, columns=["id", "event_date", "name", "category", "description"])
    if not df.empty:
        df["event_date"] = pd.to_datetime(df["event_date"])
    return df


def add_event(engine, event_date: str | date, name: str, category: str,
              description: str = "", source: str = "") -> int:
    """
    מוסיף אירוע חדש לטבלה.
    מחזיר את ה-id של הרשומה החדשה.
    """
    init_events_db(engine)
    date_str = event_date.strftime("%Y-%m-%d") if isinstance(event_date, date) else str(event_date)
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO events (event_date, name, category, description, source) "
                 "VALUES (:d, :n, :c, :desc, :src)"),
            {"d": date_str, "n": name, "c": category, "desc": description, "src": source},
        )
        row_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
        conn.commit()
    return row_id


def delete_event(engine, event_id: int) -> None:
    """מוחק אירוע לפי id."""
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM events WHERE id = :id"), {"id": event_id})
        conn.commit()


def get_events_for_expiry(
    expiry_date: date | pd.Timestamp,
    engine,
    window_days: int = 7,
) -> pd.DataFrame:
    """
    מחזיר אירועים שקרו בטווח [expiry_date - window_days, expiry_date].

    expiry_date  — תאריך הפקיעה
    window_days  — כמה ימים לפני הפקיעה לחפש (ברירת מחדל 7)
    """
    if isinstance(expiry_date, pd.Timestamp):
        expiry_date = expiry_date.date()
    date_from = (expiry_date - timedelta(days=window_days)).strftime("%Y-%m-%d")
    date_to   = expiry_date.strftime("%Y-%m-%d")

    init_events_db(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, event_date, name, category, description FROM events "
                "WHERE event_date BETWEEN :d_from AND :d_to ORDER BY event_date"
            ),
            {"d_from": date_from, "d_to": date_to},
        ).fetchall()
    df = pd.DataFrame(rows, columns=["id", "event_date", "name", "category", "description"])
    if not df.empty:
        df["event_date"] = pd.to_datetime(df["event_date"])
    return df


def enrich_expiries_with_events(
    df_expiries: pd.DataFrame,
    engine,
    window_days: int = 7,
) -> pd.DataFrame:
    """
    מוסיף עמודות אירוע לכל שורה ב-df_expiries.

    עמודות שמתווספות:
      has_event  — bool: האם יש אירוע בטווח window_days לפני הפקיעה
      event_names — str: שמות האירועים (מופרדים ב-'; ') או ''
      event_categories — str: קטגוריות ייחודיות (מופרדות ב-', ') או ''
    """
    events_df = load_all_events(engine)
    if events_df.empty:
        df_out = df_expiries.copy()
        df_out["has_event"]         = False
        df_out["event_names"]       = ""
        df_out["event_categories"]  = ""
        return df_out

    ev_dates = events_df["event_date"].dt.normalize()
    ev_names = events_df["name"].values
    ev_cats  = events_df["category"].values

    names_list: list[str] = []
    cats_list:  list[str] = []

    for exp_date in df_expiries["expiry_date"]:
        exp_norm = pd.Timestamp(exp_date).normalize()
        mask = (ev_dates >= exp_norm - pd.Timedelta(days=window_days)) & (ev_dates <= exp_norm)
        matched_names = [ev_names[i] for i in range(len(ev_dates)) if mask.iloc[i]]
        matched_cats  = list(dict.fromkeys(ev_cats[i] for i in range(len(ev_dates)) if mask.iloc[i]))
        names_list.append("; ".join(matched_names))
        cats_list.append(", ".join(matched_cats))

    df_out = df_expiries.copy()
    df_out["event_names"]      = names_list
    df_out["event_categories"] = cats_list
    df_out["has_event"]        = df_out["event_names"] != ""
    return df_out


def compute_risk_score(
    upcoming_date: date | pd.Timestamp,
    engine,
    df_expiries: Optional[pd.DataFrame] = None,
    window_days: int = 7,
) -> dict:
    """
    מחשב ציון סיכון תנודתיות (0–10) לפקיעה הקרובה.

    מבוסס על:
      - כמות אירועים בטווח window_days לפני upcoming_date (ציון בסיסי)
      - ממוצע |move_pct| של פקיעות קרוב לאירועים דומים בהיסטוריה (תוספת)

    מחזיר:
      {
        'score': float (0–10),
        'level': str ('נמוך'/'בינוני'/'גבוה'),
        'nearby_events': list[str],
        'avg_abs_move_event': float | None,   # ממוצע |move_pct| בפקיעות עם אירועים
        'avg_abs_move_normal': float | None,  # ממוצע |move_pct| בפקיעות רגילות
      }
    """
    nearby = get_events_for_expiry(upcoming_date, engine, window_days=window_days)
    event_count = len(nearby)

    # ניתוח היסטורי: פקיעות עם/ללא אירוע
    avg_event  = None
    avg_normal = None
    if df_expiries is not None and not df_expiries.empty:
        enriched = enrich_expiries_with_events(df_expiries, engine, window_days=window_days)
        valid = enriched["move_pct"].notna()
        with_ev    = enriched[valid & enriched["has_event"]]["move_pct"].abs()
        without_ev = enriched[valid & ~enriched["has_event"]]["move_pct"].abs()
        avg_event  = float(with_ev.mean())  if not with_ev.empty  else None
        avg_normal = float(without_ev.mean()) if not without_ev.empty else None

    # ציון: 0–10
    base_score = min(event_count * 2.5, 7.0)  # עד 7 מאירועים
    boost = 0.0
    if avg_event and avg_normal and avg_normal > 0:
        ratio = avg_event / avg_normal
        boost = min((ratio - 1.0) * 2.0, 3.0)  # עד +3 מהגורם ההיסטורי
    score = round(min(base_score + boost, 10.0), 1)

    level = "נמוך" if score < 3.5 else ("גבוה" if score >= 6.5 else "בינוני")

    return {
        "score":              score,
        "level":              level,
        "nearby_events":      nearby["name"].tolist() if not nearby.empty else [],
        "avg_abs_move_event": round(avg_event, 2)  if avg_event  is not None else None,
        "avg_abs_move_normal": round(avg_normal, 2) if avg_normal is not None else None,
    }
