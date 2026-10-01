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
    --width N        --once: the columns to fit (default: the terminal's width,
                     else 100). See "Fitting" below.
    --mods           Show modifiers as compact chips: an edge's (`@timeout 30s ×3`,
                     `!`, `?`) after its payload on its chip, a node's (`@sla …`,
                     `^10k drop`, `@loc …`) after its label. Off by default.
    --access         Show the permission graph (`@read` / `@write` / `@borrow`):
                     dotted edges principal → store headed r / w / b (tree: lanes
                     whose source is marked r / w / b), a store badged with its
                     writers, `1w` (one owns it) or `Nw` (shared). Off by default.

Keys (live view):
    d  cycle depth (0 → 1 → all)   p  payloads   m  modifiers   a  access
    l  lint panel   r  reload
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

Fitting: a drawing wider than the window (the live pane, or --width) is
rearranged, never squashed — boxes, lanes and the outline keep their shapes.
Comment text rewraps between 16 and 40 columns; block comments move to a panel
at the top-left (their entity keeps its #N tag), payloads and inline comments to
one at the bottom-right (the flow keeps a ┆a┆ marker; in the graph view a chip
shrinks to its letter). A panel takes an empty corner of the drawing when one is
big enough. When everything fits, the drawing is exactly the natural one.

Boxes are colour-coded by node type (border + tinted fill); the sigil theme:
    [component] periwinkle   {data} violet   <event> pink   (actor) green
    |store| amber   state cyan   ? hole grey   (a dialect may register more kinds)
Border shape:  (actor) ╭╮ round   ~mutable ┏┓ heavy   [[alias]] rose
               ? hole ┄┆ dashed     ▸ collapsed expansion   ▾ shown below
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
"""

from __future__ import annotations

import argparse
import colorsys
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
    "alias":   {"open": "[[", "close": "]]", "border": "square"},   # `name := …`
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
              "actor": "#7ee787", "store": "#ffbf47", "state": "#5ccfe6", "hole": "#6e7681",
              "alias": "#f08cac"},
    "edges": {"fail": "#f85149", "maybe": "#6e7681", "async": "#8b949e", "split": "#6e7681",
              "arm": "#5abea0", "access": "#bc8cff", "default": "#c9d1d9"},
    "ui": {"text": "#c9d1d9", "muted": "#8b949e", "dim": "#6e7681", "tree": "#6e7681",
           "relation": "#5abea0", "label": "#5abea0", "title": "#c9d1d9",
           "payload": "#8b949e", "note": "#8b949e", "note_tag": "#6e7681",
           "note_block": "#8b7aad", "note_inline": "#a5d6ff", "name_saturation": "0.5",
           "payload_words": "complement",
           "bar_fg": "#c9d1d9", "bar_bg": "#161b22", "bar_name": "#e6edf3",
           "key_fg": "#e6edf3", "key_bg": "#30363d",
           "error": "#f85149", "warn": "#ffbf47", "ok": "#3fb950", "fill": "0.22",
           "frame": "#6e7681", "section": "#8b7aad", "mode": "#e3c000"},
    # Code roles (highlight/sigil.tmTheme): payloads are drawn highlighted.
    "syntax": {"operator": "#e85d9e", "cardinality": "#f59cc4", "modifier": "#ffe0b0",
               "keyword": "#c850e0", "ref": "#bc8cff", "string": "#a5d6ff",
               "number": "#79c0ff", "punct": "#586e75", "tag": "#c9d1d9",
               "call": "#5abea0", "call_name": "#f08cac", "shade": "0.6"},
}
EDGE_ROLE = {"!>": "fail", "?>": "maybe", "~>": "async", "]>[": "split",
             "arm": "arm", "access": "access"}       # (+ a branch arm, a permission edge)
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})")


def _hex(value) -> str | None:
    """value as "#rrggbb" when it is a "#rrggbb" / "#rgb" colour, else None."""
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        return None
    return value if len(value) == 7 else "#" + "".join(ch * 2 for ch in value[1:])


def _shade(colour: "Colour", amount, bg: str) -> "Colour":
    """colour mixed toward the background, keeping `amount` of it (a fraction).
    Its role, "shade:<role>", lets the page mix the same on its CSS variables."""
    try:
        k = min(max(float(amount), 0.0), 1.0)
    except (TypeError, ValueError):
        k = float(_BUILTIN_THEME["syntax"]["shade"])
    fg = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    back = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    mixed = "#%02x%02x%02x" % tuple(round(b + (f - b) * k) for f, b in zip(fg, back))
    return Colour(mixed, "shade:" + colour.role)


def _fraction(value, default) -> float:
    """value as a number in 0..1, else the default."""
    try:
        k = float(value)
    except (TypeError, ValueError):
        k = float(default)
    return min(max(k, 0.0), 1.0) if k == k else float(default)


_MUTED: dict = {}


def muted(colour: "Colour") -> "Colour":
    """A glyph name's colour: its kind's colour at NAME_SATURATION of the
    saturation (HSL). Its role, "muted:<role>", lets the page do the same."""
    key = (str(colour), NAME_SATURATION)
    if key not in _MUTED:
        r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
        h, light, s = colorsys.rgb_to_hls(r, g, b)
        rgb = colorsys.hls_to_rgb(h, light, s * NAME_SATURATION)
        _MUTED[key] = Colour("#%02x%02x%02x" % tuple(round(c * 255) for c in rgb),
                             "muted:" + getattr(colour, "role", ""))
    return _MUTED[key]


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
                   for role in _BUILTIN_THEME["syntax"] if role != "shade"},
        "NAME_SATURATION": _fraction(t["ui"].get("name_saturation"),
                                     _BUILTIN_THEME["ui"]["name_saturation"]),
        "PAYLOAD_WORDS": (t["ui"].get("payload_words")
                          if t["ui"].get("payload_words") in ("complement", "shade")
                          else "complement"),
        "CALL_SHADE": _shade(pick("syntax", "call"), t["syntax"].get("shade"),
                             pick("palette", "bg")),
        "FRAME_STYLE": (pick("ui", "frame"), None, False),          # block frames / brackets
        "SECTION_STYLE": (pick("ui", "section"), None, False),      # `--- section ---` rules
        "MODE_STYLE": (pick("ui", "mode"), bar_bg, True),           # `#!sketch` in the bar
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
    return (EDGE_COLOR.get(_base_kind(kind), EDGE_DEFAULT), None, False)


def _base_kind(kind: str) -> str:
    """An edge kind without its qualifier: `access:w` → `access`."""
    return kind.split(":", 1)[0] if kind.startswith("access:") else kind


# A flow's `: payload` drawn in the graph view as a chip on its edge (not a glyph,
# so not in KINDS): the edge runs src → chip → dst, the chip on its own layer. A
# chip also carries an edge's modifiers (m key) and a branch arm's label.
CHIP = "payload"
# A joined endpoint (`&` all, `&?` race, `/` one of): a bar the joined edges fork
# from or meet at, labelled with the join. A branch's choice: a ◇ decision node.
JOIN = "join"
DECISION = "decision"
SYNTHETIC = (CHIP, JOIN, DECISION)


def node_styles(n):
    """(border style, label style) for a node box, colour-coded by kind."""
    if n.kind == CHIP:
        return (GREY["dim"], None, False), (PAYLOAD_STYLE[0], None, False)
    if n.kind in (JOIN, DECISION):
        return FRAME_STYLE, (SYNTAX["keyword"][0], None, True)
    colour = HOLE_COLOR if n.is_hole else kind_color(n.kind)
    fill = _tint(colour)
    return (colour, fill, False), (colour, fill, True)


def node_label(n) -> str:
    if n.kind in (CHIP, JOIN):
        return n.name
    if n.kind == DECISION:
        return f"◇ {n.name}"
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
_HDASH = {U | D: "╏", U: "╏", D: "╏", L | R: "╍", L: "╍", R: "╍"}   # heavy dashed: triggers

_DOUBLE = {0: " ", U: "║", D: "║", U | D: "║", L: "═", R: "═", L | R: "═",
           D | R: "╔", D | L: "╗", U | R: "╚", U | L: "╝",
           U | D | R: "╠", U | D | L: "╣", L | R | D: "╦", L | R | U: "╩",
           U | D | L | R: "╬"}
_TABLES = {"heavy": _HEAVY, "double": _DOUBLE, "dashed": _DASHED, "dotted": _DOTTED,
           "hdash": _HDASH}

_STROKE_RANK = {"heavy": 4, "double": 3, "light": 2, "hdash": 1, "dashed": 1, "dotted": 0}

# Each arrow kind's source marker in the tree view (its stroke comes from _stroke).
# A `<->` lane starts in ▶ (its row also gets ◀: ◀──▶ both ways); a permission
# lane (the a key) starts in its access letter: r read, w write, b borrow.
SOURCE_MARK = {"->": "●", "~>": "○", "=>": "◆", "!>": "✖", "?>": "◇", "*>": "✱",
               "<->": "▶", "trigger": "◎",
               "access:r": "r", "access:w": "w", "access:b": "b"}


def _stroke(kind: str) -> str:
    """The stroke an arrow kind draws with: one per kind, so a drawing reads
    without colour (`->` / `!>` / `<->` share the light stroke and differ in their
    heads). Triggers are heavy-dashed (╍╏), never the dashed ╌╎ of `~>`."""
    return {"=>": "heavy", "*>": "double", "~>": "dashed", "trigger": "hdash",
            "?>": "dotted", "]>[": "dotted", "arm": "dotted",
            "access": "dotted"}.get(_base_kind(kind), "light")


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

    def blit(self, other: "Canvas", ox: int, oy: int):
        """Copy another canvas's cells in at an offset (lines keep their strokes)."""
        for (x, y), v in other.text.items():
            self.text[(x + ox, y + oy)] = v
        for (x, y), v in other.lines.items():
            self.lines[(x + ox, y + oy)] = list(v)
        if other.w and other.h:
            self._grow(ox + other.w - 1, oy + other.h - 1)

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
    pw: int = 0                                     # a join bar: its width (its ports' span)


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
    # Parallel edges between one pair (`?>` beside `->`): (chain, segment) → its
    # rank k >= 1 among them, and the channel track it jogs on (its own).
    dup: dict = field(default_factory=dict)
    dup_track: dict = field(default_factory=dict)

    def centre(self, vid):
        v = self.V[vid]
        return v.x + (v.pw or v.w) // 2

    def kind(self, vid) -> str:
        return "" if self.V[vid].dummy else self.g.nodes[vid].kind


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

    # Longest-path layering (Kahn order). A join bar is as wide as its ports need,
    # its label beside it.
    deg_in, deg_out = {i: 0 for i in ids}, {i: 0 for i in ids}
    for e in lay.edges:
        deg_out[e.src] += 1
        deg_in[e.dst] += 1
    for i in ids:
        if lay.g.nodes[i].kind == JOIN:
            pw = max(2 * max(deg_in[i], deg_out[i]) + 1, 5)
            V[i] = _V(i, pw + 1 + len(lay.labels[i]), pw=pw)
        else:
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

    # Edges of different kinds between one pair keep a stroke each: every one
    # after the first is offset (its own ports and track) instead of drawn over it.
    seen = {}
    for ci, (_e, rev, chain) in enumerate(lay.chains):
        for si, (u, w) in enumerate(zip(chain, chain[1:])):
            k = seen.get((u, w, rev), 0)
            if k:
                lay.dup[(ci, si)] = k
            seen[(u, w, rev)] = k + 1

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
    def spread(vid, nbrs):
        v = V[vid]
        if v.dummy or len(nbrs) <= 1:
            return {n: centre(vid) for n in nbrs}
        inner = max((v.pw or v.w) - 2, 1)
        srt = sorted(nbrs, key=centre)
        return {n: v.x + 1 + (k * (inner - 1)) // max(len(srt) - 1, 1)
                for k, n in enumerate(srt)}

    def in_ports(vid):
        return spread(vid, V[vid].ins)

    # Outgoing edges leave from the box centre (a fan-out draws as one ┬ tree); a
    # back edge (drawn upward) gets its own out-port right of centre, so it never
    # merges into the node's forward fan-out tree.
    back_seg = {(ch[0], ch[1]) for _, rev, ch in lay.chains if rev}

    def out_ports(vid):
        outs = V[vid].outs
        if lay.kind(vid) == JOIN:                 # a fork: each branch leaves the bar
            return spread(vid, outs)
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
        return not v.dummy and v.x + 1 <= x <= v.x + (v.pw or v.w) - 2

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
        extra = 0
        for (ci, si) in sorted(lay.dup):          # an offset parallel edge: its own track
            if V[lay.chains[ci][2][si]].layer == i:
                lay.dup_track[(ci, si)] = len(cols) + extra
                extra += 1
        lay.tracks.append((assign, len(cols) + extra))

    y = 0
    for i in range(len(layers)):
        lay.top.append(y)
        y += BOX_H
        if i < len(layers) - 1:
            y += lay.tracks[i][1] + 2


def _head(kind: str, up: bool = False) -> str:
    """An arrowhead: ✖ for `!>` (an error reads without colour), a permission
    edge's access letter (r / w / b), else ▼ / ▲."""
    if kind == "!>":
        return "✖"
    if kind.startswith("access:"):
        return kind[-1]
    return "▲" if up else "▼"


def _free_port(v, x: int, k: int, used: set) -> int:
    """A port near x on vertex v for the k-th parallel edge: off the ports in use."""
    lo, hi = v.x + 1, v.x + (v.pw or v.w) - 2
    for d in (2 * k, -2 * k, 2 * k + 1, -2 * k - 1, k, -k):
        if lo <= x + d <= hi and x + d not in used:
            return x + d
    return min(max(x + k, lo), hi)


def _draw(lay: _Layout) -> Canvas:
    """Edges, then boxes over them, then edge labels where they fit, then the
    grid of unconnected nodes."""
    V, top, g = lay.V, lay.top, lay.g
    cv = Canvas()

    def is_join(vid):
        return lay.kind(vid) == JOIN

    # Edges first (boxes overwrite line cells they touch).
    heads = []
    edge_labels = []   # (x, y, text) beside an arrowhead
    bar_style = {}     # join bar → the style of the edges it joins
    for ci, (e, rev, chain) in enumerate(lay.chains):
        style = edge_style(e.kind)
        for k, (u, w) in enumerate(zip(chain, chain[1:])):
            i = V[u].layer
            assign, _n = lay.tracks[i]
            sx, dx = lay.out_port[u][w], lay.in_port[w][u]
            ty = top[i] + BOX_H + 1 + assign.get((u, w), 0)
            if (ci, k) in lay.dup:                  # a parallel edge: offset ports, own track
                n = lay.dup[(ci, k)]
                if not V[u].dummy:
                    sx = _free_port(V[u], sx, n, set(lay.out_port[u].values()))
                if not V[w].dummy:
                    dx = _free_port(V[w], dx, n, set(lay.in_port[w].values()))
                ty = top[i] + BOX_H + 1 + lay.dup_track[(ci, k)]
            y0 = top[i] + BOX_H if not V[u].dummy else top[i]
            y1 = top[i + 1] - 1 if not V[w].dummy else top[i + 1]
            if is_join(u):                          # lines meet a join bar on its middle row
                y0 = top[i] + 1
                bar_style.setdefault(u, (style, e.kind))
            if is_join(w):
                y1 = top[i + 1] + 1
                bar_style.setdefault(w, (style, e.kind))
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
            for text, style_ in lay.tags.get((src, e.dst, e.kind), ()):
                if last and not rev:
                    edge_labels.append((dx, y1, text, style_))
                elif first and rev:
                    edge_labels.append((sx, y0, text, style_))
            into_chip = g.nodes[chain[-1]].kind in (CHIP, JOIN) if not rev else False
            if last and not rev and not into_chip:
                heads.append((dx, y1, _head(e.kind), style))
            if first and rev and g.nodes[chain[0]].kind != JOIN:
                heads.append((sx, y0, _head(e.kind, up=True), style))
            if e.kind == "<->":
                if first and not rev:
                    heads.append((sx, y0, "▲", style))
                if last and rev:
                    heads.append((dx, y1, "▼", style))
    for x, y, ch, st in heads:
        cv.put(x, y, ch, st)

    for vid, v in V.items():
        if v.dummy:
            continue
        if is_join(vid):
            _draw_join(cv, v, top[v.layer], lay.labels[vid], set(lay.in_port[vid].values()),
                       set(lay.out_port[vid].values()), *bar_style.get(vid, (None, "->")))
            continue
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


def _draw_join(cv: Canvas, v, y, label, ins: set, outs: set, style, kind):
    """A join bar on its middle row: ━ with a junction where each joined edge
    meets it (┷ in, ┯ out, ┿ both; ┻ ┳ ╋ for heavy `=>` edges), its label after."""
    heavy = _stroke(kind) == "heavy"
    marks = {(True, True): "╋" if heavy else "┿", (True, False): "┻" if heavy else "┷",
             (False, True): "┳" if heavy else "┯", (False, False): "━"}
    bar = "".join(marks[(x in ins, x in outs)] for x in range(v.x, v.x + v.pw))
    cv.put(v.x, y + 1, bar, style)
    cv.put(v.x + v.pw + 1, y + 1, label, LABEL_STYLE)


# A payload drawn as code: glyphs with their kind's brackets and an off-white
# name, calls with coloured ( ), the rest by syntax role.
_PAYLOAD_TOKEN = re.compile(r"""
    (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<ref>\$\{[^}]*\})
  | (?P<glyph>[~*]?(?:\[[^\]\s,][^\],]*\]|\{[^}\s:,][^}:,]*\}|<(?!->)[^<>\s][^<>]*>
                    |(?<!\w)\([^)\s][^)]*\)|\|[^|\s][^|]*\|))
  | (?P<call>[A-Za-z_][\w.]*)(?=\()
  | (?P<operator>=>|->|~>|!>|\?>|\*>|<->|\+\+|\|\||[+\-*/])
  | (?P<cardinality>[×^]\d+\w*)
  | (?P<modifier>@[A-Za-z_][\w-]*)
  | (?P<keyword>\bop\b)
  | (?P<number>\b\d+(?:\.\d+)?\b)
  | (?P<punct>[(),:{}\[\]])
""", re.X)
_GLYPH_KIND = {"[": "service", "{": "data", "<": "event", "(": "actor", "|": "store"}


def glyph_runs(tok: str, kind: str, bold: bool = False, bg=None) -> list:
    """A glyph as runs: lead (~ *) and brackets in the kind's colour, the name in
    the same colour, muted (ui.name_saturation). Brackets are the kind's own (`[[` `]]` for an
    alias, a dialect's `<<` `>>`), else one character each side."""
    lead = tok[:len(tok) - len(tok.lstrip("~*"))]
    body = tok[len(lead):]
    colour = (kind_color(kind), bg, bold)
    spec = KINDS.get(kind, {})
    op, cl = spec.get("open") or "", spec.get("close") or ""
    if not (op and cl and len(body) > len(op) + len(cl) - 1
            and body.startswith(op) and body.endswith(cl)):
        op, cl = body[:1], body[-1:]
    if len(body) < len(op) + len(cl):
        return [(tok, colour)]
    return [(lead + op, colour), (body[len(op):len(body) - len(cl)],
                                  (muted(kind_color(kind)), bg, bold)),
            (cl, colour)]


def payload_runs(text: str) -> list:
    """A payload as styled runs, colour-coded like the code highlighter. A call's
    ( ) take syntax.call; its name and arguments follow ui.payload_words:
    "complement" (name in syntax.call_name) or "shade" (name and arguments a
    darker shade of the call colour)."""
    call, shade = SYNTAX["call"], (CALL_SHADE, None, False)
    name_style = SYNTAX["call_name"] if PAYLOAD_WORDS == "complement" else shade
    runs, last, parens, pending = [], 0, [], False

    def plain(chunk):
        inside = parens and parens[-1] and PAYLOAD_WORDS == "shade"
        runs.append((chunk, shade if inside else PAYLOAD_STYLE))

    for m in _PAYLOAD_TOKEN.finditer(text):
        if m.start() > last:
            plain(text[last:m.start()])
        role, tok = m.lastgroup, m.group()
        if role == "glyph":
            runs += glyph_runs(tok, _GLYPH_KIND[tok.lstrip("~*")[0]])
        elif role == "call":
            runs.append((tok, name_style))
            pending = True
        elif tok == "(":
            parens.append(pending)
            runs.append((tok, call if pending else SYNTAX["punct"]))
            pending = False
        elif tok == ")":
            runs.append((tok, call if parens and parens.pop() else SYNTAX["punct"]))
        elif role == "number" and parens and parens[-1] and PAYLOAD_WORDS == "shade":
            runs.append((tok, shade))
        else:
            runs.append((tok, SYNTAX[role]))
        last = m.end()
    if last < len(text):
        plain(text[last:])
    return runs


# Modifiers (the m key): compact chips — `@timeout 30s ×3`, `^10k drop`, `!`, `?`.
# The access modifiers and `@owns` are not repeated: the a key and the block
# frames draw them.
HIDDEN_MODS = {"read", "write", "borrow", "owns"}
MOD_ARG_MAX = 18                                # a longer argument is cut with …
_MOD_TOKEN = re.compile(r"(?P<modifier>@[\w-]+)|(?P<cardinality>[×^]\S+)|(?P<word>[^\s@×^]+|[@×^])")


def mod_text(pair) -> str:
    """One modifier as chip text: ("timeout", "30s") → `@timeout 30s`, ("×", "3")
    → `×3`, ("^", "10k@drop") → `^10k drop`, ("!", None) → `!`, (".", "age") → `.age`."""
    name, arg = pair
    arg = " ".join(str(arg).split()) if arg is not None else None
    if arg and len(arg) > MOD_ARG_MAX:
        arg = arg[:MOD_ARG_MAX - 1] + "…"
    if name in ("×", "^", "."):
        return name + (arg or "").replace("@", " ")
    if name in ("!", "?"):
        return name
    return f"@{name} {arg}" if arg else f"@{name}"


def mods_text(mods) -> str:
    """A node's / edge's modifiers as one chip text ("" when none are shown)."""
    return " ".join(mod_text(p) for p in mods or () if p[0] not in HIDDEN_MODS)


def mod_runs(text: str) -> list:
    """Modifier chip text as runs: `@name` in syntax.modifier, `×N` / `^N` in
    syntax.cardinality, arguments in the payload colour."""
    runs, last = [], 0
    for m in _MOD_TOKEN.finditer(text):
        if m.start() > last:
            runs.append((text[last:m.start()], PAYLOAD_STYLE))
        role = m.lastgroup
        runs.append((m.group(), SYNTAX[role] if role in SYNTAX else PAYLOAD_STYLE))
        last = m.end()
    if last < len(text):
        runs.append((text[last:], PAYLOAD_STYLE))
    return runs


def _payload_is_mods(e) -> bool:
    """A payload that is only the edge's modifiers (a state transition keeps its
    `@timeout(1d)` / `×3` as payload text too): not repeated beside the mods."""
    if not e.mods or not e.payload:
        return False
    rest = render.MODIFIER_RE.sub(" ", e.payload)
    rest = re.sub(r"×\s*\w+|\bx(?:\d+|N)\b|\^\S+|(?<!\S)[!?](?!\S)", " ", rest)
    return not rest.strip()


def chip_parts(e, payloads: bool, mods: bool):
    """(payload, modifiers) an edge's chip shows — each None when not shown."""
    payload = e.payload if payloads else None
    mtext = mods_text(e.mods) if mods else ""
    if payload and mtext and _payload_is_mods(e):
        payload = None
    return payload or None, mtext or None


def chip_text(payload, mods) -> str:
    """The chip as one line of text: `payload ┆ mods` (either part may be absent)."""
    return " ┆ ".join(p for p in (payload, mods) if p)


def label_runs(n, bold: bool = True, bg=None) -> list:
    """A node's label as runs: brackets in the kind's colour, the name off-white.
    A dialect's custom label or a pseudo-state stays one run in the kind colour."""
    spec = KINDS.get(n.kind, {})
    label = node_label(n)
    colour = (HOLE_COLOR if n.is_hole else kind_color(n.kind), bg, bold)
    if n.kind == DECISION:                      # ◇ {Request}.kind: the header as code
        return [("◇ ", (SYNTAX["keyword"][0], bg, True))] + payload_runs(n.name)
    if n.kind == JOIN:
        return [(label, LABEL_STYLE)]
    if n.kind == CHIP or "label" in spec or n.attrs.get("pseudo") in PSEUDO_LABEL:
        return [(label, colour)]
    if not spec.get("open"):                    # a state: just its name
        return [(label, (muted(kind_color(n.kind)), bg, bold))]
    return glyph_runs(label, n.kind, bold, bg) if not n.is_hole else [(label, colour)]


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


def chip_runs(n) -> list:
    """A chip's content: a branch arm's label, or the payload (as code) and the
    edge's modifiers, `┆`-separated."""
    if n.attrs.get("arm"):
        return [(n.name, (EDGE_COLOR["arm"], None, True))]
    payload, mods = n.attrs.get("payload"), n.attrs.get("mods")
    if payload is None and mods is None:
        return payload_runs(n.name)
    runs = payload_runs(payload) if payload else []
    if payload and mods:
        runs.append((" ┆ ", (GREY["dim"], None, False)))
    return runs + (mod_runs(mods) if mods else [])


def _draw_box(cv: Canvas, x, y, w, label, n):
    if n.kind == DECISION:                      # a branch's choice: ╱──╲ ◇ … ╲──╱
        tl, tr, bl, br, h, s = "╱", "╲", "╲", "╱", "─", "│"
    elif n.kind == CHIP:
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
        _put_runs(cv, x + 2, y + 1, chip_runs(n))
    else:                                       # brackets in colour, name off-white
        _put_runs(cv, x + 2, y + 1, label_runs(n, bg=text[1]))
    cv.put(x + w - 2, y + 1, " " + s, border)
    cv.put(x, y + 2, bl + h * (w - 2) + br, border)


# ---------------------------------------------------------------------------
# Document → sections → styled rows
# ---------------------------------------------------------------------------

NOTE_MODES = ("off", "markers", "callouts")
CALLOUT_TEXT = 24                               # callout box text width, given room
# Comment text may scale to the window, between these. Below 16 columns a line
# holds two or three words and prose turns into a word ladder; past 40 a side
# note stops reading at a glance (half an 80-column terminal) and crowds the
# drawing. Boxes only grow past CALLOUT_TEXT to avoid cutting a comment off.
CALLOUT_MIN = 16
CALLOUT_MAX = 40
NOTE_WIDTH = 76                                 # notes list wrap width
ONCE_WIDTH = 100                                # --once width when stdout isn't a tty
ALL_DEPTH = 99                                  # --depth all


def _walk(g):
    """g, then its expansions (and theirs), breadth-first in document order."""
    queue = [g]
    while queue:
        cur = queue.pop(0)
        yield cur
        queue += list(cur.expansions.values())


def drawn_join(g, e, side: str):
    """The index into g.joins of the joined endpoint the edge leaves ("src") or
    enters ("dst") when that join is drawn, else None. A `*>` broadcast's target
    list (`*> [A] & [B]`) is not: the double fan-out already says "all of them"."""
    idx = e.src_join if side == "src" else e.dst_join
    joins = getattr(g, "joins", None) or []
    if idx is None or not 0 <= idx < len(joins):
        return None
    if side == "dst" and e.kind == "*>" and joins[idx].kind == "&":
        return None
    return idx


def access_kind(a) -> str:
    """A permission edge's kind: `access:r` read, `access:w` write, `access:b` borrow."""
    return "access:" + a.mode[0]


def with_chips(g, payloads: bool = False, triggers=(), marks: list | None = None,
               mods: bool = False, access: bool = False):
    """The graph as the graph view draws it: each `: payload` as a chip splitting
    its edge (src → chip → dst), and each trigger whose event and owner are both
    here as an edge event ⇢ owner. Returns g itself when there is nothing to add.
    With `marks` (a list), each chip shows only a marker letter and the payload is
    appended to marks as (letter, payload) — for a panel beside the drawing.
    Joined endpoints (`&` `&?` `/`) fork from / meet at a join bar; `mods` adds an
    edge's modifiers to its chip; `access` draws the permission graph as dotted
    edges principal → store, headed r / w / b."""
    extra = [t for t in triggers if t.event in g.nodes and t.owner in g.nodes]
    perms = [a for a in (getattr(g, "access", None) or []) if access
             and a.principal in g.nodes and a.store in g.nodes and a.principal != a.store]
    chips = [any(chip_parts(e, payloads, mods)) for e in g.edges]
    joined = any(drawn_join(g, e, "src") is not None or drawn_join(g, e, "dst") is not None
                 for e in g.edges)
    if not extra and not perms and not joined and not any(chips):
        return g
    nodes, edges = dict(g.nodes), []
    finals = set()                              # a final segment shared through a join

    def join_node(idx):
        jid = f"\0j{idx}"
        if jid not in nodes:
            nodes[jid] = render.Node(id=jid, name=g.joins[idx].kind, kind=JOIN)
        return jid

    for k, e in enumerate(g.edges):
        src = e.src
        sj, dj = drawn_join(g, e, "src"), drawn_join(g, e, "dst")
        if sj is not None:
            jid = join_node(sj)
            edges.append(replace(e, dst=jid, label=None, payload=None, mods=[]))
            src = jid
        if dj is not None:
            jid = join_node(dj)
            edges.append(replace(e, src=src, dst=jid, label=None, payload=None, mods=[]))
            src = jid
        if src != e.src and (src, e.dst, e.kind) in finals:
            continue                            # this joined segment is drawn already
        if src != e.src:
            finals.add((src, e.dst, e.kind))
        payload, mtext = chip_parts(e, payloads, mods)
        if (payload or mtext) and e.src != e.dst:
            cid = f"\0p{k}"
            name = chip_text(payload, mtext)
            attrs = {"src": e.src, "payload": payload, "mods": mtext}
            if marks is not None:
                letter = _letter(len(marks))
                marks.append((letter, name))
                name, attrs = letter, {"src": e.src}
            nodes[cid] = render.Node(id=cid, name=name, kind=CHIP, attrs=attrs)
            edges += [replace(e, src=src, dst=cid, label=None, payload=None),
                      replace(e, src=cid, payload=None)]
        else:
            edges.append(replace(e, src=src) if src != e.src else e)
    seen = set()
    for t in extra:
        if (t.event, t.owner) not in seen:
            seen.add((t.event, t.owner))
            edges.append(render.Edge(src=t.event, dst=t.owner, kind="trigger"))
    for a in perms:
        edges.append(render.Edge(src=a.principal, dst=a.store, kind=access_kind(a), line=a.line))
    return replace(g, nodes=nodes, edges=edges)


def writer_badges(g) -> dict:
    """{store id: "1w" | "Nw"}: how many principals may write each store (the a
    key) — a single writer owns it, several share it."""
    writers = {}
    for a in getattr(g, "access", None) or []:
        if a.mode == "write" and a.store and a.principal:
            writers.setdefault(a.store, set()).add(a.principal)
    return {sid: f"{len(ps)}w" for sid, ps in writers.items()}


class Rule(str):
    """A part title drawn as a section divider (`── L2 · Payments ─────`) rather
    than an expansion's `── [X] := { … } ──` heading."""


def section_name(sec) -> str:
    """`--- L2: Payments ---` → `L2 · Payments`; a topic header is its title."""
    return f"{sec.level} · {sec.title}" if sec.level else sec.title


def node_lines(g, notes: bool = True) -> dict:
    """{node id: line}: where each node is first written, as near as the graph
    tells — the earliest line any edge, note (`notes`: block comments too, the
    line above), access, join, block or its own `:= { … }` names it on; for a node nothing names (a bare declaration),
    the earliest line of any node after it (nodes are kept in first-seen order),
    else the previous named node's."""
    seen = {}

    def at(nid, line):
        if nid and line and (nid not in seen or line < seen[nid]):
            seen[nid] = line

    for e in g.edges:
        at(e.src, e.line)
        at(e.dst, e.line)
    for n in getattr(g, "notes", []) or []:    # a block comment sits just above
        if notes or getattr(n, "kind", "block") == "inline":
            at(n.node, n.line)
    for a in getattr(g, "access", []) or []:
        at(a.principal, a.line)
        at(a.store, a.line)
    for j in getattr(g, "joins", []) or []:
        for m in j.members:
            at(m, j.line)
    for b in getattr(g, "blocks", []) or []:   # a header's refs; a member no flow names
        for m in list(b.refs) + [m for m in b.members if m not in seen]:
            at(m, b.lines[0])
    named = {nid: line for nid, line in seen.items()   # what bounds the nodes before it
             if nid in g.nodes and g.nodes[nid].kind != "alias"}
    for nid, sub in g.expansions.items():      # `X := { … }` names X above its body
        lines = [e.line for cur in _walk(sub) for e in cur.edges if e.line]
        if lines:
            at(nid, min(lines))
    # A node only its own `:= { … }` / `state` body names (an alias, a machine's
    # owner) may be registered out of order: it bounds nothing.
    out, bound = {}, None
    for nid in reversed(list(g.nodes)):         # unnamed: no later than any later node
        if nid in seen:
            out[nid] = seen[nid]
        elif bound is not None:
            out[nid] = bound
        if nid in named:
            bound = named[nid] if bound is None else min(bound, named[nid])
    prev = None
    for nid in g.nodes:                         # nothing after it: the previous one's
        prev = named.get(nid, prev)
        if nid not in out and prev is not None:
            out[nid] = prev
    return out


def section_of(secs, line) -> int:
    """The index of the section a line is in (-1: before the first one)."""
    k = -1
    for i, sec in enumerate(secs or ()):
        if line and sec.line <= line:
            k = i
    return k


def edge_blocks(g) -> dict:
    """{edge index: block index}: the innermost control block each edge is drawn
    in — the block whose body holds its line, or whose `}` it continues (a `!>`
    compensation, Block.after)."""
    out = {}
    blocks = getattr(g, "blocks", None) or []
    for k, e in enumerate(g.edges):
        key, best = (e.src, e.dst, e.kind), None
        for bi, b in enumerate(blocks):
            lo, hi = b.lines
            if key in b.edges and (lo <= e.line <= hi or not e.line):
                if best is None or hi - lo < blocks[best].lines[1] - blocks[best].lines[0]:
                    best = bi
        if best is None:
            for bi, b in enumerate(blocks):
                if key in b.after and e.line >= b.lines[1]:
                    if best is None or b.lines[1] > blocks[best].lines[1]:
                        best = bi
        if best is not None:
            out[k] = best
    return out


BLOCK_GLYPH = {"loop": "↺", "parallel": "∥", "branch": "◇", "scope": "□", "owns": "□"}


def block_title(b) -> str:
    """`↺ loop @while |Q|.nonempty`, `∥ parallel @all`, `◇ branch on {Request}.kind`,
    `□ checkout`, `□ [Handler] @owns |Conn|`."""
    word = {"loop": "loop ", "parallel": "parallel ", "branch": "branch on "}.get(b.kind, "")
    return f"{BLOCK_GLYPH.get(b.kind, '□')} {word}{b.header}".rstrip()


def block_title_runs(b) -> list:
    """The title as runs: glyph and keyword as code keywords, the header as code."""
    text = block_title(b)
    word = {"loop": "loop", "parallel": "parallel", "branch": "branch on"}.get(b.kind, "")
    lead = text[:2 + len(word)]
    return [(lead, SYNTAX["keyword"])] + payload_runs(text[len(lead):])


@dataclass
class _Part:
    """One drawing part of a graph: its title, the sub-graph of its free flows
    (and unconnected nodes), and the control blocks drawn as frames under it."""
    title: str
    graph: object
    blocks: list


def graph_parts(g, top: bool = True, triggers=(), access: bool = False) -> list:
    """The graph split for drawing. Flows inside a control block are drawn in
    that block's frame, not in the main layout. A top-level graph with `---`
    sections is split by them: each flow goes to the section its line is in,
    each node to every section that draws it (an unconnected node: the section
    it is first written in), each block to the section of its header."""
    eb = edge_blocks(g)
    blocks = getattr(g, "blocks", None) or []
    secs = (getattr(g, "sections", None) or []) if top else []
    est = node_lines(g) if secs else {}
    in_block = set()
    for k, bi in eb.items():
        in_block |= {g.edges[k].src, g.edges[k].dst}
    for b in blocks:
        in_block |= set(b.members) | set(b.refs)
    free = [k for k in range(len(g.edges)) if k not in eb]
    linked = {g.edges[k].src for k in free} | {g.edges[k].dst for k in free}
    groups = {}                                 # section index → [edges, nodes, blocks, access]

    def grp(i):
        return groups.setdefault(i, [[], set(), [], []])

    for k in free:
        e = g.edges[k]
        i = section_of(secs, e.line or est.get(e.src, 0))
        grp(i)[0].append(e)
        grp(i)[1] |= {e.src, e.dst}
    for nid in g.nodes:
        if nid not in linked and nid not in in_block:
            grp(section_of(secs, est.get(nid, 0)))[1].add(nid)
    for bi, b in enumerate(blocks):
        if b.parent is None:
            grp(section_of(secs, b.lines[0]))[2].append(bi)
    for a in (getattr(g, "access", None) or []) if access else ():
        if a.principal in g.nodes and a.store in g.nodes:
            i = section_of(secs, a.line or est.get(a.store, 0))
            grp(i)[1] |= {a.principal, a.store}
            grp(i)[3].append(a)
    parts = []
    for i in sorted(groups):
        edges, nodes, bis, acc = groups[i]
        nodes |= {t.event for t in triggers if t.owner in nodes and t.event in g.nodes}
        sub = replace(g, nodes={nid: n for nid, n in g.nodes.items() if nid in nodes},
                      edges=edges, access=acc)
        title = Rule(section_name(secs[i])) if i >= 0 else ""
        parts.append(_Part(title, sub, bis))
    if not parts:
        parts.append(_Part("", replace(g, nodes={}, edges=[], access=[]), []))
    return parts


def _frame_content(g, bi: int, eb: dict, draw) -> "Canvas":
    """What a block's frame holds: its own flows laid out (a branch: a ◇ decision
    node with each arm's label chip on the way to the arm's entry), then its
    nested blocks' frames."""
    b = g.blocks[bi]
    kids = [ci for ci, c in enumerate(g.blocks) if c.parent == bi]
    nested = set()
    for ci in kids:
        nested |= set(g.blocks[ci].members)
    own = [g.edges[k] for k, owner in eb.items() if owner == bi]
    keep = {e.src for e in own} | {e.dst for e in own}
    keep |= set(b.members) - nested
    nodes = {nid: n for nid, n in g.nodes.items() if nid in keep}
    edges = list(own)
    if b.kind == "branch":
        dec = f"\0b{bi}"
        name = b.header if b.header else "branch"
        nodes = {dec: render.Node(id=dec, name=name, kind=DECISION), **nodes}
        refs = set(b.refs)
        edges = [replace(e, src=dec) if e.src in refs and e.key in b.after else e
                 for e in edges]
        for ai, (label, ids) in enumerate(b.arm_nodes):
            if not ids or ids[0] not in nodes:
                continue
            cid = f"\0a{bi}.{ai}"
            nodes[cid] = render.Node(id=cid, name=label, kind=CHIP, attrs={"arm": True})
            edges += [render.Edge(src=dec, dst=cid, kind="arm"),
                      render.Edge(src=cid, dst=ids[0], kind="arm")]
    sub = replace(g, nodes=nodes, edges=edges, blocks=[], access=[])
    own_cv = draw(sub) if nodes else Canvas()
    frames = [_framed(_frame_content(g, ci, eb, draw), block_title_runs(g.blocks[ci]))
              for ci in kids]
    return _stack(own_cv, frames)


def _framed(content: "Canvas", title_runs: list) -> "Canvas":
    """A titled frame around a drawing: ╭╌ title ╌╌╮ / ╎ … ╎ / ╰╌╌╌╯ (light dashed)."""
    tw = row_len(title_runs)
    inner = max(content.w, tw + 2)
    w = inner + 4
    cv = Canvas()
    cv.put(0, 0, "╭╌ ", FRAME_STYLE)
    x = _put_runs(cv, 3, 0, title_runs)
    cv.put(x, 0, " " + "╌" * (w - 2 - x) + "╮", FRAME_STYLE)
    for y in range(1, content.h + 1):
        cv.put(0, y, "╎", FRAME_STYLE)
        cv.put(w - 1, y, "╎", FRAME_STYLE)
    cv.blit(content, 2 + (inner - content.w) // 2, 1)
    cv.put(0, content.h + 1, "╰" + "╌" * (w - 2) + "╯", FRAME_STYLE)
    return cv


FRAME_GAP = 2                                   # columns between frames in a row


def _stack(main: "Canvas", frames: list) -> "Canvas":
    """main, with the frames in rows under it (left to right, wrapped at the
    wider of main and ISOLATED_WRAP); main is centred over a wider frame row."""
    if not frames:
        return main
    wrap = max(main.w, ISOLATED_WRAP)
    placed, x, y, row_h, width = [], 0, 0, 0, 0
    for f in frames:
        if x and x + f.w > wrap:
            x, y, row_h = 0, y + row_h + 1, 0
        placed.append((f, x, y))
        width = max(width, x + f.w)
        x += f.w + FRAME_GAP
        row_h = max(row_h, f.h)
    out = Canvas()
    out.blit(main, max(width - main.w, 0) // 2, 0)
    top = main.h + 1 if main.h else 0
    for f, fx, fy in placed:
        out.blit(f, fx, top + fy)
    return out


def sections(g, depth: int, title: str = "", level: int = 0, tags: dict | None = None,
             payloads: bool = False, triggers=(), fit: int | None = None,
             marks: list | None = None, mods: bool = False, access: bool = False,
             _secs=None, _level=None):
    """Yield (title, graph, canvas) for the graph and its expansions up to depth.
    `payloads` draws each flow's payload as a chip on its edge; `triggers` (the
    document's event → state triggers) draw as dashed edges event ⇢ owner. With
    `fit` (columns) and `marks` (a list), a section wider than `fit` that has chips
    is laid out again with marker-letter chips — kept (and its payloads appended
    to marks) when that fits, or is at least a fifth narrower.

    A top-level graph with `--- sections ---` yields one part per section (its
    title a Rule); control blocks are drawn as titled frames under their part's
    flows. `mods` puts modifiers on chips (edges) and after labels (nodes);
    `access` draws the permission graph."""
    show = set(g.expansions) if level < depth else set()
    collapsed = set(g.expansions) - show
    eb = edge_blocks(g)
    secs = (getattr(g, "sections", None) or []) if level == 0 else (_secs or [])
    chipped = (payloads or mods) and any(any(chip_parts(e, payloads, mods)) and e.src != e.dst
                                         for e in g.edges)

    def draw_all(part, chip_marks):
        def draw(sub):
            return layout(with_chips(sub, payloads, triggers, chip_marks, mods, access),
                          show, collapsed, tags)
        main = draw(part.graph) if part.graph.nodes else Canvas()
        frames = [_framed(_frame_content(g, bi, eb, draw), block_title_runs(g.blocks[bi]))
                  for bi in part.blocks]
        return _stack(main, frames)

    for part in graph_parts(g, level == 0, triggers, access):
        cv = draw_all(part, None)
        if fit is not None and marks is not None and cv.w > fit and chipped:
            trial = list(marks)
            marked = draw_all(part, trial)
            # Worth it when that fits, or saves at least a fifth of the width.
            if marked.w < cv.w and (marked.w <= fit or marked.w * 5 <= cv.w * 4):
                cv, marks[:] = marked, trial
        yield part.title or title, part.graph, cv
    for nid in g.expansions:
        if nid in show:
            sub = g.expansions[nid]
            what = "state machine" if getattr(sub, "role", "") == "state" else ":= { … }"
            sub_title = f"{node_label(g.nodes[nid])} {what}"
            lines = [e.line for cur in _walk(sub) for e in cur.edges if e.line]
            k = section_of(secs, min(lines)) if lines else -1
            zoom = secs[k].level if k >= 0 and secs[k].level != "L1" else None
            if zoom and zoom != _level:         # the zoom level it is written at
                sub_title = f"{zoom} · {sub_title}"
            if title and not isinstance(title, Rule):
                sub_title = f"{title}  ›  {sub_title}"
            yield from sections(sub, depth, sub_title, level + 1, tags, payloads, triggers,
                                fit, marks, mods, access, secs, zoom or _level)


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


def compose(g, depth: int, payloads: bool, notes: str = "off", triggers: bool = True,
            width: int | None = None, access: bool = False, mods: bool = False):
    """The whole drawing as rows of (text, style) runs, plus its width. Each
    section's canvas is centred within the widest section. `payloads` draws each
    flow's payload as a chip on its edge; `triggers` wires each event to the owner
    of the state machine it drives (and lists the transitions below). Notes (any
    mode but "off") tag commented boxes `#N` and list the notes below.

    `width`: the columns to fit (None: draw at the natural width). When the
    drawing is wider, it is rearranged — never squashed: block notes move to a
    panel at the top-left, inline notes to one at the bottom-right, and a
    section still too wide because of its payload chips draws each chip as a
    marker letter (┆ a ┆) with the payload beside its letter in that panel.
    Panels go into empty corners of the drawing when one is big enough.

    `--- sections ---` split the drawing into parts under divider rules; control
    blocks are titled frames under their part's flows; joined endpoints fork
    from / meet at a join bar. `access`: the permission graph (dotted edges
    principal → store headed r / w / b, a store badged `1w` / `Nw` writers).
    `mods`: modifier chips on edges (with the payload) and after node labels."""
    idx = note_index(g) if notes != "off" else {}
    tags = {nid: note_tag_runs(node_notes(entries)) for nid, entries in idx.items()
            if node_notes(entries)}
    for key, notes_ in edge_notes(idx).items():    # inline notes ride their flow's edge
        tags[key] = [(" ".join(f"#{num}" for num, _t in notes_), NOTE_STYLE["inline"])]
    _label_extras(g, tags, access, mods)
    trig_edges = getattr(g, "triggers", []) if triggers else []
    parts = list(sections(g, depth, tags=tags, payloads=payloads, triggers=trig_edges,
                          mods=mods, access=access))
    rows, drawing_w = _section_rows(parts)
    trig = trigger_lines(g) if triggers else []
    if trig:
        rows += [[], [("── triggers ──", TITLE_STYLE)], []]
        rows += [[(t, LABEL_STYLE)] for t in trig]
    natural = rows + ([[], [("── notes ──", TITLE_STYLE)], []] + note_rows(idx) if idx else [])
    natural_w = max([drawing_w] + [row_len(r) for r in natural])
    if width is None or natural_w <= width:
        return natural, natural_w

    marks = []
    if (payloads or mods) and drawing_w > width:
        parts = list(sections(g, depth, tags=tags, payloads=payloads, triggers=trig_edges,
                              fit=width, marks=marks, mods=mods, access=access))
        rows, _w = _section_rows(parts)
        if trig:
            rows += [[], [("── triggers ──", TITLE_STYLE)], []]
            rows += [[(t, LABEL_STYLE)] for t in trig]
    listed = sorted(e for entries in idx.values() for e in entries)
    block = [([(f"#{num}", NOTE_STYLE[kind])], [(text, kind)])
             for num, text, kind, _e in listed if kind == "block"]
    side = ([(_chip_marker(letter), [(text, "code")]) for letter, text in marks]
            + [([(f"#{num}", NOTE_STYLE[kind])], [(text, kind)])
               for num, text, kind, _e in listed if kind != "block"])
    if block:
        rows = _fit_panel(rows, lambda tw: _panel_rows(block, tw), width, "tl", CALLOUT_MAX)
    if side:
        rows = _fit_panel(rows, lambda tw: _panel_rows(side, tw), width, "br", CALLOUT_MAX)
    return rows, max([0] + [row_len(r) for r in rows])


def _label_extras(g, tags: dict, access: bool, mods: bool):
    """Add to the box-label runs (tags): a node's modifiers (mods) and a store's
    writer badge (access), after any #N note tags."""
    done = set()
    for cur in _walk(g):
        if mods:
            for nid, n in cur.nodes.items():
                text = mods_text(n.mods)
                if text and nid not in done:
                    done.add(nid)
                    tags[nid] = list(tags.get(nid, [])) + [(" ", None)] + mod_runs(text)
        if access:
            for sid, badge in writer_badges(cur).items():
                tags[sid] = list(tags.get(sid, [])) + [(" " + badge,
                                                       (EDGE_COLOR["access"], None, True))]


def _section_rows(parts):
    """The sections' canvases as rows, each centred within the widest, under
    their titles; and that width. A Rule title (a `--- section ---`) is a
    divider across the drawing: `── L2 · Payments ─────`."""
    width = max([cv.w for _, _, cv in parts] + [len(t) + 6 for t, _, _ in parts if t] + [0])
    rows = []
    for title, _sg, cv in parts:
        if isinstance(title, Rule):
            rows += ([[]] if rows else []) + [section_rule(title, width), []]
        elif title:
            rows += [[], [(f"── {title} ──", TITLE_STYLE)], []]
        pad = (width - cv.w) // 2
        for row in cv.rows():
            rows.append(([(" " * pad, None)] if pad and row else []) + row)
    return rows, width


def section_rule(name: str, width: int = 0) -> list:
    """`── L2 · Payments ──`, the rule run out to `width` columns: the rails in
    ui.section, the name as code (a glyph in it keeps its colours)."""
    runs = [("── ", SECTION_STYLE)] + [(t, (st[0], st[1], True)) for t, st in payload_runs(name)]
    n = row_len(runs)
    return runs + [(" " + "─" * max(width - n - 1, 2), SECTION_STYLE)]


# ---------------------------------------------------------------------------
# Fitting — panels of relocated comments / payloads, placed in an empty corner
# of the drawing when one is big enough, else above (top-left) or below it,
# right-aligned (bottom-right). Only comment text rewraps; the drawing never
# changes shape.
# ---------------------------------------------------------------------------

def _letter(k: int) -> str:
    """The k-th marker letter: a … z, aa, ab, …"""
    s, k = "", k + 1
    while k:
        k, r = divmod(k - 1, 26)
        s = chr(97 + r) + s
    return s


def _chip_marker(letter: str) -> list:
    """`┆a┆`: a small payload chip standing in for a relocated payload."""
    dim = (GREY["dim"], None, False)
    return [("┆", dim), (letter, PAYLOAD_STYLE), ("┆", dim)]


def _callout_lines_cap(kind: str, tw: int) -> int:
    """How many lines a callout may take at text width tw: 3 for a block note (2
    inline) from CALLOUT_TEXT up; a narrowed box may take as many lines as it
    needs to hold what that box holds at CALLOUT_MAX, so narrowing never cuts a
    comment off sooner."""
    base = 3 if kind == "block" else 2
    return base if tw >= CALLOUT_TEXT else max(base, -(-base * CALLOUT_MAX // tw))


def _callout_lines(text: str, kind: str, tw: int) -> list:
    """A callout's text wrapped at tw, cut with … past its line limit."""
    lines = textwrap.wrap(text, tw) or [""]
    limit = _callout_lines_cap(kind, tw)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = lines[-1][:tw - 1] + "…"
    return lines


def _callout_need(blocks: dict) -> int:
    """The narrowest text width from CALLOUT_TEXT up to CALLOUT_MAX that shows
    every callout whole (CALLOUT_MAX if none does)."""
    need = CALLOUT_TEXT
    for entries in blocks.values():
        for _num, text, kind, _e in entries:
            while (need < CALLOUT_MAX
                   and len(textwrap.wrap(text, need)) > _callout_lines_cap(kind, need)):
                need += 1
    return need


def _callout_panel(entries, tw: int):
    """Block notes as a stack of framed boxes, each headed by its `#N` (the same
    tag sits on its entity's row); returns (rows, width)."""
    tag_w = max(len(f"#{num}") for num, _t, _k in entries) + 1
    rows = []
    for num, text, kind in entries:
        lines = _callout_lines(text, kind, tw)
        style, k = NOTE_STYLE[kind], len(lines)
        for j, ln in enumerate(lines):
            if k == 1:
                lside, rside = "│ ", " │"
            else:
                lside, rside = {0: ("╭ ", " ╮"), k - 1: ("╰ ", " ╯")}.get(j, ("│ ", " │"))
            tag = f"#{num}".ljust(tag_w) if j == 0 else " " * tag_w
            rows.append([(tag, style), (lside, style), (ln.ljust(tw), style), (rside, style)])
    return rows, tag_w + tw + 4


def _panel_rows(items, tw: int):
    """A panel: each item is (marker runs, [(text, kind)]); kind "code" is a
    payload (drawn as code), else a note kind. Each text wraps at tw under its
    marker (a payload, being code, at no less than its own length up to
    CALLOUT_MAX). Returns (rows, width)."""
    mark_w = max(row_len(m) for m, _ in items) + 1
    rows = []
    for marker, texts in items:
        first = True
        for text, kind in texts:
            wrap = max(tw, min(len(text), CALLOUT_MAX)) if kind == "code" else tw
            for ln in textwrap.wrap(text, wrap) or [""]:
                lead = (marker + [(" " * (mark_w - row_len(marker)), None)] if first
                        else [(" " * mark_w, None)])
                body = (payload_runs(ln) if kind == "code"
                        else [(ln, NOTE_STYLE[kind] if kind == "inline" else NOTE_TEXT_STYLE)])
                rows.append(lead + body)
                first = False
    return rows, max(row_len(r) for r in rows)


def _occupancy(rows, width: int):
    """Prefix sums of the non-blank cells in rows (clipped to width): a rectangle's
    count of drawn cells in O(1)."""
    acc = [[0] * (width + 1)]
    for row in rows:
        text = "".join(t for t, _ in row)[:width].ljust(width)
        line, run = [0], 0
        for x, ch in enumerate(text):
            run += ch != " "
            line.append(acc[-1][x + 1] + run)
        acc.append(line)
    return acc


def _empty_spot(acc, ph: int, pw: int, width: int, corner: str):
    """Where a ph×pw panel fits with blank clearance all round, in the
    corner's quarter of the drawing ("tl": topmost, then leftmost; "br":
    bottommost, then rightmost); None when nowhere."""
    h = len(acc) - 1
    if ph > h or pw > width:
        return None

    def blank(y, x):                    # a row of clearance, two columns
        y0, y1 = max(y - 1, 0), min(y + ph + 1, h)
        x0, x1 = max(x - 2, 0), min(x + pw + 2, width)
        return acc[y1][x1] - acc[y0][x1] - acc[y1][x0] + acc[y0][x0] == 0

    if corner == "tl":
        ys, xs = range(0, (h - ph) // 2 + 1), range(0, (width - pw) // 2 + 1)
    else:
        ys = range(h - ph, (h - ph + 1) // 2 - 1, -1)
        xs = range(width - pw, (width - pw + 1) // 2 - 1, -1)
    for y in ys:
        for x in xs:
            if blank(y, x):
                return y, x
    return None


def _splice(row, x: int, runs, w: int):
    """row with runs (w columns) written over its columns from x."""
    left = clip(row, 0, x)
    right = clip(row, x + w, 1 << 30)
    pad = x - row_len(left)
    fill = w - row_len(runs)
    return (left + ([(" " * pad, None)] if pad else []) + runs
            + ([(" " * fill, None)] if right and fill > 0 else []) + right)


def _fit_panel(rows, make, width: int, corner: str, pref: int):
    """Place a panel (make(text width) → (rows, width)) in the drawing: in an empty
    region of its corner if one is big enough at some text width (pref first, then
    CALLOUT_MAX down to CALLOUT_MIN), else above the drawing (tl) or below it,
    right-aligned (br), at the widest text width within `width`."""
    acc = _occupancy(rows, width)
    tries = [pref] + [t for t in range(CALLOUT_MAX, CALLOUT_MIN - 1, -4) if t != pref]
    for tw in tries:
        panel, pw = make(tw)
        spot = _empty_spot(acc, len(panel), pw, width, corner)
        if spot:
            y, x = spot
            out = list(rows)
            for j, prow in enumerate(panel):
                out[y + j] = _splice(out[y + j], x, prow, pw)
            return out
    tw = pref
    panel, pw = make(tw)
    while pw > width and tw > CALLOUT_MIN:
        tw -= 1
        panel, pw = make(tw)
    if corner == "tl":
        return panel + [[]] + list(rows)
    right = min(width, max([pw] + [row_len(r) for r in rows]))
    pad = max(right - pw, 0)
    return list(rows) + [[]] + [([(" " * pad, None)] if pad else []) + r for r in panel]


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
    return {"heavy": "━", "double": "═", "dashed": "╌", "dotted": "┄",
            "hdash": "╍"}.get(_stroke(kind), "─")


def _lane_colour(kind: str, src_kind: str) -> str:
    """A lane's colour: the arrow's own colour when it has one (!> ?> ~> ]>[),
    else its source node's kind colour."""
    return EDGE_COLOR[kind] if kind in EDGE_COLOR else kind_color(src_kind)


def tree_legend(triggers: bool = True, payloads: bool = False, access: bool = False,
                mods: bool = False):
    """Legend rows for the tree + wires view: relations, then lanes by arrow type,
    then the structure marks (blocks, joins, sections). Markers whose lanes take
    their source's colour are drawn neutral."""
    dim, mid = (GREY["dim"], None, False), (GREY["mid"], None, False)
    rel = [("tree   ", dim), ("─", TREE_STYLE), (" contains  ", mid)]
    for glyph, word in (("&", "has"), ("*", "spawns"), ("?", "when"), ("$", "from data"),
                        ("@", "attached"), ("!", "alerts"), ("=", "gathers"),
                        ("_", "one of"), ("(N)", "weight")):
        rel += [(glyph, REL_STYLE), (f" {word}  ", mid)]
    wires = [("wires  ", dim)]
    for kind, word in ARROW_LEGEND + ((("trigger", "trigger"),) if triggers else ()):
        colour = EDGE_COLOR.get(kind, EDGE_DEFAULT)
        sample = ("◀─▶" if kind == "<->"
                  else SOURCE_MARK.get(kind, "●") + _stroke_sample(kind))
        wires += [(sample, (colour, None, False)), (f" {word}  ", mid)]
    wires += [(EMIT_MARK + "─", (kind_color("event"), None, False)),
              (" emits  ", mid),
              ("◀", (GREY["light"], None, True)), (" target  ", mid),
              ("─│─", dim), (" crossing  ", mid),
              ("■", (EDGE_DEFAULT, None, False)), (" lane: its source's colour  ", mid)]
    if access:
        acc = (EDGE_COLOR["access"], None, False)
        wires += [("r┄", acc), (" reads  ", mid), ("w┄", acc), (" writes  ", mid),
                  ("b┄", acc), (" borrows  ", mid),
                  ("1w", (EDGE_COLOR["access"], None, True)), (" writers  ", mid)]
    if payloads:
        wires += [("┄┆{…}┆", dim), (" payload, on its target row", mid)]
    if mods:
        wires += [("┆@… ×N┆", (SYNTAX["modifier"][0], None, False)), (" modifiers", mid)]
    marks = [("blocks ", dim), ("┌─ ↺", FRAME_STYLE), (" loop  ", mid), ("∥", FRAME_STYLE),
             (" parallel  ", mid), ("◇", FRAME_STYLE), (" branch ", mid),
             ("‹arm›", (EDGE_COLOR["arm"], None, True)), ("  ", mid), ("□", FRAME_STYLE),
             (" scope / owns  ", mid), ("◀&", LABEL_STYLE), (" joined: all  ", mid),
             ("◀&?", LABEL_STYLE), (" race  ", mid), ("◀/", LABEL_STYLE), (" one of  ", mid),
             ("── ──", SECTION_STYLE), (" section", mid)]
    return [rel, wires, marks]


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


def graph_legend(triggers: bool = True, payloads: bool = False, access: bool = False,
                 mods: bool = False):
    """Legend row for the graph view: the stroke and head of each arrow type,
    then the trigger edge, structure marks (block frames, joins, branch arms),
    the permission edges, payload and modifier chips when they are shown."""
    dim, mid = (GREY["dim"], None, False), (GREY["mid"], None, False)
    row = [("arrows ", dim)]
    for kind, word in ARROW_LEGEND:
        colour = EDGE_COLOR.get(kind, EDGE_DEFAULT)
        sample = ("▲" + _stroke_sample(kind) + "▼" if kind == "<->"
                  else _stroke_sample(kind) * 2 + _head(kind))
        row += [(sample, (colour, None, False)), (f" {word}  ", mid)]
    if triggers:
        row += [(_stroke_sample("trigger") * 2 + "▼", edge_style("trigger")), (" trigger  ", mid)]
    row += [("╭╌ ↺ ∥ ◇ □", FRAME_STYLE), (" block frame  ", mid),
            ("┄‹arm›┄", (EDGE_COLOR["arm"], None, False)), (" branch arm  ", mid),
            ("━┷━ &", LABEL_STYLE), (" join: all  ", mid), ("&?", LABEL_STYLE),
            (" race  ", mid), ("/", LABEL_STYLE), (" one of  ", mid)]
    if access:
        acc = (EDGE_COLOR["access"], None, False)
        row += [("┄┄r", acc), (" read  ", mid), ("┄┄w", acc), (" write  ", mid),
                ("┄┄b", acc), (" borrow  ", mid),
                ("1w", (EDGE_COLOR["access"], None, True)), (" writers  ", mid)]
    if payloads:
        row += [("╭┄{…}┄╯", dim), (" payload", mid)]       # the chip's corners, on one row
    if mods:
        row += [("┆@… ×N┆", (SYNTAX["modifier"][0], None, False)), (" modifiers", mid)]
    return row


KEY_LEGEND = (("t", "tree/graph"), ("n", "notes"), ("e", "triggers"), ("s", "spacing"),
              ("d", "depth"), ("p", "payloads"), ("m", "mods"), ("a", "access"),
              ("l", "lint"), ("c", "centre"), ("g", "home"), ("r", "reload"), ("q", "quit"))


def keys_legend(state):
    """The hotkeys row for a ViewState; toggles that are on are shown bright."""
    dim, mid = (GREY["dim"], None, False), (GREY["mid"], None, False)
    on = {"t": state.tree, "e": state.show_triggers, "s": state.spaced,
          "p": state.payloads, "l": state.show_lint, "n": state.notes != "off",
          "m": state.show_mods, "a": state.show_access}
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


def _collapse_events(rows, wires, g):
    """Draw a pass-through event where it lands, not as its own row: a top-level
    event row with no parts, expansion or state machine of its own, that is both
    emitted (a flow into it) and delivered (a flow or trigger out of it), goes;
    each emitter is wired straight to each destination, and the event's label
    sits on the destination's row (a state's row already names its triggers).
    Returns (rows, wires, emitted lane keys, {destination id: [event nodes]},
    {emitted key: [the emission and delivery keys it merges]})."""
    nodes = {}
    for cur in _walk(g):
        for nid, n in cur.nodes.items():
            nodes.setdefault(nid, n)
    has_parts = {r.node.id for k, r in enumerate(rows)
                 if r and k + 1 < len(rows) and rows[k + 1] and rows[k + 1].depth > r.depth}
    owners = {nid for cur in _walk(g) for nid, sub in cur.expansions.items()}
    candidates = {r.node.id for r in rows if r and r.depth == 0 and r.node.kind == "event"
                  and r.node.id not in has_parts and r.node.id not in owners}
    emitted, landed, merged = set(), {}, {}
    gone, out_wires = set(), []
    for ev in candidates:
        into = [w for w in wires if w[1] == ev and w[2] != "trigger" and w[0] != ev]
        onward = [w for w in wires if w[0] == ev and w[1] != ev]
        if not into or not onward:
            continue
        gone.add(ev)
        for a in into:
            for b in onward:
                # a failure emission stays a failure path (!> stroke, ✖ source)
                kind = "!>" if a[2] == "!>" and b[2] != "trigger" else b[2]
                key = (a[0], b[1], kind)
                if key not in merged:
                    out_wires.append((a[0], b[1], kind, a[3], b[4]))
                    merged[key] = [a[:3], b[:3]]
                    if kind != "!>":
                        emitted.add(key)
                if b[2] != "trigger":
                    events = landed.setdefault(b[1], [])
                    if nodes[ev] not in events:
                        events.append(nodes[ev])
    if not gone:
        return rows, wires, frozenset(), {}, {}
    kept = [w for w in wires if w[0] not in gone and w[1] not in gone]
    rows = [r for r in rows if not (r and r.depth == 0 and r.node.id in gone)]
    return rows, kept + out_wires, frozenset(emitted), landed, merged


def compose_tree(g, depth: int, triggers: bool = True, spaced: bool = True,
                 notes: str = "off", payloads: bool = False, width: int | None = None,
                 access: bool = False, mods: bool = False):
    """The drawing as outline rows with a lane gutter; same return shape as compose().
    `triggers`: draw event → state lanes. `spaced`: a blank row between top-level
    units (a root with parts, or the first root after one). `notes`: "markers" tags
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
    idx = note_index(g) if notes != "off" else {}
    rows, wires = _tree_rows(g, depth, triggers=triggers)
    if not rows:
        return [], 0
    rows, wires, emitted, landed, merged = _collapse_events(rows, wires, g)
    if access:
        wires = wires + [(a.principal, a.store, access_kind(a), None, None)
                         for cur in _walk(g) for a in getattr(cur, "access", None) or []
                         if a.principal and a.store and a.principal != a.store]
    if spaced:
        rows = _space_units(rows)
    rows, brackets, arms = _tree_banners(rows, g)
    xs, x0 = _bracket_cols(brackets)
    after_label = _tree_extras(g, access, mods, arms)
    for nid, events in landed.items():          # an event shows where it lands
        after_label[nid] = [run for ev in events
                            for run in [(" ", None)] + glyph_runs(node_label(ev), "event")
                            ] + after_label.get(nid, [])
    joins = _join_marks(g)
    # Block notes are about a component: tagged on its row, called out on the
    # left. Inline notes are about their line: they trail it on the right, after
    # the payload the line carries — as in the source.
    blocks = {nid: [e for e in es if e[2] == "block"] for nid, es in idx.items()}
    blocks = {nid: es for nid, es in blocks.items() if es}
    payload_of = _payload_of(g, payloads, mods) if (payloads or mods) else {}
    trailing = _trailing_notes(idx) if notes != "off" else {}
    for key, parts in merged.items():           # an emitted lane carries both legs'
        for table in (payload_of, trailing):
            got = [table[p] for p in parts if p in table]
            if got and key not in table:
                table[key] = (" · ".join(got) if isinstance(got[0], str)
                              else [x for part in got for x in part])
    bases = {}

    def base(left: bool, right: bool):
        """The outline, lanes and right margin; `left`: callouts relocated (so
        rows carry #N tags), `right`: the right margin relocated."""
        if (left, right) not in bases:
            cv = Canvas()
            out = _draw_outline(cv, rows, blocks, show_tags=notes != "callouts" or left,
                                x0=x0, extra=after_label)
            _draw_brackets(cv, brackets, xs, x0)
            lanes = _collect_lanes(cv, wires, out)
            placed = _pack_lanes(lanes, max(out.ends) + 3, out.node, emitted)
            _draw_lanes(cv, placed, out.ends,
                        frozenset(i for i, ln in enumerate(lanes) if ln[2:5] in emitted))
            _draw_join_taps(cv, lanes, out.ends, joins)
            moved = [] if right else None
            drawn = _draw_right_margin(cv, lanes, placed, out, payload_of, trailing, notes,
                                       moved)
            bases[(left, right)] = (list(cv.rows()), cv.w, out, drawn, moved or [])
        return bases[(left, right)]

    def assemble(left: bool, right: bool, tw: int):
        out_rows, w, out, _drawn, _moved = base(left, right)
        if notes == "callouts" and out.tagged and not left:
            out_rows, w = _with_callouts(out_rows, blocks, out.tagged, tw)
        return out_rows, w

    callouts = notes == "callouts" and bool(blocks)
    need = _callout_need(blocks) if callouts else CALLOUT_TEXT
    choice = (False, False, CALLOUT_TEXT)
    if width is not None:
        out_rows, w = assemble(*choice)
        extra = _extras(g, idx, notes, payloads, base(False, False)[3])
        fits = max([w] + [row_len(r) for r in extra]) <= width
        if fits and need > CALLOUT_TEXT and assemble(False, False, need)[1] <= width:
            choice = (False, False, need)           # room to show every callout whole
        elif not fits:
            shrink = range(need, CALLOUT_MIN - 1, -1) if callouts else (CALLOUT_TEXT,)
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
                    NOTE_WIDTH if width is None else min(NOTE_WIDTH, width))
    if width is not None and right and moved:
        items = [(_chip_marker(letter), ([(" · ".join(chips), "code")] if chips else [])
                  + [(f"# {text}", "inline") for _num, text in notes_])
                 for letter, chips, notes_ in moved]
        out_rows = _fit_panel(out_rows, lambda t: _panel_rows(items, t), width, "br",
                              CALLOUT_MAX)
    if width is not None and left and out.tagged:
        entries = [(num, text, kind) for nid, _y in sorted(out.tagged.items(), key=lambda kv: kv[1])
                   for num, text, kind, _e in blocks[nid]]
        out_rows = _fit_panel(out_rows, lambda t: _callout_panel(entries, t), width, "tl", need)
    if (left, right) != (False, False):
        w = max([0] + [row_len(r) for r in out_rows])
    out_rows = list(out_rows) + extra
    return out_rows, max([w] + [row_len(r) for r in extra])


class _Bracket(NamedTuple):
    """A control block in the tree view: its header row and member rows."""
    header: int
    members: list


def _tree_banners(rows, g):
    """rows with banners inserted: a section divider before the first top-level
    unit of each `--- section ---`, and each control block's header — before the
    first member row the block introduces (else after its last member row).
    Returns (rows, brackets, arm labels {entry node id: [label]})."""
    first = {}
    for i, r in enumerate(rows):
        if isinstance(r, TreeRow):
            first.setdefault((id(r.graph), r.node.id), i)
    pending = []                                # (at, order, Banner, members)
    secs = getattr(g, "sections", None) or []
    if secs:
        est, cur = node_lines(g), -1
        for i, r in enumerate(rows):
            if isinstance(r, TreeRow) and r.graph is g and r.depth == 0:
                k = section_of(secs, est.get(r.node.id, 0))
                if k > cur:
                    cur = k
                    pending.append((i, (1, 0), Banner("section", section_rule(
                        section_name(secs[k]))), None))
    arms = {}
    seen_graphs = {id(r.graph): r.graph for r in rows if isinstance(r, TreeRow)}
    for G in seen_graphs.values():
        blocks = getattr(G, "blocks", None) or []
        est = node_lines(G, notes=False) if blocks else {}
        for b in blocks:
            members = [m for m in dict.fromkeys(b.members) if (id(G), m) in first]
            if not members:
                continue
            ys = [first[(id(G), m)] for m in members]
            intro = [first[(id(G), m)] for m in members if est.get(m, 0) >= b.lines[0]]
            at, prio = (min(intro), 2) if intro else (max(ys) + 1, 0)
            span = b.lines[1] - b.lines[0]
            pending.append((at, (prio, -span), Banner("block", block_title_runs(b)), ys))
            if b.kind == "branch":
                for label, ids in b.arm_nodes:
                    if ids:
                        arms.setdefault(ids[0], []).append(label)
    if not pending:
        return rows, [], arms
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
    return out, [_Bracket(h, [new_at[y] for y in ys]) for h, ys in brackets], arms


BRACKET_GAP = 2                                 # columns between block brackets


def _bracket_cols(brackets) -> tuple:
    """Each bracket's gutter column (interval-packed, the longest outermost) and
    the gutter's width (where the outline starts: 0 without brackets)."""
    cols, at = [], {}
    order = sorted(range(len(brackets)), key=lambda k: -(max(brackets[k].members + [brackets[k].header])
                                                          - min(brackets[k].members + [brackets[k].header])))
    for k in order:
        ys = brackets[k].members + [brackets[k].header]
        at[k] = _first_fit(cols, min(ys), max(ys))
    return [at[k] * BRACKET_GAP for k in range(len(brackets))], (
        len(cols) * BRACKET_GAP + 1 if cols else 0)


def _draw_brackets(cv: Canvas, brackets, xs, x0: int):
    """Each block as a bracket in the gutter left of the outline: a vertical from
    its first to its last row, a ─ tap into its header and each member row
    (hopping ─│─ the brackets it crosses)."""
    verticals = set()
    for b, x in zip(brackets, xs):
        ys = b.members + [b.header]
        if max(ys) > min(ys):
            cv.path([(x, min(ys)), (x, max(ys))], "->", FRAME_STYLE)
            verticals |= {(x, y) for y in range(min(ys), max(ys) + 1)}
    for b, x in zip(brackets, xs):
        for y in sorted(set(b.members + [b.header])):
            cv.run(x, x0 - 2, y, "->", FRAME_STYLE,
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
    node: dict                                  # node id → its node (first row's)


def _draw_outline(cv: Canvas, rows, idx: dict, show_tags: bool = True, x0: int = 0,
                  extra: dict | None = None) -> _Outline:
    """The outline from column x0: rails, relation, label, #N tag, the extra runs
    a node carries (modifiers, a writer badge, a branch arm's label) and (for a
    state) the triggers that lead into it, one row each. A banner row (a section
    divider, a block's header) is drawn as its runs; a block header inside a
    unit sits at its next row's label column, the rails it interrupts bridged."""
    out = _Outline([], {}, {}, {}, {})
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
            out.ends.append(_put_runs(cv, x, y, row.runs))
            continue
        n, rel = row.node, row.rel
        stack = stack[:row.depth] + [n.name]
        out.chain_at[y] = tuple(stack)
        x = x0
        if row.depth:
            cv.put(x0, y, guide, TREE_STYLE)
            x = x0 + len(guide)
            if rel and rel != "─":
                cv.put(x, y, rel, REL_STYLE)
                x += len(rel)
            else:
                cv.put(x, y, "─", TREE_STYLE)
                x += 1
            x += 1
        label = node_label(n) + (" ▸" if row.collapsed else "")
        _border, text = node_styles(n)
        _put_runs(cv, x, y, label_runs(n) + ([(" ▸", (text[0], None, True))]
                                             if row.collapsed else []))
        x += len(label)
        if n.id in idx and n.id not in out.tagged and not show_tags:
            out.tagged[n.id] = y                # callouts point here with `#>` instead
        if n.id in idx and n.id not in out.tagged:  # `#N` on the node's first row
            tag = " " + note_tag(idx[n.id])
            tx = x
            for run, style in note_tag_runs(idx[n.id]):
                cv.put(tx, y, run, style)
                tx += len(run)
            x += len(tag)
            out.tagged[n.id] = y
        if n.id in extra and n.id not in extra_done:    # on the node's first row
            extra_done.add(n.id)
            x = _put_runs(cv, x, y, extra[n.id])
        if n.kind == "state":                   # the triggers that lead into this state
            into = sorted({e.label for e in row.graph.edges if e.dst == n.id and e.label})
            if into:
                cv.put(x + 1, y, " ".join(into), LABEL_STYLE)
                x += 1 + len(" ".join(into))
        out.ends.append(x)
        out.by_id.setdefault(n.id, []).append(y)
        out.node.setdefault(n.id, n)

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
                cv.put(x, y, "│", TREE_STYLE)
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


def _pack_lanes(lanes, left: int, node: dict, emitted: frozenset = frozenset()):
    """Give each lane a gutter column (interval-packed) and its style:
    (x, lo, hi, src rows, dst rows, kind, style). An emitted lane (an event
    drawn where it lands, see _collapse_events) takes the event colour."""
    cols, placed = [], []
    for lo, hi, src, dst, kind, sy, dy in lanes:
        x = left + _first_fit(cols, lo, hi) * LANE_GAP
        colour = (kind_color("event") if (src, dst, kind) in emitted
                  else _lane_colour(kind, node[src].kind))
        style = (colour, None, False)
        placed.append((x, lo, hi, sy, dy, kind, style))
    return placed


EMIT_MARK = "›"          # the source of a lane that carries an emitted event


def _draw_lanes(cv: Canvas, placed, ends, emitted: frozenset = frozenset()):
    """Verticals first; then each row's runs out to the lanes it taps, hopping
    (─│─) over lanes it merely crosses, so a joint (┤ ┴ ┬ ┼) only ever appears
    where a lane is actually tapped."""
    verticals = set()
    for x, lo, hi, _s, _d, kind, style in placed:
        if hi > lo:
            cv.path([(x, lo), (x, hi)], kind, style)
            verticals |= {(x, y) for y in range(lo, hi + 1)}

    taps = {}                                   # y → [(lane x, kind, style, role, mark)]
    for i, (x, lo, hi, sy, dy, kind, style) in enumerate(placed):
        mark = EMIT_MARK if i in emitted else SOURCE_MARK.get(kind, "●")
        for y in sy:
            taps.setdefault(y, []).append((x, kind, style, "src", mark))
        for y in dy:
            taps.setdefault(y, []).append((x, kind, style, "dst", mark))

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
        for x1, kind, style, role, _mark in order:
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
            if role == "dst" or both:
                heads.append((ends[y] + 1, y, "◀", style))
    for x, y, ch, st in heads:
        cv.put(x, y, ch, st)


def _payload_of(g, payloads: bool = True, mods: bool = False) -> dict:
    """(src, dst, kind) → the chip text its flow carries — its payload, and with
    `mods` its modifiers (`payload ┆ @timeout 30s ×3`) — across g and its expansions."""
    out = {}
    for sub in _walk(g):
        for e in sub.edges:
            text = chip_text(*chip_parts(e, payloads, mods))
            if text:
                out.setdefault((e.src, e.dst, e.kind), text)
    return out


def _tree_extras(g, access: bool, mods: bool, arms: dict) -> dict:
    """{node id: runs} drawn after a node's label in the tree: its modifiers (m),
    its writer badge (a), the branch arms it is the entry of (‹read›)."""
    extra = {}
    for cur in _walk(g):
        for nid, n in cur.nodes.items():
            text = mods_text(n.mods) if mods else ""
            if text and nid not in extra:
                extra[nid] = [(" ", None)] + mod_runs(text)
        if access:
            for sid, badge in writer_badges(cur).items():
                extra.setdefault(sid, []).append((" " + badge, (EDGE_COLOR["access"], None, True)))
    for nid, labels in arms.items():
        extra.setdefault(nid, []).extend(
            (f" ‹{label}›", (EDGE_COLOR["arm"], None, True)) for label in labels)
    return extra


def _join_marks(g) -> dict:
    """(src, dst, kind) → {"src" | "dst": join label}: the flows that leave or
    enter a drawn join (`&` `&?` `/`), across g and its expansions."""
    out = {}
    for cur in _walk(g):
        for e in cur.edges:
            for side in ("src", "dst"):
                idx = drawn_join(cur, e, side)
                if idx is not None:
                    out.setdefault((e.src, e.dst, e.kind), {})[side] = cur.joins[idx].kind
    return out


def _draw_join_taps(cv: Canvas, lanes, ends, joins: dict):
    """A joined flow's label on its taps, beside the row's label: `◀&` where a
    fork's branch arrives, `─&` where a fan-in's source leaves."""
    for _lo, _hi, src, dst, kind, sy, dy in lanes:
        mark = joins.get((src, dst, kind))
        if not mark:
            continue
        for side, ys in (("dst", dy), ("src", sy)):
            if side in mark:
                for y in ys:
                    cv.put(ends[y] + 2, y, mark[side], LABEL_STYLE)


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
                       trailing: dict, notes: str, moved: list | None = None) -> set:
    """The right margin, the mirror of the note callouts: on each flow's target row
    the payload it carries (a ┆chip┆) and the inline comment from its line; on a
    node's row the inline comment of the line that placed it. A dotted leader ties
    each to the row's rightmost tap, hopping (┄│┄) over lanes it crosses. Comments
    show as `#N` (markers) or their text (callouts). Returns the flow keys whose
    payloads were drawn. With `moved` (a list), a row's payloads and comment text
    are relocated instead: the row ends in a `┆a┆` marker and moved gets
    (letter, payloads, [(number, text)]); `#N` markers stay on the row."""
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
        if moved is not None:
            row_notes = sorted(notes_at.get(y, ()))
            go = [] if notes == "markers" else row_notes
            if chips.get(y) or go:                # the same content shares a letter
                item = (chips.get(y, []), go)
                letter = next((m[0] for m in moved if m[1:] == item), None)
                if letter is None:
                    letter = _letter(len(moved))
                    moved.append((letter, *item))
                x = _put_runs(cv, x, y, _chip_marker(letter)) + 1
            if notes == "markers":
                for num, _text in row_notes:
                    cv.put(x, y, f"#{num}", NOTE_STYLE["inline"])
                    x += len(f"#{num}") + 2
            continue
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


def _extras(g, idx: dict, notes: str, payloads: bool, drawn: frozenset = frozenset(),
            note_width: int = NOTE_WIDTH):
    """The lists under the tree: payloads not drawn as chips (when shown), then
    notes (markers mode, wrapped at note_width)."""
    extra = []
    pl = [f"  {edge_text(sub, e)} : {e.payload}" for sub in _walk(g) for e in sub.edges
          if e.payload and (e.src, e.dst, e.kind) not in drawn] if payloads else []
    if pl:
        extra += [[], [("── payloads ──", TITLE_STYLE)], []] + [[(p, PAYLOAD_STYLE)] for p in pl]
    if notes == "markers" and idx:
        extra += [[], [("── notes ──", TITLE_STYLE)], []] + note_rows(idx, note_width)
    return extra


def _with_callouts(rows, idx: dict, tagged: dict, tw: int = CALLOUT_TEXT):
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
            lines = _callout_lines(text, kind, tw)
            top = max(y, free)
            while top != y and top in anchors:  # a slid box never starts on another
                top += 1                        # note's row: its runs would merge
            boxes.append((y, top, lines, kind))
            free = top + len(lines) + (1 if kind == "block" else 0)
    cols = []                                   # leader columns: list of (lo, hi)
    leader_col = [None if top == y else _first_fit(cols, y, top) for y, top, _l, _n in boxes]
    box_w = tw + 4
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
            mc.put(2, top + j, ln.ljust(tw), style)
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
    for y, _top, _lines, kind in boxes:         # each leader ends `#>` at its entity
        mc.put(end - 1, y, "#>", NOTE_STYLE[kind])
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


def doc_mode(text: str) -> str:
    """The document's mode line (`#!sketch`, `#!craft`, …): its first `#!` line
    before any statement; "" when it has none."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#!"):
            return line.split()[0]
        if line and not line.startswith("#"):
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
         triggers: bool = True, spaced: bool = True, notes: str = "off",
         width: int | None = None, access: bool = False, mods: bool = False) -> int:
    """Print the drawing once. `width`: the columns to fit it to (None: its
    natural width); the legend wraps at the narrower of that and LEGEND_WIDTH.
    The summary line ends with the document's `#!mode`, when it has one."""
    use_dialect(dialect)
    text = path.read_text()
    g = _call(render.parse_document, text, dialect)
    rows, _w = (compose_tree(g, depth, triggers, spaced, notes, payloads, width, access, mods)
                if tree else compose(g, depth, payloads, notes, triggers, width, access, mods))
    out = [ansi(r, colour) for r in rows]
    if tree:
        legend_w = LEGEND_WIDTH if width is None else min(LEGEND_WIDTH, width)
        out += [""] + [ansi(ln, colour) for r in tree_legend(triggers, payloads, access, mods)
                       for ln in wrap_legend(r, legend_w)]
    out.append("")
    mode = doc_mode(text)
    out.append(f"{path.name}: {len(g.nodes)} nodes, {len(g.edges)} edges, "
               f"{len(g.expansions)} expansions" + (f" · {mode}" if mode else ""))
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
                 triggers: bool = True, spaced: bool = True, notes: str = "off",
                 access: bool = False, mods: bool = False):
        self.path = path
        self.show_access = access
        self.show_mods = mods
        self.mode = ""
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
        self._rows, self._width = [], 0  # the drawing at its natural width
        self._fit = None               # (cols, rows, width): the drawing fitted to cols

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
        self.mode = doc_mode(text)
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
        self._fit = None
        self._rows, self._width = self._compose(None)

    def _compose(self, width: int | None):
        if self.graph is None:
            return [], 0
        if self.tree:
            return compose_tree(self.graph, self.depth, self.show_triggers, self.spaced,
                                self.notes, self.payloads, width, self.show_access,
                                self.show_mods)
        return compose(self.graph, self.depth, self.payloads, self.notes,
                       self.show_triggers, width, self.show_access, self.show_mods)

    def fitted(self, cols: int):
        """(rows, width): the drawing rearranged to fit `cols` columns when it can
        be (see compose / compose_tree); cached until the view or the size changes."""
        if self._fit is None or self._fit[0] != cols:
            self._fit = (cols, *self._compose(cols))
        return self._fit[1], self._fit[2]

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
        legend = (tree_legend(self.show_triggers, self.payloads, self.show_access,
                              self.show_mods) if self.tree
                  else [graph_legend(self.show_triggers, self.payloads, self.show_access,
                                     self.show_mods)])
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
        if self.mode:
            left.append((f"{self.mode} ", MODE_STYLE))
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
        the drawing (rearranged to fit `cols` when it is wider — see fitted(); centred
        while it fits, scrolled when it still doesn't), the footer."""
        footer = self._footer_rows(cols)
        vh = self._vh = max(rows - 1 - len(footer), 1)
        body, W = self.fitted(cols)
        H = len(body)
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


def _width_arg(text: str) -> int:
    try:
        width = int(text)
    except ValueError:
        width = 0
    if width < 1:
        raise argparse.ArgumentTypeError(f"expected a number of columns >= 1, got {text!r}")
    return width


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
    ap.add_argument("--access", action="store_true",
                    help="draw the permission graph: principal → store, headed r / w / b")
    ap.add_argument("--mods", action="store_true",
                    help="draw modifiers: chips on edges, after node labels")
    ap.add_argument("--tree", action="store_true",
                    help="tree + wires: the composition tree as an outline, flows as lanes")
    ap.add_argument("--width", type=_width_arg, default=None, metavar="N",
                    help="--once: fit the drawing to N columns (default: the terminal's "
                         f"width, or {ONCE_WIDTH} when stdout is not a terminal)")
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
        width = a.width or (shutil.get_terminal_size().columns if tty_out else ONCE_WIDTH)
        return once(a.file, a.depth, a.payloads, not a.no_lint, dialect, colour, a.tree,
                    not a.no_triggers, not a.compact, a.notes, width, a.access, a.mods)
    tui(ViewState(a.file, a.depth, a.payloads, not a.no_lint, dialect, a.tree,
                  not a.no_triggers, not a.compact, a.notes, a.access, a.mods))
    return 0


if __name__ == "__main__":
    sys.exit(main())
