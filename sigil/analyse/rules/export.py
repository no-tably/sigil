"""
check_export.py — Sigil export readiness: can this spec be exported as a build
skeleton (export.py), one folder per system with a stated contract at each
boundary?

A rule module for check.py, loaded only when a check is asked for export
readiness (`check.py --export`, `check(…, export=True)`): `rules(ck)` returns this
module's `ck.Rule`s, where `ck` is check.py itself (passed in, so this module
never imports it). Rules (binding: errors in spec):

    SGC401 no-home            a component written in two systems, neither of
                              which encloses the other
    SGC402 untyped-boundary   a flow across a system boundary with no payload,
                              or a synchronous call across one with no return

Both read the export model's facts (export_model.py: Model.shared, Model.untyped),
so what the gate refuses is exactly what the exporter would write ambiguously.
Systems are inferred: every `X := { … }` expansion, every composition-tree root,
and the top level (export.py names it after the spec file; here it is "the top
level", since a check has no file name and no fact depends on it).

Standard library only. Deterministic: the model's order, never set order.
"""

from __future__ import annotations

from sigil.model import systems


TOP_STEM = "top"                     # the top system's key in the model; never shown


def model_of(doc):
    """The export model of a check's document, built once and kept on it."""
    found = doc.__dict__.get("_export_model")
    if found is None:
        found = doc.__dict__["_export_model"] = systems.model_of(
            doc.graph, TOP_STEM, systems.accepted(doc.acks, doc.comments))
    return found


# ---------------------------------------------------------------------------
# Wording (pure)
# ---------------------------------------------------------------------------

def system_name(key: str, top: str) -> str:
    return "the top level" if key == top else f"`{key}`"


def system_list(keys, top: str) -> str:
    """`A`, `B` and the top level."""
    names = [system_name(k, top) for k in keys]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def flow_text(u) -> str:
    return f"`{u.src} {u.arrow} {u.dst}`"


# ---------------------------------------------------------------------------
# SGC401 no-home
# ---------------------------------------------------------------------------

def no_home_hit(ck, shared, top: str):
    """One Hit for a component with no one home, on the first line it is written."""
    where = system_list(shared.systems, top)
    return ck.Hit(
        shared.lines[0],
        f"`{shared.glyph}` is written in {where}, and neither encloses the other: it has "
        f"no one home (it would be exported under {system_name(shared.home, top)})",
        f"`{shared.glyph}` is written in {where}. Which system does it live in?",
        anchor=("node", shared.component),
        fix=f"write `{shared.glyph}` in one system only and reach it from the others, or "
            "write it where one system encloses them all (the top level)")


def find_no_home(ck, doc):
    model = model_of(doc)
    for shared in model.shared:
        yield no_home_hit(ck, shared, model.top)


# ---------------------------------------------------------------------------
# SGC402 untyped-boundary
# ---------------------------------------------------------------------------

def untyped_hit(ck, u, top: str):
    """One Hit for a boundary flow that states no payload or no return."""
    where = system_list(u.systems, top)
    flow = flow_text(u)
    if u.missing == "payload":
        statement = f"{flow} crosses the boundary of {where} with no payload"
        ask = f"{flow} crosses the boundary of {where}. What does it carry?"
        fix = "name what it carries: `: verb({Data})`, or a data or event glyph"
    else:
        statement = (f"{flow} is a call across the boundary of {where} that states no "
                     "return")
        ask = f"{flow} is a call across the boundary of {where}. What does it return?"
        fix = "state what the call returns (`=> {Result}`), or send it async (`~>`)"
    return ck.Hit(u.line, statement, ask,
                  anchor=("wire", f"{u.src} {u.arrow} {u.dst}"), fix=fix,
                  scopes=(("missing", u.missing),))


def find_untyped(ck, doc):
    model = model_of(doc)
    for u in model.untyped:
        yield untyped_hit(ck, u, model.top)


# ---------------------------------------------------------------------------
# The module's rules
# ---------------------------------------------------------------------------

def rules(ck) -> list:
    return [
        ck.Rule("SGC401", "no-home", "binding",
                ask="This component is written in two systems. Which one does it live in?",
                why="An export writes each component once, in its system's folder; a "
                    "component with two homes has two owners and no one contract.",
                fix="write it in one system only, or where one system encloses the rest",
                match=lambda doc: find_no_home(ck, doc), family="40"),
        ck.Rule("SGC402", "untyped-boundary", "binding",
                ask="This flow crosses a system boundary. What does it carry, and what "
                    "does the call return?",
                why="The boundary is the contract the systems are built against "
                    "separately; a flow that names no payload, or a call no return, "
                    "leaves each side to guess it.",
                fix="name the payload (`: verb({Data})`) and, for a call, its return "
                    "(`=> {Result}`)",
                match=lambda doc: find_untyped(ck, doc), family="40",
                satisfiers=(("call", "=>"), ("call", "~>"), ("call", "*>"))),
    ]
