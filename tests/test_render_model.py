"""Tests for the render.py graph MODEL (the single source of truth the Mermaid
emitter, the terminal views and a future simulation engine read).

One class per fix / model field:
  - continuation lines take the statement's SUBJECT (language.md pitfall 9);
  - generics are part of ONE glyph (`[Cache<K,V>]`), never a phantom event;
  - `branch on X { arm => … }` is a Block with arms, not a chain of `=>` edges;
  - `a / b` alternatives are both edges, joined as one "/" endpoint;
  - Graph.blocks / joins / access / sections, Node.mods / Edge.mods;
  - nodes that used to vanish (aliases, block-header glyphs, op-call targets);
  - zoom: an `--- L3 ---` expansion nests under its level-2 namesake.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
FIXTURE = _DIR / "tests" / "fixtures" / "coverage.sigil"


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


render = _load("sigil_render_model", "render.py")


def parse(text):
    return render.parse_document(text)


def keys(g):
    return {(e.src, e.dst, e.kind) for e in g.edges}


def edge(g, src, dst, kind=None):
    hits = [e for e in g.edges if e.src == src and e.dst == dst
            and (kind is None or e.kind == kind)]
    assert len(hits) == 1, (src, dst, kind, hits)
    return hits[0]


class Continuation(unittest.TestCase):
    def test_takes_the_subject_not_the_last_target(self):
        g = parse("[Auth] -> |UserDB|\n       => {Session}\n       !> <Unauthorized>\n")
        self.assertEqual(keys(g), {
            ("Auth_service", "UserDB_store", "->"),
            ("Auth_service", "Session_data", "=>"),
            ("Auth_service", "Unauthorized_event", "!>"),
        })

    def test_consecutive_continuations_keep_the_subject(self):
        g = parse("[A] -> [B] -> [C]\n  => {X} -> [D]\n  !> <E>\n")
        self.assertIn(("A_service", "X_data", "=>"), keys(g))
        self.assertIn(("X_data", "D_service", "->"), keys(g))    # the chain goes on
        self.assertIn(("A_service", "E_event", "!>"), keys(g))   # still [A]

    def test_joined_subject_fans_out(self):
        g = parse("*<Enriched> *> |Warehouse| & |RealtimeIdx|\n            !> |DLQ|\n")
        self.assertIn(("Enriched_event", "DLQ_store", "!>"), keys(g))
        self.assertNotIn(("RealtimeIdx_store", "DLQ_store", "!>"), keys(g))
        g = parse("[A] & [B] -> [C]\n  !> <E>\n")
        self.assertEqual({e.src for e in g.edges if e.kind == "!>"}, {"A_service", "B_service"})
        self.assertEqual({e.src_join for e in g.edges if e.kind == "!>"}, {0})

    def test_readme_payment_failure_hangs_off_the_caller(self):
        g = parse("(User) -> [API] : {Cart}\n[API] -> [Payment] : charge ×3 @timeout(2s)\n"
                  "       !> <PaymentFailed>\n")
        self.assertIn(("API_service", "PaymentFailed_event", "!>"), keys(g))
        self.assertNotIn(("Payment_service", "PaymentFailed_event", "!>"), keys(g))

    def test_cont_marks_the_flow_a_continuation_continues(self):
        # Edge.cont: the statement's line, then the latest continuation that drew work
        g = parse("[A] -> [B]\n  -> [C]\n  !> <E>\n  !> <F>\n[A] -> [G]\n")
        self.assertEqual(edge(g, "A_service", "B_service").cont, 0)
        self.assertEqual(edge(g, "A_service", "C_service").cont, 1)
        self.assertEqual(edge(g, "A_service", "E_event").cont, 2)
        self.assertEqual(edge(g, "A_service", "F_event").cont, 2)   # a route is no flow
        self.assertEqual(edge(g, "A_service", "G_service").cont, 0)

    def test_a_section_header_resets_the_subject(self):
        g = parse("[A] -> [B]\n--- next ---\n  -> [C]\n")
        self.assertNotIn(("A_service", "C_service", "->"), keys(g))


class Generics(unittest.TestCase):
    def test_one_glyph_with_its_generic(self):
        g = parse("[Cache<K,V>]\n{List<T>}\n<Msg<T>>\n[Worker<N>]\n{List<Map<K,V>>}\n")
        names = {n.name: n for n in g.nodes.values()}
        self.assertEqual(set(names), {"Cache<K,V>", "List<T>", "Msg<T>", "Worker<N>",
                                      "List<Map<K,V>>"})
        self.assertEqual(names["Cache<K,V>"].kind, "service")
        self.assertEqual(names["Msg<T>"].kind, "event")
        self.assertEqual(names["Cache<K,V>"].params, ("K", "V"))
        self.assertEqual(names["List<Map<K,V>>"].params, ("Map<K,V>",))
        self.assertEqual(names["Worker<N>"].base_name, "Worker")
        self.assertFalse(any(n.kind == "event" and n.name in ("K,V", "T", "N")
                             for n in g.nodes.values()))

    def test_flow_reaches_the_generic_glyph(self):
        g = parse("[Api] <-> [Cache<K,V>]\n[Api] -> <Msg<T>> -> [Sink]\n")
        self.assertEqual(keys(g), {
            ("Api_service", "Cache_K_V__service", "<->"),
            ("Api_service", "Msg_T__event", "->"),
            ("Msg_T__event", "Sink_service", "->"),
        })

    def test_mermaid_escapes_the_angle_brackets(self):
        out = render.render("[Api] <-> [Cache<K,V>]\n")
        self.assertIn('Cache_K_V__service["Cache&lt;K,V&gt;"]', out)
        self.assertNotIn("<K", out)

    def test_generic_owner_and_trigger_by_base_name(self):
        g = parse("[Src] ~> <Msg<T>>\nstate {Job<T>} {\n  + -<Msg>-> Open\n}\n")
        self.assertEqual(g.expansions["Job_T__data"].role, "state")
        self.assertEqual([t.event for t in g.triggers], ["Msg_T__event"])

    def test_lint_agrees_and_roles_resolve(self):
        doc = ("#!spec\n[Worker<N>]\n[Coord]\n|Tasks| @read(Worker) @write(Coord)\n"
               "[Api] -> <Msg<T>> -> [Cache<K,V>]\n")
        r = subprocess.run([sys.executable, str(_DIR / "lint.py"), "-"], input=doc,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        acc = {(a.principal, a.mode) for a in parse(doc).access}
        self.assertEqual(acc, {("Worker_N__service", "read"), ("Coord_service", "write")})

    def test_a_generic_named_as_a_principal_is_a_role(self):
        g = parse("[Worker<N>]\n[Worker]\n[Pool<T>]\n[Cache<K,V>]\n(Agent<M>)\n"
                  "|Tasks| @read(Worker, Agent) @write(Cache)\n[Pool] @borrow |Tasks|\n")
        roles = {n.name for n in g.nodes.values() if n.is_role}
        # also when an exact [Worker] takes the edge; a borrower names no role
        self.assertEqual(roles, {"Worker<N>", "Agent<M>", "Cache<K,V>"})


class BlockStrings(unittest.TestCase):
    def test_a_block_string_payload_keeps_its_text(self):
        g = parse('[A] -> ~|Sys| : """\n  first line\n  second\n"""\n[B] -> [C] : "x"\n')
        by = {(e.src, e.dst): e for e in g.edges}
        e = by[("A_service", "Sys_store")]
        self.assertEqual(e.payload, render.BLOCK_SENTINEL)      # the payload stays masked
        self.assertEqual(e.block_string, "\n  first line\n  second\n")
        self.assertIsNone(by[("B_service", "C_service")].block_string)

    def test_a_single_line_block_string(self):
        (e,) = parse('[A] -> [B] : """one"""\n').edges
        self.assertEqual(e.block_string, "one")

    def test_an_unterminated_block_string_keeps_none(self):
        self.assertEqual([e.block_string for e in parse('[A] -> [B]\n[C] -> [D] : """\nx\n').edges],
                         [None])


BRANCH = """branch on {Request}.kind {
  read  => [Reader] -> |DB|
  write => [Writer] -> |DB| -> |WAL|
  admin => [AdminSvc] @cap(admin)
  _     => <Rejected>
}
"""


class Branch(unittest.TestCase):
    def setUp(self):
        self.g = parse("[Metrics] -> |Obs|\n" + BRANCH)
        self.b = self.g.blocks[0]

    def test_no_phantom_chain_between_arms(self):
        self.assertEqual(keys(self.g), {
            ("Metrics_service", "Obs_store", "->"),
            ("Reader_service", "DB_store", "->"),
            ("Writer_service", "DB_store", "->"),
            ("DB_store", "WAL_store", "->"),
        })

    def test_arms(self):
        self.assertEqual(self.b.kind, "branch")
        self.assertEqual(self.b.header, "{Request}.kind")
        self.assertEqual(self.b.refs, ["Request_data"])
        self.assertEqual([label for label, _e in self.b.arms], ["read", "write", "admin", "_"])
        self.assertEqual(dict(self.b.arms)["write"],
                         [("Writer_service", "DB_store", "->"), ("DB_store", "WAL_store", "->")])
        self.assertEqual(dict(self.b.arm_nodes)["_"], ["Rejected_event"])
        self.assertEqual(dict(self.b.arm_nodes)["admin"], ["AdminSvc_service"])
        self.assertIn(("cap", "admin"), self.g.nodes["AdminSvc_service"].mods)
        self.assertIn("Request_data", self.g.nodes)

    def test_mermaid_draws_the_choice_not_a_chain(self):
        out = render.render("[Metrics] -> |Obs|\n" + BRANCH)
        self.assertIn('Request_data -. "read" .-> Reader_service', out)
        self.assertIn('Request_data -. "_" .-> Rejected_event', out)
        self.assertNotIn("==>", out)


class Alternatives(unittest.TestCase):
    def test_both_outcomes_are_edges(self):
        g = parse("[Api] => {Resp} / {Err}\n")
        self.assertEqual(keys(g), {("Api_service", "Resp_data", "=>"),
                                   ("Api_service", "Err_data", "=>")})
        self.assertEqual(len(g.joins), 1)
        self.assertEqual(g.joins[0].kind, "/")
        self.assertEqual(g.joins[0].members, ["Resp_data", "Err_data"])
        self.assertEqual({e.dst_join for e in g.edges}, {0})

    def test_qualified_path_survives_an_earlier_mention(self):
        # The path belongs to the written token even when the node already exists,
        # and a continuation keeps its subject's path.
        g = parse("[Bullet]\n  \\-& {Transform}\n[Homing] -> [Bullet]/{Transform}\n"
                  "[Bullet]/{Transform} -> [X]\n  !> <E>\n")
        self.assertEqual([(e.src_path, e.dst_path) for e in g.edges], [
            (None, ("Bullet", "Transform")), (("Bullet", "Transform"), None),
            (("Bullet", "Transform"), None)])

    def test_qualified_path_is_not_an_alternative(self):
        g = parse("[Homing] -> [Bullet]/{Transform}\n")
        self.assertEqual(g.joins, [])
        self.assertEqual(g.edges[0].dst_path, ("Bullet", "Transform"))


class Joins(unittest.TestCase):
    def test_kinds_and_members(self):
        g = parse("[Api] -> [Stock] & [Tax]\n[Api] -> [PspA] &? [PspB]\n")
        self.assertEqual([(j.kind, j.members, j.line) for j in g.joins], [
            ("&", ["Stock_service", "Tax_service"], 1),
            ("&?", ["PspA_service", "PspB_service"], 2),
        ])
        self.assertEqual(edge(g, "Api_service", "PspB_service").dst_join, 1)
        self.assertIsNone(edge(g, "Api_service", "PspB_service").src_join)


class Blocks(unittest.TestCase):
    DOC = """loop @each x of {Items} {
  [Worker] -> |Q| : pop => {Job}
}
loop @until {Job}.state = done {
  parallel @all {
    [Api] -> [Inventory] : reserve => {Hold}
    [Api] -> [Fraud] : score
  }
         !> [Inventory] : release({Hold})
}
checkout {
  [Cart] -> [Api]
}
[Handler] @owns |Conn| {
  [Handler] -> |Conn| : query => {Rows}
}
loop @times 3 { [Pinger] -> (Peer) }
"""

    def setUp(self):
        self.g = parse(self.DOC)
        self.by = {b.header: b for b in self.g.blocks}

    def test_kinds_headers_modifiers(self):
        self.assertEqual([(b.kind, b.header) for b in self.g.blocks], [
            ("loop", "@each x of {Items}"), ("loop", "@until {Job}.state = done"),
            ("parallel", "@all"), ("scope", "checkout"),
            ("owns", "[Handler] @owns |Conn|"), ("loop", "@times 3"),
        ])
        self.assertEqual(self.by["@each x of {Items}"].modifiers, [("each", "x of {Items}")])
        self.assertEqual(self.by["@times 3"].modifiers, [("times", "3")])
        self.assertEqual(self.by["@all"].modifiers, [("all", None)])

    def test_members_edges_lines_parent(self):
        par = self.by["@all"]
        until = self.by["@until {Job}.state = done"]
        self.assertEqual(par.parent, self.g.blocks.index(until))
        self.assertEqual(par.lines, (5, 8))
        self.assertEqual(until.lines, (4, 10))
        self.assertEqual(par.members, ["Api_service", "Inventory_service", "Fraud_service"])
        self.assertEqual(par.edges, [("Api_service", "Inventory_service", "->"),
                                     ("Api_service", "Fraud_service", "->")])
        # nested members and the compensation count for the enclosing loop too
        self.assertIn(("Api_service", "Inventory_service", "!>"), until.edges)
        self.assertEqual(self.by["@times 3"].edges, [("Pinger_service", "Peer_actor", "->")])

    def test_compensation_attaches_to_the_block_subject(self):
        par = self.by["@all"]
        self.assertEqual(par.subject, ["Api_service"])
        self.assertEqual(par.after, [("Api_service", "Inventory_service", "!>")])
        e = edge(self.g, "Api_service", "Inventory_service", "!>")
        self.assertEqual(e.payload, "release({Hold})")
        self.assertNotIn(("Fraud_service", "Inventory_service", "!>"), keys(self.g))

    def test_header_glyphs_are_nodes(self):
        self.assertEqual(self.by["@each x of {Items}"].refs, ["Items_data"])
        self.assertEqual(self.by["@until {Job}.state = done"].refs, ["Job_data"])
        self.assertIn("Items_data", self.g.nodes)
        self.assertIn("Job_data", self.g.nodes)

    def test_owns_block(self):
        b = self.by["[Handler] @owns |Conn|"]
        self.assertEqual(b.refs, ["Handler_service", "Conn_store"])
        self.assertEqual(b.subject, ["Handler_service"])
        self.assertEqual(b.modifiers, [("owns", "|Conn|")])
        self.assertIn(("owns", "|Conn|"), self.g.nodes["Handler_service"].mods)

    def test_text_after_the_closing_brace(self):
        g = parse("parallel @all {\n  [R] -> [A]\n} => {Out}\n")
        self.assertIn(("R_service", "Out_data", "=>"), keys(g))
        self.assertEqual(g.blocks[0].after, [("R_service", "Out_data", "=>")])


class Access(unittest.TestCase):
    def test_read_write_borrow(self):
        g = parse("[Boss]\n[Worker<N>]\n(Auditor)\n|Directives| @read(Worker) @write(Boss)\n"
                  "*|Log| @read(Auditor) @write(Boss, Worker)\n"
                  "[Helper] @borrow |Directives|\n[Helper] @borrow(read) |Log|\n"
                  "|Other| @read(Nobody)\n[Helper] @borrow |Nowhere|\n")
        acc = [(a.principal, a.store, a.mode, a.narrow, a.line) for a in g.access]
        self.assertEqual(acc, [
            ("Worker_N__service", "Directives_store", "read", None, 4),
            ("Boss_service", "Directives_store", "write", None, 4),
            ("Auditor_actor", "Log_store", "read", None, 5),
            ("Boss_service", "Log_store", "write", None, 5),
            ("Worker_N__service", "Log_store", "write", None, 5),
            ("Helper_service", "Directives_store", "borrow", None, 6),
            ("Helper_service", "Log_store", "borrow", "read", 7),
            (None, "Other_store", "read", None, 8),         # names nothing
            ("Helper_service", None, "borrow", None, 9),    # store is no node
        ])
        self.assertEqual(g.access[0].name, "Worker")
        self.assertNotIn("Nowhere_store", g.nodes)          # a modifier arg is no node


class Modifiers(unittest.TestCase):
    def test_edge_modifiers_trail_the_flow(self):
        g = parse("[Api] -> [Scorer] : score({Cart}) @timeout(30s) ×3 @fallback(0)\n"
                  "(C) -> [Api] : {Cart} !\n[Api] -> [Shard] ×4\n[Api] -> [Replica] x2\n"
                  "[Auth] -> |UserDB| @cap(read)\n[Router] -> [Handler]×N\n"
                  "[Worker] -> run() @deadline(2s)\n")
        e = edge(g, "Api_service", "Scorer_service")
        self.assertEqual(e.mods, [("timeout", "30s"), ("×", "3"), ("fallback", "0")])
        self.assertEqual(e.payload, "score({Cart})")
        e = edge(g, "C_actor", "Api_service")
        self.assertEqual((e.payload, e.mods), ("{Cart}", [("!", None)]))
        # a payload-less trailing `×N` and a glued one are cardinality (Edge.card)
        for dst, card in (("Shard_service", "4"), ("Replica_service", "2")):
            e = edge(g, "Api_service", dst)
            self.assertEqual((e.mods, e.card), ([], card))
        self.assertEqual(edge(g, "Auth_service", "UserDB_store").mods, [("cap", "read")])
        e = edge(g, "Router_service", "Handler_service")
        self.assertEqual((e.mods, e.card), ([], "N"))
        self.assertEqual(edge(g, "Worker_service", "Worker_service").mods, [("deadline", "2s")])

    def test_node_modifiers(self):
        g = parse("[Gateway] @loc(us-east) -> [Api]\n[Api] @sla(p99<100ms, avail>99.95%)\n"
                  "{User}.age @inv >= 0\n[Ingest] => *<Raw>^10k@drop\n"
                  "[Auth] => ~{Session}?\n[Cache<K,V>] @loc(eu-west)\n")
        n = g.nodes
        self.assertEqual(n["Gateway_service"].mods, [("loc", "us-east")])
        self.assertEqual(n["Api_service"].mods, [("sla", "p99<100ms, avail>99.95%")])
        self.assertEqual(n["User_data"].mods, [(".", "age"), ("inv", ">= 0")])
        self.assertEqual(n["Raw_event"].mods, [("^", "10k@drop")])
        self.assertEqual(n["Cache_K_V__service"].mods, [("loc", "eu-west")])
        self.assertEqual(edge(g, "Auth_service", "Session_data").mods, [("?", None)])
        self.assertEqual(edge(g, "Gateway_service", "Api_service").mods, [])

    def test_transition_modifiers(self):
        g = parse("state {Order} {\n  Open -<Paid>-> Settled @timeout(1d)\n"
                  "  _ -<cancel>-> Cancelled ×3\n}\n")
        m = g.expansions["Order_data"]
        self.assertEqual([e.mods for e in m.edges], [[("timeout", "1d")], [("×", "3")]])
        self.assertEqual([e.line for e in m.edges], [2, 3])

    def test_state_block_tail_modifiers_are_the_owners(self):
        g = parse("[Api] @loc(eu)\nstate [Api] {\n  + -> Idle\n} @inv ordered(order_id)\n"
                  "state {Order} { + -> Open } @deadline(1d)  # tail\n")
        self.assertEqual(g.nodes["Api_service"].mods,
                         [("loc", "eu"), ("inv", "ordered(order_id)")])
        self.assertEqual(g.nodes["Order_data"].mods, [("deadline", "1d")])
        self.assertEqual(g.dropped, [])

    def test_payload_text_unchanged(self):
        g = parse('[A] -> [B] : "a ×3" @timeout(1s)\n[A] -> [C] : x^2\n')
        self.assertEqual(edge(g, "A_service", "B_service").payload, '"a ×3"')
        self.assertEqual(edge(g, "A_service", "C_service").payload, "x^2")


class Sections(unittest.TestCase):
    def test_levels_titles_lines(self):
        g = parse("--- L1: Shop ---\n[A]\n--- Control ---\n[B]\n--- L2: [Core] ---\n")
        self.assertEqual(g.sections, [("L1", "Shop", 1), (None, "Control", 3),
                                      ("L2", "[Core]", 5)])
        self.assertEqual(g.sections[2].title, "[Core]")


class LineNumbers(unittest.TestCase):
    def test_lines_are_the_source_lines_inside_expansions(self):
        g = parse("#!sketch\n[Core] := {\n  # inside\n  [API] -> |DB|\n}\n[X] -> [Y]\n")
        sub = g.expansions["Core_service"]
        self.assertEqual(sub.edges[0].line, 4)
        self.assertEqual(sub.notes[0].line, 3)
        self.assertEqual(g.edges[0].line, 6)


class VanishedNodes(unittest.TestCase):
    def setUp(self):
        self.g = parse(FIXTURE.read_text(encoding="utf-8"))

    def test_alias_is_a_node_whose_expansion_is_its_definition(self):
        walk = self.g.nodes["walk_alias"]
        self.assertEqual(walk.kind, "alias")
        body = self.g.expansions["walk_alias"]
        self.assertIn("Node_service", body.nodes)
        e = body.edges[0]
        self.assertEqual((e.src, e.dst, e.target_op), ("Node_service", "Node_service",
                                                       "walk(.children)"))
        retry = self.g.nodes["retry_alias"]
        self.assertEqual(retry.mods, [("after", "exp-backoff, cap=1min")])
        self.assertNotIn("retry_alias", self.g.expansions)        # no flow, no expansion

    def test_block_header_glyphs(self):
        for nid in ("Items_data", "Job_data", "Request_data"):
            self.assertIn(nid, self.g.nodes)

    def test_op_call_target_flow(self):
        e = edge(self.g, "Worker_service", "Worker_service")
        self.assertEqual((e.target_op, e.payload, e.mods), ("run()", "run()", [("deadline", "2s")]))
        out = render.render("[Worker] -> run() @deadline(2s)\n")
        self.assertIn('Worker_service -- "run()" --> Worker_service', out)

    def test_op_call_then_chain(self):
        g = parse("[Worker] -> run({Job}) => <ok>\n")
        self.assertEqual(keys(g), {("Worker_service", "Worker_service", "->"),
                                   ("Worker_service", "ok_event", "=>")})
        self.assertNotIn("Job_data", g.nodes)


class Zoom(unittest.TestCase):
    def setUp(self):
        self.text = FIXTURE.read_text(encoding="utf-8")
        self.g = parse(self.text)

    def test_l3_nests_under_the_l2_occurrence(self):
        core = self.g.expansions["Core_service"]
        self.assertIn("Handler_service", core.expansions)
        self.assertNotIn("Handler_service", self.g.expansions)

    def test_alias_only_expansion_has_content(self):
        handler = self.g.expansions["Core_service"].expansions["Handler_service"]
        self.assertEqual({n.kind for n in handler.nodes.values()}, {"alias"})
        self.assertEqual(set(handler.expansions), {"ingress_alias", "process_alias",
                                                   "egress_alias"})
        proc = handler.expansions["process_alias"]
        self.assertEqual(keys(proc), {("Ctx_data", "Resp_data", "=>"),
                                      ("Ctx_data", "Err_data", "=>")})
        self.assertEqual(proc.joins[0].kind, "/")

    def test_depth_all_differs_from_depth_one(self):
        one = render.render(self.text, depth=1)
        every = render.render(self.text, depth=render.ALL_DEPTH)
        self.assertNotEqual(one, every)
        self.assertIn('subgraph ingress_alias["ingress"]', every)
        self.assertIn("classDef alias", every)

    def test_l2_falls_back_to_the_top_level(self):
        g = parse("--- L1: S ---\n[Edge] -> [Core]\n--- L2: [Core] ---\n"
                  "[Core] := {\n  [LB] -> [App]\n}\n--- L3: [Edge] ---\n"
                  "[Edge] := {\n  [Tls] -> [Proxy]\n}\n")
        self.assertIn("Core_service", g.expansions)
        self.assertIn("Edge_service", g.expansions)   # no level-2 [Edge]: top level


class Cardinality(unittest.TestCase):
    """CG1: a `×N` glued to the destination, or trailing a payload-less flow, is
    the destination's cardinality (Edge.card); only one trailing a payload retries."""

    def test_glued_and_payload_less_are_cardinality(self):
        g = parse("[LB] -> [App]×N\n[Primary] ~> [Replica]×2\n[Api] -> [Shard] ×4\n"
                  "[A] -> [B]×3 : charge()\n")
        for src, dst, card in (("LB_service", "App_service", "N"),
                               ("Primary_service", "Replica_service", "2"),
                               ("Api_service", "Shard_service", "4"),
                               ("A_service", "B_service", "3")):
            e = edge(g, src, dst)
            self.assertEqual((e.card, e.mods), (card, []), (src, dst))

    def test_trailing_a_payload_is_a_retry(self):
        g = parse("[A] -> [B] : charge() ×3\n[C] -> [D] : f() @timeout(5s) ×2\n")
        e = edge(g, "A_service", "B_service")
        self.assertEqual((e.card, e.mods), (None, [("×", "3")]))
        e = edge(g, "C_service", "D_service")
        self.assertEqual((e.card, e.mods), (None, [("timeout", "5s"), ("×", "2")]))

    def test_a_source_or_tree_count_stays_on_the_node(self):
        g = parse("[A]×3 -> [B] : f()\n[Search]\n    \\-*-= [Shard] ×N\n")
        self.assertEqual(edge(g, "A_service", "B_service").card, None)
        self.assertEqual(g.nodes["A_service"].mods, [("×", "3")])
        self.assertEqual(g.nodes["Shard_service"].mods, [("×", "N")])

    def test_only_the_marked_member_of_a_fan_out(self):
        g = parse("[LB] -> [A]×2 & [B]\n")
        self.assertEqual(edge(g, "LB_service", "A_service").card, "2")
        self.assertIsNone(edge(g, "LB_service", "B_service").card)


class SourceMods(unittest.TestCase):
    """MG3: modifiers between a source glyph and its arrow are the call's too."""

    def test_copied_onto_the_edges_of_the_next_arrow(self):
        g = parse("[A] @timeout(3s) -> [B] : f()\n[A] -> [C] @deadline(1s) -> [D]\n")
        self.assertEqual(edge(g, "A_service", "B_service").src_mods, [("timeout", "3s")])
        self.assertEqual(g.nodes["A_service"].mods, [("timeout", "3s")])   # unchanged
        self.assertEqual(edge(g, "A_service", "C_service").src_mods, [])
        self.assertEqual(edge(g, "C_service", "D_service").src_mods, [("deadline", "1s")])

    def test_signs_and_declarations_stay_off(self):
        g = parse("[A]×3 ! @loc(eu) -> [B]\n")
        self.assertEqual(edge(g, "A_service", "B_service").src_mods, [])


class ImpliedEmits(unittest.TestCase):
    """B12: a call returning an event, and a tree alert, emit it."""

    def test_call_return_event_is_emitted_by_the_callee(self):
        g = parse("[Judge] -> [Scorer] : score({Draft}) => <rated>\n"
                  "<rated> -> ~|history| : x\n")
        e = edge(g, "Scorer_service", "rated_event")
        self.assertEqual((e.kind, e.implied, e.line), ("=>", "return", 1))
        self.assertIsNone(edge(g, "Judge_service", "Scorer_service").implied)

    def test_a_data_return_or_target_op_implies_nothing(self):
        g = parse("[A] -> [B] : get() => {Row}\n[S] -> plan() => <Ready>\n")
        self.assertEqual([e for e in g.edges if e.implied], [])

    def test_tree_alert_is_a_conditional_emit(self):
        g = parse("|Replica|\n    \\-{lagging}-! <LagAlarm>\n<LagAlarm> ~> (OnCall)\n")
        e = edge(g, "Replica_store", "LagAlarm_event")
        self.assertEqual((e.kind, e.label, e.implied, e.line), ("?>", "lagging", "alert", 2))
        self.assertEqual(g.tree[1].rel, "!")                 # the branch is kept

    def test_alert_on_a_component_child_implies_nothing(self):
        g = parse("|Replica|\n    \\-! [Monitor]\n")
        self.assertEqual(g.edges, [])


class AliasRefs(unittest.TestCase):
    """B7: `×3 Retry` keeps its retry and takes the alias's modifiers."""

    def test_modifier_alias_after_a_retry(self):
        g = parse("[API] -> [Payment] : charge ×3 Retry\nRetry := @after(exp-backoff, cap=1min)\n")
        e = edge(g, "API_service", "Payment_service")
        self.assertEqual(e.payload, "charge")
        self.assertEqual(e.mods, [("×", "3"), ("after", "exp-backoff, cap=1min")])

    def test_an_undefined_name_stays_a_reference(self):
        e = edge(parse("[A] -> [B] : charge ×3 Nope\n"), "A_service", "B_service")
        self.assertEqual(e.mods, [("×", "3"), (render.ALIAS_REF, "Nope")])


class EventArgument(unittest.TestCase):
    """B8: `<H>({C})` is one glyph; the chain goes on through it."""

    def test_chain_continues_through_the_event(self):
        g = parse("|P| ~> <H>({C}) -> [R]\n")
        self.assertEqual(keys(g), {("P_store", "H_event", "~>"), ("H_event", "R_service", "->")})
        self.assertEqual(edge(g, "P_store", "H_event").payload, "{C}")
        self.assertNotIn("C_data", g.nodes)


class NarrowedTriggers(unittest.TestCase):
    """CG5: the transitions narrowing takes away are listed, not lost."""

    def test_narrowed_pairs(self):
        g = parse("<Go> -> {A}\nstate {A} { S -<Go>-> T }\nstate {B} { U -<Go>-> V }\n")
        self.assertEqual([t.owner for t in g.triggers], ["A_data"])
        self.assertEqual([(t.owner, t.src, t.dst) for t in g.narrowed],
                         [("B_data", "B_state_U", "B_state_V")])

    def test_none_without_aimed_flows(self):
        g = parse("[X] ~> <Go>\nstate {A} { S -<Go>-> T }\nstate {B} { U -<Go>-> V }\n")
        self.assertEqual(len(g.triggers), 2)
        self.assertEqual(g.narrowed, [])


class Dropped(unittest.TestCase):
    """Graph.dropped: every line the parser read and discarded."""

    def reasons(self, text):
        return [(d.line, d.reason, d.text) for d in parse(text).dropped]

    def test_unclosed_expansion(self):
        self.assertEqual(self.reasons("[Z] -> [Y]\n[A] := {\n  [B] -> [C]\n\n  # note\n"),
                         [(2, "unclosed", "[A] := {"), (3, "unclosed", "[B] -> [C]")])

    def test_unclosed_state(self):
        self.assertEqual(self.reasons("state {X} {\n  + -<a>-> S\n"),
                         [(1, "unclosed", "state {X} {"), (2, "unclosed", "+ -<a>-> S")])

    def test_ownerless_state(self):
        self.assertEqual(self.reasons("state {\n  a -> b\n}\n[Q] -> [R]\n"),
                         [(1, "no-owner", "state {"), (2, "no-owner", "a -> b"),
                          (3, "no-owner", "}")])

    def test_non_transition_inside_an_expansion(self):
        self.assertEqual(self.reasons("[A] := {\n  state {X} {\n    junk\n  }\n}\n"),
                         [(3, "not-a-transition", "junk")])

    def test_clean_document(self):
        self.assertEqual(parse(FIXTURE.read_text()).dropped, [])
        self.assertEqual(self.reasons("loop {\n  [A] -> [B]\n"), [])   # closed at the end


def _nest(depth):
    """`depth` expansions, each inside the last, each body with one flow."""
    lines = []
    for i in range(depth):
        lines += [f"{'  ' * i}[N{i}] := {{", f"{'  ' * i}  [N{i}] -> [M{i}]  # n{i}"]
    lines += [f"{'  ' * i}}}" for i in reversed(range(depth))]
    return "\n".join(lines) + "\n"


class NestedExpansions(unittest.TestCase):
    """Expansion bodies are read in one pass: a child parser per open body, on a
    stack — no re-reading per level, no recursion per level."""

    def test_deep_nesting(self):
        g = parse(_nest(1000))
        self.assertEqual(g.dropped, [])
        for i in range(1000):
            g = g.expansions[f"N{i}_service"]
            self.assertIn(f"M{i}_service", g.nodes)
        self.assertEqual(g.expansions, {})                 # the innermost body
        self.assertIn("flowchart TD", render.render(_nest(1000)))

    def test_each_line_is_read_once(self):
        read = []
        line = render._DocParser.line

        def spy(self, k, raw):
            read.append(self.ln(k))
            return line(self, k, raw)

        render._DocParser.line = spy
        try:
            text = _nest(40)
            g = parse(text)
        finally:
            render._DocParser.line = line
        self.assertEqual(len(read), len(set(read)))       # no line read twice
        self.assertEqual(len(read), 80)                    # the closing `}` lines: none
        inner = g.expansions["N0_service"].expansions["N1_service"]
        self.assertEqual([(n.node, n.text, n.line) for n in inner.notes],
                         [("N1_service", "n1", 4)])

    def test_unclosed_body_numbers_no_holes(self):
        # The body of `[X]` never closes inside `[A]`, so it is dropped unread: its
        # hole takes no number, and the hole after `[A]` is the second.
        g = parse("[?] -> [T]\n[A] := {\n  [X] := [?] -> [Y] } {\n  [?] -> [Z]\n}\n"
                  "[?] -> [W]\n")
        self.assertEqual(sorted(n for n in g.nodes if n.startswith("__")),
                         ["__service1", "__service2"])
        self.assertEqual([(d.line, d.reason) for d in g.dropped],
                         [(3, "unclosed"), (4, "unclosed")])


class ModelDocumented(unittest.TestCase):
    def test_docstring_names_every_graph_field(self):
        src = (_DIR / "render.py").read_text(encoding="utf-8")
        start = src.index("THE MODEL")
        notes = src[start:src.index("@dataclass", start)]
        for name in ("nodes", "edges", "joins", "blocks", "access", "sections", "layers",
                     "expansions", "tree", "triggers", "narrowed", "dropped", "notes", "role"):
            self.assertIn(f"#   {name}", notes, name)
        for name in ("Edge.card", "Edge.src_mods", "Edge.implied"):
            self.assertIn(name, notes, name)


if __name__ == "__main__":
    unittest.main()
