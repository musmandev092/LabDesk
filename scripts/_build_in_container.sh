#!/usr/bin/env bash
# Runs INSIDE quay.io/pypa/manylinux_2_34_x86_64 (invoked by build_release.sh).
# Compiles LabDesk to a native binary against glibc 2.34 (PySide6 6.11's own wheel
# floor) so it runs on every distro from ~2021 on, then stages it into dist/.
#
# Do not run this directly on the host — it expects the manylinux toolchain. It runs
# as the invoking (non-root) user via `docker run --user`, so artifacts are owned by
# you with no root-owned files left in the repo.
set -euo pipefail

# Runs as the INVOKING (non-root) user via `docker run --user` (see build_release.sh).
# HOME is a writable /tmp dir because the image's /root isn't writable unprivileged.
export HOME="${HOME:-/tmp/labdesk-build-home}"
mkdir -p "$HOME"
export PATH="$HOME/.local/bin:$PATH"
# Keep uv's cache / managed pythons / the project venv OFF the mounted /src so we
# never leave root-owned junk in the repo. Only build/ and dist/ are written there
# (and chowned back to the invoking user below).
#
# UV_CACHE_DIR / UV_PYTHON_INSTALL_DIR default to ephemeral /tmp, but build_release.sh
# overrides them (via -e) to a PERSISTENT host dir it mounts, so rebuilds reuse the
# ~250MB of downloaded Qt/CPython instead of re-fetching every time. The venv itself
# stays ephemeral (cheap to rebuild from the warm cache).
export UV_PROJECT_ENVIRONMENT=/tmp/labdesk-venv
: "${UV_CACHE_DIR:=/tmp/uv-cache}"
: "${UV_PYTHON_INSTALL_DIR:=/tmp/uv-python}"
export UV_CACHE_DIR UV_PYTHON_INSTALL_DIR
# The manylinux image's /opt/python has NO shared libpython (static-libs only),
# which Nuitka can't link against. Force uv to fetch a managed python-build-
# standalone instead — it ships libpython3.13.so and is the same interpreter the
# lab PC's install.sh uses, so the compiled binary's libpython ABI matches.
export UV_PYTHON_PREFERENCE=only-managed

VER="$(grep -m1 '^version' /src/pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')"

echo ">> installing uv inside the container"
curl -LsSf https://astral.sh/uv/install.sh | sh

cd /src
echo ">> uv sync (Python 3.13 + deps + nuitka/patchelf, from uv.lock)"
uv sync --frozen

echo ">> baking schema.sql + seed.sqlite into the package (so they aren't shipped loose)"
uv run python scripts/gen_embedded.py

echo ">> compiling LabDesk with Nuitka (accelerated / non-bundling)"
# Code + the baked-in schema/seed are compiled into the binary. Only the cosmetic
# assets (fonts/logos) ship as files and are found via LABDESK_RESOURCE_DIR.
# Non-bundling: only labdesk code is compiled in. Qt/Python/SQLCipher/jeepney are NOT
# embedded — install.sh installs them (hash-pinned) into the per-PC runtime venv and the
# binary imports them at runtime. The silent-plaintext guard is the runtime fail-closed
# check in db/connection.py, NOT bundling the native engine (which would bloat the binary
# and risk an ABI/glibc mismatch — the very thing this manylinux build avoids).
uv run python -m nuitka \
  --include-package=labdesk \
  --output-dir=build/nuitka-rel --remove-output \
  --assume-yes-for-downloads \
  scripts/nuitka_entry.py

# Sanity-check that SQLCipher resolves + actually ciphers in the build env (so the
# hash-pinned requirements.txt we ship can't reference a broken/keyless engine).
echo ">> verifying SQLCipher is functional (pinned for install.sh to deploy)"
uv run python -c "import sqlcipher3.dbapi2 as s; c=s.connect(':memory:'); c.execute(\"PRAGMA key='x'\"); assert c.execute('PRAGMA cipher_version').fetchone()[0], 'no cipher'; print('   sqlcipher3 OK:', c.execute('PRAGMA cipher_version').fetchone()[0])"

# Drop the generated module so it never lingers in the source tree.
rm -f src/labdesk/_embedded_data.py

echo ">> stripping the binary"
strip build/nuitka-rel/nuitka_entry.bin

echo ">> staging distributable"
OUT="dist/labdesk-$VER"
rm -rf "$OUT"
mkdir -p "$OUT"
cp build/nuitka-rel/nuitka_entry.bin "$OUT/labdesk.bin"
chmod +x "$OUT/labdesk.bin"
# schema + seed + assets are ALL baked into the binary. The only extra file shipped
# is the app icon (a plain logo) so install.sh can register the menu entry.
cp src/labdesk/assets/app_icon_256.png "$OUT/app_icon_256.png"
cp scripts/install.sh scripts/uninstall.sh "$OUT/"
chmod +x "$OUT/install.sh" "$OUT/uninstall.sh"

# Hash-pinned runtime requirements (exact versions + sha256 for the whole transitive
# closure, straight from uv.lock — the SAME stack the binary was compiled against).
# install.sh consumes this with --require-hashes so each lab PC can't silently resolve
# a tampered/yanked sqlcipher3-binary or PySide6 fresh from PyPI.
echo ">> exporting hash-pinned runtime requirements for the installer"
uv export --frozen --no-dev --no-emit-project --no-editable -o "$OUT/requirements.txt"
( cd dist && tar czf "labdesk-$VER.tar.gz" "labdesk-$VER" )

# Artifact integrity: record SHA-256 of the binary + tarball so the vendor can verify
# what was shipped (publish these alongside the download; ideally sign SHA256SUMS too).
echo ">> recording artifact checksums (dist/labdesk-$VER.sha256)"
( cd dist && sha256sum "labdesk-$VER/labdesk.bin" "labdesk-$VER.tar.gz" > "labdesk-$VER.sha256" )
cat "dist/labdesk-$VER.sha256"

echo ">> max glibc symbol required by the binary:"
objdump -T "$OUT/labdesk.bin" | grep -oE 'GLIBC_[0-9.]+' | sort -V | tail -1 || true

# When run as root (legacy/manual invocation) hand artifacts back to the host user.
# Under `docker run --user` they are already owned correctly, so this is a no-op.
if [ "$(id -u)" = "0" ]; then
  chown -R "${HOST_UID:-0}:${HOST_GID:-0}" build dist
fi

echo ">> binary:  $(du -h "$OUT/labdesk.bin" | cut -f1)"
echo ">> done:    dist/labdesk-$VER.tar.gz  ($(du -h "dist/labdesk-$VER.tar.gz" | cut -f1))"
