#!/usr/bin/env bash
# Install LabDesk on this PC. Run by the vendor during setup (needs internet ONCE).
#
# It installs the runtime (Python 3.13 + PySide6 + SQLCipher + jeepney) via uv,
# drops in the pre-compiled LabDesk binary, and adds a launcher + menu entry.
# Qt/Python are downloaded from PyPI here — they are NOT part of the distributable.
#
# The ONLY requirement is internet during setup: if uv isn't already installed,
# this script fetches it for you. (uv: https://docs.astral.sh/uv/)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HERE/labdesk.bin"
ICON_SRC="$HERE/app_icon_256.png"   # the one shipped file besides the binary (menu icon)

# Everything lives under ONE folder, the same one the app uses for its data:
#   ~/.local/share/LabDesk/
#     app/        the binary + bundled (cosmetic) assets   ─┐ removed by uninstall
#     runtime/    the isolated Python/Qt venv              ─┘
#     labdesk.sqlite, license.lic, assets/ (lab branding)  ── your data, kept
BASE="$HOME/.local/share/LabDesk"
APP="$BASE/app"                              # the app binary + bundled assets
RUNTIME="$BASE/runtime"                      # isolated venv with the GUI deps
BINDIR="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/256x256/apps"

# uv is the only prerequisite — install it automatically if it's missing.
if ! command -v uv >/dev/null 2>&1; then
  echo ">> 'uv' not found — installing it now (one-time, needs internet)"
  if ! command -v curl >/dev/null 2>&1; then
    echo "!! need 'curl' to fetch uv. Install curl (e.g. dnf/apt install curl) and re-run."
    exit 1
  fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv lands in ~/.local/bin (or $XDG_BIN_HOME / $CARGO_HOME/bin) — put it on PATH now.
  export PATH="$HOME/.local/bin:${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"
fi
command -v uv >/dev/null 2>&1 || {
  echo "!! uv installation failed. Install it manually and re-run:"
  echo "     curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
}
[ -f "$BIN" ] || { echo "!! labdesk.bin not found next to this script."; exit 1; }

echo ">> creating the runtime (Python 3.13 + PySide6 + SQLCipher + jeepney)"
echo "   (downloads from PyPI — this is the one-time internet step)"
rm -rf "$RUNTIME"
uv venv "$RUNTIME" --python 3.13
# Install the EXACT versions + sha256 hashes the binary was built/tested against,
# from the requirements.txt shipped beside this script (exported from uv.lock at build
# time). --require-hashes makes pip refuse anything whose hash doesn't match, so a
# compromised/yanked sqlcipher3-binary (the at-rest crypto engine) or PySide6 can't be
# silently substituted on the lab PC, and every PC gets a reproducible runtime.
REQ="$HERE/requirements.txt"
if [ -f "$REQ" ]; then
  uv pip install --python "$RUNTIME/bin/python" --require-hashes -r "$REQ"
else
  # Old tarball without a pinned manifest: refuse rather than silently resolve the
  # crypto stack live from PyPI with floating versions.
  echo "!! $REQ is missing — this tarball predates hash-pinned installs."
  echo "   Rebuild with scripts/build_release.sh (which now ships requirements.txt),"
  echo "   or re-download the current release. Refusing an unpinned install."
  exit 1
fi

# Resolve the base CPython the venv was built from + its layout. The compiled
# binary links libpython and imports the stdlib + the venv's site-packages, so the
# launcher must point PYTHONHOME / LD_LIBRARY_PATH / PYTHONPATH at them.
PYBASE="$(dirname "$(grep -E '^home[[:space:]]*=' "$RUNTIME/pyvenv.cfg" | cut -d= -f2- | xargs)")"
PYVER="$("$RUNTIME/bin/python" -c 'import sys;print("python%d.%d"%sys.version_info[:2])')"
SP="$RUNTIME/lib/$PYVER/site-packages"

echo ">> installing the app binary"
mkdir -p "$APP"
cp -f "$BIN" "$APP/labdesk.bin"
chmod +x "$APP/labdesk.bin"
# schema.sql / seed.sqlite / assets are ALL baked INTO the binary — the install
# folder holds only the binary; the app unpacks what it needs to a private temp dir.

echo ">> writing the launcher ($BINDIR/labdesk)"
mkdir -p "$BINDIR"
cat > "$BINDIR/labdesk" <<EOF
#!/usr/bin/env bash
# LabDesk launcher (installed by install.sh). Points the compiled app at the
# local runtime and turns on node-locked license enforcement.
export PYTHONHOME="$PYBASE"
export LD_LIBRARY_PATH="$PYBASE/lib:\${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$PYBASE/lib/$PYVER:$PYBASE/lib/$PYVER/lib-dynload:$SP"
# Native file dialogs on EVERY desktop (GNOME, KDE/Plasma, Sway, …) via
# xdg-desktop-portal. PySide6 bundles its own Qt, so it can't load the system's
# KDE/GNOME Qt theme plugins — the portal (over D-Bus) is the desktop-agnostic way
# to get each desktop's own native file picker. Needs xdg-desktop-portal + a backend
# (portal-gnome / portal-kde / portal-gtk); falls back to Qt's plain dialog if absent.
export QT_QPA_PLATFORMTHEME=xdgdesktopportal
export LABDESK_ENFORCE_LICENSE=1
exec "$APP/labdesk.bin" "\$@"
EOF
chmod +x "$BINDIR/labdesk"

echo ">> adding the applications-menu entry + icon"
mkdir -p "$APPS" "$ICONS"
[ -f "$ICON_SRC" ] && cp -f "$ICON_SRC" "$ICONS/labdesk.png"
# The .desktop filename matches the app's window id (StartupWMClass / Wayland
# app_id = LabDesk) so the desktop ties the running window to this launcher.
cat > "$APPS/LabDesk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=LabDesk
Comment=Laboratory Management System
Exec=$BINDIR/labdesk %U
Icon=labdesk
Categories=Office;MedicalSoftware;
Terminal=false
StartupWMClass=LabDesk
EOF
rm -f "$APPS/labdesk.desktop" 2>/dev/null || true
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
kbuildsycoca6 2>/dev/null || kbuildsycoca5 2>/dev/null || true

echo
echo "✓ LabDesk installed."
echo "  Launch it from your applications menu, or run:  $BINDIR/labdesk"
case ":$PATH:" in *":$BINDIR:"*) : ;; *)
  echo "  NOTE: $BINDIR is not on your PATH — add it, or use the menu entry." ;;
esac
echo "  First launch will ask to ACTIVATE this machine — send the activation"
echo "  request to the vendor and load back the license file."
