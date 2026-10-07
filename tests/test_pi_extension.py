"""Tests for the pi viewer extension (plugin/pi) and its packaging.

Covers:
  - build.py: the pi tree carries the extension (the manifest names it, the
    Claude Code mod's logic.ts beside it, pane.py and frames.py beside the
    tools, no test shipped); --check catches a missing logic.ts, a foreign
    import and a manifest that does not name the extension;
  - the extension's widget helpers (truecolour rows cut to the width, /sigil-pane's
    own words), through node's type stripping;
  - plugin/pi/tests/drive.mjs driving the built extension: registration,
    the 144-column rule for a widget nobody asked for, /sigil-pane opening it at any
    width, a run stepped, close, a missing file, no UI, and a multiplexer split
    (a fake tmux on PATH) started at the run's asked frame and playing, the
    run's speed (- / +, shown in the status), RPC mode (no terminal: the
    widget sent as plain text lines, again only on a change), and
    `/sigil-pane display` (the shared settings
    file under a temp XDG_CONFIG_HOME, and its precedence: --sigil-display >
    SIGIL_DISPLAY > the file > auto) — once with a stand-in API, and again
    through an installed pi's own loader when `pi` is on PATH; under the
    stand-in only, an older draw finishing last and a redraw that fails at a
    new width (asked once, not again and again).

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "plugin" / "pi" / "tests" / "drive.mjs"
SHOP = ROOT / "site" / "examples" / "02-shop.sigil"
NODE = shutil.which("node")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


build = _load("sigil_build_pi_t", ROOT / "build.py")


def _strips_types() -> bool:
    """node runs .ts files itself (type stripping, on by default from 23.6)."""
    if NODE is None:
        return False
    r = subprocess.run([NODE, "-e", "process.exit(process.features.typescript ? 0 : 1)"],
                       capture_output=True, timeout=30)
    return r.returncode == 0


def _pi_package() -> Path | None:
    """The installed pi's package folder (the one holding its extension loader)."""
    exe = shutil.which("pi")
    if exe is None:
        return None
    for d in Path(os.path.realpath(exe)).parents:
        if (d / "package.json").is_file():
            loader = d / "dist" / "core" / "extensions" / "loader.js"
            return d if loader.is_file() else None
    return None


STRIPS = _strips_types()
PI = _pi_package()


class PackagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "dist"
        build.build(cls.out, ["pi"])
        cls.root = cls.out / "pi"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_pi_tree_carries_the_extension(self):
        pkg = json.loads((self.root / "package.json").read_text())
        self.assertEqual(pkg["pi"]["extensions"], ["./extensions/sigil/index.ts"])
        self.assertIn("extensions", pkg["files"])
        ext = self.root / "extensions" / "sigil"
        self.assertEqual((ext / "logic.ts").read_bytes(),
                         (ROOT / "plugin" / "claude" / "hooks" / "logic.ts").read_bytes())
        scripts = self.root / "skills" / "sigil" / "scripts"
        for name in ("pane.py", "frames.py"):
            self.assertTrue((scripts / name).stat().st_mode & 0o111, name)
        shipped = {p.name for p in self.root.rglob("*")}
        self.assertNotIn("drive.mjs", shipped)
        self.assertIn("sigil_view", (self.root / "README.md").read_text())
        self.assertEqual(build.check(self.out, ["pi"]), [])

    def test_check_catches_a_broken_extension(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            build.build(out, ["pi"])
            root = out / "pi"
            (root / "extensions" / "sigil" / "logic.ts").unlink()
            index = root / "extensions" / "sigil" / "index.ts"
            index.write_text("import { Type } from 'typebox'\n" + index.read_text())
            pkg_path = root / "package.json"
            pkg = json.loads(pkg_path.read_text())
            pkg["pi"]["extensions"] = ["./extensions"]
            pkg_path.write_text(json.dumps(pkg))
            errs = build.check(out, ["pi"])
            self.assertTrue(any("logic.ts: missing" in e for e in errs), errs)
            self.assertTrue(any("imports 'typebox'" in e for e in errs), errs)
            self.assertTrue(any("pi.extensions" in e for e in errs), errs)


@unittest.skipUnless(STRIPS, "node with TypeScript type stripping not on PATH")
class HelpersTest(unittest.TestCase):
    def node(self, script: str):
        with tempfile.TemporaryDirectory() as d:
            build.build(Path(d), ["pi"])
            index = Path(d) / "pi" / "extensions" / "sigil" / "index.ts"
            r = subprocess.run([NODE, "--input-type=module", "-e",
                                f"import * as m from {json.dumps(index.as_uri())}\n{script}"],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_rows_are_truecolour_and_cut_to_the_width(self):
        got = self.node("console.log(JSON.stringify(["
                        "m.ansiRow([['abc', 0], ['def', 1]], [['#ff8000', null, true], [null, null, false]], 4),"
                        "m.sgrColour('#0a0b0c', 48), m.sgrColour('ocean', 38)]))")
        self.assertEqual(got, ["\x1b[1;38;2;255;128;0mabc\x1b[0md", "48;2;10;11;12", None])

    def test_command_words(self):
        got = self.node("console.log(JSON.stringify(["
                        "m.commandWords('close'), m.commandWords('next tree'),"
                        "m.commandWords('a.sigil sim happy pause')]))")
        self.assertEqual(got[0], {"action": "close", "input": {}})
        self.assertEqual(got[1], {"action": "next", "input": {"view": "tree"}})
        self.assertEqual(got[2], {"input": {"file": "a.sigil", "scenario": "happy", "play": False}})

    def test_speed_words_and_plain_lines(self):
        got = self.node("console.log(JSON.stringify(["
                        "m.commandWords('+'), m.commandWords('- tree'),"
                        "m.plainLines(['\\x1b[1;38;2;1;2;3mab\\x1b[0mc'])]))")
        self.assertEqual(got[0], {"action": "faster", "input": {}})
        self.assertEqual(got[1], {"action": "slower", "input": {"view": "tree"}})
        self.assertEqual(got[2], ["abc"])


class DriveMixin:
    pi_dir: Path | None = None

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        build.build(tmp / "dist", ["pi"])
        index = tmp / "dist" / "pi" / "extensions" / "sigil" / "index.ts"
        fake = tmp / "bin"
        fake.mkdir()
        (fake / "tmux").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_TMUX_LOG"\necho "%9"\n')
        (fake / "tmux").chmod(0o755)
        cls.tmux_log = tmp / "tmux.log"
        cls.settings = tmp / "xdg" / "sigil" / "viewer.json"
        env = dict(os.environ, PATH=f"{fake}{os.pathsep}{os.environ['PATH']}",
                   FAKE_TMUX_LOG=str(cls.tmux_log), TMPDIR=str(tmp), XDG_CONFIG_HOME=str(tmp / "xdg"))
        argv = [NODE, str(DRIVE), str(index), str(SHOP.relative_to(ROOT))]
        if cls.pi_dir is not None:
            argv.append(str(cls.pi_dir))
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=ROOT, env=env)
        assert r.returncode == 0, r.stderr
        cls.out = json.loads(r.stdout)
        cls.steps = {s["name"]: s for s in cls.out["steps"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_registers_the_tool_the_command_and_the_flag(self):
        self.assertEqual(self.out["errors"], [])
        self.assertEqual(self.out["tools"], ["sigil_view"])
        self.assertEqual(self.out["commands"], ["sigil-pane"])
        self.assertEqual(self.out["flags"], ["sigil-display", "sigil-layout"])
        # no default: an unset flag leaves SIGIL_DISPLAY / SIGIL_LAYOUT and the file to speak
        self.assertEqual(self.out["flagDefaults"], {"sigil-display": None, "sigil-layout": None})

    def test_an_unasked_widget_waits_below_144_columns(self):
        s = self.steps["narrow tool call"]
        self.assertFalse(s["widget"])
        self.assertIn("waiting", s["reply"])
        self.assertIn("this terminal has 100", s["reply"])
        self.assertIn("/sigil-pane", s["reply"])
        self.assertIn("lint: OK", s["reply"])

    def test_the_command_opens_it_at_any_width(self):
        s = self.steps["command opens it"]
        self.assertTrue(s["widget"])
        self.assertTrue(s["coloured"])
        self.assertTrue(s["lines"][0].startswith("02-shop.sigil · tree · depth 1"))
        self.assertTrue(any("[Shop]" in ln for ln in s["lines"]))
        self.assertLessEqual(s["widest"], 120)

    def test_a_run_is_shown_at_its_frame_and_stepped(self):
        run = self.steps["a run at frame 0"]
        self.assertIn("Shown in the sigil widget", run["reply"])
        self.assertIn("(frame 1 of", run["reply"])
        self.assertIn("frame 1/", run["lines"][0])
        self.assertIn("frame 2/", self.steps["next"]["lines"][0])
        # the run's path and narration line under the drawing, and in the reply
        plain = [re.sub(r"\x1b\[[0-9;]*m", "", ln) for ln in self.steps["next"]["lines"]]
        self.assertTrue(any(ln.startswith("path   ① (") for ln in plain), plain)
        self.assertTrue(any(ln.startswith("› ") and len(ln) > 2 for ln in plain), plain)
        self.assertIn("\nnow: ", run["reply"])

    def test_speed_steps_as_view_py_and_shows_in_the_status(self):
        self.assertIn("❚❚ 2 frames/s · sim happy", self.steps["next"]["lines"][0])   # the start
        self.assertIn("❚❚ 4 frames/s · sim happy", self.steps["faster"]["lines"][0])
        self.assertIn("❚❚ 1 frame/s · sim happy", self.steps["slower twice"]["lines"][0])

    def test_naming_the_shown_file_again_keeps_its_run(self):
        self.assertIn("paused at sim happy", self.steps["the file named again"]["reply"])

    def test_rpc_mode_sends_the_widget_as_text_on_a_change(self):
        call = self.steps["rpc tool call"]
        self.assertFalse(call["widget"])                       # no component: pi drops it there
        self.assertIn("Shown in the sigil widget", call["reply"])
        self.assertEqual(len(call["texts"]), 1, call["texts"])
        sent = call["texts"][0]
        self.assertTrue(sent[0].startswith("02-shop.sigil · flow · depth 1 · wrap · ❚❚ 1 frame/s"), sent[0])
        self.assertIn("frame 1/", sent[0])
        self.assertFalse(any("\x1b" in ln for ln in sent))     # plain text, no terminal styles
        self.assertTrue(any("[Shop]" in ln or "Shop" in ln for ln in sent[1:]))
        self.assertIn("frame 2/", self.steps["rpc next"]["texts"][-1][0])
        self.assertEqual(self.steps["rpc reopened, unchanged"]["texts"], [])
        self.assertEqual(self.steps["rpc close"]["texts"], [])   # cleared (undefined), not text

    def test_close_and_an_unasked_widget_on_a_wide_terminal(self):
        self.assertFalse(self.steps["close"]["widget"])
        wide = self.steps["wide tool call"]
        self.assertTrue(wide["widget"])
        self.assertIn("· graph ·", wide["lines"][0])
        self.assertNotIn("sim ", wide["lines"][0])            # scenario "" ended the run
        self.assertLessEqual(wide["widest"], 150)

    def test_errors_and_no_ui_are_replies(self):
        self.assertEqual(self.steps["missing file"]["reply"], "sigil: no-such.sigil: no such file")
        self.assertIn("no terminal UI", self.steps["no ui"]["reply"])

    def test_multiplex_opens_a_split_running_follow(self):
        s = self.steps["multiplex"]
        self.assertFalse(s["widget"])
        self.assertIn("Opened a tmux split", s["reply"])
        self.assertIn("--tree", s["reply"])
        argv = self.tmux_log.read_text().split("\n")
        self.assertEqual(argv[:3], ["split-window", "-h", "-d"])
        self.assertIn("follow", argv)
        self.assertTrue(argv[argv.index("follow") - 1].endswith("skills/sigil/scripts/pane.py"))

    def test_the_split_starts_a_run_where_asked(self):
        s = self.steps["multiplex run"]
        self.assertIn("--sim happy --frame 2 --play", s["reply"])
        self.assertIn("playing ", s["reply"])
        self.assertIn("(frame 3 of", s["reply"])
        argv = self.tmux_log.read_text().split("\n")
        control = json.loads(Path(argv[argv.index("follow") + 1]).read_text())
        self.assertEqual(control["argv"][-5:], ["--sim", "happy", "--frame", "2", "--play"])

    def note(self, name: str) -> list:
        notes = self.steps[name]["notes"]
        self.assertEqual(len(notes), 1, notes)
        return notes[0]

    def test_display_says_the_setting_its_source_and_auto_here(self):
        self.assertEqual(self.note("display default"),
                         ["info", "display: auto → multiplex (tmux detected) · from the default"])
        self.assertEqual(self.note("display from the env"),
                         ["info", "display: multiplex · from SIGIL_DISPLAY · auto here → multiplex (tmux detected)"])
        self.assertEqual(self.note("display from the flag"),
                         ["info", "display: mod · from --sigil-display · auto here → multiplex (tmux detected)"])

    def test_display_value_is_saved_to_the_shared_file_and_used_at_once(self):
        level, text = self.note("display set mod")
        self.assertEqual(level, "info")
        self.assertTrue(text.startswith(f"display: mod · from {self.settings} · auto here"), text)
        self.assertIn("The next view draws in the sigil widget.", text)
        level, text = self.note("display from the file")
        self.assertTrue(text.startswith(f"display: mod · from {self.settings}"), text)
        after = self.steps["a call after the file says mod"]
        self.assertIn("Shown in the sigil widget", after["reply"])   # tmux is set, the file says mod
        self.assertTrue(after["widget"])
        # the last writes (display auto under the flag, layout pan) are what the file holds
        self.assertEqual(json.loads(self.settings.read_text()), {"display": "auto", "layout": "pan"})

    def test_display_under_a_flag_says_the_flag_wins_and_bad_values_are_named(self):
        level, text = self.note("display set under the flag")
        self.assertIn("But --sigil-display (mod) wins in this session", text)
        self.assertEqual(self.note("display bad"),
                         ["error", 'sigil: display must be one of mod, multiplex, auto (got "side")'])

    def test_layout_is_said_saved_and_a_panned_drawing_pans(self):
        level, text = self.note("layout default")
        self.assertTrue(text.startswith("layout: auto"), text)
        self.assertTrue(text.endswith("· from the default"), text)
        level, text = self.note("layout set pan")
        self.assertTrue(text.startswith(f"layout: pan · from {self.settings}"), text)
        panned, moved = self.steps["layout set pan"], self.steps["pan right"]
        self.assertLessEqual(panned["widest"], 30)
        self.assertTrue(any(ln.startswith("/sigil-pane left · right") for ln in panned["lines"]))
        self.assertNotEqual(panned["lines"][1:5], moved["lines"][1:5])   # the drawing moved across
        self.assertEqual(self.note("layout bad"),
                         ["error", 'sigil: layout must be one of auto, wrap, pan (got "side")'])


@unittest.skipUnless(STRIPS, "node with TypeScript type stripping not on PATH")
class DriveTest(DriveMixin, unittest.TestCase):
    """The extension under a stand-in API."""

    def test_an_older_draw_finishing_last_never_wins(self):
        s = self.steps["a slow draw overtaken"]
        graph, tree = s["reply"]
        self.assertIn("replaced this one", graph)
        self.assertIn("Shown in the sigil widget", tree)
        self.assertIn(" · tree · ", s["lines"][0])

    def test_a_failing_redraw_is_not_asked_again_and_again(self):
        s = self.steps["a failing redraw at a new width"]
        self.assertEqual(s["reply"], "1")                    # one try at 90 columns


@unittest.skipUnless(NODE and PI, "pi not on PATH")
class PiLoaderTest(DriveMixin, unittest.TestCase):
    """The extension as an installed pi loads it (jiti) and with pi's own API."""
    pi_dir = PI


if __name__ == "__main__":
    unittest.main()
