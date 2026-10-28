"""Four export readings (patch-0.6.9 E1), in sigil.model.systems and the hashes
of sigil.publish.systems:

0. a branch's or loop's subject is a read: a level that names a node only as a
   control block's subject is no system it is written in, and a node every level
   names only so is no component (no false unit cycle, no data page);
a. a flow on from a `?>` guard's subject is the guard's caller's;
b. a comment on a data shape's field joins its data's description: the body
   hash of the data and of its home system move, no interface hash does;
c. an acknowledgement of a unit's own finding (unit-cycle, large-unit) on its
   header is the unit's: listed on its system and its face, not as a requirement
   of every member written inside; any other on a unit's header still covers
   its members' lines, as on any block.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse import check as ck  # noqa: E402
from sigil.publish import systems as em  # noqa: E402
from sigil.publish.exporter import system_md  # noqa: E402


def doc(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def model(text: str, stem: str = "doc"):
    return em.build_model(doc(text), stem)


def rules(text: str) -> list:
    return [f.rule.id for f in ck.check(doc(text), overlaps="off", export=True).findings]


# ---------------------------------------------------------------------------
# 0. A branch or loop subject is a read
# ---------------------------------------------------------------------------

# r22/b.sigil: {Assignments} is a return in both units and a branch subject in
# Run. Read as a member of Run, Plan's flows carrying it made Plan depend on Run.
CYCLE = """
#!spec
[Run] := {
  [Orch] -> [Plan] : next({World}) => {Assignments}
  branch on {Assignments}.left {
    none => [Orch] ~> <Drained>
  }
}
[Plan] := {
  [Next] -> [Rank] : rank({World}) => {Assignments}
}
[Run] -> [Plan] : next({World}) => {Assignments}
"""

# The subject is also written as a part elsewhere: that level homes it.
SIBLING = """
#!spec
(User) -> [A] : go() => {Ok}
[A] -> [B] : pass({X}) => {Ok}
[A] := {
  [P] -> {X}
}
[B] := {
  branch on {X}.f {
    yes => [Q] ~> <Done>
  }
}
"""

LOOP = """
#!spec
(User) -> [A] : go({Xs}) => {Ok}
[A] := {
  [P] -> [Q] : take({Xs}) => {R}
  loop @each x of {Xs} {
    [P] ~> <Done>
  }
}
"""


class SubjectIsARead(unittest.TestCase):
    def test_a_branch_subject_named_nowhere_else_is_no_component(self):
        m = model(CYCLE)
        self.assertNotIn("Assignments_data", m.components)
        self.assertNotIn("Run", m.systems["Plan"].depends_on)

    def test_no_false_unit_cycle(self):
        self.assertNotIn("SGC176", rules(CYCLE))

    def test_the_subject_stays_a_node_of_the_graph(self):
        from sigil.core.parse import parse_document
        g = parse_document(doc(CYCLE))
        run = g.expansions["Run_service"]
        self.assertIn("Assignments_data", run.nodes)
        self.assertEqual(run.blocks[0].refs, ["Assignments_data"])

    def test_the_block_stays_in_its_system(self):
        self.assertEqual([b[:2] for b in model(CYCLE).systems["Run"].blocks],
                         [("branch", "{Assignments}.left")])

    def test_a_subject_written_elsewhere_lives_there_only(self):
        c = model(SIBLING).components["X_data"]
        self.assertEqual((c.home, c.systems), ("A", ("A",)))

    def test_a_loop_subject_is_a_read_too(self):
        self.assertNotIn("Xs_data", model(LOOP).components)

    def test_a_top_level_subject(self):
        m = model("""
            #!spec
            (User) -> [A] : go({X}) => {Ok}
            branch on {X}.f {
              yes => [A] ~> <Done>
            }
            """)
        self.assertNotIn("X_data", m.components)

    def test_a_subject_with_a_shape_is_still_a_component(self):
        m = model("""
            #!spec
            (User) -> [A] : go({X}) => {Ok}
            {X} := { f }
            branch on {X}.f {
              yes => [A] ~> <Done>
            }
            """)
        self.assertIn("X_data", m.components)

    def test_an_arm_body_is_still_a_mention(self):
        m = model("""
            #!spec
            (User) -> [A] : go({X}) => {Ok}
            branch on {X}.f {
              yes => [B]
            }
            """)
        self.assertIn("B_service", m.components)


# ---------------------------------------------------------------------------
# a. A guard's flow is its caller's
# ---------------------------------------------------------------------------

GUARD = """
#!spec
(User) -> [Orch] : go({Dispatch}) => {Done}
[Orch] ?> {Dispatch}.ready -> [Builders] : build({Dispatch}) => {Done}
[Builders] := {
  [Phase] -> [Agent] : work({Dispatch}) => {Done}
}
"""


def ends(m, system: str) -> set:
    s = m.systems[system]
    return {(m.components[f.src].glyph, f.arrow, m.components[f.dst].glyph)
            for f in s.internal + s.interface}


class GuardCaller(unittest.TestCase):
    def test_the_caller_is_the_source(self):
        found = ends(model(GUARD), "doc")
        self.assertIn(("[Orch]", "->", "[Builders]"), found)
        self.assertNotIn(("{Dispatch}", "->", "[Builders]"), found)

    def test_the_guard_itself_is_kept(self):
        self.assertIn(("[Orch]", "?>", "{Dispatch}"), ends(model(GUARD), "doc"))

    def test_the_data_page_lists_no_call_out(self):
        flows = model(GUARD).components["Dispatch_data"].flows
        self.assertFalse([f for f in flows if f.src == "Dispatch_data"])

    def test_a_chain_of_guards_leads_back_to_its_first_source(self):
        m = model("""
            #!spec
            (User) -> [A] : go({X}) => {Ok}
            [A] ?> {X}.f ?> {Y}.g -> [B] : run({X}) => {Ok}
            """)
        self.assertIn(("[A]", "->", "[B]"), ends(m, "doc"))

    def test_a_service_after_a_guard_arrow_is_a_hop(self):
        m = model("""
            #!spec
            (User) -> [A] : go() => {Ok}
            [A] ?> [B] -> [C] : run() => {Ok}
            """)
        self.assertIn(("[B]", "->", "[C]"), ends(m, "doc"))

    def test_an_untyped_guarded_call_across_a_boundary_is_flagged(self):
        self.assertIn("SGC402", rules("""
            #!spec
            (User) -> [Orch] : go({Job}) => {Ok}
            [Orch] ?> {Job}.ready -> [Builders]
            [Builders] := {
              [Phase] -> [Agent] : work({Job}) => {Ok}
            }
            """))


# ---------------------------------------------------------------------------
# b. A field's comment joins the body hash
# ---------------------------------------------------------------------------

FIELDS = """
#!spec
(User) -> [Log] : add({Entry}) => {Ok}
[Log] := {
  [Store] -> [Disk] : put({Entry}) => {Ok}
  {Entry} := {
    path
    note?
  }
}
"""


def hashes(m):
    out = {k: (s.interface_hash, s.body_hash) for k, s in m.systems.items()}
    out.update({c.glyph: (c.interface_hash, c.body_hash) for c in m.components.values()})
    return out


class FieldComments(unittest.TestCase):
    def commented(self, text):
        return model(FIELDS.replace("    note?\n", text))

    def test_a_trailing_comment_describes_its_field(self):
        c = self.commented("    note?   # one line\n").components["Entry_data"]
        self.assertEqual(c.description, ("`note?`: one line",))

    def test_a_comment_above_a_field_is_that_fields(self):
        c = self.commented("    # free text\n    note?\n").components["Entry_data"]
        self.assertEqual(c.description, ("`note?`: free text",))

    def test_body_hashes_move_and_no_interface_hash_does(self):
        before = hashes(model(FIELDS))
        after = hashes(self.commented("    note?   # one line\n"))
        self.assertEqual({k: v[0] for k, v in before.items()},
                         {k: v[0] for k, v in after.items()})
        moved = {k for k in before if before[k][1] != after[k][1]}
        self.assertEqual(moved, {"{Entry}", "Log"})

    def test_an_acknowledgement_there_is_no_description(self):
        c = self.commented("    note?   # accepts: unit-cycle — x\n").components["Entry_data"]
        self.assertEqual(c.description, ())

    def test_an_inline_shape_keeps_its_trailing_comment_as_before(self):
        m = model("""
            #!spec
            (User) -> [A] : add({Ok}) => {Ok}
            {Ok} := { code, why? }   # the answer
            """)
        self.assertEqual(m.components["Ok_data"].description, ("the answer",))


# ---------------------------------------------------------------------------
# c. An acknowledgement on a unit's header is the unit's
# ---------------------------------------------------------------------------

UNIT_ACK = """
#!spec
(User) -> [U] : go({Job}) => {Done}
[U] := {   # accepts: unit-cycle — built with its caller
  [P] -> [Q] : work({Job}) => {Done}
  [Q] -> |S| : save({Job}) => {Ok}   # accepts: retry-without-idempotency — an upsert
}
"""


class UnitAcknowledgement(unittest.TestCase):
    def test_the_unit_and_its_face_list_it(self):
        m = model(UNIT_ACK)
        text = "accepts: unit-cycle — built with its caller"
        self.assertEqual(m.systems["U"].accepts, (text,))
        self.assertEqual(m.components["U_service"].accepts, (text,))

    def test_members_carry_only_their_own(self):
        c = model(UNIT_ACK).components
        self.assertEqual(c["P_service"].accepts, ())
        self.assertEqual(c["Q_service"].accepts,
                         ("accepts: retry-without-idempotency — an upsert",))

    def test_one_above_the_header_or_on_its_close_is_the_units_too(self):
        bare = UNIT_ACK.replace("   # accepts: unit-cycle — built with its caller", "")
        ack = "# accepts: unit-cycle — built with its caller"
        for text in (bare.replace("[U] := {", ack + "\n[U] := {"),
                     bare.replace("an upsert\n}", "an upsert\n}   " + ack)):
            m = model(text)
            self.assertEqual(m.systems["U"].accepts, (ack[2:],), text)
            self.assertEqual(m.components["P_service"].accepts, (), text)

    def test_another_rule_on_the_header_still_covers_the_members(self):
        text = UNIT_ACK.replace("unit-cycle — built with its caller",
                                "unguarded-call — local calls")
        c = model(text).components
        self.assertEqual(c["P_service"].accepts, ("accepts: unguarded-call — local calls",))
        self.assertEqual(model(text).systems["U"].accepts, ())

    def test_an_acknowledgement_naming_a_unit_rule_and_another_is_copied(self):
        text = UNIT_ACK.replace("unit-cycle — built", "unit-cycle, unguarded-call — built")
        self.assertEqual(len(model(text).components["P_service"].accepts), 1)

    def test_the_unit_rules_are_check_rules(self):
        from sigil.analyse.check import CORE_NAMES
        from sigil.model.systems import UNIT_RULES
        self.assertLessEqual(UNIT_RULES, set(CORE_NAMES.values()))

    def test_a_control_blocks_header_still_covers_its_members(self):
        m = model("""
            #!spec
            (User) -> [U] : go({Job}) => {Done}
            [U] := {
              loop @times 3 {   # accepts: capacity-mismatch — bounded
                [P] -> [Q] : work({Job}) => {Done}
              }
            }
            """)
        self.assertEqual(m.components["P_service"].accepts,
                         ("accepts: capacity-mismatch — bounded",))
        self.assertEqual(m.systems["U"].accepts, ())

    def test_the_top_still_holds_the_document_wide_ones(self):
        m = model(UNIT_ACK.replace("#!spec\n", "#!spec\n# accepts: capacity-mismatch — fine\n\n"))
        self.assertEqual(m.systems["doc"].accepts, ("accepts: capacity-mismatch — fine",))

    def test_the_readme_heading_says_where_it_was_written(self):
        m = model(UNIT_ACK)
        form = em.system_json(m.systems["U"], m.components)
        files = {c["glyph"]: "x.md" for c in form["components"]}
        self.assertIn("## Acknowledgements (on its header)", system_md("U", form, files, {}))


if __name__ == "__main__":
    unittest.main()
