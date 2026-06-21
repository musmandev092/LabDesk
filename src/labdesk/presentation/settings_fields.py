"""Settings-page field definitions — the per-section (key, label[, hint]) tuples and
the numeric-validation rules. Pure data, separated from the page widget in settings.py."""

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

# Per-field character caps. A QLineEdit with setMaxLength stops the user typing
# more than this many characters, so an over-long value (e.g. a very long lab name)
# can't stretch across the whole width of the printed report/receipt header. Sized
# to what fits the report layout; keys not listed have no cap.
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
    # report footer / signatories — the department band lists every section the lab
    # reports (e.g. "HEMATOLOGY | CHEMICAL PATHOLOGY | HORMONES | MOLECULAR BIOLOGY |
    # HISTOPATHOLOGY", ~77 chars), so give the footer fields room for the full text.
    "report_footer": 140,
    "dept_band": 140,
    "signatory_1_name": 35,
    "signatory_1_title": 35,
    "signatory_2_name": 35,
    "signatory_2_title": 35,
    # receipt footer
    "receipt_remarks": 80,
    "receipt_footer_note": 140,
    # whatsapp + misc (generous — URLs/tokens/captions can be long, but still bounded)
    "promo_until": 10,
    "whatsapp_url": 200,
    "whatsapp_api_key": 200,
    "whatsapp_country_code": 5,
    "whatsapp_report_caption": 200,
    "whatsapp_receipt_caption": 200,
    # NOTE: logo_path / accred_logo_1 are file paths chosen via a picker (read-only,
    # built by _logo_card not _add_field) — deliberately uncapped so a valid long
    # path is never truncated.
}

# Numeric settings: (kind, min, max, error message). Drives both the live input
# validator and the on-save range check, so a bad value can't be persisted.
NUMERIC_FIELDS: dict[str, tuple] = {
    "promo_discount_pct": (
        "float",
        0.0,
        100.0,
        "Special-day discount % must be a number between 0 and 100.",
    ),
    "whatsapp_timeout": (
        "int",
        1,
        600,
        "WhatsApp upload timeout must be a whole number of seconds (1–600).",
    ),
    "idle_lock_minutes": (
        "int",
        0,
        1440,
        "Auto-lock minutes must be a whole number from 0 (off) to 1440.",
    ),
}
