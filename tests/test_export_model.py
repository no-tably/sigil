"""The export model (sigil.model.systems, hashed by sigil.publish.systems): systems,
homes, components, the normalised form and hashes."""

import json
import re
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from sigil.model import systems as model_systems  # noqa: E402
from sigil.publish import systems as em  # noqa: E402


SHOP = """\
#!spec
# a shop

(Shopper) -> [Edge] -> [Shop] : {Request}
[Shop] -> |Catalog| : lookup(sku) => {Item}
[Shop] ~> <OrderPlaced> *> [Fulfilment] & |Ledger|

[Shop] := {
  [Cart] -> [Checkout] : {Cart}
  [Checkout] -> [Payments] : charge(total) => {Receipt}   # idempotent key
  [Checkout] ~> <OrderPlaced>

  [Payments] := {
    [Gateway] -> [Risk] : score(card) => {Verdict}
  }
}

[Fulfilment] := {
  [Picker] -> [Packer] -> (Courier) : {Parcel}
}
"""

# SHOP, reformatted (spacing, indentation, blank lines) and reordered (statements
# swapped inside the top level and inside an expansion).
SHOP_SHUFFLED = """\
#!spec
# a shop

[Fulfilment] := {

    [Picker]   ->   [Packer] -> (Courier) :   {Parcel}
}
[Shop]   ~>  <OrderPlaced>  *> [Fulfilment] & |Ledger|
[Shop] -> |Catalog|   : lookup(sku)   =>   {Item}



(Shopper) -> [Edge] -> [Shop] : {Request}
[Shop] := {
      [Checkout] ~> <OrderPlaced>
      [Payments] := {
          [Gateway] -> [Risk] :  score(card) => {Verdict}
      }
      [Checkout] -> [Payments] : charge(total) => {Receipt}      #   idempotent    key
      [Cart] -> [Checkout] : {Cart}
}
"""


def model(text: str = SHOP, stem: str = "store") -> em.Model:
    return em.build_model(text, stem)


def hashes(m: em.Model) -> dict:
    return {k: (s.interface_hash, s.body_hash) for k, s in m.systems.items()}


def changed(before: em.Model, after: em.Model) -> dict:
    """{system: (interface changed, body changed)} for the systems either changed."""
    a, b = hashes(before), hashes(after)
    out = {}
    for k in a:
        diff = (a[k][0] != b[k][0], a[k][1] != b[k][1])
        if any(diff):
            out[k] = diff
    return out


def glyphs(m: em.Model, key: str) -> list:
    return sorted(m.components[c].glyph for c in m.systems[key].members)


class TestSystems(unittest.TestCase):
    def setUp(self):
        self.m = model()

    def test_top_then_each_expansion(self):
        self.assertEqual(list(self.m.systems), ["store", "Shop", "Payments", "Fulfilment"])
        self.assertEqual(self.m.top, "store")
        self.assertEqual(self.m.systems["store"].kind, "top")
        self.assertEqual(self.m.systems["Payments"].parent, "Shop")

    def test_members_and_homes(self):
        self.assertEqual(glyphs(self.m, "Shop"),
                         ["<OrderPlaced>", "[Cart]", "[Checkout]", "[Payments]"])
        self.assertEqual(glyphs(self.m, "Payments"), ["[Gateway]", "[Risk]"])
        # the top level writes it only as an end of its flows, [Shop] writes it
        # too: the top's flow is a reference into Shop, its home
        self.assertEqual(self.m.components["OrderPlaced_event"].home, "Shop")
        # the face lives where it is written, not in its own system
        self.assertEqual(self.m.components["Shop_service"].home, "store")
        self.assertEqual(self.m.shared, ())

    def test_boundary_is_the_flows_crossing_it(self):
        iface = {(self.m.components[f.src].glyph, self.m.components[f.dst].glyph)
                 for f in self.m.systems["Shop"].interface}
        self.assertEqual(iface, {("[Edge]", "[Shop]"), ("[Shop]", "|Catalog|"),
                                 ("<OrderPlaced>", "[Fulfilment]"),
                                 ("<OrderPlaced>", "|Ledger|")})
        internal = {(f.src, f.dst) for f in self.m.systems["Shop"].internal}
        self.assertIn(("Checkout_service", "Payments_service"), internal)

    def test_dependencies(self):
        self.assertEqual(self.m.systems["Shop"].depends_on, ("Fulfilment", "Payments", "store"))
        self.assertIn("Fulfilment", self.m.systems["store"].depends_on)
        self.assertEqual(self.m.systems["Fulfilment"].depends_on, ())

    def test_tree_root_is_a_system(self):
        m = model("[Ship]\n    \\-& {Hull}\n    \\-& {Gun}\n[Pilot] -> [Ship] : {Order}\n",
                  "arena")
        self.assertEqual(m.systems["Ship"].kind, "tree")
        self.assertEqual(m.systems["Ship"].parent, "arena")
        self.assertEqual(glyphs(m, "Ship"), ["{Gun}", "{Hull}"])
        self.assertEqual(m.components["Ship_service"].home, "arena")

    def test_alias_body_is_no_system(self):
        m = model("walk := [Node] -> walk(.children)\n[Api] -> [Node] : {Tree}\n", "t")
        self.assertEqual(list(m.systems), ["t"])
        self.assertEqual(m.components["Node_service"].home, "t")

    def test_system_named_like_the_stem_keeps_both(self):
        # a store is no top face (TestTopFace): the top yields its name
        m = model("|shop|\n    \\-& {Row}\n[A] -> |shop| : put({Row})\n", "shop")
        self.assertEqual(list(m.systems), ["shop (top)", "shop"])
        self.assertEqual(m.top, "shop (top)")
        self.assertEqual(m.systems["shop"].face, "shop_store")


    def test_same_named_systems_keyed_by_kind_not_order(self):
        # (a data expansion is a shape, no system: a data glyph's tree stands in)
        svc = "[Pay] := {\n  [A] -> [B] : {X}\n}\n"
        data = "{Pay}\n    \\-& {C}\n\n"
        keys = [sorted((k, s.face) for k, s in model(t, "t").systems.items())
                for t in (svc + data, data + svc)]
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(keys[0], [("Pay", "Pay_service"), ("Pay (data)", "Pay_data"),
                                   ("t", None)])


class TestTopFace(unittest.TestCase):
    """A service written at the top level and named as the top (one folder slug)
    is the top: its tree or expansion is the top's face, not a system of its own."""

    TREE = ("#!spec\n"
            "# the product\n"
            "[X]\n"
            "    \\-> [A]\n"
            "    \\-> [B]\n"
            "\n"
            "[A] := {\n"
            "  [In] -> [Out] : go({Job}) => {Done}\n"
            "}\n"
            "[A] -> [B] : send({Job}) => {Done}\n")

    def test_a_tree_root_named_as_the_top_is_the_top(self):
        m = model(self.TREE, "x")
        self.assertEqual(list(m.systems), ["x", "A"])
        top = m.systems["x"]
        self.assertEqual((top.kind, top.face, top.parent), ("top", "X_service", None))
        self.assertEqual(glyphs(m, "x"), ["[A]", "[B]", "[X]"])
        self.assertEqual(m.systems["A"].parent, "x")
        self.assertEqual(top.description, ("the product",))   # the face's comment
        self.assertEqual(m.shared, ())

    def test_an_expansion_owner_named_as_the_top_is_the_top(self):
        text = ("# the document\n"
                "\n"
                "(User) -> [Shop] : buy({Order}) => {Receipt}\n"
                "# the shop's inside\n"
                "[Shop] := {\n"
                "  [Api] -> |Orders| : save({Order}) => {Ack}\n"
                "  [Pay] := {\n"
                "    [Gate] -> [Risk] : score({Card}) => {Verdict}\n"
                "  }\n"
                "}\n")
        m = model(text, "shop")
        self.assertEqual(list(m.systems), ["shop", "Pay"])
        self.assertEqual(m.systems["shop"].face, "Shop_service")
        self.assertEqual(m.systems["Pay"].parent, "shop")
        self.assertEqual(glyphs(m, "shop"), ["(User)", "[Api]", "[Pay]", "[Shop]", "|Orders|"])
        self.assertEqual(m.systems["shop"].description, ("the document", "the shop's inside"))

    def test_names_compare_as_folder_slugs(self):
        for stem in ("X", "x"):
            self.assertEqual(list(model(self.TREE, stem).systems), [stem, "A"])
        m = model(self.TREE.replace("[X]", "[MyX]"), "my-x")
        self.assertEqual(list(m.systems), ["my-x", "MyX", "A"])      # slugs myx, my-x

    def test_the_given_name_reads_so_too(self):
        # `--name X` is the stem the model gets: the same rule
        self.assertEqual(list(model(self.TREE, "other").systems), ["other", "X", "A"])
        self.assertEqual(list(model(self.TREE, "X").systems), ["X", "A"])

    def test_a_top_face_keeps_the_name_before_a_store(self):
        text = self.TREE + "|X|\n    \\-& {Row}\n[B] -> |X| : put({Row})\n"
        m = model(text, "X")
        self.assertEqual(sorted(m.systems), ["A", "X", "X (store)"])
        self.assertEqual(m.top, "X")
        self.assertEqual(m.systems["X (store)"].face, "X_store")

    def test_a_tree_member_named_as_the_top_keeps_its_system(self):
        text = ("[R]\n    \\-> [X]\n"
                "[X] := {\n  [In] -> [Out] : go({Job}) => {Done}\n}\n")
        m = model(text, "x")
        self.assertIsNone(m.systems["x"].face)
        self.assertEqual(m.systems["X"].parent, "R")

    def test_a_unit_named_as_the_top_inside_another_keeps_its_system(self):
        text = ("[Core] := {\n  [X] := {\n    [In] -> [Out] : go({Job}) => {Done}\n  }\n"
                "  [Y] -> [X] : run({Job}) => {Done}\n}\n")
        m = model(text, "x")
        self.assertIsNone(m.systems["x"].face)
        self.assertEqual(m.systems["X"].parent, "Core")


class TestComponents(unittest.TestCase):
    def test_kind_description_interface(self):
        m = model()
        c = em.component_json(m.components["Checkout_service"], m.components)
        self.assertEqual(c["kind"], "service")
        self.assertEqual(c["description"], ["idempotent key"])
        out = [f for f in c["interface"] if f["peer"] == "[Payments]"][0]
        self.assertEqual((out["dir"], out["op"], out["returns"], out["mode"]),
                         ("out", "charge(total)", "{Receipt}", "sync"))

    def test_requirements_and_accepts_verbatim(self):
        text = ("#!spec\n[Api] @sla(p99<100ms)\n|Db| @read(Api) @write(Worker)\n"
                "[Api] -> [Pay] : charge(x) => {R} ×3 @timeout(2s)   # accepts: retry-without-idempotency"
                " — upsert on id\n")
        m = model(text, "t")
        api = m.components["Api_service"]
        self.assertIn(("sla", "p99<100ms"), api.modifiers)
        self.assertIn(("read", "|Db|"), api.access)
        self.assertEqual(api.accepts,
                         ("accepts: retry-without-idempotency — upsert on id",))
        self.assertEqual(m.components["Pay_service"].accepts, api.accepts)
        self.assertEqual(m.components["Db_store"].accepts, ())
        flow = api.flows[-1]
        self.assertEqual(flow.mods, (("timeout", "2s"), ("×", "3")))

    def test_a_glyph_in_op_arguments_is_no_appearance(self):
        text = ("#!spec\n(User) -> [Api] : {Q} => {A}\n"
                "[Api] -> |Db| : find(User) => {A}  # accepts: unbounded-retry — fine\n")
        m = model(text, "t")
        user = m.components["User_actor"]
        self.assertEqual((user.lines, user.accepts), ((2,), ()))
        self.assertEqual(m.components["Db_store"].lines, (3,))

    def test_a_declaration_takes_no_neighbours_acknowledgement(self):
        text = ("#!spec\n[A] @sla(p99<1s)\n"
                "[B] -> [C] : get(k) => {V}  # accepts: unbounded-retry — fine\n")
        a = model(text, "t").components["A_service"]
        self.assertEqual((a.lines, a.accepts), ((2,), ()))

    def test_accepted_pairs_each_acknowledgement_with_its_own_text(self):
        class Ack:                      # as check.Ack: line, span, document
            def __init__(self, line, span, document=False):
                self.line, self.span, self.document = line, span, document
        comments = {1: ("accepts: a-rule — whole doc", True),
                    3: ("accepts: b-rule — here", False)}
        got = model_systems.accepted(
            [Ack(1, (), True), Ack(3, [3]), Ack(9, [9])], comments)
        self.assertEqual(got, (
            model_systems.Accepted(frozenset(), True, "accepts: a-rule — whole doc"),
            model_systems.Accepted(frozenset({3}), False, "accepts: b-rule — here"),
            model_systems.Accepted(frozenset({9}), False, "")))

    def test_lifecycle(self):
        text = ("[Checkout] -> {Order} : {Cart}\n[Pay] ~> <Paid>\n"
                "state {Order} {\n  + -<Placed>-> Open\n  Open -<Paid>-> Settled\n"
                "  Settled -<Closed>-> $\n}\n")
        lc = model(text, "t").components["Order_data"].lifecycle
        self.assertEqual(lc.states, ("Open", "Settled"))
        self.assertEqual(lc.initial, ("Open",))
        self.assertEqual(lc.terminal, ("Settled",))
        self.assertIn(("Open", "Settled", "<Paid>", ()), lc.transitions)


class TestHashes(unittest.TestCase):
    def test_reformatting_and_reordering_change_no_hash(self):
        self.assertEqual(hashes(model()), hashes(model(SHOP_SHUFFLED)))

    def test_swapping_expansions_around_a_shared_node_changes_no_hash(self):
        top = "[A] -> [Log] : put(x) => {Ok}\n[B] -> [Log] : put(x) => {Ok}\n[Log]\n"
        a = "[A] := {\n  [Log] -> |Disk| : {Line}\n}\n"
        b = "[B] := {\n  [Log] -> |Tape| : {Line}\n}\n"
        before, after = model(top + a + b, "t"), model(top + b + a, "t")
        self.assertEqual(before.shared, ())
        self.assertEqual(hashes(before), hashes(after))
        log = em.component_json(after.components["Log_service"], after.components)
        self.assertEqual(log["also_in"], ["A", "B"])

    def test_spacing_inside_a_payload_op_or_modifier_changes_no_hash(self):
        text = ("[Shop] := {\n  [Basket] -> |Orders| : save({Order}) => {Ack}"
                ' @fallback("cached")\n}\n(Buyer) -> [Shop] : {Cart}\n')
        base = hashes(model(text, "t"))
        for old, new in (("save({Order})", "save( {Order} )"),
                         ("save({Order})", "save( {Order})"),
                         ("{Order}) => {Ack}", "{Order})=>  {Ack}"),
                         ('@fallback("cached")', '@fallback( "cached" )')):
            with self.subTest(new=new):
                self.assertEqual(hashes(model(text.replace(old, new), "t")), base)
        # inside a quoted string the spacing is the text's own
        quoted = text.replace('"cached"', '"cached  copy"')
        self.assertNotEqual(hashes(model(quoted, "t")), base)

    def test_tight(self):
        self.assertEqual(model_systems.tight(" save( {Order} ,  {Id} ) "), "save({Order},{Id})")
        self.assertEqual(model_systems.tight('f( "a  b" ) x  y'), 'f("a  b")x y')
        self.assertEqual(model_systems.tight("a  =>{B}"), "a => {B}")
        self.assertEqual(model_systems.tight('x  "q"  y'), 'x "q" y')

    def test_hashes_are_16_hex(self):
        for i, b in hashes(model()).values():
            self.assertRegex(i, r"^[0-9a-f]{16}$")
            self.assertRegex(b, r"^[0-9a-f]{16}$")

    def test_a_boundary_payload_changes_the_interface(self):
        after = model(SHOP.replace("[Shop] : {Request}", "[Shop] : {Order}"))
        diff = changed(model(), after)
        self.assertEqual(diff["Shop"], (True, True))
        self.assertNotIn("Fulfilment", diff)
        self.assertNotIn("Payments", diff)

    def test_an_inner_payload_changes_the_callee_interface_only(self):
        after = model(SHOP.replace("charge(total)", "charge(total, currency)"))
        diff = changed(model(), after)
        self.assertEqual(diff["Shop"], (False, True))
        self.assertEqual(diff["Payments"], (True, True))
        self.assertEqual(set(diff), {"Shop", "Payments"})

    def test_a_description_changes_the_body_only(self):
        after = model(SHOP.replace("# idempotent key", "# idempotent on order id"))
        self.assertEqual(changed(model(), after), {"Shop": (False, True)})

    def test_a_modifier_changes_the_body_only(self):
        after = model(SHOP.replace("  [Cart] -> [Checkout]",
                                   "  [Cart] @inv nonempty\n  [Cart] -> [Checkout]"))
        self.assertEqual(changed(model(), after), {"Shop": (False, True)})

    def test_a_state_changes_the_body(self):
        text = "[A] -> {Order} : {Cart}\nstate {Order} {\n  + -<Go>-> Open\n}\n"
        before, after = model(text, "t"), model(text.replace("Open", "Ready"), "t")
        self.assertEqual(changed(before, after), {"t": (False, True)})

    def test_digest_is_canonical(self):
        self.assertEqual(em.digest({"b": 1, "a": [1, 2]}), em.digest({"a": [1, 2], "b": 1}))
        self.assertNotEqual(em.digest({"a": [1, 2]}), em.digest({"a": [2, 1]}))


class TestReadinessFacts(unittest.TestCase):
    def test_a_member_of_two_trees_has_no_one_home(self):
        text = ("[Ship]\n    \\-& {Transform}\n[Rock]\n    \\-& {Transform}\n"
                "[Physics] -> {Transform}\n")
        m = model(text, "arena")
        self.assertEqual(len(m.shared), 1)
        s = m.shared[0]
        self.assertEqual((s.glyph, s.systems, s.home), ("{Transform}", ("Ship", "Rock"), "Ship"))
        self.assertEqual(s.lines, (2, 4, 5))

    def test_a_member_of_two_expansions_has_no_one_home(self):
        text = ("[A] := {\n  [X] -> |Db| : put(k) => {Ok}\n}\n"
                "[B] := {\n  [Y] -> |Db| : get(k) => {V}\n}\n")
        m = model(text, "t")
        self.assertEqual([(s.glyph, s.systems) for s in m.shared], [("|Db|", ("A", "B"))])

    def test_untyped_boundary_flows(self):
        text = ("[Api] -> [Core] : {Req}\n[Api] -> [Log]\n[Core] -> |Db| : get(id)\n"
                "[Core] ~> |Bus| : notify(id)\n"
                "[Core] := {\n  [Router] -> [Handler]\n  [Handler] -> |Db| : put(k)\n}\n")
        m = model(text, "t")
        found = {(u.src, u.dst, u.missing, u.systems) for u in m.untyped}
        self.assertEqual(found, {("[Core]", "|Db|", "return", ("t",))})
        # |Db| is Core's (the top's flow refers into Core), so the inner
        # [Handler] -> |Db| crosses no boundary; [Api] -> [Log] is untyped but
        # crosses none either; ~> is async


    def test_failure_and_optional_calls_need_a_payload_only(self):
        text = ("[Api] := {\n  [Core] -> |Db| : read({Q}) => {R}\n"
                "  !> [Alerts] : notify({Err})\n  [Core] ?> [Audit] : log({Q})\n}\n"
                "[Alerts]\n[Audit]\n(User) -> [Api] : {Q}\n")
        self.assertEqual(model(text, "t").untyped, ())
        bare = text.replace(" : notify({Err})", "").replace(" : log({Q})", "")
        found = {(u.src, u.dst, u.missing) for u in model(bare, "t").untyped}
        self.assertEqual(found, {("[Core]", "[Alerts]", "payload"),
                                 ("[Core]", "[Audit]", "payload")})


class TestHeaderOnlyOwners(unittest.TestCase):
    """An expansion whose owner its level writes only on the `[X] := {` header
    nests under the system the owner is written in."""

    CORE = ("(U) -> [Core] : use({X}) => {Y}\n"
            "[Core] := {\n  [A]\n  [B]\n  [B] -> [A] : get({X}) => {Y}\n}\n"
            "[A] := {\n  [P] -> [Q] : go({X}) => {Y}\n}\n")

    def test_the_expansion_nests_under_the_member_s_system(self):
        m = model(self.CORE, "t")
        self.assertEqual(m.systems["A"].parent, "Core")
        self.assertEqual(m.components["A_service"].home, "Core")
        self.assertEqual(m.components["A_service"].systems, ("Core",))
        self.assertEqual(glyphs(m, "Core"), ["[A]", "[B]"])
        self.assertEqual(m.systems["t"].depends_on, ("Core",))
        self.assertEqual(m.systems["Core"].depends_on, ("A",))
        self.assertEqual(m.shared, ())

    def test_an_owner_written_only_on_its_header_lives_there(self):
        m = model("[A] := {\n  [P] -> [Q] : go({X}) => {Y}\n}\n", "t")
        self.assertEqual(m.systems["A"].parent, "t")
        self.assertEqual(m.components["A_service"].home, "t")

    def test_an_owner_wired_at_the_top_lives_where_it_is_declared(self):
        # the top writes [A] only as a flow end and on its header: a reference
        # into Core, which declares it (the home rule, 0.6.2)
        text = self.CORE + "[A] -> |Log| : put({X}) => {Ok}\n"
        m = model(text, "t")
        self.assertEqual(m.components["A_service"].home, "Core")
        self.assertEqual(m.systems["A"].parent, "Core")
        self.assertEqual(m.components["A_service"].systems, ("t", "Core"))
        self.assertEqual(m.shared, ())

    def test_an_owner_also_declared_at_the_top_stays_there(self):
        m = model(self.CORE + "[A] @sla(p99 < 5ms)\n", "t")
        self.assertEqual(m.components["A_service"].home, "t")
        self.assertEqual(m.systems["A"].parent, "t")

    def test_the_check_rule_reads_headers_the_same_way(self):
        from sigil.analyse.rules import state
        from sigil.core import graph as core_graph
        from sigil.core.parse import parse_document
        self.assertIs(state.header_only, core_graph.header_only)        # one copy
        self.assertIs(model_systems.header_only, core_graph.header_only)
        texts = (self.CORE, self.CORE + "[A] @sla(p99 < 5ms)\n",
                 self.CORE + "[A] -> |Log| : put({X}) => {Ok}\n", SHOP,
                 "walk := [Node] -> walk(.children)\n[Api] -> [Node] : {Tree}\n")
        for text in texts:
            for g in model_systems.walk(parse_document(text)):
                for nid in g.nodes:
                    with self.subTest(text=text[:20], node=nid):
                        self.assertEqual(state.header_only(g, nid),
                                         model_systems.header_only(g, nid))

    def test_two_owners_inside_each_other_keep_a_parent(self):
        text = ("[A] := {\n  [B] -> [P] : go({X}) => {Y}\n}\n"
                "[B] := {\n  [A] -> [Q] : go({X}) => {Y}\n}\n")
        m = model(text, "t")
        chain = [m.systems["A"].parent, m.systems["B"].parent]
        self.assertIn("t", chain)                     # no cycle up to the top


class TestHomeRule(unittest.TestCase):
    """A level that writes a part only as an end of its flows refers to the
    unit nested under it that writes the part too: it is no home for it."""

    REMOTE = ("(Client) -> [Transport] : connect({Hello}) => {Diffs}\n"
              "[Remote] := {\n  [Server] -> [Transport] : accept({Hello}) => {Client}\n"
              "  [Transport] -> [Protocol] : frame({Changes}) => {Message}\n}\n")

    def test_an_actor_s_entry_into_an_inner_part(self):
        m = model(self.REMOTE, "t")
        self.assertEqual(m.components["Transport_service"].home, "Remote")
        self.assertEqual(m.components["Transport_service"].systems, ("t", "Remote"))
        self.assertEqual(m.components["Client_actor"].home, "t")
        self.assertEqual(glyphs(m, "Remote"), ["[Protocol]", "[Server]", "[Transport]"])
        self.assertEqual(m.systems["t"].depends_on, ("Remote",))
        self.assertEqual(m.systems["Remote"].depends_on, ())      # no flow up to t
        self.assertEqual(m.shared, ())

    def test_a_part_declared_at_the_top_stays_there(self):
        m = model("[Transport]\n" + self.REMOTE, "t")
        self.assertEqual(m.components["Transport_service"].home, "t")
        self.assertEqual(m.systems["Remote"].depends_on, ("t",))

    def test_a_top_flow_between_parts_of_two_units(self):
        text = ("[P] -> [Q] : ask({Req}) => {Res}\n"
                "[A] := {\n  [P]\n  [R] -> [P] : go({X}) => {Y}\n}\n"
                "[B] := {\n  [Q]\n}\n")
        m = model(text, "t")
        self.assertEqual(m.components["P_service"].home, "A")
        self.assertEqual(m.components["Q_service"].home, "B")
        self.assertEqual(m.systems["A"].depends_on, ("B",))
        self.assertEqual([(f.src, f.dst) for f in m.systems["B"].interface],
                         [("P_service", "Q_service")])
        self.assertEqual(m.shared, ())

    def test_a_part_of_two_sibling_units_referred_to_from_the_top_stays_there(self):
        # both siblings declare it: dropping the top would leave two siblings
        # and no home, so the top stays
        text = ("[Api] -> [X] : get({K}) => {V}\n"
                "[A] := {\n  [X]\n}\n[B] := {\n  [X]\n  [X] -> |Db| : put({K}) => {Ok}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["X_service"].home, "t")

    def test_a_part_declared_in_one_sibling_is_homed_there(self):
        # the top and B name [X] only in their flows; A declares it (0.6.4)
        text = ("[Api] -> [X] : get({K}) => {V}\n"
                "[A] := {\n  [X]\n}\n[B] := {\n  [X] -> |Db| : put({K}) => {Ok}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["X_service"].home, "A")
        self.assertEqual(m.components["X_service"].systems, ("t", "A", "B"))

    def test_data_used_in_two_sibling_units_and_at_the_top_stays_there(self):
        text = ("[Shop] -> {Order} : make({Cart})\n"
                "[A] := {\n  [P] -> {Order} : put({K})\n}\n"
                "[B] := {\n  {Order} -> [Q] : take({K})\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Order_data"].home, "t")

    def test_a_part_declared_in_two_sibling_units_alone_is_still_shared(self):
        text = ("[A] := {\n  [X]\n}\n"
                "[B] := {\n  [X]\n  [X] -> |Db| : put({K}) => {Ok}\n}\n")
        self.assertEqual([(s.glyph, s.systems) for s in model(text, "t").shared],
                         [("[X]", ("A", "B"))])

    def test_a_part_in_the_flows_of_two_siblings_alone_is_still_shared(self):
        # declared nowhere: neither flow-only level is dropped
        text = ("[A] := {\n  [P] -> [X] : get({K}) => {V}\n}\n"
                "[B] := {\n  [X] -> |Db| : put({K}) => {Ok}\n}\n")
        self.assertEqual([(s.glyph, s.systems) for s in model(text, "t").shared],
                         [("[X]", ("A", "B"))])

    def test_a_layer_called_from_inside_another_stays_at_the_top(self):
        # [Present] heads its own flows and its expansion at the top; [Cli]
        # only calls it: a reference back out, not a declaration
        text = ("[Cli] := {\n  [ViewCmd] -> [Present] : draw({Text}) => {Drawing}\n}\n"
                "[Cli] -> [Present] : draw({Text}) => {Drawing}\n"
                "[Present] -> [Core] : parse({Text}) => {Doc}\n"
                "[Present] := {\n  [App] -> [Kit] : paint({Rows}) => {Frame}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.components["Present_service"].home, "t")
        self.assertEqual(m.systems["Present"].parent, "t")
        self.assertEqual(m.systems["Cli"].depends_on, ("Present",))

    def test_a_reference_chain_goes_to_the_innermost_unit(self):
        text = ("(U) -> [Leaf] : use({X}) => {Y}\n"
                "[Outer] := {\n  [Inner]\n  [Inner] -> [Leaf] : use({X}) => {Y}\n}\n"
                "[Inner] := {\n  [Leaf] -> [Db] : get({K}) => {V}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.systems["Inner"].parent, "Outer")
        self.assertEqual(m.components["Leaf_service"].home, "Inner")


class TestGeneralHomeRule(unittest.TestCase):
    """A level that names a part only in its flows is never its home when any
    other level declares it (a line of its own, a tree, a modifier line), even a
    level that does not enclose it (0.6.4)."""

    TEXT = ("[Core] := {\n  [Text]\n  [Text] -> |Glyphs| : load({Font}) => {Run}\n}\n"
            "[Text] := {\n  [Shaper] -> [Measure] : shape({Run}) => {Run}\n}\n"
            "[Buffer] := {\n  [Cells] -> [Text] : cell({Run}) => {Run}\n}\n")

    def test_a_flow_from_a_sibling_unit_is_a_reference(self):
        m = model(self.TEXT, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Text_service"].home, "Core")
        self.assertEqual(m.components["Text_service"].systems, ("Core", "Buffer"))
        self.assertEqual(m.systems["Text"].parent, "Core")
        self.assertEqual(glyphs(m, "Buffer"), ["[Cells]"])
        self.assertEqual(m.systems["Buffer"].depends_on, ("Text",))

    def test_a_tree_declares_it(self):
        text = ("[Core]\n    \\-> [Text]\n"
                "[Buffer] := {\n  [Cells] -> [Text] : cell({Run}) => {Run}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Text_service"].home, "Core")

    def test_a_modifier_line_declares_it(self):
        text = ("[Core] := {\n  [Text] @sla(p99 < 5ms)\n}\n"
                "[Buffer] := {\n  [Cells] -> [Text] : cell({Run}) => {Run}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Text_service"].home, "Core")

    def test_flows_in_many_units_and_the_top(self):
        text = self.TEXT + ("[Canvas] := {\n  [Grid] -> [Text] : put({Run}) => {Ok}\n}\n"
                            "[Api] -> [Text] : get({K}) => {Run}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Text_service"].home, "Core")

    def test_the_check_reads_no_home_error(self):
        from sigil.analyse import check
        found = check.check(self.TEXT, mode="spec", export=True)
        self.assertNotIn("SGC401", [f.rule.id for f in found.findings])
        shared = check.check(self.TEXT.replace("[Cells] -> [Text]", "[Text]\n  [Cells] -> [Text]"),
                             mode="spec", export=True)
        self.assertIn("SGC401", [f.rule.id for f in shared.findings])   # declared twice


class TestPayloadDependencies(unittest.TestCase):
    """A flow whose payload, op arguments or return names a data glyph homed in
    system S makes both ends' systems depend on S, as a flow to it would (0.6.4)."""

    TEXT = ("[Code] := {\n  [Parser] -> [Store] : save({Tree}) => {Ack}\n"
            "  {Unit}\n    \\-& {Contract}\n}\n"
            "[Run] := {\n  [Verify] -> [Check] : units({Tree}) => {Unit}\n}\n")

    def test_a_return_naming_a_tree_s_root_depends_on_its_tree(self):
        m = model(self.TEXT, "t")
        self.assertEqual(m.systems["Run"].depends_on, ("Unit",))
        self.assertEqual(m.systems["Code"].depends_on, ("Unit",))      # nesting only

    def test_a_member_of_the_tree_in_a_payload(self):
        m = model(self.TEXT.replace("=> {Unit}", "=> {Ok}\n  [Check] ~> [Judge] : {Contract}"), "t")
        self.assertEqual(m.systems["Run"].depends_on, ("Unit",))

    def test_data_named_only_in_payloads_makes_none(self):
        m = model(self.TEXT, "t")
        self.assertNotIn("Tree_data", m.components)
        self.assertEqual(m.systems["Code"].depends_on, ("Unit",))

    def test_data_of_the_end_s_own_or_an_enclosing_system_makes_none(self):
        text = ("{Cfg} @inv immutable\n[Run] := {\n  {Job}\n"
                "  [A] -> [B] : go({Job}, {Cfg}) => {Ok}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.components["Cfg_data"].home, "t")
        self.assertEqual(m.components["Job_data"].home, "Run")
        self.assertEqual(m.systems["Run"].depends_on, ())

    def test_an_actor_end_depends_on_nothing_the_other_end_does(self):
        text = ("[Orders] := {\n  {Order}\n  [Book] -> |Ledger| : put({Order}) => {Ok}\n}\n"
                "[Shop] := {\n  (Buyer) -> [Api] : {Order}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.systems["Shop"].depends_on, ("Orders",))
        self.assertEqual(m.components["Buyer_actor"].home, "Shop")

    def test_glyphs_read_as_the_parser_reads_them(self):
        text = ("[Store] := {\n  ~{Session}\n  {Note}\n}\n"
                "[Api] := {\n  [A] -> [B] : put(~{Session}, \"{Note}\") => {Ok}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.systems["Api"].depends_on, ("Store",))     # not the string's {Note}
        m2 = model(text.replace(', \"{Note}\"', ""), "t")
        self.assertEqual(m2.systems["Api"].depends_on, ("Store",))

    def test_a_dependency_moves_no_hash(self):
        m = model(self.TEXT, "t")
        run = m.systems["Run"]
        again = em.with_hashes(model_systems.replace(run, depends_on=()), m.components, m.top)
        self.assertEqual((again.interface_hash, again.body_hash),
                         (run.interface_hash, run.body_hash))

    def test_the_structure_reading_agrees(self):
        from sigil.core.parse import parse_document
        from sigil.model import structure
        u = structure.units_of(parse_document(self.TEXT), "t")
        run = next(x for x in u.units if x.key == "Run")
        self.assertEqual(run.calls, ("Unit",))
        self.assertEqual(run.depends_on, ("Unit",))


class TestMentionsInPassing(unittest.TestCase):
    """A level that names a part only in passing — a block header's subject, a
    branch arm's body, a store it borrows, a join's member — refers to it; it
    never declares it (0.6.4)."""

    def test_a_branch_s_field_subject_is_a_reference(self):
        text = ("[Code] := {\n  {Unit}\n    \\-& {Contract}\n}\n"
                "[Run] := {\n  [Verify] -> [Check] : units({Tree}) => {Contract}\n"
                "  branch on {Contract}.fit {\n    meets => [Check] -> [Judge] : {Contract}\n"
                "    unmeetable => [Check] ~> <Fail>\n  }\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Contract_data"].home, "Unit")
        self.assertEqual(m.systems["Run"].depends_on, ("Unit",))

    def test_a_loop_s_subject_is_a_reference(self):
        text = ("[Site] := {\n  {Pages}\n  [Crawler] -> |Index| : put({Pages}) => {Ok}\n}\n"
                "[Build] := {\n  loop @each p of {Pages} {\n    [Render] -> [Out] : {Html}\n  }\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Pages_data"].home, "Site")

    def test_an_arm_s_body_is_a_reference(self):
        text = ("[Core] := {\n  [Admin] @cap(admin)\n  [Admin] -> [Db] : {Q}\n}\n"
                "[Ui] := {\n  [Gate] -> [Router] : {Request}\n  branch on {Request}.kind {\n"
                "    admin => [Admin]\n    _ => [Router] ~> <Rejected>\n  }\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Admin_service"].home, "Core")

    def test_a_borrowed_store_is_a_reference(self):
        text = ("[Core] := {\n  [Writer] -> |Log| : append({Line}) => {Ack}\n}\n"
                "[Ui] := {\n  [Panel] @borrow(read) |Log|\n  [Panel] -> [Screen] : {Line}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())     # the writer's flows win over the borrow
        self.assertEqual(m.components["Log_store"].home, "Core")
        self.assertEqual(m.components["Panel_service"].home, "Ui")

    def test_an_access_grant_is_the_store_s_own_line(self):
        text = ("[Core] := {\n  [Writer] -> |Log| : append({Line}) => {Ack}\n  [Reader]\n}\n"
                "[Ui] := {\n  |Log| @read(Reader)\n  [Panel] -> |Log| : read() => {Line}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())     # a modifier line: it declares the store
        self.assertEqual(m.components["Log_store"].home, "Ui")

    def test_a_join_s_member_is_a_flow_end(self):
        text = ("[Core] := {\n  [Text] @inv lock-order\n  [Text] -> [Out] : {Line}\n}\n"
                "[Ui] := {\n  [Left] & [Text] -> [Merge] : {Line}\n}\n")
        m = model(text, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Text_service"].home, "Core")

    def test_a_part_named_only_in_passing_still_has_a_home(self):
        text = "[Run] := {\n  branch on {Job}.state {\n    done => [A] -> [B] : {X}\n  }\n}\n"
        m = model(text, "t")
        self.assertEqual(m.components["Job_data"].home, "Run")

    def test_the_check_reads_no_home_error(self):
        from sigil.analyse import check
        text = ("#!spec\n[Code] := {\n  {Unit}\n    \\-& {Contract}\n"
                "  [Maker] -> |Units| : put({Unit}) => {Ok}\n}\n"
                "[Run] := {\n  [Verify] -> [Check] : take({Unit}) => {Contract}\n"
                "  branch on {Contract}.fit {\n    meets => [Check] -> [Judge] : {Contract}\n"
                "    unmeetable => [Check] ~> <Fail>\n  }\n}\n")
        found = check.check(text, mode="spec", export=True)
        self.assertNotIn("SGC401", [f.rule.id for f in found.findings])


class TestActors(unittest.TestCase):
    """An actor is not built: it makes no system depend on another, and one
    written in two sibling systems is homed where they meet, not shared."""

    TEXT = ("(U) -> [Files] : run({Cmd}) => {Out}\n"
            "(U) -> [Clock] : run({Cmd}) => {Out}\n"
            "[Files] := {\n  [Themes] -> (Os) : read({Path}) => {Bytes}\n}\n"
            "[Clock] := {\n  [Wait] -> (Os) : sleep({Ms}) => {Done}\n}\n")

    def test_no_dependency_through_an_actor(self):
        m = model(self.TEXT, "t")
        self.assertEqual(m.systems["Files"].depends_on, ())
        self.assertEqual(m.systems["Clock"].depends_on, ())
        self.assertEqual(m.systems["t"].depends_on, ("Clock", "Files"))

    def test_an_actor_in_two_siblings_lives_where_they_meet(self):
        m = model(self.TEXT, "t")
        self.assertEqual(m.shared, ())
        self.assertEqual(m.components["Os_actor"].home, "t")
        self.assertEqual(m.components["Os_actor"].systems, ("Files", "Clock"))

    def test_each_system_s_interface_holds_only_its_own_call(self):
        m = model(self.TEXT, "t")
        iface = {k: sorted((f.src, f.dst) for f in m.systems[k].interface
                           if "Os_actor" in (f.src, f.dst)) for k in ("Files", "Clock")}
        self.assertEqual(iface, {"Files": [("Themes_service", "Os_actor")],
                                 "Clock": [("Wait_service", "Os_actor")]})

    def test_a_store_in_two_siblings_is_still_shared(self):
        m = model(self.TEXT.replace("(Os)", "|Os|"), "t")
        self.assertEqual([s.glyph for s in m.shared], ["|Os|"])


class TestNormalisedForm(unittest.TestCase):
    def test_to_json_is_json(self):
        m = model()
        data = json.loads(json.dumps(em.to_json(m), ensure_ascii=False))
        shop = data["systems"]["Shop"]
        self.assertEqual(shop["hashes"], {"interface": m.systems["Shop"].interface_hash,
                                          "body": m.systems["Shop"].body_hash})
        self.assertEqual(shop["face"], "[Shop]")
        # lines are where it is written: in the form, never in a hash's input
        self.assertTrue(all(c["lines"] for c in shop["components"]))
        self.assertNotIn("line", em.canonical(em.hash_form(data, m.top)))

    def test_dialect_attrs_enter_the_hash_as_they_are(self):
        # an attribute named like an export key (lines, home, description) is
        # the dialect's own data: every change to it moves the hash
        def h(attrs):
            return em.digest(em.hash_form({"attrs": attrs}, "Top"))
        self.assertNotEqual(h({"lines": [1, 2]}), h({"lines": [9]}))
        self.assertNotEqual(h({"hashes": "a"}), h({"hashes": "b"}))
        self.assertNotEqual(h({"home": "Top"}), h({"home": "Other"}))
        self.assertNotEqual(h({"description": ["b", "a"]}), h({"description": ["a", "b"]}))
        self.assertEqual(em.hash_form({"attrs": {"home": "Top", "lines": [1]}}, "Top"),
                         {"attrs": {"home": "Top", "lines": [1]}})

    def test_every_example_and_fixture(self):
        files = sorted((_DIR / "site" / "examples").glob("*.sigil")) \
            + sorted((_DIR / "tests" / "fixtures").rglob("*.sigil"))
        self.assertGreater(len(files), 7)
        for path in files:
            with self.subTest(file=path.name):
                m = em.build_model(path.read_text(encoding="utf-8"), path.stem)
                json.dumps(em.to_json(m), ensure_ascii=False)
                self.assertIn(path.stem, m.systems)
                for c in m.components.values():
                    self.assertIn(c.home, m.systems)


class TestSlugs(unittest.TestCase):
    def test_ascii_and_collision_free(self):
        s = em.slugs(["Shop", "shop", "Café", "Cache<K,V>", ""])
        self.assertEqual(s["Shop"], "shop")
        self.assertEqual(s["shop"], "shop-2")
        self.assertEqual(s["Cache<K,V>"], "cache-k-v")
        self.assertTrue(all(re.fullmatch(r"[a-z0-9-]+", v) for v in s.values()))
        self.assertEqual(len(set(s.values())), len(s))


if __name__ == "__main__":
    unittest.main()
