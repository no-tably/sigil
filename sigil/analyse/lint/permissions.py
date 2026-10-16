"""
The permission graph: `@read(…)` / `@write(…)` access lists name declared
principals, `@borrow(…)` narrows to read or write.
"""

import re

from sigil.core.vocab import GLYPH_PATTERNS, LintResult, strip_comment
from sigil.core.lex import PRINCIPAL_SET_RE
from sigil.analyse.lint.scan import BORROW_ACCESS_RE, PRINCIPAL_NAME_RE, _mask_principal_sets


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
