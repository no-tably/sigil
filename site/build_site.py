#!/usr/bin/env python3
"""
build_site.py — assemble the Sigil web page into a static directory.

Usage:
    site/build_site.py [--out _site] [--logo coin]
    python3 -m http.server -d _site 8000          # preview

What it does:
    - copies site.css / site.js as they are, and index.html with its {{…}}
      placeholders filled (version, repository, logos) — a placeholder left
      unfilled fails the build;
    - copies themes/*.yaml and writes themes/index.yaml (the theme menu) and
      theme.css (the default theme as CSS variables, so the first paint is right
      before site.js loads the YAML);
    - renders every example in site/examples/ one line at a time through
      the viewer (sigil.present) — all four views (graph, tree, flow, and the run view's happy run)
      after each typed line, wrapped to PLANE_COLS — into frames.json, which the
      page's background planes play back in step with the typing; and the URL
      shortener's RUNS frame by frame in the run view, with their narration, for
      the run section. Only what a plane plays is stored. Colours are stored as
      theme roles (e.g. "kinds-service"), so the background follows a theme
      change like everything else;
    - copies the playground's Python into py/ — the repo's own sigil package,
      byte for byte, plus playground.py — for Pyodide to run in the browser
      (loaded only when the playground opens); the export layer stays out (the
      playground does not export).

--out is wiped and rebuilt, so it must be empty, missing, or a previous build
(frames.json or .nojekyll present), and never this directory or a parent of it.

Standard library only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
if str(ROOT) not in sys.path:          # the sigil package and build.py
    sys.path.insert(0, str(ROOT))

from build import package_files  # noqa: E402  (after the path is set)
from sigil.core.parse import parse_document  # noqa: E402
from sigil.model import scene  # noqa: E402
from sigil.present import app, kit, themes  # noqa: E402
from sigil.present.frames import Styles, autoclose, pack_rows  # noqa: E402

PAGE = "index.html"                  # the one file with {{placeholders}}
ASSETS = ["site.css", "site.js"]     # copied verbatim
PY_SITE = ["playground.py"]
PLACEHOLDER_REPO = "OWNER/sigil"
MAX_DEPTH = 99                       # expand every := block in the frames
PLANE_COLS = 72                      # the planes' frames wrap to this many columns
PLANE_VIEWS = ("graph", "tree", "flow", "run")   # a plane each, the viewer's VIEWS order
RUN_EXAMPLE = "shortener"            # the run section plays this example's RUNS
RUNS = (("happy", "happy"), ("Redirect.lookup:fails", "not found"))   # scenario, label
PLACEHOLDER_RE = re.compile(r"\{\{\w+\}\}")


class BuildError(Exception):
    """A build refused or failed for a reason worth one line on stderr."""


# The playground's Python, copied verbatim into py/ (manifest.json lists them):
# the package build.py ships, then playground.py — the browser runs these files,
# never a port of them. The export layer stays out: the playground draws, lints,
# checks and runs, it never exports (and check loads its export rules only for a
# check asked for export readiness). A path ending in / leaves out its folder.
NOT_IN_PLAYGROUND = frozenset({"sigil/publish/", "sigil/model/systems.py",
                               "sigil/analyse/rules/export.py"})


def in_playground(rel: str) -> bool:
    """Whether a package file (a path such as "sigil/core/lex.py") goes to py/."""
    return not any(rel == out or (out.endswith("/") and rel.startswith(out))
                   for out in NOT_IN_PLAYGROUND)


PY_TOOLS = [rel for rel in package_files(ROOT) if in_playground(rel)]


# ---------------------------------------------------------------------------
# Themes -> CSS
# ---------------------------------------------------------------------------

def css_var(section: str, key: str) -> str:
    """The CSS custom property for a theme entry: --section-key-with-dashes."""
    return f"--{section}-{key.replace('_', '-')}"


def theme_css(raw: dict) -> str:
    """CSS custom properties for a theme with $refs kept as var(--palette-…),
    so a role follows its palette colour. site.js does the same at runtime.
    Only section -> key -> string entries become variables; deeper maps are
    skipped (site.js skips them too). A value that could break out of its
    declaration (; { }) fails the build."""
    lines = [":root {"]
    if raw.get("type") in ("dark", "light"):
        lines.append(f"  color-scheme: {raw['type']};")
    for section, entries in raw.items():
        if not isinstance(entries, dict):
            continue
        for key, value in entries.items():
            if isinstance(value, dict):
                continue
            if not isinstance(value, str) or not re.fullmatch(r"[^;{}]+", value):
                raise BuildError(f"theme {section}.{key}: not a CSS value: {value!r}")
            if value.startswith("$"):
                value = f"var({css_var('palette', value[1:])})"
            lines.append(f"  {css_var(section, key)}: {value};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def theme_index(names: list[str]) -> str:
    """themes/index.yaml: the theme menu, name -> label."""
    out = ["# The theme menu (generated by build_site.py)", "themes:"]
    for n in names:
        label = themes.load_raw(n).get("label", n)
        out.append(f"  {n}: {json.dumps(label)}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Frames: each example rendered after every typed line
# ---------------------------------------------------------------------------

def title_of(lines: list[str], fallback: str) -> str:
    """The first `--- section ---` name in an example, else the fallback."""
    for ln in lines:
        m = re.match(r"^---\s*(.+?)\s*---$", ln.strip())
        if m:
            return m.group(1)
    return fallback


def example_paths() -> list[Path]:
    """site/examples/*.sigil in play order (the NN- prefix sorts them)."""
    return sorted((SITE / "examples").glob("*.sigil"))


def public_name(path: Path) -> str:
    """An example's file name on the page, without its NN- order prefix."""
    return re.sub(r"^\d+-", "", path.name)


def draw(g, name: str, player=None) -> list:
    """`g` drawn in view `name` as the planes show it: everything the viewer can
    show (payload chips; comments as callouts in the tree, ¶/# markers in the
    graph and flow views; the run view its own run notes, as `--run` draws it)
    wrapped to PLANE_COLS. `player`: a SimPlayer whose shown frame is drawn over
    it (the run view: that run's timeline at that frame)."""
    shown, tick = None, 0
    if player is not None:
        shown = player.shown(scene.SceneOptions(app.DEFAULT_EVENTS[name], True,
                                                False, MAX_DEPTH))
        tick = player.at
    rows, _w = app.compose_view(g, name, depth=MAX_DEPTH, payloads=True,
                                 notes={"tree": "callouts", "run": "off"}.get(name, "markers"),
                                triggers=True, spaced=True, width=PLANE_COLS,
                                access=False, mods=False, events=app.DEFAULT_EVENTS[name],
                                trace=shown, tick=tick)
    return rows


def intern(rows, styles: Styles, frames: list, seen: dict) -> int:
    """The index of `rows` packed in `frames`, appending it when new (seen:
    json -> index, so an unchanged drawing is stored once)."""
    packed = pack_rows(rows, styles)
    key = json.dumps(packed, ensure_ascii=False)
    if key not in seen:
        seen[key] = len(frames)
        frames.append(packed)
    return seen[key]


def happy_player(g):
    """The happy run of `g` at its final frame (a SimPlayer)."""
    player = app.SimPlayer(g, "happy")
    player.at = player.last
    return player


def render_example(path: Path, styles: Styles, frames: list, seen: dict) -> dict:
    """One example's typing steps: a frame per plane (PLANE_VIEWS; the run
    plane the happy run's last frame) after each typed line. Mutates styles,
    frames and seen (see intern). A crash in the viewer or the simulator fails
    the build — the parser is tolerant, so a crash here is a real bug, not a
    half-typed line."""
    lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    steps = []
    for k in range(1, len(lines) + 1):
        text = autoclose(lines[:k])
        g = parse_document(text)
        ids = {name: intern(draw(g, name, happy_player(g) if name == "run" else None),
                            styles, frames, seen) for name in PLANE_VIEWS}
        diags = kit.run_lint(text)
        n_err = sum(d.severity == "error" for d in diags)
        n_warn = sum(d.severity == "warn" for d in diags)
        steps.append({"line": k - 1, **ids,
                      "nodes": len(g.nodes), "edges": len(g.edges),
                      "lint": "OK" if not (n_err or n_warn) else f"{n_err}E {n_warn}W"})
    name = public_name(path)
    stem = name.removesuffix(".sigil")
    return {"id": stem, "title": title_of(lines, stem), "file": name,
            "lines": lines, "steps": steps}


def render_runs(path: Path, styles: Styles, frames: list, seen: dict) -> list:
    """The run section's runs (RUNS) of one example, frame by frame in the run
    view, each frame with the viewer's narration line (SimPlayer.narration)."""
    g = parse_document(path.read_text(encoding="utf-8"))
    out = []
    for scenario, label in RUNS:
        player = app.SimPlayer(g, scenario)
        seq = []
        for at in range(player.last + 1):
            player.at = at
            seq.append({"run": intern(draw(g, "run", player), styles, frames, seen),
                        "say": player.narration()})
        out.append({"scenario": scenario, "label": label,
                    "outcome": str(player.trace.outcome), "frames": seq})
    return out


def build_frames() -> dict:
    """frames.json: the style table, the deduplicated frames, every example's
    steps, the example the view sections show, and its runs."""
    kit.use_dialect(None)
    kit.use_theme(themes.DEFAULT)
    styles, frames, seen = Styles(), [], {}
    paths = example_paths()
    examples = [render_example(p, styles, frames, seen) for p in paths]
    shown = next((p for p in paths if public_name(p) == f"{RUN_EXAMPLE}.sigil"), None)
    if shown is None:
        raise BuildError(f"no {RUN_EXAMPLE}.sigil in site/examples/ for the run section")
    runs = render_runs(shown, styles, frames, seen)
    return {"styles": styles.table, "frames": frames, "examples": examples,
            "views": RUN_EXAMPLE, "runs": runs}


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def repo_slug(meta: dict) -> str:
    """owner/name from meta.json's GitHub repository URL, else the placeholder."""
    url = meta.get("repository", "")
    m = re.match(r"https?://github\.com/([\w.-]+/[\w.-]+?)(\.git)?/?$", url)
    return m.group(1) if m else PLACEHOLDER_REPO


def logo_templates() -> str:
    """A <template> per site/logos/*.txt, plus one for its optional .mask (one
    colour code per cell: "a" accent, digits and letters for the coin shades)."""
    out = []
    for p in sorted((SITE / "logos").glob("*.txt")):
        name = html.escape(p.stem)
        art = html.escape(p.read_text(encoding="utf-8").rstrip("\n"))
        out.append(f'<template data-logo="{name}">{art}</template>')
        mask = p.with_suffix(".mask")
        if mask.is_file():
            cells = html.escape(mask.read_text(encoding="utf-8").rstrip("\n"))
            out.append(f'<template data-logo-mask="{name}">{cells}</template>')
    return "\n".join(out)


def check_out(out: Path) -> Path:
    """The resolved --out, refusing anything that is not safe to wipe: this
    directory or a parent of it, a file, or a non-empty directory that is not a
    previous build."""
    out = out.expanduser().resolve()
    for keep in (ROOT, SITE):
        if out == keep or out in keep.parents:
            raise BuildError(f"refusing --out {out}: it contains the sources")
    if out.exists():
        if not out.is_dir():
            raise BuildError(f"refusing --out {out}: not a directory")
        previous = (out / "frames.json").is_file() or (out / ".nojekyll").is_file()
        if any(out.iterdir()) and not previous:
            raise BuildError(f"refusing --out {out}: not empty and not a previous build")
    return out


def fill(text: str, subst: dict[str, str]) -> str:
    """Fill {{name}} placeholders; one left over fails the build."""
    for k, v in subst.items():
        text = text.replace(k, v)
    left = sorted(set(PLACEHOLDER_RE.findall(text)))
    if left:
        raise BuildError(f"{PAGE}: unfilled placeholders {', '.join(left)}")
    return text


def build(out: Path, logo: str) -> None:
    """Write the page into out (wiped first; see check_out)."""
    out = check_out(out)
    meta = json.loads((ROOT / "plugin" / "meta.json").read_text(encoding="utf-8"))
    slug = repo_slug(meta)
    subst = {
        "{{version}}": html.escape(meta["version"]),
        "{{repo}}": html.escape(slug),
        "{{repo_url}}": html.escape(f"https://github.com/{slug}"),
        "{{released}}": "false" if slug == PLACEHOLDER_REPO else "true",
        "{{logo}}": html.escape(logo),
        "{{logos}}": logo_templates(),
    }
    page = fill((SITE / PAGE).read_text(encoding="utf-8"), subst)
    frames = build_frames()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / PAGE).write_text(page, encoding="utf-8")
    for name in ASSETS:
        shutil.copyfile(SITE / name, out / name)
    (out / "themes").mkdir()
    names = themes.names()
    for n in names:
        shutil.copyfile(themes.find(n), out / "themes" / f"{n}.yaml")
    (out / "themes" / "index.yaml").write_text(theme_index(names), encoding="utf-8")
    (out / "theme.css").write_text(theme_css(themes.load_raw(themes.DEFAULT)), encoding="utf-8")
    shutil.copytree(SITE / "fonts", out / "fonts")
    (out / "examples").mkdir()
    for p in example_paths():
        shutil.copyfile(p, out / "examples" / public_name(p))
    (out / "py").mkdir()
    for rel in PY_TOOLS:
        (out / "py" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, out / "py" / rel)
    for name in PY_SITE:
        shutil.copyfile(SITE / name, out / "py" / name)
    (out / "py" / "manifest.json").write_text(
        json.dumps({"files": PY_TOOLS + PY_SITE, "themes": [f"{n}.yaml" for n in names]}),
        encoding="utf-8")
    (out / "frames.json").write_text(
        json.dumps(frames, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Sigil web page.")
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    ap.add_argument("--logo", default="coin", help="hero logo: a name in site/logos/")
    args = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+", args.logo) or not (SITE / "logos" / f"{args.logo}.txt").is_file():
        print(f"build_site.py: no logo {args.logo!r} in site/logos/", file=sys.stderr)
        return 2
    try:
        build(args.out, args.logo)
    except BuildError as exc:
        print(f"build_site.py: {exc}", file=sys.stderr)
        return 2
    out = args.out.expanduser().resolve()
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"site: {out} ({size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
