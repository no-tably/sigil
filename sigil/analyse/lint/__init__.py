"""
lint — Sigil syntax and structural validation: `sigil lint FILE|- [--dialect
NAME] [--deep]` (the command, and --deep's join with check, live in sigil.cli).

    lint(text, dialect=…) → LintResult      every rule, in a fixed order
    exit_code(severities)                   0 no issues, 1 warnings, 2 errors
    lint_summary(result)                    "sigil: N issue(s) (…)"

The rules, grouped by what they check:

    scan          the masks and the block-string report (the tables are
                  sigil.core.lex's, the reading sigil.core.statements')
    lines         per-line rules: mode line, holes, prose verbs, modifiers, …
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

# The known vocabulary, the glyph and arrow tables, the diagnostic records and
# strip_comment live in core (sigil.core.vocab, the dialect API); lint keeps the
# names (lint.VALID_MODIFIERS, lint.LintResult, …) for a dialect's wrapper.
from sigil.core.vocab import (  # noqa: F401  (re-exported)
    ANY_GLYPH_RE, ARROW_RE, ARROWS, CALL_RESILIENCE_MODIFIERS, Diagnostic, GLYPH_PATTERNS,
    LintResult, PERMISSION_MODIFIERS, VALID_LOOP_MODS, VALID_MODES, VALID_MODIFIERS,
    VALID_PARALLEL_MODS, VALID_STREAM_POLICIES, strip_comment)
from sigil.analyse.lint.composition import CORE_RELATIONS, lint_composition
from sigil.analyse.lint.graph import lint_graph, parse_for_lint
from sigil.analyse.lint.hardening import lint_hardening
from sigil.analyse.lint.lines import (
    lint_actor_as_state, lint_duplicate_glyph_in_flow, lint_holes_in_spec_mode,
    lint_invented_modifiers, lint_mode_line, lint_mode_not_first, lint_prose_verbs,
    lint_reverse_arrow, lint_semicolon_separator, lint_state_block_syntax)
from sigil.analyse.lint.payloads import lint_payloads
from sigil.analyse.lint.permissions import lint_permission_graph
from sigil.core.dialects import _hook
from sigil.core.statements import read_document
from sigil.analyse.lint.scan import (  # noqa: F401  (collapse_block_strings: a dialect's tests)
    collapse_block_strings, dialect_masks, principal_scanners, unterminated_block)


def lint(text: str, dialect=None) -> LintResult:
    """Lint a Sigil document. `dialect` is a loaded dialect (dialects.load) or
    None for core Sigil. The document is read once (read_document): the rules
    below judge that reading, and the parser builds the model from it."""
    result = LintResult()
    known = VALID_MODIFIERS | set(_hook(dialect, "KNOWN_MODIFIERS", set()))
    deferred = set(_hook(dialect, "DEFERRED_MODIFIERS", set()))

    # The one reading: block strings folded (an unterminated one is SGL170), the
    # dialect's prepasses run (what they report follows the core pre-passes').
    prepassed = LintResult()
    walk = read_document(text, dialect, prepassed)
    unterminated_block(walk.unterminated, result)
    lines = list(walk.lines)
    masks = dialect_masks(walk.lexicon)
    # Core pre-pass: composition-tree branch markers (unless the dialect owns them).
    if _hook(dialect, "COMPOSITION_LINT", True):
        lines = lint_composition(
            lines, result, CORE_RELATIONS + "".join(_hook(dialect, "COMPOSITION_RELATIONS", "")))
    result.diagnostics.extend(prepassed.diagnostics)

    mode = lint_mode_line(lines, result)
    lint_mode_not_first(lines, result)
    lint_holes_in_spec_mode(lines, mode, result)
    lint_actor_as_state(lines, result, masks)
    lint_prose_verbs(lines, result, masks)
    lint_invented_modifiers(lines, result, known, deferred)
    lint_semicolon_separator(lines, result)
    lint_reverse_arrow(lines, result)
    lint_duplicate_glyph_in_flow(lines, result)
    lint_state_block_syntax(lines, result)
    lint_permission_graph(lines, result, principal_scanners(walk.lexicon))
    lint_payloads(
        lines, result,
        checks=list(_hook(dialect, "lint_payload_checks")),
        blocks=list(_hook(dialect, "DECLARATION_BLOCKS")),
        keywords=set(_hook(dialect, "BLOCK_KEYWORDS", set())),
        known=known,
    )
    graph = parse_for_lint(text, dialect, walk)
    lint_hardening(walk, result, dialect, graph)
    for extra in _hook(dialect, "lint_passes"):
        extra(lines, result)
    lint_graph(text, result, dialect, graph)

    return result


def exit_code(severities) -> int:
    """2 if any error, 1 if any warning, else 0."""
    sev = set(severities)
    return 2 if "error" in sev else 1 if "warn" in sev else 0


def lint_summary(result: LintResult) -> str:
    counts = Counter(d.severity for d in result.diagnostics)
    return (f"sigil: {len(result.diagnostics)} issue(s) "
            f"({counts['error']} error, {counts['warn']} warn, {counts['info']} info)")


