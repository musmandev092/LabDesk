"""GUI-level end-to-end use cases against the REAL Qt pages, driven headlessly via
the offscreen platform, printing to a virtual A4 PDF printer.

These exercise the widget construction + signal-handler code the unit tests can't:
a receptionist creating a bill, printing a receipt and a report to A4, and the
void authorization being enforced at the page level (admin yes, receptionist no).

Skipped automatically if a Qt platform can't be created (e.g. no offscreen plugin).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as e:  # pragma: no cover
        pytest.skip(f"PySide6 unavailable: {e}")
    app = QApplication.instance() or QApplication(["labdesk-tests"])
    try:
        from labdesk import render

        render.preload()  # fonts must load on the main/GUI thread, once
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Qt platform unavailable: {e}")
    return app


def _a4_pdf_printer(path):
    from PySide6.QtGui import QPageSize
    from PySide6.QtPrintSupport import QPrinter

    p = QPrinter(QPrinter.HighResolution)
    p.setOutputFormat(QPrinter.PdfFormat)
    p.setPageSize(QPageSize(QPageSize.A4))
    p.setFullPage(True)
    p.setOutputFileName(str(path))
    return p


@pytest.fixture
def configured_con(con, db):
    db.set_setting(con, "lab_name", "Test Diagnostic Lab")
    db.set_setting(con, "configured", "1")
    return con


@pytest.fixture
def admin(configured_con):
    return configured_con.execute(
        "SELECT * FROM users WHERE username='admin'"
    ).fetchone()


def _make_receptionist(con):
    h = "scrypt$x"  # not used for login in these tests
    con.execute(
        "INSERT INTO users(username,full_name,pass_hash,salt,role,active) "
        "VALUES('rita','Rita',?, '', 'receptionist', 1)",
        (h,),
    )
    con.commit()
    return con.execute("SELECT * FROM users WHERE username='rita'").fetchone()


def _create_receipt_via_reception(con, user, qapp):
    """Drive the REAL ReceptionPage to create a bill, like a user would."""
    from labdesk.presentation.reception import ReceptionPage

    test = con.execute(
        "SELECT id,name,charges FROM tests WHERE charges>0 LIMIT 1"
    ).fetchone()
    page = ReceptionPage(con, user)
    page.name.setText("John A. Patient")
    page.age.setValue(35)
    page.cart.append(
        {"test_id": test["id"], "name": test["name"], "charge": test["charges"]}
    )
    page.paid.setValue(float(test["charges"]))
    page.save(do_print=False)
    return con.execute(
        "SELECT * FROM receipts ORDER BY id DESC LIMIT 1"
    ).fetchone(), test


def test_reception_page_creates_a_receipt(qapp, configured_con, admin):
    rec, _ = _create_receipt_via_reception(configured_con, admin, qapp)
    assert rec is not None
    assert rec["lab_no"], "a lab number must be allocated"
    assert rec["net_amount"] > 0


def test_print_receipt_to_a4_pdf(qapp, configured_con, admin, data_dir):
    rec, _ = _create_receipt_via_reception(configured_con, admin, qapp)
    from labdesk import render

    out = data_dir / "receipt.pdf"
    printer = _a4_pdf_printer(out)
    render.build_receipt(configured_con, rec["id"], device=printer)
    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"
    assert out.stat().st_size > 1000
    from PySide6.QtGui import QPageSize

    assert printer.pageLayout().pageSize().id() == QPageSize.A4


def test_print_report_to_a4_pdf(qapp, configured_con, admin, data_dir):
    rec, test = _create_receipt_via_reception(configured_con, admin, qapp)
    # make the report "ready": add a result row + mark reported
    param = configured_con.execute(
        "SELECT id FROM test_parameters WHERE test_id=? LIMIT 1", (test["id"],)
    ).fetchone()
    if param:
        configured_con.execute(
            "INSERT INTO results(receipt_id,test_id,parameter_id,value) VALUES (?,?,?,?)",
            (rec["id"], test["id"], param["id"], "12.3"),
        )
    configured_con.execute(
        "UPDATE receipts SET status='reported', reported_at=datetime('now') WHERE id=?",
        (rec["id"],),
    )
    configured_con.commit()
    from labdesk import render

    out = data_dir / "report.pdf"
    render.build_report(configured_con, rec["id"], device=_a4_pdf_printer(out))
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"
    assert out.stat().st_size > 1000


def test_admin_can_void_via_receipts_page(qapp, configured_con, admin, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from labdesk.presentation.receipts import ReceiptsPage

    rec, _ = _create_receipt_via_reception(configured_con, admin, qapp)
    # auto-confirm the void dialogs (reason + Yes/No)
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *a, **k: ("duplicate", True))
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
    )
    page = ReceiptsPage(configured_con, admin)
    page.refresh()
    for i in range(page.table.rowCount()):
        if page._ids[i] == rec["id"]:
            page.table.setCurrentCell(i, 0)
            break
    page.void_receipt()
    voided = configured_con.execute(
        "SELECT voided FROM receipts WHERE id=?", (rec["id"],)
    ).fetchone()[0]
    assert voided == 1


def test_receptionist_cannot_void_at_page_level(qapp, configured_con, monkeypatch):
    """The receptionist's Receipts page must not expose voiding, and calling the
    handler is a no-op (UI gate) — defence-in-depth alongside the service check."""
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from labdesk.presentation.receipts import ReceiptsPage

    admin = configured_con.execute(
        "SELECT * FROM users WHERE username='admin'"
    ).fetchone()
    rec, _ = _create_receipt_via_reception(configured_con, admin, qapp)
    rita = _make_receptionist(configured_con)

    # if the handler somehow proceeded, these would auto-confirm — so a no-op proves the gate
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *a, **k: ("x", True))
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
    )
    page = ReceiptsPage(configured_con, rita)
    page.refresh()
    for i in range(page.table.rowCount()):
        if page._ids[i] == rec["id"]:
            page.table.setCurrentCell(i, 0)
            break
    page.void_receipt()  # gated by can(role,'delete') → returns without voiding
    voided = configured_con.execute(
        "SELECT voided FROM receipts WHERE id=?", (rec["id"],)
    ).fetchone()[0]
    assert voided == 0
