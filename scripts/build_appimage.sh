#!/usr/bin/env bash
# Build a self-contained AppImage for LabDesk (white-label LMS).
# Bundles a relocatable standalone CPython 3.12 + PySide6 + the app, so it runs
# on AlmaLinux (and most Linux desktops) without any system Python or Qt.
set -euo pipefail

APP="LabDesk"
APPID="LabDesk"
HERE="$(cd "$(dirname "$0")/.." && pwd)"          # app/
BUILD="$HERE/build"
APPDIR="$BUILD/$APPID.AppDir"
TOOLS="$BUILD/tools"
PATH="$HOME/.local/bin:$PATH"

echo ">> resolving standalone python"
REALPY="$(readlink -f "$HERE/.venv/bin/python3")"
PYROOT="$(dirname "$(dirname "$REALPY")")"
echo "   python root: $PYROOT"

echo ">> cleaning AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"

echo ">> copying python runtime into bundle"
cp -a "$PYROOT" "$APPDIR/usr/python"
BPY="$APPDIR/usr/python/bin/python3.12"

echo ">> vendoring packages from .venv into the bundled python"
VENV_SP="$HERE/.venv/lib/python3.12/site-packages"
BUNDLE_SP="$APPDIR/usr/python/lib/python3.12/site-packages"
mkdir -p "$BUNDLE_SP"
# PySide6 + shiboken6 (and their dist-info) — copied, not re-downloaded
for pkg in PySide6 shiboken6 \
           pyside6-6.11.1.dist-info pyside6_addons-6.11.1.dist-info \
           pyside6_essentials-6.11.1.dist-info shiboken6-6.11.1.dist-info; do
  cp -a "$VENV_SP/$pkg" "$BUNDLE_SP/" 2>/dev/null || true
done
# WeasyPrint + its pure-Python dependencies (PDF rendering engine)
for pkg in weasyprint pydyf tinycss2 tinyhtml5 cssselect2 webencodings \
           pyphen PIL fontTools cffi pycparser brotli brotlicffi zopfli; do
  cp -a "$VENV_SP/$pkg" "$BUNDLE_SP/" 2>/dev/null || true
  cp -a "$VENV_SP/$pkg"-*.dist-info "$BUNDLE_SP/" 2>/dev/null || true
done
# top-level compiled extension modules (cffi backend, zopfli, brotli, etc.)
for so in "$VENV_SP"/_cffi_backend*.so "$VENV_SP"/_brotli*.so "$VENV_SP"/zopfli*.so; do
  [ -f "$so" ] && cp -a "$so" "$BUNDLE_SP/"
done
# manylinux ".libs" sidecars (Pillow ships libtiff/libjpeg/… in pillow.libs,
# referenced via the extension's RPATH=$ORIGIN/../<pkg>.libs)
for libsdir in "$VENV_SP"/*.libs; do
  [ -d "$libsdir" ] && cp -a "$libsdir" "$BUNDLE_SP/"
done

# our app, vendored as a real (non-editable) package
cp -a "$HERE/src/labdesk" "$BUNDLE_SP/labdesk"

echo ">> bundling WeasyPrint native libraries (pango / glib / fontconfig …)"
NATIVE="$APPDIR/usr/lib"
mkdir -p "$NATIVE"
# Best-effort, SIGPIPE-tolerant: relax -e/pipefail for this discovery block.
set +e +o pipefail
# WeasyPrint dlopens these 6; bundle them plus their transitive deps, minus the
# core C runtime (glibc/ld/libstdc++ stay on the host to avoid ABI breakage).
SEED_LIBS="libfontconfig.so.1 libgobject-2.0.so.0 libharfbuzz.so.0 \
           libharfbuzz-subset.so.0 libpango-1.0.so.0 libpangoft2-1.0.so.0"
EXCLUDE='^(libc|libm|libdl|libpthread|librt|libresolv|ld-linux|libstdc\+\+|libgcc_s)\.'
LDC="$(/usr/bin/ldconfig -p 2>/dev/null)"
declare -A SEEN
queue=()
for s in $SEED_LIBS; do
  # ldconfig lines look like: "<TAB>soname (libc6,x86-64) => /path/soname"
  p="$(printf '%s\n' "$LDC" | awk -v n="$s" '$1==n{print $NF}' | head -n1)"
  [ -n "$p" ] && queue+=("$p")
done
while [ ${#queue[@]} -gt 0 ]; do
  lib="${queue[0]}"; queue=("${queue[@]:1}")
  base="$(basename "$lib")"
  [ -n "${SEEN[$base]:-}" ] && continue
  printf '%s\n' "$base" | grep -qE "$EXCLUDE" && continue
  real="$(readlink -f "$lib")"
  [ -f "$real" ] || continue
  SEEN[$base]=1
  cp -a "$real" "$NATIVE/$base"
  # enqueue this lib's own NEEDED dependencies
  deps="$(ldd "$real" 2>/dev/null | grep '=>')"
  while read -r _name _arrow path _rest; do
    [ -f "$path" ] && queue+=("$path")
  done < <(printf '%s\n' "$deps")
done
echo "   bundled $(ls "$NATIVE" 2>/dev/null | wc -l) native libs"
set -e -o pipefail

echo ">> bundling Inter font + a minimal fontconfig config"
mkdir -p "$APPDIR/usr/share/fonts"
cp -a "$HERE/src/labdesk/assets/fonts/Inter.ttf" "$APPDIR/usr/share/fonts/" 2>/dev/null || true
mkdir -p "$APPDIR/usr/etc/fonts"
cat > "$APPDIR/usr/etc/fonts/fonts.conf" <<'FCEOF'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>/usr/share/fonts</dir>
  <dir prefix="xdg">fonts</dir>
  <cachedir prefix="xdg">fontconfig</cachedir>
  <cachedir>/tmp/.labdesk-fc-cache</cachedir>
  <config></config>
</fontconfig>
FCEOF

echo ">> trimming bundle (this is what keeps the AppImage small — see PROGRESS notes)"
PYLIB="$APPDIR/usr/python/lib/python3.12"
SP="$PYLIB/site-packages"
QSP="$SP/PySide6"
QTLIB="$QSP/Qt/lib"

# -- byte-compiled caches --------------------------------------------------
find "$APPDIR/usr/python" -depth -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$APPDIR/usr/python" -type f -name '*.pyc' -delete 2>/dev/null || true

# -- stdlib + pip the bundled runtime never needs --------------------------
( cd "$PYLIB" && rm -rf ensurepip idlelib lib2to3 tkinter turtledemo turtle.py \
      pydoc_data test 2>/dev/null || true )
find "$SP" -mindepth 1 -maxdepth 2 -type d \( -name test -o -name tests \) -exec rm -rf {} + 2>/dev/null || true
rm -rf "$SP"/pip "$SP"/pip-*.dist-info "$SP"/setuptools "$SP"/pkg_resources \
       "$SP"/_distutils_hack "$SP"/setuptools-*.dist-info 2>/dev/null || true

# -- WeasyPrint deps the English/TTF render path doesn't use ----------------
#    brotli/zopfli are WOFF/WOFF2 (de)compression; the bundled font is TTF.
rm -f  "$SP"/_brotli.cpython-*.so 2>/dev/null || true
rm -rf "$SP"/brotli "$SP"/brotli-*.dist-info "$SP"/zopfli "$SP"/zopfli-*.dist-info 2>/dev/null || true
#    Pillow AVIF: ~5MB codec for a format no lab logo uses (lazy-loaded plugin).
rm -f  "$SP"/PIL/_avif.cpython-*.so "$SP"/PIL/AvifImagePlugin.py 2>/dev/null || true
rm -f  "$SP"/pillow.libs/libavif-*.so* 2>/dev/null || true
#    Hyphenation: keep English only (reports are issued in English).
if [ -d "$SP/pyphen/dictionaries" ]; then
  ( cd "$SP/pyphen/dictionaries" && \
    find . -maxdepth 1 -name 'hyph_*.dic' ! -name 'hyph_en*.dic' -delete 2>/dev/null || true )
fi

if [ -d "$QSP" ]; then
  # -- PySide6 dev/CLI tools + build-time artifacts (not needed at runtime) --
  ( cd "$QSP" && rm -rf assistant linguist lupdate lrelease qmlls qmlformat qmllint \
        qmlimportscanner qmltyperegistrar qsb balsam balsamui deploy.py android_deploy.py \
        project examples scripts glue doc include typesystems metatypes Designer designer \
        rcc uic lconvert lprodump qml QtAsyncio svgtoqml lib 2>/dev/null || true )
  rm -f "$QSP"/*.pyi "$QSP"/libpyside6qml.abi3.so* 2>/dev/null || true

  # -- Python bindings: keep ONLY the modules the app imports ----------------
  KEEP_MODS="QtCore QtGui QtNetwork QtPdf QtPdfWidgets QtPrintSupport QtWidgets"
  for so in "$QSP"/*.abi3.so; do
    [ -e "$so" ] || continue
    m="$(basename "$so" .abi3.so)"
    case " $KEEP_MODS " in *" $m "*) : ;; *) rm -f "$so" ;; esac
  done

  # -- Qt resources / plugins the app never loads ----------------------------
  rm -rf "$QSP/Qt/resources" "$QSP/Qt/libexec" "$QSP/Qt/qml" "$QSP/Qt/translations" 2>/dev/null || true
  ( cd "$QSP/Qt/plugins" 2>/dev/null && rm -rf \
        sceneparsers assetimporters renderers renderplugins geometryloaders \
        sqldrivers qmltooling qmllint scxmldatamodel multimedia geoservices position \
        canbus wayland-shell-integration wayland-graphics-integration-server \
        wayland-graphics-integration-client wayland-decoration-client \
        egldeviceintegrations sensors texttospeech webview designer vectorimageformats \
        2>/dev/null || true )
  # platform plugins: keep only xcb (desktop) + offscreen (headless/self-test)
  ( cd "$QSP/Qt/plugins/platforms" 2>/dev/null && \
    find . -maxdepth 1 -name 'libq*.so' ! -name 'libqxcb.so' ! -name 'libqoffscreen.so' \
        -delete 2>/dev/null || true )
  # drop the dangling virtual-keyboard / ibus input-context plugins (keep compose)
  rm -f "$QSP/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so" \
        "$QSP/Qt/plugins/platforminputcontexts/libibusplatforminputcontextplugin.so" 2>/dev/null || true

  # -- FFmpeg (QtMultimedia only; ~56MB of dup copies) -----------------------
  rm -f "$QTLIB"/libav*.so* 2>/dev/null || true

  # -- remove every libQt6*.so left unreachable from the kept bindings+plugins
  #    (computed via ldd closure so it self-adapts across Qt versions). icu* and
  #    other non-Qt libs are dependencies and are preserved automatically.
  if [ -d "$QTLIB" ]; then
    export LD_LIBRARY_PATH="$QTLIB:$APPDIR/usr/lib:${LD_LIBRARY_PATH:-}"
    need="$(mktemp)"; q="$(mktemp)"
    for m in $KEEP_MODS; do [ -f "$QSP/$m.abi3.so" ] && echo "$QSP/$m.abi3.so" >> "$q"; done
    find "$QSP/Qt/plugins" -name '*.so' >> "$q" 2>/dev/null
    : > "$need"
    while [ -s "$q" ]; do
      f="$(head -n1 "$q")"; sed -i 1d "$q"
      for d in $(ldd "$f" 2>/dev/null | grep -oE 'libQt6[A-Za-z]+\.so\.6' | sort -u); do
        grep -qxF "$d" "$need" && continue
        echo "$d" >> "$need"; [ -f "$QTLIB/$d" ] && echo "$QTLIB/$d" >> "$q"
      done
    done
    for lib in "$QTLIB"/libQt6*.so.6; do
      [ -e "$lib" ] || continue
      grep -qxF "$(basename "$lib")" "$need" || rm -f "$lib"*
    done
    rm -f "$need" "$q"
  fi
fi
echo "   trimmed bundle: $(du -sh "$APPDIR/usr" | cut -f1)"

echo ">> installing app icon (microscope logo)"
ICON_SRC="$HERE/src/labdesk/assets/app_icon_256.png"
if [ -f "$ICON_SRC" ]; then
  cp -a "$ICON_SRC" "$APPDIR/$APPID.png"
  echo "   icon = $ICON_SRC"
else
  echo "   WARNING: $ICON_SRC missing; AppImage will have no icon"
fi

echo ">> writing .desktop"
cat > "$APPDIR/$APPID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP
Comment=Laboratory Management System
Exec=AppRun
Icon=$APPID
Categories=Office;MedicalSoftware;
Terminal=false
StartupWMClass=LabDesk
EOF

echo ">> writing AppRun"
cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
PYDIR="$HERE/usr/python"
# bundled WeasyPrint native libs (pango/glib/fontconfig…) ahead of host libs
export LD_LIBRARY_PATH="$HERE/usr/lib:$PYDIR/lib:${LD_LIBRARY_PATH:-}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
# fontconfig: use the bundled config so Inter resolves without host font data
export FONTCONFIG_PATH="$HERE/usr/etc/fonts"
export FONTCONFIG_FILE="$HERE/usr/etc/fonts/fonts.conf"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
# Qt: let PySide6 locate its bundled plugins; offer xcb by default on desktops.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
exec "$PYDIR/bin/python3.12" -m labdesk "$@"
EOF
chmod +x "$APPDIR/AppRun"

echo ">> building AppImage"
OUT="$BUILD/$APPID-x86_64.AppImage"
LOG="$BUILD/.appimagetool.log"
# Remove any prior artifact FIRST, for two reasons:
#  1. unlinking frees the path even if an old build is still running (a busy
#     executable can't be overwritten — ETXTBSY — but mksquashfs can create a
#     fresh file at the now-free path);
#  2. a leftover file then can't masquerade as a fresh successful build below.
rm -f "$OUT"

set +e -o pipefail
# The bundled mksquashfs only ships zstd, so push it to max level (22, vs the
# level-15 default) with 1 MiB blocks for the best ratio it can manage. Costs a
# little build + first-launch time; payload is mostly already-stripped ELF.
ARCH=x86_64 "$TOOLS/appimagetool" --appimage-extract-and-run \
    --comp zstd \
    --mksquashfs-opt -b --mksquashfs-opt 1M \
    --mksquashfs-opt -Xcompression-level --mksquashfs-opt 22 \
    "$APPDIR" "$OUT" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
set -e

# appimagetool exits 0 even when its mksquashfs child fails — so don't trust the
# exit code alone. Fail loudly on a non-zero code, a squashfs error in the log,
# or a missing / implausibly small output file.
if [ "$rc" -ne 0 ]; then
  echo "!! appimagetool failed (exit $rc) — see output above" >&2
  exit "$rc"
fi
if grep -qiE 'mksquashfs .*exited with code|sfs_mksquashfs error|Text file busy' "$LOG"; then
  echo "!! squashfs packaging failed (is a LabDesk AppImage still running / the file busy?)" >&2
  exit 1
fi
if [ ! -s "$OUT" ]; then
  echo "!! expected output not produced: $OUT" >&2
  exit 1
fi
sz=$(stat -c%s "$OUT")
if [ "$sz" -lt 10000000 ]; then
  echo "!! output is implausibly small ($sz bytes) — build likely failed: $OUT" >&2
  exit 1
fi
rm -f "$LOG"

echo ">> done: $OUT"
ls -lh "$OUT"
