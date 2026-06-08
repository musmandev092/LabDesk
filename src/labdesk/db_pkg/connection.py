"""Connection factory + schema initialisation / catalog sync / migrations."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from ._config import DEFAULT_SETTINGS, SCHEMA_FILE, SEED_DB, _EXTRA_COLUMNS
from .crypto import _verify_password, hash_password
from .paths import _harden_perms, db_path


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or db_path()
    con = sqlite3.connect(target, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 8000")  # let multiple instances share the DB
    _harden_perms(Path(target))
    return con


def init_db(
    path: Path | None = None, *, seed_admin: bool = True, from_seed: bool = True
) -> sqlite3.Connection:
    target = path or db_path()
    # First run: if no live DB yet but a seed (with the test catalog) ships
    # alongside the app, start from that instead of an empty database.
    if from_seed and not Path(target).exists() and SEED_DB.exists():
        shutil.copyfile(SEED_DB, target)
    con = connect(path)
    con.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    _ensure_columns(con)
    _ensure_indexes(con)  # after columns exist (some indexes depend on them)
    _sync_catalog_from_seed(con)  # pull updated tests/ranges into existing installs
    # seed default settings (only missing keys)
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    # seed default admin if no users exist
    if seed_admin:
        n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if n == 0:
            h, salt = hash_password("admin")
            # default admin must change its password on first login (the seeded
            # 'admin' credential is a one-time bootstrap, never a usable account).
            con.execute(
                "INSERT INTO users(username, full_name, pass_hash, salt, role, "
                "must_change_password) VALUES (?,?,?,?,?,1)",
                ("admin", "Administrator", h, salt, "admin"),
            )
        else:
            # the shipped seed.sqlite may carry a legacy 'admin'/'admin' account;
            # if it still uses the default password, force a change on first login.
            adm = con.execute(
                "SELECT id, pass_hash, salt FROM users WHERE username='admin'"
            ).fetchone()
            if adm and _verify_password("admin", adm["pass_hash"], adm["salt"] or ""):
                con.execute("UPDATE users SET must_change_password=1 WHERE id=?", (adm["id"],))
        # Force any account still on a legacy (non-scrypt) password hash to reset
        # it — the next login then rehashes to scrypt. Fresh installs have none.
        try:
            con.execute(
                "UPDATE users SET must_change_password=1 "
                "WHERE pass_hash IS NOT NULL AND pass_hash NOT LIKE 'scrypt$%'"
            )
        except sqlite3.Error:
            pass
    con.commit()
    _harden_perms(Path(target))
    return con


def _sync_catalog_from_seed(con: sqlite3.Connection) -> None:
    """Bring a newer catalog version's *additions* into an existing DB — WITHOUT
    ever overwriting the lab's own catalog.

    After first run the lab OWNS its catalog. An app update may ship new tests in
    a higher `catalog_version`; this only INSERTs tests/parameters this DB does
    not already have (matched by id). Existing rows — prices (charges), reference
    ranges, units, names, the active/retired flag — are NEVER modified or deleted.
    So pushing a new AppImage + checksum can add tests but can never reset a price
    or a range the lab edited. (Past reports keep their own snapshotted ranges.)

    To push a *correction* to an existing test, change it in the in-app Test
    Catalog editor — deliberately, by an admin — not silently via an update.
    """
    if not SEED_DB.exists():
        return
    try:
        seed_ro = sqlite3.connect(f"file:{SEED_DB}?mode=ro", uri=True)
        row = seed_ro.execute("SELECT value FROM settings WHERE key='catalog_version'").fetchone()
        seed_ro.close()
    except sqlite3.Error:
        return
    seed_ver = int(row[0]) if row and str(row[0]).isdigit() else 1
    cur = con.execute("SELECT value FROM settings WHERE key='catalog_version'").fetchone()
    live_ver = int(cur[0]) if cur and str(cur[0]).isdigit() else 1
    if live_ver >= seed_ver:
        return

    con.execute("ATTACH ? AS seed", (str(SEED_DB),))
    try:
        # ADDITIVE ONLY: insert tests/params the seed has but this DB doesn't
        # (matched by id). No UPDATE, no DELETE — the lab's edits are sacrosanct.
        tcols = [r[1] for r in con.execute('PRAGMA table_info("tests")')]
        scols = {r[1] for r in con.execute("PRAGMA seed.table_info('tests')")}
        cols = ", ".join(f'"{c}"' for c in tcols if c in scols)
        con.execute(
            f"INSERT INTO tests ({cols}) SELECT {cols} FROM seed.tests "
            f"WHERE id NOT IN (SELECT id FROM tests)"
        )
        pcols = [r[1] for r in con.execute('PRAGMA table_info("test_parameters")')]
        spcols = {r[1] for r in con.execute("PRAGMA seed.table_info('test_parameters')")}
        cols = ", ".join(f'"{c}"' for c in pcols if c in spcols)
        con.execute(
            f"INSERT INTO test_parameters ({cols}) SELECT {cols} FROM seed.test_parameters "
            f"WHERE id NOT IN (SELECT id FROM test_parameters)"
        )
        con.execute(
            "INSERT INTO settings(key,value) VALUES ('catalog_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(seed_ver),),
        )
        con.commit()  # must commit before DETACH (no open transaction allowed)
    finally:
        con.execute("DETACH seed")


def _ensure_columns(con: sqlite3.Connection) -> None:
    """Add post-v1 columns to existing databases (no-op on fresh ones)."""
    for table, cols in _EXTRA_COLUMNS.items():
        existing = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        for name, decl in cols:
            if name not in existing:
                con.execute(f'ALTER TABLE "{table}" ADD COLUMN {name} {decl}')


def _ensure_indexes(con: sqlite3.Connection) -> None:
    """Create hot-path indexes (some depend on post-v1 columns, so this runs after
    _ensure_columns) and the unique lab_no guard. Each is independent + guarded so
    a pre-existing duplicate lab_no can't block startup."""
    for ddl in (
        "CREATE INDEX IF NOT EXISTS ix_patients_tel ON patients(telephone)",
        "CREATE INDEX IF NOT EXISTS ix_patients_mr ON patients(mr_no)",
        "CREATE INDEX IF NOT EXISTS ix_items_test ON receipt_items(test_id)",
        "CREATE INDEX IF NOT EXISTS ix_results_param ON results(parameter_id)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_date ON expenses(date)",
        "CREATE INDEX IF NOT EXISTS ix_ledger_date ON ledger(date)",
        "CREATE INDEX IF NOT EXISTS ix_audit_at ON audit_log(at)",
        # one lab number can never be issued twice (guards the daily-serial race)
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_receipts_labno ON receipts(lab_no) "
        "WHERE lab_no IS NOT NULL",
    ):
        try:
            con.execute(ddl)
        except sqlite3.OperationalError:
            pass  # e.g. duplicate lab_no already present on a legacy DB
