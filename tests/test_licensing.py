"""Licensing: signature verification, node-lock thresholds, expiry, clock-rollback
defence, and the packaged-build enforcement gate (audit High H-2/H-3 + testing gap)."""

from __future__ import annotations

import base64
import datetime
import json

import pytest

from labdesk import licensing
from labdesk.licensing import _ed25519


@pytest.fixture
def keypair(monkeypatch):
    """A throwaway vendor key pair; embeds the public half so verify_signature works."""
    secret = bytes(range(32))  # deterministic seed (no RNG needed)
    public = _ed25519.secret_to_public(secret)
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", base64.b64encode(public).decode())
    return secret


def _sign(secret, payload):
    body = licensing.canonical_payload(payload)
    payload = dict(payload)
    payload["sig"] = base64.b64encode(_ed25519.sign(secret, body)).decode()
    return payload


def _signals(monkeypatch, signals):
    monkeypatch.setattr(licensing, "collect_signals", lambda: signals)


def test_valid_signature_accepted(keypair, monkeypatch):
    _signals(monkeypatch, {"machine_id": "a", "mac": "b"})
    lic = _sign(
        keypair, {"v": 1, "signals": {"machine_id": "a", "mac": "b"}, "expiry": ""}
    )
    assert licensing.verify_signature(lic) is True


def test_tampered_payload_rejected(keypair, monkeypatch):
    _signals(monkeypatch, {"machine_id": "a", "mac": "b"})
    lic = _sign(
        keypair, {"v": 1, "signals": {"machine_id": "a", "mac": "b"}, "expiry": ""}
    )
    lic["lab"] = "Evil Corp"  # change a signed field after signing
    assert licensing.verify_signature(lic) is False


def test_wrong_machine_rejected(keypair, monkeypatch, data_dir):
    _signals(monkeypatch, {"machine_id": "X", "mac": "Y"})  # this machine
    lic = _sign(
        keypair, {"v": 1, "signals": {"machine_id": "a", "mac": "b"}, "expiry": ""}
    )
    state, _ = licensing.evaluate(lic)
    assert state == "wrong_machine"


def test_single_signal_license_refused(keypair, monkeypatch):
    """H-3: a license bound to only one signal must never satisfy the node-lock."""
    _signals(monkeypatch, {"machine_id": "a", "mac": "b"})
    assert licensing._signals_match({"machine_id": "a"}) is False


def test_two_signals_need_both(keypair, monkeypatch):
    """H-3: with 2 bound signals, ONE matching is not enough (was the clone hole)."""
    _signals(monkeypatch, {"machine_id": "a", "mac": "different"})
    assert licensing._signals_match({"machine_id": "a", "mac": "b"}) is False
    _signals(monkeypatch, {"machine_id": "a", "mac": "b"})
    assert licensing._signals_match({"machine_id": "a", "mac": "b"}) is True


def test_three_signals_tolerate_one_change(keypair, monkeypatch):
    _signals(monkeypatch, {"machine_id": "a", "mac": "b", "disk": "CHANGED"})
    assert (
        licensing._signals_match({"machine_id": "a", "mac": "b", "disk": "c"}) is True
    )
    _signals(monkeypatch, {"machine_id": "a", "mac": "X", "disk": "Y"})
    assert (
        licensing._signals_match({"machine_id": "a", "mac": "b", "disk": "c"}) is False
    )


def test_expired_license_detected(keypair, monkeypatch, data_dir):
    _signals(monkeypatch, {"machine_id": "a", "mac": "b"})
    lic = _sign(
        keypair,
        {"v": 1, "signals": {"machine_id": "a", "mac": "b"}, "expiry": "2000-01-01"},
    )
    state, _ = licensing.evaluate(lic)
    assert state == "expired"


def test_clock_rollback_cannot_revive_expired(keypair, monkeypatch, data_dir):
    """Recording a high-water date in the future means rolling the system clock back
    can't make an expired license look valid again."""
    _signals(monkeypatch, {"machine_id": "a", "mac": "b"})
    # pretend we've previously run on 2030-06-01 (high-water mark)
    monkeypatch.setattr(licensing, "_today", lambda: datetime.date(2030, 6, 1))
    licensing._record_seen()
    # now the clock is rolled back to 2026; a license that expired 2027 is still expired
    monkeypatch.setattr(licensing, "_today", lambda: datetime.date(2026, 1, 1))
    assert licensing._effective_today() == datetime.date(2030, 6, 1)
    lic = _sign(
        keypair,
        {"v": 1, "signals": {"machine_id": "a", "mac": "b"}, "expiry": "2027-01-01"},
    )
    assert licensing.evaluate(lic)[0] == "expired"


def test_seen_file_tampering_is_ignored(keypair, monkeypatch, data_dir):
    """Hand-editing the high-water file to an earlier date is rejected (unstamped)."""
    monkeypatch.setattr(licensing, "_today", lambda: datetime.date(2030, 6, 1))
    licensing._record_seen()
    licensing._seen_path().write_text("1990-01-01", encoding="utf-8")  # no valid stamp
    assert licensing._high_water_date() is None


def test_parse_license_accepts_json_and_base64():
    payload = {"v": 1, "lab": "X"}
    assert licensing.parse_license_text(json.dumps(payload)) == payload
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    assert licensing.parse_license_text(b64) == payload
    assert licensing.parse_license_text("not a license") is None


def test_enforced_default_on_for_packaged_build(monkeypatch):
    """H-2: a packaged build with a key embedded enforces regardless of env."""
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", "Zm9vYmFy")  # any non-empty key
    monkeypatch.setattr(licensing, "is_packaged_build", lambda: True)
    monkeypatch.delenv("LABDESK_ENFORCE_LICENSE", raising=False)
    monkeypatch.setenv("LABDESK_SELFTEST", "1")  # must NOT relax a packaged build
    assert licensing.enforced() is True


def test_enforced_off_from_source_without_optin(monkeypatch):
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", "Zm9vYmFy")
    monkeypatch.setattr(licensing, "is_packaged_build", lambda: False)
    monkeypatch.delenv("LABDESK_ENFORCE_LICENSE", raising=False)
    assert licensing.enforced() is False
