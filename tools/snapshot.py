#!/usr/bin/env python3
"""Every command's output over the corpus, recorded and compared.

The corpus: every .sigil file under tests/fixtures and site/examples, and every
Sigil block of language.md, examples.md and README.md (written to a temporary
folder under stable names such as `language.md/block-07.sigil`). Each file runs
through lint, check (text, --json, spec mode or --export), Mermaid (depth 1, 2,
subgraphs); the site examples also through view --once (graph, tree, flow, run),
--sim all --json and --run --json; #!spec files through export --dry-run --json.

Two runners name how a command is invoked: `old` (the top-level scripts
lint.py, check.py, render.py, view.py, export.py) and `new` (`bin/sigil
lint|check|view|export`, Mermaid as `bin/sigil export FILE --mermaid`).

    tools/snapshot.py --runner old --record DIR   # outputs, exit codes, timings
    tools/snapshot.py --compare [DIR]             # rerun, diff, flag >20% slower

A recording holds one file per case (`cases/<command>/<corpus name>.out`: exit
status, stdout, stderr) and `meta.json` (timings: per command, the sum over a
fixed subset of files of the median of 3 runs; the full run's wall time).
`tools/snapshot_allow.txt` names cases expected to change (fnmatch patterns
over case ids such as `mermaid-d1/site/examples/02-shop.sigil`, one a line,
`#` comments).
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIR = REPO.parent / "sigil" / ".claude" / "campaigns" / "self-model" / "baseline"
ALLOW_FILE = REPO / "tools" / "snapshot_allow.txt"

MODES = ("#!spec", "#!sketch", "#!craft")
CORPUS_DIRS = ("tests/fixtures", "site/examples")
EXAMPLES_DIR = "site/examples"
# Markdown files whose Sigil blocks join the corpus; True: a block without a
# mode line (a fragment the prose explains) counts too.
DOC_FILES = {"language.md": True, "examples.md": True, "README.md": False}

TIMED_RUNS = 3
SLOWER = 1.20          # a command this much slower in total is flagged
CASE_TIMEOUT = 300     # seconds
DIFF_HEAD = 40         # lines of each differing case's diff to print


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    """One corpus file: `name` is its stable id, `path` is relative to `cwd`."""
    name: str
    cwd: Path
    path: str
    mode: str          # "spec", "sketch" or "craft"
    example: bool      # a site example: also drawn, simulated and run


def read_mode(text: str) -> str:
    """The mode of the first content line; none reads as sketch."""
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    word = first.split()[0] if first else ""
    return word[2:] if word in MODES else "sketch"


_FENCE_RE = re.compile(r"^```([a-z]*)\n(.*?)^```", re.S | re.M)


def doc_blocks(text: str, fragments: bool) -> list:
    """The Sigil blocks of a Markdown text, in order: a ```sigil block, or a
    plain one that starts with a mode line (or, with `fragments`, any plain
    block that is not a drawing)."""
    blocks = []
    for m in _FENCE_RE.finditer(text):
        lang, body = m.group(1), m.group(2)
        first = next((l.strip() for l in body.splitlines() if l.strip()), "")
        moded = first.split()[0] in MODES if first else False
        drawing = first.startswith("─")
        if lang == "sigil" or (lang == "" and (moded or (fragments and not drawing))):
            blocks.append(body)
    return blocks


def repo_items(repo: Path) -> list:
    items = []
    for d in CORPUS_DIRS:
        for p in sorted((repo / d).rglob("*.sigil")):
            rel = p.relative_to(repo).as_posix()
            items.append(Item(rel, repo, rel, read_mode(p.read_text(encoding="utf-8")),
                              rel.startswith(EXAMPLES_DIR + "/")))
    return items


def block_items(repo: Path, root: Path) -> list:
    """Write each document's blocks under `root` and return them as items."""
    items = []
    for doc, fragments in DOC_FILES.items():
        text = (repo / doc).read_text(encoding="utf-8")
        for i, body in enumerate(doc_blocks(text, fragments), 1):
            rel = f"{doc}/block-{i:02d}.sigil"
            (root / doc).mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body, encoding="utf-8")
            items.append(Item(rel, root, rel, read_mode(body), False))
    return items


# ---------------------------------------------------------------------------
# Cases: a command over one corpus file
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Case:
    command: str       # e.g. "check-json"; groups cases for timing
    tool: str          # lint, check, mermaid, view, export
    args: tuple
    item: Item

    @property
    def id(self) -> str:
        return f"{self.command}/{self.item.name}"


_VIEW = ("--once", "--color", "never", "--width", "100")


def commands_for(item: Item) -> list:
    """(command, tool, args) for every command this file runs through."""
    cmds = [
        ("lint", "lint", ()),
        ("lint-deep", "lint", ("--deep",)),
        ("check", "check", ()),
        ("check-json", "check", ("--json",)),
        ("mermaid-d1", "mermaid", ("--depth", "1")),
        ("mermaid-d2", "mermaid", ("--depth", "2")),
        ("mermaid-subgraphs", "mermaid", ("--composition", "subgraphs")),
    ]
    if item.mode == "spec":
        cmds += [("check-export", "check", ("--export",)),
                 ("export-dry", "export", ("--dry-run", "--json"))]
    else:
        cmds.append(("check-spec", "check", ("--mode", "spec")))
    if item.example:
        cmds += [(f"view-{v}", "view", (f"--{v}",) + _VIEW)
                 for v in ("graph", "tree", "flow", "run")]
        cmds += [("sim-json", "view", ("--sim", "all", "--json")),
                 ("run-json", "view", ("--run", "--json"))]
    return cmds


def cases_for(items: list) -> list:
    return [Case(c, t, a, it) for it in items for c, t, a in commands_for(it)]


_OLD_SCRIPTS = {"lint": "lint.py", "check": "check.py", "mermaid": "render.py",
                "view": "view.py", "export": "export.py"}


def argv_for(runner: str, case: Case, repo: Path, out_root: Path) -> list:
    """The command line for `case` under `runner`; an export writes (never,
    with --dry-run) under `out_root`."""
    args = list(case.args)
    if case.tool == "export":
        args = ["--out", str(out_root / case.command / case.item.name)] + args
    if runner == "old":
        return [sys.executable, str(repo / _OLD_SCRIPTS[case.tool]), case.item.path] + args
    sub = "export" if case.tool == "mermaid" else case.tool
    extra = ["--mermaid"] if case.tool == "mermaid" else []
    return [sys.executable, str(repo / "bin" / "sigil"), sub, case.item.path] + extra + args


# ---------------------------------------------------------------------------
# Running (the side effects)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Result:
    exit: str          # the status as text, or "timeout"
    stdout: bytes
    stderr: bytes
    seconds: float


def clean_env(env: dict) -> dict:
    """The environment every case runs in: no dialect from outside."""
    env = {k: v for k, v in env.items() if k != "SIGIL_DIALECT"}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_argv(argv: list, cwd: Path, env: dict) -> Result:
    start = time.perf_counter()
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=CASE_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        return Result("timeout", e.stdout or b"", e.stderr or b"",
                      time.perf_counter() - start)
    return Result(str(p.returncode), p.stdout, p.stderr, time.perf_counter() - start)


def render_result(r: Result) -> bytes:
    """One case's recorded text: exit status, stdout, stderr."""
    return (f"exit: {r.exit}\n--- stdout\n".encode() + r.stdout
            + b"\n--- stderr\n" + r.stderr)


@dataclass(frozen=True)
class Runner:
    name: str
    repo: Path
    env: dict
    out_root: Path

    def run(self, case: Case) -> Result:
        return run_argv(argv_for(self.name, case, self.repo, self.out_root),
                        case.item.cwd, self.env)


def run_all(runner: Runner, cases: list, jobs: int) -> dict:
    """Every case's recorded text, by case id."""
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = pool.map(runner.run, cases)
        return {c.id: render_result(r) for c, r in zip(cases, results)}


def timing_subset(items: list) -> list:
    """About twenty files, fixed by name: every site example, the top-level
    fixtures, and every n-th of the rest."""
    examples = [i for i in items if i.example]
    top = [i for i in items if i.name.count("/") == 2 and i.name.startswith("tests/fixtures/")]
    rest = [i for i in items if i not in examples and i not in top
            and i.name.startswith("tests/")]
    want = max(0, 20 - len(examples) - len(top))
    step = max(1, len(rest) // want) if want else 0
    return examples + top + (rest[::step][:want] if want else [])


def time_cases(runner: Runner, cases: list, runs: int) -> dict:
    """Per command: the sum over `cases` of the median of `runs` wall times,
    each case run serially so the measure stays steady."""
    totals = {}
    for c in cases:
        median = statistics.median(runner.run(c).seconds for _ in range(runs))
        totals[c.command] = totals.get(c.command, 0.0) + median
    return {k: round(v, 4) for k, v in sorted(totals.items())}


# ---------------------------------------------------------------------------
# Recording and comparing
# ---------------------------------------------------------------------------

def case_file(root: Path, case_id: str) -> Path:
    return root / "cases" / f"{case_id}.out"


def write_recording(root: Path, outputs: dict, meta: dict) -> None:
    """Replace the recording under `root` with `outputs` and `meta`."""
    shutil.rmtree(root / "cases", ignore_errors=True)
    for cid, data in outputs.items():
        f = case_file(root, cid)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    (root / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def read_recording(root: Path) -> tuple:
    """(outputs by case id, meta) of the recording under `root`."""
    cases = root / "cases"
    outputs = {f.relative_to(cases).as_posix()[:-len(".out")]: f.read_bytes()
               for f in sorted(cases.rglob("*.out"))}
    meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    return outputs, meta


def read_allow(path: Path) -> list:
    if not path.exists():
        return []
    lines = (l.split("#", 1)[0].strip() for l in path.read_text(encoding="utf-8").splitlines())
    return [l for l in lines if l]


@dataclass(frozen=True)
class OutputReport:
    differing: list    # (case id, diff lines), not allowed
    allowed: list      # case ids that differ as the allow-list expects
    missing: list      # recorded but not run now
    added: list        # run now but not recorded


def compare_outputs(old: dict, new: dict, allow: list) -> OutputReport:
    differing, allowed = [], []
    for cid in sorted(old.keys() & new.keys()):
        if old[cid] == new[cid]:
            continue
        if any(fnmatch.fnmatchcase(cid, pat) for pat in allow):
            allowed.append(cid)
            continue
        diff = list(unified_diff(
            old[cid].decode("utf-8", "replace").splitlines(),
            new[cid].decode("utf-8", "replace").splitlines(),
            "recorded", "now", lineterm="", n=2))
        differing.append((cid, diff))
    return OutputReport(differing, allowed, sorted(old.keys() - new.keys()),
                        sorted(new.keys() - old.keys()))


def compare_timings(old: dict, new: dict, slower: float) -> list:
    """(command, recorded, now) for every command more than `slower` times
    the recorded total."""
    return [(cmd, old[cmd], new[cmd]) for cmd in sorted(old.keys() & new.keys())
            if old[cmd] > 0 and new[cmd] > old[cmd] * slower]


def format_report(rep: OutputReport, slow: list, timings: tuple, walls) -> str:
    """The compare report; `walls` is (recorded, now) full-run seconds, or None."""
    out = []
    for cid, diff in rep.differing:
        out.append(f"DIFF {cid}")
        out += ["    " + l for l in diff[:DIFF_HEAD]]
        if len(diff) > DIFF_HEAD:
            out.append(f"    … {len(diff) - DIFF_HEAD} more diff lines")
    out += [f"MISSING {cid}" for cid in rep.missing]
    out += [f"allowed {cid}" for cid in rep.allowed]
    out += [f"added {cid}" for cid in rep.added]
    old_t, new_t = timings
    for cmd in sorted(old_t.keys() | new_t.keys()):
        mark = " SLOWER" if any(s[0] == cmd for s in slow) else ""
        out.append(f"time {cmd:18} {old_t.get(cmd, 0):8.3f}s → {new_t.get(cmd, 0):8.3f}s{mark}")
    if walls:
        out.append(f"time full run (wall)  {walls[0]:8.1f}s → {walls[1]:8.1f}s")
    verdict = "identical" if not (rep.differing or rep.missing or slow) else "DIFFERENT"
    out.append(f"snapshot: {verdict} — {len(rep.differing)} differing, {len(rep.missing)} "
               f"missing, {len(rep.allowed)} allowed, {len(rep.added)} added, "
               f"{len(slow)} slower command(s)")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def git_head(repo: Path) -> str:
    p = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                       capture_output=True, text=True)
    return p.stdout.strip()


def precompile(repo: Path) -> None:
    """Byte-compile the package once: the cases run with PYTHONDONTWRITEBYTECODE,
    so without a __pycache__ each would compile it again and time slower."""
    if (repo / "sigil").is_dir():
        subprocess.run([sys.executable, "-m", "compileall", "-q", str(repo / "sigil")],
                       check=False, capture_output=True)


def snapshot(runner_name: str, only: list, jobs: int, timed: bool) -> tuple:
    """Run the corpus: (outputs by case id, meta)."""
    precompile(REPO)
    with tempfile.TemporaryDirectory(prefix="sigil-snapshot-") as tmp:
        tmp = Path(tmp)
        items = repo_items(REPO) + block_items(REPO, tmp / "blocks")
        cases = [c for c in cases_for(items)
                 if not only or any(fnmatch.fnmatchcase(c.id, p) for p in only)]
        runner = Runner(runner_name, REPO, clean_env(dict(os.environ)), tmp / "export-out")
        start = time.perf_counter()
        outputs = run_all(runner, cases, jobs)
        wall = round(time.perf_counter() - start, 2)
        subset = {i.name for i in timing_subset(items)}
        timings = (time_cases(runner, [c for c in cases if c.item.name in subset], TIMED_RUNS)
                   if timed else {})
    meta = {"runner": runner_name, "head": git_head(REPO), "cases": len(outputs),
            "wall": wall, "timing_runs": TIMED_RUNS, "timing_files": sorted(subset),
            "timings": timings}
    return outputs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Run every command over the corpus; record the outputs or "
                    "compare them with a recording.")
    ap.add_argument("--runner", choices=("old", "new"), default="new",
                    help="old: the top-level scripts; new: bin/sigil (default)")
    act = ap.add_mutually_exclusive_group()
    act.add_argument("--record", metavar="DIR", type=Path,
                     help="store outputs, exit statuses and timings in DIR")
    act.add_argument("--compare", metavar="DIR", type=Path, nargs="?", const=DEFAULT_DIR,
                     help=f"rerun and diff against DIR (default {DEFAULT_DIR}); "
                          "the default action")
    ap.add_argument("--only", action="append", default=[], metavar="PATTERN",
                    help="run only cases whose id matches (fnmatch; repeatable)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="cases run at once")
    ap.add_argument("--no-timing", action="store_true",
                    help="skip the timed runs (no speed check; implied by --only)")
    ap.add_argument("--allow", type=Path, default=ALLOW_FILE,
                    help="cases expected to change (default tools/snapshot_allow.txt)")
    args = ap.parse_args(argv)

    # Timing a filtered run would compare part of a total with the whole.
    timed = not (args.no_timing or args.only)
    outputs, meta = snapshot(args.runner, args.only, args.jobs, timed)
    if args.record:
        write_recording(args.record, outputs, meta)
        print(f"snapshot: recorded {meta['cases']} cases with --runner {args.runner} "
              f"in {args.record} (full run {meta['wall']}s)")
        return 0

    root = args.compare or DEFAULT_DIR
    old, old_meta = read_recording(root)
    if args.only:
        old = {k: v for k, v in old.items()
               if any(fnmatch.fnmatchcase(k, p) for p in args.only)}
    rep = compare_outputs(old, outputs, read_allow(args.allow))
    old_t = {k: v for k, v in old_meta["timings"].items() if k in meta["timings"]}
    slow = compare_timings(old_t, meta["timings"], SLOWER)
    print(format_report(rep, slow, (old_t, meta["timings"]),
                        None if args.only else (old_meta["wall"], meta["wall"])))
    return 1 if (rep.differing or rep.missing or slow) else 0


if __name__ == "__main__":
    sys.exit(main())
