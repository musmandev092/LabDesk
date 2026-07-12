"""Output: native PDF bytes (QPainter → QPdfWriter via :mod:`..render`),
file exports and printing.

Imports :mod:`..render` and :mod:`..db`.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from .. import db, render


# ---------------------------------------------------------------------------
# Output — native Qt PDF (QPainter → QPdfWriter) + raster-to-printer
# ---------------------------------------------------------------------------
def _pdf_target(path: str) -> Path:
    """Normalise a caller-supplied export path: expand ~ and force a .pdf suffix
    so an export can't be coerced into writing a different file type."""
    p = Path(path).expanduser()
    if p.suffix.lower() != ".pdf":
        p = p.with_suffix(".pdf")
    return p


def export_report_pdf(con, receipt_id: int, path: str, pack: bool = True) -> None:
    # build_* is polymorphic on device/images; the default path always returns bytes.
    _pdf_target(path).write_bytes(
        cast(bytes, render.build_report(con, receipt_id, pack=pack))
    )


def export_receipt_pdf(con, receipt_id: int, path: str) -> None:
    _pdf_target(path).write_bytes(cast(bytes, render.build_receipt(con, receipt_id)))


# Build the PDF bytes natively (QPainter → QPdfWriter). Safe to run on a
# background thread (see ui/tasks.py); the bytes are printed/previewed on the UI
# thread. QPainter/QPdfWriter do not require the GUI thread.
def build_report_bytes(con, receipt_id: int, pack: bool = True) -> bytes:
    return cast(bytes, render.build_report(con, receipt_id, pack=pack))


def build_receipt_bytes(con, receipt_id: int) -> bytes:
    return cast(bytes, render.build_receipt(con, receipt_id))


def build_test_page_bytes(printer_name: str = "") -> bytes:
    """A small printer-test page, as PDF bytes."""
    return cast(bytes, render.build_test_page(printer_name))


def _make_printer(parent, title, printer_name):
    """Build a QPrinter: send to the configured default if it still exists, else
    show the print dialog. Returns None if the user cancels."""
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
    """Render a document straight onto the chosen printer — vector output, no
    QtPdf round-trip and no patient-PII temp file. MUST run on the UI thread
    (QPrinter/QPainter are not thread-safe); native rendering is fast (~tens of
    ms) so it is synchronous. Choosing 'Print to File (PDF)' in the dialog makes
    the printer emit a PDF directly — handled for free by painting onto it."""
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
