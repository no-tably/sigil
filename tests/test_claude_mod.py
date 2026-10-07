"""Tests for the Claude Code viewer mod (plugin/claude) and its packaging.

Covers:
  - pane.py draw: what it draws is what view.py draws (every cell one column,
    the styles as hex colours, never theme role names), a run's frames and
    status, the tree legend, the flow view and a run in it, errors as
    {"error"} for a missing file and an unknown scenario, a view.py without
    the flow view named;
  - pane.py follow: runs view.py as its control file says, keeps waiting past
    a view.py that fails, and removes its files when view.py ends on its own;
  - build.py: the claude tree carries the mod (manifest fields, hooks module,
    pane.py and frames.py beside the tools, no mod tests), --check catches a
    missing module and a wrong `display` option, a renamed mod fails the build;
  - with `claude` on PATH: `claude plugin validate` on the built plugin and
    `claude plugin test` on the mod's own TypeScript tests.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "plugin" / "claude"
PANE = MOD / "scripts" / "pane.py"
SHOP = ROOT / "site" / "examples" / "02-shop.sigil"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pane = _load("sigil_pane_t", PANE)
build = _load("sigil_build_mod_t", ROOT / "build.py")
view = _load("sigil_view", ROOT / "view.py")


def run_pane(*args: str, script: Path = PANE) -> dict:
    r = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def text_of(rows) -> list[str]:
    return ["".join(t for t, _ in row) for row in rows]


class DrawTest(unittest.TestCase):
    def test_draws_what_view_draws(self):
        out = run_pane("draw", str(SHOP), "--view", "tree", "--width", "90")
        g = view.render.parse_document(SHOP.read_text(encoding="utf-8"))
        rows, _w = view.compose_view(g, True, depth=1, payloads=False, notes="off",
                                     triggers=True, spaced=True, width=90, access=False,
                                     mods=False, events="land")
        want = [ln.rstrip() for ln in text_of(rows)]
        while want and not want[-1]:
            want.pop()
        self.assertEqual([ln.rstrip() for ln in text_of(out["frames"][0])], want)
        self.assertEqual(len(out["frames"]), 1)
        self.assertNotIn("status", out)
        self.assertTrue(out["legend"])                     # the tree's key
        self.assertIn("lint: OK", out["summary"])
        self.assertIn("happy", out["scenarios"])

    def test_styles_are_hex_and_cells_one_column(self):
        out = run_pane("draw", str(SHOP), "--view", "graph", "--payloads")
        for fg, bg, bold in out["styles"]:
            for c in (fg, bg):
                self.assertTrue(c is None or (c.startswith("#") and len(c) == 7), c)
            self.assertIsInstance(bold, bool)
        for row in out["frames"][0] + out["legend"]:
            for text, sid in row:
                self.assertLess(sid, len(out["styles"]))
                for ch in text:
                    self.assertNotIn(unicodedata.east_asian_width(ch), ("W", "F"), ch)

    def test_wide_and_zero_width_characters_become_one_cell(self):
        self.assertEqual(pane.cells("a界́─"), "a??─")

    def test_a_run_has_a_frame_and_a_status_per_step(self):
        out = run_pane("draw", str(SHOP), "--scenario", "happy")
        player = view.SimPlayer(view.render.parse_document(SHOP.read_text(encoding="utf-8")),
                                "happy")
        self.assertEqual(len(out["frames"]), player.last + 1)
        self.assertEqual(len(out["status"]), len(out["frames"]))
        self.assertEqual(len(out["log"]), len(out["frames"]))
        self.assertEqual(out["outcome"], player.trace.outcome)
        self.assertTrue(out["status"][-1].startswith("sim happy · "))
        self.assertNotIn("/s ·", out["status"][0])         # the live view's speed is not ours
        # the viewer's narration line and path, a frame at a time: the text, and
        # the row as view.py draws it (packed, the hop now bold)
        self.assertEqual(len(out["say"]), len(out["frames"]))
        self.assertEqual(len(out["trail"]), len(out["frames"]))
        self.assertEqual(len(out["path"]), len(out["frames"]))
        player.at = player.last
        self.assertEqual(out["say"][-1], player.narration())
        self.assertEqual(out["trail"][-1], player.path())
        self.assertTrue(out["trail"][-1].startswith("① (Shopper) -> [Edge] -> [Shop]   ② "))
        self.assertLessEqual(len(out["path"][-1]), view.PATH_ROWS)
        self.assertEqual(out["trail"][1], "① (Shopper) ▸-> [Edge]")    # a token on its first hop
        self.assertEqual("".join(t for t, _s in out["path"][1][0]), "path   ① (Shopper) -> [Edge]")
        bold = [t for t, sid in out["path"][1][0] if out["styles"][sid][2]]
        self.assertEqual(bold, ["-> [Edge]"])

    def test_sampling_keeps_both_ends(self):
        self.assertEqual(pane.sampled(3), [0, 1, 2, 3])
        picks = pane.sampled(1000, cap=5)
        self.assertEqual(picks, [0, 250, 500, 750, 1000])

    def test_errors_are_reported_not_raised(self):
        self.assertIn("error", run_pane("draw", str(ROOT / "nope.sigil")))
        bad = run_pane("draw", str(SHOP), "--scenario", "no-such-run")
        self.assertTrue(bad["error"].startswith("scenario:"), bad)

    def test_draws_the_flow_view_and_runs_in_it(self):
        out = run_pane("draw", str(SHOP), "--view", "flow")
        g = view.render.parse_document(SHOP.read_text(encoding="utf-8"))
        rows, _w = view.compose_view(g, "flow", depth=1, payloads=False, notes="off",
                                     triggers=True, spaced=True, width=None, access=False,
                                     mods=False, events=view.DEFAULT_EVENTS["flow"])
        want = [ln.rstrip() for ln in text_of(rows)]
        while want and not want[-1]:
            want.pop()
        self.assertEqual([ln.rstrip() for ln in text_of(out["frames"][0])], want)
        legend = "".join(text_of(out["legend"]))
        self.assertTrue(legend.startswith("flow "), legend)  # the flow view's own key
        run = run_pane("draw", str(SHOP), "--view", "flow", "--scenario", "happy")
        self.assertEqual(run["view"], "flow")
        self.assertEqual(len(run["frames"]), len(run["status"]))
        self.assertTrue(run["say"][-1])

    def test_a_view_py_without_the_flow_view_is_named(self):
        old = types.SimpleNamespace(VIEWS=("graph", "tree"))
        with self.assertRaisesRegex(LookupError, "no flow view"):
            pane.compose(old, None, "flow")


class FollowTest(unittest.TestCase):
    def start(self, d: Path, argv: list[str]):
        control = d / "c.json"
        control.write_text(json.dumps({"argv": argv}))
        proc = subprocess.Popen([sys.executable, str(PANE), "follow", str(control)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return control, proc

    def test_runs_view_and_cleans_up_when_it_ends(self):
        with tempfile.TemporaryDirectory() as d:
            # stdout is a pipe, so view.py prints once and exits 0: as a `q`
            control, proc = self.start(Path(d), [str(SHOP), "--tree", "--color", "never"])
            self.assertEqual(proc.wait(timeout=30), 0)
            self.assertIn("[Shop]", proc.stdout.read())
            self.assertFalse(control.exists())
            self.assertFalse(Path(str(control) + ".alive").exists())

    def test_a_failing_view_leaves_it_waiting_for_the_next_request(self):
        with tempfile.TemporaryDirectory() as d:
            control, proc = self.start(Path(d), [str(SHOP), "--no-such-flag"])
            deadline = time.monotonic() + 15
            while not Path(str(control) + ".alive").exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            time.sleep(1.5)
            self.assertIsNone(proc.poll())                 # still up after view.py failed
            time.sleep(0.05)
            control.write_text(json.dumps({"argv": [str(SHOP), "--color", "never"]}))
            self.assertEqual(proc.wait(timeout=30), 0)
            out = proc.stdout.read()
            self.assertIn("waiting for the next request", out)
            self.assertIn("[Shop]", out)


class PackagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "dist"
        build.build(cls.out, ["claude"])
        cls.root = cls.out / "claude"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_claude_tree_carries_the_mod(self):
        man = json.loads((self.root / ".claude-plugin" / "plugin.json").read_text())
        src = json.loads((MOD / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(src["name"], man["name"])
        self.assertEqual(man["userConfig"], src["userConfig"])
        self.assertEqual(man["userConfig"]["display"]["options"], ["auto", "mod", "multiplex"])
        self.assertTrue((self.root / man["types"]).is_file())
        hooks = json.loads((self.root / "hooks" / "hooks.json").read_text())
        for m in hooks["modules"]:
            self.assertTrue((self.root / "hooks" / m).is_file(), m)
        scripts = self.root / "skills" / "sigil" / "scripts"
        for name in ("pane.py", "frames.py"):
            self.assertTrue((scripts / name).stat().st_mode & 0o111, name)
        self.assertEqual((scripts / "frames.py").read_bytes(),
                         (ROOT / "site" / "frames.py").read_bytes())
        shipped = {p.name for p in self.root.rglob("*")}
        self.assertFalse({n for n in shipped if n.endswith(".test.ts")})
        self.assertNotIn("tsconfig.json", shipped)
        self.assertTrue((self.out / "claude-marketplace" / "plugins" / "sigil" / "hooks"
                         / "hooks.json").is_file())

    def test_the_packaged_pane_draws_from_its_own_folder(self):
        out = run_pane("draw", str(SHOP), "--view", "tree",
                       script=self.root / "skills" / "sigil" / "scripts" / "pane.py")
        self.assertIn("[Shop]", "\n".join(text_of(out["frames"][0])))

    def test_check_catches_a_broken_mod(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            build.build(out, ["claude"])
            root = out / "claude"
            (root / "hooks" / "sigil.tsx").unlink()
            man_path = root / ".claude-plugin" / "plugin.json"
            man = json.loads(man_path.read_text())
            man["userConfig"]["display"]["options"] = ["mod"]
            man_path.write_text(json.dumps(man))
            errs = build.check(out, ["claude"])
            self.assertTrue(any("module './sigil.tsx' missing" in e for e in errs), errs)
            self.assertTrue(any("userConfig.display" in e for e in errs), errs)

    def test_a_renamed_mod_fails_the_build(self):
        meta = dict(build.load_meta(), name="other")
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            build.stage_mod(Path(d), meta)


@unittest.skipUnless(shutil.which("claude"), "claude not on PATH")
class ClaudeCliTest(unittest.TestCase):
    def claude(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["claude", "plugin", *args], capture_output=True, text=True,
                              timeout=180)

    def test_the_built_plugin_validates(self):
        with tempfile.TemporaryDirectory() as d:
            build.build(Path(d), ["claude"])
            r = self.claude("validate", str(Path(d) / "claude"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Validation passed", r.stdout + r.stderr)

    def test_the_mod_tests_pass(self):
        r = self.claude("test", str(MOD))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout + r.stderr, r"\b0 fail\b")


if __name__ == "__main__":
    unittest.main()
