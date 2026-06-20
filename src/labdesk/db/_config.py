"""Constants for the LabDesk database layer.

Product identity, schema/seed locations, the shipped catalog version, default
settings, post-v1 column additions, brute-force lockout policy, scrypt work
factors, and the reusable SQL fragments. No logic lives here.
"""

from __future__ import annotations

from labdesk import __version__

from .._resources import schema_file, seed_db

# Neutral, white-label product identity (per-lab branding is set by the wizard).
APP_NAME = "LabDesk"
# Single source of truth for the app version: the package's __version__ (which reads
# installed metadata with a hard-coded fallback — see src/labdesk/__init__.py).
# Re-exported as db.APP_VERSION and shown in the "Updated to vX" notice / crash log.
APP_VERSION = __version__

# schema.sql / seed.sqlite: baked into the compiled binary and materialised to a
# private temp dir, or read from the package in dev — see labdesk._resources.
SCHEMA_FILE = schema_file()
SEED_DB = seed_db()  # ships with the catalog

# Bump whenever the shipped catalog (tests/parameters/ranges) changes, so
# existing installs pull the updates from the new seed on next launch.
CATALOG_VERSION = "7"

DEFAULT_SETTINGS = {
    "configured": "0",  # set to "1" once the first-run wizard completes
    "catalog_version": CATALOG_VERSION,
    "lab_name": "",  # filled in by each lab via the setup wizard
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
    "phc_reg_no": "",  # Punjab Healthcare Commission registration no.
    "lab_reg_no": "",  # lab / pharmacy registration no.
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
    # cash-receipt footer text (was hard-coded in report.py; now lab-editable)
    "receipt_footer_note": "Computer-generated document. No signature required.",
    "receipt_remarks": (
        "Please present this receipt to collect your report. Reports are "
        "issued strictly following final verification and signature by the "
        "consultant pathologist."
    ),
    # cumulative reporting: print up to 3 prior dated result columns on numeric
    # reports when the patient has previous results for the same test. Turn off to
    # print current-only reports (the house style of many smaller labs).
    "show_history": "1",
    # Appearance
    "theme": "light",  # "light" | "dark"
    # security: auto-lock the screen after N minutes idle (0 = off)
    "idle_lock_minutes": "0",
    # automatic backups: write an encrypted copy on exit + once a day on launch.
    "auto_backup": "1",  # "1" => automatic backups on
    "backup_dir": "",  # chosen folder (USB/network); blank => Documents fallback
    "backup_keep": "14",  # rotation: keep this many newest auto-backups per folder
    "last_auto_backup_date": "",  # internal: throttles the once-a-day launch backup
    # WhatsApp (self-hosted wuzapi gateway, see whatsapp.py)
    "whatsapp_url": "",  # e.g. http://localhost:8080
    "whatsapp_session": "default",
    "whatsapp_country_code": "92",
    "whatsapp_auto": "0",  # "1" => auto-send report when results saved
    "whatsapp_auto_receipt": "0",  # "1" => auto-send the bill when a receipt is saved
    # NOTE: whatsapp_api_key is deliberately NOT a default setting — the token
    # lives only in the 0600 .secrets.json file, never in the DB/backups.
    # caption templates ({lab}, {lab_no}, {name} placeholders; blank = built-in)
    "whatsapp_report_caption": "",
    "whatsapp_receipt_caption": "",
    "whatsapp_timeout": "40",  # seconds for the upload before giving up
}

# Columns added after v1 — created on existing databases if missing.
_EXTRA_COLUMNS = {
    "patients": [
        ("title", "TEXT"),
        ("mr_no", "TEXT"),
        ("wa_optout", "INTEGER NOT NULL DEFAULT 0"),
        # when the WhatsApp consent choice was last set (audit trail)
        ("wa_consent_at", "TEXT"),
    ],
    "receipts": [
        ("title", "TEXT"),
        ("mr_no", "TEXT"),
        ("case_no", "TEXT"),
        ("reported_at", "TEXT"),
        ("payment_method", "TEXT"),
        ("voided", "INTEGER NOT NULL DEFAULT 0"),
        ("void_reason", "TEXT"),
        ("voided_at", "TEXT"),
        ("voided_by", "TEXT"),
        ("delivered_at", "TEXT"),
        ("delivered_by", "TEXT"),
        # money as integer paisa, stored ALONGSIDE the REAL columns (Wave 4b)
        ("subtotal_paisa", "INTEGER"),
        ("less_paisa", "INTEGER"),
        ("net_amount_paisa", "INTEGER"),
        ("paid_paisa", "INTEGER"),
        ("due_paisa", "INTEGER"),
    ],
    # render-layout override for catalog tests (NULL ⇒ classify at render time)
    "tests": [("render_category", "TEXT")],
    # per-test free-text remarks + impression/conclusion printed under the table,
    # plus the paisa charge twin
    "receipt_items": [
        ("remarks", "TEXT"),
        ("conclusion", "TEXT"),
        ("charge_paisa", "INTEGER"),
    ],
    # money movements + expenses, paisa twins of the REAL columns
    "ledger": [("credit_paisa", "INTEGER"), ("debit_paisa", "INTEGER")],
    "expenses": [("amount_paisa", "INTEGER")],
    # hide a parameter row from the printed report (kept in the entry screen)
    "results": [("hidden", "INTEGER NOT NULL DEFAULT 0")],
    # security: force first-login password change + brute-force lockout
    "users": [
        ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
        ("failed_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("locked_until", "TEXT"),
    ],
    # audit tamper-evidence: rolling hash chain
    "audit_log": [("hash", "TEXT")],
}

# REAL money column -> its INTEGER paisa twin, per table. Used by
# connection._backfill_paisa to populate paisa from REAL where missing, with the
# SAME rounding (SQL ROUND, half-away-from-zero) that the dual-writes use inline.
_PAISA_COLUMNS = {
    "receipts": [
        ("subtotal", "subtotal_paisa"),
        ("less", "less_paisa"),
        ("net_amount", "net_amount_paisa"),
        ("paid", "paid_paisa"),
        ("due", "due_paisa"),
    ],
    "receipt_items": [("charge", "charge_paisa")],
    "ledger": [("credit", "credit_paisa"), ("debit", "debit_paisa")],
    "expenses": [("amount", "amount_paisa")],
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

# SQL fragment: receipts that are not voided (voided column is added post-v1, so
# COALESCE guards the NULL). Use inside WHERE clauses to exclude voided bills.
NOT_VOIDED = "COALESCE(voided,0)=0"

# SQL fragment: rows whose received_at falls in today (local time). Written as a
# half-open range so a plain index on received_at can be used (no date() wrap).
RECEIVED_TODAY = (
    "received_at >= date('now','localtime') "
    "AND received_at < date('now','localtime','+1 day')"
)
