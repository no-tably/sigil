"""
The text scanning lint's rules share on top of sigil.core.lex (which keeps the
tables the parser reads too): the principal-set mask, the block-string pre-pass
that reports SGL170 (collapse_block_strings) and a state block's lines. The
bracket-group scan and a dialect's masks are sigil.core.lex's (balanced_end,
apply_masks).
"""

import re

from sigil.core.lex import (
    PRINCIPAL_SET_RE, STATE_HEAD_FLAT_RE, fold_block_strings, plain_comment_col)
from sigil.core.vocab import LintResult, strip_comment


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


# ---------------------------------------------------------------------------
# Multiline block-strings — the `"""…"""` pre-pass (sigil's ONLY multiline form).
# The rest of the linter is not taught about blocks: after this pass every block
# reads as an ordinary single-line `: "<…>"` value.
# ---------------------------------------------------------------------------

def collapse_block_strings(lines: list, result: LintResult) -> list:
    """Pre-pass: fold every `\"\"\"…\"\"\"` multiline block-string into a masked
    single-line STR on its opening line, blanking the consumed body lines (the
    list length — and so every later diagnostic's line number — is preserved;
    see sigil.core.lex.fold_block_strings). Lint reads comments plainly here and
    reads each folded line again (the closing line's suffix may open another
    block: `\"\"\" -> [C] : \"\"\"`). An unterminated block (opening `\"\"\"` with no
    closing `\"\"\"`) is rejected (SGL170); every line from its opener is blanked,
    so the dangling `\"\"\"` leaks no other diagnostic."""
    folded = fold_block_strings(lines, plain_comment_col, rescan=True)
    if folded.unterminated is not None:
        result.add(
            "error", folded.unterminated + 1, "SGL170",
            "unterminated block-string: an opening `\"\"\"` has no matching "
            "closing `\"\"\"`. A `\"\"\"…\"\"\"` multiline string must be closed.",
        )
    return folded.lines


def _iter_state_block(lines: list):
    """Yield `(line_no, line, where)` for every line, `line` comment-stripped and
    trimmed. `where` is "header" for a `state … {` opener, "body" inside its block,
    "end" for the line that closes it, else None."""
    in_state_block = False
    brace_depth = 0
    for i, raw in enumerate(lines, start=1):
        line = strip_comment(raw).strip()
        if STATE_HEAD_FLAT_RE.match(line):
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
