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
    """Sidebar wrapper around the shared logo autocrop (``render.autocrop_image``), so
    the sidebar brand mark and the printed report/receipt letterhead trim margins with
    exactly the same logic — one source of truth."""
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
    def __init__(self, con, user) -> None:
        super().__init__()
        self.con = con
        self.user = user
        lab = db.get_setting(con, "lab_name", "") or PRODUCT_NAME
        # window title = just the lab's own name (cleaner than repeating "Laboratory")
        self.setWindowTitle(lab)
        # Rule 3 (split-screen snapping): a logical minimum WIDTH of 1280 so the app
        # stays usable when snapped to a half-screen layout (e.g. half of a 2560
        # monitor). The wrapping toolbar + scroll view keep all content within 1280,
        # so nothing is clipped at the minimum. The minimum HEIGHT is kept at 640
        # (not 720) so a 1280x720 panel whose taskbar leaves ~680 px usable doesn't
        # push the window bottom under the taskbar; the page scrolls if shorter.
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
        # brand mark: the lab's configured logo, else the bundled product logo
        logo_path = db.get_setting(con, "logo_path", "")
        logo_file = (
            logo_path if (logo_path and Path(logo_path).exists()) else str(ASSET_LOGO)
        )
        pm = QPixmap(logo_file)
        if not pm.isNull():
            logo = QLabel()
            logo.setObjectName("SidebarLogo")
            # 1) trim any white/transparent margins baked into the logo file (the
            #    reason it looked tiny inside a big white box), then 2) fit it to the
            #    card's inner box (≈190px wide, ≤132px tall) keeping aspect so it's as
            #    large as possible and NEVER clipped. The old scaledToHeight(96) locked
            #    height and ignored width, so a wide logo overflowed and was cut.
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

        # Only show pages this user's role level permits.
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

        # developer credit footer
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
        # Wrap the page area in a scroll view so the window can shrink BELOW the
        # content's natural width (e.g. a snapped half-screen) and scroll, instead
        # of the layout forcing the window wider than the monitor. On normal-width
        # screens the page fills the viewport and no scrollbar shows.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.stack)
        # Rule 2 (vertical-space utilisation): the page area expands in BOTH axes so
        # it soaks up the extra height on 16:10 / 3:2 panels instead of leaving dead
        # space. The pages' own tables already expand to fill this.
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cl.addWidget(scroll, 1)
        root.addWidget(content, 1)

        # Alt+1..9 jump straight to a sidebar page
        for i in range(min(9, len(self.pages))):
            QShortcut(
                QKeySequence(f"Alt+{i + 1}"), self, activated=lambda idx=i: self.go(idx)
            )

        # No bottom status bar — transient notices are shown inline on the page
        # itself (e.g. Reception's "Added N tests" toast).
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
        # Hide the page content while locked so patient data / financials aren't left
        # visible (or screenshot-able) behind the sign-in modal.
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
            central.show()  # same user re-authenticated — reveal the (still-valid) session
        if accepted:
            if dlg.user["username"] != self.user["username"]:
                # A *different* user unlocked the screen. The open pages were built
                # for — and still carry the identity/privileges of — the user who
                # locked it. Don't let them be operated under the new identity; end
                # this session so the new user starts their own (correct) one.
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
        # records sign-out (the "Sign out" button calls close()) and window close.
        # Guarded: closing must never fail, even if the DB connection is unusable.
        if not getattr(self, "_logged_out", False):
            self._logged_out = True
            with contextlib.suppress(Exception):
                db.log_audit(self.con, self.user["username"], "logout", "session ended")
        self._auto_backup_on_exit()
        super().closeEvent(event)

    def _auto_backup_on_exit(self) -> None:
        """Write an automatic encrypted backup as LabDesk closes — the session is
        still unlocked here, so no password is needed. Skipped after a restore (the
        DB file was just swapped out) and in headless self-test. Never blocks or
        fails the close."""
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

    # Rule 5 (responsive resizing): collapse the 230 px sidebar when the window gets
    # narrow so the page keeps its working width. The 1280 minimum means this is a
    # graceful-degradation safety net for out-of-spec widths (e.g. fractional Wayland
    # scaling pushing the logical width down); navigation stays available via Alt+1..9.
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
        """Jump to a page by its NAV label (used by dashboard cards). Extra kwargs
        are passed to the target page's apply_nav() if it defines one."""
        idx = self._page_index.get(label)
        if idx is None:
            return
        self.go(idx)
        page = self.pages[idx]
        if kwargs and hasattr(page, "apply_nav"):
            page.apply_nav(**kwargs)
