"""
frames — a document drawn as packed frames: the rows the hosts paint instead of
a terminal. The page (site/build_site.py's frames.json), the playground
(site/playground.py, in the browser by Pyodide), the Claude Code pane and pi
(`sigil frames draw`) all read their drawings from here.

    autoclose(lines)     a half-typed document with its open `{` blocks closed
    Styles / packed      the views' rows of (text, (fg, bg, bold)) runs → compact
                         [[text, style id], …] rows (cure's Wire) plus a style
                         table whose colours are theme roles ("kinds-service"),
                         so the page recolours them on a theme change
    HexStyles            the same table with each colour's hex value (the pane
                         paints cells, not CSS)
    draw(path, …)        the JSON object `sigil frames draw` prints (below)

`sigil frames draw FILE [--view graph|tree|flow|run] [--depth N|all] [--width N]
[--height N] [--layout auto|wrap|pan] [--scenario NAME [--from N|last]
[--count N]] [--payloads] [--theme NAME] [--dialect D] [--limit NAME=N]…` prints one
JSON object (the document read with the dialect, coloured with --theme, else the
dialect's THEME, else the default): {"file",
"view", "width", "layout" (what was drawn: wrap — fitted to --width — or pan —
the natural layout; auto picks as the live view does for a --width × --height
pane, wrap without --height), "styles": [[fg hex|null, bg hex|null, bold]],
"frames": [rows], "legend": rows, "summary", "lint": [lines], "scenarios":
[names], and with --scenario "scenario", "status": [a line per frame], "log":
[the latest log line per frame], "say": [the narration line per frame: the
latest beat in plain words, the live view's `›` line], "trail": [the episode's
path so far per frame, in notation as text — the path row without its label,
the hop now marked `▸`], "path": [the same row per frame as the live view
draws it, at most two rows, the hop now bold], "outcome", "first": the run's
frame the drawn frames start at, "last": the run's last frame}; a row is
[[text, style id], …]. A run is drawn a window at a time, every frame of it:
frames --from … --from + --count - 1 (default 0 and WINDOW; --from last: the
window that ends at the run's last frame), so the host asks for the next window
as it plays on. The legend is the tree's key, the flow view's or the run
view's, then a run's marks (the run view: its path's only; without --scenario
it draws the happy run). A document or view that cannot be drawn: {"error"}.

With any cluster longer than one code point drawn, also "clusters": {field:
side tables} for the fields "frames" (a list per frame), "path" (a list per
frame) and "legend" that hold one; a field's side tables are a list per packed
row, [[column, cluster], …], trailing rows without one left out. A drawing
with none has no "clusters" key: the envelope is the one before it.

Every packed row is cure's Wire format 2 (packed()): every character of a
packed row is one terminal cell, so the host's grid keeps the drawing's
columns — a wide cluster is its first code point and then WIDE_TAIL (the host
draws the pair as the one wide glyph), any other cluster its first code point,
widths by cure's grapheme-cluster rule (the kit's: kit.char_cells); the side
table gives the whole cluster where it is longer (e + a combining mark, an
emoji ZWJ sequence, a flag), so a host that reads it draws the cluster whole
and one that does not still keeps every column. Runs, the trailing blanks and
the style list are cure's; the styles are mapped onto the envelope's own table
(Styles / HexStyles, in sigil's order). The page (site/build_site.py) and the
playground (site/playground.py) pack through the same packed().
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from sigil.core.lex import read_source
from sigil.core.parse import parse_document
from sigil.core.statements import read_document
from sigil.model import scene
from sigil.model import sim as simulator
from sigil.present import app, kit
from sigil.present.views import flow as vflow
from sigil.present.views import run as vrun
from sigil.present.views import tree as vtree

# cure (vendored; Present's __init__ puts it on the path): the packed wire
from cure.core.buffer.rows import Rows
from cure.core.buffer.wire import pack as wire_pack
from cure.core.style import Colour, Style

WINDOW = 120               # run frames one draw holds (the host asks for the next as it plays)
LINT_LINES = 5              # diagnostics carried into the reply
_SPEED_RE = re.compile(r" (?:▶|❚❚) \S+ frames?/s")   # the live view's play mark and speed
WIDE_TAIL = "\0"   # a wide cluster's second cell on cure's wire (logic.ts's WIDE_TAIL): draws nothing


# ---------------------------------------------------------------------------
# A half-typed document
# ---------------------------------------------------------------------------

def _open_blocks(text: str):
    """Core's walk of `text` and how many blocks it leaves open at the end."""
    walk = read_document(text)
    return walk, sum(not b.closed for b in walk.blocks)


def _closers(text: str) -> int:
    """How many `}` lines close every block the walk leaves open in `text`.
    Counted by reading again, not per block: one `}` need not close a block (a
    body's braces are counted as its definition reads them — `[X] := {` then
    `"x \\" {"` takes two). None after an unterminated block string (a `}` would
    be its text), and at most one per `{` in the text; when no count closes all,
    the fewest that leave the fewest open."""
    walk, still_open = _open_blocks(text)
    if not still_open or walk.unterminated is not None:
        return 0
    best, fewest = 0, still_open
    for k in range(1, text.count("{") + 1):
        _walk, left = _open_blocks(text + "\n" + "\n".join("}" * k))
        if left < fewest:
            best, fewest = k, left
        if not left:
            break
    return best


def autoclose(lines: list[str]) -> str:
    """The prefix as a document: close any `{` blocks still open, so a half-typed
    expansion already draws. The open blocks are core's walk's (its reading of
    strings, block strings, comments and mode lines), so a `{` inside a `"…"`
    string — closed or still being typed — or a block string's body opens
    nothing, and no `}` is added that the walk would read as stray."""
    return "\n".join(lines + ["}"] * _closers("\n".join(lines))) + "\n"


# ---------------------------------------------------------------------------
# Packed rows
# ---------------------------------------------------------------------------

StyleKey = tuple  # (fg role/hex | None, bg role/hex | None, bold)


class Styles:
    """Interns (fg, bg, bold) styles as compact role/hex triples."""

    def __init__(self) -> None:
        self.table: list[list] = []
        self.index: dict[StyleKey, int] = {}

    @staticmethod
    def _colour(c) -> str | None:
        """A colour as its theme role (e.g. "kinds-service") when it has one, else hex."""
        if not c:
            return None
        role = getattr(c, "role", "")
        return role or str(c)

    def intern(self, style) -> int:
        """The table index of a view's (fg, bg, bold) style, adding it if new."""
        if style is None:
            style = (None, None, False)
        fg, bg, bold = style
        key = (self._colour(fg), self._colour(bg), bool(bold))
        if key not in self.index:
            self.index[key] = len(self.table)
            self.table.append(list(key))
        return self.index[key]


class HexStyles(Styles):
    """Styles with each colour as its hex value, not its theme role."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: dict = {}

    @staticmethod
    def _colour(c):
        return str(c) if c else None

    def intern(self, style) -> int:
        # A hex key is the colours' text, so equal styles intern alike: each
        # one is worked out once (frame after frame repeats them).
        try:
            return self.seen[style]
        except KeyError:
            sid = self.seen[style] = Styles.intern(self, style)
            return sid


# ---------------------------------------------------------------------------
# Packing — cure's Wire v2
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1024)
def _wire_colour(text: str) -> Colour:
    """A table colour (role or hex, as the envelope writes it) as a cure Colour
    whose role is that text: cure's role table gives it back as written."""
    return Colour("rgb", (0, 0, 0), text)


@functools.lru_cache(maxsize=4096)
def _wire_style(key: StyleKey):
    """A table entry (fg, bg, bold) as the cure Style that packs back to it
    (None: the plain entry)."""
    fg, bg, bold = key
    if fg is None and bg is None and not bold:
        return None
    return Style(fg=_wire_colour(fg) if fg is not None else None,
                 bg=_wire_colour(bg) if bg is not None else None, bold=bool(bold))


def _wire_pack(rows: list) -> tuple:
    """cure's Wire on rows of (text, table key) runs → (each row's packed
    (text, table key) runs, each row's side table of long clusters)."""
    p = wire_pack(Rows.of([[(t, _wire_style(k)) for t, k in row] for row in rows]),
                  colours="role")
    keys = [(fg, bg, "b" in attrs) for fg, bg, attrs, _link in p.styles]
    out = [tuple((text, keys[i]) for text, i in row) for row in p.rows]
    pad = len(rows) - len(out)
    return out + [()] * pad, list(p.clusters) + [()] * pad


_PACKED_ROWS: dict = {}     # a view's row (hex tables) → (its styles in order, runs, clusters)
_ROWS_KEPT = 8192           # rows remembered (a run's frames repeat most rows)


def packed(rows, styles: Styles, tables: list | None = None) -> list:
    """The views' rows → packed rows by cure's Wire (format 2): one code point a
    cell — a wide cluster its first code point then WIDE_TAIL, any other its
    first code point, a control U+FFFD — runs of equal styles, a row's trailing
    blanks (a space with no background) and the trailing empty rows dropped.
    Each row's styles are interned in run order into `styles` (sigil's table,
    roles or hex), so the table keeps sigil's order. `tables`: when given, a
    list each packed row's side table is appended to — [[column, cluster], …]
    for the cells whose cluster is longer than one code point (a mark, a
    joiner, a selector, a flag), so a host draws the cluster whole. A row
    packed once is remembered (frame after frame repeats most of them)."""
    out, side, todo, at = [], [], [], []
    hexed = isinstance(styles, HexStyles)       # a role table tells colours apart by role
    for row in rows:
        try:
            sig = tuple(row) if hexed else None
            done = _PACKED_ROWS.get(sig)
        except TypeError:                       # an unhashable run: packed afresh
            sig = done = None
        if done is not None:
            for st in done[0]:
                styles.intern(st)
            out.append(done[1])
            side.append(done[2])
            continue
        keys = [tuple(styles.table[styles.intern(st)]) for _t, st in row]   # sigil's order
        order = tuple(dict.fromkeys(st for _t, st in row)) if sig is not None else ()
        at.append((len(out), sig, order))
        todo.append([(t, k) for (t, _st), k in zip(row, keys)])
        out.append(())
        side.append(())
    if todo:
        runs, clusters = _wire_pack(todo)
        for (y, sig, order), r, c in zip(at, runs, clusters):
            out[y], side[y] = r, c
            if sig is not None:
                _PACKED_ROWS[sig] = (order, r, c)
    if len(_PACKED_ROWS) > _ROWS_KEPT:
        _PACKED_ROWS.clear()
    index = styles.index
    out = [[[text, index[key]] for text, key in r] for r in out]
    while out and not out[-1]:
        out.pop()
    if tables is not None:
        tables.extend([[col, glyph] for col, glyph in t] for t in side[:len(out)])
    return out


def side_tables(tables: list) -> list:
    """Packed rows' side tables as the envelope carries them: the trailing
    rows without a long cluster left out ([] when no row has one)."""
    end = len(tables)
    while end and not tables[end - 1]:
        end -= 1
    return tables[:end]


# ---------------------------------------------------------------------------
# draw — `sigil frames draw`
# ---------------------------------------------------------------------------

def window(start: int | None, count: int, last: int) -> range:
    """The run frames a draw holds: `start` … `start` + `count` - 1, kept within
    0 … `last` (start None: the `count` frames that end at the last one)."""
    count = max(1, count)
    if start is None:
        start = last - count + 1
    start = max(0, min(start, last))
    return range(start, min(start + count, last + 1))


def lint_line(diags) -> str:
    """The lint one-liner of a draw's summary: `lint: OK` or the counts."""
    errors = sum(d.severity == "error" for d in diags)
    warns = sum(d.severity == "warn" for d in diags)
    if not diags:
        return "lint: OK"
    return f"lint: {errors} error{'s' * (errors != 1)}, {warns} warning{'s' * (warns != 1)}"


def placing(g, name: str, layout: str, width: int | None, height: int | None,
            kw: dict) -> str:
    """wrap | pan: what `layout` draws in a width × height pane — auto as the
    live view picks (app.pick_layout on the natural drawing; wrap without a
    height or a width)."""
    if layout != "auto":
        return layout
    if not width or not height:
        return "wrap"
    rows, w = app.compose_view(g, name, **{**kw, "width": None})
    return app.pick_layout(w, len(rows), width, height)


def legend_rows(g, view_name: str, *, depth: int, payloads: bool, events: str, sim: bool,
                triggers: bool = True, access: bool = False, mods: bool = False) -> list:
    """The legend rows of a drawing (unwrapped): the tree's key, the flow view's
    wires or the run view's markers, then (`sim`) a run's marks — the run view:
    its path's only."""
    legend = []
    if view_name == "tree":
        legend += vtree.tree_legend(triggers, payloads, access, mods, events,
                                    calls=app.drawn_call_marks(g, depth, payloads))
    elif view_name == "flow":
        legend.append(vflow.flow_legend(triggers, payloads, access, mods, events))
    elif view_name == "run":
        legend.append(vrun.run_legend())
    if sim:
        legend += ([app.path_legend()] if view_name == "run"
                   else [app.sim_legend(view_name == "tree"), app.path_legend()])
    return legend


def draw(path: Path, view_name: str = "flow", depth: int = 1, width: int | None = None,
         scenario: str | None = None, payloads: bool = False, theme: str | None = None,
         layout: str = "auto", height: int | None = None, start: int | None = 0,
         count: int = WINDOW, limits=None, dialect=None) -> dict:
    """The JSON object `sigil frames draw` prints (see the module docstring); a
    run's frames are window(start, count, its last frame). `limits`: --limit's
    NAME=N pairs (None: none), laid over the document's own `#%` limits and the
    defaults (app.doc_limits), for the run drawn and the scenarios listed, as
    `sigil view` and `sigil check` use them: with no flag, the document's. `dialect`:
    a loaded dialect the document is read and linted with, whose THEME colours it
    when no `theme` is given."""
    try:
        kit.use_theme(theme, dialect)
    except ValueError as exc:
        return {"error": str(exc)}
    try:
        text = read_source(path)        # UTF-8, BOM dropped, size capped
    except OSError as exc:
        return {"error": f"{path}: {exc.strerror or exc}"}
    kit.use_dialect(dialect)
    g = parse_document(text, dialect=dialect)
    limits = app.doc_limits(g, limits)
    events = app.DEFAULT_EVENTS.get(view_name, "land")
    kw = dict(depth=depth, payloads=payloads, notes="off", triggers=True, spaced=True,
              width=width, access=False, mods=False, events=events)
    styles = HexStyles()
    side: dict = {}                     # the side tables of every packed field
    out: dict = {"file": path.name, "view": view_name, "width": width}
    try:
        out["layout"] = placing(g, view_name, layout, width, height, kw)
        if out["layout"] == "pan":
            kw["width"] = None
        if scenario:
            player = app.SimPlayer(g, scenario, limits)
            shown = player.shown(scene.SceneOptions(events, True, False, depth))
            picks = window(start, count, player.last)
            drawn, status, log, say, trail, path_rows = [], [], [], [], [], []
            side["frames"], side["path"] = [], []
            cols = width or app.LEGEND_WIDTH
            memo = kit.FrameMemo()
            for at in picks:
                player.at = at
                rows, _w = app.compose_view(g, view_name, trace=shown, tick=at, memo=memo, **kw)
                tables: list = []
                drawn.append(packed(rows, styles, tables))
                side["frames"].append(side_tables(tables))
                status.append(_SPEED_RE.sub("", player.status()))
                log.append(player.log_line())
                say.append(player.narration())
                trail.append(player.path())
                tables = []
                path_rows.append(packed(app.path_rows(player.path_branches(), cols, hold=True),
                                        styles, tables))
                side["path"].append(side_tables(tables))
            out.update(scenario=player.scenario.name, status=status, log=log, say=say,
                       trail=trail, path=path_rows, first=picks.start, last=player.last,
                       outcome=player.trace.outcome, choice=player.choice())
        else:
            rows, _w = app.compose_view(g, view_name, **kw)
            tables = []
            drawn = [packed(rows, styles, tables)]
            side["frames"] = [side_tables(tables)]
    except app.UnknownScenario as exc:
        return {"error": f"scenario: {exc}"}
    except LookupError as exc:
        return {"error": str(exc)}
    cols = min(app.LEGEND_WIDTH, width or app.LEGEND_WIDTH)
    legend = legend_rows(g, view_name, depth=depth, payloads=payloads, events=events,
                         sim=bool(scenario))
    tables = []
    out["legend"] = packed([ln for r in legend for ln in app.wrap_legend(r, cols)], styles,
                           tables)
    side["legend"] = side_tables(tables)
    diags = kit.run_lint(text, dialect)
    mode = kit.doc_mode(text)
    out["summary"] = (f"{path.name}: {len(g.nodes)} nodes, {len(g.edges)} edges"
                      + (f" · {mode}" if mode else "") + " · " + lint_line(diags))
    out["lint"] = [d.format() for d in diags[:LINT_LINES]]
    try:
        canon = simulator.canonical(g)
        out["scenarios"] = [s.name for s in simulator.scenarios(
            canon, limits=limits)]
    except Exception:                       # a half-written design still draws
        out["scenarios"] = []
    out["frames"], out["styles"] = drawn, styles.table
    clusters = {key: tables for key, tables in side.items() if any(tables)}
    if clusters:
        out["clusters"] = clusters
    return out
