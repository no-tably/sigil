// Drives the built pi extension through a fixed script and prints what it did
// as one JSON object, for tests/test_pi_extension.py.
//
//   node drive.mjs EXTENSION SIGIL_FILE [PI_PACKAGE_DIR]
//
// With PI_PACKAGE_DIR (an installed pi's package folder) the extension is
// loaded by pi's own loader (jiti), so the API it gets is pi's; without it,
// node imports it directly (type stripping) and gets a stand-in API whose
// exec runs the command. The UI is always a stand-in: setWidget keeps the
// factory and the script renders it at a chosen width. The multiplexer step
// expects a fake `tmux` on PATH that records its argv; the display steps
// write the settings file under $XDG_CONFIG_HOME (the test's own folder). The
// script's stdout is a pipe, so a terminal is claimed (process.stdout.isTTY)
// except for the RPC steps, where text widgets (string arrays) are recorded.
// Under the stand-in API only, `exec` can be held back or made to fail
// (`hooks`) for the redraw steps: a draw overtaken, a failing redraw at a new
// width.
//
// No step waits a fixed time: after each one the script waits until no draw
// is running (`settle`) — the stand-in's exec counts its calls, and under pi's
// API every child process is counted (node:child_process's spawn, wrapped
// before pi loads; syncBuiltinESMExports hands the wrapper to its import).

import { createRequire, syncBuiltinESMExports } from 'node:module'
import { join } from 'node:path'

const childProcess = createRequire(import.meta.url)('node:child_process')
const { execFile } = childProcess
const [, , extension, file, piDir] = process.argv
const hooks = { hold: () => null, fails: () => false, draws: 0, busy: 0, held: 0 }
const spawn = childProcess.spawn
childProcess.spawn = function counted(...args) {
  const child = spawn.apply(this, args)
  hooks.busy++
  child.once('close', () => { hooks.busy-- })
  return child
}
syncBuiltinESMExports()
for (const k of ['HERDR_ENV', 'TMUX', 'ZELLIJ', 'SIGIL_DISPLAY', 'SIGIL_LAYOUT']) delete process.env[k]

async function load() {
  if (piDir) {
    const loader = await import(join(piDir, 'dist', 'core', 'extensions', 'loader.js'))
    const got = await loader.loadExtensions([extension], process.cwd())
    if (got.errors.length > 0) return { errors: got.errors }
    const ext = got.extensions[0]
    return {
      tools: Object.fromEntries([...ext.tools].map(([k, v]) => [k, v.definition])),
      commands: Object.fromEntries(ext.commands),
      flags: [...ext.flags.keys()],
      flagDefaults: Object.fromEntries([...ext.flags].map(([k, v]) => [k, v.default ?? null])),
      handlers: Object.fromEntries(ext.handlers),
      setFlag: (name, value) => got.runtime.flagValues.set(name, value),
    }
  }
  const mod = await import(extension)
  const reg = { tools: {}, commands: {}, flags: [], flagDefaults: {}, handlers: {}, flagValues: {} }
  reg.setFlag = (name, value) => { reg.flagValues[name] = value }
  mod.default({
    registerTool: t => { reg.tools[t.name] = t },
    registerCommand: (name, o) => { reg.commands[name] = { name, ...o } },
    registerFlag: (name, o) => {
      reg.flags.push(name)
      reg.flagDefaults[name] = o.default ?? null
      if (o.default !== undefined) reg.flagValues[name] = o.default
    },
    getFlag: name => reg.flagValues[name],
    on: (event, fn) => { (reg.handlers[event] ??= []).push(fn) },
    exec: async (cmd, args, o) => {
      if (args.includes('draw')) hooks.draws++
      if (hooks.fails(args)) return { stdout: JSON.stringify({ error: 'boom' }), stderr: '', code: 0 }
      hooks.busy++
      try {
        const gate = hooks.hold(args)
        if (gate !== null) {
          hooks.held++
          await gate
        }
        return await new Promise(done => execFile(cmd, args, { timeout: o?.timeout, maxBuffer: 1 << 26 },
          (err, stdout, stderr) => done({ stdout, stderr, code: err ? (typeof err.code === 'number' ? err.code : 1) : 0 })))
      } finally {
        hooks.busy--
      }
    },
  })
  return reg
}

const reg = await load()
const out = { errors: reg.errors ?? [], tools: Object.keys(reg.tools ?? {}), commands: Object.keys(reg.commands ?? {}),
  flags: reg.flags ?? [], flagDefaults: reg.flagDefaults ?? {}, steps: [] }
if (out.errors.length === 0) {
  let factory = null
  let rendered = null
  const tui = { requestRender() {} }
  const notes = []
  const texts = []
  const ui = {
    setWidget: (key, content) => {
      if (Array.isArray(content)) return texts.push(content)
      factory = content ?? null
      rendered = content ? content(tui, {}) : null
    },
    notify: (message, level) => notes.push([level, message]),
  }
  const ctx = { cwd: process.cwd(), hasUI: true, ui }
  const tool = reg.tools.sigil_view
  const command = reg.commands['sigil-pane']
  const pause = ms => new Promise(r => setTimeout(r, ms))
  /** Waits until `ready()` holds over a few turns of the event loop (a redraw a
   * render asked for starts on a timer of 0), whatever the machine's speed. */
  async function until(ready, what) {
    for (let idle = 0, turns = 0; idle < 3; turns++) {
      if (turns > 60000) throw new Error(`drive.mjs: still waiting for ${what}`)
      await pause(idle === 0 ? 5 : 0)
      idle = ready() ? idle + 1 : 0
    }
  }
  const settle = () => until(() => hooks.busy === 0, 'the draws to finish')
  const strip = s => s.replace(/\x1b\[[0-9;]*m/g, '')
  const lines = width => (rendered ? rendered.render(width) : null)

  async function step(name, run, width = 120) {
    const reply = await run()
    let drawn = lines(width)
    if (drawn !== null) { await settle(); drawn = lines(width) } // after a redraw at this width
    out.steps.push({
      name, reply: reply ?? null, widget: factory !== null,
      lines: drawn && drawn.map(strip), coloured: drawn !== null && drawn.some(l => /\x1b\[[0-9;]*38;2;/.test(l)),
      widest: drawn ? Math.max(...drawn.map(l => [...strip(l)].length)) : 0, notes: notes.splice(0),
      texts: texts.splice(0),
    })
  }
  const call = input => tool.execute('call-1', input, undefined, undefined, ctx).then(r => r.content[0].text)

  process.stdout.columns = 100
  process.stdout.isTTY = true
  await step('narrow tool call', () => call({ file, view: 'tree' }))
  await step('command opens it', () => command.handler('', ctx))
  await step('a run at frame 0', () => call({ scenario: 'happy', frame: '0' }))
  await step('next', () => command.handler('next', ctx))
  await step('faster', () => command.handler('+', ctx))
  await step('slower twice', async () => { await command.handler('-', ctx); await command.handler('-', ctx) })
  await step('the file named again', () => call({ file, view: 'tree' }))
  await step('close', () => command.handler('close', ctx))
  // RPC mode: stdout is pi's JSON channel, no terminal; widgets go as text
  process.stdout.isTTY = false
  await step('rpc tool call', () => call({ file, view: 'flow', scenario: 'happy', frame: '0' }))
  await step('rpc next', () => command.handler('next', ctx))
  await step('rpc reopened, unchanged', () => command.handler('', ctx))
  await step('rpc close', () => command.handler('close', ctx))
  process.stdout.isTTY = true
  process.stdout.columns = 160
  await step('wide tool call', () => call({ file, view: 'graph', scenario: '' }), 150)
  await step('missing file', () => call({ file: 'no-such.sigil' }), 150)
  await step('no ui', () => tool.execute('call-2', { file }, undefined, undefined, { ...ctx, hasUI: false })
    .then(r => r.content[0].text))
  for (const fn of reg.handlers.session_shutdown ?? []) await fn({}, ctx)
  process.env.TMUX = '/tmp/fake,1,0'
  await step('multiplex', () => call({ file, view: 'tree' }))
  await step('multiplex run', () => call({ scenario: 'happy', frame: '2', play: true }))
  // /sigil-pane display: the flag, SIGIL_DISPLAY, the settings file, auto
  await step('display default', () => command.handler('display', ctx))
  await step('display set mod', () => command.handler('display mod', ctx))
  await step('display from the file', () => command.handler('display', ctx))
  await step('a call after the file says mod', () => call({ file, view: 'graph' }), 150)
  process.env.SIGIL_DISPLAY = 'multiplex'
  await step('display from the env', () => command.handler(' display ', ctx))
  reg.setFlag('sigil-display', 'mod')
  await step('display from the flag', () => command.handler('display', ctx))
  await step('display set under the flag', () => command.handler('display auto', ctx))
  await step('display bad', () => command.handler('display side', ctx))
  // /sigil-pane layout: said, saved to the same file; a panned drawing pans
  await step('layout default', () => command.handler('layout', ctx), 30)
  await step('layout set pan', () => command.handler('layout pan', ctx), 30)
  await step('pan right', () => command.handler('right', ctx), 30)
  await step('layout bad', () => command.handler('layout side', ctx), 30)
  if (!piDir) {
    // the graph's draw is held until the tree's has finished: it finishes last
    let release = () => {}
    const gate = new Promise(r => { release = r })
    hooks.hold = args => (args.includes('graph') ? gate : null)
    hooks.held = 0
    await step('a slow draw overtaken', async () => {
      const graph = call({ file, view: 'graph' })
      await until(() => hooks.held > 0, "the graph's draw")
      const tree = await call({ view: 'tree' })
      release()
      return [await graph, tree]
    }, 30)
    hooks.hold = () => null
    hooks.fails = args => args.includes('draw')
    hooks.draws = 0
    await step('a failing redraw at a new width', async () => {
      for (let i = 0; i < 20; i++) { lines(90); await settle() }
      return String(hooks.draws)
    }, 90)
    hooks.fails = () => false
  }
  for (const fn of reg.handlers.session_shutdown ?? []) await fn({}, ctx)
}
process.stdout.write(JSON.stringify(out) + '\n')
process.exit(0)
