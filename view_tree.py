"""
view_tree.py — the tree view of view.py: the composition tree as an outline,
every flow as a lane in a gutter beside it.

Not a command: view.py loads it. Outline rows (`\\-` branches and `:=`
expansions) with their call marks (`↺` / `↻` / `⇱`), lanes packed into the
gutter, block brackets, join taps, the right margin (a chip per call or payload,
modifiers, inline notes), margin callouts and the tree legend — and, given a
sim.py trace, one frame of it over the tree (lit lanes, tokens in the gutter,
row statuses, the current machine states). compose_tree() returns the rows
view.py prints. What is wired to what, in which
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
    the directory, never the bare name. view.py, view_graph.py, view_tree.py,
    view_flow.py, view_run.py and scene.py each carry a copy of this function: keep
    the copies identical."""
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
INTERNAL_MARK = "┄"      # an expansion's member: its branch and rail drawn dotted (┆ ├┄)
ONE_OF_BRACE = ("⎫", "⎪", "⎭")  # top / middle / bottom of the brace joining `_` siblings


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
    key: Optional[str] = None                   # a block's note key (kit.block_note_key)


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
        r = scene.rel_mark(t)
        pre = f"{{{t.cond}}}" if t.cond else ""
        if getattr(t, "weight", None) is not None:
            pre = f"({t.weight})"
        return pre + r

    def emit_node(nid, d, rel):
        rows.append(TreeRow(d, rel, g.nodes[nid], g, nid in g.expansions and level >= depth))
        if nid in g.expansions and level < depth:
            sub = g.expansions[nid]
            mark = "·" if getattr(sub, "role", "") == "state" else INTERNAL_MARK
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
                mods: bool = False, events: str = "land", calls: frozenset = frozenset(),
                sim: bool = False):
    """Legend rows for the tree + wires view: relations, then lanes by arrow type,
    then the structure marks (blocks, joins, sections). Each arrow's sample is in
    its own colour (scene.arrow_colour); markers whose lanes take their source's
    colour are drawn neutral. `events`: the `›` emits entry shows only in "land"
    mode — in "nodes" mode an event is a row with lanes in and out. `calls`: the
    call marks the drawing shows (view.drawn_call_marks) — an entry is listed for
    each of `↺` self-call, `↻` recursion, `⇱` host-provided and `↩` a call's
    return only when its mark is in the set; so are `≋` a stream, `‹›` a
    generic role (drawn `[R‹N›]`) and, with access, `ƀ` a borrow narrowed to read;
    so are the outline's `┄ := internals` and the one-of brace `_⎫`
    (outline_marks). `sim`: a last row of the simulation overlay's marks
    (_sim_legend). Raises ValueError for an unknown
    events mode."""
    if events not in scene.EVENTS:
        raise ValueError(f"events must be one of {', '.join(scene.EVENTS)}, not {events!r}")
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    rel = [("tree   ", dim), ("─", kit.TREE_STYLE), (" contains  ", mid)]
    if INTERNAL_MARK in calls:
        rel += [(INTERNAL_MARK, kit.TREE_STYLE), (" := internals  ", mid)]
    brace = ONE_OF_BRACE[0] if ONE_OF_BRACE[0] in calls else ""
    for glyph, word in (("&", "has"), ("*", "spawns"), ("?", "when"), ("$", "from data"),
                        ("@", "attached"), ("!", "alerts"), ("=", "gathers"),
                        ("_" + brace, "one of"), ("(N)", "weight")):
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
                  ("b┄", acc), (" borrows  ", mid)]
        if "ƀ" in calls:
            wires += [("ƀ┄", acc), (" borrows read  ", mid)]
        wires += [("1w", (kit.EDGE_COLOR["access"], None, True)), (" writers  ", mid)]
    call = (kit.EDGE_DEFAULT, None, False)
    for mark, word, style in (("↺", "self-call", call), ("↻", "recursion", call),
                              (EXTERNAL_MARK, "host-provided (opaque)", call),
                              ("↩", "returns", kit.PAYLOAD_STYLE)):
        if mark in calls:
            wires += [(mark, style), (f" {word}  ", mid)]
    for mark, sample, word in ((kit.STREAM_MARK, kit.STREAM_MARK, "stream"),
                               ("‹›", "[R‹N›]", "role: N members")):
        if mark in calls:
            wires += [(sample, (kit.GREY["light"], None, False)), (f" {word}  ", mid)]
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
    return [rel, wires, marks] + ([_sim_legend()] if sim else [])


def _sim_legend() -> list:
    """The tree view's legend row of the simulation overlay's marks, in the words
    and styles of the graph view's (view.sim_legend) wherever the two draw
    alike; the tree's own: `▸` an active row."""
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    wire = (kit.EDGE_DEFAULT, None, True)
    trail = (kit.faded(kit.EDGE_DEFAULT, kit.SIM_TRAIL, "trail"), None, False)
    faint = (kit.faded(kit.EDGE_DEFAULT, kit.SIM_FAINT, "faint"), None, False)
    fail = (scene.colour_of("edges-fail"), None, True)
    light = (kit.GREY["light"], None, False)
    state = (kit.kind_color("state"), None, True)
    return [("run    ", dim),
            ("●", wire), (" out  ", mid), ("○", wire), (" return / fallback  ", mid),
            ("✕", fail), (" failed  ", mid), (CANCELLED_MARK, faint), (" cancelled  ", mid),
            ("─", wire), (" now  ", mid), ("─", trail), (" taken  ", mid),
            ("─", faint), (" untouched  ", mid),
            ("▸", (kit.GREY["light"], None, True)), (" active  ", mid),
            ("…", light), (" waiting  ", mid), ("✕", fail), (" failed  ", mid),
            ("×n", light), (" instances  ", mid), ("↻k", light), (" recursion  ", mid),
            ("◉", state), (" current state  ", mid), ("◉ State", state),
            (" its owner's, machine not drawn", mid)]


def compose_tree(g, depth: int, triggers: bool = True, spaced: bool = True,
                 notes: str = "off", payloads: bool = False, width: int | None = None,
                 access: bool = False, mods: bool = False, events: str = "land",
                 trace=None, tick: int = 0, checks=None, probe: bool = False, memo=None):
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
    callouts) — one chip per call, never merged, each in its wire's stroke; a
    self-call's chip on its subject's row (`↺ plan({Seed}) ↩ {Plan}`); any that
    can't be placed are listed below. Whatever the options, a row whose node
    calls itself carries the call's mark after its label (`↺` a self-call, `↻`
    recursion, `⇱` a host op), and the far node of an external op call `⇱`.

    `width`: the columns to fit (None: the natural width). When the drawing is
    wider, the margins give way first — the outline never changes shape: the
    callout boxes narrow (down to CALLOUT_MIN); then the right margin moves to a
    panel at the bottom-right (each row keeps a `┆a┆` marker, the panel repeats
    it beside the payload / comment); then the callouts move to a panel at the
    top-left (each entity keeps its `#N` tag, the panel's box is headed `#N`).
    A callout that would be cut off widens (up to CALLOUT_MAX) when there is room.
    Then the lanes past the gutter columns that fit fold into numbered plugs
    (_fold_lanes: `●①` on a source row, `◀───①` on a target row); a row still
    too wide leaves a hint under the drawing (kit.wide_hint).

    `--- sections ---` divide the outline (a rule before each section's first
    unit); control blocks are brackets in a gutter left of it, from a header row
    (`┌─ ↺ loop @while |Q|.nonempty`) to their members' rows, a branch arm's label
    beside its entry (`‹read›`); a joined flow's taps carry its join (`◀&`).
    `access`: the permission graph as dotted lanes from each principal (marked r
    / w / b) into its store, a store badged `1w` / `Nw` writers. `mods`:
    modifiers after a node's label, and after the payload in a flow's chip.

    `trace`, `tick`: a simulation (sim.py) drawn over the tree at frame `tick`
    (the layout holds still for the whole trace — every row gets a status slot
    before its label, every node room for its widest badge). The trace must be
    named as this drawing's Scene: sim.project(trace, scene.build_scene(g,
    events=events, triggers=triggers, access=access, depth=depth)). See
    the overlay section for what a frame paints. Raises IndexError for a
    tick past the trace's end.

    `checks` (kit.CheckMarks, named as that same Scene names things): the
    checks overlay — a marked wire's lane in its worst finding's style
    (ui.error / ui.warn; an acknowledged one muted), each finding's number
    (`▲1`, `◆2`, `✓3`) after its node's label, a wire's on its target's row;
    None: no overlay. `probe`: the frame's tokens and active labels drawn in
    kit.Probe styles (sim_focus). `memo` (kit.FrameMemo, kept by a caller
    drawing a run frame after frame): the outline, its lanes and the wrap
    ladder's step worked out once while the frames lay out alike (_laid), each
    later one repainting only the rows that look different (the drawing is the
    same as without it).
    """
    plan = (memo.plan(("tree", depth, triggers, spaced, notes, payloads, width, access, mods,
                       events, probe), (g, trace, checks)) if memo is not None else None)
    setup = kit.held(plan, "setup", lambda: _tree_setup(g, depth, triggers, spaced, notes,
                                                        payloads, access, mods, events, checks))
    if setup is None:
        return [], 0
    rows, idx, blocks = setup.rows, setup.idx, setup.blocks
    frame = trace.frames[tick] if trace is not None else None
    chipped = payloads or mods
    look = _TreeLook(frame, probe, _call_marks(setup.scn, rows, setup.calls, frame),
                     _sim_rows(kit.held(plan, "stage", lambda: _sim_stage(setup.scn, rows, trace)),
                               rows, frame, probe) if trace is not None else None,
                     _self_call_chips(setup.calls, payloads, mods, frame) if chipped else {})
    laid = _laid(plan, look)
    bases = {}

    def base(left: bool, right: bool, keep: int | None = None):
        """The outline, lanes and right margin (_base): `left`: callouts
        relocated (so rows carry #N tags), `right`: the right margin relocated;
        `keep`: the gutter columns kept, the lanes past them folded (None: none
        folded). Each kept from frame to frame of a run (while its layout holds, _laid)."""
        if (left, right, keep) not in bases:
            kept = (laid.held.setdefault(("base", left, right, keep), {})
                    if laid is not None else None)
            bases[(left, right, keep)] = _base(setup, look, _Way(left, right, keep), kept)
        return bases[(left, right, keep)]

    def assemble(left: bool, right: bool, tw: int, keep: int | None = None):
        out_rows, w, out, _drawn, _moved, _lanes, _gutter = base(left, right, keep)
        if notes == "callouts" and out.tagged and not left:
            out_rows, w = _with_callouts(out_rows, blocks, out.tagged, tw)
        return out_rows, w

    callouts = notes == "callouts" and bool(blocks)
    need = kit._callout_need(blocks) if callouts else kit.CALLOUT_TEXT

    def choose():
        """(left, right, callout width), the gutter columns kept (None: no
        lane folded): the ladder's step, the first that fits `width`."""
        choice = (False, False, kit.CALLOUT_TEXT)
        if width is not None:
            out_rows, w = assemble(*choice)
            extra = _extras(g, idx, notes, payloads, base(False, False)[3], width=width)
            fits = max([w] + [kit.row_len(r) for r in extra]) <= width
            if fits and need > kit.CALLOUT_TEXT and assemble(False, False, need)[1] <= width:
                choice = (False, False, need)       # room to show every callout whole
            elif not fits:
                shrink = range(need, kit.CALLOUT_MIN - 1, -1) if callouts else (kit.CALLOUT_TEXT,)
                # Each margin arrangement, its callouts as wide as fit; an arrangement
                # whose narrowest callouts don't fit is skipped whole.
                tries = [[(False, False, tw) for tw in shrink],
                         [(False, True, tw) for tw in shrink]]
                if callouts:
                    tries += [[(True, False, need)], [(True, True, need)]]
                tries = [t for group in tries if assemble(*group[-1])[1] <= width for t in group]
                choice = next((t for t in tries if assemble(*t)[1] <= width),
                              (callouts, True, need))
        keep = None
        over = assemble(*choice)[1] if width is not None else 0
        if width is not None and over > width:
            # the margins have given way and the lanes still don't fit: fold the
            # lanes past the most gutter columns that then fit, else the fold that
            # is narrowest (folding none when that is)
            lanes, gutter = base(*choice[:2])[5:]
            reach = {k: _fold_reach(lanes, gutter, k) for k in range(_lane_cols(lanes, gutter))}
            keep = next((k for k in sorted(reach, reverse=True) if reach[k] <= width),
                        min(reach, key=lambda k: (reach[k], -k), default=None))
            if keep is not None and reach[keep] >= over:
                keep = None
        return choice, keep

    # The step is chosen again whenever a frame lays out unlike the last (_laid).
    choice, keep = kit.held(laid, "ladder", choose)
    left, right, tw = choice
    out_rows, w = assemble(left, right, tw, keep)
    _r, _w, out, drawn, moved, _lanes, _gutter = base(left, right, keep)
    # (A list that already fits rewraps to the same lines at the narrower width.)
    extra = _extras(g, idx, notes, payloads, drawn,
                    kit.NOTE_WIDTH if width is None else min(kit.NOTE_WIDTH, width), width)
    if width is not None and right and moved:
        items = [(kit._chip_marker(letter), [(text, "code") for text in chips]
                  + [(f"# {text}", "inline") for _num, text in notes_])
                 for letter, chips, notes_ in moved]
        out_rows = kit._fit_panel(out_rows, lambda t, most=None: kit._panel_rows(items, t, most), width, "br",
                              kit.CALLOUT_MAX)
    if width is not None and left and out.tagged:
        entries = [(num, text, kind) for nid, _y in sorted(out.tagged.items(), key=lambda kv: kv[1])
                   for num, text, kind, _e in blocks[nid]]
        out_rows = kit._fit_panel(out_rows, lambda t, _most=None: kit._callout_panel(entries, t), width, "tl", need)
    if (left, right) != (False, False):
        w = max([0] + [kit.row_len(r) for r in out_rows])
    if width is not None and w > width:         # nothing left to give way
        out_rows = list(out_rows) + [[]] + kit.wide_hint("tree", "a row", w, width, None)
    out_rows = list(out_rows) + extra
    return out_rows, max([w] + [kit.row_len(r) for r in extra])


class _TreeSetup(NamedTuple):
    """What a tree drawing holds whatever sim frame is over it (_tree_setup):
    worked out once per plan while a run plays."""
    scn: object
    rows: list                  # the outline's rows (TreeRow / Banner / None)
    idx: dict                   # the notes drawn ({} when notes are off)
    wires: list                 # _lane_wires
    homes: dict                 # unit owner → its graph
    brackets: list
    xs: dict
    x0: int
    after_label: dict           # node id → runs after its label (_tree_extras, checks)
    calls: dict                 # _self_call_rows
    joins: dict                 # scene.join_marks
    blocks: dict                # node id → its block notes
    chip_lists: dict
    trailing: dict              # scene.wire_notes (notes on)
    notes: str                  # the notes mode drawn
    checks: object              # the checks overlay's kit.CheckMarks (None: none)


def _tree_setup(g, depth: int, triggers: bool, spaced: bool, notes: str, payloads: bool,
                access: bool, mods: bool, events: str, checks) -> "_TreeSetup | None":
    """compose_tree's _TreeSetup of g; None when the outline has no rows."""
    scn = scene.build_scene(g, events=events, triggers=triggers, access=access, depth=depth)
    rows = [r for r in _tree_rows(g, depth)
            if not (r.depth == 0 and r.node.id in scn.collapsed)]
    if not rows:
        return None
    idx = scn.notes if notes != "off" else {}
    if spaced:
        rows = _space_units(rows)
    rows, brackets = _tree_banners(rows, g)
    xs, x0 = _bracket_cols(brackets)
    after_label = _tree_extras(scn, mods)
    if checks is not None:
        for nid, runs in check_extras(scn, checks).items():
            after_label[nid] = after_label.get(nid, []) + runs
    # Block notes are about a component: tagged on its row, called out on the
    # left. Inline notes are about their line: they trail it on the right, after
    # the payload the line carries — as in the source.
    blocks = {nid: [e for e in es if e[2] == "block"] for nid, es in idx.items()}
    blocks = {nid: es for nid, es in blocks.items() if es and nid != kit.DOC_NOTE}
    return _TreeSetup(scn, rows, idx, _lane_wires(scn), {u.owner: u.graph for u in scn.units},
                      brackets, xs, x0, after_label, _self_call_rows(scn, rows),
                      scene.join_marks(scn), blocks,
                      scene.chip_lists(scn, payloads, mods) if payloads or mods else {},
                      scene.wire_notes(scn) if notes != "off" else {}, notes, checks)


class _TreeLook(NamedTuple):
    """What one sim frame changes in a tree drawing (None: no frame)."""
    frame: object
    probe: bool
    marks: dict                 # _call_marks
    sim_rows: Optional[dict]    # _sim_rows
    self_chips: dict            # _self_call_chips


def _laid(plan, look: _TreeLook):
    """The plan (kit.Plan) of the layout drawn under `look` — the wrap ladder's
    step, the outline and lanes of each way tried — kept while a run's frames
    lay out alike: a fresh one when this frame's _extent differs from the last
    frame's (a mark, badge or chip of another width), so the ladder chooses
    again for it. None without a plan."""
    if plan is None:
        return None
    extent = _extent(look)
    kept = plan.held.get("laid")
    if kept is None or kept[0] != extent:
        kept = plan.held["laid"] = (extent, kit.Plan())
    return kept[1].begin()


def _extent(look: _TreeLook) -> tuple:
    """The columns a frame's own runs take on each row — its call marks, its
    badges (the status slot is one column whatever the status), its self-call
    chips: what of a frame the layout depends on."""
    def widths(rows: dict, cells) -> tuple:
        return tuple((y, cells(v)) for y, v in rows.items())
    return (widths(look.marks, kit.row_len),
            widths(look.sim_rows or {}, lambda r: kit.row_len(r.badges)),
            widths(look.self_chips, lambda chips: tuple(kit.cell_width(t) for _w, t, _s in chips)))


class _Way(NamedTuple):
    """How the outline, lanes and right margin are arranged (a step of the
    wrap ladder): `left`, the callouts relocated (rows carry their #N tags);
    `right`, the right margin relocated; `keep`, the gutter columns kept, the
    lanes past them folded (None: none folded)."""
    left: bool
    right: bool
    keep: Optional[int]


class _Again(NamedTuple):
    """A repaint of some rows of a tree drawing (_draw_base): the rows, and
    what it takes from the whole drawing — its lanes (styled for the frame),
    its outline (_Outline) and its width."""
    rows: frozenset
    lanes: list
    laid: "_Outline"
    width: int


def _base(setup: _TreeSetup, look: _TreeLook, way: _Way, kept: dict | None) -> tuple:
    """(rows, width, _Outline, drawn chip keys, moved, lanes, gutter): the
    outline, lanes and right margin drawn (_draw_base) as `way` arranges them.
    `kept` ({} the first time): the drawing kept from frame to frame of a
    run — its lanes packed once, and only the rows whose look changed drawn
    again (kit.Retained)."""
    if kept:
        lanes = _restyled(kept["lanes"], look.frame, setup.checks, kept["styles"])
        retained = kept["drawn"]
        cv = retained.repaint(
            _base_looks(setup, look, kept["out"], lanes),
            lambda rows: _draw_base(setup, look, way, _Again(rows, lanes, kept["out"],
                                                              retained.canvas.w))[0])
        return (list(cv.rows()), cv.w) + kept["rest"]
    cv, out, lanes, drawn, moved, gutter = _draw_base(setup, look, way)
    rest = (out, drawn, moved or [], lanes, gutter)
    if kept is not None:
        kept.update(lanes=lanes, out=out, rest=rest, styles={},
                    drawn=kit.Retained(cv, _base_looks(setup, look, out, lanes)))
    return (list(cv.rows()), cv.w) + rest


def _draw_base(setup: _TreeSetup, look: _TreeLook, way: _Way,
               again: _Again | None = None) -> tuple:
    """(canvas, _Outline, lanes, drawn chip keys, moved, gutter): the outline
    with its brackets, the lanes (packed, folded as `way` keeps them, styled
    by the frame and the checks), the tokens, the right margin (relocated as
    `way` says: moved) and the section rules. `again`: just the outline rows
    and the lanes taking any of its rows — those rows come out as the whole
    drawing draws them."""
    s, frame = setup, look.frame
    cv = kit.Canvas()
    out = _draw_outline(cv, s.rows, s.blocks, show_tags=s.notes != "callouts" or way.left,
                        x0=s.x0, extra=s.after_label, marks=look.marks, sim=look.sim_rows,
                        only=again.rows if again else None, laid=again.laid if again else None)
    out = again.laid if again else out
    _draw_brackets(cv, s.brackets, s.xs, s.x0)
    gutter = max(out.ends) + 3
    found = _collect_lanes(cv, s.wires, out, s.homes)
    if again:
        lanes = again.lanes
        shown = [ln for ln in lanes if not again.rows.isdisjoint(range(ln.lo, ln.hi + 1))]
    else:
        lanes = _pack_lanes(found, gutter, frame)
        if way.keep is not None:
            lanes = _fold_lanes(lanes, gutter, way.keep)
        if s.checks is not None:
            lanes = _check_lanes(lanes, s.checks)
        shown = lanes
    _draw_lanes(cv, shown, out.ends, muted_sources=frame is not None)
    _draw_join_taps(cv, shown, out.ends, s.joins)
    if frame is not None:
        for x, y, mark, style in _token_cells(frame.tokens, lanes,
                                              _self_call_cells(s.calls, out), look.probe):
            cv.put(x, y, mark, style)
    moved = [] if way.right else None
    chips, drawn = _row_chips(lanes, s.chip_lists, look.self_chips)
    _draw_right_margin(cv, lanes, out, chips, s.trailing, s.notes, moved)
    if again and again.width > cv.w:            # a part of the drawing: the whole one's width
        cv._grow(again.width - 1, 0)
    for y, row in enumerate(s.rows):            # section rules run the full width
        if isinstance(row, Banner) and row.kind == "section" and out.ends[y] < cv.w:
            cv.put(out.ends[y], y, "─" * (cv.w - out.ends[y]), kit.SECTION_STYLE)
    return cv, out, lanes, drawn, moved, gutter


def _restyled(lanes: list, frame, checks, styles: dict) -> list:
    """Packed lanes (_pack_lanes, folded or not) styled as a frame shows them:
    each its wire's colour in its simulation state, a marked one in its
    finding's style (_check_lanes). `styles`: {(lane, state): its style},
    filled here — the same lanes' styles, worked out once each."""
    out = []
    for i, ln in enumerate(lanes):
        state = _stroke_state(ln.idents, frame)
        style = styles.get((i, state))
        if style is None:
            style = scene.wire_style(ln.wire, state)
            if checks is not None:              # a marked lane: its finding's style
                style = _check_lanes([ln._replace(style=style)], checks)[0].style
            styles[(i, state)] = style
        out.append(ln if ln.style == style else ln._replace(style=style))
    return out


def _base_looks(setup: _TreeSetup, look: _TreeLook, out: _Outline, lanes: list) -> dict:
    """{element: (its rows, its look)} of a tree drawing under a frame, for
    kit.Retained: each outline row's status and call marks, each lane's style,
    each row's chips, the tokens' cells."""
    sim_rows, marks = look.sim_rows or {}, look.marks
    now = {("row", y): ((y,), (sim_rows.get(y), marks.get(y))) for y in set(sim_rows) | set(marks)}
    for i, ln in enumerate(lanes):
        now[("lane", i)] = (range(ln.lo, ln.hi + 1), ln.style)
    chips, _drawn = _row_chips(lanes, setup.chip_lists, look.self_chips)
    for y, row in chips.items():
        now[("chips", y)] = ((y,), row)
    if look.frame is not None:
        cells = _token_cells(look.frame.tokens, lanes, _self_call_cells(setup.calls, out),
                             look.probe)
        now[("tokens",)] = (frozenset(y for _x, y, _m, _s in cells), cells)
    return now


class _Bracket(NamedTuple):
    """A control block in the tree view: its header row and member rows."""
    header: int
    members: list


def _machine_banners(rows, g, secs) -> list:
    """Pending section banners for each top-level state machine drawn open: a
    `── {Trip} state machine ──` rule above its owner (the graph view's title for
    it), and — when more top-level rows of the same `--- section ---` follow the
    machine — that section's rule again after it, so they don't read as part of
    the machine."""
    out = []
    est = kit.node_lines(g) if secs else {}
    top = [i for i, r in enumerate(rows) if isinstance(r, TreeRow) and r.graph is g
           and r.depth == 0]

    def machine(i):
        sub = g.expansions.get(rows[i].node.id)
        return not rows[i].collapsed and getattr(sub, "role", "") == "state"

    for n, i in enumerate(top):
        r = rows[i]
        if not machine(i):
            continue
        out.append((i, (1, 1), Banner("section", kit.section_rule(
            f"{kit.node_label(r.node)} state machine")), None))
        nxt = top[n + 1] if n + 1 < len(top) else None
        if nxt is None or machine(nxt):         # a machine's own rule follows
            continue
        here = kit.section_of(secs, est.get(r.node.id, 0)) if secs else -1
        after = kit.section_of(secs, est.get(rows[nxt].node.id, 0)) if secs else -1
        if after == here:                       # else that section's own rule follows
            name = kit.section_name(secs[here]) if here >= 0 else ""
            out.append((nxt, (0, 0), Banner("section", kit.section_rule(name)), None))
    return out


def _tree_banners(rows, g):
    """rows with banners inserted: a section divider before the first top-level
    unit of each `--- section ---`, a `── X state machine ──` divider above each
    top-level state machine drawn open (_machine_banners), and each control
    block's header — before the first member row the block introduces (else after
    its last member row). Returns (rows, brackets)."""
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
    pending += _machine_banners(rows, g, secs)
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
            pending.append((at, (prio, -span), Banner("block", kit.block_title_runs(b),
                                                              kit.block_note_key(b)), ys))
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
    outline climbs above it — found in one backward pass. An expansion's member
    (rel INTERNAL_MARK) branches dotted (├┄ / └┄), and the rail down to one is
    dotted (┆): internals apart from the `\\->` contains relation's solid lines."""
    guides = [None] * len(rows)
    later = []              # later[k]: the rail down to the next row at depth k
    for y in range(len(rows) - 1, -1, -1):  # ("│" / "┆"), "" when none follows
        if not isinstance(rows[y], TreeRow):    # a blank row or a banner
            continue
        d = rows[y].depth
        dotted = rows[y].rel == INTERNAL_MARK
        if d:
            def cont(k):
                return later[k] if k < len(later) else ""
            guides[y] = ("".join(f"{cont(k) or ' '}  " for k in range(1, d))
                         + ("├" if cont(d) else "└") + ("┄" if dotted else "─"))
        else:
            guides[y] = ""
        del later[d + 1:]
        later += [""] * (d + 1 - len(later))
        later[d] = "┆" if dotted else "│"
    return guides


def _one_of_spans(rows) -> list:
    """[(first, last)]: the row spans of each run of two or more `\\-_` one-of
    siblings (consecutive under one parent; a sibling's own subtree may sit
    between them). The outline joins each with a brace (ONE_OF_BRACE)."""
    spans, open_at = [], {}     # depth → (first, last) of the run still open there
    def close(d):
        first, last = open_at.pop(d)
        if last > first:
            spans.append((first, last))
    for y, row in enumerate(rows):
        if not isinstance(row, TreeRow):
            continue
        for d in [k for k in open_at if k > row.depth]:     # climbed out of a run
            close(d)
        if row.depth in open_at and not row.rel.endswith("_"):
            close(row.depth)
        if row.depth and row.rel.endswith("_"):
            first = open_at.get(row.depth, (y, y))[0]
            open_at[row.depth] = (first, y)
    for d in sorted(open_at):
        close(d)
    return sorted(spans)


def outline_marks(g, depth: int) -> set:
    """The outline's structure marks the drawing of g to `depth` shows, for the
    legend: INTERNAL_MARK when an expansion's members are drawn, the brace's top
    piece when a one-of set is joined."""
    rows = _tree_rows(g, depth)
    marks = {INTERNAL_MARK} if any(r.rel == INTERNAL_MARK for r in rows) else set()
    return marks | ({ONE_OF_BRACE[0]} if _one_of_spans(rows) else set())


@dataclass
class _Outline:
    ends: list                                  # per row: x just past its text (0 if blank)
    by_id: dict                                 # node id → the rows it is drawn on
    chain_at: dict                              # y → names root → this row
    graph_at: dict                              # y → the graph its node is drawn from
    tagged: dict                                # node id → row carrying its #N
    marks_at: dict                              # y → x of its call mark (_call_marks)


def _draw_outline(cv: kit.Canvas, rows, idx: dict, show_tags: bool = True, x0: int = 0,
                  extra: dict | None = None, marks: dict | None = None,
                  sim: dict | None = None, only: frozenset | None = None,
                  laid: "_Outline | None" = None) -> _Outline:
    """The outline from column x0: rails, relation, label, the row's call marks
    (marks: {row: runs}, _call_marks), #N tag, the extra runs a node carries
    (modifiers, a writer badge, a branch arm's label) and (for a state) the
    triggers that lead into it, one row each. A banner row (a section
    divider, a block's header) is drawn as its runs; a block header inside a
    unit sits at its next row's label column, the rails it interrupts bridged.
    `sim` ({row: _SimRow}, _sim_rows): a simulation frame's look — every row a
    status slot before its label (its mark, if any), the label restyled by its
    node's status, its badges after the call marks.

    `only` (rows) with `laid` (the _Outline of the whole outline): just the
    rows `only` drawn as the whole outline draws them (and the rows a bridge or
    a brace there reads); the _Outline returned is then partial."""
    out = _Outline([], {}, {}, {}, {}, {})
    slot = len(SIM_SLOT) if sim is not None else 0
    stack = []
    guides = _guides(rows)
    extra, extra_done, bridges = extra or {}, set(), []

    def rail(y, step):
        while 0 <= y < len(rows) and isinstance(rows[y], Banner):
            y += step
        return y if 0 <= y < len(rows) and isinstance(rows[y], TreeRow) else None

    spans = _one_of_spans(rows)
    drawn = None if only is None else _outline_rows(rows, only, spans, rail)
    for y, (row, guide) in enumerate(zip(rows, guides)):
        if row is None:
            out.ends.append(0)
            continue
        if drawn is not None and y not in drawn:    # not drawn: its first-row marks only
            key = row.key if isinstance(row, Banner) else row.node.id
            if key in idx and key not in out.tagged:
                out.tagged[key] = y
            if isinstance(row, TreeRow) and key in extra:
                extra_done.add(key)
            out.ends.append(laid.ends[y])
            continue
        if isinstance(row, Banner):
            x = x0
            if row.kind == "block":
                nxt = next((guides[j] for j in range(y + 1, len(rows))
                            if isinstance(rows[j], TreeRow)), "")
                x = x0 + (kit.cell_width(nxt) + 2 if nxt else 0) + slot
                bridges.append((y, x))
            x = kit._put_runs(cv, x, y, row.runs)
            if row.key is not None:             # the header's row: its notes' anchor
                out.by_id.setdefault(row.key, []).append(y)
            if row.key in idx and row.key not in out.tagged:    # a comment above the block
                if show_tags:
                    x = kit._put_runs(cv, x, y, kit.note_tag_runs(idx[row.key]))
                out.tagged[row.key] = y
            out.ends.append(x)
            continue
        n, rel = row.node, row.rel
        stack = stack[:row.depth] + [n.name]
        out.chain_at[y] = tuple(stack)
        out.graph_at[y] = row.graph
        x = x0
        if row.depth:
            cv.put(x0, y, guide, kit.TREE_STYLE)
            x = x0 + kit.cell_width(guide)
            if rel and rel not in ("─", INTERNAL_MARK):
                cv.put(x, y, rel, kit.REL_STYLE)
                x += kit.cell_width(rel)
            else:
                cv.put(x, y, rel or "─", kit.TREE_STYLE)
                x += 1
            x += 1
        state = sim.get(y) if sim is not None else None
        if sim is not None:
            if state is not None and state.mark:
                cv.put(x, y, state.mark, _status_style(n, state.status))
            x += slot
        _border, text = kit.node_styles(n)
        runs = kit.label_runs(n) if state is None else _status_label_runs(n, state.status)
        if state is not None and state.probe:
            runs = kit.probed(runs)
        runs += _stream_runs(n) + ([(" ▸", (text[0], None, True))] if row.collapsed else [])
        x = kit._put_runs(cv, x, y, runs)
        if marks and y in marks:
            out.marks_at[y] = x + 1             # each mark run leads with a space
            x = kit._put_runs(cv, x, y, marks[y])
        if state is not None:
            x = kit._put_runs(cv, x, y, state.badges)
        if n.id in idx and n.id not in out.tagged and not show_tags:
            out.tagged[n.id] = y                # callouts point here with `#>` instead
        if n.id in idx and n.id not in out.tagged:  # `#N` on the node's first row
            tag = " " + kit.note_tag(idx[n.id])
            tx = x
            for run, style in kit.note_tag_runs(idx[n.id]):
                cv.put(tx, y, run, style)
                tx += kit.cell_width(run)
            x += kit.cell_width(tag)
            out.tagged[n.id] = y
        if n.id in extra and n.id not in extra_done:    # on the node's first row
            extra_done.add(n.id)
            x = kit._put_runs(cv, x, y, extra[n.id])
        if n.kind == "state":                   # the triggers that lead into this state
            into = sorted({e.label for e in row.graph.edges if e.dst == n.id and e.label})
            if into:
                cv.put(x + 1, y, " ".join(into), kit.LABEL_STYLE)
                x += 1 + kit.cell_width(" ".join(into))
        out.ends.append(x)
        out.by_id.setdefault(n.id, []).append(y)

    for y, text_x in bridges:                   # rails run on through a block header
        above, below = rail(y - 1, -1), rail(y + 1, 1)
        if above is None or below is None:
            continue
        for x in range(x0, text_x):
            down = cv.cell(x, below)[0]
            if (cv.cell(x, above)[0] in "│┆├" and down in "│┆├└"):
                dotted = down == "┆" or cv.cell(x + 1, below)[0] == INTERNAL_MARK
                cv.put(x, y, "┆" if dotted else "│", kit.TREE_STYLE)
    for first, last in spans:                   # a brace joins the one-of set
        if drawn is not None and not drawn.issuperset(range(first, last + 1)):
            continue
        bx = max(out.ends[first:last + 1]) + 1
        for y in range(first, last + 1):
            piece = ONE_OF_BRACE[0 if y == first else 2 if y == last else 1]
            cv.put(bx, y, piece, kit.REL_STYLE)
            out.ends[y] = bx + 1
    return out


def _outline_rows(rows, only: frozenset, spans: list, rail) -> set:
    """The outline rows to draw so that the rows `only` come out whole: those,
    the rail rows above and below a block header among them (its bridge reads
    them), and every row of a one-of set with a row among them (its brace
    stands right of the set's widest row)."""
    out = set(only)
    for y in only:
        if 0 <= y < len(rows) and isinstance(rows[y], Banner) and rows[y].kind == "block":
            out.update(r for r in (rail(y - 1, -1), rail(y + 1, 1)) if r is not None)
    for first, last in spans:
        if any(first <= y <= last for y in only):
            out.update(range(first, last + 1))
    return out


LANE_ROLES = ("flow", "trigger", "emit", "access")     # the wires drawn as lanes


def _lane_wires(scn) -> list:
    """[(wire, idents)]: the Scene's wires the gutter draws, one per stroke —
    flows, triggers, emits (the first of a key: one stroke per emitter →
    destination), permissions — keyed by (key, qualified ends); an emit wire
    takes the place of a flow it coincides with (the event is what that stroke
    carries). idents: every wire the stroke stands for (what a simulation
    frame names it by). A self-call is no lane: its row carries it
    (_self_call_rows)."""
    out, idents, emitted = {}, {}, {}           # emitted: key → its stroke
    for w in scn.wires:
        if w.role not in LANE_ROLES or _is_self_call(w):
            continue
        stroke = (w.key, w.paths)
        if w.role == "emit" and w.key in emitted:
            stroke = emitted[w.key]             # rides on the first emit of its key
        elif w.role == "emit":
            emitted[w.key] = stroke
            out[stroke] = w
        else:
            out.setdefault(stroke, w)
        idents.setdefault(stroke, set()).add(w.ident)
    return [(w, frozenset(idents[stroke])) for stroke, w in out.items()]


EXTERNAL_MARK = "⇱"      # a host-provided far node (opaque), after its label


def _is_self_call(w) -> bool:
    """A self-call drawn on its subject's row (not a qualified-path self-edge,
    which is a lane between two rows)."""
    return w.call is not None and w.call.self_call and not any(w.paths)


def _self_call_rows(scn, rows) -> dict:
    """{row index: [self-call wire]}: the self-calls of each outline row's node
    written in the unit the row is drawn from — a node drawn in two units shows
    each unit's own — in written order."""
    owner = {id(u.graph): u.owner for u in scn.units}
    by_unit = {}                                # (unit owner, node id) → wires
    for nid, ws in scene.self_calls(scn).items():
        for w in ws:
            if _is_self_call(w):
                by_unit.setdefault((w.owner, nid), []).append(w)
    out = {}
    for y, r in enumerate(rows):
        if isinstance(r, TreeRow):
            ws = by_unit.get((owner.get(id(r.graph)), r.node.id))
            if ws:
                out[y] = ws
    return out


def _call_marks(scn, rows, calls: dict, frame=None) -> dict:
    """{row index: runs} after a row's label: its self-calls' mark (scene.self_mark:
    `↻` recursion, `↺` a self-call, `⇱` only host ops) in its first call's stroke,
    then `⇱` on the far node of an external op call, in that call's stroke —
    each stroke in its simulation state in `frame` (_stroke_state).
    calls: _self_call_rows."""
    far = {}
    for w in scn.wires:
        if w.call is not None and w.call.external and not w.call.self_call:
            far.setdefault(w.dst, w)
    marks = {}
    for y, r in enumerate(rows):
        if not isinstance(r, TreeRow):
            continue
        runs = []
        if y in calls:
            mark = scene.self_mark([w.call for w in calls[y]])
            state = _stroke_state({w.ident for w in calls[y]}, frame)
            runs.append((" " + mark, scene.wire_style(calls[y][0], state)))
        if r.node.id in far:
            w = far[r.node.id]
            runs.append((" " + EXTERNAL_MARK,
                         scene.wire_style(w, _stroke_state({w.ident}, frame))))
        if runs:
            marks[y] = runs
    return marks


def _self_call_chips(calls: dict, payloads: bool, mods: bool, frame=None) -> dict:
    """{row index: [(chip text, stroke style)]}: each self-call's chip on its
    subject's row (`↺ plan({Seed}) ↩ {Plan}`, scene.chip_text) in its wire's
    stroke (its simulation state in `frame`), those with nothing to show left
    out. calls: _self_call_rows."""
    out = {}
    for y, ws in calls.items():
        chips = [(w, text, scene.wire_style(w, _stroke_state({w.ident}, frame)))
                 for w in ws for text in [scene.chip_text(w, payloads, mods)] if text]
        if chips:
            out[y] = chips
    return out


def _row_chips(lanes, chip_lists: dict, self_chips: dict) -> tuple:
    """({row index: [(chip text, stroke style)]}, {key}): each row's chips in
    order — its own self-calls' (_self_call_chips), then every chip
    (scene.chip_lists) of each lane it is the target of, one per call, never
    merged — each in its wire's stroke. A chip is one call, not one text: two
    calls with equal text both show, while the same call reaching a row twice
    (two lanes of one stroke) shows once; an error path's chip leads with `✖`
    (_error_lead). The keys are the strokes whose chips were placed."""
    chips, seen, drawn = {}, set(), set()

    def add(y, ident, text, style):
        if (y, ident) not in seen:
            seen.add((y, ident))
            chips.setdefault(y, []).append((text, style))

    for y, chips_ in self_chips.items():
        for w, text, style in chips_:
            add(y, ("self", id(w)), _error_lead(w, text), style)
            drawn.add(w.key)
    for ln in lanes:
        key = ln.wire.key
        texts = chip_lists.get(key, ())
        for y in ln.dy:
            for i, text in enumerate(texts):
                add(y, ("lane", key, i), _error_lead(ln.wire, text), ln.style)
        if texts:
            drawn.add(key)
    return chips, drawn


def _error_lead(w, text: str) -> str:
    """A chip's text, led by `✖` on an error path (`!>`): several chips on one
    row are told apart without colour."""
    return f"{kit.SOURCE_MARK['!>']} {text}" if w.kind == "!>" else text


class _Lane(NamedTuple):
    """A wire in the gutter: the rows it spans and the rows of each end; x and
    style once packed (_pack_lanes)."""
    lo: int
    hi: int
    wire: object                                # scene.Wire
    sy: list                                    # its source's rows
    dy: list                                    # its target's rows
    idents: frozenset = frozenset()             # the wires its stroke stands for
    x: int = 0
    style: tuple = None
    plug: str = ""                              # folded (_fold_lanes): its number, no vertical


def _collect_lanes(cv: kit.Canvas, wires, out: _Outline, homes: dict) -> list:
    """One _Lane per (wire, idents) of _lane_wires, over every row where either
    end occurs — in the wire's own unit (homes: owner → its graph) where the
    end is drawn there, so a node drawn in two expansions (a store each one
    borrows) takes each one's lanes on its own row — shortest first; a
    self-loop that is no call (a state's self-transition) is marked ↺ on its
    row instead."""
    def at(nid, path, home):
        ys = out.by_id.get(nid, [])
        if path:
            ys = [y for y in ys if out.chain_at[y][-len(path):] == tuple(path)]
        return [y for y in ys if out.graph_at[y] is home] or ys

    lanes = []
    for w, idents in wires:
        (spath, dpath) = w.paths
        home = homes.get(w.owner)
        sy, dy = at(w.src, spath, home), at(w.dst, dpath, home)
        if not sy or not dy:
            continue
        if w.src == w.dst and not spath and not dpath:
            for y in sy:
                cv.put(out.ends[y] + 1, y, "↺", kit.edge_style(w.kind))
            continue
        ys = sorted(set(sy) | set(dy))
        lanes.append(_Lane(ys[0], ys[-1], w, sy, dy, idents))
    lanes.sort(key=lambda lane: (lane.hi - lane.lo, lane.lo))
    return lanes


def _pack_lanes(lanes, left: int, frame=None) -> list:
    """Each lane with its gutter column (interval-packed from `left`) and its
    stroke style (its wire's colour, scene.wire_style — in its simulation state
    in `frame`, _stroke_state)."""
    cols = []
    return [lane._replace(x=left + kit._first_fit(cols, lane.lo, lane.hi) * LANE_GAP,
                          style=scene.wire_style(lane.wire, _stroke_state(lane.idents, frame)))
            for lane in lanes]


def _lane_cols(lanes, left: int) -> int:
    """How many gutter columns packed lanes take."""
    return max([(ln.x - left) // LANE_GAP + 1 for ln in lanes if not ln.plug] + [0])


def _fold_lanes(lanes, left: int, keep: int) -> list:
    """Lanes past the first `keep` gutter columns folded into plugs, for a
    drawing narrower than its gutter: a folded lane draws no vertical — each of
    its rows runs out past the kept lanes to the plug column, where it lists its
    plugs (_plug_rows): a source's mark and number (`●①`), a target's number
    (`◀───①`) — the flow view's numbered plugs (kit.plug_label), numbered in
    reading order of their first row. The kept lanes keep their columns
    (first-fit packing only ever moved them left)."""
    kept = [ln for ln in lanes if (ln.x - left) // LANE_GAP < keep]
    folded = sorted((ln for ln in lanes if (ln.x - left) // LANE_GAP >= keep),
                    key=lambda ln: (min(ln.sy + ln.dy), ln.lo, ln.x))
    start = left + keep * LANE_GAP
    return kept + [ln._replace(x=start, plug=kit.plug_label(k + 1))
                   for k, ln in enumerate(folded)]


def _fold_reach(lanes, left: int, keep: int) -> int:
    """How far right _fold_lanes(lanes, left, keep) reaches: the plug column
    plus the longest row of plugs, or the last kept lane (the outline and the
    right margin aside)."""
    folded = _fold_lanes(lanes, left, keep)
    rows = _plug_rows(folded)
    start = left + keep * LANE_GAP
    longest = max([kit.row_len(runs) for runs in rows.values()] + [0])
    return max([ln.x + 1 for ln in folded if not ln.plug] + [start + longest])


def _plug_rows(lanes) -> dict:
    """{row: runs} written from the plug column on each row a folded lane taps,
    its plugs in number order: a source's mark then the number, a target's
    number, each in its lane's style."""
    out = {}
    for ln in lanes:
        if not ln.plug:
            continue
        for y in dict.fromkeys(ln.sy + ln.dy):
            mark = _source_mark(ln.wire) if y in ln.sy else ""
            out.setdefault(y, []).append((mark + ln.plug, ln.style))
    return out


EMIT_MARK = "›"          # the source of a lane that carries an emitted event


def _source_mark(w) -> str:
    """The mark at a lane's source tap: `›` for an emitted event (a failure
    emission keeps its ✖), else the arrow's own source mark."""
    if w.role == "emit" and w.kind != "!>":
        return EMIT_MARK
    return kit.SOURCE_MARK.get(w.kind, "●")


def _draw_lanes(cv: kit.Canvas, lanes, ends, *, muted_sources: bool = False):
    """Verticals first; then each row's runs out to the lanes it taps, hopping
    (─│─) over lanes it merely crosses, so a joint (┤ ┴ ┬ ┼) only ever appears
    where a lane is actually tapped. `muted_sources`: each source mark (`●`,
    `›`, …) in its wire's muted colour whatever the lane's state — in a
    simulation, so a token (`●` in full colour + bold) on a source row stands
    out from the static marks."""
    verticals = set()
    for ln in lanes:
        if ln.hi > ln.lo and not ln.plug:
            cv.path([(ln.x, ln.lo), (ln.x, ln.hi)], ln.wire.kind, ln.style)
            verticals |= {(ln.x, y) for y in range(ln.lo, ln.hi + 1)}

    taps = {}                                   # y → [(lane x, kind, style, role, mark)]
    source_style = {}                           # (x, y) → its source mark's style
    for ln in lanes:
        mark = _source_mark(ln.wire)
        for y in ln.sy:
            taps.setdefault(y, []).append((ln.x, ln.wire.kind, ln.style, "src", mark))
            if muted_sources:
                source_style[(ln.x, y)] = scene.wire_style(ln.wire, "inactive")
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
                heads.append((x1, y, mark, source_style.get((x1, y), style)))
            # one ◀ per row, in the colour of the lane whose stroke runs into it
            if (role == "dst" and x1 == nearest) or (both and nearest < 0):
                heads.append((ends[y] + 1, y, "◀", style))
    for x, y, ch, st in heads:
        cv.put(x, y, ch, st)
    plugs = _plug_rows(lanes)                   # folded lanes: their plugs, in a row
    for y, runs in plugs.items():
        x = next(ln.x for ln in lanes if ln.plug)
        for text, style in runs:
            cv.put(x, y, text, style)
            x += kit.cell_width(text)


# ---------------------------------------------------------------------------
# Simulation overlay — one Frame of a sim.py Trace painted over the tree
# ---------------------------------------------------------------------------
#
# A frame restyles what the tree already draws and adds marks in room the
# layout keeps for them, so nothing moves while a trace plays (sim.md §7):
#   lanes     failed (a route taken, a call that failed) edges-fail; lit (a token
#             on it, a call in progress) full colour + bold; taken earlier the
#             trail (faded, ui.sim_trail); never taken faint (ui.sim_faint) —
#             chips, ◀ and taps follow;
#             source marks (`●`, `›`, …) always muted, so a token stands out
#   tokens    in the lane's gutter column, on the row `at` of the way from its
#             source row to its target row; a self-call's on its call mark
#   rows      a status mark in the slot before the label (STATUS_MARK: `▸`
#             active, `◉` a state machine's current state), the label in its
#             node's status style; a machine's other states muted
#   badges    after the call marks: `…` waiting, `✕` failed, `×n` instances
#             (n ≠ 1), `↻k` recursion depth, and `◉ State` on an owner whose
#             machine's states are not drawn — as the graph view's

SIM_SLOT = "▸ "          # the room before every label in a simulation
STATUS_MARK = {"active": "▸", "current": "◉"}
CANCELLED_MARK = "⊘"     # a cancelled token: neither `●` out nor `✕` failed
QUIET = ("idle", "cancelled", "dormant")    # statuses drawn muted (idle: untouched)
RAN = ("visited", "waiting", "opaque")      # statuses whose label is drawn as without a sim
STROKE_STATES = ("failed", "active", "trail", "inactive")   # the first that applies wins


class _SimRow(NamedTuple):
    """An outline row's look in one frame."""
    status: str             # a sim node status, or "idle" / "current" / "dormant"
    mark: str               # the status slot's mark ("" for none)
    badges: list            # runs after the call marks, padded to the node's widest
    probe: bool = False     # its label drawn in kit.Probe styles (sim_focus)


def _stroke_state(idents, frame) -> str:
    """The scene.wire_style state of a stroke standing for the wires `idents` in
    a frame ("plain" without one): failed > lit (active) > taken (trail) >
    never taken (inactive)."""
    if frame is None:
        return "plain"
    for state, seen in zip(STROKE_STATES, (frame.failed, frame.lit, frame.taken)):
        if any(i in seen for i in idents):
            return state
    return STROKE_STATES[-1]


def _row_status(row: TreeRow, machine_owner, frame) -> str:
    """A row's status in a frame: a state of a tracked machine (machine_owner:
    the owner of the state unit it is drawn in, else None) is "current" or
    "dormant"; any other row its node's sim status, "idle" when untouched."""
    if machine_owner is not None and machine_owner in frame.machines:
        return "current" if frame.machines[machine_owner] == row.node.id else "dormant"
    return frame.nodes.get(row.node.id, "idle")


def _badge_runs(n, frame, hidden: set, names: dict) -> list:
    """The runs after a node's label in a frame (sim.md §7.1, as the graph view's):
    ` …` waiting (kind colour), ` ✕` failed (edges-fail, bold), ` ×n` instances
    when n ≠ 1, ` ↻k` a recursion depth over 1 (kind colour), and ` ◉ State`
    (state colour, bold) when it owns a machine whose states are not drawn
    (hidden: those owners). names: {node id: label}."""
    nid, colour = n.id, (kit.kind_color(n.kind), None, False)
    runs = []
    status = frame.nodes.get(nid)
    if status == "waiting":
        runs.append((" …", colour))
    elif status == "failed":
        runs.append((" ✕", (scene.colour_of("edges-fail"), None, True)))
    count = frame.instances.get(nid)
    if count is not None and count != 1:
        runs.append((f" ×{count}", colour))
    if frame.depth.get(nid, 0) > 1:
        runs.append((f" ↻{frame.depth[nid]}", colour))
    if nid in hidden and nid in frame.machines:
        state = frame.machines[nid]
        runs.append((f" ◉ {names.get(state, state)}", (kit.kind_color("state"), None, True)))
    return runs


def _padded(runs: list, width: int) -> list:
    """runs followed by blanks up to width."""
    pad = width - kit.row_len(runs)
    return runs + ([(" " * pad, None)] if pad > 0 else [])


class _SimStage(NamedTuple):
    """What every frame of a run reads its outline rows' looks against
    (_sim_stage): the same for the whole trace."""
    machines: dict              # row index → the owner of the state unit it is drawn in
    hidden: set                 # the owners of machines tracked but not drawn
    names: dict                 # node id → its label
    widest: dict                # node id → its widest badges over the trace


def _sim_stage(scn, rows, trace) -> _SimStage:
    """_sim_rows' _SimStage of a trace drawn over these rows."""
    owner = {id(u.graph): u.owner for u in scn.units}
    drawn_machines = {owner.get(id(r.graph)) for r in rows
                      if isinstance(r, TreeRow) and getattr(r.graph, "role", "") == "state"}
    # the machines tracked anywhere in the trace, so every frame pads alike
    hidden = set().union(*(f.machines for f in trace.frames)) - drawn_machines
    nodes = {nid: n for cur in kit._walk(scn.graph) for nid, n in cur.nodes.items()}
    names = {nid: kit.node_label(n) for nid, n in nodes.items()}
    machines = {y: owner.get(id(r.graph)) for y, r in enumerate(rows)
                if isinstance(r, TreeRow) and getattr(r.graph, "role", "") == "state"}
    return _SimStage(machines, hidden, names, _trace_badge_widths(trace, nodes, hidden, names))


def _sim_rows(stage: _SimStage, rows, frame, probe: bool = False) -> dict:
    """{row index: _SimRow} for every outline row in `frame` (of the trace
    `stage` was worked out for); each node's badges padded to its widest over
    the whole trace, so the layout holds still."""
    out = {}
    for y, r in enumerate(rows):
        if not isinstance(r, TreeRow):
            continue
        status = _row_status(r, stage.machines.get(y), frame)
        out[y] = _SimRow(status, STATUS_MARK.get(status, ""),
                         _padded(_badge_runs(r.node, frame, stage.hidden, stage.names),
                                 stage.widest.get(r.node.id, 0)), probe and status == "active")
    return out


def _badge_nodes(frame, hidden: set) -> set:
    """The nodes that carry a badge in a frame (_badge_runs): waiting or failed,
    other than one instance, a recursion depth over 1, a hidden machine's owner."""
    return ({nid for nid, st in frame.nodes.items() if st in ("waiting", "failed")}
            | {nid for nid, k in frame.instances.items() if k != 1}
            | {nid for nid, k in frame.depth.items() if k > 1}
            | (hidden & frame.machines.keys()))


def _badge_widths(trace, nodes: dict, hidden: set, names: dict) -> dict:
    """{node id: its widest _badge_runs over the whole trace}, for the nodes
    (nodes: {id: Node}, the drawing's) that ever carry one — a node left out
    never has a badge. One pass over the frames, visiting only the badged
    nodes of each."""
    widest = {}
    for f in trace.frames:
        for nid in _badge_nodes(f, hidden) & nodes.keys():
            n = kit.row_len(_badge_runs(nodes[nid], f, hidden, names))
            widest[nid] = max(widest.get(nid, 0), n)
    return widest


_WIDTHS_KEPT = 8
_widths_memo: list = []     # (trace, its key, its _badge_widths), most recent last


def _trace_badge_widths(trace, nodes: dict, hidden: set, names: dict) -> dict:
    """_badge_widths, worked out once per trace object and drawing (its hidden
    owners, its nodes' names): a run plays frame after frame of one trace. The
    memo holds the last _WIDTHS_KEPT (by identity — a Trace holds dicts, so it
    cannot be hashed), as view_graph's _trace_slots does."""
    key = (frozenset(hidden), tuple(names.items()))
    for kept, kept_key, widest in _widths_memo:
        if kept is trace and kept_key == key:
            return widest
    widest = _badge_widths(trace, nodes, hidden, names)
    _widths_memo.append((trace, key, widest))
    del _widths_memo[:-_WIDTHS_KEPT]
    return widest


def _status_style(n, status: str) -> tuple:
    """The style of a node's label (and its status mark) in a status: active and
    a current state in full kind colour + bold, failed edges-fail, quiet ones
    muted, the rest the kind colour."""
    if status == "failed":
        return (scene.colour_of("edges-fail"), None, True)
    colour = kit.kind_color(n.kind)
    if status in QUIET:
        return (kit.muted(colour), None, False)
    return (colour, None, status in ("active", "current"))


def _status_label_runs(n, status: str) -> list:
    """A node's label as runs in a status: as drawn without a simulation when it
    has run (visited, waiting, opaque), else one run in its _status_style."""
    if status in RAN:
        return kit.label_runs(n)
    return [(kit.node_label(n), _status_style(n, status))]


def _self_call_cells(calls: dict, out: _Outline) -> dict:
    """{ident: (x, y, wire)}: where a token on a self-call is drawn — on its row's
    call mark. calls: _self_call_rows."""
    return {w.ident: (out.marks_at[y], y, w)
            for y, ws in calls.items() if y in out.marks_at for w in ws}


def _token_glyph(tok, wire) -> tuple:
    """(mark, style) of a token on a wire (sim.md §7.1): `●` out in the wire's
    colour + bold, `○` a return (produces' colour), a fallback return `○`
    muted, `✕` a failed attempt or route (edges-fail), `⊘` a cancelled one
    (CANCELLED_MARK) muted."""
    produces = kit.EDGE_DEFAULT
    if tok.state == "failed":
        return "✕", scene.wire_style(wire, "failed")
    if tok.state == "cancelled":
        return CANCELLED_MARK, scene.wire_style(wire, "inactive")
    if tok.state == "fallback":
        return "○", (kit.muted(produces), None, False)
    if tok.dir == "back":
        return "○", (produces, None, True)
    return "●", scene.wire_style(wire, "active")


def _token_row(lane: _Lane, at: float) -> int:
    """The row `at` of the way from a lane's source row to its target row (the
    target row nearest the first source row); a folded lane has no rows between:
    its source row's plug for the first half, then its target row's."""
    src = lane.sy[0]
    dst = min(lane.dy, key=lambda y: (abs(y - src), y))
    if lane.plug:
        return src if at < 0.5 else dst
    return round(src + at * (dst - src))


def _token_cells(tokens, lanes, self_cells: dict, probe: bool = False) -> tuple:
    """((x, y, mark, style), …): each token as drawn over the drawing, in task
    order (a later token on the same cell wins): in its lane's gutter column on
    _token_row, or on a self-call's mark (self_cells, _self_call_cells).
    Tokens on wires the tree does not draw are left out. `probe`: each in a
    kit.Probe style (sim_focus)."""
    lane_of = {i: ln for ln in lanes for i in ln.idents}
    out = []
    for tok in tokens:
        if tok.wire in lane_of:
            ln = lane_of[tok.wire]
            x, y, wire = ln.x, _token_row(ln, tok.at), ln.wire
        elif tok.wire in self_cells:
            x, y, wire = self_cells[tok.wire]
        else:
            continue
        mark, style = _token_glyph(tok, wire)
        out.append((x, y, mark, kit.Probe(style) if probe else style))
    return tuple(out)


def check_extras(scn, checks) -> dict:
    """{node id: runs} after a row's label for the checks overlay: the numbers
    of the findings marked on the node, then those on the wires it is the
    target of (each once, number order), kit.check_runs."""
    dst = {w.ident: w.dst for w in scn.wires}
    marks = {nid: set(ms) for nid, ms in checks.nodes.items()}
    for ident, ms in checks.wires.items():
        if ident in dst:
            marks.setdefault(dst[ident], set()).update(ms)
    return {nid: kit.check_runs(sorted(ms)) for nid, ms in marks.items()}


def _check_lanes(lanes, checks) -> list:
    """Each lane whose stroke stands for a marked wire restyled in its worst
    finding's style (kit.check_mark_style); the rest as they are."""
    out = []
    for ln in lanes:
        ms = [m for ident in ln.idents for m in checks.wires.get(ident, ())]
        out.append(ln._replace(style=kit.check_mark_style(kit.check_worst(ms))) if ms else ln)
    return out


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


def _stream_runs(n) -> list:
    """A stream's mark after its label (` ≋`, in its kind's colour): a tree row
    has no box to shadow as the graph view does."""
    return [(" " + kit.STREAM_MARK, kit.node_styles(n)[0])] if n.is_stream else []


def _tree_extras(scn, mods: bool) -> dict:
    """{node id: runs} drawn after a node's label in the tree: the events that land
    on it, its modifiers (mods), its writer badge (the access option), the branch
    arms it is the entry of (‹read›)."""
    texts = _mods_texts(scn.graph) if mods else {}
    extra = {}
    for nid, sn in scn.nodes.items():
        runs = [run for ev in sn.landed
                for run in [(" ", None)] + kit.glyph_runs(kit.node_label(ev), "event")
                + _stream_runs(ev)]
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


def _draw_right_margin(cv: kit.Canvas, lanes, out: _Outline, chips: dict,
                       trailing: dict, notes: str, moved: list | None = None) -> None:
    """The right margin, the mirror of the note callouts: on each row its chips
    (chips: {row: [(text, style)]}, _row_chips — each its own ┆chip┆ in its
    wire's stroke) and the inline comment from each line it is the target of;
    on a node's row the inline comment of the line that placed it. A dotted
    leader ties them to the row's rightmost tap, hopping (┄│┄) over lanes it
    crosses. Comments show as `#N` (markers) or their text (callouts). With
    `moved` (a list), a row's payloads and comment text are relocated instead:
    the row ends in a `┆a┆` marker and moved gets (letter, [chip text],
    [(number, text)]); `#N` markers stay on the row."""
    plugs = {y: kit.row_len(runs) - 1 for y, runs in _plug_rows(lanes).items()}
    margin = max([ln.x + plugs.get(y, 0) for ln in lanes for y in ln.sy + ln.dy]
                 + [max(out.ends) - 1]) + 3
    rightmost, notes_at = {}, {}
    for ln in lanes:
        for y in list(ln.sy) + list(ln.dy):
            rightmost[y] = max(rightmost.get(y, 0), ln.x + (plugs.get(y, 0) if ln.plug else 0))
        for y in ln.dy:
            for note in trailing.get(ln.wire.key, ()):
                if note not in notes_at.setdefault(y, []):
                    notes_at[y].append(note)
    for key, notes_ in trailing.items():         # lines that only placed a node
        if isinstance(key, str) and key in out.by_id:
            y = out.by_id[key][0]
            notes_at.setdefault(y, []).extend(n for n in notes_ if n not in notes_at[y])
    leader = (kit.GREY["dim"], None, False)
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
                item = ([text for text, _style in chips.get(y, [])], go)
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
        for text, style in chips.get(y, ()):
            x = kit._put_runs(cv, x, y, [("┆ ", style)] + kit.payload_runs(text)
                              + [(" ┆", style)]) + 1
        for num, text in sorted(notes_at.get(y, ())):
            note = f"#{num}" if notes == "markers" else f"# {text}"
            cv.put(x, y, note, kit.NOTE_STYLE["inline"])
            x += kit.cell_width(note) + 2


def _extras(g, idx: dict, notes: str, payloads: bool, drawn: frozenset = frozenset(),
            note_width: int = kit.NOTE_WIDTH, width: int | None = None):
    """The lists under the tree: payloads not drawn as chips (when shown; a line
    wider than `width` wrapped under itself), then notes (markers mode, wrapped
    at note_width; in callouts mode the document's own notes, which no row could
    call out)."""
    extra = []
    pl = [f"  {kit.edge_text(sub, e)} : {e.payload}" for sub in kit._walk(g) for e in sub.edges
          if e.payload and (e.src, e.dst, e.kind) not in drawn] if payloads else []
    if width is not None:
        pl = [ln for p in pl for ln in (kit.wrap_cells(p, width, indent="    ", hyphens=False)
                                        if kit.cell_width(p) > width else [p])]
    if pl:
        extra += [[], kit.section_rule("payloads"), []] + [[(p, kit.PAYLOAD_STYLE)] for p in pl]
    if notes == "markers" and idx:
        extra += [[], kit.section_rule("notes"), []] + kit.note_rows(idx, note_width)
    elif notes == "callouts" and kit.DOC_NOTE in idx:  # about no row: listed instead
        extra += [[], kit.section_rule("notes"), []] + kit.note_rows(
            {kit.DOC_NOTE: idx[kit.DOC_NOTE]}, note_width)
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
            mc.put(2, top + j, kit.ljust_cells(ln, tw), style)
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
