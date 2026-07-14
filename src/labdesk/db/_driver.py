"""Database driver: SQLCipher (encrypted at rest), imported here as `sqlite3` since
sqlcipher3.dbapi2 is a drop-in fork of the stdlib DB-API. Falls back to stdlib
sqlite3 (unencrypted) only when the wheel is absent, e.g. dev tooling; production
always has sqlcipher3 installed by install.sh. When unavailable, connection.connect()
/ init_db() fail closed unless LABDESK_ALLOW_PLAINTEXT=1 is set (dev-only opt-in)."""

from __future__ import annotations

try:
    from sqlcipher3 import dbapi2 as sqlite3

    ENCRYPTION_AVAILABLE = True
except ImportError:  # pragma: no cover - dev fallback only; data is NOT encrypted
    import sqlite3 as sqlite3  # explicit re-export (PEP 484)

    ENCRYPTION_AVAILABLE = False

# Explicit re-export: the sqlcipher branch renames dbapi2→sqlite3, which mypy's
# --no-implicit-reexport does not treat as a re-export; __all__ makes it explicit.
__all__ = ["ENCRYPTION_AVAILABLE", "sqlite3"]
