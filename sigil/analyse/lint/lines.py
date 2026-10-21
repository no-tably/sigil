"""
Per-line rules: the mode line (SGL001/SGL002), holes in spec mode, an actor named
like a state, prose verbs between glyphs, invented modifiers, `;` separators,
reversed arrows, a glyph twice in one flow, a `state` block's syntax, a `#&`
declaration no dialect declares (SGL189) — and the edit-distance index the
near-name suggestions use (here and in lint.graph).

The mode-line rules read the document's lines through core's line readings
(lex.first_content, is_mode_line, is_comment_line); the prose verbs rule reads the
walk's tokens (statements and control-block headers); the others read each line's
code as the walk found it (lint.reading.LineView) or the walk's `state` block lines
(Transition).
"""

import re
from typing import Optional

from sigil.core.vocab import (
    ANY_GLYPH_RE, ARROW_RE, LintResult, VALID_LOOP_MODS, VALID_MODES,
    VALID_MODIFIERS, VALID_PARALLEL_MODS, VALID_STREAM_POLICIES)

from sigil.core.lex import HOLE_RE, MOD_TOKEN_RE, first_content, is_comment_line, is_mode_line
from sigil.core.tokens import glyph_spans


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
    """The first content line (lex.first_content: past blank and comment lines)
    should be a mode declaration."""
    k = first_content(lines)
    if k is None:
        result.add("warn", 0, "SGL003", "document is empty or all comments")
        return None
    stripped = lines[k].strip()
    parts = stripped.split()
    if parts[0] not in VALID_MODES:
        result.add(
            "warn", k + 1, "SGL002",
            f"first content line is not a mode declaration "
            f"(#!spec / #!sketch / #!craft). Got: {stripped[:40]!r}"
        )
        return None
    if len(parts) > 1:
        result.add(
            "error", k + 1, "SGL001",
            f"mode line must be exactly '{parts[0]}' — no trailing text. "
            f"Put titles in section headers: `--- Title ---`"
        )
    return parts[0]


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
    lists hold no actor glyph (LineView.bare); the actors are core's glyph_spans,
    the name quoted as written between the parens."""
    for i, view in enumerate(views, start=1):
        if i in states:
            continue
        for g in glyph_spans(view.bare):
            if g.kind != "actor" or g.name.lower() not in STATE_VOCABULARY:
                continue
            result.add(
                "warn", i, "SGL020",
                f"({view.bare[g.start + 1:g.end - 1]}) looks like a lifecycle state, "
                f"not an actor. Use a `state {{Entity}} {{ ... }}` block instead."
            )


def lint_prose_verbs(statements: tuple, headers: list, result: LintResult):
    """Flag a prose verb written between two glyphs with no arrow between them
    (`[A] calls [B]`). Reads the walk's tokens (a statement's, or a control-block
    header's): a `word` token between two core glyph tokens with no arrow token
    between them. A payload (`: calls({Doc})`), a modifier's argument
    (`@inv excludes(...)`), a string and a comment are tokens of their own or no
    token at all, so their words are never read as prose."""
    reads = [(st.line, st.toks) for st in statements]
    reads += [(h.line, h.toks) for h in headers]
    for line, toks in sorted(reads, key=lambda r: r[0]):
        for word in _prose_verbs_between_glyphs(toks):
            result.add(
                "warn", line, "SGL030",
                f"prose verb {word!r} appears between glyphs without an arrow. "
                f"Model as an invariant (@inv), a flow with an arrow, or a comment."
            )


def _prose_verbs_between_glyphs(toks) -> list:
    """For each pair of consecutive core glyph tokens with no arrow token between
    them, the first prose verb among the `word` tokens between them."""
    found, words, after_glyph = [], [], False
    for tok in toks:
        if tok.kind == "glyph" and tok.node is None:
            verb = next((w for w in words if w in PROSE_VERBS), None) if after_glyph else None
            if verb:
                found.append(verb)
            words, after_glyph = [], True
        elif tok.kind == "arrow":
            words, after_glyph = [], False
        elif tok.kind == "word":
            words += re.findall(r"[a-z]+", tok.text.lower())
    return found


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


def lint_declarations(declarations, declared: Optional[set], result: LintResult,
                      loaded: bool = False):
    """SGL189: a `#&` declaration no loaded dialect declares. `declarations`: the
    walk's Declaration records (lint.reading.declarations); `declared`: the loaded
    dialect's DECLARATIONS, or None. Core reads every `#&` line the same way (a
    declaration that draws nothing), so a name is only a dialect's to give: one is
    judged when no dialect is `loaded`, or the loaded one lists its DECLARATIONS. A
    dialect without that hook validates its own `#&` lines; nothing is said."""
    if loaded and declared is None:
        return
    for d in declarations:
        if d.name is None:              # a dialect's own opener (DECLARATION_BLOCKS)
            continue
        what = f"`#& {d.name}`" if d.name else "`#&`"
        if not loaded:
            result.add("warn", d.line + 1, "SGL189",
                       f"{what} is a dialect declaration, but no loaded dialect declares "
                       "it (--dialect NAME); core reads it as a declaration that draws "
                       "nothing.")
        elif d.name not in declared:
            known = ", ".join(f"`#& {n}`" for n in sorted(declared)) or "none"
            result.add("warn", d.line + 1, "SGL189",
                       f"{what} is a dialect declaration, but the loaded dialect does not "
                       f"declare it (it declares {known}).")


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
    """If a mode line (lex.is_mode_line) appears anywhere other than the top, flag
    it; blank and comment lines (lex.is_comment_line) come before it freely."""
    seen_content = False
    for i, raw in enumerate(lines, start=1):
        if is_mode_line(raw):
            if seen_content:
                result.add(
                    "error", i, "SGL080",
                    f"mode line '{raw.strip()}' must be the first non-empty line of the document."
                )
            seen_content = True     # a second mode line is misplaced too
        elif raw.strip() and not is_comment_line(raw):
            seen_content = True


def lint_state_block_syntax(transitions: tuple, result: LintResult):
    """SGL090: a `state` block line that writes a `-<trigger>->` the model does not
    read as a trigger, or a trigger list with an empty or repeated item; SGL092: a
    transition out of `$` that is no self-loop (`transitions`: the walk's
    Transition of each line)."""
    for t in transitions:
        if t.writes_trigger and t.kind != "triggered":
            result.add(
                "warn", t.line, "SGL090",
                "malformed state transition. Expected: `source -<trigger>-> target`"
            )
            continue
        names = t.triggers
        if "" in names:
            result.add("warn", t.line, "SGL090",
                       "empty trigger in a list. Expected: `source -<a, b>-> target`")
        twice = sorted({n for n in names if n and names.count(n) > 1})
        if twice:
            result.add("warn", t.line, "SGL090",
                       f"trigger <{twice[0]}> listed twice in one transition")
        if t.src == "$" and t.dst != "$":
            result.add("error", t.line, "SGL092",
                       "`$` is the end of a record: the only transition out of it is the "
                       "self-loop `$ -<E>-> $` (ignored on purpose). To begin a new record, "
                       f"write `+ -<{names[0] if names else 'E'}>-> {t.dst}`.")


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
