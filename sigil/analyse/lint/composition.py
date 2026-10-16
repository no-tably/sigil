"""
Composition trees: `\\-` branch markers, their relation characters (core and a
dialect's) and where a branch may stand.
"""

from sigil.core.lex import BRANCH_ANY_RE, CORE_RELATIONS, branch_re
from sigil.core.vocab import LintResult, strip_comment


# Composition-tree branch markers (language.md "Composition trees"; the patterns
# are sigil.core.lex's). A dialect may add relations (COMPOSITION_RELATIONS) or
# take over this check entirely (COMPOSITION_LINT = False).
def lint_composition(lines: list, result: LintResult, relations: str = CORE_RELATIONS) -> list:
    """Validate composition-tree branch markers and mask them for the per-line rules.

    SGL110 — a `\\-` that is not a well-formed branch with a known relation.
    SGL111 — a branch at the start of a line with no parent above it (nothing at a
             shallower indent to hang under).
    Returns the lines with valid markers blanked to spaces (line length preserved)."""
    ok = branch_re(relations)
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
        for m in BRANCH_ANY_RE.finditer(code):
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
