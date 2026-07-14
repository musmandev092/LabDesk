"""Application bootstrap: init DB, run first-run setup, login, main window."""

from __future__ import annotations

import contextlib
import logging
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from . import db, licensing
from ._resources import package_root
from .presentation.login import LoginDialog
from .presentation.main_window import MainWindow
from .presentation.setup_wizard import SetupWizard
from .presentation.style import PRODUCT_NAME, apply_theme

# product icon — shown in the title bar and taskbar/dock
APP_ICON = package_root() / "assets" / "app_icon_256.png"


def _selftest() -> bool:
    """Headless self-test, honoured only when running from source (never in a packaged build)."""
    return (
        os.environ.get("LABDESK_SELFTEST") == "1" and not licensing.is_packaged_build()
    )


def _instance_paths() -> tuple[str, str]:
    """Per-user lock + activation-socket paths in the runtime dir."""
    import tempfile

    try:
        uid = os.getuid()
    except AttributeError:  # non-POSIX fallback
        uid = "x"
    runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return (
        os.path.join(runtime, f"LabDesk-{uid}.lock"),
        os.path.join(runtime, f"LabDesk-{uid}.sock"),
    )


def _acquire_single_instance():
    """Advisory fcntl lock for single-instance; returns (lock_file, activation_socket) or (None, None)."""
    import fcntl
    import socket

    lock_path, sock_path = _instance_paths()
    try:
        f = open(lock_path, "w")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None, None  # another instance holds the lock
    with contextlib.suppress(OSError):
        f.write(str(os.getpid()))
        f.flush()
    # primary: open the activation listener (best-effort)
    srv = None
    try:
        with contextlib.suppress(OSError):
            os.unlink(sock_path)  # clear stale socket
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        srv.setblocking(False)
    except OSError:
        srv = None
    return f, srv


def _ping_running_instance() -> bool:
    """Ask the already-running primary to raise its window; True if it acknowledged."""
    import socket

    _lock_path, sock_path = _instance_paths()
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(2)
        c.connect(sock_path)
        c.sendall(b"raise")
        c.close()
        return True
    except OSError:
        return False


def _install_activation_listener(app, win) -> None:
    """When a second launch connects to the activation socket, bring this window to front."""
    srv = getattr(app, "_labdesk_activation_srv", None)
    if srv is None:
        return
    from PySide6.QtCore import QSocketNotifier, Qt

    notifier = QSocketNotifier(srv.fileno(), QSocketNotifier.Type.Read, win)

    def _on_ready() -> None:
        with contextlib.suppress(OSError):
            conn, _addr = srv.accept()
            with contextlib.suppress(OSError):
                conn.recv(16)
                conn.close()
        # clear only Minimized so a maximised window isn't shrunk (showNormal() would)
        win.setWindowState(win.windowState() & ~Qt.WindowState.WindowMinimized)
        win.show()
        win.raise_()
        win.activateWindow()

    notifier.activated.connect(_on_ready)
    win._activation_notifier = notifier  # keep a reference so it isn't GC'd


def _integrate_appimage(con) -> str | None:
    """AppImage first-run: register menu entry + logo, detect version changes. No-op otherwise."""
    appimage = os.environ.get("APPIMAGE")
    if not appimage or not Path(appimage).exists():
        return None
    prev_ver = db.get_setting(con, "installed_version", "")
    apps = Path.home() / ".local/share/applications"
    icons = Path.home() / ".local/share/icons/hicolor/256x256/apps"
    # filename must match the Wayland app_id / X11 StartupWMClass, hence not lowercase
    desktop = apps / "LabDesk.desktop"
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
        # drop the pre-1.0 lowercase entry so the launcher doesn't show a duplicate
        with contextlib.suppress(OSError):
            (apps / "labdesk.desktop").unlink()
        # refresh caches in a daemon thread (fire-and-forget) so it doesn't delay startup
        import threading

        def _refresh_caches():
            hicolor = str(Path.home() / ".local/share/icons/hicolor")
            for cmd in (
                ["update-desktop-database", str(apps)],  # GNOME/GTK menu cache
                ["gtk-update-icon-cache", hicolor],  # GTK icon cache
                ["kbuildsycoca6"],  # KDE Plasma 6 menu/icon cache
                ["kbuildsycoca5"],  # KDE Plasma 5 (older installs)
            ):
                with contextlib.suppress(Exception):
                    subprocess.run(cmd, capture_output=True, timeout=10)

        threading.Thread(target=_refresh_caches, daemon=True).start()
    except Exception:
        return None
    db.set_setting(con, "installed_version", db.APP_VERSION)
    if not prev_ver:
        return (
            "LabDesk has been added to your applications menu.\n"
            "Open it from there — and pin it to your taskbar or dock yourself if you like."
        )
    if prev_ver != db.APP_VERSION:
        return f"Updated to v{db.APP_VERSION} successfully."
    return None


def _setup_crash_logging() -> None:
    """Log uncaught exceptions to a rotating file under the data dir."""
    from logging.handlers import RotatingFileHandler

    logdir = db.data_dir() / "logs"
    try:
        logdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    handler = RotatingFileHandler(
        logdir / "labdesk.log", maxBytes=1_000_000, backupCount=5
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("labdesk")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.info("LabDesk v%s starting", db.APP_VERSION)

    def _hook(exc_type, exc, tb):
        import traceback

        logger.error(
            "Uncaught exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )
        if not _selftest():
            with contextlib.suppress(Exception):
                QMessageBox.critical(
                    None,
                    "LabDesk",
                    "Something went wrong. The details were saved to:\n"
                    f"{logdir / 'labdesk.log'}",
                )
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


def _db_damaged_notice(exc: Exception) -> None:
    """Show a recoverable message pointing at backups when the database can't be opened/read."""
    logging.getLogger("labdesk").error("Database open/read failed: %r", exc)
    if _selftest():
        return
    try:
        backups = db.data_dir() / "backups"
        QMessageBox.critical(
            None,
            "LabDesk — database problem",
            "LabDesk could not open your database. It may be damaged, or the password "
            "did not fully match.\n\n"
            "Your data is not necessarily lost — timestamped backups are kept in:\n"
            f"{backups}\n\n"
            "You can restore a backup now (on the next screen), or contact support.",
        )
    except Exception:
        pass


def _auto_backup_on_launch(con) -> None:
    """Write an automatic encrypted backup at most once per calendar day."""
    if db.get_setting(con, "auto_backup", "1") != "1":
        return
    import datetime

    today = datetime.date.today().isoformat()
    if db.get_setting(con, "last_auto_backup_date", "") == today:
        return
    try:
        keep = int(db.get_setting(con, "backup_keep", "14") or 14)
    except ValueError:
        keep = 14
    path, used_fallback = db.auto_backup(
        "launch", db.get_setting(con, "backup_dir", ""), keep=keep
    )
    if path:
        db.set_setting(con, "last_auto_backup_date", today)
        detail = str(path) + (
            " [USB/network folder was unavailable — saved to Documents]"
            if used_fallback
            else ""
        )
        db.log_audit(con, "system", "backup_created", detail)


# UI is laid out for ~1080p; smaller screens auto-shrink via QT_SCALE_FACTOR (see below)
_FIT_NEED_W = 1280
_FIT_NEED_H = 860


def _fit_scale(
    avail_w: int, avail_h: int, need_w: int = _FIT_NEED_W, need_h: int = _FIT_NEED_H
) -> float | None:
    """Largest scale <= 1.0 (0.05 steps, floor 0.70) that fits the UI; None if it already fits."""
    if avail_w <= 0 or avail_h <= 0:
        return None
    s = min(avail_w / need_w, avail_h / need_h, 1.0)
    s = max(0.70, math.floor(s * 20) / 20)  # floor to 0.05 steps, legibility floor
    return s if s < 1.0 else None


def _reexec_self() -> None:
    """Restart this process in place so a freshly-set QT_SCALE_FACTOR is read at startup."""
    exe = sys.argv[0]
    if os.path.basename(exe) == "__main__.py":  # python -m labdesk (dev)
        os.execv(sys.executable, [sys.executable, "-m", "labdesk", *sys.argv[1:]])
    elif os.access(exe, os.X_OK) and not exe.endswith(".py"):  # binary / gui-script
        os.execv(exe, sys.argv)
    else:
        os.execv(sys.executable, [sys.executable, *sys.argv])


def _maybe_rescale_for_screen(app) -> None:
    """If the primary screen is too small, set QT_SCALE_FACTOR and re-exec once."""
    if _selftest():
        return
    if os.environ.get("QT_SCALE_FACTOR") or os.environ.get("QT_SCREEN_SCALE_FACTORS"):
        return  # respect an explicit override
    opted_out = os.environ.get("LABDESK_NO_AUTOSCALE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if os.environ.get("LABDESK_AUTOSCALED") == "1" or opted_out:
        return  # already scaled once, or explicitly opted out
    screen = app.primaryScreen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    s = _fit_scale(geo.width(), geo.height())
    if s is None:
        return
    os.environ["QT_SCALE_FACTOR"] = f"{s:.2f}"
    os.environ["LABDESK_AUTOSCALED"] = "1"
    try:
        _reexec_self()  # replaces the process image; does not return on success
    except OSError:
        # couldn't re-exec — carry on at native scale rather than fail to launch
        logging.getLogger("labdesk").warning(
            "auto-scale re-exec failed; running at native size "
            "(set QT_SCALE_FACTOR=%s manually if the window overflows)",
            f"{s:.2f}",
            exc_info=True,
        )


def run(argv: list[str]) -> int:
    _setup_crash_logging()
    # pass the OS's exact fractional DPI scale through; must happen before QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv)
    # done before the single-instance lock so the restart is clean
    _maybe_rescale_for_screen(app)
    app.setApplicationName(PRODUCT_NAME)
    app.setOrganizationName(PRODUCT_NAME)
    # associate running windows with the .desktop entry (dock icon on GNOME/Wayland)
    app.setDesktopFileName("LabDesk")
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    apply_theme(app, "light")  # splash is light; the saved theme is applied below

    # load the report font here (main thread); PDF worker thread must not touch QFontDatabase
    from . import render

    render.preload()

    if not _selftest():
        lock, activation_srv = _acquire_single_instance()
        if lock is None:
            # nudge the running instance; keep the message neutral since it may still be at login
            _ping_running_instance()
            QMessageBox.information(
                None,
                PRODUCT_NAME,
                "LabDesk is already running.\n\n"
                "Look for its existing window (check your taskbar); if it's just "
                "started, it may still be on the password or sign-in screen.",
            )
            return 0
        app._labdesk_lock = lock  # keep the lock file alive for the run
        app._labdesk_activation_srv = activation_srv

    # brief splash for pre-unlock feedback; closed before the password dialog
    splash = None
    if not _selftest() and APP_ICON.exists():
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QSplashScreen

        pm = QPixmap(str(APP_ICON)).scaled(
            220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        splash = QSplashScreen(pm)
        splash.showMessage(
            "Starting LabDesk…", Qt.AlignHCenter | Qt.AlignBottom, Qt.gray
        )
        splash.show()
        app.processEvents()

    # ---- node-locked licensing (machine activation) ---------------------------
    # verify activation before touching the DB; gated so dev runs / self-test aren't blocked
    license_just_activated = False
    if not _selftest() and licensing.enforced():
        if splash is not None:
            splash.close()
        state, _ = licensing.check()
        if state != "ok":
            from .presentation.activation import ActivationDialog

            if ActivationDialog(initial_state=state).exec() != QDialog.Accepted:
                return 0
            if licensing.check()[0] != "ok":
                return 0
            license_just_activated = True

    # ---- database unlock (encrypted at rest with SQLCipher) -------------------
    if not _selftest():
        if splash is not None:
            splash.close()  # don't leave the splash on top of the password dialog
        from .db import keyvault

        dbf = db.db_path()
        if not dbf.exists():
            from .presentation.unlock import (
                FirstRunDialog,
                RestoreBackupDialog,
                SetPasswordDialog,
            )

            fr = FirstRunDialog()
            if fr.exec() != QDialog.Accepted:
                return 0
            if fr.choice == "restore":
                rdlg = RestoreBackupDialog()
                if rdlg.exec() != QDialog.Accepted:
                    return 0
                from .db.backup import install_restored

                if not install_restored(rdlg.path, rdlg.passphrase):
                    QMessageBox.critical(
                        None,
                        "LabDesk",
                        "Could not restore that backup. The file may be damaged or the "
                        "password was wrong. Your computer was not changed.",
                    )
                    return 0
                db.unlock(rdlg.passphrase)
                if rdlg.remember:
                    keyvault.store_key(rdlg.passphrase)
            else:
                dlg = SetPasswordDialog()
                if dlg.exec() != QDialog.Accepted or not dlg.passphrase:
                    return 0
                db.unlock(dlg.passphrase)
                if dlg.remember:
                    keyvault.store_key(dlg.passphrase)
        elif db.db_is_plaintext(dbf):
            # upgrade an unencrypted DB left by a pre-encryption build
            from .presentation.unlock import SetPasswordDialog

            dlg = SetPasswordDialog(migrating=True)
            if dlg.exec() != QDialog.Accepted or not dlg.passphrase:
                return 0
            if not db.migrate_plaintext_to_encrypted(dlg.passphrase):
                QMessageBox.critical(
                    None,
                    "LabDesk",
                    "Could not encrypt the existing database. Your data was left "
                    "unchanged — please try again or contact support.",
                )
                return 0
            db.unlock(dlg.passphrase)
            if dlg.remember:
                keyvault.store_key(dlg.passphrase)
        else:
            # auto-unlock from the system wallet if valid; clear a stale saved key
            saved = keyvault.load_key()
            if saved and db.verify_passphrase(saved):
                db.unlock(saved)
            else:
                if saved:
                    keyvault.clear_key()
                from .presentation.unlock import UnlockDialog

                dlg = UnlockDialog()
                if dlg.exec() != QDialog.Accepted or not dlg.passphrase:
                    return 0
                db.unlock(dlg.passphrase)
                if dlg.remember:
                    keyvault.store_key(dlg.passphrase)

    try:
        con = db.init_db()
    except Exception as e:  # corrupt/unreadable DB → offer recovery, don't hard-crash
        if _selftest():
            import traceback

            traceback.print_exc()
            return 1
        if splash is not None:
            splash.close()
        _db_damaged_notice(e)
        # offer an in-app restore here since Settings -> Restore needs a running MainWindow
        from .db.backup import install_restored
        from .presentation.unlock import RestoreBackupDialog

        rdlg = RestoreBackupDialog()
        if rdlg.exec() != QDialog.Accepted:
            return 1
        if not install_restored(rdlg.path, rdlg.passphrase):
            QMessageBox.critical(
                None,
                "LabDesk",
                "Could not restore that backup. The file may be damaged or the "
                "password was wrong. Your computer was not changed.",
            )
            return 1
        db.unlock(rdlg.passphrase)
        if rdlg.remember:
            keyvault.store_key(rdlg.passphrase)
        try:
            con = db.init_db()
        except Exception as e2:
            _db_damaged_notice(e2)
            return 1

    # `labdesk --unlock` clears any brute-force lockout; runs only after DB unlock above
    if "--unlock" in argv:
        n = db.clear_lockouts(con)
        db.log_audit(
            con, "system", "lockout_cleared", f"--unlock cleared {n} account(s)"
        )
        QMessageBox.information(
            None,
            PRODUCT_NAME,
            f"Sign-in lock cleared for {n} account(s).\n\n"
            "You can now start LabDesk normally and sign in.",
        )
        return 0

    # desktop integration is done at install time by install.sh; this only fires for AppImage
    notice = _integrate_appimage(con)
    # apply the saved theme now that we can read settings (splash was light)
    apply_theme(app, db.get_setting(con, "theme", "light"))
    if splash is not None:
        splash.close()
    if notice and not _selftest():
        QMessageBox.information(None, "LabDesk", notice)

    # self-test: build the main window for an admin user, visit every page, exit
    if _selftest():
        user = con.execute("SELECT * FROM users WHERE username='admin'").fetchone()
        win = MainWindow(con, user)
        win.show()
        for i in range(win.stack.count()):
            win.go(i)
        n = con.execute("SELECT COUNT(*) FROM tests").fetchone()[0]
        print(f"SELFTEST OK — {win.stack.count()} pages, {n} tests in catalog")
        return 0

    if license_just_activated:
        db.log_audit(con, "system", "license_activated", licensing.current_code())

    # first-run setup wizard (white-label: each lab enters its own branding)
    if db.get_setting(con, "configured", "0") != "1":
        wizard = SetupWizard(con)
        if wizard.exec() != QDialog.Accepted:
            return 0

    # runs after the wizard so the lab's chosen backup folder is already set
    _auto_backup_on_launch(con)

    login = LoginDialog(con)
    if login.exec() != QDialog.Accepted:
        return 0

    try:
        win = MainWindow(con, login.user)
    except Exception as e:  # damaged DB can fail while a page reads it on build
        _db_damaged_notice(e)
        return 1
    win.showMaximized()  # data-dense table app; content reflows/scrolls to fit
    _install_activation_listener(app, win)

    return app.exec()


def run_cli() -> int:
    """GUI entry point (used by the installed launcher script)."""
    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(run(sys.argv))
