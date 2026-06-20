#!/usr/bin/env bash
# Build the LabDesk distributable: compile the app to a NATIVE binary (Nuitka,
# non-bundling) so the lab PC never sees readable Python, and stage it with the
# installer. Qt/Python/SQLCipher are NOT bundled — install.sh fetches those from
# PyPI on each lab PC (small download, runs once).
#
#   Output: dist/labdesk-<version>.tar.gz   (~6 MB — the binary + install scripts)
#
# Run on the DEVELOPER machine (needs uv + gcc + the nuitka dev dep).
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PATH="$HOME/.local/bin:$PATH"
VER="$(grep -m1 '^version' "$HERE/pyproject.toml" | sed -E 's/.*"([^"]+)".*/\1/')"
ACC="$HERE/build/nuitka-acc"
OUT="$HERE/dist/labdesk-$VER"

command -v uv >/dev/null 2>&1 || { echo "!! uv is required"; exit 1; }

echo ">> baking schema.sql + seed.sqlite into the package (not shipped loose)"
( cd "$HERE" && uv run python scripts/gen_embedded.py )

echo ">> compiling LabDesk to native code (Nuitka, accelerated / non-bundling)"
rm -rf "$ACC"
# Code + baked-in schema/seed are compiled into the binary; only cosmetic assets
# (fonts/logos) ship as files, found at runtime via LABDESK_RESOURCE_DIR.
# Non-bundling: only labdesk code is compiled in. Qt/Python/SQLCipher/jeepney are
# NOT embedded — install.sh installs them (hash-pinned) into the per-PC runtime venv
# and the binary imports them at runtime. The silent-plaintext guard is the runtime
# fail-closed check in db/connection.py (it refuses to run if SQLCipher is missing),
# NOT bundling the engine — bundling a native extension here would bloat the binary
# and risk an ABI/glibc mismatch across machines.
( cd "$HERE" && uv run python -m nuitka \
    --include-package=labdesk \
    --output-dir=build/nuitka-acc --remove-output \
    --assume-yes-for-downloads \
    scripts/nuitka_entry.py )

rm -f "$HERE/src/labdesk/_embedded_data.py"  # don't leave it in the tree

# strip the compiled binary (it is plain gcc output, not the BOLT interpreter)
command -v strip >/dev/null 2>&1 && strip "$ACC/nuitka_entry.bin" 2>/dev/null || true

echo ">> staging distributable"
rm -rf "$OUT"
mkdir -p "$OUT"
cp "$ACC/nuitka_entry.bin" "$OUT/labdesk.bin"
chmod +x "$OUT/labdesk.bin"
# schema + seed + assets are ALL baked into the binary; ship only the app icon so
# install.sh can register the menu entry.
cp "$HERE/src/labdesk/assets/app_icon_256.png" "$OUT/app_icon_256.png"
cp "$HERE/scripts/install.sh" "$HERE/scripts/uninstall.sh" "$OUT/"
chmod +x "$OUT/install.sh" "$OUT/uninstall.sh"

# Hash-pinned runtime requirements consumed by install.sh (--require-hashes), so each
# lab PC installs the exact versions+sha256 the binary was built against. (install.sh
# refuses to run without this.)
echo ">> exporting hash-pinned runtime requirements for the installer"
( cd "$HERE" && uv export --frozen --no-dev --no-emit-project --no-editable -o "$OUT/requirements.txt" )

( cd "$HERE/dist" && tar czf "labdesk-$VER.tar.gz" "labdesk-$VER" )
# artifact checksums (publish alongside the download for integrity verification)
( cd "$HERE/dist" && sha256sum "labdesk-$VER/labdesk.bin" "labdesk-$VER.tar.gz" > "labdesk-$VER.sha256" )
echo ">> binary:  $(du -h "$OUT/labdesk.bin" | cut -f1)"
echo ">> done:    dist/labdesk-$VER.tar.gz  ($(du -h "$HERE/dist/labdesk-$VER.tar.gz" | cut -f1))"
echo "   Ship that tarball. On each lab PC: extract it and run ./install.sh"
