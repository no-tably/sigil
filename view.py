#!/usr/bin/env python3
"""
view.py — Live terminal view of a Sigil document's graph.

Usage:
    view.py <file.sigil>                 # live view: redraws on every save
    view.py <file.sigil> --once          # print the graph + lint once, exit
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
    --tree           Tree + wires: the composition tree (`\\-` branches and `:=`
                     expansions) as an outline, every flow as a lane in a gutter —
                     ● marks a lane's source, ◀ each target; a row's run hops a lane
                     it only crosses (─│─) and joins (┤ ┴ ┬ ┼) only a lane it taps.
    --compact        Tree view without the blank row between top-level units.
    --no-triggers    Start without event → state triggers (lanes / wires).
    --notes MODE     off | markers (#N tags + a notes list) | callouts (tree view:
                     boxes in a left margin tied to their rows).

Keys (live view):
    d  cycle depth (0 → 1 → all)   p  payloads   l  lint panel   r  reload
    t  toggle graph / tree + wires   e  triggers (event ⇢ the state it drives)
    s  spacing between units
    n  notes: off → #N markers + list → margin callouts (tree view)
    arrows / h j k L scroll   pgup / pgdn / space page   g home   c  re-centre   q  quit

Zero dependencies: python3 standard library only. The graph comes from
render.parse_document (the same parse render.py turns into Mermaid), laid out
top-down in layers (cycle breaking, longest-path layering, barycenter ordering,
block-merged x placement, one track per fan-out) and drawn with box-drawing
characters. The live view is a plain alternate-screen terminal loop that keeps
the drawing centred in the pane while it fits, and scrolls when it doesn't.

Boxes are colour-coded by node type (border + tinted fill); the sigil theme:
    [component] periwinkle   {data} violet   <event> pink   (actor) green
    |store| amber   state cyan   ? hole grey   (a dialect may register more kinds)
Border shape:  (actor) ╭╮ round   ~mutable ┏┓ heavy
               ? hole ┄┆ dashed     ▸ collapsed expansion   ▾ shown below
Edge strokes:  ->  │─ light        ~>  ╎╌ dashed      =>  ┃━ heavy
               *>  ║═ double       ?>  ┆┄ dotted       !>  red   <-> heads both ends
               ╭┄┄╮ a payload chip on its edge (p)  ╌╌ pink  event ⇢ owner (e)
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import select
import shutil
import signal
import sys
import textwrap
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import NamedTuple

_DIR = Path(__file__).resolve().parent


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod   # dataclasses resolve string annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


render = _load("sigil_render", "render.py")
lint = _load("sigil_lint", "lint.py")
dialects = _load("sigil_dialects", "dialects.py") if (_DIR / "dialects.py").exists() else None
themes = _load("sigil_themes", "themes.py") if (_DIR / "themes.py").exists() else None


# ---------------------------------------------------------------------------
# Styles — a style is (fg, bg, bold) with "#rrggbb" colours or None. Colours
# come from the theme (themes/<name>.yaml, see themes.py); each one remembers
# its theme role, so a drawing can be re-coloured by role (the site does).
# ---------------------------------------------------------------------------

class Colour(str):
    """A "#rrggbb" colour tagged with its theme role, e.g. "kinds-service"."""
    role: str = ""

    def __new__(cls, value: str, role: str = ""):
        c = super().__new__(cls, value)
        c.role = role
        return c


# Node kinds: glyph brackets and border; apply_theme() fills in each "color". A
# dialect adds kinds through its NODE_KINDS mapping (same keys; optional "label":
# fn(node) -> str); a theme's `kinds:` map recolours any kind by name.
CORE_KINDS = {
    "service": {"open": "[", "close": "]", "border": "square", "legend": "component"},
    "data":    {"open": "{", "close": "}", "border": "square"},
    "event":   {"open": "<", "close": ">", "border": "square"},
    "actor":   {"open": "(", "close": ")", "border": "round"},
    "store":   {"open": "|", "close": "|", "border": "square"},
    "state":   {"open": "",  "close": "",  "border": "round"},
}
PSEUDO_LABEL = {"start": "●", "end": "◉", "any": "∗ any"}
KINDS: dict = {}                    # CORE_KINDS + the dialect's kinds, coloured
_DIALECT_KINDS: dict = {}
THEME: dict = {}                    # the theme in use, over the built-in colours

# The built-in colours: the sigil theme (themes/sigil.yaml), in its sections and
# role names. Every theme is applied over a fresh copy of these, so a partial
# theme overrides only what it names. Without themes.py they are used as-is.
_BUILTIN_THEME = {
    "palette": {"bg": "#0d1117"},
    "kinds": {"service": "#8aa0ff", "data": "#d2a8ff", "event": "#e85d9e",
              "actor": "#7ee787", "store": "#ffbf47", "state": "#5ccfe6", "hole": "#6e7681"},
    "edges": {"fail": "#f85149", "maybe": "#6e7681", "async": "#8b949e", "split": "#6e7681",
              "default": "#c9d1d9"},
    "ui": {"text": "#c9d1d9", "muted": "#8b949e", "dim": "#6e7681", "tree": "#6e7681",
           "relation": "#5abea0", "label": "#5abea0", "title": "#c9d1d9",
           "payload": "#8b949e", "note": "#8b949e", "note_tag": "#6e7681",
           "note_block": "#8b7aad", "note_inline": "#a5d6ff",
           "bar_fg": "#c9d1d9", "bar_bg": "#161b22", "bar_name": "#e6edf3",
           "key_fg": "#e6edf3", "key_bg": "#30363d",
           "error": "#f85149", "warn": "#ffbf47", "ok": "#3fb950", "fill": "0.22"},
    # Code roles (highlight/sigil.tmTheme): payloads are drawn highlighted.
    "syntax": {"operator": "#e85d9e", "cardinality": "#f59cc4", "modifier": "#ffe0b0",
               "keyword": "#c850e0", "ref": "#bc8cff", "string": "#a5d6ff",
               "number": "#79c0ff", "punct": "#586e75", "tag": "#c9d1d9"},
}
EDGE_ROLE = {"!>": "fail", "?>": "maybe", "~>": "async", "]>[": "split"}
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})")


def _hex(value) -> str | None:
    """value as "#rrggbb" when it is a "#rrggbb" / "#rgb" colour, else None."""
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        return None
    return value if len(value) == 7 else "#" + "".join(ch * 2 for ch in value[1:])


def _theme_styles(t: dict) -> dict:
    """Every themed module-level style, by name, from a theme merged over the
    built-ins (apply_theme binds them). A value that isn't a colour (or a fill
    that isn't a number) falls back to the built-in."""
    def pick(section: str, key: str) -> Colour:
        value = _hex(t[section].get(key)) or _BUILTIN_THEME[section][key]
        return Colour(value, f"{section}-{key.replace('_', '-')}")

    try:
        fill = float(t["ui"]["fill"])
    except (TypeError, ValueError):
        fill = float(_BUILTIN_THEME["ui"]["fill"])
    if fill != fill:                                    # nan
        fill = float(_BUILTIN_THEME["ui"]["fill"])
    bar_bg = pick("ui", "bar_bg")
    return {
        "BG": pick("palette", "bg"),
        "FILL": min(max(fill, 0.0), 1.0),
        "HOLE_COLOR": pick("kinds", "hole"),
        "GREY": {"dim": pick("ui", "dim"), "mid": pick("ui", "muted"),
                 "light": pick("ui", "text")},
        "EDGE_COLOR": {arrow: pick("edges", role) for arrow, role in EDGE_ROLE.items()},
        "EDGE_DEFAULT": pick("edges", "default"),
        "LABEL_STYLE": (pick("ui", "label"), None, False),          # edge / trigger labels
        "REL_STYLE": (pick("ui", "relation"), None, True),          # & ? $ … in the tree
        "TREE_STYLE": (pick("ui", "tree"), None, False),            # outline rails
        "TITLE_STYLE": (pick("ui", "title"), None, True),
        "PAYLOAD_STYLE": (pick("ui", "payload"), None, False),
        "NOTE_TAG_STYLE": (pick("ui", "note_tag"), None, False),
        "NOTE_TEXT_STYLE": (pick("ui", "note"), None, False),
        # block comments vs inline (trailing) ones: tag, callout text and list
        "NOTE_STYLE": {"block": (pick("ui", "note_block"), None, False),
                       "inline": (pick("ui", "note_inline"), None, False)},
        "SYNTAX": {role: (pick("syntax", role), None, False)
                   for role in _BUILTIN_THEME["syntax"]},
        "BAR_STYLE": (pick("ui", "bar_fg"), bar_bg, False),
        "BAR_NAME_STYLE": (pick("ui", "bar_name"), bar_bg, True),
        "KEY_STYLE": (pick("ui", "key_fg"), pick("ui", "key_bg"), True),
        "OK_COLOR": pick("ui", "ok"),
        "SEVERITY_COLOR": {"error": pick("ui", "error"), "warn": pick("ui", "warn")},
        "_KIND_COLOR": {kind: pick("kinds", kind) for kind in CORE_KINDS},
    }


def apply_theme(theme: dict) -> None:
    """Colour everything from a resolved theme (themes.load()), laid over a fresh
    copy of the built-in colours: whatever the theme leaves out is sigil's, never
    a previously applied theme's. Binds the names _theme_styles() returns."""
    merged = {**theme}
    for section, builtin in _BUILTIN_THEME.items():
        own = theme.get(section)
        merged[section] = {**builtin, **(own if isinstance(own, dict) else {})}
    THEME.clear()
    THEME.update(merged)
    styles = _theme_styles(merged)
    for kind, colour in styles.pop("_KIND_COLOR").items():
        CORE_KINDS[kind]["color"] = colour
    globals().update(styles)
    _refresh_kinds()


def use_theme(spec: str | None = None) -> None:
    """Load a theme by name or path (default: $SIGIL_THEME, else sigil) and apply it.
    Without themes.py beside view.py the built-in sigil colours stay. Raises
    ValueError for a theme that can't be found or read."""
    if themes is not None:
        apply_theme(themes.load(spec))
    elif spec:
        raise ValueError("--theme needs themes.py next to view.py")


def use_dialect(dialect) -> None:
    """Make the dialect's extra node kinds (if any) drawable."""
    _DIALECT_KINDS.clear()
    _DIALECT_KINDS.update(getattr(dialect, "NODE_KINDS", None) or {})
    _refresh_kinds()


def _refresh_kinds() -> None:
    KINDS.clear()
    KINDS.update(CORE_KINDS)
    themed = THEME.get("kinds", {})
    for name, spec in _DIALECT_KINDS.items():
        colour = _hex(themed.get(name))
        KINDS[name] = ({**spec, "color": Colour(colour, f"kinds-{name}")}
                       if colour else spec)


# The built-in colours until a theme is applied (main() applies --theme /
# $SIGIL_THEME). Defines BG, FILL, HOLE_COLOR, GREY, EDGE_COLOR, EDGE_DEFAULT,
# the *_STYLE tuples, OK_COLOR and SEVERITY_COLOR — see _theme_styles().
apply_theme({})


def kind_color(kind: str) -> str:
    return KINDS.get(kind, {}).get("color", GREY["light"])


def _tint(hex_colour: str) -> str:
    """The colour mixed toward the background — a box fill that keeps the label legible."""
    fg = [int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)]
    bg = [int(BG[i:i + 2], 16) for i in (1, 3, 5)]
    mixed = "#%02x%02x%02x" % tuple(round(b + (f - b) * FILL) for f, b in zip(fg, bg))
    role = getattr(hex_colour, "role", "")
    return Colour(mixed, "tint:" + role if role else "")


def edge_style(kind: str):
    if kind == "trigger":                     # event ⇢ the owner of the state it drives
        return (kind_color("event"), None, False)
    return (EDGE_COLOR.get(kind, EDGE_DEFAULT), None, False)


# A flow's `: payload` drawn in the graph view as a chip on its edge (not a glyph,
# so not in KINDS): the edge runs src → chip → dst, the chip on its own layer.
CHIP = "payload"


def node_styles(n):
    """(border style, label style) for a node box, colour-coded by kind."""
    if n.kind == CHIP:
        return (GREY["dim"], None, False), (PAYLOAD_STYLE[0], None, False)
    colour = HOLE_COLOR if n.is_hole else kind_color(n.kind)
    fill = _tint(colour)
    return (colour, fill, False), (colour, fill, True)


def node_label(n) -> str:
    if n.kind == CHIP:
        return n.name
    spec = KINDS.get(n.kind, {})
    if n.attrs.get("pseudo") in PSEUDO_LABEL:
        return PSEUDO_LABEL[n.attrs["pseudo"]]
    name = spec["label"](n) if "label" in spec else n.name
    lead = ("~" if n.is_mutable else "") + ("*" if n.is_stream else "")
    return f"{lead}{spec.get('open', '[')}{name}{spec.get('close', ']')}"


def edge_text(g, e) -> str:
    return f"{node_label(g.nodes[e.src])} {e.kind} {node_label(g.nodes[e.dst])}"


# ---------------------------------------------------------------------------
# Canvas — a grid of (char, style); lines are stored as direction bitmasks so
# crossings and corners resolve to the right box-drawing junction.
# ---------------------------------------------------------------------------

U, R, D, L = 1, 2, 4, 8
_OPP = {U: D, D: U, L: R, R: L}

_LIGHT = {0: " ", U: "│", D: "│", U | D: "│", L: "─", R: "─", L | R: "─",
          D | R: "┌", D | L: "┐", U | R: "└", U | L: "┘",
          U | D | R: "├", U | D | L: "┤", L | R | D: "┬", L | R | U: "┴",
          U | D | L | R: "┼"}
_HEAVY = {0: " ", U: "┃", D: "┃", U | D: "┃", L: "━", R: "━", L | R: "━",
          D | R: "┏", D | L: "┓", U | R: "┗", U | L: "┛",
          U | D | R: "┣", U | D | L: "┫", L | R | D: "┳", L | R | U: "┻",
          U | D | L | R: "╋"}
# Straight runs only; corners/junctions fall back to the light set.
_DASHED = {U | D: "╎", U: "╎", D: "╎", L | R: "╌", L: "╌", R: "╌"}
_DOTTED = {U | D: "┆", U: "┆", D: "┆", L | R: "┄", L: "┄", R: "┄"}

_DOUBLE = {0: " ", U: "║", D: "║", U | D: "║", L: "═", R: "═", L | R: "═",
           D | R: "╔", D | L: "╗", U | R: "╚", U | L: "╝",
           U | D | R: "╠", U | D | L: "╣", L | R | D: "╦", L | R | U: "╩",
           U | D | L | R: "╬"}
_TABLES = {"heavy": _HEAVY, "double": _DOUBLE, "dashed": _DASHED, "dotted": _DOTTED}

_STROKE_RANK = {"heavy": 4, "double": 3, "light": 2, "dashed": 1, "dotted": 0}

# Each arrow kind's source marker in the tree view (its stroke comes from _stroke).
SOURCE_MARK = {"->": "●", "~>": "○", "=>": "◆", "!>": "✖", "?>": "◇", "*>": "✱",
               "<->": "●", "trigger": "◎"}


def _stroke(kind: str) -> str:
    return {"=>": "heavy", "*>": "double", "~>": "dashed", "trigger": "dashed",
            "?>": "dotted", "]>[": "dotted"}.get(kind, "light")


class Canvas:
    def __init__(self):
        self.text: dict = {}    # (x, y) → (char, style)
        self.lines: dict = {}   # (x, y) → [mask, stroke, style]
        self.w = 0
        self.h = 0

    def _grow(self, x, y):
        self.w = max(self.w, x + 1)
        self.h = max(self.h, y + 1)

    def put(self, x, y, s, style=None):
        for i, ch in enumerate(s):
            self.text[(x + i, y)] = (ch, style)
            self._grow(x + i, y)

    def link(self, a, b, kind, style, fixed=frozenset()):
        """Connect adjacent cells a → b with a line of the given arrow kind. A cell
        takes the higher-ranked stroke of the lines through it, unless it is in
        `fixed` (its stroke is settled; the line only joins it)."""
        (ax, ay), (bx, by) = a, b
        d = R if bx > ax else L if bx < ax else D if by > ay else U
        stroke = _stroke(kind)
        for cell, bit in ((a, d), (b, _OPP[d])):
            cur = self.lines.setdefault(cell, [0, stroke, style])
            cur[0] |= bit
            if _STROKE_RANK[stroke] > _STROKE_RANK[cur[1]] and cell not in fixed:
                cur[1], cur[2] = stroke, style
            self._grow(*cell)

    def stub(self, cell, bit, kind, style):
        """Half a link: a line from `cell` toward one neighbour, not into it."""
        self.lines.setdefault(cell, [0, _stroke(kind), style])[0] |= bit

    def path(self, pts, kind, style):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            dx = (x2 > x1) - (x2 < x1)
            dy = (y2 > y1) - (y2 < y1)
            x, y = x1, y1
            while (x, y) != (x2, y2):
                nxt = (x + dx, y + dy)
                self.link((x, y), nxt, kind, style)
                x, y = nxt

    def run(self, x0, x1, y, kind, style, hops=None, fixed=frozenset()) -> set:
        """A line x0 → x1 along row y that hops every column x where hops(x): it
        stops a cell short on each side (─│─), so it never reads as joined there.
        `fixed` as for link(). Returns the cells it drew into."""
        drawn = set()
        for x in range(x0, x1):
            a, b = (x, y), (x + 1, y)
            a_hop, b_hop = hops is not None and hops(x), hops is not None and hops(x + 1)
            if a_hop and b_hop:
                continue
            if b_hop:
                self.stub(a, R, kind, style)
                drawn.add(a)
            elif a_hop:
                self.stub(b, L, kind, style)
                drawn.add(b)
            else:
                self.link(a, b, kind, style, fixed)
                drawn |= {a, b}
        return drawn

    def cell(self, x, y):
        if (x, y) in self.text:
            return self.text[(x, y)]
        if (x, y) in self.lines:
            mask, stroke, style = self.lines[(x, y)]
            return _TABLES.get(stroke, _LIGHT).get(mask, _LIGHT.get(mask, "┼")), style
        return " ", None

    def rows(self):
        """Yield each row as a list of (run_text, style) runs."""
        for y in range(self.h):
            runs = []
            for x in range(self.w):
                ch, st = self.cell(x, y)
                if runs and runs[-1][1] == st:
                    runs[-1][0] += ch
                else:
                    runs.append([ch, st])
            if runs:
                runs[-1][0] = runs[-1][0].rstrip()
            yield [(t, s) for t, s in runs if t]


def _first_fit(cols: list, lo: int, hi: int) -> int:
    """Interval packing: the first column whose spans all clear [lo, hi] by a cell
    (a new column when none does). Records the span there; returns the column."""
    for k, spans in enumerate(cols):
        if all(hi < a - 1 or lo > b + 1 for a, b in spans):
            spans.append((lo, hi))
            return k
    cols.append([(lo, hi)])
    return len(cols) - 1


# ---------------------------------------------------------------------------
# Layout — layered, top-down: _prepare → _layer → _order → _place_x → _ports →
# _route → _draw, each phase filling in more of a _Layout.
# ---------------------------------------------------------------------------

BOX_H = 3
NODE_GAP = 3
ISOLATED_WRAP = 100   # wrap width for the unconnected-node grid
ORDER_SWEEPS = 6      # barycenter ordering: down + up sweeps
PLACE_SWEEPS = 8      # x placement: alternating down / up sweeps


@dataclass
class _V:
    id: str
    w: int
    dummy: bool = False
    layer: int = 0
    x: int = 0
    ins: list = field(default_factory=list)
    outs: list = field(default_factory=list)


@dataclass
class _Layout:
    """A graph part-way through layout."""
    g: object
    labels: dict                                    # node id → box label
    edges: list                                     # distinct, non-self edges
    ids: list                                       # linked node ids, document order
    isolated: list                                  # unconnected node ids
    V: dict = field(default_factory=dict)           # vertex id → _V (dummies too)
    chains: list = field(default_factory=list)      # (edge, reversed, [vertex ids top → bottom])
    layers: list = field(default_factory=list)      # per layer: vertex ids, left → right
    out_port: dict = field(default_factory=dict)    # u → {w: x where u → w leaves u}
    in_port: dict = field(default_factory=dict)     # w → {u: x where u → w enters w}
    tracks: list = field(default_factory=list)      # per gap: ({(u, w): track}, n tracks)
    top: list = field(default_factory=list)         # per layer: its y
    tags: dict = field(default_factory=dict)        # node id / (src, dst, kind) → note tag runs

    def centre(self, vid):
        return self.V[vid].x + self.V[vid].w // 2


@dataclass
class _Block:
    """Row nodes merged to sit side by side, centred on their mean wanted x."""
    first: int                                      # the row index of its first node
    width: int
    want: float                                     # Σ (wanted left x − offset in block)
    count: int
    offsets: list                                   # each node's x offset in the block

    def left(self) -> int:
        return round(self.want / self.count)


def _break_cycles(ids, succ):
    """DFS in document order; return the set of back edges (reversed for layering)."""
    state, back = {}, set()
    for root in ids:
        if root in state:
            continue
        stack = [(root, iter(succ[root]))]
        state[root] = 1
        while stack:
            v, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[v] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                back.add((v, nxt))
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(succ[nxt])))
    return back


def layout(g, expanded: set, collapsed: set, tags: dict | None = None) -> Canvas:
    lay = _prepare(g, expanded, collapsed, tags)
    _layer(lay)
    _order(lay)
    _place_x(lay)
    _ports(lay)
    _route(lay)
    return _draw(lay)


def _prepare(g, expanded, collapsed, tags) -> _Layout:
    """Box labels (with #N tags, ▾ / ▸ and ↺ marks), the distinct edges, and the
    nodes no edge touches."""
    labels = {}
    for nid in g.nodes:
        lab = node_label(g.nodes[nid])
        if tags and nid in tags:
            lab += "".join(text for text, _style in tags[nid])
        if nid in expanded:
            lab += " ▾"
        elif nid in collapsed:
            lab += " ▸"
        labels[nid] = lab

    # Distinct, non-self edges (a self-loop is marked on the node instead).
    seen, edges = set(), []
    for e in g.edges:
        if e.src == e.dst:
            labels[e.src] = labels[e.src] + " ↺"
            continue
        key = (e.src, e.dst, e.kind)
        if key not in seen and e.src in g.nodes and e.dst in g.nodes:
            seen.add(key)
            edges.append(e)

    # Unconnected nodes skip layering (they would all pile into one very wide top
    # row) and are drawn as a wrapped grid under the graph.
    linked = {e.src for e in edges} | {e.dst for e in edges}
    return _Layout(g, labels, edges, ids=[i for i in g.nodes if i in linked],
                   isolated=[i for i in g.nodes if i not in linked], tags=tags or {})


def _layer(lay: _Layout) -> None:
    """Break cycles, assign longest-path layers, and split long edges with 1-wide
    dummies so every segment spans one layer gap."""
    ids, V = lay.ids, lay.V
    succ = {i: [] for i in ids}
    for e in lay.edges:
        succ[e.src].append(e.dst)
    back = _break_cycles(ids, succ)

    # DAG orientation: each edge as (top, bottom, edge, reversed?)
    dag = []
    for e in lay.edges:
        if (e.src, e.dst) in back:
            dag.append((e.dst, e.src, e, True))
        else:
            dag.append((e.src, e.dst, e, False))

    # Longest-path layering (Kahn order).
    for i in ids:
        V[i] = _V(i, len(lay.labels[i]) + 4)
    indeg = {i: 0 for i in ids}
    down = {i: [] for i in ids}
    for a, b, _, _ in dag:
        down[a].append(b)
        indeg[b] += 1
    queue = [i for i in ids if indeg[i] == 0]
    while queue:
        v = queue.pop(0)
        for b in down[v]:
            V[b].layer = max(V[b].layer, V[v].layer + 1)
            indeg[b] -= 1
            if indeg[b] == 0:
                queue.append(b)

    n_dummy = 0
    for a, b, e, rev in dag:
        chain = [a]
        for layer in range(V[a].layer + 1, V[b].layer):
            n_dummy += 1
            did = f"\0d{n_dummy}"
            V[did] = _V(did, 1, dummy=True, layer=layer)
            chain.append(did)
        chain.append(b)
        for u, w in zip(chain, chain[1:]):
            V[u].outs.append(w)
            V[w].ins.append(u)
        lay.chains.append((e, rev, chain))

    nlayers = max((v.layer for v in V.values()), default=0) + 1
    lay.layers = [[] for _ in range(nlayers)]
    for vid, v in V.items():          # document order, dummies after
        lay.layers[v.layer].append(vid)


def _order(lay: _Layout) -> None:
    """Barycenter ordering sweeps: down orders each layer by its parents, up by
    its children."""
    V, layers = lay.V, lay.layers
    nlayers = len(layers)
    pos = {vid: i for row in layers for i, vid in enumerate(row)}

    def barycenter(vid, ref):
        nb = getattr(V[vid], ref)
        return sum(pos[n] for n in nb) / len(nb) if nb else pos[vid]

    sweep = [(i, "ins") for i in range(1, nlayers)] + \
            [(i, "outs") for i in range(nlayers - 2, -1, -1)]
    for _ in range(ORDER_SWEEPS):
        for i, ref in sweep:
            row = layers[i]
            row.sort(key=lambda vid, _ref=ref: barycenter(vid, _ref))
            pos.update((vid, k) for k, vid in enumerate(row))   # only this row moved


def _place_x(lay: _Layout) -> None:
    """Pack each layer, then pull each node toward the mean of its neighbours'
    centres (never overlapping its left neighbour), a few sweeps each way."""
    V, layers = lay.V, lay.layers
    for row in layers:
        x = 0
        for vid in row:
            V[vid].x = x
            x += V[vid].w + NODE_GAP

    for sweep in range(PLACE_SWEEPS):
        order = range(len(layers)) if sweep % 2 == 0 else range(len(layers) - 1, -1, -1)
        for i in order:
            row = layers[i]
            want = []
            for vid in row:
                nb = V[vid].ins + V[vid].outs
                want.append(sum(lay.centre(n) for n in nb) / len(nb) - V[vid].w // 2
                            if nb else V[vid].x)
            _place(V, row, want)
    minx = min((v.x for v in V.values()), default=0)
    for v in V.values():
        v.x -= minx


def _place(V, row, want):
    """Put each node as near its wanted left x as spacing allows: overlapping
    neighbours merge into a block centred on their mean want (so siblings
    spread evenly under a shared parent instead of drifting right)."""
    blocks = []
    for k, vid in enumerate(row):
        blocks.append(_Block(k, V[vid].w, want[k], 1, [0]))
        while len(blocks) > 1:
            b, c = blocks[-2], blocks[-1]
            if b.left() + b.width + NODE_GAP <= c.left():
                break
            shift = b.width + NODE_GAP
            b.offsets += [o + shift for o in c.offsets]
            b.want += c.want - shift * c.count
            b.count += c.count
            b.width += NODE_GAP + c.width
            blocks.pop()
    for b in blocks:
        left = b.left()
        for j, off in enumerate(b.offsets):
            V[row[b.first + j]].x = left + off


def _ports(lay: _Layout) -> None:
    """Where each segment leaves its upper vertex and enters its lower one."""
    V, centre = lay.V, lay.centre

    # Incoming edges spread across the box width so each arrowhead is distinct.
    def in_ports(vid):
        v, nbrs = V[vid], V[vid].ins
        if v.dummy or len(nbrs) <= 1:
            return {n: centre(vid) for n in nbrs}
        inner = max(v.w - 2, 1)
        srt = sorted(nbrs, key=centre)
        return {n: v.x + 1 + (k * (inner - 1)) // max(len(srt) - 1, 1)
                for k, n in enumerate(srt)}

    # Outgoing edges leave from the box centre (a fan-out draws as one ┬ tree); a
    # back edge (drawn upward) gets its own out-port right of centre, so it never
    # merges into the node's forward fan-out tree.
    back_seg = {(ch[0], ch[1]) for _, rev, ch in lay.chains if rev}

    def out_ports(vid):
        outs = V[vid].outs
        fwd = [n for n in outs if (vid, n) not in back_seg]
        bk = sorted((n for n in outs if (vid, n) in back_seg), key=centre)
        res = {n: centre(vid) for n in fwd}
        if bk and not V[vid].dummy:
            right = V[vid].x + V[vid].w - 2
            for k, n in enumerate(bk):
                res[n] = min(centre(vid) + (0 if not fwd and k == 0 else 2 * (k + 1)), right)
        else:
            res.update({n: centre(vid) for n in bk})
        return res

    out_port = lay.out_port = {vid: out_ports(vid) for vid in V}
    in_port = lay.in_port = {vid: in_ports(vid) for vid in V}

    # Straighten: a lone edge whose far port lies within this box's width drops
    # straight down instead of jogging a column or two sideways.
    def inside(vid, x):
        v = V[vid]
        return not v.dummy and v.x + 1 <= x <= v.x + v.w - 2

    for u in V:
        for w in V[u].outs:
            sx, dx = out_port[u][w], in_port[w][u]
            if sx == dx:
                continue
            if len(V[u].outs) == 1 and inside(u, dx):
                out_port[u][w] = dx
            elif len(V[w].ins) == 1 and inside(w, sx):
                in_port[w][u] = sx


def _route(lay: _Layout) -> None:
    """Channel between layer i and i+1: one track per source port with a jog;
    then each layer's y."""
    V, layers = lay.V, lay.layers
    for i in range(len(layers) - 1):
        groups = {}
        for u in layers[i]:
            for w in V[u].outs:
                sx, dx = lay.out_port[u][w], lay.in_port[w][u]
                if sx != dx:
                    groups.setdefault(sx, []).append((u, w, min(sx, dx), max(sx, dx)))
        spans = sorted(((min(s[2] for s in segs), max(s[3] for s in segs), segs)
                        for segs in groups.values()), key=lambda t: t[0])
        cols, assign = [], {}
        for lo, hi, segs in spans:
            t = _first_fit(cols, lo, hi)
            for u, w, _, _ in segs:
                assign[(u, w)] = t
        lay.tracks.append((assign, len(cols)))

    y = 0
    for i in range(len(layers)):
        lay.top.append(y)
        y += BOX_H
        if i < len(layers) - 1:
            y += lay.tracks[i][1] + 2


def _draw(lay: _Layout) -> Canvas:
    """Edges, then boxes over them, then edge labels where they fit, then the
    grid of unconnected nodes."""
    V, top, g = lay.V, lay.top, lay.g
    cv = Canvas()

    # Edges first (boxes overwrite line cells they touch).
    heads = []
    edge_labels = []   # (x, y, text) beside an arrowhead
    for e, rev, chain in lay.chains:
        style = edge_style(e.kind)
        for k, (u, w) in enumerate(zip(chain, chain[1:])):
            i = V[u].layer
            assign, _n = lay.tracks[i]
            sx, dx = lay.out_port[u][w], lay.in_port[w][u]
            y0 = top[i] + BOX_H if not V[u].dummy else top[i]
            y1 = top[i + 1] - 1 if not V[w].dummy else top[i + 1]
            ty = top[i] + BOX_H + 1 + assign.get((u, w), 0)
            if V[u].dummy:
                cv.path([(sx, top[i]), (sx, top[i] + BOX_H)], e.kind, style)
                y0 = top[i] + BOX_H
            pts = [(sx, y0), (sx, ty), (dx, ty), (dx, y1)] if sx != dx else [(sx, y0), (dx, y1)]
            cv.path(pts, e.kind, style)
            if V[w].dummy:
                cv.path([(dx, top[i + 1]), (dx, top[i + 1] + BOX_H - 1)], e.kind, style)
            last = k == len(chain) - 2
            first = k == 0
            # Arrowheads at the LOGICAL destination (and both ends for <->).
            if e.label and ((last and not rev) or (first and rev)):
                edge_labels.append((dx, y1, e.label, LABEL_STYLE) if not rev
                                   else (sx, y0, e.label, LABEL_STYLE))
            # An inline note about this flow's line sits beside its head (a chip
            # remembers the flow it splits, so the tag follows into the chip half).
            src = g.nodes[e.src].attrs.get("src", e.src) if g.nodes[e.src].kind == CHIP else e.src
            for text, style in lay.tags.get((src, e.dst, e.kind), ()):
                if last and not rev:
                    edge_labels.append((dx, y1, text, style))
                elif first and rev:
                    edge_labels.append((sx, y0, text, style))
            into_chip = g.nodes[chain[-1]].kind == CHIP if not rev else False
            if last and not rev and not into_chip:
                heads.append((dx, y1, "▼", style))
            if first and rev:
                heads.append((sx, y0, "▲", style))
            if e.kind == "<->":
                if first and not rev:
                    heads.append((sx, y0, "▲", style))
                if last and rev:
                    heads.append((dx, y1, "▼", style))
    for x, y, ch, st in heads:
        cv.put(x, y, ch, st)

    for vid, v in V.items():
        if not v.dummy:
            _draw_box(cv, v.x, top[v.layer], v.w, lay.labels[vid], g.nodes[vid])
            _colour_tags(cv, v.x, top[v.layer], g.nodes[vid], lay.tags.get(vid))

    # Edge labels (e.g. state-machine triggers) beside their arrowhead, right side
    # first, then left; skipped where they would overwrite anything.
    def free(x0, y, n):
        return x0 >= 0 and all((x, y) not in cv.text and (x, y) not in cv.lines
                               for x in range(x0 - 1, x0 + n + 1))

    for x, y, text, style in edge_labels:
        for x0 in (x + 2, x - 1 - len(text)):
            if free(x0, y, len(text)):
                cv.put(x0, y, text, style)
                break

    if lay.isolated:
        wrap = max(cv.w, ISOLATED_WRAP)
        x, y = 0, cv.h + 1 if cv.h else 0
        for vid in lay.isolated:
            w = len(lay.labels[vid]) + 4
            if x and x + w > wrap:
                x, y = 0, y + BOX_H
            _draw_box(cv, x, y, w, lay.labels[vid], g.nodes[vid])
            x += w + 1
    return cv


# A payload drawn as code: glyphs in their kind's colour, the rest by role.
_PAYLOAD_TOKEN = re.compile(r"""
    (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<ref>\$\{[^}]*\})
  | (?P<glyph>[~*]?(?:\[[^\]\s,][^\],]*\]|\{[^}\s:,][^}:,]*\}|<(?!->)[^<>\s][^<>]*>
                    |(?<!\w)\([^)\s][^)]*\)|\|[^|\s][^|]*\|))
  | (?P<operator>=>|->|~>|!>|\?>|\*>|<->|\+\+|\|\||[+\-*/])
  | (?P<cardinality>[×^]\d+\w*)
  | (?P<modifier>@[A-Za-z_][\w-]*)
  | (?P<keyword>\bop\b)
  | (?P<number>\b\d+(?:\.\d+)?\b)
  | (?P<punct>[(),:{}\[\]])
""", re.X)
_GLYPH_KIND = {"[": "service", "{": "data", "<": "event", "(": "actor", "|": "store"}


def payload_runs(text: str) -> list:
    """A payload as styled runs (colour-coded like the code highlighter)."""
    runs, last = [], 0
    for m in _PAYLOAD_TOKEN.finditer(text):
        if m.start() > last:
            runs.append((text[last:m.start()], PAYLOAD_STYLE))
        role, tok = m.lastgroup, m.group()
        if role == "glyph":
            kind = _GLYPH_KIND[tok.lstrip("~*")[0]]
            style = (kind_color(kind), None, False)
        else:
            style = SYNTAX[role]
        runs.append((tok, style))
        last = m.end()
    if last < len(text):
        runs.append((text[last:], PAYLOAD_STYLE))
    return runs


def _put_runs(cv: Canvas, x, y, runs) -> int:
    """Draw styled runs from x; returns the x after them."""
    for text, style in runs:
        cv.put(x, y, text, style)
        x += len(text)
    return x


def _colour_tags(cv: Canvas, x, y, n, runs):
    """Re-colour a box's #N note tags (drawn in the label's colour) by note kind."""
    if not runs:
        return
    tx = x + 2 + len(node_label(n))
    for text, style in runs:
        if style:
            cv.put(tx, y + 1, text, style)
        tx += len(text)


def _draw_box(cv: Canvas, x, y, w, label, n):
    if n.kind == CHIP:
        tl, tr, bl, br, h, s = "╭", "╮", "╰", "╯", "┄", "┆"
    elif n.is_hole:
        tl, tr, bl, br, h, s = "┌", "┐", "└", "┘", "┄", "┆"
    elif n.is_mutable:
        tl, tr, bl, br, h, s = "┏", "┓", "┗", "┛", "━", "┃"
    elif KINDS.get(n.kind, {}).get("border") == "double":
        tl, tr, bl, br, h, s = "╔", "╗", "╚", "╝", "═", "║"
    elif KINDS.get(n.kind, {}).get("border") == "round":
        tl, tr, bl, br, h, s = "╭", "╮", "╰", "╯", "─", "│"
    else:
        tl, tr, bl, br, h, s = "┌", "┐", "└", "┘", "─", "│"
    border, text = node_styles(n)
    cv.put(x, y, tl + h * (w - 2) + tr, border)
    cv.put(x, y + 1, s + " ", border)
    cv.put(x + 2, y + 1, label.ljust(w - 4), text)
    if n.kind == CHIP:                          # a payload reads as the code it is
        _put_runs(cv, x + 2, y + 1, payload_runs(n.name))
    cv.put(x + w - 2, y + 1, " " + s, border)
    cv.put(x, y + 2, bl + h * (w - 2) + br, border)


# ---------------------------------------------------------------------------
# Document → sections → styled rows
# ---------------------------------------------------------------------------

NOTE_MODES = ("off", "markers", "callouts")
CALLOUT_TEXT = 24                               # callout box text width
NOTE_WIDTH = 76                                 # notes list wrap width
ALL_DEPTH = 99                                  # --depth all


def _walk(g):
    """g, then its expansions (and theirs), breadth-first in document order."""
    queue = [g]
    while queue:
        cur = queue.pop(0)
        yield cur
        queue += list(cur.expansions.values())


def with_chips(g, payloads: bool = False, triggers=()):
    """The graph as the graph view draws it: each `: payload` as a chip splitting
    its edge (src → chip → dst), and each trigger whose event and owner are both
    here as an edge event ⇢ owner. Returns g itself when there is nothing to add."""
    extra = [t for t in triggers if t.event in g.nodes and t.owner in g.nodes]
    if not extra and not (payloads and any(e.payload for e in g.edges)):
        return g
    nodes, edges = dict(g.nodes), []
    for k, e in enumerate(g.edges):
        if payloads and e.payload and e.src != e.dst:
            cid = f"\0p{k}"
            nodes[cid] = render.Node(id=cid, name=e.payload, kind=CHIP, attrs={"src": e.src})
            edges += [replace(e, dst=cid, label=None, payload=None),
                      replace(e, src=cid, payload=None)]
        else:
            edges.append(e)
    seen = set()
    for t in extra:
        if (t.event, t.owner) not in seen:
            seen.add((t.event, t.owner))
            edges.append(render.Edge(src=t.event, dst=t.owner, kind="trigger"))
    return replace(g, nodes=nodes, edges=edges)


def sections(g, depth: int, title: str = "", level: int = 0, tags: dict | None = None,
             payloads: bool = False, triggers=()):
    """Yield (title, graph, canvas) for the graph and its expansions up to depth.
    `payloads` draws each flow's payload as a chip on its edge; `triggers` (the
    document's event → state triggers) draw as dashed edges event ⇢ owner."""
    show = set(g.expansions) if level < depth else set()
    collapsed = set(g.expansions) - show
    yield title, g, layout(with_chips(g, payloads, triggers), show, collapsed, tags)
    for nid in g.expansions:
        if nid in show:
            what = ("state machine" if getattr(g.expansions[nid], "role", "") == "state"
                    else ":= { … }")
            sub_title = f"{node_label(g.nodes[nid])} {what}"
            if title:
                sub_title = f"{title}  ›  {sub_title}"
            yield from sections(g.expansions[nid], depth, sub_title, level + 1, tags,
                                payloads, triggers)


def trigger_lines(g):
    """`<Paid> ⇢ {Order}: Open → Settled` for each event wired to a transition."""
    nodes = {}
    for cur in _walk(g):
        nodes.update(cur.nodes)

    def lab(nid):
        return node_label(nodes[nid]) if nid in nodes else nid

    return [f"  {lab(t.event)} ⇢ {lab(t.owner)}: {lab(t.src)} → {lab(t.dst)}"
            for t in getattr(g, "triggers", [])]


def payload_lines(g):
    return [f"  {edge_text(g, e)} : {e.payload}" for e in g.edges if e.payload]


def all_payload_lines(g):
    return [line for cur in _walk(g) for line in payload_lines(cur)]


# Notes are tagged #N either way; colour tells a block comment (own lines above
# a statement, ui.note_block) from an inline one (trailing it, ui.note_inline).


def note_index(g) -> dict:
    """{node id: [(number, text, kind, edges), …]}, numbered in document order (top
    level first, then expansions). A node's block comments (about the component)
    merge into one note; each inline comment (about its line) stays its own note
    and keeps the (src, dst, kind) of the flows that line drew."""
    out, num = {}, 0
    for cur in _walk(g):
        for n in getattr(cur, "notes", []):
            kind = getattr(n, "kind", "block")
            entries = out.setdefault(n.node, [])
            block = next((i for i, e in enumerate(entries) if e[2] == "block"), None)
            if kind == "block" and block is not None:
                b = entries[block]
                entries[block] = (b[0], f"{b[1]} · {n.text}", "block", ())
                continue
            num += 1
            entries.append((num, n.text, kind, tuple(getattr(n, "edges", ()) or ())))
    return out


def node_notes(entries) -> list:
    """The notes drawn on the node itself: its block note, and inline notes from
    lines that drew no flow (a branch or a bare node line is about that node)."""
    return [e for e in entries if e[2] == "block" or not e[3]]


def edge_notes(idx: dict) -> dict:
    """(src, dst, kind) → [(number, text)]: inline notes about a flow's line."""
    out = {}
    for entries in idx.values():
        for num, text, kind, edges in entries:
            if kind == "inline":
                for key in edges:
                    out.setdefault(key, []).append((num, text))
    return out


def note_tag(entries) -> str:
    """Tags as text: `#1`, or `#1 #2`."""
    return " ".join(f"#{e[0]}" for e in entries)


def note_tag_runs(entries) -> list:
    """The tags as styled runs, each in its note kind's colour."""
    runs = []
    for e in entries:
        runs += [(" ", None), (f"#{e[0]}", NOTE_STYLE[e[2]])]
    return runs


def note_rows(idx: dict, width: int = NOTE_WIDTH):
    """The notes list: `#N text`, wrapped under its tag, in its kind's colour."""
    rows = []
    for num, text, kind, _edges in sorted(e for entries in idx.values() for e in entries):
        tag = f"#{num} "
        for k, ln in enumerate(textwrap.wrap(text, max(width - len(tag), 20)) or [""]):
            rows.append([(tag if k == 0 else " " * len(tag), NOTE_STYLE[kind]),
                         (ln, NOTE_STYLE[kind] if kind == "inline" else NOTE_TEXT_STYLE)])
    return rows


def compose(g, depth: int, payloads: bool, notes: str = "off", triggers: bool = True):
    """The whole drawing as rows of (text, style) runs, plus its width. Each
    section's canvas is centred within the widest section. `payloads` draws each
    flow's payload as a chip on its edge; `triggers` wires each event to the owner
    of the state machine it drives (and lists the transitions below). Notes (any
    mode but "off") tag commented boxes `#N` and list the notes below."""
    idx = note_index(g) if notes != "off" else {}
    tags = {nid: note_tag_runs(node_notes(entries)) for nid, entries in idx.items()
            if node_notes(entries)}
    for key, notes_ in edge_notes(idx).items():    # inline notes ride their flow's edge
        tags[key] = [(" ".join(f"#{num}" for num, _t in notes_), NOTE_STYLE["inline"])]
    trig_edges = getattr(g, "triggers", []) if triggers else []
    parts = list(sections(g, depth, tags=tags, payloads=payloads, triggers=trig_edges))
    width = max([cv.w for _, _, cv in parts] + [len(t) + 6 for t, _, _ in parts if t] + [0])
    rows = []
    for title, _sg, cv in parts:
        if title:
            rows += [[], [(f"── {title} ──", TITLE_STYLE)], []]
        pad = (width - cv.w) // 2
        for row in cv.rows():
            rows.append(([(" " * pad, None)] if pad and row else []) + row)
    trig = trigger_lines(g) if triggers else []
    if trig:
        rows += [[], [("── triggers ──", TITLE_STYLE)], []]
        rows += [[(t, LABEL_STYLE)] for t in trig]
    if idx:
        rows += [[], [("── notes ──", TITLE_STYLE)], []] + note_rows(idx)
    return rows, max([width] + [row_len(r) for r in rows])


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


def _tree_rows(g, depth: int, level: int = 0, base: int = 0, rows=None, wires=None,
               triggers: bool = True):
    """Flatten a graph (and its expansions, to `depth`) into outline TreeRows and
    collect every flow as a wire (src, dst, kind, src_path, dst_path)."""
    rows = [] if rows is None else rows
    wires = [] if wires is None else wires
    wires += [(e.src, e.dst, e.kind, getattr(e, "src_path", None), getattr(e, "dst_path", None))
              for e in g.edges]
    for t in (getattr(g, "triggers", []) if triggers else []):   # events → their states
        wires.append((t.event, t.dst if t.level <= depth else t.owner, "trigger", None, None))
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
            _tree_rows(sub, depth, level + 1, d + 1, rows, wires, triggers)
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
    return rows, wires


ARROW_LEGEND = (("->", "call"), ("~>", "async"), ("=>", "produces"), ("!>", "error"),
                ("?>", "maybe"), ("*>", "broadcast"), ("<->", "both ways"))
LEGEND_WIDTH = 100                              # --once legend wrap width


def _stroke_sample(kind: str) -> str:
    return {"heavy": "━", "double": "═", "dashed": "╌", "dotted": "┄"}.get(_stroke(kind), "─")


def _lane_colour(kind: str, src_kind: str) -> str:
    """A lane's colour: the arrow's own colour when it has one (!> ?> ~> ]>[),
    else its source node's kind colour."""
    return EDGE_COLOR[kind] if kind in EDGE_COLOR else kind_color(src_kind)


def tree_legend(triggers: bool = True, payloads: bool = False):
    """Legend rows for the tree + wires view: relations, then lanes by arrow type.
    Markers whose lanes take their source's colour are drawn neutral."""
    dim, mid = (GREY["dim"], None, False), (GREY["mid"], None, False)
    rel = [("tree   ", dim), ("─", TREE_STYLE), (" contains  ", mid)]
    for glyph, word in (("&", "has"), ("*", "spawns"), ("?", "when"), ("$", "from data"),
                        ("@", "attached"), ("!", "alerts"), ("=", "gathers"),
                        ("_", "one of"), ("(N)", "weight")):
        rel += [(glyph, REL_STYLE), (f" {word}  ", mid)]
    wires = [("wires  ", dim)]
    for kind, word in ARROW_LEGEND + ((("trigger", "trigger"),) if triggers else ()):
        colour = EDGE_COLOR.get(kind, EDGE_DEFAULT)
        wires += [(SOURCE_MARK.get(kind, "●") + _stroke_sample(kind), (colour, None, False)),
                  (f" {word}  ", mid)]
    wires += [("◀", (GREY["light"], None, True)), (" target  ", mid),
              ("─│─", dim), (" crossing  ", mid),
              ("■", (EDGE_DEFAULT, None, False)), (" lane: its source's colour  ", mid)]
    if payloads:
        wires += [("┄┆{…}┆", dim), (" payload, on its target row", mid)]
    return [rel, wires]


def wrap_legend(row, cols: int):
    """Wrap a legend row (a label run, then (marker, word) run pairs) to `cols`,
    breaking only between entries; continuation lines are indented under the label."""
    label, items = row[0], [row[i:i + 2] for i in range(1, len(row), 2)]
    indent = (" " * len(label[0]), None)
    out, cur = [], [label]
    for item in items:
        if row_len(cur) + row_len(item) > cols and len(cur) > 1:
            out.append(cur)
            cur = [indent]
        cur = cur + item
    out.append(cur)
    return out


def graph_legend(triggers: bool = True, payloads: bool = False):
    """Legend row for the graph view: the stroke of each arrow type, then the
    trigger edge and the payload chip when they are shown."""
    dim, mid = (GREY["dim"], None, False), (GREY["mid"], None, False)
    row = [("arrows ", dim)]
    for kind, word in ARROW_LEGEND:
        colour = EDGE_COLOR.get(kind, EDGE_DEFAULT)
        row += [(_stroke_sample(kind) * 2 + "▼", (colour, None, False)), (f" {word}  ", mid)]
    if triggers:
        row += [(_stroke_sample("trigger") * 2 + "▼", edge_style("trigger")), (" trigger  ", mid)]
    if payloads:
        row += [("╭┄{…}┄╯", dim), (" payload", mid)]       # the chip's corners, on one row
    return row


KEY_LEGEND = (("t", "tree/graph"), ("n", "notes"), ("e", "triggers"), ("s", "spacing"),
              ("d", "depth"), ("p", "payloads"), ("l", "lint"), ("c", "centre"),
              ("g", "home"), ("r", "reload"), ("q", "quit"))


def keys_legend(state):
    """The hotkeys row for a ViewState; toggles that are on are shown bright."""
    dim, mid = (GREY["dim"], None, False), (GREY["mid"], None, False)
    on = {"t": state.tree, "e": state.show_triggers, "s": state.spaced,
          "p": state.payloads, "l": state.show_lint, "n": state.notes != "off"}
    row = [("keys   ", dim)]
    for key, word in KEY_LEGEND:
        bright = on.get(key)
        if key == "n":
            word = f"notes:{state.notes}"
        elif key == "d":
            word = f"depth:{'all' if state.depth >= ALL_DEPTH else state.depth}"
            bright = state.depth > 0
        row += [(key, KEY_STYLE),
                (f" {word}  ", (GREY["light"], None, bright) if bright else mid)]
    return row


def compose_tree(g, depth: int, triggers: bool = True, spaced: bool = True,
                 notes: str = "off", payloads: bool = False):
    """The drawing as outline rows with a lane gutter; same return shape as compose().
    `triggers`: draw event → state lanes. `spaced`: a blank row between top-level
    units (a root with parts, or the first root after one). `notes`: "markers" tags
    commented rows `#N` and lists the notes below; "callouts" draws them as boxes in
    a left margin, each tied to its row by a leader. `payloads`: draw each flow's
    payload as a chip in a right margin, on its target row (the mirror of the
    callouts); any that can't be placed are listed below."""
    idx = note_index(g) if notes != "off" else {}
    rows, wires = _tree_rows(g, depth, triggers=triggers)
    if not rows:
        return [], 0
    if spaced:
        rows = _space_units(rows)
    # Block notes are about a component: tagged on its row, called out on the
    # left. Inline notes are about their line: they trail it on the right, after
    # the payload the line carries — as in the source.
    blocks = {nid: [e for e in es if e[2] == "block"] for nid, es in idx.items()}
    blocks = {nid: es for nid, es in blocks.items() if es}
    cv = Canvas()
    out = _draw_outline(cv, rows, blocks)
    lanes = _collect_lanes(cv, wires, out)
    placed = _pack_lanes(lanes, max(out.ends) + 3, out.node)
    _draw_lanes(cv, placed, out.ends)
    trailing = _trailing_notes(idx) if notes != "off" else {}
    drawn = _draw_right_margin(cv, lanes, placed, out, _payload_of(g) if payloads else {},
                               trailing, notes)
    out_rows, width = list(cv.rows()), cv.w
    if notes == "callouts" and out.tagged:
        out_rows, width = _with_callouts(out_rows, blocks, out.tagged)
    extra = _extras(g, idx, notes, payloads, drawn)
    out_rows += extra
    return out_rows, max([width] + [row_len(r) for r in extra])


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
        if rows[y] is None:
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
    node: dict                                  # node id → its node (first row's)


def _draw_outline(cv: Canvas, rows, idx: dict) -> _Outline:
    """The outline: rails, relation, label, #N tag and (for a state) the triggers
    that lead into it, one row each."""
    out = _Outline([], {}, {}, {}, {})
    stack = []
    for y, (row, guide) in enumerate(zip(rows, _guides(rows))):
        if row is None:
            out.ends.append(0)
            continue
        n, rel = row.node, row.rel
        stack = stack[:row.depth] + [n.name]
        out.chain_at[y] = tuple(stack)
        x = 0
        if row.depth:
            cv.put(0, y, guide, TREE_STYLE)
            x = len(guide)
            if rel and rel != "─":
                cv.put(x, y, rel, REL_STYLE)
                x += len(rel)
            else:
                cv.put(x, y, "─", TREE_STYLE)
                x += 1
            x += 1
        label = node_label(n) + (" ▸" if row.collapsed else "")
        _border, text = node_styles(n)
        cv.put(x, y, label, (text[0], None, True))
        x += len(label)
        if n.id in idx and n.id not in out.tagged:  # `#N` on the node's first row
            tag = " " + note_tag(idx[n.id])
            tx = x
            for run, style in note_tag_runs(idx[n.id]):
                cv.put(tx, y, run, style)
                tx += len(run)
            x += len(tag)
            out.tagged[n.id] = y
        if n.kind == "state":                   # the triggers that lead into this state
            into = sorted({e.label for e in row.graph.edges if e.dst == n.id and e.label})
            if into:
                cv.put(x + 1, y, " ".join(into), LABEL_STYLE)
                x += 1 + len(" ".join(into))
        out.ends.append(x)
        out.by_id.setdefault(n.id, []).append(y)
        out.node.setdefault(n.id, n)
    return out


def _collect_lanes(cv: Canvas, wires, out: _Outline):
    """One lane (lo, hi, src, dst, kind, src rows, dst rows) per distinct wire,
    over every row where either end occurs, shortest first; a self-loop is marked
    ↺ on its row instead."""
    def at(nid, path):
        ys = out.by_id.get(nid, [])
        if path:
            ys = [y for y in ys if out.chain_at[y][-len(path):] == tuple(path)]
        return ys

    lanes, seen = [], set()
    for wire in wires:
        if wire in seen:
            continue
        seen.add(wire)
        src, dst, kind, spath, dpath = wire
        sy, dy = at(src, spath), at(dst, dpath)
        if not sy or not dy:
            continue
        if src == dst and not spath and not dpath:
            for y in sy:
                cv.put(out.ends[y] + 1, y, "↺", edge_style(kind))
            continue
        ys = sorted(set(sy) | set(dy))
        lanes.append((ys[0], ys[-1], src, dst, kind, sy, dy))
    lanes.sort(key=lambda lane: (lane[1] - lane[0], lane[0]))
    return lanes


def _pack_lanes(lanes, left: int, node: dict):
    """Give each lane a gutter column (interval-packed) and its style:
    (x, lo, hi, src rows, dst rows, kind, style)."""
    cols, placed = [], []
    for lo, hi, src, _dst, kind, sy, dy in lanes:
        x = left + _first_fit(cols, lo, hi) * LANE_GAP
        style = (_lane_colour(kind, node[src].kind), None, False)
        placed.append((x, lo, hi, sy, dy, kind, style))
    return placed


def _draw_lanes(cv: Canvas, placed, ends):
    """Verticals first; then each row's runs out to the lanes it taps, hopping
    (─│─) over lanes it merely crosses, so a joint (┤ ┴ ┬ ┼) only ever appears
    where a lane is actually tapped."""
    verticals = set()
    for x, lo, hi, _s, _d, kind, style in placed:
        if hi > lo:
            cv.path([(x, lo), (x, hi)], kind, style)
            verticals |= {(x, y) for y in range(lo, hi + 1)}

    taps = {}                                   # y → [(lane x, kind, style, role)]
    for x, lo, hi, sy, dy, kind, style in placed:
        for y in sy:
            taps.setdefault(y, []).append((x, kind, style, "src"))
        for y in dy:
            taps.setdefault(y, []).append((x, kind, style, "dst"))

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
        for x1, kind, style, role in order:
            if role == "dst":
                into |= cv.run(ends[y] + 2, x1, y, kind, style, hops)
        nearest = min((t[0] for t in row_taps if t[3] == "dst"), default=-1)
        into = {cell for cell in into if cell[0] <= nearest}
        for x1, kind, style, role in order:
            if role == "src":
                x0 = ends[y] + (2 if kind == "<->" else 1)
                cv.run(x0, x1, y, kind, style, hops, fixed=into)
        for x1, kind, style, role in order:
            both = kind == "<->" and role == "src"
            if role == "src":
                heads.append((x1, y, SOURCE_MARK.get(kind, "●"), style))
            if role == "dst" or both:
                heads.append((ends[y] + 1, y, "◀", style))
    for x, y, ch, st in heads:
        cv.put(x, y, ch, st)


def _payload_of(g) -> dict:
    """(src, dst, kind) → the payload its flow carries, across g and its expansions."""
    out = {}
    for sub in _walk(g):
        for e in sub.edges:
            if e.payload:
                out.setdefault((e.src, e.dst, e.kind), e.payload)
    return out


def _trailing_notes(idx: dict) -> dict:
    """Inline notes by what their line drew: (src, dst, kind) for a flow line, the
    node id for a line that only placed a node → [(number, text)]."""
    out = {}
    for nid, entries in idx.items():
        for num, text, kind, edges in entries:
            if kind == "inline":
                for key in (edges or (nid,)):
                    out.setdefault(key, []).append((num, text))
    return out


def _draw_right_margin(cv: Canvas, lanes, placed, out: _Outline, payload_of: dict,
                       trailing: dict, notes: str) -> set:
    """The right margin, the mirror of the note callouts: on each flow's target row
    the payload it carries (a ┆chip┆) and the inline comment from its line; on a
    node's row the inline comment of the line that placed it. A dotted leader ties
    each to the row's rightmost tap, hopping (┄│┄) over lanes it crosses. Comments
    show as `#N` (markers) or their text (callouts). Returns the flow keys whose
    payloads were drawn."""
    margin = max([x for x, *_ in placed] + [max(out.ends) - 1]) + 3
    rightmost, chips, notes_at, drawn = {}, {}, {}, set()
    for (_lo, _hi, src, dst, kind, _sy, _dy), (x, _l, _h, sy, dy, _k, _st) in zip(lanes, placed):
        for y in list(sy) + list(dy):
            rightmost[y] = max(rightmost.get(y, 0), x)
        key = (src, dst, kind)
        text = payload_of.get(key)
        for y in dy:
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
    leader, border = (GREY["dim"], None, False), (GREY["dim"], None, False)
    for y in sorted(set(chips) | set(notes_at)):
        if not chips.get(y) and not notes_at.get(y):
            continue
        first = rightmost.get(y, out.ends[y]) + 1
        for x in range(first, margin - 1):
            if (x, y) not in cv.lines and (x, y) not in cv.text:
                cv.put(x, y, "┄", leader)
        x = margin - 1
        if chips.get(y):
            body = " · ".join(chips[y])
            cv.put(x, y, "┆ ", border)
            x = _put_runs(cv, x + 2, y, payload_runs(body))
            cv.put(x, y, " ┆", border)
            x += 3
        for num, text in sorted(notes_at.get(y, ())):
            note = f"#{num}" if notes == "markers" else f"# {text}"
            cv.put(x, y, note, NOTE_STYLE["inline"])
            x += len(note) + 2
    return drawn


def _extras(g, idx: dict, notes: str, payloads: bool, drawn: frozenset = frozenset()):
    """The lists under the tree: payloads not drawn as chips (when shown), then
    notes (markers mode)."""
    extra = []
    pl = [f"  {edge_text(sub, e)} : {e.payload}" for sub in _walk(g) for e in sub.edges
          if e.payload and (e.src, e.dst, e.kind) not in drawn] if payloads else []
    if pl:
        extra += [[], [("── payloads ──", TITLE_STYLE)], []] + [[(p, PAYLOAD_STYLE)] for p in pl]
    if notes == "markers" and idx:
        extra += [[], [("── notes ──", TITLE_STYLE)], []] + note_rows(idx)
    return extra


def _with_callouts(rows, idx: dict, tagged: dict):
    """Prefix the tree rows with a left margin of note boxes. A box sits level with
    its row when there is room, else slides down; its leader runs right, up to the
    row, and into it. Leaders get their own columns (interval-packed)."""
    boxes = []                                  # (row, top, lines, kind)
    free = 0
    anchors = set(tagged.values())
    for nid, y in sorted(tagged.items(), key=lambda kv: kv[1]):
        for num, text, kind, _edges in idx[nid]:
            # A block note is a framed box (up to 3 lines); an inline note stays
            # bare (two lines at most), like the trailing comment it came from.
            limit = 3 if kind == "block" else 2
            lines = textwrap.wrap(f"#{num} {text}", CALLOUT_TEXT) or [""]
            if len(lines) > limit:
                lines = lines[:limit]
                lines[-1] = lines[-1][:CALLOUT_TEXT - 1] + "…"
            top = max(y, free)
            while top != y and top in anchors:  # a slid box never starts on another
                top += 1                        # note's row: its runs would merge
            boxes.append((y, top, lines, kind))
            free = top + len(lines) + (1 if kind == "block" else 0)
    cols = []                                   # leader columns: list of (lo, hi)
    leader_col = [None if top == y else _first_fit(cols, y, top) for y, top, _l, _n in boxes]
    box_w = CALLOUT_TEXT + 4
    margin = box_w + 2 + 2 * len(cols) + 2
    mc = Canvas()
    for (y, top, lines, kind), c in zip(boxes, leader_col):
        k = len(lines)
        style = border = NOTE_STYLE[kind]       # colour tells the kinds apart
        for j, ln in enumerate(lines):
            if kind == "inline":                # bare, like a trailing comment
                lside, rside = "  ", "  "
            elif k == 1:
                lside, rside = "│ ", " │"
            else:
                lside, rside = {0: ("╭ ", " ╮"), k - 1: ("╰ ", " ╯")}.get(j, ("│ ", " │"))
            mc.put(0, top + j, lside, border)
            mc.put(2, top + j, ln.ljust(CALLOUT_TEXT), style)
            mc.put(box_w - 2, top + j, rside, border)
    # Leaders: verticals first, then horizontal runs that hop (─│─) over any other
    # leader's vertical, so two leaders never read as joined.
    start, end = box_w + 1, margin - 2          # a gap before the tree: not a guide
    runs, verticals = [], set()
    for (y, top, _lines, kind), c in zip(boxes, leader_col):
        stroke = "?>" if kind == "inline" else "->"     # inline: a dotted leader
        if c is None:
            runs.append((start, end, y, None, stroke, NOTE_STYLE[kind]))
            continue
        cx = box_w + 2 + 2 * c
        mc.path([(cx, top), (cx, y)], stroke, NOTE_STYLE[kind])
        verticals |= {(cx, yy) for yy in range(min(y, top), max(y, top) + 1)}
        runs += [(start, cx, top, cx, stroke, NOTE_STYLE[kind]),
                 (cx, end, y, cx, stroke, NOTE_STYLE[kind])]
    # Leaders that end on the same row (a node with a block and an inline note)
    # join there (┬ ┴) instead of hopping over each other.
    ends_at = {(box_w + 2 + 2 * c, y) for (y, _t, _l, _k), c in zip(boxes, leader_col)
               if c is not None}
    for x0, x1, yy, own, stroke, colour in runs:
        mc.run(x0, x1, yy, stroke, colour,
               hops=lambda x, _y=yy, _own=own: ((x, _y) in verticals and x != _own
                                               and (x, _y) not in ends_at))
    margin_rows = list(mc.rows())
    height = max(len(rows), len(margin_rows))
    out = []
    for y in range(height):
        left = margin_rows[y] if y < len(margin_rows) else []
        pad = margin - row_len(left)
        tree = rows[y] if y < len(rows) else []
        out.append(left + ([(" " * pad, None)] if tree and pad > 0 else []) + tree)
    return out, margin + max((row_len(r) for r in rows), default=0)


def doc_title(text: str) -> str:
    """A document's title: the first `# comment` line of its leading comment block
    (`#!` mode lines and `#&` lines skipped); "" when the document doesn't open
    with one."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") and not line.startswith(("#!", "#&")):
            return line.lstrip("#").strip()
        if line and not line.startswith("#!"):
            return ""
    return ""


def _call(fn, text, dialect):
    return fn(text, dialect=dialect) if dialect is not None else fn(text)


def run_lint(text, dialect=None):
    try:
        return _call(lint.lint, text, dialect).diagnostics
    except Exception as exc:   # a linter crash must not take the view down
        return [lint.Diagnostic("error", 0, "lint-crash", f"{type(exc).__name__}: {exc}")]


# ---------------------------------------------------------------------------
# ANSI
# ---------------------------------------------------------------------------

def _sgr(style) -> str:
    fg, bg, bold = style
    codes = []
    if bold:
        codes.append("1")
    for base, colour in ((38, fg), (48, bg)):
        if colour:
            codes.append(f"{base};2;{int(colour[1:3], 16)};{int(colour[3:5], 16)};{int(colour[5:7], 16)}")
    return f"\x1b[{';'.join(codes)}m" if codes else ""


def ansi(row, colour: bool = True) -> str:
    if not colour:
        return "".join(t for t, _ in row)
    out = []
    for t, st in row:
        if st:
            out.append(_sgr(st) + t + "\x1b[0m")
        else:
            out.append(t)
    return "".join(out)


def clip(row, start: int, width: int):
    """Slice a row of runs to the columns [start, start + width)."""
    out, x = [], 0
    for t, st in row:
        a, b = max(start - x, 0), min(start + width - x, len(t))
        if a < b:
            out.append((t[a:b], st))
        x += len(t)
        if x >= start + width:
            break
    return out


def row_len(row) -> int:
    return sum(len(t) for t, _ in row)


# ---------------------------------------------------------------------------
# --once
# ---------------------------------------------------------------------------

def once(path: Path, depth: int, payloads: bool, do_lint: bool,
         dialect=None, colour: bool = False, tree: bool = False,
         triggers: bool = True, spaced: bool = True, notes: str = "off") -> int:
    use_dialect(dialect)
    text = path.read_text()
    g = _call(render.parse_document, text, dialect)
    rows, _w = (compose_tree(g, depth, triggers, spaced, notes, payloads) if tree
                else compose(g, depth, payloads, notes, triggers))
    out = [ansi(r, colour) for r in rows]
    if tree:
        out += [""] + [ansi(ln, colour) for r in tree_legend(triggers, payloads)
                       for ln in wrap_legend(r, LEGEND_WIDTH)]
    out.append("")
    out.append(f"{path.name}: {len(g.nodes)} nodes, {len(g.edges)} edges, "
               f"{len(g.expansions)} expansions")
    status = 0
    if do_lint:
        diags = run_lint(text, dialect)
        if diags:
            out.extend(d.format() for d in diags)
        else:
            out.append("lint: OK")
        status = 1 if any(d.severity == "error" for d in diags) else 0
    print("\n".join(out))
    return status


# ---------------------------------------------------------------------------
# Live view — ViewState is the whole app minus the terminal (tests drive it);
# tui() is the stdlib alternate-screen loop around it.
# ---------------------------------------------------------------------------

DEPTHS = (0, 1, ALL_DEPTH)
LINT_ROWS = 8
SCROLL_X = 4                                    # columns per left / right key
POLL_S = 0.3                                    # how often to stat the file
TICK_S = 0.1                                    # key wait per loop turn
READ_BYTES = 64                                 # bytes per key read


class ViewState:
    def __init__(self, path: Path, depth: int = 1, payloads: bool = False,
                 do_lint: bool = True, dialect=None, tree: bool = False,
                 triggers: bool = True, spaced: bool = True, notes: str = "off"):
        self.path = path
        self.tree = tree
        self.notes = notes
        self.show_triggers = triggers
        self.spaced = spaced
        self.depth = depth
        self.payloads = payloads
        self.show_lint = do_lint
        self.dialect = dialect
        use_dialect(dialect)
        self.stamp = None
        self.text = None
        self.graph = None
        self.error = None
        self.diags = []
        self.updated = ""
        self.title = ""
        self.sx = self.sy = 0          # scroll offsets (only used when it overflows)
        self._recentre = False         # centre the overflowing drawing on the next frame
        self._vh = 1                   # viewport height of the last frame (a page)
        self._rows, self._width = [], 0

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
        self.title = doc_title(text)
        try:
            self.graph = _call(render.parse_document, text, self.dialect)
            self.error = None
        except Exception as exc:       # keep the last good graph on screen
            self.error = f"parse failed: {type(exc).__name__}: {exc}"
        self.diags = run_lint(text, self.dialect)
        self.updated = time.strftime("%H:%M:%S")
        self._recompose()
        return True

    def _recompose(self):
        if self.graph is None:
            self._rows, self._width = [], 0
        else:
            self._rows, self._width = (
                compose_tree(self.graph, self.depth, self.show_triggers, self.spaced,
                             self.notes, self.payloads)
                if self.tree else compose(self.graph, self.depth, self.payloads, self.notes,
                                          self.show_triggers))

    # -- keys ----------------------------------------------------------------

    def key(self, k: str, page: int | None = None) -> bool:
        """Apply a key. Returns True when the view changed. Paging moves by
        `page` rows (default: the last frame's viewport height)."""
        page = self._vh if page is None else page
        if k == "d":                   # the next larger depth, wrapping to the first
            self.depth = next((d for d in DEPTHS if d > self.depth), DEPTHS[0])
            self._recompose()
        elif k == "t":
            self.tree = not self.tree
            self.sx = self.sy = 0
            self._recentre = False
            self._recompose()
        elif k == "n":
            self.notes = NOTE_MODES[(NOTE_MODES.index(self.notes) + 1) % len(NOTE_MODES)]
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
        elif k in ("home", "g"):
            self.sx = self.sy = 0
            self._recentre = False
        elif k == "c":
            self._recentre = True
        else:
            return False
        return True

    # -- frame ---------------------------------------------------------------

    def _footer_rows(self, cols: int):
        """Everything under the drawing: the kind-legend rule, the view's legend,
        the keys, then the parse error and lint panel."""
        rows = []
        if self.error:
            rows.append([(self.error, (SEVERITY_COLOR["error"], None, True))])
        if self.show_lint:
            if not self.diags:
                rows.append([("lint: OK", (OK_COLOR, None, False))])
            shown = self.diags[:LINT_ROWS - len(rows)]
            for d in shown:
                colour = SEVERITY_COLOR.get(d.severity, GREY["mid"])
                rows.append([(f"{d.severity}:{d.line}", (colour, None, True)),
                             (f" {d.rule}: {d.message}", None)])
            if len(self.diags) > len(shown):
                rows[-1] = [(f"… {len(self.diags) - len(shown) + 1} more (view.py --once)",
                             (GREY["mid"], None, False))]
        legend = (tree_legend(self.show_triggers, self.payloads) if self.tree
                  else [graph_legend(self.show_triggers, self.payloads)])
        rows[0:0] = [ln for r in legend + [keys_legend(self)] for ln in wrap_legend(r, cols)]
        rows.insert(0, self._legend_rule(cols))
        return [clip(r, 0, cols) for r in rows]

    def _legend_rule(self, cols: int):
        """The rule above the lint panel, carrying the node-type colour legend."""
        rule = (GREY["dim"], None, False)
        row = [("── ", rule)]
        for kind, spec in KINDS.items():
            word = spec.get("legend", kind)
            row += [("■ ", (spec["color"], None, False)), (f"{word} ", (GREY["mid"], None, False))]
        row.append(("─" * max(cols - row_len(row), 0), rule))
        return row

    def _bar(self, cols: int):
        d = "all" if self.depth >= ALL_DEPTH else str(self.depth)
        g = self.graph
        summary = f"{len(g.nodes)} nodes · {len(g.edges)} edges" if g is not None else "no graph"
        n_err = sum(1 for x in self.diags if x.severity == "error")
        n_warn = sum(1 for x in self.diags if x.severity == "warn")
        left = [(f" {self.path.name} ", BAR_NAME_STYLE)]
        if self.title:
            left.append((f" {self.title} ·", BAR_NAME_STYLE))
        view = "tree" if self.tree else "graph"
        left.append((f" {summary} · {view} · depth {d} · {self.updated} ", BAR_STYLE))
        if n_err or n_warn:
            left.append((f"{n_err}E {n_warn}W ", (SEVERITY_COLOR["error" if n_err else "warn"],
                                                  BAR_STYLE[1], True)))
        return clip(left + [(" " * max(cols - row_len(left), 0), BAR_STYLE)], 0, cols)

    def frame(self, cols: int, rows: int):
        """Exactly `rows` rows of styled runs for a cols×rows terminal: the status bar,
        the drawing (centred while it fits, scrolled when it doesn't), the footer."""
        footer = self._footer_rows(cols)
        vh = self._vh = max(rows - 1 - len(footer), 1)
        body, W, H = self._rows, self._width, len(self._rows)
        if self.graph is None and not self.error:
            body = [[("waiting for " + str(self.path), (GREY["mid"], None, False))]]
            W, H = row_len(body[0]), 1

        def axis(size, view, off):
            if size <= view:
                return (view - size) // 2, 0
            if self._recentre:
                off = (size - view) // 2
            return 0, max(0, min(off, size - view))

        pad_x, self.sx = axis(W, cols, self.sx)
        pad_y, self.sy = axis(H, vh, self.sy)
        self._recentre = False
        out = [self._bar(cols)]
        for y in range(vh):
            src = y - pad_y + self.sy
            if 0 <= src < H:
                row = clip(body[src], self.sx, cols - pad_x)
                out.append(([(" " * pad_x, None)] if pad_x and row else []) + row)
            else:
                out.append([])
        out += footer
        return out[:rows]


_ESCAPES = {
    "\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
    "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left",
    "\x1b[5~": "pgup", "\x1b[6~": "pgdn", "\x1b[H": "home", "\x1b[1~": "home",
}


def parse_keys(data: str):
    i = 0
    while i < len(data):
        for seq, name in _ESCAPES.items():
            if data.startswith(seq, i):
                yield name
                i += len(seq)
                break
        else:
            ch = data[i]
            i += 1
            if ch == "\x1b":
                continue               # a lone / unknown escape
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
        out.write("\x1b[?1049h\x1b[?25l")
        state.reload(force=True)
        dirty, last_poll = True, 0.0
        while True:
            now = time.monotonic()
            if now - last_poll >= POLL_S:
                last_poll = now
                dirty |= state.reload()
            if resized[0]:
                resized[0], dirty = False, True
            cols, rows = shutil.get_terminal_size()
            if dirty:
                frame = state.frame(cols, rows)
                out.write("\x1b[H" + "\r\n".join(ansi(r) + "\x1b[K" for r in frame) + "\x1b[J")
                out.flush()
                dirty = False
            ready, _, _ = select.select([fd], [], [], TICK_S)
            if ready:
                for k in parse_keys(os.read(fd, READ_BYTES).decode(errors="ignore")):
                    if k == "quit":
                        return
                    dirty |= state.key(k)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        out.flush()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _depth_arg(text: str) -> int:
    if text == "all":
        return ALL_DEPTH
    try:
        depth = int(text)
    except ValueError:
        depth = -1
    if depth < 0:
        raise argparse.ArgumentTypeError(f"expected a number >= 0 or 'all', got {text!r}")
    return depth


def main() -> int:
    ap = argparse.ArgumentParser(description="Live terminal view of a Sigil graph.")
    ap.add_argument("file", type=Path)
    ap.add_argument("--depth", type=_depth_arg, default=1, help="expansion depth: N or 'all'")
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
    ap.add_argument("--tree", action="store_true",
                    help="tree + wires: the composition tree as an outline, flows as lanes")
    ap.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    ap.add_argument("--theme", default=None,
                    help="colour theme: a name in themes/ or a .yaml path (default: $SIGIL_THEME or sigil)")
    a = ap.parse_args()
    try:
        use_theme(a.theme)
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
    tty_out = sys.stdout.isatty()
    if a.once or not tty_out or not sys.stdin.isatty():
        colour = a.color == "always" or (a.color == "auto" and tty_out)
        return once(a.file, a.depth, a.payloads, not a.no_lint, dialect, colour, a.tree,
                    not a.no_triggers, not a.compact, a.notes)
    tui(ViewState(a.file, a.depth, a.payloads, not a.no_lint, dialect, a.tree,
                  not a.no_triggers, not a.compact, a.notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
