"""export_model.py: systems, homes, components, the normalised form and hashes."""

import json
import re
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

import export_model as em  # noqa: E402


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


def model(text: str = SHOP, stem: str = "shop") -> em.Model:
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
        self.assertEqual(list(self.m.systems), ["shop", "Shop", "Payments", "Fulfilment"])
        self.assertEqual(self.m.top, "shop")
        self.assertEqual(self.m.systems["shop"].kind, "top")
        self.assertEqual(self.m.systems["Payments"].parent, "Shop")

    def test_members_and_homes(self):
        self.assertEqual(glyphs(self.m, "Shop"), ["[Cart]", "[Checkout]", "[Payments]"])
        self.assertEqual(glyphs(self.m, "Payments"), ["[Gateway]", "[Risk]"])
        # written at the top level and in [Shop]: shared at the top level
        self.assertEqual(self.m.components["OrderPlaced_event"].home, "shop")
        # the face lives where it is written, not in its own system
        self.assertEqual(self.m.components["Shop_service"].home, "shop")
        self.assertEqual(self.m.shared, ())

    def test_boundary_is_the_flows_crossing_it(self):
        iface = {(self.m.components[f.src].glyph, self.m.components[f.dst].glyph)
                 for f in self.m.systems["Shop"].interface}
        self.assertEqual(iface, {("[Edge]", "[Shop]"), ("[Shop]", "|Catalog|"),
                                 ("[Shop]", "<OrderPlaced>"),
                                 ("[Checkout]", "<OrderPlaced>")})
        internal = {(f.src, f.dst) for f in self.m.systems["Shop"].internal}
        self.assertIn(("Checkout_service", "Payments_service"), internal)

    def test_dependencies(self):
        self.assertEqual(self.m.systems["Shop"].depends_on, ("Payments", "shop"))
        self.assertIn("Fulfilment", self.m.systems["shop"].depends_on)
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
        m = model("[shop] := {\n  [A] -> [B] : {X}\n}\n")
        self.assertEqual(list(m.systems), ["shop", "shop (service)"])


    def test_same_named_systems_keyed_by_kind_not_order(self):
        svc = "[Pay] := {\n  [A] -> [B] : {X}\n}\n"
        data = "{Pay} := {\n  [C] -> [D] : {Y}\n}\n"
        keys = [sorted((k, s.face) for k, s in model(t, "t").systems.items())
                for t in (svc + data, data + svc)]
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(keys[0], [("Pay", "Pay_service"), ("Pay (data)", "Pay_data"),
                                   ("t", None)])


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
        self.assertEqual(found, {("[Core]", "|Db|", "return", ("Core",)),
                                 ("[Handler]", "|Db|", "return", ("Core", "t"))})
        # [Api] -> [Log] is untyped but crosses no boundary; ~> is async; the
        # inner [Router] -> [Handler] crosses none either


class TestNormalisedForm(unittest.TestCase):
    def test_to_json_is_json(self):
        m = model()
        data = json.loads(json.dumps(em.to_json(m), ensure_ascii=False))
        shop = data["systems"]["Shop"]
        self.assertEqual(shop["hashes"], {"interface": m.systems["Shop"].interface_hash,
                                          "body": m.systems["Shop"].body_hash})
        self.assertEqual(shop["face"], "[Shop]")
        self.assertNotIn("line", json.dumps(data))

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
