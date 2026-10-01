r"""Pygments lexer + style for core Sigil (the architecture-description language).

This is the **core** token model: it highlights exactly the host-agnostic
language defined in `../language.md` and nothing else. A dialect that adds
vocabulary may ship its own, extended grammar set; words a dialect adds (unknown
`@`-modifiers, extra keywords) read here as generic modifiers / bare names.

Highlights by *responsibility*: glyph delimiters (`[ ]{ }< >( )| |`) + the
control keywords are the binding magenta (`#c850e0`; keyword bold, brackets
not) while the NAME inside a glyph pops in periwinkle (`#8aa0ff`); arrows
(`-> ~> <-> => !> ?> *> →`), `:=`, the joins `&`/`&?` and the value operators
are the pink operator, and cardinality (`×N`/`xN`/`^N`) a softer pink; every
`@`-modifier reads one warm less-gold; the document markers are first-class —
mode line gold, section header slate rails + violet `L<n>` level + near-white
name; `${…}` refs are the substitution seam (violet, NOT tinted toward the
magenta); booleans/null/strings/numbers carry neutral value styles.

Token families (see `language.md`):

- glyphs `[X] {X} <X> (X) |X|`, holes `?`, wildcards `_`, the mutability `~`
  and stream `*` prefixes, parametric `[Cache<K,V>]`;
- the closed arrow set, `:=` expansions, joins `&` / `&?`, alternative `/`,
  the qualified-path separator (`[Ship]/[Bullet]/{Transform}`, no spaces);
- `@`-modifiers (`@inv @sla @timeout @fallback @cap @grants @requires @owns
  @borrow @read @write @each @all …`), critical `!`, cardinality `×N`/`xN`,
  stream caps `^N`;
- mode lines `#!spec`/`#!sketch`/`#!craft`, `#` comments, section headers
  `--- [L<n>:] Name ---`;
- control keywords `state loop parallel branch` (+ `on`, `of`), state-block
  anchors `+` `$` and transitions `-<trigger>->`;
- composition-tree branch markers `\->` `\-&` `\-?` `\-$` `\-@` `\-!` `\-=`
  `\-_`, with the `*-` spawn prefix and one of the `(N)-` weight / `{cond}-`
  prefixes, and the bare spawn `\-*`;
- payload values: `true false null`, numbers, `"…"` strings, triple-quoted
  multiline block strings, `${…}` refs, the external op-call `op ns.verb(…)`.

Module shape: a `Token.Sigil.*` taxonomy, a `SigilStyle` (hex) + `RICH_STYLE`
mapping, `_resolve_style`, `lex_to_text`, `sigil_syntax`, and a `__main__`
smoke. Tools import it by path (`highlight/lexer.py`).

Usage with Rich:

    from rich.syntax import Syntax
    from lexer import SigilLexer, SigilStyle
    Syntax(code, lexer=SigilLexer(), theme=SigilStyle)

Usage for inline Rich Text:

    from lexer import lex_to_text
    text = lex_to_text(sigil_snippet)

Smoke test:

    python lexer.py <file>.sigil
"""
from __future__ import annotations

from pygments.lexer import RegexLexer, bygroups, include
from pygments.style import Style
from pygments.token import (
    Token, Comment, Punctuation, Whitespace, Name, String, Number,
)


# --- Custom token taxonomy --------------------------------------------------

T = Token.Sigil

# Document-level markers — each first-class (its own colour).
T_Doc            = T.Doc                # parent (style fallback)
T_Shebang        = T.Doc.Shebang        # #!spec / #!sketch / #!craft
T_Section        = T.Doc.Section        # the `---` rails of a section header
T_SecLevel       = T.Doc.Section.Level  # the `L<n>` zoom-level marker
T_SecName        = T.Doc.Section.Name   # the section name

# Glyph delimiters — the primary lexicon. The five entity kinds + their
# mutability/stream prefixes share one hue; the NAME inside sits in type
# position.
T_Glyph          = T.Glyph              # [ ] { } < > ( ) | |  + the ~ * prefixes
T_GlyphName      = T.Glyph.Name         # the identifier inside a glyph

# Control keywords (state / loop / parallel / branch, + on / of / op).
T_Keyword        = T.Keyword

# Operators: arrows, `:=`, value operators; joins are a child (same hue).
T_Arrow          = T.Arrow              # -> ~> <-> => !> ?> *> →  :=  ++ || + - * /
T_Join           = T.Arrow.Join         # & (strict join) / &? (race)
T_Path           = T.Arrow.Path         # `/` of a qualified path `[A]/{B}` (no spaces)

# Composition-tree branch marker `\-`, with its `*-` spawn / `(N)-` weight /
# `{cond}-` prefixes and the relation char (`> & ? $ @ ! = _`) — one token; a
# `{cond}` name reads as a glyph name, an `(N)` weight as a number.
T_Branch         = T.Branch

# Modifiers — every `@`-word, the critical `!` and the optional `?` suffix.
T_Mod            = T.Mod

# Cardinality / stream-bound markers.
T_Card           = T.Card               # ×N / xN, ^N stream cap

# Structural sigils — holes / wildcards / state-machine anchors.
T_Hole           = T.Hole               # ? hole
T_Wild           = T.Wild               # _ wildcard / anonymous
T_Anchor         = T.Anchor             # + (creation) / $ (terminal) in state blocks

# Values (neutral — not tinted toward the signature).
T_True           = T.Bool.True_
T_False          = T.Bool.False_
T_Null           = T.Null
T_Ref            = T.Ref
T_RefBrace       = T.Ref.Brace
T_OpName         = T.OpName             # the dotted ns.verb of an external op-call


# --- Lexer ------------------------------------------------------------------

# Control-flow keywords (+ `on` of `branch on`, `of` of `loop @each x of`, and
# `op` of the external op-call).
_BLOCK_KW = r'(?:state|loop|parallel|branch|on|of|op)'
_IDENT    = r'[A-Za-z_][\w-]*'


class SigilLexer(RegexLexer):
    """Pygments lexer for `.sigil` documents (core Sigil)."""

    name      = 'Sigil'
    aliases   = ['sigil']
    filenames = ['*.sigil']
    mimetypes = ['application/x-sigil', 'text/x-sigil']

    tokens = {
        'common': [
            (r'[ \t]+', Whitespace),
            (r'\n',     Whitespace),
            # Mode line: exactly `#!spec` / `#!sketch` / `#!craft`.
            (r'#!(?:spec|sketch|craft)\b', T_Shebang),
            # Section header: `--- [L<n>:] Name ---` (trailing `---` optional);
            # split into rails / level / name.
            (r'(-{3,})([ \t]*)(?:(L\d+)([ \t]*:[ \t]*))?([^\n]*?)([ \t]*)(-{3,})?[ \t]*$',
             bygroups(T_Section, Whitespace, T_SecLevel, Punctuation,
                      T_SecName, Whitespace, T_Section)),
            # Inline / whole-line comment (after the mode-line rule).
            (r'#.*$', Comment.Single),
        ],

        'root': [
            include('common'),

            # Composition-tree branch marker — only at a line start (after the
            # indentation) or right after a parent glyph: `\-` [`*-`]
            # [`(N)-` | `{cond}-`] rel, or the bare spawn `\-*`.
            (r'(?<![^\s\]})>|])(\\-(?:\*-)?)'
             r'(?:(\{)([A-Za-z0-9_-]+)(\}-)|(\()(\d+)(\)-))?([>&?$@!=_])',
             bygroups(T_Branch, T_Branch, T_GlyphName, T_Branch,
                      T_Branch, Number.Integer, T_Branch, T_Branch)),
            (r'(?<![^\s\]})>|])\\-\*(?=\s|$)', T_Branch),

            # Qualified-path separator: a `/` hugging a closing and an opening
            # glyph (`[Bullet]/{Transform}`). A spaced ` / ` stays the
            # alternative value operator.
            (r'(?<=[\]})>|])/(?=[~*]?[\[{<(|])', T_Path),

            # Multiline block-string (triple double-quote) — the one multiline
            # construct. `${…}` inside is template text, so the body stays a string.
            (r'"""', String.Double, 'blockstr'),

            # `${…}` refs — matched early so `${…}` is never read as a `{…}` glyph.
            (r'(\$\{)([^}]*)(\})', bygroups(T_RefBrace, T_Ref, T_RefBrace)),

            # `@`-modifiers (any `@`-word; the core set is listed in language.md).
            (r'@[A-Za-z][\w-]*', T_Mod),

            # State-block transition `-<trigger>->`: dash + event glyph + arrow.
            (r'(-)(<)([^<>\n]*)(>)(->)',
             bygroups(T_Arrow, T_Glyph, T_GlyphName, T_Glyph, T_Arrow)),

            # Arrows + `:=` (longest first so `<->` wins over `<`).
            (r'<->|->|~>|=>|!>|\?>|\*>|→', T_Arrow),
            (r':=', T_Arrow),
            # Joins: `&?` race / `&` strict join.
            (r'&\?|&', T_Join),

            # External op-call `op ns.verb(…)`: keyword + dotted name; the
            # argument list lexes as values until the matching `)`.
            (r'\b(op)(\s+)(' + _IDENT + r'(?:\.' + _IDENT + r')+)(\()',
             bygroups(T_Keyword, Whitespace, T_OpName, Punctuation), 'opargs'),

            # Control keywords (word-bounded).
            (r'\b' + _BLOCK_KW + r'\b', T_Keyword),

            # Mutability / stream prefixes hugging a glyph: `~{Session}`, `*<Event>`.
            (r'[~*](?=[\[{<(|])', T_Glyph),

            # State-machine anchors + holes / wildcards (before the value ops;
            # the creation source `+` is the one that opens a transition).
            (r'\+(?=[ \t]*-<)',        T_Anchor),    # creation source `+ -<e>->`
            (r'\$(?![\w{])',          T_Anchor),    # terminal state
            (r'(?<![\w])_(?![\w])',   T_Wild),      # wildcard / anonymous
            (r'(?<![\w\]})>|])\?(?![\w>])', T_Hole),  # hole (not `?>`, not a suffix)

            # Call parens `verb(…)` / `@mod(…)`: the argument list lexes as
            # values (not as an actor glyph) until the matching `)`.
            (r'(?<=\w)\(', Punctuation, 'opargs'),
            # Map literal `{k: v, …}` (a top-level `:` before the close) and list
            # literal `[v, …]` openers: bare delimiters, the body lexes as values.
            (r'\{(?=[^{}\n]*:)', T_Glyph),
            (r'\[(?=\s*(?:\$\{|"|-?\d|true\b|false\b|null\b|\]))', T_Glyph),

            # Entity glyphs (single line: open + name + close). A `{`/`[` that
            # opens a multi-line block has no close on the line, so it falls
            # through to the bare-delimiter rule and its body lexes in `root`.
            # `||` map merge — never an (empty) store glyph.
            (r'\|\|', T_Arrow),
            (r'(\()([^()\n]*?)(\))',   bygroups(T_Glyph, T_GlyphName, T_Glyph)),
            (r'(\|)([^|\n]*?)(\|)',    bygroups(T_Glyph, T_GlyphName, T_Glyph)),
            (r'(\[)([^\[\]\n]*?)(\])', bygroups(T_Glyph, T_GlyphName, T_Glyph)),
            (r'(\{)([^{}\n]*?)(\})',   bygroups(T_Glyph, T_GlyphName, T_Glyph)),
            (r'(<)([^<>\n]*?)(>)',     bygroups(T_Glyph, T_GlyphName, T_Glyph)),
            (r'[\[\]{}|()]', T_Glyph),

            include('values'),

            # Predicate / comparison operators (`@inv`, guards, `.field` tests).
            (r'!=|>=|<=|=|∈|∉|∪|∩|[<>]', Punctuation),
            # Critical `!` / optional `?` suffix modifiers.
            (r'[!?]', T_Mod),

            # Punctuation glue: `:` `,` `.`.
            (r'[:,.]', Punctuation),

            # Bare identifier — a state name, branch arm label, alias name,
            # internal op verb, map key.
            (_IDENT, Name.Tag),
        ],

        'values': [
            (r'\btrue\b',  T_True),
            (r'\bfalse\b', T_False),
            (r'\bnull\b',  T_Null),

            # Cardinality / retries / fan-out `×N` / `xN`; stream cap `^N`
            # (optional magnitude unit, e.g. `^10k`).
            (r'×(?:\d+|[A-Za-z]\w*)', T_Card),
            (r'\bx\d+\b', T_Card),
            (r'\^\d+[a-zA-Z]*', T_Card),

            # Numbers (optional duration / size unit suffix, e.g. 24h, 500ms).
            (r'-?\d+\.\d+[a-zA-Z%]*', Number.Float),
            (r'-?\d+[a-zA-Z%]*', Number.Integer),

            # Quoted strings.
            (r'"(?:\\.|[^"\\])*"', String.Double),
            (r"'(?:''|[^'])*'",     String.Single),

            # Value operators + alternative `/` (closed set).
            (r'\+\+|\|\||[+\-*/]', T_Arrow),
        ],

        'blockstr': [
            (r'"""', String.Double, '#pop'),
            (r'[^"]+', String.Double),
            (r'"', String.Double),
        ],

        'opargs': [
            (r'\)', Punctuation, '#pop'),
            include('root'),
        ],
    }


# --- Styles -----------------------------------------------------------------

# One colour table serves both the Pygments `Style` and the Rich map
# (truecolor hex; Rich downgrades on terminals without 24-bit colour).
_COLORS = {
    Whitespace:        "",
    Punctuation:       "#586e75",
    Comment.Single:    "italic #6e7681",

    # Document markers — first-class.
    T_Doc:             "bold #c850e0",           # parent fallback
    T_Shebang:         "bold #e3c000",           # mode line (gold)
    T_Section:         "#8b7aad",                # `---` rails (slate)
    T_SecLevel:        "bold #d2a8ff",           # `L<n>` level (violet)
    T_SecName:         "bold #e6edf3",           # section name (near-white)

    # Signature roles.
    T_Glyph:           "#c850e0",                # structure brackets (magenta)
    T_GlyphName:       "italic #8aa0ff",         # name in type position (periwinkle)
    T_Keyword:         "bold #c850e0",           # control keyword (magenta, bold)
    T_Arrow:           "#e85d9e",                # operator (pink)
    T_Join:            "#e85d9e",                # joins read as operators
    T_Path:            "#e85d9e",                # qualified-path `/` (operator)
    T_Mod:             "#ffe0b0",                # modifiers (less-gold)
    T_Card:            "#f59cc4",                # cardinality (soft pink)
    T_Branch:          "#5abea0",                # composition-tree branch marker (teal)
    T_OpName:          "#8aa0ff",                # external op ns.verb (periwinkle)

    # Structural sigils — muted.
    T_Hole:            "italic #6e7681",
    T_Wild:            "italic #6e7681",
    T_Anchor:          "#586e75",

    # Values — neutral.
    T_True:            "#3fb950",
    T_False:           "#f85149",
    T_Null:            "italic #6e7681",
    T_Ref:             "italic #bc8cff",         # the substitution seam
    T_RefBrace:        "#a371f7",

    Name.Tag:          "#c9d1d9",
    String:            "#a5d6ff",
    String.Double:     "#a5d6ff",
    String.Single:     "#a5d6ff",
    Number.Integer:    "#79c0ff",
    Number.Float:      "#79c0ff",
}


class SigilStyle(Style):
    """Pygments style for core Sigil: magenta structure · periwinkle names ·
    less-gold modifiers · pink operators + soft-pink cardinality · first-class
    mode line and section header · neutral value styles."""

    background_color = "#0d1117"
    default_style    = ""
    styles           = dict(_COLORS)


#: Rich style strings (truecolor hex) keyed by token.
RICH_STYLE = dict(_COLORS)


def _resolve_style(token):
    """Walk parent tokens until one has a registered style."""
    while token is not None:
        if token in RICH_STYLE:
            return RICH_STYLE[token]
        token = token.parent
    return ""


def lex_to_text(code: str, lexer: RegexLexer | None = None):
    """Lex `code` with the Sigil lexer, return a Rich `Text`.
    Trims one trailing newline (Pygments always appends one)."""
    from rich.text import Text
    if lexer is None:
        lexer = SigilLexer()
    text = Text()
    tokens = list(lexer.get_tokens(code))
    if tokens and tokens[-1] == (Whitespace, "\n"):
        tokens = tokens[:-1]
    for tok, val in tokens:
        text.append(val, style=_resolve_style(tok))
    return text


def sigil_syntax(code: str, **kwargs):
    """Return a `rich.syntax.Syntax` pre-configured with the Sigil lexer + style."""
    from rich.syntax import Syntax
    return Syntax(code, lexer=SigilLexer(), theme=SigilStyle,
                  background_color="default", **kwargs)


# --- Smoke test -------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from rich.console import Console
    if len(sys.argv) < 2:
        print("usage: lexer.py <file>.sigil", file=sys.stderr)
        sys.exit(2)
    code = open(sys.argv[1]).read()
    Console().print(sigil_syntax(code, line_numbers=True, word_wrap=False))
