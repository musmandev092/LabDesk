"""Patient ID — the lab's unique patient identifier (formerly "MR No").

  Format: YY-NNN-NN<L>, e.g. 26-000-43K
    YY  two-digit registration year
    NNN-NN  the patient's sequence, zero-padded and chunked for readability
    <L> an alpha CHECK letter derived from the digits, so a single mistyped
        digit (or most adjacent transpositions) is caught before saving —
        the same idea as a credit-card check digit, but a letter.
Existing "MR…" ids are left untouched; this only shapes NEW patient ids.
"""

from __future__ import annotations

import re as _re
import time

# 23 letters with the easily-misread I, O and U removed.
_PID_ALPHABET = "ABCDEFGHJKLMNPQRSTVWXYZ"
_PID_RE = _re.compile(r"(\d{2})-(\d{2,})-(\d{2})([A-Z])$")


def _pid_check_letter(digits: str) -> str:
    """Weighted mod-23 checksum over the digit string → one letter. Each position
    carries a distinct weight so any single-digit change flips the letter."""
    total = 0
    for i, ch in enumerate(digits):
        total = (total + int(ch) * (i + 2)) % len(_PID_ALPHABET)
    return _PID_ALPHABET[total]


def format_patient_id(seq: int, year: int | None = None) -> str:
    """Build the patient id for sequence `seq` (e.g. the patient row id).
    `year` defaults to the current local year."""
    yy = f"{(year if year is not None else int(time.strftime('%Y'))) % 100:02d}"
    s = f"{int(seq):05d}"
    head, tail = s[:-2], s[-2:]  # all but last 2, then last 2
    letter = _pid_check_letter(yy + s)
    return f"{yy}-{head}-{tail}{letter}"


def validate_patient_id(code: str) -> bool:
    """True only if `code` is in the YY-…-NN<L> shape AND its check letter is
    correct. Legacy 'MR…' / free-form ids return False (not our format)."""
    m = _PID_RE.match((code or "").strip().upper())
    if not m:
        return False
    yy, head, tail, letter = m.groups()
    return _pid_check_letter(yy + head + tail) == letter
