"""
sigil.analyse.check — Sigil composition checks: is the design a document
describes sound?

`sigil lint` checks that a document is well formed; `sigil check` asks whether
the design says how its risks are handled (RFC 0003, rfcs/0003-composition-checks.catalog.md).
A finding never forbids a shape: it names a risk the design leaves undeclared, and is satisfied by
declaring the handling in the notation (`@timeout`, `×N`, `!>`, `@inv …`, …) or by
a reasoned acknowledgement:

    [API] -> [Payments] : charge(total) ×3   # accepts: retry-without-idempotency — an upsert

Usage:
    sigil check <file.sigil> [--mode sketch|craft|spec] [--k N] [--budget N]
                [--overlaps off|listed|all|N]
                [--limit NAME=N ...] [--json] [--all] [--export]
    sigil check --rules
    cat doc.sigil | sigil check -

Options:
    --mode M     check as mode M (default: the document's mode line; none = sketch)
    --k N        failure combinations explored per scenario (default: 1, spec 2)
    --budget N   runs one exploration may make: deviation combinations, then
                 (in spec) the state starts `Owner=State`, then overlap runs
                 (default: rules.trace.BUDGET); the overlap runs also stop
                 once their frames reach rules.trace.work_cap
                 (WORK_PER_RUN frames per run of the budget, at least BUDGET's)
    --overlaps off|listed|all|N  overlap runs (a later entry started while an
                 earlier one's episode runs) to make: none; the listed starts
                 (sim.overlaps), alone and with each deviation; those, then every
                 start tick of each earlier episode's busy window; or all but at
                 most N runs. Default: all in spec (the exhaustive check before a
                 spec is final), off in sketch and craft
    --limit NAME=N  set one simulator bound (sim.Limits: depth, iterations,
                 spawn, activations, …), over the document's own (`name=N` on its
                 `#%` line) and the defaults: a flag wins, raised or lowered;
                 repeatable
    --json       one JSON object: mode, k, limits (as the runs had them, the
                 defaults grown to the document; with budget), limit_sources
                 (each limit's source: default, scaled, document or flag), findings,
                 acknowledged; kind (a `#%` line); state_starts (in spec, when
                 the document has any: the `Owner=State` runs made, by name, and
                 how many the budget left unrun)
    --all        also print the findings the mode hides (sketch's info)
    --export     check export readiness too: the readiness rules (EXPORT_MODULES:
                 SGC401 no-home, SGC402 untyped-boundary) run with the others,
                 as `sigil export`'s gate runs them
    --rules      list the rule registry (the readiness rules too) and exit
    --dialect D  load a dialect (as `sigil lint` does; default $SIGIL_DIALECT)

Output (lint-compatible, sorted by line, then rule id, then anchor):
    <severity>:<line>:<SGCnnn>: <name>: <message>
    accepted:<line>:<SGCnnn>: <name>: <reason>        (acknowledged findings)

Exit codes: 0 no warnings or errors · 1 warnings only · 2 errors (or bad input).
Acknowledged, hidden and folded findings never count; a cause keeps its own
severity (catalog §1.7).

Severity follows the mode, capped by the rule's tier (catalog §1.2):

    tier      sketch         craft                   spec
    binding   info, hidden   warn (asked)            error
    advisory  info, hidden   warn (asked)            warn
    hint      not emitted    info (asked)            info

A finding built on a guess drops one tier (never below hint); a trace finding
whose witness needs k >= 2 deviations, or that comes from a rule still marked
`trace_warn_only`, is capped at warn.

Rule modules. This module loads the modules in RULE_MODULES (sigil.analyse.rules)
that exist; each defines `rules(ck)` and returns a list of `ck.Rule`, where `ck`
is this module (passed in, so a rule module never imports sigil.analyse.check
itself). A rule's `match(doc)`
yields `ck.Hit`s; `doc` is a `ck.Doc` (lines, mode, k, graph, comments, acks, and
the simulator's canonical scene and program, all computed on first use). A module
may also define `exploration_causes(ck)`, match functions whose Hits this module
gathers into the one SGC090 rule, and `extend_rules(ck, rules)`, which returns the
whole registered list with its own additions to rules other modules register
(idempotent; applied after every module's `rules`). The modules in EXPORT_MODULES
load the same way, but only for a check asked for export readiness (`--export`,
`check(…, export=True)`); their names (EXPORT_NAMES) are known either way, so an
acknowledgement of one is no unknown rule, and never stale, in a plain check.
The modules in STRUCTURE_MODULES (the structure rules, SGC176-SGC177) load with
RULE_MODULES wherever they ship; the playground leaves them out, and its check
runs without them the same way (their names stay in CORE_NAMES).
A loaded dialect's rule pack (sigil.core.dialects,
`check_rules`, `READ_VERBS`, `policy_words`) joins the registry and the Doc. The
registry, the finding record, tiers × modes, acknowledgements and folding live
here; rule modules hold only matches and their data.

Standard library only. Deterministic: no clock, no randomness, no set-order output.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable, Optional

# Layout and acknowledgements are read in core (check.Ack, check.read_acks, … keep
# their names here).
from sigil.core.statements import read_document
from sigil.core.comments import (  # noqa: F401  (re-exported)
    Ack, Layout, RULE_ID_RE, ack_span, parse_ack, read_acks, walk_layout)


_RULES = Path(__file__).resolve().parent / "rules"      # the rule modules


def _sim():
    """The simulator, imported on first use."""
    from sigil.model import sim
    return sim


# ---------------------------------------------------------------------------
# The catalog: every core id and name (rfcs/0003-composition-checks.catalog.md §0).
# Names are what people type; ids never change and retired ids are never reused. A name is known
# (an acknowledgement may cite it) before its rule is implemented.
# ---------------------------------------------------------------------------

CORE_NAMES = {
    "SGC001": "ack-unknown-rule", "SGC002": "ack-without-reason",
    "SGC003": "ack-unused", "SGC004": "policy-in-prose",
    "SGC090": "exploration-incomplete",
    "SGC101": "unguarded-call", "SGC102": "retry-amplification",
    "SGC103": "timeout-budget-inverted", "SGC104": "retry-without-backoff",
    "SGC111": "retry-without-idempotency", "SGC112": "duplicate-delivery",
    "SGC113": "dual-write", "SGC114": "poison-message",
    "SGC121": "saga-uncompensated", "SGC122": "fragile-compensation",
    "SGC123": "race-loser-effects",
    "SGC131": "shared-writable-store", "SGC132": "undeclared-access",
    "SGC133": "lost-update", "SGC134": "held-across-call", "SGC135": "stale-read",
    "SGC136": "shared-data-order",
    "SGC141": "unreachable-state", "SGC142": "dead-end-state",
    "SGC143": "ambiguous-transition", "SGC144": "no-exit", "SGC145": "orphan-event",
    "SGC146": "undriven-transition", "SGC147": "wait-without-timeout",
    "SGC148": "wildcard-leaves-terminal",
    "SGC151": "unbounded-recursion", "SGC152": "async-cycle",
    "SGC153": "unbounded-loop",
    "SGC161": "unbounded-buffer", "SGC162": "unbounded-result",
    "SGC163": "capacity-mismatch", "SGC165": "fanout-tail",
    "SGC166": "single-point-of-failure", "SGC167": "unbounded-spawn",
    "SGC171": "dependency-cycle", "SGC172": "expansion-escape",
    "SGC173": "lock-order-cycle", "SGC174": "optional-callee", "SGC175": "unreached",
    "SGC176": "unit-cycle", "SGC177": "large-unit",
    "SGC201": "unhandled-failure", "SGC202": "dead-failure-route",
    "SGC203": "event-ignored", "SGC204": "race", "SGC205": "ordering-unstated",
    "SGC206": "stalled-join",
    "SGC301": "inv-unchecked", "SGC302": "inv-dangling", "SGC303": "inv-contradicted",
    "SGC304": "layer-inversion", "SGC306": "timeout-below-sla",
}
RETIRED_IDS = frozenset({"SGC105", "SGC164", "SGC305"})
# The export readiness rules (rules.export): in the catalog's id space, run only
# when a check is asked for export readiness (EXPORT_MODULES).
EXPORT_NAMES = {"SGC401": "no-home", "SGC402": "untyped-boundary"}
CATALOG = {**CORE_NAMES, **EXPORT_NAMES}
# The structure rules (rules.structure, STRUCTURE_MODULES): core rules every check
# runs where their module ships; the playground ships neither it nor the reading it
# reads, and its check runs without them (see idle_ids).
STRUCTURE_NAMES = {"SGC176": "unit-cycle", "SGC177": "large-unit"}
# Core id spaces: lint codes are SGL…, check ids SGC…. `sigil lint` keeps no table
# of its codes, so the core reserves both prefixes whole: a dialect's rule id or
# lint code may start with neither (registry_problem, dialect_pack).
CORE_ID_PREFIXES = {"SGL": "lint codes", "SGC": "check ids"}
# Fixed by editing a line, never by a decision about the design (catalog §5): the
# ack-* rules (SGC001-SGC003). No Rule or Hit flag can make these acknowledgeable.
# SGC090 is acknowledgeable for its loop-cap and cut-run causes only, on the
# loop's or the cut episode's entry line (see exploration_rule). SGC004 policy-in-prose is acknowledgeable: its match reads
# prose and can misfire.
NOT_ACKNOWLEDGEABLE = frozenset({"ack-unknown-rule", "ack-without-reason", "ack-unused"})
EXPLORATION = ("SGC090", "exploration-incomplete")

# The recognised `@inv` heads (RFC 0003 §3, Decision Q4). A dialect may add heads,
# never redefine one of these.
INV_HEADS = frozenset({
    "idempotent", "dedup", "atomic", "ordered", "serialised", "cas", "immutable",
    "depth", "hops", "terminates", "retention", "lock-order", "layers",
    "retry-budget", "limit", "concurrency", "consistent"})

LAYERS = {"0": "meta", "1": "structural", "2": "behavioural", "3": "invariant",
          "4": "export"}
TIERS = ("binding", "advisory", "hint")
MODES = ("sketch", "craft", "spec")
DEFAULT_K = {"sketch": 1, "craft": 1, "spec": 2}
# Overlap runs (a later entry started while an earlier one's episode runs) are the
# exhaustive part of an exploration: off while a design is drafted, every start
# tick (within the budget) in spec, the check before a spec is final.
# The group of each rule a system kind can turn off (sigil.core.kinds: the `#%`
# line); every other rule, a dialect's too, is "global" and always runs.
RULE_GROUPS = {
    **dict.fromkeys(("SGC101", "SGC102", "SGC103", "SGC104", "SGC111", "SGC112", "SGC114",
                     "SGC135", "SGC165", "SGC206", "SGC306"), "network"),
    **dict.fromkeys(("SGC123", "SGC131", "SGC133", "SGC134", "SGC136", "SGC173", "SGC204",
                     "SGC205"), "concurrency"),
    **dict.fromkeys(("SGC163", "SGC166"), "traffic"),
    **dict.fromkeys(("SGC144", "SGC147", "SGC152", "SGC153"), "ending"),
    **dict.fromkeys(("SGC145", "SGC146", "SGC175"), "entry"),
}


def group_of(rule_id: str) -> str:
    return RULE_GROUPS.get(rule_id, "global")


OVERLAPS = ("off", "listed", "all")
DEFAULT_OVERLAPS = {"sketch": "off", "craft": "off", "spec": "all"}
# State starts (sim.state_starts: a machine begun in a later state, `Owner=State`)
# are listed runs on the default choices, one per state with a way out: walked in
# spec, whatever --overlaps or the system kind says (they race nothing).
STATE_START_MODES = frozenset({"spec"})


# tier → mode → (severity, hidden); None: not emitted (catalog §1.2).
SEVERITY = {
    "binding": {"sketch": ("info", True), "craft": ("warn", False), "spec": ("error", False)},
    "advisory": {"sketch": ("info", True), "craft": ("warn", False), "spec": ("warn", False)},
    "hint": {"sketch": None, "craft": ("info", False), "spec": ("info", False)},
}


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    """One rule (catalog §1.6). `satisfiers` and `implies` are data so a later
    declarative front end only has to produce `match`.

    satisfiers  ((site, form), …): declarations that clear a candidate; site is
                call|callee|store|block|machine|owner|document, form a modifier,
                a recognised @inv head, an arrow ("!>", "?>") or a store kind.
    implies     ((rule name, scope), …): findings folded into this one when both
                carry the same value for that scope (§1.7).
    guess       the heuristics the match may use (each Hit says which it did).
    severity_in {mode: severity}: a deliberate departure from the tier table
                (SGC001 warns in sketch).
    trace_warn_only  trace Hits cap at warn until the rule's simulator fixes land.
    after_acks  match in a second pass, once the first pass's findings are folded
                and acknowledged: `doc.findings` holds them all (hidden and
                unemitted ones too) and `doc.ack_used` the lines of the
                acknowledgements that covered one (for a rule about stale ones).
    ack_document  a document-scope acknowledgement may cover this rule's findings;
                False: only one anchored on the finding's own line (or block).
    """
    id: str
    name: str
    tier: str
    ask: str
    why: str
    fix: str
    match: Callable
    satisfiers: tuple = ()
    implies: tuple = ()
    guess: tuple = ()
    family: str = ""
    acknowledgeable: bool = True
    severity_in: tuple = ()          # ((mode, severity), …)
    trace_warn_only: bool = True
    after_acks: bool = False
    ack_document: bool = True

    @property
    def layer(self) -> str:
        return LAYERS.get(self.id[3:4], "dialect") if self.id.startswith("SGC") else "dialect"


@dataclass(frozen=True)
class Hit:
    """What a rule's match reports: one candidate, before mode, tier, folding and
    acknowledgement. `statement` is said in sketch and spec, `ask` (a question) in
    craft. `scopes` are (scope, value) pairs for folding; the anchor is one too."""
    line: int
    statement: str
    ask: str
    anchor: tuple = ("line", "")     # (node|wire|block|machine|comment|line, id)
    fix: str = ""                    # specific "how to satisfy"; default: the rule's
    guess: str = ""                  # what was guessed (non-empty: drop one tier)
    tier: str = ""                   # override the rule's tier (e.g. op vs actor)
    k: Optional[int] = None          # deviations the witness needs (trace hits)
    witness: Optional[str] = None    # scenario name
    at: Optional[int] = None         # the tick in the witness run where it shows
    trace: bool = False              # evidence comes from a simulator trace
    scopes: tuple = ()
    acknowledgeable: Optional[bool] = None   # None: the rule's
    about: str = ""                  # the id of a rule this hit is about (SGC003's)
    severity_in: tuple = ()          # ((mode, severity), …): the rule's, for this hit


@dataclass
class Finding:
    rule: Rule
    hit: Hit
    severity: Optional[str]          # None: not emitted in this mode
    hidden: bool
    tier: str                        # after the guess downgrade
    mode: str
    also: list = field(default_factory=list)       # folded Findings
    folded_into: Optional["Finding"] = None
    ack: Optional["Ack"] = None

    @property
    def line(self) -> int:
        return self.hit.line

    @property
    def sort_key(self) -> tuple:
        return (self.hit.line, self.rule.id, tuple(map(str, self.hit.anchor)),
                self.hit.statement)

    @property
    def fix(self) -> str:
        return self.hit.fix or self.rule.fix

    @property
    def message(self) -> str:
        if self.mode == "craft":
            text = self.hit.ask
        elif self.mode == "spec":
            text = f"{self.hit.statement} — {self.fix}" if self.fix else self.hit.statement
        else:
            text = self.hit.statement
        if self.hit.guess:
            text += f" (guessed: {self.hit.guess})"
        if self.also:
            text += " (also: " + ", ".join(sorted({f.rule.name for f in self.also})) + ")"
        return text

    def line_text(self) -> str:
        return f"{self.severity}:{self.line}:{self.rule.id}: {self.rule.name}: {self.message}"

    def accepted_text(self) -> str:
        where = " (document-wide)" if self.ack.document else ""
        return (f"accepted:{self.line}:{self.rule.id}: {self.rule.name}: "
                f"{self.ack.reason}{where}")

    def to_dict(self) -> dict:
        h = self.hit
        return {
            "severity": self.severity, "line": h.line, "rule": self.rule.id,
            "message": self.message, "name": self.rule.name, "tier": self.tier,
            "mode": self.mode, "anchor": {"kind": h.anchor[0], "id": str(h.anchor[1])},
            "why": self.rule.why, "fix": self.fix, "guess": bool(h.guess),
            "guessed": h.guess or None, "k": h.k, "witness": h.witness,
            "at": h.at,
            "hidden": self.hidden,
            "acknowledged": self.ack.reason if self.ack else None,
            "ack_line": self.ack.line if self.ack else None,
            "document_wide": bool(self.ack and self.ack.document),
            "also": [{"rule": f.rule.id, "name": f.rule.name, "line": f.line,
                      "message": f.hit.statement} for f in self.also],
        }


@dataclass
class Report:
    mode: str
    k: int
    limits: dict
    findings: list                   # emitted, unacknowledged, unfolded (incl. hidden)
    acknowledged: list
    folded: list
    kind: str = ""                   # the `#%` line's words ("": no line)
    off: tuple = ()                  # the ids of the rules the kind turned off
    state_runs: Optional[tuple] = None   # (names ran, number left unrun) of the state
                                     # starts the exploration walked (None: it listed none)
    limit_sources: dict = None       # sim.Limits field → where it came from
                                     # (sim.LIMIT_SOURCES; None: not said)

    @property
    def shown(self) -> list:
        return [f for f in self.findings if not f.hidden]

    def exit_code(self) -> int:
        sev = {f.severity for f in self.shown}
        return 2 if "error" in sev else 1 if "warn" in sev else 0

    def to_dict(self) -> dict:
        out = {"mode": self.mode, "k": self.k, "limits": self.limits}
        if self.limit_sources is not None:
            out["limit_sources"] = self.limit_sources
        out.update({"findings": [f.to_dict() for f in self.findings],
               "acknowledged": [f.to_dict() for f in self.acknowledged]})
        if self.kind:
            out["kind"] = {"words": self.kind, "off": list(self.off)}
        if self.state_runs is not None:
            ran, left = self.state_runs
            out["state_starts"] = {"ran": list(ran), "left_out": left}
        return out


# ---------------------------------------------------------------------------
# The document as the rules see it
# ---------------------------------------------------------------------------

class Doc:
    """One document, its mode and k, and the model facts the rules read. Every
    fact is computed on first use, so a rule pays only for what it reads.

    The model's facts, for rule modules (catalog §1.4): `doc.graph` (core's
    Graph: Edge.card / src_mods / implied, Graph.narrowed / dropped), `doc.scene`
    (sigil.model.scene: call_policy, declared_access, writers), `doc.sc` / `doc.prog` (the
    simulator's canonical scene and program), and `doc.access_mode(w)` (with
    `doc.declared_access` and `doc.writers`, memoised), which
    reads the dialect's extra read verbs (catalog §1 CG6). `doc.inv_heads` is the recognised
    `@inv` heads: the core's INV_HEADS and the dialect's rule pack's. `doc.budget` and `doc.limits`
    bound the simulator's exploration; they are reported in `--json` (catalog §1.3)."""

    def __init__(self, text: str, mode: str, k: int, known: frozenset, dialect=None,
                 read_verbs: tuple = (), policy_words: tuple = (),
                 inv_heads: frozenset = frozenset(),
                 budget: Optional[int] = None, limits=None,
                 rule_ids: Optional[dict] = None, overlaps=None, walk=None, graph=None):
        self.text = text
        if walk is not None:         # the reading a caller made already (see walk)
            self.__dict__["walk"] = walk
            if graph is not None:    # and the model it parsed from that reading
                self.__dict__["graph"] = graph
        self.lines = text.splitlines()
        self.mode = mode
        self.k = k
        self.known = known           # every rule name an acknowledgement may cite
        # id → name of every rule, so SGC001 can name the rule an id stands for
        self.names_by_id = {**CATALOG, **(rule_ids or {})}
        self.dialect = dialect
        self.extra_read_verbs = tuple(sorted(read_verbs))     # a dialect's (catalog §1 CG6)
        self.policy_words = POLICY_WORDS + tuple(policy_words)
        self.inv_heads = INV_HEADS | frozenset(inv_heads)  # the recognised @inv heads
        self.findings = []           # first-pass Findings (set before after_acks rules)
        self.ack_used = frozenset()  # lines of the acknowledgements that covered one
        self._budget = budget        # None: the defaults (see budget, limits)
        self._limits = limits        # --limit's pairs or a sim.Limits (None: none given)
        self._overlaps = overlaps    # None: the mode's (DEFAULT_OVERLAPS)
        self.off = {}                # rule id → the `#%` words that turned it off
        self.state_runs = None       # (names ran, number left unrun): the state starts
                                     # the trace rules' exploration walked, if it listed any

    def id_of(self, name: str) -> str:
        """The id of the rule named `name` ("" when no rule has it)."""
        return next((i for i, n in self.names_by_id.items() if n == name), "")

    @cached_property
    def budget(self) -> Optional[int]:
        """Runs one exploration may make (--budget; default: the trace module's)."""
        return default_budget() if self._budget is None else self._budget

    @property
    def overlaps(self):
        """Which overlap runs the exploration makes (--overlaps): "off", "listed"
        (sim.overlaps, alone and with each deviation), "all" (those, then every
        start tick of each window) or N ("all", at most N runs); default: the
        mode's (DEFAULT_OVERLAPS)."""
        return DEFAULT_OVERLAPS.get(self.mode, "off") if self._overlaps is None else self._overlaps

    @property
    def state_starts(self) -> bool:
        """Whether the exploration walks the state starts (STATE_START_MODES)."""
        return self.mode in STATE_START_MODES

    @cached_property
    def limits(self):
        """The sim.Limits every run is bounded by: the one merge (sim.limits_for)
        of the defaults, the document's `#%` limits (Walk.kind.limits) and the
        given ones (--limit's pairs laid over them; a given sim.Limits as it is)."""
        return self.sim.limits_for(self.walk.kind.limits, self._limits)

    @cached_property
    def limit_sources(self) -> dict:
        """Where each limit of `limits` came from (sim.limit_sources: default,
        scaled, document, flag), as --json prints it."""
        return self.sim.limit_sources(self.walk.kind.limits, self._limits, self.limits,
                                      self.sim.sized(self.limits, self.sc))

    @cached_property
    def render(self):
        from sigil.core import parse
        return parse

    @cached_property
    def scene(self):
        from sigil.model import scene
        return scene

    @cached_property
    def read_verbs(self) -> tuple:
        """The core read verbs, then the dialect's."""
        core = self.scene.READ_VERBS
        return core + tuple(v for v in self.extra_read_verbs if v not in core)

    @cached_property
    def access_index(self):
        """scene.access_index of the document, built once for every wire."""
        return self.scene.access_index(self.graph)

    @cached_property
    def _modes(self) -> dict:
        return {}                    # id(wire) → (wire, access_mode), filled on first ask

    def access_mode(self, w) -> Optional[str]:
        """How a flow wire touches a store (scene.access_mode with this document's
        graph and read verbs)."""
        hit = self._modes.get(id(w))
        if hit is None or hit[0] is not w:
            hit = self._modes[id(w)] = (w, self.scene.access_mode(
                w, self.graph, self.read_verbs, self.access_index))
        return hit[1]

    def declared_access(self, principal: str, store: str) -> set:
        """scene.declared_access over this document."""
        return self.scene.declared_access(self.graph, principal, store, self.access_index)

    @cached_property
    def _writers(self) -> dict:
        return self.scene.all_writers(self.sc, self.read_verbs, self.access_index)

    def writers(self, store: str) -> dict:
        """scene.writers over the canonical scene, with this document's read verbs."""
        return self._writers.get(store, {})

    @cached_property
    def walk(self):
        """The document's one reading (sigil.core.statements.read_document): the
        graph, the comments and the layout all come from it."""
        from sigil.core.statements import read_document
        return read_document(self.text, self.dialect)

    @cached_property
    def graph(self):
        return self.render.parse_document(self.text, dialect=self.dialect, walk=self.walk)

    @cached_property
    def graphs(self) -> list:
        """(graph, owning node id, level) for the document and every nested graph."""
        from sigil.core.graph import walk_depth
        return list(walk_depth(self.graph))

    @cached_property
    def comments(self) -> dict:
        """{1-based line: (text, own_line)}, the walk's comments."""
        return {k + 1: v for k, v in self.walk.comments.items()}

    @cached_property
    def layout(self) -> Layout:
        return walk_layout(self.walk)

    @cached_property
    def acks(self) -> list:
        return read_acks(self.comments, self.layout, self.known)

    @cached_property
    def sim(self):
        return _sim()

    @cached_property
    def sc(self):
        return self.sim.canonical(self.graph)

    @cached_property
    def prog(self):
        return self.sim.program(self.sc)


def read_mode(lines: list) -> str:
    """The mode as lint reads it (the first content line, lex.first_content, when
    it is a mode line); none means sketch."""
    from sigil.core.lex import first_content
    from sigil.core.vocab import VALID_MODES
    k = first_content(lines)
    head = lines[k].split()[0] if k is not None else ""
    return head[2:] if head in VALID_MODES else "sketch"


# ---------------------------------------------------------------------------
# Meta rules: SGC001, SGC002, SGC004
# ---------------------------------------------------------------------------

def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def nearest_name(name: str, known: Iterable) -> Optional[str]:
    """The closest known name within a third of its length (at least 3 edits)."""
    scored = sorted((edit_distance(name, k), k) for k in known)
    if scored and scored[0][0] <= max(3, len(name) // 3):
        return scored[0][1]
    return None


def meant_name(name: str, known: frozenset, names_by_id: dict) -> tuple:
    """(the rule name an unknown ack name most likely means, why it missed): "id"
    for a rule id, "case" for a known name in the wrong case, "typo" for a near
    miss; (None, "id") for an id no rule has; (None, None) when nothing fits."""
    if RULE_ID_RE.match(name):
        return names_by_id.get(name), "id"
    if name.lower() in known:
        return name.lower(), "case"
    near = nearest_name(name.lower(), known)
    return (near, "typo") if near else (None, None)


def unknown_name_hint(name: str, meant: Optional[str], why: Optional[str]) -> str:
    """The sentence SGC001 adds after "No rule is named …" ("" when none fits)."""
    if why == "id":
        named = f", `{meant}`," if meant else ","
        return f" Write the rule's name{named} not its id `{name}`."
    if why == "case":
        return f" Rule names are lower case: write `{meant}`."
    if why == "typo":
        return f" Did you mean `{meant}`?"
    return ""


def match_ack_unknown_rule(doc: Doc):
    """SGC001: a name no rule has (a typo, a rule id, the wrong case), or a rule
    that cannot be acknowledged."""
    for ack in doc.acks:
        for name in ack.names:
            meant, why = (None, None) if name in doc.known else \
                meant_name(name, doc.known, doc.names_by_id)
            if name in NOT_ACKNOWLEDGEABLE or meant in NOT_ACKNOWLEDGEABLE:
                yield Hit(ack.line, f"`{name}` cannot be acknowledged",
                          f"`{name}` cannot be acknowledged. Fix what it reports instead?",
                          anchor=("comment", ack.line),
                          fix="remove the name and fix the line it reports")
            elif name not in doc.known:
                hint = unknown_name_hint(name, meant, why)
                yield Hit(ack.line, f"no rule is named `{name}`.{hint}".rstrip(),
                          f"No rule is named `{name}`.{hint or ' Which rule is meant?'}",
                          anchor=("comment", ack.line),
                          fix=f"write `{meant}`" if meant else "")


def match_ack_without_reason(doc: Doc):
    """SGC002: an acknowledgement with no reason (it is void)."""
    for ack in doc.acks:
        if not ack.reason:
            names = ", ".join(f"`{n}`" for n in ack.names)
            yield Hit(ack.line, f"the acknowledgement of {names} gives no reason, so it "
                                "acknowledges nothing",
                      f"Why is {names} accepted here?", anchor=("comment", ack.line))


@dataclass(frozen=True)
class PolicyWord:
    """A resilience word a comment may use, the declarations that already say it
    and the form to suggest (catalog §1 CG6: data). The words are declared when the call's
    policy (scene.call_policy) holds a modifier named in `mods` or an `@inv`
    whose head is in `heads`."""
    label: str
    words: str                       # a regex over the comment
    mods: tuple                      # modifier names, as render names them ("×", "timeout")
    heads: tuple                     # @inv heads
    form: Callable                   # comment text → suggested notation


def _retry_form(text: str) -> str:
    m = re.search(r"(\d+)\s*(?:x\s*)?retr|retr\w*\s*(?:x\s*)?(\d+)", text, re.I)
    return f"×{(m.group(1) or m.group(2)) if m else 'N'}"


def _timeout_form(text: str) -> str:
    m = re.search(r"(\d+\s*(?:ms|s|m|h)\b)", text)
    return f"@timeout({m.group(1).replace(' ', '') if m else '…'})"


POLICY_WORDS = (
    PolicyWord("retries", r"\bretr(?:y|ies|ied|ying)\b", ("×",), (), _retry_form),
    PolicyWord("a timeout", r"\btime-?outs?\b|\btimed[ -]out\b", ("timeout", "deadline"),
               (), _timeout_form),
    PolicyWord("idempotency", r"\bidempoten(?:t|cy|ce)\b", (), ("idempotent",),
               lambda _t: "@inv idempotent(key)"),
    PolicyWord("deduplication", r"\bde-?dup(?:e|ed|licated?|lication)?\b", (),
               ("dedup", "idempotent"), lambda _t: "@inv dedup(key)"),
    PolicyWord("backoff", r"\bback-?off\b", ("after",), (), lambda _t: "@after(…)"),
)

# A comment may rule a policy out or hand it to someone else ("no retries", "not
# idempotent", "retried by the caller", "timeouts not needed"); such a word states
# no policy for this call, so SGC004 never asks for it (the never-limits principle).
_CLAUSE_BREAK = re.compile(r"[,;:.!?()—–]|\s-\s")
_NEGATORS = frozenset({"no", "not", "never", "without", "none", "nor", "neither"})
_NEGATION_REACH = 3                  # words before the policy word
_DECLINED_AFTER = re.compile(
    r"\s*(?:(?:is|are|was|were|be)\s+)?"
    r"(?:none\b|not\s+needed\b|unneeded\b|unnecessary\b|by\s"
    r"|(?:handled|done|owned|managed|covered)\s+(?:by|elsewhere|upstream|downstream)\b)",
    re.I)
_DECLINED_LABEL = re.compile(r"\s*[:=]\s*(?:none|no|never|n/a)\b", re.I)   # "retries: none"


def _clause(text: str, start: int, end: int) -> tuple:
    """(the clause before the span, the clause after it): the text between the
    span and the nearest clause break on each side."""
    before = _CLAUSE_BREAK.split(text[:start])[-1]
    after = _CLAUSE_BREAK.split(text[end:])[0]
    return before, after


def declined(text: str, start: int, end: int) -> bool:
    """The policy word at text[start:end] is negated (a negator among the few
    words before it in its clause) or delegated (`by …`, `handled by …`, `not
    needed`, `: none` right after it)."""
    before, after = _clause(text, start, end)
    words = re.findall(r"[\w']+", before.lower())[-_NEGATION_REACH:]
    if any(w in _NEGATORS or w.endswith("n't") for w in words):
        return True
    return bool(_DECLINED_AFTER.match(after) or _DECLINED_LABEL.match(text, end))


def states(word: PolicyWord, comment: str) -> bool:
    """The comment uses the word to state the policy at least once (not only to
    rule it out or delegate it)."""
    return any(not declined(comment, m.start(), m.end())
               for m in re.finditer(word.words, comment, re.I))

_INV_HEAD_RE = re.compile(r"\s*([A-Za-z_][\w-]*)")


def inv_head(arg: Optional[str]) -> str:
    """The head of an `@inv` argument: `idempotent(order_id)` → "idempotent"."""
    m = _INV_HEAD_RE.match(arg or "")
    return m.group(1) if m else ""


def call_policies(wires: Iterable, call_policy: Callable) -> dict:
    """{line: [(name, arg), …]} the policy of every call drawn on a line (a flow
    with a payload or an op-call target), several calls on one line pooled."""
    out = {}
    for w in wires:
        e = w.edge
        if w.role == "flow" and w.line and e is not None and (e.payload or e.target_op):
            out.setdefault(w.line, []).extend(call_policy(w))
    return out


def declares(word: PolicyWord, policy: list) -> bool:
    return any(name in word.mods or (name == "inv" and inv_head(arg) in word.heads)
               for name, arg in policy)


def prose_policy(comment: str, policy: list, words: tuple = POLICY_WORDS) -> list:
    """The PolicyWords a comment states that the call's policy does not declare.
    A `×N` on a node is cardinality, so it never declares retries (call_policy
    leaves it out). A word the comment negates or delegates states nothing."""
    return [w for w in words if states(w, comment) and not declares(w, policy)]


def match_policy_in_prose(doc: Doc):
    """SGC004: a trailing comment on a call line states a policy the line lacks."""
    policies = call_policies(doc.sc.wires, doc.scene.call_policy)
    acked = {a.line for a in doc.acks}
    for line in sorted(doc.comments):
        text, own = doc.comments[line]
        if own or line not in policies or line in acked or line in doc.layout.quoted:
            continue
        found = prose_policy(text, policies[line], doc.policy_words)
        if not found:
            continue
        labels = " and ".join(w.label for w in found)
        forms = " ".join(w.form(text) for w in found)
        yield Hit(line, f"the comment states {labels}, which the call does not declare",
                  f"The comment says “{text}”. Should that be `{forms}`?",
                  anchor=("line", line), fix=f"write `{forms}` on the call")


def core_rules() -> list:
    """The rules sigil.analyse.check itself carries."""
    return [
        Rule("SGC001", "ack-unknown-rule", "binding",
             ask="No rule is named so. Did you mean another name?",
             why="A misspelt acknowledgement silently fails to cover its finding.",
             fix="correct the rule name", match=match_ack_unknown_rule,
             acknowledgeable=False, severity_in=(("sketch", "warn"),), family="0"),
        Rule("SGC002", "ack-without-reason", "binding",
             ask="Why is this finding accepted here?",
             why="An acknowledgement is a decision; without its reason a reader "
                 "cannot judge it, so it acknowledges nothing.",
             fix="write the reason after `—`", match=match_ack_without_reason,
             acknowledgeable=False, family="0"),
        Rule("SGC004", "policy-in-prose", "hint",
             ask="Should the policy the comment describes be written as notation?",
             why="A policy stated only in prose is invisible to the checks and the "
                 "simulator.",
             fix="write the modifier or @inv the comment describes",
             match=match_policy_in_prose, family="0",
             satisfiers=(("call", "×"), ("call", "@timeout"), ("call", "@deadline"),
                         ("call", "@after"), ("call", "idempotent"), ("call", "dedup"))),
    ]


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

RULE_MODULES = ("flow", "state", "trace", "inv")      # modules of sigil.analyse.rules
STRUCTURE_MODULES = ("structure",)  # every check, where the module ships (not the playground)
EXPORT_MODULES = ("export",)        # only for a check asked for export readiness


class RegistryError(ValueError):
    """A rule clashes with the catalog or with another rule."""


def _rule_module(name: str):
    """The rule module `name` of sigil.analyse.rules, imported once."""
    return importlib.import_module(f"sigil.analyse.rules.{name}")


class _Api:
    """This module as the rule modules and dialect packs see it (their `ck`): its
    globals, read live. Not looked up in sys.modules by __name__: under a runner
    that executes the file in its own namespace (cProfile, runpy), that name is the
    runner's module."""

    def __getattr__(self, name: str):
        try:
            return globals()[name]
        except KeyError:
            raise AttributeError(name) from None


API = _Api()


def _modules(names: tuple) -> list:
    return [_rule_module(name) for name in names if (_RULES / f"{name}.py").is_file()]


def module_rules(api, names: tuple = RULE_MODULES) -> list:
    """The rules of every rule module in `names` that exists (each `rules(api)`),
    extended by each module's `extend_rules(api, rules)`, then SGC090 built from
    the causes they contribute."""
    mods = _modules(names)
    rules = [rule for mod in mods if hasattr(mod, "rules") for rule in mod.rules(api)]
    for mod in mods:
        if hasattr(mod, "extend_rules"):
            rules = mod.extend_rules(api, rules)
    causes = [c for mod in mods if hasattr(mod, "exploration_causes")
              for c in mod.exploration_causes(api)]
    return rules + ([exploration_rule(causes)] if causes else [])


def exploration_rule(causes: list) -> Rule:
    """SGC090 exploration-incomplete: one rule over the causes several modules find
    (a module's `exploration_causes(api)` returns match functions: loop caps from
    the static rules, budget, cut and spawn ceiling from the traces). A hint,
    but a run cut at a limit warns in spec mode (its Hit's `severity_in`): a spec
    whose runs never finished is not ready to export. Only a loop-cap or cut-run
    Hit is acknowledgeable, and only on its own line (the loop header, the cut
    episode's entry): their causes yield Hits with `acknowledgeable=True`; the
    others describe the exploration, not the design (catalog §5)."""
    def match(doc):
        for cause in causes:
            yield from cause(doc)
    return Rule(EXPLORATION[0], EXPLORATION[1], "hint",
                ask="The simulator did not explore all of this. Is what it ran enough "
                    "evidence?",
                why="Behavioural findings are only as complete as the exploration "
                    "behind them.",
                fix="run with larger limits (--limit NAME=N) or budget (--budget N)",
                match=match, family="0",
                acknowledgeable=False, ack_document=False)


def core_prefix(code: str) -> Optional[str]:
    """The core id prefix `code` starts with (CORE_ID_PREFIXES), or None."""
    return next((p for p in CORE_ID_PREFIXES if code.startswith(p)), None)


def registry_problem(rule: Rule, seen_ids: set, seen_names: set) -> Optional[str]:
    """Why `rule` cannot join a registry already holding seen_ids / seen_names."""
    if rule.tier not in TIERS:
        return f"{rule.id}: unknown tier {rule.tier!r}"
    if rule.id in seen_ids or rule.name in seen_names:
        return f"{rule.id} `{rule.name}`: registered twice"
    if rule.id in RETIRED_IDS:
        return f"{rule.id}: a retired id is never reused"
    if rule.id in CATALOG:
        if CATALOG[rule.id] != rule.name:
            return f"{rule.id} is `{CATALOG[rule.id]}` in the catalog, not `{rule.name}`"
        return None
    prefix = core_prefix(rule.id)
    if prefix:
        return f"{rule.id}: not in the catalog ({prefix} ids are core {CORE_ID_PREFIXES[prefix]})"
    if rule.name in CATALOG.values():
        return f"{rule.id}: `{rule.name}` is a core name"
    return None


def build_registry(rules: Iterable) -> dict:
    """{id: Rule}, refusing clashes (RegistryError names the first one)."""
    out, names = {}, set()
    for rule in rules:
        problem = registry_problem(rule, set(out), names)
        if problem:
            raise RegistryError(problem)
        out[rule.id] = rule
        names.add(rule.name)
    return out


def default_registry(extra: Iterable = (), export: bool = False) -> dict:
    """The core rules, every rule module beside this file and `extra` (a dialect
    pack's rules); with `export`, the readiness rules (EXPORT_MODULES) too."""
    readiness = module_rules(API, names=EXPORT_MODULES) if export else []
    return build_registry(core_rules() + module_rules(API, RULE_MODULES + STRUCTURE_MODULES)
                          + readiness + list(extra))


def core_names():
    """What the core names, for refusing a clashing dialect pack (dialects.CoreNames).
    Lint codes are left empty: `sigil lint` keeps no table of them, so the core reserves
    their whole prefix instead (CORE_ID_PREFIXES, enforced by dialect_pack and
    registry_problem)."""
    return _dialects().CoreNames(
        rule_ids=frozenset(CATALOG) | RETIRED_IDS,
        rule_names=frozenset(CATALOG.values()), inv_heads=INV_HEADS)


def prefix_problems(pack) -> list:
    """Every id of a dialect rule pack that takes a core prefix, sorted."""
    out = [f"lint code {c} takes the core prefix {core_prefix(c)}"
           for c in pack.lint_codes if core_prefix(c)]
    out += [f"rule id {r.id} takes the core prefix {core_prefix(r.id)}"
            for r in pack.rules if core_prefix(r.id)]
    return sorted(out)


def _dialects():
    from sigil.core import dialects
    return dialects


def dialect_pack(dialect):
    """The dialect's rule pack (rules, read verbs, policy words, @inv heads); an
    empty one for no dialect. Raises dialects.DialectError (a ValueError) when the
    pack reuses a core name or takes a core id prefix (SGL, SGC)."""
    mod = _dialects()
    if dialect is None:
        return mod.RulePack()
    pack = mod.checked_pack(dialect, API, core_names())
    problems = prefix_problems(pack)
    if problems:
        name = getattr(dialect, "NAME", "?")
        raise mod.DialectError(f"sigil dialect {name!r}: " + "; ".join(problems))
    return pack


# ---------------------------------------------------------------------------
# Grading, folding, acknowledging
# ---------------------------------------------------------------------------

def effective_tier(tier: str, guessed: bool) -> str:
    """A guess drops one tier, never below hint."""
    if not guessed:
        return tier
    return TIERS[min(TIERS.index(tier) + 1, len(TIERS) - 1)]


def grade(rule: Rule, hit: Hit, mode: str) -> tuple:
    """(severity or None, hidden, tier) for a hit in a mode (catalog §1.2)."""
    tier = effective_tier(hit.tier or rule.tier, bool(hit.guess))
    override = dict(hit.severity_in).get(mode) or dict(rule.severity_in).get(mode)
    if override:
        severity, hidden = override, False
    else:
        cell = SEVERITY[tier][mode]
        if cell is None:
            return None, False, tier
        severity, hidden = cell
    capped = (hit.k is not None and hit.k >= 2) or (hit.trace and rule.trace_warn_only)
    if capped and severity == "error":
        severity = "warn"
    return severity, hidden, tier


def scopes_of(hit: Hit) -> dict:
    out = dict(hit.scopes)
    out.setdefault(hit.anchor[0], hit.anchor[1])
    return out


def fold(findings: list) -> None:
    """One defect, one finding (§1.7): a finding that another finding's rule
    implies at the same scope is folded into that cause (followed up to the cause
    nothing folds; a cycle of implications folds nothing). The cause keeps its own
    severity. Mutates the findings."""
    scopes = [scopes_of(f.hit) for f in findings]
    parent = {}
    for i, f in enumerate(findings):
        for j, c in enumerate(findings):
            if i == j:
                continue
            if any(name == f.rule.name and s in scopes[i] and scopes[i][s] == scopes[j].get(s)
                   for name, s in c.rule.implies):
                parent[i] = j
                break
    for i in sorted(parent):
        root, seen = parent[i], {i}
        while root in parent and root not in seen:
            seen.add(root)
            root = parent[root]
        if root == i:            # a cycle of implications: keep both
            continue
        findings[i].folded_into = findings[root]
        findings[root].also.append(findings[i])


def acknowledgeable(f: Finding) -> bool:
    """The Hit's flag, else the Rule's; the meta rules never, whatever they say."""
    if f.rule.name in NOT_ACKNOWLEDGEABLE:
        return False
    flag = f.hit.acknowledgeable
    return f.rule.acknowledgeable if flag is None else flag


def acknowledge(findings: list, acks: list) -> set:
    """Attach to each acknowledgeable finding the first valid acknowledgement
    naming its rule and covering its line (a line one before a document one, and
    no document one for a rule that refuses them). Returns the lines of the
    acknowledgements used. Mutates the findings."""
    valid = [a for a in acks if a.reason]
    ordered = [a for a in valid if not a.document] + [a for a in valid if a.document]
    used = set()
    for f in findings:
        if not acknowledgeable(f):
            continue
        ack = next((a for a in ordered if f.rule.name in a.names and a.covers(f.line)
                    and (f.rule.ack_document or not a.document)), None)
        if ack:
            f.ack = ack
            used.add(ack.line)
    return used


def run_rules(doc: Doc, rules: list) -> list:
    """The rules' hits as Findings, sorted (line, id, anchor)."""
    out = []
    for rule in sorted(rules, key=lambda r: r.id):
        for hit in rule.match(doc):
            severity, hidden, tier = grade(rule, hit, doc.mode)
            out.append(Finding(rule, hit, severity, hidden, tier, doc.mode))
    return sorted(out, key=lambda f: f.sort_key)


def idle_ids(registry: dict) -> frozenset:
    """The rule ids loaded on demand (the readiness rules, EXPORT_NAMES, and the
    structure rules, STRUCTURE_NAMES) this registry does not run."""
    return (frozenset(EXPORT_NAMES) | frozenset(STRUCTURE_NAMES)) - {r.id for r in registry.values()}


def about_idle_rule(f: Finding, idle: frozenset) -> bool:
    """An SGC003 (ack-unused) finding about a rule that did not run (`idle`: rule
    ids): an acknowledgement of a readiness rule is for the export check (of a
    structure rule, for a check where its module ships), and no check without
    the rule judges it stale."""
    return f.rule.id == "SGC003" and f.hit.about in idle


def is_acknowledged(f: Finding) -> bool:
    """Acknowledged itself, or folded into an acknowledged cause."""
    root = f.folded_into or f
    return bool(f.ack or root.ack)


def default_budget() -> Optional[int]:
    """The trace module's exploration budget (its BUDGET); None without one, since
    then nothing explores."""
    return _rule_module("trace").BUDGET if (_RULES / "trace.py").is_file() else None


def limits_from(pairs: Iterable, base):
    """`base` (a sim.Limits) with each "name=N" of `pairs` set (sim.limits_from).
    Raises ValueError naming a malformed pair, an unknown name or a value below 1."""
    return _sim().limits_from(pairs, base)


def limits_of(doc: Doc) -> dict:
    """The bounds in effect, as --json prints them: the Limits the runs had (the
    defaults grown to the document's size, sim.sized, so `--limit frames=N`
    starts from the printed N), the trace budget and k (catalog §1.3)."""
    out = dict(doc.sim.sized(doc.limits, doc.sc)._asdict())
    out["budget"] = doc.budget
    out["k"] = doc.k
    out["overlap_runs"] = doc.overlaps      # --overlaps (sim.Limits has its own "overlaps")
    return out


def check(text: str, mode: Optional[str] = None, k: Optional[int] = None,
          dialect=None, registry: Optional[dict] = None, pack=None,
          budget: Optional[int] = None, limits=None, overlaps=None,
          export: bool = False, walk=None, graph=None, all_rules: bool = False) -> Report:
    """Check a document. `mode` overrides its mode line; `pack` defaults to the
    dialect's rule pack (dialect_pack), whose read verbs, policy words and
    `@inv` heads the rules read; `registry` defaults to the core rules, every rule module beside
    this file and the pack's rules. `budget` (runs per exploration) and `limits`
    bound the simulator: --limit's "name=N" pairs, laid over the document's own
    (its `#%` line's) and the defaults (sim.limits_for), or a sim.Limits used as
    it is; `overlaps` (OVERLAPS or a number of runs)
    says which overlap runs it makes; None takes the defaults. `export` adds the
    export readiness rules to the default registry (a given `registry` runs as
    it is). `walk`: the document's reading (sigil.core.statements.read_document
    of `text` with `dialect`) when the caller has it already, as `sigil lint
    --deep` and the export gate do, and `graph` the model parsed from that walk
    (sigil.core.parse.parse_document); None reads / parses it here. The `#%`
    kind line turns rule groups off (RULE_GROUPS; a `deterministic` kind makes no
    overlap runs unless `overlaps` is given); `all_rules` runs them anyway."""
    pack = dialect_pack(dialect) if pack is None else pack
    registry = default_registry(pack.rules, export) if registry is None else registry
    lines = text.splitlines()
    mode = mode or read_mode(lines)
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r} (one of {', '.join(MODES)})")
    k = DEFAULT_K[mode] if k is None else k
    if walk is None:                 # the one reading; Doc and every rule share it
        walk, graph = read_document(text, dialect), None
    kind = walk.kind                 # the `#%` kind, as Core's walk read it
    off = () if all_rules else tuple(sorted(
        rid for rid in registry if group_of(rid) in kind.off))
    registry = {rid: r for rid, r in registry.items() if rid not in off}
    if overlaps is None and kind.concurrency == "deterministic" and not all_rules:
        overlaps = "off"
    known = frozenset(CATALOG.values()) | {r.name for r in registry.values()}
    doc = Doc(text, mode, k, known, dialect, read_verbs=pack.read_verbs,
              policy_words=pack.policy_words, inv_heads=pack.inv_heads,
              budget=budget, limits=limits, overlaps=overlaps,
              rule_ids={r.id: r.name for r in registry.values()}, walk=walk, graph=graph)
    doc.off = dict.fromkeys(off, kind.text)
    first = [r for r in registry.values() if not r.after_acks]
    findings = run_rules(doc, first)
    fold(findings)
    doc.findings = list(findings)
    doc.ack_used = frozenset(acknowledge(findings, doc.acks))
    idle = idle_ids(registry)
    later = [f for f in run_rules(doc, [r for r in registry.values() if r.after_acks])
             if not about_idle_rule(f, idle)]
    findings = sorted(findings + later, key=lambda f: f.sort_key)
    emitted = [f for f in findings if f.severity is not None]
    roots = [f for f in emitted if f.folded_into is None]
    return Report(
        mode=mode, k=k, limits=limits_of(doc), limit_sources=doc.limit_sources,
        findings=[f for f in roots if not is_acknowledged(f)],
        acknowledged=[f for f in roots if is_acknowledged(f)],
        folded=[f for f in emitted if f.folded_into is not None],
        kind=kind.text, off=off, state_runs=doc.state_runs)


# ---------------------------------------------------------------------------
# Output (the `sigil check` command is sigil.cli's)
# ---------------------------------------------------------------------------

def format_lines(report: Report, show_hidden: bool = False) -> list:
    shown = report.findings if show_hidden else report.shown
    return ([f.line_text() for f in shown]
            + [f.accepted_text() for f in report.acknowledged])


def summary(report: Report) -> str:
    sev = [f.severity for f in report.shown]
    hidden = len(report.findings) - len(report.shown)
    return (f"sigil check ({report.mode}, k={report.k}): {len(sev)} finding(s) "
            f"({sev.count('error')} error, {sev.count('warn')} warn, "
            f"{sev.count('info')} info); {len(report.acknowledged)} acknowledged; "
            f"{hidden} hidden" + off_text(report))


def off_text(report: Report) -> str:
    """The summary's note of the rules the kind turned off ("": none)."""
    if not report.off:
        return ""
    return (f"; {len(report.off)} rule(s) off for `#% {report.kind}`: {' '.join(report.off)}"
            " (--all-rules runs them)")


def registry_lines(registry: dict) -> list:
    out = []
    for rid in sorted(set(CORE_NAMES) | set(registry)):
        rule = registry.get(rid)
        tier = rule.tier if rule else "-"
        name = rule.name if rule else CORE_NAMES[rid]
        out.append(f"{rid}  {name:<28} {tier:<9} {group_of(rid):<12} "
                   f"{'' if rule else '(not implemented)'}".rstrip())
    return out
