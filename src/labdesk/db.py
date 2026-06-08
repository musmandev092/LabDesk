"""Database layer for LabDesk.

A thin wrapper over sqlite3: locates the data directory, initialises the
schema, seeds default settings + an admin user, and hands out connections.
The DB lives next to the user's data (XDG dir when packaged), so the AppImage
stays read-only while data persists across updates.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import time
from pathlib import Path

# Neutral, white-label product identity (per-lab branding is set by the wizard).
APP_NAME = "LabDesk"
APP_VERSION = "1.0.0"          # bump on each release (shown in the update notice)
SCHEMA_FILE = Path(__file__).with_name("schema.sql")
SEED_DB = Path(__file__).with_name("seed.sqlite")  # ships with the catalog

# Bump whenever the shipped catalog (tests/parameters/ranges) changes, so
# existing installs pull the updates from the new seed on next launch.
CATALOG_VERSION = "5"

DEFAULT_SETTINGS = {
    "configured": "0",            # set to "1" once the first-run wizard completes
    "catalog_version": CATALOG_VERSION,
    "lab_name": "",              # filled in by each lab via the setup wizard
    "lab_subtitle": "",
    "address": "",
    "phone": "",
    "mobile": "",
    "email": "",
    "currency": "Rs.",
    # default printer name (blank = show the print dialog each time)
    "default_printer": "",
    # special-day promo: a discount % auto-applied to every new bill (0 = off);
    # promo_until is an optional ISO date (YYYY-MM-DD) after which it stops.
    "promo_discount_pct": "0",
    "promo_until": "",
    "report_footer": "All results should be interpreted and correlated by the physician.",
    "logo_path": "",
    "lab_no_prefix": "LAB",
    # registration / accreditation (shown on the report header)
    "phc_reg_no": "",            # Punjab Healthcare Commission registration no.
    "lab_reg_no": "",            # lab / pharmacy registration no.
    "phc_logo_path": "",
    "accred_logo_1": "",
    "accred_logo_2": "",
    "accred_logo_3": "",
    # report footer signatories + department band
    "signatory_1_name": "",
    "signatory_1_title": "Consultant Pathologist",
    "signatory_2_name": "",
    "signatory_2_title": "Consultant Pathologist",
    "dept_band": "HEMATOLOGY  |  CHEMICAL PATHOLOGY  |  HORMONES  |  MOLECULAR BIOLOGY  |  HISTOPATHOLOGY",
    # Appearance
    "theme": "light",            # "light" | "dark"
    # security: auto-lock the screen after N minutes idle (0 = off)
    "idle_lock_minutes": "0",
    # WhatsApp (self-hosted wuzapi gateway, see whatsapp.py)
    "whatsapp_url": "",          # e.g. http://localhost:8080
    "whatsapp_session": "default",
    "whatsapp_country_code": "92",
    "whatsapp_auto": "0",        # "1" => auto-send report when results saved
    "whatsapp_auto_receipt": "0",  # "1" => auto-send the bill when a receipt is saved
    # NOTE: whatsapp_api_key is deliberately NOT a default setting — the token
    # lives only in the 0600 .secrets.json file, never in the DB/backups.
    # caption templates ({lab}, {lab_no}, {name} placeholders; blank = built-in)
    "whatsapp_report_caption": "",
    "whatsapp_receipt_caption": "",
    "whatsapp_timeout": "40",    # seconds for the upload before giving up
}

# Columns added after v1 — created on existing databases if missing.
_EXTRA_COLUMNS = {
    "patients": [("title", "TEXT"), ("mr_no", "TEXT"),
                 ("wa_optout", "INTEGER NOT NULL DEFAULT 0"),
                 # when the WhatsApp consent choice was last set (audit trail)
                 ("wa_consent_at", "TEXT")],
    "receipts": [("title", "TEXT"), ("mr_no", "TEXT"), ("case_no", "TEXT"),
                 ("reported_at", "TEXT"), ("payment_method", "TEXT"),
                 ("voided", "INTEGER NOT NULL DEFAULT 0"), ("void_reason", "TEXT"),
                 ("voided_at", "TEXT"), ("voided_by", "TEXT"),
                 ("delivered_at", "TEXT"), ("delivered_by", "TEXT")],
    # per-test free-text remarks printed under the results table
    "receipt_items": [("remarks", "TEXT")],
    # hide a parameter row from the printed report (kept in the entry screen)
    "results": [("hidden", "INTEGER NOT NULL DEFAULT 0")],
    # security: force first-login password change + brute-force lockout
    "users": [("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
              ("failed_attempts", "INTEGER NOT NULL DEFAULT 0"),
              ("locked_until", "TEXT")],
    # audit tamper-evidence: rolling hash chain
    "audit_log": [("hash", "TEXT")],
}

# brute-force lockout policy: lock after _MAX_FAILS wrong tries; the lockout
# window then doubles on every further failure (60s → 120s → 240s …) up to
# _LOCK_MAX_SECONDS, so a sustained guessing run is throttled, not just delayed.
_MAX_FAILS = 5
_LOCK_SECONDS = 60
_LOCK_MAX_SECONDS = 3600
# scrypt work factors (memory-hard; ~tens of ms per hash)
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 16384, 8, 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024


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
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
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
    try:
        os.chmod(assets, 0o700)
    except OSError:
        pass
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
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Password hashing — scrypt (memory-hard KDF, stdlib). The stored string is
# self-describing: "scrypt$N$r$p$salt$hexhash". Legacy sha256 rows are still
# verified and transparently upgraded on the next successful login.
# ---------------------------------------------------------------------------
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"),
                        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                        maxmem=_SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt}${dk.hex()}", ""


def _verify_password(password: str, stored: str, legacy_salt: str) -> bool:
    """Constant-time verification against a scrypt string or a legacy sha256 hash."""
    stored = stored or ""
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt, hexh = stored.split("$", 5)
            dk = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"),
                                n=int(n), r=int(r), p=int(p),
                                maxmem=_SCRYPT_MAXMEM, dklen=len(hexh) // 2)
            return hmac.compare_digest(dk.hex(), hexh)
        except Exception:
            return False
    h = hashlib.sha256(((legacy_salt or "") + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(h, stored)


_DUMMY_HASH = ""  # lazily-built scrypt string used only to equalise login timing


def _dummy_verify(password: str) -> None:
    """Run one scrypt hash on the user-miss path so an unknown/inactive username
    costs about the same as a real one — defeats username-enumeration via timing."""
    global _DUMMY_HASH
    if not _DUMMY_HASH:
        _DUMMY_HASH, _ = hash_password("login-timing-equaliser")
    _verify_password(password, _DUMMY_HASH, "")


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
    _ensure_indexes(con)           # after columns exist (some indexes depend on them)
    _sync_catalog_from_seed(con)   # pull updated tests/ranges into existing installs
    # seed default settings (only missing keys)
    for k, v in DEFAULT_SETTINGS.items():
        con.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v)
        )
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
        row = seed_ro.execute(
            "SELECT value FROM settings WHERE key='catalog_version'").fetchone()
        seed_ro.close()
    except Exception:
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
            f'INSERT INTO tests ({cols}) SELECT {cols} FROM seed.tests '
            f'WHERE id NOT IN (SELECT id FROM tests)'
        )
        pcols = [r[1] for r in con.execute('PRAGMA table_info("test_parameters")')]
        spcols = {r[1] for r in con.execute("PRAGMA seed.table_info('test_parameters')")}
        cols = ", ".join(f'"{c}"' for c in pcols if c in spcols)
        con.execute(
            f'INSERT INTO test_parameters ({cols}) SELECT {cols} FROM seed.test_parameters '
            f'WHERE id NOT IN (SELECT id FROM test_parameters)'
        )
        con.execute(
            "INSERT INTO settings(key,value) VALUES ('catalog_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(seed_ver),)
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
            pass   # e.g. duplicate lab_no already present on a legacy DB


# SQL fragment: receipts that are not voided (voided column is added post-v1, so
# COALESCE guards the NULL). Use inside WHERE clauses to exclude voided bills.
NOT_VOIDED = "COALESCE(voided,0)=0"

# SQL fragment: rows whose received_at falls in today (local time). Written as a
# half-open range so a plain index on received_at can be used (no date() wrap).
RECEIVED_TODAY = ("received_at >= date('now','localtime') "
                  "AND received_at < date('now','localtime','+1 day')")


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


def _audit_fallback(username, action, detail, err) -> None:
    """If the audit DB write fails, append to a local file so the gap is visible."""
    try:
        p = data_dir() / "audit_fallback.log"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"{username}\t{action}\t{detail}\t(audit-db-error: {err})\n")
        # this file can hold lab numbers / patient names — keep it owner-only
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    except Exception:
        pass


def log_audit(con: sqlite3.Connection, username: str, action: str, detail: str = "") -> None:
    """Append one tamper-evident entry to the audit trail (shown on the admin Logs
    page). Each row carries a rolling SHA-256 hash of (prev_hash, at, user, action,
    detail), so any later edit/deletion is detectable. Never raises — recording an
    action must never break the action itself; on DB failure it falls back to a file."""
    # str() coercion keeps the "never raises" contract even when a caller passes a
    # non-string (int/dict/object): slicing those directly would throw before the try.
    username = str(username or "")[:64]
    action = str(action or "")[:64]
    detail = str(detail or "")[:500]
    try:
        prev = con.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = (prev["hash"] or "") if (prev and "hash" in prev.keys()) else ""
        ts = con.execute("SELECT datetime('now','localtime')").fetchone()[0]
        chain = hashlib.sha256(
            "|".join([prev_hash, ts, username, action, detail]).encode("utf-8")
        ).hexdigest()
        con.execute(
            "INSERT INTO audit_log(at, username, action, detail, hash) VALUES (?,?,?,?,?)",
            (ts, username, action, detail, chain),
        )
        con.commit()
    except Exception as e:
        _audit_fallback(username, action, detail, e)


def verify_audit_chain(con: sqlite3.Connection):
    """Recompute the rolling hash chain. Returns (ok, first_bad_id|None). A
    mismatch or a missing hash after chaining began means the log was altered."""
    prev = ""
    started = False
    try:
        rows = con.execute(
            "SELECT id, at, username, action, detail, hash FROM audit_log ORDER BY id"
        ).fetchall()
    except Exception:
        return True, None
    for row in rows:
        if row["hash"] is None:
            if started:
                return False, row["id"]
            continue  # legacy rows that predate the hash chain
        started = True
        expect = hashlib.sha256(
            "|".join([prev, row["at"] or "", row["username"] or "",
                      row["action"] or "", row["detail"] or ""]).encode("utf-8")
        ).hexdigest()
        if row["hash"] != expect:
            return False, row["id"]
        prev = row["hash"]
    return True, None


def rechain_audit(con: sqlite3.Connection) -> None:
    """Recompute the rolling hash chain over all current rows. Used after an
    authorised purge (Clear old logs) so verify_audit_chain stays valid instead of
    reporting tampering at the new first row."""
    rows = con.execute(
        "SELECT id, at, username, action, detail FROM audit_log ORDER BY id"
    ).fetchall()
    prev = ""
    for r in rows:
        h = hashlib.sha256(
            "|".join([prev, r["at"] or "", r["username"] or "",
                      r["action"] or "", r["detail"] or ""]).encode("utf-8")
        ).hexdigest()
        con.execute("UPDATE audit_log SET hash=? WHERE id=?", (h, r["id"]))
        prev = h
    con.commit()


# ---------------------------------------------------------------------------
# Backups — SQLite online backup (safe while the app is running)
# ---------------------------------------------------------------------------
def backup_db(reason: str = "auto", keep: int = 14) -> Path | None:
    """Write a timestamped 0600 copy of the live DB to <data>/backups and prune to
    the newest `keep`. Returns the path, or None on failure / no DB yet."""
    src = db_path()
    if not src.exists():
        return None
    bdir = data_dir() / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(bdir, 0o700)
    except OSError:
        pass
    dest = bdir / f"labdesk-{time.strftime('%Y%m%d-%H%M%S')}-{reason}.sqlite"
    try:
        sc = sqlite3.connect(src)
        dc = sqlite3.connect(dest)
        with dc:
            sc.backup(dc)
        sc.close(); dc.close()
        os.chmod(dest, 0o600)
    except Exception:
        return None
    try:
        for old in sorted(bdir.glob("labdesk-*.sqlite"))[:-keep]:
            old.unlink()
    except Exception:
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
    except Exception:
        return False


def lock_remaining(con: sqlite3.Connection, username: str) -> int:
    """Seconds remaining on a brute-force lockout for this username (0 = none)."""
    row = con.execute("SELECT locked_until FROM users WHERE username=?", (username,)).fetchone()
    if not row or "locked_until" not in row.keys() or not row["locked_until"]:
        return 0
    try:
        return max(0, int(float(row["locked_until"]) - time.time()))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: a non-finite (inf) timestamp from a corrupted/edited DB.
        return 0


def verify_user(con: sqlite3.Connection, username: str, password: str):
    row = con.execute(
        "SELECT * FROM users WHERE username=? AND active=1", (username,)
    ).fetchone()
    if not row:
        _dummy_verify(password)   # equalise timing so missing users aren't detectable
        return None
    cols = row.keys()
    # locked out from too many recent failures?
    if "locked_until" in cols and row["locked_until"]:
        try:
            if time.time() < float(row["locked_until"]):
                return None
        except (TypeError, ValueError):
            pass
    legacy_salt = row["salt"] if "salt" in cols else ""
    if _verify_password(password, row["pass_hash"], legacy_salt):
        try:
            # transparently upgrade legacy sha256 hashes to scrypt
            if not (row["pass_hash"] or "").startswith("scrypt$"):
                newh, _ = hash_password(password)
                con.execute("UPDATE users SET pass_hash=?, salt='' WHERE id=?", (newh, row["id"]))
            con.execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?",
                        (row["id"],))
            con.commit()
        except Exception:
            pass
        return row
    # wrong password → count the failure, then lock with an exponentially
    # growing window once past _MAX_FAILS (60s, 120s, 240s … capped).
    try:
        fa = (row["failed_attempts"] if "failed_attempts" in cols and row["failed_attempts"] else 0) + 1
        lock = None
        if fa >= _MAX_FAILS:
            backoff = min(_LOCK_SECONDS * (2 ** (fa - _MAX_FAILS)), _LOCK_MAX_SECONDS)
            lock = str(time.time() + backoff)
        con.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
                    (fa, lock, row["id"]))
        con.commit()
    except Exception:
        pass
    return None


# ---- test panels / profiles -------------------------------------------------
def list_panels(con: sqlite3.Connection, include_inactive: bool = False):
    """Named test bundles (e.g. "Fever Profile"), newest-friendly alphabetical."""
    q = "SELECT * FROM panels"
    if not include_inactive:
        q += " WHERE active=1"
    q += " ORDER BY name COLLATE NOCASE"
    return con.execute(q).fetchall()


def panel_tests(con: sqlite3.Connection, panel_id: int):
    """The tests in a panel (only ones that still exist), alphabetical."""
    return con.execute(
        "SELECT t.id, t.name, t.charges FROM panel_items pi "
        "JOIN tests t ON t.id = pi.test_id "
        "WHERE pi.panel_id=? ORDER BY t.name COLLATE NOCASE", (panel_id,)
    ).fetchall()


def save_panel(con: sqlite3.Connection, name: str, test_ids, panel_id: int | None = None) -> int:
    """Create or update a panel and its member tests in one transaction."""
    name = (name or "").strip()
    if not name:
        raise ValueError("panel name is required")
    ids = [int(t) for t in test_ids]
    if panel_id is None:
        panel_id = con.execute(
            "INSERT INTO panels(name, active) VALUES (?,1)", (name,)).lastrowid
    else:
        con.execute("UPDATE panels SET name=?, active=1 WHERE id=?", (name, panel_id))
        con.execute("DELETE FROM panel_items WHERE panel_id=?", (panel_id,))
    for tid in ids:
        con.execute("INSERT INTO panel_items(panel_id, test_id) VALUES (?,?)", (panel_id, tid))
    con.commit()
    return panel_id


def delete_panel(con: sqlite3.Connection, panel_id: int) -> None:
    """Soft-delete (retire) a panel; member rows go with it."""
    con.execute("UPDATE panels SET active=0 WHERE id=?", (panel_id,))
    con.execute("DELETE FROM panel_items WHERE panel_id=?", (panel_id,))
    con.commit()


def receive_due(con: sqlite3.Connection, receipt_id: int, amount: float, username: str):
    """Record a (partial) due payment on a receipt: ledger credit + updated
    paid/due, audited. Returns (lab_no, new_paid, new_due) or None if nothing
    is owed. Shared by the Receipts page and the Accounts dues tab."""
    r = con.execute(
        "SELECT lab_no, net_amount, paid, due FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    if not r or not r["due"] or r["due"] <= 0 or amount <= 0:
        return None
    new_paid = round((r["paid"] or 0) + amount, 2)
    new_due = round(max(0.0, (r["net_amount"] or 0) - new_paid), 2)
    con.execute(
        "INSERT INTO ledger(kind,ref_id,detail,credit,date) "
        "VALUES ('due_recovery',?,?,?,date('now','localtime'))",
        (receipt_id, f"Due recovered {r['lab_no']}", amount))
    con.execute("UPDATE receipts SET paid=?, due=? WHERE id=?", (new_paid, new_due, receipt_id))
    con.commit()
    cur = currency(con)
    log_audit(con, username, "due_received",
              f"{r['lab_no']} — {cur} {amount:,.0f} (due now {cur} {new_due:,.0f})")
    return (r["lab_no"], new_paid, new_due)


# ---- in-app parameter editor ------------------------------------------------
class ParameterInUseError(Exception):
    """Raised when the editor tries to remove a parameter that already has saved
    results on a patient report (deleting it would orphan that history)."""
    def __init__(self, names):
        self.names = list(names)
        super().__init__(
            "These parameters have saved patient results and can't be removed: "
            + ", ".join(self.names))


def save_test_parameters(con: sqlite3.Connection, test_id: int, rows) -> None:
    """Persist the report-line definitions for a test from the in-app editor.

    Diff-based so existing parameter IDs (and any patient results referencing
    them) survive: existing rows are UPDATEd in place, new rows INSERTed, and
    rows the user removed are DELETEd — unless they already have saved results,
    in which case nothing is saved and ParameterInUseError is raised.
    """
    old = con.execute(
        "SELECT id, name FROM test_parameters WHERE test_id=?", (test_id,)).fetchall()
    old_ids = {r["id"]: (r["name"] or "") for r in old}
    keep = set()
    try:
        for seq, r in enumerate(rows):
            vals = (seq, (r.get("part_type") or "N"), r.get("name") or "",
                    r.get("units") or "", r.get("ref_male") or "", r.get("ref_female") or "",
                    r.get("default_result") or "", r.get("superscript") or "",
                    r.get("group_head") or "")
            pid = r.get("id")
            if pid and pid in old_ids:
                con.execute(
                    "UPDATE test_parameters SET seq=?,part_type=?,name=?,units=?,ref_male=?,"
                    "ref_female=?,default_result=?,superscript=?,group_head=? WHERE id=?",
                    (*vals, pid))
                keep.add(pid)
            else:
                con.execute(
                    "INSERT INTO test_parameters(test_id,seq,part_type,name,units,ref_male,"
                    "ref_female,default_result,superscript,group_head) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", (test_id, *vals))
        in_use = []
        for pid, name in old_ids.items():
            if pid in keep:
                continue
            if con.execute("SELECT 1 FROM results WHERE parameter_id=? LIMIT 1", (pid,)).fetchone():
                in_use.append(name or f"#{pid}")
            else:
                con.execute("DELETE FROM test_parameters WHERE id=?", (pid,))
        if in_use:
            con.rollback()
            raise ParameterInUseError(in_use)
        con.commit()
    except ParameterInUseError:
        raise
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
