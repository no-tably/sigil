"""
Payload rules: what follows a flow's `:` — values, map and list literals, op
calls (`op ns.verb(args)` / `verb(args)`), tags — classified and checked;
PayloadSite is what a dialect's payload check is handed.
"""

import re
from sigil.core.vocab import ARROW_RE, LintResult, VALID_MODIFIERS

from sigil.core.lex import EXT_OP_RE, INT_OP_RE, MOD_TOKEN_RE, mask_strings


# ---------------------------------------------------------------------------
# Payloads & values (map-literal disambiguation, external ops)
# ---------------------------------------------------------------------------

# Scalar value literals that are unambiguously value-bearing.
_BOOL_NULL_RE = re.compile(r"^(?:true|false|null)$")


_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


_STR_RE = re.compile(r'^".*"$')


_REF_RE = re.compile(r"^\$\{[^}]*\}$")


# A value-operator expression keys off a leading literal/ref/list/map followed
# by one of the closed top-level operators.
_VALUE_OP_RE = re.compile(r"(?:\+\+|\|\||[+\-*/])")


def _brace_body_is_map_literal(body: str):
    """Classify a `{...}` payload body. Returns:
        'map'    — pure key/value pairs (a map literal value)
        'entity' — a data-glyph entity (bare identifier, optionally attrs)
        'ambig'  — has a top-level ':' but is NOT pure pairs (rejected)
    """
    inner = body.strip()
    if inner == "":
        return "entity"  # `{}` — treat as (empty) entity, not value
    # Split on top-level commas (no nesting expected at this depth in sigil).
    parts = [p.strip() for p in _split_top_level_commas(inner)]
    has_top_colon = any(":" in p for p in parts)
    if not has_top_colon:
        return "entity"
    # Has a top-level ':' — is EVERY part a `name : value` pair?
    all_pairs = all(re.match(r"^[A-Za-z_][\w.<>]*\s*:\s*.+$", p) for p in parts)
    return "map" if all_pairs else "ambig"


def _split_top_level_commas(s: str):
    """Split on commas not nested inside (), [], {}, <>, or quotes."""
    out, depth, buf, q = [], 0, [], None
    for ch in s:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
            buf.append(ch)
            continue
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def _is_list_body(body: str) -> bool:
    """True if `body` (the inside of a `[…]`) reads as a list literal's elements
    rather than a service glyph's name."""
    inner = body.strip()
    if inner == "" or len(_split_top_level_commas(inner)) > 1:
        return True
    return bool(_BOOL_NULL_RE.match(inner) or _NUMBER_RE.match(inner)
                or _STR_RE.match(inner) or _REF_RE.match(inner)
                or (inner.startswith("[") and inner.endswith("]")))


def _classify_payload(value_text: str):
    """Classify the *value text* (tags already stripped). Returns a tuple
    (kind, detail) where kind is one of:
        'value'      — a literal / ref / value-operator expression (value-bearing)
        'ext-op'     — an `op <ns>.<verb>(...)` external call (value-bearing)
        'map'        — a `{k: v}` map literal (value-bearing)
        'map-ambig'  — a `{...}` with a top-level ':' but not pure pairs (reject)
        'ext-op-bad' — an `op ...` that is malformed (reject)
        'entity'     — a glyph entity (structural)
        'int-op'     — bare `verb(args)` internal op-call (structural)
        'opaque'     — bare identifier / label / unrecognized (structural)
    """
    v = value_text.strip()
    if v == "":
        return ("opaque", "")

    # External op-call: `op <ns>.<verb>(args)`.
    if re.match(r"^op\b", v):
        if EXT_OP_RE.match(v):
            return ("ext-op", v)
        return ("ext-op-bad", v)

    # A `{...}` payload — entity vs map literal vs ambiguous.
    if v.startswith("{") and v.endswith("}"):
        cls = _brace_body_is_map_literal(v[1:-1])
        if cls == "map":
            return ("map", v)
        if cls == "ambig":
            return ("map-ambig", v)
        return ("entity", v)

    # List literal: a `[…]` that is empty, has top-level commas, or holds a
    # single value literal / ref / nested list (`[1, 2]`, `["a"]`, `[${x}]`) — a
    # service glyph `[X]` holds a name.
    if v.startswith("[") and v.endswith("]") and _is_list_body(v[1:-1]):
        return ("value", v)

    # Other single glyph entity payloads (`<X>`, `[X]`, `(X)`, `|X|`,
    # optionally `~`/`*` prefixed) are structural.
    if re.match(r"^[~*]*[\[<(|]", v):
        return ("entity", v)

    # Scalars / ref / value-op expression.
    if _BOOL_NULL_RE.match(v) or _NUMBER_RE.match(v) or _STR_RE.match(v) or _REF_RE.match(v):
        return ("value", v)
    # A value-operator expression: starts with a ref/literal and contains a
    # top-level operator (e.g. `${a} + 1`, `${xs} ++ [..]`).
    if (v.startswith("${") or _STR_RE.match(v) or _NUMBER_RE.match(v.split()[0])) \
            and _VALUE_OP_RE.search(v):
        return ("value", v)

    # Bare `verb(args)` — internal op-call (structural, by-shape).
    if INT_OP_RE.match(v):
        return ("int-op", v)

    # Anything else (a bare identifier label like `reserve`, `charge`) is an
    # opaque structural payload — unchanged by-shape behavior.
    return ("opaque", v)


class PayloadSite:
    """One `: payload` segment, as handed to dialect payload checks. `branch`: it
    is the payload of a composition-branch statement (`\\-> [x] : …`)."""
    __slots__ = ("line_no", "value", "tags", "kind", "known_modifiers", "branch")

    def __init__(self, line_no, value, tags, kind, known_modifiers, branch=False):
        self.line_no = line_no
        self.value = value
        self.tags = tags
        self.kind = kind
        self.known_modifiers = known_modifiers
        self.branch = branch


_BAD_OP = ("malformed external op-call {text!r}. Expected `op <ns>.<verb>(args)`, "
           "every part of the dotted name starting with a letter (e.g. "
           "`op db.query(${{sql}})`).")


def lint_payloads(statements: tuple, result: LintResult, checks=(), known=None):
    """Enforce the core payload/value grammar (language.md "Payloads & values")
    on each flow statement the walk read (a one-line definition's body is no
    flow; a declaration block, a block header and a `state` block line are no
    statement):

      - a `{...}` with a top-level ':' that is not pure key/value pairs is
        ambiguous and rejected (SGL100);
      - a malformed external op-call (`op` without a dotted ns, or a dotted
        part that starts with no letter) is rejected (SGL102), as a payload
        and as an arrow's target alike.
    Core Sigil does NOT require a tag on a value payload. A dialect may add
    per-payload rules (`checks`, see dialects.py `lint_payload_checks`).
    """
    if known is None:
        known = VALID_MODIFIERS
    for st in statements:
        if st.alias:
            continue
        # An `op …(…)` written as an arrow's target (a self-call) holds to the
        # same rule as one written as a payload: render reads both as an op-call.
        for k, t in enumerate(st.toks):
            if t.kind == "op" and k and st.toks[k - 1].kind == "arrow" \
                    and t.text.startswith("op") \
                    and _classify_payload(t.text)[0] == "ext-op-bad":
                result.add("error", st.line, "SGL102", _BAD_OP.format(text=t.text))
        for value_text, tags in payload_segments(st):
            kind = _classify_payload(value_text)[0]

            if kind == "map-ambig":
                result.add(
                    "error", st.line, "SGL100",
                    f"`{{...}}` payload {value_text!r} is ambiguous: it has a "
                    f"top-level ':' but is not pure key/value pairs. A map "
                    f"literal must be `{{k: v, ...}}`; a data entity must be a "
                    f"bare identifier `{{X}}`."
                )
                continue
            if kind == "ext-op-bad":
                result.add("error", st.line, "SGL102", _BAD_OP.format(text=value_text))
            if checks:
                site = PayloadSite(st.line, value_text, tags, kind, known, st.branch >= 0)
                for check in checks:
                    check(site, result)


# Tokens that sit in a payload's span but are not its text: its modifiers, and
# the tail the model peels off it (count, bound, `!`, modifier-alias references).
_NOT_PAYLOAD = ("mod", "card", "bound", "mark", "aref")


def payload_segments(st) -> list:
    """The `: payload` segments of a statement as the model reads them:
    [(value, tags)] — its payload token's text (modifiers and tail already out)
    split at each top-level arrow, the first part whole and each later link's
    `: …` (`: call() => {R} : note`), each with the `@name` of every modifier
    written in that segment's span. Blank segments are left out."""
    tok = next((t for t in st.toks if t.kind == "payload" and t.flag != "kv"), None)
    if tok is None or not tok.text:
        return []
    values = {n: tok.text[s:e].strip() for n, s, e in _segments(mask_strings(tok.text), 0)}
    tags = _segment_tags(st, tok)
    return [(v, tags.get(n, [])) for n, v in values.items() if v]


def _segment_tags(st, tok) -> dict:
    """{link number: [`@name`, …]} the modifiers written in each payload segment's
    span of the statement, in written order. The spans are found in the
    statement's text with every non-payload token blanked, so they split where
    the payload token's text does."""
    others = [t for t in st.toks if t.kind in _NOT_PAYLOAD and t.col > tok.col]
    text = st.code.text
    for t in others:
        text = text[:t.col] + " " * len(t.text) + text[t.col + len(t.text):]
    out = {}
    for n, s, e in _segments(text, tok.col + 1):
        names = (MOD_TOKEN_RE.match(t.text) for t in others
                 if t.kind == "mod" and s <= t.col < e)
        out[n] = [m.group(0) for m in names if m]
    return out


def _segments(text: str, start: int) -> list:
    """[(link number, start, end)] the payload segments of `text` (strings
    blanked) from `start`: the first link whole, each later one from its
    top-level `:` (a link with none holds no payload and is left out)."""
    out = []
    for n, (s, e) in enumerate(_links(text, start)):
        if n:
            colon = _top_level_colon(text, s, e)
            if colon is None:
                continue
            s = colon + 1
        out.append((n, s, e))
    return out


def _links(text: str, start: int) -> list:
    """The (start, end) spans of `text` from `start` split at each arrow outside
    brackets (strings are blanked in `text`); the arrows are in no span."""
    spans, begin, depth, i = [], start, 0, start
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0:
            m = ARROW_RE.match(text, i)
            if m:
                spans.append((begin, i))
                begin = i = m.end()
                continue
        i += 1
    spans.append((begin, len(text)))
    return spans


def _top_level_colon(text: str, start: int, end: int):
    """The column of the first payload `:` (not part of `:=`) between `start` and
    `end` outside brackets, or None."""
    depth = 0
    for i in range(start, end):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and ch == ":" and text[i + 1:i + 2] != "=" \
                and (i == 0 or text[i - 1] not in ":="):
            return i
    return None
