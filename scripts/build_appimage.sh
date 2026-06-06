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

echo ">> trimming bundle (caches, tests, static libs)"
find "$APPDIR/usr/python" -depth -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$APPDIR/usr/python" -type f -name '*.pyc' -delete 2>/dev/null || true
# drop heavy PySide6 modules the app never imports (keep core/gui/widgets/print + sqlite)
SP="$APPDIR/usr/python/lib/python3.12/site-packages/PySide6"
if [ -d "$SP" ]; then
  # Only remove clearly-independent heavy modules. Keep Network/OpenGL/Sql etc.
  # because QtGui/QtWidgets/QtPrintSupport may link against them.
  # NOTE: QtPdf is KEPT — report.py rasterises the WeasyPrint PDF to the printer.
  for mod in Qt3D* QtWeb* QtQuick* QtQml* QtMultimedia* QtCharts* QtDataVisualization* \
             QtBluetooth* QtNfc* QtPositioning* QtLocation* QtSensors* QtSerialPort* \
             QtRemoteObjects* QtScxml* QtSpatialAudio* QtTextToSpeech* \
             QtDesigner* QtHelp* QtQuick3D*; do
    rm -rf "$SP"/$mod 2>/dev/null || true
  done
  rm -rf "$SP/Qt/qml" "$SP/Qt/translations" 2>/dev/null || true
fi
# remove matching shared libs for the trimmed modules
QTLIB="$SP/Qt/lib"
if [ -d "$QTLIB" ]; then
  for pat in Qt63D Qt6Web Qt6Quick Qt6Qml Qt6Multimedia Qt6Charts Qt6DataVisualization \
             Qt6Bluetooth Qt6Nfc Qt6Positioning Qt6Location Qt6Sensors Qt6SerialPort \
             Qt6RemoteObjects Qt6Scxml Qt6SpatialAudio Qt6TextToSpeech Qt6Designer \
             Qt6Help Qt6Quick3D; do
    rm -f "$QTLIB/lib${pat}"*.so* 2>/dev/null || true
  done
fi

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
ARCH=x86_64 "$TOOLS/appimagetool" --appimage-extract-and-run "$APPDIR" \
    "$BUILD/$APPID-x86_64.AppImage"

echo ">> done: $BUILD/$APPID-x86_64.AppImage"
ls -lh "$BUILD/$APPID-x86_64.AppImage"
