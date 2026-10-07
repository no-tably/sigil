"""
playground.py — the page's playground: the repo's own view.py, lint.py,
sim.py and check.py run in the browser by Pyodide. build_site.py copies this file, frames.py
and the tool modules verbatim into _site/py/; site.js writes them into one
directory of Pyodide's file system and calls the functions below, each taking
and returning JSON text. Nothing here re-implements the notation: it only asks
the tools for a drawing and packs it (frames.py) the way frames.json is packed.

    draw(request)    the document drawn in one view, its lint and its scenarios
    sim(request)     one frame of a scenario's run, drawn over the same view
    check(request)   the document's composition findings (check.py at k = 1)

A request: {"text", "view": "tree"|"graph"|"flow", "width": cols|null, "depth",
"payloads", "notes", "events"} (+ "scenario", "frame" for sim; "text" and
"mode" for check). Every drawing response carries "styles": the style table so far (ids are stable for the session, so
the page only adds the entries it has not seen).

Standard library only; runs under CPython too (tests/test_site.py drives it).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# the tools: beside this file in the browser (_site/py/), one up in the repo
_TOOLS = _HERE if (_HERE / "view.py").is_file() else _HERE.parent


def _load(name: str, path: Path):
    """A module by path (they are not a package)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


view = _load("sigil_view", _TOOLS / "view.py")
frames = _load("sigil_site_frames", _HERE / "frames.py")
checker = _load("sigil_check", _TOOLS / "check.py")
view.use_dialect(None)
view.use_theme(None)

MAX_DEPTH = 99
CHECK_K = 1                 # failure combinations per scenario: the RFC's playground k
STYLES = frames.Styles()
_player: dict = {}          # the run being shown: {"key": (text, scenario), "player"}


def _opts(req: dict) -> dict:
    name = view.view_name(req.get("view") or "tree")
    tree = name == "tree"
    events = req.get("events") or view.DEFAULT_EVENTS[name]
    width = req.get("width")
    return {"view": name, "tree": tree, "depth": int(req.get("depth", MAX_DEPTH)),
            "payloads": bool(req.get("payloads", True)),
            "notes": req.get("notes") or ("callouts" if tree else "markers"),
            "triggers": True, "spaced": True,
            "width": int(width) if width else None,
            "access": bool(req.get("access", False)), "mods": bool(req.get("mods", False)),
            "events": events}


def _graph(text: str):
    return view.render.parse_document(frames.autoclose(text.split("\n")))


def _rows(g, o: dict, trace=None, tick: int = 0) -> list:
    rows, _w = view.compose_view(g, o["view"], depth=o["depth"], payloads=o["payloads"],
                                 notes=o["notes"], triggers=o["triggers"],
                                 spaced=o["spaced"], width=o["width"], access=o["access"],
                                 mods=o["mods"], events=o["events"], trace=trace, tick=tick)
    return frames.pack_rows(rows, STYLES)


def _legend(o: dict, g, sim: bool) -> list:
    """The view's legend rows (the tree's key, the flow view's wires, the run's
    markers), wrapped."""
    rows = []
    if o["tree"]:
        rows += view.vtree.tree_legend(o["triggers"], o["payloads"], o["access"], o["mods"],
                                       o["events"],
                                       calls=view.drawn_call_marks(g, o["depth"], o["payloads"]))
    elif o["view"] == "flow":
        rows.append(view.vflow.flow_legend(o["triggers"], o["payloads"], o["access"], o["mods"],
                                           o["events"]))
    if sim:
        rows.append(view.sim_legend(o["tree"]))
    width = min(view.LEGEND_WIDTH, o["width"] or view.LEGEND_WIDTH)
    return frames.pack_rows([ln for r in rows for ln in view.wrap_legend(r, width)], STYLES)


def _scenarios(g) -> list:
    try:
        sc = view.simulator.scenarios(view.simulator.canonical(g))
    except Exception as exc:              # a half-typed document must not break the page
        return [{"name": "happy", "label": f"(no run: {type(exc).__name__})"}]
    return [{"name": s.name, "label": s.label or ""} for s in sc]


def draw(request: str) -> str:
    """{"rows", "legend", "lint": [{severity, line, rule, message}], "nodes",
    "edges", "scenarios": [{name, label}], "styles"}."""
    req = json.loads(request)
    text, o = req.get("text", ""), _opts(req)
    g = _graph(text)
    diags = view.run_lint(text)
    out = {"rows": _rows(g, o), "legend": _legend(o, g, False),
           "lint": [{"severity": d.severity, "line": d.line, "rule": d.rule,
                     "message": d.message} for d in diags],
           "nodes": len(g.nodes), "edges": len(g.edges),
           "scenarios": _scenarios(g), "styles": STYLES.table}
    return json.dumps(out, ensure_ascii=False)


def sim(request: str) -> str:
    """{"rows", "legend", "frame", "last", "tick", "ticks", "choice", "log": [lines so far, newest
    last], "say": the run in plain words at this frame (the latest beat,
    `tNNN …`; "" before any), "story": [the beats so far, newest last], "beats":
    [the frame of every beat, for stepping by event], "trail": the hops of the
    frame's episode so far, "outcome" (on the final frame), "styles"}; an
    unknown scenario: {"error"}. The wording is view.py's (sim.narrate) — the
    viewer's narration line, recent events and trail row say the same."""
    req = json.loads(request)
    text, o = req.get("text", ""), _opts(req)
    name = req.get("scenario") or "happy"
    key = (text, name)
    if _player.get("key") != key:
        g = _graph(text)
        try:
            player = view.SimPlayer(g, name)
        except view.UnknownScenario as exc:
            return json.dumps({"error": str(exc)})
        _player.update(key=key, player=player, graph=g)
    player, g = _player["player"], _player["graph"]
    player.at = max(0, min(int(req.get("frame", 0)), player.last))
    shown = player.shown(view.scene.SceneOptions(o["events"], o["triggers"], o["access"],
                                                 o["depth"]))
    log = [ln for f in player.trace.frames[:player.at + 1] for ln in f.log]
    out = {"rows": _rows(g, o, shown, player.at), "legend": _legend(o, g, True),
           "frame": player.at, "last": player.last,
           "tick": player.trace.frames[player.at].tick, "ticks": player.trace.frames[-1].tick,
           "choice": player.choice(), "log": log[-40:],
           "say": player.narration(),
           "story": [view.beat_line(b) for b in player.told()][-40:],
           "beats": [b.frame for b in player.beats], "trail": player.trail(),
           "outcome": player.trace.outcome if player.at == player.last else None,
           "styles": STYLES.table}
    return json.dumps(out, ensure_ascii=False)


def _finding(f) -> dict:
    """The fields the findings panel shows (check.py's --json record, trimmed)."""
    d = f.to_dict()
    return {key: d[key] for key in ("severity", "line", "rule", "name", "message", "tier",
                                    "why", "fix", "acknowledged")}


def check(request: str) -> str:
    """{"mode", "k", "findings": [{severity, line, rule, name, message, tier, why,
    fix}], "hidden": count, "acknowledged": [… + "acknowledged" (the reason)]};
    a document check.py cannot read: {"error"}. "mode" in the request overrides
    the document's mode line (null: the document's). Always k = CHECK_K with the
    trace module's run budget: the page bounds the time a check may take itself."""
    req = json.loads(request)
    text = frames.autoclose(req.get("text", "").split("\n"))
    try:
        report = checker.check(text, mode=req.get("mode") or None, k=CHECK_K)
    except ValueError as exc:                # an unknown mode
        return json.dumps({"error": str(exc)})
    except Exception as exc:                 # a half-typed document must not break the page
        return json.dumps({"error": f"no check: {type(exc).__name__}"})
    out = {"mode": report.mode, "k": report.k,
           "findings": [_finding(f) for f in report.shown],
           "hidden": len(report.findings) - len(report.shown),
           "acknowledged": [_finding(f) for f in report.acknowledged]}
    return json.dumps(out, ensure_ascii=False)
