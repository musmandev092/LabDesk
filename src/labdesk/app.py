"""Application bootstrap: init DB, run first-run setup, login, main window."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from . import db
from .ui.style import QSS, PRODUCT_NAME, build_qss
from .ui.login import LoginDialog
from .ui.setup_wizard import SetupWizard
from .ui.main_window import MainWindow

# product icon (the microscope logo) — shown in the title bar + taskbar/dock
APP_ICON = Path(__file__).resolve().parent / "assets" / "app_icon_256.png"


def _acquire_single_instance():
    """Allow only one LabDesk window per user. Returns the QLocalServer when this
    process is the primary, or None when another instance is already running
    (after poking it to come to the front)."""
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    try:
        name = f"LabDesk-{os.getuid()}"
    except AttributeError:               # non-POSIX fallback
        name = "LabDesk-instance"
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(250):      # someone is already listening → that's the app
        probe.write(b"raise\n"); probe.flush(); probe.waitForBytesWritten(250)
        probe.disconnectFromServer()
        return None
    QLocalServer.removeServer(name)      # clear a stale socket from a crash
    server = QLocalServer()
    # only let the SAME OS user connect to the single-instance socket
    server.setSocketOptions(QLocalServer.UserAccessOption)
    server.listen(name)                  # if this fails we still run (fail-open)
    return server


def _integrate_appimage(con) -> str | None:
    """When launched as an AppImage, register a menu entry + logo on first run
    (so it appears in the apps menu/dock) and detect version changes. Returns a
    one-line notice ('installed' / 'updated to vX') or None. No-op for dev runs."""
    appimage = os.environ.get("APPIMAGE")
    if not appimage or not Path(appimage).exists():
        return None
    prev_ver = db.get_setting(con, "installed_version", "")
    apps = Path.home() / ".local/share/applications"
    icons = Path.home() / ".local/share/icons/hicolor/256x256/apps"
    desktop = apps / "labdesk.desktop"
    try:
        apps.mkdir(parents=True, exist_ok=True)
        icons.mkdir(parents=True, exist_ok=True)
        if APP_ICON.exists():
            shutil.copyfile(APP_ICON, icons / "labdesk.png")
        entry = (
            "[Desktop Entry]\nType=Application\nName=LabDesk\n"
            "Comment=Laboratory Management System\n"
            f'Exec="{appimage}" %U\nIcon=labdesk\n'
            "Categories=Office;MedicalSoftware;\nTerminal=false\n"
            "StartupWMClass=LabDesk\n"
        )
        if not desktop.exists() or desktop.read_text(encoding="utf-8") != entry:
            desktop.write_text(entry, encoding="utf-8")
        # Refreshing the menu/icon caches can take 1-3s — do it in a daemon thread
        # so it never delays the first window. It's fire-and-forget (best effort).
        import threading

        def _refresh_caches():
            for cmd in (["update-desktop-database", str(apps)],
                        ["gtk-update-icon-cache",
                         str(Path.home() / ".local/share/icons/hicolor")]):
                try:
                    subprocess.run(cmd, capture_output=True, timeout=10)
                except Exception:
                    pass

        threading.Thread(target=_refresh_caches, daemon=True).start()
    except Exception:
        return None
    db.set_setting(con, "installed_version", db.APP_VERSION)
    if not prev_ver:
        return ("LabDesk has been added to your applications menu.\n"
                "Launch it from the menu (or pin it to your dock) next time.")
    if prev_ver != db.APP_VERSION:
        return f"Updated to v{db.APP_VERSION} successfully."
    return None


def _setup_crash_logging() -> None:
    """Log uncaught exceptions to a rotating file under the data dir and show the
    user where to find the details, instead of the app vanishing silently."""
    import logging
    from logging.handlers import RotatingFileHandler
    logdir = db.data_dir() / "logs"
    try:
        logdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    handler = RotatingFileHandler(logdir / "labdesk.log", maxBytes=1_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("labdesk")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.info("LabDesk v%s starting", db.APP_VERSION)

    def _hook(exc_type, exc, tb):
        import traceback
        logger.error("Uncaught exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        if os.environ.get("LABDESK_SELFTEST") != "1":
            try:
                QMessageBox.critical(None, "LabDesk",
                                     "Something went wrong. The details were saved to:\n"
                                     f"{logdir / 'labdesk.log'}")
            except Exception:  # noqa: BLE001
                pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


def run(argv: list[str]) -> int:
    _setup_crash_logging()
    app = QApplication(argv)
    app.setApplicationName(PRODUCT_NAME)
    app.setOrganizationName(PRODUCT_NAME)
    # associate running windows with the .desktop entry (dock icon on GNOME/Wayland)
    app.setDesktopFileName("LabDesk")
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    app.setStyleSheet(QSS)

    # Single instance: if LabDesk is already open, focus it and quit this launch.
    server = None
    if os.environ.get("LABDESK_SELFTEST") != "1":
        server = _acquire_single_instance()
        if server is None:
            return 0
        app._labdesk_server = server     # keep the listener alive

    # Brief splash so startup (incl. the one-time catalog sync after an update,
    # ~1s) shows feedback instead of a blank window. Flashes by on normal launches.
    splash = None
    if os.environ.get("LABDESK_SELFTEST") != "1" and APP_ICON.exists():
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QSplashScreen
        pm = QPixmap(str(APP_ICON)).scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        splash = QSplashScreen(pm)
        splash.showMessage("Starting LabDesk…", Qt.AlignHCenter | Qt.AlignBottom, Qt.gray)
        splash.show()
        app.processEvents()

    con = db.init_db()
    # automatic timestamped backup on launch (rotated) — the safety net for the
    # "one bad disk loses everything" gap. Best-effort; never blocks startup.
    if os.environ.get("LABDESK_SELFTEST") != "1":
        try:
            db.backup_db("launch")
        except Exception:  # noqa: BLE001
            pass

    # First-run / update: integrate into the desktop (menu entry + logo) and
    # show a one-time "installed" / "updated" notice when run as an AppImage.
    notice = _integrate_appimage(con)
    # apply the saved theme now that we can read settings (splash was light)
    app.setStyleSheet(build_qss(db.get_setting(con, "theme", "light")))
    if splash is not None:
        splash.close()
    if notice and os.environ.get("LABDESK_SELFTEST") != "1":
        QMessageBox.information(None, "LabDesk", notice)

    # Self-test: build the main window for an admin user, visit every page, exit.
    # Used to validate a packaged build launches without a real display/login.
    if os.environ.get("LABDESK_SELFTEST") == "1":
        user = con.execute("SELECT * FROM users WHERE username='admin'").fetchone()
        win = MainWindow(con, user)
        win.show()
        for i in range(win.stack.count()):
            win.go(i)
        n = con.execute("SELECT COUNT(*) FROM tests").fetchone()[0]
        print(f"SELFTEST OK — {win.stack.count()} pages, {n} tests in catalog")
        return 0

    # First-run setup wizard (white-label: each lab enters its own branding).
    if db.get_setting(con, "configured", "0") != "1":
        wizard = SetupWizard(con)
        if wizard.exec() != QDialog.Accepted:
            return 0

    login = LoginDialog(con)
    if login.exec() != QDialog.Accepted:
        return 0

    win = MainWindow(con, login.user)
    win.show()

    # a later launch pokes the local server → bring this window to the front
    if server is not None:
        def _raise_existing():
            conn = server.nextPendingConnection()
            if conn is None:
                return
            conn.waitForReadyRead(200)
            payload = bytes(conn.readAll()).strip()
            conn.disconnectFromServer()
            if payload != b"raise":          # only act on the expected command
                return
            from PySide6.QtCore import Qt
            win.setWindowState((win.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
            win.show(); win.raise_(); win.activateWindow()
        server.newConnection.connect(_raise_existing)

    return app.exec()


def run_cli() -> int:
    """GUI entry point (used by the installed launcher script)."""
    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(run(sys.argv))
