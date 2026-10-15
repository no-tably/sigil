"""
Rules over the parsed document (sigil.core.parse): undefined events, qualified
paths that match no occurrence, and the near-name suggestions they make.
"""

import re

from sigil.core.vocab import LintResult
from sigil.core import parse as render
from sigil.core.graph import matching_occurrences, occurrences, walk_depth
from sigil.analyse.lint.lines import _deletion_index, _deletions, _edit_distance


# ---------------------------------------------------------------------------
# Graph checks (via sigil.core.parse)
# ---------------------------------------------------------------------------

def parse_for_lint(text: str, dialect=None):
    """The parsed document (render.parse_document), or None if the parser fails —
    the parser has its own tests; lint stays up."""
    try:
        return render.parse_document(text, dialect=dialect)
    except Exception:
        return None


def lint_graph(text: str, result: LintResult, dialect=None, graph=None):
    """Checks that need the parsed document (render.parse_document; pass `graph`
    when it is already parsed).

    SGL112 (warn) — a qualified path `[A]/{B}` that matches no occurrence in the
                    composition trees.
    SGL091 (info) — a state-machine trigger that matches no event but is a likely
                    typo of one (edit distance ≤ 1, ≤ 2 for 5+ characters)."""
    g = graph if graph is not None else parse_for_lint(text, dialect)
    if g is None:
        return
    lines = text.splitlines()

    def line_of(needle):
        for n, ln in enumerate(lines, 1):
            if needle in ln:
                return n
        return 0

    for sub, _owner, _lvl in walk_depth(g):
        occ = occurrences(sub)
        for e in sub.edges:
            for nid, path in ((e.src, e.src_path), (e.dst, e.dst_path)):
                if path and not matching_occurrences(sub, occ, nid, path):
                    shown = "/".join(path)
                    at = next((n for n, ln in enumerate(lines, 1)
                               if re.search(r"/[\[{<(|~*]*" + re.escape(path[-1]) + r"[\]}>)|]", ln)),
                              0)
                    result.add("warn", at, "SGL112",
                               f"path `{shown}` matches nothing: no `{path[-1]}` sits directly "
                               f"under `{path[-2]}` in a composition tree.")
    events = {n.name.lower(): n.name for sub, _o, _l in walk_depth(g)
              for n in sub.nodes.values() if n.kind == "event" and not n.is_hole}
    seen, close = set(), None
    for sub, _owner, _lvl in walk_depth(g):
        if sub.role != "state":
            continue
        for e in sub.edges:
            trig = (e.label or "")[1:-1]
            key = trig.lower()
            if not trig or key in events or key in seen:
                continue
            seen.add(key)
            limit = 2 if len(key) >= 5 else 1
            if close is None:
                close = _deletion_index(events)
            maybe = {low for v in _deletions(key, limit) for low in close.get(v, ())}
            near = sorted((d, events[low]) for low in maybe
                          if (d := _edit_distance(key, low, limit)) <= limit)
            if near:
                result.add("info", line_of(f"-<{trig}>->"), "SGL091",
                           f"trigger <{trig}> matches no event; did you mean <{near[0][1]}>?")
