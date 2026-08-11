"""
בדיקות יחידה ל-intraday_archive — שמירת צילומי השרשרת התוך-יומיים.

הדגש כאן: **אידמפוטנטיות** (המפתח הוא הצילום של המקור, לא זמן הריצה),
**אפס כתיבה לטבלת המקור**, ו**דילוג עם סיבה** — לא בשקט.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday_archive import (  # noqa: E402
    INTRADAY_TABLE,
    SOURCE_TABLE,
    archive_current_snapshot,
    already_archived,
    create_table_sql,
    current_snapshot_id,
    table_exists,
)

SNAP = {"fetch_date": "2026-08-11", "fetch_time": "16:01",
        "trade_date": "10/08/2026", "rows": 347}


def _row(**kw) -> MagicMock:
    r = MagicMock()
    r._mapping = kw
    return r


def _conn(scalars=None, fetchone=None, rowcount=0) -> MagicMock:
    c = MagicMock()
    c.__enter__ = MagicMock(return_value=c)
    c.__exit__ = MagicMock(return_value=False)
    c.execute.return_value.scalar.side_effect = (
        list(scalars) if scalars is not None else [None])
    c.execute.return_value.fetchone.return_value = fetchone
    c.execute.return_value.rowcount = rowcount
    return c


def _engine(conn=None, raises=False) -> MagicMock:
    eng = MagicMock()
    if raises:
        eng.connect.side_effect = Exception("db down")
        eng.begin.side_effect = Exception("db down")
    else:
        conn = conn or _conn()
        eng.connect.return_value = conn
        eng.begin.return_value = conn
    return eng


# ─── DDL ────────────────────────────────────────────────────────────────

class TestCreateTableSql:
    def test_is_idempotent(self):
        sql = create_table_sql()
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "CREATE INDEX IF NOT EXISTS" in sql

    def test_unique_key_is_the_source_snapshot(self):
        """אידמפוטנטיות תלויה במפתח הזה: הצילום של המקור, לא זמן הריצה שלנו."""
        sql = create_table_sql()
        assert "UNIQUE (fetch_date, fetch_time, expiry_date, strike)" in sql

    def test_keeps_liquidity_and_pricing_fields(self):
        sql = create_table_sql()
        for col in ("dealsno_call", "turnover_units_call", "turnover_nis_call",
                    "openpositions_call", "lastrate_put", "delta_put", "baserate"):
            assert col in sql

    def test_targets_our_table_not_the_source(self):
        assert INTRADAY_TABLE in create_table_sql()
        assert SOURCE_TABLE != INTRADAY_TABLE


# ─── קריאות ─────────────────────────────────────────────────────────────

class TestReads:
    def test_table_exists_true_false(self):
        assert table_exists(_engine(_conn(scalars=[True]))) is True
        assert table_exists(_engine(_conn(scalars=[False]))) is False

    def test_table_exists_false_on_error(self):
        """fail-safe: לא יודעים ⇒ לא כותבים."""
        assert table_exists(_engine(raises=True)) is False
        assert table_exists(None) is False

    def test_current_snapshot_id_maps_fields(self):
        eng = _engine(_conn(fetchone=_row(fetch_date="2026-08-11", fetch_time="16:01",
                                          trade_date="10/08/2026", rows=347)))
        assert current_snapshot_id(eng) == SNAP

    def test_current_snapshot_none_when_empty(self):
        assert current_snapshot_id(_engine(_conn(fetchone=None))) is None
        assert current_snapshot_id(_engine(raises=True)) is None

    def test_already_archived_counts(self):
        assert already_archived(_engine(_conn(scalars=[347])), SNAP) == 347
        assert already_archived(_engine(_conn(scalars=[None])), SNAP) == 0
        assert already_archived(_engine(raises=True), SNAP) == 0


# ─── הארכוב עצמו ────────────────────────────────────────────────────────

def _archive_engine(exists=True, snap=SNAP, existing=0, rowcount=0):
    """engine שמחזיר: table_exists → snapshot → already_archived → INSERT."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.scalar.side_effect = [exists, existing] * 4
    conn.execute.return_value.fetchone.return_value = (
        _row(fetch_date=snap["fetch_date"], fetch_time=snap["fetch_time"],
             trade_date=snap["trade_date"], rows=snap["rows"]) if snap else None)
    conn.execute.return_value.rowcount = rowcount
    eng = MagicMock()
    eng.connect.return_value = conn
    eng.begin.return_value = conn
    return eng, conn


class TestArchive:
    def test_dry_run_writes_nothing(self):
        eng, conn = _archive_engine()
        r = archive_current_snapshot(eng, dry_run=True)
        assert r["status"] == "dry-run"
        assert r["inserted"] == 0
        assert not any("INSERT" in str(c[0][0]) for c in conn.execute.call_args_list)

    def test_commit_inserts(self):
        eng, _ = _archive_engine(rowcount=347)
        r = archive_current_snapshot(eng, dry_run=False)
        assert r["status"] == "archived"
        assert r["inserted"] == 347

    def test_duplicate_snapshot_is_not_reinserted(self):
        """הצילום כבר נשמר ⇒ אין מה להוסיף. זו האידמפוטנטיות בפועל."""
        eng, conn = _archive_engine(existing=347)
        r = archive_current_snapshot(eng, dry_run=False)
        assert r["status"] == "duplicate"
        assert r["inserted"] == 0
        assert not any("INSERT" in str(c[0][0]) for c in conn.execute.call_args_list)

    def test_missing_table_is_reported_not_silent(self):
        eng, _ = _archive_engine(exists=False)
        r = archive_current_snapshot(eng, dry_run=False)
        assert r["status"] == "skipped"
        assert INTRADAY_TABLE in r["reason"]

    def test_no_source_snapshot_is_reported(self):
        eng, _ = _archive_engine(snap=None)
        r = archive_current_snapshot(eng, dry_run=False)
        assert r["status"] == "skipped"
        assert SOURCE_TABLE in r["reason"]

    def test_every_skip_carries_a_reason(self):
        """דילוג שקט הוא הבאג החוזר בפרויקט — אין מסלול יציאה בלי סיבה."""
        for eng in (None,
                    _archive_engine(exists=False)[0],
                    _archive_engine(snap=None)[0]):
            assert archive_current_snapshot(eng, dry_run=False)["reason"]

    def test_db_error_returns_error_status(self):
        eng, _ = _archive_engine()
        eng.begin.side_effect = Exception("insert failed")
        r = archive_current_snapshot(eng, dry_run=False)
        assert r["status"] == "error"
        assert r["reason"]

    def test_insert_selects_from_source_and_writes_to_ours(self):
        eng, conn = _archive_engine(rowcount=1)
        archive_current_snapshot(eng, dry_run=False)
        sql = next(str(c[0][0]) for c in conn.execute.call_args_list
                   if "INSERT" in str(c[0][0]))
        assert f"INSERT INTO {INTRADAY_TABLE}" in sql
        assert f"FROM {SOURCE_TABLE}" in sql
        assert "ON CONFLICT" in sql

    def test_insert_never_writes_to_the_source_table(self):
        """`tase_putcall` בבעלות המתכנת השני — SELECT בלבד.

        גבול מילה חובה: `tase_putcall_intraday` מכיל את השם כתת-מחרוזת,
        ובלי `\\b` הבדיקה נכשלת על היעד הלגיטימי שלנו.
        """
        eng, conn = _archive_engine(rowcount=1)
        archive_current_snapshot(eng, dry_run=False)
        write = re.compile(
            rf"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+{SOURCE_TABLE}\b",
            re.IGNORECASE)
        for call in conn.execute.call_args_list:
            assert not write.search(str(call[0][0]))

    def test_source_appears_only_in_a_from_clause(self):
        eng, conn = _archive_engine(rowcount=1)
        archive_current_snapshot(eng, dry_run=False)
        sql = next(str(c[0][0]) for c in conn.execute.call_args_list
                   if "INSERT" in str(c[0][0]))
        # כל הופעה של השם המדויק חייבת לבוא אחרי FROM
        for m in re.finditer(rf"\b{SOURCE_TABLE}\b(?!_)", sql):
            assert re.search(r"FROM\s+$", sql[:m.start()])

    def test_rows_without_a_strike_are_excluded(self):
        eng, conn = _archive_engine(rowcount=1)
        archive_current_snapshot(eng, dry_run=False)
        sql = next(str(c[0][0]) for c in conn.execute.call_args_list
                   if "INSERT" in str(c[0][0]))
        assert "IS NOT NULL" in sql

    def test_no_engine_is_reported(self):
        r = archive_current_snapshot(None, dry_run=False)
        assert r["status"] == "skipped"
        assert r["reason"]
