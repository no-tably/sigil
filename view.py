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
    --events MODE    land | nodes: how a pass-through event is drawn. land: where
                     it lands — no row / box of its own, each emitter wired straight
                     to each destination in the event's colour (tree: the › emit
                     marker, the event named on the destination row; graph: the
                     event named beside the edge's head). nodes: as a row / box of
                     its own (a hub). Default: tree land, graph nodes; given, it
                     sets both views.
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
    s  spacing between units      v  events: where they land / as nodes (per view)
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

Modules: this file is the app (the --once printer, the live view, the CLI). The
drawing lives beside it — viewkit.py (styles, canvas, runs, notes, fit panels),
view_graph.py (the graph view) and view_tree.py (the tree view) — and every name
of those three is also reachable here as view.NAME.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import select
import shutil
import signal
import sys
import time
from pathlib import Path


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
vgraph = _sibling("sigil_view_graph", "view_graph.py")
vtree = _sibling("sigil_view_tree", "view_tree.py")
scene = _sibling("sigil_scene", "scene.py")


def __getattr__(name: str):
    """view.NAME for every name of viewkit, view_graph and view_tree (tests, the
    site and dialects use view.render, view.compose, view.KINDS, …). Looked up at
    access time, so a themed style (view.GREY) is always the one in use."""
    for mod in (kit, vgraph, vtree):
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
DEFAULT_EVENTS = {"tree": "land", "graph": "nodes"}   # each view's own default


def view_name(tree: bool) -> str:
    """The key of a view in DEFAULT_EVENTS / ViewState.events."""
    return "tree" if tree else "graph"


def events_by_view(events: str | None) -> dict:
    """{view: events mode} to start with: `events` (--events) for both views when
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


KEY_LEGEND = (("t", "tree/graph"), ("n", "notes"), ("e", "triggers"), ("v", "events"),
              ("s", "spacing"),
              ("d", "depth"), ("p", "payloads"), ("m", "mods"), ("a", "access"),
              ("l", "lint"), ("c", "centre"), ("g", "home"), ("r", "reload"), ("q", "quit"))


def keys_legend(state):
    """The hotkeys row for a ViewState; toggles that are on are shown bright (the
    events mode: when the active view's differs from its default)."""
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    on = {"t": state.tree, "e": state.show_triggers, "s": state.spaced,
          "p": state.payloads, "l": state.show_lint, "n": state.notes != "off",
          "m": state.show_mods, "a": state.show_access}
    row = [("keys   ", dim)]
    for key, word in KEY_LEGEND:
        bright = on.get(key)
        if key == "n":
            word = f"notes:{state.notes}"
        elif key == "v":
            word = f"events:{state.events_mode}"
            bright = state.events_mode != DEFAULT_EVENTS[view_name(state.tree)]
        elif key == "d":
            word = f"depth:{'all' if state.depth >= kit.ALL_DEPTH else state.depth}"
            bright = state.depth > 0
        row += [(key, kit.KEY_STYLE),
                (f" {word}  ", (kit.GREY["light"], None, bright) if bright else mid)]
    return row


# ---------------------------------------------------------------------------
# --once
# ---------------------------------------------------------------------------

def once(path: Path, depth: int, payloads: bool, do_lint: bool,
         dialect=None, colour: bool = False, tree: bool = False,
         triggers: bool = True, spaced: bool = True, notes: str = "off",
         width: int | None = None, access: bool = False, mods: bool = False,
         events: str | None = None) -> int:
    """Print the drawing once. `width`: the columns to fit it to (None: its
    natural width); the legend wraps at the narrower of that and LEGEND_WIDTH.
    `events`: "land" | "nodes" (None: the view's default, DEFAULT_EVENTS).
    The summary line ends with the document's `#!mode`, when it has one."""
    kit.use_dialect(dialect)
    text = path.read_text()
    g = kit._call(kit.render.parse_document, text, dialect)
    events = events or DEFAULT_EVENTS[view_name(tree)]
    rows, _w = (vtree.compose_tree(g, depth, triggers, spaced, notes, payloads, width, access,
                                   mods, events)
                if tree else vgraph.compose(g, depth, payloads, notes, triggers, width, access,
                                            mods, events))
    out = [kit.ansi(r, colour) for r in rows]
    if tree:
        legend_w = LEGEND_WIDTH if width is None else min(LEGEND_WIDTH, width)
        legend = vtree.tree_legend(triggers, payloads, access, mods, events)
        out += [""] + [kit.ansi(ln, colour) for r in legend for ln in wrap_legend(r, legend_w)]
    out.append("")
    mode = kit.doc_mode(text)
    out.append(f"{path.name}: {len(g.nodes)} nodes, {len(g.edges)} edges, "
               f"{len(g.expansions)} expansions" + (f" · {mode}" if mode else ""))
    status = 0
    if do_lint:
        diags = kit.run_lint(text, dialect)
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

DEPTHS = (0, 1, kit.ALL_DEPTH)
LINT_ROWS = 8
SCROLL_X = 4                                    # columns per left / right key
POLL_S = 0.3                                    # how often to stat the file
TICK_S = 0.1                                    # key wait per loop turn
READ_BYTES = 64                                 # bytes per key read


class ViewState:
    def __init__(self, path: Path, depth: int = 1, payloads: bool = False,
                 do_lint: bool = True, dialect=None, tree: bool = False,
                 triggers: bool = True, spaced: bool = True, notes: str = "off",
                 access: bool = False, mods: bool = False, events: str | None = None):
        """`events`: the events mode both views start in (None: each view's
        default, DEFAULT_EVENTS); each view then keeps its own (key v)."""
        self.path = path
        self.show_access = access
        self.show_mods = mods
        self.mode = ""
        self.tree = tree
        self.events = events_by_view(events)   # {view: "land" | "nodes"}
        self.notes = notes
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
        self.sx = self.sy = 0          # scroll offsets (only used when it overflows)
        self._recentre = False         # centre the overflowing drawing on the next frame
        self._vh = 1                   # viewport height of the last frame (a page)
        self._rows, self._width = [], 0  # the drawing at its natural width
        self._fit = None               # (cols, rows, width): the drawing fitted to cols

    @property
    def events_mode(self) -> str:
        """The active view's events mode."""
        return self.events[view_name(self.tree)]

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
            return vtree.compose_tree(self.graph, self.depth, self.show_triggers, self.spaced,
                                      self.notes, self.payloads, width, self.show_access,
                                      self.show_mods, self.events_mode)
        return vgraph.compose(self.graph, self.depth, self.payloads, self.notes,
                              self.show_triggers, width, self.show_access, self.show_mods,
                              self.events_mode)

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
        elif k == "v":                 # flips the active view's mode only
            view = view_name(self.tree)
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
            rows.append([(self.error, (kit.SEVERITY_COLOR["error"], None, True))])
        if self.show_lint:
            if not self.diags:
                rows.append([("lint: OK", (kit.OK_COLOR, None, False))])
            shown = self.diags[:LINT_ROWS - len(rows)]
            for d in shown:
                colour = kit.SEVERITY_COLOR.get(d.severity, kit.GREY["mid"])
                rows.append([(f"{d.severity}:{d.line}", (colour, None, True)),
                             (f" {d.rule}: {d.message}", None)])
            if len(self.diags) > len(shown):
                rows[-1] = [(f"… {len(self.diags) - len(shown) + 1} more (view.py --once)",
                             (kit.GREY["mid"], None, False))]
        legend = (vtree.tree_legend(self.show_triggers, self.payloads, self.show_access,
                                    self.show_mods, self.events_mode) if self.tree
                  else [vgraph.graph_legend(self.show_triggers, self.payloads, self.show_access,
                                            self.show_mods, self.events_mode)])
        rows[0:0] = [ln for r in legend + [keys_legend(self)] for ln in wrap_legend(r, cols)]
        rows.insert(0, self._legend_rule(cols))
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
        d = "all" if self.depth >= kit.ALL_DEPTH else str(self.depth)
        g = self.graph
        summary = f"{len(g.nodes)} nodes · {len(g.edges)} edges" if g is not None else "no graph"
        n_err = sum(1 for x in self.diags if x.severity == "error")
        n_warn = sum(1 for x in self.diags if x.severity == "warn")
        left = [(f" {self.path.name} ", kit.BAR_NAME_STYLE)]
        if self.mode:
            left.append((f"{self.mode} ", kit.MODE_STYLE))
        if self.title:
            left.append((f" {self.title} ·", kit.BAR_NAME_STYLE))
        view = view_name(self.tree)
        left.append((f" {summary} · {view} · depth {d} · {self.updated} ", kit.BAR_STYLE))
        if n_err or n_warn:
            left.append((f"{n_err}E {n_warn}W ", (kit.SEVERITY_COLOR["error" if n_err else "warn"],
                                                  kit.BAR_STYLE[1], True)))
        return kit.clip(left + [(" " * max(cols - kit.row_len(left), 0), kit.BAR_STYLE)], 0, cols)

    def frame(self, cols: int, rows: int):
        """Exactly `rows` rows of styled runs for a cols×rows terminal: the status bar,
        the drawing (rearranged to fit `cols` when it is wider — see fitted(); centred
        while it fits, scrolled when it still doesn't), the footer."""
        footer = self._footer_rows(cols)
        vh = self._vh = max(rows - 1 - len(footer), 1)
        body, W = self.fitted(cols)
        H = len(body)
        if self.graph is None and not self.error:
            body = [[("waiting for " + str(self.path), (kit.GREY["mid"], None, False))]]
            W, H = kit.row_len(body[0]), 1

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
                row = kit.clip(body[src], self.sx, cols - pad_x)
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
                out.write("\x1b[H" + "\r\n".join(kit.ansi(r) + "\x1b[K" for r in frame) + "\x1b[J")
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
        return kit.ALL_DEPTH
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
    ap.add_argument("--events", choices=EVENT_MODES, default=None,
                    help="land: a pass-through event drawn where it lands (emitter wired "
                         "to each destination); nodes: as a row / box of its own "
                         "(default: tree land, graph nodes)")
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
    tty_out = sys.stdout.isatty()
    if a.once or not tty_out or not sys.stdin.isatty():
        colour = a.color == "always" or (a.color == "auto" and tty_out)
        width = a.width or (shutil.get_terminal_size().columns if tty_out else ONCE_WIDTH)
        return once(a.file, a.depth, a.payloads, not a.no_lint, dialect, colour, a.tree,
                    not a.no_triggers, not a.compact, a.notes, width, a.access, a.mods,
                    a.events)
    tui(ViewState(a.file, a.depth, a.payloads, not a.no_lint, dialect, a.tree,
                  not a.no_triggers, not a.compact, a.notes, a.access, a.mods, a.events))
    return 0


if __name__ == "__main__":
    sys.exit(main())
