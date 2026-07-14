"""Shared pick-list constants + small shared helpers."""

import re


def format_person_name(name: str) -> str:
    """Tidy a typed patient name to proper case (per word, incl. hyphen/apostrophe parts)."""

    def _cap(word: str) -> str:
        return re.sub(r"[^\W\d_]+", lambda m: m.group(0).capitalize(), word)

    return " ".join(_cap(w) for w in (name or "").split())


def format_address(addr: str) -> str:
    """Capitalise just the first letter of an address, leaving the rest as typed."""
    a = (addr or "").strip()
    return a[:1].upper() + a[1:] if a else a


def normalize_phone(raw: str, cc: str = "92") -> str:
    """Collapse any phone input to the canonical local 11-digit form 03XXXXXXXXX."""
    d = "".join(c for c in (raw or "") if c.isdigit())
    if not d:
        return ""
    if d.startswith("00"):
        d = d[2:]
    if d.startswith(cc) and len(d) >= len(cc) + 9:
        d = d[len(cc) :]
    d = d.lstrip("0")
    return ("0" + d) if d else ""


TITLES = ["", "Mr.", "Mrs.", "Ms.", "Miss", "Master", "Baby", "Baby of", "Dr.", "Prof."]

AGE_UNITS = ["Years", "Months", "Days"]

SEXES = ["Male", "Female", "Other"]

# "Sample Required" / specimen presets (volume + tube + cap colour).
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

# Payment methods offered at billing and when editing a bill.
PAYMENT_METHODS = ["Cash", "Card", "Easypaisa", "JazzCash", "Bank", "Other"]
