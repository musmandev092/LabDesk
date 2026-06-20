"""Settings table accessors (key/value store)."""

from __future__ import annotations

from ._driver import sqlite3


def get_setting(con: sqlite3.Connection, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row and row[0] is not None else default


def currency(con: sqlite3.Connection) -> str:
    """The configured currency symbol (defaults to 'Rs.')."""
    return get_setting(con, "currency", "Rs.")


def set_setting(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO settings(key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    con.commit()


def set_settings(con: sqlite3.Connection, mapping) -> None:
    """Upsert many settings in ONE transaction (a single commit). set_setting()
    fsyncs on every call, so saving a whole form key-by-key did ~30 disk syncs and
    visibly froze the UI; this writes them all at once."""
    items = list(mapping.items())
    if not items:
        return
    con.executemany(
        "INSERT INTO settings(key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        items,
    )
    con.commit()
