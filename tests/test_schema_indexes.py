"""Wave 2/4 — foreign-key columns are indexed, and integrity holds.

Guards against the DB-review finding (unindexed FKs → full scans + slow cascades).
Asserts the indexes exist on a freshly initialised DB, that the query planner uses
one for an equality lookup, and that PRAGMA foreign_key_check is clean.
"""

from __future__ import annotations

import pytest

_FK_INDEXES = [
    "ix_receipts_patient",
    "ix_receipts_doctor",
    "ix_cultures_item",
    "ix_cultsens_culture",
    "ix_panel_items_test",
]


def _index_names(con):
    return {
        r["name"]
        for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }


@pytest.mark.parametrize("ix", _FK_INDEXES)
def test_fk_index_exists(con, ix):
    assert ix in _index_names(con)


def test_culture_lookup_uses_index_not_scan(con):
    plan = con.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM cultures WHERE receipt_item_id=?", (1,)
    ).fetchall()
    detail = " ".join(str(row["detail"]) for row in plan)
    assert "USING INDEX" in detail
    assert "SCAN cultures" not in detail


def test_foreign_key_check_is_clean(con):
    violations = con.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
