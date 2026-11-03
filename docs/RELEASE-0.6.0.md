# CADWiz 0.6.0

The owner authorized implementation, GitHub publication and website activation on November 3, 2026. Publication after isolated checks was explicitly approved in place of the clean-laptop witness gate. The current live installation and assistant settings are not the test target.

## Delivered changes

- FreeCAD Addon Manager custom-repository route; official catalog listing is not claimed. The catalog request was closed pending its mandatory 30-day waiting period.
- A validated Claude `.mcpb` with a small Node launcher starts the existing Python connector through an offline bootstrap.
- Pinned, hashed Python 3.11 dependency bundles for Windows x64, macOS Apple Silicon/Intel and Linux x64. Native dependencies and their license notices remain in the wheel archives. Mac real-device installation is unverified.
- Explicit OpenAI/Codex setup preview, exact settings backup, scoped entry replacement, manual copy controls and undo that preserves unrelated later changes.
- Legacy Claude entry migration with backup/undo, including Store-install settings discovery. Claude's own extension installation screen remains under Claude's control.
- Background local startup checks, controlled repair of previously owned entries, offline damaged-helper recovery, and preservation/undo of positively identified duplicate CADWiz folders. Missing heartbeats never justify rewriting settings.
- Immediate screen-space mark preview, geometry snapshots and cancellable background picking. Camera/document changes reject stale results. Undo/Clear cancel a pending mark. The nearest-hit face lookup optimization is included.
- Exports capture the live model, including unsaved manual edits, as a version before export. Each export includes a source/version/dimensions manifest. Slicer verification is explicitly separate.
- Render results identify their document, version and view type. Reopening an already-open file explicitly reports that it was not reloaded. Inspection explains that edit scripts execute without window APIs.
- Workshop preferences can be saved through the assistant. The slicer field already existed.

## Local evidence

No paid model calls were used. Tests use protocol clients, stand-ins and a separate native FreeCAD process.

- Full local suite: 157 passed, 2 skipped (platform/optional cases), with one upstream SDK warning.
- Both launch routes: real MCP initialize/tool-list exchange through the Node launcher and the direct OpenAI Python launcher using FreeCAD's Python, with private helpers.
- Native FreeCAD 1.1.3 imports and model inspection: passed.
- Native panel test: point handler returned immediately, preview queued, mark anchored. Most recent simple-box pick was 0.016 seconds; maximum sampled event-loop gap was 32 ms. These are a reference test, not a guarantee for every model.
- Native export: an unsaved width change from 40 to 55 mm produced a 55 mm STL and a matching manifest.
- Offline clean setup and damaged-helper recovery are tested with socket connections forbidden. Concurrent first starts share an operating-system lock.
- Lint, module imports and network allowlist checks pass locally.
- Download page: desktop and 390-pixel layouts, both assistant choices and computer switch tested. No horizontal overflow or browser script errors.

The website release has its own tests and deployment evidence. CI results and public artifact verification must be recorded by the release operator before reporting publication complete.

## Scope limits

No real Mac installation, hosted assistant sign-in, or clean-laptop owner witness is claimed. Mechanism guidance requires checking all surrounding parts; it does not add a physics engine. Slicer manifests do not certify printer settings or physical strength. Automatic repair stops on foreign settings changes or repeated failure.
