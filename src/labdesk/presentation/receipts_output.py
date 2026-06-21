"""Receipt/report preview, print, WhatsApp, PDF export + verify — split out of ReceiptsPage.

A mixin (runs on the composed ReceiptsPage instance). Pure reorg, no behavior change.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
)

from .. import db, render, report
from . import tasks, wa
from .widgets import (
    toast_info,
    toast_warn,
)

# a report can be previewed/printed only once results are in
REPORT_READY = ("reported", "delivered")


from .receipt_dialogs import _PreviewDialog

REPORT_READY = ("reported", "delivered")


class ReceiptsOutputMixin:
    def _preview(self, kind: str) -> None:
        """kind: 'report' or 'receipt'. Render to image pages natively and show
        them in the preview dialog — no PDF temp file, no QtPdf viewer."""
        rid = self._selected_id()
        if rid is None:
            return
        title = "Receipt preview" if kind == "receipt" else "Report preview"
        labno = self._lab_no(rid)
        # Page rendering is synchronous on the UI thread; show a busy cursor so a
        # multi-page report doesn't look like a frozen window while it builds.
        from PySide6.QtWidgets import QApplication

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pages = render.render_pages(self.con, rid, kind)
        # deliberate UI safety net: any render failure surfaces as a message, not a crash
        except Exception as e:
            toast_warn(self, "Preview", f"Could not build preview:\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        db.log_audit(self.con, self.user["username"], "previewed_" + kind, labno)
        _PreviewDialog(pages, self, title).exec()

    def preview(self) -> None:
        self._preview("report")

    def preview_receipt(self) -> None:
        self._preview("receipt")

    def _send_whatsapp(self, kind: str) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        clicked = self.wa_rcpt_btn if kind == "receipt" else self.wa_rpt_btn
        # runs on a background thread; disables both WhatsApp buttons until done
        wa.send_async(
            self,
            self.con,
            kind,
            rid,
            clicked=clicked,
            lock_buttons=(self.wa_rcpt_btn, self.wa_rpt_btn),
            on_done=lambda ok, m: db.log_audit(
                self.con,
                self.user["username"],
                "whatsapp_" + kind,
                ("sent" if ok else "failed") + f" — receipt {rid}",
            ),
        )

    def whatsapp_receipt(self) -> None:
        self._send_whatsapp("receipt")

    def whatsapp_report(self) -> None:
        self._send_whatsapp("report")

    def _print(self, kind: str, letterhead: bool = True) -> None:
        """Render straight onto the printer (native, vector — no PDF round-trip).
        ``letterhead=False`` prints a 'plain' report (no clinic header/footer, content
        centred) for the lab's own pre-printed letterhead paper."""
        rid = self._selected_id()
        if rid is None:
            return
        if kind == "receipt":
            title = "Print Receipt"
        else:
            title = "Print Report (plain)" if not letterhead else "Print Report"
        printer = db.get_setting(self.con, "default_printer", "")
        labno = self._lab_no(rid)
        try:
            report.print_doc(
                self.con, rid, kind, self, title, printer, letterhead=letterhead
            )
            action = "printed_" + kind + ("" if letterhead else "_plain")
            db.log_audit(self.con, self.user["username"], action, labno)
        # deliberate UI safety net: any print failure surfaces as a message, not a crash
        except Exception as e:
            toast_warn(self, "Print", f"Could not print:\n{e}")

    def reprint(self) -> None:
        self._print("receipt")

    def print_report(self) -> None:
        self._print("report")

    def print_report_plain(self) -> None:
        """Admin-only: print the report with no letterhead/footer, centred — for the
        lab's own pre-printed letterhead pad."""
        self._print("report", letterhead=False)

    def verify_report(self) -> None:
        """Check the verification code printed on a report against our records.
        A value altered on a presented printout makes the recomputed code differ."""
        rid = self._selected_id()
        if rid is None:
            return
        labno = self._lab_no(rid)
        code, ok = QInputDialog.getText(
            self,
            "Verify report",
            f"Enter the verification code printed on report {labno}:",
        )
        if not ok or not code.strip():
            return
        match = report.verify(self.con, rid, code)
        db.log_audit(
            self.con,
            self.user["username"],
            "report_verified",
            f"{labno} — {'match' if match else 'MISMATCH'}",
        )
        r = self.con.execute(
            "SELECT patient_name, reported_at FROM receipts WHERE id=?", (rid,)
        ).fetchone()
        when = (r["reported_at"] or "")[:16] if r else ""
        who = r["patient_name"] if r else ""
        if match:
            toast_info(
                self,
                "Verify report",
                f"✓ Authentic.\n\n{labno} — {who}\nReported: {when}\n\n"
                "This code matches our records — the report has not been altered.",
            )
        else:
            toast_warn(
                self,
                "Verify report",
                f"✗ Does NOT match.\n\nThe code for {labno} does not match our records.\n"
                "Either the code was mistyped, or this printout does not match the "
                "report on file. Re-check carefully.",
            )

    def _save_pdf(self, kind: str) -> None:
        """Export the receipt or report to a PDF chosen by the user (background)."""
        rid = self._selected_id()
        if rid is None:
            return
        labno = self._lab_no(rid)
        stem = labno if not labno.startswith("#") else f"receipt_{rid}"
        default = f"{stem}-{kind}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {kind} PDF", default, "PDF (*.pdf)"
        )
        if not path:
            return
        export = (
            report.export_receipt_pdf if kind == "receipt" else report.export_report_pdf
        )
        clicked = self.pdf_rcpt_btn if kind == "receipt" else self.pdf_rpt_btn

        def done(ok: bool, result) -> None:
            if ok:
                db.log_audit(
                    self.con,
                    self.user["username"],
                    "exported_pdf",
                    f"{labno} {kind} → {path}",
                )
                toast_info(self, "PDF", f"Saved:\n{path}")
            else:
                toast_warn(self, "PDF", f"Could not save the PDF:\n{result}")

        tasks.run_in_background(
            self,
            lambda con: export(con, rid, path),
            done,
            clicked=clicked,
            busy_text="Saving…",
        )

    def save_receipt_pdf(self) -> None:
        self._save_pdf("receipt")

    def save_report_pdf(self) -> None:
        self._save_pdf("report")
