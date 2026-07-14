"""Patient ID — format YY-NNN-NN<L>, e.g. 26-000-43K, <L> a check letter over the
digits (catches mistyped digits like a credit-card check digit). Existing "MR…"
ids are left untouched; this only shapes new patient ids."""

from __future__ import annotations

import re as _re
import time

# 23 letters with the easily-misread I, O and U removed.
_PID_ALPHABET = "ABCDEFGHJKLMNPQRSTVWXYZ"
_PID_RE = _re.compile(r"(\d{2})-(\d{2,})-(\d{2})([A-Z])$")


def _pid_check_letter(digits: str) -> str:
    """Weighted mod-23 checksum over the digit string -> one letter."""
    total = 0
    for i, ch in enumerate(digits):
        total = (total + int(ch) * (i + 2)) % len(_PID_ALPHABET)
    return _PID_ALPHABET[total]


def format_patient_id(seq: int, year: int | None = None) -> str:
    """Build the patient id for sequence `seq`; `year` defaults to the current year."""
    yy = f"{(year if year is not None else int(time.strftime('%Y'))) % 100:02d}"
    s = f"{int(seq):05d}"
    head, tail = s[:-2], s[-2:]
    letter = _pid_check_letter(yy + s)
    return f"{yy}-{head}-{tail}{letter}"


def validate_patient_id(code: str) -> bool:
    """True only if `code` is YY-…-NN<L> shaped with a correct check letter."""
    m = _PID_RE.match((code or "").strip().upper())
    if not m:
        return False
    yy, head, tail, letter = m.groups()
    return _pid_check_letter(yy + head + tail) == letter
