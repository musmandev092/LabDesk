"""Constants for the LabDesk database layer. No logic lives here."""

from __future__ import annotations

from labdesk import __version__

from .._resources import schema_file, seed_db

APP_NAME = "LabDesk"
APP_VERSION = __version__  # single source of truth: package __version__

SCHEMA_FILE = schema_file()
SEED_DB = seed_db()

# bump whenever the shipped catalog changes, so existing installs pull the update
CATALOG_VERSION = "7"

DEFAULT_SETTINGS = {
    "configured": "0",  # "1" once the first-run wizard completes
    "catalog_version": CATALOG_VERSION,
    "lab_name": "",
    "lab_subtitle": "",
    "address": "",
    "phone": "",
    "mobile": "",
    "email": "",
    "currency": "Rs.",
    "default_printer": "",  # blank = show the print dialog each time
    "promo_discount_pct": "0",  # special-day discount %, auto-applied to new bills
    "promo_until": "",  # optional ISO date after which the promo stops
    "report_footer": "All results should be interpreted and correlated by the physician.",
    "logo_path": "",
    "lab_no_prefix": "LAB",
    "phc_reg_no": "",  # Punjab Healthcare Commission registration no.
    "lab_reg_no": "",
    "phc_logo_path": "",
    "accred_logo_1": "",
    "accred_logo_2": "",
    "accred_logo_3": "",
    "signatory_1_name": "",
    "signatory_1_title": "Consultant Pathologist",
    "signatory_2_name": "",
    "signatory_2_title": "Consultant Pathologist",
    "dept_band": "HEMATOLOGY  |  CHEMICAL PATHOLOGY  |  HORMONES  |  MOLECULAR BIOLOGY  |  HISTOPATHOLOGY",
    "receipt_footer_note": "Computer-generated document. No signature required.",
    "receipt_remarks": (
        "Please present this receipt to collect your report. Reports are "
        "issued strictly following final verification and signature by the "
        "consultant pathologist."
    ),
    # print up to 3 prior dated result columns for a patient's repeat tests
    "show_history": "1",
    "theme": "light",  # "light" | "dark"
    "idle_lock_minutes": "0",  # auto-lock after N minutes idle (0 = off)
    "auto_backup": "1",
    "backup_dir": "",  # chosen folder (USB/network); blank => Documents fallback
    "backup_keep": "14",
    "last_auto_backup_date": "",  # throttles the once-a-day launch backup
    "whatsapp_url": "",  # self-hosted wuzapi gateway, e.g. http://localhost:8080
    "whatsapp_session": "default",
    "whatsapp_country_code": "92",
    "whatsapp_auto": "0",
    "whatsapp_auto_receipt": "0",
    # whatsapp_api_key deliberately not a default setting — lives only in .secrets.json
    "whatsapp_report_caption": "",
    "whatsapp_receipt_caption": "",
    "whatsapp_timeout": "40",
}

# columns added after v1 — created on existing databases if missing
_EXTRA_COLUMNS = {
    "patients": [
        ("title", "TEXT"),
        ("mr_no", "TEXT"),
        ("wa_optout", "INTEGER NOT NULL DEFAULT 0"),
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
        # integer paisa, stored alongside the REAL columns
        ("subtotal_paisa", "INTEGER"),
        ("less_paisa", "INTEGER"),
        ("net_amount_paisa", "INTEGER"),
        ("paid_paisa", "INTEGER"),
        ("due_paisa", "INTEGER"),
    ],
    "tests": [("render_category", "TEXT")],  # NULL => classify at render time
    "receipt_items": [
        ("remarks", "TEXT"),
        ("conclusion", "TEXT"),
        ("charge_paisa", "INTEGER"),
    ],
    "ledger": [("credit_paisa", "INTEGER"), ("debit_paisa", "INTEGER")],
    "expenses": [("amount_paisa", "INTEGER")],
    "results": [("hidden", "INTEGER NOT NULL DEFAULT 0")],
    "users": [
        ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
        ("failed_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("locked_until", "TEXT"),
    ],
    "audit_log": [("hash", "TEXT")],
}

# REAL money column -> its INTEGER paisa twin; used by connection._backfill_paisa
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

# brute-force lockout: lock after _MAX_FAILS tries, window doubles per failure
# (60s -> 120s -> 240s ...) up to _LOCK_MAX_SECONDS (kept modest: 15 min, since
# login already sits behind the database-unlock password)
_MAX_FAILS = 5
_LOCK_SECONDS = 60
_LOCK_MAX_SECONDS = 900  # 15 minutes
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 16384, 8, 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024

# COALESCE guards NULL since `voided` was added post-v1
NOT_VOIDED = "COALESCE(voided,0)=0"

# half-open range so a plain index on received_at can be used (no date() wrap)
RECEIVED_TODAY = (
    "received_at >= date('now','localtime') "
    "AND received_at < date('now','localtime','+1 day')"
)
