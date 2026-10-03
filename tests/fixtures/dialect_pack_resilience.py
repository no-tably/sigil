"""An example dialect rule pack (RFC 0003 catalog §11): two rules the core dropped
because they ask for a component shape, kept here to prove the rule-pack hook.

    unbroken-dependency  a call with @timeout and retries whose caller declares no
                         `@inv breaker(…)` (was SGC105).
    shared-pool          a node making two or more calls, one of them retrying or
                         without @timeout, that declares no `@inv bulkhead(…)`
                         (was SGC164).

Both are craft-only hints: they ask nothing in sketch or spec. Ids use the pack's
own prefix, RSL. Standard library only; loaded with dialects.load(<this path>).
"""

NAME = "pack-resilience"
INV_HEADS = {"breaker", "bulkhead"}
READ_VERBS = {"peek"}
LINT_CODES = set()


def _declares(node, head: str) -> bool:
    """The node carries `@inv head(…)` (or a bare `@inv head`)."""
    return any(name == "inv" and (arg or "").split("(")[0].strip() == head
               for name, arg in node.mods)


def _calls(graph):
    """The edges that draw a call: a payload or an op-call target."""
    return [e for e in graph.edges if e.payload or e.target_op]


def _retries(edge) -> bool:
    return any(name == "×" for name, _arg in edge.mods)


def _timed(edge) -> bool:
    return any(name in ("timeout", "deadline") for name, _arg in edge.mods)


def _unbroken(api, doc):
    if doc.mode != "craft":
        return
    for graph, _owner, _level in doc.graphs:
        for e in _calls(graph):
            src = graph.nodes.get(e.src)
            if src is None or not (_timed(e) and _retries(e)) or _declares(src, "breaker"):
                continue
            yield api.Hit(e.line, f"`{src.name}` retries this call with no breaker",
                          f"Does `{src.name}` stop calling when the callee keeps failing?",
                          anchor=("node", src.id), fix="declare `@inv breaker(…)` on the caller")


def _shared_pool(api, doc):
    if doc.mode != "craft":
        return
    for graph, _owner, _level in doc.graphs:
        by_src = {}
        for e in _calls(graph):
            by_src.setdefault(e.src, []).append(e)
        for nid, calls in sorted(by_src.items()):
            src = graph.nodes.get(nid)
            risky = [e for e in calls if _retries(e) or not _timed(e)]
            if src is None or len(calls) < 2 or not risky or _declares(src, "bulkhead"):
                continue
            yield api.Hit(min(e.line for e in calls),
                          f"`{src.name}` makes {len(calls)} calls from one pool",
                          f"Can one slow callee of `{src.name}` hold up the others?",
                          anchor=("node", nid), fix="declare `@inv bulkhead(n)` on the caller")


def check_rules(api):
    return [
        api.Rule("RSL105", "unbroken-dependency", "hint",
                 ask="Does the caller stop calling a callee that keeps failing?",
                 why="Retries against a failing callee multiply its load.",
                 fix="declare `@inv breaker(…)` on the caller",
                 match=lambda doc: _unbroken(api, doc),
                 satisfiers=(("caller", "breaker"),)),
        api.Rule("RSL164", "shared-pool", "hint",
                 ask="Can one slow callee hold up the caller's other calls?",
                 why="Calls sharing one pool wait on the slowest.",
                 fix="declare `@inv bulkhead(n)` on the caller",
                 match=lambda doc: _shared_pool(api, doc),
                 satisfiers=(("caller", "bulkhead"),)),
    ]
