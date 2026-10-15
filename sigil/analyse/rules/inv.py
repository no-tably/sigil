"""
check_inv.py — Sigil composition checks over the document's own `@inv`
declarations (RFC 0003, rfcs/0003-composition-checks.catalog.md §4).

A rule module for check.py: `rules(ck)` returns this module's `ck.Rule`s, where
`ck` is check.py itself (passed in, so this module never imports it). Rules:

    SGC301 inv-unchecked       an `@inv` with no recognised head (listed, never failed)
    SGC302 inv-dangling        a recognised `@inv` naming what its anchor never touches
    SGC303 inv-contradicted    a recognised `@inv` the wiring visibly breaks
    SGC304 layer-inversion     a sync call up the declared `layers(…)` order
    SGC306 timeout-below-sla   a caller's `@timeout` below the callee's declared `@sla`

SGC173's declared-order clause (`@inv lock-order(…)`) lives with the lock-order
graph in check_state.py.

Recognised heads are the document's (`doc.inv_heads`): check.py's INV_HEADS plus
the loaded dialect's rule-pack heads. Each rule only checks what a declaration
says; none asks for the wiring to change to fit a claim (catalog SGC303 "Declare").

Reading of the catalog's SGC302 query: a store or event a recognised invariant
names that the document never draws is dangling whatever the head (a typo);
`atomic(…)` must name what its anchor writes or emits, `lock-order(…)` resources
some `@owns` acquires, `layers(…)` tiers some `@loc` uses. The catalog's key hint
(`idempotent(order_id)` with the key in no payload) is left out: payloads rarely
name a key, so on the corpus fixtures it flagged every keyed invariant and no
typo.

Standard library only. Deterministic: written order, never set order.
"""

from __future__ import annotations

import re
from functools import cached_property
from typing import NamedTuple, Optional


SYNC_KINDS = ("->", "→", "<->", "*>", "?>")       # the caller waits (as check_flow)
BOUND_HEADS = ("depth", "hops", "concurrency")

_GLYPH_REF_RE = re.compile(r"(?P<pre>[~*]?)(?:\|(?P<store>[^|]+)\||<(?P<event>[^<>]+)>)")
_BOUND_RE = re.compile(r"^\s*[\w-]+\s*(?:<=|≤|<)\s*(?P<n>\S+)\s*$")
_SLA_RE = re.compile(r"p(?P<p>\d+(?:\.\d+)?)\s*(?:<=|≤|<)\s*(?P<t>\d+(?:\.\d+)?\s*[a-z]+)")
_OPERATOR_RE = re.compile(r"\+\+|\|\||[-+*/]")


# ---------------------------------------------------------------------------
# Reading one `@inv` argument (pure)
# ---------------------------------------------------------------------------

def paren_args(arg: str) -> list:
    """The comma-separated arguments inside the head's parentheses, stripped:
    `atomic(|S|, <E>)` → ["|S|", "<E>"]; [] with no parentheses. Commas inside
    nested brackets do not split."""
    start = arg.find("(")
    if start < 0:
        return []
    out, depth, cur = [], 0, []
    for ch in arg[start + 1:]:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur).strip())
    return [a for a in out if a]


def keyless(arg: str) -> bool:
    return not paren_args(arg)


class GlyphRef(NamedTuple):
    kind: str                        # "store" | "event"
    name: str
    text: str                        # as written: `|Orders|`, `<Placed>`


def glyph_refs(arg: str) -> list:
    """The stores and events an argument names, in written order."""
    out = []
    for m in _GLYPH_REF_RE.finditer(arg):
        kind = "store" if m.group("store") is not None else "event"
        out.append(GlyphRef(kind, (m.group(kind) or "").strip(), m.group(0)))
    return out


def chain(arg: str, sep: str) -> list:
    """`layers(ui > data)` with sep ">" → ["ui", "data"]."""
    inner = ",".join(paren_args(arg))
    return [p.strip() for p in inner.split(sep) if p.strip()]


def closure(chains) -> frozenset:
    """(earlier, later) for every pair the chains order, closed transitively."""
    pairs = {(a, b) for ch in chains for i, a in enumerate(ch) for b in ch[i + 1:]}
    while True:
        more = {(a, d) for a, b in pairs for c, d in pairs if b == c} - pairs
        if not more:
            return frozenset(pairs)
        pairs |= more


def bound_ok(arg: str) -> bool:
    """`depth <= N` with N a positive integer."""
    m = _BOUND_RE.match(arg)
    return bool(m and m.group("n").isdigit() and int(m.group("n")) > 0)


def value_op_over_state(payload: Optional[str]) -> bool:
    """A value-operator update over the store's own state: `${state.n} + 1`."""
    text = payload or ""
    if "${state." not in text:
        return False
    return bool(_OPERATOR_RE.search(re.sub(r"\$\{[^}]*\}", "", text)))


def sla_percentiles(arg: Optional[str]) -> list:
    """(percentile, duration text) of an `@sla` argument: `p99<800ms` → [(99.0, "800ms")]."""
    return [(float(m.group("p")), m.group("t").replace(" ", ""))
            for m in _SLA_RE.finditer(arg or "")]


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


# ---------------------------------------------------------------------------
# The document's invariants and the facts the rules read
# ---------------------------------------------------------------------------

class Inv(NamedTuple):
    """One `@inv`: where it is written (a node, a wire, a block), its anchor's
    glyph text, its argument and line, and the node ids that act for the anchor
    (a node and its expansion, a wire's source, a block's members)."""
    where: str
    anchor: str
    arg: str
    line: int
    actors: tuple
    head: str


def mods_of(mods) -> list:
    return [arg or "" for name, arg in mods if name == "inv"]


def mod_arg(mods, name: str) -> Optional[str]:
    return next(("" if a is None else a for n, a in mods if n == name), None)


def expansion_ids(graph, nid: str, walk) -> tuple:
    """nid and every node of its `:= { … }` expansion, nested ones included."""
    sub = graph.expansions.get(nid)
    if sub is None:
        return (nid,)
    return (nid,) + tuple(x for g, _o, _l in walk(sub) for x in g.nodes)


def glyph_pattern(name: str, delims: Optional[dict]) -> "re.Pattern":
    """The node as written: its name inside its kind's delimiters (`[A]`, `|S|`),
    so `[A]` never matches `[AB]`; a kind with no delimiters (a state) is the bare
    name, not glued to a longer word."""
    op, cl = (delims or {}).get("open") or "", (delims or {}).get("close") or ""
    if op:
        return re.compile(re.escape(op) + r"\s*" + re.escape(name) + r"\s*" + re.escape(cl))
    return re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-])")


def locate(code: list, arg: str, glyph: "re.Pattern", fallback: int) -> int:
    """The 1-based line whose code writes `@inv arg`: among those that write the
    anchor's glyph, the fallback (the anchor's own line) when it is one, else the
    first; with no such line, the first line writing the `@inv`, else the fallback."""
    want = squash(f"@inv{arg}")
    hits = [n for n, text in enumerate(code, start=1) if want in squash(text)]
    named = [n for n in hits if glyph.search(code[n - 1])]
    if fallback in named:
        return fallback
    return (named or hits or [fallback])[0]


def block_line(code: list, arg: str, head: int, close: int) -> int:
    """The line of a block's `@inv arg`: its head when the head writes it, else
    its closing `}` (a block with no close line keeps its head)."""
    if head and squash(f"@inv{arg}") in squash(code[head - 1]):
        return head
    return close or head


class Facts:
    """What this module's rules read off one check.Doc, each on first use."""

    def __init__(self, ck, doc):
        self.ck = ck
        self.doc = doc

    @cached_property
    def code(self) -> list:
        """Every line with its comment cut (block-string bodies blanked)."""
        strip = self.doc.render.strip_comment
        quoted = self.doc.layout.quoted
        return ["" if n in quoted else strip(line)
                for n, line in enumerate(self.doc.lines, start=1)]

    @cached_property
    def nodes(self) -> dict:
        out = {}
        for g, _o, _l in self.doc.graphs:
            for nid, n in g.nodes.items():
                out.setdefault(nid, n)
        return out

    @cached_property
    def mods(self) -> dict:
        """{node id: [(name, arg)]} over every occurrence in every graph."""
        out = {}
        for g, _o, _l in self.doc.graphs:
            for nid, n in g.nodes.items():
                mine = out.setdefault(nid, [])
                mine += [p for p in n.mods if p not in mine]
        return out

    def kind(self, nid: str) -> str:
        n = self.nodes.get(nid)
        return n.kind if n is not None else ""

    def label(self, nid: str) -> str:
        n = self.nodes.get(nid)
        return f"`{self.doc.scene.kit.node_label(n)}`" if n is not None else f"`{nid}`"

    def ids_named(self, kind: str, name: str) -> list:
        return [nid for nid, n in self.nodes.items() if n.kind == kind and n.name == name]

    @cached_property
    def invs(self) -> list:
        """Every `@inv` of the document, in line order, each once."""
        found = {}
        walk, node_lines = self.doc.render._walk, self.doc.scene.kit.node_lines
        for g, _o, _l in self.doc.graphs:
            lines = node_lines(g, notes=False)
            for nid, n in g.nodes.items():
                args = mods_of(n.mods)
                glyph = glyph_pattern(n.name, self.delims(n.kind)) if args else None
                for arg in args:
                    line = locate(self.code, arg, glyph, lines.get(nid, 0))
                    self._add(found, "node", self.label(nid), arg, line,
                              expansion_ids(g, nid, walk))
            for e in g.edges:
                if e.implied:
                    continue
                # e.src_mods are also the source node's mods, read above.
                for arg in mods_of(e.mods):
                    self._add(found, "wire", self.label(e.src), arg, e.line, (e.src,))
            for b in getattr(g, "blocks", None) or []:
                head_line, close_line = b.lines
                actors = tuple(dict.fromkeys(list(b.subject) + list(b.refs) + list(b.members)))
                for arg in mods_of(b.modifiers):
                    self._add(found, "block", f"`{b.header}`", arg,
                              block_line(self.code, arg, head_line, close_line), actors)
        return sorted(found.values(), key=lambda i: (i.line, i.arg, i.anchor))

    def _add(self, found: dict, where: str, anchor: str, arg: str, line: int, actors):
        """One written `@inv` is one invariant: a second reading of the same
        argument on the same line (a node's and its block header's) adds its
        actors to the first."""
        key = (arg, line)
        first = found.get(key)
        if first is None:
            found[key] = Inv(where, anchor, arg, line, tuple(actors), self.ck.inv_head(arg))
        else:
            merged = tuple(dict.fromkeys(first.actors + tuple(actors)))
            found[key] = first._replace(actors=merged)

    def delims(self, kind: str) -> Optional[dict]:
        kit = self.doc.scene.kit
        return kit.KINDS.get(kind) or kit.CORE_KINDS.get(kind)

    def recognised(self) -> list:
        return [i for i in self.invs if i.head in self.doc.inv_heads]

    @cached_property
    def flows(self) -> list:
        return [w for w in self.doc.sc.wires if w.role == "flow"
                and not getattr(w.edge, "implied", None)]

    def writes(self, actors: tuple, sid: str) -> bool:
        """Some actor writes the store: a writer by declaration, ownership or a
        write flow, or a flow into it whose mode is unknown."""
        if set(actors) & set(self.doc.writers(sid)):
            return True
        return any(w.src in actors and w.dst == sid and self.doc.access_mode(w) == "unknown"
                   for w in self.flows)

    def emits(self, actors: tuple, eid: str) -> bool:
        return any(w.src in actors and w.dst == eid for w in self.flows)

    @cached_property
    def owned(self) -> frozenset:
        """The names of the stores some `@owns` acquires (on a node or a block)."""
        args = [a for mods in self.mods.values() for n, a in mods if n == "owns"]
        args += [a for g, _o, _l in self.doc.graphs for b in getattr(g, "blocks", None) or []
                 for n, a in b.modifiers if n == "owns"]
        return frozenset(r.name for a in args for r in glyph_refs(a or "") if r.kind == "store")

    def loc(self, nid: str) -> Optional[str]:
        arg = mod_arg(self.mods.get(nid, ()), "loc")
        return arg.strip() if arg else None

    @cached_property
    def tiers(self) -> frozenset:
        return frozenset(t for t in (self.loc(nid) for nid in self.nodes) if t)


def facts_of(ck, doc) -> Facts:
    """The Facts of a document, built once and kept on it."""
    found = doc.__dict__.get("_inv_facts")
    if found is None:
        found = doc.__dict__["_inv_facts"] = Facts(ck, doc)
    return found


# ---------------------------------------------------------------------------
# SGC301 inv-unchecked
# ---------------------------------------------------------------------------

def find_unchecked(ck, f: Facts):
    for inv in f.invs:
        if inv.head in f.doc.inv_heads:
            continue
        yield ck.Hit(inv.line, f"`@inv {inv.arg}` is taken on trust: no recognised "
                               "invariant states it",
                     f"`{inv.arg}` is taken on trust. Is there a recognised invariant "
                     "that states it?",
                     anchor=("line", inv.line), scopes=(("inv", inv.arg),))


# ---------------------------------------------------------------------------
# SGC302 inv-dangling
# ---------------------------------------------------------------------------

def find_dangling(ck, f: Facts):
    for inv in f.recognised():
        missing = [r for r in glyph_refs(inv.arg) if not drawn(f, r)]
        if missing:
            yield from (undrawn_hit(ck, f, inv, r) for r in missing)
        elif inv.head == "atomic":
            yield from untouched_hits(ck, f, inv)
        elif inv.head == "lock-order":
            yield from unowned_hits(ck, f, inv)
        if inv.head == "layers":
            yield from unused_tier_hits(ck, f, inv)


def drawn(f: Facts, ref: GlyphRef) -> bool:
    """The design draws the glyph, or (a store) some `@owns` acquires it."""
    return bool(f.ids_named(ref.kind, ref.name)) or (ref.kind == "store"
                                                     and ref.name in f.owned)


def dangling_hit(ck, inv: Inv, statement: str, ask: str, fix: str):
    return ck.Hit(inv.line, statement, ask, anchor=("line", inv.line), fix=fix,
                  scopes=(("inv", inv.arg),))


def undrawn_hit(ck, f: Facts, inv: Inv, ref: GlyphRef):
    names = {n.name for n in f.nodes.values() if n.kind == ref.kind}
    names = sorted(names | f.owned if ref.kind == "store" else names)
    near = ck.nearest_name(ref.name, names)
    shown = f"|{near}|" if ref.kind == "store" else f"<{near}>"
    hint = f" Did you mean `{shown}`?" if near else ""
    return dangling_hit(
        ck, inv, f"`@inv {inv.arg}` names `{ref.text}`, which the design never draws",
        f"`{ref.text}` appears nowhere in the design.{hint or ' What should it name?'}",
        f"write `{shown}`" if near else "name a glyph the design draws")


def untouched_hits(ck, f: Facts, inv: Inv):
    for ref in glyph_refs(inv.arg):
        ids = f.ids_named(ref.kind, ref.name)
        touched = any(f.writes(inv.actors, i) if ref.kind == "store" else
                      f.emits(inv.actors, i) for i in ids)
        if touched:
            continue
        verb = "writes" if ref.kind == "store" else "emits"
        yield dangling_hit(
            ck, inv, f"{inv.anchor} never {verb} `{ref.text}`, which `@inv {inv.arg}` names",
            f"{inv.anchor} never {verb} `{ref.text}`. Which effect does `atomic` mean?",
            f"name what {inv.anchor} {verb}, or move the `@inv` to the node that does")


def unowned_hits(ck, f: Facts, inv: Inv):
    for ref in glyph_refs(inv.arg):
        if ref.kind == "store" and ref.name not in f.owned:
            yield dangling_hit(
                ck, inv, f"`{ref.text}` is in `@inv {inv.arg}` but no `@owns` acquires it",
                f"No `@owns` acquires `{ref.text}`. Which resource does the order mean?",
                f"name a resource an `@owns` acquires, or drop `{ref.text}` from the order")


def unused_tier_hits(ck, f: Facts, inv: Inv):
    for tier in chain(inv.arg, ">"):
        if tier not in f.tiers:
            near = ck.nearest_name(tier, sorted(f.tiers))
            hint = f" Did you mean `{near}`?" if near else ""
            yield dangling_hit(
                ck, inv, f"the tier `{tier}` in `@inv {inv.arg}` is on no `@loc`",
                f"No node carries `@loc({tier})`.{hint or ' Which tier is meant?'}",
                f"write `{near}`" if near else f"put `@loc({tier})` on its nodes")


# ---------------------------------------------------------------------------
# SGC303 inv-contradicted
# ---------------------------------------------------------------------------

def find_contradicted(ck, f: Facts):
    for inv in f.recognised():
        if inv.head == "immutable":
            yield from immutable_hits(ck, f, inv)
        elif inv.head == "idempotent" and keyless(inv.arg):
            yield from counter_hits(ck, f, inv)
        elif inv.head in BOUND_HEADS and not bound_ok(inv.arg):
            yield contradicted_hit(
                ck, inv, f"`@inv {inv.arg}` states no positive integer bound",
                f"`{inv.arg}` gives no positive whole number. What is the bound?",
                f"a positive whole number after `<=` (`@inv {inv.head} <= 8`)")
        elif inv.head == "ordered" and keyless(inv.arg):
            yield from unordered_hits(ck, f, inv)


def contradicted_hit(ck, inv: Inv, statement: str, ask: str, fix: str):
    return ck.Hit(inv.line, statement, ask, anchor=("line", inv.line), fix=fix,
                  scopes=(("inv", inv.arg),))


def subjects(f: Facts, inv: Inv, kinds: tuple) -> list:
    """The glyphs an invariant is about: those of `kinds` its argument names, else
    its anchor when it is one of them."""
    named = [i for r in glyph_refs(inv.arg) for i in f.ids_named(r.kind, r.name)
             if f.kind(i) in kinds]
    if named:
        return named
    return [a for a in inv.actors[:1] if f.kind(a) in kinds]


def immutable_hits(ck, f: Facts, inv: Inv):
    for sid in subjects(f, inv, ("store",)):
        n, label = f.nodes[sid], f.label(sid)
        if n.is_mutable:
            yield contradicted_hit(
                ck, inv, f"{label} is a mutable `~|…|` store, yet declared `@inv immutable`",
                f"{label} is declared mutable and immutable. Which is it?",
                "the plain `|S|` kind for a write-once store, or drop `immutable`")
            continue
        for w in f.flows:
            if w.dst == sid and value_op_over_state(w.payload):
                yield contradicted_hit(
                    ck, inv, f"{f.label(w.src)} updates {label} over its own state "
                             f"(`{w.payload}`), yet it is declared `@inv immutable`",
                    f"{f.label(w.src)} changes {label} in place. How is it immutable?",
                    "a store kind that matches the writes, or drop `immutable`")
                break


def counter_hits(ck, f: Facts, inv: Inv):
    for w in f.flows:
        if w.src in inv.actors and f.kind(w.dst) == "store" and value_op_over_state(w.payload):
            yield contradicted_hit(
                ck, inv, f"{f.label(w.src)} updates {f.label(w.dst)} by `{w.payload}` on "
                         "every call, yet `@inv idempotent` names no key",
                f"{f.label(w.src)} changes {f.label(w.dst)} on every call. How is a "
                "repeat idempotent without a key?",
                "`@inv idempotent(key)`: the key a repeat is recognised by")
            return


def counted(f: Facts, nid: str, w) -> bool:
    """The consumer runs as several instances: `×N` (N > 1 or symbolic) on it or
    on the flow into it."""
    arg = mod_arg(f.mods.get(nid, ()), "×") or getattr(w.edge, "card", None)
    return bool(arg) and not (arg.strip().isdigit() and int(arg) <= 1)


def unordered_hits(ck, f: Facts, inv: Inv):
    for sid in subjects(f, inv, ("event", "store")):
        if not f.nodes[sid].is_stream:
            continue
        for w in f.flows:
            if w.src != sid or not counted(f, w.dst, w):
                continue
            if mod_arg(f.mods.get(w.dst, ()), "owns") is not None:
                continue
            yield contradicted_hit(
                ck, inv, f"{f.label(sid)} is consumed by several {f.label(w.dst)} instances "
                         "with no owner, yet `@inv ordered` names no key",
                f"Several {f.label(w.dst)} instances consume {f.label(sid)}. How is the "
                "order kept without a key?",
                "`@inv ordered(key)` with key-partitioned consumers, or `@owns` on the "
                "consumer")
            break


# ---------------------------------------------------------------------------
# SGC304 layer-inversion
# ---------------------------------------------------------------------------

def find_layer_inversion(ck, f: Facts):
    above = closure(chain(i.arg, ">") for i in f.recognised() if i.head == "layers")
    if not above:
        return
    for w in f.flows:
        if w.kind not in SYNC_KINDS or w.src == w.dst:
            continue
        lo, hi = f.loc(w.src), f.loc(w.dst)
        if lo and hi and (hi, lo) in above:
            src, dst = f.label(w.src), f.label(w.dst)
            yield ck.Hit(w.line, f"{src} ({lo}) calls {dst} ({hi}), a tier above it",
                         f"{src} ({lo}) calls {dst} ({hi}) above it. Is that upcall "
                         "intended?",
                         anchor=("wire", w.ident),
                         fix="correct the `@loc` or the `layers(…)` order, or send an "
                             "event up (`~>`)")


# ---------------------------------------------------------------------------
# SGC306 timeout-below-sla
# ---------------------------------------------------------------------------

def unit_graph(f: Facts, w):
    prog = f.doc.prog
    ui = prog.wire_unit.get(id(w))
    return prog.units[ui].graph if ui is not None else f.doc.graph


def enclosing_blocks(g, w) -> list:
    """(index, Block) of the blocks enclosing w, innermost first."""
    blocks = getattr(g, "blocks", None) or []
    out, bi = [], w.block
    while bi is not None and 0 <= bi < len(blocks):
        out.append((bi, blocks[bi]))
        bi = blocks[bi].parent
    return out


def routed(f: Facts, w, chain_ids: set) -> bool:
    """A `!>` route takes w's failure: one continuing its line, one after an
    enclosing block, or the node's own."""
    ui = f.doc.prog.wire_unit.get(id(w), 0)
    for _r, g in f.doc.prog.routes.get((ui, w.src), ()):
        if g is None or (g[0] == "calls" and ("call", w.ident) in g[1]) or (
                g[0] == "block" and g[1] in chain_ids):
            return True
    return False


def races(g, w, blocks: list) -> bool:
    """w is a member of a race: `&?`, or a `parallel @any` body."""
    joins = getattr(g, "joins", None) or []
    j = getattr(w.edge, "dst_join", None)
    if j is not None and 0 <= j < len(joins) and joins[j].kind == "&?":
        return True
    return any(b.kind == "parallel" and any(n == "any" for n, _a in b.modifiers)
               for _i, b in blocks)


def cuts_tail(f: Facts, w, policy: list) -> bool:
    """The call cuts the callee's tail on purpose: a `@fallback`, a route, a race."""
    if mod_arg(policy, "fallback") is not None:
        return True
    g = unit_graph(f, w)
    blocks = enclosing_blocks(g, w)
    return routed(f, w, {i for i, _b in blocks}) or races(g, w, blocks)


def worst_percentile(sim, sla: Optional[str], bound: float) -> Optional[tuple]:
    """(percentile, duration text) of the lowest stated percentile above the bound."""
    over = [(p, t) for p, t in sla_percentiles(sla)
            if sim.duration(t) is not None and sim.duration(t) > bound]
    return min(over, default=None)


def find_timeout_below_sla(ck, f: Facts):
    sim, scene = f.doc.sim, f.doc.scene
    for w in f.flows:
        if w.kind not in SYNC_KINDS or w.src == w.dst:
            continue
        policy = scene.call_policy(w)
        timeout = mod_arg(policy, "timeout")
        bound = sim.duration(timeout)
        sla = mod_arg(f.mods.get(w.dst, ()), "sla")
        if bound is None or not sla:
            continue
        found = worst_percentile(sim, sla, bound)
        if found is None or cuts_tail(f, w, policy):
            continue
        p, stated = found
        share = f"{100 - p:g}%"
        src, dst = f.label(w.src), f.label(w.dst)
        yield ck.Hit(w.line, f"{src} gives up on {dst} after {timeout}, below its declared "
                             f"p{p:g} of {stated}: more than {share} of calls time out by "
                             "design",
                     f"{dst} declares p{p:g} {stated} but {src} gives up at {timeout}. "
                     "Is cutting the tail intended?",
                     anchor=("wire", w.ident),
                     fix=f"a timeout of at least {stated}, a `@fallback` or `!>` route on "
                         "the call, or a corrected `@sla`")


# ---------------------------------------------------------------------------
# The module's rules (catalog §4)
# ---------------------------------------------------------------------------

class Spec(NamedTuple):
    """One rule's registry data; `find(ck, facts)` yields its Hits.

    satisfiers are the declarations that clear a candidate (catalog §1.6), never
    the ones that switch the rule on: SGC303 fires on a recognised `@inv` head,
    SGC304 on `layers(…)` with `@loc`, SGC306 on a `@timeout` against an `@sla`.
    Clearing that depends on a value (a positive bound, a timeout at or above the
    percentile, a corrected `@sla` or `@loc`, a store kind that matches
    `immutable` given how it is written) is left to `find`.
    """
    id: str
    name: str
    tier: str
    find: object
    ask: str
    why: str
    fix: str
    satisfiers: tuple = ()


SPECS = (
    Spec("SGC301", "inv-unchecked", "hint", find_unchecked,
         "This invariant is taken on trust. Is there a recognised invariant that states it?",
         "An invariant no check can read protects only as far as readers trust it.",
         "restate it with a recognised head (language.md \"Recognised invariants\"), or "
         "leave it as a claim for readers"),
    Spec("SGC302", "inv-dangling", "advisory", find_dangling,
         "This invariant names something its anchor never touches. What should it name?",
         "A claim about a misspelt or stale name protects nothing.",
         "name what the anchor really touches, or move the `@inv` to the node that does",
         satisfiers=(("document", "@loc"), ("owner", "@owns"))),
    Spec("SGC303", "inv-contradicted", "binding", find_contradicted,
         "The wiring breaks this invariant as written. Which form of it holds?",
         "A declared invariant the design visibly breaks misleads every reader.",
         "the form the wiring supports: a key, a positive integer bound, or a matching "
         "store kind",
         satisfiers=(("callee", "idempotent(key)"), ("store", "ordered(key)"),
                     ("owner", "@owns"))),
    Spec("SGC304", "layer-inversion", "binding", find_layer_inversion,
         "A lower tier calls a higher one. Is that upcall intended?",
         "Layers mean something only while calls go down them (Dijkstra 1968; "
         "Parnas 1979).",
         "correct the `@loc` or the `layers(…)` order, or send an event up (`~>`)",
         satisfiers=(("call", "~>"),)),
    Spec("SGC306", "timeout-below-sla", "advisory", find_timeout_below_sla,
         "The caller gives up before the callee's declared percentile. Is cutting the "
         "tail intended?",
         "A timeout below the callee's stated percentile fails a share of calls by "
         "design.",
         "a timeout at or above the percentile, a `@fallback` or `!>` route, or a "
         "corrected `@sla`",
         satisfiers=(("call", "@fallback"), ("call", "!>"), ("call", "&?"),
                     ("block", "@any"))),
)


def spec_rule(ck, spec: Spec):
    def match(doc):
        yield from spec.find(ck, facts_of(ck, doc))
    return ck.Rule(spec.id, spec.name, spec.tier, ask=spec.ask, why=spec.why, fix=spec.fix,
                   match=match, satisfiers=spec.satisfiers, family=spec.id[3:5])


def rules(ck) -> list:
    return [spec_rule(ck, s) for s in SPECS]
