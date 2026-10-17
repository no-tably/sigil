"""
frames — a document drawn as packed frames: the rows the hosts paint instead of
a terminal. The page (site/build_site.py's frames.json), the playground
(site/playground.py, in the browser by Pyodide), the Claude Code pane and pi
(`sigil frames draw`) all read their drawings from here.

    autoclose(lines)     a half-typed document with its open `{` blocks closed
    Styles / pack_rows   the views' rows of (text, (fg, bg, bold)) runs → compact
                         [[text, style id], …] rows plus a style table whose
                         colours are theme roles ("kinds-service"), so the page
                         recolours them on a theme change
    HexStyles            the same table with each colour's hex value (the pane
                         paints cells, not CSS)
    draw(path, …)        the JSON object `sigil frames draw` prints (below)

`sigil frames draw FILE [--view graph|tree|flow|run] [--depth N|all] [--width N]
[--height N] [--layout auto|wrap|pan] [--scenario NAME [--from N|last]
[--count N]] [--payloads] [--theme NAME]` prints one JSON object: {"file",
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

Every character of a packed row from draw() is one terminal cell, so the host's
grid keeps the drawing's columns: a wide character is itself and then
WIDE_TAIL, the continuation cell of the two columns the views give it (the
host draws the pair as the one wide glyph), and a combining mark or zero-width
character is nothing — kit.char_cells's rule. Standard library only.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from pathlib import Path

from sigil.core.parse import parse_document
from sigil.core.statements import read_document
from sigil.model import scene
from sigil.model import sim as simulator
from sigil.present import app, kit
from sigil.present.views import flow as vflow
from sigil.present.views import run as vrun
from sigil.present.views import tree as vtree

WINDOW = 120               # run frames one draw holds (the host asks for the next as it plays)
LINT_LINES = 5              # diagnostics carried into the reply
_SPEED_RE = re.compile(r" (?:▶|❚❚) \S+ frames?/s")   # the live view's play mark and speed
WIDE_TAIL = "\0"   # a wide character's second cell (logic.ts's WIDE_TAIL): draws nothing


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


def pack_rows(rows, styles: Styles) -> list:
    """Rows of (text, style) runs -> [[text, style id], …] with equal neighbours
    merged; trailing blank runs and rows are dropped (a run with a background
    colour is kept — it is visible)."""
    out = []
    for row in rows:
        packed: list = []
        for text, st in row:
            sid = styles.intern(st)
            if packed and packed[-1][1] == sid:
                packed[-1][0] += text
            else:
                packed.append([text, sid])
        while packed and not packed[-1][0].strip() and not styles.table[packed[-1][1]][1]:
            packed.pop()
        out.append(packed)
    while out and not out[-1]:
        out.pop()
    return out


# ---------------------------------------------------------------------------
# Cells — what the pane and pi paint
# ---------------------------------------------------------------------------

def cell(ch: str) -> str:
    """`ch` as the cells the views draw it in (kit.char_cells), one character a
    cell: a wide character itself then WIDE_TAIL, a combining mark or zero-width
    character nothing, any other one-column character that is not a printable
    BMP character `?`."""
    n = kit.char_cells(ch)
    if n == 2:
        return ch + WIDE_TAIL
    if n == 0:
        return ""
    if ord(ch) > 0xFFFF or unicodedata.category(ch)[0] in "MC":
        return "?"
    return ch


@functools.lru_cache(maxsize=4096)
def cells(text: str) -> str:
    """text as cell() draws each character, one cell a character (a run's
    text recurs frame after frame)."""
    if text.isascii() and text.isprintable():
        return text
    return "".join(ch if " " <= ch < "\x7f" else cell(ch) for ch in text)


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


def packed(rows, styles: Styles) -> list:
    """The views' rows → packed rows, one character a cell (cells())."""
    return pack_rows([[(cells(t), st) for t, st in row] for row in rows], styles)


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
         count: int = WINDOW) -> dict:
    """The JSON object `sigil frames draw` prints (see the module docstring); a
    run's frames are window(start, count, its last frame)."""
    try:
        kit.use_theme(theme)
    except ValueError as exc:
        return {"error": str(exc)}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"{path}: {exc.strerror or exc}"}
    g = parse_document(text)
    events = app.DEFAULT_EVENTS.get(view_name, "land")
    kw = dict(depth=depth, payloads=payloads, notes="off", triggers=True, spaced=True,
              width=width, access=False, mods=False, events=events)
    styles = HexStyles()
    out: dict = {"file": path.name, "view": view_name, "width": width}
    try:
        out["layout"] = placing(g, view_name, layout, width, height, kw)
        if out["layout"] == "pan":
            kw["width"] = None
        if scenario:
            player = app.SimPlayer(g, scenario)
            shown = player.shown(scene.SceneOptions(events, True, False, depth))
            picks = window(start, count, player.last)
            drawn, status, log, say, trail, path_rows = [], [], [], [], [], []
            cols = width or app.LEGEND_WIDTH
            memo = kit.FrameMemo()
            for at in picks:
                player.at = at
                rows, _w = app.compose_view(g, view_name, trace=shown, tick=at, memo=memo, **kw)
                drawn.append(packed(rows, styles))
                status.append(_SPEED_RE.sub("", player.status()))
                log.append(player.log_line())
                say.append(player.narration())
                trail.append(player.path())
                path_rows.append(packed(app.path_rows(player.path_branches(), cols, hold=True),
                                        styles))
            out.update(scenario=player.scenario.name, status=status, log=log, say=say,
                       trail=trail, path=path_rows, first=picks.start, last=player.last,
                       outcome=player.trace.outcome, choice=player.choice())
        else:
            rows, _w = app.compose_view(g, view_name, **kw)
            drawn = [packed(rows, styles)]
    except app.UnknownScenario as exc:
        return {"error": f"scenario: {exc}"}
    except LookupError as exc:
        return {"error": str(exc)}
    cols = min(app.LEGEND_WIDTH, width or app.LEGEND_WIDTH)
    legend = legend_rows(g, view_name, depth=depth, payloads=payloads, events=events,
                         sim=bool(scenario))
    out["legend"] = packed([ln for r in legend for ln in app.wrap_legend(r, cols)], styles)
    diags = kit.run_lint(text)
    mode = kit.doc_mode(text)
    out["summary"] = (f"{path.name}: {len(g.nodes)} nodes, {len(g.edges)} edges"
                      + (f" · {mode}" if mode else "") + " · " + lint_line(diags))
    out["lint"] = [d.format() for d in diags[:LINT_LINES]]
    try:
        canon = simulator.canonical(g)
        out["scenarios"] = [s.name for s in simulator.scenarios(canon)]
    except Exception:                       # a half-written design still draws
        out["scenarios"] = []
    out["frames"], out["styles"] = drawn, styles.table
    return out
