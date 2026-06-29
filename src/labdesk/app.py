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

# product icon (the microscope logo) — shown in the title bar + taskbar/dock
APP_ICON = package_root() / "assets" / "app_icon_256.png"


def _selftest() -> bool:
    """The headless self-test (no display/login, builds the window as admin) is a
    DEV/CI affordance only. It is honoured solely when running from source — in a
    packaged release binary LABDESK_SELFTEST is ignored, so it can never be used to
    bypass database unlock, login, or licensing on a shipped build."""
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
    """Allow only one LabDesk window per user via an advisory fcntl lock (no
    QtNetwork dependency). Returns ``(lock_file, activation_socket)`` when this
    process is the primary, or ``(None, None)`` when another instance already holds
    the lock. The kernel releases the lock automatically on exit — including a crash
    — so there is no stale-lock cleanup to do.

    The primary also opens a tiny Unix-domain "activation" socket: a second launch
    connects to it to ask the primary to raise its window (see
    ``_ping_running_instance`` / ``_install_activation_listener``)."""
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
    # We are the primary — open the activation listener (best-effort; the lock alone
    # still enforces single-instance even if this socket can't be created).
    srv = None
    try:
        with contextlib.suppress(OSError):
            os.unlink(sock_path)  # clear a stale socket from a previous run
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        srv.setblocking(False)
    except OSError:
        srv = None
    return f, srv


def _ping_running_instance() -> bool:
    """Ask the already-running primary to raise its window. Returns True if the
    primary acknowledged (so a second launch knows the app really is up)."""
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
    """Wire the primary's activation socket into the Qt loop: when a second launch
    connects, bring this window to the front (un-minimise + raise + request focus).
    On Wayland the compositor may not steal focus, but the window is un-minimised and
    flagged for attention, which is the portable best-effort."""
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
        # Un-minimise WITHOUT dropping a maximised/full-screen state. showNormal()
        # would force the window back to its small windowed size — the reported
        # shrink bug. Clearing only the Minimized flag preserves Maximized.
        win.setWindowState(win.windowState() & ~Qt.WindowState.WindowMinimized)
        win.show()
        win.raise_()
        win.activateWindow()

    notifier.activated.connect(_on_ready)
    win._activation_notifier = notifier  # keep a reference so it isn't GC'd


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
    # The .desktop filename MUST match the Wayland app_id (set via
    # setDesktopFileName('LabDesk')) and the X11 StartupWMClass, or KDE/GNOME on
    # Wayland can't tie the running window to this launcher — the icon falls back to
    # a generic one and the app can't be pinned. Hence 'LabDesk.desktop', not lowercase.
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
        # Refreshing the menu/icon caches can take 1-3s — do it in a daemon thread so
        # it never delays the first window. Fire-and-forget; run every refresher so
        # the entry/icon appear without a relogin on BOTH GNOME/GTK and KDE Plasma.
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
        # We only add LabDesk to the applications menu; pinning to a dock/taskbar is
        # left to the user (an app can't portably pin itself without risking the
        # panel config). Open it from the menu and pin it yourself if you like.
        return (
            "LabDesk has been added to your applications menu.\n"
            "Open it from there — and pin it to your taskbar or dock yourself if you like."
        )
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
    """Show a clear, recoverable message when the database can't be opened/read
    (corruption, or a key that decrypts the header but not all pages) instead of the
    generic crash dialog. Points the user at their backups + the Restore action."""
    import logging

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
            "Reopen LabDesk and use Settings → Backup & restore → “Restore from file…”, "
            "or contact support.",
        )
    except Exception:
        pass


def _auto_backup_on_launch(con) -> None:
    """Once a day, write an automatic encrypted backup to the lab's chosen folder
    (or the ~/Documents/LabDesk Backups fallback when that folder — e.g. a USB stick
    or network share — is unavailable). Throttled by last_auto_backup_date so it runs
    at most once per calendar day no matter how often LabDesk is opened."""
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


# The UI is laid out in px for roughly a 1080p screen. On smaller panels (e.g. a
# 1366x768 laptop, where the desktop bar leaves ~731-740 px tall) it overflows and
# everything needs scrolling. We auto-shrink with QT_SCALE_FACTOR so the whole
# window fits — the same lever a user would set by hand — instead of asking them to.
# The target height (860) is calibrated so a 1366x768 screen lands on 0.85, which
# fits cleanly on that hardware; smaller screens step down from there.
_FIT_NEED_W = 1280
_FIT_NEED_H = 860


def _fit_scale(
    avail_w: int, avail_h: int, need_w: int = _FIT_NEED_W, need_h: int = _FIT_NEED_H
) -> float | None:
    """Largest scale ≤ 1.0 (in 0.05 steps, floored at 0.70 so text stays legible)
    that fits the UI's preferred size into the screen's available area. Returns None
    when no scaling is needed (the UI already fits). E.g. 1366x768 → 0.85."""
    if avail_w <= 0 or avail_h <= 0:
        return None
    s = min(avail_w / need_w, avail_h / need_h, 1.0)
    s = max(0.70, math.floor(s * 20) / 20)  # floor to 0.05 steps, legibility floor
    return s if s < 1.0 else None


def _reexec_self() -> None:
    """Restart this process in place (so a freshly-set QT_SCALE_FACTOR is read at
    QApplication construction). Handles the dev `python -m labdesk`, the installed
    gui-script, and the compiled binary."""
    exe = sys.argv[0]
    if os.path.basename(exe) == "__main__.py":  # python -m labdesk (dev)
        os.execv(sys.executable, [sys.executable, "-m", "labdesk", *sys.argv[1:]])
    elif os.access(exe, os.X_OK) and not exe.endswith(".py"):  # binary / gui-script
        os.execv(exe, sys.argv)
    else:
        os.execv(sys.executable, [sys.executable, *sys.argv])


def _maybe_rescale_for_screen(app) -> None:
    """If the primary screen is too small for the UI, set QT_SCALE_FACTOR and re-exec
    once so the whole window fits without scrolling. No-op when it already fits, when
    the user set a scale explicitly, or after we've already re-exec'd (no loop)."""
    if _selftest():
        return
    if os.environ.get("QT_SCALE_FACTOR") or os.environ.get("QT_SCREEN_SCALE_FACTORS"):
        return  # respect an explicit override
    if os.environ.get("LABDESK_AUTOSCALED") == "1" or os.environ.get(
        "LABDESK_NO_AUTOSCALE"
    ):
        return  # already scaled once, or opted out
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
    # High-DPI: pass the OS's exact fractional scale through (e.g. 150% -> 1.5) so a
    # window never gets rounded UP past the screen. This is already the Qt 6 default;
    # setting it explicitly is portable and must happen before QApplication is built.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv)
    # Fit the UI to small screens (e.g. 1366x768) by auto-setting QT_SCALE_FACTOR and
    # re-exec'ing once. Done before anything else (incl. the single-instance lock) so
    # the restart is clean. On a screen that already fits, this is a no-op.
    _maybe_rescale_for_screen(app)
    app.setApplicationName(PRODUCT_NAME)
    app.setOrganizationName(PRODUCT_NAME)
    # associate running windows with the .desktop entry (dock icon on GNOME/Wayland)
    app.setDesktopFileName("LabDesk")
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    apply_theme(app, "light")  # splash is light; the saved theme is applied below

    # Load the report font once here on the main thread; PDF building runs on a
    # worker thread and must not touch QFontDatabase off-thread.
    from . import render

    render.preload()

    # Single instance: if LabDesk is already open, raise that window and tell the
    # user, instead of silently doing nothing.
    if not _selftest():
        lock, activation_srv = _acquire_single_instance()
        if lock is None:
            running = _ping_running_instance()  # bring the existing window to front
            QMessageBox.information(
                None,
                PRODUCT_NAME,
                "LabDesk is already running.\n\n"
                + (
                    "Its window has been brought to the front."
                    if running
                    else "Look for its existing window (check your taskbar)."
                ),
            )
            return 0
        app._labdesk_lock = lock  # keep the lock file alive for the run
        app._labdesk_activation_srv = activation_srv

    # Brief splash so startup (incl. the one-time catalog sync after an update,
    # ~1s) shows feedback instead of a blank window. Flashes by on normal launches.
    splash = None
    if not _selftest() and APP_ICON.exists():
        from PySide6.QtCore import Qt
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
    # Verify activation BEFORE touching the database, so a fresh install can offer to
    # restore a backup or start anew only once the copy is licensed for this machine.
    # Activation needs no DB (it reads license.lic from the data dir). Gated by
    # licensing.enforced() so dev runs and the self-test are never blocked.
    from . import licensing

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
    # The live DB is encrypted; obtain the passphrase BEFORE opening it. On a fresh
    # install (post-activation) the lab chooses to start a new lab or restore from a
    # backup; a legacy plaintext DB is migrated; otherwise we unlock. Headless
    # self-test takes the key from LABDESK_DB_KEY in the environment.
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
            # Auto-unlock from the system wallet if a saved password is there and still
            # valid; otherwise prompt. A stale saved key (after a password change) is
            # cleared so it doesn't get retried forever.
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
    except Exception as e:  # corrupt/unreadable DB → guide recovery, don't hard-crash
        if _selftest():
            import traceback

            traceback.print_exc()
            return 1
        _db_damaged_notice(e)
        return 1

    # Recovery: `labdesk --unlock` clears any brute-force lockout so a locked-out
    # admin can sign in again without waiting out the window. It runs only after the
    # normal DB-password unlock above, so only someone who already holds the database
    # password (the lab owner / vendor) can use it. Then it exits.
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

    # Automatic backups (once a day on launch + on exit) are written to the lab's
    # chosen folder, with a Documents fallback — see _auto_backup_on_launch below and
    # MainWindow._auto_backup_on_exit. A manual "Back up now" remains in Settings.

    # Desktop integration (menu entry + logo) is done at install time by
    # install.sh for the installed launcher; this runtime hook stays a no-op
    # there and only fires for a legacy AppImage launch.
    notice = _integrate_appimage(con)
    # apply the saved theme now that we can read settings (splash was light)
    apply_theme(app, db.get_setting(con, "theme", "light"))
    if splash is not None:
        splash.close()
    if notice and not _selftest():
        QMessageBox.information(None, "LabDesk", notice)

    # Self-test: build the main window for an admin user, visit every page, exit.
    # Used to validate a packaged build launches without a real display/login.
    if _selftest():
        user = con.execute("SELECT * FROM users WHERE username='admin'").fetchone()
        win = MainWindow(con, user)
        win.show()
        for i in range(win.stack.count()):
            win.go(i)
        n = con.execute("SELECT COUNT(*) FROM tests").fetchone()[0]
        print(f"SELFTEST OK — {win.stack.count()} pages, {n} tests in catalog")
        return 0

    # Licensing was verified before the DB step (above, so a fresh install could offer
    # restore-vs-new only once activated). Record the activation now that we have a
    # connection for the audit trail.
    if license_just_activated:
        db.log_audit(con, "system", "license_activated", licensing.current_code())

    # First-run setup wizard (white-label: each lab enters its own branding).
    if db.get_setting(con, "configured", "0") != "1":
        wizard = SetupWizard(con)
        if wizard.exec() != QDialog.Accepted:
            return 0

    # Automatic once-a-day backup (in addition to the on-exit one). Runs after the
    # wizard so the lab's chosen backup folder is already set on first run.
    _auto_backup_on_launch(con)

    login = LoginDialog(con)
    if login.exec() != QDialog.Accepted:
        return 0

    try:
        win = MainWindow(con, login.user)
    except Exception as e:  # damaged DB can fail while a page reads it on build
        _db_damaged_notice(e)
        return 1
    # Maximize so a data-dense table app uses the whole screen; the content now
    # reflows (wrapping toolbar) and scrolls, so this fits every resolution.
    win.showMaximized()
    # Now that the window exists, let a second launch raise it (see run()'s lock check).
    _install_activation_listener(app, win)

    return app.exec()


def run_cli() -> int:
    """GUI entry point (used by the installed launcher script)."""
    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(run(sys.argv))
