"""Input tidiers: patient-name proper-casing and address first-letter capital."""

from __future__ import annotations

from labdesk.constants import format_address, format_person_name


def test_person_name_uppercase_to_title():
    assert format_person_name("MUHAMMAD USMAN") == "Muhammad Usman"


def test_person_name_lowercase_to_title():
    assert format_person_name("muhammad usman") == "Muhammad Usman"


def test_person_name_mixed_and_extra_spaces():
    assert format_person_name("  muHAMmad   usMAN ") == "Muhammad Usman"


def test_person_name_hyphen_and_apostrophe():
    assert format_person_name("abdul-rehman") == "Abdul-Rehman"
    assert format_person_name("o'brien") == "O'Brien"


def test_person_name_blank():
    assert format_person_name("") == ""
    assert format_person_name("   ") == ""


def test_address_first_letter_capitalised():
    assert format_address("house 12, street 5, lahore") == "House 12, street 5, lahore"


def test_address_preserves_rest_and_blank():
    # only the first letter changes; the rest is left exactly as typed
    assert format_address("12-A block") == "12-A block"
    assert format_address("") == ""
