import { describe, expect, test } from 'claude-code/testing'

import {
  colourOf, cropRows, displayReport, drawArgv, frameIndex, herdrPaneOf, herdrReadyArgv, layoutOf, layoutReport, nextView,
  panTo, parseCommandArgs, parseDisplayArgs, parseDrawing, parseLayoutArgs, parseRequest, pickDisplay, pickLayout,
  rasterCells, resolveDisplay, runLines, shellQuote, slices, splitArgv, viewArgv,
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
  test("a run's path and narration line; the log line from an older pane.py", () => {
    const row = [['path   ', 0], ['① (A) -> [B]', 1]]
    const run = { frames: [[], []], status: ['a', 'b'], log: ['', 'l'], say: ['', 's'], trail: ['', '① (A) ▸-> [B]'], path: [[], [row]] } as unknown as Drawing
    expect(runLines(run, 1)).toEqual({ trail: 'path   ① (A) ▸-> [B]', path: [row], now: '› s' })
    const old = { frames: [[]], status: ['a'], log: ['l'] } as unknown as Drawing
    expect(runLines(old, 0)).toEqual({ trail: 'path   ', path: null, now: '› l' })
    expect(runLines({ frames: [[]] } as unknown as Drawing, 0)).toBeNull()
  })
})
