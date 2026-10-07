"""
view_run.py — the run view of view.py: one simulated run drawn as a timeline.

Not a command: view.py loads it. The other three views draw the design (what
can happen); this one draws a trace (what did happen in one run): who acted,
when, in what order, for how long, waiting on whom, on which instance, and how
each call ended. Time (sim ticks) runs left to right, one column a tick, under
a ruler; one lane per participant, composition instance and recursion level,
in the order they first acted.

                      0         10        20        30
      (Shopper)       █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░✕   episode 1's entry; fails
      [API]           ╰──▶██░░░░█░░░░█░░░░█░░░░█░░░░✕   routes the failure; fails
      [Payments]           ╰───✖╰───✖╰───✖╰───✖│        4 attempts, each fails
      <PaymentFailed>                          ╰──✖◆    lands from [API]'s route

A bar per activation: █ working, ░ waiting (on a call it made, a deeper
activation of its task, the members it awaits), ◆ an event landing, then ✕ it
failed or ⊘ it was cancelled. A call is drawn at its send tick: a vertical from
the sender's lane to the receiver's, the transit along the receiver's lane in
the arrow's stroke (─ ╌ ━ ═ ┄) to its head (▶, ✖ for `!>`) in the tick before
the callee's first cell; an attempt failing on arrival ends ✖ with no bar,
retries repeat the segment, a race's loser ends ⊘; a reply runs on the callee's
lane from its last cell to ↩. A recursion's levels are sub-rows `↻k` under the
lane (flame-chart style), the deepest ending ┤ where the depth limit stopped
it; an activation that runs while one on its lane still does (another task's)
takes a sub-row `∥k` under it; a self-call is a ↺ pulse in the bar, a host op ⇱; an actor reached with no
work of its own •. A spawned instance's lane forks from its spawner by the `=>`
hop itself and carries ◌ while that hop flies. Each lane has a note in plain
words (n: run notes → the design's notes on the node → off).

During a run the playhead (▼ on the ruler, ┊ down the blank cells) is the
frame's tick: nothing right of it is drawn and lanes appear when they are born;
tokens ride the transits (● out, ○ a reply). Without a scenario chosen the view
draws the happy run's final frame and says so. Given a width the notes move
below the drawing, then the timeline wraps into bands (each with its own ruler
and the lanes active in it), then labels are cut. Long quiet stretches fold
into one ≈ column. The ruler says where a loop's next iteration starts (`↺2`).

compose_run() returns the rows view.py prints, the same shape as the other
views' compose functions; the facts are sim.timeline()'s. Drawing primitives
and styles come from viewkit.py (read as kit.NAME, so a theme change reaches
them); colours are theme roles only.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import textwrap
from pathlib import Path
from typing import NamedTuple, Optional


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
sim = _sibling("sigil_sim", "sim.py")


# ---------------------------------------------------------------------------
# Glyphs and constants
# ---------------------------------------------------------------------------

WORK, WAIT, LANDS = "█", "░", "◆"
FAILED, CANCELLED = "✕", "⊘"
FAILS = "✖"                         # an attempt failing on arrival (and `!>`'s head)
REPLY, TOKEN_OUT, TOKEN_BACK = "↩", "●", "○"
SELF, HOST, BASE, REACHED = "↺", "⇱", "┤", "•"
PENDING = "◌"                      # a spawned lane whose spawn hop still flies
EPISODE, QUIET, NOW, NOW_COL, RUNNING = "┆", "≈", "▼", "┊", "▸"
LEVEL = "↻"
PAR = "∥"                          # `∥k`: a lane's k-th row of activations at once
ITERATION = "↺"                    # `↺k` on the ruler: a loop's k-th iteration starts
GUTTER = 2                         # the ▸ column and a space before the labels
LABEL_MAX = 24                     # a longer label is cut with …
NOTE_GAP = 3                       # columns between the timeline and the notes
NOTE_MIN = 16                      # notes sit beside the drawing with this many columns left
QUIET_RUN = 3                      # a quiet stretch longer than this folds into one ≈ column
BAND_FROM = 0.6                    # a band's cut is chosen in the last 40% of its width
BAND_MIN = 8                       # a band's fewest columns: labels are cut to leave them
LABEL_MIN = 4                      # the labels are never cut narrower than this
RUN_NOTES = ("run", "design", "off")   # n in the run view: run notes → the design's → off

_U, _R, _D, _L = kit.U, kit.R, kit.D, kit.L
_ROUND = {_U | _R: "╰", _D | _R: "╭", _U | _L: "╯", _D | _L: "╮",
          _U | _D | _R: "├", _U | _D | _L: "┤", _L | _R | _D: "┬", _L | _R | _U: "┴",
          _U | _D | _L | _R: "┼"}
_VERTICAL = {"light": "│", "dashed": "╎", "heavy": "┃", "double": "║", "dotted": "┆",
             "hdash": "╏"}
_HORIZONTAL = {"light": "─", "dashed": "╌", "heavy": "━", "double": "═", "dotted": "┄",
               "hdash": "╍"}


def _head(kind: str) -> str:
    """A transit's head, as the flow view draws it: ✖ for `!>`, else ▶."""
    return FAILS if kind == "!>" else "▶"


# ---------------------------------------------------------------------------
# Styles — theme roles only
# ---------------------------------------------------------------------------

def _kind_of(scn, nid: str) -> str:
    sn = scn.nodes.get(nid)
    if sn is None:
        return ""
    return "hole" if sn.node.is_hole else sn.node.kind


def _kind_colour(kind: str):
    return kit.HOLE_COLOR if kind == "hole" else kit.kind_color(kind)


def _wire_style(scn, wire, bold: bool = False) -> tuple:
    w = next((x for x in scn.wires if x.ident == wire), None)
    if w is None:
        return (kit.EDGE_DEFAULT, None, bold)
    return (scene.colour_of(scene.wire_colour(w, _kind_of(scn, w.src))), None, bold)


def _styles() -> dict:
    dim = (kit.GREY["dim"], None, False)
    return {"dim": dim, "mid": (kit.GREY["mid"], None, False),
            "error": (kit.SEVERITY_COLOR["error"], None, True),
            "op": kit.SYNTAX["operator"], "frame": kit.FRAME_STYLE,
            "section": kit.SECTION_STYLE, "note": kit.NOTE_TEXT_STYLE,
            "now": (kit.GREY["light"], None, True)}


# ---------------------------------------------------------------------------
# The grid — cells by (row, column); lines kept as direction masks so corners,
# junctions and crossings resolve, glyph cells (bars, heads, marks) over them
# ---------------------------------------------------------------------------

class _Grid:
    def __init__(self):
        self.cells: dict = {}      # (r, c) → (glyph, style, kind): bar | head | mark | token
        self.lines: dict = {}      # (r, c) → [mask, stroke, style]

    def put(self, r: int, c: int, glyph: str, style, kind: str) -> None:
        self.cells[(r, c)] = (glyph, style, kind)

    def bar_at(self, r: int, c: int) -> bool:
        return self.cells.get((r, c), ("", None, ""))[2] == "bar"

    def free(self, r: int, c: int) -> bool:
        return (r, c) not in self.cells

    def line(self, r: int, c: int, mask: int, stroke: str, style) -> None:
        cur = self.lines.setdefault((r, c), [0, stroke, style])
        cur[0] |= mask

    def glyph(self, r: int, c: int):
        """(glyph, style, kind) of a cell: a glyph cell, else its line, else blank."""
        if (r, c) in self.cells:
            return self.cells[(r, c)]
        if (r, c) in self.lines:
            mask, stroke, style = self.lines[(r, c)]
            if mask in (_L, _R, _L | _R):
                return _HORIZONTAL.get(stroke, "─"), style, "line"
            if mask in (_U, _D, _U | _D):
                return _VERTICAL.get(stroke, "│"), style, "vertical"
            return _ROUND.get(mask, "┼"), style, "line"
        return " ", None, ""


# ---------------------------------------------------------------------------
# Columns — one a tick; long quiet stretches fold into one ≈ column
# ---------------------------------------------------------------------------

class _Cols(NamedTuple):
    of: dict                   # tick → column
    n: int                     # columns
    quiet: frozenset           # the ≈ columns
    tick_at: dict              # column → its first tick


def _columns(tl, busy: set) -> _Cols:
    """A column per tick 0 … tl.last, except a run of more than QUIET_RUN ticks
    not in `busy` (nothing sets out, lands, enters or leaves) keeps its first
    and last tick and one ≈ column between."""
    of, quiet, tick_at, c, t = {}, set(), {}, 0, 0
    while t <= tl.last:
        if t not in busy:
            end = t
            while end + 1 <= tl.last and end + 1 not in busy:
                end += 1
            if end - t + 1 > QUIET_RUN:
                of[t], tick_at[c] = c, t
                quiet.add(c + 1)
                tick_at[c + 1] = t + 1
                for x in range(t + 1, end):
                    of[x] = c + 1
                of[end], tick_at[c + 2] = c + 2, end
                c, t = c + 3, end + 1
                continue
        of[t], tick_at[c] = c, t
        c, t = c + 1, t + 1
    return _Cols(of, c, frozenset(quiet), tick_at)


def _busy_ticks(tl) -> set:
    out = {0, tl.last}
    for s in tl.spans:
        out.add(s.enter)
        if s.leave is not None:
            out.add(s.leave)
    for m in tl.moves:
        out.add(m.start)
        if m.end is not None:
            out |= {m.end, m.end - 1}
    out |= {m.t for m in tl.marks}
    out |= {it.t for it in tl.iterations}
    for _k, t, _n in tl.episodes:
        out |= {t, t - 1}
    return out


# ---------------------------------------------------------------------------
# Painting one frame of the timeline
# ---------------------------------------------------------------------------

class _Frame(NamedTuple):
    grid: _Grid
    rows: dict                 # lane key → row index
    lanes: tuple               # the lanes drawn (born by the tick), in order
    running: frozenset         # lane keys working at the tick
    cols: _Cols
    tick: int                  # the playhead's tick
    final: bool                # the run's last frame


def _paint(tl, scn, tick: int, final: bool, probe: bool = False,
           keep: frozenset = frozenset()) -> _Frame:
    """The grid of the timeline clipped at `tick`: bars, transits and their
    verticals, marks, the episode boundaries, the playhead and the tokens.
    `keep`: ticks never folded into ≈ (where the ruler marks a finding)."""
    cols = _columns(tl, _busy_ticks(tl) | ({tick} if not final else set()) | keep)
    lanes = tuple(ln for ln in tl.lanes if ln.born <= tick)
    rows = {ln.key: r for r, ln in enumerate(lanes)}
    g = _Grid()
    st = _styles()
    col = cols.of
    kinds = {}
    for ln in lanes:
        kinds[ln.key] = _kind_of(scn, ln.node)
    running = set()
    for s in tl.spans:                                         # bars
        r = rows.get(s.lane)
        if r is None or s.enter > tick:
            continue
        colour = _kind_colour(kinds[s.lane])
        work = (colour, None, False)
        wait = (kit.faded(colour, kit.SIM_TRAIL, "trail"), None, False)
        leave = s.leave if s.leave is not None else tl.last + 1
        stop = max(leave, s.enter + 1)
        waits = s.waits
        for t in range(s.enter, min(stop, tick + 1)):
            waiting = any(a <= t < b for a, b in waits)
            if t == s.enter and kinds[s.lane] == "event":
                g.put(r, col[t], LANDS, (kit.kind_color("event"), None, False), "bar")
            elif waiting:
                if not g.bar_at(r, col[t]) or g.cells[(r, col[t])][0] == WAIT:
                    g.put(r, col[t], WAIT, wait, "bar")
            else:
                g.put(r, col[t], WORK, work, "bar")
            if t == tick and not waiting:
                running.add(s.lane)
        if s.leave is not None and s.leave <= tick and s.how in ("failed", "cancelled"):
            c = col[stop] if stop in col else None
            if c is not None and g.free(r, c):
                g.put(r, c, FAILED if s.how == "failed" else CANCELLED,
                      st["error"] if s.how == "failed" else st["dim"], "head")
    for m in tl.marks:                                         # pulses, host ops, base cases
        r = rows.get(m.lane)
        if r is None or m.t > tick:
            continue
        glyph, style = {"self": (SELF, st["op"]), "host": (HOST, st["op"]),
                        "base": (BASE, st["mid"])}[m.what]
        g.put(r, col[m.t], glyph, style, "mark" if m.what != "base" else "head")
        if m.t == tick and m.what != "base":
            running.add(m.lane)
    for m in tl.moves:
        if m.start > tick:
            continue
        _paint_move(g, m, rows, col, tick, scn, st)
    for k, t, _n in tl.episodes[1:]:                           # episode boundaries
        c = col.get(t - 1)
        if c is not None and t - 1 <= tick:
            for r in range(len(lanes)):
                if g.glyph(r, c)[2] == "":
                    g.put(r, c, EPISODE, st["frame"], "rule")
    if not final:                                              # the playhead
        c = col[tick]
        for r in range(len(lanes)):
            if g.glyph(r, c)[2] == "":
                g.put(r, c, NOW_COL, st["dim"], "rule")
    if probe:
        c = col[tick]
        for (r, cc), (glyph, style, kind) in list(g.cells.items()):
            if cc == c and kind in ("bar", "token", "mark", "head"):
                g.cells[(r, cc)] = (glyph, kit.Probe(style or (None, None, False)), kind)
    return _Frame(g, rows, lanes, frozenset(running), cols, tick, final)


def _paint_move(g: _Grid, m, rows: dict, col: dict, tick: int, scn, st: dict) -> None:
    """One hop: a reply along its callee's lanes to ↩; anything else a vertical
    at its send tick from the sender's lane to each receiver's, the transit
    along the receiver's lane to its head (✖ / ⊘ where an attempt failed or was
    cancelled, • an actor reached, ⇱ a host's side), its token at the tick."""
    style = _wire_style(scn, m.wire)
    stroke = kit._stroke(m.kind)
    end = m.end if m.end is not None else tick + 1
    flying = m.end is None or m.end > tick
    if m.back:
        for k in m.src:
            r = rows.get(k)
            if r is None:
                continue
            if m.how == "cancelled" and m.end is not None and m.end <= tick:
                for t in range(m.start, m.end):
                    _hline(g, r, col[t], stroke, style)
                g.put(r, col[m.end], CANCELLED, st["dim"], "head")
                continue
            for t in range(m.start, min(end - 1, tick + 1)):
                _hline(g, r, col[t], stroke, style)
            if not flying and end - 1 >= m.start:
                g.put(r, col[end - 1], REPLY, st["op"], "head")
            elif flying and tick >= m.start and tick < end:
                g.put(r, col[tick], TOKEN_BACK, (style[0], None, True), "token")
        return
    srcs = [rows[k] for k in m.src if k in rows]
    dsts = sorted(rows[k] for k in m.dst if k in rows)
    if not srcs or not dsts:
        return
    c0 = col[m.start]
    top_src, low_src = min(srcs), max(srcs)
    vstyle = style
    above = [r for r in dsts if r < top_src]
    below = [r for r in dsts if r > low_src]
    for group, toward in ((below, _U), (above, _D)):
        if not group:
            continue
        if toward == _U:
            src_r, far = top_src, max(group)
            span = range(src_r, far + 1)
        else:
            src_r, far = low_src, min(group)
            span = range(far, src_r + 1)
        away = _D if toward == _U else _U
        for r in span:
            if r == src_r:
                if g.bar_at(r, c0) or not g.free(r, c0):
                    continue
                mask = away | (_L if g.bar_at(r, c0 - 1) or (r, c0 - 1) in g.lines else 0)
                g.line(r, c0, mask, stroke, vstyle)
            elif r == far:
                g.line(r, c0, toward | _R, stroke, vstyle)
            elif r in group:
                g.line(r, c0, _U | _D | _R, stroke, vstyle)
            elif r in srcs or g.bar_at(r, c0) or not g.free(r, c0):
                continue
            else:
                g.line(r, c0, _U | _D, stroke, vstyle)
    same = [r for r in dsts if top_src <= r <= low_src]
    for r in same:                                 # a lane calling another instance on its row
        if g.free(r, c0):
            g.line(r, c0, _R, stroke, vstyle)
    for r in dsts:
        _transit(g, r, m, col, tick, end, flying, stroke, style, st)


def _hline(g: _Grid, r: int, c: int, stroke: str, style) -> None:
    if g.free(r, c):
        g.line(r, c, _L | _R, stroke, style)


def _transit(g: _Grid, r: int, m, col: dict, tick: int, end: int, flying: bool,
             stroke: str, style, st: dict) -> None:
    ended = m.how in ("failed", "cancelled")
    last_stroke = end - 1 if ended else end - 2
    for t in range(m.start + 1, min(last_stroke, tick) + 1):
        _hline(g, r, col[t], stroke, style)
    if flying:
        if m.start < tick < end:
            g.put(r, col[tick], TOKEN_OUT, (style[0], None, True), "token")
        return
    if ended:
        g.put(r, col[end], FAILS if m.how == "failed" else CANCELLED,
              st["error"] if m.how == "failed" else st["dim"], "head")
        return
    if end - 1 > m.start and g.free(r, col[end - 1]):
        g.put(r, col[end - 1], _head(m.kind), style, "head")
    if m.how == "reached" and g.free(r, col[end]):
        g.put(r, col[end], REACHED, st["mid"], "head")
    elif m.how == "opaque" and g.free(r, col[end]):
        g.put(r, col[end], HOST, st["op"], "head")


# ---------------------------------------------------------------------------
# Labels, the ruler, notes
# ---------------------------------------------------------------------------

def _shows_ordinal(tl, prog) -> set:
    """The nodes whose lanes are labelled `·k`: two instances or more, or a
    dynamic, optional or spawned child."""
    n = {}
    for ln in tl.lanes:
        if ln.inst is not None:
            n.setdefault(ln.node, set()).add(ln.inst)
    out = {nid for nid, s in n.items() if len(s) > 1}
    for _ui, _k, t in prog.tree:
        if t.spawn or t.rel in ("$", "?"):
            out.add(t.node)
    return out


def _name(scn, nid: str) -> str:
    sn = scn.nodes.get(nid)
    return kit.node_label(sn.node) if sn is not None else nid


def _inst_name(scn, key, numbered: set) -> str:
    """An instance key as a label: `[Bullet·1]`, or `[Ship]` when its node
    has one instance."""
    label = _name(scn, key[0])
    if key[0] not in numbered:
        return label
    sn = scn.nodes.get(key[0])
    close = kit.KINDS.get(sn.node.kind, {}).get("close", "]") if sn is not None else "]"
    return label[:len(label) - len(close)] + f"·{key[1]}" + close if close else label


def _label_text(ln, scn, numbered: set) -> str:
    if ln.par > 1:
        return f"{PAR}{ln.par}"
    if ln.levels:
        return f"{LEVEL}{ln.levels[0]}‥{LEVEL}{ln.levels[1]}"
    if ln.level > 1:
        return f"{LEVEL}{ln.level}"
    label = _name(scn, ln.node)
    sn = scn.nodes.get(ln.node)
    close = kit.KINDS.get(sn.node.kind, {}).get("close", "]") if sn is not None else "]"
    if ln.fold:
        opener = label[:len(label) - len(close) - len(sn.node.name if sn else "")]
        return f"{opener}…×{len(ln.fold)} more{close}"
    if ln.inst is not None and ln.node in numbered:
        return label[:len(label) - len(close)] + f"·{ln.inst[1]}" + close
    return label


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def _label_runs(ln, scn, numbered: set, tick: int, marks) -> list:
    text = _cut(_label_text(ln, scn, numbered), LABEL_MAX)
    st = _styles()
    if ln.level > 1 or ln.levels or ln.par > 1:
        runs = [(text, st["op"])]
    else:
        kind = _kind_of(scn, ln.node)
        runs = (kit.glyph_runs(text, kind) if kind not in ("", "state", "hole")
                else [(text, (_kind_colour(kind), None, False))])
    if ln.spawned is not None and ln.spawned > tick:
        runs.append((" " + PENDING, st["mid"]))
    if marks:
        runs += kit.check_runs(marks)
    return runs


def _ruler(fr: _Frame, tl, lo: int, hi: int, x0: int, witnessed: tuple = (),
           room: Optional[int] = None) -> list:
    """The ruler over columns lo … hi - 1: the playhead `▼t`, a finding's
    number where this run shows it (`witnessed`: ((tick, CheckMark), …)), `ep2`
    where an episode starts, `↺k` where a loop's k-th iteration starts (k ≥ 2),
    the last tick, ticks at multiples of 10, ≈ on a folded stretch — each only
    where it touches no label placed before it, and nothing right of the
    playhead. room: the columns after x0 a label may reach (None: any); the
    playhead short of room is `▼` alone."""
    st = _styles()
    want = []
    if not fr.final:
        want.append((fr.cols.of[fr.tick], NOW + str(fr.tick), st["now"]))
    want += [(fr.cols.of[t], kit.check_glyph(m), kit.check_mark_style(m))
             for t, m in witnessed if t in fr.cols.of and t <= fr.tick]
    want += [(fr.cols.of[t], f"ep{k}", st["section"]) for k, t, _n in tl.episodes[1:]
             if t in fr.cols.of]
    want += [(fr.cols.of[it.t], f"{ITERATION}{it.k}", st["op"]) for it in tl.iterations
             if it.k > 1 and it.t in fr.cols.of and it.t <= fr.tick]
    want += [(c, QUIET, st["dim"]) for c in sorted(fr.cols.quiet)]
    want += [(fr.cols.of[t], str(t), st["dim"]) for t in range(0, tl.last + 1, 10)
             if t in fr.cols.of and fr.cols.of[t] not in fr.cols.quiet]
    want.append((fr.cols.of[tl.last], str(tl.last), st["dim"]))
    taken, placed = set(), []
    for c, text, style in want:
        if not lo <= c < hi:
            continue
        if room is not None and c - lo + len(text) > room:
            if not text.startswith(NOW):
                continue
            text = NOW
        cells = set(range(c - 1, c + len(text) + 1))
        if cells & taken:
            continue
        taken |= set(range(c, c + len(text)))
        placed.append((c, text, style))
    row, x = [(" " * x0, None)], lo
    for c, text, style in sorted(placed):
        if c > x:
            row.append((" " * (c - x), None))
        row.append((text, style))
        x = c + len(text)
    return row


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _call_word(carries: Optional[str]) -> str:
    return re.sub(r"\(.*\)", "()", carries or "").strip()


class Clause(NamedTuple):
    """One clause of a lane's note: its text, how long it stays when the note
    must shrink (higher stays longer; an outcome, OUTCOME, goes last) and a
    shorter form tried before it is dropped."""
    text: str
    keep: int
    short: Optional[str] = None


OUTCOME, ROLE, REPEAT, WHO, ENTRY, MINOR = 9, 6, 5, 4, 3, 1


def _by_lane(items: list, lanes_of) -> dict:
    """{lane key: [the indices of the items that name it]} (lanes_of(item))."""
    out = {}
    for i, it in enumerate(items):
        for k in lanes_of(it):
            out.setdefault(k, []).append(i)
    return out


def _of_lanes(items: list, at: dict, fam) -> list:
    """The items naming any lane of fam, in their order, each once."""
    return [items[i] for i in sorted({i for k in fam for i in at.get(k, ())})]


def lane_notes(tl, scn, numbered: set, tick: int, final: bool) -> dict:
    """{lane key: [Clause, …]}: each lane's run in plain words as far as
    `tick` — who (whose instance, who spawned it, a fold's), its role (an
    episode's entry, lands, calls, fans out, routes a failure, emits, returns,
    produces, a self-call, the host, reached), how often (runs k×, k attempts,
    recursion depth) and how it ended (fails, cancelled, falls back) — read
    from the timeline's facts. During a run the counts say "so far". A lane
    with nothing notable has none."""
    so_far = "" if final else " so far"
    spans = [s for s in tl.spans if s.enter <= tick]
    moves = [m for m in tl.moves if m.start <= tick]
    marks = [m for m in tl.marks if m.t <= tick]
    by_key = {ln.key: ln for ln in tl.lanes}
    entries = {(t, n) for _k, t, n in tl.episodes}
    ep_of = {t: k for k, t, _n in tl.episodes}
    depth = {}
    for ln in tl.lanes:
        if ln.level > 1 and ln.born <= tick:
            top = ln.levels[1] + 1 if ln.levels else ln.level
            base = (ln.node, ln.key[1], 1)
            depth[base] = max(depth.get(base, 1), top)
    rows = {}                           # lane key → it and its ∥ sub-rows
    for ln in tl.lanes:
        rows.setdefault(ln.key[:3], set()).add(ln.key)
    # Each lane's spans, moves (by source, by destination) and marks, by index.
    span_at = _by_lane(spans, lambda s: (s.lane,))
    src_at, dst_at = _by_lane(moves, lambda m: m.src), _by_lane(moves, lambda m: m.dst)
    mark_at = _by_lane(marks, lambda m: (m.lane,))
    loops_at = {}
    for it in tl.iterations:
        loops_at.setdefault(it.act, []).append(it)
    out = {}
    for ln in tl.lanes:
        if ln.born > tick or ln.level > 1 or ln.levels or ln.par > 1:
            continue
        fam = rows[ln.key]
        mine = _of_lanes(spans, span_at, fam)
        acts = {s.act for s in mine}
        into = [m for m in _of_lanes(moves, dst_at, fam) if not m.back]
        from_fam = _of_lanes(moves, src_at, fam)
        outof = [m for m in from_fam if not m.back]
        replies = [m for m in from_fam if m.back]
        kind = _kind_of(scn, ln.node)
        cl = []
        if ln.fold:
            owners = ln.owners
            if owners and all(o[0] == owners[0][0] for o in owners):
                cl.append(Clause(f"{_inst_range(scn, owners[0], owners[-1], numbered)}'s, alike",
                                 WHO))
            else:
                cl.append(Clause("alike", WHO))
        elif ln.spawned is not None:
            who = f"spawned by {_name(scn, ln.spawner)}" if ln.spawner else "spawned"
            short = who
            if ln.owner:
                who += f" for {_inst_name(scn, ln.owner, numbered)}"
                short = f"spawned for {_inst_name(scn, ln.owner, numbered)}"
            cl.append(Clause(who, WHO, short))
        elif ln.owner:
            cl.append(Clause(f"{_inst_name(scn, ln.owner, numbered)}'s", WHO))
        for s in mine:
            if s.caller is None and s.wire is None and (s.enter, s.node) in entries:
                cl.append(Clause(f"episode {ep_of[s.enter]}'s entry", ENTRY))
                break
        if kind == "event" and mine:
            n = len(acts)
            cl.append(Clause("lands" + (f" {n}×" if n > 1 else ""), MINOR))
        calls = list(dict.fromkeys(scn_dst(scn, m) for m in outof
                                   if m.kind in ("->", "<->") and len(m.dst) == 1
                                   and scn_dst(scn, m) != ln.node))
        if calls:
            names = [_name(scn, n) for n in calls]
            text = ("calls " + names[0] if len(names) == 1 else
                    f"calls {', '.join(names[:-1])}, then {names[-1]}")
            cl.append(Clause(text, MINOR, f"calls {len(names)} others" if len(names) > 1 else None))
        fan = {}
        for m in outof:
            if m.kind == "*>":
                fan.setdefault(m.act, set()).update(m.dst)
        if fan and max(len(v) for v in fan.values()) > 1:
            cl.append(Clause(f"fans out to {max(len(v) for v in fan.values())}, waits for all",
                             ROLE))
        if any(m.kind == "!>" for m in outof):
            cl.append(Clause("routes the failure", ROLE))
        spawning = [m for m in outof if m.kind == "=>" and any(
            k in by_key and by_key[k].spawned is not None for k in m.dst)]
        if spawning:
            dst = _name(scn, scn_dst(scn, spawning[0]))
            cl.append(Clause(f"produces into {dst}: a new instance", ROLE,
                             f"produces into {dst}"))
        produced = [m for m in into if m.kind == "=>"]
        if produced and ln.spawned is None:
            who = by_key.get(produced[0].src[0])
            cl.append(Clause(f"produced by {_name(scn, who.node) if who else '?'}", ROLE))
        emits = list(dict.fromkeys(scn_dst(scn, m) for m in outof if m.kind == "~>"))
        if emits:
            cl.append(Clause(f"emits {_name(scn, emits[0])}, doesn't wait", ROLE,
                             "emits, doesn't wait"))
        returned = [m for m in replies if m.how == "returned" and m.carries]
        if returned:
            cl.append(Clause(f"returns {returned[-1].carries}", ROLE))
        mine_marks = _of_lanes(marks, mark_at, fam)
        selfs = [m for m in mine_marks if m.what == "self"]
        hosts = [m for m in mine_marks if m.what == "host"]
        if selfs:
            cl.append(Clause(f"runs {_call_word(selfs[0].carries) or 'a self-call'} itself",
                             ROLE))
        if hosts:
            cl.append(Clause(f"calls the host: {_call_word(hosts[0].carries)}", ROLE))
        if any(m.how == "reached" for m in into):
            cl.append(Clause("reached: an actor, no work of its own", ROLE, "reached"))
        elif any(m.how == "opaque" for m in into):
            cl.append(Clause("reached: the host's side, opaque", ROLE, "reached: opaque"))
        if len(acts) > 1 and kind != "event":
            cl.append(Clause(f"runs {len(acts)}×{so_far}", REPEAT))
        loops = {}
        for act in acts:
            for it in loops_at.get(act, ()):
                if it.t <= tick:
                    loops[it.block] = max(loops.get(it.block, 0), it.k)
        if loops and max(loops.values()) > 1:
            cl.append(Clause(f"loops {max(loops.values())}×{so_far}", REPEAT))
        if ln.key in depth:
            cl.append(Clause(f"recurses to depth {depth[ln.key]}"
                             + (" each time" if len(acts) > 1 else ""), REPEAT))
        attempts = [m for m in into if m.attempt]
        ended = [m for m in into if m.end is not None and m.end <= tick]
        failed_in = [m for m in ended if m.how == "failed"]
        lost = [m for m in ended if m.how == "cancelled"]
        if len(attempts) > 1 and failed_in and all(m.how == "failed" for m in ended
                                                   if m.attempt):
            cl.append(Clause(f"{_plural(len(attempts), 'attempt')}{so_far}, each fails", OUTCOME,
                             f"{len(attempts)} attempts fail"))
        elif failed_in:
            cl.append(Clause("its call fails on arrival", OUTCOME, "fails on arrival"))
        elif lost:
            cl.append(Clause("cancelled on the way: lost", OUTCOME, "lost"))
        elif len(attempts) > 1:
            cl.append(Clause(f"{_plural(len(attempts), 'attempt')}{so_far}", REPEAT))
        fb = [m for m in replies if m.how == "fallback"
              and m.end is not None and m.end <= tick]
        if fb:
            cl.append(Clause(f"falls back to {fb[-1].carries}", OUTCOME))
        hows = {s.how for s in mine if s.leave is not None and s.leave <= tick}
        if "failed" in hows:
            cl.append(Clause("fails", OUTCOME))
        elif "cancelled" in hows:
            cl.append(Clause("cancelled", OUTCOME))
        if not mine and not ended and into:
            cl.append(Clause("on its way", MINOR))
        if cl:
            out[ln.key] = cl
    return out


def scn_dst(scn, m) -> str:
    w = next((x for x in scn.wires if x.ident == m.wire), None)
    return w.dst if w is not None else m.dst[0][0]


def _inst_range(scn, a, b, numbered: set) -> str:
    if a == b:
        return _inst_name(scn, a, numbered)
    first = _inst_name(scn, a, numbered)
    close = first[-1]
    return first[:-1] + f"‥{b[1]}" + close if a[0] == b[0] else first


def _fit_note(clauses: list, budget: int, cut: bool = True) -> Optional[str]:
    """The clauses joined with `; ` in their order, shrunk to fit `budget`: in
    turn, the clause that stays least long first (an outcome last), each takes
    its short form if it has one, then is dropped (never the last one). Still
    too long: cut with … (cut=False: None instead)."""
    keep = [[c.text, c.keep, c.short] for c in clauses]
    text = lambda: "; ".join(k[0] for k in keep)
    for item in sorted(keep, key=lambda k: k[1]):
        if len(text()) <= budget:
            break
        if item[2]:
            item[0], item[2] = item[2], None
            if len(text()) <= budget:
                break
        if len(keep) > 1:
            keep.remove(item)
    if len(text()) <= budget:
        return text()
    if not cut:
        return None
    return _cut(text(), budget) if budget > 1 else ""


def _design_notes(scn, ln) -> list:
    """The design's notes (its `#` comments) on a lane's node, as clauses."""
    sn = scn.nodes.get(ln.node)
    if sn is None or ln.level > 1 or ln.levels or ln.par > 1:
        return []
    return [Clause(f"#{num} {text}" if num else text, MINOR) for num, text, _k, _e in sn.notes]


# ---------------------------------------------------------------------------
# compose_run
# ---------------------------------------------------------------------------

_CACHE: dict = {}                  # (id(trace), show, limits) → (trace, Timeline)


def run_timeline(trace, limits=None, show: Optional[int] = None):
    """sim.timeline(trace) for a canonical trace, cached per trace (a run's
    frames are drawn from one Timeline)."""
    limits = limits or sim.Limits()
    show = sim.RUN_SHOW if show is None else show
    key = (id(trace), show, limits)
    hit = _CACHE.get(key)
    if hit is None or hit[0] is not trace:
        if len(_CACHE) > 8:
            _CACHE.clear()
        tl = sim.timeline(trace, limits=limits, show=show if show > 0 else None)
        hit = _CACHE[key] = (trace, tl)
    return hit[1]


_HAPPY: list = [None, None, None]   # [graph, limits, its happy run]


def happy_run(g, limits=None):
    """The happy run (every default) of a parsed document, on its canonical
    scene; the last one kept (the view redraws it often)."""
    limits = limits or sim.Limits()
    if _HAPPY[0] is not g or _HAPPY[1] != limits:
        canon = sim._program_of(g).scene
        run = sim.simulate(canon, sim.scenario(canon, "happy", limits=limits), limits=limits)
        _HAPPY[:] = [g, limits, run]
    return _HAPPY[2]


def compose_run(g, trace=None, tick: Optional[int] = None, width: Optional[int] = None,
                notes: str = "run", checks=None, show: Optional[int] = None, limits=None,
                chosen: bool = True, probe: bool = False):
    """The run view as rows of (text, style) runs, plus its width. `trace`: a
    run on the canonical scene (sim.simulate's; None: the happy run, and the
    title says no scenario was chosen); `tick`: the frame shown (None: the
    last). `chosen`: whether a scenario was chosen (False: the title and the
    line under the drawing say this is the happy run). `width`: the columns to
    fit — notes beside (clauses dropped to fit), then below, then bands, then
    labels cut. `notes`: run | design | off. `checks`: kit.CheckMarks named as
    the canonical scene names things (a finding this run witnesses also puts
    its number on the ruler at the tick it shows). `show`: instances per group before
    folding (sim.RUN_SHOW; 0: never fold). `probe`: the playhead's cells in
    kit.Probe styles (sim_focus)."""
    if trace is None:
        trace, chosen = happy_run(g, limits), False
    prog = sim._program_of(trace.scene.graph)
    scn = prog.scene                    # the canonical scene: a projected trace's events
    tl = run_timeline(trace, limits, show)   # name things as it does
    last_i = len(trace.frames) - 1
    i = last_i if tick is None else max(0, min(tick, last_i))
    t = trace.frames[i].tick if trace.frames else 0
    final = i == last_i
    witnessed = tuple(sorted(((at, m) for name, at, m in getattr(checks, "witnesses", ())
                              if name == trace.scenario.name and at <= tl.last),
                             key=lambda x: (x[1].number, x[0])))
    fr = _paint(tl, scn, t, final, probe, frozenset(at for at, _m in witnessed))
    numbered = _shows_ordinal(tl, prog)
    st = _styles()
    node_marks = checks.nodes if checks is not None else {}
    wire_marks = {}
    if checks is not None:
        for ident, ms in checks.wires.items():
            wire_marks.setdefault(ident[1], []).extend(ms)
    labels, label_w = {}, 0
    shown = {ln.key for ln in fr.lanes}
    for ln in tl.lanes:                 # every lane's widest label: the column holds still in a run
        depth = 0
        p = ln.parent
        while p is not None and depth < 50:
            depth += 1
            p = next((x.parent for x in tl.lanes if x.key == p), None)
        ms = () if ln.level > 1 or ln.levels or ln.par > 1 else tuple(sorted(set(
            list(node_marks.get(ln.node, ())) + wire_marks.get(ln.node, []))))
        lead = [(" " * (2 * depth), None)]
        widest = lead + _label_runs(ln, scn, numbered, -1, ms)    # with ◌ if it is ever spawned
        label_w = max(label_w, kit.row_len(widest))
        if ln.key in shown:
            labels[ln.key] = lead + _label_runs(ln, scn, numbered, t, ms)
    x0 = GUTTER + label_w + 1
    shown_cols = fr.cols.of[t] + 1
    if notes == "run":
        said = lane_notes(tl, scn, numbered, t, final)
    elif notes == "design":
        said = {ln.key: _design_notes(scn, ln) for ln in fr.lanes}
        said = {k: v for k, v in said.items() if v}
    else:
        said = {}
    title = _title(trace, chosen)
    total = x0 + fr.cols.n
    room = (width - total - NOTE_GAP) if width is not None else None
    beside = bool(said) and (room is None or (room >= NOTE_MIN and all(
        _fit_note(cl, room, cut=False) is not None for cl in said.values())))
    banded = width is not None and total > width
    if banded:
        beside = False
        if width - x0 < BAND_MIN and label_w > LABEL_MIN:      # labels cut to leave a band room
            label_w = max(width - GUTTER - 1 - BAND_MIN, LABEL_MIN)
            labels = {k: _cut_runs(v, label_w) for k, v in labels.items()}
            x0 = GUTTER + label_w + 1
    rows = [kit.section_rule(title if width is None else kit.fit_title(title, width - 6)), []]
    bands = _bands(fr, width - x0 if banded else fr.cols.n, shown_cols)
    for k, (lo, hi) in enumerate(bands):
        if k:
            rows.append([])
        rows.append(_ruler(fr, tl, lo, hi, x0, witnessed,
                           None if width is None else width - x0))
        for ln in fr.lanes:
            r = fr.rows[ln.key]
            cells = [fr.grid.glyph(r, c) for c in range(lo, min(hi, shown_cols))]
            if len(bands) > 1 and not any(kind not in ("", "vertical", "rule")
                                          for _g, _s, kind in cells):
                continue
            gutter = (RUNNING + " ", st["now"]) if ln.key in fr.running and not final \
                else (" " * GUTTER, None)
            row = [gutter] + labels[ln.key]
            row.append((" " * (x0 - kit.row_len(row)), None))
            row += [(glyph, style) for glyph, style, _k in cells]
            if beside and k == 0 and ln.key in said:
                pad = fr.cols.n - (min(hi, shown_cols) - lo) + NOTE_GAP
                budget = (width - total - NOTE_GAP) if width is not None else 10 ** 6
                text = _fit_note(said[ln.key], budget)
                if text:
                    row += [(" " * pad, None), (text, st["note"])]
            rows.append(_merge(row))
    if said and not beside:
        rows.append([])
        budget = (width - x0) if width is not None else 10 ** 6
        for ln in fr.lanes:
            if ln.key in said:
                lab = [(" " * GUTTER, None)] + labels[ln.key]
                lab.append((" " * (x0 - kit.row_len(lab)), None))
                rows.append(lab + [(_fit_note(said[ln.key], budget), st["note"])])
    if not chosen:
        head = f"happy run (every default) · {trace.outcome} · {len(trace.frames)} frames"
        keys = "x plays it   [ ] another scenario"
        rows.append([])
        if width is None or len(head) + 3 + len(keys) <= width:
            rows.append([(head, st["mid"]), ("   " + keys, st["dim"])])
        else:                                   # each on lines of its own, wrapped
            rows += [[(ln, st["mid"])] for ln in _wrapped(head, width)]
            rows += [[(ln, st["dim"])] for ln in _wrapped(keys, width)]
    w = max(kit.row_len(r) for r in rows if not isinstance(r, kit.RuleRow))
    if width is not None and w > width:         # still wider: too narrow for a band
        rows += [[]] + kit.wide_hint("run", "the timeline", w, width, advice=None)
    if width is not None:                       # the title runs out to the width
        w = max(w, width)
    rows = [_strip(r) for r in kit.stretch_rules(rows, w)]
    return rows, w


def _title(trace, chosen: bool) -> str:
    sc = trace.scenario
    if not chosen:
        return f"run · {sc.name} — no scenario chosen: the happy run"
    return f"run · {sc.name}" + (f" — {sc.label}" if sc.label else "")


def _cut_runs(row: list, w: int) -> list:
    """A label's runs cut to w columns, the last one `…`."""
    if kit.row_len(row) <= w:
        return row
    cut = kit.clip(row, 0, w - 1)
    return cut + [("…", cut[-1][1] if cut else None)]


def _wrapped(text: str, width: int) -> list:
    """Text wrapped at width between words (a word longer stays whole)."""
    return textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False) or [text]


def _merge(row: list) -> list:
    out = []
    for text, style in row:
        if not text:
            continue
        if out and out[-1][1] == style:
            out[-1] = (out[-1][0] + text, style)
        else:
            out.append((text, style))
    return out


def _strip(row):
    if isinstance(row, kit.RuleRow) or not row:
        return row
    row = list(row)
    while row and not row[-1][0].strip():
        row.pop()
    if row:
        row[-1] = (row[-1][0].rstrip(), row[-1][1])
    return row


def _bands(fr: _Frame, band_w: int, shown: int) -> list:
    """[(lo, hi)] column ranges: one band when the shown columns fit band_w,
    else cuts each chosen in the last 40% of a band at the column with the
    fewest marks (an episode boundary best); only the bands up to the
    playhead."""
    n = fr.cols.n
    if n <= band_w or band_w < 8:
        return [(0, min(n, max(shown, 0)) if not fr.final else n)] if n else [(0, 0)]
    out, lo = [], 0
    while lo < n:
        if n - lo <= band_w:
            out.append((lo, n))
            break
        best, score = lo + band_w, None
        for c in range(lo + max(int(band_w * BAND_FROM), 1), lo + band_w + 1):
            s = _col_score(fr, c)
            if score is None or s <= score:
                best, score = c, s
        out.append((lo, best))
        lo = best
    return [(a, b) for a, b in out if a < shown]


def _col_score(fr: _Frame, c: int) -> int:
    marks = 0
    for r in range(len(fr.lanes)):
        glyph, _s, kind = fr.grid.glyph(r, c)
        if glyph == EPISODE:
            return -1
        if kind not in ("", "rule"):
            marks += 1
    return marks


# ---------------------------------------------------------------------------
# Legend and data
# ---------------------------------------------------------------------------

def run_legend() -> list:
    """The run view's legend row: the bars, the connectors in each arrow's
    stroke, the outcomes, the marks, the ruler's."""
    st = _styles()
    mid = st["mid"]
    work = (kit.kind_color("service"), None, False)
    wait = (kit.faded(kit.kind_color("service"), kit.SIM_TRAIL, "trail"), None, False)
    row = [("run    ", st["dim"]), (WORK, work), (" working  ", mid), (WAIT, wait),
           (" waiting  ", mid), (LANDS, (kit.kind_color("event"), None, False)),
           (" lands  ", mid)]
    for kind, word in (("->", "call"), ("~>", "async"), ("=>", "produces"),
                       ("*>", "broadcast"), ("!>", "error")):
        own = scene.arrow_colour(kind)
        colour = scene.colour_of(own) if own else kit.EDGE_DEFAULT
        sample = "╰" + kit._stroke_sample(kind) * 2 + _head(kind)
        row += [(sample, (colour, None, False)), (f" {word}  ", mid)]
    wire = (kit.EDGE_DEFAULT, None, False)
    row += [("───" + REPLY, wire), (" reply  ", mid),
            (FAILS, st["error"]), (" fails on arrival  ", mid),
            (FAILED, st["error"]), (" failed  ", mid), (CANCELLED, st["dim"]),
            (" cancelled  ", mid), (SELF, st["op"]), (" self-call  ", mid),
            (LEVEL + "k", st["op"]), (" depth k  ", mid), (PAR + "k", st["op"]),
            (" at once  ", mid), (BASE, mid), (" base case  ", mid),
            (HOST, st["op"]), (" host  ", mid), (REACHED, mid), (" reached  ", mid),
            (PENDING, mid), (" spawning  ", mid), (EPISODE, st["frame"]), (" episode  ", mid),
            (QUIET, st["dim"]), (" quiet ticks  ", mid), (ITERATION + "k", st["op"]),
            (" iteration k  ", mid), (NOW, st["now"]), (" now  ", mid),
            (RUNNING, st["now"]), (" running", mid)]
    return row


def timeline_json(trace, limits=None, show: Optional[int] = None) -> dict:
    """The timeline of a canonical trace as data (--run --json): lanes with
    their labels, spans, moves and marks."""
    tl = run_timeline(trace, limits, show)
    prog = sim._program_of(trace.scene.graph)
    scn = prog.scene
    numbered = _shows_ordinal(tl, prog)
    key = lambda k: list(k)
    return {
        "scenario": trace.scenario.name, "outcome": trace.outcome, "last": tl.last,
        "episodes": [{"episode": k, "tick": t, "entry": _name(scn, n)}
                     for k, t, n in tl.episodes],
        "folded": tl.folded,
        "iterations": [{"t": it.t, "k": it.k, "of": it.of, "owner": it.block[0],
                        "block": it.block[1], "act": it.act} for it in tl.iterations],
        "lanes": [{"key": key(ln.key), "label": _label_text(ln, scn, numbered),
                   "parent": key(ln.parent) if ln.parent else None, "born": ln.born,
                   "owner": list(ln.owner) if ln.owner else None, "spawned": ln.spawned,
                   "fold": [list(i) for i in ln.fold], "levels": list(ln.levels),
                   "par": ln.par}
                  for ln in tl.lanes],
        "spans": [{"lane": key(s.lane), "act": s.act, "task": s.task, "enter": s.enter,
                   "leave": s.leave, "how": s.how, "waits": [list(w) for w in s.waits]}
                  for s in tl.spans],
        "moves": [{"id": m.id, "kind": m.kind, "back": m.back, "start": m.start,
                   "end": m.end, "how": m.how, "src": [key(k) for k in m.src],
                   "dst": [key(k) for k in m.dst], "attempt": list(m.attempt)
                   if m.attempt else None, "carries": m.carries} for m in tl.moves],
        "marks": [{"lane": key(m.lane), "t": m.t, "what": m.what} for m in tl.marks],
    }
