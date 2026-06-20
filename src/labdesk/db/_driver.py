"""Database driver: SQLCipher (encrypted at rest) with a stdlib fallback.

The live database is encrypted with SQLCipher (page-level AES; the data pages and
the WAL are never written in plaintext). ``sqlcipher3.dbapi2`` is a drop-in fork of
the stdlib ``sqlite3`` DB-API (same ``Connection`` / ``Row`` / ``Error`` /
``connect``), so importing it here under the name ``sqlite3`` lets the rest of the
package keep writing ``sqlite3.X`` unchanged — they just import it from this module.

The stdlib fallback exists ONLY so dev tooling / imports don't hard-fail when the
wheel is absent; in that mode the database is NOT encrypted. In production sqlcipher3
is installed into the runtime venv by install.sh (hash-pinned) and imported here, so
the database is always encrypted — the engine is NOT bundled into the binary (the
build is deliberately non-bundling).

IMPORTANT: when ``ENCRYPTION_AVAILABLE`` is False, ``connection.connect()`` /
``init_db()`` FAIL CLOSED (raise) unless ``LABDESK_ALLOW_PLAINTEXT=1`` is set — a
deliberate dev-only opt-in — so a mispackaged/incomplete install can never silently
write the patient database in cleartext. Code that must know which engine is active
can check ``ENCRYPTION_AVAILABLE``.
"""

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
