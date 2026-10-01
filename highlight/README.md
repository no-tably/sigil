# Sigil syntax highlighting — core grammars

Highlighting for `.sigil` files (core Sigil, as defined in
[`../language.md`](../language.md)) across these tools: **bat · broot · nvim ·
vscode**, plus a Pygments lexer for Python.

**One token model, many surfaces.** The token model is
[`lexer.py`](./lexer.py) (a Pygments lexer, usable from Python via Rich); the
grammars here are its *edge* deployments. Every grammar maps the same token
classes to the same scope / group names, and each theme maps those scopes to
one palette: **themed roles** (keyword / modifier / operator / type) carry the
`.sigil` suffix and the magenta signature; **universal roles** (ref / string /
number / constant / comment / meta / tag / punctuation) use the bare standard
scopes with neutral values.

## What is highlighted

| Token family | Examples | Scope (TextMate / syntect) | Colour |
|---|---|---|---|
| glyph delimiters + `~` / `*` prefixes | `[ ] { } < > ( ) \| \|`, `~{Session}`, `*<Evt>` | `keyword.control.sigil.glyph` | magenta `#c850e0` |
| glyph name (type position) | `AuthSvc` in `[AuthSvc]` | `storage.type.sigil` | periwinkle `#8aa0ff` italic |
| control keywords | `state loop parallel branch on of op` | `keyword.control.sigil` | magenta bold |
| arrows · `:=` · joins · value operators | `-> ~> <-> => !> ?> *> →`, `:=`, `&` `&?`, `++ \|\| + - * /` | `keyword.operator.sigil.*` | pink `#e85d9e` |
| cardinality / stream cap | `×3` `xN` `^10k` | `keyword.operator.sigil.cardinality` | soft pink `#f59cc4` |
| modifiers | `@inv @sla @timeout @fallback @cap @owns @borrow @read @write @each @all …`, critical `!`, optional `?` | `storage.modifier.sigil` | less-gold `#ffe0b0` |
| external op-call name | `db.insert` in `op db.insert(…)` | `entity.name.function.sigil.op` | periwinkle |
| mode line | `#!spec` `#!sketch` `#!craft` | `keyword.other.sigil.shebang` | gold `#e3c000` bold |
| section header | `--- L2: [Core] ---` | rails `punctuation.definition.sigil.section` · level `markup.heading.sigil.level` · name `markup.heading.sigil.name` | slate · violet · near-white |
| comment | `# note` | `comment.line.sigil` | grey italic |
| refs | `${state.count}` | `variable.interpolation` + `punctuation.definition.template-expression` | violet |
| strings | `"x"`, `'x'`, triple-quoted block strings | `string.quoted.sigil.*` | `#a5d6ff` |
| numbers · constants | `3` `0.5` `30s`, `true false null` | `constant.numeric` · `constant.language.*` | blue · green / red / grey |
| state-block anchors · holes · wildcards | `+` `$`, `?`, `_` | `comment.other.meta.sigil.*` | muted |
| state transition | `-<trigger>->` | arrow + event glyph | pink + magenta |
| bare names | state names, branch labels, verbs, map keys | `entity.name.tag.sigil` | `#c9d1d9` |

Anything outside core Sigil gets no special treatment: an unfamiliar `@word`
reads as a modifier, an unfamiliar word as a bare name. A dialect of Sigil may
ship its own extended grammar set built on these same scopes.

## Files

| File | Tool(s) | Purpose |
|------|---------|---------|
| `lexer.py` | Python (Pygments / Rich) | the token model + Pygments `Style` + `lex_to_text` |
| `sigil.sublime-syntax` | bat · broot (syntect) | grammar (contexts → scopes) |
| `sigil.tmTheme` | bat · broot (syntect) | theme (scope → hex) |
| `sigil.tmLanguage.json` | vscode (TextMate) | grammar (patterns → scopes) |
| `sigil-color-theme.json` | vscode | colour theme (scope → hex) |
| `package.json` + `language-configuration.json` | vscode | extension scaffold |
| `syntax/sigil.vim` | nvim/vim | syntax (`syn match/region` → `sigil*` groups) |
| `ftdetect/sigil.vim` | nvim/vim | filetype detection for `*.sigil` |
| `after/syntax/sigil.vim` | nvim/vim | the `sigil*` group → hex mapping |
| `sample.sigil` | all | smoke fixture (lints clean with `../lint.py`) |

---

## bat (syntect)

`bat` reads sublime-syntax grammars + `.tmTheme` themes from its config dir.

```sh
# 1. Install the grammar + theme
mkdir -p "$(bat --config-dir)/syntaxes" "$(bat --config-dir)/themes"
cp sigil.sublime-syntax "$(bat --config-dir)/syntaxes/"
cp sigil.tmTheme        "$(bat --config-dir)/themes/"

# 2. Rebuild bat's cache so it picks them up
bat cache --build

# 3. Use it
bat --theme=sigil sample.sigil
```

Set `--theme` permanently via `BAT_THEME=sigil` or bat's config file. The theme
name bat expects is the `.tmTheme` **filename** (`sigil`). `sigil.tmTheme` is a
complete dark theme (a GitHub-Dark-style base under the signature), so it is
safe as a global default. The `.sigil` extension is bound by the grammar's
`file_extensions`.

## broot (syntect)

`broot` uses the same syntect engine; one `sigil.sublime-syntax` serves both:

```sh
mkdir -p ~/.config/broot/syntaxes
cp sigil.sublime-syntax ~/.config/broot/syntaxes/
# broot picks the syntect theme via its conf.toml `syntax_theme` key.
```

## nvim / vim

Install as a tiny plugin directory (any plugin manager, or native packages).
The three vim files mirror vim's runtime layout:

```sh
# Option A — native packages (no plugin manager)
DEST=~/.config/nvim/pack/sigil/start/sigil        # nvim
# DEST=~/.vim/pack/sigil/start/sigil               # vim
mkdir -p "$DEST"
cp -r syntax ftdetect after "$DEST/"
```

```vim
" Option B — any plugin manager, pointed at this directory, e.g. lazy.nvim:
{ dir = "/path/to/sigil/highlight" }
```

`ftdetect/sigil.vim` binds `*.sigil` → `filetype=sigil`; `syntax/sigil.vim`
defines the groups + links them to standard groups; `after/syntax/sigil.vim`
applies the palette hexes (GUI + 256-colour terminals; lower-colour terminals
fall back to the standard-group links). Use `set termguicolors` for the exact
hexes.

## vscode (TextMate)

The `highlight/` directory is a minimal extension. For development:

```sh
ln -s "$(pwd)" ~/.vscode/extensions/sigil-syntax-0.1.0
# then reload VS Code
```

Or package it with `vsce`:

```sh
npm install -g @vscode/vsce
vsce package          # produces sigil-syntax-0.1.0.vsix
code --install-extension sigil-syntax-0.1.0.vsix
```

`package.json` contributes the `sigil` language (`.sigil`), the grammar
(`sigil.tmLanguage.json` → `source.sigil`) and the **Sigil (magenta)** colour
theme. The grammar alone highlights with whatever theme is active, since the
scopes are standard TextMate names; the bundled theme gives the exact palette.

## From Python

```python
from lexer import lex_to_text, sigil_syntax   # load highlight/lexer.py by path
text = lex_to_text("[A] -> [B] : ${x}")       # a rich.text.Text
```

`python lexer.py sample.sigil` prints a highlighted smoke render.

## Keeping the surfaces in sync

The lexer is the authority. When a token rule changes, change it in every
grammar (sublime, tmLanguage, vim) and keep every scope mapped by both themes;
`../tests/test_highlight_grammars.py` checks the grammars and themes stay
consistent, and `../tests/test_lexer.py` pins the token model.
