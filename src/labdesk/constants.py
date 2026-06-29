"""Shared pick-list constants + small shared helpers."""

import re


def format_person_name(name: str) -> str:
    """Tidy a typed patient name to proper case regardless of how it was entered.

    ``MUHAMMAD USMAN``, ``muhammad usman`` and ``muHAMmad   usman`` all become
    ``Muhammad Usman``. Each whitespace-separated word is capitalised (first letter
    upper, rest lower); hyphen/apostrophe sub-parts are capitalised too
    (``abdul-rehman`` → ``Abdul-Rehman``, ``o'brien`` → ``O'Brien``). Runs of
    whitespace collapse to a single space. Returns "" for blank input."""

    def _cap(word: str) -> str:
        return re.sub(r"[^\W\d_]+", lambda m: m.group(0).capitalize(), word)

    return " ".join(_cap(w) for w in (name or "").split())


def format_address(addr: str) -> str:
    """Capitalise just the first letter of an address (leave the rest as typed);
    a small touch that makes the printed header read nicely. Blank stays blank."""
    a = (addr or "").strip()
    return a[:1].upper() + a[1:] if a else a


def normalize_phone(raw: str, cc: str = "92") -> str:
    """Canonical local phone format used everywhere in the system.

    Any input (+92…, 0092…, 92…, 03xx…, bare national) collapses to the local
    11-digit form ``03XXXXXXXXX`` (leading 0 + national number). Returns "" for
    empty/garbage input. WhatsApp ids are derived from this (see whatsapp.py)."""
    d = "".join(c for c in (raw or "") if c.isdigit())
    if not d:
        return ""
    if d.startswith("00"):  # 0092… → 92…
        d = d[2:]
    if d.startswith(cc) and len(d) >= len(cc) + 9:  # 92XXXXXXXXXX → national
        d = d[len(cc) :]
    d = d.lstrip("0")  # drop any leading zero(s)
    return ("0" + d) if d else ""


TITLES = ["", "Mr.", "Mrs.", "Ms.", "Miss", "Master", "Baby", "Baby of", "Dr.", "Prof."]

AGE_UNITS = ["Years", "Months", "Days"]

SEXES = ["Male", "Female", "Other"]

# Standard "Sample Required" / specimen presets (volume + tube + cap colour),
# matching the conventions used on typical pathology requisitions.
SPECIMEN_PRESETS = [
    "3cc EDTA Whole Blood (Lavender)",
    "3-5cc Clotted Blood / Serum (Red / Gold)",
    "3cc Sodium Citrate Plasma (Blue)",
    "2cc Sodium Fluoride Plasma (Grey)",
    "5cc Lithium Heparin Plasma (Green)",
    "Random Urine",
    "Early Morning Urine",
    "24 Hours Urine",
    "Mid-Stream Urine (C/S)",
    "Stool Sample",
    "Sputum Sample",
    "Semen Sample",
    "Throat Swab",
    "Wound / Pus Swab",
    "High Vaginal Swab",
    "Body Fluid",
    "CSF (Cerebro-Spinal Fluid)",
    "Whole Blood (Heparin)",
    "Nasopharyngeal Swab",
    "Blood for Culture",
]


# Payment methods offered at billing and when editing a bill (single source of truth).
PAYMENT_METHODS = ["Cash", "Card", "Easypaisa", "JazzCash", "Bank", "Other"]
