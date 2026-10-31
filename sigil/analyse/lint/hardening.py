"""
Lint hardening (SGL120–188, SGL190–195): the lines the parser would misread or drop. The
rules read the document's one reading (sigil.core.statements.read_document):
each statement's tokens (sigil.core.tokens) and the walk's record of blocks,
headers, sections, transitions and continuation lines — the same reading the
parser builds the model from; lint keeps no walk or scanner of its own.
"""

import re
from typing import NamedTuple, Optional

from sigil.core import parse as render
from sigil.core.graph import walk_depth
from sigil.core.dialects import _hook
from sigil.core.lex import (
    ARROWS, CLOSERS_CLASS, DIALECT_COL, FIELD_RE, GLYPH_PREFIXES, MOD_NAME_RE, NAME_CHARS,
    OPENERS_CLASS, PREFIXES_CLASS, SECTION_RE, escape_char, glyph_kind, hidden_chars, visible)
from sigil.core.statements import (
    StateHead, Statement, Walk, data_shapes, field_name, read_document, read_fields)
from sigil.core.tokens import Code, Tok, glyph_spans
from sigil.core.vocab import LintResult
from sigil.analyse.lint.payloads import _classify_payload
from sigil.analyse.lint.reading import documents


# ---------------------------------------------------------------------------
# Lint hardening — lines the parser would misread or drop (RFC 0003 §8)
# ---------------------------------------------------------------------------
#
# The parser skips what it cannot read: an unclosed glyph becomes a phantom
# node, a dangling arrow draws nothing, an unclosed `:= {` loses its whole body.
# A model with silent holes cannot be trusted by anything downstream, so these
# rules report each such line. The statement walk (sigil.core.statements)
# follows the document's blocks the way the parser does; the rule functions
# below read its record and each statement's tokens. Codes and severities are
# fixed by RFC 0003's catalog §8: a silent drop is an error in every mode. Since
# the parser fix for `×3 Alias` (catalog §6 B7) an alias after `×N` is no longer
# dropped, so SGL181 (now: the alias is undefined) is a warning; since the
# `<H>({C})` chain fix (catalog §6 B8) and the one reading, SGL153 is retired
# (its id stays reserved, never reused).

HARDENING_SEVERITY = {
    "SGL120": "error", "SGL121": "error", "SGL122": "error",
    "SGL130": "error", "SGL131": "error", "SGL132": "error",
    "SGL150": "warn", "SGL151": "error", "SGL152": "warn", "SGL153": "error",
    "SGL160": "error", "SGL161": "error", "SGL162": "warn", "SGL163": "info",
    "SGL180": "error", "SGL181": "warn", "SGL182": "warn", "SGL183": "warn",
    "SGL184": "warn", "SGL185": "warn", "SGL186": "warn", "SGL187": "info",
    "SGL188": "warn", "SGL190": "error", "SGL191": "warn", "SGL192": "error",
    "SGL193": "warn", "SGL194": "warn", "SGL195": "error",
}


class Finding(NamedTuple):
    """One hardening diagnostic before it reaches a LintResult."""
    line: int
    rule: str
    message: str



# -- rules over one statement's tokens ---------------------------------------

_RESILIENCE_MODS = {"timeout", "deadline", "fallback"}


_STRUCTURAL = {"glyph", "nothing", "arrow", "join", "slash", "payload", "op", "word",
               "str", "set", "blockopen", "blockclose", "alias", "bad"}


def _glyph_findings(toks: list) -> list:
    """SGL120 unclosed glyph · SGL121 empty glyph · SGL122 stray / mismatched closer."""
    out = []
    for t in toks:
        if t.kind == "glyph" and t.problem == "unclosed":
            out.append(("SGL120", f"unclosed glyph `{t.text.strip()}`: the parser reads a "
                        "different node (or none) here. Close it with its matching bracket."))
        elif t.kind == "glyph" and t.problem == "empty":
            out.append(("SGL121", f"empty glyph `{t.text.strip()}` names nothing and is "
                        "dropped. Name it, or write a hole (`[?]`) in sketch / craft."))
        elif t.kind == "glyph" and t.problem == "mismatched":
            out.append(("SGL122", f"glyph `{t.text.strip()}…` is closed by another kind's "
                        "bracket. Each glyph closes with its own: [] {} <> () ||."))
        elif t.kind == "bad" and t.problem == "closer":
            out.append(("SGL122", f"stray `{t.text}` closes no glyph; the parser ignores it."))
        elif t.kind == "blockclose":
            out.append(("SGL122", "stray `}` closes no block; the parser ignores it."))
    return out


def _arrow_findings(sig: list) -> list:
    """SGL130 an arrow with no endpoint · SGL131 a malformed arrow."""
    out = []
    if sig and sig[0].kind == "nothing":
        out.append(("SGL130", "a flow starts with `()`, which names no source."))
    for k, t in enumerate(sig):
        if t.kind == "bad" and t.problem == "not-arrow":
            out.append(("SGL131", f"`{t.text}` is not an arrow (arrows: "
                        f"{' '.join(ARROWS)}); the parser skips it, so no edge is drawn."))
            continue
        if t.kind != "arrow":
            continue
        nxt = sig[k + 1] if k + 1 < len(sig) else None
        if nxt is not None and nxt.kind == "arrow":
            out.append(("SGL131", f"two arrows in a row (`{t.text} {nxt.text}`): the parser "
                        f"keeps one and drops the other. Write one arrow per link."))
        elif nxt is None or nxt.kind in ("payload", "nothing", "str", "blockopen",
                                          "blockclose") or (nxt.kind == "word"
                                                            and nxt.text != "_"):
            what = ("nothing" if nxt is None else f"the payload `: {nxt.text}`"
                    if nxt.kind == "payload" else f"`{nxt.text}`")
            out.append(("SGL130", f"arrow `{t.text}` has no destination (it is followed by "
                        f"{what}); the parser draws no edge. Name the target glyph or op."))
    return out


def _set_findings(sig: list) -> list:
    """SGL190 a set `{a, b}` written as a flow's end: a set is a value (it makes
    no node), so the flow has no glyph there. A set is a flow's end right after an
    arrow or a join, or leading the statement before an arrow; after anything else
    (`?> {O}.s ∈ {a, b} -> [E]`) it is a condition's value."""
    out = []
    for k, t in enumerate(sig):
        if t.kind != "set":
            continue
        prev = sig[k - 1] if k else None
        nxt = sig[k + 1] if k + 1 < len(sig) else None
        if (prev is not None and prev.kind in ("arrow", "join")) or \
                (prev is None and nxt is not None and nxt.kind in ("arrow", "join")):
            names = t.text.lstrip(GLYPH_PREFIXES)[1:-1].split(",")
            items = ", ".join(f"`{{{x.strip()}}}`" for x in names if x.strip())
            out.append(("SGL190", f"`{t.text}`: a set is a value, not a flow end: write one "
                        f"flow per glyph ({items}); the parser draws no edge to a set."))
    return out


def _join_findings(sig: list, is_alias: bool) -> list:
    """SGL132 a join (`&`, `&?`, `/`) with no glyph on one side, or no arrow."""
    out = []
    for k, t in enumerate(sig):
        if t.kind != "join":
            continue
        prev = sig[k - 1] if k else None
        nxt = sig[k + 1] if k + 1 < len(sig) else None
        if prev is None or prev.kind != "glyph" or nxt is None or nxt.kind != "glyph":
            out.append(("SGL132", f"join `{t.text}` needs a glyph on both sides "
                        "(`[A] & [B]`); the parser drops it here."))
            return out
    if not is_alias and any(t.kind == "join" for t in sig) \
            and not any(t.kind == "arrow" for t in sig):
        out.append(("SGL132", "a join with no arrow joins nothing: `[A] & [B]` must be "
                    "one end of a flow (`[A] & [B] -> [C]`)."))
    return out


def _payload_findings(toks: list, sig: list, is_alias: bool) -> list:
    """SGL150 payload with no flow · SGL151 unclosed payload or modifier · SGL152
    glyph after a payload."""
    out = []
    for t in toks:
        if t.kind == "payload" and t.problem == "unclosed":
            out.append(("SGL151", f"unclosed payload `{t.text}`: a string, `${{`, or "
                        "bracket is never closed, so the payload is kept as broken text."))
        elif t.kind == "mod" and t.problem == "unclosed":
            out.append(("SGL151", f"unclosed modifier `{t.text.strip()}`: its `(` is "
                        "never closed."))
        elif t.kind == "payload" and t.problem == "glyph-after":
            out.append(("SGL152", f"a glyph follows the payload `{t.text}` with no arrow: "
                        "the parser keeps it as payload text and draws no node. Add the "
                        "arrow, or move the glyph before the `:`."))
    payload = next((t for t in sig if t.kind == "payload"), None)
    if not is_alias and sig and sig[0].kind == "glyph" and payload is not None \
            and not any(t.kind == "arrow" for t in sig):
        out.extend(_lone_payload_finding(sig[0], payload))
    return out


def _lone_payload_finding(subject: Tok, payload: Tok) -> list:
    """SGL150 for a glyph subject with a payload and no arrow. A store slot with a
    value (`~|sys| : \"\"\"…\"\"\"`, `~|total| : ${x} + 1`) is a declaration, not a
    lost payload; so is an empty map (`~|graph| : {}`). A type annotation
    (`[A] : {X}`) is grammar the model drops."""
    kind = "map" if re.fullmatch(r"\{\s*\}", payload.text) else _classify_payload(payload.text)[0]
    if glyph_kind(subject.text) == "store" and kind in ("value", "map"):
        return []
    if kind == "entity":
        return [("SGL150", f"the type annotation `: {payload.text}` is grammar, but the "
                 "parser keeps the node and drops the type, so no view or check sees it.")]
    return [("SGL150", "a payload with no flow: the parser keeps the node and "
             "drops the payload. Put it on a flow (`[A] -> [B] : {X}`).")]


class _LastLink(NamedTuple):
    """The statement's last link: its final endpoint's column, arrow and target."""
    end_col: int
    arrow: Tok
    dst: Optional[Tok]


def _last_link(sig: list) -> Optional[_LastLink]:
    ends = [t for t in sig if t.kind in ("glyph", "op")]
    arrows = [t for t in sig if t.kind == "arrow"]
    if not ends or not arrows:
        return None
    dst = next((t for t in sig if t.col > arrows[-1].col and t.kind in ("glyph", "op")), None)
    return _LastLink(ends[-1].col, arrows[-1], dst)


def _argument_findings(toks: list) -> list:
    """SGL180: a modifier, count or bound with a missing or impossible argument."""
    out = []
    for t in toks:
        if t.problem == "no-arg":
            out.append(("SGL180", f"`{t.text.strip()}` needs an argument "
                        f"(`{t.text.strip()}(…)`); the parser keeps it with none."))
        elif t.problem == "bad-duration":
            out.append(("SGL180", f"`{t.text.strip()}`: a duration must be positive."))
        elif t.problem == "no-count":
            out.append(("SGL180", f"`{t.text.strip()}` has no count (`×3`, `^100@drop`)."))
        elif t.problem == "zero":
            out.append(("SGL180", f"`{t.text.strip()}`: a count of zero is no count."))
    return out


def _trailing_findings(toks: list, sig: list) -> list:
    """What trails the last link: SGL182 a resilience modifier on a flow that is no
    call · SGL187 a spaced `×N` on a payload-less flow (cardinality or retries?)."""
    link = _last_link(sig)
    if link is None:
        return []
    out = []
    has_payload = any(t.kind == "payload" for t in sig)
    dst_text = link.dst.text.strip() if link.dst else ""
    for t in (t for t in toks if t.col > link.end_col):
        if t.kind == "mod" and MOD_NAME_RE.match(t.text).group(1) in _RESILIENCE_MODS:
            data = link.dst is not None and link.dst.kind == "glyph" \
                and glyph_kind(dst_text) in ("data", "event")
            if link.arrow.text == "=>" or data:
                out.append(("SGL182", f"`{t.text.strip()}` sits on a flow that is not a "
                            f"call (`{link.arrow.text} {dst_text}`); resilience modifiers "
                            "bound a call (`->`, `<->`, `~>` to a component, actor, store "
                            "or op)."))
        elif t.kind == "card" and not t.glued and not has_payload and not t.problem:
            out.append(("SGL187", f"trailing `{t.text}` on a flow with no payload reads as "
                        f"cardinality; write `{dst_text or '[X]'}{t.text}` to say so, or "
                        "put it after a call payload (`: op() ×3`) for retries."))
    return out


def _marker_findings(toks: list) -> list:
    """SGL183: `!` / `?` between a glyph and an arrow marks the node, not the flow."""
    out = []
    for k, t in enumerate(toks):
        if t.kind != "mark" or not k or toks[k - 1].kind not in ("glyph", "field", "card"):
            continue
        nxt = next((u for u in toks[k + 1:] if u.kind != "mark"), None)
        if nxt is not None and nxt.kind == "arrow":
            out.append(("SGL183", f"`{t.text}` between a glyph and an arrow marks the node, "
                        "not the flow. Put it on the node's own line, or after the "
                        "flow's destination or payload."))
    return out


def statement_findings(st: Statement, target=None) -> list:
    """Every hardening finding of one statement, as Findings. `target(word)`: a
    bare word the dialect reads as an arrow's destination (an endpoint here)."""
    toks = _as_judged(st.toks, st.code, target)
    sig = [t for t in toks if t.kind in _STRUCTURAL]
    first_broken = next((t for t in toks if t.kind == "glyph"
                         and t.problem in ("unclosed", "mismatched")), None)
    line, is_alias = st.line, st.alias
    if first_broken is not None:
        # A broken glyph throws the rest of the line out of step: report it alone.
        return [Finding(line, rule, msg) for rule, msg in _glyph_findings([first_broken])]
    pairs = (_glyph_findings(toks) + _arrow_findings(sig) + _set_findings(sig)
             + _join_findings(sig, is_alias)
             + _payload_findings(toks, sig, is_alias) + _argument_findings(toks)
             + _trailing_findings(toks, sig) + _marker_findings(toks))
    return [Finding(line, rule, msg) for rule, msg in pairs]


def _as_judged(toks, code: Code, target) -> list:
    """A statement's tokens as these rules judge them: a payload that is a
    modifier's `key:value` is the word it is written as, and a dialect's bare
    target word after an arrow (`<go> -> resume`) an endpoint."""
    out = []
    for t in toks:
        if t.kind == "payload" and t.flag == "kv":
            continue
        if target is not None and t.kind == "word" and out and out[-1].kind == "arrow" \
                and not code.text[out[-1].col + len(out[-1].text):t.col].strip() \
                and not code.text.startswith("(", t.col + len(t.text)) and target(t.text):
            t = t._replace(kind="glyph", text=t.text)
        out.append(t)
    return out



# -- rules over the statement walk --------------------------------------------

_LOOP_BOUND_RE = re.compile(r"@(?:each|while|until|times)\b")


# A header that is one glyph and nothing else: prefixes, a bracket pair, its name.
_HEADER_GLYPH_RE = re.compile("^" + PREFIXES_CLASS + "*" + OPENERS_CLASS
                              + "(?P<name>" + NAME_CHARS + "+)" + CLOSERS_CLASS + "$")


_DROPS_BODY = ("alias", "state")


def walk_findings(walk: Walk, dialect=None) -> list:
    """The findings about the document's structure, from its statement walk
    (`dialect`: the one it was read with, whose glyphs may own a `state` block)."""
    return (_block_findings(walk.blocks) + _header_findings(walk.headers)
            + _section_findings(walk.sections, walk.definitions)
            + _state_findings(walk.transitions, ownerless_heads(walk.doc, dialect))
            + _bare_branch_findings(walk.bare_branches)
            + _continuation_findings(walk.continuations)
            + shape_findings(walk) + field_ref_findings(walk) + hidden_name_findings(walk))


def hidden_name_findings(walk: Walk) -> list:
    """SGL195 a name holding a control character (Unicode Cc: ESC, BEL, a tab
    inside brackets …) or a format character (Cf: a bidi override or isolate, a
    zero-width space or joiner — an emoji's ZWJ too —, a BOM, a soft hyphen): it
    garbles the terminal it is printed in, or looks like another name (`[A]`,
    `[A<U+200B>]`). A name is a glyph's (between its brackets) or any other word
    of a line's code (a state, a field, a section title, a modifier's argument);
    whitespace between words, a comment and a string's text are no name. The
    message shows the name escaped (lex.visible). A `#&` declaration's lines are
    the dialect's and a block string's are text: neither is read."""
    out = []
    for k, code in enumerate(walk.codes):
        if k in walk.declared or k in walk.quoted or code.text.isprintable():
            continue
        name = _hidden_name(code)
        if name is not None:
            chars = ", ".join(dict.fromkeys(escape_char(ch) for ch in hidden_chars(name)))
            out.append(Finding(k + 1, "SGL195", f"`{visible(name)}` holds a control or "
                               f"invisible format character ({chars}): it garbles a terminal "
                               "or reads as another name. Remove it."))
    return out


def _hidden_name(code: Code) -> Optional[str]:
    """The first name of a line's code (a glyph as written, else a word outside
    every glyph) holding a hidden character, or None. A dialect glyph's columns
    (DIALECT_COL in the code, the glyph itself in the raw text) are not read."""
    text = "".join(" " if ch == DIALECT_COL and raw != DIALECT_COL else ch
                   for ch, raw in zip(code.text, code.raw))
    rest = list(text)
    for span in sorted(glyph_spans(text), key=lambda s: s.start):
        if hidden_chars(span.name):
            return text[span.start:span.end].strip()
        rest[span.start:span.end] = " " * (span.end - span.start)
    return next((w for w in "".join(rest).split() if hidden_chars(w)), None)


def shape_findings(walk: Walk) -> list:
    """SGL191 a bare name outside a data expansion (the parser drops it: only a
    data expansion's own level reads bare names, as its fields) · SGL192 a field
    written twice in one data shape (statements.read_fields, data_shapes) ·
    SGL193 a line of a data shape that is neither fields nor a flow (`a b`, `x:
    y`): the parser drops it."""
    out, in_shape = [], set()
    for _definition, sts in data_shapes(walk.doc):
        seen = set()
        for st in sts:
            in_shape.add(id(st))
            fields = read_fields(st)
            if fields is None and not st.quiet and stray_in_shape(st):
                out.append(Finding(st.line, "SGL193", "this line of a data shape is "
                                   "neither fields nor a flow: the parser drops it. Write "
                                   "fields as names (`path, note?`, `rows: {Row}`), "
                                   "comma-separated, or a flow with an arrow."))
            for name, _optional, glyph in fields or ():
                name = field_name(name, glyph)
                if name in seen:
                    out.append(Finding(st.line, "SGL192", f"field `{name}` is written twice "
                                       "in this data shape: write each field once."))
                seen.add(name)
    for st in walk.statements:
        if id(st) in in_shape or st.quiet:
            continue
        bare = [name for name, _optional, _glyph in read_fields(st) or () if name is not None]
        if bare:
            out.append(Finding(st.line, "SGL191", f"bare name `{bare[0]}` outside a data "
                               "expansion: the parser drops it. A field belongs in its "
                               f"data's shape (`{{Data}} := {{ {bare[0]}, … }}`); a part "
                               "is a glyph."))
    return out


def field_ref_findings(walk: Walk) -> list:
    """SGL194 a `{X}.f` that names no field of X's shape: once a data glyph
    declares its fields (`{X} := { a, b }`, every expansion of it together), a
    `.f` written after it anywhere (a flow, a `?>` guard, a `branch on`, a loop's
    condition, an `@inv`) names one of them. A glyph that owns a `state` block
    also reads `.state`. A glyph with no shape is not judged."""
    fields = {}
    for definition, sts in data_shapes(walk.doc):
        names = fields.setdefault(definition.name, set())
        for st in sts:
            names.update(field_name(n, g) for n, _optional, g in read_fields(st) or ())
    if not fields:
        return []
    owners = {name for d in documents(walk.doc) for item in d.items
              if isinstance(item, StateHead) and item.owner
              for _kind, name, _start, _end in glyph_spans(item.owner)}
    out = []
    for k, code in enumerate(walk.codes):
        if k in walk.declared or k in walk.quoted:
            continue
        for span in glyph_spans(code.text):
            m = FIELD_RE.match(code.text, span.end)
            if span.kind != "data" or span.name not in fields or m is None:
                continue
            f = m.group(0)[1:].split(".")[0]
            if f in fields[span.name] or (f == "state" and span.name in owners):
                continue
            known = ", ".join(sorted(fields[span.name])) or "none"
            out.append(Finding(k + 1, "SGL194", f"`{{{span.name}}}.{f}`: {{{span.name}}}'s "
                               f"shape has no field `{f}` (its fields: {known}). Add it to "
                               "the shape, or name a field it has."))
    return out


def stray_in_shape(st: Statement) -> bool:
    """Whether a data shape's line that reads as no fields is dropped: it has no
    arrow (no flow) and a bare word or a `: …` part (what a field would be), so a
    glyph's declaration (`[Part]`) and a modifier line stay as they are."""
    kinds = {t.kind for t in st.toks}
    return "arrow" not in kinds and bool(kinds & {"word", "payload"})


def _block_findings(blocks: tuple) -> list:
    """SGL162 an empty block (not a dialect keyword's) · SGL160 one never closed."""
    out = []
    for b in blocks:
        if b.closed and not b.content and b.kind != "keyword":
            out.append(Finding(b.line, "SGL162", f"empty `{b.kind}` block: it has no "
                               "statements. Fill it in or remove it."))
        elif not b.closed:
            what = "its body is dropped" if b.kind in _DROPS_BODY else \
                "the parser closes it at the end of the document"
            out.append(Finding(b.line, "SGL160", f"block opened here is never closed: "
                               f"{what}. Add the closing `}}`."))
    return out


def _header_findings(headers: tuple) -> list:
    """SGL163: a `loop` that says nothing about what bounds it."""
    return [Finding(h.line, "SGL163", "`loop` with no `@each`, `@while`, `@until` or "
                    "`@times`: say what bounds it.")
            for h in headers if h.kind == "loop" and not _LOOP_BOUND_RE.search(h.head)]


def _section_findings(sections: tuple, defined: frozenset) -> list:
    """SGL184: a malformed section header, or a layer section naming no expansion."""
    out = []
    for no, t in sections:
        m = SECTION_RE.match(t)
        if not m:
            out.append(Finding(no, "SGL184", "malformed section header: write `--- Lk: Name "
                               "---` or `--- Name ---` (closing dashes included); the "
                               "parser reads this line as a flow."))
            continue
        g = _HEADER_GLYPH_RE.match(m.group(2).strip())
        if m.group(1) and g and g.group("name").strip() not in defined:
            out.append(Finding(no, "SGL184", f"section `{m.group(2).strip()}` names no "
                               f"expansion: nothing defines `{m.group(2).strip()} := {{ … }}`."))
    return out


def ownerless_heads(doc, dialect=None) -> list:
    """The lines (1-based) of the `state` heads with no owner the model reads: no
    owner glyph (`state {`, `state Foo {`), or one the parser reads as no glyph
    (sigil.core.parse.parse_glyph), in every definition body too. The parser
    drops each such machine whole."""
    if doc is None:
        return []
    return sorted(item.line + 1 for d in documents(doc) for item in d.items
                  if isinstance(item, StateHead)
                  and (item.owner is None or render.parse_glyph(item.owner, dialect=dialect)
                       is None))


def _state_findings(transitions: tuple, ownerless: list) -> list:
    """SGL161, every one: a `state` block with no owner (`ownerless`: the lines of
    its heads), and from the model's reading of each line of an owned one
    (Transition) an edge with no trigger, or a line that is no transition and
    writes no `-<` (a malformed trigger is SGL090's)."""
    out = [Finding(line, "SGL161", "`state` block with no owner glyph "
                   "(`state {Order} {`): the parser drops the whole machine.")
           for line in ownerless]
    for t in transitions:
        if t.kind == "untriggered":
            out.append(Finding(t.line, "SGL161", f"transition `{t.raw}` has no trigger: "
                               "write `Src -<trigger>-> Dst`. The parser keeps no cause "
                               "for it."))
        elif t.kind == "unread":
            out.append(Finding(t.line, "SGL161", f"`{t.raw}` is not a transition "
                               "(`Src -<trigger>-> Dst`); the parser drops it."))
    return out


def _bare_branch_findings(bare: tuple) -> list:
    """SGL186: a composition branch written without its `\\-`."""
    return [Finding(no, "SGL186", f"`{t.split()[0]}` looks like a composition branch "
                    "without its `\\-`; the parser reads it as a continuation line. "
                    "Write `\\-` before it.")
            for no, t in bare]


def _continuation_findings(continuations: tuple) -> list:
    """SGL130 a continuation with no flow above · SGL185 one after a blank line."""
    out = []
    for c in continuations:
        if not c.subject:
            out.append(Finding(c.line, "SGL130", f"continuation `{c.text.split()[0]}` has no "
                               "flow above to continue (start of a document, section or "
                               "block); the parser drops its source."))
        elif c.after_blank:
            out.append(Finding(c.line, "SGL185", "continuation line after a blank line: it "
                               "still attaches to the flow above. Keep it directly under "
                               "that flow."))
    return out


def reserved_marker_findings(walk: Walk) -> list:
    """SGL188: `#=` is reserved for the decorated acknowledgement (RFC 0003 Q7).
    A line's comment starts where the walk cut its code (Code.raw ends there: at
    its `#`, or at a dialect's comment marker that comes first)."""
    out = []
    for no, (raw, code) in enumerate(zip(walk.lines, walk.codes), 1):
        if raw.startswith("#=", len(code.raw)):
            out.append(Finding(no, "SGL188", "`#=` is reserved for acknowledgements "
                               "(RFC 0003) and acknowledges nothing yet; write "
                               "`# accepts: rule — reason`, or a plain `# …` comment."))
    return out


# -- what the parser itself reports (Graph.dropped, edges by line) -------------

class ParsedFacts(NamedTuple):
    """What the parsed model says about each line, for the rule that asks the
    parser rather than the walk. `alias_refs`: line → {name} of each modifier
    alias after a `×N` that no modifier-only alias defines (render.ALIAS_REF)."""
    alias_refs: dict


def parsed_facts(graph) -> ParsedFacts:
    """The ParsedFacts of a render.Graph (every expansion and machine included)."""
    alias_refs = {}
    for sub, _owner, _lvl in walk_depth(graph):
        for e in sub.edges:
            for name, arg in e.mods:
                if name == render.ALIAS_REF:
                    alias_refs.setdefault(e.line, set()).add(arg)
    return ParsedFacts(alias_refs)


def parser_gap_findings(facts: ParsedFacts) -> list:
    """What the parsed model reports: SGL181 a modifier alias after `×N` that
    nothing defines. Every other drop is the walk's to report (SGL160 at a block
    never closed, SGL161 at a `state` block with no owner). SGL153 (an event
    argument that breaks the chain) is retired: the parser reads `<E>(…)` from
    the same tokens, so the chain cannot break; the id stays reserved."""
    out = []
    for no, names in facts.alias_refs.items():
        for name in sorted(names):
            out.append(Finding(no, "SGL181", f"`{name}` after `×N` names no modifier-only "
                               f"alias: define it (`{name} := @after(…)`) or write its "
                               "modifiers inline. The model keeps it as an unresolved name."))
    return out


def hardening_findings(walk, facts: Optional[ParsedFacts] = None, target=None,
                       dialect=None) -> list:
    """Every hardening finding of a document's reading (a Walk; a list of lines is
    read first), in line order, at most one per rule per line. `facts` (from the parsed
    document) adds the rule that asks the parser; without it it is skipped.
    `target`: see statement_findings; `dialect`: the one `walk` was read with."""
    if not isinstance(walk, Walk):
        walk = read_document("\n".join(walk))
    found = walk_findings(walk, dialect) + reserved_marker_findings(walk)
    for st in walk.statements:
        if not st.quiet:
            found += statement_findings(st, target)
    if facts is not None:
        found += parser_gap_findings(facts)
    return _one_per_rule_and_line(found)


def _one_per_rule_and_line(found: list) -> list:
    """The findings in (line, rule) order, the first of each (line, rule) kept."""
    seen, out = set(), []
    for f in sorted(found, key=lambda f: (f.line, f.rule)):
        if (f.line, f.rule) not in seen:
            seen.add((f.line, f.rule))
            out.append(f)
    return out


ANY_TARGET_WORD = r"(?!op\b)[A-Za-z_][\w.-]*"   # a bare word that is not an op call


def target_words(words):
    """A test (`fn(word) -> bool`) for a dialect's bare-word arrow targets
    (`<go> -> context`), which these rules read as endpoints; None when there are
    none. `words` is a set of words, or ANY_TARGET_WORD for every bare word (not
    an op call `run()` or the `op` keyword)."""
    if not words:
        return None
    alt = words if isinstance(words, str) else "|".join(map(re.escape, sorted(words)))
    rx = re.compile(r"(?:" + alt + r")$")
    return lambda word: rx.match(word) is not None


def lint_hardening(walk: Walk, result: LintResult, dialect=None, graph=None):
    """Report the hardening findings (SGL120–SGL195) on `result`. `walk` is the
    document's reading; `graph` the parsed document (render.parse_document), or
    None when it could not be parsed."""
    # A dialect owns its vocabulary: one that has not said which bare words it
    # reads as arrow targets keeps every bare word there (core cannot judge them).
    if dialect is not None and not hasattr(dialect, "ARROW_TARGET_WORDS"):
        target = target_words(ANY_TARGET_WORD)
    else:
        target = target_words(set(_hook(dialect, "ARROW_TARGET_WORDS", set())))
    for f in hardening_findings(walk, parsed_facts(graph) if graph is not None else None,
                                target, dialect):
        result.add(HARDENING_SEVERITY[f.rule], f.line, f.rule, f.message)
