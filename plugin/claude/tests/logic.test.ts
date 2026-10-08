import { describe, expect, test } from 'claude-code/testing'

import {
  WINDOW, WINDOW_AHEAD, WINDOW_BACK, askedFrame, colourOf, cropRows, displayReport, drawArgv, drawnFrame, frameIndex,
  herdrPaneOf, herdrReadyArgv, holds, layoutOf, layoutReport, nextView, nextSpeed, panTo, parseCommandArgs, parseDisplayArgs,
  parseDrawing, parseLayoutArgs, parseRequest, pickDisplay, pickLayout, playbackFor, playTick, rasterCells, replyText,
  resolveDisplay, runLines, shellQuote, slices, slot, speedText, splitArgv, splitStart, statusLine, viewArgv, windowFor,
  windowStart,
} from '../hooks/logic'
import type { Drawing } from '../types'

describe('display', () => {
  test('unset: mod outside a multiplexer, multiplex inside one', () => {
    expect(resolveDisplay(undefined, {})).toBe('mod')
    expect(resolveDisplay('auto', {})).toBe('mod')
    expect(resolveDisplay(undefined, { herdr: '1' })).toBe('multiplex')
    expect(resolveDisplay('auto', { tmux: '/tmp/tmux-1/default,1,0' })).toBe('multiplex')
    expect(resolveDisplay(undefined, { zellij: '0' })).toBe('multiplex')
  })
  test('set: the setting wins over what is detected', () => {
    expect(resolveDisplay('mod', { tmux: 'x' })).toBe('mod')
    expect(resolveDisplay('multiplex', {})).toBe('multiplex')
  })
})

describe('the display command', () => {
  test('display and its value are words of their own, never a file', () => {
    expect(parseDisplayArgs('display')).toEqual({})
    expect(parseDisplayArgs(' display  multiplex ')).toEqual({ choice: 'multiplex' })
    expect(parseDisplayArgs('display side')).toEqual({ error: 'display must be one of mod, multiplex, auto (got "side")' })
    expect(parseDisplayArgs('display mod tree')).toEqual({ error: 'display takes one value: mod, multiplex, auto' })
    expect(parseDisplayArgs('shop.sigil tree')).toBeNull()
    expect(parseDisplayArgs('')).toBeNull()
    expect(parseCommandArgs('display')).toEqual({ display: '' })
    expect(parseCommandArgs('display auto')).toEqual({ display: 'auto' })
    expect(parseCommandArgs('a.sigil display tree')).toEqual({ file: 'a.sigil', display: '', view: 'tree' })
  })
  test('the first source holding a value wins; the reply says it and what auto is here', () => {
    expect(pickDisplay([['--sigil-display', undefined], ['SIGIL_DISPLAY', 'mod'], ['file', 'multiplex']], 'default'))
      .toEqual({ choice: 'mod', source: 'SIGIL_DISPLAY' })
    expect(pickDisplay([['flag', ''], ['env', undefined]], 'default')).toEqual({ choice: 'auto', source: 'default' })
    expect(pickDisplay([['flag', 'sideways']], 'default')).toEqual({ choice: 'auto', source: 'flag' })
    expect(displayReport('auto', 'X', { herdr: '1' })).toBe('display: auto → multiplex (herdr detected) · from X')
    expect(displayReport('mod', 'X', { zellij: '0' })).toBe('display: mod · from X · auto here → multiplex (zellij detected)')
    expect(displayReport('auto', 'X', {})).toBe('display: auto → mod (no multiplexer detected) · from X')
  })
})

describe('the layout command', () => {
  test('layout and its value are words of their own, never a file', () => {
    expect(parseLayoutArgs('layout')).toEqual({})
    expect(parseLayoutArgs(' layout  pan ')).toEqual({ choice: 'pan' })
    expect(parseLayoutArgs('layout side')).toEqual({ error: 'layout must be one of auto, wrap, pan (got "side")' })
    expect(parseLayoutArgs('layout pan tree')).toEqual({ error: 'layout takes one value: auto, wrap, pan' })
    expect(parseLayoutArgs('display mod')).toBeNull()
    expect(parseCommandArgs('a.sigil layout tree')).toEqual({ file: 'a.sigil', layout: '', view: 'tree' })
    expect(parseCommandArgs('layout wrap')).toEqual({ layout: 'wrap' })
  })
  test('anything but a layout is auto; the reply says what auto drew', () => {
    expect(layoutOf('pan')).toBe('pan')
    expect(layoutOf(undefined)).toBe('auto')
    expect(layoutOf('sideways')).toBe('auto')
    expect(pickLayout([['--sigil-layout', undefined], ['SIGIL_LAYOUT', 'wrap']], 'default'))
      .toEqual({ choice: 'wrap', source: 'SIGIL_LAYOUT' })
    expect(pickLayout([], 'default')).toEqual({ choice: 'auto', source: 'default' })
    expect(layoutReport('auto', 'X', 'pan')).toBe('layout: auto → pan (the drawing shown) · from X')
    expect(layoutReport('auto', 'X')).toBe('layout: auto · from X')
    expect(layoutReport('wrap', 'X', 'wrap')).toBe('layout: wrap · from X')
  })
  test('pane.py and view.py are told the layout; auto is their own default', () => {
    const req = { file: '/d/a.sigil', view: 'flow' as const, depth: 1 }
    expect(drawArgv('p.py', req, 80, { layout: 'pan' }).slice(-2)).toEqual(['--layout', 'pan'])
    expect(drawArgv('p.py', req, 80, { layout: 'auto', height: 30 }).slice(-2)).toEqual(['--height', '30'])
    expect(drawArgv('p.py', req, 80)).not.toContain('--layout')
    expect(viewArgv(req, 'wrap')).toEqual(['/d/a.sigil', '--depth', '1', '--layout', 'wrap'])
    expect(viewArgv(req, 'auto')).toEqual(['/d/a.sigil', '--depth', '1'])
  })
  test('a panned drawing is cropped to its window, kept within the drawing', () => {
    const rows = [[['abc', 0], ['defg', 1]], [['xy', 2]]] as [string, number][][]
    expect(cropRows(rows, 2, 3)).toEqual([[['c', 0], ['de', 1]], []])
    expect(cropRows(rows, 0, 10)).toEqual(rows)
    expect(panTo(0, 5, 7, 4)).toBe(3)
    expect(panTo(3, -5, 7, 4)).toBe(0)
    expect(panTo(0, 5, 3, 4)).toBe(0)
  })
})

describe('requests', () => {
  test('a file is needed the first time; fields left out keep their value', () => {
    expect(parseRequest({}, null)).toEqual({ error: 'name the Sigil file to show (file)' })
    const first = parseRequest({ file: 'a.sigil', view: 'tree', depth: 'all', scenario: 'happy' }, null)
    expect(first).toEqual({ request: { file: 'a.sigil', view: 'tree', depth: 99, scenario: 'happy' } })
    if ('error' in first) throw new Error('unexpected')
    const again = parseRequest({ frame: 3, play: true }, first.request)
    expect(again).toEqual({ request: first.request, frame: 3, play: true })
    expect(parseRequest({ scenario: '' }, first.request)).toEqual({ request: { file: 'a.sigil', view: 'tree', depth: 99 } })
    expect(parseRequest({ frame: 'last' }, first.request)).toEqual({ request: first.request, frame: -1 })
    expect(parseRequest({ frame: 150 }, first.request)).toMatchObject({ frame: 150 })      // a frame is no depth: never capped at 99
    expect(parseRequest(parseCommandArgs('frame 840'), first.request)).toMatchObject({ frame: 840 })
  })
  test('another file drops the run; bad values are named', () => {
    const shown = { file: 'a.sigil', view: 'graph' as const, depth: 1, scenario: 'happy' }
    expect(parseRequest({ file: 'b.sigil' }, shown)).toEqual({ request: { file: 'b.sigil', view: 'graph', depth: 1 } })
    expect(parseRequest({ file: 'a.sigil' }, null)).toEqual({ request: { file: 'a.sigil', view: 'flow', depth: 1 } })
    expect(parseRequest({ file: 'a.sigil', view: 'side' }, null)).toEqual({ error: 'view must be one of graph, tree, flow, run' })
    expect(parseRequest({ file: 'a.sigil', depth: -1 }, null)).toEqual({ error: 'depth must be a whole number or "all"' })
  })
  test('/sigil words', () => {
    expect(parseCommandArgs('')).toEqual({})
    expect(parseCommandArgs('shop.sigil flow depth all sim API.charge:fails frame 2 play'))
      .toEqual({ file: 'shop.sigil', view: 'flow', depth: 'all', scenario: 'API.charge:fails', frame: '2', play: true })
  })
})

describe('commands', () => {
  test("view.py's live flags, a view other than flow (the default) passed through", () => {
    expect(viewArgv({ file: '/d/a.sigil', view: 'graph', depth: 99, scenario: 'happy' }))
      .toEqual(['/d/a.sigil', '--depth', 'all', '--graph', '--sim', 'happy'])
    expect(viewArgv({ file: '/d/a.sigil', view: 'flow', depth: 0 })).toEqual(['/d/a.sigil', '--depth', '0'])
  })
  test("the split starts a run as the pane shows a new one: the frame asked, else the last, the first when it plays", () => {
    const req = { file: '/d/a.sigil', view: 'graph' as const, depth: 1, scenario: 'happy' }
    expect(splitStart({ request: req })).toEqual({ frame: -1, play: false })
    expect(splitStart({ request: req, play: true })).toEqual({ frame: 0, play: true })
    expect(splitStart({ request: req, frame: 4, play: false })).toEqual({ frame: 4, play: false })
    expect(viewArgv(req, 'auto', { frame: -1, play: false }).slice(-4)).toEqual(['--sim', 'happy', '--frame', 'last'])
    expect(viewArgv(req, 'auto', { frame: 3, play: true }).slice(-3)).toEqual(['--frame', '3', '--play'])
    expect(viewArgv({ ...req, scenario: undefined }, 'auto', { frame: 3, play: true })).toEqual(['/d/a.sigil', '--depth', '1', '--graph'])
  })
  test('a split per multiplexer', () => {
    const follow = ['python3', '/p/pane.py', 'follow', '/tmp/c.json']
    expect(splitArgv('tmux', follow)).toEqual(['tmux', 'split-window', '-h', '-d', '-P', '-F', '#{pane_id}', '--', ...follow])
    expect(splitArgv('zellij', follow).slice(0, 3)).toEqual(['zellij', 'run', '--direction'])
    expect(splitArgv('herdr', follow, 'w6:p1')).toEqual(['herdr', 'pane', 'split', 'w6:p1', '--direction', 'right', '--no-focus'])
    expect(herdrPaneOf('{"result":{"pane":{"pane_id":"w6:p2"}}}')).toBe('w6:p2')
    expect(herdrPaneOf('nope')).toBeUndefined()
    expect(herdrReadyArgv('w6:p2')).toEqual(['herdr', 'pane', 'wait-output', 'w6:p2', '--regex', '\\S', '--source', 'visible'])
    expect(shellQuote(['python3', "/a b/it's.py"])).toBe(`python3 '/a b/it'\\''s.py'`)
  })
})

describe('cells', () => {
  test('a run in its colour, padded with the default', () => {
    expect(colourOf('#8b7aad')).toBe(0x8b7aad)
    expect(colourOf('#fff')).toBe(0xffffff)
    expect(colourOf(null)).toBe(0x01000000)
    expect(rasterCells([[['A', 0]]], [['#8b7aad', null, false]], 2)).toBe('QQAAAK16iwAAAAABIAAAAAAAAAEAAAAB')
  })
  test('slices and frames', () => {
    expect(slices([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]])
    const drawing = { frames: [[], [], []], styles: [] } as unknown as Drawing
    expect(frameIndex(drawing, { at: 9, isPlaying: false })).toBe(2)
    expect(nextView('graph')).toBe('tree')
    expect(nextView('tree')).toBe('flow')
    expect(nextView('flow')).toBe('run')
    expect(nextView('run')).toBe('graph')
    expect(parseDrawing('{"error":"x: no such file"}')).toEqual({ error: 'x: no such file' })
    expect(parseDrawing('garbage')).toEqual({ error: 'pane.py printed no drawing' })
  })
  test("speeds: view.py's, clamped, written as its status bar writes them", () => {
    expect([0, 1, 2, 3, 7].map(speedText)).toEqual(['¼ frame/s', '½ frame/s', '1 frame/s', '2 frames/s', '32 frames/s'])
    expect(nextSpeed(3, 1)).toBe(4)
    expect(nextSpeed(7, 1)).toBe(7)
    expect(nextSpeed(0, -1)).toBe(0)
    const run = { file: 'a.sigil', view: 'flow', frames: [[], []], status: ['sim happy · start', 'sim happy · end · ok'] } as unknown as Drawing
    const req = { file: '/d/a.sigil', view: 'flow' as const, depth: 1 }
    expect(statusLine(run, req, 0, true)).toBe('a.sigil · flow · depth 1 · ▶ 2 frames/s · sim happy · start · frame 1/2')
    expect(statusLine(run, req, 1, false, 0)).toBe('a.sigil · flow · depth 1 · ❚❚ ¼ frame/s · sim happy · end · ok · frame 2/2')
  })
  test("a run drawn a window at a time: its frames are the run's own, asked by them, numbered by them", () => {
    const run = { file: 'a.sigil', view: 'flow', frames: [[], [], [], []], status: ['a', 'b', 'c', 'd'],
      first: 280, last: 838, summary: '', lint: [], scenarios: [] } as unknown as Drawing
    expect([0, 279, 280, 420, 838, 900, -1].map(f => drawnFrame(run, f))).toEqual([0, 279, 280, 420, 838, 838, 838])
    expect([279, 280, 283, 284].map(f => holds(run, f))).toEqual([false, true, true, false])
    expect([0, 281, 900].map(f => slot(run, f))).toEqual([0, 1, 3])
    const req = { file: '/d/a.sigil', view: 'flow' as const, depth: 1 }
    expect(statusLine(run, req, 281, false)).toMatch(/· b · frame 282\/839$/)
    expect(replyText(run, 281, false, 'here')).toContain('paused at b (frame 282 of 839)')
    expect(frameIndex(run, { at: 5000, isPlaying: false })).toBe(838)
    const whole = { frames: [[], []] } as unknown as Drawing                          // a still
    expect([0, 1, 5, -1].map(f => drawnFrame(whole, f))).toEqual([0, 1, 1, 1])
  })
  test('which window to draw: the one holding the frame, the next one ahead of a playing run', () => {
    expect([-1, 0, 3, 100].map(windowStart)).toEqual([-1, 0, 0, 100 - WINDOW_BACK])
    const frames = Array.from({ length: WINDOW }, () => [])
    const run = { frames, status: frames.map(() => 's'), first: 0, last: 1000 } as unknown as Drawing
    expect(windowFor(run, 10, false)).toBeNull()
    expect(windowFor(run, WINDOW - 1, false)).toBeNull()                       // held; paused, no need
    expect(windowFor(run, WINDOW - WINDOW_AHEAD + 1, true)).toBe(WINDOW - WINDOW_AHEAD + 1 - WINDOW_BACK)
    expect(windowFor(run, 500, false)).toBe(500 - WINDOW_BACK)                 // a step far off
    const end = { frames, status: frames.map(() => 's'), first: 1001 - WINDOW, last: 1000 } as unknown as Drawing
    expect(windowFor(end, 999, true)).toBeNull()                               // the window ends the run
    expect(windowFor({ frames: [[]] } as unknown as Drawing, 5, true)).toBeNull()  // a still
    expect(drawArgv('p.py', { file: 'a', view: 'flow', depth: 1, scenario: 'happy' }, 80, { from: 92 }).slice(-4))
      .toEqual(['--from', '92', '--count', String(WINDOW)])
    expect(drawArgv('p.py', { file: 'a', view: 'flow', depth: 1, scenario: 'happy' }, 80, { from: -1 }))
      .toContain('last')
    expect(drawArgv('p.py', { file: 'a', view: 'flow', depth: 1 }, 80, { from: 92 })).not.toContain('--from')
  })
  test('a playing run plays every frame, waits at its window\'s end, stops at the last', () => {
    const run = { frames: [[], [], []], status: ['a', 'b', 'c'], first: 10, last: 20 } as unknown as Drawing
    expect(playTick(run, { at: 10, isPlaying: true })).toEqual({ at: 11, isPlaying: true })
    expect(playTick(run, { at: 12, isPlaying: true })).toEqual({ at: 12, isPlaying: true }) // 13 not drawn yet
    const end = { frames: [[], []], status: ['a', 'b'], first: 19, last: 20 } as unknown as Drawing
    expect(playTick(end, { at: 19, isPlaying: true })).toEqual({ at: 20, isPlaying: false })
  })
  test('where a request starts its run, before and after it is drawn', () => {
    const req = { file: 'a', view: 'flow' as const, depth: 1, scenario: 'happy' }
    const before = { at: 50, isPlaying: false }
    expect(askedFrame({ request: req }, before, true)).toBe(-1)                  // a new run: its last
    expect(askedFrame({ request: req, play: true }, before, true)).toBe(0)       // played: its first
    expect(askedFrame({ request: req }, before, false)).toBe(50)                 // the same run: where it was
    expect(askedFrame({ request: req, frame: 7 }, before, false)).toBe(7)
    const run = { frames: [[], []], status: ['a', 'b'], first: 499, last: 500 } as unknown as Drawing
    expect(playbackFor({ request: req }, run, before, true)).toEqual({ at: 500, isPlaying: false })
    expect(playbackFor({ request: req, play: true }, run, before, false)).toEqual({ at: 50, isPlaying: true })
    expect(playbackFor({ request: req, frame: 900 }, run, before, false)).toEqual({ at: 500, isPlaying: false })
  })
  test("a run's path and narration line; the log line from an older pane.py", () => {
    const row = [['path   ', 0], ['① (A) -> [B]', 1]]
    const run = { frames: [[], []], status: ['a', 'b'], log: ['', 'l'], say: ['', 's'], trail: ['', '① (A) ▸-> [B]'], path: [[], [row]] } as unknown as Drawing
    expect(runLines(run, 1)).toEqual({ trail: 'path   ① (A) ▸-> [B]', path: [row], now: '› s' })
    const old = { frames: [[]], status: ['a'], log: ['l'] } as unknown as Drawing
    expect(runLines(old, 0)).toEqual({ trail: 'path   ', path: null, now: '› l' })
    expect(runLines({ frames: [[]] } as unknown as Drawing, 0)).toBeNull()
  })
})
