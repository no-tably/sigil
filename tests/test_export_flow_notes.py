"""Round 10 (F1): a comment trailing a line that draws flows describes those flows.
Each Flow keeps it as its `note` (system.json, the components' interface entries,
the Markdown pages); it is in the body hash of both ends and of each system
listing the flow, never in an interface hash. A line that draws no flow keeps
describing its first node."""

import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from sigil.publish import exporter  # noqa: E402
from sigil.publish import systems as em  # noqa: E402


def model(text: str):
    return em.build_model(text, stem="doc")


def comp(m, name: str):
    return next(c for c in m.components.values() if c.name == name)


def flows(m, src: str, dst: str) -> list:
    ids = {c.id: c.name for c in m.components.values()}
    seen = {f for c in m.components.values() for f in c.flows}
    return [f for f in seen if ids[f.src] == src and ids[f.dst] == dst]


def note(m, src: str, dst: str):
    found = flows(m, src, dst)
    assert len(found) == 1, found
    return found[0].note


class FlowLineNotes(unittest.TestCase):

    def test_chain_line_gives_every_flow_its_note(self):
        m = model("#!spec\n\n[Api] -> [Mid] -> [End]   # passes it on\n")
        self.assertEqual(note(m, "Api", "Mid"), "passes it on")
        self.assertEqual(note(m, "Mid", "End"), "passes it on")
        for name in ("Api", "Mid", "End"):
            self.assertEqual(comp(m, name).description, (), name)

    def test_fan_out_line_gives_every_flow_its_note(self):
        m = model("#!spec\n\n[Api] -> [A] & [B]   # both at once\n")
        self.assertEqual(note(m, "Api", "A"), "both at once")
        self.assertEqual(note(m, "Api", "B"), "both at once")
        self.assertEqual(comp(m, "Api").description, ())

    def test_continued_trailing_comment(self):
        m = model("#!spec\n\n[Api] ~> [Q] : put({Job})   # queued for\n"
                  "                            #   the   worker\n")
        self.assertEqual(note(m, "Api", "Q"), "queued for the worker")
        self.assertEqual(comp(m, "Api").description, ())

    def test_comment_under_a_statement(self):
        m = model("#!spec\n\n[Api] -> [Db] : save({Order})\n  # kept in order\n")
        self.assertEqual(note(m, "Api", "Db"), "kept in order")
        self.assertEqual(comp(m, "Api").description, ())

    def test_comment_above_a_flow_still_describes_its_node(self):
        m = model("#!spec\n\n# the front door\n[Api] -> [Db] : save({Order})\n")
        self.assertIsNone(note(m, "Api", "Db"))
        self.assertEqual(comp(m, "Api").description, ("the front door",))

    def test_declaration_line_unchanged(self):
        m = model("#!spec\n\n[Api] -> [Db] : save({Order})\n[Db]   # the ledger\n")
        self.assertEqual(comp(m, "Db").description, ("the ledger",))
        self.assertIsNone(note(m, "Api", "Db"))

    def test_branch_line_unchanged(self):
        m = model("#!spec\n\n[Ship]\n    \\-& {Health}   # hit points\n"
                  "[Combat] -> {Health}\n")
        self.assertEqual(comp(m, "Health").description, ("hit points",))
        self.assertIsNone(note(m, "Combat", "Health"))

    def test_transition_line_gives_no_flow_a_note(self):
        m = model("#!spec\n\n[Api] -> [Db] : save({Order})\n"
                  "state {Order} {\n  + -<place>-> Open   # placed by the shop\n"
                  "  Open -<pay>-> $\n}\n")
        self.assertIsNone(note(m, "Api", "Db"))
        self.assertEqual(comp(m, "Order").description, ())

    def test_acknowledgement_is_no_note(self):
        m = model("#!spec\n\n[Api] -> [Db] : save({Order})   "
                  "# accepts: unguarded-call — the db is local\n")
        self.assertIsNone(note(m, "Api", "Db"))


class Hashes(unittest.TestCase):
    BARE = ("#!spec\n\n(User) -> [Shop] : buy({Order}) => {Receipt}\n"
            "[Shop] := {\n  [Cart] -> |Db| : save({Order}) => {Ack}\n}\n")

    def with_notes(self) -> str:
        return (self.BARE
                .replace("=> {Receipt}\n", "=> {Receipt}   # one order at a time\n")
                .replace("=> {Ack}\n", "=> {Ack}   # appended, never rewritten\n"))

    def test_interface_hash_never_moves_body_hash_does(self):
        bare, noted = model(self.BARE), model(self.with_notes())
        for name in ("User", "Shop", "Cart", "Db"):
            a, b = comp(bare, name), comp(noted, name)
            self.assertEqual(a.interface_hash, b.interface_hash, name)
            self.assertNotEqual(a.body_hash, b.body_hash, name)
        for key in bare.systems:
            a, b = bare.systems[key], noted.systems[key]
            self.assertEqual(a.interface_hash, b.interface_hash, key)
            self.assertNotEqual(a.body_hash, b.body_hash, key)

    def test_interface_order_ignores_notes(self):
        # Two flows whose canonical order a note would swap: the interface hash
        # still matches the note-free one.
        bare = "#!spec\n\n[A] -> [B] : b()\n[A] -> [B] : a()\n"
        noted = "#!spec\n\n[A] -> [B] : b()   # zzz\n[A] -> [B] : a()\n"
        self.assertEqual(comp(model(bare), "A").interface_hash,
                         comp(model(noted), "A").interface_hash)

    def test_json_carries_the_note(self):
        j = em.to_json(model(self.with_notes()))
        shop = j["systems"]["Shop"]
        self.assertEqual([f.get("note") for f in shop["flows"]],
                         ["appended, never rewritten"])
        top = j["systems"]["doc"]
        cart = next(c for c in shop["components"] if c["name"] == "Cart")
        self.assertEqual(cart["interface"][0]["note"], "appended, never rewritten")
        self.assertNotIn("description", cart)
        self.assertEqual([f.get("note") for f in top.get("flows", [])],
                         ["one order at a time"])


class Markdown(unittest.TestCase):

    def test_pages_print_the_note_after_the_flow(self):
        m = model("#!spec\n\n[Api] -> [Db] : save({Order})   # kept in order\n")
        j = em.to_json(m)
        top = j["systems"]["doc"]
        api = next(c for c in top["components"] if c["name"] == "Api")
        page = exporter.component_md(api, "doc", "doc")
        self.assertIn("- `[Api] -> [Db] : save({Order})` — sync call — kept in order", page)
        self.assertNotIn("## Description", page)
        files = {c["glyph"]: c["name"] + ".md" for c in top["components"]}
        sys_page = exporter.system_md("doc", top, files, {})
        self.assertIn("— sync call — kept in order", sys_page)


if __name__ == "__main__":
    unittest.main()
