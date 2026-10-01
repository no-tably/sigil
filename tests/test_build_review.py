"""Regression tests for build.py review fixes: install.sh argument handling and
paths, --check robustness (archives, broken frontmatter), --version validation
and Codex command paths.

Every install.sh run is isolated: HOME, XDG_CONFIG_HOME and OPENCODE_CONFIG_DIR
all point into a temporary directory.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_build():
    spec = importlib.util.spec_from_file_location("sigil_build_review", ROOT / "build.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sigil_build_review"] = mod
    spec.loader.exec_module(mod)
    return mod


build = _load_build()


class ReviewTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "dist"
        build.build(cls.out, build.TARGETS, version="1.2.3")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def fresh(self, targets: list[str]) -> Path:
        """A private build (for tests that break things)."""
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        out = Path(d.name) / "dist"
        build.build(out, targets, version="1.2.3")
        return out


@unittest.skipUnless(os.name == "posix", "install.sh is POSIX sh")
class InstallScriptTest(ReviewTestCase):
    def run_install(self, args: list[str], cwd: Path):
        sandbox = cwd / "sandbox"
        env = dict(os.environ, HOME=str(sandbox / "home"),
                   XDG_CONFIG_HOME=str(sandbox / "xdg"),
                   OPENCODE_CONFIG_DIR=str(sandbox / "oc"))
        r = subprocess.run([str(self.out / "opencode" / "install.sh"), *args], cwd=cwd,
                           env=env, capture_output=True, text=True)
        return r, sandbox

    def test_relative_project_dir_gives_absolute_paths(self):          # 1
        with tempfile.TemporaryDirectory() as d:
            cwd = Path(d).resolve()
            (cwd / "proj").mkdir()
            r, sandbox = self.run_install(["--project", "proj"], cwd)
            self.assertEqual(r.returncode, 0, r.stderr)
            dest = cwd / "proj" / ".opencode"
            text = (dest / "commands" / "sigil-lint.md").read_text()
            self.assertIn(f"python3 {dest}/skills/sigil/scripts/lint.py", text)
            self.assertNotIn("<sigil-skill-dir>", text)
            self.assertNotIn(build.SIGIL_DIR_NOTE_PREFIX, text)
            self.assertFalse(sandbox.exists())

    def test_missing_project_dir_fails(self):                             # 1
        with tempfile.TemporaryDirectory() as d:
            r, sandbox = self.run_install(["--project", "nope"], Path(d))
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse((Path(d) / "nope").exists())
            self.assertFalse(sandbox.exists())

    def test_help_and_unknown_arguments_do_not_install(self):             # 2
        with tempfile.TemporaryDirectory() as d:
            cwd = Path(d)
            r, sandbox = self.run_install(["--help"], cwd)
            self.assertEqual(r.returncode, 0)
            self.assertIn("usage", r.stdout)
            for args in (["-p", "x"], ["--projcet", "x"], ["--project"],
                         ["--project", "a", "b"], [""]):
                with self.subTest(args=args):
                    r, sandbox = self.run_install(args, cwd)
                    self.assertEqual(r.returncode, 2, r.stderr)
                    self.assertIn("usage", r.stderr)
            self.assertFalse(sandbox.exists())

    def test_no_argument_uses_opencode_config_dir(self):
        with tempfile.TemporaryDirectory() as d:
            r, sandbox = self.run_install([], Path(d))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((sandbox / "oc" / "commands" / "sigil-view.md").is_file())
            self.assertFalse((sandbox / "xdg").exists())

    def test_sed_special_characters_in_install_path(self):               # 11
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d).resolve() / r"a&b|c\d"
            proj.mkdir()
            r, _ = self.run_install(["--project", str(proj)], Path(d))
            self.assertEqual(r.returncode, 0, r.stderr)
            text = (proj / ".opencode" / "commands" / "sigil-lint.md").read_text()
            self.assertIn(f"{proj}/.opencode/skills/sigil/scripts/lint.py", text)


class CheckRobustnessTest(ReviewTestCase):
    def assert_check_reports(self, out: Path, targets: list[str], needle: str):
        errs = build.check(out, targets)
        self.assertTrue(any(needle in e for e in errs), errs)

    def test_missing_plugin_archive_detected(self):                      # 3
        for name in ("sigil-claude-1.2.3.zip", "sigil-claude-1.2.3.tar.gz",
                     "sigil-claude-marketplace-1.2.3.tar.gz"):
            with self.subTest(name=name):
                out = self.fresh(["claude"])
                (out / name).unlink()
                self.assert_check_reports(out, ["claude"], name)

    def test_missing_opencode_archive_detected(self):                    # 3
        out = self.fresh(["opencode"])
        (out / "sigil-opencode-1.2.3.tar.gz").unlink()
        self.assert_check_reports(out, ["opencode"], "sigil-opencode-1.2.3.tar.gz")
        (out / "sigil-opencode-1.2.3.zip").unlink()
        self.assert_check_reports(out, ["opencode"], "archive version")

    def test_command_without_frontmatter_is_an_error(self):              # 4
        out = self.fresh(["claude", "pi", "opencode"])
        for rel in ("claude/commands/sigil-lint.md", "pi/prompts/sigil-lint.md",
                    "opencode/commands/sigil-lint.md"):
            (out / rel).write_text("no frontmatter here\n")
        (out / "pi" / "prompts" / "sigil-view.md").write_bytes(b"\xff\xfe---\n")
        errs = build.check(out, ["claude", "pi", "opencode"])
        for rel in ("claude/commands/sigil-lint.md", "pi/prompts/sigil-lint.md",
                    "opencode/commands/sigil-lint.md", "pi/prompts/sigil-view.md"):
            self.assertTrue(any(rel in e for e in errs), (rel, errs))

    def test_codex_command_skill_without_skill_md(self):                 # 4
        out = self.fresh(["codex"])
        (out / "codex" / "skills" / "sigil-view" / "SKILL.md").unlink()
        self.assert_check_reports(out, ["codex"], "sigil-view/SKILL.md: missing")

    def test_odd_marketplace_shapes(self):                               # 17
        out = self.fresh(["codex"])
        mk = out / "codex-marketplace" / ".agents" / "plugins" / "marketplace.json"
        mk.write_text('{"plugins": [{"name": "x", "source": "./plugins/sigil", '
                      '"policy": "open", "category": "c"}, "junk"]}')
        self.assert_check_reports(out, ["codex"], "plugin source has no plugin.json")
        mk.write_text("[1, 2]")
        self.assert_check_reports(out, ["codex"], "expected a JSON object")

    def test_placeholder_note_checked(self):                             # 16
        out = self.fresh(["pi"])
        p = out / "pi" / "prompts" / "sigil-lint.md"
        p.write_text(p.read_text().replace(build.SIGIL_DIR_NOTE, ""))
        self.assert_check_reports(out, ["pi"], "<sigil-skill-dir> note")


class VersionTest(unittest.TestCase):
    def test_bad_versions_rejected(self):                                # 5
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "dist"
            for bad in ("../../evil", "1.2", "1.2.3/x", "v", ""):
                with self.subTest(version=bad):
                    with contextlib.redirect_stderr(io.StringIO()), \
                            self.assertRaises(SystemExit) as cm:
                        build.main(["--out", str(out), "--version", bad])
                    self.assertEqual(cm.exception.code, 2)
                    with self.assertRaises(ValueError):
                        build.build(out, ["pi"], version=bad or "x")
            self.assertEqual(list(Path(d).rglob("*evil*")), [])

    def test_good_versions_accepted(self):
        for good, want in (("v1.2.3", "1.2.3"), ("1.2.3-rc.1", "1.2.3-rc.1"),
                           ("0.1.0+build.5", "0.1.0+build.5")):
            self.assertEqual(build.normalize_version(good), want)


class CodexPathsTest(ReviewTestCase):
    def test_commands_use_skill_dir_placeholder(self):                   # 6
        for cmd in ("sigil-view", "sigil-lint"):
            body = (self.out / "codex" / "skills" / cmd / "SKILL.md").read_text()
            self.assertIn("<sigil-skill-dir>/scripts/", body)
            self.assertIn(build.SIGIL_DIR_NOTE, body)
            self.assertNotIn("python3 ../", body)

    def test_dollar_one_not_confused_with_dollar_ten(self):              # 10
        out = self.fresh(["codex"])
        errs = build.check(out, ["codex"])
        self.assertEqual(errs, [])
        p = out / "codex" / "skills" / "sigil-lint" / "SKILL.md"
        p.write_text(p.read_text() + "\nCosts $10.\n")
        self.assertEqual(build.check(out, ["codex"]), [])


class FrontmatterTest(unittest.TestCase):
    def test_crlf_empty_and_bools(self):                                 # 9, 22
        fields, body = build.parse_frontmatter("---\r\na: true\r\nb: \"true\"\r\n---\r\nx\r\n")
        self.assertEqual(fields, {"a": True, "b": "true"})
        self.assertEqual(body, "x\n")
        self.assertEqual(build.parse_frontmatter("---\n---\nbody"), ({}, "body"))
        text = build.emit_frontmatter(fields, "x\n")
        self.assertIn("a: true\n", text)
        self.assertIn('b: "true"\n', text)


class DeterminismTest(ReviewTestCase):
    def test_two_builds_byte_identical(self):
        again = self.fresh(build.TARGETS)
        archives = sorted(p.name for p in self.out.iterdir() if p.is_file())
        self.assertEqual(len(archives), 12)
        self.assertEqual(archives, sorted(p.name for p in again.iterdir() if p.is_file()))
        for name in archives:
            self.assertEqual((self.out / name).read_bytes(), (again / name).read_bytes(),
                             name)


if __name__ == "__main__":
    unittest.main()
