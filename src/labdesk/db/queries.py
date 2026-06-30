"""Domain queries: test panels/profiles, due payments, and the parameter editor."""

from __future__ import annotations

import contextlib

from ..roles import require
from ._driver import sqlite3
from .audit import log_audit
from .settings import currency


# ---- test panels / profiles -------------------------------------------------
def list_panels(con: sqlite3.Connection, include_inactive: bool = False):
    """Named test bundles (e.g. "Fever Profile"), newest-friendly alphabetical."""
    q = "SELECT * FROM panels"
    if not include_inactive:
        q += " WHERE active=1"
    q += " ORDER BY name COLLATE NOCASE"
    return con.execute(q).fetchall()


def panel_tests(con: sqlite3.Connection, panel_id: int):
    """The tests in a panel (only ones that still exist), alphabetical."""
    return con.execute(
        "SELECT t.id, t.name, t.charges FROM panel_items pi "
        "JOIN tests t ON t.id = pi.test_id "
        "WHERE pi.panel_id=? ORDER BY t.name COLLATE NOCASE",
        (panel_id,),
    ).fetchall()


def save_panel(
    con: sqlite3.Connection,
    name: str,
    test_ids,
    panel_id: int | None = None,
    *,
    actor_role: str,
    username: str,
) -> int:
    """Create or update a panel and its member tests in one transaction. Authorized
    and AUDITED here (not in the caller) so a privileged catalog write always leaves a
    trail regardless of which UI path reaches it."""
    require(actor_role, "edit_catalog")
    name = (name or "").strip()
    if not name:
        raise ValueError("panel name is required")
    ids = [int(t) for t in test_ids]
    is_update = panel_id is not None
    if panel_id is None:
        panel_id = con.execute(
            "INSERT INTO panels(name, active) VALUES (?,1)", (name,)
        ).lastrowid
        if panel_id is None:
            raise RuntimeError("failed to create panel")
    else:
        con.execute("UPDATE panels SET name=?, active=1 WHERE id=?", (name, panel_id))
        con.execute("DELETE FROM panel_items WHERE panel_id=?", (panel_id,))
    for tid in ids:
        con.execute(
            "INSERT INTO panel_items(panel_id, test_id) VALUES (?,?)", (panel_id, tid)
        )
    con.commit()
    log_audit(
        con,
        username,
        "panel_updated" if is_update else "panel_created",
        f"{name} ({len(ids)} tests)",
    )
    return panel_id


def delete_panel(
    con: sqlite3.Connection, panel_id: int, *, actor_role: str, username: str
) -> None:
    """Soft-delete (retire) a panel; member rows go with it. Authorized + audited here."""
    require(actor_role, "edit_catalog")
    row = con.execute("SELECT name FROM panels WHERE id=?", (panel_id,)).fetchone()
    con.execute("UPDATE panels SET active=0 WHERE id=?", (panel_id,))
    con.execute("DELETE FROM panel_items WHERE panel_id=?", (panel_id,))
    con.commit()
    log_audit(con, username, "panel_deleted", (row["name"] if row else f"#{panel_id}"))


def receive_due(
    con: sqlite3.Connection,
    receipt_id: int,
    amount: float,
    username: str,
    *,
    actor_role: str,
):
    """Record a (partial) due payment on a receipt: ledger credit + updated
    paid/due, audited. Returns (lab_no, new_paid, new_due) or None if nothing
    is owed. Shared by the Receipts page and the Accounts dues tab."""
    require(actor_role, "receive_payment")
    r = con.execute(
        "SELECT lab_no, net_amount, paid, due FROM receipts WHERE id=?", (receipt_id,)
    ).fetchone()
    if not r or not r["due"] or r["due"] <= 0 or amount <= 0:
        return None
    new_paid = round((r["paid"] or 0) + amount, 2)
    new_due = round(max(0.0, (r["net_amount"] or 0) - new_paid), 2)
    con.execute(
        "INSERT INTO ledger(kind,ref_id,detail,credit,credit_paisa,date) "
        "VALUES ('due_recovery',?,?,?,CAST(ROUND(?*100) AS INTEGER),date('now','localtime'))",
        (receipt_id, f"Due recovered {r['lab_no']}", amount, amount),
    )
    con.execute(
        "UPDATE receipts SET paid=?, due=?, "
        "paid_paisa=CAST(ROUND(?*100) AS INTEGER), due_paisa=CAST(ROUND(?*100) AS INTEGER) "
        "WHERE id=?",
        (new_paid, new_due, new_paid, new_due, receipt_id),
    )
    con.commit()
    cur = currency(con)
    log_audit(
        con,
        username,
        "due_received",
        f"{r['lab_no']} — {cur} {amount:,.0f} (due now {cur} {new_due:,.0f})",
    )
    return (r["lab_no"], new_paid, new_due)


def income_between(con: sqlite3.Connection, from_date: str, to_date: str) -> float:
    """Period income from the LEDGER: cash actually booked (credits minus refund/void
    debits), dated by the EVENT date. Excludes expenses. This is correct across later
    due-recovery, bill edits and voids — unlike SUM(MIN(paid,net)) keyed on
    receipts.received_at, which retroactively mis-states already-closed months."""
    return con.execute(
        "SELECT COALESCE(SUM(COALESCE(credit,0)-COALESCE(debit,0)),0) FROM ledger "
        "WHERE COALESCE(kind,'')<>'expense' AND date(date) BETWEEN ? AND ?",
        (from_date, to_date),
    ).fetchone()[0]


def income_by_method(con: sqlite3.Connection, from_date: str, to_date: str):
    """Per-payment-method cash for the period, from the ledger joined to each
    referenced receipt's method. Same event-date basis as income_between()."""
    return con.execute(
        "SELECT COALESCE(NULLIF(TRIM(rc.payment_method),''),'Cash') AS m, "
        "COUNT(DISTINCT l.ref_id) AS n, "
        "COALESCE(SUM(COALESCE(l.credit,0)-COALESCE(l.debit,0)),0) AS total "
        "FROM ledger l LEFT JOIN receipts rc ON rc.id=l.ref_id "
        "WHERE COALESCE(l.kind,'')<>'expense' AND date(l.date) BETWEEN ? AND ? "
        "GROUP BY m HAVING total<>0 ORDER BY total DESC",
        (from_date, to_date),
    ).fetchall()


# ---- in-app parameter editor ------------------------------------------------
class ParameterInUseError(Exception):
    """Raised when the editor tries to remove a parameter that already has saved
    results on a patient report (deleting it would orphan that history)."""

    def __init__(self, names):
        self.names = list(names)
        super().__init__(
            "These parameters have saved patient results and can't be removed: "
            + ", ".join(self.names)
        )


def save_test_parameters(
    con: sqlite3.Connection, test_id: int, rows, *, actor_role: str, username: str
) -> None:
    """Persist the report-line definitions for a test from the in-app editor.

    Diff-based so existing parameter IDs (and any patient results referencing
    them) survive: existing rows are UPDATEd in place, new rows INSERTed, and
    rows the user removed are DELETEd — unless they already have saved results,
    in which case nothing is saved and ParameterInUseError is raised.

    Authorized + audited here so the privileged catalog edit always leaves a trail.
    """
    require(actor_role, "edit_catalog")
    rows = list(rows)
    old = con.execute(
        "SELECT id, name FROM test_parameters WHERE test_id=?", (test_id,)
    ).fetchall()
    old_ids = {r["id"]: (r["name"] or "") for r in old}
    keep = set()
    try:
        for seq, r in enumerate(rows):
            vals = (
                seq,
                (r.get("part_type") or "N"),
                r.get("name") or "",
                r.get("units") or "",
                r.get("ref_male") or "",
                r.get("ref_female") or "",
                r.get("default_result") or "",
                r.get("superscript") or "",
                r.get("group_head") or "",
            )
            pid = r.get("id")
            if pid and pid in old_ids:
                con.execute(
                    "UPDATE test_parameters SET seq=?,part_type=?,name=?,units=?,ref_male=?,"
                    "ref_female=?,default_result=?,superscript=?,group_head=? WHERE id=?",
                    (*vals, pid),
                )
                keep.add(pid)
            else:
                con.execute(
                    "INSERT INTO test_parameters(test_id,seq,part_type,name,units,ref_male,"
                    "ref_female,default_result,superscript,group_head) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (test_id, *vals),
                )
        in_use = []
        for pid, name in old_ids.items():
            if pid in keep:
                continue
            if con.execute(
                "SELECT 1 FROM results WHERE parameter_id=? LIMIT 1", (pid,)
            ).fetchone():
                in_use.append(name or f"#{pid}")
            else:
                con.execute("DELETE FROM test_parameters WHERE id=?", (pid,))
        if in_use:
            con.rollback()
            raise ParameterInUseError(in_use)
        con.commit()
        log_audit(
            con, username, "parameters_edited", f"test #{test_id} ({len(rows)} lines)"
        )
    except ParameterInUseError:
        raise
    except sqlite3.Error:
        with contextlib.suppress(Exception):
            con.rollback()
        raise
