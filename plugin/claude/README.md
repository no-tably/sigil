# The Claude Code viewer mod

This folder holds the source of the viewer that the Claude Code plugin carries. It is
a plugin of function hooks. `build.py` merges its manifest's `types` and
`userConfig` into the claude `plugin.json` and copies `hooks/` and `types/`. Its
Python half is the package's `sigil frames` (`sigil/present/frames.py`), which the
skill ships in `skills/sigil/scripts/` with `bin/sigil`. `tests/` and
`tsconfig.json` are not shipped.
[`docs/tools.md`](../../docs/tools.md#the-claude-code-viewer) documents how it
behaves.

```
hooks/hooks.json     names the hooks module
hooks/sigil.tsx      the tool, /sigil-pane, the pane, the file watch, playback, the split
hooks/logic.ts       the pure half: requests, argv, the display and layout choices, cell packing
types/index.d.ts     the session state the pane draws from (PluginState)
tests/*.test.ts      run by `claude plugin test`
```

On the terminal the pane draws the drawing as `Raster`s, which `$.ui.blit` repaints
in place. Rows that hold a wide character (CJK, most emoji) are drawn as `Text`
instead, so they can't be blitted. The engine's `RasterProps.cells` takes only
"one printable width-1 BMP character" per cell, and a tree whose Raster holds a
wide code point is refused ("Raster … cell 0 holds U+754C, which is not one
printable width-1 code point"). A blit carries the same cells, so it is refused
too. Writing the glyph as `?` would keep the Raster but lose the character, so
those rows stay text until the engine's Raster takes wide cells.

`/sigil` is the skill's own command, so the mod's command is `/sigil-pane`.
`/sigil-pane display [mod|multiplex|auto]` says or sets where it draws, and
`/sigil-pane layout [auto|wrap|pan]` how a wide drawing fits: each writes the
plugin's own `/config` row (`<plugin>.display`, `<plugin>.layout`) with
`$.config.set`, which reloads the module with the new option. It follows the
[viewer plugin contract](../../docs/tools.md#the-viewer-plugin-contract).

## Develop

```sh
claude plugin validate plugin/claude          # what the module hooks and calls
claude plugin test plugin/claude              # tests/*.test.ts against the engine
./build.py --target claude && claude --plugin-dir dist/claude   # try it
```

To type-check, use TypeScript 5.4 or newer with `tsconfig.json` here. When Claude
Code loads the folder it writes the API's declarations to `.claude-plugin/types/`
(gitignored). Those declarations come only from a Claude Code install, so CI
can't type-check `hooks/sigil.tsx` or `tests/`. It does check `hooks/logic.ts`,
through the pi extension's check ([`../pi`](../pi/README.md#develop)). Outside a loaded
folder, the plugin-authoring skill writes the same file (`claude-code.d.ts`). Put it
in a `tsconfig` that `extends` this one and `include` it with `hooks`, `types` and
`tests`.

`tests/test_claude_mod.py` covers `sigil frames` and the packaging. When `claude` is on
the PATH, it also runs the validate and test commands above.
