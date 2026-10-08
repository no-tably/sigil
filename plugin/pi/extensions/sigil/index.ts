// The Sigil viewer inside pi: a `sigil_view` tool the agent calls and a
// /sigil-pane command, drawing a document in a widget above the editor (pane.py's
// theme-coloured rows as truecolour text, redrawn on every save, a simulated
// run stepped or played) or, in a multiplexer, in a split running view.py
// live. The display rule, the requests and the split commands are the Claude
// Code mod's (logic.ts, copied beside this file by build.py). Nothing here
// imports pi itself, so it loads in any pi that has extensions; the
// repository's plugin/pi/README.md has the layout.

import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import { homedir, tmpdir } from 'node:os'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  DEFAULT_WIDTH, DISPLAYS, LAYOUTS, START_SPEED, SUPERSEDED, UNASKED_COLUMNS, VIEWS,
  askedFrame, cellWidth, cropRows, cutCells, detectMux, displayReport, drawArgv, drawnFrame, frameIndex, frameMs, herdrPaneOf, herdrReadyArgv,
  lastFrame, layoutReport, nextSpeed, panTo, parseCommandArgs, parseDisplayArgs, parseDrawing, parseLayoutArgs, parseRequest,
  pickDisplay, pickLayout, playbackFor, playTick, replyText, resolveDisplay, runLines, shellQuote, slot, splitArgv,
  splitStart, statusLine, viewArgv, windowFor, windowStart,
} from './logic.ts'
import type { Asked, Display, DisplayChoice, LayoutChoice } from './logic.ts'

// The shapes this file uses (types/index.d.ts in plugin/claude has them all).
type ViewRequest = { file: string; view: 'graph' | 'tree' | 'flow' | 'run'; depth: number; scenario?: string; payloads?: boolean }
type PackedRow = [string, number][]
type Style = [string | null, string | null, boolean]
type Drawing = {
  file: string; view: string; width: number | null; layout?: 'wrap' | 'pan'; height?: number
  styles: Style[]; frames: PackedRow[][]
  legend: PackedRow[]; summary: string; lint: string[]; scenarios: string[]
  status?: string[]; log?: string[]; say?: string[]; trail?: string[]; path?: PackedRow[][]; outcome?: string
  first?: number; last?: number // a run is drawn a window at a time: its frames first … first + frames.length - 1
}
type Playback = { at: number; isPlaying: boolean }
type Split = { mux: 'herdr' | 'tmux' | 'zellij'; control: string; pane?: string }

// The part of pi's extension API this uses, as its docs describe it.
type ExecResult = { stdout: string; stderr: string; code: number }
type Component = { render(width: number): string[]; invalidate(): void }
type Tui = { requestRender(): void }
type Ui = {
  setWidget(key: string, content: undefined | ((tui: Tui, theme: unknown) => Component)): void
  notify(message: string, level?: 'info' | 'warning' | 'error'): void
}
type Ctx = { cwd: string; hasUI: boolean; ui: Ui }
type ToolResult = { content: { type: 'text'; text: string }[]; details: Record<string, unknown> }
type Pi = {
  registerTool(tool: {
    name: string; label: string; description: string; promptSnippet?: string
    parameters: Record<string, unknown>
    execute(id: string, params: Record<string, unknown>, signal: unknown, onUpdate: unknown, ctx: Ctx): Promise<ToolResult>
  }): void
  registerCommand(name: string, options: { description: string; handler(args: string, ctx: Ctx): Promise<void> }): void
  registerFlag(name: string, options: { description: string; type: 'string'; default?: string }): void
  getFlag(name: string): unknown
  exec(command: string, args: string[], options?: { timeout?: number }): Promise<ExecResult>
  on(event: string, handler: (event: unknown, ctx: Ctx) => unknown): void
}

export const TOOL = 'sigil_view'
export const COMMAND = 'sigil-pane' // matches the Claude Code mod, where /sigil is the skill's
export const WIDGET = 'sigil'
export const FLAG = 'sigil-display'
export const LAYOUT_FLAG = 'sigil-layout'
const WATCH_MS = 1000 // how often the shown file is looked at
const ALIVE_MS = 3000 // a split whose follow loop touched its file this recently is up
const CHROME_ROWS = 14 // the editor, footer and some conversation the widget leaves room for
const MIN_BODY_ROWS = 10
const HINT = `/${COMMAND} graph|tree|flow|run · depth N|all · sim NAME · play · pause · back · next · - + speed · close · display · layout`
const PAN_HINT = `/${COMMAND} left · right: pan the drawing`   // while a panned one is wider than the widget

const HERE = dirname(fileURLToPath(import.meta.url))
const PANE_PY = join(HERE, '..', '..', 'skills', 'sigil', 'scripts', 'pane.py')

const TOOL_DESCRIPTION = [
  'Show a Sigil design to the person in a live viewer in their terminal:',
  'the graph, tree or flow view (the design), or the run view (one simulated',
  'run as a timeline: a lane per participant, time left to right; the happy',
  'run when no scenario is given), redrawn on every save of the file. With',
  'scenario, the simulated run of that pathway (view.py --sim names: happy, or',
  'one from the scenarios list the reply gives), shown at frame (0-based, or',
  '"last") or played (play: true). Fields left out keep their last value.',
  'The reply says where it is shown, the summary, lint, and the run at that',
  'frame; it does not return the drawing (view.py --once prints that as text).',
  'Pick the view that fits: flow for request paths and failure routes;',
  'tree for composition, ownership and state machines, or a narrow pane;',
  'graph for the overall topology and fan-in of a small design; run to',
  'present a simulation (timing, retries, spawns, recursion). Tell the',
  'person in one sentence which view you picked and why.',
].join(' ')

// Plain JSON Schema (pi validates with ajv, coercing types): depth and frame
// are strings so a number or "all" / "last" both pass, without a union.
const TOOL_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string', description: 'The .sigil file (relative to the working directory, or absolute).' },
    view: { type: 'string', enum: [...VIEWS], description: 'Which view (default flow).' },
    depth: { type: 'string', description: 'Expansion depth: a whole number, or "all" (default 1).' },
    scenario: { type: 'string', description: 'A scenario to simulate; "" ends the run.' },
    frame: { type: 'string', description: 'The run frame to show: a 0-based number, or "last" (default: the last).' },
    play: { type: 'boolean', description: 'Play the run from the frame shown (true) or pause it (false).' },
    payloads: { type: 'boolean', description: 'Show flow payloads.' },
  },
}

/** The viewer settings every agent plugin without settings of its own shares
 * (docs/tools.md, the viewer plugin contract): $XDG_CONFIG_HOME/sigil/viewer.json,
 * else ~/.config/sigil/viewer.json. */
export function settingsPath(env: Record<string, string | undefined> = process.env): string {
  const base = env.XDG_CONFIG_HOME && isAbsolute(env.XDG_CONFIG_HOME) ? env.XDG_CONFIG_HOME : join(homedir(), '.config')
  return join(base, 'sigil', 'viewer.json')
}

/** A setting in the settings file (`display`, `layout`), or undefined (no
 * file, not JSON, unset). */
export function savedSetting(path: string, key: string): string | undefined {
  try {
    const value = JSON.parse(readFileSync(path, 'utf8'))?.[key]
    return typeof value === 'string' ? value : undefined
  } catch {
    return undefined
  }
}

/** Writes a setting into the settings file, keeping any other keys. */
export async function saveSetting(path: string, key: string, value: string): Promise<void> {
  let kept: Record<string, unknown> = {}
  try {
    const got = JSON.parse(await readFile(path, 'utf8'))
    if (got !== null && typeof got === 'object' && !Array.isArray(got)) kept = got
  } catch {
    // a missing or broken file is written afresh
  }
  await mkdir(dirname(path), { recursive: true })
  await writeFile(path, JSON.stringify({ ...kept, [key]: value }, null, 2) + '\n')
}

/** The settings file's `display`, or undefined. */
export function savedDisplay(path: string): string | undefined {
  return savedSetting(path, 'display')
}

/** Writes `display` into the settings file, keeping any other keys. */
export async function saveDisplay(path: string, choice: DisplayChoice): Promise<void> {
  await saveSetting(path, 'display', choice)
}

/** `#rrggbb` as an SGR colour (38 foreground, 48 background), or null. */
export function sgrColour(hex: string | null, base: 38 | 48): string | null {
  const m = hex === null ? null : /^#([0-9a-f]{6})$/i.exec(hex)
  if (m === null || m[1] === undefined) return null
  const n = parseInt(m[1], 16)
  return `${base};2;${(n >> 16) & 255};${(n >> 8) & 255};${n & 255}`
}

/** A packed row as one terminal line, at most `width` cells (pane.py makes
 * every character one cell), each run in its style's colours. */
export function ansiRow(row: PackedRow, styles: readonly Style[], width: number): string {
  let out = ''
  let left = width
  for (const [text, id] of row) {
    if (left <= 0) break
    const cut = [...text].slice(0, left).join('')
    left -= [...cut].length
    const [fg, bg, bold] = styles[id] ?? [null, null, false]
    const codes = [bold ? '1' : null, sgrColour(fg, 38), sgrColour(bg, 48)].filter(c => c !== null)
    out += codes.length > 0 ? `\x1b[${codes.join(';')}m${cut}\x1b[0m` : cut
  }
  return out
}

/** Plain text cut to `width` columns (a wide character two), in an SGR style (dim 2, bold 1, red 31). */
export function styled(text: string, width: number, sgr?: string): string {
  const cut = cutCells(text, width)
  return sgr === undefined ? cut : `\x1b[${sgr}m${cut}\x1b[0m`
}

/** Plain text wrapped at `width` cells between words (a continuation indented
 * two), each line in an SGR style — the summary and lint under the drawing. */
export function wrapped(text: string, width: number, sgr?: string): string[] {
  const out: string[] = []
  let line = ''
  for (const word of text.split(' ')) {
    const next = line === '' ? word : `${line} ${word}`
    if (cellWidth(next) > width && line.trim() !== '') {
      out.push(line)
      line = `  ${word}`
    } else line = next
  }
  out.push(line)
  return out.map(l => styled(l, width, sgr))
}

/** The widget's lines: the status (the run at `speed`, an index into SPEEDS),
 * the frame (cut to `bodyRows`, saying how many rows are left out; a panned one
 * from column `panX`), the run's path and narration line (runLines), the
 * legend, summary, lint and the command hint. */
export function widgetLines(drawing: Drawing, request: ViewRequest, playback: Playback,
                            error: string | null, width: number, bodyRows: number, panX = 0,
                            speed: number = START_SPEED): string[] {
  const at = frameIndex(drawing as never, playback)
  const drawn = drawing.frames[slot(drawing as never, at)] ?? []
  const isPanned = drawing.layout === 'pan' && drawn.some(r => r.reduce((n, [t]) => n + [...t].length, 0) > width)
  const rows = isPanned ? cropRows(drawn, panX, width) : drawn
  const lines = [styled(statusLine(drawing as never, request, at, playback.isPlaying, speed), width, '1')]
  if (error !== null) lines.push(styled(`✖ ${error}`, width, '31'))
  const shown = rows.length > bodyRows ? rows.slice(0, Math.max(1, bodyRows - 1)) : rows
  for (const row of shown) lines.push(ansiRow(row, drawing.styles, width))
  if (shown.length < rows.length) {
    lines.push(styled(`… ${rows.length - shown.length} more rows: view.py ${drawing.file} draws the whole of it`, width, '2'))
  }
  const told = runLines(drawing as never, at)
  if (told !== null) {
    if (told.path !== null) for (const row of told.path) lines.push(ansiRow(row, drawing.styles, width))
    else lines.push(styled(told.trail, width, '2'))
    lines.push(styled(told.now, width, '1'))
  }
  if (shown.length === rows.length) for (const row of drawing.legend) lines.push(ansiRow(row, drawing.styles, width))
  lines.push(...wrapped(drawing.summary, width, '2'))
  for (const line of drawing.lint) lines.push(...wrapped(line, width, '2'))
  if (isPanned) lines.push(styled(PAN_HINT, width, '2'))
  lines.push(styled(HINT, width, '2'))
  return lines
}

/** The widget's lines as plain text: what pi's RPC mode sends a client, which
 * takes text lines and no terminal styles. */
export function plainLines(lines: readonly string[]): string[] {
  return lines.map(line => line.replace(/\x1b\[[0-9;]*m/g, ''))
}

type Action = 'close' | 'back' | 'next' | 'left' | 'right' | 'slower' | 'faster'
const ACTIONS: Record<string, Action> = {
  close: 'close', back: 'back', next: 'next', left: 'left', right: 'right', '-': 'slower', '+': 'faster',
}

/** /sigil-pane's own words over the tool's: `close`, `pause`, `back`, `next`,
 * `left` / `right` (a panned drawing, half a widget across) and `-` / `+`
 * (the run's speed, as view.py's keys). */
export function commandWords(args: string): { action?: Action; input: Record<string, unknown> } {
  const words = args.trim().split(/\s+/).filter(w => w !== '')
  const own = words.map(w => ACTIONS[w]).find(a => a !== undefined)
  const rest = words.filter(w => ACTIONS[w] === undefined && w !== 'pause')
  const input = parseCommandArgs(rest.join(' '))
  if (words.includes('pause')) input.play = false
  return own === undefined ? { input } : { action: own, input }
}

export default function sigil(pi: Pi): void {
  let request: ViewRequest | null = null
  let drawing: Drawing | null = null
  let failure: string | null = null
  let playback: Playback = { at: 0, isPlaying: false }
  let speed = START_SPEED // the played run's speed, an index into SPEEDS
  let split: Split | null = null
  let tui: Tui | null = null // set while the widget is shown
  let ui: Ui | null = null
  let texted: string | null = null // RPC mode: the lines last sent as a text widget
  let watchTimer: ReturnType<typeof setInterval> | null = null
  let playTimer: ReturnType<typeof setInterval> | null = null
  let seenMtime = 0
  let panX = 0 // the first column a panned drawing shows
  let drawingFor = '' // the request + size the latest redraw is for ('' once it drew; kept when it failed)
  let drawSeq = 0 // counts redraws: only the latest stores what it drew
  let isWindowing = false // a run window is being drawn (fetchWindow asks for one at a time)

  const columns = () => process.stdout.columns || DEFAULT_WIDTH
  const bodyRows = () => Math.max(MIN_BODY_ROWS, (process.stdout.rows || 40) - CHROME_ROWS)
  /** RPC mode: pi speaks JSON on stdout, so it is no terminal, and it sends a
   * client only text widgets (a component widget is dropped). */
  const isTextOnly = () => !process.stdout.isTTY
  const env = () => ({ herdr: process.env.HERDR_ENV, tmux: process.env.TMUX, zellij: process.env.ZELLIJ })
  /** The display setting by precedence: --sigil-display, SIGIL_DISPLAY, the
   * shared settings file (read on each use), else auto. */
  const setting = () => pickDisplay([
    [`--${FLAG}`, pi.getFlag(FLAG)],
    ['SIGIL_DISPLAY', process.env.SIGIL_DISPLAY],
    [settingsPath(), savedDisplay(settingsPath())],
  ], 'the default')
  const display = (): Display => resolveDisplay(setting().choice, env())
  /** The layout setting by the same precedence: --sigil-layout, SIGIL_LAYOUT,
   * the settings file, else auto. */
  const layoutSetting = () => pickLayout([
    [`--${LAYOUT_FLAG}`, pi.getFlag(LAYOUT_FLAG)],
    ['SIGIL_LAYOUT', process.env.SIGIL_LAYOUT],
    [settingsPath(), savedSetting(settingsPath(), 'layout')],
  ], 'the default')
  /** What a redraw at `width` is for: the request, the layout, and (auto only)
   * the rows it picks by. */
  const drawKey = (req: ViewRequest, width: number) => {
    const layout = layoutSetting().choice
    return JSON.stringify([req, width, layout, layout === 'auto' ? bodyRows() : 0])
  }

  /** `/sigil-pane layout [VALUE]`: the setting in words, or saved to the file. */
  async function layoutCommand(choice: LayoutChoice | undefined): Promise<string> {
    const now = layoutSetting()
    if (choice === undefined) return layoutReport(now.choice, now.source, drawing?.layout)
    const path = settingsPath()
    await saveSetting(path, 'layout', choice)
    const after = layoutSetting()
    const said = layoutReport(choice, path)
    if (after.source !== path) {
      return `${said}\nBut ${after.source} (${after.choice}) wins in this session; the file applies once it is unset.`
    }
    if (request !== null && tui !== null) await redraw(request, drawing?.width ?? columns())
    return `${said}\nThe next drawing is laid out ${choice === 'auto' ? 'as fits the widget best' : `to ${choice}`}.`
  }

  /** `/sigil-pane display [VALUE]`: the setting in words, or saved to the file. */
  async function displayCommand(choice: DisplayChoice | undefined): Promise<string> {
    const now = setting()
    if (choice === undefined) return displayReport(now.choice, now.source, env())
    const path = settingsPath()
    await saveDisplay(path, choice)
    const after = setting()
    const said = displayReport(choice, path, env())
    if (after.source !== path) {
      return `${said}\nBut ${after.source} (${after.choice}) wins in this session; the file applies once it is unset.`
    }
    return `${said}\nThe next view draws ${resolveDisplay(choice, env()) === 'mod' ? 'in the sigil widget' : 'in a split'}.`
  }

  /** The file as an absolute path, or why it cannot be shown. */
  async function located(cwd: string, file: string): Promise<string | { error: string }> {
    const path = file.replace(/^@/, '') // some models prefix paths with @
    const full = isAbsolute(path) ? path : resolve(cwd, path)
    const st = await stat(full).catch(() => undefined)
    if (st === undefined) return { error: `${file}: no such file` }
    if (!st.isFile()) return { error: `${file}: not a file` }
    seenMtime = st.mtimeMs
    return full
  }

  /** Shows what changed: the component redrawn, or in RPC mode the text widget
   * sent again when its lines differ (the whole drawing: the client scrolls;
   * the status whole too, as the client wraps it). */
  function refresh(): void {
    if (tui !== null) return tui.requestRender()
    if (texted === null || ui === null || request === null || drawing === null) return
    const lines = plainLines(widgetLines(drawing, request, playback, failure, DEFAULT_WIDTH, Infinity, panX, speed))
    lines[0] = statusLine(drawing as never, request, frameIndex(drawing as never, playback), playback.isPlaying, speed)
    const sent = lines.join('\n')
    if (sent === texted) return
    texted = sent
    ui.setWidget(WIDGET, lines)
  }

  /** pane.py's drawing of the request at `width`; a run's window from `from` (windowStart). */
  async function runPane(req: ViewRequest, width: number, from: number): Promise<Drawing | { error: string }> {
    const layout = layoutSetting().choice
    const argv = drawArgv(PANE_PY, req, width, { layout, from, ...(layout === 'auto' ? { height: bodyRows() } : {}) })
    const ran = await pi.exec(argv[0] ?? 'python3', argv.slice(1), { timeout: 60000 })
      .catch((err: unknown) => ({ code: 1, stdout: '', stderr: String(err) }))
    if (ran.code !== 0) return { error: ran.stderr.trim().split('\n').pop() || 'pane.py failed' }
    return parseDrawing(ran.stdout) as Drawing | { error: string }
  }

  /** Runs pane.py for the request at `width` and stores what it drew, unless a
   * later redraw started meanwhile (an older run finishing last never wins). A
   * run is drawn a window at a time: the one starting at `from` (windowStart),
   * else the one holding the frame shown. A failure keeps `drawingFor`, so the
   * widget does not ask for the same width again until the request or the
   * width changes (or a save redraws). */
  async function redraw(req: ViewRequest, width: number, from?: number): Promise<Drawing | { error: string }> {
    const key = drawKey(req, width)
    const seq = ++drawSeq
    drawingFor = key
    const got = await runPane(req, width, from ?? windowStart(playback.at))
    if (seq !== drawSeq) return { error: SUPERSEDED }
    if ('error' in got) failure = got.error
    else {
      drawingFor = ''
      got.width = width
      drawing = got
      failure = null
      playback = { ...playback, at: Math.min(playback.at, lastFrame(got as never)) }
    }
    refresh()
    return got
  }

  /** Draws the run's window for showing `at` when the drawing does not hold it
   * (or, playing, will soon run out of it): windowFor, one window at a time. */
  function fetchWindow(at: number, isPlaying: boolean): void {
    if (request === null || drawing === null || isWindowing) return
    const from = windowFor(drawing as never, at, isPlaying)
    if (from === null) return
    isWindowing = true
    void redraw(request, drawing.width ?? columns(), from).finally(() => { isWindowing = false })
  }

  function startWatch(): void {
    if (watchTimer !== null) return
    watchTimer = setInterval(async () => {
      if (request === null || (tui === null && texted === null)) return
      const st = await stat(request.file).catch(() => undefined)
      if (st === undefined || st.mtimeMs === seenMtime) return
      seenMtime = st.mtimeMs
      await redraw(request, drawing?.width ?? columns())
    }, WATCH_MS)
  }

  function stopPlay(): void {
    if (playTimer !== null) clearInterval(playTimer)
    playTimer = null
  }

  function setPlayback(next: Playback): void {
    playback = next
    refresh()
    if (!next.isPlaying) return stopPlay()
    if (playTimer !== null) return
    playTimer = setInterval(() => {
      if (drawing === null || !playback.isPlaying) return stopPlay()
      playback = playTick(drawing as never, playback)
      fetchWindow(playback.at + 1, playback.isPlaying)
      refresh()
      if (!playback.isPlaying) stopPlay()
    }, frameMs(speed))
  }

  /** A speed step faster (+1) or slower (-1); a playing run goes on at it. */
  function setSpeed(delta: number): void {
    speed = nextSpeed(speed, delta)
    stopPlay()
    setPlayback(playback)
  }

  function component(): Component {
    return {
      render(width: number): string[] {
        if (request === null || drawing === null) {
          return [styled(failure ?? `No Sigil file shown yet: /${COMMAND} FILE, or ask the agent to show one.`, width, '2')]
        }
        if (drawing.width !== width && drawingFor !== drawKey(request, width)) {
          const req = request
          drawingFor = drawKey(req, width)
          setTimeout(() => void redraw(req, width), 0)
        }
        return widgetLines(drawing, request, playback, failure, width, bodyRows(), panX, speed)
      },
      invalidate() {},
    }
  }

  function openWidget(onUi: Ui): void {
    ui = onUi
    if (tui !== null) return tui.requestRender()
    if (isTextOnly()) {
      texted ??= ''
      refresh()
      return startWatch()
    }
    onUi.setWidget(WIDGET, t => {
      tui = t
      return component()
    })
    startWatch()
  }

  function closeWidget(): void {
    stopPlay()
    if (watchTimer !== null) clearInterval(watchTimer)
    watchTimer = null
    playback = { ...playback, isPlaying: false }
    ui?.setWidget(WIDGET, undefined)
    tui = null
    texted = null
  }

  /** Shows `asked` in the widget; `isAsked`: the person's /sigil-pane (any width). */
  async function showInWidget(ctx: Ctx, asked: Asked, isAsked: boolean): Promise<string> {
    if (!ctx.hasUI) {
      return 'sigil: this pi session has no terminal UI (print or json mode); view.py --once prints the drawing.'
    }
    const path = await located(ctx.cwd, asked.request.file)
    if (typeof path !== 'string') return `sigil: ${path.error}`
    const req = { ...asked.request, file: path }
    const isNewRun = req.scenario !== request?.scenario || req.file !== request?.file
    request = req
    panX = 0
    const width = columns()
    const got = await redraw(req, width, windowStart(askedFrame(asked, playback, isNewRun)))
    if ('error' in got) return `sigil: ${got.error}`
    setPlayback(playbackFor(asked, got as never, playback, isNewRun))
    let where = 'Shown in the sigil widget above the editor (redrawn on every save).'
    if (tui !== null || isAsked || width >= UNASKED_COLUMNS || isTextOnly()) openWidget(ctx.ui)
    else {
      where = `The sigil widget is waiting: a widget the person did not ask for opens from ${UNASKED_COLUMNS} `
        + `columns (this terminal has ${width}). They can open it at any width with /${COMMAND}.`
    }
    return replyText(got as never, frameIndex(got as never, playback), playback.isPlaying, where)
  }

  async function isAlive(held: Split): Promise<boolean> {
    const st = await stat(`${held.control}.alive`).catch(() => undefined)
    return st !== undefined && Date.now() - st.mtimeMs < ALIVE_MS
  }

  /** A split's reply: where, then the summary and the run where the split
   * starts it (splitStart) as pane.py reads them. */
  async function about(req: ViewRequest, asked: Asked, where: string): Promise<string> {
    const start = splitStart(asked)
    const got = await runPane(req, DEFAULT_WIDTH, windowStart(start.frame))
    if ('error' in got) return `${where}\nsigil: ${got.error}`
    const last = lastFrame(got as never)
    const at = drawnFrame(got as never, start.frame)
    return replyText(got as never, at, start.play && at < last, where)
  }

  /** Writes the split's control file, opening the split first when none is up. */
  async function showInSplit(ctx: Ctx, asked: Asked): Promise<string> {
    const path = await located(ctx.cwd, asked.request.file)
    if (typeof path !== 'string') return `sigil: ${path.error}`
    const req = { ...asked.request, file: path }
    request = req
    const mux = detectMux(env())
    if (mux === null) {
      return `sigil: display is multiplex, but no herdr, tmux or zellij session was found; /${COMMAND} display mod draws in the widget.`
    }
    const layout = layoutSetting().choice
    const live = viewArgv(req, layout, splitStart(asked))
    const control = JSON.stringify({ argv: live })
    if (split !== null && split.mux === mux && (await isAlive(split))) {
      await writeFile(split.control, control)
      return about(req, asked, `Shown in the ${mux} split running view.py live: ${shellQuote(live)}.`)
    }
    const opened: Split = { mux, control: join(tmpdir(), `sigil-view-${randomUUID()}.json`) }
    await writeFile(opened.control, control)
    const follow = ['python3', PANE_PY, 'follow', opened.control]
    const argv = splitArgv(mux, follow, mux === 'herdr' ? process.env.HERDR_PANE_ID : undefined)
    const ran = await pi.exec(argv[0] ?? mux, argv.slice(1), { timeout: 30000 })
    if (ran.code !== 0) return `sigil: could not open a ${mux} split: ${ran.stderr.trim()}`
    if (mux === 'herdr') {
      const pane = herdrPaneOf(ran.stdout)
      if (pane === undefined) return 'sigil: herdr split gave no pane id'
      opened.pane = pane
      const ready = herdrReadyArgv(pane)
      await pi.exec(ready[0], ready.slice(1), { timeout: 10000 }).catch(() => undefined)
      await pi.exec('herdr', ['pane', 'run', pane, shellQuote(follow)], { timeout: 30000 })
    } else if (mux === 'tmux') {
      opened.pane = ran.stdout.trim()
    }
    split = opened
    return about(req, asked, `Opened a ${mux} split running view.py live (it redraws on every save; `
      + `q closes it): ${shellQuote(live)}.`)
  }

  async function show(ctx: Ctx, input: Record<string, unknown>, isAsked: boolean): Promise<string> {
    // the file as the request stores it (its full path), so naming the shown
    // file again keeps its run
    const named = typeof input.file === 'string' && input.file !== '' ? await located(ctx.cwd, input.file) : undefined
    if (typeof named === 'object') return `sigil: ${named.error}`
    const asked = parseRequest(named === undefined ? input : { ...input, file: named }, request as never)
    if ('error' in asked) return `sigil: ${asked.error}`
    return display() === 'multiplex' ? showInSplit(ctx, asked) : showInWidget(ctx, asked, isAsked)
  }

  pi.registerFlag(FLAG, {
    description: 'Where the sigil viewer draws: mod (a widget above the editor), multiplex '
      + '(a herdr / tmux / zellij split running view.py live) or auto (multiplex inside a multiplexer, else mod). '
      + `Unset: SIGIL_DISPLAY, then ${settingsPath()} (/${COMMAND} display sets it), then auto.`,
    type: 'string',
  })
  pi.registerFlag(LAYOUT_FLAG, {
    description: 'How the sigil viewer fits a drawing wider than the widget: wrap (fit the width, grow down), '
      + 'pan (keep the natural layout; /sigil-pane left and right pan it) or auto (whichever overflows less). '
      + `Unset: SIGIL_LAYOUT, then ${settingsPath()} (/${COMMAND} layout sets it), then auto.`,
    type: 'string',
  })

  pi.registerTool({
    name: TOOL,
    label: 'Sigil view',
    description: TOOL_DESCRIPTION,
    promptSnippet: 'Show a Sigil design (and a simulated run of it) to the person in a live viewer',
    parameters: TOOL_SCHEMA,
    async execute(_id, params, _signal, _onUpdate, ctx) {
      const text = await show(ctx, params, false)
        .catch((err: unknown) => `sigil: the viewer failed (${String(err)}); view.py --once still prints the drawing.`)
      return { content: [{ type: 'text', text }], details: {} }
    },
  })

  pi.registerCommand(COMMAND, {
    description: 'Show a Sigil file in the viewer widget (any width), step or play its run, pan it, close it, '
      + `or set where it draws (display ${DISPLAYS.join('|')}) or how a wide drawing fits (layout ${LAYOUTS.join('|')})`,
    async handler(args, ctx) {
      const asked = parseDisplayArgs(args)
      if (asked !== null) {
        if ('error' in asked) return ctx.ui.notify(`sigil: ${asked.error}`, 'error')
        const text = await displayCommand(asked.choice)
          .catch((err: unknown) => `sigil: could not save the display setting (${String(err)})`)
        return ctx.ui.notify(text, text.startsWith('sigil:') ? 'error' : 'info')
      }
      const laid = parseLayoutArgs(args)
      if (laid !== null) {
        if ('error' in laid) return ctx.ui.notify(`sigil: ${laid.error}`, 'error')
        const text = await layoutCommand(laid.choice)
          .catch((err: unknown) => `sigil: could not save the layout setting (${String(err)})`)
        return ctx.ui.notify(text, text.startsWith('sigil:') ? 'error' : 'info')
      }
      const { action, input } = commandWords(args)
      if (action === 'close') return closeWidget()
      if (action === 'left' || action === 'right') {
        if (drawing === null) return ctx.ui.notify(`sigil: nothing shown yet: /${COMMAND} FILE`, 'warning')
        const width = drawing.width ?? columns()
        const across = Math.max(0, ...(drawing.frames[slot(drawing as never, frameIndex(drawing as never, playback))] ?? [])
          .map(r => r.reduce((n, [t]) => n + [...t].length, 0)))
        panX = panTo(panX, (action === 'right' ? 1 : -1) * Math.floor(width / 2), across, width)
        refresh()
        return openWidget(ctx.ui)
      }
      if (action !== undefined) {
        if (drawing === null) return ctx.ui.notify(`sigil: nothing shown yet: /${COMMAND} FILE`, 'warning')
        if (action === 'slower' || action === 'faster') setSpeed(action === 'faster' ? 1 : -1)
        else {
          const step = action === 'next' ? 1 : -1
          const at = Math.max(0, Math.min(frameIndex(drawing as never, playback) + step, lastFrame(drawing as never)))
          setPlayback({ at, isPlaying: false })
          fetchWindow(at, false)
        }
        if (Object.keys(input).length === 0) return openWidget(ctx.ui)
      }
      if (Object.keys(input).length === 0 && display() === 'mod' && request !== null) return openWidget(ctx.ui)
      const text = await show(ctx, input, true)
      const first = text.split('\n')[0] ?? ''
      ctx.ui.notify(first, first.startsWith('sigil:') ? 'error' : 'info')
    },
  })

  pi.on('session_shutdown', () => closeWidget())
}
