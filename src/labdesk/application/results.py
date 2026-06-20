"""Clinical result + culture release (no Qt).

The worklist and microbiology views read their widgets and resolve reference
ranges, then hand plain data here. These functions enforce authorization
(``require("finalize_results")``) and perform the multi-table write + audit in one
transaction — so releasing a clinical report can't be done by a role that lacks the
capability regardless of which code path reaches it (defence-in-depth).
"""

from __future__ import annotations

import contextlib

from .. import db
from ..db import sqlite3
from ..roles import require


def release_results(
    con: sqlite3.Connection,
    *,
    receipt_id: int,
    result_rows: list[dict[str, object]],
    remarks: dict[int, str],
    static_rows: list[dict[str, object]],
    actor_username: str,
    actor_role: str,
    conclusion: dict[int, str] | None = None,
) -> str:
    """Persist entered results + remarks + static report lines and stamp the receipt
    'reported' (on first finalisation), then audit. Returns the lab number.

    ``result_rows`` carry resolved metadata (``item_id, parameter_id, seq, part_type,
    group_head, name, units, superscript, ref_text, value, hidden``); a ``None``
    ``parameter_id`` is a single-line free result. ``static_rows`` are no-editor
    H/L/continuation lines inserted only if absent. ``conclusion`` maps item_id →
    impression/interpretation text (imaging/molecular/serology), stored on
    receipt_items.conclusion and printed as a block below the table. On failure the
    whole write rolls back and re-raises so the view can report nothing was saved."""
    require(actor_role, "finalize_results")
    try:
        for row in result_rows:
            if row["parameter_id"] is None:
                con.execute(
                    "DELETE FROM results WHERE receipt_item_id=? AND parameter_id IS NULL",
                    (row["item_id"],),
                )
                con.execute(
                    "INSERT INTO results"
                    "(receipt_item_id,parameter_id,seq,part_type,name,value,hidden)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        row["item_id"],
                        None,
                        0,
                        "N",
                        "Result",
                        row["value"],
                        row["hidden"],
                    ),
                )
                continue
            con.execute(
                """INSERT INTO results
                   (receipt_item_id,parameter_id,seq,part_type,group_head,name,units,
                    superscript,ref_text,value,hidden)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(receipt_item_id,parameter_id) DO UPDATE SET
                     value=excluded.value, ref_text=excluded.ref_text,
                     hidden=excluded.hidden""",
                (
                    row["item_id"],
                    row["parameter_id"],
                    row["seq"],
                    row["part_type"],
                    row["group_head"],
                    row["name"],
                    row["units"],
                    row["superscript"],
                    row["ref_text"],
                    row["value"],
                    row["hidden"],
                ),
            )
        for item_id, txt in remarks.items():
            con.execute(
                "UPDATE receipt_items SET remarks=? WHERE id=?", (txt or None, item_id)
            )
        for item_id, txt in (conclusion or {}).items():
            con.execute(
                "UPDATE receipt_items SET conclusion=? WHERE id=?",
                (txt or None, item_id),
            )
        for row in static_rows:
            con.execute(
                """INSERT OR IGNORE INTO results
                   (receipt_item_id,parameter_id,seq,part_type,group_head,name,
                    units,superscript,ref_text,value)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["item_id"],
                    row["parameter_id"],
                    row["seq"],
                    row["part_type"],
                    row["group_head"],
                    row["name"],
                    row["units"],
                    row["superscript"],
                    row["ref_text"],
                    None,
                ),
            )
        con.execute(
            "UPDATE receipts SET status='reported', "
            "reported_at=datetime('now','localtime') "
            "WHERE id=? AND status IN ('pending','in_progress')",
            (receipt_id,),
        )
        con.commit()
    except Exception:
        with contextlib.suppress(Exception):
            con.rollback()
        raise
    lab_no = con.execute(
        "SELECT lab_no FROM receipts WHERE id=?", (receipt_id,)
    ).fetchone()[0]
    db.log_audit(con, actor_username, "results_saved", f"{lab_no or receipt_id}")
    return lab_no or str(receipt_id)


def save_culture(
    con: sqlite3.Connection,
    *,
    item_id: int,
    culture: dict[str, str],
    sensitivities: list[tuple[str, str]],
    actor_username: str,
    actor_role: str,
) -> str:
    """Replace the culture + sensitivities for a receipt item, mark it reported, stamp
    the receipt 'reported' on first finalisation, then audit. Returns an audit detail
    string (lab_no — test_name). ``culture`` carries specimen/growth/organism/
    colony_count/gram_stain/zn_stain/remarks; ``sensitivities`` is (antibiotic, result)
    pairs (blank antibiotics are skipped)."""
    require(actor_role, "finalize_results")
    try:
        con.execute("DELETE FROM cultures WHERE receipt_item_id=?", (item_id,))
        cid = con.execute(
            """INSERT INTO cultures
               (receipt_item_id,specimen,growth,organism,colony_count,gram_stain,
                zn_stain,remarks,reported_at)
               VALUES (?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (
                item_id,
                culture["specimen"],
                culture["growth"],
                culture["organism"],
                culture["colony_count"],
                culture["gram_stain"],
                culture["zn_stain"],
                culture["remarks"],
            ),
        ).lastrowid
        for ab, res in sensitivities:
            if ab:
                con.execute(
                    "INSERT INTO culture_sensitivity(culture_id,antibiotic,result) "
                    "VALUES (?,?,?)",
                    (cid, ab, res),
                )
        con.execute(
            "UPDATE receipt_items SET reported=1, "
            "reported_at=datetime('now','localtime') WHERE id=?",
            (item_id,),
        )
        con.execute(
            "UPDATE receipts SET status='reported', "
            "reported_at=datetime('now','localtime') "
            "WHERE id=(SELECT receipt_id FROM receipt_items WHERE id=?) "
            "AND status IN ('pending','in_progress')",
            (item_id,),
        )
        con.commit()
    except Exception:
        with contextlib.suppress(Exception):
            con.rollback()
        raise
    info = con.execute(
        "SELECT r.lab_no, ri.test_name FROM receipt_items ri "
        "JOIN receipts r ON r.id=ri.receipt_id WHERE ri.id=?",
        (item_id,),
    ).fetchone()
    detail = f"{info['lab_no']} — {info['test_name']}" if info else f"item {item_id}"
    db.log_audit(con, actor_username, "culture_saved", detail)
    return detail
