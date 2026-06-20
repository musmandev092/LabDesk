"""Characterization tests for report/verify.py — the HMAC report verification code.

Pins: a finalised report produces a stable code; that code re-verifies (case/dash/
space-insensitive, constant-time); forging or altering any verifiable content
(result value, hidden flag, culture, sensitivity) breaks verification; and an empty
report has no code. This is the report-tamper-evidence guarantee.
"""

from __future__ import annotations

import re

from factories import build_full_receipt, make_receipt
from labdesk import db as dbpkg
from labdesk.report.verify import (
    report_fingerprint,
    verification_code,
    verify,
)

_CODE_RE = re.compile(r"^[0-9A-F]{4}-[0-9A-F]{4}$")


def test_code_has_expected_shape(con):
    rid = build_full_receipt(con)
    code = verification_code(con, rid)
    assert _CODE_RE.match(code)


def test_code_round_trips(con):
    rid = build_full_receipt(con)
    code = verification_code(con, rid)
    assert verify(con, rid, code) is True


def test_verify_is_format_insensitive(con):
    rid = build_full_receipt(con)
    code = verification_code(con, rid)
    assert verify(con, rid, code.lower()) is True
    assert verify(con, rid, code.replace("-", "")) is True
    assert verify(con, rid, f"  {code}  ") is True


def test_verify_rejects_wrong_code(con):
    rid = build_full_receipt(con)
    assert verify(con, rid, "0000-0000") is False


def test_code_is_stable_across_reprints(con):
    rid = build_full_receipt(con)
    assert verification_code(con, rid) == verification_code(con, rid)
    assert report_fingerprint(con, rid) == report_fingerprint(con, rid)


def test_key_is_persisted_in_settings(con):
    rid = build_full_receipt(con)
    verification_code(con, rid)
    assert dbpkg.get_setting(con, "report_verify_key", "") != ""


def test_altering_a_result_value_breaks_verification(con):
    rid = build_full_receipt(con)
    old = verification_code(con, rid)
    con.execute(
        "UPDATE results SET value='99.9' WHERE receipt_item_id IN "
        "(SELECT id FROM receipt_items WHERE receipt_id=?)",
        (rid,),
    )
    con.commit()
    new = verification_code(con, rid)
    assert new != old
    assert verify(con, rid, old) is False


def test_toggling_hidden_flag_changes_code(con):
    rid = build_full_receipt(con)
    old = verification_code(con, rid)
    con.execute(
        "UPDATE results SET hidden=1 WHERE receipt_item_id IN "
        "(SELECT id FROM receipt_items WHERE receipt_id=?)",
        (rid,),
    )
    con.commit()
    assert verification_code(con, rid) != old


def test_altering_sensitivity_breaks_verification(con):
    rid = build_full_receipt(con)
    old = verification_code(con, rid)
    con.execute("UPDATE culture_sensitivity SET result='R'")
    con.commit()
    new = verification_code(con, rid)
    assert new != old
    assert verify(con, rid, old) is False


def test_empty_or_missing_receipt_has_no_code(con):
    # No such receipt → empty fingerprint → empty code → verify always False.
    assert verification_code(con, 999999) == ""
    assert verify(con, 999999, "ABCD-1234") is False


def test_receipt_with_no_results_still_codes_off_header(con):
    # A receipt that exists but has no result/culture rows still has a header
    # fingerprint, so it produces a (non-empty) code.
    rid = make_receipt(con, lab_no="LAB-EMPTY")
    code = verification_code(con, rid)
    assert _CODE_RE.match(code)
    assert verify(con, rid, code) is True
