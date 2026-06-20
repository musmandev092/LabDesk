"""Wave 5 — licensing failure branches (no private key needed).

Covers the paths reachable without the vendor's Ed25519 private key: request
building, canonical payload, license-text parsing, and the evaluate() rejection
branches (invalid shape, bad signature). The 'ok'/expired/wrong_machine accept
paths need a real signature and are out of scope here.
"""

from __future__ import annotations

import base64
import json

from labdesk import licensing


def test_build_request_is_base64_json_with_signals():
    req = licensing.build_request()
    payload = json.loads(base64.b64decode(req))
    assert payload["v"] == 1
    assert "signals" in payload
    assert isinstance(payload["host"], str)


def test_canonical_payload_excludes_sig_and_is_order_stable():
    c1 = licensing.canonical_payload({"a": 1, "b": 2, "sig": "xxx"})
    c2 = licensing.canonical_payload({"b": 2, "a": 1, "sig": "yyy"})
    assert c1 == c2  # sorted keys, signature excluded
    assert b'"sig"' not in c1


def test_parse_license_text_variants():
    assert licensing.parse_license_text("") is None
    assert licensing.parse_license_text("not json at all") is None
    assert licensing.parse_license_text('{"v": 1}') == {"v": 1}
    wrapped = base64.b64encode(b'{"v": 2}').decode()
    assert licensing.parse_license_text(wrapped) == {"v": 2}


def test_verify_signature_false_without_or_bad_sig():
    assert licensing.verify_signature({"v": 1}) is False  # no sig
    assert licensing.verify_signature({"v": 1, "sig": 123}) is False  # non-str sig
    assert licensing.verify_signature({"v": 1, "sig": "!!notbase64!!"}) is False


def test_evaluate_rejects_non_dict_as_invalid():
    assert licensing.evaluate("not-a-dict")[0] == "invalid"  # type: ignore[arg-type]


def test_evaluate_rejects_bad_signature():
    # configured() is true (a public key is embedded), so a payload carrying a
    # syntactically-valid but wrong signature is rejected as bad_signature.
    payload = {"v": 1, "signals": {}, "sig": base64.b64encode(b"x" * 64).decode()}
    state, _msg = licensing.evaluate(payload)
    assert state == "bad_signature"
