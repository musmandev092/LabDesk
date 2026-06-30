"""Reception / Billing: register a patient visit, pick tests, take payment."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .. import db, report, roles, whatsapp
from ..application import billing
from ..application import receipts as receipts_svc
from ..constants import (
    AGE_UNITS,
    PAYMENT_METHODS,
    SEXES,
    SPECIMEN_PRESETS,
    TITLES,
    format_address,
    format_person_name,
    normalize_phone,
)
from ..db import sqlite3
from . import tasks, wa
from .reception_cart import ReceptionCartMixin
from .reception_patient import ReceptionPatientMixin
from .widgets import (
    card,
    field_label,
    muted,
    page_header,
    toast_info,
    toast_warn,
)


def _clean_specimen(s: str) -> str:
    """Tidy a legacy `sample_required` value for the specimen dropdown."""
    s = (s or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("phay") or low.startswith("phys"):  # "Phaysically"/"Physcially"
        return "Physical (no sample)"
    return s


class ReceptionPage(ReceptionCartMixin, ReceptionPatientMixin, QWidget):
    def __init__(self, con: sqlite3.Connection, user) -> None:
        super().__init__()
        self.con = con
        self.user = user
        self.cart: list[dict] = []  # list of dicts: {test_id, name, charge}
        self._existing_patient_id = None  # set when a returning patient is picked

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header, _ = page_header(
            "Reception / Billing", "Register a patient and create an invoice"
        )
        root.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(14)

        # ---- left: patient + test picker ----
        left = QVBoxLayout()
        left.setSpacing(12)

        # patient form
        pgrid = QGridLayout()
        pgrid.setSpacing(8)
        pgrid.setColumnStretch(1, 1)
        pgrid.setColumnStretch(3, 1)
        self.title = QComboBox()
        self.title.addItems(TITLES)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Patient name *")
        self.name.setMaxLength(
            60
        )  # snapshotted onto receipts/reports — keep it bounded
        self.mr_no = QLineEdit()
        self.mr_no.setPlaceholderText("auto if blank")
        self.mr_no.setMaxLength(20)
        self.age = QSpinBox()
        self.age.setMaximum(150)
        self.age_desc = QComboBox()
        self.age_desc.addItems(AGE_UNITS)
        self.sex = QComboBox()
        self.sex.addItems(SEXES)
        self.tel = QLineEdit()
        self.tel.setPlaceholderText("Telephone / WhatsApp")
        self.tel.setMaxLength(20)
        self.address = QLineEdit()
        self.address.setPlaceholderText("Address")
        self.address.setMaxLength(120)
        self.doctor = QComboBox()
        self.doctor.setEditable(True)
        self.doctor.lineEdit().setMaxLength(50)  # snapshotted as dr_name on reports
        self.specimen = QComboBox()
        self.specimen.setEditable(True)
        self.specimen.lineEdit().setMaxLength(40)
        self.update_specimen_options()  # presets (no cart yet)
        # editing identity fields by hand breaks any "returning patient" link
        self.name.textEdited.connect(self._unlink)
        self.tel.textEdited.connect(self._unlink)
        self.mr_no.textEdited.connect(self._unlink)
        age_box = QHBoxLayout()
        age_box.setContentsMargins(0, 0, 0, 0)
        age_box.addWidget(self.age)
        age_box.addWidget(self.age_desc)
        age_w = QWidget()
        age_w.setLayout(age_box)
        pgrid.addWidget(field_label("Title"), 0, 0)
        pgrid.addWidget(self.title, 0, 1)
        pgrid.addWidget(field_label("Name"), 0, 2)
        pgrid.addWidget(self.name, 0, 3)
        pgrid.addWidget(field_label("Age"), 1, 0)
        pgrid.addWidget(age_w, 1, 1)
        pgrid.addWidget(field_label("Sex"), 1, 2)
        pgrid.addWidget(self.sex, 1, 3)
        pgrid.addWidget(field_label("Patient ID"), 2, 0)
        pgrid.addWidget(self.mr_no, 2, 1)
        pgrid.addWidget(field_label("Phone"), 2, 2)
        pgrid.addWidget(self.tel, 2, 3)
        pgrid.addWidget(field_label("Address"), 3, 0)
        pgrid.addWidget(self.address, 3, 1, 1, 3)
        pgrid.addWidget(field_label("Doctor"), 4, 0)
        pgrid.addWidget(self.doctor, 4, 1, 1, 3)
        pgrid.addWidget(field_label("Specimen"), 5, 0)
        pgrid.addWidget(self.specimen, 5, 1, 1, 3)
        pform = QWidget()
        pform.setLayout(pgrid)
        # returning-patient lookup (phone is the practical key patients remember)
        self.find = QLineEdit()
        self.find.setPlaceholderText(
            "🔍  Returning patient? search phone / Patient ID / name"
        )
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
        self.wa_consent = QCheckBox(
            "Send reports and bills to this patient on WhatsApp"
        )
        self.wa_consent.setChecked(True)
        self.wa_consent.setToolTip(
            "Reports/bills are delivered through WhatsApp (Meta). Untick if the "
            "patient does not want messages sent to their number."
        )
        # previous visits of a picked returning patient (hidden until one is chosen)
        self.prev_lbl = muted("Previous visits")
        self.prev_lbl.hide()
        self.prev_visits = QListWidget()
        self.prev_visits.setMaximumHeight(108)
        self.prev_visits.setEditTriggers(QListWidget.NoEditTriggers)
        self.prev_visits.hide()
        patient_card = card(
            self.find,
            self.find_results,
            self.linked_lbl,
            pform,
            self.wa_consent,
            self.prev_lbl,
            self.prev_visits,
            title="Patient",
        )
        patient_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        left.addWidget(patient_card)

        # test search
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.test_search = QLineEdit()
        self.test_search.setPlaceholderText(
            "Search test by name or number… (type, then double-click)"
        )
        self.test_search.setMinimumHeight(38)
        self.test_search.textChanged.connect(tasks.debounce(self, self.search_tests))
        self.panel_btn = QPushButton("Add panel ▾")
        self.panel_btn.setObjectName("ghost")
        self.panel_btn.setMinimumHeight(38)
        self.panel_btn.setToolTip("Add every test in a saved panel / profile at once")
        self.panel_btn.clicked.connect(self._show_panel_menu)
        search_row.addWidget(self.test_search, 1)
        search_row.addWidget(self.panel_btn)
        search_w = QWidget()
        search_w.setLayout(search_row)
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
        ch.setSectionResizeMode(0, QHeaderView.Stretch)  # test name grows
        ch.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # charge
        ch.setSectionResizeMode(2, QHeaderView.Fixed)
        self.cart_table.setColumnWidth(2, 42)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setEditTriggers(QTableWidget.NoEditTriggers)
        cart_card = card(self.cart_table, title="Selected tests")
        cart_card.layout().setStretch(cart_card.layout().count() - 1, 1)
        right.addWidget(cart_card, 1)

        # totals
        tgrid = QGridLayout()
        tgrid.setSpacing(9)
        tgrid.setColumnStretch(1, 1)
        self.subtotal = QLabel("—")
        self.subtotal.setStyleSheet("font-weight:700;")
        self.discount = QDoubleSpinBox()
        self.discount.setMaximum(100)
        self.discount.setSuffix(" %")
        self.discount.valueChanged.connect(self.recompute)
        # A discount needs manager/admin rights; a cashier must get it approved.
        self._can_discount = roles.can(self.user["role"], "apply_discount")
        self._discount_approved_by = None
        self._discount_approved_pct = 0.0  # ceiling a manager approved for a cashier
        self.discount_lock = QPushButton("🔒 Approve")
        self.discount_lock.setObjectName("ghost")
        self.discount_lock.setToolTip("A discount needs manager/admin approval")
        self.discount_lock.clicked.connect(self._request_discount_approval)
        drow = QHBoxLayout()
        drow.setContentsMargins(0, 0, 0, 0)
        drow.setSpacing(6)
        drow.addWidget(self.discount, 1)
        if not self._can_discount:
            drow.addWidget(self.discount_lock)
            self.discount.setEnabled(False)
        dwrap = QWidget()
        dwrap.setLayout(drow)
        self.net = QLabel("—")
        self.net.setStyleSheet("font-weight:800;font-size:18px;color:#0a5f67;")
        self.paid = QDoubleSpinBox()
        self.paid.setMaximum(1_000_000)
        self.paid.setPrefix("Rs. ")
        self.paid.valueChanged.connect(self.recompute)
        self.due = QLabel("—")
        self.due.setStyleSheet("font-weight:800;font-size:15px;color:#c0392b;")
        # change to hand back when the customer overpays (paid > net)
        self.change = QLabel("—")
        self.change.setStyleSheet("font-weight:800;font-size:15px;color:#1f9d55;")
        self.change_lbl = field_label("Change to return")
        self.change.setVisible(False)
        self.change_lbl.setVisible(False)
        tgrid.addWidget(field_label("Subtotal"), 0, 0)
        tgrid.addWidget(self.subtotal, 0, 1, Qt.AlignRight)
        tgrid.addWidget(field_label("Discount"), 1, 0)
        tgrid.addWidget(dwrap, 1, 1)
        tgrid.addWidget(field_label("Net payable"), 2, 0)
        tgrid.addWidget(self.net, 2, 1, Qt.AlignRight)
        tgrid.addWidget(field_label("Paid"), 3, 0)
        tgrid.addWidget(self.paid, 3, 1)
        self.payment_method = QComboBox()
        self.payment_method.addItems(PAYMENT_METHODS)
        tgrid.addWidget(field_label("Payment method"), 4, 0)
        tgrid.addWidget(self.payment_method, 4, 1)
        tgrid.addWidget(field_label("Due"), 5, 0)
        tgrid.addWidget(self.due, 5, 1, Qt.AlignRight)
        tgrid.addWidget(self.change_lbl, 6, 0)
        tgrid.addWidget(self.change, 6, 1, Qt.AlignRight)
        tw = QWidget()
        tw.setLayout(tgrid)
        pay_card = card(tw, title="Payment")
        pay_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        right.addWidget(pay_card)

        btns = QHBoxLayout()
        # NB: clicked(checked) passes a bool — wrap so do_print stays True
        save = QPushButton("Save && Print receipt")
        save.setMinimumHeight(42)
        save.clicked.connect(lambda: self.save(do_print=True))
        save_only = QPushButton("Save (no print)")
        save_only.setObjectName("ghost")
        save_only.clicked.connect(lambda: self.save(do_print=False))
        clear = QPushButton("Clear")
        clear.setObjectName("ghost")
        clear.clicked.connect(self.clear_form)
        btns.addWidget(clear)
        btns.addStretch(1)
        btns.addWidget(save_only)
        btns.addWidget(save)
        right.addLayout(btns)
        body.addLayout(right, 2)

        root.addLayout(body, 1)

        # keyboard shortcuts: Ctrl+S save & print, Ctrl+Enter save (no print)
        QShortcut(
            QKeySequence("Ctrl+S"), self, activated=lambda: self.save(do_print=True)
        )
        QShortcut(
            QKeySequence("Ctrl+Return"),
            self,
            activated=lambda: self.save(do_print=False),
        )
        QShortcut(
            QKeySequence("Ctrl+Enter"),
            self,
            activated=lambda: self.save(do_print=False),
        )
        # Enter in the test search adds the top match
        self.test_search.returnPressed.connect(self._add_top_test)

    # ---------------------------------------------------------------
    def on_show(self) -> None:
        self.load_doctors()
        if self.results.count() == 0:
            self.search_tests("")
        if not self.cart:
            self._apply_promo()
            self.recompute()

    # ---- discount approval + special-day promo --------------------
    def _request_discount_approval(self) -> None:
        """A cashier asks a manager/admin to approve a discount on this bill."""
        u, ok = QInputDialog.getText(
            self, "Manager approval", "Manager / Admin username:"
        )
        if not ok or not u.strip():
            return
        p, ok = QInputDialog.getText(
            self, "Manager approval", f"Password for {u.strip()}:", QLineEdit.Password
        )
        if not ok:
            return
        approver = db.verify_user(self.con, u.strip(), p)
        if not approver or not roles.can(approver["role"], "apply_discount"):
            # audit the failed approval attempt (brute-force of a manager password)
            db.log_audit(
                self.con,
                self.user["username"],
                "discount_approval_failed",
                f"attempted approver: {u.strip() or '(blank)'}",
            )
            toast_warn(
                self,
                "Approval",
                "Invalid credentials, or that user can't approve discounts.",
            )
            return
        # Bind the approval to a concrete amount the manager authorises — otherwise
        # the cashier could be approved for "a discount" and then type any value.
        pct, ok = QInputDialog.getDouble(
            self,
            "Approve discount",
            "Approved discount %:",
            float(self.discount.value()),
            0.0,
            100.0,
            2,
        )
        if not ok:
            return
        self._discount_approved_by = approver["username"]
        self._discount_approved_pct = pct
        self.discount.setValue(pct)
        self.discount.setMaximum(pct)  # hard-cap the field to what was approved
        self.discount.setEnabled(True)
        self.discount_lock.setText(f"✓ {roles.role_label(approver['role'])} — {pct:g}%")
        self.discount_lock.setEnabled(False)
        db.log_audit(
            self.con,
            self.user["username"],
            "discount_approved",
            f"by {approver['username']} — {pct:g}%",
        )
        self.discount.setFocus()

    def _promo_pct(self) -> float:
        """Active special-day discount %, honouring the optional end date."""
        return billing.get_active_promo_discount(self.con)

    def _apply_promo(self) -> None:
        pct = self._promo_pct()
        self.discount.blockSignals(True)
        self.discount.setValue(pct)  # auto-apply the special-day discount
        self.discount.blockSignals(False)

    def load_doctors(self) -> None:
        cur = self.doctor.currentText()
        self.doctor.clear()
        self.doctor.addItem("", None)
        self._doctors = self.con.execute(
            "SELECT id, name FROM doctors WHERE active=1 ORDER BY name"
        ).fetchall()
        for d in self._doctors:
            self.doctor.addItem(d["name"], d["id"])
        self.doctor.setCurrentText(cur)

    # ---- specimen options driven by the chosen tests --------------
    def update_specimen_options(self) -> None:
        """Offer each cart test's `sample_required` as a specimen option (plus the
        standard presets); auto-select when there is a single specimen."""
        cur = self.specimen.currentText().strip()
        ids = [c["test_id"] for c in self.cart]
        cart_specs = []
        if ids:
            q = (
                "SELECT DISTINCT sample_required FROM tests WHERE id IN ({}) "
                "AND sample_required<>''".format(",".join("?" * len(ids)))
            )
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

    def statusBar_message(self, msg: str) -> None:
        """Show a brief, self-clearing confirmation toast (top-right, non-blocking)."""
        toast_info(self, "", msg)

    # ---------------------------------------------------------------
    def save(self, do_print=True):
        # Auto-format the typed name to proper case (MUHAMMAD USMAN / muhammad usman
        # → Muhammad Usman) so it stores and prints tidily however it was entered.
        name = format_person_name(self.name.text())
        if name:
            self.name.setText(name)  # reflect the tidy form back in the field
        # require a real name — not blank, and not digits/punctuation only
        if not name or not re.search(r"[^\W\d_]", name):
            toast_warn(self, "Reception", "Enter a valid patient name.")
            return
        if not self.cart:
            toast_warn(self, "Reception", "Add at least one test.")
            return
        # Re-validate the discount at save (defence-in-depth — don't trust only the
        # widget's enabled state). A discount ABOVE the auto-applied promo needs the
        # apply_discount capability or a recorded manager approval.
        if self.discount.value() > self._promo_pct() + 1e-9 and not roles.can(
            self.user["role"], "apply_discount"
        ):
            # a cashier needs an approval, AND the discount must not exceed the amount
            # the manager actually approved (not merely "a discount was approved").
            ceiling = max(self._promo_pct(), self._discount_approved_pct)
            if not self._discount_approved_by or self.discount.value() > ceiling + 1e-9:
                toast_warn(
                    self,
                    "Discount",
                    "A discount above the promo needs manager/admin approval "
                    "for that amount.",
                )
                return
        c = self.con
        title = self.title.currentText().strip()
        mr_no = self.mr_no.text().strip()
        # A manually-entered Patient ID in the new YY-…-NN<L> format is typo-checked via
        # its trailing check letter. Accept it typed WITHOUT the dashes (e.g. 2600043K)
        # by re-inserting them, and store our-format ids in canonical UPPER-dashed form.
        # Legacy 'MR…' / free-form ids pass through unchanged.
        cand = mr_no.upper()
        m = re.fullmatch(r"(\d{2})(\d{3})(\d{2})([A-Z])", cand)
        if m:
            cand = f"{m.group(1)}-{m.group(2)}-{m.group(3)}{m.group(4)}"
        if cand[:2].isdigit() and "-" in cand:  # looks like our new Patient-ID format
            if not db.validate_patient_id(cand):
                toast_warn(
                    self,
                    "Patient ID",
                    "That Patient ID looks mistyped — its check letter doesn't match.\n"
                    "Leave it blank to auto-generate one, or re-enter it correctly.",
                )
                return
            mr_no = cand  # canonical form
        specimen = self.specimen.currentText().strip()
        cc = db.get_setting(c, "whatsapp_country_code", "92") or "92"
        tel = normalize_phone(self.tel.text(), cc)
        age = self.age.value()
        age_desc = self.age_desc.currentText()
        sex = self.sex.currentText()
        addr = format_address(self.address.text())
        # Resolve the patient identity:
        #  1) an explicitly picked "returning patient", else
        #  2) auto-match on (canonical phone + same name), else
        #  3) a brand-new patient with an auto-assigned Patient ID.
        pid = self._existing_patient_id
        if not pid and tel:
            m = c.execute(
                "SELECT id FROM patients WHERE telephone=? AND lower(name)=lower(?) "
                "ORDER BY id DESC LIMIT 1",
                (tel, name),
            ).fetchone()
            if m:
                pid = m["id"]
        doc_id = self.doctor.currentData()
        doc_name = self.doctor.currentText().strip()
        # compute totals directly (don't depend on cached recompute state), exactly
        # in integer paisa so a discount can't leave a sub-cent "phantom due"
        disc_pct = self.discount.value()
        totals = billing.compute_bill_totals(self.cart, disc_pct, self.paid.value())
        sub = totals["subtotal"]
        net = totals["net"]
        paid = totals["paid"]
        due = totals["due"]
        pay_method = self.payment_method.currentText()
        optout = 0 if self.wa_consent.isChecked() else 1
        # All writes + authorization + audit happen at the service boundary; the view
        # keeps validation, money computation, and the print/WhatsApp UX. A failure
        # rolls back inside the service (nothing charged) and is surfaced here.
        try:
            res = receipts_svc.create_receipt(
                c,
                receipts_svc.BillDraft(
                    existing_patient_id=pid,
                    title=title,
                    mr_no=mr_no,
                    name=name,
                    age=age,
                    age_desc=age_desc,
                    sex=sex,
                    telephone=tel,
                    address=addr,
                    wa_optout=optout,
                    doctor_id=doc_id,
                    doctor_name=doc_name,
                    specimen=specimen,
                    items=self.cart,
                    subtotal=sub,
                    discount_pct=disc_pct,
                    net=net,
                    paid=paid,
                    due=due,
                    payment_method=pay_method,
                    discount_approved_by=self._discount_approved_by,
                    promo_pct=self._promo_pct(),
                ),
                actor_username=self.user["username"],
                actor_role=self.user["role"],
            )
        except PermissionError:
            toast_warn(
                self, "Not allowed", "You don't have permission to create bills."
            )
            return
        except (sqlite3.Error, RuntimeError) as e:
            toast_warn(
                self,
                "Save failed",
                "The receipt was NOT saved — nothing has been charged. "
                f"Please try again.\n\n{e}",
            )
            return
        rid = res.receipt_id
        lab_no = res.lab_no
        # non-blocking inline confirmation (no modal to dismiss → save feels instant)
        self.statusBar_message(f"✓ Receipt {lab_no} saved.")
        if do_print:
            # native render is fast and prints straight onto the printer (vector);
            # a print failure here never loses the already-saved receipt.
            try:
                report.print_receipt(self.con, rid, self)
            except Exception as e:
                toast_warn(
                    self, "Print", f"Saved as {lab_no}, but printing failed:\n{e}"
                )
        # optional: auto-send the bill on WhatsApp (gated silently so it never
        # nags when WhatsApp isn't set up or the patient has no number)
        if (
            db.get_setting(self.con, "whatsapp_auto_receipt", "0") == "1"
            and whatsapp.config_ready(self.con)[0]
            and whatsapp.recipient_ready(self.con, rid)[0]
        ):
            wa.send_async(self, self.con, "receipt", rid)
        self.clear_form()

    def clear_form(self) -> None:
        self.cart = []
        self._existing_patient_id = None
        self.linked_lbl.hide()
        self.prev_lbl.hide()
        self.prev_visits.hide()
        for w in (
            self.name,
            self.tel,
            self.address,
            self.mr_no,
            self.test_search,
            self.find,
        ):
            w.clear()
        self.find_results.hide()
        self.title.setCurrentIndex(0)
        self.specimen.setCurrentIndex(0)
        self.age.setValue(0)
        self.paid.setValue(0)
        self.wa_consent.setChecked(True)
        self.payment_method.setCurrentIndex(0)
        # reset the discount-approval lock + approved ceiling for cashiers, then
        # re-apply any promo
        self._discount_approved_by = None
        self._discount_approved_pct = 0.0
        self.discount.setMaximum(100)  # undo the per-approval cap
        if not self._can_discount:
            self.discount.setEnabled(False)
            self.discount_lock.setText("🔒 Approve")
            self.discount_lock.setEnabled(True)
        self._apply_promo()
        self.search_tests("")
        self.refresh_cart()
