"""Returning-patient search / pick / history, split out of ReceptionPage."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from .. import db
from .widgets import money


class ReceptionPatientMixin:
    def _unlink(self, *_) -> None:
        """Hand-editing identity fields detaches any picked patient."""
        if self._existing_patient_id is not None:
            self._existing_patient_id = None
            self.linked_lbl.hide()
            self.prev_lbl.hide()
            self.prev_visits.hide()

    def search_patients(self, text: str | None = None) -> None:
        text = (self.find.text() if text is None else text).strip()
        self.find_results.clear()
        if len(text) < 2:
            self.find_results.hide()
            return
        like = f"%{text}%"
        # one row per patient (no GROUP BY on phone — family members can share a number)
        rows = self.con.execute(
            """SELECT id,title,name,age,age_desc,sex,telephone,address,mr_no
               FROM patients
               WHERE name LIKE ? OR telephone LIKE ? OR mr_no LIKE ?
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

    def pick_patient(self, item: QListWidgetItem | None) -> None:
        if item is None:  # itemActivated can fire with no item (Enter on empty list)
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
            f"✓ Linked to existing patient {r['mr_no'] or ''} — new visit will join their history"
        )
        self.linked_lbl.show()
        self._show_previous_visits(pid)
        self.find.clear()
        self.find_results.hide()

    def _show_previous_visits(self, pid: int) -> None:
        """List this patient's recent receipts so reception sees their history."""
        cur = db.currency(self.con)
        rows = self.con.execute(
            "SELECT lab_no, received_at, net_amount, due, status FROM receipts "
            f"WHERE patient_id=? AND {db.NOT_VOIDED} ORDER BY id DESC LIMIT 12",
            (pid,),
        ).fetchall()
        self.prev_visits.clear()
        if not rows:
            self.prev_lbl.hide()
            self.prev_visits.hide()
            return
        for r in rows:
            when = (r["received_at"] or "")[:10]
            due = f" · due {money(r['due'], cur)}" if r["due"] else ""
            st = (r["status"] or "").replace("_", " ")
            it = QListWidgetItem(
                f"{r['lab_no'] or ''}  ·  {when}  ·  {money(r['net_amount'] or 0, cur)}  ·  {st}{due}"
            )
            if r["due"]:
                it.setForeground(Qt.red)
            self.prev_visits.addItem(it)
        self.prev_lbl.setText(f"Previous visits ({len(rows)})")
        self.prev_lbl.show()
        self.prev_visits.show()
