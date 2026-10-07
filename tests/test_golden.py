"""Golden outputs: every input drawn every way matches tests/golden/ byte for byte.

The kit is tools/golden.py (inputs, variants, how each drawing is made). After an
intended change to a drawing, rewrite the goldens with `tools/golden.py --update`
and review the diff; `tools/golden.py --check --diff` shows what differs.

Run:  python3 -m unittest tests.test_golden
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


golden = _load("sigil_golden", _DIR / "tools" / "golden.py")

_SHOWN_CHARS = 6000             # of the --check --diff report, in a failure message


class TestGolden(unittest.TestCase):
    def test_every_drawing_matches_its_golden(self):
        # a subprocess: the kit pins PYTHONHASHSEED (see golden.HASH_SEED)
        r = subprocess.run([sys.executable, str(_DIR / "tools" / "golden.py"), "--check", "--diff"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "drawings differ from tests/golden/ "
                         "(tools/golden.py --update after an intended change):\n"
                         + r.stdout[:_SHOWN_CHARS] + r.stderr)

    def test_every_input_has_every_variant(self):
        inputs = golden.collect_inputs(_DIR)
        self.assertGreaterEqual(len(inputs), 6)
        runs = golden.run_inputs(_DIR)
        self.assertIn("01-checkout", runs)
        self.assertIn("executions", runs)
        expected = {f"{i.name}/{v.name}.txt" for i in inputs for v in golden.VARIANTS
                    if golden.drawn_in(v, i, runs)}
        expected |= {f"{i.name}/{golden.MERMAID}.txt" for i in inputs}
        self.assertEqual(set(golden.read_goldens(golden.GOLDEN_DIR)), expected)

    def test_goldens_are_plain_unless_coloured(self):
        for rel, text in golden.read_goldens(golden.GOLDEN_DIR).items():
            with self.subTest(rel):
                self.assertEqual("\x1b[" in text, rel.endswith("-color.txt"))


class TestKit(unittest.TestCase):
    def test_examples_inputs_skip_drawings_and_name_by_header(self):
        md = ("```\n#!spec\n--- Agent Memory ---\n[A] -> [B]\n```\n"
              "```text\n[A]\n```\n"
              "```\n[C] -> [D]\n```\n")
        got = golden.examples_inputs(md)
        self.assertEqual([i.name for i in got], ["examples-01-agent-memory", "examples-02"])
        self.assertEqual(got[1].text, "[C] -> [D]\n")

    def test_examples_inputs_skip_blocks_already_drawn(self):
        md = "```\n[A] -> [B]\n```\n```\n[C] -> [D]\n```\n"
        got = golden.examples_inputs(md, drawn=frozenset({"[A] -> [B]\n"}))
        self.assertEqual([(i.name, i.text) for i in got], [("examples-01", "[C] -> [D]\n")])

    def test_site_example_repeated_in_examples_md_is_drawn_once(self):
        # examples.md opens with the site's first example; Example A stays examples-01
        inputs = {i.name: i.text for i in golden.collect_inputs(_DIR)}
        md = (_DIR / "examples.md").read_text(encoding="utf-8")
        self.assertIn("```\n" + inputs["00-shortener"] + "```", md)
        self.assertIn("(User) -> [Web]", inputs["examples-01"])
        self.assertNotIn(inputs["00-shortener"],
                         [t for n, t in inputs.items() if n.startswith("examples-")])

    def test_compare_sorts_missing_changed_stale(self):
        drift = golden.compare({"a/x.txt": "1", "b/y.txt": "2"},
                               {"a/x.txt": "1!", "c/z.txt": "3"})
        self.assertEqual((drift.missing, drift.changed, drift.stale),
                         (["c/z.txt"], ["a/x.txt"], ["b/y.txt"]))
        self.assertFalse(golden.compare({"a": "1"}, {"a": "1"}))


if __name__ == "__main__":
    unittest.main()
