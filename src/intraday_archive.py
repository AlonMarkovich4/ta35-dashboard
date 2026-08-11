"""
intraday_archive.py — שימור צילומי השרשרת התוך-יומיים.

**למה המודול הזה קיים**

`tase_putcall` (הטבלה החיה של המתכנת השני) מתעדכנת כל ~15 דקות במהלך המסחר.
`tase_putcall_history` שומרת ממנה **צילום אחד ביום, ב-~17:15**. כלומר כל
ההתפתחות התוך-יומית — כמה נסחר עד 11:00, עד 14:00, עד 16:00 — נזרקת.

זה בדיוק הנתון שחסר כדי לענות על השאלה "האם השעה שאני נכנס בה סבירה":
משתמש ניסה למכור אופציות ב-16:30 (נעילה ~17:00) ולא נמצא קונה. עם עקומת
מחזור לפי שעה אפשר לדעת מראש כמה מהמחזור היומי כבר עבר.

**מה שהמודול הזה אינו נותן:** ספר פקודות. `bid`/`ask` אינם קיימים במקור
כלל (HANDOFF 11.2ג). מחזור הוא עבר, לא הווה — הוא מקטין סיכון, לא מבטל אותו.

**גבולות בעלות (AGENTS.md):** `tase_putcall` שייכת למתכנת השני — **SELECT
בלבד**. הטבלה שנכתבת כאן היא שלנו.

**אידמפוטנטיות:** המפתח הוא `(fetch_date, fetch_time, expiry_date, strike)` —
כלומר הצילום של **המקור**, לא זמן הריצה שלנו. ריצה כפולה על אותו צילום
אינה מוסיפה כלום, ו-Action שנדחה אינו מייצר כפילות.

API ציבורי:
  INTRADAY_TABLE                              קבוע — שם הטבלה
  create_table_sql()                     -> str        (טהור)
  table_exists(engine)                   -> bool
  archive_current_snapshot(engine, dry_run=True) -> dict
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

INTRADAY_TABLE = "tase_putcall_intraday"
SOURCE_TABLE = "tase_putcall"          # SELECT בלבד — בבעלות המתכנת השני


def create_table_sql() -> str:
    """DDL לטבלת הארכוב. אידמפוטנטי (IF NOT EXISTS).

    שומר גם שדות שאינם נזילות (`lastrate`, `delta`) בכוונה: הלקח החוזר
    בפרויקט הזה הוא שדאטה שנזרק אינו ניתן לשחזור, ועלות האחסון זניחה מול
    עלות הגילוי שחסר שדה.
    """
    return f"""
    CREATE TABLE IF NOT EXISTS {INTRADAY_TABLE} (
        id                  bigserial PRIMARY KEY,
        fetch_date          date        NOT NULL,
        fetch_time          text        NOT NULL,
        trade_date          text,
        expiry_date         date        NOT NULL,
        strike              numeric     NOT NULL,
        baserate            numeric,
        lastrate_call       numeric,
        lowrate_call        numeric,
        highrate_call       numeric,
        dealsno_call        numeric,
        turnover_units_call numeric,
        turnover_nis_call   numeric,
        openpositions_call  numeric,
        delta_call          numeric,
        lastrate_put        numeric,
        lowrate_put         numeric,
        highrate_put        numeric,
        dealsno_put         numeric,
        turnover_units_put  numeric,
        turnover_nis_put    numeric,
        openpositions_put   numeric,
        delta_put           numeric,
        archived_at         timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT {INTRADAY_TABLE}_snapshot_key
            UNIQUE (fetch_date, fetch_time, expiry_date, strike)
    );
    CREATE INDEX IF NOT EXISTS {INTRADAY_TABLE}_expiry_idx
        ON {INTRADAY_TABLE} (expiry_date, fetch_date, fetch_time);
    """


def table_exists(engine) -> bool:
    """האם טבלת הארכוב קיימת. כשל DB ⇒ False (fail-safe: אל תנסה לכתוב)."""
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            return bool(conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"),
                {"t": INTRADAY_TABLE},
            ).scalar())
    except Exception as exc:
        logger.warning("table_exists נכשל: %s", exc, exc_info=True)
        return False


def current_snapshot_id(engine) -> Optional[dict]:
    """זהות הצילום שיושב כרגע ב-`tase_putcall`: {fetch_date, fetch_time, rows}."""
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT fetch_date, fetch_time, trade_date, count(*) AS rows
                FROM {SOURCE_TABLE}
                GROUP BY fetch_date, fetch_time, trade_date
                ORDER BY max(fetched_at) DESC
                LIMIT 1
            """)).fetchone()
    except Exception as exc:
        logger.warning("current_snapshot_id נכשל: %s", exc, exc_info=True)
        return None
    if row is None:
        return None
    m = row._mapping
    return {"fetch_date": str(m["fetch_date"])[:10],
            "fetch_time": m["fetch_time"],
            "trade_date": m["trade_date"],
            "rows": int(m["rows"] or 0)}


def already_archived(engine, snap: dict) -> int:
    """כמה שורות כבר קיימות בארכוב עבור הצילום הזה."""
    if engine is None or not snap:
        return 0
    try:
        with engine.connect() as conn:
            return int(conn.execute(text(f"""
                SELECT count(*) FROM {INTRADAY_TABLE}
                WHERE fetch_date = CAST(:d AS date) AND fetch_time = :t
            """), {"d": snap["fetch_date"], "t": snap["fetch_time"]}).scalar() or 0)
    except Exception as exc:
        logger.warning("already_archived נכשל: %s", exc, exc_info=True)
        return 0


def archive_current_snapshot(engine, dry_run: bool = True) -> dict:
    """מעתיק את הצילום הנוכחי מ-`tase_putcall` לטבלת הארכוב.

    `ON CONFLICT DO NOTHING` על מפתח הצילום — ריצה כפולה בטוחה.
    מחזיר {status, snapshot, source_rows, existing, inserted, reason}.
    """
    result: dict = {"status": "skipped", "snapshot": None, "source_rows": 0,
                    "existing": 0, "inserted": 0, "reason": None}

    if engine is None:
        result["reason"] = "אין חיבור ל-DB"
        return result
    if not table_exists(engine):
        result["reason"] = f"טבלת {INTRADAY_TABLE} אינה קיימת — צור אותה פעם אחת"
        return result

    snap = current_snapshot_id(engine)
    if snap is None or not snap["rows"]:
        result["reason"] = f"אין צילום ב-{SOURCE_TABLE}"
        logger.warning("archive_current_snapshot: %s", result["reason"])
        return result
    result["snapshot"] = snap
    result["source_rows"] = snap["rows"]

    existing = already_archived(engine, snap)
    result["existing"] = existing
    if existing:
        result["status"] = "duplicate"
        result["reason"] = (f"צילום {snap['fetch_date']} {snap['fetch_time']} כבר "
                            f"מארכב ({existing} שורות) — אין מה להוסיף")
        return result

    if dry_run:
        result["status"] = "dry-run"
        result["reason"] = f"dry-run — היו נכתבות עד {snap['rows']} שורות"
        return result

    try:
        with engine.begin() as conn:
            res = conn.execute(text(f"""
                INSERT INTO {INTRADAY_TABLE} (
                    fetch_date, fetch_time, trade_date, expiry_date, strike, baserate,
                    lastrate_call, lowrate_call, highrate_call, dealsno_call,
                    turnover_units_call, turnover_nis_call, openpositions_call, delta_call,
                    lastrate_put,  lowrate_put,  highrate_put,  dealsno_put,
                    turnover_units_put,  turnover_nis_put,  openpositions_put,  delta_put
                )
                SELECT
                    s.fetch_date::date, s.fetch_time, s.trade_date, s.expiry_date::date,
                    COALESCE(s.expirationprice_call, s.expirationprice_put),
                    COALESCE(s.baserate_call, s.baserate_put),
                    s.lastrate_call, s.lowrate_call, s.highrate_call, s.dealsno_call,
                    s.overallturnoverunits_call, s.overallturnovervalue_shekel_call,
                    s.openpositions_call, s.delta_call,
                    s.lastrate_put,  s.lowrate_put,  s.highrate_put,  s.dealsno_put,
                    s.overallturnoverunits_put,  s.overallturnovervalue_shekel_put,
                    s.openpositions_put,  s.delta_put
                FROM {SOURCE_TABLE} s
                WHERE s.fetch_date::date = CAST(:d AS date)
                  AND s.fetch_time = :t
                  AND COALESCE(s.expirationprice_call, s.expirationprice_put) IS NOT NULL
                  AND s.expiry_date IS NOT NULL
                ON CONFLICT ON CONSTRAINT {INTRADAY_TABLE}_snapshot_key DO NOTHING
            """), {"d": snap["fetch_date"], "t": snap["fetch_time"]})
            result["inserted"] = int(res.rowcount or 0)
    except Exception as exc:
        result["status"] = "error"
        result["reason"] = str(exc)[:200]
        logger.warning("archive_current_snapshot נכשל: %s", exc, exc_info=True)
        return result

    result["status"] = "archived"
    logger.info("archive_current_snapshot: %s %s — נשמרו %d שורות.",
                snap["fetch_date"], snap["fetch_time"], result["inserted"])
    return result
