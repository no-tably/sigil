#!/usr/bin/env python3
"""
check.py — Sigil composition checks: is the design a document describes sound?

lint.py checks that a document is well formed; check.py asks whether the design
says how its risks are handled (RFC 0003, rfcs/0003-catalog.md). A finding never
forbids a shape: it names a risk the design leaves undeclared, and is satisfied by
declaring the handling in the notation (`@timeout`, `×N`, `!>`, `@inv …`, …) or by
a reasoned acknowledgement:

    [API] -> [Payments] : charge(total) ×3   # accepts: retry-without-idempotency — an upsert

Usage:
    ./check.py <file.sigil> [--mode sketch|craft|spec] [--k N] [--json] [--all]
    ./check.py --rules
    cat doc.sigil | ./check.py -

Options:
    --mode M     check as mode M (default: the document's mode line; none = sketch)
    --k N        failure combinations explored per scenario (default: 1, spec 2)
    --json       one JSON object: mode, k, limits, findings, acknowledged
    --all        also print the findings the mode hides (sketch's info)
    --rules      list the rule registry and exit
    --dialect D  load a dialect (as lint.py does; default $SIGIL_DIALECT)

Output (lint-compatible, sorted by line, then rule id, then anchor):
    <severity>:<line>:<SGCnnn>: <name>: <message>
    accepted:<line>:<SGCnnn>: <name>: <reason>        (acknowledged findings)

Exit codes: 0 no warnings or errors · 1 warnings only · 2 errors (or bad input).
Acknowledged and hidden findings never count.

Severity follows the mode, capped by the rule's tier (catalog §1.2):

    tier      sketch         craft                   spec
    binding   info, hidden   warn (asked)            error
    advisory  info, hidden   warn (asked)            warn
    hint      not emitted    info (asked)            info

A finding built on a guess drops one tier (never below hint); a trace finding
whose witness needs k >= 2 deviations, or that comes from a rule still marked
`trace_warn_only`, is capped at warn.

Rule modules. check.py loads the sibling modules in RULE_MODULES that exist; each
defines `rules(ck)` and returns a list of `ck.Rule`, where `ck` is this module
(passed in, so a rule module never imports check.py itself). A rule's `match(doc)`
yields `ck.Hit`s; `doc` is a `ck.Doc` (lines, mode, k, graph, comments, acks, and
the simulator's canonical scene and program, all computed on first use). A module
may also define `exploration_causes(ck)`, match functions whose Hits check.py
gathers into the one SGC090 rule. A loaded dialect's rule pack (dialects.py,
`check_rules`, `READ_VERBS`, `policy_words`) joins the registry and the Doc. The
registry, the finding record, tiers × modes, acknowledgements and folding live
here; rule modules hold only matches and their data.

Standard library only. Deterministic: no clock, no randomness, no set-order output.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable, Optional


_HERE = Path(__file__).resolve().parent


def _sibling(name: str, fname: str):
    """The module fname beside this file, loaded by path once per directory and then
    shared: the view modules of one directory read the one viewkit, so a theme
    applied through any of them (apply_theme rebinds viewkit's style globals)
    reaches them all, while a view.py loaded from another directory (a packaged
    copy) gets modules, theme and dialect state of its own. The cache key names
    the directory, never the bare name. view.py, view_graph.py, view_tree.py and
    scene.py each carry a copy of this function: keep the copies identical."""
    key = f"{name}@{_HERE}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, _HERE / fname)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod   # dataclasses resolve string annotations via sys.modules
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[key]
            raise
    return sys.modules[key]


def _kit():
    """viewkit: the render and lint modules the simulator itself reads."""
    return _sibling("sigil_viewkit", "viewkit.py")


def _sim():
    return _sibling("sigil_sim", "sim.py")


# ---------------------------------------------------------------------------
# The catalog: every core id and name (rfcs/0003-catalog.md §0). Names are what
# people type; ids never change and retired ids are never reused. A name is known
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
    "SGC201": "unhandled-failure", "SGC202": "dead-failure-route",
    "SGC203": "event-ignored", "SGC204": "race", "SGC205": "ordering-unstated",
    "SGC206": "stalled-join",
    "SGC301": "inv-unchecked", "SGC302": "inv-dangling", "SGC303": "inv-contradicted",
    "SGC304": "layer-inversion", "SGC306": "timeout-below-sla",
}
RETIRED_IDS = frozenset({"SGC105", "SGC164", "SGC305"})
# Fixed by editing a line, never by a decision about the design (catalog §5): the
# ack-* rules (SGC001-SGC003) and SGC004 policy-in-prose (writing the modifier is
# the fix). No Rule or Hit flag can make these acknowledgeable. SGC090 is
# acknowledgeable for its loop-cap cause only, on the loop's line (see
# exploration_rule).
NOT_ACKNOWLEDGEABLE = frozenset({"ack-unknown-rule", "ack-without-reason", "ack-unused",
                                 "policy-in-prose"})
EXPLORATION = ("SGC090", "exploration-incomplete")

# The recognised `@inv` heads (RFC 0003 §3, Decision Q4). A dialect may add heads,
# never redefine one of these.
INV_HEADS = frozenset({
    "idempotent", "dedup", "atomic", "ordered", "serialised", "cas", "immutable",
    "depth", "hops", "terminates", "retention", "lock-order", "layers",
    "retry-budget", "limit", "concurrency", "consistent"})

LAYERS = {"0": "meta", "1": "structural", "2": "behavioural", "3": "invariant"}
TIERS = ("binding", "advisory", "hint")
MODES = ("sketch", "craft", "spec")
DEFAULT_K = {"sketch": 1, "craft": 1, "spec": 2}

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
    trace: bool = False              # evidence comes from a simulator trace
    scopes: tuple = ()
    acknowledgeable: Optional[bool] = None   # None: the rule's


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
            "hidden": self.hidden,
            "acknowledged": self.ack.reason if self.ack else None,
            "ack_line": self.ack.line if self.ack else None,
            "document_wide": bool(self.ack and self.ack.document),
            "also": [{"rule": f.rule.id, "name": f.rule.name, "line": f.line,
                      "message": f.hit.statement} for f in self.also],
        }


@dataclass(frozen=True)
class Ack:
    """One acknowledgement comment (catalog §10.1). `reason` is "" when missing
    (the acknowledgement is then void, SGC002). `span` is the set of lines it
    covers; `document` makes it cover every line."""
    line: int
    names: tuple
    reason: str
    span: frozenset = frozenset()
    document: bool = False

    def covers(self, line: int) -> bool:
        return self.document or line in self.span


@dataclass(frozen=True)
class Layout:
    """Where the statements and blocks of a document are (1-based lines)."""
    statements: frozenset            # lines holding a statement
    blocks: dict                     # header or closing line → (header, closing)
    quoted: frozenset                # lines inside a `\"\"\"…\"\"\"` block-string body

    @property
    def first(self) -> Optional[int]:
        return min(self.statements, default=None)

    def span(self, line: int) -> frozenset:
        """A block header or its `}` covers the whole block; any other line itself."""
        if line in self.blocks:
            head, close = self.blocks[line]
            return frozenset(range(head, close + 1))
        return frozenset({line})


@dataclass
class Report:
    mode: str
    k: int
    limits: dict
    findings: list                   # emitted, unacknowledged, unfolded (incl. hidden)
    acknowledged: list
    folded: list

    @property
    def shown(self) -> list:
        return [f for f in self.findings if not f.hidden]

    def exit_code(self) -> int:
        sev = {f.severity for f in self.shown}
        return 2 if "error" in sev else 1 if "warn" in sev else 0

    def to_dict(self) -> dict:
        return {"mode": self.mode, "k": self.k, "limits": self.limits,
                "findings": [f.to_dict() for f in self.findings],
                "acknowledged": [f.to_dict() for f in self.acknowledged]}


# ---------------------------------------------------------------------------
# The document as the rules see it
# ---------------------------------------------------------------------------

class Doc:
    """One document, its mode and k, and the model facts the rules read. Every
    fact is computed on first use, so a rule pays only for what it reads.

    The model's facts, for rule modules (catalog §1.4): `doc.graph` (render's
    Graph: Edge.card / src_mods / implied, Graph.narrowed / dropped), `doc.scene`
    (scene.py: call_policy, declared_access, writers), `doc.sc` / `doc.prog` (the
    simulator's canonical scene and program), and `doc.access_mode(w)`, which
    reads the dialect's extra read verbs (CG6)."""

    def __init__(self, text: str, mode: str, k: int, known: frozenset, dialect=None,
                 read_verbs: tuple = (), policy_words: tuple = ()):
        self.text = text
        self.lines = text.splitlines()
        self.mode = mode
        self.k = k
        self.known = known           # every rule name an acknowledgement may cite
        self.dialect = dialect
        self.extra_read_verbs = tuple(sorted(read_verbs))     # a dialect's (CG6)
        self.policy_words = POLICY_WORDS + tuple(policy_words)
        self.findings = []           # first-pass Findings (set before after_acks rules)
        self.ack_used = frozenset()  # lines of the acknowledgements that covered one

    @cached_property
    def render(self):
        return _kit().render

    @cached_property
    def scene(self):
        return _sibling("sigil_scene", "scene.py")

    @cached_property
    def read_verbs(self) -> tuple:
        """The core read verbs, then the dialect's."""
        core = self.scene.READ_VERBS
        return core + tuple(v for v in self.extra_read_verbs if v not in core)

    def access_mode(self, w) -> Optional[str]:
        """How a flow wire touches a store (scene.access_mode with this document's
        graph and read verbs)."""
        return self.scene.access_mode(w, self.graph, read_verbs=self.read_verbs)

    @cached_property
    def graph(self):
        return self.render.parse_document(self.text, dialect=self.dialect)

    @cached_property
    def graphs(self) -> list:
        """(graph, owning node id, level) for the document and every nested graph."""
        return list(self.render._walk(self.graph))

    @cached_property
    def comments(self) -> dict:
        """{1-based line: (text, own_line)} (render.collect_comments)."""
        return {k + 1: v for k, v in
                self.render.collect_comments(self.lines, self.dialect).items()}

    @cached_property
    def layout(self) -> Layout:
        return layout_of(self.lines, self.render.strip_comment)

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
    """The mode as lint reads it (the first content line); none means sketch."""
    lint = _kit().lint
    found = lint.lint_mode_line(lines, lint.LintResult())
    return found[2:] if found else "sketch"


# ---------------------------------------------------------------------------
# Layout and acknowledgements (catalog §10.1)
# ---------------------------------------------------------------------------

_STRING_RE = re.compile(r'"[^"]*"')


def layout_of(lines: list, strip_comment: Callable) -> Layout:
    """Statement lines and block spans. A line whose code ends with `{` opens a
    block, one whose code starts with `}` closes the innermost open block."""
    statements, quoted, blocks, stack = set(), set(), {}, []
    in_quote = False
    for n, raw in enumerate(lines, start=1):
        if in_quote:
            quoted.add(n)
            in_quote = raw.count('"""') % 2 == 0
            continue
        stripped = raw.strip()
        if stripped.startswith("#!"):
            continue
        code = stripped if stripped.startswith("#&") else strip_comment(raw).strip()
        if not code:
            continue
        statements.add(n)
        in_quote = code.count('"""') % 2 == 1
        bare = _STRING_RE.sub('""', code)
        if bare.startswith("}") and stack:
            head = stack.pop()
            blocks[head] = blocks[n] = (head, n)
        if bare.endswith("{"):
            stack.append(n)
    return Layout(frozenset(statements), blocks, frozenset(quoted))


_KEBAB = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_ACK_RE = re.compile(rf"^accepts:\s*(?P<names>{_KEBAB}(?:\s*,\s*{_KEBAB})*)(?P<tail>.*)$")
_SEPARATOR_RE = re.compile(r"^\s*(?:—|--)\s*(?P<reason>.*)$|^\s+-(?:\s+(?P<reason2>.*))?$")


def parse_ack(text: str, known: frozenset) -> Optional[tuple]:
    """(names, reason) when a comment's text is an acknowledgement, else None.
    `accepts:` then kebab-case rule names, a separator (`—`, `--`, ` - `) and a
    reason. With no separator it is an acknowledgement (missing its reason) only
    when the text is nothing but names and one of them is a rule name or kebab
    compound; so `# accepts: any JSON body` stays prose."""
    m = _ACK_RE.match(text.strip())
    if not m:
        return None
    names = tuple(n.strip() for n in m.group("names").split(","))
    tail = m.group("tail")
    if not tail.strip():
        if any(n in known or "-" in n for n in names):
            return names, ""
        return None
    sep = _SEPARATOR_RE.match(tail)
    if not sep:
        return None
    return names, (sep.group("reason") or sep.group("reason2") or "").strip()


def ack_span(line: int, own_line: bool, layout: Layout, comment_lines: frozenset):
    """(span, document) for an acknowledgement on `line`: trailing → its line (a
    block header or `}` → the block); own line(s) directly above a statement →
    that statement (or block); before the first statement and not directly above
    it → the whole document; anywhere else → nothing."""
    if not own_line:
        return layout.span(line), False
    nxt = line + 1
    while nxt in comment_lines and nxt not in layout.statements:
        nxt += 1
    if nxt in layout.statements:
        return layout.span(nxt), False
    first = layout.first
    if first is None or line < first:
        return frozenset(), True
    return frozenset(), False


def read_acks(comments: dict, layout: Layout, known: frozenset) -> list:
    """Every acknowledgement in the document, in line order."""
    comment_lines = frozenset(comments)
    out = []
    for line in sorted(comments):
        text, own = comments[line]
        if line in layout.quoted:
            continue
        parsed = parse_ack(text, known)
        if parsed is None:
            continue
        span, document = ack_span(line, own, layout, comment_lines)
        out.append(Ack(line, parsed[0], parsed[1], span, document))
    return out


# ---------------------------------------------------------------------------
# Meta rules of P1: SGC001, SGC002, SGC004
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


def match_ack_unknown_rule(doc: Doc):
    """SGC001: a name no rule has, or a rule that cannot be acknowledged."""
    for ack in doc.acks:
        for name in ack.names:
            if name in NOT_ACKNOWLEDGEABLE:
                yield Hit(ack.line, f"`{name}` cannot be acknowledged",
                          f"`{name}` cannot be acknowledged. Fix what it reports instead?",
                          anchor=("comment", ack.line),
                          fix="remove the name and fix the line it reports")
            elif name not in doc.known:
                near = nearest_name(name, doc.known)
                hint = f" Did you mean `{near}`?" if near else ""
                yield Hit(ack.line, f"no rule is named `{name}`.{hint}".rstrip(),
                          f"No rule is named `{name}`.{hint or ' Which rule is meant?'}",
                          anchor=("comment", ack.line),
                          fix=f"write `{near}`" if near else "")


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
    and the form to suggest (CG6: data). The words are declared when the call's
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
    """The rules check.py itself carries (P1)."""
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
             match=match_policy_in_prose, acknowledgeable=False, family="0",
             satisfiers=(("call", "×"), ("call", "@timeout"), ("call", "@deadline"),
                         ("call", "@after"), ("call", "idempotent"), ("call", "dedup"))),
    ]


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

RULE_MODULES = ("check_flow.py", "check_state.py", "check_trace.py", "check_inv.py")


class RegistryError(ValueError):
    """A rule clashes with the catalog or with another rule."""


def _rule_module(path: Path):
    """A rule module loaded by path, once per file."""
    key = f"sigil_{path.stem}@{path.parent}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[key]
            raise
    return sys.modules[key]


def _modules(here: Path, names: tuple) -> list:
    return [_rule_module(here / fname) for fname in names if (here / fname).is_file()]


def module_rules(api, here: Path = _HERE, names: tuple = RULE_MODULES) -> list:
    """The rules of every rule module in `here` that exists (each `rules(api)`),
    then SGC090 built from the causes they contribute."""
    mods = _modules(here, names)
    rules = [rule for mod in mods if hasattr(mod, "rules") for rule in mod.rules(api)]
    causes = [c for mod in mods if hasattr(mod, "exploration_causes")
              for c in mod.exploration_causes(api)]
    return rules + ([exploration_rule(causes)] if causes else [])


def exploration_rule(causes: list) -> Rule:
    """SGC090 exploration-incomplete: one rule over the causes several modules find
    (a module's `exploration_causes(api)` returns match functions: loop caps from
    the static rules, budget, cut and spawn ceiling from the traces). Only a
    loop-cap Hit is acknowledgeable, and only on the loop's own line: its cause
    yields Hits with `acknowledgeable=True` anchored on the loop header; the
    others describe a run, not the design (catalog §5)."""
    def match(doc):
        for cause in causes:
            yield from cause(doc)
    return Rule(EXPLORATION[0], EXPLORATION[1], "hint",
                ask="The simulator did not explore all of this. Is what it ran enough "
                    "evidence?",
                why="Behavioural findings are only as complete as the exploration "
                    "behind them.",
                fix="run with larger limits or budget", match=match, family="0",
                acknowledgeable=False, ack_document=False)


def registry_problem(rule: Rule, seen_ids: set, seen_names: set) -> Optional[str]:
    """Why `rule` cannot join a registry already holding seen_ids / seen_names."""
    if rule.tier not in TIERS:
        return f"{rule.id}: unknown tier {rule.tier!r}"
    if rule.id in seen_ids or rule.name in seen_names:
        return f"{rule.id} `{rule.name}`: registered twice"
    if rule.id in RETIRED_IDS:
        return f"{rule.id}: a retired id is never reused"
    if rule.id in CORE_NAMES:
        if CORE_NAMES[rule.id] != rule.name:
            return f"{rule.id} is `{CORE_NAMES[rule.id]}` in the catalog, not `{rule.name}`"
        return None
    if rule.id.startswith("SGC"):
        return f"{rule.id}: not in the catalog (SGC ids are core)"
    if rule.name in CORE_NAMES.values():
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


def default_registry(extra: Iterable = ()) -> dict:
    return build_registry(core_rules() + module_rules(sys.modules[__name__]) + list(extra))


def core_names():
    """What the core names, for refusing a clashing dialect pack (dialects.CoreNames).
    Lint codes are left empty: lint.py exposes no list of them."""
    return _dialects().CoreNames(
        rule_ids=frozenset(CORE_NAMES) | RETIRED_IDS,
        rule_names=frozenset(CORE_NAMES.values()), inv_heads=INV_HEADS)


def _dialects():
    return _sibling("sigil_dialects", "dialects.py")


def dialect_pack(dialect):
    """The dialect's rule pack (rules, read verbs, policy words, @inv heads); an
    empty one for no dialect. Raises dialects.DialectError (a ValueError) when the
    pack reuses a core name."""
    mod = _dialects()
    if dialect is None:
        return mod.RulePack()
    return mod.checked_pack(dialect, sys.modules[__name__], core_names())


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
    override = dict(rule.severity_in).get(mode)
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
    nothing folds; a cycle of implications folds nothing). Mutates the findings."""
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


def is_acknowledged(f: Finding) -> bool:
    """Acknowledged itself, or folded into an acknowledged cause."""
    root = f.folded_into or f
    return bool(f.ack or root.ack)


def limits_of(k: int) -> dict:
    out = dict(_sim().Limits()._asdict())
    out["k"] = k
    return out


def check(text: str, mode: Optional[str] = None, k: Optional[int] = None,
          dialect=None, registry: Optional[dict] = None, pack=None) -> Report:
    """Check a document. `mode` overrides its mode line; `pack` defaults to the
    dialect's rule pack (dialect_pack), whose read verbs and policy words the
    rules read; `registry` defaults to the core rules, every rule module beside
    this file and the pack's rules."""
    pack = dialect_pack(dialect) if pack is None else pack
    registry = default_registry(pack.rules) if registry is None else registry
    lines = text.splitlines()
    mode = mode or read_mode(lines)
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r} (one of {', '.join(MODES)})")
    k = DEFAULT_K[mode] if k is None else k
    known = frozenset(CORE_NAMES.values()) | {r.name for r in registry.values()}
    doc = Doc(text, mode, k, known, dialect, read_verbs=pack.read_verbs,
              policy_words=pack.policy_words)
    first = [r for r in registry.values() if not r.after_acks]
    findings = run_rules(doc, first)
    fold(findings)
    doc.findings = list(findings)
    doc.ack_used = frozenset(acknowledge(findings, doc.acks))
    later = run_rules(doc, [r for r in registry.values() if r.after_acks])
    findings = sorted(findings + later, key=lambda f: f.sort_key)
    emitted = [f for f in findings if f.severity is not None]
    roots = [f for f in emitted if f.folded_into is None]
    return Report(
        mode=mode, k=k, limits=limits_of(k),
        findings=[f for f in roots if not is_acknowledged(f)],
        acknowledged=[f for f in roots if is_acknowledged(f)],
        folded=[f for f in emitted if f.folded_into is not None])


# ---------------------------------------------------------------------------
# Output and CLI
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
            f"{hidden} hidden")


def registry_lines(registry: dict) -> list:
    out = []
    for rid in sorted(set(CORE_NAMES) | set(registry)):
        rule = registry.get(rid)
        tier = rule.tier if rule else "-"
        name = rule.name if rule else CORE_NAMES[rid]
        out.append(f"{rid}  {name:<28} {tier:<9} {'' if rule else '(not implemented)'}"
                   .rstrip())
    return out


def _read_input(path: str) -> str:
    if path == "-":
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="check.py", description="Check a Sigil design's "
                                 "composition: risks it leaves undeclared.")
    ap.add_argument("file", nargs="?", help="a .sigil file, or - for stdin")
    ap.add_argument("--mode", choices=MODES, help="check as this mode")
    ap.add_argument("--k", type=int, help="failure combinations per scenario")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    ap.add_argument("--all", action="store_true", help="also print hidden findings")
    ap.add_argument("--rules", action="store_true", help="list the rules and exit")
    ap.add_argument("--dialect", default=None,
                    help="dialect name or path (default: $SIGIL_DIALECT)")
    a = ap.parse_args(argv)
    if a.k is not None and a.k < 1:
        ap.error("--k must be at least 1")
    if not (a.rules or a.file):
        ap.error("a file is required (or --rules)")
    try:
        dialect = _dialects().load(a.dialect)
        pack = dialect_pack(dialect)
        registry = default_registry(pack.rules)
        text = None if a.rules else _read_input(a.file)
    except RegistryError as exc:
        print(f"check.py: rule registry: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"check.py: {exc}", file=sys.stderr)
        return 2
    if a.rules:
        print("\n".join(registry_lines(registry)))
        return 0
    report = check(text, mode=a.mode, k=a.k, dialect=dialect, registry=registry, pack=pack)
    if a.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        out = format_lines(report, a.all)
        print("\n".join(out) if out else "sigil check: OK (no findings)")
        print(summary(report), file=sys.stderr)
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
