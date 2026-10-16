"""
Composition trees: `\\-` branch markers, their relation characters (core and a
dialect's) and where a branch may stand. The walk reads a marker where the model
does (a statement's start, after a glyph-only parent, after the line's leading
marker); a `\\-` anywhere else is text (prose, a payload, a string).
"""

from typing import Optional

from sigil.core.graph import walk_depth
from sigil.core.lex import CORE_RELATIONS, branch_re
from sigil.core.statements import Walk
from sigil.core.vocab import LintResult


MALFORMED = ("malformed composition branch: a branch is "
             "`\\- [*-]? [(N)- | {{cond}}-]? <rel>` with <rel> one of "
             "`{relations}` (> contains · & has · ? when · $ from data · "
             "@ attached · ! alerts when · = gathers · _ one of), or a bare "
             "spawn `\\-*`.")

NO_PARENT = ("composition branch has no parent: its parent is the nearest glyph "
             "line above at a shallower indent, and a plain glyph line at the "
             "branch's own indent or deeper in between ends the tree (e.g. `[Ship]` "
             "then `    \\-& {Transform}`).")


def branch_markers(walk: Walk, relations: Optional[str] = CORE_RELATIONS) -> dict:
    """{line index: [(start, end)]} of each branch marker the walk read whose
    relation is one of `relations` (None: every one — a dialect that owns the
    markers judges them), which the per-line rules read past."""
    ok = branch_re(relations) if relations is not None else None
    out: dict = {}
    for st in walk.statements:
        if st.branch < 0:
            continue
        tok = st.toks[st.branch]
        if ok is None or ok.fullmatch(tok.text):
            start = st.code.col + tok.col
            out.setdefault(st.line - 1, []).append((start, start + len(tok.text)))
    return out


def lint_composition(walk: Walk, graph, result: LintResult, relations: str = CORE_RELATIONS):
    """Validate composition-tree branch markers, in line order.

    SGL111 — a branch the model hangs under nothing (`graph`: the parsed
             document, None when it could not be parsed).
    SGL110 — a `\\-` where a branch stands that is not a well-formed branch with a
             known relation (one per line)."""
    found = [(line, 0, "SGL111", NO_PARENT) for line in parentless_lines(graph)]
    found += [(line, 1, "SGL110", MALFORMED.format(relations=relations))
              for line in malformed_lines(walk, relations)]
    for line, _order, rule, message in sorted(found):
        result.add("error", line, rule, message)


def parentless_lines(graph) -> list:
    """The lines (1-based, once each) of the tree entries with a relation and no
    parent, in every expansion."""
    if graph is None:
        return []
    return sorted({t.line for sub, _owner, _lvl in walk_depth(graph)
                   for t in sub.tree if t.rel is not None and t.parent is None})


def malformed_lines(walk: Walk, relations: str) -> list:
    """The lines (1-based, once each) with a `\\-` where a branch stands that no
    relation of `relations` makes a branch."""
    ok = branch_re(relations)
    bad = set()
    for st in walk.statements:
        text = walk.codes[st.line - 1].text
        if any(not ok.match(text, st.code.col + col) for col in st.marks):
            bad.add(st.line)
    return sorted(bad)
