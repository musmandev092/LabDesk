"""Dashboard: at-a-glance stats."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout

from .widgets import page_header, stat_card, money, card, h2, muted
from .style import ACCENT, DANGER, PRIMARY_DARK, AMBER
from .. import db


class DashboardPage(QWidget):
    def __init__(self, con, user):
        super().__init__()
        self.con = con
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lab = db.get_setting(con, "lab_name", "") or "your laboratory"
        header, self.sub = page_header("Dashboard", f"Welcome back — {lab}")
        lay.addWidget(header)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_receipts = stat_card("Receipts today", "0",
                                    on_click=lambda: self._go("Receipts / Reports", today=True))
        self.c_income = stat_card("Income today", "—", ACCENT,
                                  on_click=lambda: self._go("Accounts"))
        self.c_pending = stat_card("Pending reports", "0", AMBER,
                                   on_click=lambda: self._go("Worklist / Results"))
        self.c_tests = stat_card("Tests in catalog", "0", PRIMARY_DARK,
                                 on_click=lambda: self._go("Test Catalog"))
        for i, w in enumerate((self.c_receipts, self.c_income, self.c_pending, self.c_tests)):
            grid.addWidget(w, 0, i)
            grid.setColumnStretch(i, 1)
        lay.addLayout(grid)

        steps = [
            "1.  Reception / Billing — register a patient and create an invoice.",
            "2.  Worklist / Results — enter results and print or WhatsApp the report.",
            "3.  Microbiology — enter culture & sensitivity findings.",
            "4.  Settings — update your lab branding, logo and registration numbers.",
        ]
        step_labels = []
        for s in steps:
            lbl = muted(s); lbl.setWordWrap(True); step_labels.append(lbl)
        lay.addWidget(card(*step_labels, title="Getting started"))
        lay.addStretch(1)

    def _go(self, label, **kw):
        nav = getattr(self, "navigate", None)
        if nav:
            nav(label, **kw)

    def on_show(self):
        c = self.con
        currency = db.get_setting(c, "currency", "Rs.")
        lab = db.get_setting(c, "lab_name", "") or "your laboratory"
        self.sub.setText(f"Welcome back — {lab}")
        n_rec = c.execute(
            "SELECT COUNT(*) FROM receipts WHERE COALESCE(voided,0)=0 "
            "AND received_at >= date('now','localtime') "
            "AND received_at < date('now','localtime','+1 day')"
        ).fetchone()[0]
        income = c.execute(
            "SELECT COALESCE(SUM(paid),0) FROM receipts WHERE COALESCE(voided,0)=0 "
            "AND received_at >= date('now','localtime') "
            "AND received_at < date('now','localtime','+1 day')"
        ).fetchone()[0]
        pending = c.execute(
            "SELECT COUNT(*) FROM receipts WHERE status IN ('pending','in_progress') "
            "AND COALESCE(voided,0)=0"
        ).fetchone()[0]
        n_tests = c.execute("SELECT COUNT(*) FROM tests WHERE active=1").fetchone()[0]
        self.c_receipts.value_label.setText(str(n_rec))
        self.c_income.value_label.setText(money(income, currency))
        self.c_pending.value_label.setText(str(pending))
        self.c_tests.value_label.setText(str(n_tests))
