#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
#
# Protect `main` on the public CADWiz repository: changes only through pull
# requests, the maintainer's review required, no force-push or deletion, and the
# DCO, secrets and test checks must pass. MAINTAINER ONLY -- run once, right after
# the repository is made public (GitHub refuses branch protection on a private
# repository without a paid plan).
#
#   bash scripts/release/branch_protection.sh KingDragon8/cadwiz
set -euo pipefail
REPO="${1:?usage: branch_protection.sh OWNER/REPO}"

gh api --method PUT "repos/${REPO}/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "DCO sign-off",
      "Secrets scan",
      "Lint, imports, tests, connector handshake (ubuntu-latest)",
      "Lint, imports, tests, connector handshake (windows-latest)",
      "FreeCAD loads the addon (no window)"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

echo "main is protected on ${REPO}:"
gh api "repos/${REPO}/branches/main/protection" --jq '{reviews: .required_pull_request_reviews.required_approving_review_count, checks: .required_status_checks.contexts, force_push: .allow_force_pushes.enabled}'
