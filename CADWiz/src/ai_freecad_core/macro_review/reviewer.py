# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Deterministic prohibited-operations review of model-generated Python.

`docs/ASCENT-ARCHITECTURE.md` L4 specifies "generated macro -> prohibited-
operations review -> protected-copy execution". The review step did not exist
in code (verified 2026-09-05, Phase 0 reconciliation §D.5) while
`execute_python`, `safe_execute`, `create_macro` and `run_macro` were all in the
model's tool catalogue and executed inside FreeCAD's own process. This is that
step.

**What this is, and what it is not.** It is a deterministic static review: an
allowlist of importable modules, plus a denylist of the constructs that reach
past an import allowlist. It is *not* a sandbox and does not prove a macro is
safe. It raises the bar from "anything the model writes runs" to "the known
escape shapes are refused, in the open, with a reason." Anyone reading a PASS
here should read it as "nothing prohibited was found", never as "this is safe".
The real containment story is process isolation, which founder decision 5
(2026-09-05) deliberately deferred past beta.

**Why an allowlist of imports is the primary control.** Denying `os.remove`,
`shutil.rmtree` and their hundred cousins by name is a losing game and produces
false positives on innocent code - `replace`, `remove` and `write` are ordinary
method names. Denying the *import* of `os`, `shutil`, `subprocess`, `socket`
and the rest reaches all of them at once, and is checkable. The denylist then
only has to cover what needs no import: the builtins that execute strings, and
the dunder attributes that walk from any object back to `__builtins__`.

Analysis is over the AST, never over the text. A regex over source is defeated
by a line continuation, a comment, or an alias; `ast.parse` is not.
"""

from __future__ import annotations

import ast

from .contracts import Finding, MacroReview, ReviewOutcome

#: Modules a generated CAD macro may import.
#:
#: The FreeCAD surface a macro actually builds with, plus pure-computation
#: modules that cannot touch the filesystem, the network, or another process.
#:
#: `Mesh`, `Import` and `ImportGui` are deliberately absent even though they are
#: FreeCAD's own: each writes files. Export is a real need and it already has
#: reviewed tools (`export_stl`, `export_step`, `export_obj`, `export_iges`), so
#: a macro does not have to be the thing that writes to disk. Adding one here
#: later is a policy change and needs a test that says why.
ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {
        # FreeCAD, as a macro sees it.
        "FreeCAD",
        "App",
        "FreeCADGui",
        "Gui",
        "Part",
        "PartDesign",
        "Sketcher",
        "Draft",
        "BOPTools",
        "DraftVecUtils",
        # Computation only. None of these can open a file or a socket.
        "math",
        "cmath",
        "statistics",
        "decimal",
        "fractions",
        "itertools",
        "functools",
        "operator",
        "collections",
        "dataclasses",
        "enum",
        "typing",
        "re",
        "uuid",
        "random",
    }
)

#: Builtins that execute a string, reach the interpreter's own namespaces, or
#: open a handle. None of them needs an import, so the allowlist above cannot
#: reach them. `os`/`subprocess`/network access is covered by ALLOWED_IMPORTS
#: above (nothing that opens a file, a process or a socket can be imported at
#: all); `__import__`, `eval`, `exec` and `compile` are the dynamic-import/
#: dynamic-code-execution route, and stay blocked unconditionally.
PROHIBITED_CALLS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "globals",
        "locals",
        "vars",
        "open",
        "input",
        "breakpoint",
        "exit",
        "quit",
    }
)

#: `getattr`/`setattr`/`delattr` with a NAMED, statically-visible attribute
#: are ordinary, legitimate FreeCAD/Part/PartDesign/Sketcher scripting
#: (parametric property access -- `setattr(obj, "Length", 40)` is idiomatic
#: FreeCAD, not an escape attempt). Founder ruling, ORDER-2026-09-27-06
#: ruling 3 (2026-09-28): loosen the fence for this legitimate usage while
#: keeping the one real risk these calls create -- reaching a dunder
#: attribute (`__globals__`, `__subclasses__`, `__class__`, `__mro__`, ...)
#: through a string argument that `visit_Attribute` below cannot see,
#: since it is a call argument, not a static `.attr` access. Any call to
#: one of these three names whose attribute-name argument is a STRING
#: LITERAL starting with `__` is still refused; a literal that does not,
#: or a fully dynamic (non-literal) name, is allowed. This does not
#: reopen the escape by itself -- reaching a dunder via a name computed at
#: runtime is a materially higher bar than the direct literal this
#: closes, and CLAUDE.md's own framing stands: this is a static review
#: that raises the bar, never a sandbox or a safety proof.
DYNAMIC_ATTRIBUTE_CALLS: frozenset[str] = frozenset({"getattr", "setattr", "delattr"})

#: Document-destroying FreeCAD APIs. A macro may build, cut and modify; closing
#: or removing the user's document is not a modelling operation, and the product
#: has reviewed tools for it. Matched on the attribute name, which is how these
#: are always written (`FreeCAD.closeDocument(...)`, `App.removeDocument(...)`).
PROHIBITED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "closeDocument",
        "removeDocument",
        "deleteDocument",
    }
)

#: Plain-language wording for each rule, for the tester who sees the refusal.
#: Written to answer three things in one breath: what it tried to do, why that
#: is not allowed, and whether their model is safe. Founder ruling 2026-09-06.
#:
#: No rule ids, no line numbers, no Python vocabulary. Someone who asked for a
#: phone stand should be able to read this and know where they stand.
_PLAIN = {
    "MR-001": (
        "CADWiz wrote a step that tried to load {symbol}, which can reach files, "
        "programs or the network outside your design. It was not run, and nothing "
        "in your model changed."
    ),
    "MR-002": (
        "CADWiz wrote a step that tried to use {symbol}, which can run code or open "
        "files that CADWiz has not checked. It was not run, and nothing in your "
        "model changed."
    ),
    "MR-003": (
        "CADWiz wrote a step that tried to reach inside Python itself, which is how "
        "a safety check gets bypassed. It was not run, and nothing in your model "
        "changed."
    ),
    "MR-004": (
        "CADWiz wrote a step that tried to close or delete your document rather "
        "than change the model in it. It was not run, and your document is "
        "untouched."
    ),
    "MR-006": (
        "CADWiz wrote a step that tried to load code from inside CADWiz's own "
        "files. It was not run, and nothing in your model changed."
    ),
    "MR-007": (
        "CADWiz wrote a step that tried to reach inside Python itself through "
        "{symbol}, which is how a safety check gets bypassed. It was not run, "
        "and nothing in your model changed."
    ),
}


def _plain(rule_id: str, symbol: str) -> str:
    """The tester-facing wording for one finding."""
    template = _PLAIN.get(
        rule_id,
        "CADWiz stopped a step it generated because it was not safe to run. "
        "Nothing in your model changed.",
    )
    return template.format(symbol=f"'{symbol}'" if symbol else "something")


_RULE_IMPORT = "MR-001"
_RULE_CALL = "MR-002"
_RULE_DUNDER = "MR-003"
_RULE_DOCUMENT = "MR-004"
_RULE_SYNTAX = "MR-005"
_RULE_RELATIVE_IMPORT = "MR-006"
_RULE_DYNAMIC_DUNDER = "MR-007"

#: ORDER-2026-09-30-01, Fix 3 ("CLOSE THE SAFETY-FENCE GAP"): manually
#: combined from commit `d2f9863` (`security/macro-review-reflection-audit`,
#: never merged -- a real trial merge found this file rewritten on both
#: sides since their common ancestor: main added the getattr/setattr/
#: delattr loosening above [ORDER-2026-09-27-06 ruling 3], the branch
#: added this operator-reflection check, neither aware of the other).
#: `operator.attrgetter`/`itemgetter`/`methodcaller` reach an object's
#: attributes exactly like `getattr` does, but as a VALUE (a callable)
#: rather than a direct call -- `attrgetter('__class__')(obj)` walks to the
#: same dunder `visit_Attribute` above cannot see, since the attribute name
#: is a string argument, not a static `.attr` access, and `visit_Call`'s
#: dunder-literal check above only inspects `getattr`/`setattr`/`delattr`
#: themselves, never `operator`'s equivalents. This closes that route
#: without touching the getattr/setattr/delattr ruling at all -- the two
#: are independent escape shapes through the same static-review gap, kept
#: side by side rather than one replacing the other.
_OPERATOR_REFLECTION_HELPERS: frozenset[str] = frozenset(
    {"attrgetter", "itemgetter", "methodcaller"}
)


def _static_string(node: ast.AST, constants: dict[str, str]) -> str | None:
    """Resolve literals and simple string concatenation without evaluating code."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left, constants)
        right = _static_string(node.right, constants)
        if left is not None and right is not None:
            return left + right
    return None


def _has_dunder_component(value: str) -> bool:
    """Whether a dotted reflective path names Python interpreter internals."""
    return any(component.startswith("__") for component in value.split("."))


class _Visitor(ast.NodeVisitor):
    """Walk the tree once, collecting every finding rather than the first.

    All of them, deliberately: a caller that fixes one prohibited call and
    resubmits should not discover the next one on the next round trip. The
    refusal names everything wrong with the macro at once.
    """

    def __init__(self) -> None:
        self.findings: list[Finding] = []
        # Operator-reflection tracking (Fix 3, above): a real, if crude,
        # static alias-following -- an `import operator as op` or
        # `from operator import attrgetter as ag` still has to resolve back
        # to `_OPERATOR_REFLECTION_HELPERS` for the check below to fire.
        self._operator_aliases: set[str] = set()
        self._operator_helpers: dict[str, str] = {}
        self._string_constants: dict[str, str] = {}
        self._direct_helper_references: set[int] = set()
        self._operator_attribute_bases: set[int] = set()

    def _add(self, rule_id: str, symbol: str, node: ast.AST, message: str) -> None:
        self.findings.append(
            Finding(
                rule_id,
                symbol,
                getattr(node, "lineno", 0),
                message,
                plain=_plain(rule_id, symbol),
            )
        )

    # ---- imports ------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802 - ast API
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root not in ALLOWED_IMPORTS:
                self._add(
                    _RULE_IMPORT,
                    alias.name,
                    node,
                    f"import of {alias.name!r} is not permitted in a generated macro",
                )
            elif alias.name == "operator":
                self._operator_aliases.add(alias.asname or "operator")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802 - ast API
        if node.level:
            # `from . import x` inside a macro means the macro is reaching into
            # a package layout it has no business knowing.
            self._add(
                _RULE_RELATIVE_IMPORT,
                "." * node.level + (node.module or ""),
                node,
                "relative imports are not permitted in a generated macro",
            )
        elif (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
            self._add(
                _RULE_IMPORT,
                node.module or "?",
                node,
                f"import from {node.module!r} is not permitted in a generated macro",
            )
        elif node.module == "operator":
            for alias in node.names:
                if alias.name in _OPERATOR_REFLECTION_HELPERS:
                    self._operator_helpers[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    # ---- simple bindings (Fix 3: alias-following for operator helpers) --
    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802 - ast API
        value = _static_string(node.value, self._string_constants)
        helper = self._operator_helper(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                if value is None:
                    self._string_constants.pop(target.id, None)
                else:
                    self._string_constants[target.id] = value
                if helper is None:
                    self._operator_helpers.pop(target.id, None)
                else:
                    self._operator_helpers[target.id] = helper
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802 - ast API
        if isinstance(node.target, ast.Name):
            value = (
                _static_string(node.value, self._string_constants)
                if node.value is not None
                else None
            )
            if value is None:
                self._string_constants.pop(node.target.id, None)
            else:
                self._string_constants[node.target.id] = value
        self.generic_visit(node)

    def _operator_helper(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self._operator_helpers.get(node.id)
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in self._operator_aliases
            and node.attr in _OPERATOR_REFLECTION_HELPERS
        ):
            return node.attr
        return None

    # ---- calls --------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast API
        target = node.func
        if isinstance(target, ast.Name):
            if target.id in PROHIBITED_CALLS:
                # Reported here, at the Call node, for the clearer "call to
                # X()" wording -- `_direct_helper_references` stops
                # `visit_Name` (Fix 3, below) from reporting the exact same
                # Name node a second time as it generically-visits into
                # `node.func`.
                self._direct_helper_references.add(id(target))
                self._add(
                    _RULE_CALL,
                    target.id,
                    node,
                    f"call to {target.id}() is not permitted in a generated macro",
                )
            elif target.id in DYNAMIC_ATTRIBUTE_CALLS and self._names_a_dunder(node):
                self._add(
                    _RULE_DYNAMIC_DUNDER,
                    f"{target.id}(...)",
                    node,
                    f"call to {target.id}() naming a dunder attribute is not permitted",
                )
        helper = self._operator_helper(target)
        if helper is not None:
            self._direct_helper_references.add(id(target))
            self._review_operator_helper(helper, node)
        self.generic_visit(node)

    @staticmethod
    def _names_a_dunder(node: ast.Call) -> bool:
        """True only for a STRING-LITERAL attribute-name argument starting
        with `__` -- a fully dynamic (non-literal) name cannot be checked
        statically and is allowed, per the ruling this enforces."""
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("__"):
                return True
        return False

    def _review_operator_helper(self, helper: str, node: ast.Call) -> None:
        """Fix 3: the same dunder-literal / fully-dynamic distinction the
        getattr/setattr/delattr ruling above applies, extended to
        `operator.attrgetter`/`itemgetter`/`methodcaller` -- a literal
        dunder component is refused, a resolvable non-dunder literal is
        allowed, and (stricter than the builtins above, since these two
        helpers exist almost solely for reflection, not ordinary FreeCAD
        property access) a fully dynamic name is refused for `attrgetter`/
        `methodcaller`. `itemgetter` is exempted from that stricter part --
        `itemgetter('width')` on an ordinary dict of dimensions is normal
        computation, not a reflection primitive.
        """
        if not node.args:
            return
        arguments = node.args if helper in {"attrgetter", "itemgetter"} else node.args[:1]
        for argument in arguments:
            value = _static_string(argument, self._string_constants)
            if value is None:
                if helper in {"attrgetter", "methodcaller"}:
                    self._add(
                        _RULE_DUNDER,
                        f"operator.{helper}",
                        argument,
                        f"dynamic names passed to operator.{helper} are not permitted",
                    )
                continue
            if _has_dunder_component(value):
                self._add(
                    _RULE_DUNDER,
                    value,
                    argument,
                    f"indirect access to {value!r} through operator.{helper} is not permitted",
                )

    # ---- attributes ---------------------------------------------------
    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802 - ast API
        if node.attr.startswith("__"):
            # Every documented escape from a restricted namespace runs through
            # one of these - __globals__, __subclasses__, __class__, __mro__.
            # Denying the shape rather than the list means a new one does not
            # need a new rule.
            self._add(
                _RULE_DUNDER,
                node.attr,
                node,
                f"access to the dunder attribute {node.attr!r} is not permitted",
            )
        elif node.attr in PROHIBITED_ATTRIBUTES:
            self._add(
                _RULE_DOCUMENT,
                node.attr,
                node,
                f"{node.attr}() destroys a document and is not permitted in a macro",
            )
        if isinstance(node.value, ast.Name) and node.value.id in self._operator_aliases:
            self._operator_attribute_bases.add(id(node.value))
        helper = self._operator_helper(node)
        if helper is not None and id(node) not in self._direct_helper_references:
            self._add(
                _RULE_DUNDER,
                f"operator.{helper}",
                node,
                f"storing operator.{helper} for indirect use is not permitted",
            )
        self.generic_visit(node)

    # ---- bare names ---------------------------------------------------
    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802 - ast API
        if node.id.startswith("__") and node.id.endswith("__"):
            self._add(
                _RULE_DUNDER,
                node.id,
                node,
                f"reference to {node.id!r} is not permitted in a generated macro",
            )
        if (
            isinstance(node.ctx, ast.Load)
            and node.id in self._operator_aliases
            and id(node) not in self._operator_attribute_bases
        ):
            self._add(
                _RULE_DUNDER,
                "operator",
                node,
                "storing the operator module for indirect use is not permitted",
            )
        if (
            isinstance(node.ctx, ast.Load)
            and node.id in self._operator_helpers
            and id(node) not in self._direct_helper_references
        ):
            helper = self._operator_helpers[node.id]
            self._add(
                _RULE_DUNDER,
                f"operator.{helper}",
                node,
                f"storing operator.{helper} for indirect use is not permitted",
            )
        if (
            isinstance(node.ctx, ast.Load)
            and node.id in PROHIBITED_CALLS
            and id(node) not in self._direct_helper_references
        ):
            # Fix 3: a prohibited builtin remains the same escape primitive
            # when it is aliased or handed to functools rather than called
            # directly (`e = eval; e(...)`, `partial(eval, ...)`). The
            # `id(node) not in self._direct_helper_references` guard stops
            # this from double-reporting the exact same Name node visit_Call
            # already flagged for a direct `eval(...)`-style call, above.
            # Deliberately NOT extended to getattr/setattr/delattr here --
            # those are not in PROHIBITED_CALLS on this fence (the
            # ORDER-2026-09-27-06 ruling 3 loosening above), and a bare
            # reference to them (unlike a dunder-literal CALL, which
            # _names_a_dunder already catches) is ordinary, e.g. passing
            # `getattr` itself as a sort key.
            self._add(
                _RULE_CALL,
                node.id,
                node,
                f"reference to {node.id} is not permitted in a generated macro",
            )
        self.generic_visit(node)


def review_source(source: str) -> MacroReview:
    """Review one piece of generated Python and say whether it may run.

    Never raises on bad input. Source that will not parse is refused as
    UNPARSEABLE, because a macro that cannot be read cannot be reviewed, and
    failing to parse is not evidence of safety.
    """
    if not source or not source.strip():
        # An empty macro is harmless, but permitting it means "allowed" can be
        # produced by sending nothing, which is a confusing thing to have in a
        # log next to a real approval.
        return MacroReview(
            ReviewOutcome.NOT_REVIEWED, reason="no source was supplied to review"
        )
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as error:
        # ValueError covers source containing null bytes, which SyntaxError
        # does not.
        return MacroReview(
            ReviewOutcome.UNPARSEABLE,
            reason=f"source could not be parsed as Python: {error}",
        )
    visitor = _Visitor()
    visitor.visit(tree)
    if visitor.findings:
        ordered = tuple(sorted(visitor.findings, key=lambda item: (item.line, item.rule_id)))
        return MacroReview(ReviewOutcome.PROHIBITED, ordered)
    return MacroReview(ReviewOutcome.ALLOWED)
