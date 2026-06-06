#!/usr/bin/env bash
# Register LabDesk in the desktop menu/launcher with its microscope logo.
# Usage:  ./install_desktop.sh [/path/to/LabDesk-x86_64.AppImage]
# (defaults to the AppImage sitting next to this script, or in ./build)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APPIMAGE="${1:-}"
if [ -z "$APPIMAGE" ]; then
  for c in "$HERE/LabDesk-x86_64.AppImage" "$HERE/../build/LabDesk-x86_64.AppImage" \
           "$HOME/LabDesk-x86_64.AppImage"; do
    [ -f "$c" ] && APPIMAGE="$c" && break
  done
fi
[ -n "$APPIMAGE" ] && [ -f "$APPIMAGE" ] || { echo "AppImage not found. Pass its path:  $0 /path/to/LabDesk-x86_64.AppImage"; exit 1; }
APPIMAGE="$(readlink -f "$APPIMAGE")"
chmod +x "$APPIMAGE" 2>/dev/null || true

ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$ICON_DIR" "$APP_DIR"

# pull the microscope icon out of the AppImage and install it
TMP="$(mktemp -d)"; ( cd "$TMP" && "$APPIMAGE" --appimage-extract LabDesk.png >/dev/null 2>&1 || true )
if [ -f "$TMP/squashfs-root/LabDesk.png" ]; then
  cp "$TMP/squashfs-root/LabDesk.png" "$ICON_DIR/labdesk.png"
  echo "   icon installed -> $ICON_DIR/labdesk.png"
else
  echo "   WARNING: could not extract icon from the AppImage"
fi
rm -rf "$TMP"

cat > "$APP_DIR/labdesk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=LabDesk
Comment=Laboratory Management System
Exec="$APPIMAGE" %U
Icon=labdesk
Categories=Office;MedicalSoftware;
Terminal=false
StartupWMClass=LabDesk
EOF
echo "   launcher installed -> $APP_DIR/labdesk.desktop"

update-desktop-database "$APP_DIR" 2>/dev/null || true
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Done. 'LabDesk' is now in your apps menu with the logo."
echo "If the menu/dock still shows the old icon, log out/in (or restart the shell)."
