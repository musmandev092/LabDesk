#!/usr/bin/env bash
# Optional: re-pack the already-built AppImage with xz + x86 BCJ compression for
# ~15% smaller output than the default zstd. ROOT-FREE.
#
# appimagetool's bundled mksquashfs is zstd-only, so this needs a separate
# xz-capable mksquashfs. The easiest root-free source is conda-forge:
#
#   curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba
#   ./bin/micromamba create -y -p ./sqfs-env -c conda-forge squashfs-tools
#   MKSQUASHFS=./sqfs-env/bin/mksquashfs scripts/repack_xz.sh
#
# or point MKSQUASHFS at any mksquashfs whose `-help-comp` lists xz.
#
# It reuses the runtime from the existing zstd AppImage (via --appimage-offset),
# so it needs no network: just run scripts/build_appimage.sh first.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$HERE/build"
APPDIR="$BUILD/LabDesk.AppDir"
SRC="$BUILD/LabDesk-x86_64.AppImage"           # the zstd AppImage (runtime source)
OUT="${1:-$BUILD/LabDesk-x86_64.AppImage}"     # overwrite by default
MKSQUASHFS="${MKSQUASHFS:-mksquashfs}"

[ -d "$APPDIR" ] || { echo "!! $APPDIR missing — run scripts/build_appimage.sh first" >&2; exit 1; }
[ -x "$SRC" ]   || { echo "!! $SRC missing — run scripts/build_appimage.sh first" >&2; exit 1; }
command -v "$MKSQUASHFS" >/dev/null 2>&1 || {
  echo "!! no mksquashfs found. Get an xz-capable one root-free, e.g.:" >&2
  echo "   curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba" >&2
  echo "   ./bin/micromamba create -y -p ./sqfs-env -c conda-forge squashfs-tools" >&2
  echo "   MKSQUASHFS=./sqfs-env/bin/mksquashfs $0" >&2
  exit 1; }
if ! "$MKSQUASHFS" -help-comp all 2>&1 | grep -qiw xz && \
   ! "$MKSQUASHFS" -help 2>&1 | grep -qiw xz; then
  echo "!! $MKSQUASHFS has no xz support (bundled appimagetool one is zstd-only)." >&2
  echo "   Install squashfs-tools from conda-forge as shown in this script's header." >&2
  exit 1
fi

echo ">> carving AppImage runtime from $SRC"
OFFSET="$("$SRC" --appimage-offset)"           # bytes of runtime before the squashfs
[ "$OFFSET" -gt 0 ] 2>/dev/null || { echo "!! could not read --appimage-offset" >&2; exit 1; }
head -c "$OFFSET" "$SRC" > "$BUILD/.runtime"
echo "   runtime: $OFFSET bytes"

echo ">> building xz+bcj squashfs"
rm -f "$BUILD/.payload.squashfs"
"$MKSQUASHFS" "$APPDIR" "$BUILD/.payload.squashfs" \
    -root-owned -noappend -mkfs-time 0 \
    -comp xz -Xbcj x86 -b 1048576 -Xdict-size 100%

echo ">> assembling AppImage (runtime + squashfs)"
tmp="$BUILD/.out.AppImage"
cat "$BUILD/.runtime" "$BUILD/.payload.squashfs" > "$tmp"
chmod +x "$tmp"
mv -f "$tmp" "$OUT"
rm -f "$BUILD/.runtime" "$BUILD/.payload.squashfs"

# sanity: the runtime must still find its filesystem
"$OUT" --appimage-offset >/dev/null || { echo "!! reassembled AppImage looks broken" >&2; exit 1; }
echo ">> done: $OUT ($(du -h "$OUT" | cut -f1), was $(du -h "$SRC" 2>/dev/null | cut -f1 || echo '?'))"
ls -lh "$OUT"
