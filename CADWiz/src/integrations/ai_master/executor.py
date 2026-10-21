# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The coarse tools, executed (ORDER-2026-10-11-03 Phase 2.3).

Every build, render, E4 test and export runs in the headless worker
(`worker.py`) in a separate `freecadcmd.exe`, inside the hard safety envelope:
the sandbox in the worker, a 2 GB Job Object memory cap and a time ceiling on
the process, and file access only inside the project folder. The founder's own
files are read-only; new versions are written beside them. While the worker
runs, the window keeps answering and hears Cancel (the same pump the window-lock
fix uses), when the panel has installed it.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ai_freecad_core.ai_master.design_contract import DesignContract
from ai_freecad_core.ai_master.design_source import DesignSource, VersionStore
from ai_freecad_core.ai_master.fact_layer import FactReport, PrinterProfile, certify, check_contract
from ai_freecad_core.ai_master.project_store import Project
from ai_freecad_core.ai_master.units import Quantity, UnitError, parse_quantity
from integrations.mcp_tools.cadwiz_sandbox import DEFAULT_MEMORY_LIMIT_BYTES, DEFAULT_TIME_LIMIT_SECONDS

WORKER = Path(__file__).resolve().with_name("worker.py")
_FALLBACK_FREECADCMD = Path(r"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe")
_EXPORT_EXT = {"stl": ".stl", "3mf": ".3mf", "step": ".step", "fcstd": ".FCStd"}


def find_freecadcmd() -> Path:
    sibling = Path(sys.executable).resolve().with_name("freecadcmd.exe")
    return sibling if sibling.exists() else _FALLBACK_FREECADCMD


class WorkerFailed(RuntimeError):
    pass


def _facts_from_dict(data: dict[str, Any]) -> FactReport:
    """Rebuild a FactReport from the worker's JSON (editability and printer
    are recomputed by `finish_report` from the raw fields)."""
    keep = {k: data[k] for k in (
        "object_name", "bbox_mm", "volume_mm3", "area_mm2", "solid_count", "valid_solid", "mesh_only", "holes", "min_wall_mm",
        "min_wall_is_estimate", "hollow", "clearances_mm", "feature_tree", "parameter_names", "file_integrity_ok", "living_design_verified", "notes",
    ) if k in data}
    if keep.get("bbox_mm") is not None:
        keep["bbox_mm"] = tuple(keep["bbox_mm"])
    keep["collisions"] = [tuple(c) for c in data.get("collisions", [])]
    return FactReport(**keep)


def _to_value(value: Any) -> Any:
    """'4 in' -> Quantity; {'value': 4, 'unit': 'in'} -> Quantity; words and flags stay."""
    if isinstance(value, Quantity):
        return value
    if isinstance(value, dict) and "value" in value:
        return Quantity(float(value["value"]), str(value.get("unit", "mm")))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Quantity(float(value), "mm")
    if isinstance(value, str):
        try:
            return parse_quantity(value)
        except UnitError:
            return value
    return value


def run_worker_job(request: dict[str, Any], *, project_dir: str, pump: Callable[[], None] | None = None,
                   freecadcmd: Path | None = None, time_limit_s: float = DEFAULT_TIME_LIMIT_SECONDS,
                   memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES) -> dict[str, Any]:
    """One headless worker job outside any project (the panel's measurement
    answers use this). Same envelope as the executor's builds."""
    holder = AIMasterExecutor.__new__(AIMasterExecutor)
    holder.project = type("P", (), {"folder": Path(project_dir)})()
    holder._pump = pump
    holder.freecadcmd = freecadcmd or find_freecadcmd()
    holder.time_limit_s = time_limit_s
    holder.memory_limit_bytes = memory_limit_bytes
    return AIMasterExecutor._run_worker(holder, request)


class AIMasterExecutor:
    def __init__(self, project: Project, object_name: str, *, printer: PrinterProfile | None = None,
                 pump: Callable[[], None] | None = None, show: Callable[[dict[str, Any]], None] | None = None,
                 find_examples: Callable[[str], dict[str, Any]] | None = None, freecadcmd: Path | None = None,
                 time_limit_s: float = DEFAULT_TIME_LIMIT_SECONDS, memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES) -> None:
        self.project = project
        self.object_name = object_name
        self.printer = printer or PrinterProfile()
        self._pump = pump
        self._show = show
        self._find_examples = find_examples
        self.freecadcmd = freecadcmd or find_freecadcmd()
        self.time_limit_s = time_limit_s
        self.memory_limit_bytes = memory_limit_bytes
        self.export_allowed = False            # set per turn: only on the founder's request
        #: Set by the master loop to the screen's status line: a long worker job
        #: reports its steps there as it goes ("Measuring the bottom opening...").
        self.progress: Callable[[str], None] | None = None
        self._facts: dict[int, FactReport] = {}

    # ---- plumbing -------------------------------------------------------------
    @property
    def store(self) -> VersionStore:
        return self.project.versions(self.object_name)

    def _contract(self) -> DesignContract | None:
        return self.project.contract()

    def _run_worker(self, request: dict[str, Any]) -> dict[str, Any]:
        work = Path(tempfile.mkdtemp(prefix="cadwiz_master_"))
        time_limit_s = float(request.get("time_limit_s") or self.time_limit_s)
        request = dict(request, result_path=str(work / "result.json"), time_limit_s=time_limit_s,
                       memory_limit_bytes=self.memory_limit_bytes, progress_path=str(work / "progress.txt"))
        request_path = work / "request.json"
        request_path.write_text(json.dumps(request, default=str), encoding="utf-8")
        env = {**os.environ, "CADWIZ_SANDBOX_PROJECT_DIR": str(self.project.folder)}
        process = subprocess.Popen([str(self.freecadcmd), str(WORKER), str(request_path)], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            from integrations.mcp_tools.isolated import limit_process_memory

            limit_process_memory(process, self.memory_limit_bytes)
        except Exception:  # noqa: BLE001 - reported in the result, never silently
            pass
        sink: "queue.Queue[str]" = queue.Queue()
        threading.Thread(target=lambda: sink.put(process.communicate()[1] or ""), daemon=True).start()
        started = time.monotonic()
        # A build gets the sandbox's time limit plus FreeCAD's own start-up.
        ceiling = time_limit_s + 30.0
        progress_path = Path(request["progress_path"])
        shown = 0
        report = getattr(self, "progress", None)
        try:
            while process.poll() is None:
                if time.monotonic() - started > ceiling:
                    process.kill()
                    raise WorkerFailed(f"the job ran past its {time_limit_s:g}-second limit and was stopped")
                if report is not None and progress_path.exists():
                    lines = progress_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for line in lines[shown:]:
                        if line.strip():
                            report(line.strip() + "\u2026")
                    shown = len(lines)
                if self._pump is not None:
                    self._pump()          # keeps the window alive; raises on Cancel
                time.sleep(0.05)
        except BaseException:
            if process.poll() is None:
                process.kill()
            raise
        result_path = Path(request["result_path"])
        if not result_path.exists():
            stderr = sink.get(timeout=5) if not sink.empty() else ""
            raise WorkerFailed(f"the FreeCAD worker stopped without a result (exit {process.returncode}){': ' + stderr[-400:] if stderr else ''}")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def facts_for(self, version: int) -> FactReport | None:
        if version in self._facts:
            return self._facts[version]
        path = self.project.facts_path(self.object_name, version)
        if path.exists():
            facts = _facts_from_dict(json.loads(path.read_text(encoding="utf-8")))
            from ai_freecad_core.ai_master.fact_layer import finish_report

            finish_report(facts, self._contract(), self.printer)
            self._facts[version] = facts
            return facts
        return None

    def _current(self):
        record = self.store.current()
        if record is None:
            raise RuntimeError("there is no design source yet: call edit_source with parameters and a script first")
        return record

    # ---- the coarse tools ------------------------------------------------------
    def edit_source(self, patch: dict[str, Any], script: str | None, note: str) -> dict[str, Any]:
        values = {str(k): _to_value(v) for k, v in patch.items()}
        current = self.store.current()
        if current is None:
            if not script:
                raise ValueError("the first version needs a construction script that reads its parameters from P (mm) and P_RAW")
            contract = self._contract()
            source = DesignSource(self.object_name, {k.lstrip("+"): v for k, v in values.items()},
                                  features=list(contract.features) if contract else [], script=script,
                                  build_path=contract.build_path if contract else "mechanical", note=note or "first version")
        else:
            source = current.source.apply_patch({(k if k in current.source.parameters else "+" + k.lstrip("+")): v for k, v in values.items()},
                                                note=note, script=script)
        record = self.store.add(source, contract_version=(self._contract().version if self._contract() else 0))
        self.project.set_active(self.object_name, record.version)
        return {"version": record.version, "diff": record.diff, "parameters": record.source.parameter_values_line()}

    def build(self, source_version: int | None) -> dict[str, Any]:
        record = self.store.get(source_version) if source_version else self._current()
        if record is None:
            raise KeyError(f"no version {source_version}")
        version = record.version
        native = self.project.native_path(self.object_name, version)
        self.project.guard_write(native)
        contract = self._contract()
        result = self._run_worker({
            "action": "build", "script": record.source.render_script(), "project_dir": str(self.project.folder),
            "native_out": str(native), "render_out": str(self.project.render_path(self.object_name, version)), "views": ["iso"],
            "object_name": self.object_name, "contract": contract.to_dict() if contract else None,
            "printer": self.printer.__dict__ if hasattr(self.printer, "__dict__") else {
                k: getattr(self.printer, k) for k in ("name", "bed_x_mm", "bed_y_mm", "bed_z_mm", "min_wall_mm", "max_overhang_deg")},
        })
        if not result.get("ok"):
            line = result.get("error_line")
            return {"success": False, "version": version, "error": result.get("error", "unknown failure"),
                    "error_line": line, "error_line_text": _line(record.source.render_script(), line)}
        facts = _facts_from_dict(result["facts"])
        from ai_freecad_core.ai_master.fact_layer import finish_report

        finish_report(facts, contract, self.printer)
        self._facts[version] = facts
        facts_path = self.project.save_facts(self.object_name, version, facts.to_dict())
        renders = result.get("renders") or []
        self.store.attach(version, render_path=renders[0] if renders else "", facts_path=str(facts_path), native_path=str(native))
        self.project.set_active(self.object_name, version)
        return {"success": True, "version": version, "measurements": facts.plain_summary(), "facts": facts.to_dict(),
                "images": renders, "editability": facts.editability.display() if facts.editability else ""}

    def render(self, views: list[str], section: bool) -> dict[str, Any]:
        record = self._current()
        native = self.project.native_path(self.object_name, record.version)
        if not native.exists():
            raise RuntimeError(f"version {record.version} has not been built yet: call build first")
        out = self.project.object_folder(self.object_name) / "renders" / f"v{record.version}{'_section' if section else ''}.png"
        result = self._run_worker({"action": "render", "native_path": str(native), "render_out": str(out), "views": views or ["iso"], "section": section})
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "render failed"))
        return {"images": result.get("renders", [])}

    def measure(self, queries: list[str]) -> dict[str, Any]:
        record = self._current()
        facts = self.facts_for(record.version)
        if facts is None:
            raise RuntimeError(f"version {record.version} has not been built yet: call build first")
        data = facts.to_dict()
        if queries:
            wanted = {q.lower() for q in queries}
            mapping = {"bbox": "bbox_mm", "size": "bbox_mm", "volume": "volume_mm3", "holes": "holes", "wall": "min_wall_mm",
                       "hollow": "hollow", "collisions": "collisions", "clearance": "clearances_mm", "solids": "solid_count", "valid": "valid_solid"}
            data = {mapping.get(q, q): data.get(mapping.get(q, q)) for q in wanted}
        return {"version": record.version, "summary": facts.plain_summary(), "facts": data}

    def check_print(self, printer: str) -> dict[str, Any]:
        record = self._current()
        facts = self.facts_for(record.version)
        if facts is None or facts.printer is None:
            raise RuntimeError("build first, then check the print")
        return {"printer": self.printer.name, "ready": facts.printer.ready, "notes": facts.printer.notes}

    def editability_check(self, verify_living_design: bool) -> dict[str, Any]:
        record = self._current()
        facts = self.facts_for(record.version)
        if facts is None:
            raise RuntimeError("build first, then check editability")
        evidence = ""
        if verify_living_design:
            contract = self._contract()
            result = self._run_worker({"action": "living_test", "native_path": str(self.project.native_path(self.object_name, record.version)),
                                       "commitments": contract.editability_commitments if contract else []})
            facts.living_design_verified = bool(result.get("verified"))
            evidence = str(result.get("evidence", result.get("error", "")))
            from ai_freecad_core.ai_master.fact_layer import finish_report

            finish_report(facts, contract, self.printer)
            self.project.save_facts(self.object_name, record.version, facts.to_dict())
        level = facts.editability
        return {"level": level.level.name if level else "?", "display": level.display() if level else "", "evidence": list(level.evidence) if level else [],
                "living_design_test": evidence}

    def contract_check(self) -> dict[str, Any]:
        contract = self._contract()
        record = self._current()
        facts = self.facts_for(record.version)
        if contract is None:
            raise RuntimeError("there is no Design Contract yet: call update_contract first")
        if facts is None:
            raise RuntimeError(f"version {record.version} has not been built yet: call build first")
        check = check_contract(contract, facts)
        cert = certify(contract, facts)
        return {"status": cert.status if cert.complete else "NOT COMPLETE: " + " | ".join(cert.reasons), "complete": cert.complete,
                "requirements": check.plain_lines(), "measurements": facts.plain_summary(),
                "editability": facts.editability.display() if facts.editability else ""}

    def export(self, format: str) -> dict[str, Any]:
        if not self.export_allowed:
            raise PermissionError("exports happen only when the founder asks for a file; he has not asked in this request")
        fmt = format.lower().strip(".")
        if fmt not in _EXPORT_EXT:
            raise ValueError(f"format must be one of {', '.join(_EXPORT_EXT)}")
        record = self._current()
        native = self.project.native_path(self.object_name, record.version)
        if not native.exists():
            raise RuntimeError("build first, then export")
        out_dir = self.project.folder / "exports"
        out_dir.mkdir(exist_ok=True)
        out = out_dir / f"{self.object_name}_v{record.version}{_EXPORT_EXT[fmt]}"
        self.project.guard_write(out)
        result = self._run_worker({"action": "export", "native_path": str(native), "format": fmt, "export_path": str(out)})
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "export failed"))
        return {"path": str(out), "bytes": result.get("bytes", 0)}

    def show(self, content: dict[str, Any]) -> dict[str, Any]:
        if self._show is not None:
            self._show(content)
        return {"shown": True}

    #: Founder addendum 2026-10-12 ("concept first"): 3-4 real example pictures.
    MAX_EXAMPLE_PICTURES = 4

    def find_examples(self, query: str) -> dict[str, Any]:
        """Real reference designs (Thingiverse, Printables, manufacturer pages, ...)
        with their source and licence. Up to four pictures go on the founder's
        screen, each captioned with where it came from and its licence. When the
        founder gave his own picture, his picture is what is designed from; the
        examples are labelled as references only."""
        if self._find_examples is None:
            return {"results": [], "note": "no design library is connected in this session"}
        found = self._find_examples(query)
        lines, shown = [], 0
        founder_picture = bool(getattr(self, "founder_images", None))
        for item in found.get("results", [])[:8]:
            licence = item.get("license") or "not stated"
            lines.append(f"Reference: {item.get('title', '?')} \u2014 {item.get('url', '')} \u2014 licence: {licence} \u2014 a downloaded mesh is E0 (not editable); I can rebuild it as a native editable design")
            if item.get("image") and shown < self.MAX_EXAMPLE_PICTURES and self._show is not None:
                caption = f"Example {shown + 1}: {item.get('title', '?')} \u2014 {item.get('url', '')} \u2014 licence: {licence}"
                if founder_picture:
                    caption += " (a reference only: your own picture is what I design from)"
                self._show({"image": item["image"], "caption": caption})
                shown += 1
        return {**found, "provenance_lines": lines, "pictures_shown": shown,
                "founder_picture_wins": founder_picture}

    def versions(self, action: str, version: int | None, note: str) -> dict[str, Any]:
        if action == "list":
            return {"versions": [{"version": r.version, "diff": r.diff, "render": r.render_path} for r in self.store.list_recent(10)]}
        if version is None:
            raise ValueError(f"{action} needs a version number")
        record = self.store.restore(int(version)) if action == "restore" else self.store.branch(int(version), note)
        self.project.set_active(self.object_name, record.version)
        return {"version": record.version, "diff": record.diff}

    def read_file(self, path: str) -> dict[str, Any]:
        target = Path(path)
        inside = str(target.resolve()).startswith(str(self.project.folder.resolve()))
        if not (self.project.is_founder_file(target) or inside):
            raise PermissionError("only files the founder gave CADWiz, or files in this project, can be read")
        if not target.exists():
            raise FileNotFoundError(str(target))
        data = target.read_bytes()
        if target.suffix.lower() in (".txt", ".md", ".csv", ".json", ".py", ".scad"):
            return {"path": str(target), "text": data[:20000].decode("utf-8", "replace")}
        return {"path": str(target), "bytes": len(data), "type": target.suffix.lower(), "note": "binary file: images go to the master as images; meshes are E0"}


def _line(script: str, number: int | None) -> str:
    if not number:
        return ""
    lines = script.splitlines()
    return lines[number - 1].strip() if 0 < number <= len(lines) else ""


def wants_a_file(text: str) -> bool:
    """The founder asked for a file this turn (exports happen only then)."""
    return bool(re.search(r"\b(export|download|save (it )?as|stl|3mf|step file|step|fcstd|send (it )?to (the )?printer|slice|give me the file)\b", text.casefold()))
