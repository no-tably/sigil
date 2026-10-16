#!/usr/bin/env python3
"""
playground_smoke.py — the page's playground in a real browser (headless Chromium).

Usage:
    tools/playground_smoke.py [--chromium PATH] [--examples 00-shortener,07-export]
                              [--site DIR] [--timeout SECONDS]

What it does:
    builds the site (site/build_site.py) into a temporary directory (or uses
    --site DIR, an existing build), serves it on a free local port, and drives
    the playground with headless Chromium over the DevTools protocol (a pipe, so
    no websocket library is needed): start the playground (Pyodide loads the
    sigil package from py/), then for each example: load it, draw it in the graph
    and the tree view, pick its first scenario and step the run forward, and wait
    for the check's findings line. Any console error or uncaught exception fails
    the smoke.

    Not part of the unit tests: it needs a Chromium and the network (Pyodide comes
    from its CDN). Without either it says SKIP and exits 0. Exit 1 when a step
    fails, 2 for a usage error.

Chromium: --chromium, else $CHROMIUM, else Playwright's download under
~/.cache/ms-playwright (its headless shell first), else chromium / google-chrome on PATH.

Standard library only.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXAMPLES = ("00-shortener", "07-export")   # 07 is #!spec: its check lists a finding
DRAW_VIEWS = ("graph", "tree")


class SmokeFailed(Exception):
    """A playground step did not do what it should (one line for the report)."""


# ---------------------------------------------------------------------------
# Finding a browser and the network
# ---------------------------------------------------------------------------

def find_chromium(given: str | None, env: dict, home: Path) -> Path | None:
    """The Chromium to drive: `given`, $CHROMIUM, Playwright's newest download
    (headless shell, then full Chromium),
    or one on PATH; None when there is none."""
    for cand in (given, env.get("CHROMIUM")):
        if cand:
            return Path(cand) if Path(cand).is_file() else None
    cache = home / ".cache" / "ms-playwright"
    shells = sorted(cache.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"))
    fulls = sorted(cache.glob("chromium-*/chrome-linux64/chrome"))
    for found in shells[::-1] + fulls[::-1]:     # the newest headless shell first
        return found
    for name in ("chromium", "chromium-browser", "google-chrome"):
        if shutil.which(name):
            return Path(shutil.which(name))
    return None


def pyodide_url(site_js: str) -> str:
    """pyodide.js at the CDN folder site.js loads it from (its PYODIDE constant)."""
    m = re.search(r'const PYODIDE = "([^"]+)"', site_js)
    if not m:
        raise SmokeFailed("site.js names no PYODIDE folder")
    return m.group(1) + "pyodide.js"


def online(url: str, timeout: float = 8.0) -> bool:
    """Whether `url` answers (Pyodide's CDN: the playground needs it)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=timeout):
            return True
    except Exception:  # noqa: BLE001  (any failure means: no network for us)
        return False


# ---------------------------------------------------------------------------
# The site: built and served
# ---------------------------------------------------------------------------

def build_site(out: Path) -> None:
    """site/build_site.py --out `out` (raises SmokeFailed with its stderr)."""
    run = subprocess.run([sys.executable, str(ROOT / "site" / "build_site.py"), "--out", str(out)],
                         capture_output=True, text=True)
    if run.returncode:
        raise SmokeFailed(f"site build failed: {run.stderr.strip()}")


@contextmanager
def served(directory: Path):
    """`directory` over HTTP on a free local port; yields its base URL."""
    quiet = type("Quiet", (http.server.SimpleHTTPRequestHandler,),
                 {"log_message": lambda *a: None})
    handler = functools.partial(quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# DevTools protocol over a pipe (--remote-debugging-pipe: fd 3 in, fd 4 out,
# messages are JSON ended by a NUL byte)
# ---------------------------------------------------------------------------

@dataclass
class Cdp:
    """One browser over its DevTools pipe; `problems` collects console errors
    and uncaught exceptions from the page as they arrive."""
    proc: subprocess.Popen
    to_browser: int
    from_browser: int
    session: str | None = None
    problems: list = field(default_factory=list)
    _next: int = 0
    _buf: bytes = b""

    def call(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        self._next += 1
        msg = {"id": self._next, "method": method, "params": params or {}}
        if self.session:
            msg["sessionId"] = self.session
        os.write(self.to_browser, json.dumps(msg).encode() + b"\0")
        deadline = time.monotonic() + timeout
        while True:
            reply = self._read(deadline)
            if reply.get("id") == self._next:
                if "error" in reply:
                    raise SmokeFailed(f"{method}: {reply['error'].get('message')}")
                return reply.get("result", {})
            self._note(reply)

    def _read(self, deadline: float) -> dict:
        while b"\0" not in self._buf:
            if time.monotonic() > deadline:
                raise SmokeFailed("the browser did not answer in time")
            chunk = os.read(self.from_browser, 1 << 16)
            if not chunk:
                raise SmokeFailed("the browser closed its pipe")
            self._buf += chunk
        raw, self._buf = self._buf.split(b"\0", 1)
        return json.loads(raw)

    def _note(self, event: dict) -> None:
        problem = page_problem(event.get("method"), event.get("params") or {})
        if problem:
            self.problems.append(problem)


def page_problem(method: str | None, params: dict) -> str | None:
    """A console error or uncaught exception in a DevTools event, as one line."""
    if method == "Runtime.exceptionThrown":
        d = params.get("exceptionDetails", {})
        return f"exception: {d.get('exception', {}).get('description') or d.get('text')}"
    if method == "Runtime.consoleAPICalled" and params.get("type") == "error":
        args = params.get("args", [])
        return "console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in args)
    if method == "Log.entryAdded" and params.get("entry", {}).get("level") == "error":
        e = params["entry"]
        return f"log: {e.get('text')} {e.get('url', '')}".strip()
    return None


@contextmanager
def browser(chromium: Path):
    """Headless Chromium attached to one blank page; yields its Cdp."""
    in_r, in_w = os.pipe()     # we write, the browser reads fd 3
    out_r, out_w = os.pipe()   # the browser writes fd 4, we read

    def plumb():               # in the child: the pipe ends to fds 3 and 4
        read, write = os.dup(in_r), os.dup(out_w)   # above 4, so neither dup2 clobbers
        os.dup2(read, 3)
        os.dup2(write, 4)

    profile = tempfile.mkdtemp(prefix="pg-smoke-profile-")
    proc = subprocess.Popen(
        [str(chromium), "--headless", "--remote-debugging-pipe", "--no-sandbox",
         "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
         "--window-size=1400,1000", "about:blank"],
        preexec_fn=plumb, pass_fds=(3, 4), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(in_r)
    os.close(out_w)
    cdp = Cdp(proc, in_w, out_r)
    try:
        target = cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        cdp.session = cdp.call("Target.attachToTarget",
                               {"targetId": target, "flatten": True})["sessionId"]
        for domain in ("Runtime", "Log", "Page"):
            cdp.call(f"{domain}.enable")
        yield cdp
    finally:
        proc.kill()
        proc.wait()
        os.close(in_w)
        os.close(out_r)
        shutil.rmtree(profile, ignore_errors=True)


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

def evaluate(cdp: Cdp, expr: str):
    """The value of a JS expression in the page (awaited when a promise)."""
    r = cdp.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                      "awaitPromise": True})
    if "exceptionDetails" in r:
        raise SmokeFailed(f"page script failed: {r['exceptionDetails'].get('text')} in {expr[:60]}")
    return r["result"].get("value")


def wait_for(cdp: Cdp, expr: str, what: str, timeout: float):
    """Poll a JS expression until it is truthy; its value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = evaluate(cdp, expr)
        if value:
            return value
        time.sleep(0.25)
    raise SmokeFailed(f"timed out waiting for {what}")


def text_of(sel: str) -> str:
    return f"(document.querySelector({json.dumps(sel)})?.textContent || '')"


def click(sel: str) -> str:
    return f"document.querySelector({json.dumps(sel)}).click(), true"


def choose(sel: str, value: str) -> str:
    """JS that sets a <select> and fires its change event."""
    return (f"(() => {{ const s = document.querySelector({json.dumps(sel)}); "
            f"s.value = {json.dumps(value)}; s.dispatchEvent(new Event('change')); return true; }})()")


# ---------------------------------------------------------------------------
# The smoke steps
# ---------------------------------------------------------------------------

def start_playground(cdp: Cdp, url: str, timeout: float) -> str:
    """Open the page and boot the playground; what the status line said."""
    cdp.call("Page.navigate", {"url": url})
    wait_for(cdp, "document.readyState === 'complete' && !!document.querySelector('#pg-go')",
             "the page", 30)
    evaluate(cdp, click("#pg-go"))
    state = wait_for(cdp, "(() => { const s = document.querySelector('#pg').dataset.state; "
                          "const m = document.querySelector('#pg-msg'); "
                          "return s === 'ready' ? 'ready' : (m.classList.contains('bad') ? "
                          "'failed: ' + m.textContent : ''); })()", "Pyodide and sigil", timeout)
    if state != "ready":
        raise SmokeFailed(f"playground {state}")
    return state


def example_index(cdp: Cdp, stem: str) -> str:
    """The playground's option value for the example named like `stem`."""
    name = stem.split("-", 1)[1] if stem[:2].isdigit() else stem
    opts = evaluate(cdp, "[...document.querySelectorAll('#pg-example option')]"
                         ".map(o => [o.value, o.textContent])")
    for value, label in opts:
        if label.startswith(name):
            return value
    raise SmokeFailed(f"example {stem}: not in the playground's list ({[l for _, l in opts]})")


def smoke_example(cdp: Cdp, stem: str, timeout: float) -> list[str]:
    """Load one example and check draw (graph, tree), sim step and check; report lines."""
    report = []
    evaluate(cdp, "document.querySelector('#pg-check').textContent = '', true")  # no stale check
    evaluate(cdp, choose("#pg-example", example_index(cdp, stem)))
    lint = wait_for(cdp, text_of("#pg-lint"), "lint line", 30)
    if lint.startswith("python:"):
        raise SmokeFailed(f"{stem}: draw failed: {lint}")
    report.append(f"{stem}: {lint} · {evaluate(cdp, text_of('#pg-count'))}")
    for view in DRAW_VIEWS:
        evaluate(cdp, click(f"#pg-views button[data-view={view}]"))
        rows = wait_for(cdp, f"{text_of('#pg-draw')}.split('\\n').filter(r => r.trim()).length",
                        f"{view} drawing", 30)
        report.append(f"  {view}: {rows} rows drawn")
    report.append("  " + step_run(cdp, stem))
    check = wait_for(cdp, f"{text_of('#pg-check')}.startsWith('check (') && {text_of('#pg-check')}",
                     "check findings", timeout)
    shown = evaluate(cdp, "document.querySelectorAll('#pg-findings li').length")
    report.append(f"  {check} ({shown} listed)")
    return report


def step_run(cdp: Cdp, stem: str) -> str:
    """Pick the first scenario, step forward twice; the tick line before and after."""
    first = evaluate(cdp, "[...document.querySelectorAll('#pg-scenario option')]"
                          ".map(o => o.value).find(v => v)")
    if not first:
        raise SmokeFailed(f"{stem}: no scenarios to simulate")
    evaluate(cdp, choose("#pg-scenario", first))
    before = wait_for(cdp, text_of("#pg-tick"), "the run's first frame", 30)
    if not before.startswith("t"):
        raise SmokeFailed(f"{stem}: sim failed: {before}")
    for _ in range(2):
        evaluate(cdp, click("#pg-fwd"))
    after = evaluate(cdp, text_of("#pg-tick"))
    frame = evaluate(cdp, "document.querySelector('#pg-scrub').value")
    if frame != "2":
        raise SmokeFailed(f"{stem}: stepping did not advance (frame {frame}, {after})")
    return f"sim {first!r}: {before} -> frame {frame} {after}"


def smoke(cdp: Cdp, url: str, examples: list[str], timeout: float):
    """Every step, yielding report lines as they pass. Raises SmokeFailed on the
    first failure or, at the end, on any console error the page logged."""
    yield f"playground: {start_playground(cdp, url, timeout)}"
    for stem in examples:
        yield from smoke_example(cdp, stem, timeout)
    evaluate(cdp, "true")                     # drain events logged after the last step
    if cdp.problems:
        raise SmokeFailed("console errors:\n  " + "\n  ".join(cdp.problems))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="playground_smoke.py",
                                 description="Drive the site's playground in headless Chromium.")
    ap.add_argument("--chromium", help="the browser binary (default: found)")
    ap.add_argument("--examples", default=",".join(DEFAULT_EXAMPLES),
                    help="comma-separated example stems from site/examples")
    ap.add_argument("--site", type=Path, help="an existing site build (default: build one)")
    ap.add_argument("--timeout", type=float, default=240.0,
                    help="seconds for Pyodide to start and for a check (default 240)")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    chromium = find_chromium(args.chromium, dict(os.environ), Path.home())
    if chromium is None:
        print("SKIP: no Chromium found (--chromium or $CHROMIUM)")
        return 0
    probe = pyodide_url((ROOT / "site" / "site.js").read_text(encoding="utf-8"))
    if not online(probe):
        print(f"SKIP: no network ({probe} unreachable)")
        return 0
    examples = [e for e in args.examples.split(",") if e]
    try:
        with tempfile.TemporaryDirectory(prefix="pg-smoke-site-") as tmp:
            site = args.site or Path(tmp) / "site"
            if not args.site:
                build_site(site)
            with served(site) as url, browser(chromium) as cdp:
                print(f"chromium: {chromium}\nsite: {url}", flush=True)
                for line in smoke(cdp, url, examples, args.timeout):
                    print(line, flush=True)
    except SmokeFailed as err:
        print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
