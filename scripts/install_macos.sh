#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# PR #7's workbench-only staging approach; backups now stay outside Mod.
set -euo pipefail
[ "$(uname -s)" = Darwin ] || { echo 'This installer is for macOS only.' >&2; exit 1; }
exec bash "$(cd "$(dirname "$0")" && pwd)/install.sh" "$@"
