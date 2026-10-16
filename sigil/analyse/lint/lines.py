"""
Per-line rules: the mode line (SGL001/SGL002), holes in spec mode, an actor named
like a state, prose verbs between glyphs, invented modifiers, `;` separators,
reversed arrows, a glyph twice in one flow, a `state` block's syntax — and the
edit-distance index the near-name suggestions use (here and in lint.graph).

The mode-line rules read the document's lines; the others read each line's code
as the walk found it (lint.reading.LineView) or the walk's `state` block lines (Transition).
"""

import re
from typing import Optional

from sigil.core.vocab import (
    ANY_GLYPH_RE, ARROW_RE, GLYPH_PATTERNS, LintResult, VALID_LOOP_MODS, VALID_MODES,
    VALID_MODIFIERS, VALID_PARALLEL_MODS, VALID_STREAM_POLICIES)

from sigil.core.lex import HOLE_RE, MOD_TOKEN_RE


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


def lint_holes_in_spec_mode(views: tuple, mode: Optional[str], result: LintResult):
    """In #!spec mode, holes (`[?]`, `{?}` etc.) are errors."""
    if mode != "#!spec":
        return
    for i, view in enumerate(views, start=1):
        for m in HOLE_RE.finditer(view.plain):
            result.add(
                "error", i, "SGL010",
                f"hole {m.group(0)} is not allowed in #!spec mode. "
                f"Either fill it in or switch to #!sketch / #!craft."
            )


def lint_actor_as_state(views: tuple, states: frozenset, result: LintResult):
    """Flag `(X)` where X looks like a state name, outside `state` blocks (`states`:
    the line numbers they cover). Dialect glyphs and `@read`/`@write` principal
    lists hold no actor glyph (LineView.bare)."""
    for i, view in enumerate(views, start=1):
        if i in states:
            continue
        for m in GLYPH_PATTERNS["actor"].finditer(view.bare):
            name = m.group(1).strip().lower()
            if name in STATE_VOCABULARY:
                result.add(
                    "warn", i, "SGL020",
                    f"({m.group(1)}) looks like a lifecycle state, not an actor. "
                    f"Use a `state {{Entity}} {{ ... }}` block instead."
                )


def lint_prose_verbs(views: tuple, result: LintResult):
    """Flag prose verbs appearing between glyphs on a flow-like line.

    Skip verbs that appear inside a modifier expression like `@inv excludes(...)`,
    where the verb is a predicate name and is legitimately English.
    """
    for i, view in enumerate(views, start=1):
        line = view.bare.strip()
        if not line or _section_or_mode(view.plain):
            continue

        # Blank out anything inside modifier expressions `@name(...)` so we
        # don't flag prose inside them. This is intentionally loose; invariant
        # contents are allowed to be prose-like.
        masked = re.sub(r"@[a-z][a-z0-9_-]*\([^)]*\)", lambda m: " " * len(m.group(0)), line)
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


def _section_or_mode(plain: str) -> bool:
    """A `---` section line or a `#!` mode line (no flow there)."""
    return plain.strip().startswith(("---", "#!"))


def lint_invented_modifiers(views: tuple, result: LintResult,
                            known=None, deferred=frozenset()):
    """Flag @-modifiers not in the known vocabulary.

    Context-sensitive: a bare `@name : description` at the start of a line
    is an invariant label, not a modifier. Skip those. `known` is the allowlist
    (default: the core VALID_MODIFIERS; a dialect extends it); `deferred` are
    modifiers a dialect validates itself (never reported here).
    """
    if known is None:
        known = VALID_MODIFIERS
    for i, view in enumerate(views, start=1):
        line = view.plain.strip()
        if not line or _section_or_mode(line):
            continue

        # Invariant-label form: line starts with @name and has a `:` after it,
        # or the invariant appears as a standalone named condition.
        if re.match(r"^@[a-z][a-z0-9_-]*\s*:", line):
            continue

        for m in MOD_TOKEN_RE.finditer(line):
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


def lint_semicolon_separator(views: tuple, result: LintResult):
    """Flag `;` used as a statement separator (not standard)."""
    for i, view in enumerate(views, start=1):
        if ";" in view.plain:
            result.add(
                "warn", i, "SGL050",
                "`;` is not a Sigil statement separator. "
                "Put each statement on its own line, or use a `branch on ... { ... }` block."
            )


def lint_reverse_arrow(views: tuple, result: LintResult):
    """`<-` is not a valid Sigil arrow (flows are source-to-sink)."""
    for i, view in enumerate(views, start=1):
        # Careful: `<->` contains `<-`. Blank `<->` first.
        stripped = view.plain.replace("<->", "   ")
        if re.search(r"(?<!\w)<-(?!\w)", stripped):
            result.add(
                "error", i, "SGL060",
                "reverse arrow `<-` is not valid — flows are source-to-sink. "
                "Rewrite as `src -> dst`."
            )


def lint_duplicate_glyph_in_flow(views: tuple, result: LintResult):
    """Warn when the same exact glyph appears twice in one flow line."""
    for i, view in enumerate(views, start=1):
        line = view.plain.strip()
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


def lint_state_block_syntax(transitions: tuple, result: LintResult):
    """SGL090: a `state` block line that writes a `-<trigger>->` the model does not
    read as a trigger (`transitions`: the walk's Transition of each line)."""
    for t in transitions:
        if t.writes_trigger and t.kind != "triggered":
            result.add(
                "warn", t.line, "SGL090",
                "malformed state transition. Expected: `source -<trigger>-> target`"
            )


def _edit_distance(a: str, b: str, most: Optional[int] = None) -> int:
    """Levenshtein distance; with `most`, any distance over it may come back as
    most + 1 (a row's minimum never falls, so the rest is skipped)."""
    if most is not None and abs(len(a) - len(b)) > most:
        return most + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if most is not None and min(cur) > most:
            return most + 1
        prev = cur
    return prev[-1]


def _deletions(word: str, k: int) -> set:
    """word and every string k or fewer deletions make of it."""
    out = edge = {word}
    for _ in range(k):
        edge = {w[:i] + w[i + 1:] for w in edge for i in range(len(w))}
        out = out | edge
    return out


def _deletion_index(words) -> dict:
    """{variant: [word]} over _deletions(word, 2): two words within edit distance
    k <= 2 share a variant of k or fewer deletions each, so a typo hint looks up
    its candidates instead of measuring every word (symmetric-delete search)."""
    out = {}
    for word in words:
        for v in _deletions(word, 2):
            out.setdefault(v, []).append(word)
    return out
