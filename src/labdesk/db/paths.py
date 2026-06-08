"""Filesystem locations + secrets for LabDesk.

The DB lives next to the user's data (XDG dir when packaged), so the AppImage
stays read-only while data persists across updates. The data dir is hardened to
0700 and the DB/secrets to 0600. Secrets are kept OUT of the SQLite DB so DB
copies/backups don't leak them.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from pathlib import Path

from ._config import APP_NAME


def data_dir() -> Path:
    """Where the live database + assets are stored (writable). Hardened to 0700 so
    other OS users can't read the patient data / secrets."""
    override = os.environ.get("LABDESK_DATA_DIR")
    if override:
        d = Path(override)
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(d, 0o700)
    return d


def db_path() -> Path:
    return data_dir() / "labdesk.sqlite"


def _harden_perms(target: Path) -> None:
    """Restrict the SQLite DB + its WAL/SHM sidecars to the owner (0600)."""
    for p in (target, Path(str(target) + "-wal"), Path(str(target) + "-shm")):
        try:
            if p.exists():
                os.chmod(p, 0o600)
        except OSError:
            pass


def import_asset(src: str, name_hint: str = "asset") -> Path:
    """Copy a chosen branding image into the (0700) data dir's `assets/` folder and
    return the managed path. Keeps logos inside the protected data dir instead of
    referencing arbitrary, possibly-sensitive locations elsewhere on disk."""
    s = Path(src).expanduser()
    assets = data_dir() / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(assets, 0o700)
    dest = assets / f"{name_hint}{s.suffix.lower() or '.png'}"
    shutil.copyfile(s, dest)
    return dest


# ---------------------------------------------------------------------------
# Secrets kept OUT of the SQLite DB (so DB copies/backups don't leak them).
# Stored in a 0600 JSON file in the data dir. Used for the WhatsApp token.
# ---------------------------------------------------------------------------
def _secret_path() -> Path:
    return data_dir() / ".secrets.json"


def get_secret(key: str, default: str = "") -> str:
    try:
        data = json.loads(_secret_path().read_text(encoding="utf-8"))
        return str(data.get(key, default))
    except (OSError, ValueError):
        return default


def set_secret(key: str, value: str) -> None:
    p = _secret_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[key] = value
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    with contextlib.suppress(OSError):
        os.chmod(p, 0o600)
