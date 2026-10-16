"""
mermaid — a Sigil document as a Mermaid flowchart (TD): the `--mermaid` export.

Usage:
    sigil export FILE --mermaid [--depth N|all] [--composition MODE] [--dialect NAME]
    sigil export FILE --mermaid --spine [--dialect NAME]

Options:
    --depth N          Draw `X := { … }` expansions (and `state` machines) as
                       subgraphs up to N levels deep (default: 1). --depth 0 draws
                       no expansion subgraphs; --depth all draws every level.
    --composition MODE How composition trees (`\\-<rel>` branches) are drawn:
                       `subgraphs` (default — nested subgraphs, one node per
                       occurrence), `edges` (one node per name, dotted relation
                       edges) or `none`. A dialect may change the default.
    --spine            Group the chart by the export's systems: a subgraph per
                       expansion and composition tree, nested as the export
                       nests them (sigil/publish/spine.py). --depth and
                       --composition do not apply.
    --dialect NAME     Load a dialect (name or path to a dialect.py) that extends
                       the glyph syntax / strips. Default: env SIGIL_DIALECT; unset
                       = core Sigil. See sigil/core/dialects.py.

Output:
    Mermaid `flowchart TD` source on stdout, ready to paste into any
    Mermaid-compatible renderer (GitHub, Obsidian, Notion, mermaid.live).

Visual language (NODE_SHAPE):
    [X]  component → rectangle,  blue
    {X}  data      → hexagon,    purple
    <X>  event     → asymmetric, orange
    (X)  actor     → circle,     green
    |X|  store     → cylinder,   yellow
    a state of a `state {X} { … }` machine → stadium, teal
    an alias `name := …` (a bare-word definition) → subroutine, grey

    [?]  hole      → dashed border (every hole is its own node)
    ~X   mutable   → thick border, label prefixed `~`
    *X   stream    → label prefixed `*`

Arrows (ARROW_MAP):
    ->  / →   solid           -->
    ~>        dotted          -.->
    <->       double          <-->
    =>        thick           ==>
    !>        labelled "!"    -- "!" -->
    ?>        dotted "?"      -. "?" .->
    *>        fan-out         one --> per target
    branch arm                dotted, labelled with the arm, from the `branch on X`
                              glyph to the arm's first node
    `-> run()`                a self-edge labelled with the op it runs

The document is read by sigil.core.parse (parse_document → Graph, the records
in sigil.core.graph); this module only writes it out.
"""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import PurePath
from typing import Optional

from sigil.core.graph import (Edge, Graph, Node, depth_arg, matching_occurrences, occurrences,
                              walk_depth)
from sigil.core.dialects import _hook
from sigil.core.parse import parse_document

ARROW_MAP = {
    "<->": "<-->",
    "->":  "-->",
    "~>":  "-.->",
    "=>":  "==>",
    "!>":  '-- "!" -->',
    "?>":  '-. "?" .->',
    "*>":  "-->",  # broadcast — rendered by fanning out to each target
    "→":   "-->",
}


NODE_SHAPE = {
    "service":   ("[", "]"),         # rectangle
    "data":      ("{{", "}}"),       # hexagon
    "event":     (">", "]"),         # asymmetric (flag)
    "actor":     ("((", "))"),       # circle
    "store":     ("[(", ")]"),       # cylinder
    "state":     ("([", "])"),       # stadium — a state of a `state {X}` machine
    "alias":     ("[[", "]]"),       # subroutine — a bare-word `name := …` definition
}


_CORE_CLASSDEFS = [
    "classDef service fill:#E3F2FD,stroke:#1976D2,color:#0D47A1",
    "classDef data    fill:#F3E5F5,stroke:#7B1FA2,color:#4A148C",
    "classDef event   fill:#FFF3E0,stroke:#F57C00,color:#E65100",
    "classDef actor   fill:#E8F5E9,stroke:#388E3C,color:#1B5E20",
    "classDef store   fill:#FFF9C4,stroke:#F9A825,color:#F57F17",
    "classDef state   fill:#E0F2F1,stroke:#00897B,color:#004D40",
]


# Emitted only when a document has alias nodes (keeps every other footer as it was).
_ALIAS_CLASSDEF = "classDef alias   fill:#ECEFF1,stroke:#546E7A,color:#263238"


_STYLE_CLASSDEFS = [
    "classDef hole    stroke-dasharray:5 5,opacity:0.7",
    "classDef mutable stroke-width:3px",
]


def _node_kinds(dialect=None) -> dict:
    return _hook(dialect, "NODE_KINDS", {}) or {}


def class_defs(dialect=None) -> str:
    """The chart's classDef footer: the core kinds, a dialect's, the styles."""
    extra = [f"classDef {k['mermaid_class']} {k['classdef']}"
             for k in _node_kinds(dialect).values()
             if k.get("mermaid_class") and k.get("classdef")]
    return "\n".join("    " + ln for ln in _CORE_CLASSDEFS + extra + _STYLE_CLASSDEFS)


def _kind_classes(dialect=None) -> dict:
    """Node kind → Mermaid class: the core kinds, then each dialect kind's
    `mermaid_class` (default: the kind's own name)."""
    kinds = {k: k for k in NODE_SHAPE}
    for kind, spec in _node_kinds(dialect).items():
        kinds[kind] = spec.get("mermaid_class", kind)
    return kinds


def mermaid_text(text: str) -> str:
    """Text safe inside a Mermaid `"…"` label: `<` / `>` / `"` as HTML entities."""
    return text.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def node_label(n: Node, dialect=None) -> str:
    """The plain-text label of a node: its name, or what the dialect's NODE_KINDS
    `label` callable makes of it (e.g. appending metadata from `n.attrs`)."""
    spec = _node_kinds(dialect).get(n.kind) or {}
    fn = spec.get("label")
    if fn:
        return fn(n)
    return {"start": "●", "end": "◉", "any": "∗ any"}.get(n.attrs.get("pseudo"), n.name)


def emit_node(n: Node, indent: str = "    ", dialect=None) -> str:
    spec = _node_kinds(dialect).get(n.kind)
    if spec is not None:
        open_shape, close_shape = spec["mermaid_shape"]
    else:
        open_shape, close_shape = NODE_SHAPE[n.kind]
    label = mermaid_text(node_label(n, dialect))
    if n.is_stream:
        label = f"*{label}"
    if n.is_mutable:
        label = f"~{label}"
    return f'{indent}{n.id}{open_shape}"{label}"{close_shape}'


def emit_edge(e: Edge, indent: str = "    ", dialect=None) -> str:
    arrow = ARROW_MAP.get(e.kind) or _hook(dialect, "RENDER_ARROWS", {}).get(e.kind, "-->")
    label = e.label or getattr(e, "target_op", None)    # `[W] -> run()`: the op it runs
    if label:
        arrow = _labelled(arrow, mermaid_text(label))
    return f"{indent}{e.src} {arrow} {e.dst}"


def _labelled(arrow: str, label: str) -> str:
    """A Mermaid arrow carrying `label`: joined to the label an arrow already has
    (`-- "!" -->`), written into a `-->` (`-- "x" -->`), else in pipes (`-.->|"x"|`)."""
    m = re.fullmatch(r'(\S+) "([^"]*)" (\S+)', arrow)
    if m:
        return f'{m.group(1)} "{m.group(2)} {label}" {m.group(3)}'
    if "-->" in arrow:
        return arrow.replace("-->", f'-- "{label}" -->', 1)
    return f'{arrow}|"{label}"|'


def emit_classes(graph: Graph, indent: str = "    ", dialect=None) -> list:
    lines = []
    for kind, cls in _kind_classes(dialect).items():
        ids = [n.id for n in graph.nodes.values() if n.kind == kind]
        if ids:
            lines.append(f"{indent}class {','.join(ids)} {cls}")
    holes = [n.id for n in graph.nodes.values() if n.is_hole]
    if holes:
        lines.append(f"{indent}class {','.join(holes)} hole")
    mutables = [n.id for n in graph.nodes.values() if n.is_mutable]
    if mutables:
        lines.append(f"{indent}class {','.join(mutables)} mutable")
    return lines


REL_WORD = {">": "contains", "&": "has", "?": "when", "$": "from data", "@": "attached",
            "!": "alerts", "=": "gathers", "_": "one of"}


def rel_word(t) -> str:
    """A tree entry's relation as words: `spawns`, `has`, `(3) contains`, …"""
    word = REL_WORD.get(t.rel or ">", t.rel or "contains")
    if t.spawn:
        word = "spawns" if word == "contains" else f"spawns, {word}"
    if t.weight is not None:
        word = f"({t.weight}) {word}"
    if t.cond:
        word = f"{{{t.cond}}} {word}"
    return word


def arm_wires(graph: Graph) -> list:
    """(decision node, arm entry node, arm label) per `branch on X { label => … }`
    arm: the branch's choice drawn from its subject glyph to each arm's first
    node. A branch with no glyph in its header draws no wires."""
    out = []
    for b in graph.blocks:
        if b.kind != "branch" or not b.refs:
            continue
        for label, nodes in b.arm_nodes:
            if nodes and nodes[0] != b.refs[0]:
                out.append((b.refs[0], nodes[0], label))
    return out


def emit_graph(graph: Graph, depth: int = 1, indent: str = "    ", depth_so_far: int = 0,
               dialect=None, composition: str = "none") -> str:
    if composition == "subgraphs" and graph.tree:
        return _emit_composed(graph, depth, indent, depth_so_far, dialect)
    body = _emit_flat(graph, depth, indent, depth_so_far, dialect, composition)
    if composition == "edges":
        extra = []
        for t in graph.tree:
            if t.parent is not None:
                extra.append(f'{indent}{graph.tree[t.parent].node} -. "{rel_word(t)}" .-> {t.node}')
        body += ("\n" + "\n".join(dict.fromkeys(extra))) if extra else ""
    return body


def _emit_composed(graph: Graph, depth: int, indent: str, depth_so_far: int, dialect) -> str:
    """Composition as subgraphs: one Mermaid node per occurrence; flows fan out to
    every occurrence of a bare name, or to the path-matching ones."""
    occ = occurrences(graph)
    kids = {}
    for i, t in enumerate(graph.tree):
        kids.setdefault(t.parent, []).append(i)
    in_tree = {t.node for t in graph.tree}
    lines, class_of = [], {}
    shown_internals = set()

    def node_line(oid, n, ind):
        return emit_node(n, ind, dialect).replace(f"{ind}{n.id}", f"{ind}{oid}", 1)

    def emit_occ(i, ind):
        oid, _chain = occ[i]
        n = graph.nodes[graph.tree[i].node]
        expand = (n.id in graph.expansions and depth_so_far < depth
                  and n.id not in shown_internals)
        if kids.get(i) or expand:
            lines.append(f'{ind}subgraph {oid}["{mermaid_text(node_label(n, dialect))}"]')
            lines.append(f"{ind}    direction TB")
            if expand:
                shown_internals.add(n.id)
                lines.append(f'{ind}    subgraph {oid}__internals["internals"]')
                lines.append(emit_graph(graph.expansions[n.id], depth, ind + "        ",
                                        depth_so_far + 1, dialect, "subgraphs"))
                lines.append(f"{ind}    end")
            for c in kids.get(i, []):
                emit_occ(c, ind + "    ")
            lines.append(f"{ind}end")
        else:
            lines.append(node_line(oid, n, ind))
        class_of[oid] = n

    # Nodes outside every tree, then the trees (roots in document order).
    rest = Graph(nodes={k: v for k, v in graph.nodes.items() if k not in in_tree},
                 expansions={k: v for k, v in graph.expansions.items() if k not in in_tree})
    flat = _emit_flat(rest, depth, indent, depth_so_far, dialect, "subgraphs",
                      with_edges=False, with_classes=False)
    if flat:
        lines.append(flat)
    for i in kids.get(None, []):
        emit_occ(i, indent)

    def ends(nid, path):
        return matching_occurrences(graph, occ, nid, path) if nid in in_tree else [nid]

    for e in graph.edges:
        for s in ends(e.src, e.src_path):
            for d in ends(e.dst, e.dst_path):
                lines.append(emit_edge(Edge(src=s, dst=d, kind=e.kind, label=e.label,
                                            target_op=e.target_op), indent, dialect))
    for src, dst, label in arm_wires(graph):
        for s in ends(src, None):
            for d in ends(dst, None):
                lines.append(f'{indent}{s} -. "{mermaid_text(label)}" .-> {d}')
    # Classes: nodes outside the trees as usual, occurrences by their node's kind.
    lines += emit_classes(rest, indent, dialect)
    by_cls = {}
    kinds = _kind_classes(dialect)
    for oid, n in class_of.items():
        by_cls.setdefault(kinds.get(n.kind, n.kind), []).append(oid)
        if n.is_hole:
            by_cls.setdefault("hole", []).append(oid)
        if n.is_mutable:
            by_cls.setdefault("mutable", []).append(oid)
    for cls, ids in by_cls.items():
        lines.append(f"{indent}class {','.join(ids)} {cls}")
    return "\n".join(lines)


def _emit_flat(graph: Graph, depth: int = 1, indent: str = "    ", depth_so_far: int = 0,
               dialect=None, composition: str = "none", with_edges: bool = True,
               with_classes: bool = True) -> str:
    """Emit Mermaid for a graph, recursively expanding up to `depth` levels.

    When a node has an expansion being rendered, it's emitted as a subgraph
    instead of a flat node — edges automatically route to the subgraph boundary.
    """
    lines = []
    expanded_ids = set()

    # First pass: figure out which nodes are being expanded
    for node in graph.nodes.values():
        if depth_so_far < depth and node.id in graph.expansions:
            expanded_ids.add(node.id)

    # Emit nodes — flat ones first, subgraphs after
    for node in graph.nodes.values():
        if node.id in expanded_ids:
            continue  # will be emitted as subgraph below
        lines.append(emit_node(node, indent, dialect))

    # Emit subgraphs for expanded nodes
    for node in graph.nodes.values():
        if node.id not in expanded_ids:
            continue
        sub = graph.expansions[node.id]
        lines.append(f'{indent}subgraph {node.id}["{mermaid_text(node_label(node, dialect))}"]')
        lines.append(f"{indent}    direction TB")
        # Recurse into sub with incremented depth_so_far (only render() adds the
        # classDef footer, once).
        lines.append(emit_graph(sub, depth, indent + "    ", depth_so_far + 1, dialect,
                                composition))
        lines.append(f"{indent}end")

    # Emit edges at this level
    if with_edges:
        for edge in graph.edges:
            lines.append(emit_edge(edge, indent, dialect))
        for src, dst, label in arm_wires(graph):
            lines.append(f'{indent}{src} -. "{mermaid_text(label)}" .-> {dst}')

    # Emit classes at this level
    if with_classes:
        for cls_line in emit_classes(graph, indent, dialect):
            lines.append(cls_line)

    return "\n".join(lines)


def unique_ids(graph: Graph, depth: int = 1) -> Graph:
    """A copy of the graph whose node ids are unique across every graph Mermaid
    draws (the top level and the expansions up to `depth`): Mermaid ids are
    global, so `[Handler]` at the top level and `[Core]`'s `[Handler]` would be
    one node. The top level keeps its ids; a nested graph's id that a graph
    nearer the top already uses becomes `<owner id>__<id>` (the owner being the
    node the expansion hangs off, as emitted). Triggers follow their nodes."""
    claimed = set(graph.nodes)
    renamed = {}                                # id(graph) → {old id: new id}
    queue = [(graph, None, 0)]
    order = []
    while queue:                                # breadth first: the shallower claims first
        g, owner_mid, level = queue.pop(0)
        order.append(g)
        names = renamed.setdefault(id(g), {})
        if g is not graph:
            for nid in g.nodes:
                new = nid
                if nid in claimed:
                    new, k = f"{owner_mid}__{nid}", 2
                    while new in claimed:
                        new, k = f"{owner_mid}__{nid}_{k}", k + 1
                    names[nid] = new
                claimed.add(new)
        if level < depth:
            for nid, sub in g.expansions.items():
                queue.append((sub, names.get(nid, nid), level + 1))
    if not any(renamed.values()):
        return graph

    copies = {}                                 # id(graph) → its copy
    for g, _o, _l in reversed(list(walk_depth(graph))):   # nested graphs before their owners
        m = renamed.get(id(g), {})

        def r(nid, m=m):
            return m.get(nid, nid)

        copies[id(g)] = replace(
            g,
            nodes={r(k): replace(n, id=r(n.id)) for k, n in g.nodes.items()},
            edges=[replace(e, src=r(e.src), dst=r(e.dst)) for e in g.edges],
            expansions={r(k): copies[id(sub)] for k, sub in g.expansions.items()},
            tree=[replace(t, node=r(t.node)) for t in g.tree],
            blocks=[replace(b, refs=[r(x) for x in b.refs],
                            members=[r(x) for x in b.members],
                            arm_nodes=[(lab, [r(x) for x in ids]) for lab, ids in b.arm_nodes])
                    for b in g.blocks],
        )
    out = copies[id(graph)]
    trig = []
    for t in graph.triggers:
        owner, src, dst, event = t.owner, t.src, t.dst, t.event
        for g, _o, _l in walk_depth(graph):
            sub = g.expansions.get(t.owner)
            if sub is not None and t.dst in sub.nodes:
                owner = renamed.get(id(g), {}).get(t.owner, t.owner)
                src = renamed.get(id(sub), {}).get(t.src, t.src)
                dst = renamed.get(id(sub), {}).get(t.dst, t.dst)
                break
        for g in order:
            if t.event in g.nodes:
                event = renamed.get(id(g), {}).get(t.event, t.event)
                break
        trig.append(replace(t, owner=owner, src=src, dst=dst, event=event))
    out.triggers = trig
    return out


def render(text: str, depth: int = 1, dialect=None, composition: Optional[str] = None) -> str:
    """Mermaid for a document. `composition`: "subgraphs" (default — composition
    trees as nested subgraphs, one node per occurrence), "edges" (one node per name,
    dotted relation edges), or "none"; a dialect may change the default
    (MERMAID_COMPOSITION)."""
    if composition is None:
        composition = _hook(dialect, "MERMAID_COMPOSITION", "subgraphs")
    graph = unique_ids(parse_document(text, dialect=dialect), depth)
    body = emit_graph(graph, depth=depth, dialect=dialect, composition=composition)
    in_tree = {t.node for t in graph.tree} if composition == "subgraphs" else set()
    occ = occurrences(graph) if in_tree else []
    wires = []
    for t in graph.triggers:
        # Into the state the transition enters when its machine is drawn, else
        # into the machine's owner (its first occurrence when it sits in a tree);
        # from every drawn occurrence of the event, as flows are.
        dst = t.dst if t.level <= depth else t.owner
        if dst in in_tree:
            dst = matching_occurrences(graph, occ, dst, None)[0]
        srcs = (matching_occurrences(graph, occ, t.event, None) if t.event in in_tree
                else [t.event])
        wires += [f'\n    {src} -. "triggers" .-> {dst}' for src in srcs]
    body += "".join(wires)
    classes = class_defs(dialect)
    if any(n.kind == "alias" for g, _o, _l in walk_depth(graph) for n in g.nodes.values()):
        classes += "\n    " + _ALIAS_CLASSDEF
    return f"flowchart TD\n{body}\n\n{classes}"


def main(argv=None, default_dialect=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="render.py",
                                 description="Render a Sigil document as Mermaid.")
    ap.add_argument("file", help="a .sigil file, or - for stdin")
    ap.add_argument("--depth", type=depth_arg, default=1,
                    help="expansion depth (N or 'all')")
    ap.add_argument("--composition", choices=("subgraphs", "edges", "none"), default=None,
                    help="composition trees as nested subgraphs (default), dotted "
                         "relation edges, or not at all")
    ap.add_argument("--spine", action="store_true",
                    help="group the chart by the export's systems (a subgraph per system)")
    ap.add_argument("--dialect", default=default_dialect,
                    help="dialect name or path (default: $SIGIL_DIALECT)")
    a = ap.parse_args(argv)
    from sigil.core import dialects
    try:
        dialect = dialects.load(a.dialect)
    except ValueError as exc:
        print(f"render.py: {exc}", file=sys.stderr)
        return 2

    try:
        if a.file == "-":
            text = sys.stdin.read()
        else:
            with open(a.file, "r", encoding="utf-8") as f:
                text = f.read()
    except OSError as exc:
        print(f"render.py: cannot read {a.file}: {exc.strerror or exc}", file=sys.stderr)
        return 2

    if a.spine:
        from sigil.publish.spine import spine
        print(spine(text, stem_of(a.file), dialect=dialect))
    else:
        print(render(text, depth=a.depth, dialect=dialect, composition=a.composition))
    return 0


def stem_of(path: str) -> str:
    """The top system's name for a file (as `sigil export` names it); stdin's
    is `document`."""
    return "document" if path == "-" else PurePath(path).stem
