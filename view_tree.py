"""
view_tree.py — the tree view of view.py: the composition tree as an outline,
every flow as a lane in a gutter beside it.

Not a command: view.py loads it. Outline rows (`\\-` branches and `:=`
expansions), lanes packed into the gutter, block brackets, join taps, the right
margin (payloads, modifiers, inline notes), margin callouts and the tree legend.
compose_tree() returns the rows view.py prints. What is wired to what, in which
colour, with which payload, notes and join marks — and where an event is drawn —
comes from the Scene (scene.py); this module only lays it out. Drawing
primitives and styles come from viewkit.py (read as kit.NAME, so a theme change
reaches them).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple


_HERE = Path(__file__).resolve().parent


def _sibling(name: str, fname: str):
    """The module fname beside this file, loaded by path once per directory and then
    shared: the view modules of one directory read the one viewkit, so a theme
    applied through any of them (apply_theme rebinds viewkit's style globals)
    reaches them all, while a view.py loaded from another directory (a packaged
    copy) gets modules, theme and dialect state of its own. The cache key names
    the directory, never the bare name. view.py, view_graph.py, view_tree.py and
    scene.py each carry a copy of this function: keep the copies identical."""
    key = f"{name}@{_HERE}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, _HERE / fname)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod   # dataclasses resolve string annotations via sys.modules
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[key]
            raise
    return sys.modules[key]


kit = _sibling("sigil_viewkit", "viewkit.py")
scene = _sibling("sigil_scene", "scene.py")


# ---------------------------------------------------------------------------
# Tree + wires — the composition tree as an outline, every flow as a lane
# ---------------------------------------------------------------------------

LANE_GAP = 2


class TreeRow(NamedTuple):
    depth: int
    rel: str                                    # relation text before the label
    node: object
    graph: object                               # the graph the node is drawn from
    collapsed: bool                             # an expansion not shown (▸)


class Banner(NamedTuple):
    """A row that is not a node: a `--- section ---` divider, or a control
    block's header (`┌─ ↺ loop @while |Q|.nonempty`)."""
    kind: str                                   # "section" | "block"
    runs: list


def _tree_rows(g, depth: int, level: int = 0, base: int = 0, rows=None):
    """Flatten a graph (and its expansions, to `depth`) into outline TreeRows."""
    rows = [] if rows is None else rows
    tree = getattr(g, "tree", [])
    kids = {}
    for i, t in enumerate(tree):
        kids.setdefault(t.parent, []).append(i)
    placed = {t.node for t in tree if t.parent is not None}

    def rel_text(t):
        if t.parent is None:
            return ""
        r = {None: "─", ">": "─"}.get(t.rel, t.rel)
        if t.spawn:
            r = "*" if r in ("─", "*") else "*" + r
        pre = f"{{{t.cond}}}" if t.cond else ""
        if getattr(t, "weight", None) is not None:
            pre = f"({t.weight})"
        return pre + r

    def emit_node(nid, d, rel):
        rows.append(TreeRow(d, rel, g.nodes[nid], g, nid in g.expansions and level >= depth))
        if nid in g.expansions and level < depth:
            sub = g.expansions[nid]
            mark = "·" if getattr(sub, "role", "") == "state" else "─"
            before = len(rows)
            _tree_rows(sub, depth, level + 1, d + 1, rows)
            for k in range(before, len(rows)):     # direct members hang off with :=
                if rows[k].depth == d + 1 and not rows[k].rel:
                    rows[k] = rows[k]._replace(rel=mark)

    def emit_entry(i):
        t = tree[i]
        emit_node(t.node, base + t.depth, rel_text(t))
        for c in kids.get(i, []):
            emit_entry(c)

    roots_done = set()
    for nid in g.nodes:
        root_entries = [i for i, t in enumerate(tree) if t.parent is None and t.node == nid]
        if root_entries:
            for i in root_entries:
                if i not in roots_done:
                    roots_done.add(i)
                    emit_entry(i)
        elif nid not in placed:
            emit_node(nid, base, "")
    return rows


def tree_legend(triggers: bool = True, payloads: bool = False, access: bool = False,
                mods: bool = False, events: str = "land"):
    """Legend rows for the tree + wires view: relations, then lanes by arrow type,
    then the structure marks (blocks, joins, sections). Each arrow's sample is in
    its own colour (scene.arrow_colour); markers whose lanes take their source's
    colour are drawn neutral. `events`: the `›` emits entry shows only in "land"
    mode — in "nodes" mode an event is a row with lanes in and out. Raises
    ValueError for an unknown events mode."""
    if events not in scene.EVENTS:
        raise ValueError(f"events must be one of {', '.join(scene.EVENTS)}, not {events!r}")
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    rel = [("tree   ", dim), ("─", kit.TREE_STYLE), (" contains  ", mid)]
    for glyph, word in (("&", "has"), ("*", "spawns"), ("?", "when"), ("$", "from data"),
                        ("@", "attached"), ("!", "alerts"), ("=", "gathers"),
                        ("_", "one of"), ("(N)", "weight")):
        rel += [(glyph, kit.REL_STYLE), (f" {word}  ", mid)]
    wires = [("wires  ", dim)]
    for kind, word in kit.ARROW_LEGEND + ((("trigger", "trigger"),) if triggers else ()):
        own = scene.arrow_colour(kind)
        colour = scene.colour_of(own) if own else kit.EDGE_DEFAULT
        sample = ("◀─▶" if kind == "<->"
                  else kit.SOURCE_MARK.get(kind, "●") + kit._stroke_sample(kind))
        wires += [(sample, (colour, None, False)), (f" {word}  ", mid)]
    if events == "land":
        wires += [(EMIT_MARK + "─", (kit.kind_color("event"), None, False)), (" emits  ", mid)]
    wires += [("◀", (kit.GREY["light"], None, True)), (" target  ", mid),
              ("─│─", dim), (" crossing  ", mid),
              ("■", (kit.EDGE_DEFAULT, None, False)), (" lane: its source's colour  ", mid)]
    if access:
        acc = (kit.EDGE_COLOR["access"], None, False)
        wires += [("r┄", acc), (" reads  ", mid), ("w┄", acc), (" writes  ", mid),
                  ("b┄", acc), (" borrows  ", mid),
                  ("1w", (kit.EDGE_COLOR["access"], None, True)), (" writers  ", mid)]
    if payloads:
        wires += [("┄┆{…}┆", dim), (" payload, on its target row", mid)]
    if mods:
        wires += [("┆@… ×N┆", (kit.SYNTAX["modifier"][0], None, False)), (" modifiers", mid)]
    marks = [("blocks ", dim), ("┌─ ↺", kit.FRAME_STYLE), (" loop  ", mid), ("∥", kit.FRAME_STYLE),
             (" parallel  ", mid), ("◇", kit.FRAME_STYLE), (" branch ", mid),
             ("‹arm›", (kit.EDGE_COLOR["arm"], None, True)), ("  ", mid), ("□", kit.FRAME_STYLE),
             (" scope / owns  ", mid), ("◀&", kit.LABEL_STYLE), (" joined: all  ", mid),
             ("◀&?", kit.LABEL_STYLE), (" race  ", mid), ("◀/", kit.LABEL_STYLE), (" one of  ", mid),
             ("── ──", kit.SECTION_STYLE), (" section", mid)]
    return [rel, wires, marks]


def compose_tree(g, depth: int, triggers: bool = True, spaced: bool = True,
                 notes: str = "off", payloads: bool = False, width: int | None = None,
                 access: bool = False, mods: bool = False, events: str = "land"):
    """The drawing as outline rows with a lane gutter; same return shape as compose().
    `triggers`: draw event → state lanes. `events`: "land" draws a pass-through
    event where it lands — no row of its own, its emitters wired straight to its
    destinations (a `›` source), its label on each destination's row; "nodes"
    keeps it as a row with lanes in and out (see scene.land_events). `spaced`: a
    blank row between top-level units (a root with parts, or the first root after
    one). `notes`: "markers" tags
    commented rows `#N` and lists the notes below; "callouts" draws them as boxes in
    a left margin, each tied to its row by a leader. `payloads`: draw each flow's
    payload as a chip in a right margin, on its target row (the mirror of the
    callouts); any that can't be placed are listed below.

    `width`: the columns to fit (None: the natural width). When the drawing is
    wider, the margins give way — the outline and lanes never change shape: the
    callout boxes narrow (down to CALLOUT_MIN); then the right margin moves to a
    panel at the bottom-right (each row keeps a `┆a┆` marker, the panel repeats
    it beside the payload / comment); then the callouts move to a panel at the
    top-left (each entity keeps its `#N` tag, the panel's box is headed `#N`).
    A callout that would be cut off widens (up to CALLOUT_MAX) when there is room.

    `--- sections ---` divide the outline (a rule before each section's first
    unit); control blocks are brackets in a gutter left of it, from a header row
    (`┌─ ↺ loop @while |Q|.nonempty`) to their members' rows, a branch arm's label
    beside its entry (`‹read›`); a joined flow's taps carry its join (`◀&`).
    `access`: the permission graph as dotted lanes from each principal (marked r
    / w / b) into its store, a store badged `1w` / `Nw` writers. `mods`:
    modifiers after a node's label, and after the payload in a flow's chip."""
    scn = scene.build_scene(g, events=events, triggers=triggers, access=access, depth=depth)
    rows = [r for r in _tree_rows(g, depth)
            if not (r.depth == 0 and r.node.id in scn.collapsed)]
    if not rows:
        return [], 0
    idx = scn.notes if notes != "off" else {}
    wires = _lane_wires(scn)
    if spaced:
        rows = _space_units(rows)
    rows, brackets = _tree_banners(rows, g)
    xs, x0 = _bracket_cols(brackets)
    after_label = _tree_extras(scn, mods)
    joins = scene.join_marks(scn)
    # Block notes are about a component: tagged on its row, called out on the
    # left. Inline notes are about their line: they trail it on the right, after
    # the payload the line carries — as in the source.
    blocks = {nid: [e for e in es if e[2] == "block"] for nid, es in idx.items()}
    blocks = {nid: es for nid, es in blocks.items() if es}
    payload_of = scene.chip_texts(scn, payloads, mods) if (payloads or mods) else {}
    trailing = scene.wire_notes(scn) if notes != "off" else {}
    bases = {}

    def base(left: bool, right: bool):
        """The outline, lanes and right margin; `left`: callouts relocated (so
        rows carry #N tags), `right`: the right margin relocated."""
        if (left, right) not in bases:
            cv = kit.Canvas()
            out = _draw_outline(cv, rows, blocks, show_tags=notes != "callouts" or left,
                                x0=x0, extra=after_label)
            _draw_brackets(cv, brackets, xs, x0)
            lanes = _pack_lanes(_collect_lanes(cv, wires, out), max(out.ends) + 3)
            _draw_lanes(cv, lanes, out.ends)
            _draw_join_taps(cv, lanes, out.ends, joins)
            moved = [] if right else None
            drawn = _draw_right_margin(cv, lanes, out, payload_of, trailing, notes, moved)
            for y, row in enumerate(rows):      # section rules run the full width
                if isinstance(row, Banner) and row.kind == "section" and out.ends[y] < cv.w:
                    cv.put(out.ends[y], y, "─" * (cv.w - out.ends[y]), kit.SECTION_STYLE)
            bases[(left, right)] = (list(cv.rows()), cv.w, out, drawn, moved or [])
        return bases[(left, right)]

    def assemble(left: bool, right: bool, tw: int):
        out_rows, w, out, _drawn, _moved = base(left, right)
        if notes == "callouts" and out.tagged and not left:
            out_rows, w = _with_callouts(out_rows, blocks, out.tagged, tw)
        return out_rows, w

    callouts = notes == "callouts" and bool(blocks)
    need = kit._callout_need(blocks) if callouts else kit.CALLOUT_TEXT
    choice = (False, False, kit.CALLOUT_TEXT)
    if width is not None:
        out_rows, w = assemble(*choice)
        extra = _extras(g, idx, notes, payloads, base(False, False)[3])
        fits = max([w] + [kit.row_len(r) for r in extra]) <= width
        if fits and need > kit.CALLOUT_TEXT and assemble(False, False, need)[1] <= width:
            choice = (False, False, need)           # room to show every callout whole
        elif not fits:
            shrink = range(need, kit.CALLOUT_MIN - 1, -1) if callouts else (kit.CALLOUT_TEXT,)
            # Each margin arrangement, its callouts as wide as fit; an arrangement
            # whose narrowest callouts don't fit is skipped whole.
            tries = [[(False, False, tw) for tw in shrink], [(False, True, tw) for tw in shrink]]
            if callouts:
                tries += [[(True, False, need)], [(True, True, need)]]
            tries = [t for group in tries if assemble(*group[-1])[1] <= width for t in group]
            choice = next((t for t in tries if assemble(*t)[1] <= width),
                          (callouts, True, need))
    left, right, tw = choice
    out_rows, w = assemble(left, right, tw)
    _r, _w, out, drawn, moved = base(left, right)
    # (A list that already fits rewraps to the same lines at the narrower width.)
    extra = _extras(g, idx, notes, payloads, drawn,
                    kit.NOTE_WIDTH if width is None else min(kit.NOTE_WIDTH, width))
    if width is not None and right and moved:
        items = [(kit._chip_marker(letter), ([(" · ".join(chips), "code")] if chips else [])
                  + [(f"# {text}", "inline") for _num, text in notes_])
                 for letter, chips, notes_ in moved]
        out_rows = kit._fit_panel(out_rows, lambda t: kit._panel_rows(items, t), width, "br",
                              kit.CALLOUT_MAX)
    if width is not None and left and out.tagged:
        entries = [(num, text, kind) for nid, _y in sorted(out.tagged.items(), key=lambda kv: kv[1])
                   for num, text, kind, _e in blocks[nid]]
        out_rows = kit._fit_panel(out_rows, lambda t: kit._callout_panel(entries, t), width, "tl", need)
    if (left, right) != (False, False):
        w = max([0] + [kit.row_len(r) for r in out_rows])
    out_rows = list(out_rows) + extra
    return out_rows, max([w] + [kit.row_len(r) for r in extra])


class _Bracket(NamedTuple):
    """A control block in the tree view: its header row and member rows."""
    header: int
    members: list


def _tree_banners(rows, g):
    """rows with banners inserted: a section divider before the first top-level
    unit of each `--- section ---`, and each control block's header — before the
    first member row the block introduces (else after its last member row).
    Returns (rows, brackets)."""
    first = {}
    for i, r in enumerate(rows):
        if isinstance(r, TreeRow):
            first.setdefault((id(r.graph), r.node.id), i)
    pending = []                                # (at, order, Banner, members)
    secs = getattr(g, "sections", None) or []
    if secs:
        est, cur = kit.node_lines(g), -1
        for i, r in enumerate(rows):
            if isinstance(r, TreeRow) and r.graph is g and r.depth == 0:
                k = kit.section_of(secs, est.get(r.node.id, 0))
                if k > cur:
                    cur = k
                    pending.append((i, (1, 0), Banner("section", kit.section_rule(
                        kit.section_name(secs[k]))), None))
    seen_graphs = {id(r.graph): r.graph for r in rows if isinstance(r, TreeRow)}
    for G in seen_graphs.values():
        blocks = getattr(G, "blocks", None) or []
        est = kit.node_lines(G, notes=False) if blocks else {}
        for b in blocks:
            members = [m for m in dict.fromkeys(b.members) if (id(G), m) in first]
            if not members:
                continue
            ys = [first[(id(G), m)] for m in members]
            intro = [first[(id(G), m)] for m in members if est.get(m, 0) >= b.lines[0]]
            at, prio = (min(intro), 2) if intro else (max(ys) + 1, 0)
            span = b.lines[1] - b.lines[0]
            pending.append((at, (prio, -span), Banner("block", kit.block_title_runs(b)), ys))
    if not pending:
        return rows, []
    pending.sort(key=lambda p: (p[0], p[1]))
    out, new_at, brackets, k = [], {}, [], 0
    for i in range(len(rows) + 1):
        while k < len(pending) and pending[k][0] == i:
            _at, _o, banner, ys = pending[k]
            if ys is not None:
                brackets.append((len(out), ys))
            out.append(banner)
            k += 1
        if i < len(rows):
            new_at[i] = len(out)
            out.append(rows[i])
    return out, [_Bracket(h, [new_at[y] for y in ys]) for h, ys in brackets]


BRACKET_GAP = 2                                 # columns between block brackets


def _bracket_cols(brackets) -> tuple:
    """Each bracket's gutter column (interval-packed, the longest outermost) and
    the gutter's width (where the outline starts: 0 without brackets)."""
    cols, at = [], {}
    order = sorted(range(len(brackets)), key=lambda k: -(max(brackets[k].members + [brackets[k].header])
                                                          - min(brackets[k].members + [brackets[k].header])))
    for k in order:
        ys = brackets[k].members + [brackets[k].header]
        at[k] = kit._first_fit(cols, min(ys), max(ys))
    return [at[k] * BRACKET_GAP for k in range(len(brackets))], (
        len(cols) * BRACKET_GAP + 1 if cols else 0)


def _draw_brackets(cv: kit.Canvas, brackets, xs, x0: int):
    """Each block as a bracket in the gutter left of the outline: a vertical from
    its first to its last row, a ─ tap into its header and each member row
    (hopping ─│─ the brackets it crosses)."""
    verticals = set()
    for b, x in zip(brackets, xs):
        ys = b.members + [b.header]
        if max(ys) > min(ys):
            cv.path([(x, min(ys)), (x, max(ys))], "->", kit.FRAME_STYLE)
            verticals |= {(x, y) for y in range(min(ys), max(ys) + 1)}
    for b, x in zip(brackets, xs):
        for y in sorted(set(b.members + [b.header])):
            cv.run(x, x0 - 2, y, "->", kit.FRAME_STYLE,
                   hops=lambda xx, _y=y, _x=x: (xx, _y) in verticals and xx != _x)


def _space_units(rows):
    """A None (blank row) before each top-level unit: a root with parts, or the
    first root after one."""
    out = []
    for k, r in enumerate(rows):
        unit = k + 1 < len(rows) and rows[k + 1].depth > r.depth
        if k and r.depth == 0 and (unit or rows[k - 1].depth > 0):
            out.append(None)
        out.append(r)
    return out


def _guides(rows):
    """Each row's ├─ / └─ / │ prefix ("" at depth 0, None for a blank row). A rail
    continues at a level while a later sibling at that level follows, before the
    outline climbs above it — found in one backward pass."""
    guides = [None] * len(rows)
    later = []              # later[k]: rows below reach depth k before anything shallower
    for y in range(len(rows) - 1, -1, -1):
        if not isinstance(rows[y], TreeRow):    # a blank row or a banner
            continue
        d = rows[y].depth
        if d:
            def cont(k):
                return k < len(later) and later[k]
            guides[y] = ("".join("│  " if cont(k) else "   " for k in range(1, d))
                         + ("├─" if cont(d) else "└─"))
        else:
            guides[y] = ""
        del later[d + 1:]
        later += [False] * (d + 1 - len(later))
        later[d] = True
    return guides


@dataclass
class _Outline:
    ends: list                                  # per row: x just past its text (0 if blank)
    by_id: dict                                 # node id → the rows it is drawn on
    chain_at: dict                              # y → names root → this row
    tagged: dict                                # node id → row carrying its #N


def _draw_outline(cv: kit.Canvas, rows, idx: dict, show_tags: bool = True, x0: int = 0,
                  extra: dict | None = None) -> _Outline:
    """The outline from column x0: rails, relation, label, #N tag, the extra runs
    a node carries (modifiers, a writer badge, a branch arm's label) and (for a
    state) the triggers that lead into it, one row each. A banner row (a section
    divider, a block's header) is drawn as its runs; a block header inside a
    unit sits at its next row's label column, the rails it interrupts bridged."""
    out = _Outline([], {}, {}, {})
    stack = []
    guides = _guides(rows)
    extra, extra_done, bridges = extra or {}, set(), []
    for y, (row, guide) in enumerate(zip(rows, guides)):
        if row is None:
            out.ends.append(0)
            continue
        if isinstance(row, Banner):
            x = x0
            if row.kind == "block":
                nxt = next((guides[j] for j in range(y + 1, len(rows))
                            if isinstance(rows[j], TreeRow)), "")
                x = x0 + (len(nxt) + 2 if nxt else 0)
                bridges.append((y, x))
            out.ends.append(kit._put_runs(cv, x, y, row.runs))
            continue
        n, rel = row.node, row.rel
        stack = stack[:row.depth] + [n.name]
        out.chain_at[y] = tuple(stack)
        x = x0
        if row.depth:
            cv.put(x0, y, guide, kit.TREE_STYLE)
            x = x0 + len(guide)
            if rel and rel != "─":
                cv.put(x, y, rel, kit.REL_STYLE)
                x += len(rel)
            else:
                cv.put(x, y, "─", kit.TREE_STYLE)
                x += 1
            x += 1
        label = kit.node_label(n) + (" ▸" if row.collapsed else "")
        _border, text = kit.node_styles(n)
        kit._put_runs(cv, x, y, kit.label_runs(n) + ([(" ▸", (text[0], None, True))]
                                             if row.collapsed else []))
        x += len(label)
        if n.id in idx and n.id not in out.tagged and not show_tags:
            out.tagged[n.id] = y                # callouts point here with `#>` instead
        if n.id in idx and n.id not in out.tagged:  # `#N` on the node's first row
            tag = " " + kit.note_tag(idx[n.id])
            tx = x
            for run, style in kit.note_tag_runs(idx[n.id]):
                cv.put(tx, y, run, style)
                tx += len(run)
            x += len(tag)
            out.tagged[n.id] = y
        if n.id in extra and n.id not in extra_done:    # on the node's first row
            extra_done.add(n.id)
            x = kit._put_runs(cv, x, y, extra[n.id])
        if n.kind == "state":                   # the triggers that lead into this state
            into = sorted({e.label for e in row.graph.edges if e.dst == n.id and e.label})
            if into:
                cv.put(x + 1, y, " ".join(into), kit.LABEL_STYLE)
                x += 1 + len(" ".join(into))
        out.ends.append(x)
        out.by_id.setdefault(n.id, []).append(y)

    def rail(y, step):
        while 0 <= y < len(rows) and isinstance(rows[y], Banner):
            y += step
        return y if 0 <= y < len(rows) and isinstance(rows[y], TreeRow) else None

    for y, text_x in bridges:                   # rails run on through a block header
        above, below = rail(y - 1, -1), rail(y + 1, 1)
        if above is None or below is None:
            continue
        for x in range(x0, text_x):
            if (cv.cell(x, above)[0] in "│├" and cv.cell(x, below)[0] in "│├└"):
                cv.put(x, y, "│", kit.TREE_STYLE)
    return out


LANE_ROLES = ("flow", "trigger", "emit", "access")     # the wires drawn as lanes


def _lane_wires(scn) -> list:
    """The Scene's wires the gutter draws, one per stroke — flows, triggers, emits
    (the first of a key: one stroke per emitter → destination), permissions —
    keyed by (key, qualified ends); an emit wire takes the place of a flow it
    coincides with (the event is what that stroke carries)."""
    out, emitted = {}, set()
    for w in scn.wires:
        if w.role not in LANE_ROLES or (w.role == "emit" and w.key in emitted):
            continue
        if w.role == "emit":
            emitted.add(w.key)
            out[(w.key, w.paths)] = w
        else:
            out.setdefault((w.key, w.paths), w)
    return list(out.values())


class _Lane(NamedTuple):
    """A wire in the gutter: the rows it spans and the rows of each end; x and
    style once packed (_pack_lanes)."""
    lo: int
    hi: int
    wire: object                                # scene.Wire
    sy: list                                    # its source's rows
    dy: list                                    # its target's rows
    x: int = 0
    style: tuple = None


def _collect_lanes(cv: kit.Canvas, wires, out: _Outline) -> list:
    """One _Lane per wire, over every row where either end occurs, shortest
    first; a self-loop is marked ↺ on its row instead."""
    def at(nid, path):
        ys = out.by_id.get(nid, [])
        if path:
            ys = [y for y in ys if out.chain_at[y][-len(path):] == tuple(path)]
        return ys

    lanes = []
    for w in wires:
        (spath, dpath) = w.paths
        sy, dy = at(w.src, spath), at(w.dst, dpath)
        if not sy or not dy:
            continue
        if w.src == w.dst and not spath and not dpath:
            for y in sy:
                cv.put(out.ends[y] + 1, y, "↺", kit.edge_style(w.kind))
            continue
        ys = sorted(set(sy) | set(dy))
        lanes.append(_Lane(ys[0], ys[-1], w, sy, dy))
    lanes.sort(key=lambda lane: (lane.hi - lane.lo, lane.lo))
    return lanes


def _pack_lanes(lanes, left: int) -> list:
    """Each lane with its gutter column (interval-packed from `left`) and its
    stroke style (its wire's colour, scene.wire_style)."""
    cols = []
    return [lane._replace(x=left + kit._first_fit(cols, lane.lo, lane.hi) * LANE_GAP,
                          style=scene.wire_style(lane.wire))
            for lane in lanes]


EMIT_MARK = "›"          # the source of a lane that carries an emitted event


def _source_mark(w) -> str:
    """The mark at a lane's source tap: `›` for an emitted event (a failure
    emission keeps its ✖), else the arrow's own source mark."""
    if w.role == "emit" and w.kind != "!>":
        return EMIT_MARK
    return kit.SOURCE_MARK.get(w.kind, "●")


def _draw_lanes(cv: kit.Canvas, lanes, ends):
    """Verticals first; then each row's runs out to the lanes it taps, hopping
    (─│─) over lanes it merely crosses, so a joint (┤ ┴ ┬ ┼) only ever appears
    where a lane is actually tapped."""
    verticals = set()
    for ln in lanes:
        if ln.hi > ln.lo:
            cv.path([(ln.x, ln.lo), (ln.x, ln.hi)], ln.wire.kind, ln.style)
            verticals |= {(ln.x, y) for y in range(ln.lo, ln.hi + 1)}

    taps = {}                                   # y → [(lane x, kind, style, role, mark)]
    for ln in lanes:
        mark = _source_mark(ln.wire)
        for y in ln.sy:
            taps.setdefault(y, []).append((ln.x, ln.wire.kind, ln.style, "src", mark))
        for y in ln.dy:
            taps.setdefault(y, []).append((ln.x, ln.wire.kind, ln.style, "dst", mark))

    heads = []
    for y, row_taps in taps.items():
        joined = {x for x, *_ in row_taps}

        def hops(x, _y=y, _joined=joined):
            return (x, _y) in verticals and x not in _joined

        order = sorted(row_taps, key=lambda t: -t[0])
        # Runs into the ◀ first. From the ◀ out to the nearest incoming lane the
        # cells keep the incoming stroke, so a row that is also a source still
        # shows what arrives; a source run sharing them only joins them.
        into = set()
        # nearest first: the lane whose stroke reaches the ◀ owns the cells it
        # shares with farther incoming lanes, so the colours follow the lines
        for x1, kind, style, role, _mark in sorted(order, key=lambda t: t[0]):
            if role == "dst":
                into |= cv.run(ends[y] + 2, x1, y, kind, style, hops)
        nearest = min((t[0] for t in row_taps if t[3] == "dst"), default=-1)
        into = {cell for cell in into if cell[0] <= nearest}
        for x1, kind, style, role, _mark in order:
            if role == "src":
                x0 = ends[y] + (2 if kind == "<->" else 1)
                cv.run(x0, x1, y, kind, style, hops, fixed=into)
        for x1, kind, style, role, mark in order:
            both = kind == "<->" and role == "src"
            if role == "src":
                heads.append((x1, y, mark, style))
            # one ◀ per row, in the colour of the lane whose stroke runs into it
            if (role == "dst" and x1 == nearest) or (both and nearest < 0):
                heads.append((ends[y] + 1, y, "◀", style))
    for x, y, ch, st in heads:
        cv.put(x, y, ch, st)


def _mods_texts(g) -> dict:
    """{node id: its modifiers' text}: the first graph (g, then its expansions)
    that gives the node any — a node written bare in one graph may carry them
    in another."""
    out = {}
    for cur in kit._walk(g):
        for nid, n in cur.nodes.items():
            text = kit.mods_text(n.mods)
            if text:
                out.setdefault(nid, text)
    return out


def _tree_extras(scn, mods: bool) -> dict:
    """{node id: runs} drawn after a node's label in the tree: the events that land
    on it, its modifiers (mods), its writer badge (the access option), the branch
    arms it is the entry of (‹read›)."""
    texts = _mods_texts(scn.graph) if mods else {}
    extra = {}
    for nid, sn in scn.nodes.items():
        runs = [run for ev in sn.landed
                for run in [(" ", None)] + kit.glyph_runs(kit.node_label(ev), "event")]
        text = texts.get(nid)
        if text:
            runs += [(" ", None)] + kit.mod_runs(text)
        runs += [(" " + badge, (kit.EDGE_COLOR["access"], None, True)) for badge in sn.badges]
        runs += [(f" ‹{label}›", (kit.EDGE_COLOR["arm"], None, True)) for label in sn.arms]
        if runs:
            extra[nid] = runs
    return extra


def _draw_join_taps(cv: kit.Canvas, lanes, ends, joins: dict):
    """A joined flow's label on its taps, beside the row's label: `◀&` where a
    fork's branch arrives, `─&` where a fan-in's source leaves. joins: {key:
    {"src" | "dst": join}} (scene.join_marks)."""
    for ln in lanes:
        mark = joins.get(ln.wire.key)
        if not mark:
            continue
        for side, ys in (("dst", ln.dy), ("src", ln.sy)):
            if side in mark:
                for y in ys:
                    cv.put(ends[y] + 2, y, mark[side], kit.LABEL_STYLE)


def _draw_right_margin(cv: kit.Canvas, lanes, out: _Outline, payload_of: dict,
                       trailing: dict, notes: str, moved: list | None = None) -> set:
    """The right margin, the mirror of the note callouts: on each flow's target row
    the payload it carries (a ┆chip┆) and the inline comment from its line; on a
    node's row the inline comment of the line that placed it. A dotted leader ties
    each to the row's rightmost tap, hopping (┄│┄) over lanes it crosses. Comments
    show as `#N` (markers) or their text (callouts). Returns the flow keys whose
    payloads were drawn. With `moved` (a list), a row's payloads and comment text
    are relocated instead: the row ends in a `┆a┆` marker and moved gets
    (letter, payloads, [(number, text)]); `#N` markers stay on the row."""
    margin = max([ln.x for ln in lanes] + [max(out.ends) - 1]) + 3
    rightmost, chips, notes_at, drawn = {}, {}, {}, set()
    for ln in lanes:
        for y in list(ln.sy) + list(ln.dy):
            rightmost[y] = max(rightmost.get(y, 0), ln.x)
        key = ln.wire.key
        text = payload_of.get(key)
        for y in ln.dy:
            if text and text not in chips.setdefault(y, []):
                chips[y].append(text)
            for note in trailing.get(key, ()):
                if note not in notes_at.setdefault(y, []):
                    notes_at[y].append(note)
        if text:
            drawn.add(key)
    for key, notes_ in trailing.items():         # lines that only placed a node
        if isinstance(key, str) and key in out.by_id:
            y = out.by_id[key][0]
            notes_at.setdefault(y, []).extend(n for n in notes_ if n not in notes_at[y])
    leader, border = (kit.GREY["dim"], None, False), (kit.GREY["dim"], None, False)
    for y in sorted(set(chips) | set(notes_at)):
        if not chips.get(y) and not notes_at.get(y):
            continue
        first = rightmost.get(y, out.ends[y]) + 1
        for x in range(first, margin - 1):
            if (x, y) not in cv.lines and (x, y) not in cv.text:
                cv.put(x, y, "┄", leader)
        x = margin - 1
        if moved is not None:
            row_notes = sorted(notes_at.get(y, ()))
            go = [] if notes == "markers" else row_notes
            if chips.get(y) or go:                # the same content shares a letter
                item = (chips.get(y, []), go)
                letter = next((m[0] for m in moved if m[1:] == item), None)
                if letter is None:
                    letter = kit._letter(len(moved))
                    moved.append((letter, *item))
                x = kit._put_runs(cv, x, y, kit._chip_marker(letter)) + 1
            if notes == "markers":
                for num, _text in row_notes:
                    cv.put(x, y, f"#{num}", kit.NOTE_STYLE["inline"])
                    x += len(f"#{num}") + 2
            continue
        if chips.get(y):
            body = " · ".join(chips[y])
            cv.put(x, y, "┆ ", border)
            x = kit._put_runs(cv, x + 2, y, kit.payload_runs(body))
            cv.put(x, y, " ┆", border)
            x += 3
        for num, text in sorted(notes_at.get(y, ())):
            note = f"#{num}" if notes == "markers" else f"# {text}"
            cv.put(x, y, note, kit.NOTE_STYLE["inline"])
            x += len(note) + 2
    return drawn


def _extras(g, idx: dict, notes: str, payloads: bool, drawn: frozenset = frozenset(),
            note_width: int = kit.NOTE_WIDTH):
    """The lists under the tree: payloads not drawn as chips (when shown), then
    notes (markers mode, wrapped at note_width)."""
    extra = []
    pl = [f"  {kit.edge_text(sub, e)} : {e.payload}" for sub in kit._walk(g) for e in sub.edges
          if e.payload and (e.src, e.dst, e.kind) not in drawn] if payloads else []
    if pl:
        extra += [[], kit.section_rule("payloads"), []] + [[(p, kit.PAYLOAD_STYLE)] for p in pl]
    if notes == "markers" and idx:
        extra += [[], kit.section_rule("notes"), []] + kit.note_rows(idx, note_width)
    return extra


def _with_callouts(rows, idx: dict, tagged: dict, tw: int = kit.CALLOUT_TEXT):
    """Prefix the tree rows with a left margin of note boxes, their text tw wide. A
    box sits level with its row when there is room, else slides down; its leader
    runs right, up to the row, and into it. Leaders get their own columns
    (interval-packed)."""
    boxes = []                                  # (row, top, lines, kind)
    free = 0
    anchors = set(tagged.values())
    for nid, y in sorted(tagged.items(), key=lambda kv: kv[1]):
        for num, text, kind, _edges in idx[nid]:
            # A block note is a framed box (3 lines at CALLOUT_TEXT); an inline
            # note stays bare (2), like the trailing comment it came from. No
            # number: the leader itself points at the entity (`#>`).
            lines = kit._callout_lines(text, kind, tw)
            top = max(y, free)
            while top != y and top in anchors:  # a slid box never starts on another
                top += 1                        # note's row: its runs would merge
            boxes.append((y, top, lines, kind))
            free = top + len(lines) + (1 if kind == "block" else 0)
    cols = []                                   # leader columns: list of (lo, hi)
    leader_col = [None if top == y else kit._first_fit(cols, y, top) for y, top, _l, _n in boxes]
    box_w = tw + 4
    margin = box_w + 2 + 2 * len(cols) + 2
    mc = kit.Canvas()
    for (y, top, lines, kind), c in zip(boxes, leader_col):
        k = len(lines)
        style = border = kit.NOTE_STYLE[kind]       # colour tells the kinds apart
        for j, ln in enumerate(lines):
            if kind == "inline":                # bare, like a trailing comment
                lside, rside = "  ", "  "
            elif k == 1:
                lside, rside = "│ ", " │"
            else:
                lside, rside = {0: ("╭ ", " ╮"), k - 1: ("╰ ", " ╯")}.get(j, ("│ ", " │"))
            mc.put(0, top + j, lside, border)
            mc.put(2, top + j, ln.ljust(tw), style)
            mc.put(box_w - 2, top + j, rside, border)
    # Leaders: verticals first, then horizontal runs that hop (─│─) over any other
    # leader's vertical, so two leaders never read as joined.
    start, end = box_w + 1, margin - 2          # a gap before the tree: not a guide
    runs, verticals = [], set()
    for (y, top, _lines, kind), c in zip(boxes, leader_col):
        stroke = "?>" if kind == "inline" else "->"     # inline: a dotted leader
        if c is None:
            runs.append((start, end, y, None, stroke, kit.NOTE_STYLE[kind]))
            continue
        cx = box_w + 2 + 2 * c
        mc.path([(cx, top), (cx, y)], stroke, kit.NOTE_STYLE[kind])
        verticals |= {(cx, yy) for yy in range(min(y, top), max(y, top) + 1)}
        runs += [(start, cx, top, cx, stroke, kit.NOTE_STYLE[kind]),
                 (cx, end, y, cx, stroke, kit.NOTE_STYLE[kind])]
    # Leaders that end on the same row (a node with a block and an inline note)
    # join there (┬ ┴) instead of hopping over each other.
    ends_at = {(box_w + 2 + 2 * c, y) for (y, _t, _l, _k), c in zip(boxes, leader_col)
               if c is not None}
    for x0, x1, yy, own, stroke, colour in runs:
        mc.run(x0, x1, yy, stroke, colour,
               hops=lambda x, _y=yy, _own=own: ((x, _y) in verticals and x != _own
                                               and (x, _y) not in ends_at))
    for y, _top, _lines, kind in boxes:         # each leader ends `#>` at its entity
        mc.put(end - 1, y, "#>", kit.NOTE_STYLE[kind])
    margin_rows = list(mc.rows())
    height = max(len(rows), len(margin_rows))
    out = []
    for y in range(height):
        left = margin_rows[y] if y < len(margin_rows) else []
        pad = margin - kit.row_len(left)
        tree = rows[y] if y < len(rows) else []
        out.append(left + ([(" " * pad, None)] if tree and pad > 0 else []) + tree)
    return out, margin + max((kit.row_len(r) for r in rows), default=0)
