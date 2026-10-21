# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The persistent design source and its versions (Phase 1.2, addendum 2 and 3).

Each project object holds ONE design source: named parameters (with units),
semantic features, and the construction script that builds the part from those
parameters. The master edits it INCREMENTALLY -- `apply_patch` changes
`hole_2_y` from 23 to 26 and nothing else -- never by regenerating the model for
a small change. Every version stores its parameter values with units, and the
one-line diff between versions is what the VCS shows ("base diameter 2 in -> 4 in;
wall: solid -> 1.6 mm"). Renders, measurements and the native FreeCAD result are
stored beside each version and linked to it.

The script is plain FreeCAD Python. It reads its parameters from a dict `P`
(millimetres, what FreeCAD wants) and `P_UNITS` (the founder's units, for
labels); CADWiz prepends both when it renders the script for a build, so the
master never hard-codes a number that a parameter owns.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .units import Quantity, fmt_num

#: Parameter values a patch may set: a dimension, or a plain word/flag for
#: non-dimensional choices ("open", "closed", True).
ParamValue = Quantity | str | bool | int | float


def _label(name: str) -> str:
    return name.replace("_", " ")


def _show(value: ParamValue | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, Quantity):
        return value.native()
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return fmt_num(float(value), 3)
    return str(value)


def _value_to_dict(value: ParamValue) -> dict[str, Any]:
    if isinstance(value, Quantity):
        return {"kind": "quantity", **value.to_dict()}
    return {"kind": "plain", "value": value}


def _value_from_dict(data: dict[str, Any]) -> ParamValue:
    if data.get("kind") == "quantity":
        return Quantity.from_dict(data)
    return data["value"]


@dataclass(slots=True)
class DesignSource:
    object_name: str
    parameters: dict[str, ParamValue] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    script: str = ""
    build_path: str = "mechanical"
    version: int = 1
    parent_version: int | None = None
    note: str = ""
    created_utc: str = ""

    def render_script(self) -> str:
        """The script with its parameters bound: `P` in millimetres, `P_UNITS` as
        the founder gave them, `P_RAW` for non-dimensional choices."""
        mm = {k: round(v.mm, 6) for k, v in self.parameters.items() if isinstance(v, Quantity)}
        units = {k: v.native() for k, v in self.parameters.items() if isinstance(v, Quantity)}
        raw = {k: v for k, v in self.parameters.items() if not isinstance(v, Quantity)}
        header = (
            f"# CADWiz design source: {self.object_name} version {self.version}\n"
            f"P = {json.dumps(mm)}\n"
            f"P_UNITS = {json.dumps(units)}\n"
            f"P_RAW = {json.dumps(raw)}\n"
        )
        return header + self.script

    def apply_patch(self, patch: dict[str, ParamValue], *, note: str = "", script: str | None = None) -> "DesignSource":
        """An incremental change: the named parameters take their new values,
        everything else is kept. `script` is given only when the master really
        has to change the construction (a new feature), never for a value change."""
        unknown = [k for k in patch if k not in self.parameters and script is None and not k.startswith("+")]
        params = dict(self.parameters)
        for key, value in patch.items():
            params[key.lstrip("+")] = value
        return DesignSource(
            object_name=self.object_name, parameters=params, features=list(self.features),
            script=self.script if script is None else script, build_path=self.build_path,
            version=self.version + 1, parent_version=self.version,
            note=note or ("; ".join(f"{_label(k.lstrip('+'))} -> {_show(v)}" for k, v in patch.items()) + (f" (new parameters: {', '.join(unknown)})" if unknown else "")),
            created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    def parameter_values_line(self) -> str:
        """Addendum 3/5: every parameter with its unit, both systems for dimensions."""
        parts = []
        for key, value in self.parameters.items():
            parts.append(f"{_label(key)} {value.display() if isinstance(value, Quantity) else _show(value)}")
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_name": self.object_name,
            "parameters": {k: _value_to_dict(v) for k, v in self.parameters.items()},
            "features": list(self.features), "script": self.script, "build_path": self.build_path,
            "version": self.version, "parent_version": self.parent_version, "note": self.note, "created_utc": self.created_utc,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesignSource":
        return cls(
            object_name=str(data["object_name"]),
            parameters={k: _value_from_dict(v) for k, v in data.get("parameters", {}).items()},
            features=list(data.get("features", [])), script=str(data.get("script", "")),
            build_path=str(data.get("build_path", "mechanical")), version=int(data.get("version", 1)),
            parent_version=data.get("parent_version"), note=str(data.get("note", "")), created_utc=str(data.get("created_utc", "")),
        )


def diff_line(old: DesignSource | None, new: DesignSource) -> str:
    """Addendum 3: 'base diameter 2 in -> 4 in; wall: solid -> 1.6 mm'. A parameter
    that appears for the first time reads from its absence ('solid' for a wall,
    a dash otherwise); one removed reads to its absence."""
    if old is None:
        return "first version: " + "; ".join(f"{_label(k)} {_show(v)}" for k, v in new.parameters.items())
    changes: list[str] = []
    for key in sorted(set(old.parameters) | set(new.parameters), key=lambda k: (k not in old.parameters, k)):
        before, after = old.parameters.get(key), new.parameters.get(key)
        if before == after:
            continue
        before_text = _show(before) if before is not None else ("solid" if "wall" in key else "—")
        after_text = _show(after) if after is not None else ("solid" if "wall" in key else "—")
        changes.append(f"{_label(key)}: {before_text} → {after_text}")
    if old.script != new.script:
        changes.append("construction changed")
    return "; ".join(changes) if changes else "no change"


@dataclass(slots=True)
class VersionRecord:
    version: int
    source: DesignSource
    diff: str
    render_path: str = ""      # thumbnail / render beside the version
    facts_path: str = ""       # the fact report for this version
    native_path: str = ""      # the FreeCAD result (.FCStd) this version produced
    contract_version: int = 0
    restored_from: int | None = None
    branched_from: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "source": self.source.to_dict(), "diff": self.diff, "render_path": self.render_path,
            "facts_path": self.facts_path, "native_path": self.native_path, "contract_version": self.contract_version,
            "restored_from": self.restored_from, "branched_from": self.branched_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VersionRecord":
        return cls(
            version=int(data["version"]), source=DesignSource.from_dict(data["source"]), diff=str(data.get("diff", "")),
            render_path=str(data.get("render_path", "")), facts_path=str(data.get("facts_path", "")),
            native_path=str(data.get("native_path", "")), contract_version=int(data.get("contract_version", 0)),
            restored_from=data.get("restored_from"), branched_from=data.get("branched_from"),
        )


class VersionStore:
    """Every version of one object's design source, with what it produced. Restoring
    or branching never rewrites history: it adds a new version whose content is the
    chosen one (addendum 2)."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def _path(self, version: int) -> Path:
        return self.folder / f"v{version}.json"

    def latest_version(self) -> int:
        return max((int(p.stem[1:]) for p in self.folder.glob("v*.json")), default=0)

    def get(self, version: int) -> VersionRecord | None:
        path = self._path(version)
        return VersionRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def current(self) -> VersionRecord | None:
        latest = self.latest_version()
        return self.get(latest) if latest else None

    def add(self, source: DesignSource, *, render_path: str = "", facts_path: str = "", native_path: str = "",
            contract_version: int = 0, restored_from: int | None = None, branched_from: int | None = None) -> VersionRecord:
        previous = self.current()
        source.version = self.latest_version() + 1
        if source.parent_version is None and previous is not None:
            source.parent_version = previous.version
        if not source.created_utc:
            source.created_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record = VersionRecord(
            version=source.version, source=source, diff=diff_line(previous.source if previous else None, source),
            render_path=render_path, facts_path=facts_path, native_path=native_path, contract_version=contract_version,
            restored_from=restored_from, branched_from=branched_from,
        )
        if restored_from is not None:
            record.diff = f"restored version {restored_from} exactly" + (f" ({record.diff})" if record.diff != "no change" else "")
        self._path(record.version).write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
        return record

    def attach(self, version: int, *, render_path: str | None = None, facts_path: str | None = None, native_path: str | None = None) -> VersionRecord:
        record = self.get(version)
        if record is None:
            raise KeyError(f"no version {version}")
        if render_path is not None:
            record.render_path = render_path
        if facts_path is not None:
            record.facts_path = facts_path
        if native_path is not None:
            record.native_path = native_path
        self._path(version).write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
        return record

    def list_recent(self, limit: int = 10) -> list[VersionRecord]:
        """The strip on the VCS: the last `limit` versions, oldest first."""
        latest = self.latest_version()
        return [r for v in range(max(1, latest - limit + 1), latest + 1) if (r := self.get(v)) is not None]

    def restore(self, version: int) -> VersionRecord:
        """'Go back to version 1': a new version with exactly version 1's source."""
        chosen = self.get(version)
        if chosen is None:
            raise KeyError(f"no version {version}")
        copy = DesignSource.from_dict(chosen.source.to_dict())
        copy.parent_version = self.latest_version()
        copy.note = f"restored from version {version}"
        copy.created_utc = ""
        return self.add(copy, restored_from=version, contract_version=chosen.contract_version)

    def branch(self, version: int, note: str = "") -> VersionRecord:
        chosen = self.get(version)
        if chosen is None:
            raise KeyError(f"no version {version}")
        copy = DesignSource.from_dict(chosen.source.to_dict())
        copy.parent_version = version
        copy.note = note or f"branched from version {version}"
        copy.created_utc = ""
        return self.add(copy, branched_from=version, contract_version=chosen.contract_version)


_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
             "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def parse_version_reference(spoken: str, latest: int) -> int | None:
    """Addendum 2, by voice: 'version 2', 'the first one', 'go back to version 1',
    'the previous one', 'the last one'. None when the words do not name a version."""
    text = " ".join(spoken.casefold().replace("’", "'").split())
    import re  # noqa: PLC0415

    m = re.search(r"\bversion\s+(\d+)\b", text)
    if m:
        return int(m.group(1))
    m = re.search(r"\bversion\s+([a-z]+)\b", text)
    if m and m.group(1) in _ORDINALS:
        return _ORDINALS[m.group(1)]
    m = re.search(r"\bthe\s+([a-z]+)\s+(one|version)\b", text)
    if m:
        word = m.group(1)
        if word in _ORDINALS:
            return _ORDINALS[word]
        if word in ("previous", "earlier", "last"):
            return max(1, latest - 1) if word != "last" or "go back" in text else latest
        if word == "latest":
            return latest
    return None
