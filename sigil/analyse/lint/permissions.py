"""
The permission graph: `@read(…)` / `@write(…)` access lists name declared
principals, `@borrow(…)` narrows to read or write. The lists are the walk's
modifier tokens (a flow's, an owns header's, a control-block header's).
"""

import re
from typing import NamedTuple

from sigil.core.lex import PRINCIPAL_SET_RE
from sigil.core.tokens import dialect_glyph_nodes
from sigil.core.vocab import GLYPH_PATTERNS, LintResult


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


def declared_principals(views: tuple, statements: tuple, lx) -> set:
    """The declared ENTITY names a `@read`/`@write` principal may name (the
    closed-reference universe): the bare name of every glyph of any kind
    (`[X]`/`{X}`/`<X>`/`(X)`/`|X|`) in the document's code (LineView.bare: an
    access list's members are not their own declaration), and of each dialect
    glyph (`lx`: the dialect's reading) a statement holds — as a token or inside
    its payload or a modifier's argument."""
    declared: set = set()
    for view in views:
        for pat in GLYPH_PATTERNS.values():
            for m in pat.finditer(view.bare):
                base = principal_base(m.group(1).strip())
                if base and base not in ("?", "_"):
                    declared.add(base)
    if lx.tokenizers:
        for st in statements:
            for t in st.toks:
                if t.node is not None:
                    names = [t.node.name]
                elif t.kind in ("payload", "mod") and not is_access_list(t):
                    names = [node.name for node, _span in dialect_glyph_nodes(t.text, lx)]
                else:
                    continue
                declared.update(b for b in map(principal_base, names) if b and b != "?")
    return declared


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
