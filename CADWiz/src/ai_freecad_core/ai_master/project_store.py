# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""One folder per project: the Design Contract, every design-source version with
its render, facts and native result beside it, and the founder's own files
listed READ-ONLY (Phase 1.2, hard safety envelope).

    <root>/<project>/
        contract.json, contract.v1.json, ...
        objects/<object>/versions/v1.json, v2.json, ...
        objects/<object>/renders/v1.png, ...
        objects/<object>/facts/v1.json, ...
        objects/<object>/native/v1.FCStd, ...
        founder_files.json          -- paths the founder provided; never written to
        sources.json                -- downloaded models: URL + licence (addendum 6)
        active.json                 -- "Working on: <object>, version N" (addendum 1)
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .design_contract import ContractStore, DesignContract
from .design_source import VersionRecord, VersionStore


def default_projects_root() -> Path:
    override = os.environ.get("CADWIZ_PROJECTS_ROOT", "").strip()
    return Path(override) if override else Path.home() / "CADWiz Projects"


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_. -]+", "_", (name or "").strip()).strip(" ._")
    return cleaned or "Untitled"


@dataclass(frozen=True, slots=True)
class DownloadRecord:
    """Addendum 6: a downloaded model's provenance, shown on the VCS."""

    object_name: str
    source_url: str
    license: str
    title: str = ""
    author: str = ""
    editability: str = "E0"

    def plain(self) -> str:
        who = f" by {self.author}" if self.author else ""
        return f"{self.title or self.object_name}{who} — from {self.source_url} — licence: {self.license or 'not stated'} — editability {self.editability} (mesh)"


class Project:
    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.contracts = ContractStore(self.folder)

    @property
    def name(self) -> str:
        return self.folder.name

    @classmethod
    def open(cls, name: str, root: str | Path | None = None) -> "Project":
        return cls(Path(root or default_projects_root()) / safe_name(name))

    # ---- objects and versions --------------------------------------------
    def object_folder(self, object_name: str) -> Path:
        folder = self.folder / "objects" / safe_name(object_name)
        for sub in ("versions", "renders", "facts", "native"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        return folder

    def versions(self, object_name: str) -> VersionStore:
        return VersionStore(self.object_folder(object_name) / "versions")

    def render_path(self, object_name: str, version: int) -> Path:
        return self.object_folder(object_name) / "renders" / f"v{version}.png"

    def facts_path(self, object_name: str, version: int) -> Path:
        return self.object_folder(object_name) / "facts" / f"v{version}.json"

    def native_path(self, object_name: str, version: int) -> Path:
        return self.object_folder(object_name) / "native" / f"v{version}.FCStd"

    def save_facts(self, object_name: str, version: int, facts: dict[str, Any]) -> Path:
        path = self.facts_path(object_name, version)
        path.write_text(json.dumps(facts, indent=2, default=str), encoding="utf-8")
        return path

    def objects(self) -> list[str]:
        root = self.folder / "objects"
        return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []

    # ---- the active object (addendum 1) ------------------------------------
    def set_active(self, object_name: str, version: int) -> None:
        (self.folder / "active.json").write_text(json.dumps({"object": object_name, "version": version, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}), encoding="utf-8")

    def active(self) -> tuple[str, int] | None:
        path = self.folder / "active.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data["object"]), int(data["version"])

    def working_on_line(self) -> str:
        current = self.active()
        if current is None:
            return "Working on: nothing yet"
        return f"Working on: {current[0]}, version {current[1]}"

    # ---- the founder's files: read-only ------------------------------------
    def register_founder_file(self, path: str | Path) -> None:
        record = self.founder_files()
        resolved = str(Path(path).resolve())
        if resolved not in record:
            record.append(resolved)
            (self.folder / "founder_files.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    def founder_files(self) -> list[str]:
        path = self.folder / "founder_files.json"
        return list(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else []

    def is_founder_file(self, path: str | Path) -> bool:
        try:
            resolved = str(Path(path).resolve())
        except OSError:
            return False
        return resolved in self.founder_files()

    def guard_write(self, path: str | Path) -> None:
        """Raise before anything of the founder's is written. New versions go beside."""
        if self.is_founder_file(path):
            raise PermissionError(f"the founder's file is read-only: {path}")

    # ---- downloads (addendum 6) -------------------------------------------
    def record_download(self, record: DownloadRecord) -> None:
        path = self.folder / "sources.json"
        rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        rows.append(asdict(record))
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    def downloads(self) -> list[DownloadRecord]:
        path = self.folder / "sources.json"
        return [DownloadRecord(**row) for row in json.loads(path.read_text(encoding="utf-8"))] if path.exists() else []

    # ---- convenience --------------------------------------------------------
    def contract(self) -> DesignContract | None:
        return self.contracts.load()

    def current_version(self, object_name: str) -> VersionRecord | None:
        return self.versions(object_name).current()
