# Safe document and dimensional operations

Use **Working file — create a variant or edit this document** on the home panel
to choose the exact original file and a separately named working copy. Keep the
source saved before making a file-based variant. CADWiz preserves the source and
protects other documents while that operation is active. The panel identifies
the working file, protected source, and last operation status.

Your assistant can use `document_operation` to establish the same explicit
operation. Once a target is protected, changing that authority requires your
Working file button. A label shared by several files is ambiguous; use an exact
document Name or full file path. Window focus alone does not authorize a target.

Point and Highlight keep their existing behavior. Frozen frames additionally
carry native geometry references where a mark actually lands on a face or edge.
A visual annotation without a native reference remains a visual annotation.
References include document revision, placement, geometry type and dimensions.
After recompute, CADWiz accepts only a unique geometric re-resolution; otherwise
select the intended feature again.

For a supported annular groove or ridge, the assistant uses `resolve_geometry`
and `annular_edit`. Inward widening lowers the inner radius and preserves the
outer radius. Outward widening raises the outer radius and preserves the inner
radius. Radial and diametric amounts are distinct. Depth changes are separate,
explicit requests. The current deterministic operation supports one-sided,
explicit-length native Pocket/Pad features driven by two concentric complete
circles. It can add a driving radius to a valid underconstrained circle without
rebuilding the whole part. Other geometry is classified unsupported for this
operation; ordinary tools remain available with their actual verification limits.

CADWiz measures actual cylindrical B-rep walls and compares the complete result
against the authorized material change. The default dimensional tolerance is
0.001 mm; the whole-solid symmetric material difference tolerance is 0.001 mm³.
These are verification tolerances, not claims about printer accuracy. Curved
boundaries, unrelated bodies, feature history and save/reopen results must pass.
A rejected worker copy never replaces the last accepted user file.

`VERIFIED SUCCESS` applies to the supported operation and its recorded evidence.
An ordinary script completing is `PARTIALLY VERIFIED`; it does not establish that
the assistant interpreted a requested dimension correctly. Unresolved targets,
unsupported operations, failed verification and rollback have separate statuses.
The same unsuccessful annular intent on an unchanged revision is not run again.

To repeat Neil's acceptance workflow, keep Variant B active, select Variant A as
the exact source, create a separate variant, point to the annular groove, and
request an inward 0.8 mm radial widening. Require an inner radius delta of
−0.800 mm, outer radius delta of 0.000 mm, unchanged source and shaft opening,
preserved curvature/history and successful native save/reopen checks. Request
any mating-ridge clearance or depth change separately and inspect the assembled
clearance. The permanent native suite uses representative fixtures; it does not
claim to test Neil's original files when those files are unavailable.
