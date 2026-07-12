#!/usr/bin/env python3
"""Generate the vendor's Ed25519 license key pair — RUN ONCE.

Creates two files under ~/Documents/LabDesk-signing-key/ (OUTSIDE the repo, so the
secret never sits next to the code and can't be committed):
  * private.key  — SECRET. Stays on YOUR machine. Used by issue_license.py to sign
                   licenses. BACK IT UP somewhere safe. If you lose it you cannot
                   issue new licenses (existing ones keep working). If it leaks,
                   anyone can mint licenses — generate a new pair and rebuild.
  * public.key   — not secret. Embedded in the app so it can verify licenses.

It then patches src/labdesk/licensing/__init__.py to embed the public key
(PUBLIC_KEY_B64), which ARMS licensing for the next build.

Usage:
    uv run python scripts/licensing/generate_keys.py
    uv run python scripts/licensing/generate_keys.py --force   # overwrite existing
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from labdesk.licensing import _ed25519  # noqa: E402


def signing_key_dir() -> Path:
    """Where the vendor's signing key lives — by default ~/Documents/LabDesk-signing-key/,
    OUTSIDE the repo so the secret never sits next to the code. Override with
    LABDESK_SIGNING_KEY_DIR. NOTE: Documents is often cloud-synced/backed-up; a leaked
    private key lets anyone mint licenses, so keep any backup OFFLINE (the run prints a
    warning) — or point LABDESK_SIGNING_KEY_DIR at a non-synced folder."""
    env = os.environ.get("LABDESK_SIGNING_KEY_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Documents" / "LabDesk-signing-key"


# Keys live OUTSIDE the repo so the secret never sits next to the code.
KEYS_DIR = signing_key_dir()
INIT_PY = REPO / "src" / "labdesk" / "licensing" / "__init__.py"


def _warn_if_synced(path: Path) -> None:
    parts = {p.lower() for p in path.parts}
    if parts & {
        "documents",
        "desktop",
        "dropbox",
        "onedrive",
        "google drive",
        "nextcloud",
    }:
        print(
            f"!! WARNING: {path} looks like it may be cloud-synced/backed-up. The PRIVATE "
            "signing key must NOT leave this machine. Move it to a non-synced location "
            "(set LABDESK_SIGNING_KEY_DIR) and keep your backup OFFLINE."
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate the vendor Ed25519 key pair (run once)."
    )
    ap.add_argument(
        "--force", action="store_true", help="overwrite an existing private.key"
    )
    args = ap.parse_args()

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    with __import__("contextlib").suppress(OSError):
        os.chmod(KEYS_DIR, 0o700)
    _warn_if_synced(KEYS_DIR)
    priv_path = KEYS_DIR / "private.key"
    pub_path = KEYS_DIR / "public.key"

    if priv_path.exists() and not args.force:
        print(
            f"!! {priv_path} already exists — refusing to overwrite your signing key."
        )
        print(
            "   (Re-run with --force ONLY if you really want a brand-new key pair; doing so"
        )
        print("    invalidates every license you've already issued.)")
        return 1

    secret = secrets.token_bytes(32)
    public = _ed25519.secret_to_public(secret)
    priv_b64 = base64.b64encode(secret).decode()
    pub_b64 = base64.b64encode(public).decode()

    fd = os.open(str(priv_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(priv_b64 + "\n")
    pub_path.write_text(pub_b64 + "\n", encoding="utf-8")

    # Embed the public key into the app (arms licensing for the next build).
    patched = False
    if INIT_PY.exists():
        lines = INIT_PY.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.startswith("PUBLIC_KEY_B64 ="):
                lines[i] = f'PUBLIC_KEY_B64 = "{pub_b64}"\n'
                patched = True
                break
        if patched:
            INIT_PY.write_text("".join(lines), encoding="utf-8")

    print("✓ Key pair generated.")
    print(f"  private key (SECRET, back this up): {priv_path}")
    print(f"  public  key:                        {pub_path}")
    print(f"  public key (base64): {pub_b64}")
    if patched:
        print(
            f"✓ Embedded the public key into {INIT_PY.relative_to(REPO)} (PUBLIC_KEY_B64)."
        )
        print("  Now rebuild: bash scripts/build_release.sh")
    else:
        print("!! Could not auto-embed the public key — set PUBLIC_KEY_B64 in")
        print(f"   {INIT_PY} manually to the base64 value above.")
    print("\nNEVER commit private.key. NEVER ship it. Keep a safe backup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
