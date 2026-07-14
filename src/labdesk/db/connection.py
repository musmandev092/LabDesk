"""Connections + schema initialisation for LabDesk."""

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

# Session key (DB passphrase): memory-only, never written to disk. Set once at
# launch; LABDESK_DB_KEY env overrides for headless self-test/QA.
_SESSION_KEY: str | None = None


def _plaintext_allowed() -> bool:
    """DEV-ONLY escape hatch: must be explicitly opted into (never silent)."""
    return os.environ.get("LABDESK_ALLOW_PLAINTEXT") == "1"


def _require_encryption() -> None:
    """Fail closed if the cipher engine is absent and plaintext wasn't opted into."""
    if not ENCRYPTION_AVAILABLE and not _plaintext_allowed():
        raise RuntimeError(
            "SQLCipher is unavailable — refusing to open an UNENCRYPTED patient "
            "database. Reinstall LabDesk (the build must bundle sqlcipher3). To run "
            "without encryption for development only, set LABDESK_ALLOW_PLAINTEXT=1."
        )


def _assert_cipher_active(con) -> None:
    """Abort if PRAGMA cipher_version comes back empty (cipher not actually engaged)."""
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
    """Apply the SQLCipher key (quotes doubled — PRAGMA can't be parameterised)."""
    if key:
        con.execute("PRAGMA key = '{}'".format(key.replace("'", "''")))


def db_is_plaintext(path: Path) -> bool:
    """True if `path` is an unencrypted SQLite file (starts with the magic header)."""
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def verify_passphrase(passphrase: str, path: Path | None = None) -> bool:
    """True if `passphrase` actually decrypts the encrypted database at `path`."""
    target = path or db_path()
    if not Path(target).exists():
        return False
    if not passphrase:
        return False
    if not ENCRYPTION_AVAILABLE:
        return False
    if db_is_plaintext(Path(target)):
        return False
    try:
        con = sqlite3.connect(str(target), timeout=10)
        try:
            _apply_key(con, passphrase)
            # forces SQLCipher to decrypt a page; wrong key raises DatabaseError
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return True
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False


def connect(path: Path | None = None, *, key: str | None = None) -> sqlite3.Connection:
    _require_encryption()
    target = path or db_path()
    con = sqlite3.connect(target, timeout=10)
    con.row_factory = sqlite3.Row
    resolved = _resolve_key(key)
    _apply_key(con, resolved)  # must run before any other SQL
    if resolved:
        _assert_cipher_active(con)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    # WAL+NORMAL: crash-safe, no fsync per write — the on-launch backup is the
    # real durability net.
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA busy_timeout = 8000")  # let multiple instances share the DB
    con.execute("PRAGMA temp_store = MEMORY")
    _harden_perms(Path(target))
    return con


def init_db(
    path: Path | None = None, *, seed_admin: bool = True, from_seed: bool = True
) -> sqlite3.Connection:
    _require_encryption()
    target = path or db_path()
    # First run: build the live DB from the shipped seed catalog (encrypted if a
    # session key is set, plain copy otherwise — dev fallback).
    if from_seed and not Path(target).exists() and SEED_DB.exists():
        _create_db_from_seed(Path(target), _resolve_key())
    con = connect(path)
    con.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    _ensure_columns(con)
    _backfill_paisa(con)
    _ensure_indexes(con)
    _sync_catalog_from_seed(con)
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    if seed_admin:
        n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if n == 0:
            h, salt = hash_password("admin")
            # seeded admin is a one-time bootstrap — must change password on first login
            con.execute(
                "INSERT INTO users(username, full_name, pass_hash, salt, role, "
                "must_change_password) VALUES (?,?,?,?,?,1)",
                ("admin", "Administrator", h, salt, "admin"),
            )
        else:
            # shipped seed.sqlite may carry a legacy admin/admin account — force change
            adm = con.execute(
                "SELECT id, pass_hash, salt FROM users WHERE username='admin'"
            ).fetchone()
            if adm and _verify_password("admin", adm["pass_hash"], adm["salt"] or ""):
                con.execute(
                    "UPDATE users SET must_change_password=1 WHERE id=?", (adm["id"],)
                )
        # force reset of any legacy (non-scrypt) password hash so it rehashes to scrypt
        with contextlib.suppress(sqlite3.Error):
            con.execute(
                "UPDATE users SET must_change_password=1 "
                "WHERE pass_hash IS NOT NULL AND pass_hash NOT LIKE 'scrypt$%'"
            )
    con.commit()
    _harden_perms(Path(target))
    return con


def _create_db_from_seed(target: Path, key: str | None) -> None:
    """Build the live DB from the plaintext seed catalog (encrypted if key+cipher
    available via sqlcipher_export, else a dev-only plain copy)."""
    if not key or not ENCRYPTION_AVAILABLE:
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
    """Rekey the live DB in place (SQLCipher PRAGMA rekey) and adopt it as the
    session key. Backups made before this still need the OLD passphrase."""
    if not ENCRYPTION_AVAILABLE:
        return False
    if not verify_passphrase(old_passphrase):
        return False
    from .backup import backup_db  # local import avoids a connection<->backup cycle

    # safety copy (OLD key) before the in-place rewrite — refuse to rekey without it
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
    if not verify_passphrase(new_passphrase):
        return False
    unlock(new_passphrase)
    return True


def migrate_plaintext_to_encrypted(passphrase: str, path: Path | None = None) -> bool:
    """One-time upgrade of a legacy plaintext DB to encrypted, atomically swapped in."""
    target = Path(path or db_path())
    if not target.exists() or not db_is_plaintext(target) or not ENCRYPTION_AVAILABLE:
        return False
    enc = Path(str(target) + ".enc-tmp")
    with contextlib.suppress(OSError):
        enc.unlink()
    try:
        src = sqlite3.connect(str(target))
        try:
            src.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # fold -wal/-shm into file
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
    os.replace(str(enc), str(target))  # atomic swap
    for sidecar in ("-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(str(target) + sidecar).unlink()
    _harden_perms(target)
    return True


def _sync_catalog_from_seed(con: sqlite3.Connection) -> None:
    """Additively pull new tests/params from a newer seed catalog_version into an
    existing DB, without ever touching the lab's own edits (prices, ranges, etc.)."""
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

    # KEY '' attaches the plaintext seed unencrypted alongside the encrypted main DB
    if ENCRYPTION_AVAILABLE:
        con.execute("ATTACH DATABASE ? AS seed KEY ''", (str(SEED_DB),))
    else:
        con.execute("ATTACH DATABASE ? AS seed", (str(SEED_DB),))
    try:
        # additive only, matched by stable keys (legacy_no / seq+name) not the
        # autoincrement id, which the live DB reassigns — no UPDATE/DELETE ever
        tcols = [r[1] for r in con.execute('PRAGMA table_info("tests")')]
        scols = {r[1] for r in con.execute("PRAGMA seed.table_info('tests')")}
        tcols = [c for c in tcols if c in scols and c != "id"]  # don't force the id
        tlist = ", ".join(f'"{c}"' for c in tcols)
        tph = ", ".join("?" for _ in tcols)
        have_t = {
            r[0]
            for r in con.execute(
                "SELECT legacy_no FROM tests WHERE legacy_no IS NOT NULL"
            )
        }
        id_map: dict = {}  # seed tests.id -> live tests.id (every seed test present)
        for srow in con.execute(
            f"SELECT id, legacy_no, {tlist} FROM seed.tests ORDER BY id"
        ).fetchall():
            sid, legacy = srow[0], srow[1]
            if legacy is not None and legacy in have_t:
                live = con.execute(
                    "SELECT id FROM tests WHERE legacy_no=? LIMIT 1", (legacy,)
                ).fetchone()
                if live:
                    id_map[sid] = live[0]
                continue
            cur2 = con.execute(
                f"INSERT INTO tests ({tlist}) VALUES ({tph})", tuple(srow[2:])
            )
            id_map[sid] = cur2.lastrowid
            if legacy is not None:
                have_t.add(legacy)

        pcols = [r[1] for r in con.execute('PRAGMA table_info("test_parameters")')]
        spcols = {
            r[1] for r in con.execute("PRAGMA seed.table_info('test_parameters')")
        }
        pcols = [c for c in pcols if c in spcols and c != "id"]  # keeps test_id
        plist = ", ".join(f'"{c}"' for c in pcols)
        pph = ", ".join("?" for _ in pcols)
        ti, si, ni = pcols.index("test_id"), pcols.index("seq"), pcols.index("name")
        have_p = {
            (r[0], r[1], r[2] or "")
            for r in con.execute("SELECT test_id, seq, name FROM test_parameters")
        }
        for prow in con.execute(
            f"SELECT {plist} FROM seed.test_parameters ORDER BY id"
        ).fetchall():
            vals = list(prow)
            new_tid = id_map.get(vals[ti])
            if new_tid is None:
                continue  # parent test not shipped/mapped — skip orphan param
            vals[ti] = new_tid
            key = (new_tid, vals[si], (vals[ni] or ""))
            if key in have_p:
                continue
            con.execute(
                f"INSERT INTO test_parameters ({plist}) VALUES ({pph})", tuple(vals)
            )
            have_p.add(key)

        # bump catalog_version only after rows landed, so a failed sync retries later
        con.execute(
            "INSERT INTO settings(key,value) VALUES ('catalog_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(seed_ver),),
        )
        con.commit()  # must commit before DETACH
    except sqlite3.Error:
        # leave catalog_version unbumped so the sync retries next launch
        with contextlib.suppress(sqlite3.Error):
            con.rollback()
    finally:
        with contextlib.suppress(sqlite3.Error):
            con.execute("DETACH seed")


def _ensure_columns(con: sqlite3.Connection) -> None:
    """Add post-v1 columns to existing databases (no-op on fresh ones)."""
    for table, cols in _EXTRA_COLUMNS.items():
        existing = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        for name, decl in cols:
            if name not in existing:
                con.execute(f'ALTER TABLE "{table}" ADD COLUMN {name} {decl}')


def _backfill_paisa(con: sqlite3.Connection) -> None:
    """Populate NULL integer-paisa columns from their REAL twins (idempotent)."""
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
    """Create hot-path indexes + the unique lab_no guard (runs after _ensure_columns)."""
    for ddl in (
        "CREATE INDEX IF NOT EXISTS ix_patients_tel ON patients(telephone)",
        "CREATE INDEX IF NOT EXISTS ix_patients_mr ON patients(mr_no)",
        "CREATE INDEX IF NOT EXISTS ix_items_test ON receipt_items(test_id)",
        "CREATE INDEX IF NOT EXISTS ix_results_param ON results(parameter_id)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_date ON expenses(date)",
        "CREATE INDEX IF NOT EXISTS ix_ledger_date ON ledger(date)",
        "CREATE INDEX IF NOT EXISTS ix_audit_at ON audit_log(at)",
        "CREATE INDEX IF NOT EXISTS ix_receipts_patient ON receipts(patient_id)",
        "CREATE INDEX IF NOT EXISTS ix_receipts_doctor ON receipts(doctor_id)",
        "CREATE INDEX IF NOT EXISTS ix_cultures_item ON cultures(receipt_item_id)",
        "CREATE INDEX IF NOT EXISTS ix_cultsens_culture "
        "ON culture_sensitivity(culture_id)",
        "CREATE INDEX IF NOT EXISTS ix_panel_items_test ON panel_items(test_id)",
        # guards the daily-serial race: a lab number can never be issued twice
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_receipts_labno ON receipts(lab_no) "
        "WHERE lab_no IS NOT NULL",
    ):
        try:
            con.execute(ddl)
        except sqlite3.OperationalError:
            pass  # e.g. duplicate lab_no already present on a legacy DB
