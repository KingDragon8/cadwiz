# Efficient, evidence-based CAD workflow

Keep a compact project record containing the authoritative file, confirmed
dimensions, assumptions, construction decisions, completed checks and unresolved
items. Refresh it after meaningful changes. Use it for project handoff rather
than repeatedly loading unrelated conversation history. Do not create a new
user chat automatically.

Prefer the connected CAD tools in the existing FreeCAD window. Prototype the
risky feature first: for gears, qualify one tooth form and a helical half before
detailing an enclosure. Kernel validity alone does not establish surface quality.
Inspect actual generated geometry, including regions between construction inputs.

Batch independent reads. Have long-running workers write bounded progress and a
completion result. Keep full logs, XML and geometry arrays on disk; return short
summaries and targeted images. Do not repeatedly retry the same failed UI action
without new evidence. Use focused checks during iteration and broader regression
checks at the release gate. Preserve native viewport verification, backups and
required geometry checks; reduce repetition rather than omitting evidence.

Never call a preview physical simulation or label a model ready for manufacture
solely because it rebuilds or animates. Report measured scope and remaining limits.
