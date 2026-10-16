"""Tests for build.py — the multi-agent packaging of the Sigil skill.

Runs from the repo root (`python -m unittest discover tests`) or from any parent
checkout (`python -m unittest discover path/to/sigil/tests/`); build.py is loaded
by file path so no package layout is assumed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_build():
    spec = importlib.util.spec_from_file_location("sigil_build", ROOT / "build.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sigil_build"] = mod
    spec.loader.exec_module(mod)
    return mod


build = _load_build()


class VersionTest(unittest.TestCase):
    def test_the_plugin_version_is_no_older_than_the_last_release(self):
        """main once built 0.3.2 while CHANGELOG.md (and the v0.3.3 tag) said 0.3.3."""
        meta = json.loads((ROOT / "plugin" / "meta.json").read_text())["version"]
        released = re.findall(r"^## (\d+)\.(\d+)\.(\d+) — \d{4}-\d\d-\d\d",
                              (ROOT / "CHANGELOG.md").read_text(), re.M)
        newest = max(tuple(int(x) for x in v) for v in released)
        self.assertGreaterEqual(tuple(int(x) for x in meta.split(".")), newest, meta)


class PackageFilesTest(unittest.TestCase):
    def test_the_package_is_what_ships(self):
        """The plugin ships the whole sigil/ package (the playground takes it less
        the export layer): every file under it but build junk, and no top-level
        module beside build.py, which would not ship."""
        on_disk = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "sigil").rglob("*.py")
                         if "__pycache__" not in p.parts)
        self.assertEqual(build.package_files(), on_disk)
        self.assertEqual({p.name for p in ROOT.glob("*.py")}, {"build.py"})

    def test_the_required_files_are_in_the_repo(self):
        for rel in build.REQUIRED_FILES:
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertIn("sigil/cli.py", build.package_files())

    def test_build_junk_never_ships(self):
        self.assertTrue(build.is_junk(Path("sigil/core/__pycache__/lex.cpython-312.pyc")))
        self.assertTrue(build.is_junk(Path("sigil/stray.pyc")))
        self.assertFalse(build.is_junk(Path("sigil/core/lex.py")))


class BuildTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "dist"
        cls.made = build.build(cls.out, build.TARGETS, version="v9.8.7")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # -- helpers ------------------------------------------------------------

    def frontmatter(self, path: Path) -> tuple[dict, str]:
        return build.parse_frontmatter(path.read_text(encoding="utf-8"))

    def assert_sigil_skill(self, skill: Path):
        fields, body = self.frontmatter(skill / "SKILL.md")
        self.assertEqual(fields["name"], "sigil")
        self.assertRegex(fields["name"], build.SKILL_NAME_RE)
        self.assertTrue(1 <= len(fields["description"]) <= 1024)
        self.assertLessEqual(set(fields), build.SKILL_KEYS)
        scripts = skill / "scripts"
        for rel in build.package_files():
            p = scripts / rel
            self.assertTrue(p.is_file(), p)
            self.assertEqual(p.read_bytes(), (ROOT / rel).read_bytes(), p)
        for rel in build.REQUIRED_FILES:
            self.assertTrue((scripts / rel).is_file(), rel)
        self.assertTrue(os.access(scripts / build.COMMAND, os.X_OK), "bin/sigil not executable")
        self.assertEqual((scripts / build.COMMAND).read_bytes(), (ROOT / build.COMMAND).read_bytes())
        self.assertTrue((scripts / "themes" / "sigil.yaml").is_file())
        for ref in build.REFERENCES:
            self.assertTrue((skill / "references" / ref).is_file())
        return fields, body

    def all_text(self, tree: Path):
        for p in sorted(tree.rglob("*")):
            if p.is_file() and p.suffix in (".md", ".json", ".yaml", ".sh"):
                yield p, p.read_text(encoding="utf-8")

    # -- global -------------------------------------------------------------

    def test_check_mode_passes(self):
        self.assertEqual(build.check(self.out, build.TARGETS), [])

    def test_cli_check_exit_code(self):
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(build.main(["--check", "--out", str(self.out)]), 0)
        self.assertIn("check: OK", buf.getvalue())

    def test_check_detects_breakage(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            build.build(out, ["codex"])
            man = out / "codex" / "plugin.json"
            data = json.loads(man.read_text())
            data["commands"] = "./commands"          # a Claude-only key
            man.write_text(json.dumps(data))
            scripts = out / "codex" / "skills" / "sigil" / "scripts"
            (scripts / "bin" / "sigil").chmod(0o644)
            (scripts / "sigil" / "present" / "frames.py").unlink()
            errs = build.check(out, ["codex"])
            self.assertTrue(any("'commands'" in e for e in errs), errs)
            self.assertTrue(any("bin/sigil: not executable" in e for e in errs), errs)
            self.assertTrue(any("sigil/present/frames.py: missing" in e for e in errs), errs)

    def test_version_override_strips_v(self):
        man = json.loads((self.out / "claude" / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(man["version"], "9.8.7")
        self.assertTrue((self.out / "sigil-pi-9.8.7.zip").is_file())

    def test_no_absolute_paths_or_placeholders_leak(self):
        for target in ["claude", "claude-marketplace", "codex", "codex-marketplace",
                       "pi", "opencode"]:
            for p, text in self.all_text(self.out / target):
                self.assertNotIn(str(ROOT), text, p)
                self.assertNotIn("@SCRIPTS@", text, p)
                self.assertIsNone(build.ABS_LEAK_RE.search(text), p)

    def test_source_skill_is_spec_only(self):
        fields, body = self.frontmatter(ROOT / "skills" / "sigil" / "SKILL.md")
        self.assertLessEqual({"name", "description"}, set(fields))
        self.assertLessEqual(set(fields), build.SKILL_KEYS)        # spec keys only
        self.assertEqual(fields.get("license"), "MIT")
        self.assertRegex(body, build.REL_PATH_RE)     # its tools as relative scripts/ paths
        self.assertNotIn("CLAUDE_SKILL_DIR", body)
        self.assertNotIn("sigil_lint.py", body)
        self.assertNotIn("sigil_mermaid.py", body)

    def test_archives_deterministic_and_executable(self):
        with tempfile.TemporaryDirectory() as d:
            build.build(Path(d), ["pi"], version="9.8.7")
            for ext in ("zip", "tar.gz"):
                a = (self.out / f"sigil-pi-9.8.7.{ext}").read_bytes()
                b = (Path(d) / f"sigil-pi-9.8.7.{ext}").read_bytes()
                self.assertEqual(a, b, ext)
        with zipfile.ZipFile(self.out / "sigil-claude-9.8.7.zip") as z:
            names = z.namelist()
            self.assertEqual(names, sorted(names))
            info = z.getinfo("sigil-claude-9.8.7/skills/sigil/scripts/bin/sigil")
            self.assertEqual((info.external_attr >> 16) & 0o777, 0o755)
            self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
            info = z.getinfo("sigil-claude-9.8.7/skills/sigil/scripts/sigil/cli.py")
            self.assertEqual((info.external_attr >> 16) & 0o777, 0o644)
        with tarfile.open(self.out / "sigil-opencode-9.8.7.tar.gz") as t:
            m = t.getmember("sigil-opencode-9.8.7/install.sh")
            self.assertEqual(m.mode, 0o755)
            self.assertEqual(m.mtime, 0)

    # -- claude -------------------------------------------------------------

    def test_claude_plugin(self):
        root = self.out / "claude"
        man = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(man["name"], "sigil")
        self.assertRegex(man["name"], build.SKILL_NAME_RE)
        self.assertEqual(man["author"]["name"], "Ian Patrick")
        self.assertLessEqual(set(man), build.CLAUDE_KEYS | set(build.MOD_KEYS))
        for k in ("homepage", "repository"):
            if k in man:
                self.assertTrue(man[k].startswith("https://"))
        _, body = self.assert_sigil_skill(root / "skills" / "sigil")
        self.assertIn("${CLAUDE_SKILL_DIR}/scripts/", body)
        self.assertIn("${CLAUDE_SKILL_DIR}/references/language.md", body)
        self.assertNotRegex(body, r"(?<![\w./${}-])scripts/")
        for cmd in ("sigil-view", "sigil-lint"):
            fields, cbody = self.frontmatter(root / "commands" / f"{cmd}.md")
            self.assertIn("description", fields)
            self.assertIn("python3 ${CLAUDE_PLUGIN_ROOT}/skills/sigil/scripts/bin/sigil ", cbody)
            self.assertRegex(cbody, r"\$1|\$ARGUMENTS")

    def test_claude_marketplace(self):
        market = self.out / "claude-marketplace"
        mk = json.loads((market / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(mk["owner"]["name"], "Ian Patrick")
        [entry] = mk["plugins"]
        self.assertEqual(entry["source"], "./plugins/sigil")
        self.assertTrue((market / entry["source"] / ".claude-plugin" / "plugin.json").is_file())

    # -- codex --------------------------------------------------------------

    def test_codex_plugin(self):
        root = self.out / "codex"
        man = json.loads((root / "plugin.json").read_text())
        self.assertEqual(man["$schema"], build.CODEX_SCHEMA)
        self.assertRegex(man["name"], build.CODEX_NAME_RE)
        self.assertLessEqual(set(man), build.CODEX_KEYS)
        self.assertFalse((root / ".claude-plugin").exists())
        _, body = self.assert_sigil_skill(root / "skills" / "sigil")
        self.assertNotIn("CLAUDE_", body)
        self.assertRegex(body, build.REL_PATH_RE)

    def test_codex_commands_become_explicit_skills(self):
        root = self.out / "codex" / "skills"
        for cmd in ("sigil-view", "sigil-lint"):
            fields, body = self.frontmatter(root / cmd / "SKILL.md")
            self.assertEqual(fields["name"], cmd)
            self.assertLessEqual(set(fields), build.SKILL_KEYS)
            self.assertNotIn("$ARGUMENTS", body)
            self.assertNotIn("$1", body)
            self.assertIn("../sigil/scripts/", body)
            self.assertIn("<sigil-skill-dir>/scripts/bin/sigil ", body)
            policy = (root / cmd / "agents" / "openai.yaml").read_text()
            self.assertIn("allow_implicit_invocation: false", policy)

    def test_codex_marketplace(self):
        market = self.out / "codex-marketplace"
        mk = json.loads((market / ".agents" / "plugins" / "marketplace.json").read_text())
        [entry] = mk["plugins"]
        self.assertLessEqual({"name", "source", "policy", "category"}, set(entry))
        self.assertLessEqual({"installation", "authentication"}, set(entry["policy"]))
        self.assertTrue((market / entry["source"]["path"] / "plugin.json").is_file())

    # -- pi -----------------------------------------------------------------

    def test_pi_package(self):
        root = self.out / "pi"
        pkg = json.loads((root / "package.json").read_text())
        self.assertIn("pi-package", pkg["keywords"])
        self.assertIn("./skills", pkg["pi"]["skills"])
        self.assertEqual(pkg["version"], "9.8.7")
        self.assert_sigil_skill(root / "skills" / "sigil")
        for cmd in ("sigil-view", "sigil-lint"):
            fields, body = self.frontmatter(root / "prompts" / f"{cmd}.md")
            self.assertIn("description", fields)
            self.assertIn("$1", body)
            self.assertIn("<sigil-skill-dir>/scripts/bin/sigil ", body)

    # -- opencode -----------------------------------------------------------

    def test_opencode_tree(self):
        root = self.out / "opencode"
        self.assert_sigil_skill(root / "skills" / "sigil")
        self.assertTrue(os.access(root / "install.sh", os.X_OK))
        for cmd in ("sigil-view", "sigil-lint"):
            fields, body = self.frontmatter(root / "commands" / f"{cmd}.md")
            self.assertEqual(set(fields), {"description"})
            self.assertRegex(body, r"\$1|\$ARGUMENTS")

    @unittest.skipUnless(os.name == "posix", "install.sh is POSIX sh")
    def test_opencode_install_into_temp_dir(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, HOME=d, XDG_CONFIG_HOME=str(Path(d) / "cfg"))
            env.pop("OPENCODE_CONFIG_DIR", None)
            subprocess.run([str(self.out / "opencode" / "install.sh")], env=env,
                           check=True, capture_output=True)
            dest = Path(d) / "cfg" / "opencode"
            self.assertTrue(os.access(dest / "skills/sigil/scripts/bin/sigil", os.X_OK))
            self.assertTrue((dest / "skills/sigil/scripts/sigil/cli.py").is_file())
            text = (dest / "commands" / "sigil-lint.md").read_text()
            self.assertIn(str(dest / "skills" / "sigil" / "scripts" / "bin" / "sigil") + " lint", text)
            self.assertNotIn("<sigil-skill-dir>", text)

    def test_every_rule_module_ships(self):
        """check loads its rule modules from sigil/analyse/rules: each one ships,
        with the simulator, the scene and the kit it reads."""
        rules = {p.relative_to(ROOT).as_posix() for p in (ROOT / "sigil" / "analyse" / "rules").glob("*.py")}
        self.assertLessEqual({"sigil/analyse/rules/flow.py", "sigil/analyse/rules/export.py"}, rules)
        self.assertLessEqual(rules | {"sigil/model/sim/__init__.py", "sigil/model/scene.py",
                                      "sigil/present/kit.py"}, set(build.package_files()))

    def test_every_archive_ships_the_package(self):
        """Every archive holds bin/sigil (executable) and every package file
        (sigil/analyse/rules/*.py among them) under the skill's scripts/."""
        archives = sorted(p for p in self.out.iterdir()
                          if p.name.endswith(build.ARCHIVE_EXTS))
        self.assertEqual(len(archives), 2 * 6)        # 4 targets + 2 marketplaces
        for archive in archives:
            if archive.suffix == ".zip":
                with zipfile.ZipFile(archive) as z:
                    modes = {n: (z.getinfo(n).external_attr >> 16) & 0o777
                             for n in z.namelist() if not n.endswith("/")}
            else:
                with tarfile.open(archive) as t:
                    modes = {m.name: m.mode for m in t.getmembers() if m.isfile()}
            shipped = {n.split("/skills/sigil/scripts/", 1)[1]: mode for n, mode in modes.items()
                       if "/skills/sigil/scripts/" in n}
            self.assertEqual(shipped.get(build.COMMAND), 0o755, archive.name)
            for rel in build.package_files():
                self.assertEqual(shipped.get(rel), 0o644, f"{archive.name}: {rel}")
            self.assertFalse([n for n in shipped if "__pycache__" in n or n.endswith(".pyc")])

    def test_commands_name_shipped_scripts(self):
        """Every `@SCRIPTS@/…` path a command names is a file the skill ships."""
        scripts = self.out / "claude" / "skills" / "sigil" / "scripts"
        for name, _fields, body in build.load_commands():
            named = re.findall(r"@SCRIPTS@/(\S+?)[`\s]", body)
            self.assertTrue(named, name)
            for rel in named:
                self.assertTrue((scripts / rel).is_file(), f"{name}: {rel}")

    def test_the_packaged_command_runs_its_own_package(self):
        """bin/sigil puts its own folder first on the path: a packaged copy runs
        its package, not the repo's (even from the repo, with the repo on
        PYTHONPATH)."""
        import shutil, subprocess
        with tempfile.TemporaryDirectory() as d:
            scripts = Path(d) / "scripts"
            shutil.copytree(self.out / "opencode" / "skills" / "sigil" / "scripts", scripts)
            with open(scripts / "sigil" / "__init__.py", "a", encoding="utf-8") as f:
                f.write("\nimport sys as _s\n_s.stderr.write('packaged copy\\n')\n")
            r = subprocess.run([sys.executable, str(scripts / "bin" / "sigil"), "lint", "-"],
                               input="#!sketch\n[A] -> [B]\n", capture_output=True, text=True,
                               cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("packaged copy", r.stderr)

    def test_packaged_check_and_deep_lint_run(self):
        import subprocess
        sample = ("#!spec\n\n--- T ---\n(User) -> [Api] : go()\n"
                  "[Api] -> |Doc| : put({Doc})\n[Job] -> |Doc| : put({Doc})\n"
                  "|Doc| @write(Api, Job)\n")
        scripts = self.out / "opencode" / "skills" / "sigil" / "scripts"
        sigil = scripts / "bin" / "sigil"
        for argv in ([sigil, "check", "-"], [sigil, "lint", "-", "--deep"]):
            r = subprocess.run([sys.executable, *map(str, argv)], input=sample,
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("warn:5:SGC131: shared-writable-store", r.stdout)

    def test_packaged_export_runs(self):
        """`sigil export` runs from an archive's scripts: its model and readiness
        rules ship in the package, and a ready spec exports with manifest.json last."""
        import subprocess
        sample = ("#!spec\n\n--- Notes ---\n(User) -> [Api] : save({Note}) => {Ack}\n"
                  "[Api] -> |Notes| : put({Note}) => {Ack}\n")
        scripts = self.out / "claude" / "skills" / "sigil" / "scripts"
        for rel in ("sigil/publish/exporter.py", "sigil/model/systems.py",
                    "sigil/analyse/rules/export.py"):
            self.assertTrue((scripts / rel).is_file(), rel)
        with tempfile.TemporaryDirectory() as d:
            spec, dest = Path(d) / "tiny.sigil", Path(d) / "out"
            spec.write_text(sample, encoding="utf-8")
            r = subprocess.run([sys.executable, str(scripts / "bin" / "sigil"), "export", str(spec),
                                "--out", str(dest)], capture_output=True, text=True,
                               encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            man = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(list(man["systems"]), ["tiny"])

    def test_packaged_lint_runs(self):
        import subprocess
        sample = "#!sketch\n\n--- T ---\n(User) -> [API] -> |DB|\n"
        sigil = self.out / "pi" / "skills" / "sigil" / "scripts" / "bin" / "sigil"
        r = subprocess.run([sys.executable, str(sigil), "lint", "-"], input=sample,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
