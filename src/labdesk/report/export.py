"""Native PDF bytes (QPainter → QPdfWriter via :mod:`..render`), file exports and printing."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from .. import db, render


def _pdf_target(path: str) -> Path:
    """Expand ~ and force a .pdf suffix on a caller-supplied export path."""
    p = Path(path).expanduser()
    if p.suffix.lower() != ".pdf":
        p = p.with_suffix(".pdf")
    return p


def export_report_pdf(con, receipt_id: int, path: str, pack: bool = True) -> None:
    _pdf_target(path).write_bytes(
        cast(bytes, render.build_report(con, receipt_id, pack=pack))
    )


def export_receipt_pdf(con, receipt_id: int, path: str) -> None:
    _pdf_target(path).write_bytes(cast(bytes, render.build_receipt(con, receipt_id)))


def build_report_bytes(con, receipt_id: int, pack: bool = True) -> bytes:
    return cast(bytes, render.build_report(con, receipt_id, pack=pack))


def build_receipt_bytes(con, receipt_id: int) -> bytes:
    return cast(bytes, render.build_receipt(con, receipt_id))


def build_test_page_bytes(printer_name: str = "") -> bytes:
    """A small printer-test page, as PDF bytes."""
    return cast(bytes, render.build_test_page(printer_name))


def _make_printer(parent, title, printer_name):
    """Build a QPrinter for the default printer, or show the print dialog; None if cancelled."""
    from PySide6.QtGui import QPageSize
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo

    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageSize(QPageSize(QPageSize.A4))
    printer.setFullPage(True)
    if printer_name and printer_name in QPrinterInfo.availablePrinterNames():
        printer.setPrinterName(printer_name)
        return printer
    dlg = QPrintDialog(printer, parent)
    dlg.setWindowTitle(title)
    return printer if dlg.exec() else None


def print_doc(
    con,
    receipt_id,
    kind,
    parent,
    title,
    printer_name="",
    letterhead=True,
    pack: bool = True,
) -> None:
    """Paint a document straight onto the chosen printer (vector output); must run on the UI thread."""
    printer = _make_printer(parent, title, printer_name)
    if printer is None:
        return
    if kind == "testpage":
        render.build_test_page(printer_name, device=printer)
    elif kind == "receipt":
        render.build_receipt(con, receipt_id, device=printer)
    else:
        render.build_report(
            con, receipt_id, device=printer, letterhead=letterhead, pack=pack
        )


def print_report(con, receipt_id: int, parent=None, pack: bool = True) -> None:
    print_doc(
        con,
        receipt_id,
        "report",
        parent,
        "Print Report",
        db.get_setting(con, "default_printer", ""),
        pack=pack,
    )


def print_receipt(con, receipt_id: int, parent=None) -> None:
    print_doc(
        con,
        receipt_id,
        "receipt",
        parent,
        "Print Receipt",
        db.get_setting(con, "default_printer", ""),
    )


def print_test_page(parent=None, printer_name: str = "") -> None:
    """Print a small test page to verify the printer works (synchronous)."""
    print_doc(None, None, "testpage", parent, "Print Test Page", printer_name)


def save_report_pdf(con, receipt_id: int, parent=None, pack: bool = True) -> str | None:
    from PySide6.QtWidgets import QFileDialog

    r = con.execute("SELECT lab_no FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    default = f"{(r['lab_no'] if r else 'report')}.pdf"
    path, _ = QFileDialog.getSaveFileName(
        parent, "Save report PDF", default, "PDF (*.pdf)"
    )
    if path:
        export_report_pdf(con, receipt_id, path, pack=pack)
        return path
    return None
