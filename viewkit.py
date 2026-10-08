"""
viewkit.py — the drawing kit both views of view.py share.

Not a command: view.py (the app) loads it, and view_graph.py / view_tree.py
draw with it. It holds:

    styles      the theme's colours as (fg, bg, bold) styles — apply_theme(),
                use_theme(), use_dialect(), kind_color(), edge_style(), muted()
    cells       cell_width() — a drawn width in terminal columns (wide CJK 2,
                combining marks 0), never len() — and cut_cells, ljust_cells,
                wrap_cells by it
    Canvas      a grid of (char, style) cells with box-drawing strokes that merge
    frames      FrameMemo, Plan, Retained: what a run drawn frame after frame
                keeps — a drawing laid out once, then only what changed repainted
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
import itertools
import re
import sys
import textwrap
import unicodedata
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
           "sim_trail": "0.6", "sim_faint": "0.4",
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


_FADED: dict = {}


def faded(colour: "Colour", k: float, kind: str) -> "Colour":
    """A colour mixed toward the background, keeping fraction `k` of it — a sim
    overlay's rank: "trail" (a wire taken before, ui.sim_trail) the colour,
    "faint" (never taken, ui.sim_faint) its muted() colour. Its role,
    "<kind>:<role>", lets the page do the same. Raises ValueError for another kind."""
    if kind not in ("trail", "faint"):
        raise ValueError(f"kind must be trail or faint, not {kind!r}")
    role = getattr(colour, "role", "")
    base = muted(colour) if kind == "faint" else colour
    key = (str(base), role, kind, k, str(BG))
    if key not in _FADED:
        fg = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
        bg = [int(BG[i:i + 2], 16) for i in (1, 3, 5)]
        mixed = "#%02x%02x%02x" % tuple(round(b + (f - b) * k) for f, b in zip(fg, bg))
        _FADED[key] = Colour(mixed, f"{kind}:{role}" if role else "")
    return _FADED[key]


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
        "SIM_TRAIL": _fraction(t["ui"].get("sim_trail"), _BUILTIN_THEME["ui"]["sim_trail"]),
        "SIM_FAINT": _fraction(t["ui"].get("sim_faint"), _BUILTIN_THEME["ui"]["sim_faint"]),
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


_STYLED = 0     # bumped when a theme or a dialect is applied: FrameMemo drops its plans


def _refresh_kinds() -> None:
    global _STYLED
    _STYLED += 1
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
    return _STROKES.get(_base_kind(kind), "light")


_STROKES = {"=>": "heavy", "*>": "double", "~>": "dashed", "trigger": "hdash",
            "?>": "dotted", "]>[": "dotted", "arm": "dotted", "access": "dotted"}


# ---------------------------------------------------------------------------
# Cells — what a drawing measures. A terminal shows a wide character (CJK,
# east_asian_width W / F) in two columns and a combining mark in none, so a
# drawn width is cell_width(text), never len(text). A Canvas cell is one
# column: a wide character takes two, the second holding WIDE_TAIL.
# ---------------------------------------------------------------------------

WIDE_TAIL = ""          # the second cell of a wide character: draws nothing
_ZERO_WIDTH = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"}   # ZWSP ZWNJ ZWJ WJ BOM
_CHAR_CELLS: dict = {}  # a non-ASCII character → its cells, as char_cells finds them


def char_cells(ch: str) -> int:
    """The columns one character takes: 2 wide (W / F), 0 a combining mark or a
    zero-width character, else 1."""
    if ch < "\x80":
        return 1
    n = _CHAR_CELLS.get(ch)
    if n is None:
        if unicodedata.category(ch) in ("Mn", "Me") or ch in _ZERO_WIDTH:
            n = 0
        else:
            n = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        _CHAR_CELLS[ch] = n
    return n


def cell_width(s: str) -> int:
    """The columns text takes in a terminal (len(s) for ASCII)."""
    if s.isascii():
        return len(s)
    return sum(map(char_cells, s))


def cut_cells(s: str, n: int) -> str:
    """The longest start of s that fits n columns (s[:n] for ASCII); a wide
    character that would straddle the edge is left out, a combining mark kept
    with its base."""
    if s.isascii():
        return s[:max(n, 0)]
    used = 0
    for k, ch in enumerate(s):
        used += char_cells(ch)
        if used > n:
            return s[:k]
    return s


def ljust_cells(s: str, n: int, fill: str = " ") -> str:
    """s padded with fill to n columns (str.ljust by drawn width)."""
    return s + fill * (n - cell_width(s))


_SPACES = re.compile(r"[ \t\n\r\f\v]+")       # textwrap's whitespace (not \xa0)


def wrap_cells(text: str, width: int, indent: str = "", hyphens: bool = True,
               long_words: bool = True) -> list:
    """textwrap.wrap by drawn width (indent: its subsequent_indent, hyphens:
    break_on_hyphens, long_words: break_long_words). Text whose characters
    are one column each gets textwrap's own lines; otherwise words fill lines
    greedily, and a word wider than its line is cut by columns — even with
    long_words=False when it holds a wide character (CJK has no spaces to
    break at)."""
    if cell_width(text) == len(text) and cell_width(indent) == len(indent):
        return textwrap.wrap(text, width, subsequent_indent=indent,
                             break_on_hyphens=hyphens, break_long_words=long_words)
    lines, line = [], ""                        # line: the open line's words, no indent

    def room() -> int:
        lead = cell_width(indent) if lines else 0
        return max(width - lead - (cell_width(line) + 1 if line else 0), 0)

    def close():
        nonlocal line
        lines.append((indent if lines else "") + line)
        line = ""

    for word in _SPACES.split(text.strip()):
        cut = long_words or cell_width(word) != len(word)
        if line and cell_width(word) > room() and (
                not cut or cell_width(word) <= width - cell_width(indent)):
            close()                             # it fits a line of its own: start one
        while cut and word and cell_width(word) > room():
            head = cut_cells(word, room())
            if not head and not line:           # not one character fits: take one anyway
                head = word[0]
            if head:
                line = line + " " + head if line else head
                word = word[len(head):]
            close()
        if word:
            if line and cell_width(word) > room():
                close()
            line = line + " " + word if line else word
    if line:
        close()
    return lines


class Probe(tuple):
    """A style that draws exactly like the (fg, bg, bold) it wraps but equals
    only another Probe, so Canvas.rows never merges it into a plain run and
    the cells drawn in it can be found in the finished rows (probed_box): a
    view's sim focus — where a frame's action is — read back out of a drawing
    made with its tokens and active nodes in Probe styles."""
    __slots__ = ()

    def __eq__(self, other):
        return isinstance(other, Probe) and tuple.__eq__(self, other)

    def __ne__(self, other):
        return not self == other

    __hash__ = tuple.__hash__


def probed(runs: list) -> list:
    """runs with every style a Probe (an unstyled run a plain-text Probe)."""
    return [(text, Probe(style if style is not None else (None, None, False)))
            for text, style in runs]


def probed_box(rows) -> tuple | None:
    """(x, y, w, h) around every cell drawn in a Probe style; None: none."""
    cells = []
    for y, row in enumerate(rows):
        x = 0
        for text, style in row:
            n = cell_width(text)
            if isinstance(style, Probe) and n:
                cells += [(x, y), (x + n - 1, y)]
            x += n
    if not cells:
        return None
    xs, ys = [x for x, _y in cells], [y for _x, y in cells]
    return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def _line_cell(line) -> tuple | None:
    """A Canvas.lines entry [mask, stroke, style] as the (char, style) it draws."""
    if line is None:
        return None
    mask, stroke, style = line
    ch = _LINE_CHARS.get((stroke, mask))
    if ch is None:
        ch = _LINE_CHARS[(stroke, mask)] = _TABLES.get(stroke, _LIGHT).get(
            mask, _LIGHT.get(mask, "┼"))
    return ch, style


_LINE_CHARS = {}    # (stroke, mask) → its char, as _line_cell finds them


class Canvas:
    CORNERS: dict = {}          # a line's char → the char drawn instead (a subclass's look)

    def __init__(self):
        self.text: dict = {}    # (x, y) → (char, style)
        self.lines: dict = {}   # (x, y) → [mask, stroke, style]
        self.w = 0
        self.h = 0
        self._kept = None       # a kept canvas (keep_rows): y → {span: its runs}, once worked out
        self._xs = None         # … and y → {span: the columns drawn in it} (ROW_SPAN wide)
        self._wide = False      # a wide character was put: rows mend split ones
        self._under = {}        # a kept canvas: cell → what this frame's overlay() covered

    def _grow(self, x, y):
        self.w = max(self.w, x + 1)
        self.h = max(self.h, y + 1)

    def put(self, x, y, s, style=None):
        """Text from column x on row y: one cell a character, two a wide one
        (its second WIDE_TAIL), a combining mark joined to the character before
        (a wide one's first cell, never its tail)."""
        if not s:
            return
        if s.isascii():
            n = len(s)
            self.text.update(zip(zip(range(x, x + n), itertools.repeat(y)),
                                 zip(s, itertools.repeat(style))))
            self._grow(x + n - 1, y)
            return
        at = x
        base = None                     # the last character's own cell (not its tail)
        for ch in s:
            k = char_cells(ch)
            if k == 0:                  # a combining mark: onto that character's cell
                if base is not None:
                    self.text[(base, y)] = (self.text[(base, y)][0] + ch, style)
                continue
            base = at
            self.text[(at, y)] = (ch, style)
            if k == 2:
                self.text[(at + 1, y)] = (WIDE_TAIL, style)
                self._wide = True
            at += k
        if at > x:
            self._grow(at - 1, y)

    def link(self, a, b, kind, style, fixed=frozenset()):
        """Connect adjacent cells a → b with a line of the given arrow kind. A cell
        takes the higher-ranked stroke of the lines through it, unless it is in
        `fixed` (its stroke is settled; the line only joins it)."""
        (ax, ay), (bx, by) = a, b
        d = R if bx > ax else L if bx < ax else D if by > ay else U
        stroke = _stroke(kind)
        self._join(a, d, stroke, style, fixed)
        self._join(b, _OPP[d], stroke, style, fixed)
        self._grow(max(ax, bx), max(ay, by))

    def _join(self, cell, bit, stroke, style, fixed=frozenset()):
        """link()'s half at one cell: its mask gains bit, its stroke the higher-ranked."""
        cur = self.lines.get(cell)
        if cur is None:
            self.lines[cell] = [bit, stroke, style]
            return
        cur[0] |= bit
        if _STROKE_RANK[stroke] > _STROKE_RANK[cur[1]] and cell not in fixed:
            cur[1], cur[2] = stroke, style

    def stub(self, cell, bit, kind, style):
        """Half a link: a line from `cell` toward one neighbour, not into it."""
        self.lines.setdefault(cell, [0, _stroke(kind), style])[0] |= bit

    def path(self, pts, kind, style):
        """link() along a polyline through pts (inlined: the views' hot loop)."""
        stroke = _stroke(kind)
        rank, lines = _STROKE_RANK[stroke], self.lines
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            dx = (x2 > x1) - (x2 < x1)
            dy = (y2 > y1) - (y2 < y1)
            if not (dx or dy):
                continue
            d = R if dx > 0 else L if dx < 0 else D if dy > 0 else U
            back = _OPP[d]
            x, y = x1, y1
            while (x, y) != (x2, y2):
                for cell, bit in (((x, y), d), ((x + dx, y + dy), back)):
                    cur = lines.get(cell)
                    if cur is None:
                        lines[cell] = [bit, stroke, style]
                    else:
                        cur[0] |= bit
                        if rank > _STROKE_RANK[cur[1]]:
                            cur[1], cur[2] = stroke, style
                x, y = x + dx, y + dy
            self._grow(max(x1, x2), max(y1, y2))

    def run(self, x0, x1, y, kind, style, hops=None, fixed=frozenset()) -> set:
        """A line x0 → x1 along row y that hops every column x where hops(x): it
        stops a cell short on each side (─│─), so it never reads as joined there.
        `fixed` as for link(). Returns the cells it drew into."""
        drawn = set()
        if x1 <= x0:
            return drawn
        stroke, lines = _stroke(kind), self.lines
        rank = _STROKE_RANK[stroke]
        hop = [hops(x) for x in range(x0, x1 + 1)] if hops is not None else None
        right = None                    # the rightmost cell a link reached
        for x in range(x0, x1):
            a, b = (x, y), (x + 1, y)
            a_hop, b_hop = (hop[x - x0], hop[x - x0 + 1]) if hop else (False, False)
            if a_hop and b_hop:
                continue
            if b_hop:
                self.stub(a, R, kind, style)
                drawn.add(a)
            elif a_hop:
                self.stub(b, L, kind, style)
                drawn.add(b)
            else:                       # link(a, b), inlined: _join at each end
                for cell, bit in ((a, R), (b, L)):
                    cur = lines.get(cell)
                    if cur is None:
                        lines[cell] = [bit, stroke, style]
                    else:
                        cur[0] |= bit
                        if rank > _STROKE_RANK[cur[1]] and cell not in fixed:
                            cur[1], cur[2] = stroke, style
                drawn.add(a)
                drawn.add(b)
                right = x + 1
        if right is not None:
            self._grow(right, y)
        return drawn

    def blit(self, other: "Canvas", ox: int, oy: int):
        """Copy another canvas's cells in at an offset (lines keep their strokes)."""
        for (x, y), v in other.text.items():
            self.text[(x + ox, y + oy)] = v
        for (x, y), v in other.lines.items():
            self.lines[(x + ox, y + oy)] = list(v)
        if other.w and other.h:
            self._grow(ox + other.w - 1, oy + other.h - 1)
        self._wide = self._wide or other._wide

    def cell(self, x, y):
        if (x, y) in self.text:
            return self.text[(x, y)]
        if (x, y) in self.lines:
            ch, style = _line_cell(self.lines[(x, y)])
            return self.CORNERS.get(ch, ch), style
        return " ", None

    def rows(self):
        """Yield each row as a list of (run_text, style) runs."""
        w, h = self.w, self.h
        if self._kept is not None:                  # a kept canvas: each span worked out once
            for y in range(h):
                yield self._kept_row(y, w)
            return
        if type(self).cell is not Canvas.cell:      # a subclass's cells: ask for each
            grid = [{x: self.cell(x, y) for x in range(w)} for y in range(h)]
        else:                                       # else only the drawn cells, by row
            grid, corners = [{} for _y in range(h)], self.CORNERS
            for (x, y), line in self.lines.items():
                if 0 <= x < w and 0 <= y < h:
                    grid[y][x] = _line_cell(line)
                    if corners:
                        ch, style = grid[y][x]
                        grid[y][x] = corners.get(ch, ch), style
            for (x, y), v in self.text.items():
                if 0 <= x < w and 0 <= y < h:
                    grid[y][x] = v
        for cells in grid:
            yield self._runs(self._mend(cells), w)

    def _mend(self, cells: dict) -> dict:
        """A row's cells ({x: (char, style)}) with every wide character that
        lost a half to a later put drawn as a blank, so the row keeps its
        columns. Unchanged when no wide character was put."""
        if not self._wide:
            return cells
        for x, (ch, st) in list(cells.items()):
            if ch == WIDE_TAIL:
                head = cells.get(x - 1)
                if head is None or not head[0] or char_cells(head[0][0]) != 2:
                    cells[x] = (" ", st)
            elif ch and char_cells(ch[0]) == 2:
                tail = cells.get(x + 1)
                if tail is None or tail[0] != WIDE_TAIL:
                    cells[x] = (" ", st)
        return cells

    @staticmethod
    def _runs(cells: dict, w: int) -> list:
        """One row's runs: its drawn cells ({x: (char, style)}) merged by style,
        the blanks between them unstyled, the last run's trailing blanks cut."""
        return _cut_tail(Canvas._span(cells, 0, w))

    @staticmethod
    def _span(cells: dict, lo: int, hi: int) -> list:
        """The runs of columns lo … hi-1 of a row (`cells`: its drawn cells
        there, {x: (char, style)}): merged by style, the blanks unstyled, up
        to hi (no blanks cut)."""
        runs = []
        last = None                     # the open run: [chars, style]
        at = lo                         # the next column to fill
        for x in sorted(cells) + [hi]:
            if x > at:                  # blank cells up to x
                if last is not None and last[1] is None:
                    last[0].append(" " * (x - at))
                else:
                    last = [[" " * (x - at)], None]
                    runs.append(last)
            if x == hi:
                break
            ch, st = cells[x]
            if last is not None and last[1] == st:
                last[0].append(ch)
            else:
                last = [[ch], st]
                runs.append(last)
            at = x + 1
        return [("".join(t), s) for t, s in runs]

    def _kept_row(self, y: int, w: int) -> list:
        """Row y of a kept canvas: each span of ROW_SPAN columns worked out once
        (until a cell of it changes), the spans' runs joined — the row as
        _runs works it out. A row with a wide character or a subclass's
        cells is worked out whole (a wide character may straddle two spans)."""
        spans = self._kept.setdefault(y, {})
        if self._wide or type(self).cell is not Canvas.cell:
            if None not in spans:
                spans[None] = self._runs(self._mend(self._row_cells(y)), w)
            return list(spans[None])
        xs, out = self._xs.get(y, {}), []
        for k in range((w + ROW_SPAN - 1) // ROW_SPAN):
            lo, hi = k * ROW_SPAN, min((k + 1) * ROW_SPAN, w)
            got = spans.get(k)
            if got is None or got[0] != hi:
                got = spans[k] = (hi, self._span(self._cells_at(y, xs.get(k, ())), lo, hi))
            _join_runs(out, got[1])
        return _cut_tail(out)

    def _cells_at(self, y: int, xs) -> dict:
        """{x: (char, style)} of a kept canvas's row y at the columns xs."""
        out, corners = {}, self.CORNERS
        for x in xs:
            if not 0 <= x < self.w:
                continue
            v = self.text.get((x, y))
            if v is None:
                ch, style = _line_cell(self.lines[(x, y)])
                v = (corners.get(ch, ch), style) if corners else (ch, style)
            out[x] = v
        return out

    def _row_cells(self, y: int) -> dict:
        """{x: (char, style)}: the cells rows() reads on row y of a kept canvas."""
        if type(self).cell is not Canvas.cell:
            return {x: self.cell(x, y) for x in range(self.w)}
        out, corners = {}, self.CORNERS
        for x in sorted(x for xs in self._xs.get(y, {}).values() for x in xs):
            if not 0 <= x < self.w:
                continue
            v = self.text.get((x, y))
            if v is None:
                ch, style = _line_cell(self.lines[(x, y)])
                v = (corners.get(ch, ch), style) if corners else (ch, style)
            out[x] = v
        return out

    def keep_rows(self) -> "Canvas":
        """This canvas kept from frame to frame of a run (Retained): its rows are
        worked out once each and kept, and from now on only splice() may
        change it. Returns itself."""
        self._kept, self._xs = {}, {}
        for x, y in itertools.chain(self.text, self.lines):
            self._xs.setdefault(y, {}).setdefault(x // ROW_SPAN, set()).add(x)
        return self

    def splice(self, other: "Canvas", ys) -> None:
        """A kept canvas's rows `ys` replaced by the same rows of `other` (a
        drawing of the same size whose rows ys are right; the rest of it may
        be anything): their cells are other's, their runs worked out again."""
        ys = set(ys)
        for y in ys:
            for xs in self._xs.pop(y, {}).values():
                for x in xs:
                    self.text.pop((x, y), None)
                    self.lines.pop((x, y), None)
            self._kept.pop(y, None)
        for (x, y), v in other.text.items():
            if y in ys:
                self.text[(x, y)] = v
                self._xs.setdefault(y, {}).setdefault(x // ROW_SPAN, set()).add(x)
        self._wide = self._wide or other._wide
        for (x, y), v in other.lines.items():
            if y in ys:
                self.lines[(x, y)] = list(v)
                self._xs.setdefault(y, {}).setdefault(x // ROW_SPAN, set()).add(x)

    def patch(self, other: "Canvas", cells) -> None:
        """A kept canvas's `cells` replaced by the same cells of `other` (a
        drawing whose cells `cells` are right; elsewhere it may be anything):
        each takes other's text and line there, or none; only their rows are
        worked out again. splice() by the cell, for a drawing whose rows are
        wide (a row of many elements, a few of which look different)."""
        text, lines = other.text, other.lines
        for cell in cells:
            self._set(cell, text.get(cell), lines.get(cell))
        self._wide = self._wide or other._wide

    def _set(self, cell, text, line) -> None:
        """One cell of a kept canvas set to `text` and `line` (None: none)."""
        x, y = cell
        if text is None:
            self.text.pop(cell, None)
        else:
            self.text[cell] = text
        if line is None:
            self.lines.pop(cell, None)
        else:
            self.lines[cell] = list(line)
        k = x // ROW_SPAN
        xs = self._xs.setdefault(y, {}).setdefault(k, set())
        if text is None and line is None:
            xs.discard(x)
        else:
            xs.add(x)
            self._grow(x, y)
        spans = self._kept.get(y)
        if spans is not None:
            spans.pop(k, None)
            spans.pop(None, None)

    def overlay(self, x, y, s, style=None) -> None:
        """put() onto a kept canvas for one frame only (a run's tokens): the
        cells it covers remember what they held, and clear_overlay() puts
        that back. A later overlay over an earlier one wins its cells."""
        top = Canvas()
        top.put(x, y, s, style)
        for cell, v in top.text.items():
            if cell not in self._under:
                self._under[cell] = self.text.get(cell)
            self._set(cell, v, self.lines.get(cell))
        self._wide = self._wide or top._wide

    def clear_overlay(self) -> None:
        """A kept canvas as it was before this frame's overlay() calls."""
        under, self._under = self._under, {}
        for cell, v in under.items():
            self._set(cell, v, self.lines.get(cell))


ROW_SPAN = 128      # a kept canvas works a row out in spans this wide (Canvas._kept_row)


def _join_runs(out: list, runs: list) -> None:
    """runs appended to out, the first merged into out's last when they share a style."""
    if out and runs and out[-1][1] == runs[0][1]:
        out[-1] = (out[-1][0] + runs[0][0], out[-1][1])
        out.extend(runs[1:])
    else:
        out.extend(runs)


def _cut_tail(runs: list) -> list:
    """A row's runs with the last one's trailing blanks cut (and it dropped when
    nothing is left of it)."""
    if runs:
        runs[-1] = (runs[-1][0].rstrip(), runs[-1][1])
    return [(t, s) for t, s in runs if t]


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
# Frames — what drawing a run frame after frame keeps. A run's frames differ
# only in how things look (a wire lit or muted, a label's status, a badge, a
# token's cell); the layout holds still (every badge padded to its widest over
# the run). So a view lays a drawing out once per plan (FrameMemo) and repaints
# only the rows of what looks different (Retained).
# ---------------------------------------------------------------------------

class Plan:
    """One drawing's plan, kept while its run plays: `held`, what the view
    works out once (its Scene, the choices its wrap ladder made); and the
    drawings one compose makes, in the order it makes them (slot()), so the
    next frame's compose finds each where the last one left it."""

    def __init__(self):
        self.held: dict = {}
        self._slots: list = []
        self._at = 0

    def begin(self) -> "Plan":
        """Start a compose: slot() hands out the slots from the first again."""
        self._at = 0
        return self

    def slot(self) -> dict:
        """The next drawing's slot (a dict the view fills; {} the first time)."""
        if self._at == len(self._slots):
            self._slots.append({})
        self._at += 1
        return self._slots[self._at - 1]

    def sub(self, name) -> "Plan":
        """The plan of one way of drawing (a step of a wrap ladder, taken on
        some frames only), slots of its own, begun."""
        if ("sub", name) not in self.held:
            self.held[("sub", name)] = Plan()
        return self.held[("sub", name)].begin()


def held(plan: Plan | None, name: str, make):
    """make(), worked out once per plan (kept in plan.held under `name`); each
    time without a plan."""
    if plan is None:
        return make()
    if name not in plan.held:
        plan.held[name] = make()
    return plan.held[name]


def slot(plan: Plan | None) -> dict | None:
    """plan's next slot (Plan.slot); None without a plan."""
    return plan.slot() if plan is not None else None


class FrameMemo:
    """What a caller that draws a run frame after frame (view.ViewState, a
    pane) keeps between its frames: a Plan per drawing — a view, its options
    and width, the document, the run and the checks overlay drawn — the
    newest KEEP of them. Pass one to view.compose_view for every frame of a
    run; a drawing made with it is the drawing made without it. A theme or a
    dialect applied in between starts every plan afresh (what they keep is
    drawn in the colours and kinds of then)."""
    KEEP = 8

    def __init__(self):
        self._plans: list = []          # (key, held objects, Plan), newest last

    def plan(self, key: tuple, holds: tuple) -> Plan:
        """The Plan of the drawing `key` names (the view's name and options) of
        the objects `holds` (the document, the run, the overlay: the same
        objects, not equal ones), begun (Plan.begin)."""
        key = (_STYLED,) + key
        for i, (k, h, p) in enumerate(self._plans):
            if k == key and len(h) == len(holds) and all(a is b for a, b in zip(h, holds)):
                self._plans.append(self._plans.pop(i))
                return p.begin()
        p = Plan()
        self._plans.append((key, holds, p))
        del self._plans[:-self.KEEP]
        return p.begin()


class Retained:
    """A drawing kept from frame to frame of a run: its canvas, and for each
    element drawn on it (a box, a wire, the tokens …) the rows it takes and the
    look it was drawn with. repaint() redraws only the rows of the elements
    whose look or rows changed. Looks compare by value, as Canvas.rows merges
    runs: a colour by its hex, whatever its theme role."""

    def __init__(self, canvas: Canvas, now: dict):
        """`now`: {element: (its rows, its look)} — every element of the drawing."""
        self.canvas = canvas.keep_rows()
        self.now = now

    def repaint(self, now: dict, paint) -> Canvas:
        """The canvas as drawn with the looks `now` (as __init__'s): the rows of
        every element whose look or rows changed since the last paint (both its
        old rows and its new) come from paint(rows) — a drawing whose rows
        `rows` are right (of every element taking any of them, the rest may be
        left out); the others are kept."""
        old, dirty = self.now, set()
        for e, (rows, look) in now.items():
            was = old.get(e)
            if was is None:
                dirty.update(rows)
            elif was[0] is not rows and was[0] != rows:
                dirty.update(was[0])
                dirty.update(rows)
            elif was[1] != look:
                dirty.update(rows)
        for e in old.keys() - now.keys():
            dirty.update(old[e][0])
        dirty = frozenset(y for y in dirty if 0 <= y < self.canvas.h)
        if dirty:
            self.canvas.splice(paint(dirty), dirty)
        self.now = now
        return self.canvas


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
    if arg and cell_width(arg) > MOD_ARG_MAX:
        arg = cut_cells(arg, MOD_ARG_MAX - 1) + "…"
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
    more = len(lines) > 1 or cell_width(first) > BLOCK_PREVIEW
    if cell_width(first) > BLOCK_PREVIEW:       # cut at a word, else mid-word
        cut = cut_cells(first, BLOCK_PREVIEW + 1).rfind(" ")
        first = (first[:cut] if cut > 0 else cut_cells(first, BLOCK_PREVIEW)).rstrip()
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
        x += cell_width(text)
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

# The note-index key of the document's own notes (a header comment that precedes
# no statement): listed with the notes, tagged on nothing. Node ids never hold
# `@`, so neither this nor a block_note_key (BLOCK_NOTE…) can meet one.
DOC_NOTE = "@document"
BLOCK_NOTE = "@block:"


def block_note_key(b) -> str:
    """The note-index key of a control block's notes (a comment above its
    glyph-less header): its frame title (graph) or header row (tree) is tagged."""
    return f"{BLOCK_NOTE}{b.lines[0]}-{b.lines[1]}"


def note_key(g, n) -> str:
    """Where note n (of graph g) is indexed: its node id, its block's key, or
    DOC_NOTE."""
    if n.node is not None:
        return n.node
    bi = getattr(n, "block", None)
    return block_note_key(g.blocks[bi]) if bi is not None else DOC_NOTE


def note_index(g) -> dict:
    """{node id: [(number, text, kind, edges), …]}, numbered in document order (top
    level first, then expansions). A node's block comments (about the component)
    merge into one note; each inline comment (about its line) stays its own note
    and keeps the (src, dst, kind) of the flows that line drew. A control block's
    notes are keyed block_note_key; the document's are keyed DOC_NOTE (note_key)
    and merge into one note numbered 0, so the numbers tags show stay 1, 2, …"""
    out, num = {}, 0
    for cur in _walk(g):
        for n in _notes_and_blocks(cur):
            kind = getattr(n, "kind", "block")
            entries = out.setdefault(note_key(cur, n), [])
            block = next((i for i, e in enumerate(entries) if e[2] == "block"), None)
            if kind == "block" and block is not None:
                b = entries[block]
                entries[block] = (b[0], f"{b[1]} · {n.text}", "block", ())
                continue
            key = note_key(cur, n)
            if key != DOC_NOTE:
                num += 1
            entries.append((num if key != DOC_NOTE else 0, n.text, kind,
                            tuple(getattr(n, "edges", ()) or ())))
    return out


def note_label(num: int) -> str:
    """A note's label in the lists: `#N`, or `¶` for the document's own note
    (number 0, tagged on nothing, listed first)."""
    return f"#{num}" if num else "¶"


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
    """The notes list: `#N text` (`¶ text` for the document's), wrapped under its
    tag, in its kind's colour."""
    rows = []
    for num, text, kind, _edges in sorted(e for entries in idx.values() for e in entries):
        tag = f"{note_label(num)} "
        wrapped = [w for part in text.split("\n")
                   for w in wrap_cells(part, max(width - len(tag), 20)) or [""]]
        for k, ln in enumerate(wrapped):
            rows.append([(tag if k == 0 else " " * len(tag), NOTE_STYLE[kind]),
                         (ln, NOTE_STYLE[kind] if kind == "inline" else NOTE_TEXT_STYLE)])
    return rows


class RuleRow(list):
    """A title row (`── name ───`) whose rule is stretched to the drawing's width
    once that is known (stretch_rules), so every title looks the same."""


TITLE_STEP = "  ›  "             # between an expansion's title and its parent's


def fit_title(name: str, room: int) -> str:
    """A part title cut to `room` columns (a str subclass, Rule, kept): a nested
    expansion's oldest ancestors first, as `…  ›  [Risk] := { … }`, then the
    end, `[VeryLong…`. Untouched when it fits."""
    if room < 1 or cell_width(name) <= room:
        return name
    steps, out = name.split(TITLE_STEP), name
    while len(steps) > 1 and cell_width(out) > room:
        steps = steps[1:]
        out = "…" + TITLE_STEP + TITLE_STEP.join(steps)
    if cell_width(out) > room:
        out = cut_cells(out, max(room - 1, 0)).rstrip(" …") + "…"
    return type(name)(out) if isinstance(name, Rule) else out


def section_rule(name: str, width: int = 0) -> list:
    """`── L2 · Payments ──`, the rule run out to `width` columns: the rails in
    ui.section, the name as code (a glyph in it keeps its colours). Every title —
    sections, expansions, state machines, lists — is one of these."""
    runs = [("── ", SECTION_STYLE)] + [(t, (st[0], st[1], True)) for t, st in payload_runs(name)]
    n = row_len(runs)
    return RuleRow(runs + [(" " + "─" * max(width - n - 1, 2), SECTION_STYLE)])


NARROW_ADVICE = "the tree view reads narrow panes best"
CIRCLED = 20                    # ① … ⑳; past them «21», as the circled 21+ are wide


def plug_label(n: int) -> str:
    """The n-th plug's number (from 1): ① … ⑳, then «21» … — the flow view's cut
    wires and the tree view's folded lanes."""
    return chr(0x2460 + n - 1) if n <= CIRCLED else f"«{n}»"


def wide_hint(view: str, what: str, over: int, width: int,
              advice: str | None = NARROW_ADVICE) -> list:
    """The rows that end a drawing still wider than `width` after its view's
    wrap ladder (it never switches view by itself): `VIEW: WHAT is OVER wide,
    WIDTH here;` and the advice, dim, rewrapped when a line is wider than width."""
    dim = (GREY["dim"], None, False)
    hint = [f"{view}: {what} is {over} wide, {width} here" + (";" if advice else "")]
    hint += [advice] if advice else []
    if any(cell_width(text) > width for text in hint):
        hint = wrap_cells(" ".join(hint), width)
    return [[(ln, dim)] for ln in hint]


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
    lines = wrap_cells(text, tw) or [""]
    limit = _callout_lines_cap(kind, tw)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = cut_cells(lines[-1], tw - 1) + "…"
    return lines


def _callout_need(blocks: dict) -> int:
    """The narrowest text width from CALLOUT_TEXT up to CALLOUT_MAX that shows
    every callout whole (CALLOUT_MAX if none does)."""
    need = CALLOUT_TEXT
    for entries in blocks.values():
        for _num, text, kind, _e in entries:
            while (need < CALLOUT_MAX
                   and len(wrap_cells(text, need)) > _callout_lines_cap(kind, need)):
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
            rows.append([(tag, style), (lside, style), (ljust_cells(ln, tw), style), (rside, style)])
    return rows, tag_w + tw + 4


def _panel_rows(items, tw: int, most: int | None = None):
    """A panel: each item is (marker runs, [(text, kind)]); kind "code" is a
    payload (drawn as code), else a note kind. Each text wraps at tw under its
    marker (a payload, being code, at no less than its own length up to
    CALLOUT_MAX — unless that would make the panel wider than `most`).
    Returns (rows, width)."""
    mark_w = max(row_len(m) for m, _ in items) + 1
    rows = []
    for marker, texts in items:
        first = True
        for text, kind in texts:
            wrap = max(tw, min(cell_width(text), CALLOUT_MAX)) if kind == "code" else tw
            if most is not None:
                wrap = max(min(wrap, most - mark_w), 1)
            for ln in wrap_cells(text, wrap) or [""]:
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
        text = _one_per_column("".join(t for t, _ in row))[:width].ljust(width)
        line, run = [0], 0
        for x, ch in enumerate(text):
            run += ch != " "
            line.append(acc[-1][x + 1] + run)
        acc.append(line)
    return acc


def _one_per_column(text: str) -> str:
    """text with one character a column: a wide character's second column
    repeats it, a combining mark is dropped (what is drawn where, by column)."""
    if text.isascii():
        return text
    return "".join(ch * char_cells(ch) for ch in text)


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
    """Place a panel (make(text width, most=None) → (rows, width)) in the drawing:
    in an empty region of its corner if one is big enough at some text width (pref
    first, then CALLOUT_MAX down to CALLOUT_MIN), else above the drawing (tl) or
    below it, right-aligned (br), at the widest text width within `width` (made
    with most=width when even CALLOUT_MIN is wider: code wraps too)."""
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
    if pw > width:
        panel, pw = make(tw, width)
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
    {node id: (CheckMark, …)} and {wire ident: (CheckMark, …)}, number order;
    `witnesses`: ((scenario name, tick, CheckMark), …) — where a behavioural
    finding shows in its witness run (the run view's ruler)."""
    nodes: dict
    wires: dict
    witnesses: tuple = ()

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
    """Slice a row of runs to the columns [start, start + width). A wide
    character cut in half by either edge leaves a blank column in its place."""
    out, x = [], 0
    for t, st in row:
        n = cell_width(t)
        if n == len(t):
            a, b = max(start - x, 0), min(start + width - x, n)
            if a < b:
                out.append((t[a:b], st))
        else:
            part = _clip_cells(t, start - x, start + width - x)
            if part:
                out.append((part, st))
        x += n
        if x >= start + width:
            break
    return out


def _clip_cells(t: str, lo: int, hi: int) -> str:
    """The columns [lo, hi) of text with wide characters: a wide character
    straddling lo or hi becomes a blank column, combining marks stay with
    their base."""
    out, x, kept = [], 0, False                 # kept: the last base character is in
    for ch in t:
        k = char_cells(ch)
        if k == 0:
            if kept:
                out.append(ch)
            continue
        kept = x >= lo and x + k <= hi
        if kept:
            out.append(ch)
        elif x < hi and x + k > lo:             # straddles an edge: its cells inside
            out.append(" " * (min(x + k, hi) - max(x, lo)))
        x += k
    return "".join(out)


def row_len(row) -> int:
    """A row of runs' drawn width, in columns."""
    return sum(cell_width(t) for t, _ in row)
