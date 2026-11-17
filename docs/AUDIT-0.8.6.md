# Beta 0.8.6 corrective-action audit

## Findings

The active October AI-master path lets the frontier assistant choose and submit FreeCAD Python through build_model/edit_object. It is not a mechanical-versus-nonmechanical classifier or a compiler choosing a safe construction automatically. Earlier prompt language encouraged native features for engineered parts, but the acceptance path chiefly checked that a shape existed and was valid. The existing fact layer also promoted a native-looking tree and named parameters without proving that they drove geometry. A successful-looking solid could therefore be saved without native editability. No evidence establishes the exact prompt, assistant decision or failed attempt used in Neil's original session; that generation transcript is unavailable. We do not attribute a specific fallback to that session.

The supplied clamp confirms two Body containers with one fixed PartDesign::Feature each, no Sketcher history, no pads/pockets and no expression-linked spreadsheet aliases. It is E1. No label or workbook can recover absent construction history. The private model is excluded from the public package.

## Corrections and architecture

The frontier assistant remains the designer and FreeCAD remains authoritative. The existing design contract, worker, fact layer and version store are used. parametric_checks adds evidence to that path; no retired compiler or competing geometry engine is introduced.

E0 means mesh/no solid, E1 direct solid, E2 functional native construction without verified named driving edits, E3 native fully constrained construction with real driving changes surviving reopen. E4 still requires separate relationship/fit evidence. Fixed bases prevent a fully editable classification. A populated spreadsheet is not evidence unless aliases occur in expressions and mutations change final geometry.

The production adopted executor checks worker health and objective requirements before promoting the candidate into the accepted file/version. The worker saves/reopens a disposable candidate, mutates up to twelve candidate dimensions until three successful probes cover every final component (or candidates are exhausted), checks downstream validity and unaffected components, and discards probes. Health certificates expire when relevant construction/geometry changes. These are bounded tests, not a universal guarantee. Direct-solid exceptions remain explicit and disclosed, including after reopening their saved metadata.

Presentation hides only construction on owned models automatically and preserves deliberately visible references. Explicit Clean model view can hide references on older models. Only the current Tip is shown, avoiding overlapping pre-cut features. A construction-visibility control preserves data rather than deleting origins.

Docking now explicitly reattaches right, guards cramped placements, and exposes Reset CADWiz Layout. Folder selection now changes the live session and persists atomically; default/new-folder labels distinguish the current file. Registered historical roots preserve discovery of earlier version stores. Safe labels avoid accidental filename collisions.

## Validation

- 200 unit/integration tests passed; three optional tests skipped. Lint, egress allowlist and all 176 module imports passed.
- Real FreeCAD 1.1.3 headless tests: constrained four-hole plate; width/diameter edits; dependent bracket; two-component clamp fixture; save/reopen; correct hole count; hidden origins/current Tip; deliberate references preserved; fake-parametric and broken dependencies detected.
- Production PluginSession through sandbox worker: native build and named edit accepted; flattened replacement rejected without accepted-file changes; unsaved health snapshot preserved; objective mismatch blocked; direct solid refused until an explicit exception is recorded and returned.
- Actual Qt component test: repeated floating/right return, cramped top recovery, Reset Layout and Setup controls. This is an offscreen widget check, not a claim of manual macOS testing.
- CI native scripts terminate explicitly with failure status even when FreeCAD would otherwise swallow a Python exception.

The existing installed application reload path was exercised using a disposable 40-to-45 mm plate edit in PID 22092. Current-view rendering showed the changed geometry, and GUI process IDs 22092, 83452 and 94824 were unchanged. All earlier user documents were preserved. Candidate strict acceptance was tested separately through the real headless PluginSession; the installed UI was not hot-replaced while user work was open. Native file opening now falls back to App.openDocument in the same process when Gui.open does not load the file; a regression covers that branch. Full Windows desktop capture was unavailable in this session; the native current-view image and actual Qt component checks support the narrower display/layout claims. Public beta publication requires exact-commit CI success. Live evidence and final release checks are saved in the release delivery audit.

## Known limits

No automatic inverse reconstruction is claimed. No physical fit, load or print tests, no physical Mac GUI session, no broad natural-language AI benchmark, and no E4 fit guarantee were performed. Complex models can fail the stricter gate and need assistant correction. The original clamp's sheet/geometry bore discrepancy and its reconstructed smooth loft are documented with the private delivered model, not silently altered.
