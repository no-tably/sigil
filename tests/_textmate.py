"""A small stdlib reader for sigil's two TextMate-family grammars
(`highlight/sigil.tmLanguage.json`, `highlight/sigil.sublime-syntax`): enough
to tokenize them line by line with Python `re`, so a test can compare what an
editor shows with what sigil's own highlighter says (tests/test_highlight_drift.py).

    tmlanguage(path) → Grammar       a TextMate grammar (JSON)
    sublime(path)    → Grammar       a sublime-syntax grammar (needs PyYAML)
    Grammar.scopes(text) → [[scopes per character] per line]

One model serves both: a grammar is a set of *contexts*, each an ordered list of
rules; a rule matches a regex, names scopes for the match and its groups, and
may push a context or pop the current one. That is sublime-syntax's own model;
a TextMate `begin`/`end` rule becomes a push of a context whose first rule is
its `end` (popping, so `end` wins a tie, as TextMate's default), followed by its
`patterns`, the region's `name` laid over everything from the `begin` to the
`end` (sublime's `meta_scope`).

At each position the rule whose match starts earliest wins; a tie goes to the
rule listed first (both engines' rule). A match that is empty and changes no
context steps one character on, unscoped.

What is supported — everything these grammars use, nothing more: `match` /
`name` / `captures`; `begin` / `end` / `beginCaptures` / `endCaptures` /
`patterns`; `include` of `#name`, `$self` and (sublime) a context name;
sublime `scope`, `captures`, `push` (a named or an inline context), `pop: true`,
`meta_scope` and `{{variables}}`. Anything else (`contentName`, `while`,
`applyEndPatternLast`, back-references from `begin` into `end`, `\\G`, sublime
`set` / `embed` / `with_prototype` / `prototype`) raises Unsupported, so a
grammar that grows a construct this reader cannot follow fails loudly rather
than reading wrong.

Regex dialect: the grammars' regexes are written in the common subset of
Oniguruma (TextMate) and Python `re` — `\\w` `\\s` `\\d` `\\b`, classes,
lookahead, fixed-width lookbehind, lazy quantifiers. A regex that uses an
Oniguruma-only construct (`\\h`, `\\A`/`\\G`, possessive or atomic groups,
`(?i:` scoped flags are fine in Python too, variable-width lookbehind) would
fail to compile here or raise Unsupported, and the test says which. None of the
current regexes needs translating. Lines are fed without their newline, so `$`
matches at the line's end, as TextMate's per-line `$` does.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple, Optional


class Unsupported(ValueError):
    """A grammar construct this reader does not follow."""


_ONIG_ONLY = re.compile(r"\\[hHGAKzZ]|\(\?>|[*+?}]\+|\\[pP]\{")


def compile_rx(rx: str) -> "re.Pattern":
    """A grammar regex as a Python pattern; Unsupported for Oniguruma-only text."""
    m = _ONIG_ONLY.search(rx)
    if m:
        raise Unsupported(f"Oniguruma-only construct {m.group(0)!r} in {rx!r}")
    try:
        return re.compile(rx)
    except re.error as exc:
        raise Unsupported(f"regex does not compile in Python re: {rx!r} ({exc})") from exc


class Rule(NamedTuple):
    rx: "re.Pattern"
    scope: Optional[str]          # over the whole match
    captures: tuple               # ((group, scope), …)
    push: Optional[str]           # a context name
    pop: bool


class Context(NamedTuple):
    meta: Optional[str]           # laid over the whole region (begin … end)
    items: tuple                  # Rule | ("include", name)


class Grammar:
    def __init__(self, contexts: dict, main: str):
        self.contexts = contexts
        self.main = main
        self._flat: dict = {}

    def rules(self, name: str) -> list:
        """A context's rules, includes expanded (each context once)."""
        if name not in self._flat:
            out, seen = [], set()

            def walk(ctx_name):
                if ctx_name in seen:
                    return
                seen.add(ctx_name)
                if ctx_name not in self.contexts:
                    raise Unsupported(f"include of an unknown context {ctx_name!r}")
                for item in self.contexts[ctx_name].items:
                    if isinstance(item, Rule):
                        out.append(item)
                    else:
                        walk(item[1])
            walk(name)
            self._flat[name] = out
        return self._flat[name]

    def scopes(self, text: str) -> list:
        """Per line (str.splitlines), per character: the scopes on it, outer
        first (the root scope left out)."""
        stack = [self.main]
        out = []
        for raw in text.splitlines():
            line, stack = self._line(raw, stack)
            out.append(line)
        return out

    def _line(self, raw: str, stack: list) -> tuple:
        stack = list(stack)
        cells = [[] for _ in raw]
        pos = 0
        n = len(raw)

        def base():
            return [self.contexts[c].meta for c in stack[1:] if self.contexts[c].meta]

        while pos <= n:
            best = None
            for rule in self.rules(stack[-1]):
                m = rule.rx.search(raw, pos)
                if m and (best is None or m.start() < best[1].start()):
                    best = (rule, m)
                    if m.start() == pos:
                        break
            if best is None:
                for k in range(pos, n):           # the rest: the context's scopes
                    cells[k] = base()
                break
            rule, m = best
            a, b = m.span()
            meta = None
            if rule.push:
                meta = self.contexts[rule.push].meta
            outer = base() + ([meta] if meta else [])
            if rule.pop and not rule.push:
                outer = base()                    # the region's meta covers its end
            for k in range(pos, a):               # skipped text: the context's scopes
                cells[k] = base()
            for k in range(a, b):
                cells[k] = outer + ([rule.scope] if rule.scope else [])
            for g, scope in rule.captures:
                ga, gb = m.span(g)
                if ga < 0:
                    continue
                for k in range(ga, gb):
                    cells[k] = cells[k] + [scope]
            if rule.pop and len(stack) > 1:
                stack.pop()
            if rule.push:
                stack.append(rule.push)
            if a == b and not rule.push and not rule.pop:
                if a < n:
                    cells[a] = base()
                pos = a + 1
            else:
                pos = b
            if pos >= n and a == b and not rule.push:
                break
        return cells, stack


# ---------------------------------------------------------------------------
# TextMate (JSON)
# ---------------------------------------------------------------------------

_TM_KEYS = {"name", "match", "captures", "begin", "end", "beginCaptures",
            "endCaptures", "patterns", "include", "comment"}


def _caps(obj) -> tuple:
    return tuple(sorted((int(g), c["name"]) for g, c in (obj or {}).items() if "name" in c))


def tmlanguage(path: Path) -> Grammar:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    contexts: dict = {}
    counter = [0]

    def patterns(items) -> tuple:
        out = []
        for p in items:
            extra = set(p) - _TM_KEYS
            if extra:
                raise Unsupported(f"TextMate keys not followed: {sorted(extra)}")
            if "include" in p:
                inc = p["include"]
                if inc == "$self":
                    out.append(("include", "$self"))
                elif inc.startswith("#"):
                    out.append(("include", "repo:" + inc[1:]))
                else:
                    raise Unsupported(f"include of another grammar {inc!r}")
            elif "match" in p:
                out.append(Rule(compile_rx(p["match"]), p.get("name"),
                                _caps(p.get("captures")), None, False))
            elif "begin" in p:
                counter[0] += 1
                ctx = f"region:{counter[0]}"
                end = Rule(compile_rx(p["end"]), None,
                           _caps(p.get("endCaptures") or p.get("captures")), None, True)
                contexts[ctx] = Context(p.get("name"), (end,) + patterns(p.get("patterns", ())))
                out.append(Rule(compile_rx(p["begin"]), None,
                                _caps(p.get("beginCaptures") or p.get("captures")), ctx, False))
            elif "patterns" in p:
                out.extend(patterns(p["patterns"]))
            else:
                raise Unsupported(f"TextMate rule with neither match nor begin: {p}")
        return tuple(out)

    contexts["$self"] = Context(None, patterns(doc["patterns"]))
    for name, entry in doc.get("repository", {}).items():
        contexts["repo:" + name] = Context(None, patterns(
            entry["patterns"] if "patterns" in entry and len(entry) <= 2 else [entry]))
    return Grammar(contexts, "$self")


# ---------------------------------------------------------------------------
# sublime-syntax (YAML)
# ---------------------------------------------------------------------------

_SUB_KEYS = {"match", "scope", "captures", "push", "pop", "include", "meta_scope"}


def sublime(path: Path) -> Grammar:
    import yaml                                  # optional: callers skip without it
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    variables = doc.get("variables", {})

    def expand(rx: str) -> str:
        for _ in range(10):
            new = re.sub(r"\{\{(\w+)\}\}", lambda m: variables[m.group(1)], rx)
            if new == rx:
                return rx
            rx = new
        return rx

    contexts: dict = {}
    counter = [0]

    def context(items) -> Context:
        meta, out = None, []
        for p in items:
            extra = set(p) - _SUB_KEYS
            if extra:
                raise Unsupported(f"sublime-syntax keys not followed: {sorted(extra)}")
            if "meta_scope" in p:
                meta = p["meta_scope"]
            elif "include" in p:
                out.append(("include", p["include"]))
            else:
                push = p.get("push")
                if isinstance(push, list):
                    counter[0] += 1
                    name = f"inline:{counter[0]}"
                    contexts[name] = context(push)
                    push = name
                caps = tuple(sorted((int(g), s) for g, s in (p.get("captures") or {}).items()))
                out.append(Rule(compile_rx(expand(p["match"])), p.get("scope"), caps,
                                push, bool(p.get("pop"))))
        return Context(meta, tuple(out))

    for name, items in doc["contexts"].items():
        if name == "prototype":
            raise Unsupported("sublime-syntax prototype context")
        contexts[name] = context(items)
    return Grammar(contexts, "main")
