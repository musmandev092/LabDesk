"""Reception / Billing: register a patient visit, pick tests, take payment."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QComboBox,
    QSpinBox, QDoubleSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QMessageBox, QListWidget, QListWidgetItem,
    QInputDialog, QCheckBox, QMenu,
)

from PySide6.QtWidgets import QSizePolicy

import sqlite3

from .widgets import muted, card, money, page_header, field_label
from . import tasks, wa
from .. import db, report, roles, whatsapp
from ..constants import (
    TITLES, AGE_UNITS, SEXES, SPECIMEN_PRESETS, PAYMENT_METHODS, normalize_phone,
)


def _clean_specimen(s: str) -> str:
    """Tidy a legacy `sample_required` value for the specimen dropdown."""
    s = (s or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("phay") or low.startswith("phys"):   # "Phaysically"/"Physcially"
        return "Physical (no sample)"
    return s


class ReceptionPage(QWidget):
    def __init__(self, con, user):
        super().__init__()
        self.con = con
        self.user = user
        self.cart = []  # list of dicts: {test_id, name, charge}
        self._existing_patient_id = None  # set when a returning patient is picked

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header, _ = page_header("Reception / Billing", "Register a patient and create an invoice")
        root.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(14)

        # ---- left: patient + test picker ----
        left = QVBoxLayout()
        left.setSpacing(12)

        # patient form
        pgrid = QGridLayout(); pgrid.setSpacing(8)
        pgrid.setColumnStretch(1, 1); pgrid.setColumnStretch(3, 1)
        self.title = QComboBox(); self.title.addItems(TITLES)
        self.name = QLineEdit(); self.name.setPlaceholderText("Patient name *")
        self.mr_no = QLineEdit(); self.mr_no.setPlaceholderText("auto if blank")
        self.age = QSpinBox(); self.age.setMaximum(150)
        self.age_desc = QComboBox(); self.age_desc.addItems(AGE_UNITS)
        self.sex = QComboBox(); self.sex.addItems(SEXES)
        self.tel = QLineEdit(); self.tel.setPlaceholderText("Telephone / WhatsApp")
        self.address = QLineEdit(); self.address.setPlaceholderText("Address")
        self.doctor = QComboBox(); self.doctor.setEditable(True)
        self.specimen = QComboBox(); self.specimen.setEditable(True)
        self.update_specimen_options()  # presets (no cart yet)
        # editing identity fields by hand breaks any "returning patient" link
        self.name.textEdited.connect(self._unlink)
        self.tel.textEdited.connect(self._unlink)
        self.mr_no.textEdited.connect(self._unlink)
        age_box = QHBoxLayout(); age_box.setContentsMargins(0, 0, 0, 0)
        age_box.addWidget(self.age); age_box.addWidget(self.age_desc)
        age_w = QWidget(); age_w.setLayout(age_box)
        pgrid.addWidget(field_label("Title"), 0, 0); pgrid.addWidget(self.title, 0, 1)
        pgrid.addWidget(field_label("Name"), 0, 2); pgrid.addWidget(self.name, 0, 3)
        pgrid.addWidget(field_label("Age"), 1, 0); pgrid.addWidget(age_w, 1, 1)
        pgrid.addWidget(field_label("Sex"), 1, 2); pgrid.addWidget(self.sex, 1, 3)
        pgrid.addWidget(field_label("MR No"), 2, 0); pgrid.addWidget(self.mr_no, 2, 1)
        pgrid.addWidget(field_label("Phone"), 2, 2); pgrid.addWidget(self.tel, 2, 3)
        pgrid.addWidget(field_label("Address"), 3, 0); pgrid.addWidget(self.address, 3, 1, 1, 3)
        pgrid.addWidget(field_label("Doctor"), 4, 0); pgrid.addWidget(self.doctor, 4, 1, 1, 3)
        pgrid.addWidget(field_label("Specimen"), 5, 0); pgrid.addWidget(self.specimen, 5, 1, 1, 3)
        pform = QWidget(); pform.setLayout(pgrid)
        # returning-patient lookup (phone is the practical key patients remember)
        self.find = QLineEdit()
        self.find.setPlaceholderText("🔍  Returning patient? search phone / MR No / name")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(tasks.debounce(self, self.search_patients))
        self.find_results = QListWidget()
        self.find_results.setMaximumHeight(0)
        self.find_results.hide()
        self.find_results.itemActivated.connect(self.pick_patient)
        self.find_results.itemClicked.connect(self.pick_patient)
        self.linked_lbl = muted("")
        self.linked_lbl.hide()
        # Positive consent, default ON (giving a number implies the patient wants
        # WhatsApp delivery). Unticking opts them out; the choice is timestamped.
        self.wa_consent = QCheckBox("Send reports & bills to this patient on WhatsApp")
        self.wa_consent.setChecked(True)
        self.wa_consent.setToolTip(
            "Reports/bills are delivered through WhatsApp (Meta). Untick if the "
            "patient does not want messages sent to their number.")
        # previous visits of a picked returning patient (hidden until one is chosen)
        self.prev_lbl = muted("Previous visits")
        self.prev_lbl.hide()
        self.prev_visits = QListWidget()
        self.prev_visits.setMaximumHeight(108)
        self.prev_visits.setEditTriggers(QListWidget.NoEditTriggers)
        self.prev_visits.hide()
        patient_card = card(self.find, self.find_results, self.linked_lbl, pform,
                            self.wa_consent, self.prev_lbl, self.prev_visits, title="Patient")
        patient_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        left.addWidget(patient_card)

        # test search
        search_row = QHBoxLayout(); search_row.setContentsMargins(0, 0, 0, 0); search_row.setSpacing(8)
        self.test_search = QLineEdit()
        self.test_search.setPlaceholderText("Search test by name or number… (type, then double-click)")
        self.test_search.setMinimumHeight(38)
        self.test_search.textChanged.connect(tasks.debounce(self, self.search_tests))
        self.panel_btn = QPushButton("Add panel ▾"); self.panel_btn.setObjectName("ghost")
        self.panel_btn.setMinimumHeight(38)
        self.panel_btn.setToolTip("Add every test in a saved panel / profile at once")
        self.panel_btn.clicked.connect(self._show_panel_menu)
        search_row.addWidget(self.test_search, 1)
        search_row.addWidget(self.panel_btn)
        search_w = QWidget(); search_w.setLayout(search_row)
        self.results = QListWidget()
        self.results.itemActivated.connect(self.add_from_list)
        self.results.itemDoubleClicked.connect(self.add_from_list)
        add_card = card(search_w, self.results, title="Add tests")
        # let the results list grow to fill the card and the column
        add_card.layout().setStretch(add_card.layout().count() - 1, 1)
        left.addWidget(add_card, 1)
        body.addLayout(left, 3)

        # ---- right: cart + totals ----
        right = QVBoxLayout()
        right.setSpacing(12)
        self.cart_table = QTableWidget(0, 3)
        self.cart_table.setHorizontalHeaderLabels(["Test", "Charge", ""])
        ch = self.cart_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.Stretch)             # test name grows
        ch.setSectionResizeMode(1, QHeaderView.ResizeToContents)    # charge
        ch.setSectionResizeMode(2, QHeaderView.Fixed)
        self.cart_table.setColumnWidth(2, 42)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setEditTriggers(QTableWidget.NoEditTriggers)
        cart_card = card(self.cart_table, title="Selected tests")
        cart_card.layout().setStretch(cart_card.layout().count() - 1, 1)
        right.addWidget(cart_card, 1)

        # totals
        tgrid = QGridLayout(); tgrid.setSpacing(9)
        tgrid.setColumnStretch(1, 1)
        self.subtotal = QLabel("—"); self.subtotal.setStyleSheet("font-weight:700;")
        self.discount = QDoubleSpinBox(); self.discount.setMaximum(100); self.discount.setSuffix(" %")
        self.discount.valueChanged.connect(self.recompute)
        # A discount needs manager/admin rights; a cashier must get it approved.
        self._can_discount = roles.can(self.user["role"], "apply_discount")
        self._discount_approved_by = None
        self.discount_lock = QPushButton("🔒 Approve"); self.discount_lock.setObjectName("ghost")
        self.discount_lock.setToolTip("A discount needs manager/admin approval")
        self.discount_lock.clicked.connect(self._request_discount_approval)
        drow = QHBoxLayout(); drow.setContentsMargins(0, 0, 0, 0); drow.setSpacing(6)
        drow.addWidget(self.discount, 1)
        if not self._can_discount:
            drow.addWidget(self.discount_lock)
            self.discount.setEnabled(False)
        dwrap = QWidget(); dwrap.setLayout(drow)
        self.net = QLabel("—"); self.net.setStyleSheet("font-weight:800;font-size:18px;color:#0a5f67;")
        self.paid = QDoubleSpinBox(); self.paid.setMaximum(1_000_000); self.paid.setPrefix("Rs. ")
        self.paid.valueChanged.connect(self.recompute)
        self.due = QLabel("—"); self.due.setStyleSheet("font-weight:800;font-size:15px;color:#c0392b;")
        # change to hand back when the customer overpays (paid > net)
        self.change = QLabel("—"); self.change.setStyleSheet("font-weight:800;font-size:15px;color:#1f9d55;")
        self.change_lbl = field_label("Change to return")
        self.change.setVisible(False); self.change_lbl.setVisible(False)
        tgrid.addWidget(field_label("Subtotal"), 0, 0); tgrid.addWidget(self.subtotal, 0, 1, Qt.AlignRight)
        tgrid.addWidget(field_label("Discount"), 1, 0); tgrid.addWidget(dwrap, 1, 1)
        tgrid.addWidget(field_label("Net payable"), 2, 0); tgrid.addWidget(self.net, 2, 1, Qt.AlignRight)
        tgrid.addWidget(field_label("Paid"), 3, 0); tgrid.addWidget(self.paid, 3, 1)
        self.payment_method = QComboBox()
        self.payment_method.addItems(PAYMENT_METHODS)
        tgrid.addWidget(field_label("Payment method"), 4, 0); tgrid.addWidget(self.payment_method, 4, 1)
        tgrid.addWidget(field_label("Due"), 5, 0); tgrid.addWidget(self.due, 5, 1, Qt.AlignRight)
        tgrid.addWidget(self.change_lbl, 6, 0); tgrid.addWidget(self.change, 6, 1, Qt.AlignRight)
        tw = QWidget(); tw.setLayout(tgrid)
        pay_card = card(tw, title="Payment")
        pay_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        right.addWidget(pay_card)

        btns = QHBoxLayout()
        # NB: clicked(checked) passes a bool — wrap so do_print stays True
        save = QPushButton("Save && Print receipt"); save.setMinimumHeight(42)
        save.clicked.connect(lambda: self.save(do_print=True))
        save_only = QPushButton("Save (no print)"); save_only.setObjectName("ghost")
        save_only.clicked.connect(lambda: self.save(do_print=False))
        clear = QPushButton("Clear"); clear.setObjectName("ghost"); clear.clicked.connect(self.clear_form)
        btns.addWidget(clear); btns.addStretch(1); btns.addWidget(save_only); btns.addWidget(save)
        right.addLayout(btns)
        body.addLayout(right, 2)

        root.addLayout(body, 1)

        # keyboard shortcuts: Ctrl+S save & print, Ctrl+Enter save (no print)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=lambda: self.save(do_print=True))
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=lambda: self.save(do_print=False))
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=lambda: self.save(do_print=False))
        # Enter in the test search adds the top match
        self.test_search.returnPressed.connect(self._add_top_test)

    # ---------------------------------------------------------------
    def on_show(self):
        self.load_doctors()
        if self.results.count() == 0:
            self.search_tests("")
        if not self.cart:
            self._apply_promo()
            self.recompute()

    # ---- discount approval + special-day promo --------------------
    def _request_discount_approval(self):
        """A cashier asks a manager/admin to approve a discount on this bill."""
        u, ok = QInputDialog.getText(self, "Manager approval", "Manager / Admin username:")
        if not ok or not u.strip():
            return
        p, ok = QInputDialog.getText(
            self, "Manager approval", f"Password for {u.strip()}:", QLineEdit.Password)
        if not ok:
            return
        approver = db.verify_user(self.con, u.strip(), p)
        if not approver or not roles.can(approver["role"], "apply_discount"):
            # audit the failed approval attempt (brute-force of a manager password)
            db.log_audit(self.con, self.user["username"], "discount_approval_failed",
                         f"attempted approver: {u.strip() or '(blank)'}")
            QMessageBox.warning(self, "Approval",
                                "Invalid credentials, or that user can't approve discounts.")
            return
        self._discount_approved_by = approver["username"]
        self.discount.setEnabled(True)
        self.discount_lock.setText(f"✓ {roles.role_label(approver['role'])}")
        self.discount_lock.setEnabled(False)
        self.discount.setFocus()

    def _promo_pct(self) -> float:
        """Active special-day discount %, honouring the optional end date."""
        try:
            pct = float(db.get_setting(self.con, "promo_discount_pct", "0") or 0)
        except ValueError:
            pct = 0.0
        until = db.get_setting(self.con, "promo_until", "").strip()
        if until:
            import datetime
            try:
                if datetime.date.today() > datetime.date.fromisoformat(until):
                    return 0.0
            except ValueError:
                pass
        return max(0.0, min(100.0, pct))

    def _apply_promo(self):
        pct = self._promo_pct()
        self.discount.blockSignals(True)
        self.discount.setValue(pct)            # auto-apply the special-day discount
        self.discount.blockSignals(False)

    def load_doctors(self):
        cur = self.doctor.currentText()
        self.doctor.clear()
        self.doctor.addItem("", None)
        self._doctors = self.con.execute(
            "SELECT id, name FROM doctors WHERE active=1 ORDER BY name"
        ).fetchall()
        for d in self._doctors:
            self.doctor.addItem(d["name"], d["id"])
        self.doctor.setCurrentText(cur)

    def _hint_item(self, text):
        it = QListWidgetItem(text)
        it.setFlags(Qt.NoItemFlags)
        it.setForeground(Qt.gray)
        return it

    # ---- returning-patient lookup ---------------------------------
    def _unlink(self, *_):
        """Hand-editing identity fields detaches any picked patient."""
        if self._existing_patient_id is not None:
            self._existing_patient_id = None
            self.linked_lbl.hide()
            self.prev_lbl.hide(); self.prev_visits.hide()

    def search_patients(self, text=None):
        text = (self.find.text() if text is None else text).strip()
        self.find_results.clear()
        if len(text) < 2:
            self.find_results.hide()
            return
        like = f"%{text}%"
        rows = self.con.execute(
            """SELECT id,title,name,age,age_desc,sex,telephone,address,mr_no
               FROM patients
               WHERE id IN (
                 SELECT MAX(id) FROM patients
                 WHERE name LIKE ? OR telephone LIKE ? OR mr_no LIKE ?
                 GROUP BY COALESCE(NULLIF(telephone,''), mr_no, id))
               ORDER BY id DESC LIMIT 8""",
            (like, like, like),
        ).fetchall()
        if not rows:
            self.find_results.hide()
            return
        for r in rows:
            who = f"{(r['title'] or '').strip()} {r['name']}".strip()
            meta = "  ·  ".join(x for x in [r["mr_no"], r["telephone"]] if x)
            it = QListWidgetItem(f"{who}    —    {meta}" if meta else who)
            it.setData(Qt.UserRole, r["id"])
            self.find_results.addItem(it)
        self.find_results.setMaximumHeight(min(self.find_results.count(), 5) * 36 + 8)
        self.find_results.show()

    def pick_patient(self, item):
        if item is None:        # itemActivated can fire with no item (Enter on empty list)
            return
        pid = item.data(Qt.UserRole)
        if pid is None:
            return
        r = self.con.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        if not r:
            return
        self._existing_patient_id = pid
        self.title.setCurrentText((r["title"] or "").strip())
        self.name.setText(r["name"] or "")
        self.age.setValue(r["age"] or 0)
        self.age_desc.setCurrentText(r["age_desc"] or "Years")
        self.sex.setCurrentText(r["sex"] or "Male")
        self.tel.setText(r["telephone"] or "")
        self.address.setText(r["address"] or "")
        self.mr_no.setText(r["mr_no"] or "")
        # consent = NOT opted out (default ON for rows predating the column)
        self.wa_consent.setChecked(not ("wa_optout" in r.keys() and r["wa_optout"]))
        self.linked_lbl.setText(
            f"✓ Linked to existing patient {r['mr_no'] or ''} — new visit will join their history")
        self.linked_lbl.show()
        self._show_previous_visits(pid)
        self.find.clear()
        self.find_results.hide()

    def _show_previous_visits(self, pid):
        """List this patient's recent receipts so reception sees their history."""
        cur = db.currency(self.con)
        rows = self.con.execute(
            "SELECT lab_no, received_at, net_amount, due, status FROM receipts "
            f"WHERE patient_id=? AND {db.NOT_VOIDED} ORDER BY id DESC LIMIT 12", (pid,)
        ).fetchall()
        self.prev_visits.clear()
        if not rows:
            self.prev_lbl.hide(); self.prev_visits.hide()
            return
        for r in rows:
            when = (r["received_at"] or "")[:10]
            due = f" · due {money(r['due'], cur)}" if r["due"] else ""
            st = (r["status"] or "").replace("_", " ")
            it = QListWidgetItem(
                f"{r['lab_no'] or ''}  ·  {when}  ·  {money(r['net_amount'] or 0, cur)}  ·  {st}{due}")
            if r["due"]:
                it.setForeground(Qt.red)
            self.prev_visits.addItem(it)
        self.prev_lbl.setText(f"Previous visits ({len(rows)})")
        self.prev_lbl.show(); self.prev_visits.show()

    # ---- specimen options driven by the chosen tests --------------
    def update_specimen_options(self):
        """Offer each cart test's `sample_required` as a specimen option (plus the
        standard presets); auto-select when there is a single specimen."""
        cur = self.specimen.currentText().strip()
        ids = [c["test_id"] for c in self.cart]
        cart_specs = []
        if ids:
            q = ("SELECT DISTINCT sample_required FROM tests WHERE id IN (%s) "
                 "AND sample_required<>''" % ",".join("?" * len(ids)))
            for row in self.con.execute(q, ids):
                s = _clean_specimen(row[0])
                if s and s not in cart_specs:
                    cart_specs.append(s)
        self.specimen.blockSignals(True)
        self.specimen.clear()
        self.specimen.addItem("")
        for s in cart_specs:
            self.specimen.addItem(s)
        if cart_specs:
            self.specimen.insertSeparator(self.specimen.count())
        for s in SPECIMEN_PRESETS:
            self.specimen.addItem(s)
        self.specimen.blockSignals(False)
        if cur:
            self.specimen.setCurrentText(cur)
        elif len(cart_specs) == 1:
            self.specimen.setCurrentText(cart_specs[0])

    def search_tests(self, text=None):
        text = (self.test_search.text() if text is None else text).strip()
        self.results.clear()
        cur = db.currency(self.con)
        if len(text) < 1:
            self.results.addItem(self._hint_item("Start typing a test name or number above to see matches…"))
            return
        like = f"%{text}%"
        # match on the test name OR its (legacy) test number — staff often know
        # tests by the number from the old system.
        rows = self.con.execute(
            "SELECT id,name,charges,legacy_no FROM tests WHERE active=1 "
            "AND (name LIKE ? OR CAST(legacy_no AS TEXT) LIKE ?) "
            "ORDER BY name LIMIT 40", (like, like),
        ).fetchall()
        if not rows:
            self.results.addItem(self._hint_item(f"No tests match “{text}”."))
            return
        for r in rows:
            no = f"#{r['legacy_no']}  " if r["legacy_no"] else ""
            it = QListWidgetItem(f"{no}{r['name']}   —   {cur} {r['charges']:,.0f}")
            it.setData(Qt.UserRole, (r["id"], r["name"], r["charges"]))
            self.results.addItem(it)

    def _show_panel_menu(self):
        """Drop down the saved panels; picking one adds all its tests to the cart."""
        panels = db.list_panels(self.con)
        menu = QMenu(self)
        if not panels:
            act = menu.addAction("No panels yet — create them in Test Catalog")
            act.setEnabled(False)
        else:
            for p in panels:
                menu.addAction(p["name"], lambda _=False, pid=p["id"], nm=p["name"]: self._add_panel(pid, nm))
        menu.exec(self.panel_btn.mapToGlobal(self.panel_btn.rect().bottomLeft()))

    def _add_panel(self, panel_id, name):
        rows = db.panel_tests(self.con, panel_id)
        added = 0
        for r in rows:
            if any(c["test_id"] == r["id"] for c in self.cart):
                continue
            self.cart.append({"test_id": r["id"], "name": r["name"], "charge": r["charges"]})
            added += 1
        self.refresh_cart()
        skipped = len(rows) - added
        msg = f"Added {added} test(s) from “{name}”."
        if skipped:
            msg += f" {skipped} already in the cart."
        self.statusBar_message(msg)

    def statusBar_message(self, msg):
        """Surface a brief status note via the main window's status bar if present."""
        w = self.window()
        if hasattr(w, "statusBar"):
            try:
                w.statusBar().showMessage(msg, 4000)
                return
            except Exception:
                pass

    def _add_top_test(self):
        """Enter in the test search box adds the first matching test."""
        for i in range(self.results.count()):
            it = self.results.item(i)
            if it.data(Qt.UserRole):
                self.add_from_list(it)
                self.test_search.clear()
                return

    def add_from_list(self, item):
        # itemActivated can fire with no item (Enter on a focused empty list, esp. Wayland)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return  # hint / empty-state row
        tid, name, charge = data
        if any(c["test_id"] == tid for c in self.cart):
            return  # no duplicates
        self.cart.append({"test_id": tid, "name": name, "charge": charge})
        self.test_search.clear()
        self.search_tests("")
        self.refresh_cart()

    def remove_cart(self, idx):
        del self.cart[idx]
        self.refresh_cart()

    def refresh_cart(self):
        self.cart_table.setRowCount(0)
        for i, c in enumerate(self.cart):
            r = self.cart_table.rowCount(); self.cart_table.insertRow(r)
            self.cart_table.setItem(r, 0, QTableWidgetItem(c["name"]))
            charge_it = QTableWidgetItem(f"{c['charge']:,.0f}")
            charge_it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.cart_table.setItem(r, 1, charge_it)
            btn = QPushButton("✕")
            btn.setToolTip("Remove this test")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(28, 26)
            btn.setStyleSheet(
                "QPushButton{background:transparent;color:#c0392b;border:1px solid #e3b4ae;"
                "border-radius:6px;font-weight:bold;padding:0;}"
                "QPushButton:hover{background:#c0392b;color:white;border-color:#c0392b;}"
            )
            btn.clicked.connect(lambda _=False, idx=i: self.remove_cart(idx))
            self.cart_table.setCellWidget(r, 2, btn)
        self.update_specimen_options()
        self.recompute()

    def recompute(self):
        cur = db.currency(self.con)
        sub = sum(c["charge"] for c in self.cart)
        disc = sub * self.discount.value() / 100.0
        net = max(0.0, sub - disc)
        paid = self.paid.value()
        due = max(0.0, net - paid)
        change = max(0.0, paid - net)
        self.subtotal.setText(money(sub, cur))
        self.net.setText(money(net, cur))
        self.due.setText(money(due, cur))
        # show the change-to-return row only when the customer overpaid (due == 0)
        self.change.setText(money(change, cur))
        self.change_lbl.setVisible(change > 0)
        self.change.setVisible(change > 0)
        self._net = net
        self._sub = sub

    # ---------------------------------------------------------------
    def save(self, do_print=True):
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Reception", "Patient name is required.")
            return
        if not self.cart:
            QMessageBox.warning(self, "Reception", "Add at least one test.")
            return
        # Re-validate the discount at save (defence-in-depth — don't trust only the
        # widget's enabled state). A discount ABOVE the auto-applied promo needs the
        # apply_discount capability or a recorded manager approval.
        if self.discount.value() > self._promo_pct() + 1e-9 and not (
                roles.can(self.user["role"], "apply_discount") or self._discount_approved_by):
            QMessageBox.warning(self, "Discount",
                                "A discount above the promo needs manager/admin approval.")
            return
        c = self.con
        title = self.title.currentText().strip()
        mr_no = self.mr_no.text().strip()
        specimen = self.specimen.currentText().strip()
        cc = db.get_setting(c, "whatsapp_country_code", "92") or "92"
        tel = normalize_phone(self.tel.text(), cc)
        age = self.age.value(); age_desc = self.age_desc.currentText(); sex = self.sex.currentText()
        addr = self.address.text().strip()
        # Resolve the patient identity:
        #  1) an explicitly picked "returning patient", else
        #  2) auto-match on (canonical phone + same name), else
        #  3) a brand-new patient with an auto-assigned MR No.
        pid = self._existing_patient_id
        if not pid and tel:
            m = c.execute(
                "SELECT id FROM patients WHERE telephone=? AND lower(name)=lower(?) "
                "ORDER BY id DESC LIMIT 1", (tel, name),
            ).fetchone()
            if m:
                pid = m["id"]
        new_patient = not pid
        doc_id = self.doctor.currentData()
        doc_name = self.doctor.currentText().strip()
        # compute totals directly (don't depend on cached recompute state);
        # round to whole paisa so a discount can't leave a sub-cent "phantom due"
        sub = round(sum(it["charge"] for it in self.cart), 2)
        disc_pct = self.discount.value()
        net = round(max(0.0, sub - sub * disc_pct / 100.0), 2)
        paid = round(self.paid.value(), 2)
        due = round(max(0.0, net - paid), 2)
        pay_method = self.payment_method.currentText()
        optout = 0 if self.wa_consent.isChecked() else 1
        prefix = db.get_setting(c, "lab_no_prefix", "LAB")
        datestr = c.execute("SELECT strftime('%Y-%m-%d','now','localtime')").fetchone()[0]
        consent_at = c.execute("SELECT datetime('now','localtime')").fetchone()[0]
        # The whole write is one transaction: if anything fails we roll back so a
        # half-saved bill can never exist (nothing charged), and we surface it.
        try:
            if pid:  # returning patient → reuse row + permanent MR, refresh details
                row = c.execute("SELECT mr_no FROM patients WHERE id=?", (pid,)).fetchone()
                mr_no = mr_no or (row["mr_no"] if row else "") or f"MR{pid:05d}"
                c.execute(
                    "UPDATE patients SET title=?,name=?,age=?,age_desc=?,sex=?,telephone=?,"
                    "address=?,mr_no=?,wa_optout=?,wa_consent_at=? WHERE id=?",
                    (title, name, age, age_desc, sex, tel, addr, mr_no, optout, consent_at, pid))
            else:    # new patient
                pid = c.execute(
                    "INSERT INTO patients(title,mr_no,name,age,age_desc,sex,telephone,address,"
                    "wa_optout,wa_consent_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (title, mr_no, name, age, age_desc, sex, tel, addr, optout, consent_at)).lastrowid
                if not mr_no:
                    mr_no = f"MR{pid:05d}"
                    c.execute("UPDATE patients SET mr_no=? WHERE id=?", (mr_no, pid))
            rid = c.execute(
                """INSERT INTO receipts
                   (patient_id,doctor_id,title,mr_no,patient_name,age,age_desc,sex,telephone,address,
                    dr_name,specimen,subtotal,discount_pct,less,net_amount,paid,due,
                    payment_method,status,created_by,received_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                (pid, doc_id, title, mr_no, name, age, age_desc, sex, tel, addr,
                 doc_name, specimen, sub, disc_pct, 0, net, paid, due,
                 pay_method, "pending", self.user["username"])).lastrowid
            # atomic lab number: base it on the highest serial already minted
            # today for this prefix — NOT COUNT(*), which regresses (and triggers
            # a retry storm) if a receipt is ever removed — then bump on the
            # UNIQUE guard (ux_receipts_labno) so two terminals can't collide.
            serial_prefix = f"{prefix}_{datestr}_"
            like = (serial_prefix.replace("\\", "\\\\")
                    .replace("%", "\\%").replace("_", "\\_") + "%")
            top = c.execute(
                "SELECT MAX(CAST(substr(lab_no, ?) AS INTEGER)) FROM receipts "
                "WHERE lab_no LIKE ? ESCAPE '\\'",
                (len(serial_prefix) + 1, like),
            ).fetchone()[0]
            base = (top or 0) + 1
            lab_no = None
            for bump in range(500):
                cand = f"{prefix}_{datestr}_{base + bump:03d}"
                try:
                    c.execute("UPDATE receipts SET lab_no=?, case_no=? WHERE id=?", (cand, cand, rid))
                    lab_no = cand
                    break
                except sqlite3.IntegrityError:
                    continue
            if lab_no is None:
                raise RuntimeError("could not allocate a unique lab number")
            for item in self.cart:
                c.execute(
                    "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
                    (rid, item["test_id"], item["name"], item["charge"]))
            if paid:
                c.execute(
                    "INSERT INTO ledger(kind,ref_id,detail,credit,date) "
                    "VALUES ('income',?,?,?,date('now','localtime'))",
                    (rid, f"Receipt {lab_no} — {name}", paid))
            c.commit()
        except Exception as e:
            try:
                c.rollback()
            except Exception:
                pass
            QMessageBox.warning(self, "Save failed",
                                "The receipt was NOT saved — nothing has been charged. "
                                f"Please try again.\n\n{e}")
            return
        self._last_receipt = rid
        db.log_audit(c, self.user["username"],
                     "patient_created" if new_patient else "patient_updated",
                     f"{name} ({mr_no})")
        db.log_audit(c, self.user["username"], "receipt_created",
                     f"{lab_no} — {name}, net {net:.0f}, paid {paid:.0f}, due {due:.0f}")
        if disc_pct > 0:  # always record any discount (promo, self-applied, or approved)
            who = (self._discount_approved_by
                   or ("promo" if disc_pct <= self._promo_pct() + 1e-9 else self.user["username"]))
            db.log_audit(c, self.user["username"], "discount_approved",
                         f"{disc_pct:g}% on {lab_no} (by {who})")
        QMessageBox.information(self, "Saved", f"Receipt {lab_no} saved.")
        if do_print:
            # native render is fast and prints straight onto the printer (vector);
            # a print failure here never loses the already-saved receipt.
            try:
                report.print_receipt(self.con, rid, self)
            except Exception as e:  # noqa: BLE001 - printing must never lose the save
                QMessageBox.warning(
                    self, "Print", f"Saved as {lab_no}, but printing failed:\n{e}")
        # optional: auto-send the bill on WhatsApp (gated silently so it never
        # nags when WhatsApp isn't set up or the patient has no number)
        if (db.get_setting(self.con, "whatsapp_auto_receipt", "0") == "1"
                and whatsapp.config_ready(self.con)[0]
                and whatsapp.recipient_ready(self.con, rid)[0]):
            wa.send_async(self, self.con, "receipt", rid)
        self.clear_form()

    def clear_form(self):
        self.cart = []
        self._existing_patient_id = None
        self.linked_lbl.hide()
        self.prev_lbl.hide(); self.prev_visits.hide()
        for w in (self.name, self.tel, self.address, self.mr_no, self.test_search, self.find):
            w.clear()
        self.find_results.hide()
        self.title.setCurrentIndex(0)
        self.specimen.setCurrentIndex(0)
        self.age.setValue(0); self.paid.setValue(0)
        self.wa_consent.setChecked(True)
        self.payment_method.setCurrentIndex(0)
        # reset the discount-approval lock for cashiers, then re-apply any promo
        self._discount_approved_by = None
        if not self._can_discount:
            self.discount.setEnabled(False)
            self.discount_lock.setText("🔒 Approve")
            self.discount_lock.setEnabled(True)
        self._apply_promo()
        self.search_tests("")
        self.refresh_cart()
