#!/usr/bin/env python3
"""Issue a signed LabDesk license for one machine — run on YOUR machine.

Takes the activation REQUEST the lab sent you, signs a license bound to that
machine with your PRIVATE key, and writes license.lic to send back.

Usage:
    # request can be the pasted token, or a file containing it
    uv run python scripts/licensing/issue_license.py \
        --request "<token-from-lab>" --lab "City Diagnostic Lab" --out license.lic

    # time-limited (subscription) license:
    uv run python scripts/licensing/issue_license.py --request req.txt \
        --lab "City Lab" --days 365 --out city-lab.lic
    # or an explicit date:
        --expiry 2027-06-30
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from labdesk.licensing import _ed25519, canonical_payload  # noqa: E402

import os


def _signing_key_dir() -> Path:
    """Resolve the signing-key home: LABDESK_SIGNING_KEY_DIR override, else the legacy
    ~/Documents location if a key exists there (backward compat), else the XDG data
    dir (the non-synced default generate_keys.py now uses)."""
    env = os.environ.get("LABDESK_SIGNING_KEY_DIR")
    if env:
        return Path(env).expanduser()
    legacy = Path.home() / "Documents" / "LabDesk-signing-key"
    if (legacy / "private.key").exists():
        return legacy
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "labdesk-signing-key"


KEY_DIR = _signing_key_dir()
DEFAULT_KEY = KEY_DIR / "private.key"
LICENSES_DIR = KEY_DIR / "licenses"


def _read_request(value: str) -> dict:
    """`value` is either the base64 token or a path to a file containing it."""
    token = value.strip()
    try:
        p = Path(value)
        if p.exists():  # may raise OSError when `value` is a long token, not a path
            token = p.read_text(encoding="utf-8").strip()
    except OSError:
        pass  # not a path — treat `value` as the token itself
    raw = base64.b64decode(token)
    data = json.loads(raw.decode())
    if (
        "signals" not in data
        or not isinstance(data["signals"], dict)
        or not data["signals"]
    ):
        raise ValueError("request has no machine signals")
    # Refuse to bind a license to a single signal: the node-lock verifier
    # (_signals_match) requires ≥2 bound signals, and a one-signal lock could be
    # defeated by copying one world-readable value (e.g. /etc/machine-id).
    if len(data["signals"]) < 2:
        raise ValueError(
            f"request carries only {len(data['signals'])} machine signal "
            f"({', '.join(data['signals'])}); at least 2 are required to issue a "
            "node-locked license. Ask the lab to re-run activation on the actual "
            "target PC (a minimal VM may expose too few signals)."
        )
    return data


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sign a LabDesk license for a machine request."
    )
    ap.add_argument(
        "--request", required=True, help="activation request token, or a file with it"
    )
    ap.add_argument(
        "--lab", required=True, help="lab/customer name (recorded in the license)"
    )
    ap.add_argument(
        "--expiry", default="", help="expiry date YYYY-MM-DD (blank = perpetual)"
    )
    ap.add_argument(
        "--days", type=int, default=0, help="alternative to --expiry: valid N days"
    )
    ap.add_argument("--key", default=str(DEFAULT_KEY), help="path to private.key")
    ap.add_argument(
        "--out",
        default="license.lic",
        help="output file; a bare name is saved under ~/Documents/LabDesk-signing-key/licenses/",
    )
    args = ap.parse_args()

    key_path = Path(args.key)
    if not key_path.exists():
        print(f"!! private key not found: {key_path}")
        print("   Run scripts/licensing/generate_keys.py first.")
        return 1
    secret = base64.b64decode(key_path.read_text(encoding="utf-8").strip())

    try:
        req = _read_request(args.request)
    except Exception as e:  # noqa: BLE001
        print(f"!! could not read the activation request: {e}")
        return 1

    expiry = args.expiry.strip()
    if args.days > 0:
        expiry = (
            datetime.date.today() + datetime.timedelta(days=args.days)
        ).isoformat()
    if expiry:
        try:
            datetime.date.fromisoformat(expiry)
        except ValueError:
            print(f"!! invalid --expiry date: {expiry} (use YYYY-MM-DD)")
            return 1

    payload = {
        "v": 1,
        "lab": args.lab.strip(),
        "signals": req["signals"],
        "issued": datetime.date.today().isoformat(),
        "expiry": expiry,
    }
    payload["sig"] = base64.b64encode(
        _ed25519.sign(secret, canonical_payload(payload))
    ).decode()

    # A bare filename (e.g. "CPHC-Lab.lic") is saved under ~/Documents/.../licenses/;
    # an explicit path is honoured as-is.
    out = Path(args.out)
    if out.parent == Path("."):
        LICENSES_DIR.mkdir(parents=True, exist_ok=True)
        out = LICENSES_DIR / out.name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"✓ License written: {out}")
    print(f"  lab:    {payload['lab']}")
    print(f"  host:   {req.get('host', '?')}")
    print(f"  expiry: {expiry or 'perpetual'}")
    print(f"  signals bound: {', '.join(sorted(req['signals']))}")
    print("Send this file to the lab; they load it in LabDesk's activation screen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
