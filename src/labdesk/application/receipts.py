"""Receipt DB-mutation helpers (no Qt) — the writes + audit behind the Receipts view."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from .. import db
from ..db import sqlite3
from ..roles import require


@dataclass
class BillDraft:
    """A validated bill's fields. Truthy existing_patient_id => returning patient."""

    existing_patient_id: int | None
    title: str
    mr_no: str
    name: str
    age: int
    age_desc: str
    sex: str
    telephone: str
    address: str
    wa_optout: int
    doctor_id: int | None
    doctor_name: str
    specimen: str
    items: list[dict[str, object]]
    subtotal: float
    discount_pct: float
    net: float
    paid: float
    due: float
    payment_method: str
    discount_approved_by: str | None
    promo_pct: float


@dataclass
class CreateReceiptResult:
    """Outcome of a successful bill creation."""

    receipt_id: int
    lab_no: str
    new_patient: bool


def _upsert_patient(
    con: sqlite3.Connection, d: BillDraft, consent_at: str
) -> tuple[int, str, bool]:
    """Insert or refresh the patient row. Returns (patient_id, mr_no, new_patient)."""
    pid = d.existing_patient_id
    mr_no = d.mr_no
    if pid:  # returning patient -> reuse row + permanent MR, refresh details
        row = con.execute("SELECT mr_no FROM patients WHERE id=?", (pid,)).fetchone()
        # prefer the stored permanent MR: don't let a typed value overwrite the
        # canonical id of an auto-matched returning patient
        stored = (row["mr_no"] if row else "") or ""
        mr_no = stored or mr_no or db.format_patient_id(pid)
        con.execute(
            "UPDATE patients SET title=?,name=?,age=?,age_desc=?,sex=?,telephone=?,"
            "address=?,mr_no=?,wa_optout=?,wa_consent_at=? WHERE id=?",
            (
                d.title,
                d.name,
                d.age,
                d.age_desc,
                d.sex,
                d.telephone,
                d.address,
                mr_no,
                d.wa_optout,
                consent_at,
                pid,
            ),
        )
        return pid, mr_no, False
    pid = con.execute(
        "INSERT INTO patients(title,mr_no,name,age,age_desc,sex,telephone,address,"
        "wa_optout,wa_consent_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            d.title,
            mr_no,
            d.name,
            d.age,
            d.age_desc,
            d.sex,
            d.telephone,
            d.address,
            d.wa_optout,
            consent_at,
        ),
    ).lastrowid
    if not mr_no:
        mr_no = db.format_patient_id(pid)
        con.execute("UPDATE patients SET mr_no=? WHERE id=?", (mr_no, pid))
    return pid, mr_no, True


def _allocate_lab_no(
    con: sqlite3.Connection, prefix: str, datestr: str, receipt_id: int
) -> str:
    """Assign a unique lab number, based on today's highest minted serial (not
    COUNT(*), which would regress on deletion); bumps on the UNIQUE guard on collision."""
    serial_prefix = f"{prefix}-{datestr}-"
    like = (
        serial_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        + "%"
    )
    top = con.execute(
        "SELECT MAX(CAST(substr(lab_no, ?) AS INTEGER)) FROM receipts "
        "WHERE lab_no LIKE ? ESCAPE '\\'",
        (len(serial_prefix) + 1, like),
    ).fetchone()[0]
    base = (top or 0) + 1
    for bump in range(500):
        cand = f"{prefix}-{datestr}-{base + bump:03d}"
        try:
            con.execute(
                "UPDATE receipts SET lab_no=?, case_no=? WHERE id=?",
                (cand, cand, receipt_id),
            )
            return cand
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("could not allocate a unique lab number")


def create_receipt(
    con: sqlite3.Connection, draft: BillDraft, *, actor_username: str, actor_role: str
) -> CreateReceiptResult:
    """Create a bill in one transaction: upsert patient, insert receipt+items+ledger,
    allocate a lab number, audit. Authorized here (defence-in-depth). Rolls back and
    re-raises on any DB failure."""
    require(actor_role, "create_receipt")
    d = draft
    prefix = db.get_setting(con, "lab_no_prefix", "LAB")
    datestr = con.execute("SELECT strftime('%Y%m%d','now','localtime')").fetchone()[0]
    consent_at = con.execute("SELECT datetime('now','localtime')").fetchone()[0]
    try:
        pid, mr_no, new_patient = _upsert_patient(con, d, consent_at)
        # money dual-written: REAL columns + integer-paisa twins (CAST(ROUND(?*100)))
        rid = con.execute(
            """INSERT INTO receipts
               (patient_id,doctor_id,title,mr_no,patient_name,age,age_desc,sex,
                telephone,address,dr_name,specimen,subtotal,discount_pct,less,
                net_amount,paid,due,payment_method,status,created_by,received_at,
                subtotal_paisa,less_paisa,net_amount_paisa,paid_paisa,due_paisa)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                       datetime('now','localtime'),
                       CAST(ROUND(?*100) AS INTEGER),CAST(ROUND(?*100) AS INTEGER),
                       CAST(ROUND(?*100) AS INTEGER),CAST(ROUND(?*100) AS INTEGER),
                       CAST(ROUND(?*100) AS INTEGER))""",
            (
                pid,
                d.doctor_id,
                d.title,
                mr_no,
                d.name,
                d.age,
                d.age_desc,
                d.sex,
                d.telephone,
                d.address,
                d.doctor_name,
                d.specimen,
                d.subtotal,
                d.discount_pct,
                0,
                d.net,
                d.paid,
                d.due,
                d.payment_method,
                "pending",
                actor_username,
                d.subtotal,
                0,
                d.net,
                d.paid,
                d.due,
            ),
        ).lastrowid
        lab_no = _allocate_lab_no(con, prefix, datestr, rid)
        for item in d.items:
            con.execute(
                "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge,charge_paisa) "
                "VALUES (?,?,?,?,CAST(ROUND(?*100) AS INTEGER))",
                (rid, item["test_id"], item["name"], item["charge"], item["charge"]),
            )
        # income capped at the bill; over-payment is change returned, not revenue
        collected = min(d.paid, d.net)
        if collected:
            con.execute(
                "INSERT INTO ledger(kind,ref_id,detail,credit,credit_paisa,date) "
                "VALUES ('income',?,?,?,CAST(ROUND(?*100) AS INTEGER),"
                "date('now','localtime'))",
                (rid, f"Receipt {lab_no} — {d.name}", collected, collected),
            )
        con.commit()
    except (sqlite3.Error, RuntimeError):
        with contextlib.suppress(Exception):
            con.rollback()
        raise
    db.log_audit(
        con,
        actor_username,
        "patient_created" if new_patient else "patient_updated",
        f"{d.name} ({mr_no})",
    )
    db.log_audit(
        con,
        actor_username,
        "receipt_created",
        f"{lab_no} — {d.name}, net {d.net:.0f}, paid {d.paid:.0f}, due {d.due:.0f}",
    )
    if d.discount_pct > 0:
        who = d.discount_approved_by or (
            "promo" if d.discount_pct <= d.promo_pct + 1e-9 else actor_username
        )
        db.log_audit(
            con,
            actor_username,
            "discount_approved",
            f"{d.discount_pct:g}% on {lab_no} (by {who})",
        )
    return CreateReceiptResult(receipt_id=rid, lab_no=lab_no, new_patient=new_patient)


def void_receipt(
    con: sqlite3.Connection,
    receipt_id: int,
    reason: str,
    username: str,
    *,
    actor_role: str,
) -> None:
    """Void a receipt: mark voided, zero its due, reverse the ledger if paid, audit.
    Idempotent — a no-op if already voided, so a double-void can't double-reverse."""
    require(actor_role, "void_receipt")
    r = con.execute(
        "SELECT lab_no, paid, net_amount, voided FROM receipts WHERE id=?",
        (receipt_id,),
    ).fetchone()
    if r is None or r["voided"]:
        return
    con.execute(
        "UPDATE receipts SET voided=1, void_reason=?, voided_at=datetime('now','localtime'), "
        "voided_by=?, due=0, due_paisa=0 WHERE id=?",
        (reason, username, receipt_id),
    )
    # reverse exactly what was booked as income, not the raw tendered amount
    collected = min(r["paid"] or 0.0, r["net_amount"] or 0.0)
    if collected:
        con.execute(
            "INSERT INTO ledger(kind,ref_id,detail,debit,debit_paisa,date) "
            "VALUES ('void',?,?,?,CAST(ROUND(?*100) AS INTEGER),date('now','localtime'))",
            (receipt_id, f"Void {r['lab_no']} — {reason[:60]}", collected, collected),
        )
    con.commit()
    db.log_audit(
        con,
        username,
        "receipt_voided",
        f"{r['lab_no']} — {reason[:80]}",
    )


def mark_receipt_delivered(
    con: sqlite3.Connection, receipt_id: int, username: str, *, actor_role: str
) -> None:
    """Mark a receipt's report as delivered + audit."""
    require(actor_role, "deliver_report")
    r = con.execute("SELECT lab_no FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    con.execute(
        "UPDATE receipts SET status='delivered', delivered_at=datetime('now','localtime'), "
        "delivered_by=? WHERE id=?",
        (username, receipt_id),
    )
    con.commit()
    db.log_audit(con, username, "report_delivered", r["lab_no"] or f"#{receipt_id}")
