"""Main application window: sidebar navigation + stacked pages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import db, render
from .._resources import package_root

# bundled product logo (also the per-lab fallback brand mark)
ASSET_LOGO = package_root() / "assets" / "app_logo.png"


def _autocrop(pm: QPixmap) -> QPixmap:
    """Sidebar wrapper around the shared logo autocrop used by printed reports."""
    return QPixmap.fromImage(render.autocrop_image(pm.toImage()))


from .. import __version__
from ..roles import can_view_page, role_label
from .accounts import AccountsPage
from .catalog import CatalogPage
from .dashboard import DashboardPage
from .doctors import DoctorsPage
from .logs import LogsPage
from .microbiology import MicrobiologyPage
from .receipts import ReceiptsPage
from .reception import ReceptionPage
from .settings import SettingsPage
from .style import DEVELOPER, DEVELOPER_GITHUB, PRODUCT_NAME, PRODUCT_TAGLINE
from .worklist import WorklistPage
import contextlib

NAV = [
    ("Dashboard", DashboardPage),
    ("Reception / Billing", ReceptionPage),
    ("Worklist / Results", WorklistPage),
    ("Receipts / Reports", ReceiptsPage),
    ("Test Catalog", CatalogPage),
    ("Doctors", DoctorsPage),
    ("Microbiology", MicrobiologyPage),
    ("Accounts", AccountsPage),
    ("Settings", SettingsPage),
    ("Logs", LogsPage),
]


class MainWindow(QMainWindow):
    def __init__(self, con, user) -> None:
        super().__init__()
        self.con = con
        self.user = user
        lab = db.get_setting(con, "lab_name", "") or PRODUCT_NAME
        self.setWindowTitle(lab)
        # min width 1280 keeps the app usable half-screen; min height 640 (not 720)
        # avoids pushing under the taskbar on a 1280x720 panel — page scrolls if shorter
        self.setMinimumSize(1280, 640)
        self.resize(1280, 820)  # windowed-fallback size; showMaximized() at launch

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- sidebar ----
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        self._sidebar = sidebar  # kept for the responsive resizeEvent (Rule 5)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)

        sb.addSpacing(16)
        logo_path = db.get_setting(con, "logo_path", "")
        logo_file = (
            logo_path if (logo_path and Path(logo_path).exists()) else str(ASSET_LOGO)
        )
        pm = QPixmap(logo_file)
        if not pm.isNull():
            logo = QLabel()
            logo.setObjectName("SidebarLogo")
            # trim baked-in margins, then fit to the sidebar box keeping aspect ratio
            pm = _autocrop(pm)
            logo.setPixmap(
                pm.scaled(190, 132, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
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

        visible = [(lbl, cls) for (lbl, cls) in NAV if can_view_page(user["role"], lbl)]
        self._page_index = {}
        for i, (label, PageCls) in enumerate(visible):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, idx=i: self.go(idx))
            sb.addWidget(btn)
            self.btn_group.addButton(btn, i)
            page: QWidget = PageCls(con, user)
            page.setObjectName("page")
            page.navigate = self.navigate_to  # let pages jump to other pages
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

        credit = QLabel(
            f"{PRODUCT_NAME} v{__version__}\nDeveloped by {DEVELOPER}\n{DEVELOPER_GITHUB}"
        )
        credit.setObjectName("SidebarCredit")
        credit.setAlignment(Qt.AlignCenter)
        sb.addWidget(credit)

        root.addWidget(sidebar)

        # ---- content ----
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(22, 18, 22, 18)
        # scroll view lets the window shrink below the content's natural width
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.stack)
        # expand in both axes to fill extra height on tall aspect ratios
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cl.addWidget(scroll, 1)
        root.addWidget(content, 1)

        # Alt+1..9 jump straight to a sidebar page
        for i in range(min(9, len(self.pages))):
            QShortcut(
                QKeySequence(f"Alt+{i + 1}"), self, activated=lambda idx=i: self.go(idx)
            )

        # transient notices are shown inline on the page instead
        self.statusBar().hide()
        self.btn_group.button(0).setChecked(True)
        self.go(0)

        self._locked = False
        self._idle_ms = 0
        self._setup_idle_lock()

    # ---- idle auto-lock ----------------------------------------------------
    def _setup_idle_lock(self) -> None:
        try:
            mins = int(db.get_setting(self.con, "idle_lock_minutes", "0") or 0)
        except ValueError:
            mins = 0
        self._idle_ms = max(0, mins) * 60_000
        if self._idle_ms <= 0:
            return
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._lock_screen)
        QApplication.instance().installEventFilter(self)
        self._idle_timer.start(self._idle_ms)

    def eventFilter(self, obj, event) -> bool:
        if (
            self._idle_ms
            and not self._locked
            and event.type()
            in (
                QEvent.MouseMove,
                QEvent.KeyPress,
                QEvent.MouseButtonPress,
                QEvent.Wheel,
            )
        ):
            self._idle_timer.start(self._idle_ms)  # reset the countdown on activity
        return super().eventFilter(obj, event)

    def _lock_screen(self) -> None:
        if self._locked:
            return
        self._locked = True
        from .login import LoginDialog

        db.log_audit(self.con, self.user["username"], "logout", "auto-locked (idle)")
        # hide page content (patient data / financials) behind the sign-in modal
        central = self.centralWidget()
        if central is not None:
            central.hide()
        dlg = LoginDialog(self.con, self)
        dlg.setWindowTitle("Locked — sign in to continue")
        accepted = dlg.exec() == QDialog.Accepted and dlg.user is not None
        if (
            central is not None
            and accepted
            and dlg.user["username"] == self.user["username"]
        ):
            central.show()
        if accepted:
            if dlg.user["username"] != self.user["username"]:
                # a different user unlocked it — end this session; pages were built
                # for the identity/privileges of the user who locked it
                db.log_audit(
                    self.con,
                    self.user["username"],
                    "logout",
                    f"locked session ended — {dlg.user['username']} signed in instead",
                )
                self.close()
                return
            self.user = dlg.user
            db.log_audit(self.con, self.user["username"], "login", "unlocked")
            self._locked = False
            self._idle_timer.start(self._idle_ms)
        else:
            self.close()  # couldn't re-auth → end the session

    def closeEvent(self, event) -> None:
        # guarded: closing must never fail, even if the DB connection is unusable
        if not getattr(self, "_logged_out", False):
            self._logged_out = True
            with contextlib.suppress(Exception):
                db.log_audit(self.con, self.user["username"], "logout", "session ended")
        self._auto_backup_on_exit()
        super().closeEvent(event)

    def _auto_backup_on_exit(self) -> None:
        """Write an automatic encrypted backup on close; never blocks or fails it."""
        import os

        if os.environ.get("LABDESK_SELFTEST") == "1" or getattr(
            self, "_restoring", False
        ):
            return
        try:
            if (
                not db.is_unlocked()
                or db.get_setting(self.con, "auto_backup", "1") != "1"
            ):
                return
            try:
                keep = int(db.get_setting(self.con, "backup_keep", "14") or 14)
            except ValueError:
                keep = 14
            path, used_fallback = db.auto_backup(
                "exit", db.get_setting(self.con, "backup_dir", ""), keep=keep
            )
            if path:
                detail = str(path) + (
                    " [USB/network folder was unavailable — saved to Documents]"
                    if used_fallback
                    else ""
                )
                db.log_audit(self.con, self.user["username"], "backup_created", detail)
        except Exception:
            pass  # closing must never fail

    # collapse the sidebar below this width (e.g. fractional Wayland scaling);
    # navigation stays available via Alt+1..9
    _SIDEBAR_MIN_WIDTH = 1180

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        sidebar = getattr(self, "_sidebar", None)
        if sidebar is not None:
            sidebar.setVisible(self.width() >= self._SIDEBAR_MIN_WIDTH)

    def go(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        page = self.pages[idx]
        if hasattr(page, "on_show"):
            page.on_show()
        self.btn_group.button(idx).setChecked(True)

    def navigate_to(self, label: str, **kwargs) -> None:
        """Jump to a page by its NAV label, passing kwargs to its apply_nav()."""
        idx = self._page_index.get(label)
        if idx is None:
            return
        self.go(idx)
        page = self.pages[idx]
        if kwargs and hasattr(page, "apply_nav"):
            page.apply_nav(**kwargs)
