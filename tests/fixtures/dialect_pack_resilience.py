"""An example dialect rule pack (RFC 0003 catalog §11): two rules the core dropped
because they ask for a component shape, kept here to prove the rule-pack hook.

    unbroken-dependency  an external call with @timeout and retries whose caller
                         neither declares `@inv breaker(…)` nor owns a state
                         machine (was SGC105).
    shared-pool          a node making two or more external calls, one of them
                         retrying or without @timeout, that declares no
                         `@inv bulkhead(…)` (was SGC164).

An external call is the core's (catalog §1.4): an `op ns.verb(…)`, or a call to an
actor that returns. Both rules are craft-only hints: they ask nothing in sketch or
spec. Ids use the pack's own prefix, RSL. Standard library only; loaded with
dialects.load(<this path>).
"""

NAME = "pack-resilience"
INV_HEADS = {"breaker", "bulkhead"}
READ_VERBS = {"peek"}
LINT_CODES = set()


# ---------------------------------------------------------------------------
# Model facts (read from check.Doc: doc.graphs, doc.sc, doc.scene, doc.sim)
# ---------------------------------------------------------------------------

def _inv_heads(mods) -> set:
    """The heads of the `@inv head(…)` modifiers among (name, arg) pairs."""
    return {(arg or "").split("(")[0].strip() for name, arg in mods if name == "inv"}


def _declared_heads(doc) -> dict:
    """{node id: the @inv heads on any occurrence of the node}."""
    out = {}
    for graph, _owner, _level in doc.graphs:
        for nid, node in graph.nodes.items():
            out.setdefault(nid, set()).update(_inv_heads(node.mods))
    return out


def _machine_owners(doc) -> set:
    """The ids of the nodes that own a state machine."""
    return {owner for graph, owner, _level in doc.graphs
            if graph.role == "state" and owner is not None}


def _is_external(doc, w) -> bool:
    if w.call is not None and w.call.external:
        return True
    dst = doc.sc.nodes.get(w.dst)
    return (dst is not None and dst.node.kind == "actor" and w.kind != "!>"
            and doc.sim.returned(w) is not None)


def _external_calls(doc) -> list:
    """The external call wires outside state machines, in scene order."""
    return [w for w in doc.sc.wires if w.role == "flow" and _is_external(doc, w)]


def _policy_names(doc, w) -> set:
    return {name for name, _arg in doc.scene.call_policy(w)}


def _retries(doc, w) -> bool:
    return "×" in _policy_names(doc, w)


def _timed(doc, w) -> bool:
    return bool({"timeout", "deadline"} & _policy_names(doc, w))


def _name(doc, nid: str) -> str:
    sn = doc.sc.nodes.get(nid)
    return sn.node.name if sn is not None else nid


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _unbroken(api, doc):
    if doc.mode != "craft":
        return
    heads, machines = _declared_heads(doc), _machine_owners(doc)
    for w in _external_calls(doc):
        if not (_timed(doc, w) and _retries(doc, w)):
            continue
        if "breaker" in heads.get(w.src, ()) or w.src in machines:
            continue
        who = _name(doc, w.src)
        yield api.Hit(w.line, f"`{who}` retries this call with no breaker",
                      f"Does `{who}` stop calling when the callee keeps failing?",
                      anchor=("node", w.src),
                      fix="declare `@inv breaker(…)` on the caller, or give it a state machine")


def _shared_pool(api, doc):
    if doc.mode != "craft":
        return
    heads = _declared_heads(doc)
    by_src = {}
    for w in _external_calls(doc):
        by_src.setdefault(w.src, []).append(w)
    for nid, calls in sorted(by_src.items()):
        risky = [w for w in calls if _retries(doc, w) or not _timed(doc, w)]
        if len(calls) < 2 or not risky or "bulkhead" in heads.get(nid, ()):
            continue
        who = _name(doc, nid)
        yield api.Hit(min(w.line for w in calls),
                      f"`{who}` makes {len(calls)} external calls from one pool",
                      f"Can one slow callee of `{who}` hold up the others?",
                      anchor=("node", nid), fix="declare `@inv bulkhead(n)` on the caller")


def check_rules(api):
    return [
        api.Rule("RSL105", "unbroken-dependency", "hint",
                 ask="Does the caller stop calling a callee that keeps failing?",
                 why="Retries against a failing callee multiply its load.",
                 fix="declare `@inv breaker(…)` on the caller, or give it a state machine",
                 match=lambda doc: _unbroken(api, doc),
                 satisfiers=(("caller", "breaker"), ("caller", "state machine"))),
        api.Rule("RSL164", "shared-pool", "hint",
                 ask="Can one slow callee hold up the caller's other calls?",
                 why="Calls sharing one pool wait on the slowest.",
                 fix="declare `@inv bulkhead(n)` on the caller",
                 match=lambda doc: _shared_pool(api, doc),
                 satisfiers=(("caller", "bulkhead"),)),
    ]
