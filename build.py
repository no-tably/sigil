#!/usr/bin/env python3
"""
build.py — package Sigil as a plugin / skill bundle for several coding agents.

Usage:
    build.py [--out dist] [--target claude|codex|pi|opencode|all] [--version X.Y.Z]
    build.py --check [--out dist] [--target ...]

Canonical sources (edit these, never dist/):
    skills/sigil/SKILL.md      the skill (spec-only frontmatter, relative paths)
    plugin/meta.json           name, version, description, author, keywords, urls
    plugin/commands/*.md       slash commands; bodies use $1 / $ARGUMENTS and the
                               placeholder @SCRIPTS@ for the skill's scripts dir
    plugin/claude/             the Claude Code viewer mod: its manifest's types and
                               userConfig (merged into the claude plugin.json),
                               hooks/ and types/ (copied), scripts/pane.py and
                               site/frames.py (into the skill's scripts/); its
                               tests/ and tsconfig.json stay here
    plugin/pi/                 the pi viewer extension: extensions/sigil/index.ts,
                               with the mod's hooks/logic.ts beside it and pane.py
                               and frames.py in the skill's scripts/
    lint.py render.py view.py  copied into skills/sigil/scripts/ (required)
    viewkit.py view_graph.py   view.py's drawing modules, the scene layer and
    view_tree.py view_flow.py  the simulation engine, copied alongside (required)
    view_run.py scene.py
    sim.py check.py            check.py: the composition checker, and its rule
    check_state.py             modules beside it (required)
    check_trace.py check_flow.py
    check_inv.py
    dialects.py themes.py      copied alongside when present (optional)
    themes/*.yaml              copied into skills/sigil/scripts/themes/
    language.md examples.md    copied into skills/sigil/references/

Outputs (under --out, default ./dist):
    claude/                    Claude Code plugin (.claude-plugin/plugin.json), with
                               the viewer mod (hooks/hooks.json)
    claude-marketplace/        marketplace repo layout -> ./plugins/sigil
    codex/                     Agent Plugins 1.0 plugin (root plugin.json);
                               commands become skills that opt out of implicit use
    codex-marketplace/         .agents/plugins/marketplace.json -> ./plugins/sigil
    pi/                        pi package (package.json "pi" key, prompts/), with
                               the viewer extension (extensions/sigil/)
    opencode/                  config tree + install.sh (skills/, commands/)
    sigil-<tree>-<version>.zip and .tar.gz   both archives for every tree above,
                               e.g. sigil-claude-marketplace-<version>.zip

Archives are deterministic: sorted entries, fixed timestamps and ownership,
mode 0755 for directories and executable files, 0644 for everything else.
--version must look like X.Y.Z (optionally -pre / +build; a leading v is stripped).

--check validates an existing --out tree (manifests, frontmatter, paths,
executable scripts, both archives per tree) and exits 1 on any problem.
Standard library only.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# Every shipped module, here only: the plugin bundles them and site/build_site.py
# copies the same list into the playground (tests/test_build.py: every top-level
# module but this one is listed).
TOOLS = ["lint.py", "render.py", "view.py", "viewkit.py", "view_graph.py", "view_tree.py",
         "view_flow.py", "view_run.py", "scene.py", "sim.py", "check.py", "check_state.py", "check_trace.py", "check_flow.py",
         "check_inv.py", "dialects.py", "themes.py"]
REQUIRED_TOOLS = {"lint.py", "render.py", "view.py", "viewkit.py", "view_graph.py",
                  "view_tree.py", "view_flow.py", "view_run.py", "scene.py", "sim.py", "check.py", "check_state.py",
                  "check_trace.py", "check_flow.py", "check_inv.py"}
REFERENCES = ["language.md", "examples.md"]
TARGETS = ["claude", "codex", "pi", "opencode"]
SKILL = "sigil"

# Agent Skills spec (agentskills.io)
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SKILL_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Agent Plugins 1.0.0 (Codex)
CODEX_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
CODEX_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
CODEX_KEYS = {"$schema", "name", "version", "description", "author", "homepage",
              "repository", "license", "keywords", "extensions"}
# Manifest fields shared by the targets, in output order.
MANIFEST_ORDER = ("name", "version", "description", "author", "homepage", "repository",
                  "license", "keywords")
CLAUDE_KEYS = set(MANIFEST_ORDER)
# The Claude Code viewer mod (plugin/claude): the manifest fields it adds, the
# folders copied whole, and its Python, which goes beside the skill's tools.
MOD = ROOT / "plugin" / "claude"
MOD_KEYS = ("types", "userConfig")
MOD_DIRS = ("hooks", "types")
MOD_SCRIPTS = {"pane.py": MOD / "scripts" / "pane.py", "frames.py": ROOT / "site" / "frames.py"}
# The pi viewer extension (plugin/pi): its published files and their sources. It
# shares the Claude Code mod's pure half, and imports nothing but node: builtins
# and these files, so it loads in any pi with extensions.
PI_EXT = "extensions/sigil/index.ts"
PI_FILES = {PI_EXT: ROOT / "plugin" / "pi" / "extensions" / "sigil" / "index.ts",
            "extensions/sigil/logic.ts": MOD / "hooks" / "logic.ts"}
PI_IMPORT_RE = re.compile(r"^\s*(?:import|export)\b[^'\"]*?\bfrom\s+['\"]([^'\"]+)['\"]", re.M)
# Where each target records its version (opencode has no manifest).
VERSION_FILES = {"claude": ".claude-plugin/plugin.json", "codex": "plugin.json",
                 "pi": "package.json"}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
ARCHIVE_EXTS = (".zip", ".tar.gz")

# A path segment `scripts/` or `references/` that is not already part of a longer path.
REL_PATH_RE = re.compile(r"(?<![\w./${}-])(scripts|references)/")
ABS_LEAK_RE = re.compile(r"(/home/[\w.-]+|/Users/[\w.-]+|/tmp/claude|[A-Z]:\\Users)")

EPOCH_ZIP = (1980, 1, 1, 0, 0, 0)
PORTABLE_SCRIPTS = "<sigil-skill-dir>/scripts"
# install.sh deletes the note line by this prefix (a literal in a sed BRE).
SIGIL_DIR_NOTE_PREFIX = "(`<sigil-skill-dir>`"
SIGIL_DIR_NOTE = (SIGIL_DIR_NOTE_PREFIX + " is the directory containing the sigil "
                  "skill's SKILL.md.)")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse a flat `key: value` YAML frontmatter block. Returns (fields, body).

    Unquoted true/false become bools; every other value is a string."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.find("\n---\n", 3)      # from 3 so an empty block is accepted
    if end < 0:
        raise ValueError("unterminated frontmatter")
    fields: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line or line[0].isspace():
            raise ValueError(f"unsupported frontmatter line: {line!r}")
        key, _, val = line.partition(":")
        val = val.strip()
        if val.startswith('"'):
            val = json.loads(val)
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1].replace("''", "'")
        elif val in ("true", "false"):
            val = val == "true"
        fields[key.strip()] = val
    return fields, text[end + 5:]


def emit_frontmatter(fields: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {json.dumps(str(v), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)


def write_json(path: Path, data: Any) -> None:
    write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def is_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _is_exec(p: Path) -> bool:
    """Any execute bit in the mode (not os.access: that varies with mounts/ACLs)."""
    return bool(p.stat().st_mode & 0o111)


def normalize_version(version: str) -> str:
    """Strip a leading v; raise ValueError unless the rest is X.Y.Z[-pre][+build]."""
    v = version[1:] if version.startswith("v") else version
    if not VERSION_RE.match(v):
        raise ValueError(f"invalid version {version!r} (expected X.Y.Z)")
    return v


def load_meta(version: str | None = None) -> dict[str, Any]:
    meta = json.loads((ROOT / "plugin" / "meta.json").read_text(encoding="utf-8"))
    meta["version"] = normalize_version(version or meta["version"])
    return meta


def base_manifest(meta: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    """Manifest fields shared by targets; homepage/repository only when a URL."""
    out = {}
    for k in MANIFEST_ORDER:
        if k not in keys or k not in meta:
            continue
        if k in ("homepage", "repository") and not is_url(meta[k]):
            continue
        out[k] = meta[k]
    return out


def load_commands() -> list[tuple[str, dict[str, Any], str]]:
    cmds = []
    for p in sorted((ROOT / "plugin" / "commands").glob("*.md")):
        fields, body = parse_frontmatter(p.read_text(encoding="utf-8"))
        cmds.append((p.stem, fields, body))
    return cmds


# ---------------------------------------------------------------------------
# Skill staging
# ---------------------------------------------------------------------------

def stage_skill(dest: Path, claude: bool = False) -> None:
    """Assemble skills/sigil into dest: SKILL.md + scripts/ + references/."""
    src = ROOT / "skills" / SKILL
    fields, body = parse_frontmatter((src / "SKILL.md").read_text(encoding="utf-8"))
    if claude:
        body = REL_PATH_RE.sub(r"${CLAUDE_SKILL_DIR}/\1/", body)
    write(dest / "SKILL.md", emit_frontmatter(fields, body))
    # Any extra canonical files (besides generated scripts/ and references/)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        generated = rel.parts[0] in ("scripts", "references")
        if p.is_dir() or rel.name == "SKILL.md" or generated or "__pycache__" in rel.parts:
            continue
        write(dest / rel, p.read_text(encoding="utf-8"), _is_exec(p))
    for name in TOOLS:
        p = ROOT / name
        if p.exists():
            write(dest / "scripts" / name, p.read_text(encoding="utf-8"), executable=True)
        elif name in REQUIRED_TOOLS:
            raise FileNotFoundError(f"required tool missing: {p}")
    for p in sorted((ROOT / "themes").glob("*.yaml")):
        write(dest / "scripts" / "themes" / p.name, p.read_text(encoding="utf-8"))
    for name in REFERENCES:
        write(dest / "references" / name, (ROOT / name).read_text(encoding="utf-8"))


def render_command(body: str, scripts: str) -> str:
    return body.replace("@SCRIPTS@", scripts)


def write_commands(dest: Path, scripts: str, keep: set[str] | None = None,
                   note: bool = False) -> None:
    """Render plugin/commands/*.md into dest, keeping only `keep` frontmatter keys
    (all when None) and appending SIGIL_DIR_NOTE when `note`."""
    for name, fields, body in load_commands():
        if keep is not None:
            fields = {k: v for k, v in fields.items() if k in keep}
        text = render_command(body, scripts)
        if note:
            text += "\n" + SIGIL_DIR_NOTE + "\n"
        write(dest / f"{name}.md", emit_frontmatter(fields, text))


def copy_into_marketplace(root: Path, market: Path, meta: dict[str, Any]) -> str:
    """Copy a built plugin to market/plugins/<name>; returns the ./ source path."""
    shutil.copytree(root, market / "plugins" / meta["name"])
    return f"./plugins/{meta['name']}"


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

def load_mod_manifest() -> dict[str, Any]:
    """plugin/claude's own plugin.json (the fields it adds to the claude manifest);
    its name must be the plugin's, since its state and tool are named by it."""
    return json.loads((MOD / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))


def stage_mod(root: Path, meta: dict) -> dict[str, Any]:
    """Copy the viewer mod into a built claude plugin; returns its manifest fields."""
    mod = load_mod_manifest()
    if mod.get("name") != meta["name"]:
        raise ValueError(f"plugin/claude: name {mod.get('name')!r} != {meta['name']!r}")
    for d in MOD_DIRS:
        for p in sorted((MOD / d).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                write(root / p.relative_to(MOD), p.read_text(encoding="utf-8"))
    for name, src in MOD_SCRIPTS.items():
        write(root / "skills" / SKILL / "scripts" / name, src.read_text(encoding="utf-8"),
              executable=True)
    return {k: mod[k] for k in MOD_KEYS if k in mod}


def build_claude(out: Path, meta: dict) -> list[Path]:
    root = out / "claude"
    manifest = base_manifest(meta, CLAUDE_KEYS)
    stage_skill(root / "skills" / SKILL, claude=True)
    manifest.update(stage_mod(root, meta))
    write_json(root / ".claude-plugin" / "plugin.json", manifest)
    write_commands(root / "commands", f"${{CLAUDE_PLUGIN_ROOT}}/skills/{SKILL}/scripts")

    market = out / "claude-marketplace"
    source = copy_into_marketplace(root, market, meta)
    entry = {"name": meta["name"], "source": source,
             "description": meta["description"], "version": meta["version"]}
    write_json(market / ".claude-plugin" / "marketplace.json", {
        "name": meta["name"],
        "owner": {"name": meta["author"]["name"]},
        "metadata": {"description": meta["description"], "version": meta["version"]},
        "plugins": [entry],
    })
    return [root, market]


def build_codex(out: Path, meta: dict) -> list[Path]:
    root = out / "codex"
    manifest = {"$schema": CODEX_SCHEMA, **base_manifest(meta, CODEX_KEYS)}
    write_json(root / "plugin.json", manifest)
    stage_skill(root / "skills" / SKILL)
    for name, fields, body in load_commands():
        # Custom prompts are deprecated in Codex: ship each command as an
        # explicit-only skill. Skills get no argument substitution, and commands
        # run from the user's project, so scripts are named via <sigil-skill-dir>.
        text = render_command(body, PORTABLE_SCRIPTS)
        text = re.sub(r"\$1(?!\d)", "FILE", text.replace("$ARGUMENTS", "FILE [OPTIONS]"))
        intro = ("Invoked explicitly by the user. FILE is the Sigil document they "
                 "named; OPTIONS are any extra flags they gave.\n")
        note = (f"\n{SIGIL_DIR_NOTE} In this plugin that is the sibling `{SKILL}` "
                f"skill: the scripts are `../{SKILL}/scripts/` relative to this "
                "SKILL.md's directory, not the working directory.\n")
        desc = fields.get("description", name)
        if "argument-hint" in fields:
            # `$name` is how a user mentions (invokes) a skill in Codex.
            desc = f"{desc} (usage: ${name} {fields['argument-hint']})"
        write(root / "skills" / name / "SKILL.md",
              emit_frontmatter({"name": name, "description": desc},
                               "\n" + intro + text + note))
        write(root / "skills" / name / "agents" / "openai.yaml",
              "policy:\n  allow_implicit_invocation: false\n")

    market = out / "codex-marketplace"
    source = copy_into_marketplace(root, market, meta)
    write_json(market / ".agents" / "plugins" / "marketplace.json", {
        "name": meta["name"],
        "interface": {"displayName": "Sigil"},
        "plugins": [{
            "name": meta["name"],
            "source": {"source": "local", "path": source},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Developer Tools",
        }],
    })
    return [root, market]


def build_pi(out: Path, meta: dict) -> list[Path]:
    root = out / "pi"
    pkg = {
        "name": meta["name"],
        "version": meta["version"],
        "description": meta["description"],
        "author": meta["author"]["name"],
        "keywords": sorted(set(meta.get("keywords", [])) | {"pi-package"}),
        "type": "module",
        "files": ["extensions", "skills", "prompts", "README.md"],
        "pi": {"extensions": [f"./{PI_EXT}"], "skills": ["./skills"],
               "prompts": ["./prompts/*.md"]},
    }
    for k in ("homepage", "repository"):
        if is_url(meta.get(k)):
            pkg[k] = meta[k]
    write_json(root / "package.json", pkg)
    stage_skill(root / "skills" / SKILL)
    for rel, src in PI_FILES.items():
        write(root / rel, src.read_text(encoding="utf-8"))
    for name, src in MOD_SCRIPTS.items():
        write(root / "skills" / SKILL / "scripts" / name, src.read_text(encoding="utf-8"),
              executable=True)
    write_commands(root / "prompts", PORTABLE_SCRIPTS, note=True)
    prompts = ", ".join(f"`/{name}`" for name, _, _ in load_commands())
    write(root / "README.md", f"# {meta['name']} (pi package)\n\n{meta['description']}\n\n"
          "Install: `pi install ./` from this directory (add `-l` for project-local).\n"
          f"Provides the `{SKILL}` skill, the prompts {prompts}, and a viewer: the\n"
          "agent's `sigil_view` tool and the `/sigil-pane` command show a design live, in a\n"
          "widget above the editor or in a herdr / tmux / zellij split.\n"
          "`/sigil-pane display auto|mod|multiplex` picks which (saved in\n"
          "~/.config/sigil/viewer.json; `--sigil-display` or `SIGIL_DISPLAY` wins for a\n"
          "session); auto takes the split inside a multiplexer.\n")
    return [root]


OPENCODE_INSTALL = r"""#!/bin/sh
# Install the Sigil skill and commands for OpenCode.
#   ./install.sh                 -> $OPENCODE_CONFIG_DIR if set, else
#                                   ${XDG_CONFIG_HOME:-~/.config}/opencode
#   ./install.sh --project DIR   -> DIR/.opencode (DIR must exist)
# Commands are rewritten to the absolute path of the installed skill, so an
# installed .opencode/ is tied to this machine: re-run after moving it.
set -eu
usage() {
  echo "usage: install.sh [--project DIR]"
  echo "  (no args)      install into \$OPENCODE_CONFIG_DIR if set,"
  echo "                 else \${XDG_CONFIG_HOME:-~/.config}/opencode"
  echo "  --project DIR  install into DIR/.opencode"
}
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "${1:-}" in
  --project)
    [ $# -eq 2 ] || { usage >&2; exit 2; }
    dest="$(CDPATH= cd -- "$2" && pwd)/.opencode" ;;
  -h|--help) usage; exit 0 ;;
  "")
    [ $# -eq 0 ] || { usage >&2; exit 2; }
    dest="${OPENCODE_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}" ;;
  *) usage >&2; exit 2 ;;
esac
mkdir -p "$dest/skills" "$dest/commands"
rm -rf "$dest/skills/sigil"
cp -R "$here/skills/sigil" "$dest/skills/sigil"
chmod 755 "$dest/skills/sigil/scripts/"*.py
skill_dir="$dest/skills/sigil"
# Escape \ | & for the sed replacement below.
skill_sed=$(printf '%s\n' "$skill_dir" | sed -e 's/[\\|&]/\\&/g')
for f in "$here/commands/"*.md; do
  sed -e '/^@NOTE_PREFIX@/d' -e "s|<sigil-skill-dir>|$skill_sed|g" "$f" \
    > "$dest/commands/$(basename "$f")"
done
echo "sigil installed into $dest"
""".replace("@NOTE_PREFIX@", SIGIL_DIR_NOTE_PREFIX)


def build_opencode(out: Path, meta: dict) -> list[Path]:
    root = out / "opencode"
    stage_skill(root / "skills" / SKILL)
    # OpenCode command frontmatter: description (agent/model/subtask optional).
    write_commands(root / "commands", PORTABLE_SCRIPTS, keep={"description"}, note=True)
    write(root / "install.sh", OPENCODE_INSTALL, executable=True)
    return [root]


BUILDERS = {"claude": build_claude, "codex": build_codex, "pi": build_pi,
            "opencode": build_opencode}


# ---------------------------------------------------------------------------
# Archives
# ---------------------------------------------------------------------------

def _entries(tree: Path) -> list[Path]:
    # Sorted by archive name: a directory sorts as "name/", after "name.py".
    return sorted(tree.rglob("*"),
                  key=lambda p: p.relative_to(tree).as_posix() + ("/" if p.is_dir() else ""))


def _mode(p: Path) -> int:
    if p.is_dir():
        return 0o755
    return 0o755 if _is_exec(p) else 0o644


def make_archives(tree: Path, stem: str) -> list[Path]:
    out = tree.parent
    zpath, tpath = out / f"{stem}.zip", out / f"{stem}.tar.gz"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in _entries(tree):
            arc = f"{stem}/{p.relative_to(tree).as_posix()}"
            info = zipfile.ZipInfo(arc + ("/" if p.is_dir() else ""), EPOCH_ZIP)
            info.create_system = 3
            info.external_attr = ((stat.S_IFDIR if p.is_dir() else stat.S_IFREG)
                                  | _mode(p)) << 16
            if p.is_dir():
                z.writestr(info, b"")
            else:
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, p.read_bytes())
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as t:
        for p in _entries(tree):
            info = tarfile.TarInfo(f"{stem}/{p.relative_to(tree).as_posix()}")
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            info.mode = _mode(p)
            if p.is_dir():
                info.type = tarfile.DIRTYPE
                t.addfile(info)
            else:
                data = p.read_bytes()
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    with open(tpath, "wb") as f, gzip.GzipFile(filename="", mode="wb", fileobj=f,
                                               mtime=0) as gz:
        gz.write(buf.getvalue())
    return [zpath, tpath]


def build(out: Path, targets: list[str], version: str | None = None) -> list[Path]:
    meta = load_meta(version)
    out.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for target in targets:
        for sub in (target, f"{target}-marketplace"):
            if (out / sub).exists():
                shutil.rmtree(out / sub)
        for old in out.glob(f"sigil-{target}-*"):
            old.unlink()
        for tree in BUILDERS[target](out, meta):
            made.append(tree)
            made += make_archives(tree, f"sigil-{tree.name}-{meta['version']}")
    return made


# ---------------------------------------------------------------------------
# Validation (--check)
# ---------------------------------------------------------------------------

def _load_json(path: Path, errs: list[str]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errs.append(f"{path}: missing")
    except (OSError, UnicodeDecodeError) as e:
        errs.append(f"{path}: unreadable: {e}")
    except json.JSONDecodeError as e:
        errs.append(f"{path}: invalid JSON: {e}")
    return None


def _load_obj(path: Path, errs: list[str]) -> dict[str, Any]:
    """_load_json, but a non-object counts as an error and yields {}."""
    data = _load_json(path, errs)
    if data is not None and not isinstance(data, dict):
        errs.append(f"{path}: expected a JSON object")
    return data if isinstance(data, dict) else {}


def _read_frontmatter(path: Path, errs: list[str]) -> tuple[dict[str, Any], str] | None:
    """parse_frontmatter on a file; problems become errors, not exceptions."""
    try:
        return parse_frontmatter(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errs.append(f"{path}: missing")
    except (OSError, ValueError) as e:     # ValueError covers UnicodeDecodeError
        errs.append(f"{path}: {e}")
    return None


def check_skill(skill_dir: Path, errs: list[str]) -> None:
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        errs.append(f"{md}: missing")
        return
    fm = _read_frontmatter(md, errs)
    if fm is None:
        return
    fields = fm[0]
    name, desc = fields.get("name", ""), fields.get("description", "")
    if not (isinstance(name, str) and 1 <= len(name) <= 64 and SKILL_NAME_RE.match(name)):
        errs.append(f"{md}: bad skill name {name!r}")
    if name != skill_dir.name:
        errs.append(f"{md}: name {name!r} != directory {skill_dir.name!r}")
    if not (isinstance(desc, str) and 1 <= len(desc) <= 1024):
        errs.append(f"{md}: description must be a string of 1..1024 characters")
    for k in set(fields) - SKILL_KEYS:
        errs.append(f"{md}: frontmatter key {k!r} not in the Agent Skills spec")
    scripts = skill_dir / "scripts"
    if scripts.is_dir():
        for p in scripts.iterdir():
            if p.suffix == ".py" and not _is_exec(p):
                errs.append(f"{p}: not executable")


def check_sigil_skill(skill_dir: Path, errs: list[str]) -> None:
    check_skill(skill_dir, errs)
    for name in REQUIRED_TOOLS:
        if not (skill_dir / "scripts" / name).is_file():
            errs.append(f"{skill_dir}/scripts/{name}: missing")
    if not (skill_dir / "scripts" / "themes" / "sigil.yaml").is_file():
        errs.append(f"{skill_dir}/scripts/themes/sigil.yaml: missing")
    for name in REFERENCES:
        if not (skill_dir / "references" / name).is_file():
            errs.append(f"{skill_dir}/references/{name}: missing")


def check_tree_text(tree: Path, errs: list[str]) -> None:
    for p in _entries(tree):
        if p.is_file() and p.suffix in (".md", ".json", ".yaml", ".sh"):
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                errs.append(f"{p}: unreadable: {e}")
                continue
            if "@SCRIPTS@" in text:
                errs.append(f"{p}: unreplaced @SCRIPTS@ placeholder")
            m = ABS_LEAK_RE.search(text)
            if m:
                errs.append(f"{p}: absolute path leaked: {m.group(0)}")
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            errs.append(f"{p}: build junk")


def check_commands(cmd_dir: Path, errs: list[str], needle: str,
                   keys: set[str] | None = None, note: bool = False) -> None:
    """Every command has a description (exactly `keys` when given), addresses the
    scripts via `needle`, and carries SIGIL_DIR_NOTE when `note`."""
    cmds = sorted(cmd_dir.glob("*.md"))
    if not cmds:
        errs.append(f"{cmd_dir}: no commands")
    for c in cmds:
        fm = _read_frontmatter(c, errs)
        if fm is None:
            continue
        fields, body = fm
        if "description" not in fields:
            errs.append(f"{c}: missing description")
        if keys is not None and set(fields) != keys:
            errs.append(f"{c}: frontmatter should carry only {', '.join(sorted(keys))}")
        if needle not in body:
            errs.append(f"{c}: scripts not addressed via {needle}")
        if note and SIGIL_DIR_NOTE not in body:
            errs.append(f"{c}: missing the <sigil-skill-dir> note")


def check_claude(out: Path, errs: list[str]) -> None:
    root = out / "claude"
    man = _load_obj(root / ".claude-plugin" / "plugin.json", errs)
    if not SKILL_NAME_RE.match(str(man.get("name", ""))):
        errs.append(f"{root}: plugin.json name must be kebab-case")
    for k in set(man) - CLAUDE_KEYS - set(MOD_KEYS):
        errs.append(f"{root}: plugin.json has unexpected key {k!r}")
    skill = root / "skills" / SKILL
    check_sigil_skill(skill, errs)
    check_mod(root, man, errs)
    fm = _read_frontmatter(skill / "SKILL.md", []) if (skill / "SKILL.md").is_file() else None
    body = fm[1] if fm else ""
    if "${CLAUDE_SKILL_DIR}/scripts/" not in body:
        errs.append(f"{skill}/SKILL.md: scripts not addressed via ${{CLAUDE_SKILL_DIR}}")
    if REL_PATH_RE.search(body):
        errs.append(f"{skill}/SKILL.md: bare relative scripts/ or references/ path remains")
    check_commands(root / "commands", errs, f"${{CLAUDE_PLUGIN_ROOT}}/skills/{SKILL}/scripts/")
    market = out / "claude-marketplace"
    mk = _load_obj(market / ".claude-plugin" / "marketplace.json", errs)
    owner = mk.get("owner")
    if not mk.get("name") or not (isinstance(owner, dict) and owner.get("name")):
        errs.append(f"{market}: marketplace.json needs name and owner.name")
    for pl in mk.get("plugins", []):
        source = pl.get("source") if isinstance(pl, dict) else None
        if not (isinstance(source, str)
                and (market / source / ".claude-plugin" / "plugin.json").is_file()):
            errs.append(f"{market}: plugin source {source!r} has no plugin.json")
    check_tree_text(root, errs)
    check_tree_text(market, errs)


def check_mod(root: Path, man: dict[str, Any], errs: list[str]) -> None:
    """The viewer mod: hooks.json names modules that are there, the types file the
    manifest names is there, `display` offers its three values, and pane.py and
    frames.py sit beside the skill's tools."""
    hooks = root / "hooks" / "hooks.json"
    mods = _load_obj(hooks, errs).get("modules")
    if not (isinstance(mods, list) and mods):
        errs.append(f"{hooks}: no modules")
        mods = []
    for m in mods:
        if not (isinstance(m, str) and (hooks.parent / m).is_file()):
            errs.append(f"{hooks}: module {m!r} missing")
    types = man.get("types")
    if not (isinstance(types, str) and (root / types).is_file()):
        errs.append(f"{root}: plugin.json types {types!r} missing")
    display = (man.get("userConfig") or {}).get("display")
    if not (isinstance(display, dict) and display.get("options") == ["auto", "mod", "multiplex"]
            and display.get("default") == "auto"):
        errs.append(f"{root}: plugin.json userConfig.display must offer auto / mod / multiplex")
    for name in MOD_SCRIPTS:
        p = root / "skills" / SKILL / "scripts" / name
        if not p.is_file():
            errs.append(f"{p}: missing")
    for p in _entries(root):
        if p.name.endswith((".test.ts", ".test.tsx")):
            errs.append(f"{p}: a mod test shipped")


def check_codex(out: Path, errs: list[str]) -> None:
    root = out / "codex"
    man = _load_obj(root / "plugin.json", errs)
    if man.get("$schema") != CODEX_SCHEMA:
        errs.append(f"{root}/plugin.json: $schema must be {CODEX_SCHEMA}")
    if not CODEX_NAME_RE.match(str(man.get("name", ""))):
        errs.append(f"{root}/plugin.json: bad name {man.get('name')!r}")
    for k in set(man) - CODEX_KEYS:
        errs.append(f"{root}/plugin.json: key {k!r} not allowed by Agent Plugins 1.0.0")
    check_sigil_skill(root / "skills" / SKILL, errs)
    skills = sorted((root / "skills").iterdir()) if (root / "skills").is_dir() else []
    for d in skills:
        if d.name == SKILL or not d.is_dir():
            continue
        check_skill(d, errs)
        fm = _read_frontmatter(d / "SKILL.md", []) if (d / "SKILL.md").is_file() else None
        if fm is None:
            continue                      # already reported by check_skill
        text = fm[1]
        if "$ARGUMENTS" in text or re.search(r"\$1(?!\d)", text):
            errs.append(f"{d}/SKILL.md: argument placeholders are not substituted in skills")
        if f"{PORTABLE_SCRIPTS}/" not in text or SIGIL_DIR_NOTE not in text:
            errs.append(f"{d}/SKILL.md: scripts not addressed via {PORTABLE_SCRIPTS}")
        pol = d / "agents" / "openai.yaml"
        if not pol.is_file() or "allow_implicit_invocation: false" not in pol.read_text():
            errs.append(f"{pol}: command skill must set allow_implicit_invocation: false")
    market = out / "codex-marketplace"
    mk = _load_obj(market / ".agents" / "plugins" / "marketplace.json", errs)
    for pl in mk.get("plugins", []):
        if not isinstance(pl, dict):
            errs.append(f"{market}: marketplace entry must be an object")
            continue
        if not {"name", "source", "policy", "category"} <= set(pl):
            errs.append(f"{market}: marketplace entry needs name/source/policy/category")
        pol = pl.get("policy")
        if not (isinstance(pol, dict) and {"installation", "authentication"} <= set(pol)):
            errs.append(f"{market}: policy needs installation and authentication")
        source = pl.get("source")
        path = source.get("path") if isinstance(source, dict) else None
        if not (isinstance(path, str) and (market / path / "plugin.json").is_file()):
            errs.append(f"{market}: plugin source has no plugin.json")
    check_tree_text(root, errs)
    check_tree_text(market, errs)


def check_pi(out: Path, errs: list[str]) -> None:
    root = out / "pi"
    pkg = _load_obj(root / "package.json", errs)
    if "pi-package" not in pkg.get("keywords", []):
        errs.append(f"{root}/package.json: keywords must include 'pi-package'")
    pi = pkg.get("pi")
    if not (isinstance(pi, dict) and "./skills" in pi.get("skills", [])):
        errs.append(f"{root}/package.json: pi.skills must include ./skills")
    for k in ("name", "version"):
        if not pkg.get(k):
            errs.append(f"{root}/package.json: missing {k}")
    check_sigil_skill(root / "skills" / SKILL, errs)
    check_commands(root / "prompts", errs, f"{PORTABLE_SCRIPTS}/", note=True)
    check_pi_extension(root, pi if isinstance(pi, dict) else {}, errs)
    check_tree_text(root, errs)


def check_pi_extension(root: Path, pi: dict[str, Any], errs: list[str]) -> None:
    """The viewer extension: the manifest names it, it and logic.ts are there, they
    import only node: builtins and each other, pane.py and frames.py sit beside the
    skill's tools, and no test shipped."""
    if pi.get("extensions") != [f"./{PI_EXT}"]:
        errs.append(f"{root}/package.json: pi.extensions must be ['./{PI_EXT}']")
    for rel in PI_FILES:
        p = root / rel
        if not p.is_file():
            errs.append(f"{p}: missing")
            continue
        for spec in PI_IMPORT_RE.findall(p.read_text(encoding="utf-8")):
            local = spec.startswith("./") and (p.parent / spec).is_file()
            if not (spec.startswith("node:") or local or spec == "../types"):
                errs.append(f"{p}: imports {spec!r} (only node: builtins and its own files)")
    for name in MOD_SCRIPTS:
        p = root / "skills" / SKILL / "scripts" / name
        if not p.is_file():
            errs.append(f"{p}: missing")
    for p in _entries(root / "extensions") if (root / "extensions").is_dir() else []:
        if p.name.endswith((".test.ts", ".test.mjs")):
            errs.append(f"{p}: an extension test shipped")


def check_opencode(out: Path, errs: list[str]) -> None:
    root = out / "opencode"
    check_sigil_skill(root / "skills" / SKILL, errs)
    inst = root / "install.sh"
    if not (inst.is_file() and _is_exec(inst)):
        errs.append(f"{inst}: missing or not executable")
    elif f"/^{SIGIL_DIR_NOTE_PREFIX}/d" not in inst.read_text(encoding="utf-8"):
        errs.append(f"{inst}: does not strip the <sigil-skill-dir> note")
    check_commands(root / "commands", errs, f"{PORTABLE_SCRIPTS}/",
                   keys={"description"}, note=True)
    check_tree_text(root, errs)


CHECKERS = {"claude": check_claude, "codex": check_codex, "pi": check_pi,
            "opencode": check_opencode}


def check_archives(out: Path, target: str, errs: list[str]) -> None:
    """Both archives exist, under exact names, for the target's trees. The version
    comes from the target's manifest, else (opencode) from the archive names."""
    trees = [out / target]
    if (out / f"{target}-marketplace").is_dir():
        trees.append(out / f"{target}-marketplace")
    version = None
    if target in VERSION_FILES:
        version = _load_obj(out / target / VERSION_FILES[target], []).get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        pat = re.compile(rf"^sigil-{re.escape(target)}-(.+?)(?:\.zip|\.tar\.gz)$")
        found = sorted({m.group(1) for p in out.glob(f"sigil-{target}-*")
                        if (m := pat.match(p.name)) and VERSION_RE.match(m.group(1))})
        if len(found) != 1:
            errs.append(f"{out / target}: cannot tell the archive version "
                        f"(found {', '.join(found) or 'none'})")
            return
        version = found[0]
    for tree in trees:
        for ext in ARCHIVE_EXTS:
            archive = out / f"sigil-{tree.name}-{version}{ext}"
            if not archive.is_file():
                errs.append(f"{archive}: missing archive")


def check(out: Path, targets: list[str]) -> list[str]:
    errs: list[str] = []
    for t in targets:
        if not (out / t).is_dir():
            errs.append(f"{out / t}: not built")
            continue
        CHECKERS[t](out, errs)
        check_archives(out, t, errs)
    return errs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Package Sigil for coding agents.")
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    ap.add_argument("--target", default="all", choices=TARGETS + ["all"])
    ap.add_argument("--version", help="override meta.json version: X.Y.Z[-pre][+build] "
                                      "(a leading v is stripped)")
    ap.add_argument("--check", action="store_true", help="validate an existing build")
    args = ap.parse_args(argv)
    if args.version is not None:
        try:
            args.version = normalize_version(args.version)
        except ValueError as e:
            ap.error(str(e))
    targets = TARGETS if args.target == "all" else [args.target]
    if args.check:
        errs = check(args.out, targets)
        for e in errs:
            print(f"error: {e}", file=sys.stderr)
        print(f"check: {'FAILED' if errs else 'OK'} ({', '.join(targets)})")
        return 1 if errs else 0
    for p in build(args.out, targets, args.version):
        rel = os.path.relpath(p)
        print(p if rel.startswith("..") else rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
