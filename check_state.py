"""
check_state.py — Sigil composition checks over shared state, state machines and
the acknowledgements themselves (RFC 0003, rfcs/0003-catalog.md).

A rule module for check.py: `rules(ck)` returns this module's `ck.Rule`s, where
`ck` is check.py itself (passed in, so this module never imports it). So far:

    SGC003 ack-unused   an acknowledgement that covers no finding of a rule it names

Standard library only. Deterministic: no clock, no randomness, no set-order output.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# SGC003 ack-unused (catalog §5)
# ---------------------------------------------------------------------------

def judged(finding) -> bool:
    """Whether a first-pass finding can make an acknowledgement used: a static one
    (no witness) or a trace one with a k <= 1 witness. Craft explores at k = 1 and
    spec at k = 2, so counting a k >= 2-only finding would flip the verdict with
    the mode. Severity is not looked at: a hidden or unemitted finding counts."""
    return finding.hit.k is None or finding.hit.k <= 1


def covered_names(ack, findings) -> frozenset:
    """The rule names whose judged findings `ack` covered (check.acknowledge
    attaches to each finding the acknowledgement that covered it)."""
    return frozenset(f.rule.name for f in findings if f.ack == ack and judged(f))


def judgeable_names(ack, known: frozenset, refused: frozenset) -> tuple:
    """The names of a valid acknowledgement that SGC003 judges, in written order.
    A void one (no reason, SGC002) and names no rule has or that cannot be
    acknowledged (SGC001) are left to those rules."""
    if not ack.reason:
        return ()
    return tuple(n for n in ack.names if n in known and n not in refused)


def stale_names(ack, findings, known: frozenset, refused: frozenset) -> tuple:
    used = covered_names(ack, findings)
    return tuple(n for n in judgeable_names(ack, known, refused) if n not in used)


def ack_scope(ack) -> str:
    """Where an acknowledgement reaches, as the message says it."""
    if ack.document:
        return "in the document"
    if len(ack.span) > 1:
        return "in its block"
    if ack.span:
        return "on its line"
    return "anywhere: it sits above no statement"


def stale_hit(ck, ack, name: str):
    where = ack_scope(ack)
    return ck.Hit(ack.line, f"the acknowledgement covers no `{name}` finding {where}",
                  f"This acknowledgement covers no `{name}` finding {where}. Is it stale?",
                  anchor=("comment", ack.line), scopes=(("rule", name),),
                  fix=f"delete `{name}` from the acknowledgement, or move it to the "
                      "line it is about")


def ack_unused_rule(ck):
    def match(doc):
        for ack in doc.acks:
            for name in stale_names(ack, doc.findings, doc.known, ck.NOT_ACKNOWLEDGEABLE):
                yield stale_hit(ck, ack, name)

    return ck.Rule(
        "SGC003", "ack-unused", "advisory",
        ask="This acknowledgement covers no finding of the rule it names. Is it stale?",
        why="A stale acknowledgement may later silence an unrelated new finding.",
        fix="delete or move the stale acknowledgement", match=match,
        acknowledgeable=False, after_acks=True, family="0")


# ---------------------------------------------------------------------------
# The module's rules
# ---------------------------------------------------------------------------

def rules(ck) -> list:
    return [ack_unused_rule(ck)]
