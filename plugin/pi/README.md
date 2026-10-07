# The pi viewer extension

This folder holds the source of the viewer that the pi package carries. It does
what the Claude Code mod in [`../claude`](../claude/README.md) does, with pi's
extension API: a `sigil_view` tool for the agent, a `/sigil-pane` command for the
person, and a widget above the editor that redraws on every save. `build.py`
copies `extensions/sigil/index.ts` into the package, puts the mod's
`hooks/logic.ts` beside it (the requests, the `display` rule and the split
commands are shared), and puts `pane.py` and `site/frames.py` beside the skill's
tools. The package's `package.json` names the extension under `pi.extensions`.
[`docs/tools.md`](../../docs/tools.md#the-pi-viewer) documents how it behaves.

```
extensions/sigil/index.ts   the tool, /sigil-pane, the widget, the file watch, playback, the split
tests/drive.mjs             drives the built extension for tests/test_pi_extension.py
```

The extension imports only `node:` builtins and `./logic.ts`, so it loads in any pi
with extensions. That holds whichever name pi's own packages go by, and
`build.py --check` enforces it. The tool's parameters are plain JSON Schema, not
TypeBox, for the same reason. The command is `/sigil-pane`, the same name as the
Claude Code mod's.

## Develop

```sh
./build.py --target pi && pi -e dist/pi/extensions/sigil/index.ts   # try it
python3 -m unittest tests.test_pi_extension
```

The tests drive the built extension twice. The first run uses a stand-in API and
needs a node that runs `.ts` files itself (23.6 or newer). The second, which runs
when `pi` is on the PATH, loads the extension through that pi's own loader.
