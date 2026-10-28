"""Limits in the document (design round 9): a `name=N` word on the `#%` line is
a simulator limit (`#% daemon frames=300000`). Core's kinds keeps the pairs as
written (Kind.limits); the simulator owns the names and the one merge
(sim.limits_for: the defaults, scaled < the document's < --limit, a flag wins);
lint judges each pair with the simulator's validator (SGL096); check, the export
gate, view, `--sim` and `frames draw` start from the document's limits, and
`check --json` says where each limit came from (limit_sources)."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sigil import cli  # noqa: E402
from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse import lint as lint_mod  # noqa: E402
from sigil.analyse.lint import lint  # noqa: E402
from sigil.core import kinds  # noqa: E402
from sigil.core.parse import parse_document  # noqa: E402
from sigil.model import sim  # noqa: E402
from sigil.publish import exporter  # noqa: E402

CHAIN = "(User) -> [A] -> [B] -> [C] -> [D]\n"
SPEC = """(User) -> [Shop] : buy({Order}) => {Receipt}
[Shop] -> [Billing] : charge({Order}) => {Receipt}

[Shop] := {
  [Cart] -> |Db| : save({Order}) => {Ack}
}
"""


def doc(kind_line: str, body: str = CHAIN, mode: str = "spec") -> str:
    return f"#!{mode}\n{kind_line}\n{body}" if kind_line else f"#!{mode}\n{body}"


def rules(text: str, code: str) -> list:
    return [(d.line, d.message) for d in lint(text).diagnostics if d.rule == code]


def run_cli(argv: list) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class KindKeepsTheLimits(unittest.TestCase):
    def kind(self, line: str):
        return parse_document(doc(line)).kind

    def test_pairs_are_kept_apart_from_the_kind_words(self):
        k = self.kind("#% daemon frames=300000 activations=80000")
        self.assertEqual(k.shape, "daemon")
        self.assertEqual(k.words, ("daemon",))
        self.assertEqual(k.limits, ("frames=300000", "activations=80000"))
        self.assertEqual(k.text, "daemon")
        self.assertEqual(k.read.words, ("daemon", "frames=300000", "activations=80000"))

    def test_a_line_of_limits_alone_is_the_default_kind(self):
        k = self.kind("#% frames=300000")
        self.assertEqual((k.shape, k.reach, k.concurrency), ("service", "networked", "concurrent"))
        self.assertEqual((k.words, k.limits, k.off), ((), ("frames=300000",), ()))

    def test_pairs_as_written_in_order_whatever_they_say(self):
        k = self.kind("#% frmes=3 job depth=0 frames=1 frames=2  # a note")
        self.assertEqual(k.limits, ("frmes=3", "depth=0", "frames=1", "frames=2"))
        self.assertEqual(k.words, ("job",))

    def test_no_line_no_limits(self):
        self.assertEqual(parse_document(doc("")).kind.limits, ())
        self.assertEqual(kinds.split_words(("a", "b=1", "c")), (("a", "c"), ("b=1",)))


class TheOneMerge(unittest.TestCase):
    def test_defaults_then_document_then_flags(self):
        self.assertEqual(sim.limits_for(), sim.Limits())
        got = sim.limits_for(("frames=300000", "depth=5"), ("depth=7",))
        self.assertEqual((got.frames, got.depth), (300000, 7))
        self.assertIs(type(got.frames), int)            # a document's limit is never scaled
        self.assertIs(type(got.activations), sim.Floor)  # an unset default still is

    def test_a_flag_wins_lowered_too(self):
        self.assertEqual(sim.limits_for(("frames=300000",), ("frames=10",)).frames, 10)
        self.assertEqual(sim.limits_for(("hop=8",), ("hop=4",)).hop, 4)   # at its default

    def test_what_lint_refuses_a_run_ignores(self):
        self.assertEqual(sim.usable_limits(("frmes=3", "depth=0", "x=", "frames=9", "frames=2")),
                         ("frames=9",))
        self.assertEqual(sim.limits_for(("depth=0", "frames=9", "frames=2")).frames, 9)

    def test_a_flag_the_validator_refuses_raises_as_before(self):
        with self.assertRaisesRegex(ValueError, r"^--limit 'nope': unknown"):
            sim.limits_for((), ("nope=3",))
        with self.assertRaisesRegex(ValueError, r"^--limit frames: must be at least 1"):
            sim.limits_from(["frames=0"])

    def test_a_given_limits_is_used_as_it_is(self):
        given = sim.Limits(frames=10)
        self.assertIs(sim.limits_for(("frames=300000", "depth=5"), given), given)

    def test_sources(self):
        merged = sim.limits_for(("frames=300000",), ("depth=5",))
        grown = merged._replace(activations=900)
        src = sim.limit_sources(("frames=300000",), ("depth=5",), merged, grown)
        self.assertEqual(set(src), set(sim.Limits._fields))
        self.assertEqual((src["frames"], src["depth"], src["activations"], src["hop"]),
                         ("document", "flag", "scaled", "default"))
        self.assertEqual(sim.limit_sources((), sim.Limits(stack=9))["stack"], "flag")
        self.assertEqual(set(sim.LIMIT_SOURCES), {"default", "scaled", "document", "flag"})


class LintJudgesThePairs(unittest.TestCase):
    def test_a_good_line_is_clean(self):
        for line in ("#% daemon frames=300000 activations=80000", "#% frames=300000"):
            self.assertEqual([d.format() for d in lint(doc(line)).diagnostics], [], line)

    def test_refused_and_doubled_in_the_validators_words(self):
        text = doc("#% daemon frmes=3 depth=0 frames=4 frames=5 stack=abc")
        names = ", ".join(sim.Limits._fields)
        self.assertEqual(rules(text, "SGL096"), [
            (2, f"limit 'frmes': unknown (one of {names})."),
            (2, "limit depth: must be at least 1."),
            (2, "limit frames: named twice on the `#%` line; a run takes the first."),
            (2, "limit 'stack=abc': expected NAME=N."),
        ])
        self.assertEqual(rules(text, "SGL093"), [])
        self.assertTrue(all(d.severity == "error" for d in lint(text).diagnostics
                            if d.rule == "SGL096"))

    def test_the_message_is_the_flags(self):
        for pair in ("frmes=3", "depth=0", "stack=abc"):
            with self.assertRaises(ValueError) as caught:
                sim.limits_from([pair])
            (_line, message), = rules(doc(f"#% {pair}"), "SGL096")
            self.assertEqual(message, str(caught.exception).replace("--limit ", "limit ", 1) + ".")

    def test_an_unread_line_is_not_judged(self):
        text = doc("#% frames=3", body="#% frmes=3\n" + CHAIN)
        self.assertEqual(rules(text, "SGL096"), [])
        self.assertEqual([d.rule for d in lint(text).diagnostics], ["SGL094"])

    def test_kind_words_are_still_judged_beside_limits(self):
        self.assertEqual(len(rules(doc("#% demon frames=3"), "SGL093")), 1)
        self.assertEqual(len(rules(doc("#%"), "SGL093")), 1)    # no word at all


class CheckStartsFromTheDocument(unittest.TestCase):
    def cut(self, report) -> list:
        return [f for f in report.findings if f.rule.id == "SGC090"]

    def test_the_documents_limit_bounds_the_runs(self):
        self.assertFalse(self.cut(ck.check(doc(""))))
        rep = ck.check(doc("#% frames=3"))
        self.assertTrue(self.cut(rep))
        self.assertEqual(rep.limits["frames"], 3)
        self.assertEqual(rep.limit_sources["frames"], "document")

    def test_a_flag_lays_over_it(self):
        rep = ck.check(doc("#% frames=3"), limits=("frames=5000",))
        self.assertFalse(self.cut(rep))
        self.assertEqual((rep.limits["frames"], rep.limit_sources["frames"]), (5000, "flag"))
        rep = ck.check(doc("#% frames=5000"), limits=("frames=3",))
        self.assertTrue(self.cut(rep))

    def test_as_a_flag_gives_the_same_result(self):
        # the shape a host writes today as flags, written in the document instead
        written = ck.check(doc("#% daemon frames=300000 activations=80000", SPEC)).to_dict()
        flagged = ck.check(doc("#% daemon", SPEC),
                           limits=("frames=300000", "activations=80000")).to_dict()
        sources = written.pop("limit_sources"), flagged.pop("limit_sources")
        self.assertEqual(written, flagged)
        self.assertEqual((sources[0]["frames"], sources[1]["frames"]), ("document", "flag"))
        self.assertEqual(written["limits"]["frames"], 300000)
        self.assertEqual(written["kind"], {"words": "daemon", "off": written["kind"]["off"]})

    def test_without_document_limits_the_limits_are_as_before(self):
        rep = ck.check(doc("", SPEC))
        prog_sized = sim.sized(sim.Limits(), sim.canonical(parse_document(doc("", SPEC))))
        self.assertEqual({k: rep.limits[k] for k in sim.Limits._fields}, prog_sized._asdict())
        self.assertEqual(set(rep.limit_sources.values()) - {"default", "scaled"}, set())
        self.assertEqual(list(rep.to_dict())[:4], ["mode", "k", "limits", "limit_sources"])

    def test_scaled_says_so(self):
        big = "".join(f"[N{i}] -> [N{i + 1}]\n" for i in range(40))
        rep = ck.check(doc("", "(User) -> [N0]\n" + big), mode="sketch")
        self.assertGreater(rep.limits["frames"], 2000)
        self.assertEqual(rep.limit_sources["frames"], "scaled")

    def test_check_json_on_the_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.sigil"
            path.write_text(doc("#% frames=3000", SPEC), encoding="utf-8")
            code, out, _err = run_cli(["check", str(path), "--json", "--limit", "depth=5"])
            data = json.loads(out)
            self.assertEqual((data["limits"]["frames"], data["limits"]["depth"]), (3000, 5))
            self.assertEqual((data["limit_sources"]["frames"], data["limit_sources"]["depth"],
                              data["limit_sources"]["hop"]), ("document", "flag", "default"))
            self.assertNotIn("budget", data["limit_sources"])
            self.assertNotIn("kind", data)                # a line of limits names no kind


class GateViewAndFrames(unittest.TestCase):
    def test_the_export_gate_reads_the_documents_limits(self):
        text = doc("#% frames=3", SPEC)
        blocking = exporter.gate(text, None, lint_mod, ck, ())
        self.assertTrue(any("SGC090" in b for b in blocking), blocking)
        self.assertEqual(exporter.gate(text, None, lint_mod, ck, ("frames=5000",)), ())
        self.assertEqual(exporter.gate(doc("#% frames=5000", SPEC), None, lint_mod, ck, ()), ())

    def test_a_refused_limit_blocks_the_export(self):
        blocking = exporter.gate(doc("#% frmes=5000", SPEC), None, lint_mod, ck, ())
        self.assertTrue(blocking and all("SGL096" in b for b in blocking), blocking)

    def outcome(self, text: str, *flags) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.sigil"
            path.write_text(text, encoding="utf-8")
            limit = [x for f in flags for x in ("--limit", f)]
            _code, out, _err = run_cli(["view", str(path), "--sim", "happy", "--json", *limit])
            sim_json = json.loads(out)["outcome"]
            _code, out, _err = run_cli(["frames", "draw", str(path), "--view", "run",
                                        "--scenario", "happy", *limit])
            drawn = json.loads(out)
            self.assertEqual(drawn["outcome"], sim_json)
            _code, out, _err = run_cli(["view", str(path), "--sim", "all", "--json", *limit])
            (batch,) = json.loads(out)["scenarios"]
            self.assertEqual(batch["outcome"], sim_json)
            return sim_json

    def test_view_sim_and_frames_draw_start_from_the_document(self):
        self.assertEqual(self.outcome(doc("")), "ok")
        self.assertEqual(self.outcome(doc("#% frames=3")), "cut")
        self.assertEqual(self.outcome(doc(""), "frames=3"), "cut")
        self.assertEqual(self.outcome(doc("#% frames=3"), "frames=3000"), "ok")

    def test_the_happy_run_drawn_and_a_player_take_them(self):
        from sigil.present import app
        from sigil.present.views import run as vrun
        g = parse_document(doc("#% frames=3"))
        self.assertEqual(app.SimPlayer(g, "happy").trace.outcome, "cut")
        self.assertEqual(app.SimPlayer(g, "happy", ("frames=3000",)).trace.outcome, "ok")
        self.assertEqual(vrun.happy_run(g).outcome, "cut")
        rebuilt = app.SimPlayer(g, "happy", ("frames=3000",)).rebuilt(parse_document(doc("")))
        self.assertEqual((rebuilt.limits.frames, rebuilt.trace.outcome), (3000, "ok"))
        again = app.SimPlayer(parse_document(doc("")), "happy").rebuilt(g)
        self.assertEqual(again.trace.outcome, "cut")   # the re-read document's limits


if __name__ == "__main__":
    unittest.main()
