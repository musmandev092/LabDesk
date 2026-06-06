"""Database layer for LabDesk.

A thin wrapper over sqlite3: locates the data directory, initialises the
schema, seeds default settings + an admin user, and hands out connections.
The DB lives next to the user's data (XDG dir when packaged), so the AppImage
stays read-only while data persists across updates.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import sqlite3
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
    # WhatsApp (self-hosted wuzapi gateway, see whatsapp.py)
    "whatsapp_url": "",          # e.g. http://localhost:8080
    "whatsapp_session": "default",
    "whatsapp_country_code": "92",
    "whatsapp_auto": "0",        # "1" => auto-send report when results saved
    "whatsapp_auto_receipt": "0",  # "1" => auto-send the bill when a receipt is saved
    "whatsapp_api_key": "",
    # caption templates ({lab}, {lab_no}, {name} placeholders; blank = built-in)
    "whatsapp_report_caption": "",
    "whatsapp_receipt_caption": "",
    "whatsapp_timeout": "40",    # seconds for the upload before giving up
}

# Columns added after v1 — created on existing databases if missing.
_EXTRA_COLUMNS = {
    "patients": [("title", "TEXT"), ("mr_no", "TEXT")],
    "receipts": [("title", "TEXT"), ("mr_no", "TEXT"), ("case_no", "TEXT")],
    # per-test free-text remarks printed under the results table
    "receipt_items": [("remarks", "TEXT")],
    # hide a parameter row from the printed report (kept in the entry screen)
    "results": [("hidden", "INTEGER NOT NULL DEFAULT 0")],
}


def data_dir() -> Path:
    """Where the live database + assets are stored (writable)."""
    override = os.environ.get("LABDESK_DATA_DIR")
    if override:
        d = Path(override)
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "labdesk.sqlite"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt


def connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 8000")  # let multiple instances share the DB
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
            con.execute(
                "INSERT INTO users(username, full_name, pass_hash, salt, role) "
                "VALUES (?,?,?,?,?)",
                ("admin", "Administrator", h, salt, "admin"),
            )
    con.commit()
    return con


def _sync_catalog_from_seed(con: sqlite3.Connection) -> None:
    """Update an existing DB's catalog (tests + parameters + ranges) from the
    shipped seed when the seed is newer. Patient/receipt/result/settings data is
    untouched. Past reports keep their own snapshotted ranges, so this is safe.
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
        # 1) refresh reference ranges + units on every parameter that exists in both
        con.execute(
            """UPDATE test_parameters SET
                 ref_male   = (SELECT s.ref_male   FROM seed.test_parameters s WHERE s.id=test_parameters.id),
                 ref_female = (SELECT s.ref_female FROM seed.test_parameters s WHERE s.id=test_parameters.id),
                 units      = (SELECT s.units      FROM seed.test_parameters s WHERE s.id=test_parameters.id)
               WHERE id IN (SELECT id FROM seed.test_parameters)"""
        )
        # 2) add tests/params that the seed has but this DB doesn't
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
        # remove known junk placeholder parameters from older installs
        con.execute(
            "DELETE FROM test_parameters WHERE name IN "
            "('b','bb','bbb','bbbb','bbbbb','bbbbbb') OR name LIKE '741%'"
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


def get_setting(con: sqlite3.Connection, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row and row[0] is not None else default


def set_setting(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO settings(key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    con.commit()


def log_audit(con: sqlite3.Connection, username: str, action: str, detail: str = "") -> None:
    """Append one entry to the audit trail (shown on the admin Logs page).
    Never raises — recording an action must never break the action itself."""
    try:
        con.execute(
            "INSERT INTO audit_log(username, action, detail) VALUES (?,?,?)",
            ((username or "")[:64], (action or "")[:64], (detail or "")[:500]),
        )
        con.commit()
    except Exception:  # noqa: BLE001
        pass


def verify_user(con: sqlite3.Connection, username: str, password: str):
    row = con.execute(
        "SELECT * FROM users WHERE username=? AND active=1", (username,)
    ).fetchone()
    if not row:
        return None
    h, _ = hash_password(password, row["salt"])
    return row if h == row["pass_hash"] else None
