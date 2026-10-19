"""
lint — Sigil syntax and structural validation: `sigil lint FILE|- [--dialect
NAME] [--deep]` (the command, and --deep's join with check, live in sigil.cli).

    lint(text, dialect=…) → LintResult      every rule, in a fixed order
    lint_reading(text, dialect=…) → Linted  the same, with the reading it judged
    exit_code(severities)                   0 no issues, 1 warnings, 2 errors
    lint_summary(result)                    "sigil: N issue(s) (…)"

The rules, grouped by what they check:

    reading       what the rules read off the one reading
                  (sigil.core.statements): each line's code (LineView), the
                  `state` block lines, header tokens; the block-string report
    lines         per-line rules: mode line, holes, prose verbs, modifiers,
                  `#&` declarations no dialect declares (SGL189), …
    payloads      what follows a flow's `:`
    permissions   `@read` / `@write` / `@borrow`
    composition   `\\-` branch markers
    hardening     SGL120–188: lines the parser would misread or drop
    graph         rules over the parsed document

Output format (one diagnostic per line): `<severity>:<line>:<rule>: <message>`;
severities: error (spec violation, document is invalid), warn (suspicious
pattern, probably a mistake), info (style suggestion, not required to fix).
"""

from collections import Counter
from typing import NamedTuple

# The known vocabulary, the glyph and arrow tables, the diagnostic records and
# strip_comment live in core (sigil.core.vocab, the dialect API); lint keeps the
# names (lint.VALID_MODIFIERS, lint.LintResult, …) for a dialect's wrapper.
from sigil.core.vocab import (  # noqa: F401  (re-exported)
    ANY_GLYPH_RE, ARROW_RE, ARROWS, CALL_RESILIENCE_MODIFIERS, Diagnostic, GLYPH_PATTERNS,
    LintResult, PERMISSION_MODIFIERS, VALID_LOOP_MODS, VALID_MODES, VALID_MODIFIERS,
    VALID_PARALLEL_MODS, VALID_STREAM_POLICIES, strip_comment)
from sigil.analyse.lint.composition import CORE_RELATIONS, branch_markers, lint_composition
from sigil.analyse.lint.graph import lint_graph, parse_for_lint
from sigil.analyse.lint.hardening import lint_hardening
from sigil.analyse.lint.lines import (
    lint_actor_as_state, lint_declarations, lint_duplicate_glyph_in_flow,
    lint_holes_in_spec_mode, lint_invented_modifiers, lint_mode_line, lint_mode_not_first, lint_prose_verbs,
    lint_reverse_arrow, lint_semicolon_separator, lint_state_block_syntax)
from sigil.analyse.lint.payloads import lint_payloads
from sigil.analyse.lint.permissions import declared_principals, lint_permission_graph
from sigil.analyse.lint.reading import (  # noqa: F401  (collapse_block_strings: a dialect's tests)
    blank_lines, collapse_block_strings, declarations, header_tokens, line_views,
    state_lines, unterminated_block)
from sigil.core.dialects import _hook
from sigil.core.statements import Walk, read_document


class Linted(NamedTuple):
    """A document's lint result, the one reading its rules judged and the model
    parsed from it (None when the parser failed) — what `sigil lint --deep` and
    the export gate hand the checks, so the document is read and parsed once."""
    result: LintResult
    walk: Walk
    graph: object = None


def lint(text: str, dialect=None) -> LintResult:
    """Lint a Sigil document. `dialect` is a loaded dialect (dialects.load) or
    None for core Sigil. The document is read once (read_document): the rules
    below judge that reading, and the parser builds the model from it."""
    return lint_reading(text, dialect).result


def lint_reading(text: str, dialect=None) -> Linted:
    """lint, with the document's reading (a Walk) beside the result."""
    result = LintResult()
    known = VALID_MODIFIERS | set(_hook(dialect, "KNOWN_MODIFIERS", set()))
    deferred = set(_hook(dialect, "DEFERRED_MODIFIERS", set()))

    # The one reading: block strings folded (an unterminated one is SGL170), the
    # dialect's prepasses run (what they report follows the core pre-passes').
    prepassed = LintResult()
    walk = read_document(text, dialect, prepassed)
    graph = parse_for_lint(text, dialect, walk)
    unterminated_block(walk.unterminated, result)
    markers, passed = _composition(walk, graph, dialect, result)
    result.diagnostics.extend(prepassed.diagnostics)
    views = line_views(walk, markers)
    headers = header_tokens(walk.doc)

    lines = blank_lines(walk.lines, markers)
    mode = lint_mode_line(lines, result)
    lint_mode_not_first(lines, result)
    lint_holes_in_spec_mode(views, mode, result)
    lint_actor_as_state(views, state_lines(walk.doc), result)
    lint_prose_verbs(walk.statements, headers, result)
    lint_invented_modifiers(views, result, known, deferred)
    lint_declarations(declarations(walk.doc), _declared(dialect), result,
                      loaded=dialect is not None)
    lint_semicolon_separator(views, result)
    lint_reverse_arrow(views, result)
    lint_duplicate_glyph_in_flow(views, result)
    lint_state_block_syntax(walk.transitions, result)
    lint_permission_graph(walk.statements, headers,
                          declared_principals(walk, markers), result)
    lint_payloads(walk.statements, result,
                  checks=list(_hook(dialect, "lint_payload_checks")), known=known)
    lint_hardening(walk, result, dialect, graph)
    passes = list(_hook(dialect, "lint_passes"))
    if passes:
        pass_lines = blank_lines(walk.lines, passed)
        for extra in passes:
            extra(pass_lines, result)
    lint_graph(text, result, dialect, graph)

    return Linted(result, walk, graph)


def _composition(walk, graph, dialect, result: LintResult) -> tuple:
    """Judge the composition-tree branch markers (SGL110/SGL111) unless the
    dialect owns them (COMPOSITION_LINT = False). Returns the markers the rules
    read past — the well-formed ones, or every one a dialect owns — and those its
    lint passes read past (none of a dialect's own: it reads them as written)."""
    if not _hook(dialect, "COMPOSITION_LINT", True):
        return branch_markers(walk, relations=None), {}
    relations = CORE_RELATIONS + "".join(_hook(dialect, "COMPOSITION_RELATIONS", ""))
    lint_composition(walk, graph, result, relations)
    markers = branch_markers(walk, relations)
    return markers, markers


def _declared(dialect):
    """The `#&` names the dialect declares (its DECLARATIONS), or None when it
    names none (no dialect, or one without the hook)."""
    names = _hook(dialect, "DECLARATIONS", None)
    return None if names is None else set(names)


def exit_code(severities) -> int:
    """2 if any error, 1 if any warning, else 0."""
    sev = set(severities)
    return 2 if "error" in sev else 1 if "warn" in sev else 0


def lint_summary(result: LintResult) -> str:
    counts = Counter(d.severity for d in result.diagnostics)
    return (f"sigil: {len(result.diagnostics)} issue(s) "
            f"({counts['error']} error, {counts['warn']} warn, {counts['info']} info)")


