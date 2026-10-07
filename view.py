#!/usr/bin/env python3
"""
view.py — Live terminal view of a Sigil document's graph.

Usage:
    view.py <file.sigil>                 # live view: redraws on every save
    view.py <file.sigil> --once          # print the drawing + lint once, exit
    view.py <file.sigil> --once --depth all --payloads --color always

Options:
    --depth N|all    Show `X := { … }` expansions as sections below the graph,
                     nested up to N levels (default: 1).
    --payloads       Show each flow's `: payload`: as a chip on its edge in the
                     graph view, in a list under the tree in the tree view.
    --no-lint        Skip lint diagnostics.
    --dialect NAME   Load a dialect (default: env SIGIL_DIALECT).
    --once           Print to stdout and exit (for agents / CI). Exit status is 1
                     when lint reports an error. Also used when stdout is not a tty.
    --color WHEN     auto (default: colour when stdout is a tty) | always | never.
    --theme NAME     Colour theme: a name in themes/ or a .yaml path (default:
                     env SIGIL_THEME, else sigil). See themes.py.
    --events MODE    land | nodes: how a pass-through event is drawn. land: where
                     it lands — no row / box of its own, each emitter wired straight
                     to each destination in the event's colour (tree: the › emit
                     marker, the event named on the destination row; graph: the
                     event named beside the edge's head). nodes: as a row / box of
                     its own (a hub). Default: tree land, graph and flow nodes;
                     given, it sets every view.
    --graph          Graph: boxes and edges, laid out top-down in layers.
    --tree           Tree + wires: the composition tree (`\\-` branches and `:=`
                     expansions) as an outline, every flow as a lane in a gutter —
                     ● marks a lane's source, ◀ each target; a row's run hops a lane
                     it only crosses (─│─) and joins (┤ ┴ ┬ ┼) only a lane it taps.
    --flow           Flow: a call graph read left to right — bare glyph labels (no
                     boxes) in columns by call depth, a node's first callee on its
                     row and the rest below, wires bending between the columns
                     (─┬─▶ ├─▶ ╰─▶), each flow's chip on its wire. The default view;
                     --graph, --tree and --run pick one of the others.
    --run            Run: one simulated run as a timeline — a lane per participant,
                     composition instance and recursion level, time (ticks) left to
                     right; --sim's run, else the happy one (the title says so).
    --unroll N|all   The run view: instances of one node shown before the rest fold
                     into `…×k more` (default 3; all: none fold).
    --compact        Tree view without the blank row between top-level units.
    --no-triggers    Start without event → state triggers (lanes / wires).
    --notes MODE     off | markers (#N tags + a notes list) | callouts (tree view:
                     boxes in a left margin tied to their rows).
    --width N        --once: the columns to fit (default: the terminal's width,
                     else 100). See "Fitting" below.
    --mods           Show modifiers as compact chips: an edge's (`@timeout 30s ×3`,
                     `!`, `?`) after its payload on its chip, a node's (`@sla …`,
                     `^10k drop`, `@loc …`) after its label. Off by default.
    --access         Show the permission graph (`@read` / `@write` / `@borrow`):
                     dotted edges principal → store headed r / w / b (tree: lanes
                     whose source is marked r / w / b), a store badged with its
                     writers, `1w` (one owns it) or `Nw` (shared). Off by default.
    --sim SCENARIO   Simulate a pathway of the design (sim.py): `happy` (every
                     default), a scenario's name (an unknown one lists them all),
                     or `a+b` to combine two. With --once: the final frame of the
                     run drawn over the view, the sim legend, then the outcome and
                     the run in plain words, one `tNNN …` line per step (sim.narrate).
                     Live: start in sim mode on that scenario.
                     `list`: the scenarios, one a line with its label. `all`: run
                     every scenario and print, with no drawing, a line per run —
                     name, outcome, frames, label — then its facts (machines' end
                     states, what failed, routes taken, ignored events, nodes left
                     waiting, open joins, bounds hit) and a summary line; diff
                     two versions' tables to see what changed. Exit status 0.
    --json           With --sim list / all: the same as JSON. With a scenario: that
                     run as JSON, no drawing — its facts (as --sim all lists them),
                     "steps" (the run in plain words: frame, tick, text) and "log"
                     (the simulator's own lines). With --run: the run's timeline as
                     data — lanes (key, label, parent, born, owner, spawned, folds),
                     spans (enter, leave, how, waits), moves, marks.
    --checks         The composition checks overlay (check.py, the document's mode):
                     with --once, the findings marked on the drawing, the checks
                     legend, then the findings list (each finding's question) after
                     lint. Live: start with the overlay on (key c).

Keys (live view):
    d  cycle depth (0 → 1 → all)   p  payloads   m  modifiers   a  access
    l  lint panel   r  reload
    1 2 3 4  the view: graph / tree / flow / run   t  the next view (graph → tree →
       flow → run → …)
    e  triggers (event ⇢ the state it drives)
    s  spacing between units      v  events: where they land / as nodes (per view)
    n  notes: off → #N markers + list → margin callouts (tree view); in the run
       view its own: run notes → the design's notes on each lane's node → off
    u  the run view: instances shown before folding, 3 → 8 → all
    f  fit to the window (rearranged, centred) / the natural layout, free to pan
    c  checks: the composition checks overlay (check.py) and the findings panel
    arrows / h j k L pan   pgup / pgdn / space page   g home   z  re-centre   q  quit
    mouse: drag to pan; wheel scrolls (shift+wheel or a sideways wheel: across)
    x  sim mode: play the chosen scenario's run over the drawing (every view plays
       the same run). In sim mode: space play / pause   , .  a frame back / on
       < >  the previous / next event (a frame where something happens)
       [ ]  previous / next scenario (named in the status bar; which of how many
       and what it is in the sim keys row)   - +  speed (¼ ½ 1 2 4 … 32 frames a
       second, starting at 2; a slow drawing skips frames to keep the pace)
       w  follow: pan to keep the run's tokens and active nodes in view (on)

Zero dependencies: python3 standard library only. The graph comes from
render.parse_document (the same parse render.py turns into Mermaid), laid out
top-down in layers (cycle breaking, longest-path layering, barycenter ordering,
block-merged x placement, one track per fan-out) and drawn with box-drawing
characters. The live view is a plain alternate-screen terminal loop. Fitted
(f, the default) it shows the drawing rearranged to the pane's width, centred while
it fits and scrolled when it doesn't; natural (f again) it shows the drawing as
--once without --width would and pans freely in x and y — keys, mouse drag, the
wheel — clamped so part of it always stays on screen. The status bar says which.

Fitting: a drawing wider than the window (the live pane, or --width) is
rearranged, never squashed — boxes, labels and the outline keep their shapes —
and grows down. Comment text rewraps between 16 and 40 columns; block comments
move to a panel at the top-left (their entity keeps its #N tag), payloads and
inline comments to one at the bottom-right (the flow keeps a ┆a┆ marker; in the
graph view a chip shrinks to its letter). A panel takes an empty corner of the
drawing when one is big enough. Then each view wraps: the graph view's layers
onto the layers below, the tree view's lanes into numbered plugs (●① … ◀───①),
the flow view into bands joined by plugs, the run view into bands of ticks; a
drawing that still can't fit says so under it. The summary and lint lines wrap
too. When everything fits, the drawing is exactly the natural one.

Boxes are colour-coded by node type (border + tinted fill); the sigil theme:
    [component] periwinkle   {data} violet   <event> pink   (actor) green
    |store| amber   state cyan   ? hole grey   (a dialect may register more kinds)
Border shape:  (actor) ╭╮ round   ~mutable ┏┓ heavy   [[alias]] rose
               ? hole ┄┆ dashed     ▸ collapsed expansion   ▾ shown below
               *stream ┒┃┛ shadowed   [Role‹N›] ╖║╜ stacked (a generic role: N
               members); tree rows mark a stream ` ≋`
Edge strokes:  ->  │─ light ▼      ~>  ╎╌ dashed      =>  ┃━ heavy
               *>  ║═ double       ?>  ┆┄ dotted       !>  │─ light, head ✖ (red)
               <-> heads both ends  ╏╍ pink  event ⇢ owner (e: a trigger)
               ╭┄┄╮ a chip on its edge: its payload (p) ┆ its modifiers (m)
               ┆┆r ┆┆w ┆┆b  principal → store access (a)  1w / Nw writers
               Two edges of different kinds between one pair are two strokes.
Structure:     ── L2 · Payments ──── a `--- section ---`: its flows and nodes
               ╭╌ ↺ loop @while … ╌╮ a control block's frame (∥ parallel,
               ◇ branch on, □ scope / @owns); a branch draws ╱◇ X.kind╲ with a
               ┆‹arm›┆ chip to each arm's entry; a `!>` after `}` leaves its subject
               ━┷┯┷━ &  a join bar where an `&` / `&?` / `/` endpoint forks or meets
               Tree view: blocks are brackets in a gutter left of the outline
               (┌─ header, ├─ member rows), a branch arm's label beside its entry
               (‹read›), a joined flow's taps marked (◀& ◀&? ◀/), sections a
               divider row, `<->` lanes ◀──▶.
The status bar shows the document's `#!mode`.

Flow view (--flow, 3): the call graph left to right, as the page's toy graphs
draw it. A node sits in the column of its call depth, its first callee on its
row; wires from one source share a trunk (─┬─▶ ├─▶ ╰─▶), wires into one target
with one head share its last run (─┴─▶), a target fed by several kinds of
arrow takes their heads stacked (▶┐ ✖┘). Strokes and heads are the graph's
(━ =>, ╌ ~>, ═ *>, ┄ ?>, ✖ !>, ◀─▶ <->, ╍ a trigger); a wire that only
crosses another hops it (─│─); a wire back to an earlier column runs along a
return row under the drawing (╰──╯) and comes up into its target. A chip sits
on its wire between the columns (─┆{Cart}┆─▶), a transition's or arm's label
and what the graph writes beside a head as bare text there; a self-call's chip
hangs on a stub under its subject (╰─● ┆ ↺ plan() ┆). Expansions and state
machines are parts under the document's; control blocks are not framed.

Simulation (x, --sim): the run's tokens travel the drawn wires — ● out (bold,
in the wire's colour), ○ a return or fallback, ✕ a failure (edges.fail), a faint
⊘ cancelled. Wires rank bright > taken > faint: the one a token is on now in
full colour and bold, those taken before faded (ui.sim_trail), those never
taken fainter (ui.sim_faint); untouched boxes muted; a node running is bold (▸
in the tree); after a label … waiting, ✕ failed, ×n spawned instances, ↻k
recursion depth, `◉ State` on a machine's owner when the machine is not drawn;
◉ before a drawn machine's current state. The status bar shows `sim <scenario>
▶ <speed> · t<tick>/<last> · episode <k>: <entry>` (the outcome on the last
frame). Under the footer, in words a mono terminal reads as well: `path` and
the hops of the episode so far in notation, numbered by branch — each run of
hops that starts again from a node already on the path is a branch, ① ② … —
with ✖ on a hop that failed, ⊘ one cancelled, ×N one repeated, and the hop a
token is on now bold, as its wire is (`▸` before it without colour):
`① (Shopper) -> [API] -> [Payments] ✖×4   ② [API] !> <PaymentFailed>` (on two
rows at most; when longer, the oldest branches fold into `①–③ …`); then the
last few events dim, and the narration line after `›` — what is happening now
in plain words (`[API] calls [Payments] with charge(total) — attempt 2 of 4`),
held while a token travels. --once --sim prints the path under its outcome.

Run view (--run, 4): one run as a timeline (view_run.py over sim.timeline) —
what did happen, where the other three views draw what can. Time runs left to
right on a tick ruler, one column a tick (a quiet stretch of more than 3 ticks
folds into one ≈ column); one lane per participant, composition instance
(`{Transform·2}`) and recursion level (`↻2` sub-rows), in the order they first
acted, an expansion's lanes indented under its node. █ working, ░ waiting, ◆
an event landing, then ✕ failed / ⊘ cancelled; a call drawn at its send tick
(╰──▶ in its arrow's stroke into the callee's first cell, a fan-out sharing one
vertical ├══▶ ╰══▶), an attempt failing on arrival ╰───✖ (retries repeat it), a
reply ───↩ on the callee's lane, ↺ a self-call, ┤ the base case, ⇱ a host op, •
an actor reached; ┆ between episodes; a spawned lane ◌ while its spawn hop
flies; `{…×k more}` a fold. A note per lane in plain words. During a run the
playhead ▼ (┊ down the blank cells) is the frame's tick: nothing right of it,
lanes appear as they are born, ● / ○ tokens ride the transits, ▸ marks the
lanes working. Without a run chosen it draws the happy run's final frame and
says so (x plays it). Narrow: notes shrink, then move below, then the timeline
wraps into bands, each with its own ruler and the lanes active in it.

Checks (c, --checks): check.py's findings, as the document's mode shows them,
marked on the drawing in the theme's ui.error / ui.warn colours — a box's
border, a wire's stroke (graph) or lane (tree) in its worst finding's colour,
and each finding's number after the label (◆ error, ▲ warning, △ info; a
wire's beside its head in the graph, on its target's row in the tree).
Acknowledged findings (`# accepts: rule — reason`) are drawn dimmed, numbered
✓N. The panel under the drawing lists each finding's line, rule and the
question it asks (an acknowledged one: its reason). A finding anchored on no
drawn node or wire (a block, the document) is listed only.

Modules: this file is the app (the --once printer, the live view, the CLI). The
drawing lives beside it — viewkit.py (styles, canvas, runs, notes, fit panels),
view_graph.py (the graph view), view_tree.py (the tree view), view_flow.py
(the flow view) and view_run.py (the run view) — and every name of those five
is also reachable here as view.NAME.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import select
import shutil
import signal
import sys
import textwrap
import time
from dataclasses import replace
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
vgraph = _sibling("sigil_view_graph", "view_graph.py")
vtree = _sibling("sigil_view_tree", "view_tree.py")
vflow = _sibling("sigil_view_flow", "view_flow.py")
vrun = _sibling("sigil_view_run", "view_run.py")
scene = _sibling("sigil_scene", "scene.py")
simulator = _sibling("sigil_sim", "sim.py")


def __getattr__(name: str):
    """view.NAME for every name of viewkit, view_graph, view_tree, view_flow and
    view_run (tests, the site and dialects use view.render, view.compose,
    view.KINDS, …). Looked up at access time, so a themed style (view.GREY) is
    always the one in use."""
    for mod in (kit, vgraph, vtree, vflow, vrun):
        if name in vars(mod):
            return vars(mod)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


dialects = (kit._load("sigil_dialects", "dialects.py") if (_HERE / "dialects.py").exists()
            else None)


# ---------------------------------------------------------------------------
# Options and legends — the --notes modes, the --once widths, the legend rows
# ---------------------------------------------------------------------------

NOTE_MODES = ("off", "markers", "callouts")
EVENT_MODES = scene.EVENTS                       # --events / v: "land" | "nodes"
# The views, in the order `t` steps through them and keys 1, 2, 3 … select them.
# A new view goes at the end (its key the next digit).
VIEWS = ("graph", "tree", "flow", "run")
DEFAULT_VIEW = "flow"                           # the view the viewer starts in
DEFAULT_EVENTS = {"graph": "nodes", "tree": "land", "flow": "nodes",
                  "run": "nodes"}               # each view's own (the run view draws a trace)
RUN_NOTES = vrun.RUN_NOTES                      # n in the run view: run → design → off
RUN_UNROLL = (vrun.sim.RUN_SHOW, 8, 0)          # u in the run view: instances shown before
                                                # folding (0: all)


def view_name(view) -> str:
    """The name of a view (a key of DEFAULT_EVENTS / ViewState.events): a name in
    VIEWS as it is, or a bool as the old tree flag (True: tree, False: graph).
    Raises ValueError for an unknown name."""
    if isinstance(view, bool):
        return "tree" if view else "graph"
    if view not in VIEWS:
        raise ValueError(f"view must be one of {', '.join(VIEWS)}, not {view!r}")
    return view


def start_view(view: str | None, tree: bool = False) -> str:
    """The view to start in: `view` (a name in VIEWS) when given, else the tree
    view for the old tree flag, else DEFAULT_VIEW."""
    return view_name(view) if view else "tree" if tree else DEFAULT_VIEW


def view_keys() -> str:
    """The keys that select a view, as the legend writes them (`1 2 3 4`)."""
    return " ".join(str(k) for k in range(1, len(VIEWS) + 1))


def events_by_view(events: str | None) -> dict:
    """{view: events mode} to start with: `events` (--events) for every view when
    given, else each view's default."""
    return {v: events or d for v, d in DEFAULT_EVENTS.items()}


ONCE_WIDTH = 100                                # --once width when stdout isn't a tty
LEGEND_WIDTH = 100                              # --once legend wrap width


def wrap_legend(row, cols: int):
    """Wrap a legend row (a label run, then (marker, word) run pairs) to `cols`,
    breaking only between entries; continuation lines are indented under the label."""
    label, items = row[0], [row[i:i + 2] for i in range(1, len(row), 2)]
    indent = (" " * len(label[0]), None)
    out, cur = [], [label]
    for item in items:
        if kit.row_len(cur) + kit.row_len(item) > cols and len(cur) > 1:
            out.append(cur)
            cur = [indent]
        cur = cur + item
    out.append(cur)
    return out


KEY_LEGEND = (("views", "view"), ("t", "next"), ("x", "sim"), ("c", "checks"),
              ("n", "notes"), ("u", "unroll"), ("e", "triggers"), ("v", "events"), ("s", "spacing"), ("f", "fit"),
              ("d", "depth"), ("p", "payloads"), ("m", "mods"), ("a", "access"),
              ("l", "lint"), ("z", "centre"), ("g", "home"), ("r", "reload"), ("q", "quit"))


def drawn_call_marks(graph, depth: int, payloads: bool) -> frozenset:
    """The call marks the drawing of `graph` to `depth` shows — the tree legend
    lists only these: each call wire's mark (scene.call_mark: `↻`, `⇱`, `↺`),
    `⇱` for an external op's far node, and `↩` when a call returns something and
    payloads are on; with them the glyph marks a node of it carries (`≋` a
    stream, `‹›` a generic role) and `ƀ` when a `@borrow(read)` is declared
    (listed only with the access entries), and the outline's structure marks
    (view_tree.outline_marks: `┄` internals, `⎫` a one-of set). A missing graph
    (a parse error) shows none."""
    if graph is None:
        return frozenset()
    scn = scene.build_scene(graph, depth=depth)
    calls = [w.call for w in scn.wires if w.call is not None]
    marks = {scene.call_mark(c) for c in calls}
    if any(n.external for n in scn.nodes.values()):
        marks.add("⇱")
    if any(sn.node.is_stream for sn in scn.nodes.values()):
        marks.add(kit.STREAM_MARK)
    if any(getattr(sn.node, "is_role", False) for sn in scn.nodes.values()):
        marks.add("‹›")
    if any(w.kind == "access:ƀ" for w in scene.access_wires(graph)):
        marks.add("ƀ")
    if payloads and any(c.returns for c in calls):
        marks.add("↩")
    marks |= vtree.outline_marks(graph, depth)
    return frozenset(marks - {""})


def keys_legend(state):
    """The hotkeys row for a ViewState; toggles that are on are shown bright (the
    events mode: when the active view's differs from its default)."""
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    on = {"x": state.sim_on, "c": state.show_checks,
          "e": state.show_triggers, "s": state.spaced,
          "p": state.payloads, "l": state.show_lint, "n": state.notes != "off",
          "m": state.show_mods, "a": state.show_access, "f": state.fit}
    row = [("keys   ", dim)]
    run = state.view == "run"
    for key, word in KEY_LEGEND:
        bright = on.get(key)
        if (key == "u" and not run) or (key in ("v", "d", "p", "m", "a", "e", "s") and run):
            continue                           # u: the run view's own; the rest: not its
        if key == "views":                     # 1 2 3 …: one key per view
            key, word = view_keys(), f"view:{state.view}"
            bright = state.view != DEFAULT_VIEW
        elif key == "n":
            word = f"notes:{state.run_notes if run else state.notes}"
            bright = (state.run_notes != "off") if run else bright
        elif key == "u":
            word = f"unroll:{state.unroll or 'all'}"
            bright = state.unroll != RUN_UNROLL[0]
        elif key == "v":
            word = f"events:{state.events_mode}"
            bright = state.events_mode != DEFAULT_EVENTS[state.view]
        elif key == "d":
            word = f"depth:{'all' if state.depth >= kit.ALL_DEPTH else state.depth}"
            bright = state.depth > 0
        row += [(key, kit.KEY_STYLE),
                (f" {word}  ", (kit.GREY["light"], None, bright) if bright else mid)]
    return row


SIM_KEYS = (("space", "play/pause"), (", .", "frame"), ("< >", "event"), ("[ ]", "scenario"),
            ("- +", "speed"), ("w", "follow"))


def sim_keys_legend(player=None, follow: bool | None = None):
    """The sim-mode hotkeys row (shown while sim mode is on); with a SimPlayer, the
    scenario entry says which of how many is chosen and what it is
    (`[ ] scenario 2/14 · Auth fails → Unauthorized`) and the speed entry the
    speed (`- + speed 2 frames/s`); `follow`: the follow toggle's state
    (`w follow:on`), bright while on."""
    mid = (kit.GREY["mid"], None, False)
    row = [("sim    ", (kit.GREY["dim"], None, False))]
    for key, word in SIM_KEYS:
        style = mid
        if key == "[ ]" and player is not None:
            word = player.choice()
        elif key == "- +" and player is not None:
            word = f"speed {speed_text(player.fps)}"
            style = (kit.GREY["light"], None, True)
        elif key == "w" and follow is not None:
            word = f"follow:{'on' if follow else 'off'}"
            style = (kit.GREY["light"], None, True) if follow else mid
        row += [(key, kit.KEY_STYLE), (f" {word}  ", style)]
    return row


def sim_legend(tree: bool = False) -> list:
    """The legend row of the simulation overlay's marks, one row for every view so
    they can't drift apart: tokens (● out in its wire's colour, ○ a return or
    fallback, ✕ failed, a muted ⊘ cancelled — view_graph.sim_look, which the flow
    view draws with too, and view_tree's lanes draw them alike; a failed node's
    badge shares the token's ✕ and its meaning, so it is listed once, here), wires
    now, taken before or untouched, the other badges after a label (… waiting, ×n, ↻k) and the
    drawn machine's current state. `tree`: adds the tree view's own entry, `▸` an
    active row."""
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    wire = (kit.EDGE_DEFAULT, None, True)
    trail = (kit.faded(kit.EDGE_DEFAULT, kit.SIM_TRAIL, "trail"), None, False)
    faint = (kit.faded(kit.EDGE_DEFAULT, kit.SIM_FAINT, "faint"), None, False)
    fail = (scene.colour_of("edges-fail"), None, True)
    light = (kit.GREY["light"], None, False)
    state = (kit.kind_color("state"), None, True)
    active = [("▸", (kit.GREY["light"], None, True)), (" active  ", mid)] if tree else []
    return ([("run    ", dim),
             ("●", wire), (" out  ", mid), ("○", wire), (" return / fallback  ", mid),
             ("✕", fail), (" failed  ", mid), (vtree.CANCELLED_MARK, faint), (" cancelled  ", mid),
             ("─", wire), (" now  ", mid), ("─", trail), (" taken  ", mid),
             ("─", faint), (" untouched  ", mid)]
            + active
            + [("…", light), (" waiting  ", mid),
               ("×n", light), (" instances  ", mid), ("↻k", light), (" recursion  ", mid),
               ("◉", state), (" current state  ", mid), ("◉ State", state),
               (" its owner's, machine not drawn", mid)])


def path_legend() -> list:
    """The legend row of the run's path (the row under the footer, path_rows):
    the hops taken so far, ①② its branches, the marks on a hop, and the hop a
    token is on now — bold, or `▸` where there is no colour."""
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    light = (kit.GREY["light"], None, False)
    return [("path   ", dim), ("", mid), ("the hops taken so far:  ", mid),
            ("①②", light), (" its branches  ", mid), ("✖", light), (" failed  ", mid),
            ("⊘", light), (" cancelled  ", mid), ("×N", light), (" repeated  ", mid),
            ("▸", (kit.GREY["mid"], None, True)), (" the hop now (bold in colour)", mid)]


# ---------------------------------------------------------------------------
# Simulation — one document's run and the controls over it (sim.py does the
# running; the views draw a Frame). Pure: the clock comes in as `now`.
# ---------------------------------------------------------------------------

SIM_KEY_NAMES = (" ", ",", ".", "<", ">", "[", "]", "-", "+", "=", "w")   # = is + without shift
SIM_SPEEDS = (0.25, 0.5, 1, 2, 4, 8, 16, 32)   # frames per second, - / + steps
SIM_SPEED = 3                                   # the starting speed: 2 frames a second (a hop
                                                # of Limits.hop = 4 ticks takes 2 s)
SIM_LOG_ROWS = 3                                # the recent events above the narration line
_FRACTIONS = {0.25: "¼", 0.5: "½"}


def speed_text(fps: float) -> str:
    """A speed as the status bar writes it: `2 frames/s`, `½ frame/s`, `1 frame/s`."""
    n = _FRACTIONS.get(fps, f"{fps:g}")
    return f"{n} frame{'s' if fps > 1 else ''}/s"


class UnknownScenario(LookupError):
    """A scenario name the document doesn't have; the message lists the known ones."""


class SimPlayer:
    """The simulator's controls over one parsed document: its scenarios, the
    chosen one's Trace (on the canonical scene), the frame shown, play / pause
    and speed. shown(options) is the run named as a view drawn with those
    SceneOptions draws it (sim.project, cached per options); `at` the frame shown.

    `name`: the scenario to start on (None: `happy`; `a+b` combines two and is
    added to the list); `limits`: the simulator's bounds (None: its defaults).
    Raises UnknownScenario for an unknown name."""

    def __init__(self, graph, name: str | None = None, limits=None):
        self.graph = graph
        self.limits = limits or simulator.Limits()
        self.canon = simulator.canonical(graph)
        self.scenarios = simulator.scenarios(self.canon, limits=self.limits)
        names = [sc.name for sc in self.scenarios]
        if name is not None and name not in names:
            try:
                self.scenarios.append(simulator.scenario(self.canon, name, limits=self.limits))
            except KeyError as exc:
                raise UnknownScenario(exc.args[0]) from None
            names.append(name)
        self.index = names.index(name) if name is not None else 0
        self.playing = False
        self.speed = SIM_SPEED
        self.due = 0.0                  # when (monotonic seconds) the next frame shows
        self._run()

    def _run(self) -> None:
        """Simulate the chosen scenario and show its first frame."""
        self.trace = simulator.simulate(self.canon, self.scenarios[self.index],
                                        limits=self.limits)
        self.at = 0
        self._shown = {}                # SceneOptions → the trace projected onto them
        self._beats = self._hops = None  # sim.narrate / sim.hops of the run, when first asked

    @property
    def beats(self) -> tuple:
        """The run in plain words (sim.narrate): a Beat per frame where something
        happens."""
        if self._beats is None:
            self._beats = simulator.narrate(self.trace)
        return self._beats

    @property
    def hops(self) -> tuple:
        """Every hop the run sets out on (sim.hops), for the path."""
        if self._hops is None:
            self._hops = simulator.hops(self.trace)
        return self._hops

    @property
    def scenario(self):
        return self.scenarios[self.index]

    @property
    def last(self) -> int:
        """The index of the run's final frame."""
        return len(self.trace.frames) - 1

    def rebuilt(self, graph) -> "SimPlayer":
        """A player on a re-parsed document keeping this one's scenario (when it
        still exists, else `happy`), position (clamped), play state and speed."""
        try:
            new = SimPlayer(graph, self.scenario.name, self.limits)
        except UnknownScenario:
            new = SimPlayer(graph, None, self.limits)
        new.at = min(self.at, new.last)
        new.playing, new.speed, new.due = self.playing, self.speed, self.due
        return new

    # -- controls (each returns True when the shown frame changed) -------------

    def choose(self, delta: int) -> bool:
        """The previous (-1) / next (+1) scenario, wrapping; its run from the start."""
        self.index = (self.index + delta) % len(self.scenarios)
        self._run()
        return True

    def step(self, delta: int) -> bool:
        """Pause and move `delta` frames, clamped to the run."""
        self.playing = False
        at = max(0, min(self.at + delta, self.last))
        changed, self.at = at != self.at, at
        return changed

    def step_event(self, delta: int) -> bool:
        """Pause and move to the next (+1) / previous (-1) frame where something
        happens (a beat); past the last beat: the final frame, before the first:
        the first frame."""
        self.playing = False
        frames = [b.frame for b in self.beats]
        if delta > 0:
            at = next((k for k in frames if k > self.at), self.last)
        else:
            at = next((k for k in reversed(frames) if k < self.at), 0)
        changed, self.at = at != self.at, at
        return changed

    def toggle(self, now: float) -> bool:
        """Play / pause; playing from the final frame starts the run over."""
        self.playing = not self.playing
        changed = self.playing and self.at == self.last
        if changed:
            self.at = 0
        self.due = now + self.interval
        return changed

    def faster(self, delta: int) -> None:
        """Speed up (+1) / slow down (-1) a step, clamped to SIM_SPEEDS."""
        self.speed = max(0, min(self.speed + delta, len(SIM_SPEEDS) - 1))

    @property
    def fps(self) -> float:
        """The speed: frames a second."""
        return SIM_SPEEDS[self.speed]

    @property
    def interval(self) -> float:
        return 1.0 / SIM_SPEEDS[self.speed]

    def advance(self, now: float) -> bool:
        """Playing and due by `now`: show the next frame (pausing on the last) —
        or a later one when drawing has fallen behind the speed, so a run plays
        in the same time however slow its frames are to draw."""
        if not self.playing or now < self.due:
            return False
        behind = int((now - self.due) / self.interval)   # frames already overdue
        self.at = min(self.at + 1 + behind, self.last)
        self.due = now + self.interval
        self.playing = self.at < self.last
        return True

    def wait(self, now: float) -> float | None:
        """Seconds until the next frame is due (None: paused)."""
        return max(self.due - now, 0.0) if self.playing else None

    # -- what is shown -------------------------------------------------------

    def shown(self, options):
        """The run (a Trace) named as a view drawn with `options`
        (scene.SceneOptions) draws it."""
        if options not in self._shown:
            view = scene.build_scene(self.graph, **options._asdict())
            self._shown[options] = simulator.project(self.trace, view)
        return self._shown[options]

    def choice(self) -> str:
        """`scenario <k>/<n> · <label>` — the chosen scenario among them all."""
        sc = self.scenario
        text = f"scenario {self.index + 1}/{len(self.scenarios)}"
        return text + (f" · {sc.label}" if sc.label else "")

    def status(self) -> str:
        """`sim <scenario> ▶ <speed>/s · t<tick>/<last> · episode <k>: <entry>`,
        then the outcome on the final frame."""
        f = self.trace.frames[self.at]
        mark = "▶" if self.playing else "❚❚"
        text = (f"sim {self.scenario.name} {mark} {speed_text(self.fps)} · "
                f"t{f.tick}/{self.trace.frames[-1].tick}")
        if f.entry is not None:
            text += f" · episode {f.episode}: {self.node_name(f.entry)}"
        return text + (f" · {self.trace.outcome}" if self.at == self.last else "")

    def node_name(self, nid: str) -> str:
        """A node id of the run as the document writes it (`(Shopper)`)."""
        sn = self.canon.nodes.get(nid)
        return kit.node_label(sn.node) if sn is not None else nid

    def log_line(self) -> str:
        """The run's latest log line at the shown frame ("" before any)."""
        return next((f.log[-1] for f in reversed(self.trace.frames[:self.at + 1]) if f.log), "")

    def told(self) -> list:
        """The beats up to the shown frame, oldest first."""
        return [b for b in self.beats if b.frame <= self.at]

    def narration(self) -> str:
        """The latest beat at or before the shown frame, as `tNNN text` ("" before
        any): what is happening, in plain words, while a token travels."""
        told = self.told()
        return beat_line(told[-1]) if told else ""

    def path_branches(self) -> list:
        """The hops the shown frame's episode has taken so far, as branches
        (sim_path): outcomes as far as the shown frame knows them, the hop a
        token is on now marked."""
        f = self.trace.frames[self.at]
        start = next((k for k in range(self.at, -1, -1)
                      if self.trace.frames[k].episode != f.episode), -1) + 1
        return sim_path([h for h in self.hops if start <= h.frame <= self.at],
                        self.node_name, self.at)

    def path(self, mono: bool = True) -> str:
        """The path row's text without its label (path_text): `① (Shopper) -> [API]
        ▸-> [Payments] ×2`; mono: the hop now marked `▸`."""
        return path_text(self.path_branches(), mono)


PATH_ARROW = {"trigger": "⇢", "arm": "◇"}        # hops with no arrow of their own
PATH_MARK = {"failed": "✖", "cancelled": "⊘"}     # how a hop ended
PATH_LABEL = "path   "                           # as wide as the legend's labels
PATH_GAP = "   "                                 # between two branches
PATH_ROWS = 2                                    # the most rows the path takes
PATH_NOW = "▸"                                   # the hop now, where there is no colour


def info_lines(text: str, cols: int, indent: int = 2) -> list[str]:
    """A line of text under a drawing (the summary, a diagnostic) wrapped at
    `cols` between words, each continuation indented `indent`; a ` · ` stays
    with the word after it, a word longer than cols stays whole, and a line
    that fits is kept as it is."""
    if len(text) <= cols:
        return [text]
    lines = textwrap.wrap(text.replace(" · ", " ·\xa0"), cols, subsequent_indent=" " * indent,
                          break_long_words=False, break_on_hyphens=False)
    return [ln.replace("\xa0", " ") for ln in lines] or [text]


def beat_line(beat) -> str:
    """A sim.Beat as one line: `tNNN [API] calls [Payments] with charge(total)`,
    the tick zero-padded as the log pads it."""
    return f"t{beat.tick:03} {beat.text}"


class PathHop(NamedTuple):
    """One hop of the path as written: `-> [Payments] ✖×4` (text) and whether a
    token is on it now (now)."""
    text: str
    now: bool


def branch_number(n: int) -> str:
    """①, ②, … ⑳, then (21), (22), …"""
    return chr(0x245F + n) if 1 <= n <= 20 else f"({n})"


def sim_path(hops: list, name, at: int | None = None) -> list:
    """Hops (sim.Hop, in order) as the path's branches, [(start, [PathHop])]: a
    hop that goes on from where the last one arrived continues the branch
    (`(Shopper) -> [API] -> [Payments]`), any other starts a new one from its
    source; a hop repeated straight after itself (a retry) counts `×N`. A hop
    that failed on arrival is marked `✖` (`✖×4` repeated), one cancelled `⊘` —
    the latest of a repeat's attempts says. at: the frame shown — only outcomes
    reached by then are marked, and a hop whose token is on its wire then is
    `now` (None: every outcome, nothing now). name(node id) -> text."""
    branches, last, prev = [], None, None
    for h in hops:
        end = h.frame if h.end is None else h.end
        outcome = h.outcome if at is None or end <= at else ""
        now = at is not None and h.frame <= at <= end
        if prev is not None and (h.src, h.kind, h.dst) == prev:
            g = branches[-1][1][-1]
            g[1], g[2], g[3] = g[1] + 1, outcome, g[3] or now
            continue
        if h.src != last or not branches:
            branches.append((name(h.src), []))
        branches[-1][1].append([f"{PATH_ARROW.get(h.kind, h.kind)} {name(h.dst)}", 1, outcome, now])
        last, prev = h.dst, (h.src, h.kind, h.dst)
    out = []
    for start, group in branches:
        written = []
        for text, k, outcome, now in group:
            mark = PATH_MARK.get(outcome, "") + (f"×{k}" if k > 1 else "")
            written.append(PathHop(text + (f" {mark}" if mark else ""), now))
        out.append((start, written))
    return out


def path_text(branches: list, mono: bool = True) -> str:
    """The branches (sim_path) on one line: `① (Shopper) -> [API] -> [Payments]
    ✖×4   ② [API] !> <PaymentFailed>`; mono: the hop now marked `▸` (in colour
    it is bold instead, path_rows)."""
    return PATH_GAP.join(
        " ".join([f"{branch_number(i)} {start}"]
                 + [(PATH_NOW if h.now and mono else "") + h.text for h in hs])
        for i, (start, hs) in enumerate(branches, 1))


def path_rows(branches: list, cols: int, hold: bool = False, mono: bool = False) -> list:
    """The path row under the footer as styled rows: `path` and the branches
    (sim_path), wrapped between hops onto at most PATH_ROWS rows (the next under
    the first's text). Longer, the oldest branches fold into `①–③ …` at the start
    (then the newest branch's oldest hops into `④ …`) so the newest stay whole.
    The hop now is bold (mono: marked `▸`). hold: always PATH_ROWS rows, so the
    rows above don't move as the path grows."""
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    num, bold = (kit.GREY["light"], None, False), (kit.GREY["mid"], None, True)
    width = max(cols - len(PATH_LABEL), 1)

    def hop(h):
        return [((PATH_NOW if h.now and mono else "") + h.text, bold if h.now else mid)]

    def words(folded: int, cut: int) -> list:
        """(gap, runs, keep) words, a branch's number and start glued to its first
        hop: the first `folded` branches folded, `cut` hops of the next one left
        out. keep: a branch's width from its first word, to start it on a new row
        rather than split it when it fits there."""
        out = []
        if folded:
            span = branch_number(1) + ("" if folded == 1 else "–" + branch_number(folded))
            out.append(("", [(span + " …", dim)], 0))
        for i, (start, hs) in enumerate(branches[folded:], folded + 1):
            hs = hs[cut if i == folded + 1 else 0:]
            first = [(branch_number(i) + " ", num), ("…" if cut else start, dim if cut else mid)]
            ws = [first + ([(" ", None)] + hop(hs[0]) if hs else [])] + [hop(h) for h in hs[1:]]
            keep = sum(kit.row_len(w) for w in ws) + len(ws) - 1
            out.append((PATH_GAP if out else "", ws[0], keep))
            out += [(" ", w, 0) for w in ws[1:]]
        return out

    def laid(ws):
        rows, x = [[]], 0
        for gap, runs, keep in ws:
            n = kit.row_len(runs)
            if rows[-1] and (x + len(gap) + n > width
                             or x + len(gap) + keep > width >= keep):
                if len(rows) == PATH_ROWS:
                    return None
                rows.append([])
                x = 0
            if rows[-1]:
                rows[-1].append((gap, None))
                x += len(gap)
            if n > width:
                return None
            rows[-1] += runs
            x += n
        return rows

    tries = [(k, 0) for k in range(len(branches))]
    if branches:
        tries += [(len(branches) - 1, j) for j in range(1, len(branches[-1][1]))]
    body = next((r for r in (laid(words(k, j)) for k, j in tries) if r is not None), None)
    if body is None:                     # one hop wider than a row: its end, cut
        k, j = tries[-1]
        line = [run for gap, runs, _keep in words(k, j) for run in [(gap, None)] + runs]
        over = kit.row_len(line) - width + 2
        body = [[("… ", dim)] + kit.clip(line, over, width - 2)]
    body = body or [[]]
    rows = [[(PATH_LABEL, dim)] + body[0]]
    rows += [[(" " * len(PATH_LABEL), None)] + r for r in body[1:]]
    if hold:
        rows += [[("  ", None)] for _k in range(PATH_ROWS - len(rows))]
    return rows


def sim_report(player: SimPlayer, cols: int = LEGEND_WIDTH, colour: bool = False) -> list[str]:
    """The text --once --sim prints under the drawing: the scenario, its outcome
    and length, the run's path at the shown frame (path_rows, as the live view's
    row under its footer: the hop now bold, or `▸` without colour), the
    simulator's reading conventions, then the run in plain words — one `tNNN …`
    line per beat (sim.narrate). The raw log is in --json."""
    sc, trace = player.scenario, player.trace
    head = f"sim {sc.name}" + (f" ({sc.label})" if sc.label else "")
    head += f": {trace.outcome} · {len(trace.frames)} frames"
    path = [kit.ansi(r, colour).rstrip()
            for r in path_rows(player.path_branches(), cols, mono=not colour)]
    conventions = simulator.Beat(0, 0, simulator.CONVENTIONS)
    return (info_lines(head, cols) + path + [beat_line(conventions)]
            + [beat_line(b) for b in player.beats])


def sim_run(player: SimPlayer, limits=None) -> dict:
    """One run as --sim NAME --json prints it: its facts (sim_facts), then
    "steps" — the run in plain words, [{frame, tick, text}] (sim.narrate) — and
    "log", the simulator's own log lines."""
    out = sim_facts(player.trace, limits)
    out["steps"] = [b._asdict() for b in player.beats]
    out["log"] = list(player.trace.end["log"])
    return out


# -- every scenario at once (--sim list / --sim all): text an agent reads and
#    diffs between two versions of a design. Running is the edge (run_all); the
#    facts and the table are pure. No scenario is named `list` or `all`: sim.py
#    names a deviation after its choice point, always with punctuation
#    (`API.charge:fails`, `Risk?>Review`, `Order.Open-Paid->Settled`). --------

SIM_BATCH = ("list", "all")
SIM_WIDTH = 100                                 # the table's columns
SIM_NAME = 24                                   # the name column (a longer name pushes)
SIM_FACTS = ("states", "failed", "routes", "ignored", "waiting", "open", "bounds")


def run_all(graph, limits=None) -> list:
    """[Trace]: every scenario of the document (sim.scenarios), each run once,
    keeping only its final frame (sim_facts reads the rest from `end`)."""
    limits = limits or simulator.Limits()
    canon = simulator.canonical(graph)
    return [simulator.simulate(canon, sc, limits=limits, keep=False)
            for sc in simulator.scenarios(canon, limits=limits)]


def _state_text(scn, nid) -> str:
    """A machine state as a transition writes it (`Open`, `+`, `$`)."""
    sn = scn.nodes.get(nid)
    if sn is None:
        return str(nid)
    return {"start": "+", "end": "$", "any": "_"}.get(sn.node.attrs.get("pseudo"), sn.node.name)


def sim_facts(trace, limits=None) -> dict:
    """What one run did, as an agent judges it: the scenario's name and label, its
    outcome and length, then each fact (SIM_FACTS, lists of text, written order,
    no repeats) — `states` each machine's end state, `failed` what failed (a node,
    or a call `A -> B`, `↩ fallback` / `critical`), `routes` the failure routes
    taken, `ignored` events a machine's state had no transition for, `waiting`
    nodes still blocked at the end, `open` `&` joins left open, `bounds` every
    simulator bound hit (base case, visit limit, spawn cap, a loop capped or run
    at the cap with no `@times`, a cut)."""
    limits = limits or simulator.Limits()
    scn, end, sc = trace.scene, trace.end, trace.scenario
    name = lambda nid: kit.node_label(scn.nodes[nid].node) if nid in scn.nodes else str(nid)
    wires = {w.ident: w for w in scn.wires}
    wire = lambda ident: (f"{name(wires[ident].src)} {wires[ident].kind} "
                          f"{name(wires[ident].dst)}" if ident in wires else str(ident))
    facts = {k: [] for k in SIM_FACTS}
    facts["states"] = [f"{name(o)} {_state_text(scn, s)}" for o, s in end["machines"].items()]
    for ev in end["events"]:
        kind = ev["kind"]
        if kind == "fail":
            what, at = ev["origin"]
            text = name(at) if what == "node" else wire(at)
            text += " ↩ fallback" if ev.get("fallback") else " critical" if ev.get("critical") else ""
            facts["failed"].append(text)
        elif kind == "route":
            facts["routes"].append(wire(ev["wire"]))
        elif kind == "ignored":
            facts["ignored"].append(f"{name(ev['event'])} in {name(ev['owner'])} "
                                    f"{_state_text(scn, ev['state'])}")
        elif kind == "limit":
            facts["bounds"].append(_bound_text(ev, name, scn))
    facts["bounds"] += _capped_loops(trace, limits, name)
    facts["waiting"] = [name(n) for n in end["stalled"]]
    facts["open"] = [f"{name(d['target'])} missing "
                     + ", ".join(name(m) for m in d["missing"]) for d in end["deposits"]]
    facts = {k: list(dict.fromkeys(v)) for k, v in facts.items()}
    return {"name": sc.name, "label": sc.label, "outcome": trace.outcome,
            "frames": trace.frames[-1].tick + 1, **facts}


_BOUND_TEXT = {"depth": "base case", "visits": "visit limit", "spawns": "spawn cap",
               "iterations": "loop capped"}


def _block_ref(scn, owner, index):
    """The scene.BlockRef of a unit's block (None: not in this scene)."""
    return next((b for b in scn.blocks if b.owner == owner and b.index == index), None)


def _block_line(scn, owner, index) -> int:
    ref = _block_ref(scn, owner, index)
    return ref.block.lines[0] if ref is not None and ref.block.lines else 0


def _bound_text(ev: dict, name, scn) -> str:
    """A `limit` event as a bound: `base case at [Walker]`, `cut: frames limit`."""
    what = ev["name"]
    if what not in _BOUND_TEXT:
        return f"cut: {what} limit"
    if what == "iterations":
        return f"loop capped at line {_block_line(scn, ev['node'], ev.get('block'))}"
    return f"{_BOUND_TEXT[what]} at {name(ev['node'])}" if ev.get("node") else _BOUND_TEXT[what]


def _capped_loops(trace, limits, name) -> list:
    """Loops with no `@times` that ran the simulator's cap of iterations (the
    design says nothing about when they stop)."""
    most = trace.end["loops"]
    out = []
    for (owner, index), k in most.items():
        ref = _block_ref(trace.scene, owner, index)
        if ref is None or any(n == "times" for n, _a in ref.block.modifiers):
            continue
        if k >= limits.iterations:
            out.append(f"loop at line {_block_line(trace.scene, owner, index)} "
                       f"ran {k}/{limits.iterations} (the cap, no @times)")
    return out


def _fit(head: str, tail: str, width: int) -> list[str]:
    """head + tail on one line when it fits in width, else tail on an indented
    line of its own."""
    if not tail:
        return [head.rstrip()]
    if len(head) + len(tail) <= width:
        return [head + tail]
    return [head.rstrip(), "    " + tail]


def sim_list(scenarios, width: int = SIM_WIDTH) -> list[str]:
    """--sim list: one line per scenario, its name then its label."""
    pad = min(max((len(sc.name) for sc in scenarios), default=0), 32) + 2
    return [ln for sc in scenarios for ln in _fit(f"{sc.name:<{pad}}", sc.label, width)]


def sim_table(facts: list, width: int = SIM_WIDTH) -> list[str]:
    """--sim all: per scenario a line `name  outcome  N frames  label` (the label
    on a line of its own when it doesn't fit), then an indented line per fact it
    has (`  failed: …`, wrapped at width); then a summary line. Columns are
    fixed (SIM_NAME), never fitted to the other runs, so a diff between two
    versions of a design shows only the runs that changed."""
    out = []
    for f in facts:
        head = f"{f['name']:<{SIM_NAME}} {f['outcome']:<6} {f['frames']:>4} frames  "
        out += _fit(head, f["label"], width)
        out += [ln for k in SIM_FACTS if f[k] for ln in _fact_lines(k, f[k], width)]
    return out + [sim_summary(facts)]


def _fact_lines(key: str, items: list, width: int) -> list[str]:
    """`  key: a · b · c`, wrapped between items (never inside one) at width."""
    lines, line = [], f"  {key}: {items[0]}"
    for item in items[1:]:
        if len(line) + 3 + len(item) > width:
            lines.append(line)
            line = "      " + item
        else:
            line += " · " + item
    return lines + [line]


def sim_summary(facts: list) -> str:
    """`N scenarios: a ok, b failed, c cut`."""
    n = {o: sum(f["outcome"] == o for f in facts) for o in ("ok", "failed", "cut")}
    return (f"{len(facts)} scenario{'s' if len(facts) != 1 else ''}: "
            f"{n['ok']} ok, {n['failed']} failed, {n['cut']} cut")


def sim_batch(path: Path, mode: str, dialect=None, as_json: bool = False,
              limits=None) -> int:
    """--sim list | all: print the scenarios (list) or every run's facts (all),
    as text or JSON; no drawing, no lint. Exit status 0: a run is information,
    not a verdict. `limits`: the simulator's bounds (None: its defaults)."""
    kit.use_dialect(dialect)
    g = kit._call(kit.render.parse_document, path.read_text(), dialect)
    if mode == "list":
        found = simulator.scenarios(simulator.canonical(g), limits=limits or simulator.Limits())
        text = (json.dumps([{"name": sc.name, "label": sc.label} for sc in found], indent=2,
                           ensure_ascii=False) if as_json else "\n".join(sim_list(found)))
    else:
        facts = [sim_facts(t, limits) for t in run_all(g, limits)]
        text = (json.dumps({"scenarios": facts, "summary": sim_summary(facts)}, indent=2,
                           ensure_ascii=False) if as_json else "\n".join(sim_table(facts)))
    print(text)
    return 0


def sim_json(path: Path, name: str, dialect=None, limits=None) -> int:
    """--sim NAME --json: print one run (sim_run) as JSON; no drawing, no lint.
    Exit status 0; raises UnknownScenario for an unknown name."""
    kit.use_dialect(dialect)
    g = kit._call(kit.render.parse_document, path.read_text(), dialect)
    player = SimPlayer(g, name, limits)
    print(json.dumps(sim_run(player, limits), indent=2, ensure_ascii=False))
    return 0


def run_json(path: Path, name: str | None, dialect=None, limits=None,
             unroll: int | None = None) -> int:
    """--run --json [--sim NAME]: print the run's timeline (view_run.timeline_json:
    lanes with their labels, spans, moves, marks) as JSON — the scenario's run,
    else the happy one; no drawing, no lint. Exit status 0; raises
    UnknownScenario for an unknown name."""
    kit.use_dialect(dialect)
    g = kit._call(kit.render.parse_document, path.read_text(), dialect)
    player = SimPlayer(g, name, limits)
    data = vrun.timeline_json(player.trace, player.limits, unroll)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# Checks — check.py's findings on one document, mapped onto the Scene a view
# draws (kit.CheckMarks; the views mark them) and listed in a panel. Running
# the checker is the edge (run_checks); the rest is pure.
# ---------------------------------------------------------------------------

CHECK_ROWS = 10                                 # live panel rows (with its summary row)


class ChecksUnavailable(RuntimeError):
    """The checker can't run here (no check.py beside view.py)."""


def run_checks(text: str, dialect=None):
    """check.py's Report on `text` in its document mode. Raises ChecksUnavailable
    without check.py; the checker's own errors pass through."""
    if not (_HERE / "check.py").exists():
        raise ChecksUnavailable("checks need check.py next to view.py")
    return _sibling("sigil_check", "check.py").check(text, dialect=dialect)


def checks_summary(report) -> str:
    """check.py's one-line summary of a Report."""
    return _sibling("sigil_check", "check.py").summary(report)


class CheckEntry(NamedTuple):
    """A finding as the overlay lists and marks it."""
    mark: object                                # kit.CheckMark
    finding: object                             # check.Finding


def check_entries(report) -> list:
    """[CheckEntry]: the findings the report shows, then the acknowledged ones,
    numbered from 1 in that order (check.py's own output order)."""
    found = [(f, False) for f in report.shown] + [(f, True) for f in report.acknowledged]
    return [CheckEntry(kit.CheckMark(n, f.severity, acked), f)
            for n, (f, acked) in enumerate(found, 1)]


def _line_of(at) -> int:
    try:
        return int(at)
    except (TypeError, ValueError):
        return 0


def finding_targets(anchor: tuple, view, idmap: dict, hosts: dict) -> tuple:
    """(node ids, wire idents) of `view` (a Scene) that a finding's anchor names.
    `idmap` / `hosts`: sim.ident_map / sim.host_map from the canonical Scene
    (the checker's) to `view`. A node: the drawn node standing for it, or the
    wires a landed event rides; a machine: its owner; a wire: the view's wires
    for it; a line (or an acknowledgement's comment): the wires written on it;
    anything else (a block, the document, a limit): nothing."""
    kind, at = anchor
    if kind in ("node", "machine"):
        host = hosts.get(at, at if at in view.nodes else None)
        if host is not None:
            return {host}, set()
        return set(), {w.ident for w in view.wires if w.via == at}
    if kind == "wire":
        return set(), {v for v, _off, _scale in idmap.get(tuple(at), ())}
    if kind in ("line", "comment"):
        line = _line_of(at)
        return set(), {w.ident for w in view.wires if line and w.line == line}
    return set(), set()


def check_marks(entries: list, canon, view):
    """kit.CheckMarks: every entry's mark on what its anchor names in `view`
    (finding_targets), from the canonical Scene `canon`."""
    idmap = simulator.ident_map(canon, view)
    hosts = simulator.host_map(canon, view)
    nodes, wires = {}, {}
    for e in entries:
        ns, ws = finding_targets(e.finding.hit.anchor, view, idmap, hosts)
        for nid in sorted(ns):
            nodes.setdefault(nid, []).append(e.mark)
        for ident in sorted(ws):
            wires.setdefault(ident, []).append(e.mark)
    return kit.CheckMarks({k: tuple(v) for k, v in nodes.items()},
                          {k: tuple(v) for k, v in wires.items()})


def finding_question(f) -> str:
    """What the panel says of a finding: the question it asks (its craft-mode
    message, with what it guessed and the findings folded into it), or
    `accepted: <reason>` for an acknowledged one."""
    if f.ack is not None:
        return f"accepted: {f.ack.reason}"
    return replace(f, mode="craft").message


def entry_rows(e: CheckEntry, cols: int) -> list:
    """An entry's panel rows: `▲1 12:rule-name the question…`, wrapped to `cols`
    under its text; the glyph in its finding's style, the text dimmed when
    acknowledged."""
    glyph = kit.check_glyph(e.mark)
    f = e.finding
    text = f"{glyph} {f.line}:{f.rule.name} {finding_question(f)}"
    lines = textwrap.wrap(text, width=max(cols, len(glyph) + 12), break_long_words=False,
                          subsequent_indent=" " * (len(glyph) + 1)) or [glyph]
    body = (kit.GREY["dim"] if e.mark.acked else kit.GREY["light"], None, False)
    return ([[(glyph, kit.check_mark_style(e.mark)), (lines[0][len(glyph):], body)]]
            + [[(ln, body)] for ln in lines[1:]])


def checks_panel(summary: str, entries: list, cols: int, limit: int | None = None) -> list:
    """The findings panel: check.py's summary, then each entry's rows
    (entry_rows); at most `limit` rows (None: all), the last then saying how
    many entries are left out."""
    rows = [[(summary, (kit.GREY["mid"], None, False))]]
    for k, e in enumerate(entries):
        more = entry_rows(e, cols)
        if limit is not None and len(rows) + len(more) > limit - (k < len(entries) - 1):
            rows.append([(f"… {len(entries) - k} more (check.py)", (kit.GREY["mid"], None, False))])
            break
        rows += more
    return rows


def checks_legend() -> list:
    """The legend row of the checks overlay's marks, one row for every view."""
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    error, warn = kit.CheckMark(0, "error"), kit.CheckMark(0, "warn")
    acked = kit.CheckMark(0, "warn", True)
    return [("checks ", dim),
            (kit.CHECK_GLYPH["error"] + "N", kit.check_mark_style(error)), (" error  ", mid),
            (kit.CHECK_GLYPH["warn"] + "N", kit.check_mark_style(warn)), (" warning  ", mid),
            (kit.CHECK_GLYPH["info"] + "N", kit.check_mark_style(kit.CheckMark(0, "info"))),
            (" info  ", mid),
            (kit.ACKED_GLYPH + "N", kit.check_mark_style(acked)), (" acknowledged (dimmed)  ", mid),
            ("─", kit.check_mark_style(warn)), (" a marked wire / box  ", mid),
            ("N", mid), (" the finding's number in the checks list", mid)]


class ChecksOverlay:
    """One document's findings for the overlay: its Report, the numbered
    entries, and their marks named as each view's Scene names things (marks(),
    cached per scene.SceneOptions, like SimPlayer.shown). `summary`: the
    panel's first row (checks_summary)."""

    def __init__(self, graph, report, summary: str):
        self.graph = graph
        self.report = report
        self.summary = summary
        self.entries = check_entries(report)
        self._canon = None
        self._marks = {}

    def marks(self, options):
        """kit.CheckMarks for a view drawn with `options` (scene.SceneOptions)."""
        if options not in self._marks:
            if self._canon is None:
                self._canon = simulator.canonical(self.graph)
            view = scene.build_scene(self.graph, **options._asdict())
            self._marks[options] = check_marks(self.entries, self._canon, view)
        return self._marks[options]

    def run_marks(self):
        """kit.CheckMarks named as the canonical scene names things — what the
        run view draws (its lanes are the run's nodes)."""
        if "run" not in self._marks:
            if self._canon is None:
                self._canon = simulator.canonical(self.graph)
            self._marks["run"] = check_marks(self.entries, self._canon, self._canon)
        return self._marks["run"]

    def panel(self, cols: int, limit: int | None = None) -> list:
        return checks_panel(self.summary, self.entries, cols, limit)


# ---------------------------------------------------------------------------
# --once
# ---------------------------------------------------------------------------

def run_notes_of(notes: str) -> str:
    """The run view's notes (RUN_NOTES) for a --notes mode: off (the default)
    the run's notes, markers or callouts the design's notes on each lane's node."""
    return "run" if notes == "off" else "design"


def compose_view(g, view, *, depth: int, payloads: bool, notes: str, triggers: bool,
                 spaced: bool, width: int | None, access: bool, mods: bool, events: str,
                 trace=None, tick: int = 0, checks=None, limits=None, unroll=None,
                 run_notes: str | None = None):
    """(rows, width): the drawing of `g` in a view — a name in VIEWS, or a bool
    as the old tree flag (view_name) — see compose / compose_flow /
    compose_tree / compose_run. `trace`, `tick`: a simulation run drawn over it at
    frame `tick`, named as this view's scene names it (SimPlayer.shown — the same
    Trace object for every frame, so the graph view's per-trace badge slots are
    worked out once), or None. `checks`: the checks overlay's kit.CheckMarks,
    named as this view's scene names things (ChecksOverlay.marks; the run view:
    ChecksOverlay.run_marks), or None. The run view draws `trace` as a timeline
    (None: the happy run, said so; `limits` its bounds), its notes `run_notes`
    (a RUN_NOTES mode; None: run_notes_of(notes)), `unroll` the instances it
    shows before folding (None: sim.RUN_SHOW, 0: all)."""
    view = view_name(view)
    if view == "run":
        return vrun.compose_run(g, trace, tick if trace is not None else None, width,
                                run_notes or run_notes_of(notes), checks, unroll, limits,
                                trace is not None)
    if view == "tree":
        return vtree.compose_tree(g, depth, triggers, spaced, notes, payloads, width, access,
                                  mods, events, trace=trace, tick=tick, checks=checks)
    if view == "flow":
        return vflow.compose_flow(g, depth, payloads, notes, triggers, width, access, mods,
                                  events, trace=trace, tick=tick, checks=checks)
    return vgraph.compose(g, depth, payloads, notes, triggers, width, access, mods, events,
                          trace=trace, tick=tick, checks=checks)


def sim_focus(g, view, *, depth: int, payloads: bool, notes: str, triggers: bool,
              spaced: bool, width: int | None, access: bool, mods: bool, events: str,
              trace, tick: int, limits=None, unroll=None, run_notes: str | None = None):
    """(x, y, w, h): the cells of compose_view's rows (same arguments) where frame
    `tick` of `trace` acts — its tokens and the nodes it has active — in any
    view; None when the frame has nothing drawn in motion. Draws the frame once
    more with those in kit.Probe styles and reads them back (kit.probed_box)."""
    view = view_name(view)
    if view == "graph":
        return vgraph.sim_focus(g, depth, payloads, notes, triggers, width, access, mods,
                                events, trace=trace, tick=tick)
    if view == "run":
        rows, _w = vrun.compose_run(g, trace, tick, width, run_notes or run_notes_of(notes),
                                    show=unroll, limits=limits, probe=True)
    elif view == "tree":
        rows, _w = vtree.compose_tree(g, depth, triggers, spaced, notes, payloads, width,
                                      access, mods, events, trace=trace, tick=tick, probe=True)
    else:
        rows, _w = vflow.compose_flow(g, depth, payloads, notes, triggers, width, access, mods,
                                      events, trace=trace, tick=tick, probe=True)
    return kit.probed_box(rows)


def once(path: Path, depth: int, payloads: bool, do_lint: bool,
         dialect=None, colour: bool = False, tree: bool = False,
         triggers: bool = True, spaced: bool = True, notes: str = "off",
         width: int | None = None, access: bool = False, mods: bool = False,
         events: str | None = None, sim: str | None = None, checks: bool = False,
         limits=None, view: str | None = None, unroll: int | None = None) -> int:
    """Print the drawing once, in `view` (a name in VIEWS; None: start_view —
    the tree view when `tree`, else DEFAULT_VIEW). The run view draws `sim`'s run as a
    timeline, or the happy run when no scenario is given (`unroll`: the
    instances it shows before folding; None: sim.RUN_SHOW, 0: all). `width`: the columns to fit it to (None: its
    natural width); the legend wraps at the narrower of that and LEGEND_WIDTH.
    `events`: "land" | "nodes" (None: the view's default, DEFAULT_EVENTS).
    `sim`: a scenario name — the run's final frame is drawn over the view and its
    legend, outcome and log printed after the summary (raises UnknownScenario
    for an unknown one). `checks`: the checks overlay over the drawing, its
    legend, and the findings panel after lint (the checker failing: why, in
    its place; the exit status stays lint's).
    The summary line ends with the document's `#!mode`, when it has one."""
    kit.use_dialect(dialect)
    text = path.read_text()
    g = kit._call(kit.render.parse_document, text, dialect)
    view = start_view(view, tree)
    tree = view == "tree"
    events = events or DEFAULT_EVENTS[view]
    options = scene.SceneOptions(events, triggers, access, depth)
    player = shown = None
    if sim is not None:
        player = SimPlayer(g, sim, limits)
        player.at = player.last
        shown = player.shown(options)
    overlay = check_failed = None
    if checks:
        try:
            report = run_checks(text, dialect)
            overlay = ChecksOverlay(g, report, checks_summary(report))
        except Exception as exc:       # the drawing still prints
            check_failed = f"checks failed: {type(exc).__name__}: {exc}"
    run = view == "run"
    marks = None
    if overlay is not None:
        marks = overlay.run_marks() if run else overlay.marks(options)
    rows, _w = compose_view(g, view, depth=depth, payloads=payloads, notes=notes,
                            triggers=triggers, spaced=spaced, width=width, access=access,
                            mods=mods, events=events, trace=shown,
                            tick=player.at if player else 0, checks=marks, limits=limits,
                            unroll=unroll)
    out = [kit.ansi(r, colour) for r in rows]
    if tree:
        legend = vtree.tree_legend(triggers, payloads, access, mods, events,
                                   calls=drawn_call_marks(g, depth, payloads))
    elif run:
        legend = [vrun.run_legend()]
    else:
        legend = []
    if player is not None:
        legend += [path_legend()] if run else [sim_legend(tree), path_legend()]
    legend += [checks_legend()] if overlay is not None else []
    legend_w = LEGEND_WIDTH if width is None else min(LEGEND_WIDTH, width)
    if legend:
        out += [""] + [kit.ansi(ln, colour) for r in legend for ln in wrap_legend(r, legend_w)]
    out.append("")
    mode = kit.doc_mode(text)
    out += info_lines(f"{path.name}: {len(g.nodes)} nodes, {len(g.edges)} edges, "
                      f"{len(g.expansions)} expansions" + (f" · {mode}" if mode else ""), legend_w)
    status = 0
    if do_lint:
        diags = kit.run_lint(text, dialect)
        if diags:
            out.extend(ln for d in diags for ln in info_lines(d.format(), legend_w))
        else:
            out.append("lint: OK")
        status = 1 if any(d.severity == "error" for d in diags) else 0
    if overlay is not None:
        out += [""] + [kit.ansi(r, colour) for r in overlay.panel(legend_w)]
    elif check_failed:
        out += [""] + info_lines(check_failed, legend_w)
    if player is not None:
        out += [""] + sim_report(player, legend_w, colour)
    print("\n".join(out))
    return status


# ---------------------------------------------------------------------------
# Live view — ViewState is the whole app minus the terminal (tests drive it);
# tui() is the stdlib alternate-screen loop around it.
# ---------------------------------------------------------------------------

DEPTHS = (0, 1, kit.ALL_DEPTH)
LINT_ROWS = 8
SCROLL_X = 4                                    # columns per left / right key / wheel notch
WHEEL_Y = 3                                     # rows per wheel notch
POLL_S = 0.3                                    # how often to stat the file
TICK_S = 0.1                                    # key wait per loop turn
READ_BYTES = 1024                               # bytes per input read (mouse drags are chatty)
MOUSE_ON = "\x1b[?1002h\x1b[?1006h"            # report button drags + wheel, SGR encoded
MOUSE_OFF = "\x1b[?1006l\x1b[?1002l"


# -- placing the drawing in the viewport: one axis at a time. An origin is the
#    drawing cell at the viewport's first cell; negative = blank lead-in. --------

def home_origin(size: int, view: int) -> int:
    """Where a drawing opens: centred while it fits, else at its start."""
    return -((view - size) // 2) if size <= view else 0


def centre_origin(size: int, view: int) -> int:
    """The drawing's middle on the viewport's middle."""
    return home_origin(size, view) if size <= view else (size - view) // 2


def pan_bounds(size: int, view: int, fit: bool) -> tuple[int, int]:
    """(lowest, highest) origin. Fitted: pinned centred while the drawing fits,
    else scrolled within it. Natural (free pan): anywhere that keeps at least half
    the viewport (or all of a smaller drawing) on screen."""
    if fit:
        if size <= view:
            return (home_origin(size, view),) * 2
        return 0, size - view
    keep = min(size, max(view // 2, 1))
    return keep - view, size - keep


def place(size: int, view: int, origin: int, fit: bool, request: str | None) -> int:
    """The origin to draw at: `request` ("home" | "centre" | None: keep `origin`),
    clamped to pan_bounds."""
    if request == "home":
        origin = home_origin(size, view)
    elif request == "centre":
        origin = centre_origin(size, view)
    lo, hi = pan_bounds(size, view, fit)
    return max(lo, min(origin, hi))


def wheel_step(code: int) -> tuple[int, int]:
    """(dx, dy) of a wheel notch from its SGR button code: up / down scroll rows,
    a sideways wheel or shift+wheel scrolls columns."""
    sign = -1 if code & 1 == 0 else 1          # 64 up / 66 left: back; 65 / 67: on
    if code & 2 or code & 4:
        return sign * SCROLL_X, 0
    return 0, sign * WHEEL_Y


class ViewState:
    def __init__(self, path: Path, depth: int = 1, payloads: bool = False,
                 do_lint: bool = True, dialect=None, tree: bool = False,
                 triggers: bool = True, spaced: bool = True, notes: str = "off",
                 access: bool = False, mods: bool = False, events: str | None = None,
                 sim: str | None = None, checks: bool = False, limits=None,
                 view: str | None = None, unroll: int | None = None):
        """`view`: the view to start in (a name in VIEWS; None: start_view — the
        tree view when `tree`, else DEFAULT_VIEW). `unroll`: the run view's instances shown
        before folding (None: sim.RUN_SHOW; 0: all; key u). `events`: the events mode every view starts
        in (None: each view's default, DEFAULT_EVENTS); each view then keeps its
        own (key v). `sim`: a
        scenario to start in sim mode on (None: sim mode off until x).
        `checks`: start with the checks overlay on (key c)."""
        self.path = path
        self.limits = limits                   # the simulator's bounds (None: defaults)
        self.show_access = access
        self.show_mods = mods
        self.mode = ""
        self.view = start_view(view, tree)
        self.events = events_by_view(events)   # {view: "land" | "nodes"}
        self.notes = notes
        self.run_notes = run_notes_of(notes)   # the run view's own (n there): RUN_NOTES
        self.unroll = RUN_UNROLL[0] if unroll is None else unroll
        self.show_triggers = triggers
        self.spaced = spaced
        self.depth = depth
        self.payloads = payloads
        self.show_lint = do_lint
        self.dialect = dialect
        kit.use_dialect(dialect)
        self.stamp = None
        self.text = None
        self.graph = None
        self.error = None
        self.diags = []
        self.updated = ""
        self.title = ""
        self.fit = True                # f: fitted to the window, else natural + free pan
        self.sx = self.sy = 0          # the origin: drawing cell at the viewport's top-left
        self._place = "home"           # a pending "home" / "centre", resolved by frame()
        self._drag = None              # (x, y, sx, sy) where a mouse drag started
        self._vh = 1                   # viewport height of the last frame (a page)
        self._natural = None           # (rows, width): the drawing at its natural width
        self._fit = None               # (cols, rows, width): the drawing fitted to cols
        self.sim_on = sim is not None  # x: the run drawn over the view
        self.player = None             # SimPlayer, made on the first sim mode with a graph
        self.sim_error = None          # why the simulator could not run (a footer row)
        self._sim_name = sim           # the scenario that player starts on
        self.follow = True             # w: pan to keep the run's focus in view
        self._followed = None          # what the last follow panned for (see _follow)
        self.show_checks = checks      # c: the checks overlay and its panel
        self.checks = None             # ChecksOverlay of the current text (made while on)
        self.check_error = None        # why the checker could not run (a footer row)

    @property
    def tree(self) -> bool:
        """Whether the tree view is shown (setting it: the tree, else the graph)."""
        return self.view == "tree"

    @tree.setter
    def tree(self, on: bool) -> None:
        self.view = view_name(bool(on))

    @property
    def events_mode(self) -> str:
        """The active view's events mode."""
        return self.events[self.view]

    # -- model ---------------------------------------------------------------

    def reload(self, force: bool = False) -> bool:
        """Re-read the file if it changed. Returns True when the view changed."""
        try:
            st = self.path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            return False               # mid-save rename or deleted: keep the last view
        if stamp == self.stamp and not force:
            return False
        self.stamp = stamp
        try:
            text = self.path.read_text()
        except OSError:
            return False
        self.text = text
        self.title = kit.doc_title(text)
        self.mode = kit.doc_mode(text)
        try:
            self.graph = kit._call(kit.render.parse_document, text, self.dialect)
            self.error = None
        except Exception as exc:       # keep the last good graph on screen
            self.error = f"parse failed: {type(exc).__name__}: {exc}"
        self.diags = kit.run_lint(text, self.dialect)
        self.checks = None             # re-checked when next shown
        self.updated = time.strftime("%H:%M:%S")
        if self.error is None and self.player is not None:
            self.player = self._sim(self.player.rebuilt, self.graph)
        self._recompose()
        return True

    def _sim(self, make, *args):
        """make(*args) — a SimPlayer — or None with sim_error saying why not (the
        live view keeps running when the simulator can't). UnknownScenario passes
        through for the caller to handle."""
        try:
            player = make(*args)
        except UnknownScenario:
            raise
        except Exception as exc:
            self.sim_error = f"sim failed: {type(exc).__name__}: {exc}"
            return None
        self.sim_error = None
        return player

    def _ensure_player(self) -> None:
        """Sim mode with a graph and no player yet: make one on the requested
        scenario (an unknown name: the error shown, `happy` played)."""
        if not self.sim_on or self.player is not None or self.graph is None:
            return
        name, self._sim_name = self._sim_name, None
        try:
            self.player = self._sim(SimPlayer, self.graph, name, self.limits)
        except UnknownScenario as exc:  # say so, play `happy`
            self.player = self._sim(SimPlayer, self.graph, None, self.limits)
            self.sim_error = f"sim: {exc}"

    def _ensure_checks(self) -> None:
        """Checks on with a graph and no findings yet: run the checker on the
        current text (it failing: check_error says why, the view runs on)."""
        if not self.show_checks or self.checks is not None or self.graph is None:
            return
        try:
            report = run_checks(self.text, self.dialect)
            self.checks = ChecksOverlay(self.graph, report, checks_summary(report))
            self.check_error = None
        except Exception as exc:
            self.check_error = f"checks failed: {type(exc).__name__}: {exc}"

    def check_marks(self):
        """The checks overlay as the active view draws it (kit.CheckMarks), or
        None: the overlay is off or has no findings to mark."""
        if not self.show_checks or self.checks is None:
            return None
        if self.view == "run":
            return self.checks.run_marks()
        return self.checks.marks(self._scene_options())

    def _scene_options(self):
        """The SceneOptions the active view is drawn with."""
        return scene.SceneOptions(self.events_mode, self.show_triggers, self.show_access,
                                  self.depth)

    def sim_trace(self):
        """The run named as the active view draws it (None: sim mode is off or
        has no run); the frame shown is self.player.at."""
        if not self.sim_on or self.player is None:
            return None
        return self.player.shown(self._scene_options())

    def _recompose(self):
        """Something drawn changed: drop the composed drawings (frame() composes
        the one it shows, natural or fitted, when it needs it)."""
        self._ensure_player()
        self._ensure_checks()
        self._fit = None
        self._natural = None

    def natural(self):
        """(rows, width): the drawing at its natural width; cached until the view
        changes."""
        if self._natural is None:
            self._natural = self._compose(None)
        return self._natural

    @property
    def _rows(self):
        return self.natural()[0]

    @property
    def _width(self) -> int:
        return self.natural()[1]

    def _compose(self, width: int | None):
        if self.graph is None:
            return [], 0
        return compose_view(self.graph, self.view, depth=self.depth, payloads=self.payloads,
                            notes=self.notes, run_notes=self.run_notes,
                            triggers=self.show_triggers, spaced=self.spaced,
                            width=width, access=self.show_access, mods=self.show_mods,
                            events=self.events_mode, trace=self.sim_trace(),
                            tick=self.player.at if self.player else 0,
                            checks=self.check_marks(), limits=self.limits, unroll=self.unroll)

    def fitted(self, cols: int):
        """(rows, width): the drawing rearranged to fit `cols` columns when it can
        be (see compose / compose_tree); cached until the view or the size changes."""
        if self._fit is None or self._fit[0] != cols:
            self._fit = (cols, *self._compose(cols))
        return self._fit[1], self._fit[2]

    # -- keys ----------------------------------------------------------------

    def key(self, k: str, page: int | None = None, now: float = 0.0) -> bool:
        """Apply a key. Returns True when the view changed. Paging moves by
        `page` rows (default: the last frame's viewport height). `now`: the
        monotonic clock, for play (sim mode's keys take precedence)."""
        page = self._vh if page is None else page
        if self.sim_on and self.player is not None and k in SIM_KEY_NAMES:
            return self._sim_key(k, now)
        if k == "x":                   # off pauses the run: it resumes paused where it was
            self.sim_on = not self.sim_on
            if self.player is not None:
                self.player.playing = False
            self._recompose()
        elif k == "c":
            self.show_checks = not self.show_checks
            self._recompose()
        elif k == "d":                 # the next larger depth, wrapping to the first
            self.depth = next((d for d in DEPTHS if d > self.depth), DEPTHS[0])
            self._recompose()
        elif k == "t" or (k.isdigit() and 1 <= int(k) <= len(VIEWS)):
            # t: the next view; a digit: that view (1 the first in VIEWS)
            at = VIEWS.index(self.view)
            to = VIEWS[(at + 1) % len(VIEWS)] if k == "t" else VIEWS[int(k) - 1]
            if to == self.view:
                return False
            self.view = to
            self._place = "home"
            self._recompose()
        elif k == "n" and self.view == "run":   # the run view's notes: run → design → off
            self.run_notes = RUN_NOTES[(RUN_NOTES.index(self.run_notes) + 1) % len(RUN_NOTES)]
            self._recompose()
        elif k == "n":
            self.notes = NOTE_MODES[(NOTE_MODES.index(self.notes) + 1) % len(NOTE_MODES)]
            self._recompose()
        elif k == "u" and self.view == "run":   # instances shown before folding: 3 → 8 → all
            self.unroll = RUN_UNROLL[(RUN_UNROLL.index(self.unroll) + 1) % len(RUN_UNROLL)
                                     if self.unroll in RUN_UNROLL else 0]
            self._recompose()
        elif k == "v" and self.view == "run":   # the run view draws the run's lanes
            return False
        elif k == "v":                 # flips the active view's mode only
            view = self.view
            self.events[view] = EVENT_MODES[(EVENT_MODES.index(self.events[view]) + 1)
                                            % len(EVENT_MODES)]
            self._recompose()
        elif k == "e":
            self.show_triggers = not self.show_triggers
            self._recompose()
        elif k == "s":
            self.spaced = not self.spaced
            self._recompose()
        elif k == "p":
            self.payloads = not self.payloads
            self._recompose()
        elif k == "a":
            self.show_access = not self.show_access
            self._recompose()
        elif k == "m":
            self.show_mods = not self.show_mods
            self._recompose()
        elif k == "l":
            self.show_lint = not self.show_lint
        elif k == "r":
            self.reload(force=True)
        elif k in ("up", "k"):
            self.sy -= 1
        elif k in ("down", "j"):
            self.sy += 1
        elif k in ("left", "h"):
            self.sx -= SCROLL_X
        elif k in ("right", "L"):
            self.sx += SCROLL_X
        elif k == "pgup":
            self.sy -= page
        elif k in ("pgdn", " "):
            self.sy += page
        elif k == "f":                 # keeps the origin; frame() re-clamps it
            self.fit = not self.fit
        elif k in ("home", "g"):
            self._place = "home"
        elif k == "z":
            self._place = "centre"
        else:
            return False
        return True

    def _sim_key(self, k: str, now: float) -> bool:
        """Apply a sim-mode key (SIM_KEY_NAMES); the status bar always changes."""
        p = self.player
        if k == " ":
            changed = p.toggle(now)
        elif k in (",", "."):
            changed = p.step(1 if k == "." else -1)
        elif k in ("<", ">"):
            changed = p.step_event(1 if k == ">" else -1)
        elif k == "w":
            self.follow = not self.follow
            self._followed = None
            changed = False
        elif k in ("[", "]"):
            changed = p.choose(1 if k == "]" else -1)
        else:
            p.faster(-1 if k == "-" else 1)
            changed = False
        if changed:
            self._recompose()
        return True

    def tick(self, now: float) -> bool:
        """Playing: show the run's next frame when it is due by `now`. Returns
        True when the view changed."""
        if not self.sim_on or self.player is None or not self.player.advance(now):
            return False
        self._recompose()
        return True

    def wait(self, now: float) -> float | None:
        """Seconds until tick() has a frame to show (None: nothing is playing)."""
        return self.player.wait(now) if self.sim_on and self.player is not None else None

    def mouse(self, ev: Mouse) -> bool:
        """Apply a mouse report: a left-button drag pans (the drawing follows the
        pointer), the wheel scrolls. Returns True when the view changed."""
        if ev.code & 64:
            dx, dy = wheel_step(ev.code)
            self.sx, self.sy = self.sx + dx, self.sy + dy
            return True
        if ev.release:
            self._drag = None
            return False
        if ev.code & 3 != 0:           # middle / right button: not ours
            return False
        if not ev.code & 32:           # press: anchor the drag
            self._drag = (ev.x, ev.y, self.sx, self.sy)
            return False
        if self._drag is None:
            return False
        x0, y0, sx0, sy0 = self._drag
        self.sx, self.sy = sx0 - (ev.x - x0), sy0 - (ev.y - y0)
        return True

    # -- frame ---------------------------------------------------------------

    def _footer_rows(self, cols: int):
        """Everything under the drawing: the kind-legend rule, the view's legend
        (and the sim and checks legends), the keys (and the sim keys), then the
        parse error, the simulator's error, the lint panel and the checks panel
        (or why the checker failed); in sim mode the run's latest log line last."""
        rows = []
        failed = (kit.SEVERITY_COLOR["error"], None, True)
        if self.error:
            rows += [[(ln, failed)] for ln in info_lines(self.error, cols)]
        if self.sim_on and self.sim_error:
            rows += [[(ln, failed)] for ln in info_lines(self.sim_error, cols)]
        if self.show_lint:
            if not self.diags:
                rows.append([("lint: OK", (kit.OK_COLOR, None, False))])
            shown = 0
            for d in self.diags:
                lines = info_lines(f"{d.severity}:{d.line} {d.rule}: {d.message}", cols)
                if len(rows) + len(lines) > LINT_ROWS - (shown + 1 < len(self.diags)):
                    break
                colour = kit.SEVERITY_COLOR.get(d.severity, kit.GREY["mid"])
                head = len(f"{d.severity}:{d.line}")
                rows.append([(lines[0][:head], (colour, None, True)), (lines[0][head:], None)])
                rows += [[(ln, None)] for ln in lines[1:]]
                shown += 1
            if shown < len(self.diags):
                rows.append([(f"… {len(self.diags) - shown} more (view.py --once)",
                              (kit.GREY["mid"], None, False))])
        if self.show_checks and self.check_error:
            rows += [[(ln, failed)] for ln in info_lines(self.check_error, cols)]
        elif self.show_checks and self.checks is not None:
            rows += self.checks.panel(cols, CHECK_ROWS)
        if self.tree:
            legend = vtree.tree_legend(self.show_triggers, self.payloads, self.show_access,
                                       self.show_mods, self.events_mode,
                                       calls=drawn_call_marks(self.graph, self.depth,
                                                              self.payloads))
        elif self.view == "flow":
            legend = [vflow.flow_legend(self.show_triggers, self.payloads, self.show_access,
                                        self.show_mods, self.events_mode)]
        elif self.view == "run":
            legend = [vrun.run_legend()]
        else:
            legend = [vgraph.graph_legend(self.show_triggers, self.payloads, self.show_access,
                                          self.show_mods, self.events_mode)]
        if self.sim_on:
            legend += ([path_legend()] if self.view == "run"
                       else [sim_legend(self.tree), path_legend()])
        legend += [checks_legend()] if self.show_checks else []
        keys = [keys_legend(self)] + ([sim_keys_legend(self.player, self.follow)]
                                      if self.sim_on else [])
        rows[0:0] = [ln for r in legend + keys for ln in wrap_legend(r, cols)]
        rows.insert(0, self._legend_rule(cols))
        if self.sim_on and self.player is not None:
            rows += sim_story_rows(self.player, cols)
        return [kit.clip(r, 0, cols) for r in rows]

    def _legend_rule(self, cols: int):
        """The rule above the lint panel, carrying the node-type colour legend."""
        rule = (kit.GREY["dim"], None, False)
        row = [("── ", rule)]
        for kind, spec in kit.KINDS.items():
            word = spec.get("legend", kind)
            row += [("■ ", (spec["color"], None, False)), (f"{word} ", (kit.GREY["mid"], None, False))]
        row.append(("─" * max(cols - kit.row_len(row), 0), rule))
        return row

    def _bar(self, cols: int):
        """The status bar: file, #!mode, view · fit / pan, title, counts, depth, time,
        lint counts."""
        d = "all" if self.depth >= kit.ALL_DEPTH else str(self.depth)
        g = self.graph
        summary = f"{len(g.nodes)} nodes · {len(g.edges)} edges" if g is not None else "no graph"
        n_err = sum(1 for x in self.diags if x.severity == "error")
        n_warn = sum(1 for x in self.diags if x.severity == "warn")
        left = [(f" {self.path.name} ", kit.BAR_NAME_STYLE)]
        if self.mode:
            left.append((f"{self.mode} ", kit.MODE_STYLE))
        placing = "fit" if self.fit else "pan"     # before the title: never clipped off
        left.append((f"· {self.view} · {placing} ·", kit.BAR_STYLE))
        if self.sim_on and self.player is not None:   # before the title: never clipped off
            left.append((f" {self.player.status()} ·", kit.BAR_NAME_STYLE))
        if self.title:
            left.append((f" {self.title} ·", kit.BAR_NAME_STYLE))
        left.append((f" {summary} · depth {d} · {self.updated} ", kit.BAR_STYLE))
        if n_err or n_warn:
            left.append((f"{n_err}E {n_warn}W ", (kit.SEVERITY_COLOR["error" if n_err else "warn"],
                                                  kit.BAR_STYLE[1], True)))
        return kit.clip(left + [(" " * max(cols - kit.row_len(left), 0), kit.BAR_STYLE)], 0, cols)

    def _follow(self, cols: int, vh: int) -> bool:
        """Following a run (sim mode, w on): when the shown frame (or the view,
        size or placing) changed since the last follow, pan the least that brings
        the frame's focus (sim_focus) inside the viewport; between frames the
        origin is the reader's to pan. Returns True when it moved the origin."""
        if not (self.sim_on and self.follow and self.player is not None):
            return False
        key = (self.player.index, self.player.at, self.view, self.fit, cols, vh, self.depth,
               self.unroll)
        if key == self._followed:
            return False
        self._followed = key
        try:
            box = sim_focus(self.graph, self.view, depth=self.depth, payloads=self.payloads,
                            notes=self.notes, triggers=self.show_triggers, spaced=self.spaced,
                            width=cols if self.fit else None, access=self.show_access,
                            mods=self.show_mods, events=self.events_mode,
                            trace=self.sim_trace(), tick=self.player.at,
                            limits=self.limits, unroll=self.unroll, run_notes=self.run_notes)
        except Exception:              # following is a nicety: never break the frame
            return False
        if box is None:
            return False
        x, y, w, h = box
        origin = (self.sx, self.sy)
        self.sx = follow_origin(self.sx, x, w, cols)
        self.sy = follow_origin(self.sy, y, h, vh)
        return (self.sx, self.sy) != origin

    def frame(self, cols: int, rows: int):
        """Exactly `rows` rows of styled runs for a cols×rows terminal: the status bar,
        the drawing, the footer. Fitted (self.fit): the drawing rearranged to fit
        `cols` when it is wider (see fitted()), centred while it fits, scrolled when
        it still doesn't. Natural: the drawing as composed, panned freely (see
        pan_bounds). Resolves a pending home / centre and clamps the origin."""
        footer = self._footer_rows(cols)
        vh = self._vh = max(rows - 1 - len(footer), 1)
        body, W = self.fitted(cols) if self.fit else self.natural()
        H = len(body)
        if self.graph is None and not self.error:
            body = [[("waiting for " + str(self.path), (kit.GREY["mid"], None, False))]]
            W, H = kit.row_len(body[0]), 1
        self.sx = place(W, cols, self.sx, self.fit, self._place)
        self.sy = place(H, vh, self.sy, self.fit, self._place)
        self._place = None
        if self.graph is not None and self._follow(cols, vh):
            self.sx = place(W, cols, self.sx, self.fit, None)
            self.sy = place(H, vh, self.sy, self.fit, None)
        return ([self._bar(cols)] + viewport(body, self.sx, self.sy, cols, vh) + footer)[:rows]


def sim_story_rows(player: SimPlayer, cols: int) -> list:
    """The rows under the footer in sim mode: `path` and the hops of the shown
    episode so far, by branch (path_rows: PATH_ROWS rows, the hop now bold), the
    SIM_LOG_ROWS beats before the current one (dim), then the current one after
    `›` (bright) — the narration line. Mono reads them all; colour only ranks
    them."""
    dim = (kit.GREY["dim"], None, False)
    rows = path_rows(player.path_branches(), cols, hold=True)
    told = player.told()
    earlier = told[-SIM_LOG_ROWS - 1:-1]
    rows += [[("  ", None)] for _k in range(SIM_LOG_ROWS - len(earlier))]   # rows hold still
    rows += [[("  ", None), (beat_line(b), dim)] for b in earlier]
    now = beat_line(told[-1]) if told else ""
    rows.append([("› ", (kit.GREY["light"], None, True)), (now, (kit.GREY["light"], None, True))])
    return rows


def follow_origin(origin: int, lo: int, size: int, view: int, margin: int = 2) -> int:
    """The origin, moved the least that shows cells lo … lo + size - 1 of the
    drawing with `margin` cells to spare (a span wider than the view: its start)."""
    if size + 2 * margin >= view:
        return lo - min(margin, max(view - size, 0) // 2)
    if lo - margin < origin:
        return lo - margin
    if lo + size + margin > origin + view:
        return lo + size + margin - view
    return origin


def viewport(body, ox: int, oy: int, cols: int, vh: int):
    """`vh` rows of `body` seen through a cols-wide window whose top-left is drawing
    cell (ox, oy); a negative origin leaves blank lead-in."""
    pad = max(-ox, 0)
    out = []
    for y in range(oy, oy + vh):
        row = kit.clip(body[y], max(ox, 0), cols - pad) if 0 <= y < len(body) else []
        out.append(([(" " * pad, None)] if pad and row else []) + row)
    return out


_ESCAPES = {
    "\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
    "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left",
    "\x1b[5~": "pgup", "\x1b[6~": "pgdn", "\x1b[H": "home", "\x1b[1~": "home",
}


class Mouse(NamedTuple):
    """An SGR (1006) mouse report: `code` the button code (0 left, 1 middle,
    2 right; +4 shift, +8 meta, +16 ctrl, +32 motion, 64-67 wheel up / down /
    left / right), `x` / `y` the 1-based cell, `release` a button let go."""
    code: int
    x: int
    y: int
    release: bool


_SGR_MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")           # any complete CSI sequence
_CSI_OPEN = re.compile(r"\x1b(\[[0-?]*[ -/]*)?\Z")      # one cut off by the read


def split_input(data: str) -> tuple[str, str]:
    """(complete, rest): `data` with an escape sequence cut off at its end (a read
    ended mid-sequence) moved to `rest`, to be read again with the next bytes."""
    m = _CSI_OPEN.search(data)
    return (data[:m.start()], data[m.start():]) if m else (data, "")


def parse_keys(data: str):
    """Yield the keys in `data`: a key name ("up", "pgdn", …; "quit" for q), a
    character, or a Mouse report. Unknown escape sequences are dropped whole."""
    i = 0
    while i < len(data):
        for seq, name in _ESCAPES.items():
            if data.startswith(seq, i):
                yield name
                i += len(seq)
                break
        else:
            if m := _SGR_MOUSE.match(data, i):
                yield Mouse(int(m[1]), int(m[2]), int(m[3]), m[4] == "m")
                i = m.end()
            elif m := _CSI.match(data, i):
                i = m.end()            # an unknown sequence: none of its bytes are keys
            else:
                ch = data[i]
                i += 1
                if ch != "\x1b":      # a lone escape
                    yield "quit" if ch == "q" else ch


def tui(state: ViewState) -> None:
    import termios                     # POSIX-only: imported here so --once runs anywhere
    import tty

    def leave(signum, _frame):         # SIGTERM / SIGHUP: unwind through the finally
        raise SystemExit(128 + signum)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    out = sys.stdout
    resized = [True]
    previous = {sig: signal.signal(sig, leave) for sig in (signal.SIGTERM, signal.SIGHUP)}
    previous[signal.SIGWINCH] = signal.signal(signal.SIGWINCH,
                                              lambda *_: resized.__setitem__(0, True))
    try:
        tty.setcbreak(fd)
        out.write("\x1b[?1049h\x1b[?25l" + MOUSE_ON)
        state.reload(force=True)
        dirty, last_poll, pending = True, 0.0, ""
        while True:
            now = time.monotonic()
            if now - last_poll >= POLL_S:
                last_poll = now
                dirty |= state.reload()
            if resized[0]:
                resized[0], dirty = False, True
            dirty |= state.tick(now)
            cols, rows = shutil.get_terminal_size()
            if dirty:
                frame = state.frame(cols, rows)
                out.write("\x1b[H" + "\r\n".join(kit.ansi(r) + "\x1b[K" for r in frame) + "\x1b[J")
                out.flush()
                dirty = False
            due = state.wait(time.monotonic())
            ready, _, _ = select.select([fd], [], [], TICK_S if due is None else min(due, TICK_S))
            if ready:
                data, pending = split_input(pending + os.read(fd, READ_BYTES)
                                            .decode(errors="ignore"))
                for k in parse_keys(data):
                    if k == "quit":
                        return
                    dirty |= (state.mouse(k) if isinstance(k, Mouse)
                              else state.key(k, now=time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.write(MOUSE_OFF + "\x1b[0m\x1b[?25h\x1b[?1049l")
        out.flush()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _width_arg(text: str) -> int:
    try:
        width = int(text)
    except ValueError:
        width = 0
    if width < 1:
        raise argparse.ArgumentTypeError(f"expected a number of columns >= 1, got {text!r}")
    return width


def _unroll_arg(text: str) -> int:
    """--unroll N|all: N ≥ 1, or all (0: nothing folds)."""
    if text == "all":
        return 0
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"expected a number >= 1 or all, got {text!r}")
    return n


def _readable(path: Path) -> bool:
    """Whether path opens for reading; if not, say so on stderr. (The live view
    waits for the file instead: reload keeps the last view while it is missing.)"""
    try:
        path.open("rb").close()
    except OSError as exc:
        print(f"view.py: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
        return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Live terminal view of a Sigil graph.")
    ap.add_argument("file", type=Path)
    ap.add_argument("--depth", type=kit.render.depth_arg, default=1, help="expansion depth: N or 'all'")
    ap.add_argument("--payloads", action="store_true",
                    help="show flow payloads: chips on edges (graph view), a list (tree view)")
    ap.add_argument("--no-lint", action="store_true", help="skip lint")
    ap.add_argument("--dialect", default=None, help="dialect name or path (default: $SIGIL_DIALECT)")
    ap.add_argument("--once", action="store_true", help="print once and exit")
    ap.add_argument("--notes", choices=NOTE_MODES, default="off",
                    help="comments: #N markers + a notes list, or margin callouts (tree)")
    ap.add_argument("--compact", action="store_true",
                    help="tree view without blank rows between top-level units")
    ap.add_argument("--no-triggers", action="store_true",
                    help="hide event → state triggers (dashed edges in the graph view, "
                         "lanes in the tree view)")
    ap.add_argument("--access", action="store_true",
                    help="draw the permission graph: principal → store, headed r / w / b")
    ap.add_argument("--mods", action="store_true",
                    help="draw modifiers: chips on edges, after node labels")
    ap.add_argument("--events", choices=EVENT_MODES, default=None,
                    help="land: a pass-through event drawn where it lands (emitter wired "
                         "to each destination); nodes: as a row / box of its own "
                         "(default: tree land, graph and flow nodes)")
    views = ap.add_mutually_exclusive_group()
    views.add_argument("--graph", action="store_true",
                       help="graph: boxes and edges laid out top-down in layers")
    views.add_argument("--tree", action="store_true",
                       help="tree + wires: the composition tree as an outline, flows as lanes")
    views.add_argument("--flow", action="store_true",
                       help="flow: a call graph read left to right, bare labels in columns "
                            "by call depth")
    views.add_argument("--run", action="store_true",
                       help="run: one simulated run as a timeline — a lane per participant, "
                            "instance and recursion level, time left to right (--sim's run, "
                            "else the happy one)")
    ap.add_argument("--unroll", type=_unroll_arg, default=None, metavar="N|all",
                    help=f"the run view: instances of one node shown before the rest fold "
                         f"(default {RUN_UNROLL[0]}; all: none fold)")
    ap.add_argument("--width", type=_width_arg, default=None, metavar="N",
                    help="--once: fit the drawing to N columns (default: the terminal's "
                         f"width, or {ONCE_WIDTH} when stdout is not a terminal)")
    ap.add_argument("--sim", default=None, metavar="SCENARIO",
                    help="simulate a pathway: happy, a scenario's name, or a+b (--once: "
                         "the run's final frame, outcome and log; live: start in sim mode); "
                         "list: the scenarios; all: run every one, a table of outcomes")
    ap.add_argument("--limit", action="append", default=[], metavar="NAME=N",
                    help="raise one simulator bound for --sim (repeatable; e.g. frames=5000, "
                         "depth=5)")
    ap.add_argument("--json", action="store_true",
                    help="with --sim: print JSON instead of text (list / all: the "
                         "scenarios / every run's facts; a scenario: its facts, the run in "
                         "plain words and its log; no drawing); with --run: the run's "
                         "timeline (lanes, spans, moves, marks)")
    ap.add_argument("--checks", action="store_true",
                    help="the composition checks overlay (check.py): findings marked on the "
                         "drawing, listed with their questions (live: start with it on, key c)")
    ap.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    ap.add_argument("--theme", default=None,
                    help="colour theme: a name in themes/ or a .yaml path (default: $SIGIL_THEME or sigil)")
    a = ap.parse_args(argv)
    try:
        kit.use_theme(a.theme)
    except ValueError as exc:
        print(f"view.py: {exc}", file=sys.stderr)
        return 2
    dialect = None
    if dialects is not None:
        try:
            dialect = dialects.load(a.dialect)
        except ValueError as exc:
            print(f"view.py: {exc}", file=sys.stderr)
            return 2
    elif a.dialect:
        print("view.py: --dialect needs dialects.py next to view.py", file=sys.stderr)
        return 2
    try:
        limits = simulator.limits_from(a.limit) if a.limit else None
    except ValueError as exc:
        print(f"view.py: {exc}", file=sys.stderr)
        return 2
    if a.json and a.sim is None and not a.run:
        print("view.py: --json needs --sim (list, all or a scenario) or --run", file=sys.stderr)
        return 2
    view = next((v for v in VIEWS if getattr(a, v)), DEFAULT_VIEW)
    batch = a.sim in SIM_BATCH             # never drawn: the same live or --once
    tty_out = sys.stdout.isatty()
    once_out = a.once or not tty_out or not sys.stdin.isatty()
    if (batch or once_out) and not _readable(a.file):
        return 2
    if batch:
        return sim_batch(a.file, a.sim, dialect, a.json, limits)
    if a.json:                             # one run, no drawing: the same live or --once
        if not _readable(a.file):
            return 2
        try:
            if a.run:
                return run_json(a.file, a.sim, dialect, limits, a.unroll)
            return sim_json(a.file, a.sim, dialect, limits)
        except UnknownScenario as exc:
            print(f"view.py: --sim: {exc}", file=sys.stderr)
            return 2
    if once_out:
        colour = a.color == "always" or (a.color == "auto" and tty_out)
        width = a.width or (shutil.get_terminal_size().columns if tty_out else ONCE_WIDTH)
        try:
            return once(a.file, a.depth, a.payloads, not a.no_lint, dialect, colour, a.tree,
                        not a.no_triggers, not a.compact, a.notes, width, a.access, a.mods,
                        a.events, a.sim, a.checks, limits, view, a.unroll)
        except UnknownScenario as exc:     # the message lists the known ones
            print(f"view.py: --sim: {exc}", file=sys.stderr)
            return 2
    tui(ViewState(a.file, a.depth, a.payloads, not a.no_lint, dialect, a.tree,
                  not a.no_triggers, not a.compact, a.notes, a.access, a.mods, a.events,
                  a.sim, a.checks, limits, view, a.unroll))
    return 0


if __name__ == "__main__":
    sys.exit(main())
