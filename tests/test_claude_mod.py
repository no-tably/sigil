"""Tests for the Claude Code viewer mod (plugin/claude) and its packaging.

Covers:
  - `sigil frames draw` (the mod's Python half): what it draws is what the viewer
    draws (every cell one column, the styles as hex colours, never theme role
    names), a run's frames and status, the tree legend, the flow view and a run
    in it, errors as {"error"} for a missing file and an unknown scenario;
  - `sigil frames follow`: runs `sigil view` as its control file says, keeps
    waiting past a view that fails, and removes its files when the view ends on
    its own;
  - build.py: the claude tree carries the mod (manifest fields, hooks module,
    the package's bin/sigil and frames in the skill's scripts, no mod tests), a
    packaged bin/sigil draws from its own folder, --check catches a missing
    module and a wrong `display` option, a renamed mod fails the build;
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
import unicodedata
import unittest
from pathlib import Path

from sigil.core.parse import parse_document
from sigil.model import sim as simulator
from sigil.present import app
from sigil.present import frames as pane

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "plugin" / "claude"
SIGIL = ROOT / "bin" / "sigil"
SHOP = ROOT / "site" / "examples" / "02-shop.sigil"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


build = _load("sigil_build_mod_t", ROOT / "build.py")


def run_pane(*args: str, script: Path = SIGIL) -> dict:
    """`sigil frames ARGS` through `script` (a bin/sigil), its JSON."""
    r = subprocess.run([sys.executable, str(script), "frames", *args], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def text_of(rows) -> list[str]:
    return ["".join(t for t, _ in row) for row in rows]


class DrawTest(unittest.TestCase):
    def test_draws_what_view_draws(self):
        out = run_pane("draw", str(SHOP), "--view", "tree", "--width", "90")
        g = parse_document(SHOP.read_text(encoding="utf-8"))
        rows, _w = app.compose_view(g, "tree", depth=1, payloads=False, notes="off",
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

    def test_layout_wrap_fits_pan_keeps_auto_picks_by_the_pane(self):
        wide = ["draw", str(SHOP), "--view", "graph", "--width", "30"]
        wrapped, panned = run_pane(*wide, "--layout", "wrap"), run_pane(*wide, "--layout", "pan")
        self.assertEqual((wrapped["layout"], panned["layout"]), ("wrap", "pan"))
        widest = lambda out: max(len(ln) for ln in text_of(out["frames"][0]))
        self.assertLessEqual(widest(wrapped), 30)
        self.assertGreater(widest(panned), 30)                  # the natural layout
        self.assertEqual(run_pane(*wide)["layout"], "wrap")     # auto without a height
        g = parse_document(SHOP.read_text(encoding="utf-8"))
        rows, w = app.compose_view(g, "graph", depth=1, payloads=False, notes="off",
                                   triggers=True, spaced=True, width=None, access=False,
                                   mods=False, events="nodes")
        for height in (5, 400):
            self.assertEqual(run_pane(*wide, "--height", str(height))["layout"],
                             app.pick_layout(w, len(rows), 30, height))

    def test_wide_and_zero_width_characters_become_one_cell(self):
        self.assertEqual(pane.cells("a界́─"), "a界\0─")   # a wide one itself, then its second cell

    def test_a_run_has_a_frame_and_a_status_per_step(self):
        out = run_pane("draw", str(SHOP), "--scenario", "happy")
        player = app.SimPlayer(parse_document(SHOP.read_text(encoding="utf-8")), "happy")
        self.assertEqual(len(out["frames"]), player.last + 1)
        self.assertEqual(len(out["status"]), len(out["frames"]))
        self.assertEqual(len(out["log"]), len(out["frames"]))
        self.assertEqual(out["outcome"], player.trace.outcome)
        self.assertTrue(out["status"][-1].startswith("sim happy · "))
        self.assertNotIn("/s ·", out["status"][0])         # the live view's speed is not ours
        # the viewer's narration line and path, a frame at a time: the text, and
        # the row as the viewer draws it (packed, the hop now bold)
        self.assertEqual(len(out["say"]), len(out["frames"]))
        self.assertEqual(len(out["trail"]), len(out["frames"]))
        self.assertEqual(len(out["path"]), len(out["frames"]))
        self.assertEqual((out["first"], out["last"]), (0, player.last))
        player.at = player.last
        self.assertEqual(out["say"][-1], player.narration())
        self.assertEqual(out["trail"][-1], player.path())
        self.assertTrue(out["trail"][-1].startswith("① (Shopper) -> [Edge] -> [Shop]   ② "))
        self.assertLessEqual(len(out["path"][-1]), app.PATH_ROWS)
        self.assertEqual(out["trail"][1], "① (Shopper) ▸-> [Edge]")    # a token on its first hop
        self.assertEqual("".join(t for t, _s in out["path"][1][0]), "path   ① (Shopper) -> [Edge]")
        bold = [t for t, sid in out["path"][1][0] if out["styles"][sid][2]]
        self.assertEqual(bold, ["-> [Edge]"])

    def test_a_window_is_every_frame_in_it_kept_within_the_run(self):
        self.assertEqual(pane.window(0, 120, 3), range(0, 4))
        self.assertEqual(pane.window(10, 5, 1000), range(10, 15))
        self.assertEqual(pane.window(998, 5, 1000), range(998, 1001))
        self.assertEqual(pane.window(None, 5, 1000), range(996, 1001))    # last: ends the run
        self.assertEqual(pane.window(None, 120, 3), range(0, 4))
        self.assertEqual(pane.window(5000, 5, 1000), range(1000, 1001))

    def test_a_run_is_drawn_a_window_at_a_time_every_frame(self):
        whole = pane.draw(SHOP, "graph", scenario="happy", width=100)
        self.assertGreater(whole["last"], 6)
        part = run_pane("draw", str(SHOP), "--view", "graph", "--width", "100",
                        "--scenario", "happy", "--from", "3", "--count", "4")
        self.assertEqual((part["first"], part["last"]), (3, whole["last"]))
        for key in ("frames", "status", "log", "say", "trail", "path"):
            self.assertEqual(part[key], whole[key][3:7], key)   # the same frames, none skipped
        end = run_pane("draw", str(SHOP), "--view", "graph", "--width", "100",
                       "--scenario", "happy", "--from", "last", "--count", "2")
        self.assertEqual(end["first"], whole["last"] - 1)
        self.assertEqual(end["status"], whole["status"][-2:])

    def test_errors_are_reported_not_raised(self):
        self.assertIn("error", run_pane("draw", str(ROOT / "nope.sigil")))
        bad = run_pane("draw", str(SHOP), "--scenario", "no-such-run")
        self.assertTrue(bad["error"].startswith("scenario:"), bad)

    def test_draws_the_flow_view_and_runs_in_it(self):
        out = run_pane("draw", str(SHOP), "--view", "flow")
        g = parse_document(SHOP.read_text(encoding="utf-8"))
        rows, _w = app.compose_view(g, "flow", depth=1, payloads=False, notes="off",
                                    triggers=True, spaced=True, width=None, access=False,
                                    mods=False, events=app.DEFAULT_EVENTS["flow"])
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

    def test_draws_the_run_view_and_runs_in_it(self):
        out = run_pane("draw", str(SHOP), "--view", "run", "--width", "120")
        g = parse_document(SHOP.read_text(encoding="utf-8"))
        rows, _w = app.compose_view(g, "run", depth=1, payloads=False, notes="off",
                                    triggers=True, spaced=True, width=120, access=False,
                                    mods=False, events=app.DEFAULT_EVENTS["run"])
        want = [ln.rstrip() for ln in text_of(rows)]
        while want and not want[-1]:
            want.pop()
        self.assertEqual([ln.rstrip() for ln in text_of(out["frames"][0])], want)
        self.assertIn("no scenario chosen", want[0])            # the happy run, said so
        legend = "".join(text_of(out["legend"]))
        self.assertTrue(legend.startswith("run    █ working"), legend)
        run = run_pane("draw", str(SHOP), "--view", "run", "--scenario", "happy")
        self.assertEqual(run["view"], "run")
        self.assertEqual(len(run["frames"]), len(run["status"]))
        self.assertTrue(any("▼" in ln for ln in text_of(run["frames"][1])))   # the playhead

    def test_overlap_scenarios_are_listed_and_play_like_any_other(self):
        """The listed overlaps (`Entry@t`) come after the failure scenarios, and one
        plays every frame: the narration the viewer gives, both episodes' marks while
        they overlap; a start no list names is taken by name too."""
        orders = ROOT / "site" / "examples" / "04-orders.sigil"
        g = parse_document(orders.read_text(encoding="utf-8"))
        listed = [s.name for s in simulator.overlaps(simulator.canonical(g))]
        self.assertTrue(listed)
        out = run_pane("draw", str(orders))
        starts = len(simulator.state_starts(simulator.canonical(g)))   # listed after them
        self.assertEqual(out["scenarios"][-len(listed) - starts:len(out["scenarios"]) - starts],
                         listed)
        name = listed[-1]
        player = app.SimPlayer(g, name)
        both = next(i for i, f in enumerate(player.trace.frames) if len(f.episodes) > 1)
        run = run_pane("draw", str(orders), "--view", "run", "--width", "100", "--scenario", name)
        self.assertEqual((run["scenario"], len(run["frames"])), (name, player.last + 1))
        player.at = both
        self.assertEqual(run["say"][both], player.narration())
        self.assertIn("ep2:", run["say"][both])                 # sentences led by episode
        self.assertTrue(any(ln.startswith("episodes ") for ln in text_of(run["frames"][both])))
        graph = run_pane("draw", str(orders), "--view", "graph", "--width", "100",
                         "--scenario", name, "--from", str(both), "--count", "1")
        self.assertEqual(len(graph["frames"]), 1)
        named = run_pane("draw", str(orders), "--scenario", "Payments@3", "--from", "last")
        self.assertNotIn("error", named)
        self.assertEqual(named["scenario"], "Payments@3")


class FollowTest(unittest.TestCase):
    def start(self, d: Path, argv: list[str]):
        control = d / "c.json"
        control.write_text(json.dumps({"argv": argv}))
        control.chmod(0o600)                 # as a host makes it (control_problem)
        proc = subprocess.Popen([sys.executable, str(SIGIL), "frames", "follow", str(control)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return control, proc

    def test_runs_view_and_cleans_up_when_it_ends(self):
        with tempfile.TemporaryDirectory() as d:
            # stdout is a pipe, so `sigil view` prints once and exits 0: as a `q`
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
            self.assertIsNone(proc.poll())                 # still up after the view failed
            time.sleep(0.05)
            control.write_text(json.dumps({"argv": [str(SHOP), "--color", "never"]}))
            self.assertEqual(proc.wait(timeout=30), 0)
            out = proc.stdout.read()
            self.assertIn("waiting for the next request", out)
            self.assertIn("[Shop]", out)


class FollowRefusesTest(unittest.TestCase):
    """CONTROL names what `sigil view` runs (a --dialect is Python code): follow
    refuses one another user could write, in a directory another user could write,
    or not a regular file of this user's, and runs nothing it asks."""

    def private(self, argv: list | None = None) -> Path:
        d = Path(tempfile.mkdtemp(prefix="sigil-view-"))
        self.addCleanup(shutil.rmtree, d, True)
        d.chmod(0o700)
        control = d / "c.json"
        control.write_text(json.dumps({"argv": argv or [str(SHOP), "--tree", "--color", "never"]}))
        control.chmod(0o600)
        return control

    @unittest.skipUnless(hasattr(__import__("os"), "getuid"), "unix file modes")
    def test_a_private_file_in_a_private_directory_is_accepted(self):
        from sigil import cli
        self.assertIsNone(cli.control_problem(self.private()))

    @unittest.skipUnless(hasattr(__import__("os"), "getuid"), "unix file modes")
    def test_a_file_or_directory_others_can_write_is_refused(self):
        from sigil import cli
        for mode in (0o620, 0o602, 0o666):
            control = self.private()
            control.chmod(mode)
            self.assertIn("can be written by other users", cli.control_problem(control), oct(mode))
        for mode in (0o770, 0o1777):
            control = self.private()
            control.parent.chmod(mode)
            said = cli.control_problem(control)
            self.assertIn("its directory", said)
            self.assertIn("can be written by other users", said)

    @unittest.skipUnless(hasattr(__import__("os"), "getuid"), "unix file modes")
    def test_a_link_or_another_users_file_is_refused(self):
        from unittest import mock
        from sigil import cli
        control = self.private()
        link = control.with_name("link.json")
        link.symlink_to(control)
        self.assertIn("not a regular file", cli.control_problem(link))
        import os
        with mock.patch.object(os, "getuid", return_value=os.getuid() + 1):
            self.assertIn("not to you", cli.control_problem(control))

    @unittest.skipUnless(hasattr(__import__("os"), "getuid"), "unix file modes")
    def test_follow_refuses_on_screen_and_runs_nothing(self):
        import contextlib, io
        from sigil import cli
        control = self.private()
        control.chmod(0o666)
        err, waited = io.StringIO(), []
        with contextlib.redirect_stderr(err), mock_popen() as popen:
            self.assertEqual(cli.follow(control, wait=lambda: waited.append(1)), 2)
        self.assertEqual(waited, [1])                       # held for the split to close
        popen.assert_not_called()
        self.assertIn("refusing", err.getvalue())
        self.assertIn("can be written by other users", err.getvalue())
        self.assertTrue(control.exists())                   # nothing removed
        self.assertFalse(Path(str(control) + ".alive").exists())   # nor written

    @unittest.skipUnless(hasattr(__import__("os"), "getuid"), "unix file modes")
    def test_a_request_made_writable_later_is_refused(self):
        # a first request that fails, so the split stays up waiting (stdout is a
        # pipe: a view that runs prints once and ends, and so does the split)
        control = self.private([str(SHOP), "--no-such-flag"])
        proc = subprocess.Popen([sys.executable, str(SIGIL), "frames", "follow", str(control)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.monotonic() + 15
        while not Path(str(control) + ".alive").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(1.0)
        control.chmod(0o666)
        control.write_text(json.dumps({"argv": [str(SHOP), "--tree", "--color", "never"]}))
        time.sleep(1.5)
        self.assertIsNone(proc.poll())                      # the open request was not run
        proc.terminate()
        proc.wait(timeout=10)
        out = proc.stdout.read()
        self.assertIn("refusing", out)
        self.assertNotIn("[Shop]", out)
        self.assertFalse(control.parent.exists())           # its files gone, the directory too


def mock_popen():
    from unittest import mock
    return mock.patch("subprocess.Popen")


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
        self.assertTrue((scripts / "bin" / "sigil").stat().st_mode & 0o111)
        self.assertEqual((scripts / "sigil" / "present" / "frames.py").read_bytes(),
                         (ROOT / "sigil" / "present" / "frames.py").read_bytes())
        self.assertFalse((scripts / "pane.py").exists())
        shipped = {p.name for p in self.root.rglob("*")}
        self.assertFalse({n for n in shipped if n.endswith(".test.ts")})
        self.assertNotIn("tsconfig.json", shipped)
        self.assertTrue((self.out / "claude-marketplace" / "plugins" / "sigil" / "hooks"
                         / "hooks.json").is_file())

    def test_the_packaged_frames_draw_from_its_own_folder(self):
        out = run_pane("draw", str(SHOP), "--view", "tree",
                       script=self.root / "skills" / "sigil" / "scripts" / "bin" / "sigil")
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
            del man["userConfig"]["layout"]
            man_path.write_text(json.dumps(man))
            errs = build.check(out, ["claude"])
            self.assertTrue(any("module './sigil.tsx' missing" in e for e in errs), errs)
            self.assertTrue(any("userConfig.display" in e for e in errs), errs)
            self.assertTrue(any("userConfig.layout" in e for e in errs), errs)

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
