"""Main application window: sidebar navigation + stacked pages."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QPushButton, QLabel, QButtonGroup,
)

from .. import db

# bundled product logo (also the per-lab fallback brand mark)
ASSET_LOGO = Path(__file__).resolve().parent.parent / "assets" / "app_logo.png"
from ..roles import can_view_page, role_label
from .style import PRODUCT_NAME, PRODUCT_TAGLINE
from .dashboard import DashboardPage
from .reception import ReceptionPage
from .receipts import ReceiptsPage
from .worklist import WorklistPage
from .catalog import CatalogPage
from .doctors import DoctorsPage
from .microbiology import MicrobiologyPage
from .accounts import AccountsPage
from .settings import SettingsPage
from .logs import LogsPage


NAV = [
    ("Dashboard", DashboardPage),
    ("Reception / Billing", ReceptionPage),
    ("Receipts / Reports", ReceiptsPage),
    ("Worklist / Results", WorklistPage),
    ("Test Catalog", CatalogPage),
    ("Doctors", DoctorsPage),
    ("Microbiology", MicrobiologyPage),
    ("Accounts", AccountsPage),
    ("Settings", SettingsPage),
    ("Logs", LogsPage),
]


class MainWindow(QMainWindow):
    def __init__(self, con, user):
        super().__init__()
        self.con = con
        self.user = user
        lab = db.get_setting(con, "lab_name", "") or PRODUCT_NAME
        # window title = just the lab's own name (cleaner than repeating "Laboratory")
        self.setWindowTitle(lab)
        self.resize(1240, 800)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- sidebar ----
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)

        sb.addSpacing(16)
        # brand mark: the lab's configured logo, else the bundled product logo
        logo_path = db.get_setting(con, "logo_path", "")
        logo_file = logo_path if (logo_path and Path(logo_path).exists()) else str(ASSET_LOGO)
        pm = QPixmap(logo_file)
        if not pm.isNull():
            logo = QLabel()
            logo.setObjectName("SidebarLogo")
            logo.setPixmap(pm.scaledToHeight(96, Qt.SmoothTransformation))
            logo.setAlignment(Qt.AlignHCenter)
            sb.addWidget(logo)
            sb.addSpacing(8)
        brand = QLabel(lab)
        brand.setObjectName("SidebarBrand")
        brand.setWordWrap(True)
        brand.setAlignment(Qt.AlignHCenter)
        sb.addWidget(brand)
        brand_sub = QLabel(db.get_setting(con, "lab_subtitle", "") or PRODUCT_TAGLINE)
        brand_sub.setObjectName("SidebarSub")
        brand_sub.setWordWrap(True)
        sb.addWidget(brand_sub)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)
        self.stack = QStackedWidget()
        self.pages = []

        # Only show pages this user's role level permits.
        visible = [(lbl, cls) for (lbl, cls) in NAV if can_view_page(user["role"], lbl)]
        self._page_index = {}
        for i, (label, PageCls) in enumerate(visible):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, idx=i: self.go(idx))
            sb.addWidget(btn)
            self.btn_group.addButton(btn, i)
            page = PageCls(con, user)
            page.setObjectName("page")
            page.navigate = self.navigate_to   # let pages jump to other pages
            self._page_index[label] = i
            self.pages.append(page)
            self.stack.addWidget(page)

        sb.addStretch(1)
        uname = user["full_name"] or user["username"]
        urole = role_label(user["role"])
        userlbl = QLabel(f"👤 {uname}" if uname == urole else f"👤 {uname}\n{urole}")
        userlbl.setObjectName("SidebarUser")
        sb.addWidget(userlbl)
        logout = QPushButton("Sign out")
        logout.setStyleSheet(
            "QPushButton{margin:10px 16px 18px 16px; background:rgba(255,255,255,0.12);"
            "color:#eafafb; border:1px solid rgba(255,255,255,0.35); border-radius:8px;"
            "padding:9px 16px; font-weight:700;}"
            "QPushButton:hover{background:rgba(255,255,255,0.22);}"
        )
        logout.clicked.connect(self.close)
        sb.addWidget(logout)

        root.addWidget(sidebar)

        # ---- content ----
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(22, 18, 22, 18)
        cl.addWidget(self.stack)
        root.addWidget(content, 1)

        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("Ready")
        self.btn_group.button(0).setChecked(True)
        self.go(0)

    def go(self, idx: int):
        self.stack.setCurrentIndex(idx)
        page = self.pages[idx]
        if hasattr(page, "on_show"):
            page.on_show()
        self.btn_group.button(idx).setChecked(True)

    def navigate_to(self, label: str, **kwargs):
        """Jump to a page by its NAV label (used by dashboard cards). Extra kwargs
        are passed to the target page's apply_nav() if it defines one."""
        idx = self._page_index.get(label)
        if idx is None:
            return
        self.go(idx)
        page = self.pages[idx]
        if kwargs and hasattr(page, "apply_nav"):
            page.apply_nav(**kwargs)
