"""patch-0.6.12 P1: work that grows with the input, not with its square.

Each scaling test times a command on an input (best of two) and on one four
times its size (once: noise there only slows it) and asks that the larger take less than eight times as long
(linear work: about four; the quadratic steps these fixed: about sixteen), plus
a fixed allowance for start-up. Run the suite under `heavy -s`.
"""

import random
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sigil.present.views import graph as vgraph  # noqa: E402

GROWTH = 4          # the larger input is this many times the smaller
LINEAR_BOUND = 8    # times as long, at most (quadratic would be ~GROWTH ** 2)
ALLOWANCE = 0.5     # seconds: process start-up and noise
CAP = 300           # seconds: a run that takes this long has failed anyway


def _run(args: list, text: str) -> float:
    """Seconds `sigil ARGS FILE` takes on a file holding text (exit status not
    asked: lint exits 1 on warnings)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.sigil"
        path.write_text(text, encoding="utf-8")
        start = time.perf_counter()
        done = subprocess.run([sys.executable, "-m", "sigil", *args, str(path)], cwd=ROOT,
                              capture_output=True, timeout=CAP)
        took = time.perf_counter() - start
        if b"Traceback" in done.stderr:
            raise AssertionError(done.stderr.decode(errors="replace")[-2000:])
        return took


def _best(args: list, text: str) -> float:
    return min(_run(args, text) for _ in range(2))


class _Scaling(unittest.TestCase):
    def assertLinear(self, args: list, make, n: int):
        small, large = _best(args, make(n)), _run(args, make(n * GROWTH))
        self.assertLess(large, LINEAR_BOUND * small + ALLOWANCE,
                        f"{' '.join(args)}: {small:.2f}s at {n}, {large:.2f}s at {n * GROWTH}")


def _line(segment: str):
    return lambda n: "[A] -> " + segment * n + "[C]\n"


class TestLintOneLongLine(_Scaling):
    """(a) One statement with many edges: the tokenizer, the model's modifier
    attachment and the lint rules each read the line a bounded number of times."""

    def test_chain(self):
        self.assertLinear(["lint"], _line("[B] -> "), 30000)

    def test_modifier_per_edge(self):
        self.assertLinear(["lint"], _line("[B] @timeout(3) -> "), 3000)

    def test_unknown_modifier_per_edge(self):
        self.assertLinear(["lint"], _line("[B] @async -> "), 3000)

    def test_marker_per_edge(self):
        self.assertLinear(["lint"], _line("[B]? -> "), 3000)

    def test_cardinality_per_edge(self):
        self.assertLinear(["lint"], _line("[B]×2 -> "), 3000)


def _chain(n: int) -> str:
    return "".join(f"[A{i}] := {{ [A{i + 1}] -> [X{i}] }}\n" for i in range(n))


class TestGraphViewDeepChain(_Scaling):
    """(b) The graph view of a chain of expansions: what every level reads off
    the one Scene is worked out once, and the column split bisects."""

    def test_expansion_chain(self):
        self.assertLinear(["view", "--graph", "--once", "--no-lint", "--depth", "all"],
                          _chain, 1000)


def _loop(n: int) -> str:
    return f"#!sketch\n(U) -> [A]\nloop @times {n} {{\n  [A] -> [B]\n  [B] -> [C]\n}}\n"


class TestRunViewLongLoop(_Scaling):
    """(c) The run view of a loop run many times: a lane's waits are swept once
    and each band of the ruler reads only its own labels."""

    def test_loop(self):
        n = 1000
        limits = [a for name in ("iterations", "frames", "visits", "activations")
                  for a in ("--limit", f"{name}={1000000}")]
        self.assertLinear(["view", "--run", "--once", "--no-lint", "--sim", "happy",
                           "--width", "100", *limits], _loop, n)


def _columns_before(sizes, fit):
    """graph._columns as it was before P1 (one O(n) pass per cap): the reference
    the bisecting one must agree with."""
    n = len(sizes)
    whole = [(0, n)]
    if fit is None or n < 2:
        return whole
    top = max(h for h, _w in sizes)
    while True:
        runs, a, h = [], 0, 0
        for i, (hi, _w) in enumerate(sizes):
            if i > a and h + hi > top:
                runs.append((a, i, h))
                a, h = i, 0
            h += hi
        runs.append((a, n, h))
        if len(runs) == 1:
            return whole
        wide = sum(max(w for _h, w in sizes[s:e]) for s, e, _h in runs) \
            + vgraph.COLUMN_GAP * (len(runs) - 1)
        if wide <= fit:
            return [(s, e) for s, e, _h in runs]
        top = min(h + sizes[e][0] for _s, e, h in runs[:-1])


class TestColumnsUnchanged(unittest.TestCase):
    def test_same_split_as_before(self):
        rng = random.Random(612)
        for _ in range(5000):
            sizes = [(rng.randint(0, 40), rng.randint(1, 60)) for _ in range(rng.randint(0, 30))]
            fit = rng.choice([None, 20, 40, 80, 120, 200, 400])
            self.assertEqual(vgraph._columns(sizes, fit), _columns_before(sizes, fit),
                             (sizes, fit))

    def test_range_max(self):
        rng = random.Random(6)
        values = [rng.randint(0, 99) for _ in range(70)]
        widest = vgraph._range_max(values)
        for s in range(len(values)):
            for e in range(s + 1, len(values) + 1):
                self.assertEqual(widest(s, e), max(values[s:e]))


if __name__ == "__main__":
    unittest.main()
