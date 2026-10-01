#!/usr/bin/env python3
"""
lint.py — Sigil syntax and structural validator.

Usage:
    ./lint.py <file.sigil> [--dialect NAME]
    cat doc.sigil | ./lint.py - [--dialect NAME]

Options:
    --dialect NAME   Load a dialect (a name, or a path to a dialect.py) that
                     extends the core vocabulary and rules. Default: the
                     SIGIL_DIALECT environment variable; unset = core Sigil.
                     See dialects.py.

Exit codes:
    0 — no issues
    1 — warnings only
    2 — errors present

Output format (one diagnostic per line):
    <severity>:<line>:<rule>: <message>

Severities:
    error   — spec violation, document is invalid
    warn    — suspicious pattern, probably a mistake
    info    — style suggestion, not required to fix
"""

import importlib.util
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Known vocabulary
# ---------------------------------------------------------------------------

VALID_MODES = {"#!spec", "#!sketch", "#!craft"}

# The closed arrow set, ordered longest-first so `<->` is not matched as `->`.
ARROWS = ["<->", "->", "~>", "=>", "!>", "?>", "*>", "→"]
ARROW_RE = re.compile("(" + "|".join(map(re.escape, ARROWS)) + ")")

# Call resilience is the trio `@timeout` · `×N` (retry cardinality) · `@fallback(x)`
# — together a call's error policy (language.md "Call resilience"). `@timeout` sits
# in VALID_MODIFIERS and `×N` is cardinality, so only `@fallback` lives here; its
# arg is the recovery payload (a value / ref / op-call / component).
CALL_RESILIENCE_MODIFIERS = {"@fallback"}

# Permission-graph access modifiers — `@read(…)` / `@write(…)`; see
# PRINCIPAL_SET_RE below, language.md "Permission graph" + lint_permission_graph.
PERMISSION_MODIFIERS = {"@read", "@write"}

VALID_MODIFIERS = {
    "@inv", "@sla", "@cap", "@grants", "@requires",
    "@owns", "@borrow", "@loc", "@timeout", "@after", "@deadline",
} | CALL_RESILIENCE_MODIFIERS | PERMISSION_MODIFIERS
# Modifiers outside this set (and any a loaded dialect adds) get an info
# diagnostic. `@notify` is NOT in the standard vocabulary — language.md forbids it.


def _hook(dialect, name: str, default=()):
    """Read an optional dialect hook (see dialects.py): a callable hook is called,
    a data hook returned as-is, a missing one (or no dialect) gives `default`."""
    if dialect is None:
        return default
    val = getattr(dialect, name, None)
    if val is None:
        return default
    return val() if callable(val) else val


VALID_LOOP_MODS = {"@each", "@while", "@until", "@times"}
VALID_PARALLEL_MODS = {"@all", "@any", "@none"}
VALID_STREAM_POLICIES = {"block", "drop", "latest", "err"}

# Permission graph — an access modifier `@read(…)` / `@write(…)` carrying a `( )`
# comma-list of bare principal names permitted that access on a store. It joins the
# capability-modifier family (`@grants`/`@requires`/`@owns`/`@borrow`, `@cap(read,
# write)`), every member of which takes its args in `( )`, never `{ }`.
# `PRINCIPAL_SET_RE` captures the modifier + its `( )` list so the structural
# linters can MASK it (a `(boss, worker)` list is NOT an actor glyph).
PRINCIPAL_SET_RE = re.compile(
    r"@(?P<mod>read|write)\s*\((?P<set>[^()]*)\)"
)
# `@borrow(…)` with a narrowing arg, lending access to a delegate (the lent
# resource is a store `|S|` or a bare name). The arg is captured whatever it is so
# lint_permission_graph can reject anything but `read` / `write`; bare `@borrow`
# (full access) has no arg to check.
BORROW_ACCESS_RE = re.compile(r"@borrow\s*\((?P<arg>[^)]*)\)")


def _mask_principal_sets(line: str) -> str:
    """Blank out permission-graph access modifiers `@read(…)` / `@write(…)` (and
    their `( )` principal lists) so the contained `(boss, worker)` list is NOT
    mis-read as an actor-glyph `(X)` by the structural / payload linters. The
    members are bare principal names, not glyphs. The dedicated
    `lint_permission_graph` validates them. Length-preserving."""
    return PRINCIPAL_SET_RE.sub(lambda m: " " * len(m.group(0)), line)


# A bare principal name in a set — a declared entity name or a generic role name.
PRINCIPAL_NAME_RE = re.compile(r"^[A-Za-z_][\w-]*$")
# Vocabulary that strongly suggests a lifecycle state (if used as an actor)
STATE_VOCABULARY = {
    "live", "dead", "active", "inactive", "pending", "running", "done",
    "idle", "queued", "failed", "success", "archived", "draft", "published",
    "open", "closed", "disputed", "superseded", "retracted", "cancelled",
    "expired", "ready", "waiting", "ok", "error", "created", "deleted",
    "new", "processing", "completed", "retryable",
}

# Prose verbs that commonly get written between glyphs instead of arrows
PROSE_VERBS = {
    "excludes", "includes", "surfaces", "filters", "returns", "calls",
    "reads", "writes", "sends", "receives", "produces", "consumes",
    "emits", "stores", "loads", "fetches", "queries", "updates",
    "composes", "contains", "uses", "requires", "provides",
}

# Glyph patterns
GLYPH_PATTERNS = {
    "service": re.compile(r"\[([^\[\]]+)\]"),
    "data":    re.compile(r"\{([^\{\}]+)\}"),
    "event":   re.compile(r"<([^<>]+)>"),
    "actor":   re.compile(r"\(([^()]+)\)"),
    "store":   re.compile(r"\|([^|]+)\|"),
}

# Any glyph at all (for flow-line analysis). The `<->` bidirectional arrow is
# never an event glyph `<-…>`.
ANY_GLYPH_RE = re.compile(
    r"(\[[^\[\]]+\]|\{[^\{\}]+\}|<(?!->)[^<>]+>|\([^()]+\)|\|[^|]+\|)"
)

# A hole glyph (`[?]`, `{?}`, `<?>`, `(?)`, `|?|`).
HOLE_RE = re.compile(r"(\[\?\]|\{\?\}|<\?>|\(\?\)|\|\?\|)")

# A `"…"` string literal (masked by the per-line rules so its text is inert).
_STRING_RE = re.compile(r'"[^"]*"')

# An @-modifier token.
_MODIFIER_RE = re.compile(r"@[a-z][a-z0-9_-]*")

# A state-block header: `state <owner-glyph> {`, the owner optionally `~`/`*`
# prefixed and carrying one level of generics (`state {Job<T>} {`).
STATE_HEADER_RE = re.compile(
    r"^state\s*[~*]*[\[{<(|][^\[\]{}<>()|]+(?:<[^\[\]{}<>()|]+>)?[\]}>)|]\s*\{"
)

# Multiline block-string delimiter — a `str` literal's triple-quoted multiline form
# `"""…"""` (language.md "Multiline block-strings"). It is sigil's ONLY multiline
# construct.
BLOCK_DELIM = '"""'
# The masked stand-in a folded block body collapses to — an ordinary single-line
# STR value, so every downstream per-line linter reads the block as a normal `str`
# (trailing modifiers after the closing delimiter survive). The sentinel carries no
# glyphs / arrows / `:` so it perturbs no linter.
_BLOCK_SENTINEL = '"block-string"'
# A comment start: a `#` preceded by whitespace/SOL, not part of `#!`. Used by
# strip_comment, and to tell an opening `"""` from a `"""` sitting in a comment.
_COMMENT_START_RE = re.compile(r"(?<!\S)#(?!!)")


# ---------------------------------------------------------------------------
# Diagnostic dataclass
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


# ---------------------------------------------------------------------------
# Multiline block-strings — the `"""…"""` pre-pass (sigil's ONLY multiline form)
# ---------------------------------------------------------------------------
#
# A STR literal has a triple-quoted multiline form `"""…"""` (language.md
# "Multiline block-strings") — usable wherever a single-line STR is accepted. This
# is the ONE place sigil leaves strict line-orientation. To keep that cost CONTAINED
# to this token, the rest of the linter is NOT taught about blocks; instead a single
# tightly-scoped PRE-PASS folds each `"""…"""` block into a masked single-line STR
# on its opening line and BLANKS the consumed body lines. Line numbering is
# preserved (the list length is unchanged), so every downstream per-line linter
# runs UNCHANGED on a fully line-oriented document — the block reads to it as an
# ordinary `: "<…>"` value. `${…}` inside the block is NOT substituted here: sigil
# carries the template text; whatever consumes the design assembles/substitutes it.

def _block_open_pos(raw: str) -> Optional[int]:
    """Index of an opening `\"\"\"` on this line that is NOT inside a trailing
    comment, or None. A `#!` mode line never opens a block; a `\"\"\"` sitting after
    a `#` comment-start is comment text, not a delimiter (so `# see \"\"\"` is inert)."""
    if raw.lstrip().startswith("#!"):
        return None
    pos = raw.find(BLOCK_DELIM)
    if pos == -1:
        return None
    cm = _COMMENT_START_RE.search(raw)
    if cm and cm.start() < pos:
        return None
    return pos


def collapse_block_strings(lines: list, result: LintResult) -> list:
    """Pre-pass: fold every `\"\"\"…\"\"\"` multiline block-string into a masked
    single-line STR on its opening line, blanking the consumed body lines (the
    list length — and so every later diagnostic's line number — is preserved).
    The opening line becomes `<prefix>"block-string"<suffix>`, where `<suffix>` is
    whatever followed the closing `\"\"\"` (any trailing modifiers) so they
    survive. An unterminated block (opening `\"\"\"` with no closing `\"\"\"`) is
    rejected (SGL170). Tightly scoped to the `\"\"\"` token — nothing else in the
    linter leaves line-orientation."""
    out = list(lines)
    n = len(out)
    i = 0
    while i < n:
        open_pos = _block_open_pos(out[i])
        if open_pos is None:
            i += 1
            continue
        prefix = out[i][:open_pos]
        after_open = out[i][open_pos + len(BLOCK_DELIM):]
        # Degenerate single-line `"""…"""` (open + close on one physical line).
        # The folded line goes back through the scan (`i` is not advanced): the
        # suffix may open another block.
        close_rel = after_open.find(BLOCK_DELIM)
        if close_rel != -1:
            suffix = after_open[close_rel + len(BLOCK_DELIM):]
            out[i] = prefix + _BLOCK_SENTINEL + suffix
            continue
        # Multiline: consume forward to the line carrying the closing `"""`.
        j = i + 1
        while j < n and BLOCK_DELIM not in out[j]:
            j += 1
        if j >= n:
            result.add(
                "error", i + 1, "SGL170",
                "unterminated block-string: an opening `\"\"\"` has no matching "
                "closing `\"\"\"`. A `\"\"\"…\"\"\"` multiline string must be closed.",
            )
            # Blank the opening line too — a malformed (unterminated) block is one
            # hard error (SGL170); don't also leak a downstream payload diagnostic
            # on the dangling `"""`.
            for k in range(i, n):
                out[k] = ""
            break
        # Fold onto the opening line and rescan it: the closing line's suffix may
        # open another block (`""" -> [C] : """`).
        suffix = out[j][out[j].find(BLOCK_DELIM) + len(BLOCK_DELIM):]
        out[i] = prefix + _BLOCK_SENTINEL + suffix
        for k in range(i + 1, j + 1):
            out[k] = ""
    return out


# ---------------------------------------------------------------------------
# Linters
# ---------------------------------------------------------------------------

def _apply_masks(line: str, masks) -> str:
    """Apply dialect glyph masks (length-preserving `fn(line) -> line`) in order."""
    for mask in masks:
        line = mask(line)
    return line


def strip_comment(line: str) -> str:
    """Remove inline comments: a `#` at the start of the line or after whitespace
    starts one, unless it is a `#!` (a mode line is returned whole)."""
    if line.startswith("#!"):
        return line
    m = _COMMENT_START_RE.search(line)
    if m:
        return line[: m.start()]
    return line


def _mask_strings(line: str) -> str:
    """Blank the text inside `"…"` string literals (the quotes stay), so `;`, `@`,
    holes, glyphs and prose inside a string payload are inert. Length-preserving."""
    return _STRING_RE.sub(lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', line)


def _iter_state_block(lines: list):
    """Yield `(line_no, line, where)` for every line, `line` comment-stripped and
    trimmed. `where` is "header" for a `state … {` opener, "body" inside its block,
    "end" for the line that closes it, else None."""
    in_state_block = False
    brace_depth = 0
    for i, raw in enumerate(lines, start=1):
        line = strip_comment(raw).strip()
        if STATE_HEADER_RE.match(line):
            in_state_block = True
            brace_depth = line.count("{") - line.count("}")
            yield i, line, "header"
            continue
        if in_state_block:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                in_state_block = False
                yield i, line, "end"
            else:
                yield i, line, "body"
            continue
        yield i, line, None


def lint_mode_line(lines: list, result: LintResult) -> Optional[str]:
    """First non-empty, non-comment line should be a mode declaration."""
    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#") and not stripped.startswith("#!"):
            continue  # comment, skip
        # This is the first content line
        parts = stripped.split()
        if parts[0] in VALID_MODES:
            if len(parts) > 1:
                result.add(
                    "error", i, "SGL001",
                    f"mode line must be exactly '{parts[0]}' — no trailing text. "
                    f"Put titles in section headers: `--- Title ---`"
                )
            return parts[0]
        else:
            result.add(
                "warn", i, "SGL002",
                f"first content line is not a mode declaration "
                f"(#!spec / #!sketch / #!craft). Got: {stripped[:40]!r}"
            )
            return None
    result.add("warn", 0, "SGL003", "document is empty or all comments")
    return None


def lint_holes_in_spec_mode(lines: list, mode: Optional[str], result: LintResult):
    """In #!spec mode, holes (`[?]`, `{?}` etc.) are errors."""
    if mode != "#!spec":
        return
    for i, raw in enumerate(lines, start=1):
        line = _mask_strings(strip_comment(raw))
        for m in HOLE_RE.finditer(line):
            result.add(
                "error", i, "SGL010",
                f"hole {m.group(0)} is not allowed in #!spec mode. "
                f"Either fill it in or switch to #!sketch / #!craft."
            )


def lint_actor_as_state(lines: list, result: LintResult, masks=()):
    """Flag `(X)` where X looks like a state name. `masks` are dialect glyph masks
    (length-preserving) applied before the actor-glyph scan."""
    for i, line, where in _iter_state_block(lines):
        if where is not None:
            continue
        # Outside a state block — scan for actor glyphs containing state words.
        # Apply any dialect glyph masks first (so dialect syntax carrying `( )` is
        # not mis-read as an actor glyph), then mask the `( )` principal lists of
        # `@read`/`@write` so their members are not mis-read as actor glyphs.
        scan = _mask_principal_sets(_apply_masks(line, masks))
        for m in GLYPH_PATTERNS["actor"].finditer(scan):
            name = m.group(1).strip().lower()
            if name in STATE_VOCABULARY:
                result.add(
                    "warn", i, "SGL020",
                    f"({m.group(1)}) looks like a lifecycle state, not an actor. "
                    f"Use a `state {{Entity}} {{ ... }}` block instead."
                )


def lint_prose_verbs(lines: list, result: LintResult, masks=()):
    """Flag prose verbs appearing between glyphs on a flow-like line.

    Skip verbs that appear inside a modifier expression like `@inv excludes(...)`,
    where the verb is a predicate name and is legitimately English.
    """
    for i, raw in enumerate(lines, start=1):
        line = _mask_strings(strip_comment(raw).strip())
        if not line:
            continue
        if line.startswith("---") or line.startswith("#!"):
            continue

        # Blank out anything inside modifier expressions `@name(...)` so we
        # don't flag prose inside them. This is intentionally loose; invariant
        # contents are allowed to be prose-like. Apply dialect glyph masks and mask
        # `@read`/`@write` principal lists first (they are not glyphs).
        masked = _mask_principal_sets(_apply_masks(line, masks))
        masked = re.sub(r"@[a-z][a-z0-9_-]*\([^)]*\)", lambda m: " " * len(m.group(0)), masked)
        # Also mask `@name ...rest-of-line` invariant-form (no parens)
        masked = re.sub(r"@inv\b[^\n]*", lambda m: " " * len(m.group(0)), masked)
        masked = re.sub(r"@sla\b[^\n]*", lambda m: " " * len(m.group(0)), masked)
        masked = re.sub(r"@cap\b[^\n]*", lambda m: " " * len(m.group(0)), masked)

        glyphs = list(ANY_GLYPH_RE.finditer(masked))
        if len(glyphs) < 2:
            continue
        for a, b in zip(glyphs, glyphs[1:]):
            between = masked[a.end() : b.start()]
            if ARROW_RE.search(between):
                continue
            for word in re.findall(r"\b[a-z]+\b", between.lower()):
                if word in PROSE_VERBS:
                    result.add(
                        "warn", i, "SGL030",
                        f"prose verb {word!r} appears between glyphs without an arrow. "
                        f"Model as an invariant (@inv), a flow with an arrow, or a comment."
                    )
                    break


def lint_invented_modifiers(lines: list, result: LintResult,
                            known=None, deferred=frozenset()):
    """Flag @-modifiers not in the known vocabulary.

    Context-sensitive: a bare `@name : description` at the start of a line
    is an invariant label, not a modifier. Skip those. `known` is the allowlist
    (default: the core VALID_MODIFIERS; a dialect extends it); `deferred` are
    modifiers a dialect validates itself (never reported here).
    """
    if known is None:
        known = VALID_MODIFIERS
    for i, raw in enumerate(lines, start=1):
        line = _mask_strings(strip_comment(raw).strip())
        if not line or line.startswith("---") or line.startswith("#!"):
            continue

        # Invariant-label form: line starts with @name and has a `:` after it,
        # or the invariant appears as a standalone named condition.
        if re.match(r"^@[a-z][a-z0-9_-]*\s*:", line):
            continue

        for m in _MODIFIER_RE.finditer(line):
            mod = m.group(0)
            if mod in known:
                continue
            # Accessor context: any modifier immediately after a glyph close
            # (`}` `]` `)` `>` `|`) is an accessor-style token such as
            # `{Concept}@hash` ("address by hash"), not an edge modifier.
            if m.start() > 0 and line[m.start() - 1] in "}])>|":
                continue
            if mod in deferred:
                continue
            if mod in VALID_LOOP_MODS and re.search(r"\bloop\b", line):
                continue
            if mod in VALID_PARALLEL_MODS and re.search(r"\bparallel\b", line):
                continue
            if mod[1:] in VALID_STREAM_POLICIES and re.search(r"\^[^@]*" + re.escape(mod), line):
                continue
            near = min(sorted(known), key=lambda k: _edit_distance(mod, k))
            if _edit_distance(mod, near) <= 2:
                hint = f"Did you mean {near}? "
            else:
                hint = f"Known: {', '.join(sorted(known))}. "
            result.add(
                "info", i, "SGL040",
                f"modifier {mod} is not in the standard vocabulary. "
                f"{hint}Consider demoting to a comment."
            )


def lint_semicolon_separator(lines: list, result: LintResult):
    """Flag `;` used as a statement separator (not standard)."""
    for i, raw in enumerate(lines, start=1):
        line = _mask_strings(strip_comment(raw))
        if ";" in line:
            result.add(
                "warn", i, "SGL050",
                "`;` is not a Sigil statement separator. "
                "Put each statement on its own line, or use a `branch on ... { ... }` block."
            )


def lint_reverse_arrow(lines: list, result: LintResult):
    """`<-` is not a valid Sigil arrow (flows are source-to-sink)."""
    for i, raw in enumerate(lines, start=1):
        line = strip_comment(raw)
        # Careful: `<->` contains `<-`. Blank `<->` first.
        stripped = line.replace("<->", "   ")
        if re.search(r"(?<!\w)<-(?!\w)", stripped):
            result.add(
                "error", i, "SGL060",
                "reverse arrow `<-` is not valid — flows are source-to-sink. "
                "Rewrite as `src -> dst`."
            )


def lint_duplicate_glyph_in_flow(lines: list, result: LintResult):
    """Warn when the same exact glyph appears twice in one flow line."""
    for i, raw in enumerate(lines, start=1):
        line = strip_comment(raw).strip()
        if not ARROW_RE.search(line):
            continue
        glyphs = [m.group(0) for m in ANY_GLYPH_RE.finditer(line)]
        seen = set()
        for g in glyphs:
            if g in seen:
                result.add(
                    "info", i, "SGL070",
                    f"glyph {g} appears twice on one flow line. "
                    f"If it plays two roles, consider role-qualified names "
                    f"(e.g. {g[:-1]}.read{g[-1:]} / {g[:-1]}.write{g[-1:]}) "
                    f"or expand at L2 with `:= {{ ... }}`."
                )
                break
            seen.add(g)


def lint_mode_not_first(lines: list, result: LintResult):
    """If a mode line appears anywhere other than the top, flag it."""
    seen_content = False
    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#!"):
            if seen_content:
                result.add(
                    "error", i, "SGL080",
                    f"mode line '{stripped}' must be the first non-empty line of the document."
                )
            seen_content = True     # a second mode line is misplaced too
            continue
        if stripped.startswith("#"):
            continue
        seen_content = True


def lint_state_block_syntax(lines: list, result: LintResult):
    """Check that transitions inside state blocks use the `-<trigger>->` form."""
    for i, line, where in _iter_state_block(lines):
        if where != "body" or not line or line == "}":
            continue
        # Inside state block: expect `name -<trigger>-> name`
        if "-<" in line or ">->" in line:
            if not re.search(r"\S+\s*-<[^>]+>->\s*\S+", line):
                result.add(
                    "warn", i, "SGL090",
                    "malformed state transition. Expected: `source -<trigger>-> target`"
                )


# ---------------------------------------------------------------------------
# Payloads & values (map-literal disambiguation, external ops)
# ---------------------------------------------------------------------------

# A trailing edge modifier that is NOT part of the payload value: any
# @-modifier, cardinality (×N / xN), a stream bound (`^N` / `^N@policy`, N may
# carry a k/m/g scale suffix).
_TRAILING_MOD_RE = re.compile(
    r"\s*(?:@[a-z][a-z0-9_-]*(?:\([^)]*\))?|×\s*\d+|\bx\d+\b"
    r"|\^\d+[kKmMgG]?(?:@[a-z][a-z0-9_-]*)?)\s*$"
)

# Scalar value literals that are unambiguously value-bearing.
_BOOL_NULL_RE = re.compile(r"^(?:true|false|null)$")
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_STR_RE = re.compile(r'^".*"$')
_REF_RE = re.compile(r"^\$\{[^}]*\}$")
# A value-operator expression keys off a leading literal/ref/list/map followed
# by one of the closed top-level operators.
_VALUE_OP_RE = re.compile(r"(?:\+\+|\|\||[+\-*/])")


def _split_payload_and_tags(seg: str):
    """Given a payload segment (text after `:`, before the next arrow), peel
    trailing edge modifiers off the end and return (value_text, [tags_seen]).

    Tags are returned in source order (left-to-right). Only `@`-modifiers are
    collected as tags; cardinality / stream bounds are dropped."""
    tags = []
    s = seg.strip()
    while True:
        m = _TRAILING_MOD_RE.search(s)
        if not m:
            break
        chunk = s[m.start():].strip()
        if chunk.startswith("@"):
            # Take just the @name (strip any (...) args for tag identity).
            name = _MODIFIER_RE.match(chunk)
            if name:
                tags.insert(0, name.group(0))
        s = s[: m.start()].rstrip()
    return s, tags


def _brace_body_is_map_literal(body: str):
    """Classify a `{...}` payload body. Returns:
        'map'    — pure key/value pairs (a map literal value)
        'entity' — a data-glyph entity (bare identifier, optionally attrs)
        'ambig'  — has a top-level ':' but is NOT pure pairs (rejected)
    """
    inner = body.strip()
    if inner == "":
        return "entity"  # `{}` — treat as (empty) entity, not value
    # Split on top-level commas (no nesting expected at this depth in sigil).
    parts = [p.strip() for p in _split_top_level_commas(inner)]
    has_top_colon = any(":" in p for p in parts)
    if not has_top_colon:
        return "entity"
    # Has a top-level ':' — is EVERY part a `name : value` pair?
    all_pairs = all(re.match(r"^[A-Za-z_][\w.<>]*\s*:\s*.+$", p) for p in parts)
    return "map" if all_pairs else "ambig"


def _split_top_level_commas(s: str):
    """Split on commas not nested inside (), [], {}, <>, or quotes."""
    out, depth, buf, q = [], 0, [], None
    for ch in s:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
            buf.append(ch)
            continue
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def _is_list_body(body: str) -> bool:
    """True if `body` (the inside of a `[…]`) reads as a list literal's elements
    rather than a service glyph's name."""
    inner = body.strip()
    if inner == "" or len(_split_top_level_commas(inner)) > 1:
        return True
    return bool(_BOOL_NULL_RE.match(inner) or _NUMBER_RE.match(inner)
                or _STR_RE.match(inner) or _REF_RE.match(inner)
                or (inner.startswith("[") and inner.endswith("]")))


def _classify_payload(value_text: str):
    """Classify the *value text* (tags already stripped). Returns a tuple
    (kind, detail) where kind is one of:
        'value'      — a literal / ref / value-operator expression (value-bearing)
        'ext-op'     — an `op <ns>.<verb>(...)` external call (value-bearing)
        'map'        — a `{k: v}` map literal (value-bearing)
        'map-ambig'  — a `{...}` with a top-level ':' but not pure pairs (reject)
        'ext-op-bad' — an `op ...` that is malformed (reject)
        'entity'     — a glyph entity (structural)
        'int-op'     — bare `verb(args)` internal op-call (structural)
        'opaque'     — bare identifier / label / unrecognized (structural)
    """
    v = value_text.strip()
    if v == "":
        return ("opaque", "")

    # External op-call: `op <ns>.<verb>(args)`.
    if re.match(r"^op\b", v):
        m = re.match(r"^op\s+([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+)\s*\((.*)\)\s*$", v)
        if m:
            return ("ext-op", v)
        return ("ext-op-bad", v)

    # A `{...}` payload — entity vs map literal vs ambiguous.
    if v.startswith("{") and v.endswith("}"):
        cls = _brace_body_is_map_literal(v[1:-1])
        if cls == "map":
            return ("map", v)
        if cls == "ambig":
            return ("map-ambig", v)
        return ("entity", v)

    # List literal: a `[…]` that is empty, has top-level commas, or holds a
    # single value literal / ref / nested list (`[1, 2]`, `["a"]`, `[${x}]`) — a
    # service glyph `[X]` holds a name.
    if v.startswith("[") and v.endswith("]") and _is_list_body(v[1:-1]):
        return ("value", v)

    # Other single glyph entity payloads (`<X>`, `[X]`, `(X)`, `|X|`,
    # optionally `~`/`*` prefixed) are structural.
    if re.match(r"^[~*]*[\[<(|]", v):
        return ("entity", v)

    # Scalars / ref / value-op expression.
    if _BOOL_NULL_RE.match(v) or _NUMBER_RE.match(v) or _STR_RE.match(v) or _REF_RE.match(v):
        return ("value", v)
    # A value-operator expression: starts with a ref/literal and contains a
    # top-level operator (e.g. `${a} + 1`, `${xs} ++ [..]`).
    if (v.startswith("${") or _STR_RE.match(v) or _NUMBER_RE.match(v.split()[0])) \
            and _VALUE_OP_RE.search(v):
        return ("value", v)

    # Bare `verb(args)` — internal op-call (structural, by-shape).
    if re.match(r"^[A-Za-z_][\w]*\s*\(.*\)\s*$", v):
        return ("int-op", v)

    # Anything else (a bare identifier label like `reserve`, `charge`) is an
    # opaque structural payload — unchanged by-shape behavior.
    return ("opaque", v)


class PayloadSite:
    """One `: payload` segment, as handed to dialect payload checks."""
    __slots__ = ("line_no", "value", "tags", "kind", "known_modifiers")

    def __init__(self, line_no, value, tags, kind, known_modifiers):
        self.line_no = line_no
        self.value = value
        self.tags = tags
        self.kind = kind
        self.known_modifiers = known_modifiers


def lint_payloads(lines: list, result: LintResult, checks=(),
                  blocks=(), keywords=(), known=None):
    """Enforce the core payload/value grammar (language.md "Payloads & values"):

      - a `{...}` with a top-level ':' that is not pure key/value pairs is
        ambiguous and rejected (SGL100);
      - a malformed external op-call (`op` without a dotted ns) is rejected
        (SGL102).
    Core Sigil does NOT require a tag on a value payload. A dialect may add
    per-payload rules (`checks`, see dialects.py `lint_payload_checks`), declare
    blocks whose bodies are declarations rather than flows (`blocks` — skipped),
    and add statement-leading block keywords (`keywords` — header lines skipped).
    """
    if known is None:
        known = VALID_MODIFIERS
    kw = ["state", "loop", "parallel", "branch"] + sorted(set(keywords))
    in_block_header = re.compile(r"^(" + "|".join(map(re.escape, kw)) + r")\b")
    active = None          # (regex, on_raw) of the declaration block we are inside
    depth = 0
    for i, raw in enumerate(lines, start=1):
        raw_lead = raw.strip()
        line = strip_comment(raw).strip()

        # Declaration-block skip: a dialect-declared `name { … }` block carries
        # DECLARATIONS, not flow payloads (mirrors the state/loop block skips).
        # Brace depth is tracked on the raw line for raw-matched openers (a `#…`
        # marker would be blanked by comment stripping), else on the stripped line.
        if active is not None:
            txt = raw_lead if active[1] else line
            depth += txt.count("{") - txt.count("}")
            if depth <= 0:
                active = None
            continue
        opened = False
        for opener, on_raw in blocks:
            txt = raw_lead if on_raw else line
            if opener.match(txt):
                depth = txt.count("{") - txt.count("}")
                active = (opener, on_raw) if depth > 0 else None
                opened = True
                break
        if opened:
            continue

        if not line or line.startswith("#!") or line.startswith("---"):
            continue
        if in_block_header.match(line):
            continue
        # Skip aliases (`name := ...`) and state-block transitions.
        if ":=" in line or "-<" in line:
            continue
        # Find each `: payload` segment: a `:` that is not part of `:=`,
        # running to the next arrow or end of line.
        for m in re.finditer(r"(?<![:=]):(?!=)", line):
            start = m.end()
            rest = line[start:]
            am = ARROW_RE.search(rest)
            seg = rest[: am.start()] if am else rest
            if not seg.strip():
                continue
            value_text, tags = _split_payload_and_tags(seg)
            kind = _classify_payload(value_text)[0]

            if kind == "map-ambig":
                result.add(
                    "error", i, "SGL100",
                    f"`{{...}}` payload {value_text!r} is ambiguous: it has a "
                    f"top-level ':' but is not pure key/value pairs. A map "
                    f"literal must be `{{k: v, ...}}`; a data entity must be a "
                    f"bare identifier `{{X}}`."
                )
                continue
            if kind == "ext-op-bad":
                result.add(
                    "error", i, "SGL102",
                    f"malformed external op-call {value_text!r}. Expected "
                    f"`op <ns>.<verb>(args)` with a dotted host-registered op "
                    f"name (e.g. `op db.query(${{sql}})`)."
                )
            if checks:
                site = PayloadSite(i, value_text, tags, kind, known)
                for check in checks:
                    check(site, result)


# ---------------------------------------------------------------------------
# Permission graph — `@read(…)` / `@write(…)` access edges + `@borrow`
# ---------------------------------------------------------------------------

def _collect_declared_principals(lines: list, scanners=()) -> set:
    """Collect the set of declared ENTITY names a `@read`/`@write` principal may
    name (the closed-reference universe). A principal is the BARE name of any
    modeled entity — a glyph of any kind (`[X]`/`{X}`/`<X>`/`(X)`/`|X|`), plus any
    names a dialect's principal scanners extract from its own glyph syntax.
    Generics/inputs/`~`/`*` prefixes and dotted address tails are stripped to the
    base principal name. Principal lists themselves are masked so a list member is
    not counted as its own declaration."""
    declared: set = set()
    for raw in lines:
        line = strip_comment(raw)
        # Don't let a `( )` principal list count as an `(X)` actor-glyph declaration.
        line = _mask_principal_sets(line)
        # Dialect glyph syntax first: each scanner yields names + a masked line.
        for scan in scanners:
            names, line = scan(line)
            declared.update(names)
        masked = line
        for _kind, pat in GLYPH_PATTERNS.items():
            for m in pat.finditer(masked):
                name = m.group(1).strip()
                base = re.sub(r"<[^<>]*>|\([^()]*\)", "", name).strip()
                base = base.split(".")[0].strip()
                if base and base not in ("?", "_"):
                    declared.add(base)
    return declared


def lint_permission_graph(lines: list, result: LintResult, scanners=()):
    """Validate the permission-graph access modifiers (language.md "Permission
    graph"): `@read(…)` / `@write(…)` carrying a `( )` comma-list of principal
    names, and the `@borrow` delegation modifier. The surface is consumer-agnostic
    — it describes a permission graph over entities and stores; whatever consumes
    the design INTERPRETS it. Checks:
      - a principal list is non-empty (SGL140);
      - no principal is listed twice in one list (SGL141);
      - each member is a bare principal name — not a glyph, `k: v` pair, or dotted
        name (SGL142);
      - each member resolves to a declared entity — the closed-reference check
        (SGL143);
      - a `@borrow(...)` narrowing arg is `read`/`write` (SGL144).
    The list well-formedness (140-142) + borrow-arg (144) are local; the closed-
    reference check (143) sees the whole document's declared entity set."""
    declared = _collect_declared_principals(lines, scanners)
    for i, raw in enumerate(lines, start=1):
        line = strip_comment(raw)

        # `@read(…)` / `@write(…)` principal lists.
        for m in PRINCIPAL_SET_RE.finditer(line):
            mod = m.group("mod")
            body = m.group("set").strip()
            if body == "":
                result.add(
                    "error", i, "SGL140",
                    f"`@{mod}()` is an empty principal list — list at least one "
                    f"principal entity, e.g. `@{mod}(boss)`."
                )
                continue
            members = [p.strip() for p in body.split(",")]
            seen: set = set()
            for member in members:
                if member == "":
                    result.add(
                        "error", i, "SGL142",
                        f"`@{mod}({body})` has an empty member — principals are "
                        f"comma-separated bare names."
                    )
                    continue
                if not PRINCIPAL_NAME_RE.match(member):
                    result.add(
                        "error", i, "SGL142",
                        f"`@{mod}` list member {member!r} is not a bare principal "
                        f"name. A list holds entity names ("
                        f"`@{mod}(boss, worker)`), not glyphs, `k: v` pairs, or "
                        f"dotted names."
                    )
                    continue
                if member in seen:
                    result.add(
                        "error", i, "SGL141",
                        f"principal {member!r} appears twice in this `@{mod}` list."
                    )
                    continue
                seen.add(member)
                if member not in declared:
                    result.add(
                        "error", i, "SGL143",
                        f"`@{mod}` principal {member!r} does not resolve to a "
                        f"declared entity. A principal must be a modeled entity "
                        f"(a glyph / reference / generic role) declared in the "
                        f"document."
                    )

        # `@borrow(...)` narrowing arg.
        for m in BORROW_ACCESS_RE.finditer(line):
            arg = m.group("arg").strip()
            if arg not in ("read", "write"):
                result.add(
                    "error", i, "SGL144",
                    f"`@borrow({arg})` — a borrow narrowing arg is `read` or "
                    f"`write` (a child borrows access ⊆ the parent's). Bare "
                    f"`@borrow` lends the full access."
                )


# ---------------------------------------------------------------------------
# Composition trees
# ---------------------------------------------------------------------------

# Composition-tree branch markers (language.md "Composition trees"): `\\-`, an
# optional `*-` (spawned instances), an optional `(N)-` (weight) or `{cond}-`
# (guard / source), then one core relation — or a bare spawn `\\-*`. A dialect may add relations (COMPOSITION_RELATIONS) or take over this
# check entirely (COMPOSITION_LINT = False).
CORE_RELATIONS = ">&?$@!=_"
_BRANCH_ANY_RE = re.compile(r"\\-")


def _branch_re(relations: str):
    rel = re.escape(relations)
    return re.compile(
        rf"\\-(?:\*-)?(?:\(\d+\)-|\{{[A-Za-z0-9_-]+\}}-)?[{rel}](?=\s|$)|\\-\*(?=\s|$)")


def lint_composition(lines: list, result: LintResult, relations: str = CORE_RELATIONS) -> list:
    """Validate composition-tree branch markers and mask them for the per-line rules.

    SGL110 — a `\\-` that is not a well-formed branch with a known relation.
    SGL111 — a branch at the start of a line with no parent above it (nothing at a
             shallower indent to hang under).
    Returns the lines with valid markers blanked to spaces (line length preserved)."""
    ok = _branch_re(relations)
    out = list(lines)
    parent_cols: list = []                   # indents of the open parent lines
    for idx, line in enumerate(out):
        code = strip_comment(line)
        stripped = code.strip()
        if not stripped or stripped.startswith("#!"):
            continue
        col = len(code) - len(code.lstrip())
        leads = stripped.startswith("\\-")
        if leads:
            if not any(c < col for c in parent_cols):
                result.add("error", idx + 1, "SGL111",
                           "composition branch has no parent: put the parent glyph on a "
                           "line above, at a shallower indent (e.g. `[Ship]` then "
                           "`    \\-& {Transform}`).")
        parent_cols = [c for c in parent_cols if c < col] + [col]
        chars = list(line)
        flagged = False
        for m in _BRANCH_ANY_RE.finditer(code):
            tok = ok.match(code, m.start())
            if tok:
                for k in range(tok.start(), tok.end()):
                    chars[k] = " "
            elif not flagged:
                result.add("error", idx + 1, "SGL110",
                           "malformed composition branch: a branch is "
                           "`\\- [*-]? [(N)- | {cond}-]? <rel>` with <rel> one of "
                           f"`{relations}` (> contains · & has · ? when · $ from data · "
                           "@ attached · ! alerts when · = gathers · _ one of), or a bare "
                           "spawn `\\-*`.")
                flagged = True
        out[idx] = "".join(chars)
    return out


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ---------------------------------------------------------------------------
# Graph checks (via render.py)
# ---------------------------------------------------------------------------

def _load_sibling(modname: str, filename: str):
    """Path-load a sibling tool module (stdlib only), once: it is registered in
    sys.modules under `modname` and reused on later calls."""
    mod = sys.modules.get(modname)
    if mod is None:
        sp = importlib.util.spec_from_file_location(
            modname, Path(__file__).resolve().parent / filename)
        mod = importlib.util.module_from_spec(sp)
        sys.modules[modname] = mod
        sp.loader.exec_module(mod)
    return mod


def _render_module():
    return _load_sibling("sigil_render_for_lint", "render.py")


def lint_graph(text: str, result: LintResult, dialect=None):
    """Checks that need the parsed document (render.parse_document).

    SGL112 (warn) — a qualified path `[A]/{B}` that matches no occurrence in the
                    composition trees.
    SGL091 (info) — a state-machine trigger that matches no event but is a likely
                    typo of one (edit distance ≤ 1, ≤ 2 for 5+ characters)."""
    try:
        render = _render_module()
        g = render.parse_document(text, dialect=dialect)
    except Exception:           # the parser has its own tests; lint stays up
        return
    lines = text.splitlines()

    # NOTE: `render._walk` is private to render.py; lint relies on it to visit
    # every sub-graph, so a change to its yield shape must be mirrored here.
    def line_of(needle):
        for n, ln in enumerate(lines, 1):
            if needle in ln:
                return n
        return 0

    for sub, _owner, _lvl in render._walk(g):
        occ = render.occurrences(sub)
        for e in sub.edges:
            for nid, path in ((e.src, e.src_path), (e.dst, e.dst_path)):
                if path and not render.matching_occurrences(sub, occ, nid, path):
                    shown = "/".join(path)
                    at = next((n for n, ln in enumerate(lines, 1)
                               if re.search(r"/[\[{<(|~*]*" + re.escape(path[-1]) + r"[\]}>)|]", ln)),
                              0)
                    result.add("warn", at, "SGL112",
                               f"path `{shown}` matches nothing: no `{path[-1]}` sits directly "
                               f"under `{path[-2]}` in a composition tree.")
    events = {n.name.lower(): n.name for sub, _o, _l in render._walk(g)
              for n in sub.nodes.values() if n.kind == "event" and not n.is_hole}
    seen = set()
    for sub, _owner, _lvl in render._walk(g):
        if sub.role != "state":
            continue
        for e in sub.edges:
            trig = (e.label or "")[1:-1]
            key = trig.lower()
            if not trig or key in events or key in seen:
                continue
            seen.add(key)
            limit = 2 if len(key) >= 5 else 1
            near = sorted((d, name) for low, name in events.items()
                          if (d := _edit_distance(key, low)) <= limit)
            if near:
                result.add("info", line_of(f"-<{trig}>->"), "SGL091",
                           f"trigger <{trig}> matches no event; did you mean <{near[0][1]}>?")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def lint(text: str, dialect=None) -> LintResult:
    """Lint a Sigil document. `dialect` is a loaded dialect (dialects.load) or
    None for core Sigil."""
    lines = text.splitlines()
    result = LintResult()

    known = VALID_MODIFIERS | set(_hook(dialect, "KNOWN_MODIFIERS", set()))
    deferred = set(_hook(dialect, "DEFERRED_MODIFIERS", set()))
    masks = list(_hook(dialect, "lint_glyph_masks"))

    # Core pre-pass: fold multiline `"""…"""` block-strings into masked single-line
    # STRs (sigil's ONLY departure from line-orientation; see collapse_block_strings).
    # Every linter below then runs unchanged on a line-oriented document.
    lines = collapse_block_strings(lines, result)
    # Core pre-pass: composition-tree branch markers (unless the dialect owns them).
    if _hook(dialect, "COMPOSITION_LINT", True):
        lines = lint_composition(
            lines, result, CORE_RELATIONS + "".join(_hook(dialect, "COMPOSITION_RELATIONS", "")))
    # Dialect pre-passes (line-count preserving).
    for prepass in _hook(dialect, "lint_prepasses"):
        lines = prepass(lines, result)

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
    lint_permission_graph(lines, result, list(_hook(dialect, "lint_principal_scanners")))
    lint_payloads(
        lines, result,
        checks=list(_hook(dialect, "lint_payload_checks")),
        blocks=list(_hook(dialect, "DECLARATION_BLOCKS")),
        keywords=set(_hook(dialect, "BLOCK_KEYWORDS", set())),
        known=known,
    )
    for extra in _hook(dialect, "lint_passes"):
        extra(lines, result)
    lint_graph(text, result, dialect)

    return result


def _load_dialect(spec):
    """Load a dialect via the sibling dialects.py (path-loaded; stdlib only)."""
    return _load_sibling("sigil_dialects_for_lint", "dialects.py").load(spec)


def main(argv=None, default_dialect=None):
    import argparse
    ap = argparse.ArgumentParser(prog="lint.py", description="Lint a Sigil document.")
    ap.add_argument("file", help="a .sigil file, or - for stdin")
    ap.add_argument("--dialect", default=default_dialect,
                    help="dialect name or path (default: $SIGIL_DIALECT)")
    a = ap.parse_args(argv)
    try:
        dialect = _load_dialect(a.dialect)
    except ValueError as exc:
        print(f"lint.py: {exc}", file=sys.stderr)
        sys.exit(2)

    if a.file == "-":
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        text = sys.stdin.read()
    else:
        try:
            text = Path(a.file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"lint.py: cannot read {a.file}: {exc.strerror or exc}", file=sys.stderr)
            sys.exit(2)

    result = lint(text, dialect=dialect)

    if not result.diagnostics:
        print("sigil: OK (no issues)")
        sys.exit(0)

    for d in result.diagnostics:
        print(d.format())

    counts = Counter(d.severity for d in result.diagnostics)
    print(
        f"\nsigil: {len(result.diagnostics)} issue(s) "
        f"({counts['error']} error, {counts['warn']} warn, {counts['info']} info)",
        file=sys.stderr,
    )

    if result.has_errors():
        sys.exit(2)
    if result.has_warnings():
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
