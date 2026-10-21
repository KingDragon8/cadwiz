# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Existing models: adopt, edit, version (ORDER-2026-10-12-01).

Founder ruling 2026-10-12 replaces "the founder's open documents are never
touched / his files are read-only to the master" with:

    The master may edit the founder's open document and files, but never without
    first saving the prior state as a version. Before the first change in a
    session a full backup is written BESIDE the file (CoolOff_AI1.v1.FCStd) and
    recorded as version 1; every later change is a new version, restorable by
    voice or tap. A founder file is never deleted.

This module is the pure half: where versions live, how they are named, the
rule that no write happens before the backup, the one-line diff between two
measured versions, and the "adopted" Design Contract (what EXISTS, recorded by
CADWiz; the intent stays the master's to add).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .design_contract import DesignContract, Parameter
from .units import Quantity, both

_VERSION_RE = re.compile(r"\.v(\d+)\.FCStd$", re.I)


def sha256_of(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_path(founder_file: str | Path, version: int) -> Path:
    """CoolOff_AI1.FCStd -> CoolOff_AI1.v3.FCStd, beside it."""
    path = Path(founder_file)
    stem = path.stem if path.suffix.lower() == ".fcstd" else path.name.replace(".", "_")
    return path.with_name(f"{stem}.v{version}.FCStd")


@dataclass(slots=True)
class AdoptedVersion:
    version: int
    file: str                      # the version file beside the founder's file
    sha256: str
    diff: str
    note: str = ""
    kind: str = "edit"             # backup | edit | restore
    restored_from: int | None = None
    measurements: dict[str, Any] = field(default_factory=dict)
    render: str = ""
    utc: str = ""
    #: Objects that were in error when this version was saved (ORDER-2026-10-18-01:
    #: the time slider marks such a version red, and it can still be restored).
    #: Empty for a healthy version and for records written before this was kept.
    broken: list[str] = field(default_factory=list)


class AdoptedStore:
    """Versions of one adopted file. Records live in the project; the version
    FILES live beside the founder's file, so he finds them where his work is."""

    def __init__(self, record_folder: str | Path, founder_file: str | Path) -> None:
        self.folder = Path(record_folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.founder_file = Path(founder_file)
        self._session_backed_up = False
        #: Optional `probe(version_file) -> [labels of objects in error]`, set by
        #: whoever has the open document (the Claude plug-in's session); a backup
        #: of a model that was already broken is recorded as broken.
        self.health_probe: Any = None

    # ---- records ----------------------------------------------------------
    def _record_path(self, version: int) -> Path:
        return self.folder / f"adopted.v{version}.json"

    def latest(self) -> int:
        return max((int(p.stem.split(".v")[1]) for p in self.folder.glob("adopted.v*.json")), default=0)

    def get(self, version: int) -> AdoptedVersion | None:
        path = self._record_path(version)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        known = set(AdoptedVersion.__dataclass_fields__)
        return AdoptedVersion(**{k: v for k, v in data.items() if k in known})

    def current(self) -> AdoptedVersion | None:
        latest = self.latest()
        return self.get(latest) if latest else None

    def list_recent(self, limit: int = 10) -> list[AdoptedVersion]:
        latest = self.latest()
        return [v for n in range(max(1, latest - limit + 1), latest + 1) if (v := self.get(n)) is not None]

    def _save(self, record: AdoptedVersion) -> AdoptedVersion:
        record.utc = record.utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._record_path(record.version).write_text(json.dumps(asdict(record), indent=2, default=str), encoding="utf-8")
        return record

    def next_version_file(self) -> Path:
        """The file the next version will be written to. Never an existing file."""
        n = self.latest() + 1
        candidate = version_path(self.founder_file, n)
        while candidate.exists():                 # a version file from an earlier history: never overwritten
            n += 1
            candidate = version_path(self.founder_file, n)
        return candidate

    # ---- the rule: back up before the first change ------------------------
    @property
    def backed_up_this_session(self) -> bool:
        return self._session_backed_up

    def backup(self, snapshot_to: Any, *, note: str = "", measurements: dict[str, Any] | None = None, render: str = "",
               broken: list[str] | None = None) -> AdoptedVersion:
        """Save the prior state as a version. `snapshot_to(dest_path)` writes the
        current state of the open document (in memory, unsaved changes included)
        to `dest_path`; for a file nobody has open it is a plain copy."""
        target = self.next_version_file()
        snapshot_to(str(target))
        if not target.exists():
            raise RuntimeError(f"the backup was not written: {target}")
        if broken is None and self.health_probe is not None:
            try:
                broken = [str(label) for label in self.health_probe(str(target)) or []]
            except Exception:  # noqa: BLE001 - a failed health look never costs him the backup itself
                broken = []
        record = AdoptedVersion(version=int(_VERSION_RE.search(target.name).group(1)), file=str(target), sha256=sha256_of(target),
                                diff="backup of the model as it was before any change" if self.latest() == 0 else "your model as it stood before this change",
                                note=note or "backup", kind="backup", measurements=measurements or {}, render=render,
                                broken=list(broken or []))
        self._session_backed_up = True
        return self._save(record)

    def require_backup(self) -> None:
        """Called before ANY write to the founder's file. Refuses otherwise."""
        if not self._session_backed_up or self.current() is None:
            raise PermissionError("the prior state has not been saved as a version yet; nothing of the founder's is written before that")

    def add_edit(self, result_file: str | Path, *, diff: str, note: str, measurements: dict[str, Any], render: str = "") -> AdoptedVersion:
        path = Path(result_file)
        n = int(_VERSION_RE.search(path.name).group(1))
        return self._save(AdoptedVersion(version=n, file=str(path), sha256=sha256_of(path), diff=diff, note=note, kind="edit",
                                         measurements=measurements, render=render))

    def add_restore(self, version: int, measurements: dict[str, Any], render: str = "") -> AdoptedVersion:
        chosen = self.get(version)
        if chosen is None:
            raise KeyError(f"no version {version}")
        n = self.latest() + 1
        return self._save(AdoptedVersion(version=n, file=chosen.file, sha256=chosen.sha256, diff=f"restored version {version} exactly",
                                         note=f"restored from version {version}", kind="restore", restored_from=version,
                                         measurements=measurements or chosen.measurements, render=render or chosen.render,
                                         broken=list(chosen.broken)))

    def write_founder_file(self, from_file: str | Path) -> None:
        """Put a version's content in the founder's file. Only after the backup;
        never deletes anything (the old content is already a version)."""
        self.require_backup()
        shutil.copyfile(str(from_file), str(self.founder_file))


# ---- the one-line diff between two measured versions ---------------------------

_DIFF_KEYS = (
    ("opening_inside_width_mm", "bottom opening inside width"),
    ("opening_inside_depth_mm", "bottom opening inside depth"),
    ("opening_perimeter_mm", "bottom opening distance around"),
    ("width_mm", "overall width"),
    ("depth_mm", "overall depth"),
    ("height_mm", "overall height"),
    ("min_wall_mm", "wall"),
    ("bottom_ports", "small openings in the bottom"),
    ("hole_count", "holes"),
)

#: The one-line diff keeps the biggest few changes; the rest are in the version record.
_DIFF_MAX_ITEMS = 4


def key_measurements(facts: dict[str, Any] | None, opening: dict[str, Any] | None = None, parameters: list[dict] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if facts:
        bbox = facts.get("bbox_mm")
        if bbox:
            out.update(width_mm=round(bbox[0], 2), depth_mm=round(bbox[1], 2), height_mm=round(bbox[2], 2))
        if facts.get("min_wall_mm") is not None:
            out["min_wall_mm"] = round(float(facts["min_wall_mm"]), 2)
        out["hole_count"] = len(facts.get("holes") or [])
        if facts.get("volume_mm3") is not None:
            out["volume_mm3"] = round(float(facts["volume_mm3"]), 1)
    inside = (opening or {}).get("inside") or {}
    if opening and "small_openings" in opening:
        # Counted from the section (geometry), not from face types: a scale or a
        # boolean can turn a round port into a spline face and fool a face count.
        out["bottom_ports"] = len(opening.get("small_openings") or [])
        out.pop("hole_count", None)
    if inside:
        out.update(opening_inside_width_mm=inside.get("width_mm"), opening_inside_depth_mm=inside.get("depth_mm"),
                   opening_perimeter_mm=inside.get("perimeter_mm"))
    for p in parameters or []:
        out[f"param:{p['name']}"] = p.get("value")
    return out


def measured_diff(old: dict[str, Any], new: dict[str, Any], tolerance: float = 0.01) -> str:
    changes: list[str] = []
    for key, label in _DIFF_KEYS:
        a, b = old.get(key), new.get(key)
        if a is None or b is None or abs(float(a) - float(b)) <= tolerance:
            continue
        if key in ("hole_count", "bottom_ports"):
            changes.append(f"{label}: {int(a)} → {int(b)}")
        else:
            changes.append(f"{label}: {both(float(a))} → {both(float(b))}")
    for key in sorted(k for k in new if k.startswith("param:")):
        a, b = old.get(key), new.get(key)
        if a is not None and b is not None and abs(float(a) - float(b)) > tolerance:
            changes.append(f"{key[6:]}: {float(a):g} → {float(b):g}")
    if not changes:
        return "no measurable change"
    shown = changes[:_DIFF_MAX_ITEMS]
    return "; ".join(shown) + (f" (+{len(changes) - _DIFF_MAX_ITEMS} more)" if len(changes) > _DIFF_MAX_ITEMS else "")


def adopted_contract(project: str, object_name: str, founder_words: str, adoption: dict[str, Any], founder_file: str) -> DesignContract:
    """What EXISTS, recorded by CADWiz from the model itself. No intent is
    invented: the founder's words are kept verbatim and the master adds its own
    summary and requirements later."""
    params: dict[str, Parameter] = {}
    for p in adoption.get("parameters") or []:
        if p.get("unit") == "mm" and isinstance(p.get("value"), (int, float)):
            name = re.sub(r"[^A-Za-z0-9_]+", "_", str(p["name"])).strip("_")[:60] or "parameter"
            params[name] = Parameter(name, Quantity(float(p["value"]), "mm"), str(p["name"]))
    editability = ((adoption.get("facts") or {}).get("editability") or {}).get("level", "E0")
    return DesignContract(
        project=project, object_name=object_name, intent_founder_words=founder_words,
        master_summary="",
        parameters=params,
        features=[f"{row.get('label')} ({row.get('type')})" for row in adoption.get("tree") or []][:40],
        relationships=[],
        requirements=[],
        editability_commitments=list(params)[:20],
        build_path="mechanical" if editability in ("E2", "E3", "E4") else "organic",
        assumptions=[f"adopted from {Path(founder_file).name} as it stands; detected editability {editability}"],
        authored_by="adopted (recorded by CADWiz from the model; intent is the master's to add)",
    )
