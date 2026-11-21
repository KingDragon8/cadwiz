#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
set -eu
REPO="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${FREECAD_PY:-python3}"
"$PYTHON" "$REPO/CADWiz/src/integrations/cadwiz_plugin/doctor.py" "$@"
echo "Read-only checks complete. Startup and the assistant connection need separate verification."
read -r -p "Press Return to close. " answer
