# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The plug-in's tools, run inside the founder's FreeCAD (ORDER-2026-10-12-05).

Each tool does one complete job and returns a plain JSON-able result. They are
built on what CADWiz already has: the headless sandboxed worker and versions
beside the founder's file (`AdoptedExecutor`), measurement of the open document
(`measurements`), ring-level editing of lofted bodies (`reshape_rings`), print
checks, export and the Design Contract.

Rules enforced here, in code:
  * a founder file is backed up beside itself before the first change of the
    session; every change is a new version; nothing of his is ever deleted;
  * model code (`build_model`, script edits) runs in the sandboxed headless
    worker (no network, no shell, no subprocesses, files only inside the project
    folder) on a copy; the result is written back only after the backup;
  * open/save/export stay inside his CAD folders and the project folder;
  * every call is logged (`tool-calls.jsonl`);
  * what is meant for the founder is plain: a failure carries one plain sentence
    (`say_to_founder`); technical detail for Claude to fix its own code
    (`detail_for_claude`) is kept separate, and the instructions tell Claude never
    to pass it on.
"""
from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import tempfile
import time
import traceback
from importlib import import_module
from pathlib import Path
from typing import Any, Callable

from ai_freecad_core.ai_master.flags import read_settings
from ai_freecad_core.ai_master.project_store import Project
from ai_freecad_core.ai_master.units import both
from ai_freecad_core.conversation.founder_words import PLAIN_ERROR, clean_reply

PROJECT_NAME = "CADWiz plug-in"
TOOL_NAMES = ("inspect_document", "measure", "render", "build_model", "edit_object", "versions", "check_print", "export",
              "open_document", "save_document", "design_record", "contract_check",
              # ORDER-2026-10-18-01: the Visual Communications Screen he and Claude share
              "shown_to_claude", "mark_for_user", "get_selection",
              # ORDER-2026-10-18-03: the settings he chose for how Claude works, and the problems list
              "user_preferences", "problems",
              # ORDER-2026-10-18-02: the concept stage and guided intent
              "show_concepts", "concept_choice", "design_questions",
              # ORDER-2026-10-18-02 B: mesh and Blender
              "import_mesh", "mesh_edit", "swap_part", "repair_mesh",
              # ORDER-2026-10-19-06: technical drawings (founder ruling 2026-10-19)
              "drawing")


class PlainError(Exception):
    """A failure whose message is already one plain sentence for the founder."""


def plugin_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    folder = base / "CADWiz" / "plugin"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def cad_folders(extra: list[str] | tuple[str, ...] = ()) -> list[Path]:
    """Where the founder's CAD files may be opened, saved and exported: the folders
    named in `~/.cadwiz/settings.json` ("cad_folders"), his Documents folder, the
    plug-in's project folder, and the folders of documents he already has open."""
    folders = [Path(p) for p in (read_settings().get("cad_folders") or []) if str(p).strip()]
    folders.append(Path.home() / "Documents")
    folders.extend(Path(p) for p in extra if p)
    return [f.resolve() for f in folders]


def inside(path: str | Path, folders: list[Path]) -> bool:
    target = Path(path).resolve()
    return any(target == f or f in target.parents for f in folders)


class PluginSession:
    """One FreeCAD session's tools. `app` is the FreeCAD module (a stand-in in tests);
    `gui` is FreeCADGui or None headless; `executor_factory(project, name, file, **hooks)`
    builds the per-document executor (AdoptedExecutor in the product)."""

    def __init__(self, *, app: Any = None, gui: Any = None, project_root: str | Path | None = None,
                 executor_factory: Callable[..., Any] | None = None, pump: Callable[[], None] | None = None,
                 log_path: str | Path | None = None, section_runner: Callable[..., dict] | None = None) -> None:
        self.app = app if app is not None else import_module("FreeCAD")
        self.gui = gui
        self.project = Project.open(PROJECT_NAME, root=project_root)
        self._factory = executor_factory or _adopted_executor
        self._pump = pump
        self._executors: dict[str, Any] = {}
        self.log_path = Path(log_path) if log_path else plugin_data_dir() / "tool-calls.jsonl"
        self._section_runner = section_runner
        #: What the slim panel shows: the document and object being worked on, its
        #: version, its key measurements, the last change in one line, and the
        #: newest picture of the model (ORDER-2026-10-15-01).
        self.state: dict[str, Any] = {"document": "", "object": "", "version": 0, "measurements": "", "last_change": "", "file": "",
                                      "picture": ""}
        #: The screen he and Claude share: marks, the frame he froze with Show
        #: Claude, and whether Claude has read it (ORDER-2026-10-18-01).
        from integrations.cadwiz_plugin.screen import ScreenState

        self.screen = ScreenState(self.log_path.parent)

    # ---- the one entry point ----------------------------------------------------------
    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        started = time.monotonic()
        entry: dict[str, Any] = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": tool,
                                 "arguments": {k: (v[:400] + "..." if isinstance(v, str) and len(v) > 400 else v) for k, v in args.items()}}
        try:
            if tool not in TOOL_NAMES:
                raise PlainError(f"CADWiz has no tool called {tool!r}.")
            result = getattr(self, "_" + tool)(**args)
            result = {"ok": True, **result} if "ok" not in result else result
        except PlainError as error:
            result = {"ok": False, "say_to_founder": str(error)}
        except PermissionError as error:
            result = {"ok": False, "say_to_founder": clean_reply(str(error)) or PLAIN_ERROR}
        except TypeError as error:
            result = {"ok": False, "say_to_founder": PLAIN_ERROR, "detail_for_claude": f"bad arguments for {tool}: {error}"}
            self._attach_report(result, "CW-PLUGIN-ARGS", tool)
        except Exception as error:  # noqa: BLE001 - every failure becomes a plain sentence plus a logged detail
            entry["traceback"] = traceback.format_exc()[-2000:]
            result = {"ok": False, "say_to_founder": PLAIN_ERROR, "detail_for_claude": f"{type(error).__name__}: {error}"[:600]}
            self._attach_report(result, "CW-PLUGIN-FAIL", tool)
        entry.update(ok=bool(result.get("ok")), seconds=round(time.monotonic() - started, 2),
                     **({"detail": result.get("detail_for_claude", "")} if not result.get("ok") else {}))
        with contextlib.suppress(OSError):
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
        return result

    # ---- error reports (ORDER-2026-10-21-01, Addendum One Part C) ------------------------
    def _attach_report(self, result: dict[str, Any], error_code: str, tool: str) -> None:
        """Write a local error report for this failure and tell Claude its id. Nothing
        is sent anywhere: cadwiz_send_feedback shows the user what it holds first."""
        from integrations.cadwiz_plugin import CADWIZ_VERSION
        from integrations.cadwiz_plugin.error_report import write_report

        try:
            freecad = ".".join(str(part) for part in self.app.Version()[:3])
        except Exception:  # noqa: BLE001
            freecad = ""
        document = getattr(self.app, "ActiveDocument", None)
        report_id = write_report(
            self.log_path.parent, error_code=error_code, message=str(result.get("detail_for_claude", "")), tool=tool,
            log_path=self.log_path, grab_window=self._grab_window, model_file=str(getattr(document, "FileName", "") or ""),
            version_info={"cadwiz": CADWIZ_VERSION, "freecad": freecad or "unknown",
                          "os": platform.platform(terse=True), "claude_desktop": "unknown"})
        if report_id:
            result["report_id"] = report_id
            result["error_code"] = error_code
            result["note_for_claude"] = (f"A local error report {report_id} ({error_code}) was saved on this computer. Offer once: "
                                         "\"Want me to send this to Steve?\" -- only with a yes, use cadwiz_send_feedback.")

    def _grab_window(self, path: Path) -> bool:
        """FreeCAD's whole window as a picture (a fraction of a second; window thread)."""
        if self.gui is None:
            return False
        window = self.gui.getMainWindow()
        return bool(window.grab().save(str(path), "PNG"))

    # ---- documents ---------------------------------------------------------------------
    def _document(self, name: str | None = None) -> Any:
        documents = dict(self.app.listDocuments() or {})
        if name:
            for key, document in documents.items():
                if name in (key, getattr(document, "Label", ""), Path(str(getattr(document, "FileName", "") or "")).stem):
                    return document
            raise PlainError(f"There is no open document called {name!r}; the open ones are: {', '.join(d.Label for d in documents.values()) or 'none'}.")
        document = getattr(self.app, "ActiveDocument", None)
        if document is None and documents:
            document = next(iter(documents.values()))
        if document is None:
            raise PlainError("Nothing is open in FreeCAD yet. Open a model, or ask me to build one.")
        return document

    def _file_of(self, document: Any) -> str:
        """The document's file; an unsaved document gets one in the project folder first."""
        file_name = str(getattr(document, "FileName", "") or "")
        if not file_name:
            folder = self.project.folder / "documents"
            folder.mkdir(parents=True, exist_ok=True)
            file_name = str(folder / f"{document.Label or document.Name}.FCStd")
            document.saveAs(file_name)
        return file_name

    def _executor(self, document: Any) -> Any:
        file_name = self._file_of(document)
        key = str(Path(file_name).resolve()).casefold()
        executor = self._executors.get(key)
        if executor is None:
            label = str(getattr(document, "Label", "") or Path(file_name).stem)
            executor = self._factory(self.project, label, file_name, pump=self._pump,
                                     snapshot_open=lambda dest, doc_name=document.Name: self._snapshot(doc_name, file_name, dest),
                                     reload=self._reload, current_view=self._capture_view)
            self._executors[key] = executor
            with contextlib.suppress(Exception):
                # His own printer from Setup, for the print check (ORDER-2026-10-18-03).
                from integrations.cadwiz_plugin import preferences_store

                executor.printer = preferences_store.printer_profile(preferences_store.load())
            with contextlib.suppress(AttributeError):
                # A backup of a model that is already broken is recorded as broken,
                # so the time slider can mark it red (ORDER-2026-10-18-01).
                executor.store.health_probe = lambda _path, name=document.Name: self._broken_objects(name)
        if not getattr(executor, "adoption", None):
            executor.adopt()
            executor.adopted_at_version = executor.store.latest()
        self.state.update(document=str(getattr(document, "Label", "")), file=file_name, object=str((executor.adoption or {}).get("main_object", "")))
        return executor

    def _broken_objects(self, document_name: str) -> list[str]:
        from integrations.cadwiz_plugin.view_link import broken_objects

        document = dict(self.app.listDocuments() or {}).get(document_name)
        return broken_objects(document) if document is not None else []

    def store_for(self, document: Any) -> Any:
        """The version store of an open document WITHOUT reading the model: the
        executor's when Claude has worked on it this session, else the store an
        earlier session left beside its record (None when there is none yet).
        The panel's time slider reads this every few seconds; it must never start
        the headless worker."""
        file_name = str(getattr(document, "FileName", "") or "")
        if not file_name:
            return None
        executor = self._executors.get(str(Path(file_name).resolve()).casefold())
        if executor is not None:
            return executor.store
        import hashlib

        from ai_freecad_core.ai_master.adopted import AdoptedStore

        label = str(getattr(document, "Label", "") or Path(file_name).stem)
        file_key = hashlib.sha256(str(Path(file_name).resolve()).casefold().encode("utf-8")).hexdigest()[:12]
        from ai_freecad_core.ai_master.project_store import safe_name

        folder = self.project.folder / "objects" / safe_name(label) / "adopted" / file_key
        if not folder.is_dir():
            return None
        return AdoptedStore(folder, file_name)

    def version_pictures(self, document: Any, version: int) -> dict[str, Any]:
        """For "Compare with now": a picture of `version` and of the model as it is
        now, from the same angle, plus the measured difference in one line."""
        from ai_freecad_core.ai_master.adopted import measured_diff

        executor = self._executor(document)
        store = executor.store
        chosen = store.get(int(version))
        if chosen is None:
            raise PlainError(f"There is no version {version}.")
        folder = self.project.folder / "renders" / "compare"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time())
        now_file = folder / f"now_{stamp}.FCStd"
        self._snapshot(document.Name, self._file_of(document), str(now_file))
        before = executor.look_at_file(chosen.file, str(folder / f"v{chosen.version}_{stamp}.png"))
        now = executor.look_at_file(str(now_file), str(folder / f"now_{stamp}.png"))
        diff = measured_diff(before["measurements"], now["measurements"]) or "no measured difference in size, wall or holes"
        return {"before": before["picture"], "now": now["picture"], "diff": diff, "version": chosen.version}

    def _snapshot(self, document_name: str, file_name: str, dest: str) -> None:
        """The document exactly as it is open (unsaved changes included) -> dest."""
        document = dict(self.app.listDocuments()).get(document_name)
        if document is not None and hasattr(document, "saveCopy"):
            document.saveCopy(dest)
        else:
            shutil.copyfile(file_name, dest)

    def _reload(self, path: str) -> None:
        """After a change was written to the file: show it in his FreeCAD -- visible,
        in the 3D view, turned to the iso view and framed, with nothing for him to press."""
        target = str(Path(path).resolve()).casefold()
        shown = visible_in_file(path)
        for name, document in list(dict(self.app.listDocuments()).items()):
            if str(Path(str(getattr(document, "FileName", "") or "")).resolve()).casefold() == target:
                self.app.closeDocument(name)
                break
        reopened = self.app.openDocument(path)
        with contextlib.suppress(Exception):
            self.app.setActiveDocument(reopened.Name)
        if self.gui is not None:
            show_and_frame(self.gui, reopened, shown)

    def _capture_view(self, dest: str) -> str:
        if self.gui is None:
            return ""
        try:
            view = self.gui.ActiveDocument.ActiveView
            view.saveImage(dest, 800, 600, "Current")
            return dest if Path(dest).is_file() else ""
        except Exception:  # noqa: BLE001
            return ""

    def _after_change(self, executor: Any, outcome: dict[str, Any]) -> dict[str, Any]:
        if not outcome.get("success", True) and outcome.get("error"):
            error = str(outcome.get("error"))
            line = outcome.get("error_line")
            raise _ScriptFailed(error + (f" (line {line})" if line else ""))
        state = executor.current_state() if hasattr(executor, "current_state") else {}
        self.state.update(version=int(state.get("version") or 0), last_change=str(outcome.get("diff") or state.get("diff") or ""),
                          measurements=str(outcome.get("measurements") or ""))
        self._remember_picture(outcome.get("images"))
        return outcome

    def _remember_picture(self, images: Any) -> None:
        """The slim panel's picture box shows the newest render that exists on disk."""
        picture = next((str(p) for p in (images or []) if p and Path(str(p)).is_file()), "")
        if picture:
            self.state["picture"] = picture

    # ---- the tools -------------------------------------------------------------------
    def _inspect_document(self, document: str | None = None) -> dict[str, Any]:
        documents = dict(self.app.listDocuments() or {})
        open_list = [{"name": d.Label, "file": str(getattr(d, "FileName", "") or "(not saved yet)"), "objects": len(getattr(d, "Objects", []) or [])}
                     for d in documents.values()]
        if not documents:
            return {"open_documents": [], "summary": "Nothing is open in FreeCAD yet."}
        target = self._document(document)
        tree = [_describe_object(o) for o in getattr(target, "Objects", []) or []]
        executor = self._executor(target)
        if getattr(executor, "adopted_at_version", 0) != executor.store.latest():
            executor.adopt()                      # changed since it was read: read it again
            executor.adopted_at_version = executor.store.latest()
        adoption = executor.adoption or {}
        facts = adoption.get("facts") or {}
        editability = (facts.get("editability") or {})
        construction = adoption.get("construction") or {}
        return {"open_documents": open_list, "document": target.Label, "objects": tree,
                "how_it_was_built": construction.get("plain") or construction.get("kind") or "",
                "editability": {"level": editability.get("level"), "evidence": editability.get("evidence")},
                "measurements": executor.measure([]).get("summary", ""), "bottom_opening": adoption.get("bottom_opening"),
                "versions": [{"version": v.version, "kind": v.kind, "diff": v.diff} for v in executor.store.list_recent(10)]}

    def _measure(self, question: str = "", object: str | None = None, document: str | None = None) -> dict[str, Any]:  # noqa: A002
        from integrations.freecad_native.measurements import SectionRunner, answer_measurement

        target = self._document(document)
        executor = self._executor(target)
        words = " ".join(w for w in (question or "how big is it", object or "") if w)
        runner = SectionRunner(lambda label, opening=None, height_mm=None: _section(executor, label, opening, height_mm))
        answer = answer_measurement(target, words, runner)
        summary = executor.measure([])
        return {"answer": answer or summary.get("summary", ""), "summary": summary.get("summary", ""),
                "bottom_opening": summary.get("bottom_opening"), "units": "every length is given in mm and inches"}

    def _render(self, views: list[str] | None = None, section: bool = False, current_view: bool = True,
                object: str | None = None, document: str | None = None) -> dict[str, Any]:  # noqa: A002
        target = self._document(document)
        executor = self._executor(target)
        images = list(executor.render(list(views or ["iso"]), bool(section)).get("images") or [])
        self._remember_picture(images)
        if current_view:
            view = self._capture_view(str(self.project.folder / "renders" / f"current_view_{int(time.time())}.png"))
            if view:
                images.insert(0, view)
        return {"images": images, "captions": ["the user's current 3D view"] * (1 if current_view and images else 0)}

    def _build_model(self, code: str, document: str | None = None, note: str = "", new_document: str | None = None) -> dict[str, Any]:
        if not code.strip():
            raise PlainError("There was no FreeCAD code to run.")
        if new_document or (document is None and getattr(self.app, "ActiveDocument", None) is None):
            # Something new goes in its own document (in the project folder), never
            # into whatever the founder happens to have open.
            name = _safe_doc_name(new_document or note or "Design")
            folder = self.project.folder / "documents"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{name}.FCStd"
            n = 2
            while path.exists():
                path = folder / f"{name}_{n}.FCStd"
                n += 1
            created = self.app.newDocument(path.stem)
            created.saveAs(str(path))
            with contextlib.suppress(Exception):
                self.app.setActiveDocument(created.Name)
            document = created.Name
        target = self._document(document)
        executor = self._executor(target)
        return self._after_change(executor, executor.edit_existing(code, note or "built by Claude"))

    def _edit_object(self, object: str | None = None, parameters: dict[str, Any] | None = None, script: str | None = None,  # noqa: A002
                     inner_bottom_circumference_mm: float | None = None, note: str = "", document: str | None = None) -> dict[str, Any]:
        target = self._document(document)
        executor = self._executor(target)
        if inner_bottom_circumference_mm:
            return self._after_change(executor, executor.reshape_rings(float(inner_bottom_circumference_mm), note))
        if parameters:
            return self._after_change(executor, executor.set_parameters(dict(parameters), note))
        if script:
            return self._after_change(executor, executor.edit_existing(script, note or f"edited {object or 'the model'}"))
        raise PlainError("Tell me what to change: named sizes, a shape operation, or the new distance around the bottom ring.")

    def _versions(self, action: str = "list", version: int | None = None, other: int | None = None, document: str | None = None,
                  note: str = "") -> dict[str, Any]:
        target = self._document(document)
        executor = self._executor(target)
        store = executor.store
        if action == "list":
            return {"versions": [{"version": v.version, "kind": v.kind, "diff": v.diff, "note": v.note, "file": v.file, "utc": v.utc,
                                  "broken": list(getattr(v, "broken", []) or []), "restored_from": v.restored_from}
                                 for v in store.list_recent(20)],
                    "note_for_claude": "Every version is a complete saved copy. A version with 'broken' objects can still be restored; "
                                       "restoring adds a new version and never deletes a newer one."}
        if action == "save":
            executor._ensure_backup() if not store.backed_up_this_session else store.backup(
                lambda dest: self._snapshot(target.Name, self._file_of(target), dest), note=note or "saved on request")
            current = store.current()
            return {"version": current.version if current else 0, "file": current.file if current else ""}
        if action == "restore":
            if version is None:
                raise PlainError("Which version should I go back to?")
            if store.get(int(version)) is None:
                raise PlainError(f"There is no version {version}.")
            self._keep_now_before_restore(target, store, int(version))
            restored = executor.versions("restore", int(version), "")
            self.state.update(version=int(restored.get("version") or 0), last_change=str(restored.get("diff", "")))
            return restored
        if action == "compare":
            from ai_freecad_core.ai_master.adopted import measured_diff

            a, b = store.get(int(version or 0)), store.get(int(other or store.latest()))
            if a is None or b is None:
                raise PlainError("I don't have both of those versions.")
            return {"from": a.version, "to": b.version, "diff": measured_diff(a.measurements, b.measurements) or "no measured difference",
                    "same_file_content": a.sha256 == b.sha256}
        raise PlainError("Versions can be listed, saved, restored or compared.")

    def _keep_now_before_restore(self, document: Any, store: Any, version: int) -> None:
        """A restore never loses anything (ORDER-2026-10-18-01): if his model has
        changed since its newest version -- edited by hand in FreeCAD, saved or not --
        it is kept as a version of its own before the older one comes back. (Before
        the first change of a session the executor's own backup already does this.)"""
        if not store.backed_up_this_session:
            return
        from ai_freecad_core.ai_master.adopted import sha256_of

        current = store.current()
        file_name = self._file_of(document)
        changed = current is None
        with contextlib.suppress(OSError):
            changed = changed or sha256_of(file_name) != current.sha256
        if self.gui is not None:
            with contextlib.suppress(Exception):
                changed = changed or bool(self.gui.getDocument(document.Name).Modified)
        if changed:
            store.backup(lambda dest: self._snapshot(document.Name, file_name, dest),
                         note=f"your model just before going back to version {version}")

    def _check_print(self, printer: str = "", document: str | None = None) -> dict[str, Any]:
        executor = self._executor(self._document(document))
        return executor.check_print(printer)

    def _export(self, format: str, document: str | None = None) -> dict[str, Any]:  # noqa: A002
        executor = self._executor(self._document(document))
        executor.export_allowed = True            # Claude asked for the file on the founder's behalf
        return executor.export(format)

    def _open_document(self, path: str) -> dict[str, Any]:
        allowed = cad_folders([str(self.project.folder)] + [str(Path(str(getattr(d, "FileName", "") or ".")).parent)
                                                            for d in dict(self.app.listDocuments()).values() if getattr(d, "FileName", "")])
        if not inside(path, allowed):
            raise PlainError("That file is outside your CAD folders, so I won't open it. Add its folder to CADWiz's CAD folders first.")
        if not Path(path).is_file():
            raise PlainError("I can't find that file.")
        document = self.app.openDocument(str(path))
        with contextlib.suppress(Exception):
            self.app.setActiveDocument(document.Name)
        return {"document": document.Label, "file": str(path)}

    def _save_document(self, document: str | None = None, path: str | None = None) -> dict[str, Any]:
        target = self._document(document)
        current = str(getattr(target, "FileName", "") or "")
        if path:
            allowed = cad_folders([str(self.project.folder)] + ([str(Path(current).parent)] if current else []))
            if not inside(path, allowed):
                raise PlainError("That place is outside your CAD folders, so I won't save there.")
            if Path(path).exists():
                raise PlainError("A file with that name already exists; I never overwrite a file of yours. Pick a new name.")
            target.saveAs(str(path))
            return {"saved": str(path)}
        if current and Path(current).exists():
            # His file is about to change: its prior state becomes a version first.
            executor = self._executor(target)
            if not executor.store.backed_up_this_session:
                executor.store.backup(lambda dest: shutil.copyfile(current, dest), note="before saving")
        target.save() if current else self._file_of(target)
        return {"saved": str(getattr(target, "FileName", "") or "")}

    def _design_record(self, action: str = "get", fields: dict[str, Any] | None = None, document: str | None = None) -> dict[str, Any]:
        from ai_freecad_core.ai_master.design_contract import update_contract

        executor = self._executor(self._document(document))
        if action == "update":
            contract = update_contract(self.project, executor.object_name, dict(fields or {}), str((fields or {}).get("founder_words", "")))
            return {"contract": contract.to_dict()}
        contract = self.project.contract()
        return {"contract": contract.to_dict() if contract else None}

    def _contract_check(self, document: str | None = None) -> dict[str, Any]:
        executor = self._executor(self._document(document))
        return executor.contract_check()

    # ---- the shared screen (ORDER-2026-10-18-01) -------------------------------------
    def _drawing(self, dimensions: list[dict[str, Any]] | None = None, section: str = "auto", note: str = "",
                 document: str | None = None) -> dict[str, Any]:
        """A technical drawing sheet of the open model (ORDER-2026-10-19-06): made in
        FreeCAD's windowless program from a saved copy, kept as SVG and PDF in the
        project's drawings folder, and shown on his CADWiz screen."""
        from integrations.cadwiz_plugin import drawings

        if section not in ("auto", "on", "off"):
            raise PlainError("A section can be on, off, or auto (on for a hollow part).")
        for spec in dimensions or []:
            if not isinstance(spec, dict) or len(spec.get("start") or []) != 3 or len(spec.get("end") or []) != 3:
                raise PlainError("Each dimension needs a start and an end point, each [x, y, z] in millimetres.")
        target = self._document(document)
        label = str(getattr(target, "Label", "") or target.Name)
        store = self.store_for(target)
        version = int(store.latest()) if store is not None and hasattr(store, "latest") else 0
        folder = self.project.folder / "drawings"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{_safe_doc_name(label)}_v{version}" if version else _safe_doc_name(label)
        copy = folder / f".{stem}.source.FCStd"
        self._snapshot(target.Name, self._file_of(target), str(copy))
        job = drawings.DrawingJob(str(copy), str(folder / f"{stem}.svg"), title=label.replace("_", " "), version=version,
                                  section=section, dimensions=dimensions, note=note)
        result = job.wait(self._pump)
        with contextlib.suppress(OSError):
            copy.unlink()
        if not result.get("ok"):
            raise _ScriptFailed(str(result.get("detail") or result.get("say") or "the drawing job failed"))
        svg = str(result["svg"])
        out: dict[str, Any] = {"svg": svg, "scale": result.get("scale"), "section": result.get("section"),
                               "size_mm": result.get("size_mm")}
        with contextlib.suppress(Exception):          # PDF and picture need Qt: there in FreeCAD, not in tests
            out["pdf"] = drawings.svg_to_pdf(svg, str(folder / f"{stem}.pdf"))
            out["images"] = [drawings.svg_to_png(svg, str(folder / f"{stem}.png"))]
        # The panel shows it, and keeps these dimensions when it remakes the sheet after a change.
        self.state["drawing"] = {"document": target.Name, "svg": svg, "pdf": out.get("pdf", ""), "dimensions": list(dimensions or []),
                                 "section": section, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        out["say_to_founder"] = ("The drawing is on your CADWiz screen (Drawing), and saved as a PDF in your CADWiz Projects "
                                 "drawings folder." if out.get("pdf") else "The drawing is on your CADWiz screen (Drawing).")
        out["note_for_claude"] = ("Dimensions: points [x, y, z] in model mm, in the view named (front, top, right, section); "
                                  "offset + puts it below / right of the line, - above / left. Read points with measure or from their marks.")
        return out

    def _shown_to_claude(self) -> dict[str, Any]:
        from integrations.cadwiz_plugin.screen import NOTHING_SHOWN

        frame = self.screen.read()
        if frame is None:
            return {"shown": False, "note_for_claude": NOTHING_SHOWN}
        pictures = [p for p in frame.pop("pictures", []) if Path(str(p)).is_file()]
        return {"shown": True, **frame, "images": pictures}

    def _user_preferences(self) -> dict[str, Any]:
        """How he wants Claude to work, as he set it on the Setup page."""
        from integrations.cadwiz_plugin import preferences_store

        preferences = preferences_store.load()
        return {"follow_these": preferences.rules_for_claude(), "preferences": preferences.to_dict(),
                "note_for_claude": "Follow these in every reply. Teaching happens here in the Claude app when the user asks; "
                                   "the CADWiz panel only holds their choice."}

    def _problems(self, document: str | None = None) -> dict[str, Any]:
        """What the Creating page lists as problems, with the technical detail for you."""
        from ai_freecad_core.cadwiz_screen.problems import summary_line
        from integrations.cadwiz_plugin.problems_watch import find_problems

        target = self._document(document) if document or getattr(self.app, "ActiveDocument", None) is not None else None
        connected = True
        found = find_problems(target, connected)
        return {"document": getattr(target, "Label", ""), "summary": summary_line(found), "problems": [p.to_dict() for p in found]}

    # ---- the concept stage and guided intent (ORDER-2026-10-18-02 A, D) -------------------
    def _show_concepts(self, cards: list[dict[str, Any]] | None = None, note: str = "", new_design: bool = False) -> dict[str, Any]:
        from ai_freecad_core.cadwiz_screen.concepts import HONEST_LINE, MAX_CARDS, ConceptCard
        from ai_freecad_core.cadwiz_screen.licences import allowed_by, read_licence
        from integrations.cadwiz_plugin import fetch, preferences_store

        specs = list(cards or [])
        if not 1 <= len(specs) <= MAX_CARDS:
            raise TypeError(f"show one to {MAX_CARDS} cards")
        if new_design:
            self.screen.new_design()
        folder = self.project.folder / "concepts" / f"round-{len(self.screen.concepts.rounds) + 1:02d}-{int(time.time())}"
        made: list[ConceptCard] = []
        for number, spec in enumerate(specs, start=1):           # every card checked and fetched before the round is shown
            if not isinstance(spec, dict):
                raise TypeError('each card is an object: {"title", "picture_url" or "picture_path" or "svg", "kind", "source", "licence", "has_3d_file"}')
            title = str(spec.get("title") or "").strip()
            name = f"{number}-{title or 'card'}"
            if spec.get("svg"):
                svg = str(spec["svg"])
                if not svg.lstrip().startswith("<svg") or len(svg) > 500_000:
                    raise TypeError("svg must be one <svg> drawing under 500 KB")
                folder.mkdir(parents=True, exist_ok=True)
                picture = fetch.unique(folder / (fetch.safe_name(name, "sketch") + ".svg"))
                picture.write_text(svg, encoding="utf-8")
            elif spec.get("picture_path"):
                source_path = Path(str(spec["picture_path"]))
                if not source_path.is_file() or source_path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
                    raise TypeError(f"picture_path {source_path} is not a picture file on this computer")
                folder.mkdir(parents=True, exist_ok=True)
                picture = fetch.unique(folder / (fetch.safe_name(name, "picture") + source_path.suffix.lower()))
                shutil.copyfile(source_path, picture)
            elif spec.get("picture_url"):
                try:
                    picture = fetch.fetch_picture(str(spec["picture_url"]), folder, name, self._pump)
                except fetch.FetchRefused as error:
                    raise TypeError(f"card {number}: {error}") from None
            else:
                raise TypeError(f"card {number} needs a picture: picture_url, picture_path or svg")
            try:
                made.append(ConceptCard(title, str(picture), str(spec.get("kind") or ("sketch" if spec.get("svg") else "found")),
                                        str(spec.get("source") or ""), str(spec.get("licence") or ""), bool(spec.get("has_3d_file")),
                                        str(spec.get("model_url") or ""), str(spec.get("note") or "")))
            except ValueError as error:
                raise TypeError(f"card {number}: {error}") from None
        round_ = self.screen.concepts.add_round(made, str(note or ""))
        self.screen.save_concepts()
        preference = preferences_store.load().licences
        refused = [c.title for c in made if c.kind == "found" and not allowed_by(preference, read_licence(c.licence))]
        pictures = [c.picture for c in made if Path(c.picture).suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp")]
        return {"round": round_.number, "cards": [c.to_dict() for c in made], "on_his_screen": "Choosing a design",
                "honest_line": HONEST_LINE,
                **({"not_allowed_by_his_licence_setting": refused} if refused else {}),
                "note_for_claude": "The user picks a card on their screen and may ask for changes (another round). Build nothing in 3D "
                                   "until concept_choice shows make_3d_requested or the user says to make it 3D.",
                "images": pictures}

    def _concept_choice(self) -> dict[str, Any]:
        history = self.screen.concepts
        if not history.rounds:
            return {"rounds": 0, "note_for_claude": "No concepts have been shown yet (show_concepts)."}
        return history.summary()

    def _design_questions(self, request: str = "") -> dict[str, Any]:
        from ai_freecad_core.cadwiz_screen.intent import plan_questions
        from integrations.cadwiz_plugin import preferences_store

        if not str(request).strip():
            raise TypeError("pass their request in their own words, e.g. 'a fishing lure for bass'")
        preferences = preferences_store.load()
        plan = plan_questions(str(request), preferences.questions, material_default=preferences.print_material)
        plan["after_answers"] = ("Record their answers with design_record(action='update', fields=...) -- measurable ones as requirements "
                                 "(record_with shows the shape), the rest as assumptions -- build, then run contract_check.")
        return plan

    # ---- mesh and Blender (ORDER-2026-10-18-02 B) --------------------------------------------
    def _mesh_change(self, document: Any, note: str, change: Callable[[], str]) -> dict[str, Any]:
        """One mesh operation as a version: the model is saved as a version first,
        changed, saved, and saved as the next version (the time slider)."""
        from integrations.cadwiz_plugin import mesh_tools

        executor = self._executor(document)
        executor._ensure_backup()
        before = mesh_tools.size_mm(document)
        what = change()
        document.recompute()
        document.save()
        target = executor.store.next_version_file()
        document.saveCopy(str(target))
        after = mesh_tools.size_mm(document)
        diff = what if before == after else f"{what}; size {mesh_tools.size_words(before)} -> {mesh_tools.size_words(after)}"
        record = executor.store.add_edit(target, diff=diff, note=note, measurements={})
        self.state.update(document=str(document.Label), file=str(document.FileName), version=record.version, last_change=diff)
        picture = self._capture_view(str(self.project.folder / "renders" / f"mesh_v{record.version}_{int(time.time())}.png"))
        if picture:
            self.state["picture"] = picture
        from integrations.cadwiz_plugin.problems_watch import find_problems

        problems = [p.for_founder() for p in find_problems(document, True) if p.kind in ("loose", "mesh_holes", "rebuild")]
        return {"version": record.version, "change": diff, "size": mesh_tools.size_words(after), "parts": [
            {"name": o.Name, "label": o.Label, "triangles": int(o.Mesh.CountFacets)} for o in mesh_tools.mesh_parts(document)],
            "problems_now": problems, "images": [picture] if picture else []}

    def _import_mesh(self, path: str | None = None, url: str | None = None, name: str = "", source: str = "", licence: str = "",
                     separate_parts: bool = False) -> dict[str, Any]:
        from integrations.cadwiz_plugin import fetch, mesh_tools

        if bool(path) == bool(url):
            raise TypeError("give exactly one of path (a file on their PC) or url (a download link)")
        imports = self.project.folder / "imports"
        if url:
            try:
                original = fetch.fetch_model(str(url), imports, self._pump)
            except fetch.FetchRefused as error:
                raise TypeError(str(error)) from None
            source = source or str(url)
        else:
            original = Path(str(path))
            if not original.is_file():
                raise PlainError("I can't find that file.")
            source = source or str(original)
        suffix = original.suffix.lower()
        if suffix not in mesh_tools.MESH_SUFFIXES + mesh_tools.SOLID_SUFFIXES:
            raise TypeError("import_mesh takes STL, 3MF, OBJ or STEP files")
        label = fetch.safe_name(name or original.stem, "Imported")
        folder = self.project.folder / "documents"
        folder.mkdir(parents=True, exist_ok=True)
        target = fetch.unique(folder / f"{label}.FCStd")
        document = self.app.newDocument(target.stem)
        if suffix in mesh_tools.SOLID_SUFFIXES:
            import Part

            solid = document.addObject("Part::Feature", "Body")
            solid.Shape = Part.read(str(original))
        else:
            import Mesh

            mesh = Mesh.Mesh(str(original))
            pieces = mesh.getSeparateComponents() if separate_parts else [mesh]
            pieces = sorted(pieces, key=lambda m: m.CountFacets, reverse=True)
            for index, piece in enumerate(pieces):
                obj = document.addObject("Mesh::Feature", "Body" if index == 0 else f"Piece{index}")
                obj.Label = "Body" if index == 0 else f"Piece {index}"
                obj.Mesh = piece
        document.recompute()
        document.saveAs(str(target))
        record = mesh_tools.write_provenance(target, source=source, licence=licence, original=str(original))
        with contextlib.suppress(Exception):
            self.app.setActiveDocument(document.Name)
        if self.gui is not None:
            show_and_frame(self.gui, document, {o.Name for o in document.Objects})
        saved = self._versions("save", document=document.Name, note=f"as imported from {source}")
        from integrations.cadwiz_plugin.problems_watch import find_problems

        problems = [p.for_founder() for p in find_problems(document, True)]
        picture = self._capture_view(str(self.project.folder / "renders" / f"import_{int(time.time())}.png"))
        reply = {"document": document.Label, "file": str(target), "source": source, "licence": record["licence"],
                 "licence_plain": record["licence_plain"], "size": mesh_tools.size_words(mesh_tools.size_mm(document)),
                 "parts": [o.Label for o in document.Objects], "version": saved.get("version"), "problems": problems,
                 "images": [picture] if picture else []}
        if record["can_sell"] is False:
            reply["say_to_founder"] = f"Heads up: {record['licence_plain']}."
        return reply

    def _mesh_edit(self, operation: str, part: str | None = None, document: str | None = None, iterations: int = 8, factor: float = 0.5,
                   voxel_mm: float = 0.3, ratio: float = 0.5, scale: float | None = None, height_mm: float | None = None,
                   thickness_mm: float = 2.0, other: str | None = None, boolean: str = "union", base_height_mm: float = 3.0,
                   base_margin_mm: float = 3.0, base_shape: str = "round") -> dict[str, Any]:
        from integrations.cadwiz_plugin import mesh_tools

        operation = str(operation).lower().strip()
        if operation not in mesh_tools.OPERATIONS:
            raise TypeError(f"operation must be one of {', '.join(mesh_tools.OPERATIONS)}")
        target = self._document(document)
        try:
            obj = mesh_tools.part(target, part)
        except mesh_tools.MeshToolError as error:
            raise TypeError(str(error)) from None
        params: dict[str, Any] = {"operation": operation}
        what = ""
        if operation == "smooth":
            params.update(iterations=int(iterations), factor=float(factor))
            what = f"smoothed {obj.Label} ({int(iterations)} passes)"
        elif operation == "remesh":
            if not 0.02 <= float(voxel_mm) <= 10:
                raise TypeError("voxel_mm is the detail size, 0.02 to 10 mm")
            params.update(voxel_mm=float(voxel_mm))
            what = f"remeshed {obj.Label} at {voxel_mm:g} mm detail"
        elif operation == "decimate":
            if not 0.01 <= float(ratio) < 1:
                raise TypeError("ratio is the share of triangles to keep, 0.01 to 0.99")
            params.update(ratio=float(ratio))
            what = f"reduced {obj.Label} to {ratio:.0%} of its triangles"
        elif operation == "scale":
            factor_value = float(scale) if scale else None
            if height_mm:
                current = obj.Mesh.BoundBox.ZLength
                factor_value = float(height_mm) / current if current else None
            if not factor_value or factor_value <= 0:
                raise TypeError("give scale (e.g. 1.5) or height_mm (the new height)")
            params.update(factor=factor_value)
            what = f"scaled {obj.Label} by {factor_value:.3g}"
        elif operation in ("hollow", "solidify"):
            if not 0.2 <= float(thickness_mm) <= 50:
                raise TypeError("thickness_mm is the wall, 0.2 to 50 mm")
            params.update(thickness_mm=float(thickness_mm))
            what = f"{'hollowed' if operation == 'hollow' else 'gave a thickness to'} {obj.Label} with a {inches_first_words(thickness_mm)} wall"
        elif operation == "boolean":
            if boolean.lower() not in ("union", "difference", "intersect"):
                raise TypeError("boolean is union, difference or intersect")
            try:
                tool = mesh_tools.part(target, other)
            except mesh_tools.MeshToolError as error:
                raise TypeError(str(error)) from None
            if tool is obj:
                raise TypeError("other must be a different part")
            params.update(boolean=boolean.lower())
            what = f"{boolean.lower()} of {obj.Label} with {tool.Label}"
        work = Path(tempfile.mkdtemp(prefix="cadwiz-mesh-", dir=str(self.project.folder)))
        if operation == "add_base":
            size = obj.Mesh.copy()
            with contextlib.suppress(Exception):
                size.transform(obj.Placement.toMatrix())
            box = size.BoundBox
            params.update(min=[box.XMin, box.YMin, box.ZMin], max=[box.XMax, box.YMax, box.ZMax], height_mm=float(base_height_mm),
                          margin_mm=float(base_margin_mm), shape=base_shape if base_shape in ("round", "square") else "round")
            params["output"] = str(work / "base.stl")

            def change() -> str:
                mesh_tools.run_blender(params, self._pump)
                mesh_tools.add_part(target, "Base", Path(params["output"]))
                return f"added a {params['shape']} base {inches_first_words(base_height_mm)} tall under {obj.Label}"
        else:
            params["source"] = str(mesh_tools.export_part(obj, work / "in.stl"))
            if operation == "boolean":
                params["other"] = str(mesh_tools.export_part(tool, work / "other.stl"))
            params["output"] = str(work / "out.stl")

            def change() -> str:
                mesh_tools.run_blender(params, self._pump)
                mesh_tools.set_part_mesh(obj, Path(params["output"]))
                if operation == "boolean":
                    with contextlib.suppress(Exception):
                        tool.ViewObject.Visibility = False      # kept (never deleted), only hidden
                return what
        try:
            return self._mesh_change(target, f"mesh_edit {operation}", change)
        except mesh_tools.MeshToolError as error:
            raise TypeError(str(error)) from None

    def _swap_part(self, region: dict[str, Any] | None = None, replacement: str = "bone", part: str | None = None,
                   replacement_file: str | None = None, length_mm: float | None = None, thickness_mm: float | None = None,
                   document: str | None = None, keep: str = "", remove: str = "") -> dict[str, Any]:
        from integrations.cadwiz_plugin import mesh_tools

        target = self._document(document)
        try:
            obj = mesh_tools.part(target, part)
            spec = mesh_tools.region_from(dict(region or {}), self.screen.book_for(target.Name).marks)
        except mesh_tools.MeshToolError as error:
            raise TypeError(str(error)) from None
        kind = str(replacement or "none").lower()
        if kind not in mesh_tools.REPLACEMENTS and not replacement_file:
            raise TypeError(f"replacement is one of {', '.join(mesh_tools.REPLACEMENTS)}, or give replacement_file")
        if replacement_file and not Path(str(replacement_file)).is_file():
            raise TypeError("replacement_file is not a file on this computer")
        work = Path(tempfile.mkdtemp(prefix="cadwiz-swap-", dir=str(self.project.folder)))
        source = mesh_tools.export_part(obj, work / "body.stl")
        length = float(length_mm or spec["half_length_mm"] * 2)
        thickness = float(thickness_mm or max(1.0, spec["radius_mm"] * 1.8))

        def change() -> str:
            result = mesh_tools.run_mesh_job({"job": "swap", "source": str(source), "output": str(work / "body_swapped.stl"),
                                              "region": spec, "keep": keep or obj.Label, "remove": remove or "the held part"}, self._pump)
            if not result.get("ok"):
                raise mesh_tools.MeshToolError("the held part could not be taken out: " + str(result.get("why_not") or result.get("error")))
            mesh_tools.set_part_mesh(obj, Path(result["output"]))
            added = ""
            if replacement_file:
                placed = mesh_tools.run_blender({"operation": "place_file", "source": str(replacement_file), "center": spec["center"],
                                                 "output": str(work / "held.stl")}, self._pump)
                mesh_tools.add_part(target, f"Held {Path(str(replacement_file)).stem}", placed)
                added = f", and put {Path(str(replacement_file)).name} in its place as its own part"
            elif kind != "none":
                made = mesh_tools.run_blender({"operation": "make_replacement", "kind": kind, "center": spec["center"], "axis": spec["axis"],
                                               "length_mm": length, "thickness_mm": thickness, "output": str(work / "held.stl")}, self._pump)
                mesh_tools.add_part(target, f"Held {kind}", made)
                added = f", and added a {kind} {inches_first_words(length)} long in its place as its own part"
            return f"took the held part out of {obj.Label} and closed the gap{added}"

        try:
            reply = self._mesh_change(target, f"swap_part -> {kind if not replacement_file else 'file'}", change)
        except mesh_tools.MeshToolError as error:
            raise TypeError(str(error)) from None
        reply["region"] = spec
        reply["note_for_claude"] = ("The body and the held object are separate parts now: the next swap changes only the held part. "
                                    "If the new part should touch the body (it prints loose otherwise), check problems and move or "
                                    "union it (mesh_edit boolean union).")
        return reply

    def _repair_mesh(self, part: str | None = None, document: str | None = None, max_hole_edges: int = 100,
                     drop_bits_under_faces: int = 0) -> dict[str, Any]:
        from integrations.cadwiz_plugin import mesh_tools

        target = self._document(document)
        try:
            obj = mesh_tools.part(target, part)
        except mesh_tools.MeshToolError as error:
            raise TypeError(str(error)) from None
        work = Path(tempfile.mkdtemp(prefix="cadwiz-repair-", dir=str(self.project.folder)))
        source = mesh_tools.export_part(obj, work / "in.stl")
        found: dict[str, Any] = {}

        def change() -> str:
            result = mesh_tools.run_mesh_job({"job": "repair", "source": str(source), "output": str(work / "repaired.stl"),
                                              "max_hole_edges": int(max_hole_edges), "drop_bits_under_faces": int(drop_bits_under_faces)},
                                             self._pump)
            if not result.get("ok"):
                raise mesh_tools.MeshToolError("the repair did not finish: " + str(result.get("error")))
            mesh_tools.set_part_mesh(obj, Path(result["output"]))
            found.update(before=result["before"], after=result["after"])
            before, after = result["before"], result["after"]
            return (f"repaired {obj.Label}: holes {before['holes']} -> {after['holes']}, loose pieces {before['pieces']} -> {after['pieces']}, "
                    f"{'now a closed solid' if after['watertight'] else 'still not fully closed'}")

        try:
            reply = self._mesh_change(target, "repair_mesh", change)
        except mesh_tools.MeshToolError as error:
            raise TypeError(str(error)) from None
        reply.update(found)
        return reply

    def _get_selection(self, document: str | None = None) -> dict[str, Any]:
        from integrations.cadwiz_plugin.view_link import selection, selection_summary

        if self.gui is None:
            return {"selection": [], "summary": "FreeCAD has no window open, so nothing can be selected."}
        picked = selection(self.gui)
        if document:
            target = self._document(document)
            picked = [item for item in picked if item["document"] == target.Name]
        return {"selection": picked, "summary": selection_summary(picked)}

    def _mark_for_user(self, marks: list[dict[str, Any]] | None = None, clear_previous: bool = True,
                          document: str | None = None) -> dict[str, Any]:
        from ai_freecad_core.visual_communications.contracts import VisualMarkAuthor

        if not marks and not clear_previous:
            raise TypeError("give at least one mark, or clear_previous=true to take yours off their screen")
        target = self._document(document)
        # Every mark is checked before any is drawn: half a set never reaches his screen.
        resolved = [(_mark_kind(spec), self._mark_anchors(target, spec), str(spec.get("text") or "")) for spec in (marks or [])]
        book = self.screen.book_for(target.Name)
        cleared = book.clear(VisualMarkAuthor.ASSISTANT) if clear_previous else 0
        drawn = [book.add(kind, anchors, author=VisualMarkAuthor.ASSISTANT, text=text).describe() for kind, anchors, text in resolved]
        picture = ""
        if self.screen.compose is not None:
            with contextlib.suppress(Exception):
                picture = self.screen.compose()
        return {"drawn": drawn, "removed_earlier_marks": cleared, "your_marks_on_screen": len(self.screen.claude_marks(target.Name)),
                "note_for_claude": "Your marks are orange on their CADWiz screen and stay on the model as the user turns it. "
                                   "The picture is their screen with them.",
                "images": [picture] if picture and Path(picture).is_file() else []}

    def _mark_anchors(self, document: Any, spec: dict[str, Any]) -> list[Any]:
        kind = _mark_kind(spec)
        if kind == "lasso":
            points = spec.get("points") or []
            if len(points) < 3:
                raise TypeError("a lasso needs 'points': at least three places")
            return [self._where(document, p) for p in points]
        start_key = next((k for k in ("at", "on", "picture_xy", "from") if spec.get(k) is not None), None)
        if start_key is None:
            raise TypeError("say where the mark goes: 'at' [x, y, z] mm, 'on' an object or face such as 'Pad.Face6', "
                            "or 'picture_xy' [x, y] as fractions of the frame the user showed you")
        start = self._picture_point(spec["picture_xy"]) if start_key == "picture_xy" else self._where(document, spec[start_key])
        if kind in ("point", "note"):
            return [start]
        if kind == "circle":
            from ai_freecad_core.visual_communications.anchored import ModelAnchor

            radius = float(spec.get("radius_mm") or 5.0)
            if radius <= 0:
                raise TypeError("radius_mm must be more than 0")
            camera, _aspect = self._camera_now()
            right = camera.right if camera is not None else (1.0, 0.0, 0.0)
            rim = tuple(start.point[i] + right[i] * radius for i in range(3))
            return [start, ModelAnchor(rim, start.obj, start.element, start.on_model)]  # type: ignore[arg-type]
        if spec.get("to") is None:
            if kind in ("box", "highlight") and isinstance(spec.get(start_key), str):
                return self._element_corners(document, str(spec[start_key]))
            raise TypeError(f"a {kind} needs 'to' as well: where it ends")
        return [start, self._where(document, spec["to"])]

    def _where(self, document: Any, value: Any) -> Any:
        from ai_freecad_core.visual_communications.anchored import ModelAnchor
        from integrations.cadwiz_plugin import view_link

        if isinstance(value, dict):
            if value.get("picture_xy") is not None:
                return self._picture_point(value["picture_xy"])
            for key in ("at", "on"):
                if value.get(key) is not None:
                    return self._where(document, value[key])
            raise TypeError("a place is 'at' [x, y, z] mm, 'on' an object or face, or 'picture_xy' [x, y]")
        if isinstance(value, str):
            try:
                return view_link.resolve(document, value)
            except ValueError as error:
                raise TypeError(str(error)) from None
            except Exception as error:  # noqa: BLE001 - a face that does not exist, etc.
                raise TypeError(f"could not find {value!r} on the model: {error}") from None
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return ModelAnchor(tuple(float(c) for c in value), on_model=True)  # type: ignore[arg-type]
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return self._picture_point(value)
        raise TypeError(f"could not read {value!r} as a place on the model")

    def _picture_point(self, value: Any) -> Any:
        from ai_freecad_core.visual_communications.anchored import ModelAnchor
        from integrations.cadwiz_plugin import view_link

        try:
            u, v = (float(value[0]), float(value[1]))
        except (TypeError, ValueError, IndexError):
            raise TypeError("picture_xy is two fractions, across and down the picture the user showed you") from None
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            raise TypeError("picture_xy is two fractions from 0 to 1 across and down the picture the user showed you")
        camera, aspect = self.screen.frozen_camera()
        live, live_aspect = self._camera_now()
        if camera is None:
            camera, aspect = live, live_aspect
        if camera is None:
            raise TypeError("there is no picture to place that on yet: use 'at' or 'on' instead")
        view = view_link.active_view(self.gui) if self.gui is not None else None
        if view is not None and live is not None and live.to_dict() == camera.to_dict():
            return view_link.pick(view, camera, u, v, aspect)     # the view he froze is still on screen: find the surface
        return ModelAnchor(camera.point_at_focus(u, v, aspect))

    def _camera_now(self) -> tuple[Any, float]:
        if self.screen.current_view is not None:
            with contextlib.suppress(Exception):
                return self.screen.current_view()
        from integrations.cadwiz_plugin import view_link

        view = view_link.active_view(self.gui) if self.gui is not None else None
        return (view_link.read_camera(view) if view is not None else None), 1.0

    def _element_corners(self, document: Any, where: str) -> list[Any]:
        """A box or highlight 'on' a face with no far corner: the face's own outline
        (so a highlight paints that face as it looks from any side), else the
        corners of the box around the face, edge or object."""
        from ai_freecad_core.visual_communications.anchored import ModelAnchor
        from integrations.cadwiz_plugin import view_link

        try:
            centre = view_link.resolve(document, where)
            obj = document.getObject(centre.obj)
            shape = obj.Shape.getElement(centre.element) if centre.element else obj.Shape
            box = shape.BoundBox
        except Exception as error:  # noqa: BLE001
            raise TypeError(f"could not find {where!r} on the model: {error}") from None
        if centre.element.startswith("Face"):
            with contextlib.suppress(Exception):
                points = list(shape.OuterWire.discretize(Number=48))
                parent = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
                if parent is not None:
                    placement = parent.getGlobalPlacement()
                    points = [placement.multVec(p) for p in points]
                if len(points) >= 3:
                    return [ModelAnchor((float(p.x), float(p.y), float(p.z)), centre.obj, centre.element, True) for p in points]
        return [ModelAnchor((box.XMin, box.YMin, box.ZMin), centre.obj, centre.element, True),
                ModelAnchor((box.XMax, box.YMax, box.ZMax), centre.obj, centre.element, True)]


#: The kinds Claude can draw (the founder's toolbar has the same eight).
_MARK_KINDS = ("point", "circle", "box", "highlight", "lasso", "arrow", "measure", "note")
_MARK_ALIASES = {"rectangle": "box", "rect": "box", "measurement": "measure", "label": "note", "pin": "point", "dot": "point"}


def _mark_kind(spec: Any) -> str:
    if not isinstance(spec, dict):
        raise TypeError('each mark is an object such as {"kind": "circle", "on": "Pad.Face6", "radius_mm": 5}')
    kind = str(spec.get("kind") or "point").lower().strip()
    kind = _MARK_ALIASES.get(kind, kind)
    if kind not in _MARK_KINDS:
        raise TypeError(f"mark kind {kind!r} is not one of {', '.join(_MARK_KINDS)}")
    return kind


class _ScriptFailed(Exception):
    """Claude's own FreeCAD code failed: the exact error and line go back to Claude."""


def _section(executor: Any, label: str, opening: str | None, height_mm: float | None) -> dict[str, Any]:
    result = executor.section(height_mm, opening, label)
    return result


def _describe_object(obj: Any) -> dict[str, Any]:
    type_id = str(getattr(obj, "TypeId", ""))
    entry: dict[str, Any] = {"name": getattr(obj, "Name", ""), "label": getattr(obj, "Label", ""), "type": type_id,
                             "visible": bool(getattr(obj, "Visibility", True))}
    if type_id.startswith("Sketcher::"):
        constraints = list(getattr(obj, "Constraints", []) or [])
        entry["constraints"] = len(constraints)
        entry["named_constraints"] = [c.Name for c in constraints if getattr(c, "Name", "")]
    elif type_id.startswith("Spreadsheet::"):
        with contextlib.suppress(Exception):
            entry["aliases"] = [obj.getAlias(cell) for cell in obj.getUsedCells() if obj.getAlias(cell)]
    elif type_id.startswith(("PartDesign::", "Part::Box", "Part::Cylinder", "Part::Cone", "Part::Sphere", "Part::Torus", "Part::Extrusion",
                             "Part::Revolution", "Part::Loft", "Part::Sweep", "Part::Thickness", "Part::Fillet", "Part::Chamfer", "Part::Cut",
                             "Part::Fuse", "Part::Common")):
        entry["parametric"] = True
    elif type_id == "Part::Feature":
        entry["parametric"] = False
    shape = getattr(obj, "Shape", None)
    with contextlib.suppress(Exception):
        if shape is not None and not shape.isNull():
            from integrations.ai_master.shape_box import tight_box

            box = tight_box(shape)
            entry["size"] = f"{both(box.XLength)} x {both(box.YLength)} x {both(box.ZLength)}"
    return entry


def visible_in_file(path: str | Path) -> set[str]:
    """The objects a saved FreeCAD file marks visible that have no window state of
    their own -- the ones his FreeCAD would otherwise open hidden.

    A change is built in the windowless worker, so what it adds has no entry in the
    file's window state (GuiDocument.xml, absent altogether for a new document); his
    FreeCAD opened those with the new shape hidden, and he had to find it and press
    Space (ORDER-2026-10-15-01). Objects that DO have window state keep his own
    choice: something he hid stays hidden.

    What went INTO another shape stays hidden, as FreeCAD's window would leave it:
    a cut's sphere and tool, the sketch a pad was made from. The windowless worker
    never hides them, and on 2026-10-19 a tennis ball arrived with its plain sphere
    and seam tube showing too -- three heavy shapes to draw, and overlapping ones
    for the Problems check to grind on (ORDER-2026-10-19-03)."""
    import zipfile
    from xml.etree import ElementTree

    try:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("Document.xml"))
            names = archive.namelist()
            window = ElementTree.fromstring(archive.read("GuiDocument.xml")) if "GuiDocument.xml" in names else None
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return set()
    has_window_state = {str(vp.get("name")) for vp in window.iter("ViewProvider")} if window is not None else set()
    consumed = _consumed_by_another_shape(root)
    shown: set[str] = set()
    for data in root.iter("ObjectData"):
        for obj in data.iter("Object"):
            name = str(obj.get("name"))
            if name in has_window_state or name in consumed:
                continue
            for prop in obj.iter("Property"):
                if prop.get("name") == "Visibility":
                    flag = prop.find("Bool")
                    if flag is not None and flag.get("value") == "true":
                        shown.add(name)
    return shown


#: The links through which a shape feature uses up another shape (Part booleans,
#: extrusions, lofts, sweeps, fillets, mirrors, offsets; PartDesign features).
#: Attachments, external geometry, groups and a Body's Tip are NOT among them: a
#: sketch attached to a pad's face does not hide the pad.
CONSUMING_LINKS = frozenset({"Base", "Tool", "Shapes", "Source", "Sections", "Spine", "Profile", "BaseFeature"})
#: Objects that hold or point at others without being made from them.
NOT_SHAPE_MAKERS = ("App::", "PartDesign::Body", "Spreadsheet::", "Sketcher::", "PartDesign::Plane", "PartDesign::Line",
                    "PartDesign::Point", "PartDesign::CoordinateSystem", "PartDesign::ShapeBinder", "PartDesign::SubShapeBinder")


def _consumed_by_another_shape(root: Any) -> set[str]:
    types = {str(o.get("name")): str(o.get("type") or "") for objects in root.iter("Objects") for o in objects.iter("Object")}
    consumed: set[str] = set()
    for data in root.iter("ObjectData"):
        for obj in data.iter("Object"):
            if types.get(str(obj.get("name")), "").startswith(NOT_SHAPE_MAKERS):
                continue
            for prop in obj.iter("Property"):
                if prop.get("name") not in CONSUMING_LINKS:
                    continue
                for link in prop.iter():
                    # <Link value=".."/>, <LinkSub value=".."/>; inside a LinkSubList, <Link obj=".."/>.
                    target = (link.get("value") or link.get("obj")) if link.tag in ("Link", "LinkSub") else None
                    if target:
                        consumed.add(str(target))
    return consumed


def show_and_frame(gui: Any, document: Any, shown: set[str]) -> None:
    """Make `shown` visible in his window, bring the document's 3D view to the front,
    turn it to the iso view and fit the model in it. Each step is best effort: a view
    that cannot be turned must never cost him the change itself."""
    for name in sorted(shown or ()):
        obj = document.getObject(name) if hasattr(document, "getObject") else None
        if obj is None:
            continue
        with contextlib.suppress(Exception):
            obj.Visibility = True
        with contextlib.suppress(Exception):
            obj.ViewObject.Visibility = True
    with contextlib.suppress(Exception):
        gui.setActiveDocument(document.Name)
    view = None
    with contextlib.suppress(Exception):
        view = gui.getDocument(document.Name).ActiveView
    if view is None:
        with contextlib.suppress(Exception):
            view = gui.ActiveDocument.ActiveView
    if view is None:
        return
    with contextlib.suppress(Exception):
        view.viewIsometric()
    with contextlib.suppress(Exception):
        view.fitAll()


def inches_first_words(mm: float) -> str:
    from ai_freecad_core.visual_communications.anchored import inches_first

    return inches_first(float(mm))


def _safe_doc_name(text: str) -> str:
    cleaned = "".join(c if c.isalnum() else "_" for c in text.strip())[:40].strip("_")
    return cleaned or "Design"


def _adopted_executor(project: Any, name: str, file_name: str, **hooks: Any) -> Any:
    from integrations.ai_master.adopted_executor import AdoptedExecutor

    return AdoptedExecutor(project, name, file_name, pump=hooks.get("pump"), snapshot_open=hooks.get("snapshot_open"),
                           reload=hooks.get("reload"), current_view=hooks.get("current_view"))
