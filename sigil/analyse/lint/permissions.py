"""
The permission graph: `@read(…)` / `@write(…)` access lists name declared
principals, `@borrow(…)` narrows to read or write. The lists are the walk's
modifier tokens (a flow's, an owns header's, a control-block header's).
"""

import re
from typing import NamedTuple

from sigil.core.lex import DIALECT_COL, PRINCIPAL_SET_RE
from sigil.core.statements import BlockMods, Definition, SectionHead
from sigil.core.tokens import dialect_glyph_nodes, glyph_spans
from sigil.core.vocab import LintResult
from sigil.analyse.lint.reading import documents, header_tokens, state_lines


# `@borrow(…)` with a narrowing arg, lending access to a delegate (the lent
# resource is a store `|S|` or a bare name). The arg is captured whatever it is so
# lint_permission_graph can reject anything but `read` / `write`; bare `@borrow`
# (full access) has no arg to check.
BORROW_ACCESS_RE = re.compile(r"@borrow\s*\((?P<arg>[^)]*)\)")


# A bare principal name in a set — a declared entity name or a generic role name.
PRINCIPAL_NAME_RE = re.compile(r"^[A-Za-z_][\w-]*$")


def is_access_list(tok) -> bool:
    """A `@read(…)` / `@write(…)` modifier token (its principal list)."""
    return tok.kind == "mod" and PRINCIPAL_SET_RE.fullmatch(tok.text) is not None


def principal_base(name: str) -> str:
    """The principal a glyph's name declares: generics, inputs and a dotted
    address tail dropped."""
    return re.sub(r"<[^<>]*>|\([^()]*\)", "", name).strip().split(".")[0].strip()


def declared_principals(walk, markers: dict) -> set:
    """The declared ENTITY names a `@read`/`@write` principal may name (the
    closed-reference universe), from the walk's reading (`walk`, a
    sigil.core.statements.Walk): the bare name of every glyph of any kind
    (`[X]`/`{X}`/`<X>`/`(X)`/`|X|`) its tokens hold — a statement's or a
    control-block header's, a glyph token or one inside a payload, op or
    modifier argument — and of every dialect glyph they hold (its Node); every
    core glyph written on a `state` block's lines (head to close: its owner, a
    transition's trigger event — `-<E>-` reads as the event glyph `<E>` — its
    payload and modifiers, the text after the `}`); and the glyphs its records
    name: a definition's head, a layer section's title, and those in the
    modifiers after a block's `}`. An access list's members are no declaration of their
    own, nor is a branch marker the rules read past (`markers`:
    lint.composition.branch_markers)."""
    declared = _state_names(walk)
    for d in documents(walk.doc):
        for item in d.items:
            declared.update(_record_names(item))
    for toks, skip in _token_runs(walk.statements, walk.doc, markers):
        for k, t in enumerate(toks):
            if k != skip and not is_access_list(t):
                declared.update(_token_names(t, walk.lexicon))
    return declared


def _state_names(walk) -> set:
    """The principal name of each core glyph on the lines a `state` block covers
    (lint.reading.state_lines), read from the walk's code of each line with its
    access lists and dialect glyphs blanked."""
    names: set = set()
    for n in state_lines(walk.doc):
        code = walk.codes[n - 1].text.replace(DIALECT_COL, " ")
        names |= glyph_names(PRINCIPAL_SET_RE.sub(lambda m: " " * len(m.group(0)), code))
    return names


def _token_runs(statements: tuple, doc, markers: dict):
    """(tokens, index of the branch marker read past or -1) of each statement and
    control-block header (lint.reading.header_tokens)."""
    for st in statements:
        skip = st.branch
        if skip >= 0:
            start = st.code.col + st.toks[skip].col
            if (start, start + len(st.toks[skip].text)) not in markers.get(st.line - 1, ()):
                skip = -1
        yield st.toks, skip
    for h in header_tokens(doc):
        yield h.toks, -1


def _token_names(tok, lx) -> set:
    """The principal names one token declares: its dialect glyph's (`lx`: the
    dialect's reading), each core glyph in its text outside the dialect glyphs
    there (glyph_names), and those dialect glyphs' in a payload's or a
    modifier's text."""
    if tok.node is not None:
        return _bases([tok.node.name], holes=("?",))
    nodes = dialect_glyph_nodes(tok.text, lx) if lx.tokenizers else []
    text = tok.text
    for _node, (start, end) in nodes:
        text = text[:start] + " " * (end - start) + text[end:]
    names = glyph_names(text)
    if tok.kind in ("payload", "mod"):
        names |= _bases([node.name for node, _span in nodes], holes=("?",))
    return names


def _record_names(item) -> set:
    """The principal names a walk record declares (see declared_principals)."""
    if isinstance(item, Definition):
        return (_bases([item.name]) if item.kind is not None else set()) \
            | glyph_names(item.tail)
    if isinstance(item, BlockMods):
        return glyph_names(item.text)
    if isinstance(item, SectionHead) and item.level:
        return glyph_names(item.title)
    return set()


def glyph_names(text: str) -> set:
    """The principal name of each core glyph written in `text` (core's
    glyph_spans: outside a `"…"` string, nested glyphs too)."""
    return _bases([g.name for g in glyph_spans(text)])


def _bases(names, holes=("?", "_")) -> set:
    """The principal_base of each name, without the empty ones and the holes."""
    return {b for b in map(principal_base, names) if b and b not in holes}


class AccessMod(NamedTuple):
    """A modifier token, where access lists are written: `text` its code (string
    contents blanked, so a `,` or `)` in a string is inert), `raw` the same
    columns as written (what a message quotes)."""
    line: int
    text: str
    raw: str


def _access_mod(line: int, tok, code) -> AccessMod:
    """The AccessMod of a modifier token `tok` of the Code span `code`."""
    return AccessMod(line, tok.text, code.raw[tok.col:tok.col + len(tok.text)])


def access_modifiers(statements: tuple, headers: list) -> list:
    """The AccessMod of every modifier token of the control-block headers
    (`headers`: lint.reading.HeaderTokens) and the statements, in reading order:
    by line, a header before the statements after its `{`."""
    found = [(h.line, 0, _access_mod(h.line, t, h.code))
             for h in headers for t in h.toks if t.kind == "mod"]
    found += [(st.line, 1, _access_mod(st.line, t, st.code))
              for st in statements for t in st.toks if t.kind == "mod"]
    return [mod for _line, _order, mod in sorted(found, key=lambda f: f[:2])]


def list_members(mod: AccessMod, start: int, end: int) -> list:
    """The members of the comma-list at mod.text[start:end], each as written
    (stripped): split where the code has a comma, so a comma in a string
    separates nothing."""
    out, at = [], start
    for piece in mod.text[start:end].split(","):
        out.append(mod.raw[at:at + len(piece)].strip())
        at += len(piece) + 1
    return out


def lint_permission_graph(statements: tuple, headers: list, declared: set,
                          result: LintResult):
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
        (SGL143; `declared`: declared_principals);
      - a `@borrow(...)` narrowing arg is `read`/`write` (SGL144).
    Within a line the lists come first, then the borrows."""
    by_line: dict = {}
    for mod in access_modifiers(statements, headers):
        by_line.setdefault(mod.line, []).append(mod)
    for line, mods in by_line.items():
        for mod in mods:
            m = PRINCIPAL_SET_RE.fullmatch(mod.text)
            if m:
                _check_list(line, m.group("mod"), mod.raw[m.start("set"):m.end("set")].strip(),
                            list_members(mod, *m.span("set")), declared, result)
        for mod in mods:
            m = BORROW_ACCESS_RE.match(mod.text)
            if m:
                _check_borrow(line, mod.raw[m.start("arg"):m.end("arg")].strip(), result)


def _check_list(i: int, mod: str, body: str, members: list, declared: set,
                result: LintResult):
    """SGL140–143 for one `@read(…)` / `@write(…)` list: `body` its text and
    `members` its members (list_members), as written."""
    if body == "":
        result.add(
            "error", i, "SGL140",
            f"`@{mod}()` is an empty principal list — list at least one "
            f"principal entity, e.g. `@{mod}(boss)`."
        )
        return
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


def _check_borrow(i: int, arg: str, result: LintResult):
    """SGL144: a `@borrow(…)` narrowing arg that is not `read` / `write`."""
    if arg not in ("read", "write"):
        result.add(
            "error", i, "SGL144",
            f"`@borrow({arg})` — a borrow narrowing arg is `read` or "
            f"`write` (a child borrows access ⊆ the parent's). Bare "
            f"`@borrow` lends the full access."
        )
