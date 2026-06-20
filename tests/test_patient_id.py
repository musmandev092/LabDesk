"""Characterization tests for db/patient_id.py — the check-letter scheme.

Pins the round-trip property (format → validate) and the single-digit catch, so the
identifier scheme can't silently change. Pure functions; no DB.
"""

from __future__ import annotations

import pytest

from labdesk.db.patient_id import (
    _PID_ALPHABET,
    _PID_RE,
    format_patient_id,
    validate_patient_id,
)


def test_format_shape_and_known_value():
    pid = format_patient_id(43, year=2026)
    assert _PID_RE.match(pid)  # YY-NNN-NN<L>
    assert pid.startswith("26-000-43")
    assert pid[-1] in _PID_ALPHABET


@pytest.mark.parametrize("seq", [0, 1, 9, 43, 100, 999, 1234, 99999])
def test_round_trip_format_then_validate(seq):
    assert validate_patient_id(format_patient_id(seq, year=2026)) is True


@pytest.mark.parametrize("year", [2000, 2024, 2026, 2099])
def test_round_trip_across_years(year):
    pid = format_patient_id(77, year=year)
    assert validate_patient_id(pid) is True


def test_default_year_produces_valid_id():
    # year=None → current local year; shape + self-consistency still hold.
    pid = format_patient_id(5)
    assert _PID_RE.match(pid)
    assert validate_patient_id(pid) is True


def test_single_digit_change_is_rejected():
    pid = format_patient_id(43, year=2026)  # e.g. 26-000-43X
    # Flip a digit in the sequence; the check letter must no longer match.
    bad = pid.replace("43", "44")
    assert validate_patient_id(bad) is False


def test_wrong_check_letter_rejected():
    pid = format_patient_id(43, year=2026)
    wrong_letter = "A" if pid[-1] != "A" else "B"
    assert validate_patient_id(pid[:-1] + wrong_letter) is False


def test_case_insensitive_and_stripped():
    pid = format_patient_id(43, year=2026)
    assert validate_patient_id(f"  {pid.lower()}  ") is True


@pytest.mark.parametrize("bad", ["", "MR12345", "garbage", "26-000-43", "26-43X", None])
def test_legacy_and_malformed_ids_rejected(bad):
    assert validate_patient_id(bad) is False
