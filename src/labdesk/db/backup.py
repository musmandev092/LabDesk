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
    """Copy via SQLite's online backup API with both ends keyed to the same passphrase."""
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
    """Local-disk fallback when the lab's chosen backup folder is missing/unwritable."""
    return Path.home() / "Documents" / "LabDesk Backups"


def _usable_dir(path: str | None) -> Path | None:
    """Return `path` as a writable directory (creating it if needed), or None."""
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
    """Write a rotated, encrypted backup to `preferred_dir`, falling back to
    fallback_backup_dir() when missing/unwritable. Never raises."""
    src = db_path()
    if not src.exists():
        return None, False
    target = _usable_dir(preferred_dir)
    used_fallback = False
    if target is None:
        used_fallback = preferred_dir not in (None, "")
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
    try:
        keep = max(1, int(keep))
        for old in sorted(target.glob("labdesk-*.sqlite"))[:-keep]:
            old.unlink()
    except (OSError, ValueError):
        pass
    return dest, used_fallback


def backup_db(reason: str = "auto", keep: int = 14) -> Path | None:
    """Write a timestamped 0600 copy of the live DB to <data>/backups, pruned to `keep`."""
    src = db_path()
    if not src.exists():
        return None
    bdir = data_dir() / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(bdir, 0o700)
    dest = bdir / f"labdesk-{time.strftime('%Y%m%d-%H%M%S')}-{reason}.sqlite"
    try:
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
    """Write an encrypted backup to a caller-chosen path (no rotation)."""
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
    """True if `path` opens with `key` (or the session key) and has settings +
    a non-empty users table. `key` lets a caller probe a specific passphrase."""
    try:
        # as_uri() percent-encodes the path so '?'/'#' in it can't mangle the URI
        probe = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
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
            nusers = probe.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            return nusers > 0
        finally:
            probe.close()
    except sqlite3.Error:
        return False


def install_restored(src_path: str, key: str | None) -> bool:
    """First-run restore: validate a backup opens with `key`, then copy it into place
    as the live database (no existing DB to safety-copy). Never raises."""
    src = Path(src_path)
    if not src.exists() or not _looks_like_labdesk_db(src, key):
        return False
    try:
        cur = db_path()
        cur.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, cur)
        for sidecar in ("-wal", "-shm"):
            p = Path(str(cur) + sidecar)
            if p.exists():
                p.unlink()
        os.chmod(cur, 0o600)
        return True
    except OSError:
        return False


def restore_db(path: str) -> bool:
    """Replace the live DB with a backup file, taking a timestamped safety copy of
    the current DB first (caller should close connections and restart afterwards)."""
    from .audit import _audit_fallback  # local import avoids an audit<->backup cycle

    src = Path(path)
    if not src.exists():
        return False
    if not _looks_like_labdesk_db(src):
        return False
    try:
        cur = db_path()
        if cur.exists():
            # timestamped + de-duplicated so successive restores don't overwrite each other
            base = f"{cur}.pre-restore-{time.strftime('%Y%m%d-%H%M%S')}"
            safety, i = base, 1
            while Path(safety).exists():
                safety = f"{base}-{i}"
                i += 1
            shutil.copyfile(cur, safety)
            with contextlib.suppress(OSError):
                os.chmod(safety, 0o600)
        # record before the swap: the live audit chain is about to be replaced
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
