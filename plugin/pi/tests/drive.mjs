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
// expects a fake `tmux` on PATH that records its argv.

import { execFile } from 'node:child_process'
import { join } from 'node:path'

const [, , extension, file, piDir] = process.argv
for (const k of ['HERDR_ENV', 'TMUX', 'ZELLIJ', 'SIGIL_DISPLAY']) delete process.env[k]

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
      handlers: Object.fromEntries(ext.handlers),
    }
  }
  const mod = await import(extension)
  const reg = { tools: {}, commands: {}, flags: [], handlers: {}, flagValues: {} }
  mod.default({
    registerTool: t => { reg.tools[t.name] = t },
    registerCommand: (name, o) => { reg.commands[name] = { name, ...o } },
    registerFlag: (name, o) => { reg.flags.push(name); reg.flagValues[name] = o.default },
    getFlag: name => reg.flagValues[name],
    on: (event, fn) => { (reg.handlers[event] ??= []).push(fn) },
    exec: (cmd, args, o) => new Promise(done => execFile(cmd, args, { timeout: o?.timeout, maxBuffer: 1 << 26 },
      (err, stdout, stderr) => done({ stdout, stderr, code: err ? (typeof err.code === 'number' ? err.code : 1) : 0 }))),
  })
  return reg
}

const reg = await load()
const out = { errors: reg.errors ?? [], tools: Object.keys(reg.tools ?? {}), commands: Object.keys(reg.commands ?? {}),
  flags: reg.flags ?? [], steps: [] }
if (out.errors.length === 0) {
  let factory = null
  let rendered = null
  const tui = { requestRender() {} }
  const notes = []
  const ui = {
    setWidget: (key, content) => { factory = content ?? null; rendered = content ? content(tui, {}) : null },
    notify: (message, level) => notes.push([level, message]),
  }
  const ctx = { cwd: process.cwd(), hasUI: true, ui }
  const tool = reg.tools.sigil_view
  const command = reg.commands.sigil
  const pause = ms => new Promise(r => setTimeout(r, ms))
  const strip = s => s.replace(/\x1b\[[0-9;]*m/g, '')
  const lines = width => (rendered ? rendered.render(width) : null)

  async function step(name, run, width = 120) {
    const reply = await run()
    let drawn = lines(width)
    if (drawn !== null) { await pause(1500); drawn = lines(width) } // after a redraw at this width
    out.steps.push({
      name, reply: reply ?? null, widget: factory !== null,
      lines: drawn && drawn.map(strip), coloured: drawn !== null && drawn.some(l => /\x1b\[[0-9;]*38;2;/.test(l)),
      widest: drawn ? Math.max(...drawn.map(l => [...strip(l)].length)) : 0, notes: notes.splice(0),
    })
  }
  const call = input => tool.execute('call-1', input, undefined, undefined, ctx).then(r => r.content[0].text)

  process.stdout.columns = 100
  await step('narrow tool call', () => call({ file, view: 'tree' }))
  await step('command opens it', () => command.handler('', ctx))
  await step('a run at frame 0', () => call({ scenario: 'happy', frame: '0' }))
  await step('next', () => command.handler('next', ctx))
  await step('close', () => command.handler('close', ctx))
  process.stdout.columns = 160
  await step('wide tool call', () => call({ file, view: 'graph', scenario: '' }), 150)
  await step('missing file', () => call({ file: 'no-such.sigil' }), 150)
  await step('no ui', () => tool.execute('call-2', { file }, undefined, undefined, { ...ctx, hasUI: false })
    .then(r => r.content[0].text))
  for (const fn of reg.handlers.session_shutdown ?? []) await fn({}, ctx)
  process.env.TMUX = '/tmp/fake,1,0'
  await step('multiplex', () => call({ file, view: 'tree' }))
}
process.stdout.write(JSON.stringify(out) + '\n')
process.exit(0)
