"""The export model and the delta on a chain of nested expansions: a thousand and
more levels take about as long per level as a shallow document (they took
quadratic to cubic time: 13 s for the model at 800 levels, 70 s for a re-export's
delta at 500), and the faster lookups answer as the plain walks do."""

import random
import sys
import time
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from sigil.model import systems as ms  # noqa: E402
from sigil.publish import delta as dl  # noqa: E402
from sigil.publish import exporter  # noqa: E402
from sigil.publish import systems as em  # noqa: E402


def chain(n: int) -> str:
    return "#!spec\n" + "".join(f"[A{i}] := {{ [A{i + 1}] ~> [X{i}] : {{D}} }}\n"
                                for i in range(n))


def plan(text: str, old=None):
    model = em.build_model(text, "nest", None)
    return exporter.plan_export(model, "nest.sigil", text, None, None, old)


class DeepChain(unittest.TestCase):
    def test_the_model_nests_every_level(self):
        model = em.build_model(chain(60), "nest", None)
        parents = {k: s.parent for k, s in model.systems.items()}
        self.assertEqual(parents["A1"], "A0")
        self.assertEqual(parents["A59"], "A58")
        self.assertEqual(len(ms.ancestors("A59", {k: (None, None, None, p)
                                                   for k, p in parents.items()})), 61)

    def test_two_thousand_levels_in_seconds(self):
        text = chain(2000)
        start = time.perf_counter()
        first = plan(text)
        again = plan(text.replace("[X1999] : {D}", "[X1999] : {E}"), first.manifest)
        change = dl.delta(first.manifest, again.manifest)
        took = time.perf_counter() - start
        self.assertEqual(change["rebuild"][-1:], ["A1999"])
        self.assertLess(took, 60, f"{took:.1f}s")   # was hours (cubic and worse)


def random_systems(rng, n: int) -> dict:
    keys = [f"s{i}" for i in range(n)]
    out = {}
    for i, k in enumerate(keys):
        p = rng.choice([None] + keys)       # forward refs and cycles too
        out[k] = ("n", "expansion", None, None if p == k and rng.random() < .5 else p)
    return out


class SameAnswers(unittest.TestCase):
    def test_nesting_encloses_as_ancestors(self):
        rng = random.Random(7)
        for _ in range(200):
            systems = random_systems(rng, rng.randint(1, 12))
            for fixed in (False, True):
                nest = ms.Nesting(systems, fixed=fixed)
                for a in systems:
                    for b in systems:
                        self.assertEqual(nest.encloses(a, b), a in ms.ancestors(b, systems),
                                         (systems, a, b, fixed))

    def test_nesting_follows_moves(self):
        rng = random.Random(11)
        for _ in range(100):
            systems = random_systems(rng, rng.randint(2, 10))
            nest = ms.Nesting(systems)
            for _move in range(5):
                k = rng.choice(list(systems))
                p = rng.choice(list(systems) + [None])
                nest.set_parent(k, p)
                systems[k] = systems[k][:3] + (p,)
                for a in systems:
                    for b in systems:
                        self.assertEqual(nest.encloses(a, b), a in ms.ancestors(b, systems))

    def test_within_with_spans_as_without(self):
        rng = random.Random(3)
        for _ in range(200):
            keys = [f"s{i}" for i in range(rng.randint(1, 12))]
            news = {k: {"parent": rng.choice([None, "gone"] + keys)} for k in keys}
            spans = dl.nesting_spans(news)
            for a in keys:
                for b in keys:
                    self.assertEqual(dl.within(a, b, news, spans), dl.within(a, b, news),
                                     (news, a, b))


if __name__ == "__main__":
    unittest.main()
