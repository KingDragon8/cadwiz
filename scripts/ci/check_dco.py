# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Developer Certificate of Origin: every commit must be signed off.

    python scripts/ci/check_dco.py <base>..<head>     # e.g. origin/main..HEAD

Each commit's message must carry `Signed-off-by: Name <email>` for the commit's
author (what `git commit -s` adds). Merge commits are skipped. Exits non-zero and
names every commit that is missing it. See CONTRIBUTING.md.
"""
from __future__ import annotations

import re
import subprocess
import sys

SIGNED = re.compile(r"^Signed-off-by: (?P<name>.+) <(?P<email>[^>]+)>\s*$", re.MULTILINE)


def commits(span: str) -> list[tuple[str, str, str, str]]:
    out = subprocess.run(["git", "log", "--no-merges", "--format=%H%x1f%an%x1f%ae%x1f%B%x1e", span],
                         capture_output=True, text=True, check=True).stdout
    found = []
    for record in out.split("\x1e"):
        if record.strip():
            sha, name, email, body = record.strip("\n").split("\x1f", 3)
            found.append((sha, name, email, body))
    return found


def unsigned(span: str) -> list[str]:
    missing = []
    for sha, name, email, body in commits(span):
        signers = {m.group("email").strip().lower() for m in SIGNED.finditer(body)}
        if email.strip().lower() not in signers:
            missing.append(f"{sha[:10]} by {name} <{email}>")
    return missing


def main(argv: list[str]) -> int:
    span = argv[1] if len(argv) > 1 else "HEAD"
    missing = unsigned(span)
    checked = len(commits(span))
    if missing:
        print(f"DCO: {len(missing)} of {checked} commit(s) are not signed off:")
        for line in missing:
            print("  " + line)
        print("Fix: git commit --amend -s (last commit) or git rebase --signoff <base> (several). See CONTRIBUTING.md.")
        return 1
    print(f"DCO: all {checked} commit(s) signed off.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
