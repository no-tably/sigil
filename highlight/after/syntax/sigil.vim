" Sigil colour mapping — the palette hexes applied to the `sigil*` groups.
"
" Loaded after syntax/sigil.vim (the `hi def link`s), so these explicit `hi`
" definitions win for .sigil buffers WITHOUT clobbering the user's colorscheme
" globally.

if !has("gui_running") && &t_Co < 256
  " Low-color terminals fall through to the `hi def link` standard groups.
  finish
endif

" --- Signature roles -------------------------------------------------------
hi sigilKeyword       guifg=#c850e0 gui=bold    ctermfg=170 cterm=bold
hi sigilGlyphDelim    guifg=#c850e0 gui=NONE    ctermfg=170 cterm=NONE
hi sigilTypeName      guifg=#8aa0ff gui=italic  ctermfg=111 cterm=italic
hi sigilOpName        guifg=#8aa0ff gui=NONE    ctermfg=111 cterm=NONE
hi sigilModifier      guifg=#ffe0b0 gui=NONE    ctermfg=223 cterm=NONE
hi sigilOperator      guifg=#e85d9e gui=NONE    ctermfg=168 cterm=NONE
hi sigilCard          guifg=#f59cc4 gui=NONE    ctermfg=211 cterm=NONE
hi sigilBranch        guifg=#5abea0 gui=NONE    ctermfg=73  cterm=NONE
hi sigilBranchCond    guifg=#8aa0ff gui=italic  ctermfg=111 cterm=italic
hi sigilBranchWeight  guifg=#79c0ff gui=NONE    ctermfg=75  cterm=NONE

" --- Document markers (first-class) ---------------------------------------
hi sigilShebang       guifg=#e3c000 gui=bold    ctermfg=178 cterm=bold
hi sigilSecRail       guifg=#8b7aad gui=NONE    ctermfg=103 cterm=NONE
hi sigilSecLevel      guifg=#d2a8ff gui=bold    ctermfg=183 cterm=bold
hi sigilSecName       guifg=#e6edf3 gui=bold    ctermfg=255 cterm=bold

" --- Universal roles (not tinted) -----------------------------------------
hi sigilRef           guifg=#bc8cff gui=italic  ctermfg=141 cterm=italic
hi sigilRefBrace      guifg=#a371f7 gui=NONE    ctermfg=99  cterm=NONE
hi sigilString        guifg=#a5d6ff gui=NONE    ctermfg=153 cterm=NONE
hi sigilNumber        guifg=#79c0ff gui=NONE    ctermfg=75  cterm=NONE
hi sigilConst         guifg=#3fb950 gui=NONE    ctermfg=71  cterm=NONE
hi sigilComment       guifg=#6e7681 gui=italic  ctermfg=242 cterm=italic
hi sigilMeta          guifg=#6e7681 gui=italic  ctermfg=242 cterm=italic
hi sigilPunct         guifg=#586e75 gui=NONE    ctermfg=242 cterm=NONE
hi sigilTag           guifg=#c9d1d9 gui=NONE    ctermfg=252 cterm=NONE
