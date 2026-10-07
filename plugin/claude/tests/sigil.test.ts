import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

// The world beneath the mod: one file, pane.py answering with a two-frame run
// (or a still drawing), and a pane the test seats or leaves waiting.

const FILE = '/w/shop.sigil'

function drawingOf(argv: readonly string[]): string {
  const isRun = argv.includes('--scenario')
  const row = [['[API]', 0]]
  return JSON.stringify({
    file: 'shop.sigil', view: argv[argv.indexOf('--view') + 1], width: null,
    styles: [['#8b7aad', null, true]], frames: isRun ? [[row], [row, row]] : [[row]], legend: [],
    summary: 'shop.sigil: 1 nodes, 0 edges · lint: OK', lint: [], scenarios: ['happy', 'API.charge:fails'],
    ...(isRun ? { scenario: 'happy', status: ['sim happy · start', 'sim happy · end · ok'], log: ['', 'done: ok'],
      say: ['', '[API] returns to (Shopper)'], trail: ['', '(Shopper) -> [API]'], outcome: 'ok' } : {}),
  })
}

type World = { runs: string[][]; writes: { path: string; text: string }[]; opens: number; focused: boolean[] }

function world(on: On, opts: { isPlaced: boolean; env?: Record<string, string>; stdout?: (argv: readonly string[]) => string }): World {
  const seen: World = { runs: [], writes: [], opens: 0, focused: [] }
  mock.env(on, opts.env ?? {})
  mock.clock(on, { now: 10_000 })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('tool.register', ($, e) => ({ value: { tool: `mcp__sigil__${e.name}` } }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('fs.exists', () => ({ value: true }))
  on('fs.stat', ($, e) => ({ value: e.path.endsWith('.alive')
    ? { kind: 'file', size: 4, mtimeMs: 9_000, isLink: false }
    : { kind: 'file', size: 10, mtimeMs: 1, isLink: false, realPath: FILE } }))
  on('fs.write', ($, e) => {
    seen.writes.push({ path: e.path, text: e.text })
    return { value: undefined }
  })
  on('process.run', ($, e) => {
    seen.runs.push([...e.argv])
    const stdout = opts.stdout?.(e.argv) ?? (e.argv.includes('draw') ? drawingOf(e.argv) : e.argv[0] === 'tmux' ? '%7\n' : '')
    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.open', ($, e) => {
    seen.opens++
    seen.focused.push(e.focus === true)
    return { value: opts.isPlaced ? { isPlaced: true } : { isPlaced: false, reason: 'unasked panes need 144 columns; the terminal is 120' } }
  })
  return seen
}

const START = { cwd: '/w', surface: 'terminal' as const, isInteractive: true }

describe('mod display', () => {
  test('the tool draws in the pane and answers with the summary', { options: { display: 'mod' } }, async ($, on) => {
    const seen = world(on, { isPlaced: true, env: { TMUX: 'x' } })
    await $.session.start(START)
    const { result } = await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', view: 'tree' })
    expect(String(result)).toContain('Shown in the sigil pane')
    expect(String(result)).toContain('lint: OK')
    const draw = seen.runs.find(argv => argv.includes('draw'))
    expect(draw?.slice(2, 6)).toEqual(['draw', FILE, '--view', 'tree'])
    expect(seen.opens).toBe(1)
  })

  test('an unasked pane on a narrow terminal waits, and the reply names /sigil', { options: { display: 'mod' } }, async ($, on) => {
    world(on, { isPlaced: false })
    await $.session.start(START)
    const { result } = await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil' })
    expect(String(result)).toContain('waiting')
    expect(String(result)).toContain('144')
    expect(String(result)).toContain('/sigil-pane')
  })

  test('a run is shown at its last frame unless asked; flow passes through', { options: { display: 'mod' } }, async ($, on) => {
    const seen = world(on, { isPlaced: true })
    await $.session.start(START)
    const { result } = await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', view: 'flow', scenario: 'happy' })
    expect(String(result)).toContain('paused at sim happy · end · ok (frame 2 of 2)')
    expect(String(result)).toContain('outcome of the whole run: ok')
    expect(String(result)).toContain('now: [API] returns to (Shopper)')
    expect(String(result)).toContain('trail: (Shopper) -> [API]')
    expect(String(result)).not.toContain('log: ')
    expect(seen.runs.at(-1)).toContain('flow')
    const back = await $.tool.call({ tool: 'mcp__sigil__view', frame: 0 })
    expect(String(back.result)).toContain('(frame 1 of 2)')
  })

  test('/sigil-pane shows a file, and with no words reopens the pane', { options: { display: 'mod' } }, async ($, on) => {
    const seen = world(on, { isPlaced: true })
    await $.session.start(START)
    const run = { origin: { kind: 'composer' as const }, presentation: { isFullscreen: true, columns: 90 } }
    const shown = await $.command.run({ command: 'sigil-pane', args: 'shop.sigil tree depth all', ...run })
    expect(shown.text).toContain('Shown in the sigil pane')
    expect(seen.runs.at(-1)?.slice(4, 8)).toEqual(['--view', 'tree', '--depth', '99'])
    const again = await $.command.run({ command: 'sigil-pane', args: '', ...run })
    expect(again.text).toBe('Sigil pane opened.')
    expect(seen.opens).toBe(2)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil' })
    expect(seen.focused).toEqual([true, true, false])   // the person's opens take the keys, the agent's never
  })

  test('the pane draws theme-coloured cells on the terminal, text runs elsewhere', { options: { display: 'mod' } }, async ($, on) => {
    world(on, { isPlaced: true })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil' })
    const props = { title: 'Sigil', isFocused: false, bodyColumns: 100, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const term = await $.ui.mount({ plugin: 'sigil', surface: 'terminal', component: 'Pane', props, requestId: 'sigil' })
    const raster = await term.find({ type: 'Raster' })
    expect(raster?.props.columns).toBe(5)
    expect(await term.find({ type: 'Text', text: /shop\.sigil · graph · depth 1/ })).toBeDefined()
    const desk = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    expect(await desk.find({ type: 'Text', text: '[API]' })).toBeDefined()
    expect(await desk.find({ key: 'view' })).toBeDefined()
  })

  test('a run in the pane carries its trail and narration line', { options: { display: 'mod' } }, async ($, on) => {
    world(on, { isPlaced: true })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', view: 'flow', scenario: 'happy' })
    const props = { title: 'Sigil', isFocused: false, bodyColumns: 100, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const pane = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    expect(await pane.find({ type: 'Text', text: '› [API] returns to (Shopper)' })).toBeDefined()
    expect(await pane.find({ type: 'Text', text: 'trail  (Shopper) -> [API]' })).toBeDefined()
  })
})

describe('multiplex display', () => {
  test('unset inside tmux: a split runs view.py live, nothing opens in Claude Code', async ($, on) => {
    const seen = world(on, { isPlaced: true, env: { TMUX: '/tmp/tmux-1/default,1,0', TMPDIR: '/t' } })
    await $.session.start(START)
    const { result } = await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', view: 'flow', depth: 'all' })
    expect(String(result)).toContain('tmux split')
    expect(String(result)).toContain('lint: OK')
    expect(seen.opens).toBe(0)
    const split = seen.runs.find(argv => argv[0] === 'tmux')
    expect(split?.slice(0, 8)).toEqual(['tmux', 'split-window', '-h', '-d', '-P', '-F', '#{pane_id}', '--'])
    expect(split?.slice(10, 11)).toEqual(['follow'])
    expect(JSON.parse(seen.writes[0]?.text ?? '{}')).toEqual({ argv: [FILE, '--depth', 'all', '--flow'] })
    expect(seen.writes[0]?.path.startsWith('/t/sigil-view-')).toBe(true)
  })

  test('a split still up is driven through its control file', async ($, on) => {
    const seen = world(on, { isPlaced: true, env: { HERDR_ENV: '1', HERDR_PANE_ID: 'w1:p1' },
      stdout: argv => (argv[2] === 'split' ? '{"result":{"pane":{"pane_id":"w1:p2"}}}' : '') })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil' })
    const herdr = () => seen.runs.filter(argv => argv[0] === 'herdr')
    expect(herdr().map(argv => argv.slice(0, 4))).toEqual([
      ['herdr', 'pane', 'split', 'w1:p1'], ['herdr', 'pane', 'wait-output', 'w1:p2'], ['herdr', 'pane', 'run', 'w1:p2']])
    const { result } = await $.tool.call({ tool: 'mcp__sigil__view', scenario: 'happy' })
    expect(String(result)).toContain('Shown in the herdr split')
    expect(herdr().length).toBe(3)   // split, wait, run: a reused split adds none
    expect(JSON.parse(seen.writes[1]?.text ?? '{}')).toEqual({ argv: [FILE, '--depth', '1', '--sim', 'happy'] })
  })
})

describe('/sigil-pane display', () => {
  const run = { origin: { kind: 'composer' as const }, presentation: { isFullscreen: true, columns: 90 } }

  test('with no value it says the setting, its row and what auto is here', { options: { display: 'auto' } }, async ($, on) => {
    world(on, { isPlaced: true, env: { HERDR_ENV: '1' } })
    await $.session.start(START)
    const { text } = await $.command.run({ command: 'sigil-pane', args: 'display', ...run })
    expect(text).toBe('display: auto → multiplex (herdr detected) · from /config sigil.display')
  })

  test('a value set outright still says what auto would be', { options: { display: 'mod' } }, async ($, on) => {
    world(on, { isPlaced: true })
    await $.session.start(START)
    const { text } = await $.command.run({ command: 'sigil-pane', args: 'display', ...run })
    expect(text).toBe('display: mod · from /config sigil.display · auto here → mod (no multiplexer detected)')
  })

  test("a value writes the plugin's own /config row", { options: { display: 'auto' } }, async ($, on) => {
    const seen = world(on, { isPlaced: true, env: { TMUX: 'x' } })
    const sets: { key: string; value: unknown }[] = []
    on('config.set', ($, e) => {
      sets.push({ key: e.key, value: e.value })
      return { value: e.value }
    })
    await $.session.start(START)
    const { text } = await $.command.run({ command: 'sigil-pane', args: 'display mod', ...run })
    expect(sets).toEqual([{ key: 'sigil.display', value: 'mod' }])
    expect(text).toContain('display: mod · from /config sigil.display · auto here → multiplex (tmux detected)')
    expect(text).toContain('The next view draws in the sigil pane.')
    expect(seen.runs).toEqual([])   // nothing drawn, no file looked for
  })

  test('a refused change and a bad value are said, nothing written', { options: { display: 'auto' } }, async ($, on) => {
    world(on, { isPlaced: true })
    const sets: string[] = []
    on('config.set', ($, e) => {
      sets.push(String(e.value))
      return { deny: 'your organization sets it' }
    })
    await $.session.start(START)
    const denied = await $.command.run({ command: 'sigil-pane', args: 'display multiplex', ...run })
    expect(denied.text).toBe('sigil: display stays auto: your organization sets it')
    const bad = await $.command.run({ command: 'sigil-pane', args: 'display side', ...run })
    expect(bad.text).toBe('sigil: display must be one of mod, multiplex, auto (got "side")')
    const same = await $.command.run({ command: 'sigil-pane', args: 'display auto', ...run })
    expect(same.text).toContain('(unchanged)')
    expect(sets).toEqual(['multiplex'])
  })
})
