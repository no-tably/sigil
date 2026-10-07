#!/usr/bin/env python3
"""
pane.py — the Claude Code mod's Python half: a Sigil document drawn for the
mod's pane, and the supervisor its multiplexer split runs. The build copies it
into the plugin's skills/sigil/scripts/ beside view.py and site/frames.py
(as frames.py); in the repo it finds them two directories up. Nothing here
draws: view.py does, and frames.py packs the rows as the page's frames.json
is packed — with the theme's hex colours in the style table instead of its
role names, since the mod paints cells, not CSS.

Usage:
    pane.py draw FILE [--view graph|tree|flow|run] [--depth N|all] [--width N]
                      [--height N] [--layout auto|wrap|pan] [--scenario NAME]
                      [--payloads] [--theme NAME]
        One JSON object on stdout: {"file", "view", "width", "layout" (what was
        drawn: wrap — fitted to --width — or pan — the natural layout; auto picks
        as view.py does for a --width × --height pane, wrap without --height),
        "styles":
        [[fg hex|null, bg hex|null, bold]], "frames": [rows], "legend": rows,
        "summary", "lint": [lines], "scenarios": [names], and with --scenario
        "scenario", "status": [a line per frame], "log": [the latest log line
        per frame], "say": [the narration line per frame: the latest beat in
        plain words, view.py's `›` line], "trail": [the episode's path so far
        per frame, in notation as text — view.py's path row without its label,
        the hop now marked `▸`], "path": [the same row per frame as view.py
        draws it, at most two rows, the hop now bold], "outcome", "at": [the
        run's frame each drawn frame shows: a long run is sampled to at most
        MAX_FRAMES], "last": the run's last frame}; a row is
        [[text, style id], …].
        The legend is the tree's key, the flow view's or the run view's, then a
        run's marks (the run view: its path's only; without --scenario it draws
        the happy run). A document or
        view that cannot be drawn: {"error"}. Exit status 0 either way.
    pane.py follow CONTROL
        The multiplexer split's loop: runs `view.py` live with the argv in the
        JSON file CONTROL ({"argv": [...]}), restarts it whenever CONTROL
        changes, touches CONTROL.alive every second so the mod can tell the
        split is still up, and exits when view.py quits on its own (q) or the
        split closes — removing both files. A view.py that fails (a bad flag,
        an unreadable file) leaves its message on screen and the loop waiting.

Every cell is one terminal column: a wide or zero-width character becomes `?`
so the mod's grid keeps the drawing's columns. Standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# the tools: beside this file in the plugin, two up in the repo
_TOOLS = _HERE if (_HERE / "view.py").is_file() else _HERE.parents[2]
_FRAMES = _HERE / "frames.py" if (_HERE / "frames.py").is_file() else _TOOLS / "site" / "frames.py"

VIEWS = ("graph", "tree", "flow", "run")
MAX_FRAMES = 400            # a longer run is sampled evenly, its last frame kept
LINT_LINES = 5              # diagnostics carried into the reply
FOLLOW_POLL_S = 0.3         # how often follow looks at CONTROL
ALIVE_S = 1.0               # how often follow touches CONTROL.alive
_SPEED_RE = re.compile(r" (?:▶|❚❚) \S+ frames?/s")   # the live view's play mark and speed


def _load(name: str, path: Path):
    """A module by path (they are not a package)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


# ---------------------------------------------------------------------------
# draw
# ---------------------------------------------------------------------------

def cell(ch: str) -> str:
    """`ch` when it fills exactly one terminal column, else `?`."""
    if len(ch) != 1 or ord(ch) > 0xFFFF:
        return "?"
    if unicodedata.east_asian_width(ch) in ("W", "F") or unicodedata.category(ch)[0] in "MC":
        return "?"
    return ch


def cells(text: str) -> str:
    return "".join(ch if " " <= ch < "\x7f" else cell(ch) for ch in text)


def hex_styles(frames):
    """frames.Styles with each colour as its hex value, not its theme role."""
    class HexStyles(frames.Styles):
        @staticmethod
        def _colour(c):
            return str(c) if c else None
    return HexStyles()


def packed(rows, styles, frames) -> list:
    """view.py rows → frames.py's packed rows, every cell one column wide."""
    return frames.pack_rows([[(cells(t), st) for t, st in row] for row in rows], styles)


def compose(view, g, name: str, **kw):
    """(rows, width) of `g` in view `name` (a name in VIEWS); a view.py too old to
    know it raises LookupError naming what is missing."""
    if name not in getattr(view, "VIEWS", ("graph", "tree")):
        raise LookupError(f"this view.py has no {name} view")
    return view.compose_view(g, name, **kw)


def sampled(last: int, cap: int = MAX_FRAMES) -> list[int]:
    """Frame indices 0..last, at most `cap` of them, evenly spread, both ends kept."""
    if last + 1 <= cap:
        return list(range(last + 1))
    return sorted({round(i * last / (cap - 1)) for i in range(cap)})


def lint_summary(diags) -> str:
    errors = sum(d.severity == "error" for d in diags)
    warns = sum(d.severity == "warn" for d in diags)
    if not diags:
        return "lint: OK"
    return f"lint: {errors} error{'s' * (errors != 1)}, {warns} warning{'s' * (warns != 1)}"


def placing(view, g, name: str, layout: str, width: int | None, height: int | None,
            kw: dict) -> str:
    """wrap | pan: what `layout` draws in a width × height pane — auto as the
    live view picks (view.pick_layout on the natural drawing; wrap without a
    height or a width)."""
    if layout != "auto":
        return layout
    if not width or not height:
        return "wrap"
    rows, w = compose(view, g, name, **{**kw, "width": None})
    return view.pick_layout(w, len(rows), width, height)


def draw(path: Path, view_name: str = "flow", depth: int = 1, width: int | None = None,
         scenario: str | None = None, payloads: bool = False, theme: str | None = None,
         layout: str = "auto", height: int | None = None) -> dict:
    """The JSON object `pane.py draw` prints (see the module docstring)."""
    view = _load("sigil_view", _TOOLS / "view.py")
    frames = _load("sigil_site_frames", _FRAMES)
    try:
        view.use_theme(theme)
    except ValueError as exc:
        return {"error": str(exc)}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"{path}: {exc.strerror or exc}"}
    tree = view_name == "tree"
    g = view.render.parse_document(text)
    events = view.DEFAULT_EVENTS.get(view_name, "land")
    kw = dict(depth=depth, payloads=payloads, notes="off", triggers=True, spaced=True,
              width=width, access=False, mods=False, events=events)
    styles = hex_styles(frames)
    out: dict = {"file": path.name, "view": view_name, "width": width}
    try:
        out["layout"] = placing(view, g, view_name, layout, width, height, kw)
        if out["layout"] == "pan":
            kw["width"] = None
        sim = None
        if scenario:
            sim = view.SimPlayer(g, scenario)
            shown = sim.shown(view.scene.SceneOptions(events, True, False, depth))
            picks = sampled(sim.last)
            drawn, status, log, say, trail, path_rows = [], [], [], [], [], []
            cols = width or view.LEGEND_WIDTH
            for at in picks:
                sim.at = at
                rows, _w = compose(view, g, view_name, trace=shown, tick=at, **kw)
                drawn.append(packed(rows, styles, frames))
                status.append(_SPEED_RE.sub("", sim.status()))
                log.append(sim.log_line())
                say.append(sim.narration())
                trail.append(sim.path())
                path_rows.append(packed(view.path_rows(sim.path_branches(), cols, hold=True),
                                   styles, frames))
            out.update(scenario=sim.scenario.name, status=status, log=log, say=say, trail=trail,
                       path=path_rows, at=picks, last=sim.last,
                       outcome=sim.trace.outcome, choice=sim.choice())
        else:
            rows, _w = compose(view, g, view_name, **kw)
            drawn = [packed(rows, styles, frames)]
    except view.UnknownScenario as exc:
        return {"error": f"scenario: {exc}"}
    except LookupError as exc:
        return {"error": str(exc)}
    legend = []
    if tree:
        legend += view.vtree.tree_legend(True, payloads, False, False, events,
                                         calls=view.drawn_call_marks(g, depth, payloads))
    elif view_name == "flow":
        legend.append(view.vflow.flow_legend(True, payloads, False, False, events))
    elif view_name == "run":
        legend.append(view.vrun.run_legend())
    if scenario:
        legend += ([view.path_legend()] if view_name == "run"
                   else [view.sim_legend(tree), view.path_legend()])
    cols = min(view.LEGEND_WIDTH, width or view.LEGEND_WIDTH)
    out["legend"] = packed([ln for r in legend for ln in view.wrap_legend(r, cols)],
                           styles, frames)
    diags = view.run_lint(text)
    mode = view.doc_mode(text)
    out["summary"] = (f"{path.name}: {len(g.nodes)} nodes, {len(g.edges)} edges"
                      + (f" · {mode}" if mode else "") + " · " + lint_summary(diags))
    out["lint"] = [d.format() for d in diags[:LINT_LINES]]
    try:
        canon = view.simulator.canonical(g)
        out["scenarios"] = [s.name for s in view.simulator.scenarios(canon)]
    except Exception:                       # a half-written design still draws
        out["scenarios"] = []
    out["frames"], out["styles"] = drawn, styles.table
    return out


# ---------------------------------------------------------------------------
# follow
# ---------------------------------------------------------------------------

def read_control(path: Path) -> list[str] | None:
    """The argv CONTROL asks for (None: unreadable or not a list of strings)."""
    try:
        argv = json.loads(path.read_text(encoding="utf-8")).get("argv")
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv):
        return argv
    return None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _stop(child) -> None:
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def follow(control: Path) -> int:
    """Run view.py as CONTROL says until it quits on its own (see the docstring)."""
    alive = control.with_name(control.name + ".alive")
    child, seen, touched = None, None, 0.0
    for sig in (signal.SIGTERM, signal.SIGHUP):    # the split closed: unwind through finally
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        while True:
            now = time.monotonic()
            if now - touched >= ALIVE_S:
                alive.write_text(str(os.getpid()), encoding="utf-8")
                touched = now
            stamp = _mtime(control)
            if stamp != seen:
                seen = stamp
                argv = read_control(control)
                if argv is not None:
                    _stop(child)
                    child = subprocess.Popen([sys.executable, str(_TOOLS / "view.py"), *argv])
            if child is not None and child.poll() is not None:
                if child.returncode == 0:
                    return 0                # quit from its own keys: the split's done
                print(f"\nview.py stopped (status {child.returncode}); waiting for the "
                      "next request (ctrl-c closes this split)", flush=True)
                child = None
            time.sleep(FOLLOW_POLL_S)
    except KeyboardInterrupt:
        return 0
    finally:
        _stop(child)
        for path in (alive, control):
            try:
                path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _depth(text: str) -> int:
    return 99 if text == "all" else max(0, int(text))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The Claude Code mod's drawing and split helper.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw", help="a document's drawing as JSON for the mod's pane")
    d.add_argument("file", type=Path)
    d.add_argument("--view", choices=VIEWS, default="flow")
    d.add_argument("--depth", type=_depth, default=1)
    d.add_argument("--width", type=int, default=None)
    d.add_argument("--height", type=int, default=None)
    d.add_argument("--layout", choices=("auto", "wrap", "pan"), default="auto")
    d.add_argument("--scenario", default=None)
    d.add_argument("--payloads", action="store_true")
    d.add_argument("--theme", default=None)
    f = sub.add_parser("follow", help="run view.py live as a control file says")
    f.add_argument("control", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "follow":
        return follow(a.control)
    out = draw(a.file, a.view, a.depth, a.width, a.scenario, a.payloads, a.theme, a.layout,
               a.height)
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
