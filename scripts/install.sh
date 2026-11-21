#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Install only the workbench. Network, pip and assistant settings are not used.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fail() { printf 'CADWiz: %s\n' "$*" >&2; exit 2; }
if [ "${1:-}" = --source ]; then
  fail '--source no longer modifies assistant settings. Use AI Wiz Setup after installing the workbench.'
fi
if [ -n "${MOD_DIR:-}" ]; then
  fail 'MOD_DIR overrides are not trusted. Select FreeCAD using FREECAD_APP or FREECAD_PY; its runtime supplies the data directory.'
fi
if [ -n "${FREECAD_PY:-}" ]; then
  [ -x "$FREECAD_PY" ] || fail 'FREECAD_PY is not executable.'
  selected="$FREECAD_PY"
else
  matches=()
  case "$(uname -s)" in
    Darwin)
      apps=()
      if [ -n "${FREECAD_APP:-}" ]; then
        apps+=("$FREECAD_APP")
      else
        while IFS= read -r app; do apps+=("$app"); done < <(
          find /Applications "$HOME/Applications" -type d -name '*.app' -prune -iname '*freecad*.app' -print 2>/dev/null || true)
      fi
      for app in "${apps[@]}"; do
        for candidate in "$app/Contents/Resources/bin/python" "$app/Contents/Resources/bin/python3" "$app/Contents/bin/python3" "$app/Contents/MacOS/python"; do
          if [ -x "$candidate" ] && "$candidate" -c 'import FreeCAD; assert tuple(map(int, FreeCAD.Version()[:2])) >= (1,1); assert FreeCAD.getUserAppDataDir()' >/dev/null 2>&1; then
            matches+=("$candidate")
            break
          fi
        done
      done
      ;;
    Linux)
      for name in freecad-python python3; do
        candidate="$(command -v "$name" || true)"
        if [ -n "$candidate" ] && "$candidate" -c 'import FreeCAD; assert tuple(map(int, FreeCAD.Version()[:2])) >= (1,1)' >/dev/null 2>&1; then
          matches+=("$candidate")
          break
        fi
      done
      ;;
    *) fail 'Use the Windows Setup.exe on Windows.' ;;
  esac
  [ "${#matches[@]}" -eq 1 ] || fail 'Could not choose one FreeCAD 1.1 runtime. Select a custom installation with FREECAD_APP=/path/FreeCAD.app or FREECAD_PY=/path/to/its/python. No installation was changed.'
  selected="${matches[0]}"
fi
exec "$selected" "$REPO/CADWiz/src/integrations/cadwiz_plugin/installation.py" --source "$REPO/CADWiz" "$@"
