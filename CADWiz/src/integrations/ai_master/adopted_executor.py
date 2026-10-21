# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Coarse tools for an EXISTING model (ORDER-2026-10-12-01): the document open in
FreeCAD, a file the founder gives, or a downloaded STL/STEP.

Every change follows the founder's 2026-10-12 rule: the prior state is saved as
a version beside his file BEFORE anything of his is written; every change is a
new version; restore by voice or tap; nothing of his is ever deleted.

How a change reaches the open document: the edit runs in the headless worker
(inside the sandbox) on the latest version file, the result is saved as the next
version file beside his file, copied into his file, and the open document is
reloaded from it (`reload` callback, supplied by the panel). Headless (tests,
the witness script) the "open document" is just the file.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from ai_freecad_core.ai_master.adopted import AdoptedStore, adopted_contract, key_measurements, measured_diff
from ai_freecad_core.ai_master.fact_layer import PrinterProfile, certify, check_contract, finish_report
from ai_freecad_core.ai_master.project_store import Project
from integrations.ai_master.executor import AIMasterExecutor, _facts_from_dict

MESH_OR_FOREIGN = (".stl", ".obj", ".3mf", ".ply", ".step", ".stp", ".iges", ".igs")


class AdoptedExecutor(AIMasterExecutor):
    def __init__(self, project: Project, object_name: str, founder_file: str | Path, *,
                 snapshot_open: Callable[[str], None] | None = None, reload: Callable[[str], None] | None = None,
                 current_view: Callable[[str], str] | None = None, founder_words: str = "", **kwargs: Any) -> None:
        super().__init__(project, object_name, **kwargs)
        source = Path(founder_file)
        self.original_source = source
        if source.suffix.lower() in MESH_OR_FOREIGN:
            # A download is never overwritten: its working copy is an FCStd beside it.
            working = source.with_name(f"{source.stem}.adopted.FCStd")
            self._import_from = source
        else:
            working = source
            self._import_from = None
        self.founder_file = working
        # Keyed by the file itself, not just its name: two files called CoolOff_AI1
        # (his and a copy) must never share a history (found by the plug-in
        # witness, ORDER-2026-10-12-05: a fresh copy picked up a copy's versions).
        import hashlib

        file_key = hashlib.sha256(str(Path(working).resolve()).casefold().encode("utf-8")).hexdigest()[:12]
        self.store = AdoptedStore(self.project.object_folder(object_name) / "adopted" / file_key, working)
        self._snapshot_open = snapshot_open or (lambda dest: shutil.copyfile(str(self.founder_file), dest))
        self._reload = reload or (lambda path: None)
        self._current_view = current_view
        self.founder_words = founder_words
        self.adoption: dict[str, Any] = {}
        self._opening: dict[int, dict[str, Any]] = {}

    @property
    def store(self):  # type: ignore[override]
        return self._adopted_store

    @store.setter
    def store(self, value) -> None:
        self._adopted_store = value

    # ---- adopt ------------------------------------------------------------------
    def adopt(self) -> dict[str, Any]:
        """Read the tree, measure, render, and record an adopted contract. Runs
        once per object per session (and again after an outside change)."""
        source = self._import_from or self.founder_file
        request: dict[str, Any] = {"action": "adopt", "source_path": str(source), "object_name": self.object_name,
                                   "project_dir": str(self.project.folder),
                                   "render_out": str(self.project.object_folder(self.object_name) / "renders" / "adopted.png")}
        if self._import_from is not None and not self.founder_file.exists():
            request["save_as"] = str(self.founder_file)
        result = self._run_worker(request)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or result.get("note") or "could not read the model")
        renders = list(result.get("renders") or [])
        if self._current_view is not None:
            view = self._current_view(str(self.project.object_folder(self.object_name) / "renders" / "founder_view.png"))
            if view:
                renders.insert(0, view)
        self.adoption = {**result, "renders": renders}
        if self.project.contract() is None or self.project.contract().object_name != self.object_name:
            self.project.contracts.save(adopted_contract(self.project.name, self.object_name, self.founder_words, result, str(self.original_source)))
        facts = _facts_from_dict(result["facts"]) if result.get("facts") else None
        if facts is not None:
            finish_report(facts, self.project.contract(), self.printer)
            self._adopted_facts = facts
        self.project.set_active(self.object_name, max(self.store.latest(), 1))
        return {"document": result.get("document"), "kind": result.get("kind"), "objects": result.get("objects"),
                "construction": result.get("construction"),
                "tree": result.get("tree"), "parameters": result.get("parameters"), "bottom_opening": result.get("bottom_opening"),
                "measurements": facts.plain_summary() if facts else "", "editability": facts.editability.display() if facts and facts.editability else "E0",
                "images": renders}

    def _latest_file(self) -> Path:
        current = self.store.current()
        return Path(current.file) if current else (self._import_from or self.founder_file)

    def _ensure_backup(self) -> None:
        if self.store.backed_up_this_session:
            return
        measurements = key_measurements(self.adoption.get("facts"), self.adoption.get("bottom_opening"), self.adoption.get("parameters"))
        if self._import_from is not None and not self.founder_file.exists():
            self.adopt()
        self.store.backup(self._snapshot_open, measurements=measurements,
                          render=(self.adoption.get("renders") or [""])[0])

    def _apply(self, result: dict[str, Any], result_file: Path, note: str) -> dict[str, Any]:
        before = (self.store.current().measurements if self.store.current() else {}) or {}
        after = key_measurements(result.get("facts"), result.get("bottom_opening"), result.get("parameters"))
        diff = measured_diff(before, after)
        renders = result.get("renders") or []
        record = self.store.add_edit(result_file, diff=diff, note=note, measurements=after, render=renders[0] if renders else "")
        self.store.write_founder_file(result_file)
        self._reload(str(self.founder_file))
        facts = _facts_from_dict(result["facts"])
        finish_report(facts, self.project.contract(), self.printer)
        self._facts[record.version] = facts
        self.project.save_facts(self.object_name, record.version, facts.to_dict())
        if result.get("bottom_opening"):
            self._opening[record.version] = result["bottom_opening"]
        self.project.set_active(self.object_name, record.version)
        return {"success": True, "version": record.version, "diff": diff, "measurements": facts.plain_summary(),
                "bottom_opening": result.get("bottom_opening"), "images": renders}

    # ---- the tools ------------------------------------------------------------
    def build(self, source_version: int | None) -> dict[str, Any]:
        """For an existing model, 'build' re-measures the current version."""
        current = self.store.current()
        path = Path(current.file) if current else self._latest_file()
        out = self.project.object_folder(self.object_name) / "renders" / f"adopted_v{current.version if current else 0}.png"
        result = self._run_worker({"action": "adopt", "source_path": str(path), "object_name": self.object_name,
                                   "project_dir": str(self.project.folder), "render_out": str(out), "views": ["iso"]})
        if not result.get("ok"):
            return {"success": False, "error": result.get("error", "could not measure")}
        facts = _facts_from_dict(result["facts"])
        finish_report(facts, self.project.contract(), self.printer)
        version = current.version if current else 0
        self._facts[version] = facts
        self._opening[version] = result.get("bottom_opening") or {}
        return {"success": True, "version": version, "measurements": facts.plain_summary(), "images": result.get("renders") or [],
                "bottom_opening": result.get("bottom_opening")}

    def edit_source(self, patch: dict[str, Any], script: str | None, note: str) -> dict[str, Any]:
        raise RuntimeError("this is an existing model, not a CADWiz design source: use set_parameters for named values or edit_existing for shape changes")

    def section(self, height_mm: float | None, opening: str | None, object_label: str | None) -> dict[str, Any]:
        request: dict[str, Any] = {"action": "section", "source_path": str(self._latest_file()), "object": object_label}
        if opening:
            request["opening"] = opening
        else:
            request["height_mm"] = float(height_mm or 0.0)
        result = self._run_worker(request)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "section failed"))
        return {"object": result.get("object"), **(result.get("result") or {})}

    def set_parameters(self, changes: dict[str, Any], note: str) -> dict[str, Any]:
        self._ensure_backup()
        target = self.store.next_version_file()
        values = {}
        for where, value in changes.items():
            from ai_freecad_core.ai_master.units import parse_quantity

            values[where] = parse_quantity(str(value)).mm if not isinstance(value, (int, float)) else float(value)
        result = self._run_worker({"action": "set_parameters", "source_path": str(self._latest_file()), "changes": values,
                                   "result_path_fcstd": str(target), "object_name": self.object_name, "project_dir": str(self.project.folder),
                                   "contract": self.project.contract().to_dict() if self.project.contract() else None})
        if not result.get("ok"):
            return {"success": False, "error": result.get("error")}
        return self._apply(result, target, note or "; ".join(f"{k} = {v:g} mm" for k, v in values.items()))

    def edit_existing(self, script: str, note: str) -> dict[str, Any]:
        self._ensure_backup()
        target = self.store.next_version_file()
        result = self._run_worker({"action": "edit_existing", "source_path": str(self._latest_file()), "script": script,
                                   "result_path_fcstd": str(target), "object_name": self.object_name, "project_dir": str(self.project.folder),
                                   "render_out": str(self.project.object_folder(self.object_name) / "renders" / f"{target.stem}.png"),
                                   "contract": self.project.contract().to_dict() if self.project.contract() else None})
        if not result.get("ok"):
            return {"success": False, "error": result.get("error"), "error_line": result.get("error_line")}
        return self._apply(result, target, note)

    #: Rebuilding a lofted body from its rings takes about two minutes on the
    #: founder's helmet (measured 2026-10-12); the job gets five.
    RESHAPE_TIME_LIMIT_S = 300.0

    def reshape_rings(self, inner_bottom_circumference_mm: float, note: str) -> dict[str, Any]:
        """Resize a lofted ring body by its rings (ORDER-2026-10-12-04 Part 3.3)."""
        if inner_bottom_circumference_mm <= 0:
            raise ValueError("give the new distance around the inside of the bottom ring, in mm")
        construction = (self.adoption or {}).get("construction") or {}
        if construction and construction.get("kind") not in ("lofted ring body", None):
            raise RuntimeError(f"this model is a {construction.get('kind')}, not a lofted ring body: use edit_existing or set_parameters")
        self._ensure_backup()
        target = self.store.next_version_file()
        result = self._run_worker({"action": "reshape_rings", "source_path": str(self._latest_file()),
                                   "inner_bottom_circumference_mm": float(inner_bottom_circumference_mm),
                                   "result_path_fcstd": str(target), "object_name": self.object_name, "project_dir": str(self.project.folder),
                                   "render_out": str(self.project.object_folder(self.object_name) / "renders" / f"{target.stem}.png"),
                                   "time_limit_s": self.RESHAPE_TIME_LIMIT_S,
                                   "contract": self.project.contract().to_dict() if self.project.contract() else None})
        if not result.get("ok"):
            return {"success": False, "error": result.get("error")}
        applied = self._apply(result, target, note or f"inside bottom ring reshaped to {inner_bottom_circumference_mm:g} mm around")
        return {**applied, "before": result.get("before"), "after": result.get("after"), "reshape": result.get("reshape")}

    def render(self, views: list[str], section: bool) -> dict[str, Any]:
        out = self.project.object_folder(self.object_name) / "renders" / f"adopted_render{'_section' if section else ''}.png"
        result = self._run_worker({"action": "render", "native_path": str(self._latest_file()), "render_out": str(out), "views": views or ["iso"], "section": section})
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "render failed"))
        return {"images": result.get("renders", [])}

    def look_at_file(self, path: str, out: str) -> dict[str, Any]:
        """A picture of any saved copy (a version, or a snapshot of the open model)
        from the standard angle, and its key measurements, in ONE headless worker
        run: the panel's "Compare with now" shows two of these and the measured
        difference between them (ORDER-2026-10-18-01)."""
        result = self._run_worker({"action": "adopt", "source_path": str(path), "object_name": self.object_name,
                                   "project_dir": str(self.project.folder), "render_out": str(out), "views": ["iso"]})
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "could not read that copy"))
        renders = [str(r) for r in result.get("renders") or [] if Path(str(r)).is_file()]
        return {"picture": renders[0] if renders else "",
                "measurements": key_measurements(result.get("facts"), result.get("bottom_opening"), result.get("parameters"))}

    def _current_facts(self):
        current = self.store.current()
        version = current.version if current else 0
        facts = self._facts.get(version) or getattr(self, "_adopted_facts", None)
        if facts is None:
            self.build(None)
            facts = self._facts.get(version)
        return version, facts

    def measure(self, queries: list[str]) -> dict[str, Any]:
        version, facts = self._current_facts()
        opening = self._opening.get(version) or self.adoption.get("bottom_opening")
        return {"version": version, "summary": facts.plain_summary() if facts else "", "facts": facts.to_dict() if facts else {},
                "bottom_opening": opening}

    def check_print(self, printer: str) -> dict[str, Any]:
        _v, facts = self._current_facts()
        return {"printer": self.printer.name, "ready": bool(facts and facts.printer and facts.printer.ready), "notes": facts.printer.notes if facts and facts.printer else []}

    def editability_check(self, verify_living_design: bool) -> dict[str, Any]:
        _v, facts = self._current_facts()
        level = facts.editability if facts else None
        return {"level": level.level.name if level else "E0", "display": level.display() if level else "", "evidence": list(level.evidence) if level else [],
                "living_design_test": "not applicable to an adopted model unless it has named parameters" if verify_living_design else ""}

    def contract_check(self) -> dict[str, Any]:
        contract = self.project.contract()
        _v, facts = self._current_facts()
        if contract is None or facts is None:
            raise RuntimeError("adopt the model first")
        check = check_contract(contract, facts)
        # An adopted contract has no requirements until the master adds them:
        # nothing to certify is reported as such, not as a failure of the model.
        if not contract.objective_requirements():
            return {"status": "ADOPTED (no requirements recorded yet)", "complete": False, "requirements": [],
                    "measurements": facts.plain_summary(), "editability": facts.editability.display() if facts.editability else ""}
        cert = certify(contract, facts)
        return {"status": cert.status if cert.complete else "NOT COMPLETE: " + " | ".join(cert.reasons), "complete": cert.complete,
                "requirements": check.plain_lines(), "measurements": facts.plain_summary(), "editability": facts.editability.display() if facts.editability else ""}

    def versions(self, action: str, version: int | None, note: str) -> dict[str, Any]:
        if action == "list":
            return {"versions": [{"version": v.version, "diff": v.diff, "file": v.file} for v in self.store.list_recent(10)]}
        if version is None:
            raise ValueError(f"{action} needs a version number")
        if action == "branch":
            raise RuntimeError("an existing model has one line of versions: restore the one you want, then change it")
        self._ensure_backup()
        chosen = self.store.get(int(version))
        if chosen is None:
            raise KeyError(f"no version {version}")
        record = self.store.add_restore(int(version), measurements=chosen.measurements, render=chosen.render)
        self.store.write_founder_file(chosen.file)
        self._reload(str(self.founder_file))
        if int(version) in self._facts:
            self._facts[record.version] = self._facts[int(version)]
        if int(version) in self._opening:
            self._opening[record.version] = self._opening[int(version)]
        self.project.set_active(self.object_name, record.version)
        return {"version": record.version, "diff": record.diff, "file": chosen.file}

    def export(self, format: str) -> dict[str, Any]:
        if not self.export_allowed:
            raise PermissionError("exports happen only when the founder asks for a file; he has not asked in this request")
        out_dir = self.project.folder / "exports"
        out_dir.mkdir(exist_ok=True)
        ext = {"stl": ".stl", "3mf": ".3mf", "step": ".step", "fcstd": ".FCStd"}[format.lower().strip(".")]
        current = self.store.current()
        out = out_dir / f"{self.object_name}_v{current.version if current else 0}{ext}"
        result = self._run_worker({"action": "export", "native_path": str(self._latest_file()), "format": format.lower(), "export_path": str(out)})
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "export failed"))
        return {"path": str(out), "bytes": result.get("bytes", 0)}

    def read_file(self, path: str) -> dict[str, Any]:
        return super().read_file(path)

    def current_state(self) -> dict[str, Any]:
        current = self.store.current()
        renders = self.adoption.get("renders") or []
        if current is None:
            return {"version": 0, "diff": "", "render": renders[0] if renders else ""}
        return {"version": current.version, "diff": current.diff, "render": current.render or (renders[0] if renders else "")}

    def facts_for_master(self) -> dict[str, Any]:
        """Beside the founder's words: what this existing model is and measures."""
        current = self.store.current()
        return {"existing_model": {
            "file": str(self.original_source), "working_file": str(self.founder_file),
            "kind": self.adoption.get("kind"), "objects": self.adoption.get("objects"), "tree": self.adoption.get("tree"),
            "construction": self.adoption.get("construction"),
            "named_parameters": self.adoption.get("parameters"), "bottom_opening": self._opening.get(current.version if current else 0) or self.adoption.get("bottom_opening"),
            "editability": ((self.adoption.get("facts") or {}).get("editability") or {}).get("level"),
            "versions": [{"version": v.version, "diff": v.diff} for v in self.store.list_recent(10)],
            "rule": "the founder's file may be edited; CADWiz saves the prior state as a version first, automatically",
        }}
