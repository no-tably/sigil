import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { MockClock } from 'claude-code/testing'

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
      say: ['', '[API] returns to (Shopper)'], trail: ['', '① (Shopper) -> [API]'],
      path: [[[['path   ', 0], ['① (Shopper) ▸-> [API]', 0]]], [[['path   ', 0], ['① (Shopper) -> [API]', 0]]]],
      outcome: 'ok' } : {}),
  })
}

/** pane.py over a run of `frames` frames, answering with the window --from /
 * --count ask for (pane.py's own defaults: 0 and 120). */
function longRunOf(frames: number) {
  return (argv: readonly string[]): string => {
    if (!argv.includes('draw')) return ''
    const at = argv.indexOf('--from')
    const count = argv.includes('--count') ? Number(argv[argv.indexOf('--count') + 1]) : 120
    const last = frames - 1
    const asked = at < 0 ? 0 : argv[at + 1] === 'last' ? last - count + 1 : Number(argv[at + 1])
    const first = Math.max(0, Math.min(asked, last))
    const shown = Array.from({ length: Math.min(count, frames - first) }, (_, i) => first + i)
    return JSON.stringify({
      file: 'long.sigil', view: 'flow', width: null, styles: [['#8b7aad', null, true]],
      frames: shown.map(n => [[[`[N${n}]`, 0]]]), legend: [], summary: 'long.sigil', lint: [], scenarios: ['happy'],
      scenario: 'happy', status: shown.map(n => `sim happy · f${n}`), log: shown.map(() => ''), say: shown.map(() => ''),
      trail: shown.map(() => ''), outcome: 'ok', first, last,
    })
  }
}

type World = { runs: string[][]; writes: { path: string; text: string }[]; opens: number; focused: boolean[]; clock: MockClock }

function world(on: On, opts: { isPlaced: boolean; env?: Record<string, string>; stdout?: (argv: readonly string[]) => string;
                               delay?: (argv: readonly string[]) => number }): World {
  mock.env(on, opts.env ?? {})
  const seen: World = { runs: [], writes: [], opens: 0, focused: [], clock: mock.clock(on, { now: 10_000 }) }
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
  on('process.run', async ($, e) => {
    seen.runs.push([...e.argv])
    const ms = opts.delay?.(e.argv) ?? 0
    if (ms > 0) await seen.clock.sleep(ms)
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
    expect(String(result)).toContain('path: ① (Shopper) -> [API]')
    expect(String(result)).not.toContain('log: ')
    expect(seen.runs.at(-1)).toContain('flow')
    const back = await $.tool.call({ tool: 'mcp__sigil__view', frame: 0 })
    expect(String(back.result)).toContain('(frame 1 of 2)')
  })

  test('naming the shown file again (as written, not its real path) keeps its run', { options: { display: 'mod' } }, async ($, on) => {
    const seen = world(on, { isPlaced: true })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', scenario: 'happy' })
    const { result } = await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', view: 'tree' })
    expect(String(result)).toContain('paused at sim happy · end · ok')
    expect(seen.runs.at(-1)).toContain('--scenario')
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
    expect(await term.find({ type: 'Text', text: /shop\.sigil · flow · depth 1/ })).toBeDefined()   // flow: the default
    const desk = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    expect(await desk.find({ type: 'Text', text: '[API]' })).toBeDefined()
    expect(await desk.find({ key: 'view' })).toBeDefined()
    expect(await desk.find({ key: 'view-graph' })).toMatchObject({ props: { label: 'graph', hotkey: '1' } })
    expect(await desk.find({ key: 'view-flow' })).toMatchObject({ props: { label: '[flow]', hotkey: '3' } })
    expect(await desk.find({ key: 'view-run' })).toMatchObject({ props: { label: 'run', hotkey: '4' } })
    expect(await desk.find({ type: 'Box', props: { height: 40 } })).toBeDefined()   // docked: fills, info at the bottom
  })

  test('a wide character in the drawing is itself over its two cells: such rows are text, not a Raster', { options: { display: 'mod' } }, async ($, on) => {
    const wide = JSON.stringify({ file: 'cjk.sigil', view: 'flow', width: null, styles: [[null, null, false]],
      frames: [[[['(利\u0000用\u0000)', 0]]]], legend: [], summary: 'cjk.sigil', lint: [], scenarios: [] })
    world(on, { isPlaced: true, stdout: argv => (argv.includes('draw') ? wide : '') })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'cjk.sigil' })
    const props = { title: 'Sigil', isFocused: false, bodyColumns: 100, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const term = await $.ui.mount({ plugin: 'sigil', surface: 'terminal', component: 'Pane', props, requestId: 'sigil' })
    expect(await term.find({ type: 'Raster' })).toBeUndefined()
    expect(await term.find({ type: 'Text', text: '(利用)' })).toBeDefined()
  })

  test('a run in the pane carries its path and narration line, as the live view does', { options: { display: 'mod' } }, async ($, on) => {
    world(on, { isPlaced: true })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', view: 'flow', scenario: 'happy' })
    const props = { title: 'Sigil', isFocused: false, bodyColumns: 100, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const pane = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    expect(await pane.find({ type: 'Text', text: '› [API] returns to (Shopper)' })).toBeDefined()
    expect(await pane.find({ type: 'Text', text: '① (Shopper) -> [API]' })).toBeDefined()
  })

  test('an older draw that finishes last never replaces the newer one', { options: { display: 'mod' } }, async ($, on) => {
    const seen = world(on, { isPlaced: true, delay: argv => (argv.includes('graph') ? 200 : 0) })
    await $.session.start(START)
    const first = $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', view: 'graph' })
    await seen.clock.advance(20)
    const second = $.tool.call({ tool: 'mcp__sigil__view', view: 'tree' })
    await seen.clock.advance(300)
    const [graph, tree] = await Promise.all([first, second])
    expect(String(graph.result)).toContain('replaced this one')
    expect(String(tree.result)).toContain('Shown in the sigil pane')
    const props = { title: 'Sigil', isFocused: false, bodyColumns: 100, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const desk = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    expect(await desk.find({ type: 'Text', text: /shop\.sigil · tree · depth 1/ })).toBeDefined()
  })

  test('a redraw for a new pane size that fails is not asked again and again', { options: { display: 'mod' } }, async ($, on) => {
    let draws = 0
    const seen = world(on, { isPlaced: true,
      stdout: argv => (argv.includes('draw') ? (draws++ === 0 ? drawingOf(argv) : JSON.stringify({ error: 'boom' })) : '') })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil' })
    const props = { title: 'Sigil', isFocused: false, bodyColumns: 80, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const desk = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    await seen.clock.advance(10)
    await seen.clock.advance(2000)
    expect(draws).toBe(2)                                   // the first, then one try at 80 columns
    expect(await desk.find({ type: 'Text', text: '✖ boom' })).toBeDefined()
  })

  test("a run's speed steps as view.py's (- / + there, s / f here) and shows in the status", { options: { display: 'mod' } }, async ($, on) => {
    world(on, { isPlaced: true })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', scenario: 'happy' })
    const props = { title: 'Sigil', isFocused: true, bodyColumns: 100, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const pane = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    expect(await pane.find({ type: 'Text', text: /❚❚ 2 frames\/s · sim happy/ })).toBeDefined()
    expect(await pane.find({ key: 'faster' })).toMatchObject({ props: { hotkey: 'f' } })
    await pane.press({ key: 'faster' })
    await pane.press({ key: 'faster' })
    expect(await pane.find({ type: 'Text', text: /❚❚ 8 frames\/s/ })).toBeDefined()
    for (let i = 0; i < 9; i++) await pane.press({ key: 'slower' })
    expect(await pane.find({ type: 'Text', text: /❚❚ ¼ frame\/s/ })).toBeDefined()
  })
})

describe('a long run', () => {
  test('the pane plays every frame, drawing the run a window at a time', { options: { display: 'mod' } }, async ($, on) => {
    const seen = world(on, { isPlaced: true, stdout: longRunOf(300) })
    await $.session.start(START)
    const { result } = await $.tool.call({ tool: 'mcp__sigil__view', file: 'long.sigil', scenario: 'happy' })
    expect(String(result)).toContain('(frame 300 of 300)')               // a new run: its last frame
    expect(seen.runs.at(-1)).toContain('last')                           // drawn in the window that ends it
    const props = { title: 'Sigil', isFocused: true, bodyColumns: 100, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const pane = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    for (let i = 0; i < 4; i++) await pane.press({ key: 'faster' })    // 32 frames a second
    await pane.press({ key: 'play' })                                   // from its end: again from the start
    const shown: number[] = []
    for (let tick = 0; tick < 1000 && shown.at(-1) !== 300; tick++) {      // half a frame a look
      const status = await pane.find({ type: 'Text', text: /frame \d+\/300/ })
      const n = Number(/frame (\d+)\/300/.exec(String(status?.props?.text ?? status?.text ?? ''))?.[1])
      if (shown.at(-1) !== n) shown.push(n)
      await seen.clock.advance(16)
    }
    expect(shown[0]).toBe(1)
    expect(shown.at(-1)).toBe(300)
    expect(shown).toEqual(Array.from({ length: 300 }, (_, i) => i + 1))  // every frame, none skipped
    const windows = seen.runs.filter(r => r.includes('--from')).map(r => r[r.indexOf('--from') + 1])
    expect(windows.length).toBeGreaterThan(2)                            // asked for window by window
  })

  test('a playing run never waits at a window\'s end: the next window is drawn while it plays', { options: { display: 'mod' }, timeoutMs: 30000 }, async ($, on) => {
    // each draw takes 1.5 s of the clock: longer than the old 30 frames' notice at 32 frames a second
    const seen = world(on, { isPlaced: true, stdout: longRunOf(300), delay: argv => (argv.includes('--from') ? 1500 : 0) })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'long.sigil', scenario: 'happy', frame: 0 })
    const props = { title: 'Sigil', isFocused: true, bodyColumns: 100, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const pane = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    for (let i = 0; i < 4; i++) await pane.press({ key: 'faster' })    // 32 frames a second
    await pane.press({ key: 'play' })
    const looks = new Map<number, number>()                                  // frame → looks it stayed shown
    for (let tick = 0; tick < 2000 && !looks.has(300); tick++) {
      const status = await pane.find({ type: 'Text', text: /frame \d+\/300/ })
      const n = Number(/frame (\d+)\/300/.exec(String(status?.props?.text ?? status?.text ?? ''))?.[1])
      looks.set(n, (looks.get(n) ?? 0) + 1)
      await seen.clock.advance(16)
    }
    expect([...looks.keys()]).toEqual(Array.from({ length: 300 }, (_, i) => i + 1))   // every frame, in order
    expect(Math.max(...[...looks.entries()].filter(([n]) => n > 1).map(([, k]) => k))).toBeLessThan(5)  // none held
  })
})

describe('multiplex display', () => {
  test('unset inside tmux: a split runs view.py live, nothing opens in Claude Code', async ($, on) => {
    const seen = world(on, { isPlaced: true, env: { TMUX: '/tmp/tmux-1/default,1,0', TMPDIR: '/t' } })
    await $.session.start(START)
    const { result } = await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', view: 'tree', depth: 'all' })
    expect(String(result)).toContain('tmux split')
    expect(String(result)).toContain('lint: OK')
    expect(seen.opens).toBe(0)
    const split = seen.runs.find(argv => argv[0] === 'tmux')
    expect(split?.slice(0, 8)).toEqual(['tmux', 'split-window', '-h', '-d', '-P', '-F', '#{pane_id}', '--'])
    expect(split?.slice(10, 11)).toEqual(['follow'])
    expect(JSON.parse(seen.writes[0]?.text ?? '{}')).toEqual({ argv: [FILE, '--depth', 'all', '--tree'] })
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
    expect(JSON.parse(seen.writes[1]?.text ?? '{}')).toEqual({ argv: [FILE, '--depth', '1', '--sim', 'happy', '--frame', 'last'] })
  })

  test("the split's run starts at the frame asked, playing when asked", async ($, on) => {
    const seen = world(on, { isPlaced: true, env: { TMUX: 'x', TMPDIR: '/t' } })
    await $.session.start(START)
    const { result } = await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil', scenario: 'happy', frame: 0, play: true })
    expect(JSON.parse(seen.writes[0]?.text ?? '{}').argv.slice(-5)).toEqual(['--sim', 'happy', '--frame', '0', '--play'])
    expect(String(result)).toContain('--frame 0 --play')
    expect(String(result)).toContain('playing sim happy · start (frame 1 of 2)')
    expect(String(result)).not.toContain('starts paused')
  })
})

describe('/sigil-pane layout', () => {
  const run = { origin: { kind: 'composer' as const }, presentation: { isFullscreen: true, columns: 90 } }

  test("it says the setting, and a value writes the plugin's own /config row", { options: { layout: 'auto' } }, async ($, on) => {
    world(on, { isPlaced: true })
    const sets: { key: string; value: unknown }[] = []
    on('config.set', ($, e) => {
      sets.push({ key: e.key, value: e.value })
      return { value: e.value }
    })
    await $.session.start(START)
    expect((await $.command.run({ command: 'sigil-pane', args: 'layout', ...run })).text)
      .toBe('layout: auto · from /config sigil.layout')
    const { text } = await $.command.run({ command: 'sigil-pane', args: 'layout pan', ...run })
    expect(sets).toEqual([{ key: 'sigil.layout', value: 'pan' }])
    expect(text).toContain('layout: pan · from /config sigil.layout')
    const bad = await $.command.run({ command: 'sigil-pane', args: 'layout side', ...run })
    expect(bad.text).toBe('sigil: layout must be one of auto, wrap, pan (got "side")')
  })

  test('pane.py is told the layout; a panned drawing wider than the pane pans with h and l', { options: { display: 'mod', layout: 'pan' } }, async ($, on) => {
    const wide = (argv: readonly string[]) => (argv.includes('draw')
      ? JSON.stringify({ ...JSON.parse(drawingOf(argv)), layout: 'pan', frames: [[[['[API]' + '─'.repeat(40) + '[DB]', 0]]]] })
      : '')
    const seen = world(on, { isPlaced: true, stdout: wide })
    await $.session.start(START)
    await $.tool.call({ tool: 'mcp__sigil__view', file: 'shop.sigil' })
    expect(seen.runs[0]).toContain('--layout')
    const props = { title: 'Sigil', isFocused: true, bodyColumns: 20, placement: 'dock' as const,
      scroll: { offset: 0, bodyRows: 40 }, view: {} }
    const desk = await $.ui.mount({ plugin: 'sigil', surface: 'desktop', component: 'Pane', props, requestId: 'sigil' })
    expect(await desk.find({ type: 'Text', text: /shop\.sigil · flow · depth 1 · pan/ })).toBeDefined()
    expect(await desk.find({ type: 'Text', text: '[API]' + '─'.repeat(15) })).toBeDefined()
    expect(await desk.find({ key: 'right' })).toMatchObject({ props: { hotkey: 'l' } })
    await desk.press({ key: 'right' })
    expect(await desk.find({ type: 'Text', text: '─'.repeat(20) })).toBeDefined()
    await desk.press({ key: 'left' })
    expect(await desk.find({ type: 'Text', text: '[API]' + '─'.repeat(15) })).toBeDefined()
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
