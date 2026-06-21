"""Backups + restore — SQLite online backup (safe while the app is running)."""

from __future__ import annotations

import contextlib
import os
import shutil
import time
from pathlib import Path

from ._driver import sqlite3
from .connection import _apply_key, _resolve_key
from .paths import data_dir, db_path


def _encrypted_copy(src: Path, dest: Path, key: str | None) -> None:
    """Copy `src` to `dest` via SQLite's online backup API with both ends keyed to
    the same passphrase (so the destination is an encrypted copy). Hardens dest to
    0600. Raises sqlite3.Error / OSError on failure — callers decide how to handle."""
    sc = sqlite3.connect(str(src))
    _apply_key(sc, key)
    dc = sqlite3.connect(str(dest))
    _apply_key(dc, key)
    try:
        with dc:
            sc.backup(dc)
    finally:
        sc.close()
        dc.close()
    with contextlib.suppress(OSError):
        os.chmod(dest, 0o600)


def fallback_backup_dir() -> Path:
    """Where automatic backups land when the lab's chosen folder (a USB stick or a
    network share) is missing or unwritable — always on the local disk so a backup
    can never be silently skipped just because the USB was unplugged."""
    return Path.home() / "Documents" / "LabDesk Backups"


def _usable_dir(path: str | None) -> Path | None:
    """Return `path` as a writable directory (creating it if needed), or None if it
    is unset or can't be written to (e.g. an unplugged USB / down network mount)."""
    if not path:
        return None
    p = Path(path).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".labdesk-write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return p
    except OSError:
        return None


def auto_backup(
    reason: str, preferred_dir: str | None, *, keep: int = 14
) -> tuple[Path | None, bool]:
    """Write a rotated, encrypted backup to `preferred_dir` (the lab's chosen folder),
    falling back to ~/Documents/LabDesk Backups when that folder is missing/unwritable.

    Returns ``(path_written, used_fallback)`` — ``path_written`` is None only if even
    the fallback couldn't be written (or there is no DB yet). Never raises.
    """
    src = db_path()
    if not src.exists():
        return None, False
    target = _usable_dir(preferred_dir)
    used_fallback = False
    if target is None:
        used_fallback = preferred_dir not in (
            None,
            "",
        )  # only "fell back" if a dir was set
        target = _usable_dir(str(fallback_backup_dir()))
        if target is None:
            return None, used_fallback
    dest = target / f"labdesk-{time.strftime('%Y%m%d-%H%M%S')}-{reason}.sqlite"
    try:
        _encrypted_copy(src, dest, _resolve_key())
    except (sqlite3.Error, OSError):
        with contextlib.suppress(OSError):
            if dest.exists():
                dest.unlink()
        return None, used_fallback
    # rotation: keep only the newest `keep` auto-backups in this folder
    try:
        keep = max(1, int(keep))
        for old in sorted(target.glob("labdesk-*.sqlite"))[:-keep]:
            old.unlink()
    except (OSError, ValueError):
        pass
    return dest, used_fallback


def backup_db(reason: str = "auto", keep: int = 14) -> Path | None:
    """Write a timestamped 0600 copy of the live DB to <data>/backups and prune to
    the newest `keep`. Returns the path, or None on failure / no DB yet."""
    src = db_path()
    if not src.exists():
        return None
    bdir = data_dir() / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(bdir, 0o700)
    dest = bdir / f"labdesk-{time.strftime('%Y%m%d-%H%M%S')}-{reason}.sqlite"
    try:
        # Encrypt the backup with the same passphrase as the live DB (keying both
        # ends so SQLCipher copies into an encrypted destination).
        key = _resolve_key()
        sc = sqlite3.connect(src)
        _apply_key(sc, key)
        dc = sqlite3.connect(dest)
        _apply_key(dc, key)
        with dc:
            sc.backup(dc)
        sc.close()
        dc.close()
        os.chmod(dest, 0o600)
    except (sqlite3.Error, OSError):
        return None
    try:
        for old in sorted(bdir.glob("labdesk-*.sqlite"))[:-keep]:
            old.unlink()
    except OSError:
        pass
    return dest


def backup_to(dest: str) -> bool:
    """Write an encrypted backup of the live DB to a caller-chosen path (e.g. one
    picked in a Save-As dialog). Same passphrase as the live DB; no rotation — the
    user owns the file. Returns True on success."""
    src = db_path()
    if not src.exists():
        return False
    target = Path(dest)
    try:
        _encrypted_copy(src, target, _resolve_key())
        return True
    except (sqlite3.Error, OSError):
        return False


def _looks_like_labdesk_db(path: Path, key: str | None = None) -> bool:
    """A restore source must OPEN with a passphrase AND look like a real LabDesk DB —
    a `settings` table plus a NON-EMPTY `users` table — guarding against a garbage,
    foreign, or empty/forged file. (Encrypted backups have no plaintext SQLite header
    to inspect, so we validate by opening with the key rather than by the magic bytes.)

    `key` lets the caller probe with a SPECIFIC passphrase — used to recognise a
    valid backup that was made under a *different* (e.g. older) database password.
    When omitted, the current session/env key is used.
    """
    try:
        probe = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            _apply_key(probe, key if key is not None else _resolve_key())
            tables = {
                r[0]
                for r in probe.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not {"users", "settings"}.issubset(tables):
                return False
            # a real LabDesk DB always has at least the seeded admin user; an empty
            # users table is a sign of a truncated/forged file, not a genuine backup.
            nusers = probe.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            return nusers > 0
        finally:
            probe.close()
    except sqlite3.Error:
        return False


def install_restored(src_path: str, key: str | None) -> bool:
    """First-run restore: validate an encrypted backup opens with ``key`` and looks
    like a real LabDesk DB, then copy it into place as the live database. Unlike
    :func:`restore_db` there is no existing DB to safety-copy (this runs before any
    DB exists), and validation uses the BACKUP's own passphrase. Returns True on
    success, never raises."""
    src = Path(src_path)
    if not src.exists() or not _looks_like_labdesk_db(src, key):
        return False
    try:
        cur = db_path()
        cur.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, cur)
        # drop any stale WAL/SHM sidecars so the copied DB is opened cleanly
        for sidecar in ("-wal", "-shm"):
            p = Path(str(cur) + sidecar)
            if p.exists():
                p.unlink()
        os.chmod(cur, 0o600)
        return True
    except OSError:
        return False


def restore_db(path: str) -> bool:
    """Replace the live DB with a backup file (caller should close connections and
    restart the app afterwards). A TIMESTAMPED safety copy of the current DB is taken
    first (so successive restores never clobber an earlier rollback), and the restore
    is recorded to the audit-fallback log — the swapped-in DB carries its own audit
    chain, so the event would otherwise leave no trace in the live trail."""
    from .audit import _audit_fallback  # local import avoids an audit<->backup cycle

    src = Path(path)
    if not src.exists():
        return False
    if not _looks_like_labdesk_db(src):
        return False
    try:
        cur = db_path()
        if cur.exists():
            # Timestamped + de-duplicated so successive restores (even within the same
            # second) never overwrite an earlier rollback.
            base = f"{cur}.pre-restore-{time.strftime('%Y%m%d-%H%M%S')}"
            safety, i = base, 1
            while Path(safety).exists():
                safety = f"{base}-{i}"
                i += 1
            shutil.copyfile(cur, safety)
            with contextlib.suppress(OSError):
                os.chmod(safety, 0o600)
        # Record the restore BEFORE the swap, to the fallback log in the (persistent)
        # data dir — the live audit chain is about to be replaced by the backup's.
        _audit_fallback(
            "system", "database_restored", f"restored from {src}", "restore"
        )
        shutil.copyfile(src, cur)
        for sidecar in ("-wal", "-shm"):
            p = Path(str(cur) + sidecar)
            if p.exists():
                p.unlink()
        os.chmod(cur, 0o600)
        return True
    except OSError:
        return False
