// The Sigil viewer inside Claude Code: a tool the agent calls and a
// /sigil-pane command (/sigil is the skill's), drawing a document in a pane
// (theme-coloured cells from pane.py, redrawn on every save, a simulated run
// stepped or played) or, in a multiplexer, in a split running view.py live.
// The repository's plugin/claude/README.md has the layout.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, UiOpenResult } from 'claude-code'

import type { Drawing, Playback, Split, ViewRequest } from '../types'
import {
  COMMAND, DEFAULT_WIDTH, PANE, RASTER_COLUMNS, TOOL, UNASKED_COLUMNS,
  detectMux, drawArgv, frameIndex, herdrPaneOf, nextDepth, nextView, parseCommandArgs,
  parseDrawing, parseRequest, rasterCells, replyText, resolveDisplay, rowsWidth,
  shellQuote, slices, splitArgv, statusLine, viewArgv,
} from './logic'
import type { Asked, Display } from './logic'

const request = atom({ plugin: 'sigil', key: 'request' } as const, null)
const drawing = atom({ plugin: 'sigil', key: 'drawing' } as const, null)
const failure = atom({ plugin: 'sigil', key: 'error' } as const, null)
const playback = atom({ plugin: 'sigil', key: 'playback' } as const, { at: 0, isPlaying: false })
const split = atom({ plugin: 'sigil', key: 'split' } as const, null)

const WATCH_MS = 1000 // how often the shown file is looked at
const PLAY_MS = 125 // a played run's frame time: 8 frames a second, view.py's start
const ALIVE_MS = 3000 // a split whose follow loop touched its file this recently is up
const TITLE = 'Sigil'

type $ = EngineInterface

const TOOL_DESCRIPTION = [
  'Show a Sigil design to the person in a live viewer beside the conversation:',
  'the graph, tree or flow view, redrawn on every save of the file. With',
  'scenario, the simulated run of that pathway (view.py --sim names: happy, or',
  'one from the scenarios list the reply gives), shown at frame (0-based, or',
  '"last") or played (play: true). Fields left out keep their last value.',
  'The reply says where it is shown, the summary, lint, and the run at that',
  'frame; it does not return the drawing (view.py --once prints that as text).',
].join(' ')

const TOOL_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string', description: 'The .sigil file (relative to the working directory, or absolute).' },
    view: { type: 'string', enum: ['graph', 'tree', 'flow'], description: 'Which view (default graph).' },
    depth: { oneOf: [{ type: 'integer', minimum: 0 }, { const: 'all' }], description: 'Expansion depth (default 1).' },
    scenario: { type: 'string', description: 'A scenario to simulate; "" ends the run.' },
    frame: { oneOf: [{ type: 'integer', minimum: 0 }, { const: 'last' }], description: 'The run frame to show (default: the last).' },
    play: { type: 'boolean', description: 'Play the run from the frame shown (true) or pause it (false).' },
    payloads: { type: 'boolean', description: 'Show flow payloads.' },
  },
}

// Timers live with the module (a reload drops them and they are started
// again by the next draw); everything drawn lives in $.state.
let watchTimer: { cancel: () => void } | null = null
let playTimer: { cancel: () => void } | null = null
let seenMtime = 0
let columns = DEFAULT_WIDTH // the pane body's width as last drawn
let drawingFor = '' // the request + width a redraw is under way for

async function scriptPath($: $): Promise<string> {
  const built = `${$.plugin.root}/skills/sigil/scripts/pane.py`
  return (await $.fs.exists(built)) ? built : `${$.plugin.root}/scripts/pane.py`
}

async function muxEnv($: $) {
  return { herdr: await $.env.get('HERDR_ENV'), tmux: await $.env.get('TMUX'), zellij: await $.env.get('ZELLIJ') }
}

/** The file as an absolute path, or why it cannot be shown. */
async function located($: $, file: string): Promise<string | { error: string }> {
  const stat = await $.fs.stat(file, { resolve: true }).catch(() => undefined)
  if (stat === undefined || stat.realPath === undefined) return { error: `${file}: no such file` }
  if (stat.kind !== 'file') return { error: `${file}: not a file` }
  seenMtime = stat.mtimeMs
  return stat.realPath
}

/** Runs pane.py for the request at `width` and stores what it drew. */
async function redraw($: $, req: ViewRequest, width: number): Promise<Drawing | { error: string }> {
  const key = JSON.stringify([req, width])
  drawingFor = key
  const ran = await $.process.run(drawArgv(await scriptPath($), req, width), { timeoutMs: 60000 })
    .catch((err: unknown) => ({ exitCode: 1, stdout: '', stderr: String(err) }))
  const got = ran.exitCode === 0 ? parseDrawing(ran.stdout) : { error: ran.stderr.trim().split('\n').pop() ?? 'pane.py failed' }
  if (drawingFor === key) drawingFor = ''
  if ('error' in got) {
    await update($, failure, () => got.error)
    return got
  }
  got.width = width
  await update($, drawing, () => got)
  await update($, failure, () => null)
  await update($, playback, p => ({ ...p, at: Math.min(p.at, got.frames.length - 1) }))
  return got
}

function startWatch($: $): void {
  if (watchTimer !== null) return
  watchTimer = $.clock.every(WATCH_MS, async () => {
    const req = await read($, request)
    if (req === null) return
    const stat = await $.fs.stat(req.file).catch(() => undefined)
    if (stat === undefined || stat.mtimeMs === seenMtime) return
    seenMtime = stat.mtimeMs
    await redraw($, req, columns)
  })
}

function stopPlay(): void {
  playTimer?.cancel()
  playTimer = null
}

function startPlay($: $): void {
  if (playTimer !== null) return
  playTimer = $.clock.every(PLAY_MS, async () => {
    const shown = await read($, drawing)
    const now = await read($, playback)
    if (shown === null || !now.isPlaying) return stopPlay()
    const last = shown.frames.length - 1
    const at = Math.min(now.at + 1, last)
    await update($, playback, () => ({ at, isPlaying: at < last }))
    if (at >= last) stopPlay()
  })
}

async function setPlayback($: $, next: Playback): Promise<void> {
  await update($, playback, () => next)
  if (next.isPlaying) startPlay($)
  else stopPlay()
}

/** The playback a request asks for over the drawing: `frame` (-1: the last),
 * else the last frame of a new run, else where it stood; `play` from there. */
function playbackFor(asked: Asked, shown: Drawing, before: Playback, isNewRun: boolean): Playback {
  const last = shown.frames.length - 1
  let at = asked.frame === undefined ? (isNewRun ? (asked.play ? 0 : last) : before.at) : asked.frame
  if (at < 0 || at > last) at = last
  const isPlaying = asked.play ?? (isNewRun ? false : before.isPlaying)
  return { at: isPlaying && at >= last && asked.frame === undefined ? 0 : at, isPlaying: isPlaying && last > 0 }
}

/** Shows `asked` in the mod's pane; `isAsked`: the person's /sigil (any width). */
async function showInPane($: $, asked: Asked, isAsked: boolean): Promise<string> {
  const before = await read($, request)
  const path = await located($, asked.request.file)
  if (typeof path !== 'string') return `sigil: ${path.error}`
  const req = { ...asked.request, file: path }
  const isNewRun = req.scenario !== before?.scenario || req.file !== before?.file
  await update($, request, () => req)
  const got = await redraw($, req, columns)
  if ('error' in got) return `sigil: ${got.error}`
  const now = playbackFor(asked, got, await read($, playback), isNewRun)
  await setPlayback($, now)
  startWatch($)
  const opened: UiOpenResult = await $.ui.open({ id: PANE, title: TITLE })
  const where = opened.isPlaced
    ? 'Shown in the sigil pane (redrawn on every save).'
    : isAsked
      ? `The sigil pane is open but not drawn: ${opened.reason}`
      : `The sigil pane is waiting: a pane the person did not ask for opens from ${UNASKED_COLUMNS} columns (${opened.reason}). `
        + `They can open it at any width with /${COMMAND}.`
  return replyText(got, frameIndex(got, now), now.isPlaying, where)
}

/** Writes the split's control file, opening the split first when none is up. */
async function showInSplit($: $, asked: Asked): Promise<string> {
  const path = await located($, asked.request.file)
  if (typeof path !== 'string') return `sigil: ${path.error}`
  const req = { ...asked.request, file: path }
  await update($, request, () => req)
  const mux = detectMux(await muxEnv($))
  if (mux === null) return 'sigil: display is multiplex, but no herdr, tmux or zellij session was found; set display to mod.'
  const control = JSON.stringify({ argv: viewArgv(req) })
  const held = await read($, split)
  if (held !== null && held.mux === mux && (await isAlive($, held))) {
    await $.fs.write(held.control, control)
    return about($, req, asked, `Shown in the ${mux} split running view.py live: ${shellQuote(viewArgv(req))}.`)
  }
  const tmp = (await $.env.get('TMPDIR')) ?? '/tmp'
  const opened: Split = { mux, control: `${tmp.replace(/\/$/, '')}/sigil-view-${crypto.randomUUID()}.json` }
  await $.fs.write(opened.control, control)
  const follow = ['python3', await scriptPath($), 'follow', opened.control]
  const ran = await $.process.run(splitArgv(mux, follow, mux === 'herdr' ? await $.env.get('HERDR_PANE_ID') : undefined))
  if (ran.exitCode !== 0) return `sigil: could not open a ${mux} split: ${ran.stderr.trim()}`
  if (mux === 'herdr') {
    const pane = herdrPaneOf(ran.stdout)
    if (pane === undefined) return 'sigil: herdr split gave no pane id'
    opened.pane = pane
    await $.process.run(['herdr', 'pane', 'run', pane, shellQuote(follow)])
  } else if (mux === 'tmux') {
    opened.pane = ran.stdout.trim()
  }
  await update($, split, () => opened)
  return about($, req, asked, `Opened a ${mux} split running view.py live (it redraws on every save; `
    + `q closes it): ${shellQuote(viewArgv(req))}.`)
}

/** A split's reply: where, then the summary and the run's end as pane.py
 * reads them (the split plays from its own keys: space, , and .). */
async function about($: $, req: ViewRequest, asked: Asked, where: string): Promise<string> {
  const steer = asked.frame !== undefined || asked.play !== undefined
    ? ' Its run starts paused at the first frame: space plays it, , and . step it there.'
    : ''
  const ran = await $.process.run(drawArgv(await scriptPath($), req, DEFAULT_WIDTH), { timeoutMs: 60000 })
    .catch(() => undefined)
  const got = ran?.exitCode === 0 ? parseDrawing(ran.stdout) : undefined
  if (got === undefined) return where + steer
  if ('error' in got) return `${where}${steer}\nsigil: ${got.error}`
  const last = got.frames.length - 1
  return replyText(got, last, false, where + steer).replace(/^paused at /m, 'the run ends at ')
}

async function isAlive($: $, held: Split): Promise<boolean> {
  const stat = await $.fs.stat(`${held.control}.alive`).catch(() => undefined)
  return stat !== undefined && (await $.clock.now()) - stat.mtimeMs < ALIVE_MS
}

async function show($: $, input: Record<string, unknown>, display: Display, isAsked: boolean): Promise<string> {
  const asked = parseRequest(input, await read($, request))
  if ('error' in asked) return `sigil: ${asked.error}`
  return display === 'multiplex' ? showInSplit($, asked) : showInPane($, asked, isAsked)
}

/** A key of the pane's: a new request redrawn, or a playback step. */
async function press($: $, change: (req: ViewRequest) => ViewRequest): Promise<void> {
  const req = await read($, request)
  if (req === null) return
  const next = change(req)
  await update($, request, () => next)
  await redraw($, next, columns)
}

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.tool.register({ name: 'view', description: TOOL_DESCRIPTION, inputSchema: TOOL_SCHEMA })
    await $.command.register({
      name: 'sigil-pane',
      description: 'Show a Sigil file in the viewer pane (any width), or reopen the last one',
      argumentHint: '[FILE] [graph|tree|flow] [depth N|all] [sim SCENARIO] [frame N|last] [play]',
    })
    return started
  })

  on('tool.call', { tool: 'mcp__sigil__view' }, async ($, e) => {
    const display = resolveDisplay(options.display, await muxEnv($))
    const { tool: _tool, tool_use_id: _id, ...input } = e as Record<string, unknown>
    return { result: await show($, input, display, false) }
  }).catch(($, e, next) => ({ result: `sigil: the viewer failed (${next.error.kind}); view.py --once still prints the drawing.` }))

  on('command.run', { command: 'sigil-pane' }, async ($, e) => {
    const display = resolveDisplay(options.display, await muxEnv($))
    const input = parseCommandArgs(e.args)
    if (Object.keys(input).length === 0 && display === 'mod' && (await read($, request)) !== null) {
      await $.ui.open({ id: PANE, title: TITLE })
      return { text: 'Sigil pane opened.' }
    }
    return { text: await show($, input, display, true) }
  })

  on('ui.close', { id: 'sigil' }, async ($, e, next) => {
    stopPlay()
    watchTimer?.cancel()
    watchTimer = null
    await update($, playback, p => ({ ...p, isPlaying: false }))
    return next(e)
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: 'sigil' }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const req = await read($, request)
    const shown = await read($, drawing)
    const error = await read($, failure)
    const now = await read($, playback)
    const width = Math.max(20, Math.min(e.props.bodyColumns, RASTER_COLUMNS))
    if (req !== null && shown !== null && shown.width !== width && drawingFor !== JSON.stringify([req, width])) {
      columns = width
      drawingFor = JSON.stringify([req, width])
      $.clock.after(0, () => void redraw($, req, width))
    }
    if (req !== null) startWatch($)
    if (shown === null || req === null) {
      return (
        <Box flexDirection="column">
          <Text dimColor>{error ?? `No Sigil file shown yet: /${COMMAND} FILE, or ask the agent to show one.`}</Text>
        </Box>
      )
    }
    const at = frameIndex(shown, now)
    const rows = shown.frames[at] ?? []
    const isRun = shown.status !== undefined
    const body = (cells: typeof rows, key: string) => {
      if (e.surface === 'terminal') {
        const { Raster } = $.ui.resolve(e)
        const cols = Math.max(1, Math.min(width, rowsWidth(cells) || 1))
        return slices(cells).map((part, i) => (
          <Raster key={`${key}${i}`} columns={cols} rows={Math.max(1, part.length)}
            cells={rasterCells(part.length > 0 ? part : [[]], shown.styles, cols)} />
        ))
      }
      return cells.map(row => (
        <Text wrap="truncate">
          {row.map(([text, id]) => {
            const [fg, bg, bold] = shown.styles[id] ?? [null, null, false]
            return <Text color={fg ?? undefined} backgroundColor={bg ?? undefined} bold={bold}>{text}</Text>
          })}
        </Text>
      ))
    }
    const step = (delta: number) => () =>
      setPlayback($, { at: Math.max(0, Math.min(at + delta, shown.frames.length - 1)), isPlaying: false })
    return (
      <Box flexDirection="column">
        <Text bold wrap="truncate">{statusLine(shown, req, at, now.isPlaying)}</Text>
        {error !== null && <Text color="error" wrap="truncate">✖ {error}</Text>}
        {body(rows, 'frame')}
        {isRun && <Text dimColor wrap="truncate">{shown.log?.[at] || ' '}</Text>}
        {shown.legend.length > 0 && body(shown.legend, 'legend')}
        <Text dimColor wrap="truncate">{shown.summary}</Text>
        {shown.lint.map(line => <Text dimColor wrap="truncate">{line}</Text>)}
        <Box flexDirection="row" gap={1}>
          <Button key="view" plain hotkey="t" label={`view ${nextView(req.view)}`}
            onPress={() => press($, r => ({ ...r, view: nextView(r.view) }))} />
          <Button key="depth" plain hotkey="d" label="depth"
            onPress={() => press($, r => ({ ...r, depth: nextDepth(r.depth) }))} />
          {isRun && <Button key="play" plain hotkey="p" label={now.isPlaying ? 'pause' : 'play'}
            onPress={() => setPlayback($, {
              at: !now.isPlaying && at >= shown.frames.length - 1 ? 0 : at, isPlaying: !now.isPlaying,
            })} />}
          {isRun && <Button key="back" plain hotkey="b" label="back" onPress={step(-1)} />}
          {isRun && <Button key="next" plain hotkey="n" label="next" onPress={step(1)} />}
        </Box>
      </Box>
    )
  })
}
