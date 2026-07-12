"""Worklist / Results: pick a receipt, enter results per parameter, print report."""

from __future__ import annotations

from PySide6.QtCore import QDate, QEvent, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import db, report, whatsapp
from ..application import results as results_svc
from ..catalog_render import category_for_test
from ..roles import can
from . import tasks, wa
from .widgets import (
    card,
    h2,
    muted,
    page_header,
    selected_id,
    setup_date_edit,
    status_badge,
    toast_info,
    toast_warn,
)


def resolve_ref(param_row, sex: str) -> str:
    """Pick the gender-appropriate reference range text."""
    male = param_row["ref_male"] or ""
    female = param_row["ref_female"] or ""
    if (sex or "").lower().startswith("f"):
        return female or male
    return male or female


def _qual_options(ref: str) -> list[str]:
    """Likely result options for a qualitative parameter, inferred from its
    reference text. The combo stays editable so titres (e.g. 1:160) are typeable."""
    r = (ref or "").lower()
    if "reactive" in r:
        return ["", "Non-Reactive", "Reactive"]
    if "detected" in r:
        return ["", "Not Detected", "Detected"]
    if "positive" in r or "negative" in r:
        return ["", "Negative", "Positive"]
    return ["", "Negative", "Positive", "Reactive", "Non-Reactive", "Not Detected"]


def _bloodbank_options(name: str) -> list[str]:
    """Result options for a blood-bank parameter, inferred from its name. An empty
    list means "no fixed vocabulary" → the entry should be a free-text box (e.g.
    Blood Bag No, donor name), not a constrained dropdown."""
    n = (name or "").lower()
    if "group" in n and "rh" not in n:
        return ["", "A", "B", "AB", "O"]
    if "rh" in n:
        return ["", "Positive", "Negative"]
    if "cross" in n or "compat" in n:
        return ["", "Compatible", "Not Compatible"]
    if "coomb" in n or "antibod" in n or "screen" in n:
        return ["", "Positive", "Negative"]
    return []  # bag numbers, names, free notes → plain text field


def _widget_text(w) -> str:
    """Current text of a result editor regardless of widget type."""
    if isinstance(w, QPlainTextEdit):
        return w.toPlainText()
    if isinstance(w, QComboBox):
        return w.currentText()
    return w.text()


def _has_enterable_content(result_rows, remarks, conclusion) -> bool:
    """True if the technician actually entered something worth saving: at least one
    result value, or any remark / impression text. Used to refuse an all-blank save
    so a completely empty report can never be saved (and thus previewed / printed /
    sent). Values and texts arrive already stripped."""
    if any((r.get("value") or "") for r in result_rows):
        return True
    if any((t or "") for t in remarks.values()):
        return True
    return any((t or "") for t in conclusion.values())


def _widget_set_readonly(w, ro: bool) -> None:
    """Lock/unlock a result editor regardless of widget type."""
    if isinstance(w, QComboBox):
        w.setEnabled(not ro)
    else:
        w.setReadOnly(ro)


class _GrowingText(QPlainTextEdit):
    """A multi-line editor that grows to fit its content (so long findings /
    impressions aren't clipped on entry) up to ``max_h``, then scrolls.

    Height is driven by the document layout's documentSizeChanged signal, whose
    reported height is the wrapped line count at the editor's *current* width —
    reliable across resizes, unlike reading viewport().width() before layout.
    """

    def __init__(self, min_h: int = 78, max_h: int = 240) -> None:
        super().__init__()
        self._min_h = min_h
        self._max_h = max_h
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(min_h)
        self.textChanged.connect(self._fit)

    def _fit(self, *args) -> None:
        fm = self.fontMetrics()
        width = self.viewport().width()
        if width < 80:  # not laid out yet → assume the entry column width
            width = 560
        avail = max(1, width - 8)
        text = self.toPlainText() or self.placeholderText()
        lines = 0
        for para in (text or "").split("\n"):
            adv = fm.horizontalAdvance(para)
            lines += max(1, (int(adv) + avail - 1) // avail)  # ceil division
        h = (
            lines * fm.lineSpacing()
            + 2 * self.document().documentMargin()
            + 2 * self.frameWidth()
            + 6
        )
        self.setFixedHeight(int(max(self._min_h, min(self._max_h, h))))

    def resizeEvent(self, e) -> None:  # re-fit when the column width changes
        super().resizeEvent(e)
        self._fit()


class WorklistPage(QWidget):
    def __init__(self, con, user) -> None:
        super().__init__()
        self.con = con
        self.user = user
        self._ids: list[int] = []  # parallel to worklist table rows; filled by refresh
        self.current_receipt: int | None = None
        # (item_id, parameter_id) -> QLineEdit
        self._editors: dict[tuple[int, int | None], QLineEdit] = {}
        # (item_id, parameter_id) -> QCheckBox (ticked = print this row)
        self._show: dict[tuple[int, int | None], QCheckBox] = {}
        # item_id -> QPlainTextEdit (per-test remarks)
        self._remarks: dict[int, QPlainTextEdit] = {}
        # item_id -> QPlainTextEdit (impression/interpretation, descriptive/qualitative)
        self._conclusion: dict[int, QPlainTextEdit] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header, _ = page_header("Worklist / Results", "Enter results and print reports")
        root.addWidget(header)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search patient / lab no…")
        self.search.setMinimumHeight(40)
        self.search.textChanged.connect(tasks.debounce(self, self.refresh_list))
        self.status_filter = QComboBox()
        self.status_filter.setMinimumHeight(40)
        for value, label in [
            ("All", "All"),
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("reported", "Reported"),
            ("delivered", "Delivered"),
        ]:
            self.status_filter.addItem(label, value)
        self.status_filter.setCurrentIndex(1)  # Pending
        self.status_filter.currentIndexChanged.connect(self.refresh_list)
        # optional calendar date-range filter (on received date)
        self.use_dates = QCheckBox("By date")
        self.use_dates.toggled.connect(self._dates_toggled)
        self.date_from = self._date_edit()
        self.date_to = self._date_edit()
        self.date_from.dateChanged.connect(self.refresh_list)
        self.date_to.dateChanged.connect(self.refresh_list)
        top.addWidget(self.search, 1)
        top.addWidget(QLabel("Status:"))
        top.addWidget(self.status_filter)
        top.addWidget(self.use_dates)
        top.addWidget(self.date_from)
        top.addWidget(QLabel("→"))
        top.addWidget(self.date_to)
        root.addLayout(top)

        split = QSplitter()
        split.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # left: receipts
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Lab No", "Patient", "Date", "Status"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)  # Patient grows
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Date readable
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_receipt)
        split.addWidget(self.table)

        # right: result entry
        right = QWidget()
        rl = QVBoxLayout(right)
        self.header = h2("Select a receipt")
        rl.addWidget(self.header)
        self.empty_hint = muted("← Select a patient from the list to enter results.")
        rl.addWidget(self.empty_hint)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.entry_host = QWidget()
        self.entry_layout = QVBoxLayout(self.entry_host)
        self.entry_layout.addStretch(1)
        self.scroll.setWidget(self.entry_host)
        rl.addWidget(self.scroll, 1)

        btns = QHBoxLayout()
        self.save_btn = QPushButton("Save results")
        self.save_btn.clicked.connect(self.save_results)
        self.save_btn.setEnabled(False)
        btns.addStretch(1)
        btns.addWidget(self.save_btn)
        rl.addLayout(btns)
        # Worklist is for entering & saving results only. Printing, PDF export and
        # WhatsApp delivery of the report all live on the Receipts / Reports page.
        self.report_hint = muted(
            "Print, save as PDF or send the report on WhatsApp from the "
            "Receipts / Reports page (once results are saved)."
        )
        self.report_hint.setWordWrap(True)
        rl.addWidget(self.report_hint)
        split.addWidget(right)
        split.setSizes([430, 650])
        # Proportional stretch so the two panes scale with the window instead of the
        # right pane dominating on wide/4K screens (absolute setSizes alone don't).
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

        # ESC clears the selection / right panel; clicking empty list area too
        sc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.clear_selection)
        self.table.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.table.viewport() and event.type() == QEvent.MouseButtonPress:
            if not self.table.indexAt(event.position().toPoint()).isValid():
                self.clear_selection()
        return super().eventFilter(obj, event)

    def clear_selection(self) -> None:
        """Deselect the current receipt and reset the right-hand panel."""
        # block signals while clearing — otherwise clearSelection() fires
        # itemSelectionChanged -> load_receipt while currentRow() is still the old
        # row, which would re-select the receipt we're trying to clear.
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)
        self.current_receipt = None
        self.header.setText("Select a receipt")
        self.empty_hint.show()
        while self.entry_layout.count():
            it = self.entry_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.entry_layout.addStretch(1)
        self._editors = {}
        self._show = {}
        self._remarks = {}
        self._conclusion = {}
        self.save_btn.setEnabled(False)

    # ---------------------------------------------------------------
    def _date_edit(self) -> QDateEdit:
        """A calendar-popup date editor, defaulting to today, disabled until the
        'By date' filter is switched on."""
        d = QDateEdit()
        setup_date_edit(d)
        d.setDisplayFormat("yyyy-MM-dd")
        d.setDate(QDate.currentDate())
        d.setEnabled(False)
        d.setMinimumHeight(40)
        return d

    def _dates_toggled(self, on: bool) -> None:
        self.date_from.setEnabled(on)
        self.date_to.setEnabled(on)
        self.refresh_list()

    def _date_clause(self) -> tuple[str | None, list[str]]:
        """SQL fragment + args for the active date-range filter, else (None, [])."""
        if not self.use_dates.isChecked():
            return None, []
        d1 = self.date_from.date()
        d2 = self.date_to.date()
        if d1 > d2:
            d1, d2 = d2, d1
        return (
            "received_at >= ? AND received_at < ?",
            [d1.toString("yyyy-MM-dd"), d2.addDays(1).toString("yyyy-MM-dd")],
        )

    def on_show(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        q = f"%{self.search.text().strip()}%"
        st = self.status_filter.currentData() or "All"
        sql = (
            f"SELECT * FROM receipts WHERE {db.NOT_VOIDED} "
            "AND (COALESCE(patient_name,'') LIKE ? OR COALESCE(lab_no,'') LIKE ?)"
        )
        args = [q, q]
        if st != "All":
            sql += " AND status=?"
            args.append(st)
        dc, dargs = self._date_clause()
        if dc:
            sql += f" AND {dc}"
            args += dargs
        sql += " ORDER BY id DESC LIMIT 500"
        rows = self.con.execute(sql, args).fetchall()
        self.table.setRowCount(0)
        self._ids = []
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self._ids.append(r["id"])
            self.table.setItem(i, 0, QTableWidgetItem(r["lab_no"] or ""))
            self.table.setItem(i, 1, QTableWidgetItem(r["patient_name"] or ""))
            self.table.setItem(i, 2, QTableWidgetItem((r["received_at"] or "")[:16]))
            self.table.setItem(i, 3, status_badge(r["status"] or ""))

    def _selected_id(self) -> int | None:
        return selected_id(self.table, self._ids)

    # ---------------------------------------------------------------
    def load_receipt(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        self.current_receipt = rid
        r = self.con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
        self.header.setText(
            f"{r['lab_no']} — {r['patient_name']} ({r['sex']}, {r['age']} {r['age_desc']})"
        )
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
        self._editors = {}
        self._show = {}
        self._remarks = {}
        self._conclusion = {}

        items = self.con.execute(
            "SELECT ri.*, t.is_culture FROM receipt_items ri JOIN tests t ON t.id=ri.test_id "
            "WHERE ri.receipt_id=? ORDER BY ri.id",
            (rid,),
        ).fetchall()
        for it in items:
            if it["is_culture"]:
                self.entry_layout.addWidget(self._culture_note(it))
            else:
                self.entry_layout.addWidget(self._build_test_block(it, sex))
        self.entry_layout.addStretch(1)
        # Lock editing by report status + role: a delivered report is frozen for
        # everyone; a reported report may be corrected only by an admin.
        lock = self._results_locked_reason(r["status"])
        if lock:
            self.entry_layout.insertWidget(0, muted(f"🔒  {lock}"))
        editable = not lock
        for ed in self._editors.values():
            _widget_set_readonly(ed, not editable)
        for cb in self._show.values():
            cb.setEnabled(editable)
        for rem in self._remarks.values():
            rem.setReadOnly(not editable)
        for con_box in self._conclusion.values():
            con_box.setReadOnly(not editable)
        self.save_btn.setEnabled(editable)

    def _results_locked_reason(self, status: str | None) -> str:
        """Why result editing is blocked for the current user (else '').
        delivered -> locked for everyone (incl. admin); reported -> admin only;
        pending / in-progress -> open."""
        status = status or ""
        if status == "delivered":
            return "This report is delivered — it is locked and cannot be edited by anyone."
        if status == "reported" and not can(
            self.user["role"], "edit_finalized_results"
        ):
            return "This report is finalised — only an administrator can edit it."
        return ""

    def _culture_note(self, item) -> QWidget:
        lbl = muted(
            f"“{item['test_name']}” is a culture & sensitivity test — "
            "enter its findings on the Microbiology screen."
        )
        lbl.setWordWrap(True)
        return card(lbl, title=item["test_name"])

    def _make_check(self) -> QCheckBox:
        """A ticked 'show on report' checkbox for a parameter row."""
        cb = QCheckBox()
        cb.setChecked(True)
        cb.setToolTip("Tick to print this line on the report; untick to hide it.")
        return cb

    # -- per-category result-entry grids -----------------------------------
    def _grid_single(
        self, grid, item, existing, hidden, had_results, multiline=False
    ) -> None:
        """A test with no parameters → one free result box. ``multiline`` gives a
        tall narrative box (histopathology / biopsy / free-text imaging)."""
        cb = self._make_check()
        cb.setChecked(not (had_results and hidden.get(None)))
        grid.addWidget(cb, 0, 0, Qt.AlignTop if multiline else Qt.AlignVCenter)
        grid.addWidget(QLabel("Findings" if multiline else "Result"), 0, 1, Qt.AlignTop)
        if multiline:
            ed = _GrowingText(min_h=140, max_h=440)
            ed.setPlainText(existing.get(None, "") or "")
            ed.setPlaceholderText("Type the report (gross, microscopy, etc.)")
        else:
            ed = QLineEdit()
            ed.setText(existing.get(None, "") or "")
        grid.addWidget(ed, 0, 2, 1, 3)
        grid.setColumnStretch(2, 1)
        self._editors[(item["id"], None)] = ed
        self._show[(item["id"], None)] = cb

    def _grid_numeric(self, grid, item, params, existing, hidden, had, sex) -> None:
        """Numeric tabular tests (CBC/LFT/RFT…): Show | Parameter | Result | Unit |
        Reference, with the live out-of-range colour cue."""
        for col, lbl in enumerate(("Show", "Parameter", "Result", "Unit", "Reference")):
            grid.addWidget(QLabel(f"<b>{lbl}</b>"), 0, col)
        row_i = 1
        for p in params:
            pt = (p["part_type"] or "N").upper()
            ref = resolve_ref(p, sex)
            name = p["name"] or ""
            if pt == "H":
                grid.addWidget(QLabel(f"<b>{name}</b>"), row_i, 0, 1, 5)
                row_i += 1
                continue
            # legacy static 'L' legend rows are never fillable and their text did not
            # survive the catalog migration — not shown here or on the report
            # (see render.report_doc._measure_qual). A nameless row has nothing to enter.
            if pt == "L" or not name:
                continue
            cb = self._make_check()
            cb.setChecked(not (had and hidden.get(p["id"])))
            grid.addWidget(cb, row_i, 0, Qt.AlignCenter)
            grid.addWidget(QLabel(name), row_i, 1)
            le = QLineEdit()
            le.setText(existing.get(p["id"], "") or "")
            le.setMaximumWidth(160)

            def _flagit(text: str, le: QLineEdit = le, ref: str = ref) -> None:
                fl = report._flag(text, ref)
                if fl and fl[0] == "High":
                    le.setStyleSheet("color:#dc2626; font-weight:700;")
                elif fl and fl[0] == "Low":
                    le.setStyleSheet("color:#d97706; font-weight:700;")
                else:
                    le.setStyleSheet("")

            le.textChanged.connect(_flagit)
            _flagit(le.text())
            grid.addWidget(le, row_i, 2)
            grid.addWidget(QLabel(p["units"] or ""), row_i, 3)
            grid.addWidget(QLabel(ref), row_i, 4)
            self._editors[(item["id"], p["id"])] = le
            self._show[(item["id"], p["id"])] = cb
            row_i += 1

    def _grid_descriptive(self, grid, item, params, existing, hidden, had, sex) -> None:
        """Imaging / narrative tests (ultrasound, x-ray, histopath): Show | Organ /
        Part | Findings — a wide multi-line box per organ, pre-filled on first entry
        with the catalog's normal text so staff edit only the abnormal lines."""
        for col, lbl in enumerate(("Show", "Organ / Part", "Findings")):
            grid.addWidget(QLabel(f"<b>{lbl}</b>"), 0, col)
        grid.setColumnStretch(2, 1)
        row_i = 1
        for p in params:
            pt = (p["part_type"] or "N").upper()
            name = (p["name"] or "").strip()
            # whole-name match (not substring) so a real organ row like "Impression
            # of liver" keeps its editor; only the dedicated block names are skipped.
            # Keep in sync with render.report_doc._CONCLUSION_NAMES.
            if name.lower().rstrip(":").strip() in (
                "conclusion",
                "impression",
                "conclusion / impression",
                "impression / conclusion",
                "interpretation",
            ):
                continue  # handled by the dedicated conclusion box
            if pt == "H":
                grid.addWidget(QLabel(f"<b>{name}</b>"), row_i, 0, 1, 3)
                row_i += 1
                continue
            if not name:
                continue
            cb = self._make_check()
            cb.setChecked(not (had and hidden.get(p["id"])))
            grid.addWidget(cb, row_i, 0, Qt.AlignTop)
            grid.addWidget(QLabel(name), row_i, 1, Qt.AlignTop)
            box = _GrowingText(min_h=60, max_h=260)
            if p["id"] in existing:
                box.setPlainText(existing.get(p["id"]) or "")
            else:  # first entry → start from the normal template
                box.setPlainText(resolve_ref(p, sex) or "")
            grid.addWidget(box, row_i, 2)
            self._editors[(item["id"], p["id"])] = box
            self._show[(item["id"], p["id"])] = cb
            row_i += 1

    def _grid_qualitative(self, grid, item, params, existing, hidden, had, sex) -> None:
        """Serology / blood-bank / qualitative PCR: Show | Parameter | Result |
        Reference — Result is an editable dropdown of the likely word-states (still
        free-typeable for titres like 1:160)."""
        for col, lbl in enumerate(("Show", "Parameter", "Result", "Reference")):
            grid.addWidget(QLabel(f"<b>{lbl}</b>"), 0, col)
        row_i = 1
        for p in params:
            pt = (p["part_type"] or "N").upper()
            ref = resolve_ref(p, sex)
            name = p["name"] or ""
            if pt == "H":
                grid.addWidget(QLabel(f"<b>{name}</b>"), row_i, 0, 1, 4)
                row_i += 1
                continue
            if pt == "L" or not name:
                continue  # legacy static legend row — not shown (see report_doc)
            cb = self._make_check()
            cb.setChecked(not (had and hidden.get(p["id"])))
            grid.addWidget(cb, row_i, 0, Qt.AlignCenter)
            grid.addWidget(QLabel(name), row_i, 1)
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems(_qual_options(ref))
            combo.setMaximumWidth(200)
            combo.setCurrentText(existing.get(p["id"], "") or "")
            grid.addWidget(combo, row_i, 2)
            grid.addWidget(QLabel(ref), row_i, 3)
            self._editors[(item["id"], p["id"])] = combo
            self._show[(item["id"], p["id"])] = cb
            row_i += 1

    def _grid_blood_bank(self, grid, item, params, existing, hidden, had, sex) -> None:
        """Blood bank (group / cross-match / Coombs): Show | Parameter | Result —
        an editable dropdown of the valid result values, no reference column."""
        for col, lbl in enumerate(("Show", "Parameter", "Result")):
            grid.addWidget(QLabel(f"<b>{lbl}</b>"), 0, col)
        row_i = 1
        for p in params:
            pt = (p["part_type"] or "N").upper()
            name = p["name"] or ""
            if pt == "H":
                grid.addWidget(QLabel(f"<b>{name}</b>"), row_i, 0, 1, 3)
                row_i += 1
                continue
            if pt == "L" or not name:
                continue  # legacy static legend row — not shown (see report_doc)
            cb = self._make_check()
            cb.setChecked(not (had and hidden.get(p["id"])))
            grid.addWidget(cb, row_i, 0, Qt.AlignCenter)
            grid.addWidget(QLabel(name), row_i, 1)
            opts = _bloodbank_options(name)
            if opts:  # known result vocabulary → editable dropdown
                editor = QComboBox()
                editor.setEditable(True)
                editor.addItems(opts)
                editor.setMaximumWidth(200)
                editor.setCurrentText(existing.get(p["id"], "") or "")
            else:  # bag number, donor name, free note → plain text field
                editor = QLineEdit()
                editor.setMaximumWidth(240)
                editor.setText(existing.get(p["id"], "") or "")
            grid.addWidget(editor, row_i, 2)
            self._editors[(item["id"], p["id"])] = editor
            self._show[(item["id"], p["id"])] = cb
            row_i += 1

    def _build_test_block(self, item, sex: str) -> QWidget:
        params = self.con.execute(
            "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq",
            (item["test_id"],),
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

        grid = QGridLayout()
        grid.setSpacing(6)
        # Entry layout follows the same render category as the printed report, so
        # what staff type matches what comes out: descriptive tests get wide
        # multi-line finding boxes (pre-filled with the normal text), qualitative
        # tests get result dropdowns, numeric tests keep the value/unit/ref grid.
        cat = category_for_test(self.con, item["test_id"])
        if not params:
            # histopathology / biopsy / free-text imaging: one big narrative box,
            # not a one-line field. Other single-result tests keep the line box.
            multiline = cat == "descriptive"
            self._grid_single(grid, item, existing, hidden, had_results, multiline)
        elif cat == "descriptive":
            self._grid_descriptive(
                grid, item, params, existing, hidden, had_results, sex
            )
        elif cat == "qualitative":
            self._grid_qualitative(
                grid, item, params, existing, hidden, had_results, sex
            )
        elif cat == "blood_bank":
            self._grid_blood_bank(
                grid, item, params, existing, hidden, had_results, sex
            )
        else:
            self._grid_numeric(grid, item, params, existing, hidden, had_results, sex)
        grid_host = QWidget()
        grid_host.setLayout(grid)

        # per-test remarks (printed under the results table)
        rk = item.keys()
        existing_rem = (item["remarks"] if "remarks" in rk else "") or ""
        rem = QPlainTextEdit()
        rem.setPlainText(existing_rem)
        rem.setPlaceholderText("Remarks (optional) — printed under this test's results")
        rem.setFixedHeight(60)
        self._remarks[item["id"]] = rem
        rem_lbl = muted("Remarks")

        host = QWidget()
        hl = QVBoxLayout(host)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(grid_host)
        hl.addWidget(rem_lbl)
        hl.addWidget(rem)

        # Imaging / descriptive and serology / molecular reports carry an
        # Impression / Interpretation block (printed prominently below the table).
        # Offer a dedicated box for those categories so staff can type the
        # conclusion the report needs — the numeric grid tests don't have one.
        if cat in ("descriptive", "qualitative", "blood_bank", "obstetric"):
            label = (
                "Conclusion / Impression"
                if cat in ("descriptive", "obstetric")
                else "Interpretation"
            )
            existing_con = (item["conclusion"] if "conclusion" in rk else "") or ""
            con_box = _GrowingText(min_h=72, max_h=220)
            con_box.setPlainText(existing_con)
            con_box.setPlaceholderText(
                f"{label} (optional) — printed as a highlighted block on the report"
            )
            self._conclusion[item["id"]] = con_box
            hl.addWidget(muted(label))
            hl.addWidget(con_box)
        return card(h2(item["test_name"]), host)

    # ---------------------------------------------------------------
    def save_results(self) -> None:
        if self.current_receipt is None:
            return
        c = self.con
        r = c.execute(
            "SELECT sex, status FROM receipts WHERE id=?", (self.current_receipt,)
        ).fetchone()
        # defence in depth: refuse to write to a locked report even if the button slipped through
        lock = self._results_locked_reason(r["status"])
        if lock:
            toast_warn(self, "Locked", lock)
            return
        sex = r["sex"]
        # Load each parameter once per distinct test on this receipt (a single query)
        # instead of one SELECT per editor plus a second full pass in the snapshot step.
        items = c.execute(
            "SELECT ri.id, ri.test_id, t.is_culture FROM receipt_items ri "
            "JOIN tests t ON t.id=ri.test_id WHERE ri.receipt_id=?",
            (self.current_receipt,),
        ).fetchall()
        test_ids = list({it["test_id"] for it in items})
        params_by_test: dict[int, list] = {tid: [] for tid in test_ids}
        param_by_id: dict[int, object] = {}
        if test_ids:
            ph = ",".join("?" * len(test_ids))
            for p in c.execute(
                f"SELECT * FROM test_parameters WHERE test_id IN ({ph}) ORDER BY test_id, seq",
                tuple(test_ids),
            ):
                params_by_test[p["test_id"]].append(p)
                param_by_id[p["id"]] = p
        # Gather entered values from the widgets here; the DB writes + authorization
        # + audit happen at the service boundary (results_svc.release_results).
        result_rows: list[dict] = []
        for (item_id, param_id), editor in self._editors.items():
            value = _widget_text(editor).strip()
            cb = self._show.get((item_id, param_id))
            hidden = 0 if (cb is None or cb.isChecked()) else 1
            if param_id is None:  # single-line free result
                result_rows.append(
                    {
                        "item_id": item_id,
                        "parameter_id": None,
                        "value": value,
                        "hidden": hidden,
                    }
                )
                continue
            p = param_by_id.get(param_id)
            if p is None:
                continue  # parameter was removed from the test since entry
            result_rows.append(
                {
                    "item_id": item_id,
                    "parameter_id": param_id,
                    "seq": p["seq"],
                    "part_type": p["part_type"],
                    "group_head": p["group_head"],
                    "name": p["name"],
                    "units": p["units"],
                    "superscript": p["superscript"],
                    "ref_text": resolve_ref(p, sex),
                    "value": value,
                    "hidden": hidden,
                }
            )
        remarks = {
            item_id: rem.toPlainText().strip() for item_id, rem in self._remarks.items()
        }
        conclusion = {
            item_id: box.toPlainText().strip()
            for item_id, box in self._conclusion.items()
        }
        # Refuse to save/finalize a report with nothing entered on this screen: at
        # least one value (or an impression / remark) must be present. This also stops
        # a CULTURE-ONLY receipt (no editors here — cultures are entered on the
        # Microbiology screen) from being stamped 'reported' with no data and, with
        # whatsapp_auto on, auto-sending an empty report.
        if not _has_enterable_content(result_rows, remarks, conclusion):
            culture_only = bool(items) and all(
                it["is_culture"] for it in items if "is_culture" in it.keys()
            )
            toast_warn(
                self,
                "Nothing to save",
                "Enter culture results on the Microbiology screen."
                if culture_only
                else "Enter at least one result before saving the report.",
            )
            return
        static_rows = self._static_line_rows(sex, items, params_by_test)
        try:
            lab_no = results_svc.release_results(
                c,
                receipt_id=self.current_receipt,
                result_rows=result_rows,
                remarks=remarks,
                static_rows=static_rows,
                actor_username=self.user["username"],
                actor_role=self.user["role"],
                conclusion=conclusion,
            )
        except PermissionError:
            toast_warn(
                self, "Not allowed", "You don't have permission to save results."
            )
            return
        except Exception as e:
            toast_warn(
                self,
                "Save failed",
                f"Results were NOT saved — please try again.\n\n{e}",
            )
            return
        toast_info(self, "Results", "✓ Results saved.")
        rid = self.current_receipt
        # optional auto-send on WhatsApp — gated SILENTLY first (config + recipient),
        # so an opted-out patient / missing number / unconfigured gateway is a quiet
        # skip, not a red error toast on every save (matches the receipt path).
        if (
            db.get_setting(c, "whatsapp_auto", "0") == "1"
            and whatsapp.config_ready(c)[0]
            and whatsapp.recipient_ready(c, rid)[0]
        ):
            wa.send_async(
                self,
                c,
                "report",
                rid,
                on_done=lambda ok, m: db.log_audit(
                    self.con,
                    self.user["username"],
                    "whatsapp_report",
                    ("sent" if ok else "failed") + f" (auto) — {lab_no or rid}",
                ),
            )
        self.refresh_list()
        # re-render the entry panel so it reflects the now-finalised (locked) state
        # instead of staying editable until the next interaction.
        self.load_receipt()

    def _static_line_rows(self, sex: str, items, params_by_test) -> list[dict]:
        """H/L/continuation lines (no editor) so reports render fully. Reuses the
        parameters already loaded in save_results — no extra queries. The service
        inserts these with INSERT OR IGNORE."""
        rows: list[dict] = []
        for it in items:
            if "is_culture" in it.keys() and it["is_culture"]:
                continue  # cultures are entered on the Microbiology screen — no static rows
            for p in params_by_test.get(it["test_id"], []):
                pt = (p["part_type"] or "N").upper()
                if pt in ("L", "H") or not (p["name"] or "").strip():
                    rows.append(
                        {
                            "item_id": it["id"],
                            "parameter_id": p["id"],
                            "seq": p["seq"],
                            "part_type": p["part_type"],
                            "group_head": p["group_head"],
                            "name": p["name"],
                            "units": p["units"],
                            "superscript": p["superscript"],
                            "ref_text": resolve_ref(p, sex),
                        }
                    )
        return rows
