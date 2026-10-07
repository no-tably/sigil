# The Claude Code viewer mod

This folder holds the source of the viewer that the Claude Code plugin carries. It is
a plugin of function hooks. `build.py` merges its manifest's `types` and
`userConfig` into the claude `plugin.json` and copies `hooks/` and `types/`. It
also puts `scripts/pane.py` and `site/frames.py` beside the skill's tools in
`skills/sigil/scripts/`. `tests/` and `tsconfig.json` are not shipped.
[`docs/tools.md`](../../docs/tools.md#the-claude-code-viewer) documents how it
behaves.

```
hooks/hooks.json     names the hooks module
hooks/sigil.tsx      the tool, /sigil-pane, the pane, the file watch, playback, the split
hooks/logic.ts       the pure half: requests, argv, the display choice, cell packing
types/index.d.ts     the session state the pane draws from (PluginState)
scripts/pane.py      `draw`: a document as packed rows (JSON); `follow`: the split's loop
tests/*.test.ts      run by `claude plugin test`
```

`/sigil` is the skill's own command, so the mod's command is `/sigil-pane`.

## Develop

```sh
claude plugin validate plugin/claude          # what the module hooks and calls
claude plugin test plugin/claude              # tests/*.test.ts against the engine
./build.py --target claude && claude --plugin-dir dist/claude   # try it
```

To type-check, use TypeScript 5.4 or newer with `tsconfig.json` here. When Claude
Code loads the folder it writes the API's declarations to `.claude-plugin/types/`
(gitignored).

`tests/test_claude_mod.py` covers `pane.py` and the packaging. When `claude` is on
the PATH, it also runs the validate and test commands above.
