#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# macOS repair/install for CADWiz workbench. Does not configure AI providers.
# Run from an extracted CADWiz release: bash scripts/install_macos.sh
set -euo pipefail

fail() { printf 'CADWiz installation stopped: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }

[ "$(uname -s)" = Darwin ] || fail "This installer is for macOS only."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "$SCRIPT_DIR/.." && pwd)/CADWiz"
[ -f "$SOURCE/InitGui.py" ] || fail "Release is incomplete: missing CADWiz/InitGui.py."
[ -f "$SOURCE/src/integrations/cadwiz_plugin/addon.py" ] || fail "Release is incomplete: missing CADWiz Python code."
[ -d "/Applications/FreeCAD.app" ] || note "Warning: FreeCAD was not found in /Applications. Check your FreeCAD installation."

# Never overwrite or modify an active FreeCAD installation.
if pgrep -x FreeCAD >/dev/null 2>&1; then
  fail "Quit FreeCAD completely, then rerun the installer."
fi

# FreeCAD 1.1 normally uses v1-1; allow an explicit override for custom installs.
MOD_DIR="${MOD_DIR:-$HOME/Library/Application Support/FreeCAD/v1-1/Mod}"
[ -d "$(dirname "$MOD_DIR")" ] || note "Creating the FreeCAD v1-1 user directory."
mkdir -p "$MOD_DIR" || fail "Cannot write to FreeCAD's user Mod directory: $MOD_DIR"

STAMP="$(date +%Y%m%d-%H%M%S)-$$"
TARGET="$MOD_DIR/CADWiz"
STAGING="$MOD_DIR/.CADWiz.install.$STAMP"
BACKUP=""
cleanup() { [ ! -d "$STAGING" ] || rm -rf "$STAGING"; }
trap cleanup EXIT
cp -R "$SOURCE" "$STAGING" || fail "Could not copy CADWiz into the staging directory."
[ -f "$STAGING/InitGui.py" ] || fail "Staged install missing InitGui.py."
[ -f "$STAGING/src/integrations/cadwiz_plugin/addon.py" ] || fail "Staged install missing addon.py."

# The Mac defaults to case-insensitive storage: 'cadwiz' and 'CADWiz'
# may refer to the SAME directory. Back up just once.
if [ -e "$MOD_DIR/cadwiz" ] || [ -e "$TARGET" ]; then
  EXISTING="$TARGET"
  [ -e "$EXISTING" ] || EXISTING="$MOD_DIR/cadwiz"
  BACKUP="$MOD_DIR/cadwiz.backup.$STAMP"
  mv "$EXISTING" "$BACKUP" || fail "Unable to back up the current CADWiz folder."
  note "Saved previous installation: $BACKUP"
fi
if ! mv "$STAGING" "$TARGET"; then
  if [ -n "$BACKUP" ] && [ ! -e "$TARGET" ]; then mv "$BACKUP" "$TARGET" || true; fi
  fail "Could not install CADWiz; previous version was restored where possible."
fi
[ -f "$TARGET/InitGui.py" ] || fail "Install failed verification: InitGui.py is absent."
[ -f "$TARGET/src/integrations/cadwiz_plugin/addon.py" ] || fail "Install failed verification: CADWiz code is absent."
note "CADWiz workbench installed: $TARGET"
note "The installed folder is Mod/CADWiz with InitGui.py immediately inside it."
note "Restart FreeCAD. If the CADWiz panel is absent, open View > Panels and check the Report view for 'CADWiz could not start'."
note "This installer does not change Claude/ChatGPT settings or install Python dependencies."
note "If the panel fails to load, collect the full FreeCAD Report view and report it at https://cadwiz.app/feedback."
note "No models, documents, or assistant settings were deleted."
