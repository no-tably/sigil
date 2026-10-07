"""Tests for the pi viewer extension (plugin/pi) and its packaging.

Covers:
  - build.py: the pi tree carries the extension (the manifest names it, the
    Claude Code mod's logic.ts beside it, pane.py and frames.py beside the
    tools, no test shipped); --check catches a missing logic.ts, a foreign
    import and a manifest that does not name the extension;
  - the extension's widget helpers (truecolour rows cut to the width, /sigil's
    own words), through node's type stripping;
  - plugin/pi/tests/drive.mjs driving the built extension: registration,
    the 144-column rule for a widget nobody asked for, /sigil opening it at any
    width, a run stepped, close, a missing file, no UI, and a multiplexer split
    (a fake tmux on PATH) — once with a stand-in API, and again through an
    installed pi's own loader when `pi` is on PATH.

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
        env = dict(os.environ, PATH=f"{fake}{os.pathsep}{os.environ['PATH']}",
                   FAKE_TMUX_LOG=str(cls.tmux_log), TMPDIR=str(tmp))
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
        self.assertEqual(self.out["commands"], ["sigil"])
        self.assertEqual(self.out["flags"], ["sigil-display"])

    def test_an_unasked_widget_waits_below_144_columns(self):
        s = self.steps["narrow tool call"]
        self.assertFalse(s["widget"])
        self.assertIn("waiting", s["reply"])
        self.assertIn("this terminal has 100", s["reply"])
        self.assertIn("/sigil", s["reply"])
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
        # the run's trail and narration line under the drawing, and in the reply
        plain = [re.sub(r"\x1b\[[0-9;]*m", "", ln) for ln in self.steps["next"]["lines"]]
        self.assertTrue(any(ln.startswith("trail  (") for ln in plain), plain)
        self.assertTrue(any(ln.startswith("› ") and len(ln) > 2 for ln in plain), plain)
        self.assertIn("\nnow: ", run["reply"])

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


@unittest.skipUnless(STRIPS, "node with TypeScript type stripping not on PATH")
class DriveTest(DriveMixin, unittest.TestCase):
    """The extension under a stand-in API."""


@unittest.skipUnless(NODE and PI, "pi not on PATH")
class PiLoaderTest(DriveMixin, unittest.TestCase):
    """The extension as an installed pi loads it (jiti) and with pi's own API."""
    pi_dir = PI


if __name__ == "__main__":
    unittest.main()
