" Vim syntax file for core Sigil (the architecture-description language).
"
" Regexes mirror the token model in lexer.py (this highlight directory); the
" `sigil*` groups link to standard groups via `hi def link`, and
" after/syntax/sigil.vim applies the palette hexes. Items are defined from
" lowest to highest priority (for items starting at the same column, the one
" defined LAST wins in vim).

if exists("b:current_syntax")
  finish
endif

" --- Bare names: states / labels / verbs / map keys (lowest priority) -------
syn match sigilTag "[A-Za-z_][[:alnum:]_-]*"
" A state name, in a state block's body (sigilStateBody, below) in sigilTag's place.
syn match sigilStateName "[A-Za-z_][[:alnum:]_-]*" contained containedin=sigilStateBody
" A call's name, right before its `(`: charge({Order}), walk(.children).
syn match sigilCallName "[A-Za-z_][[:alnum:]_.]*\%(-[[:alnum:]_.]\+\)*\ze("

" --- Punctuation, predicates, suffix modifiers -----------------------------
syn match sigilPunct "[:,.]"
" A .field hugging a closing glyph ({Order}.total) — one bare name, the dot included.
syn match sigilTag "\%([]})>|]\)\@1<=\.[A-Za-z_][[:alnum:]_-]*"
syn match sigilPunct "!=\|>=\|<=\|=\|∈\|∉\|∪\|∩\|[<>]"
syn match sigilModifier "[!?]"

" --- Values: constants / numbers / value operators / cardinality -----------
syn keyword sigilConst true false null
syn match sigilNumber "-\=\d\+\%(\.\d\+\)\=[a-zA-Z%]*"
syn match sigilOperator "++\|||\|[-+*/]"
syn match sigilCard "×\%(\d\+\|[A-Za-z]\w*\)"
syn match sigilCard "\<x\d\+\>"
syn match sigilCard "\^\d\+[a-zA-Z]*"
" Modifier-alias references after a cardinality, to the end of the payload
" (charge ×3 Retry): each name reads as a modifier.
syn match sigilModifier "\%(\%(×\%(\d\+\|[A-Za-z]\w*\)\|\<x\d\+\>\)\%([ \t]\+[A-Za-z_][[:alnum:]_-]*\)*[ \t]\+\)\@<=[A-Za-z_][[:alnum:]_-]*\ze\%([ \t]\+[A-Za-z_][[:alnum:]_-]*\)*[ \t]*\%([#@!]\|$\)"
syn region sigilString start=+"+ skip=+\\.+ end=+"+ oneline
syn region sigilString start=+'+ skip=+''+ end=+'+ oneline
" Multiline triple-quoted block string (the one multiline construct).
syn region sigilString start=+"""+ end=+"""+ keepend

" --- Glyphs: delimiters (keyword) + inner name (type position) --------------
" Bare (unbalanced) delimiters — overridden by the regions below; a block's
" { } is punctuation.
syn match sigilGlyphDelim "[][|()]"
syn match sigilPunct "[{}]"
syn region sigilGlyph matchgroup=sigilGlyphDelim start="\[" end="\]" oneline contains=sigilTypeName
syn region sigilGlyph matchgroup=sigilGlyphDelim start="(" end=")" oneline contains=sigilTypeName
syn region sigilGlyph matchgroup=sigilGlyphDelim start="|" end="|" oneline contains=sigilTypeName
syn region sigilGlyph matchgroup=sigilGlyphDelim start="{\s\@!" end="}" oneline contains=sigilTypeName
syn region sigilGlyph matchgroup=sigilGlyphDelim start="<" end=">" oneline contains=sigilTypeName
syn match sigilTypeName "[^][(){}|<>]\+" contained
" A transition's trigger list -<A, B>->: split at its commas (each item its own
" name, the comma punctuation).
syn region sigilGlyph matchgroup=sigilGlyphDelim start="-\@1<=<\ze[^<>]*>->" end=">\ze->" oneline contains=sigilTriggerName,sigilPunct
syn match sigilTriggerName "[^][(){}|<>,[:space:]]\+" contained
" Mutability / stream prefixes hugging a glyph.
syn match sigilGlyphDelim "[~*]\ze[[{<(|]"
" Map literal {k: v} and list literal [v, …] openers: bare openers
" (punctuation, as a block's brace), the body highlights as values.
syn match sigilPunct "{\ze[^{}]*:"
" A set {a, b} (a comma before its close, as in {Order}.status ∈ {pending,
" active}): a bare opener too, its items highlight as values — no data glyph.
syn match sigilPunct "{\ze[^{}]*,[^{}]*}"
" Braces right after ∈ / ∉ are a set whatever they hold (∈ {Open}).
syn match sigilPunct "\%([∈∉][ \t]\{,3}\)\@<={"
syn region sigilArgs matchgroup=sigilPunct start="\[\ze\s*\%(\${\|\"\|-\=\d\|true\>\|false\>\|null\>\|]\)" end="]" transparent contains=TOP
" `||` map merge — never an (empty) store glyph.
syn match sigilOperator "||"
" Call parens verb(…) / @mod(…): the arguments highlight as values.
syn region sigilArgs matchgroup=sigilPunct start="\w\@1<=(" end=")" transparent contains=TOP

" --- Structural sigils: anchors / holes / wildcards (muted meta) -----------
syn match sigilMeta "\$\ze\%([^[:alnum:]{]\|$\)"
syn match sigilMeta "+\ze[ \t]*-<"
syn match sigilMeta "\%(^\|\s\)\zs_\ze\%(\s\|$\)"
syn match sigilMeta "\%(^\|\s\)\zs?\ze\%(\s\|$\)"

" --- Operators: arrows, :=, joins, transitions ----------------------------
syn match sigilOperator "<->\|->\|\~>\|=>\|!>\|?>\|\*>\|→"
syn match sigilOperator ":="
syn match sigilOperator "&?\|&"
syn match sigilOperator "-\ze<[^<>]*>->"

" --- Composition-tree branch marker (after the operators, so it wins) -------
" `\-` [`*-`] [`(N)-` | `{cond}-`] rel (rel ∈ > & ? $ @ ! = _), or the bare
" spawn `\-*`; only at a line start or right after a parent glyph. The {cond}
" name is a type name, the (N) weight a number.
syn match sigilBranch "\%([^[:space:]\]})>|]\)\@1<!\\-\%(\*-\)\=\%({[A-Za-z0-9_-]\+}-\|(\d\+)-\)\=[>&?$@!=_]" contains=sigilBranchCond,sigilBranchWeight
syn match sigilBranch "\%([^[:space:]\]})>|]\)\@1<!\\-\*\ze\%(\s\|$\)"
syn match sigilBranchCond "{\@1<=[A-Za-z0-9_-]\+\ze}" contained
syn match sigilBranchWeight "(\@1<=\d\+\ze)" contained
" Qualified-path separator `[Bullet]/{Transform}` (no spaces) — an operator.
syn match sigilOperator "\%([]})>|]\)\@1<=/\ze[~*]\=[[{<(|]"

" --- Modifiers + refs ------------------------------------------------------
syn match sigilModifier "@[A-Za-z][[:alnum:]_-]*"
syn match sigilRef "\${[^}]*}" contains=sigilRefBrace
syn match sigilRefBrace "\${" contained
syn match sigilRefBrace "}" contained

" --- State blocks ----------------------------------------------------------
" `state <owner> {` … `}` (one line or many): from after the keyword to the `}`
" that closes the body (the owner glyph's own `}` is inside its glyph). In the
" body a bare name is a state name (sigilStateName, defined with sigilTag so
" every other item still wins over it), `+ $ _` its anchors.
syn region sigilStateBody start="\%(^\s*state\)\@<=\ze\%(\s[^#]*\)\={" matchgroup=sigilPunct end="}"
      \ transparent contains=TOP,sigilTag
syn match sigilMeta "\%(^\|\s\)\zs+\ze\%(\s\|$\)" contained containedin=sigilStateBody

" --- Control keywords + the external op-call name --------------------------
syn keyword sigilKeyword state loop parallel branch on of op
syn match sigilOpName "\%(\<op\s\+\)\@<=[A-Za-z_][[:alnum:]_-]*\%(\.[A-Za-z_][[:alnum:]_-]*\)\+"

" --- Doc markers: comment / section header / mode line (highest) -----------
syn match sigilComment "#.*$" contains=NONE
syn region sigilSecName matchgroup=sigilSecRail
      \ start="^-\{3,}" end="-\{3,}\s*$\|$" keepend oneline
      \ contains=sigilSecLevel
syn match sigilSecLevel "\<L\d\+\>\s*:\?" contained
" Mode line: a line-leading `#!` holds the whole line (sigil.core.lex
" .is_mode_line; trailing text is lint's SGL001, still the mode line).
syn match sigilShebang "^\s*\zs#!.*$"
" Kind line `#% …` (sigil.core.kinds): the mark first-class, its known words
" keywords, other words plain; a `#` ends it (a comment).
syn match sigilKindLine "^\s*#%[^#]*" transparent contains=sigilShebang,sigilKeyword
syn match sigilShebang "#%" contained
syn match sigilKeyword "\%(^\|[^[:alnum:]_-]\)\@1<=\%(service\|library\|daemon\|job\|networked\|in-process\|concurrent\|deterministic\)\%([[:alnum:]_-]\)\@!" contained
" Dialect declaration `#& name …` (line-leading; language.md "Dialects"): the
" mark first-class, the name a keyword, what it holds dialect text core does not
" read (sigilDecl), a `{ … }` body over as many lines as its braces take (a brace
" in a `"…"` string is text).
syn region sigilDecl matchgroup=sigilDeclMark start="^\s*#&" end="$"
      \ contains=sigilDeclName,sigilDeclBraces,sigilDeclStr
syn match sigilDeclName "\%(#&\s*\)\@<=[^[:space:]~[\]{}<>()|]\+" contained
syn region sigilDeclBraces start="{" end="}" contained transparent
      \ contains=sigilDeclBraces,sigilDeclStr
syn match sigilDeclStr +"\%([^"\\]\|\\.\)*"+ contained transparent contains=NONE

" --- hi def link to the standard groups ------------------------------------
hi def link sigilKeyword        Statement
hi def link sigilGlyphDelim     Statement
hi def link sigilTypeName       Type
hi def link sigilTriggerName    Type
hi def link sigilStateName      Type
hi def link sigilModifier       StorageClass
hi def link sigilOperator       Operator
hi def link sigilCard           Operator
hi def link sigilBranch         Operator
hi def link sigilBranchCond     Type
hi def link sigilBranchWeight   Number
hi def link sigilOpName         Function
hi def link sigilCallName       Function
hi def link sigilShebang        PreProc
hi def link sigilDeclMark       PreProc
hi def link sigilDeclName       Statement
hi def link sigilDecl           Comment
hi def link sigilSecName        Title
hi def link sigilSecRail        Comment
hi def link sigilSecLevel       Special
hi def link sigilRef            Identifier
hi def link sigilRefBrace       Special
hi def link sigilString         String
hi def link sigilNumber         Number
hi def link sigilConst          Boolean
hi def link sigilComment        Comment
hi def link sigilMeta           Comment
hi def link sigilPunct          Delimiter
hi def link sigilTag            Identifier

let b:current_syntax = "sigil"
