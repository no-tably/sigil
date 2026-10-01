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

" --- Punctuation, predicates, suffix modifiers -----------------------------
syn match sigilPunct "[:,.]"
syn match sigilPunct "!=\|>=\|<=\|=\|∈\|∉\|∪\|∩\|[<>]"
syn match sigilModifier "[!?]"

" --- Values: constants / numbers / value operators / cardinality -----------
syn keyword sigilConst true false null
syn match sigilNumber "-\=\d\+\%(\.\d\+\)\=[a-zA-Z%]*"
syn match sigilOperator "++\|||\|[-+*/]"
syn match sigilCard "×\%(\d\+\|[A-Za-z]\w*\)"
syn match sigilCard "\<x\d\+\>"
syn match sigilCard "\^\d\+[a-zA-Z]*"
syn region sigilString start=+"+ skip=+\\.+ end=+"+ oneline
syn region sigilString start=+'+ skip=+''+ end=+'+ oneline
" Multiline triple-quoted block string (the one multiline construct).
syn region sigilString start=+"""+ end=+"""+ keepend

" --- Glyphs: delimiters (keyword) + inner name (type position) --------------
" Bare (unbalanced / block-opening) delimiters — overridden by the regions below.
syn match sigilGlyphDelim "[][{}|()]"
syn region sigilGlyph matchgroup=sigilGlyphDelim start="\[" end="\]" oneline contains=sigilTypeName
syn region sigilGlyph matchgroup=sigilGlyphDelim start="(" end=")" oneline contains=sigilTypeName
syn region sigilGlyph matchgroup=sigilGlyphDelim start="|" end="|" oneline contains=sigilTypeName
syn region sigilGlyph matchgroup=sigilGlyphDelim start="{" end="}" oneline contains=sigilTypeName
syn region sigilGlyph matchgroup=sigilGlyphDelim start="<" end=">" oneline contains=sigilTypeName
syn match sigilTypeName "[^][(){}|<>]\+" contained
" Mutability / stream prefixes hugging a glyph.
syn match sigilGlyphDelim "[~*]\ze[[{<(|]"
" Map literal {k: v} and list literal [v, …] openers: bare delimiters, the
" body highlights as values.
syn match sigilGlyphDelim "{\ze[^{}]*:"
syn match sigilGlyphDelim "\[\ze\s*\%(\${\|\"\|-\=\d\|true\>\|false\>\|null\>\|]\)"
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

" --- Control keywords + the external op-call name --------------------------
syn keyword sigilKeyword state loop parallel branch on of op
syn match sigilOpName "\%(\<op\s\+\)\@<=[A-Za-z_][[:alnum:]_-]*\%(\.[A-Za-z_][[:alnum:]_-]*\)\+"

" --- Doc markers: comment / section header / mode line (highest) -----------
syn match sigilComment "#.*$" contains=NONE
syn region sigilSecName matchgroup=sigilSecRail
      \ start="^-\{3,}" end="-\{3,}\s*$\|$" keepend oneline
      \ contains=sigilSecLevel
syn match sigilSecLevel "\<L\d\+\>\s*:\?" contained
syn match sigilShebang "#!\%(spec\|sketch\|craft\)\>"

" --- hi def link to the standard groups ------------------------------------
hi def link sigilKeyword        Statement
hi def link sigilGlyphDelim     Statement
hi def link sigilTypeName       Type
hi def link sigilModifier       StorageClass
hi def link sigilOperator       Operator
hi def link sigilCard           Operator
hi def link sigilBranch         Operator
hi def link sigilBranchCond     Type
hi def link sigilBranchWeight   Number
hi def link sigilOpName         Function
hi def link sigilShebang        PreProc
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
