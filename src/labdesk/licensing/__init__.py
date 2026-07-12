"""Offline, node-locked licensing for LabDesk.

A copy of LabDesk only runs on a machine it has been ACTIVATED for. Activation is
offline and signature-based — no internet, no license server:

  1. The app builds an activation REQUEST (the machine's hashed signals).
  2. The vendor signs a LICENSE for that request with their Ed25519 PRIVATE key
     (scripts/licensing/issue_license.py) and sends back a `license.lic`.
  3. The app verifies the license with the embedded PUBLIC key, checks it is for
     THIS machine (tolerating one hardware change) and not expired, then unlocks.

Copying the app to another PC fails: the signals don't match. Editing the license
fails: the signature breaks (the attacker doesn't have the private key).

Enforcement is deliberately gated (see `enforced()`): it only bites for the
installed launcher (which sets LABDESK_ENFORCE_LICENSE) with a real public key
configured — never in dev runs or the self-test — so development and CI are never
blocked.
"""

from __future__ import annotations

import base64
import contextlib
import datetime
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import cast

from . import _ed25519
from .fingerprint import collect_signals, fingerprint_code

# ---------------------------------------------------------------------------
# The vendor's Ed25519 PUBLIC key (base64 of 32 bytes). EMPTY = licensing not
# configured (the app runs unlocked). Run scripts/licensing/generate_keys.py to
# create your key pair; it fills this in. The matching PRIVATE key stays on the
# vendor's machine and is NEVER shipped.
# ---------------------------------------------------------------------------
PUBLIC_KEY_B64 = "PY6JRxT2SXwadi0fgLZnrcqHK9VtB1quDNZTJZKhG5I="

_LICENSE_NAME = "license.lic"
_SEEN_NAME = ".license-seen"  # clock-rollback high-water mark (anti-cheat for expiry)


# ---- configuration / gating ------------------------------------------------
def configured() -> bool:
    """True once a real public key is embedded (licensing machinery is armed)."""
    return bool(PUBLIC_KEY_B64.strip())


def is_packaged_build() -> bool:
    """True when running as a compiled/frozen release binary rather than from source.
    Nuitka injects ``__compiled__`` into every compiled module; PyInstaller sets
    ``sys.frozen``. Used to make license enforcement (and the self-test bypass)
    default-correct without depending on an attacker-settable environment variable."""
    return bool(globals().get("__compiled__")) or bool(getattr(sys, "frozen", False))


def enforced() -> bool:
    """Whether the launch must be licensed.

    In a PACKAGED release build, enforcement is the DEFAULT whenever a public key is
    embedded — it cannot be switched off via the environment, so a user can no longer
    bypass the node-lock by launching the binary directly or unsetting a variable.

    Running from SOURCE (dev/CI) is never blocked: enforcement there is opt-IN via
    LABDESK_ENFORCE_LICENSE (for testing the licensed flow), and the headless
    self-test is exempt. The self-test exemption is honoured ONLY from source — in a
    packaged build LABDESK_SELFTEST can never relax enforcement (see app._selftest)."""
    if not configured():
        return False
    if is_packaged_build():
        return True  # shipped release: always enforced, env cannot disable it
    # --- from source (dev/CI) ---
    if os.environ.get("LABDESK_SELFTEST") == "1":
        return False
    return bool(os.environ.get("LABDESK_ENFORCE_LICENSE"))


def _public_key() -> bytes:
    return base64.b64decode(PUBLIC_KEY_B64.strip())


# ---- file locations --------------------------------------------------------
def _license_path() -> Path:
    from ..db.paths import data_dir

    return data_dir() / _LICENSE_NAME


def _seen_path() -> Path:
    from ..db.paths import data_dir

    return data_dir() / _SEEN_NAME


# ---- activation request (app -> vendor) ------------------------------------
def build_request() -> str:
    """A compact, copy-pasteable token the lab sends to the vendor. Carries the
    machine's HASHED signals (no raw hardware ids) + hostname for the vendor's
    records."""
    import socket

    payload = {
        "v": 1,
        "host": socket.gethostname()[:64],
        "signals": collect_signals(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(raw).decode()


def current_code() -> str:
    """Short human code for this machine (for quick reference on the phone)."""
    return fingerprint_code()


# ---- license signing payload (shared with issue_license.py) ----------------
def canonical_payload(payload: dict[str, object]) -> bytes:
    """Exact byte string that gets signed — everything except the signature, in a
    stable canonical JSON form. issue_license.py signs this; the app verifies it."""
    body = {k: payload[k] for k in payload if k != "sig"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


# ---- verification ----------------------------------------------------------
def _today() -> datetime.date:
    return datetime.date.today()


def _seen_stamp(iso_date: str) -> str:
    """Keyed digest binding a date to this build's public key. A user editing the
    high-water file by hand to an earlier date can't recompute this, so the tampered
    value is rejected on read. (Not unbreakable — a determined attacker can extract
    the embedded key from the binary — but it defeats trivial text-editing.)"""
    key = PUBLIC_KEY_B64.strip().encode() or b"labdesk-seen"
    return hmac.new(key, iso_date.encode(), hashlib.sha256).hexdigest()[:16]


def _high_water_date() -> datetime.date | None:
    with contextlib.suppress(OSError, ValueError):
        raw = _seen_path().read_text(encoding="utf-8").strip()
        iso, _, stamp = raw.partition("|")
        iso = iso.strip()[:10]
        # Reject an unstamped or hand-edited value (treat as no high-water → falls back
        # to the real clock, which still can't move expiry past today).
        if not stamp or not hmac.compare_digest(stamp.strip(), _seen_stamp(iso)):
            return None
        return datetime.date.fromisoformat(iso)
    return None


def _record_seen() -> None:
    """Persist the latest date we've seen (monotonic high-water mark) so rolling the
    system clock backwards can't revive an expired license. The value is keyed-stamped
    so the file can't be hand-edited to an earlier date undetected."""
    today = _today()
    hw = _high_water_date()
    newest = max(today, hw) if hw else today
    iso = newest.isoformat()
    with contextlib.suppress(OSError):
        p = _seen_path()
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{iso}|{_seen_stamp(iso)}")


def _effective_today() -> datetime.date:
    """Today, but never earlier than the highest date ever seen (clock-rollback safe)."""
    hw = _high_water_date()
    today = _today()
    return max(today, hw) if hw else today


def verify_signature(payload: dict[str, object]) -> bool:
    """True iff `payload['sig']` is a valid vendor signature over the payload."""
    if not configured():
        return False
    sig = payload.get("sig")
    if not isinstance(sig, str):
        return False
    with contextlib.suppress(Exception):
        return _ed25519.verify(
            _public_key(), canonical_payload(payload), base64.b64decode(sig)
        )
    return False


def _signals_match(lic_signals: dict[str, object]) -> bool:
    """Node-lock check, hardened against single-value cloning.

    A license must be bound to at least TWO signals (issue_license.py refuses fewer),
    and activation requires ``max(2, n-1)`` of those ``n`` bound signals to match this
    machine. So at most one hardware change is tolerated and ONLY when ≥3 signals were
    bound; a 2-signal license needs both. Copying one world-readable value (e.g.
    /etc/machine-id) to another machine can therefore no longer pass the check."""
    if not isinstance(lic_signals, dict) or len(lic_signals) < 2:
        return False  # too few signals to be a trustworthy node-lock — refuse
    cur = collect_signals()
    matched = sum(1 for k, v in lic_signals.items() if k in cur and v == cur[k])
    needed = max(2, len(lic_signals) - 1)
    return matched >= needed


def evaluate(payload: dict[str, object]) -> tuple[str, str]:
    """Classify a parsed license payload for THIS machine. Returns (state, message)
    where state is one of: ok | bad_signature | wrong_machine | expired | invalid."""
    if not isinstance(payload, dict):
        return "invalid", "License file is not valid."
    if not verify_signature(payload):
        return (
            "bad_signature",
            "License signature is invalid (not issued by the vendor, or edited).",
        )
    if not _signals_match(cast("dict[str, object]", payload.get("signals", {}))):
        return "wrong_machine", "This license is for a different computer."
    expiry = str(payload.get("expiry") or "").strip()
    if expiry:
        with contextlib.suppress(ValueError):
            if _effective_today() > datetime.date.fromisoformat(expiry):
                return "expired", f"This license expired on {expiry}."
    return "ok", "Licensed."


def parse_license_text(text: str) -> dict[str, object] | None:
    """Accept a license as raw JSON, or base64-wrapped JSON. Returns the dict or None."""
    text = (text or "").strip()
    if not text:
        return None
    with contextlib.suppress(Exception):
        return cast("dict[str, object]", json.loads(text))
    with contextlib.suppress(Exception):
        return cast("dict[str, object]", json.loads(base64.b64decode(text).decode()))
    return None


def check() -> tuple[str, dict[str, object] | None]:
    """Evaluate the installed license (if any). Returns (state, payload). state is
    'unactivated' when no license file is present, else the evaluate() state."""
    p = _license_path()
    if not p.exists():
        return "unactivated", None
    with contextlib.suppress(OSError):
        payload = parse_license_text(p.read_text(encoding="utf-8"))
        if payload is None:
            return "invalid", None
        state, _ = evaluate(payload)
        if state == "ok":
            _record_seen()
        return state, payload
    return "invalid", None


def install_license(text: str) -> tuple[bool, str]:
    """Validate a pasted/loaded license for THIS machine and, if good, save it.
    Returns (ok, message)."""
    payload = parse_license_text(text)
    if payload is None:
        return False, "That doesn't look like a license file."
    state, msg = evaluate(payload)
    if state != "ok":
        return False, msg
    with contextlib.suppress(OSError):
        p = _license_path()
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        _record_seen()
        return True, "Activated."
    return False, "Could not save the license file."


def license_info() -> dict[str, object] | None:
    """The installed license payload (for display), or None."""
    _state, payload = check()
    return payload
