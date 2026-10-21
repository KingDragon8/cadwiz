#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
#
# Install CADWiz on macOS or Linux (LESS TESTED than Windows -- reports welcome at
# https://cadwiz.app/feedback). Close FreeCAD and Claude Desktop first.
#
#   bash scripts/install.sh            # copy CADWiz into FreeCAD and connect Claude Desktop
#   bash scripts/install.sh --source   # developers: point Claude Desktop at this checkout
#
# It asks before opening FreeCAD's download page (it never downloads by itself),
# keeps any earlier CADWiz as CADWiz.backup.<date>, saves a copy of Claude
# Desktop's settings before adding CADWiz, and lists what it changed.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$REPO/CADWiz"
STAMP="$(date +%Y%m%d-%H%M%S)"
SOURCE_ONLY=0; [ "${1:-}" = "--source" ] && SOURCE_ONLY=1
CHANGED=()

case "$(uname -s)" in
  Darwin)
    FREECAD_PY="${FREECAD_PY:-/Applications/FreeCAD.app/Contents/Resources/bin/python}"
    MOD_DIR="${MOD_DIR:-$HOME/Library/Application Support/FreeCAD/v1-1/Mod}"
    CLAUDE_CONFIG="${CLAUDE_CONFIG:-$HOME/Library/Application Support/Claude/claude_desktop_config.json}" ;;
  *)
    FREECAD_PY="${FREECAD_PY:-$(command -v freecad-python || true)}"
    MOD_DIR="${MOD_DIR:-$HOME/.local/share/FreeCAD/v1-1/Mod}"
    CLAUDE_CONFIG="${CLAUDE_CONFIG:-$HOME/.config/Claude/claude_desktop_config.json}" ;;
esac

if [ -z "$FREECAD_PY" ] || [ ! -x "$FREECAD_PY" ]; then
  echo "CADWiz needs FreeCAD 1.1 or newer, and its Python was not found."
  echo "(If FreeCAD is installed somewhere else, run again with FREECAD_PY=/path/to/FreeCAD's/python.)"
  read -r -p "Open FreeCAD's official download page now? [y/N] " answer
  if [[ "$answer" =~ ^[Yy] ]]; then
    (command -v open >/dev/null && open https://www.freecad.org/downloads.php) || xdg-open https://www.freecad.org/downloads.php
  fi
  echo "Nothing was changed. Install FreeCAD 1.1, then run this script again."
  exit 2
fi

ADDON="$SOURCE"
if [ "$SOURCE_ONLY" -eq 0 ]; then
  mkdir -p "$MOD_DIR"
  if [ -e "$MOD_DIR/CADWiz" ]; then
    mv "$MOD_DIR/CADWiz" "$MOD_DIR/CADWiz.backup.$STAMP"
    CHANGED+=("Kept your earlier CADWiz as $MOD_DIR/CADWiz.backup.$STAMP")
  fi
  cp -R "$SOURCE" "$MOD_DIR/CADWiz"
  ADDON="$MOD_DIR/CADWiz"
  CHANGED+=("Installed CADWiz into $ADDON")
fi

"$FREECAD_PY" -m pip install --user --quiet "mcp==1.27.0"
CHANGED+=("Installed mcp 1.27 into FreeCAD's Python ($FREECAD_PY)")

mkdir -p "$(dirname "$CLAUDE_CONFIG")"
if [ -f "$CLAUDE_CONFIG" ]; then
  cp "$CLAUDE_CONFIG" "$CLAUDE_CONFIG.before-cadwiz-$STAMP"
  CHANGED+=("Saved a copy of Claude Desktop's settings as $CLAUDE_CONFIG.before-cadwiz-$STAMP")
fi
"$FREECAD_PY" - "$CLAUDE_CONFIG" "$FREECAD_PY" "$ADDON/src/integrations/cadwiz_plugin/server.py" <<'PY'
import json, sys, pathlib
path, python, server = sys.argv[1:4]
p = pathlib.Path(path)
config = json.loads(p.read_text(encoding="utf-8") or "{}") if p.exists() else {}
config.setdefault("mcpServers", {})["cadwiz"] = {"command": python, "args": [server]}
p.write_text(json.dumps(config, indent=2), encoding="utf-8")
PY
CHANGED+=("Added CADWiz to Claude Desktop's settings ($CLAUDE_CONFIG)")

echo; echo "Done. What this script changed:"
for line in "${CHANGED[@]}"; do echo "  - $line"; done
echo; echo "Next: open FreeCAD, then Claude Desktop. The light on the CADWiz panel turns green within a minute."
