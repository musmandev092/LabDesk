"""Settings-page field definitions: per-section (key, label[, hint]) tuples and numeric-validation rules."""

from __future__ import annotations

LAB_FIELDS: list[tuple[str, ...]] = [
    ("lab_name", "Lab name"),
    ("lab_subtitle", "Subtitle / tagline"),
    ("address", "Address"),
    ("phone", "Phone"),
    ("mobile", "Mobile"),
    ("email", "Email"),
    ("currency", "Currency symbol"),
    ("lab_no_prefix", "Lab no. prefix"),
]
REG_FIELDS: list[tuple[str, ...]] = [
    ("phc_reg_no", "PHC registration no."),
    ("lab_reg_no", "Lab registration no."),
]
PROMO_FIELDS: list[tuple[str, ...]] = [
    ("promo_discount_pct", "Special-day discount %", "0 = off"),
    ("promo_until", "Promo active until", "YYYY-MM-DD (blank = no end)"),
]
REPORT_FIELDS: list[tuple[str, ...]] = [
    ("report_footer", "Report footer line"),
    ("dept_band", "Department band"),
    ("signatory_1_name", "Signatory 1 — name"),
    ("signatory_1_title", "Signatory 1 — title"),
    ("signatory_2_name", "Signatory 2 — name"),
    ("signatory_2_title", "Signatory 2 — title"),
]
RECEIPT_FIELDS: list[tuple[str, ...]] = [
    ("receipt_remarks", "Remarks line", "Shown under the bill's Remarks heading"),
    (
        "receipt_footer_note",
        "Footer note",
        "Small italic line at the bottom of the bill",
    ),
]
LOGO_FIELDS = [
    ("logo_path", "Main logo"),
    ("accred_logo_1", "Secondary logo"),
]
WHATSAPP_FIELDS: list[tuple[str, ...]] = [
    ("whatsapp_url", "Gateway URL", "http://localhost:8080"),
    ("whatsapp_api_key", "Access token", "wuzapi user token"),
    ("whatsapp_country_code", "Country code", "92"),
    ("whatsapp_timeout", "Upload timeout (sec)", "40"),
    ("whatsapp_report_caption", "Report caption", "{lab} — Report {lab_no} for {name}"),
    (
        "whatsapp_receipt_caption",
        "Receipt caption",
        "{lab} — Receipt {lab_no} for {name}",
    ),
]

# Per-field character caps, sized to what fits the printed report/receipt layout;
# keys not listed have no cap.
MAX_LENGTHS: dict[str, int] = {
    # report / receipt header identity
    "lab_name": 35,
    "lab_subtitle": 45,
    "address": 60,
    "phone": 20,
    "mobile": 20,
    "email": 40,
    "currency": 5,
    "lab_no_prefix": 8,
    "phc_reg_no": 25,
    "lab_reg_no": 25,
    # report footer / signatories — dept_band can list many sections (~77 chars)
    "report_footer": 140,
    "dept_band": 140,
    "signatory_1_name": 35,
    "signatory_1_title": 35,
    "signatory_2_name": 35,
    "signatory_2_title": 35,
    # receipt footer
    "receipt_remarks": 80,
    "receipt_footer_note": 140,
    # whatsapp + misc
    "promo_until": 10,
    "whatsapp_url": 200,
    "whatsapp_api_key": 200,
    "whatsapp_country_code": 5,
    "whatsapp_report_caption": 200,
    "whatsapp_receipt_caption": 200,
    # logo_path / accred_logo_1 (file-picker paths, built by _logo_card) are uncapped
}

# Numeric settings: (kind, min, max, error message). Drives the live validator
# and the on-save range check.
NUMERIC_FIELDS: dict[str, tuple] = {
    "promo_discount_pct": (
        "float",
        0.0,
        100.0,
        "Special-day discount % must be a number between 0 and 100.",
    ),
    # matches the runtime clamp in whatsapp._cfg (5-120)
    "whatsapp_timeout": (
        "int",
        5,
        120,
        "WhatsApp upload timeout must be a whole number of seconds (5–120).",
    ),
    "whatsapp_country_code": (
        "int",
        1,
        9999,
        "Country code must be digits only, e.g. 92 (no '+', spaces or dashes).",
    ),
    "idle_lock_minutes": (
        "int",
        0,
        1440,
        "Auto-lock minutes must be a whole number from 0 (off) to 1440.",
    ),
}
