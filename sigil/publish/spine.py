"""
spine — a Sigil document as a Mermaid flowchart grouped by its export systems:
`sigil export FILE --mermaid --spine`.

The chart is the document's top system; every other system (an expansion, a
composition tree) is a subgraph inside the system it is nested in, labelled
with its key, holding the components homed there. A system's face (the
expansion's owner, the tree's root) is drawn where it is written, as the export
reads it. Flows are drawn between components as `--mermaid` draws them. Holes,
aliases and states are no components and are left out; `--depth` does not
apply (every system is drawn) and composition trees are drawn as their systems.

The systems are sigil.model.systems' (what `sigil export` writes); no readiness
gate runs, so a sketch or a craft document draws too.
"""

from __future__ import annotations

from dataclasses import replace

from sigil.core.graph import Graph
from sigil.core.parse import parse_document
from sigil.model import systems
from sigil.publish import mermaid
from sigil.publish.systems import slugs

INDENT = "    "
SUBGRAPH_PREFIX = "system__"


def spine(text: str, stem: str, dialect=None) -> str:
    """The Mermaid chart of a document grouped by its export systems; `stem`
    names the top system (as `sigil export` names it after the file)."""
    graph = parse_document(text, dialect=dialect)
    model = systems.model_of(graph, stem)
    return chart(graph, model, dialect)


def chart(graph: Graph, model: systems.Model, dialect=None) -> str:
    """The chart of a parsed document and its export model."""
    nodes = drawn_nodes(graph)
    ids = subgraph_ids(model, frozenset(nodes))
    body = system_lines(model.top, model, ids, nodes, INDENT, dialect)
    body += flow_lines(graph, nodes, dialect)
    body += mermaid.emit_classes(Graph(nodes=nodes), INDENT, dialect)
    return "flowchart TD\n" + "\n".join(body) + f"\n\n{mermaid.class_defs(dialect)}"


def drawn_nodes(graph: Graph) -> dict:
    """{node id: Node} of every component, mutable or stream when any of its
    occurrences is (as its export glyph reads)."""
    out = {}
    for nid, insts in systems.component_nodes(graph).items():
        out[nid] = replace(insts[0], is_mutable=any(n.is_mutable for n in insts),
                           is_stream=any(n.is_stream for n in insts))
    return out


def subgraph_ids(model: systems.Model, taken: frozenset) -> dict:
    """{system key: Mermaid subgraph id} for every system but the top, clear of
    the node ids in `taken` and of each other."""
    keys = [k for k in model.systems if k != model.top]
    out = {}
    used = set(taken)
    for key, slug in slugs(keys).items():
        base = sid = SUBGRAPH_PREFIX + slug.replace("-", "_")
        n = 1
        while sid in used:
            n += 1
            sid = f"{base}_{n}"
        used.add(sid)
        out[key] = sid
    return out


def system_lines(key: str, model: systems.Model, ids: dict, nodes: dict, indent: str,
                 dialect) -> list:
    """The lines of system `key`: its members' nodes, then each system nested
    in it as a subgraph (the top system's lines are the chart's own)."""
    lines = [mermaid.emit_node(nodes[m], indent, dialect)
             for m in model.systems[key].members if m in nodes]
    for child in (k for k, s in model.systems.items() if s.parent == key and k != key):
        lines.append(f'{indent}subgraph {ids[child]}["{mermaid.mermaid_text(child)}"]')
        lines.append(f"{indent}{INDENT}direction TB")
        lines += system_lines(child, model, ids, nodes, indent + INDENT, dialect)
        lines.append(f"{indent}end")
    return lines


def flow_lines(graph: Graph, nodes: dict, dialect) -> list:
    """Every flow between two components, in every graph of the document, each
    drawn once."""
    lines = (mermaid.emit_edge(e, INDENT, dialect)
             for g in systems.walk(graph) for e in g.edges
             if e.src in nodes and e.dst in nodes)
    return list(dict.fromkeys(lines))
