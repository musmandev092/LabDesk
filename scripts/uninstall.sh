#!/usr/bin/env bash
# Remove LabDesk from this PC. Keeps the patient DATA (encrypted, in
# ~/.local/share/LabDesk) — delete that yourself only if you really mean to.
set -euo pipefail

BASE="$HOME/.local/share/LabDesk"        # the one LabDesk folder (app + data)
BINDIR="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/256x256/apps"

# Remove only the installed program (app/ + runtime/). The patient database,
# license and lab branding sit at the top of $BASE and are left untouched.
rm -rf "$BASE/app" "$BASE/runtime"
rm -f "$BINDIR/labdesk"
rm -f "$APPS/LabDesk.desktop"
rm -f "$ICONS/labdesk.png"
update-desktop-database "$APPS" 2>/dev/null || true
kbuildsycoca6 2>/dev/null || kbuildsycoca5 2>/dev/null || true

echo "✓ LabDesk removed (app + runtime)."
echo "  Your data in $BASE was NOT touched (DB, license, branding)."
echo "  To erase everything including patient data:  rm -rf $BASE"
