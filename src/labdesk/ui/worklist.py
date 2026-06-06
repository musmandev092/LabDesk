"""Worklist / Results: pick a receipt, enter results per parameter, print report."""
from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QPushButton, QHeaderView, QLabel, QScrollArea,
    QFrame, QGridLayout, QMessageBox, QCheckBox, QPlainTextEdit,
)

from PySide6.QtWidgets import QSizePolicy

from .widgets import h1, h2, muted, card, money, page_header
from . import wa, tasks
from .. import db, report


def resolve_ref(param_row, sex: str) -> str:
    """Pick the gender-appropriate reference range text."""
    male = param_row["ref_male"] or ""
    female = param_row["ref_female"] or ""
    if (sex or "").lower().startswith("f"):
        return female or male
    return male or female


class WorklistPage(QWidget):
    def __init__(self, con, user):
        super().__init__()
        self.con = con
        self.user = user
        self.current_receipt = None
        self._editors = {}   # (item_id, parameter_id) -> QLineEdit
        self._show = {}      # (item_id, parameter_id) -> QCheckBox (ticked = print this row)
        self._remarks = {}   # item_id -> QPlainTextEdit (per-test remarks)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header, _ = page_header("Worklist / Results", "Enter results and print reports")
        root.addWidget(header)

        top = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search patient / lab no…")
        self.search.setMinimumHeight(40)
        self.search.textChanged.connect(tasks.debounce(self, self.refresh_list))
        self.status_filter = QComboBox()
        self.status_filter.setMinimumHeight(40)
        for value, label in [("All", "All"), ("pending", "Pending"),
                             ("in_progress", "In Progress"), ("reported", "Reported"),
                             ("delivered", "Delivered")]:
            self.status_filter.addItem(label, value)
        self.status_filter.setCurrentIndex(1)  # Pending
        self.status_filter.currentIndexChanged.connect(self.refresh_list)
        top.addWidget(self.search, 1); top.addWidget(QLabel("Status:")); top.addWidget(self.status_filter)
        root.addLayout(top)

        split = QSplitter()
        split.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # left: receipts
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Lab No", "Patient", "Date", "Status"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)          # Patient grows
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Date readable
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_receipt)
        split.addWidget(self.table)

        # right: result entry
        right = QWidget(); rl = QVBoxLayout(right)
        self.header = h2("Select a receipt")
        rl.addWidget(self.header)
        self.empty_hint = muted("← Select a patient from the list to enter results.")
        rl.addWidget(self.empty_hint)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.entry_host = QWidget()
        self.entry_layout = QVBoxLayout(self.entry_host)
        self.entry_layout.addStretch(1)
        self.scroll.setWidget(self.entry_host)
        rl.addWidget(self.scroll, 1)

        btns = QHBoxLayout()
        self.save_btn = QPushButton("Save results"); self.save_btn.clicked.connect(self.save_results)
        self.print_btn = QPushButton("Print report"); self.print_btn.setObjectName("ghost")
        self.print_btn.clicked.connect(self.print_report)
        self.pdf_btn = QPushButton("Save PDF"); self.pdf_btn.setObjectName("ghost")
        self.pdf_btn.clicked.connect(self.save_pdf)
        self.wa_btn = QPushButton("Send WhatsApp"); self.wa_btn.setObjectName("ghost")
        self.wa_btn.clicked.connect(self.send_whatsapp)
        for b in (self.save_btn, self.print_btn, self.pdf_btn, self.wa_btn):
            b.setEnabled(False)
        btns.addStretch(1)
        btns.addWidget(self.wa_btn); btns.addWidget(self.pdf_btn)
        btns.addWidget(self.print_btn); btns.addWidget(self.save_btn)
        rl.addLayout(btns)
        split.addWidget(right)
        split.setSizes([430, 650])
        root.addWidget(split, 1)

        # ESC clears the selection / right panel; clicking empty list area too
        sc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.clear_selection)
        self.table.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.table.viewport() and event.type() == QEvent.MouseButtonPress:
            if not self.table.indexAt(event.position().toPoint()).isValid():
                self.clear_selection()
        return super().eventFilter(obj, event)

    def clear_selection(self):
        """Deselect the current receipt and reset the right-hand panel."""
        self.current_receipt = None
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.header.setText("Select a receipt")
        self.empty_hint.show()
        while self.entry_layout.count():
            it = self.entry_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None); w.deleteLater()
        self.entry_layout.addStretch(1)
        self._editors = {}; self._show = {}; self._remarks = {}
        for b in (self.save_btn, self.print_btn, self.pdf_btn, self.wa_btn):
            b.setEnabled(False)

    # ---------------------------------------------------------------
    def on_show(self):
        self.refresh_list()

    def refresh_list(self):
        q = f"%{self.search.text().strip()}%"
        st = self.status_filter.currentData() or "All"
        sql = ("SELECT * FROM receipts WHERE (patient_name LIKE ? OR lab_no LIKE ?)")
        args = [q, q]
        if st != "All":
            sql += " AND status=?"; args.append(st)
        sql += " ORDER BY id DESC LIMIT 500"
        rows = self.con.execute(sql, args).fetchall()
        self.table.setRowCount(0)
        self._ids = []
        for r in rows:
            i = self.table.rowCount(); self.table.insertRow(i)
            self._ids.append(r["id"])
            self.table.setItem(i, 0, QTableWidgetItem(r["lab_no"] or ""))
            self.table.setItem(i, 1, QTableWidgetItem(r["patient_name"] or ""))
            self.table.setItem(i, 2, QTableWidgetItem((r["received_at"] or "")[:16]))
            st_item = QTableWidgetItem((r["status"] or "").title())
            colors = {"pending": "#b9770e", "in_progress": "#0e7c86",
                      "reported": "#1f9d55", "delivered": "#6b7280"}
            col = colors.get(r["status"] or "")
            if col:
                st_item.setForeground(QColor(col))
                f = st_item.font(); f.setBold(True); st_item.setFont(f)
            self.table.setItem(i, 3, st_item)

    def _selected_id(self):
        r = self.table.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    # ---------------------------------------------------------------
    def load_receipt(self):
        rid = self._selected_id()
        if rid is None:
            return
        self.current_receipt = rid
        r = self.con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
        self.header.setText(f"{r['lab_no']} — {r['patient_name']} ({r['sex']}, {r['age']} {r['age_desc']})")
        self.empty_hint.hide()
        sex = r["sex"]

        # clear entry area synchronously (setParent(None) removes immediately —
        # deleteLater alone is async and can leave duplicates on rapid re-select)
        while self.entry_layout.count():
            it = self.entry_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._editors = {}; self._show = {}; self._remarks = {}

        items = self.con.execute(
            "SELECT ri.*, t.is_culture FROM receipt_items ri JOIN tests t ON t.id=ri.test_id "
            "WHERE ri.receipt_id=? ORDER BY ri.id", (rid,)
        ).fetchall()
        for it in items:
            if it["is_culture"]:
                self.entry_layout.addWidget(self._culture_note(it))
            else:
                self.entry_layout.addWidget(self._build_test_block(it, sex))
        self.entry_layout.addStretch(1)
        for b in (self.save_btn, self.print_btn, self.pdf_btn, self.wa_btn):
            b.setEnabled(True)

    def _culture_note(self, item):
        lbl = muted(
            f"“{item['test_name']}” is a culture & sensitivity test — "
            "enter its findings on the Microbiology screen.")
        lbl.setWordWrap(True)
        return card(lbl, title=item["test_name"])

    def _make_check(self):
        """A ticked 'show on report' checkbox for a parameter row."""
        cb = QCheckBox(); cb.setChecked(True)
        cb.setToolTip("Tick to print this line on the report; untick to hide it.")
        return cb

    def _build_test_block(self, item, sex):
        params = self.con.execute(
            "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq", (item["test_id"],)
        ).fetchall()
        # existing results keyed by parameter_id (value + hidden flag)
        existing, hidden = {}, {}
        for row in self.con.execute(
            "SELECT parameter_id, value, hidden FROM results WHERE receipt_item_id=?",
            (item["id"],),
        ):
            existing[row["parameter_id"]] = row["value"]
            hidden[row["parameter_id"]] = row["hidden"]
        had_results = bool(existing)  # first entry → everything ticked by default

        grid = QGridLayout(); grid.setSpacing(6)
        if not params:
            # single-line test: one free result box
            cb = self._make_check()
            cb.setChecked(not (had_results and hidden.get(None)))
            grid.addWidget(cb, 0, 0)
            grid.addWidget(QLabel("Result"), 0, 1)
            le = QLineEdit(); le.setText(existing.get(None, "") or "")
            grid.addWidget(le, 0, 2, 1, 3)
            self._editors[(item["id"], None)] = le
            self._show[(item["id"], None)] = cb
        else:
            grid.addWidget(QLabel("<b>Show</b>"), 0, 0)
            grid.addWidget(QLabel("<b>Parameter</b>"), 0, 1)
            grid.addWidget(QLabel("<b>Result</b>"), 0, 2)
            grid.addWidget(QLabel("<b>Unit</b>"), 0, 3)
            grid.addWidget(QLabel("<b>Reference</b>"), 0, 4)
            row_i = 1
            for p in params:
                pt = (p["part_type"] or "N").upper()
                ref = resolve_ref(p, sex)
                name = p["name"] or ""
                if pt == "H":
                    lbl = QLabel(f"<b>{name}</b>")
                    grid.addWidget(lbl, row_i, 0, 1, 5)
                    row_i += 1
                    continue
                if pt == "L" or not name:
                    # continuation / extra reference line — show ref only
                    grid.addWidget(QLabel(f"<i>{name}</i>"), row_i, 1)
                    grid.addWidget(QLabel(f"<span style='color:#555'>{ref}</span>"), row_i, 4)
                    row_i += 1
                    continue
                cb = self._make_check()
                cb.setChecked(not (had_results and hidden.get(p["id"])))
                grid.addWidget(cb, row_i, 0, Qt.AlignCenter)
                grid.addWidget(QLabel(name), row_i, 1)
                le = QLineEdit(); le.setText(existing.get(p["id"], "") or "")
                le.setMaximumWidth(160)
                grid.addWidget(le, row_i, 2)
                grid.addWidget(QLabel(p["units"] or ""), row_i, 3)
                grid.addWidget(QLabel(ref), row_i, 4)
                self._editors[(item["id"], p["id"])] = le
                self._show[(item["id"], p["id"])] = cb
                row_i += 1
        grid_host = QWidget(); grid_host.setLayout(grid)

        # per-test remarks (printed under the results table)
        rk = item.keys()
        existing_rem = (item["remarks"] if "remarks" in rk else "") or ""
        rem = QPlainTextEdit(); rem.setPlainText(existing_rem)
        rem.setPlaceholderText("Remarks (optional) — printed under this test's results")
        rem.setFixedHeight(60)
        self._remarks[item["id"]] = rem
        rem_lbl = muted("Remarks")

        host = QWidget(); hl = QVBoxLayout(host)
        hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(6)
        hl.addWidget(grid_host); hl.addWidget(rem_lbl); hl.addWidget(rem)
        return card(h2(item["test_name"]), host)

    # ---------------------------------------------------------------
    def save_results(self):
        if self.current_receipt is None:
            return
        c = self.con
        r = c.execute("SELECT sex FROM receipts WHERE id=?", (self.current_receipt,)).fetchone()
        sex = r["sex"]
        for (item_id, param_id), editor in self._editors.items():
            value = editor.text().strip()
            cb = self._show.get((item_id, param_id))
            hidden = 0 if (cb is None or cb.isChecked()) else 1
            if param_id is None:
                # single-line free result
                c.execute(
                    "DELETE FROM results WHERE receipt_item_id=? AND parameter_id IS NULL",
                    (item_id,),
                )
                c.execute(
                    "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,value,hidden)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (item_id, None, 0, "N", "Result", value, hidden),
                )
                continue
            p = c.execute("SELECT * FROM test_parameters WHERE id=?", (param_id,)).fetchone()
            ref = resolve_ref(p, sex)
            c.execute(
                """INSERT INTO results
                   (receipt_item_id,parameter_id,seq,part_type,group_head,name,units,
                    superscript,ref_text,value,hidden)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(receipt_item_id,parameter_id) DO UPDATE SET
                     value=excluded.value, ref_text=excluded.ref_text, hidden=excluded.hidden""",
                (item_id, param_id, p["seq"], p["part_type"], p["group_head"], p["name"],
                 p["units"], p["superscript"], ref, value, hidden),
            )
        # per-test remarks
        for item_id, rem in self._remarks.items():
            txt = rem.toPlainText().strip()
            c.execute("UPDATE receipt_items SET remarks=? WHERE id=?", (txt or None, item_id))
        # also persist continuation/heading lines so the printed report is complete
        self._snapshot_static_lines(sex)
        c.execute(
            "UPDATE receipts SET status='reported' WHERE id=? AND status IN ('pending','in_progress')",
            (self.current_receipt,),
        )
        c.commit()
        QMessageBox.information(self, "Results", "Results saved.")
        # optional auto-send on WhatsApp — runs in the background, reports when done
        if db.get_setting(c, "whatsapp_auto", "0") == "1":
            wa.send_async(self, c, "report", self.current_receipt,
                          clicked=self.wa_btn, lock_buttons=(self.wa_btn,))
        self.refresh_list()

    def send_whatsapp(self):
        if self.current_receipt is None:
            return
        # background send — keeps the window responsive
        wa.send_async(self, self.con, "report", self.current_receipt,
                      clicked=self.wa_btn, lock_buttons=(self.wa_btn,))

    def _snapshot_static_lines(self, sex):
        """Persist H/L/continuation lines (no editor) so reports render fully."""
        c = self.con
        items = c.execute(
            "SELECT id, test_id FROM receipt_items WHERE receipt_id=?",
            (self.current_receipt,),
        ).fetchall()
        for it in items:
            params = c.execute(
                "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq", (it["test_id"],)
            ).fetchall()
            for p in params:
                pt = (p["part_type"] or "N").upper()
                if pt in ("L", "H") or not (p["name"] or "").strip():
                    ref = resolve_ref(p, sex)
                    c.execute(
                        """INSERT OR IGNORE INTO results
                           (receipt_item_id,parameter_id,seq,part_type,group_head,name,
                            units,superscript,ref_text,value)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (it["id"], p["id"], p["seq"], p["part_type"], p["group_head"],
                         p["name"], p["units"], p["superscript"], ref, None),
                    )

    def print_report(self):
        if self.current_receipt is None:
            return
        rid = self.current_receipt
        printer = db.get_setting(self.con, "default_printer", "")

        def done(ok, result):
            if not ok:
                QMessageBox.warning(self, "Print", f"Could not prepare the report:\n{result}")
                return
            report.print_bytes(result, self, "Print Report", printer)

        tasks.run_in_background(self, lambda con: report.build_report_bytes(con, rid), done,
                                clicked=self.print_btn, busy_text="Preparing…")

    def save_pdf(self):
        if self.current_receipt is None:
            return
        from PySide6.QtWidgets import QFileDialog
        rid = self.current_receipt
        r = self.con.execute("SELECT lab_no FROM receipts WHERE id=?", (rid,)).fetchone()
        default = f"{(r['lab_no'] if r else 'report')}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save report PDF", default, "PDF (*.pdf)")
        if not path:
            return

        def done(ok, result):
            if ok:
                QMessageBox.information(self, "PDF", f"Saved:\n{path}")
            else:
                QMessageBox.warning(self, "PDF", f"Could not save the PDF:\n{result}")

        tasks.run_in_background(self, lambda con: report.export_report_pdf(con, rid, path), done,
                                clicked=self.pdf_btn, busy_text="Saving…")
