#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
set -u
REPO="$(cd "$(dirname "$0")" && pwd)"
bash "$REPO/scripts/install_macos.sh" "$@"
result=$?
printf '\nInstallation command finished (status %s). Verify CADWiz in FreeCAD before considering installation complete.\n' "$result"
read -r -p 'Press Return to close. ' answer
exit "$result"
