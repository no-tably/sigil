"""
Payload rules: what follows a flow's `:` — values, map and list literals, op
calls (`op ns.verb(args)` / `verb(args)`), tags — classified and checked;
PayloadSite is what a dialect's payload check is handed.
"""

import re
from sigil.core.vocab import ARROW_RE, LintResult, VALID_MODIFIERS, strip_comment

from sigil.core.lex import EXT_OP_RE, INT_OP_RE, MOD_TOKEN_RE, OP_HEAD_RE, balanced_end


# ---------------------------------------------------------------------------
# Payloads & values (map-literal disambiguation, external ops)
# ---------------------------------------------------------------------------

# A trailing edge modifier that is NOT part of the payload value: any
# @-modifier, cardinality (×N / xN), a stream bound (`^N` / `^N@policy`, N may
# carry a k/m/g scale suffix).
_TRAILING_MOD_RE = re.compile(
    r"\s*(?:@[a-z][a-z0-9_-]*(?:\([^)]*\))?|×\s*\d+|\bx\d+\b"
    r"|\^\d+[kKmMgG]?(?:@[a-z][a-z0-9_-]*)?)\s*$"
)


# Scalar value literals that are unambiguously value-bearing.
_BOOL_NULL_RE = re.compile(r"^(?:true|false|null)$")


_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


_STR_RE = re.compile(r'^".*"$')


_REF_RE = re.compile(r"^\$\{[^}]*\}$")


# A value-operator expression keys off a leading literal/ref/list/map followed
# by one of the closed top-level operators.
_VALUE_OP_RE = re.compile(r"(?:\+\+|\|\||[+\-*/])")


def _split_payload_and_tags(seg: str):
    """Given a payload segment (text after `:`, before the next arrow), peel
    trailing edge modifiers off the end and return (value_text, [tags_seen]).

    Tags are returned in source order (left-to-right). Only `@`-modifiers are
    collected as tags; cardinality / stream bounds are dropped."""
    tags = []
    s = seg.strip()
    while True:
        m = _TRAILING_MOD_RE.search(s)
        if not m:
            break
        chunk = s[m.start():].strip()
        if chunk.startswith("@"):
            # Take just the @name (strip any (...) args for tag identity).
            name = MOD_TOKEN_RE.match(chunk)
            if name:
                tags.insert(0, name.group(0))
        s = s[: m.start()].rstrip()
    return s, tags


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
    """One `: payload` segment, as handed to dialect payload checks."""
    __slots__ = ("line_no", "value", "tags", "kind", "known_modifiers")

    def __init__(self, line_no, value, tags, kind, known_modifiers):
        self.line_no = line_no
        self.value = value
        self.tags = tags
        self.kind = kind
        self.known_modifiers = known_modifiers


def lint_payloads(lines: list, result: LintResult, checks=(),
                  blocks=(), keywords=(), known=None):
    """Enforce the core payload/value grammar (language.md "Payloads & values"):

      - a `{...}` with a top-level ':' that is not pure key/value pairs is
        ambiguous and rejected (SGL100);
      - a malformed external op-call (`op` without a dotted ns, or a dotted
        part that starts with no letter) is rejected (SGL102), as a payload
        and as an arrow's target alike.
    Core Sigil does NOT require a tag on a value payload. A dialect may add
    per-payload rules (`checks`, see dialects.py `lint_payload_checks`), declare
    blocks whose bodies are declarations rather than flows (`blocks` — skipped),
    and add statement-leading block keywords (`keywords` — header lines skipped).
    """
    if known is None:
        known = VALID_MODIFIERS
    kw = ["state", "loop", "parallel", "branch"] + sorted(set(keywords))
    in_block_header = re.compile(r"^(" + "|".join(map(re.escape, kw)) + r")\b")
    active = None          # (regex, on_raw) of the declaration block we are inside
    depth = 0
    for i, raw in enumerate(lines, start=1):
        raw_lead = raw.strip()
        line = strip_comment(raw).strip()

        # Declaration-block skip: a dialect-declared `name { … }` block carries
        # DECLARATIONS, not flow payloads (mirrors the state/loop block skips).
        # Brace depth is tracked on the raw line for raw-matched openers (a `#…`
        # marker would be blanked by comment stripping), else on the stripped line.
        if active is not None:
            txt = raw_lead if active[1] else line
            depth += txt.count("{") - txt.count("}")
            if depth <= 0:
                active = None
            continue
        opened = False
        for opener, on_raw in blocks:
            txt = raw_lead if on_raw else line
            if opener.match(txt):
                depth = txt.count("{") - txt.count("}")
                active = (opener, on_raw) if depth > 0 else None
                opened = True
                break
        if opened:
            continue

        if not line or line.startswith("#!") or line.startswith("---"):
            continue
        if in_block_header.match(line):
            continue
        # Skip aliases (`name := ...`) and state-block transitions.
        if ":=" in line or "-<" in line:
            continue
        # An `op …(…)` written as an arrow's target (a self-call) holds to the
        # same rule as one written as a payload: render reads both as an op-call.
        for am in ARROW_RE.finditer(line):
            j = len(line) - len(line[am.end():].lstrip())
            om = OP_HEAD_RE.match(line, j)
            if not om or not line.startswith("op", j):
                continue
            end = balanced_end(line, om.end() - 1)
            target = line[j:end] if end > 0 else ""
            if target and _classify_payload(target)[0] == "ext-op-bad":
                result.add(
                    "error", i, "SGL102",
                    f"malformed external op-call {target!r}. Expected "
                    f"`op <ns>.<verb>(args)`, every part of the dotted name "
                    f"starting with a letter (e.g. `op db.query(${{sql}})`)."
                )
        # Find each `: payload` segment: a `:` that is not part of `:=`,
        # running to the next arrow or end of line.
        for m in re.finditer(r"(?<![:=]):(?!=)", line):
            start = m.end()
            rest = line[start:]
            am = ARROW_RE.search(rest)
            seg = rest[: am.start()] if am else rest
            if not seg.strip():
                continue
            value_text, tags = _split_payload_and_tags(seg)
            kind = _classify_payload(value_text)[0]

            if kind == "map-ambig":
                result.add(
                    "error", i, "SGL100",
                    f"`{{...}}` payload {value_text!r} is ambiguous: it has a "
                    f"top-level ':' but is not pure key/value pairs. A map "
                    f"literal must be `{{k: v, ...}}`; a data entity must be a "
                    f"bare identifier `{{X}}`."
                )
                continue
            if kind == "ext-op-bad":
                result.add(
                    "error", i, "SGL102",
                    f"malformed external op-call {value_text!r}. Expected "
                    f"`op <ns>.<verb>(args)`, every part of the dotted name "
                    f"starting with a letter (e.g. `op db.query(${{sql}})`)."
                )
            if checks:
                site = PayloadSite(i, value_text, tags, kind, known)
                for check in checks:
                    check(site, result)
