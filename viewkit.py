"""
viewkit.py — the drawing kit both views of view.py share.

Not a command: view.py (the app) loads it, and view_graph.py / view_tree.py
draw with it. It holds:

    styles      the theme's colours as (fg, bg, bold) styles — apply_theme(),
                use_theme(), use_dialect(), kind_color(), edge_style(), muted()
    Canvas      a grid of (char, style) cells with box-drawing strokes that merge
    runs        a glyph / payload / modifier / label as styled text runs; chips
    the model   helpers over render.py's Graph: expansions (_walk), joins,
                access, sections, control blocks, notes and their tags
    fit panels  the corner panels that take comments and payloads when a
                drawing is wider than the window (_fit_panel)
    checks      CheckMarks (findings named as a Scene names things) and their
                marks and styles, in the theme's ui.error / ui.warn roles
    output      ansi(), clip(), row_len(); doc_title(), doc_mode(), run_lint()

Theme application rebinds this module's style globals (GREY, EDGE_COLOR,
PAYLOAD_STYLE, … — see _theme_styles()), so other modules read them as
`kit.NAME` at call time, never as copies.
"""

from __future__ import annotations

import colorsys
import importlib.util
import re
import sys
import textwrap
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
           "note_block": "#8b7aad", "note_inline": "#a5d6ff", "name_saturation": "0.4",
           "bar_fg": "#c9d1d9", "bar_bg": "#161b22", "bar_name": "#e6edf3",
           "key_fg": "#e6edf3", "key_bg": "#30363d",
           "error": "#f85149", "warn": "#ffbf47", "ok": "#3fb950", "fill": "0.22",
           "frame": "#6e7681", "section": "#8b7aad", "mode": "#e3c000"},
    # Code roles (highlight/sigil.tmTheme): payloads are drawn highlighted.
    "syntax": {"operator": "#e85d9e", "cardinality": "#f59cc4", "modifier": "#ffe0b0",
               "keyword": "#c850e0", "ref": "#bc8cff", "string": "#a5d6ff",
               "number": "#79c0ff", "punct": "#586e75", "tag": "#c9d1d9",
               "call": "#5abea0", "call_name": "#f08cac"},
}
EDGE_ROLE = {"!>": "fail", "?>": "maybe", "~>": "async", "]>[": "split",
             "arm": "arm", "access": "access"}       # (+ a branch arm, a permission edge)
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})")


def _hex(value) -> str | None:
    """value as "#rrggbb" when it is a "#rrggbb" / "#rgb" colour, else None."""
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        return None
    return value if len(value) == 7 else "#" + "".join(ch * 2 for ch in value[1:])


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
    key = (str(colour), getattr(colour, "role", ""), NAME_SATURATION)   # one hex, two roles
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
                   for role in _BUILTIN_THEME["syntax"]},
        "NAME_SATURATION": _fraction(t["ui"].get("name_saturation"),
                                     _BUILTIN_THEME["ui"]["name_saturation"]),
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


# The built-in colours until a theme is applied (view.main() applies --theme /
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
    name = spec["label"](n) if "label" in spec else role_name(n)
    lead = ("~" if n.is_mutable else "") + ("*" if n.is_stream else "")
    return f"{lead}{spec.get('open', '[')}{name}{spec.get('close', ']')}"


def role_name(n) -> str:
    """A node's name, a generic role's generics in ‹ › (`Worker<N>` → `Worker‹N›`:
    N members of one role, not a parametric type)."""
    if not getattr(n, "is_role", False) or not n.name.endswith(">"):
        return n.name
    base = n.name.split("<", 1)[0]
    return f"{base}‹{n.name[n.name.index('<') + 1:-1]}›"


# A stream's mark beside its label where no box shape can show it (tree rows).
STREAM_MARK = "≋"


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
# lane (the a key) starts in its access letter: r read, w write, b borrow, ƀ a
# borrow narrowed to read (`@borrow(read)`: b with its write struck off).
SOURCE_MARK = {"->": "●", "~>": "○", "=>": "◆", "!>": "✖", "?>": "◇", "*>": "✱",
               "<->": "▶", "trigger": "◎",
               "access:r": "r", "access:w": "w", "access:b": "b", "access:ƀ": "ƀ"}


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
    """A payload as styled runs, colour-coded like the code highlighter: a call's
    ( ) in syntax.call, its name in the complement (syntax.call_name)."""
    runs, last, parens, pending = [], 0, [], False
    for m in _PAYLOAD_TOKEN.finditer(text):
        if m.start() > last:
            runs.append((text[last:m.start()], PAYLOAD_STYLE))
        role, tok = m.lastgroup, m.group()
        if role == "glyph":
            runs += glyph_runs(tok, _GLYPH_KIND[tok.lstrip("~*")[0]])
        elif role == "call":
            runs.append((tok, SYNTAX["call_name"]))
            pending = True
        elif tok == "(":
            parens.append(pending)
            runs.append((tok, SYNTAX["call"] if pending else SYNTAX["punct"]))
            pending = False
        elif tok == ")":
            runs.append((tok, SYNTAX["call"] if parens and parens.pop() else SYNTAX["punct"]))
        else:
            runs.append((tok, SYNTAX[role]))
        last = m.end()
    if last < len(text):
        runs.append((text[last:], PAYLOAD_STYLE))
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


def edge_mods(e) -> list:
    """An edge's modifiers as its chip lists them: the destination's cardinality
    written on the flow (Edge.card, `-> [App]×N`) as `×N` first, then Edge.mods
    (where a `×N` is a retry). A wire carries no card: just its mods."""
    card = getattr(e, "card", None)
    return ([("×", card)] if card else []) + list(e.mods or ())


BLOCK_PREVIEW = 24      # the most of a block-string's first line a chip shows


def block_string_of(e):
    """The text of an edge's (or a wire's edge's) `\"\"\"…\"\"\"` payload, or None."""
    body = getattr(e, "block_string", None)
    return body if body is not None else getattr(getattr(e, "edge", None), "block_string", None)


def block_lines(body: str) -> list:
    """A block-string's lines, the blank ones at its ends dropped, each stripped."""
    lines = [ln.strip() for ln in body.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def block_preview(body: str) -> str:
    """A block-string as a chip shows it: its first line (to BLOCK_PREVIEW
    characters, cut at a word) in triple quotes, `…` when there is more (`\"\"\"You are a strict
    rubric…\"\"\"`)."""
    lines = block_lines(body)
    first = lines[0] if lines else ""
    more = len(lines) > 1 or len(first) > BLOCK_PREVIEW
    if len(first) > BLOCK_PREVIEW:              # cut at a word, else mid-word
        cut = first[:BLOCK_PREVIEW + 1].rfind(" ")
        first = first[:cut if cut > 0 else BLOCK_PREVIEW].rstrip()
    return '"""' + first + ("…" if more else "") + '"""'


def shown_payload(e):
    """An edge's payload as written, a block-string's masked STR shown by its
    preview (block_preview)."""
    payload, body = e.payload, block_string_of(e)
    if payload and body is not None and render.BLOCK_SENTINEL in payload:
        payload = payload.replace(render.BLOCK_SENTINEL, block_preview(body), 1)
    return payload


def chip_parts(e, payloads: bool, mods: bool):
    """(payload, modifiers) an edge's chip shows — each None when not shown."""
    payload = shown_payload(e) if payloads else None
    mtext = mods_text(edge_mods(e)) if mods else ""
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


# ---------------------------------------------------------------------------
# Document → sections → styled rows: the model helpers both views draw from
# ---------------------------------------------------------------------------

CALLOUT_TEXT = 24                               # callout box text width, given room
# Comment text may scale to the window, between these. Below 16 columns a line
# holds two or three words and prose turns into a word ladder; past 40 a side
# note stops reading at a glance (half an 80-column terminal) and crowds the
# drawing. Boxes only grow past CALLOUT_TEXT to avoid cutting a comment off.
CALLOUT_MIN = 16
CALLOUT_MAX = 40
NOTE_WIDTH = 76                                 # notes list wrap width
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
    """A permission edge's kind: `access:r` read, `access:w` write, `access:b`
    borrow, `access:ƀ` a borrow narrowed to read (`@borrow(read)`). A borrow
    narrowed to write keeps `b`: only the write it lends is left."""
    if a.mode == "borrow" and getattr(a, "narrow", None) == "read":
        return "access:ƀ"
    return "access:" + a.mode[0]


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
    holding, after = {}, {}                     # edge key → [block index], in order
    for bi, b in enumerate(blocks):
        for key in dict.fromkeys(b.edges):
            holding.setdefault(key, []).append(bi)
        for key in dict.fromkeys(b.after):
            after.setdefault(key, []).append(bi)
    for k, e in enumerate(g.edges):
        key, best = (e.src, e.dst, e.kind), None
        for bi in holding.get(key, ()):
            lo, hi = blocks[bi].lines
            if lo <= e.line <= hi or not e.line:
                if best is None or hi - lo < blocks[best].lines[1] - blocks[best].lines[0]:
                    best = bi
        if best is None:
            for bi in after.get(key, ()):
                b = blocks[bi]
                if e.line >= b.lines[1]:
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


# Notes are tagged #N either way; colour tells a block comment (own lines above
# a statement, ui.note_block) from an inline one (trailing it, ui.note_inline).


def note_index(g) -> dict:
    """{node id: [(number, text, kind, edges), …]}, numbered in document order (top
    level first, then expansions). A node's block comments (about the component)
    merge into one note; each inline comment (about its line) stays its own note
    and keeps the (src, dst, kind) of the flows that line drew."""
    out, num = {}, 0
    for cur in _walk(g):
        for n in _notes_and_blocks(cur):
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


def _notes_and_blocks(g) -> list:
    """g's notes with, among them in line order, an inline note per edge with a
    `\"\"\"…\"\"\"` payload holding its full text (about the flow, so drawn on it
    and listed where notes are)."""
    blocks = sorted((e.line, i, e) for i, e in enumerate(getattr(g, "edges", []))
                    if getattr(e, "block_string", None) is not None)
    out, k = [], 0
    for n in getattr(g, "notes", []):
        while k < len(blocks) and blocks[k][0] < n.line:
            out.append(_block_note(blocks[k][2]))
            k += 1
        out.append(n)
    return out + [_block_note(b[2]) for b in blocks[k:]]


def _block_note(e):
    """The note holding edge e's block-string, one line of it per text line."""
    text = '"""' + "\n".join(block_lines(e.block_string)) + '"""'
    return render.Note(e.src, text, e.line, "inline", (e.key,))


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
        wrapped = [w for part in text.split("\n")
                   for w in textwrap.wrap(part, max(width - len(tag), 20)) or [""]]
        for k, ln in enumerate(wrapped):
            rows.append([(tag if k == 0 else " " * len(tag), NOTE_STYLE[kind]),
                         (ln, NOTE_STYLE[kind] if kind == "inline" else NOTE_TEXT_STYLE)])
    return rows


class RuleRow(list):
    """A title row (`── name ───`) whose rule is stretched to the drawing's width
    once that is known (stretch_rules), so every title looks the same."""


def section_rule(name: str, width: int = 0) -> list:
    """`── L2 · Payments ──`, the rule run out to `width` columns: the rails in
    ui.section, the name as code (a glyph in it keeps its colours). Every title —
    sections, expansions, state machines, lists — is one of these."""
    runs = [("── ", SECTION_STYLE)] + [(t, (st[0], st[1], True)) for t, st in payload_runs(name)]
    n = row_len(runs)
    return RuleRow(runs + [(" " + "─" * max(width - n - 1, 2), SECTION_STYLE)])


def stretch_rules(rows, width: int):
    """Run every title rule out to `width` columns."""
    for row in rows:
        if isinstance(row, RuleRow) and row_len(row) < width:
            text, style = row[-1]
            row[-1] = (text + "─" * (width - row_len(row)), style)
    return rows


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
# Legends (the samples both views' legend rows share) and documents
# ---------------------------------------------------------------------------

ARROW_LEGEND = (("->", "call"), ("~>", "async"), ("=>", "produces"), ("!>", "error"),
                ("?>", "maybe"), ("*>", "broadcast"), ("<->", "both ways"))


def _stroke_sample(kind: str) -> str:
    return {"heavy": "━", "double": "═", "dashed": "╌", "dotted": "┄",
            "hdash": "╍"}.get(_stroke(kind), "─")


# ---------------------------------------------------------------------------
# Checks overlay — composition-check findings (check.py) marked on a drawing.
# view.py maps each finding's anchor onto the Scene a view draws (CheckMarks);
# both views then mark what it names alike: a marked box's border / a marked
# wire's stroke in its worst finding's colour, and each finding's number after
# the node's label (graph: beside a wire's head; tree: on its target's row).
# Colours are the theme's ui.error / ui.warn roles only; an acknowledged
# finding is drawn dimmed (the role's muted colour), never bold.
# ---------------------------------------------------------------------------

CHECK_GLYPH = {"error": "◆", "warn": "▲", "info": "△"}
ACKED_GLYPH = "✓"                                 # an acknowledged finding, dimmed
_CHECK_RANK = {"info": 0, "warn": 1, "error": 2}


class CheckMark(NamedTuple):
    """One finding as a drawing marks it: its number in the checks list, its
    severity ("error" | "warn" | "info") and whether it is acknowledged."""
    number: int
    severity: str
    acked: bool = False


class CheckMarks(NamedTuple):
    """The findings a drawing marks, named as its Scene names things:
    {node id: (CheckMark, …)} and {wire ident: (CheckMark, …)}, number order."""
    nodes: dict
    wires: dict

    def by_key(self) -> dict:
        """{wire key: (CheckMark, …)}: the wires' marks gathered by the stroke
        that draws them (a wire's ident is its key and an ordinal)."""
        out = {}
        for ident, marks in self.wires.items():
            out.setdefault(tuple(ident[:-1]), []).extend(marks)
        return {key: tuple(sorted(set(ms))) for key, ms in out.items()}


def check_mark_style(m: CheckMark) -> tuple:
    """A finding's style: ui.error for an error, ui.warn for a warning (bold)
    or an info (not bold); acknowledged, that colour muted."""
    colour = SEVERITY_COLOR["error" if m.severity == "error" else "warn"]
    if m.acked:
        return (muted(colour), None, False)
    return (colour, None, m.severity != "info")


def check_worst(marks) -> CheckMark:
    """The mark a stroke or border is drawn in: an open finding before an
    acknowledged one, then the most severe, then the first."""
    return max(marks, key=lambda m: (not m.acked, _CHECK_RANK.get(m.severity, 0), -m.number))


def check_glyph(m: CheckMark) -> str:
    """`◆3` / `▲3` / `△3`, or `✓3` for an acknowledged finding."""
    return (ACKED_GLYPH if m.acked else CHECK_GLYPH.get(m.severity, "△")) + str(m.number)


def check_runs(marks) -> list:
    """The runs after a label (or beside a head) for its findings: ` ▲1 ◆3`."""
    return [(" " + check_glyph(m), check_mark_style(m)) for m in marks]


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
