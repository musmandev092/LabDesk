"""Backups + restore — SQLite online backup (safe while the app is running)."""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import time
from pathlib import Path

from .paths import data_dir, db_path


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
        sc = sqlite3.connect(src)
        dc = sqlite3.connect(dest)
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


def _looks_like_labdesk_db(path: Path) -> bool:
    """A restore source must be a real SQLite database that has a users table —
    guards against overwriting the live DB with a garbage or foreign file."""
    try:
        with open(path, "rb") as fh:
            if fh.read(16) != b"SQLite format 3\x00":
                return False
    except OSError:
        return False
    try:
        probe = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = probe.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
        finally:
            probe.close()
        return bool(row)
    except sqlite3.Error:
        return False


def restore_db(path: str) -> bool:
    """Replace the live DB with a backup file (caller should close connections and
    restart the app afterwards). A safety copy of the current DB is taken first."""
    src = Path(path)
    if not src.exists():
        return False
    if not _looks_like_labdesk_db(src):
        return False
    try:
        cur = db_path()
        if cur.exists():
            shutil.copyfile(cur, str(cur) + ".pre-restore")
        shutil.copyfile(src, cur)
        for sidecar in ("-wal", "-shm"):
            p = Path(str(cur) + sidecar)
            if p.exists():
                p.unlink()
        os.chmod(cur, 0o600)
        return True
    except OSError:
        return False
