"""A dialect's THEME hook and the theme precedence (design/sigil.sigil: [Themes]
reads the dialect's THEME through Core's dialect hooks).

Covers: dialects.theme_hook (a name, a path beside the dialect module, a bad
value); themes.load's precedence (an explicit spec, then the dialect's THEME,
then the default); the same precedence in `sigil view --once`, `sigil frames
draw` and `sigil highlight --json`; a THEME that cannot be found errors as a
bad --theme does (exit 2, or frames' {"error"}); `sigil highlight --stream`'s
{"dialect"} request: the switch, null back to core, a dialect that fails to load
(the old one kept), and the theme following the dialect until a theme is asked
for explicitly. Everything runs in-process on a two-line document.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli  # noqa: E402
from sigil.core import dialects  # noqa: E402
from sigil.present import kit, themes  # noqa: E402

PROBES = ROOT / "tests" / "fixtures" / "theme_dialect"
BY_PATH = PROBES / "dialect.py"         # THEME = "probe.yaml" (beside it)
BY_NAME = PROBES / "named.py"           # THEME = "probe" (on $SIGIL_THEME_PATH)
PROBE = "#123456"                       # probe.yaml's service / operator colour
SGR = "38;2;18;52;86"                   # the same colour as a truecolour escape
DEFAULT = themes.load(themes.DEFAULT)["kinds"]["service"]
DOC = "[A] -> [B] : go({X})\n"
ENV = {"SIGIL_THEME_PATH": str(PROBES)}


def run(argv, stdin: str | None = None, env: dict | None = None):
    """cli.main in-process: (exit code, stdout, stderr). SIGIL_THEME and
    SIGIL_DIALECT are unset unless `env` sets them."""
    out, err = io.StringIO(), io.StringIO()
    clean = {k: v for k, v in os.environ.items() if k not in ("SIGIL_THEME", "SIGIL_DIALECT")}
    patches = [contextlib.redirect_stdout(out), contextlib.redirect_stderr(err),
               mock.patch.dict(os.environ, {**clean, **(env or {})}, clear=True)]
    if stdin is not None:
        patches.append(mock.patch.object(sys, "stdin", io.StringIO(stdin)))
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class _Doc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.doc = self.dir / "doc.sigil"
        self.doc.write_text(DOC, encoding="utf-8")
        self.addCleanup(kit.use_dialect, None)
        self.addCleanup(kit.apply_theme, themes.load(themes.DEFAULT))

    def bad_dialect(self, theme) -> Path:
        """A dialect file in the temp folder whose THEME is `theme`."""
        path = self.dir / f"bad{len(list(self.dir.glob('bad*.py')))}.py"
        path.write_text(f"NAME = 'bad'\nTHEME = {theme!r}\n", encoding="utf-8")
        return path

    def service(self, highlighted: str) -> str:
        """The colour of [A]'s name in a `highlight --json` answer."""
        runs = json.loads(highlighted)["lines"][0]
        return next(c for text, role, c in runs if role == "kinds.service")


class TestHook(_Doc):
    def test_path_is_read_beside_the_dialect(self):
        d = dialects.load(str(BY_PATH))
        self.assertEqual(dialects.theme_hook(d), ("probe.yaml", PROBES.resolve()))
        self.assertEqual(themes.load(None, d)["kinds"]["service"], PROBE)

    def test_name_is_looked_up_as_theme_names_are(self):
        d = dialects.load(str(BY_NAME))
        with mock.patch.dict(os.environ, ENV):
            self.assertEqual(themes.load(None, d)["name"], "probe")
        with self.assertRaisesRegex(themes.ThemeError, r"'theme-named' THEME: unknown theme"):
            themes.load(None, d)

    def test_precedence(self):
        d = dialects.load(str(BY_PATH))
        self.assertEqual(themes.load("sigil", d)["kinds"]["service"], DEFAULT)
        self.assertIsNone(dialects.theme_hook(None))
        self.assertIsNone(dialects.theme_hook(types.SimpleNamespace(NAME="plain")))
        with mock.patch.dict(os.environ, {"SIGIL_THEME": "sigil"}):
            self.assertEqual(themes.chosen(None, d)[0], "probe.yaml")
            self.assertEqual(themes.chosen(None, None)[0], "sigil")

    def test_not_a_string_is_refused(self):
        for value in (3, "", ["probe"]):
            with self.subTest(value=value), self.assertRaisesRegex(
                    dialects.DialectError, "THEME must be a theme name or a path"):
                dialects.theme_hook(types.SimpleNamespace(NAME="x", THEME=value))

    def test_a_theme_file_is_data_with_the_same_errors(self):
        bad = self.dir / "broken.yaml"
        bad.write_text("kinds:\n  - service\n", encoding="utf-8")
        d = dialects.load(str(self.bad_dialect("broken.yaml")))
        with self.assertRaises(themes.ThemeError) as caught:
            themes.load(None, d)
        with self.assertRaises(themes.ThemeError) as direct:
            themes.load(str(bad))
        self.assertEqual(str(caught.exception), f"sigil dialect 'bad' THEME: {direct.exception}")


class TestCommands(_Doc):
    def test_view_once(self):
        base = ["view", str(self.doc), "--once", "--color", "always", "--no-lint"]
        code, out, _ = run(base + ["--dialect", str(BY_PATH)])
        self.assertEqual(code, 0)
        self.assertIn(SGR, out)
        code, out, _ = run(base + ["--dialect", str(BY_NAME)], env=ENV)
        self.assertIn(SGR, out)
        code, out, _ = run(base + ["--dialect", str(BY_PATH), "--theme", "sigil"])
        self.assertNotIn(SGR, out)
        code, out, _ = run(base)
        self.assertNotIn(SGR, out)

    def test_frames_draw(self):
        def styles(*flags, env=None):
            code, out, _ = run(["frames", "draw", str(self.doc), *flags], env=env)
            self.assertEqual(code, 0)
            return json.loads(out)
        self.assertIn(PROBE, json.dumps(styles("--dialect", str(BY_PATH))["styles"]))
        self.assertIn(PROBE, json.dumps(styles("--dialect", str(BY_NAME), env=ENV)["styles"]))
        self.assertNotIn(PROBE, json.dumps(
            styles("--dialect", str(BY_PATH), "--theme", "sigil")["styles"]))
        self.assertNotIn(PROBE, json.dumps(styles()["styles"]))

    def test_highlight_json(self):
        def hl(*flags, env=None):
            code, out, _ = run(["highlight", str(self.doc), "--json", *flags], env=env)
            self.assertEqual(code, 0)
            return json.loads(out)["theme"], self.service(out)
        self.assertEqual(hl("--dialect", str(BY_PATH)), ("probe", PROBE))
        self.assertEqual(hl("--dialect", str(BY_NAME), env=ENV), ("probe", PROBE))
        self.assertEqual(hl("--dialect", str(BY_PATH), "--theme", "sigil"), ("sigil", DEFAULT))
        self.assertEqual(hl(), ("sigil", DEFAULT))
        self.assertEqual(hl(env={"SIGIL_DIALECT": str(BY_PATH)}), ("probe", PROBE))

    def test_a_bad_theme_errors_as_a_bad_flag_does(self):
        missing = str(self.bad_dialect("nope"))
        for argv in (["view", str(self.doc), "--once"], ["highlight", str(self.doc), "--json"]):
            with self.subTest(cmd=argv[0]):
                flag = run(argv + ["--theme", "nope"])
                hook = run(argv + ["--dialect", missing])
                self.assertEqual((flag[0], hook[0]), (2, 2))
                self.assertEqual((flag[1], hook[1]), ("", ""))
                self.assertIn("unknown theme 'nope'", hook[2])
                self.assertIn("THEME", hook[2])
        flag = run(["frames", "draw", str(self.doc), "--theme", "nope"])
        hook = run(["frames", "draw", str(self.doc), "--dialect", missing])
        self.assertEqual((flag[0], hook[0]), (0, 0))
        self.assertIn("unknown theme 'nope'", json.loads(hook[1])["error"])
        self.assertIn("unknown theme 'nope'", json.loads(flag[1])["error"])
        code, _, err = run(["view", str(self.doc), "--once", "--dialect",
                            str(self.bad_dialect(7))])
        self.assertEqual(code, 2)
        self.assertIn("THEME must be", err)


class TestStream(_Doc):
    def stream(self, *requests, flags=(), env=None) -> list:
        lines = "".join(json.dumps(r) + "\n" for r in requests)
        code, out, err = run(["highlight", "--stream", *flags], stdin=lines, env=env)
        self.assertEqual((code, err), (0, ""))
        return [json.loads(ln) for ln in out.splitlines()]

    def colour(self, answer: dict) -> str:
        return next(c for text, role, c in answer["lines"][0] if role == "kinds.service")

    def test_switch_follows_the_dialect_theme(self):
        line = {"lines": ["[A] -> [B]"]}
        a = self.stream({"id": 1, **line},
                        {"id": 2, "dialect": str(BY_PATH)},
                        {"id": 3, **line},
                        {"id": 4, "dialect": None, **line})
        self.assertEqual(self.colour(a[0]), DEFAULT)
        self.assertEqual(a[1], {"id": 2, "dialect": "theme-probe", "theme": "probe"})
        self.assertEqual(self.colour(a[2]), PROBE)
        self.assertEqual((a[3]["dialect"], a[3]["theme"]), (None, "sigil"))
        self.assertEqual(self.colour(a[3]), DEFAULT)

    def test_null_is_core_whatever_the_environment_says(self):
        a = self.stream({"id": 1, "dialect": None}, env={"SIGIL_DIALECT": str(BY_PATH)})
        self.assertEqual(a, [{"id": 1, "dialect": None, "theme": "sigil"}])

    def test_explicit_theme_holds(self):
        line = ["[A] -> [B]"]
        a = self.stream({"id": 1, "dialect": str(BY_PATH), "lines": line},
                        flags=("--theme", "sigil"))
        self.assertEqual(set(a[0]), {"id", "dialect", "start", "lines", "carry"})
        self.assertEqual(self.colour(a[0]), DEFAULT)
        a = self.stream({"id": 1, "theme": "sigil"},
                        {"id": 2, "dialect": str(BY_PATH), "lines": line})
        self.assertNotIn("theme", a[1])
        self.assertEqual(self.colour(a[1]), DEFAULT)

    def test_order_dialect_then_theme_then_lines(self):
        a = self.stream({"id": 1, "dialect": str(BY_PATH), "theme": "sigil",
                         "lines": ["[A]"]},
                        {"id": 2, "dialect": None},
                        {"id": 3, "dialect": str(BY_PATH), "lines": ["[A]"]})
        self.assertEqual((a[0]["dialect"], a[0]["theme"]), ("theme-probe", "sigil"))
        self.assertEqual(self.colour(a[0]), DEFAULT)
        self.assertNotIn("theme", a[1])                   # the theme was asked for
        self.assertEqual(self.colour(a[2]), DEFAULT)

    def test_a_failed_switch_keeps_the_old_dialect(self):
        broken = self.dir / "broken.py"
        broken.write_text("NAME = 'broken'\nraise RuntimeError('no')\n", encoding="utf-8")
        a = self.stream({"id": 1, "dialect": str(BY_PATH)},
                        {"id": 2, "dialect": str(self.dir / "absent.py")},
                        {"id": 3, "dialect": str(broken)},
                        {"id": 4, "dialect": str(self.bad_dialect("nope"))},
                        {"id": 5, "dialect": 3},
                        {"id": 6, "dialect": str(BY_PATH), "theme": "nope"},
                        {"id": 7, "lines": ["[A]"]})
        for answer in a[1:6]:
            self.assertEqual(set(answer), {"id", "error"}, answer)
        self.assertIn("unknown sigil dialect", a[1]["error"])
        self.assertIn("RuntimeError: no", a[2]["error"])
        self.assertIn("THEME: unknown theme 'nope'", a[3]["error"])
        self.assertIn("dialect must be", a[4]["error"])
        self.assertEqual(self.colour(a[6]), PROBE)        # still the probe, unforced

    def test_a_request_needs_a_part(self):
        a = self.stream({"id": 1, "start": 0})
        self.assertEqual(a, [{"id": 1, "error": "a request holds lines, a theme or a dialect"}])


if __name__ == "__main__":
    unittest.main()
