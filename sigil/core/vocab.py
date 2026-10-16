"""The core vocabulary — THE DIALECT API.

What a dialect (sigil-<name>/dialect.py, see sigil.core.dialects) builds on:
the known modes, arrows and modifiers, the glyph patterns, the diagnostic
records its lint passes add to, and the comment rule its line scans use. These
names are stable: a dialect imports them from here (`from sigil.core import
vocab`), never from the linter.

    VALID_MODES                 the mode lines: #!spec, #!sketch, #!craft
    ARROWS, ARROW_RE            the closed arrow set, longest first (one capture group)
    VALID_MODIFIERS             the core @-modifier allowlist (a dialect adds KNOWN_MODIFIERS)
    CALL_RESILIENCE_MODIFIERS   @fallback (with @timeout and ×N: a call's error policy)
    PERMISSION_MODIFIERS        @read, @write (the permission graph)
    VALID_LOOP_MODS             @each @while @until @times
    VALID_PARALLEL_MODS         @all @any @none
    VALID_STREAM_POLICIES       a stream bound's policy: block drop latest err
    GLYPH_PATTERNS              {service, data, event, actor, store: pattern}, group 1 the name
    ANY_GLYPH_RE                any glyph, one group (`<->` is never an event)
    Diagnostic, LintResult      a lint finding (`severity:line:rule: message`) and the
                                list a pass adds to (`result.add(severity, line, rule, message)`)
    strip_comment(line)         the line without its comment: a `#` at line start or
                                after whitespace starts one, never inside a `"…"`
                                string (`: "issue #5"` keeps its `#`); a `#!` mode line
                                is returned whole

The hooks a dialect defines are listed in sigil.core.dialects. One hook set
serves the one reading of a document (sigil.core.statements): `prepasses()`
(line rewrites before the walk; the place for a blank that depends on context,
such as whether a line is a composition branch), `strips()` (length-preserving
blanks of a flow statement's text, blind to its context) and `tokenizers()`
(extra glyph / arrow syntax: a node in the model, an endpoint for lint, a
principal an access list may name) — the retired `lint_*` / `render_*` pairs
(lint_prepasses, render_prepasses, render_line_strips, render_tokenizers,
lint_glyph_masks, lint_principal_scanners) are refused by dialects.load().

The lexical names (arrows, glyph patterns, the comment rule) are kept once in
sigil.core.lex and re-exported here.
"""

from dataclasses import dataclass, field

from sigil.core.lex import (  # noqa: F401  (re-exported: the dialect API)
    ANY_GLYPH_RE, ARROW_RE, ARROWS, COMMENT_START_RE, GLYPH_PATTERNS, strip_comment)

# ---------------------------------------------------------------------------
# Known vocabulary
# ---------------------------------------------------------------------------

VALID_MODES = {"#!spec", "#!sketch", "#!craft"}

# Call resilience is the trio `@timeout` · `×N` (retry cardinality) · `@fallback(x)`
# — together a call's error policy (language.md "Call resilience"). `@timeout` sits
# in VALID_MODIFIERS and `×N` is cardinality, so only `@fallback` lives here; its
# arg is the recovery payload (a value / ref / op-call / component).
CALL_RESILIENCE_MODIFIERS = {"@fallback"}


# Permission-graph access modifiers — `@read(…)` / `@write(…)`; see
# sigil.core.lex.PRINCIPAL_SET_RE, language.md "Permission graph" + lint_permission_graph.
PERMISSION_MODIFIERS = {"@read", "@write"}


VALID_MODIFIERS = {
    "@inv", "@sla", "@cap", "@grants", "@requires",
    "@owns", "@borrow", "@loc", "@timeout", "@after", "@deadline",
} | CALL_RESILIENCE_MODIFIERS | PERMISSION_MODIFIERS
# Modifiers outside this set (and any a loaded dialect adds) get an info
# diagnostic. `@notify` is NOT in the standard vocabulary — language.md forbids it.


VALID_LOOP_MODS = {"@each", "@while", "@until", "@times"}
VALID_PARALLEL_MODS = {"@all", "@any", "@none"}
VALID_STREAM_POLICIES = {"block", "drop", "latest", "err"}


# ---------------------------------------------------------------------------
# Diagnostics — what a lint pass (core or a dialect's) reports
# ---------------------------------------------------------------------------

@dataclass
class Diagnostic:
    severity: str  # "error" | "warn" | "info"
    line: int
    rule: str
    message: str

    def format(self) -> str:
        return f"{self.severity}:{self.line}:{self.rule}: {self.message}"


@dataclass
class LintResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(self, severity: str, line: int, rule: str, message: str):
        self.diagnostics.append(Diagnostic(severity, line, rule, message))

    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)

    def has_warnings(self) -> bool:
        return any(d.severity == "warn" for d in self.diagnostics)
