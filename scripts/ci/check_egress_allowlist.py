# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Fail when shipped code gains an outbound network call that is not allowlisted.

CADWiz's design promise is that a user's models, geometry, design intent and
the product's own algorithms stay on their machine. That promise is only worth
anything if it is enforced: a policy document does not stop someone adding a
`urlopen` next month.

This scans the shipped source tree for network egress and compares what it finds
against `config/egress_allowlist.toml`. Anything not listed fails the build.

    python scripts/check_egress_allowlist.py

Deliberately conservative: it flags the *capability* to make a network call, not
proof that one happens at runtime. A false positive costs one allowlist entry
with a written justification, which is exactly the review this is meant to force.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (ROOT / "CADWiz" / "src",)
ALLOWLIST = ROOT / "config" / "egress_allowlist.toml"

#: Callables that can open a network connection.
_NETWORK_CALLS = frozenset(
    {
        "urlopen",
        "urlretrieve",
        "socket",
        "create_connection",
        "HTTPConnection",
        "HTTPSConnection",
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "head",
        "request",
    }
)

#: Modules whose mere import indicates network capability.
_NETWORK_MODULES = frozenset(
    {"requests", "httpx", "aiohttp", "urllib3", "websockets", "ftplib", "smtplib"}
)

#: `get`/`post` and friends are ordinary words. Only treat them as egress when
#: they are attributes of something that looks like an HTTP client.
_HTTP_CLIENT_HINTS = frozenset({"requests", "httpx", "session", "client", "aiohttp"})


class _Scanner(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[tuple[int, str]] = []
        self._network_names: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _NETWORK_MODULES:
                self.findings.append((node.lineno, f"import {alias.name}"))
                self._network_names.add(alias.asname or root)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        root = module.split(".")[0]
        for alias in node.names:
            if root in _NETWORK_MODULES:
                self.findings.append((node.lineno, f"from {module} import {alias.name}"))
            elif alias.name in _NETWORK_CALLS and module.startswith(
                ("urllib", "http", "socket")
            ):
                # The import itself is the capability. Recording it only on a
                # direct call missed `opener: Callable = urlopen`, where the
                # function is handed on as a default argument and invoked
                # through another name entirely.
                self._network_names.add(alias.asname or alias.name)
                self.findings.append(
                    (node.lineno, f"from {module} import {alias.name}")
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = self._callable_name(node.func)
        if name is not None:
            self.findings.append((node.lineno, f"{name}(...)"))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Catch network callables handed to another function instead of called directly."""
        if node.attr in {"urlopen", "urlretrieve", "create_connection"}:
            parts: list[str] = []
            owner: ast.expr = node.value
            while isinstance(owner, ast.Attribute):
                parts.append(owner.attr)
                owner = owner.value
            if isinstance(owner, ast.Name):
                parts.append(owner.id)
            qualified = ".".join(reversed(parts))
            if qualified.startswith(("urllib", "socket")):
                finding = (node.lineno, f"{qualified}.{node.attr}")
                if finding not in self.findings:
                    self.findings.append(finding)
        self.generic_visit(node)

    def _callable_name(self, func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            if func.id in self._network_names and func.id in _NETWORK_CALLS:
                return func.id
            return None
        if isinstance(func, ast.Attribute):
            if func.attr not in _NETWORK_CALLS:
                return None
            owner = func.value
            owner_name = (
                owner.id
                if isinstance(owner, ast.Name)
                else owner.attr
                if isinstance(owner, ast.Attribute)
                else ""
            )
            lowered = owner_name.casefold()
            if func.attr in {"urlopen", "urlretrieve", "create_connection"}:
                return f"{owner_name}.{func.attr}"
            if any(hint in lowered for hint in _HTTP_CLIENT_HINTS):
                return f"{owner_name}.{func.attr}"
            return None
        return None


def _load_allowlist() -> dict[str, dict[str, object]]:
    if not ALLOWLIST.is_file():
        return {}
    payload = tomllib.loads(ALLOWLIST.read_text(encoding="utf-8"))
    return {
        str(entry["path"]): entry for entry in payload.get("allowed", []) if "path" in entry
    }


def main() -> int:
    allowed = _load_allowlist()
    scanned = 0
    offenders: list[str] = []
    seen_paths: set[str] = set()

    for source in SOURCES:
        for path in sorted(source.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            scanned += 1
            scanner = _Scanner(path)
            scanner.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
            if not scanner.findings:
                continue
            relative = path.relative_to(ROOT).as_posix()
            seen_paths.add(relative)
            if relative in allowed:
                continue
            for line, what in scanner.findings:
                offenders.append(f"{relative}:{line}  {what}")

    stale = sorted(set(allowed) - seen_paths)

    print(f"Scanned {scanned} shipped source files.")
    print(f"Allowlisted egress points: {len(allowed)}")
    if stale:
        print("\nAllowlist entries that no longer make any network call:")
        for item in stale:
            print(f"  {item}")
        print("  (remove them - an allowlist that drifts stops being a control)")
    if offenders:
        print(f"\nEGRESS NOT ALLOWLISTED - {len(offenders)} finding(s):\n")
        for item in offenders:
            print(f"  {item}")
        print(
            "\nCADWiz keeps user models, design intent and its own algorithms on "
            "the user's machine.\nIf this call is genuinely required, add it to "
            f"{ALLOWLIST.relative_to(ROOT).as_posix()} with a written justification."
        )
        return 1
    print("\nNo unapproved network egress in shipped code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
