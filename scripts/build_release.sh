#!/usr/bin/env bash
# Build the PORTABLE LabDesk distributable.
#
# Compiles the app to a native binary INSIDE the manylinux_2_34 image so the
# result needs no newer than glibc 2.34 — the same floor as PySide6 6.11's own
# Linux wheels. It then runs on every distro from ~2021 on (Ubuntu 22.04,
# RHEL/AlmaLinux 9, Debian 12, etc.). Older distros (Ubuntu 20.04, RHEL 8) cannot
# run PySide6 6.11 regardless, so they are out of scope by design.
#
#   Output: dist/labdesk-<version>.tar.gz   (~2-6 MB — the binary + install scripts)
#
# Requires: docker (daemon running, your user in the 'docker' group).
# For a quick, NON-portable build on the dev host, use scripts/build_app.sh instead.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
# Pin the build image by DIGEST for reproducibility / supply-chain integrity. The
# floating tag is the default for convenience, but production builds should set
# LABDESK_BUILD_IMAGE to a digest-pinned ref, e.g.:
#   export LABDESK_BUILD_IMAGE="quay.io/pypa/manylinux_2_34_x86_64@sha256:<digest>"
IMAGE="${LABDESK_BUILD_IMAGE:-quay.io/pypa/manylinux_2_34_x86_64}"
case "$IMAGE" in
  *@sha256:*) : ;;  # digest-pinned — good
  *) echo "   NOTE: building from a floating tag ($IMAGE). For a reproducible/"
     echo "         supply-chain-hardened build, pin LABDESK_BUILD_IMAGE to a @sha256 digest." ;;
esac

command -v docker >/dev/null 2>&1 || { echo "!! docker is required"; exit 1; }
docker info >/dev/null 2>&1 || {
  echo "!! cannot reach the docker daemon."
  echo "   Is it running, and is your user in the 'docker' group?"
  echo "     sudo systemctl enable --now docker"
  echo "     sudo usermod -aG docker \"\$USER\"   # then log out/in (or: newgrp docker)"
  exit 1
}

echo ">> pulling $IMAGE (first run only)"
docker pull "$IMAGE"

# Persistent download cache so rebuilds don't re-fetch ~250MB of Qt/CPython each
# time. Lives outside the repo (in your XDG cache); first build fills it, the rest
# reuse it. Override the location with LABDESK_BUILD_CACHE, or delete it to reclaim
# the space. Mounted into the container and pointed at by uv (see _build_in_container.sh).
CACHE="${LABDESK_BUILD_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/labdesk-build}"
mkdir -p "$CACHE/uv" "$CACHE/python"

echo ">> building inside manylinux_2_34 (glibc 2.34 — portable)"
echo "   (download cache: $CACHE — first build is slow, later ones reuse it)"
# Run as the INVOKING user (not root): no root-owned files land in the repo/cache and
# the build can't run as root inside the container. HOME is redirected to a writable
# /tmp dir (the manylinux image's /root isn't writable by a non-root user). uv, nuitka,
# strip, objdump and patchelf all run fine unprivileged.
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -e HOME=/tmp/labdesk-build-home \
  -e UV_CACHE_DIR=/cache/uv -e UV_PYTHON_INSTALL_DIR=/cache/python \
  -v "$CACHE":/cache \
  -v "$HERE":/src -w /src \
  "$IMAGE" bash /src/scripts/_build_in_container.sh

echo
echo "✓ portable distributable ready in dist/"
echo "  Verify the glibc floor:  objdump -T dist/labdesk-*/labdesk.bin | grep -oE 'GLIBC_[0-9.]+' | sort -V | tail -1   (expect <= 2.34)"
