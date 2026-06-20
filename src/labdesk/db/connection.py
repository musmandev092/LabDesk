"""Connections + schema initialisation for LabDesk.

Opens hardened sqlite3 connections, initialises the schema, applies post-v1
column/index migrations, and additively syncs the shipped catalog into existing
installs.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

from ._config import (
    _EXTRA_COLUMNS,
    _PAISA_COLUMNS,
    DEFAULT_SETTINGS,
    SCHEMA_FILE,
    SEED_DB,
)
from ._driver import ENCRYPTION_AVAILABLE, sqlite3
from .crypto import _verify_password, hash_password
from .paths import _harden_perms, db_path

# ---------------------------------------------------------------------------
# Session key (the DB passphrase). Held in memory only — NEVER written to disk;
# SQLCipher keeps its KDF salt in the DB header, so the same passphrase reopens
# the file. Set once at launch (unlock dialog / setup wizard); every connect()
# on any thread then reads it. LABDESK_DB_KEY env is an override for headless
# self-test / QA. There is no recovery: lose the passphrase, lose the data.
# ---------------------------------------------------------------------------
_SESSION_KEY: str | None = None


def _plaintext_allowed() -> bool:
    """Plaintext (stdlib sqlite3) operation is a DEV-ONLY escape hatch. It must be
    opted into explicitly so a mispackaged/stripped build — where sqlcipher3 fails to
    load — can never silently write the patient database in cleartext."""
    return os.environ.get("LABDESK_ALLOW_PLAINTEXT") == "1"


def _require_encryption() -> None:
    """Fail closed: refuse to touch the database when the encryption engine is absent,
    unless plaintext mode was explicitly opted into for development."""
    if not ENCRYPTION_AVAILABLE and not _plaintext_allowed():
        raise RuntimeError(
            "SQLCipher is unavailable — refusing to open an UNENCRYPTED patient "
            "database. Reinstall LabDesk (the build must bundle sqlcipher3). To run "
            "without encryption for development only, set LABDESK_ALLOW_PLAINTEXT=1."
        )


def _assert_cipher_active(con) -> None:
    """Prove the cipher is actually engaged on an encrypted connection. On real
    SQLCipher `PRAGMA cipher_version` returns a non-empty version string; on stdlib
    sqlite3 it returns nothing. An empty result means the data would be written in
    cleartext, so abort rather than proceed under a false sense of encryption."""
    if not ENCRYPTION_AVAILABLE:
        return
    try:
        row = con.execute("PRAGMA cipher_version").fetchone()
    except sqlite3.Error:
        row = None
    if not (row and row[0]):
        con.close()
        raise RuntimeError(
            "Database opened without an active cipher (PRAGMA cipher_version empty) — "
            "aborting to avoid writing patient data in cleartext."
        )


def unlock(passphrase: str) -> None:
    """Hold the DB passphrase for this process so connect() can open the DB."""
    global _SESSION_KEY
    _SESSION_KEY = passphrase or None


def lock() -> None:
    global _SESSION_KEY
    _SESSION_KEY = None


def _resolve_key(explicit: str | None = None) -> str | None:
    if explicit is not None:
        return explicit
    return _SESSION_KEY or os.environ.get("LABDESK_DB_KEY") or None


def is_unlocked() -> bool:
    return _resolve_key() is not None


def _apply_key(con, key: str | None) -> None:
    """Apply the SQLCipher key. PRAGMA can't be parameterised, so the passphrase is
    inlined with doubled single-quotes (standard SQL string escaping) — injection-safe.
    Must run BEFORE any other statement touches the database."""
    if key:
        con.execute("PRAGMA key = '{}'".format(key.replace("'", "''")))


def db_is_plaintext(path: Path) -> bool:
    """True if `path` is an UNENCRYPTED SQLite file (starts with the magic header).
    Used to detect a legacy plaintext install that needs migrating to encrypted."""
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def verify_passphrase(passphrase: str, path: Path | None = None) -> bool:
    """True if `passphrase` actually decrypts the ENCRYPTED database at `path` (the
    unlock check). Fails closed for the cases that would otherwise wave any passphrase
    through: an empty passphrase, a non-encrypted (plaintext) file, or a build without
    the cipher engine — none of which constitute a verified unlock of encrypted data."""
    target = path or db_path()
    if not Path(target).exists():
        return False
    if not passphrase:
        return False  # an empty key never "unlocks" an encrypted DB
    if not ENCRYPTION_AVAILABLE:
        return False  # can't verify encryption without the cipher engine
    if db_is_plaintext(Path(target)):
        return False  # a plaintext file is not unlocked by a passphrase — it must be migrated
    try:
        con = sqlite3.connect(str(target), timeout=10)
        try:
            _apply_key(con, passphrase)
            # Reading a page forces SQLCipher to derive the key and decrypt; a wrong
            # passphrase raises DatabaseError here rather than returning a bogus True.
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return True
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False


def connect(path: Path | None = None, *, key: str | None = None) -> sqlite3.Connection:
    _require_encryption()  # fail closed if the cipher engine is missing (no silent plaintext)
    target = path or db_path()
    con = sqlite3.connect(target, timeout=10)
    con.row_factory = sqlite3.Row
    resolved = _resolve_key(key)
    _apply_key(con, resolved)  # SQLCipher key first, before any other SQL
    if resolved:
        _assert_cipher_active(con)  # confirm AES is really engaged, not a silent no-op
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    # WAL + NORMAL is the SQLite-recommended pairing: commits no longer fsync on
    # every write (only at checkpoint), which is what made each Save feel slow on
    # spinning/USB disks. It is crash-safe — the DB can never corrupt; at worst a
    # power loss drops the last just-committed transaction, an acceptable trade for
    # a single-site desktop app (the on-launch backup is the real durability net).
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA busy_timeout = 8000")  # let multiple instances share the DB
    con.execute("PRAGMA temp_store = MEMORY")  # sorts/temp tables in RAM, not on disk
    _harden_perms(Path(target))
    return con


def init_db(
    path: Path | None = None, *, seed_admin: bool = True, from_seed: bool = True
) -> sqlite3.Connection:
    _require_encryption()  # fail closed before any file is created (no silent plaintext)
    target = path or db_path()
    # First run: build the live DB from the shipped (plaintext) seed catalog. With a
    # session key set, the seed is imported into a NEW ENCRYPTED database; without a
    # key (dev fallback) it's a plain copy.
    if from_seed and not Path(target).exists() and SEED_DB.exists():
        _create_db_from_seed(Path(target), _resolve_key())
    con = connect(path)
    con.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    _ensure_columns(con)
    _backfill_paisa(con)  # populate integer-paisa twins from REAL (after columns exist)
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
                con.execute(
                    "UPDATE users SET must_change_password=1 WHERE id=?", (adm["id"],)
                )
        # Force any account still on a legacy (non-scrypt) password hash to reset
        # it — the next login then rehashes to scrypt. Fresh installs have none.
        with contextlib.suppress(sqlite3.Error):
            con.execute(
                "UPDATE users SET must_change_password=1 "
                "WHERE pass_hash IS NOT NULL AND pass_hash NOT LIKE 'scrypt$%'"
            )
    con.commit()
    _harden_perms(Path(target))
    return con


def _create_db_from_seed(target: Path, key: str | None) -> None:
    """Build the live DB from the plaintext seed catalog. With a key (and SQLCipher
    available), import the seed into a NEW ENCRYPTED database via sqlcipher_export;
    otherwise copy it as-is (dev fallback — unencrypted)."""
    if not key or not ENCRYPTION_AVAILABLE:
        # Plaintext seed copy is a dev-only fallback. Never do it silently in a build
        # that lacks the cipher — that is exactly the silent-plaintext footgun.
        if not _plaintext_allowed():
            raise RuntimeError(
                "Refusing to create an unencrypted database from the seed "
                "(SQLCipher unavailable or no key). Set LABDESK_ALLOW_PLAINTEXT=1 for dev only."
            )
        shutil.copyfile(SEED_DB, target)
        return
    src = sqlite3.connect(str(SEED_DB))  # plaintext seed, opened with no key
    try:
        # attach a fresh encrypted DB and copy the whole seed (schema + catalog) in
        src.execute(
            "ATTACH DATABASE ? AS enc KEY '{}'".format(key.replace("'", "''")),
            (str(target),),
        )
        src.execute("SELECT sqlcipher_export('enc')")
        src.execute("DETACH DATABASE enc")
    finally:
        src.close()
    _harden_perms(target)


def rekey_database(
    con: sqlite3.Connection, old_passphrase: str, new_passphrase: str
) -> bool:
    """Change the database passphrase IN PLACE on the live connection (SQLCipher
    ``PRAGMA rekey``), re-encrypting every page with the new key and adopting it as
    the session key (so the open connection keeps working and future connections use
    the new key — no restart needed). Verifies the old passphrase and takes a backup
    (encrypted with the OLD key) first. Returns True on success.

    NOTE: backups made BEFORE this still require the OLD passphrase to restore — the
    caller must warn the user.
    """
    if not ENCRYPTION_AVAILABLE:
        return False
    if not verify_passphrase(old_passphrase):  # independent check the old one is right
        return False
    from .backup import backup_db  # local import avoids a connection<->backup cycle

    # Safety copy (encrypted with the OLD key) BEFORE the in-place rewrite. If it
    # can't be written, refuse to rekey — a failed rewrite with no backup could
    # otherwise leave the only copy of the data unrecoverable.
    try:
        if backup_db("pre-rekey") is None:
            return False
    except Exception:
        return False
    try:
        con.execute("PRAGMA rekey = '{}'".format(new_passphrase.replace("'", "''")))
        con.commit()
    except sqlite3.Error:
        return False
    if not verify_passphrase(new_passphrase):  # confirm the rewrite took
        return False
    unlock(new_passphrase)
    return True


def migrate_plaintext_to_encrypted(passphrase: str, path: Path | None = None) -> bool:
    """One-time upgrade of a legacy PLAINTEXT database to an encrypted one with the
    given passphrase. Builds the encrypted copy, VERIFIES it opens, then atomically
    swaps it in (os.replace) — so a failure can never lose data — and drops the WAL
    sidecars. Returns True on success, False if there is nothing to migrate or it
    failed (original left untouched)."""
    target = Path(path or db_path())
    if not target.exists() or not db_is_plaintext(target) or not ENCRYPTION_AVAILABLE:
        return False
    enc = Path(str(target) + ".enc-tmp")
    with contextlib.suppress(OSError):
        enc.unlink()
    try:
        src = sqlite3.connect(str(target))
        try:
            src.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            )  # fold -wal/-shm into the file
            src.execute(
                "ATTACH DATABASE ? AS enc KEY '{}'".format(
                    passphrase.replace("'", "''")
                ),
                (str(enc),),
            )
            src.execute("SELECT sqlcipher_export('enc')")
            src.execute("DETACH DATABASE enc")
        finally:
            src.close()
    except sqlite3.Error:
        with contextlib.suppress(OSError):
            enc.unlink()
        return False
    # only destroy the plaintext original once the encrypted copy verifies-opens
    if not verify_passphrase(passphrase, enc):
        with contextlib.suppress(OSError):
            enc.unlink()
        return False
    os.replace(str(enc), str(target))  # atomic: plaintext original is overwritten
    for sidecar in ("-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(str(target) + sidecar).unlink()
    _harden_perms(target)
    return True


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
        row = seed_ro.execute(
            "SELECT value FROM settings WHERE key='catalog_version'"
        ).fetchone()
        seed_ro.close()
    except sqlite3.Error:
        return
    seed_ver = int(row[0]) if row and str(row[0]).isdigit() else 1
    cur = con.execute(
        "SELECT value FROM settings WHERE key='catalog_version'"
    ).fetchone()
    live_ver = int(cur[0]) if cur and str(cur[0]).isdigit() else 1
    if live_ver >= seed_ver:
        return

    # The shipped seed is plaintext; KEY '' tells SQLCipher to attach it unencrypted
    # alongside the encrypted main DB. (Plain ATTACH on the stdlib dev fallback.)
    if ENCRYPTION_AVAILABLE:
        con.execute("ATTACH DATABASE ? AS seed KEY ''", (str(SEED_DB),))
    else:
        con.execute("ATTACH DATABASE ? AS seed", (str(SEED_DB),))
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
        spcols = {
            r[1] for r in con.execute("PRAGMA seed.table_info('test_parameters')")
        }
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


def _backfill_paisa(con: sqlite3.Connection) -> None:
    """Populate the integer-paisa money columns from their REAL twins wherever a paisa
    value is still missing. Idempotent (only touches NULL paisa rows) and guarded, so
    it runs harmlessly on every open. Uses SQL ROUND — the same rounding the inline
    dual-writes use — so paisa always equals round(real*100)."""
    for table, pairs in _PAISA_COLUMNS.items():
        for real_col, paisa_col in pairs:
            with contextlib.suppress(sqlite3.Error):
                con.execute(
                    f'UPDATE "{table}" SET {paisa_col} = '
                    f"CAST(ROUND({real_col} * 100) AS INTEGER) "
                    f"WHERE {paisa_col} IS NULL AND {real_col} IS NOT NULL"
                )
    con.commit()


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
        # foreign-key columns lacking a covering index → full scans on lookups and
        # slow ON DELETE CASCADE on the fastest-growing tables (DB review finding).
        "CREATE INDEX IF NOT EXISTS ix_receipts_patient ON receipts(patient_id)",
        "CREATE INDEX IF NOT EXISTS ix_receipts_doctor ON receipts(doctor_id)",
        "CREATE INDEX IF NOT EXISTS ix_cultures_item ON cultures(receipt_item_id)",
        "CREATE INDEX IF NOT EXISTS ix_cultsens_culture "
        "ON culture_sensitivity(culture_id)",
        "CREATE INDEX IF NOT EXISTS ix_panel_items_test ON panel_items(test_id)",
        # one lab number can never be issued twice (guards the daily-serial race)
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_receipts_labno ON receipts(lab_no) "
        "WHERE lab_no IS NOT NULL",
    ):
        try:
            con.execute(ddl)
        except sqlite3.OperationalError:
            pass  # e.g. duplicate lab_no already present on a legacy DB
