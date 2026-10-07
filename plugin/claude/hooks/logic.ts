// The mod's pure half: requests, argv, the display and layout choices, the
// multiplexer commands and the cell packing. No `$` here, so the tests drive it
// directly.

import type { Drawing, Mux, PackedRow, Playback, Style, ViewName, ViewRequest } from '../types'

export const PANE = 'sigil'
export const TOOL = 'view'
export const COMMAND = 'sigil-pane' // /sigil is the skill's own
export const VIEWS: readonly ViewName[] = ['graph', 'tree', 'flow', 'run']
export const DEFAULT_VIEW: ViewName = 'flow' // view.py's DEFAULT_VIEW: the view it starts in
export const ALL_DEPTH = 99
export const UNASKED_COLUMNS = 144 // the engine's floor for a pane opened unasked
export const DEFAULT_WIDTH = 100 // the width drawn for before the pane has measured
export const SUPERSEDED = 'a later view request replaced this one before it drew'
export const RASTER_ROWS = 256 // a Raster's tallest; a taller drawing is several
export const RASTER_COLUMNS = 512
export const DEFAULT_COLOUR = 0x01000000 // the terminal's own colour
export const SPEEDS: readonly number[] = [0.25, 0.5, 1, 2, 4, 8, 16, 32] // frames a second: view.py's SIM_SPEEDS
export const START_SPEED = 3 // 2 frames a second, view.py's start (an index into SPEEDS)

export type Display = 'mod' | 'multiplex'
export type MuxEnv = { herdr?: string; tmux?: string; zellij?: string }

/** The multiplexer this session runs in: herdr, tmux or zellij, else null. */
export function detectMux(env: MuxEnv): Mux | null {
  if (env.herdr) return 'herdr'
  if (env.tmux) return 'tmux'
  if (env.zellij) return 'zellij'
  return null
}

/** The `display` option as it applies: `mod` / `multiplex` as set; unset
 * (or `auto`): `multiplex` inside a multiplexer, else `mod`. */
export function resolveDisplay(option: unknown, env: MuxEnv): Display {
  if (option === 'mod' || option === 'multiplex') return option
  return detectMux(env) === null ? 'mod' : 'multiplex'
}

/** The `display` values a person sets: auto picks by the multiplexer rule. */
export const DISPLAYS = ['mod', 'multiplex', 'auto'] as const
export type DisplayChoice = (typeof DISPLAYS)[number]

export function isDisplayChoice(value: unknown): value is DisplayChoice {
  return typeof value === 'string' && (DISPLAYS as readonly string[]).includes(value)
}

/** Where a display setting stands: the first source that holds a value, by
 * precedence (a value that is not a display choice counts as `auto`). */
export function pickDisplay(sources: readonly (readonly [source: string, value: unknown])[], fallback: string):
  { choice: DisplayChoice; source: string } {
  for (const [source, value] of sources) {
    if (typeof value === 'string' && value !== '') return { choice: isDisplayChoice(value) ? value : 'auto', source }
  }
  return { choice: 'auto', source: fallback }
}

/** What auto resolves to here, in words: `multiplex (herdr detected)`. */
export function autoWords(env: MuxEnv): string {
  const mux = detectMux(env)
  return mux === null ? 'mod (no multiplexer detected)' : `multiplex (${mux} detected)`
}

/** The display reply every viewer plugin gives (docs/tools.md, the viewer
 * plugin contract): `display: auto → multiplex (herdr detected) · from SOURCE`,
 * or for a value set outright `display: mod · from SOURCE · auto here → …`. */
export function displayReport(choice: DisplayChoice, source: string, env: MuxEnv): string {
  return choice === 'auto'
    ? `display: auto → ${autoWords(env)} · from ${source}`
    : `display: ${choice} · from ${source} · auto here → ${autoWords(env)}`
}

/** `/sigil-pane display [VALUE]`: null when the words are not that command;
 * `{}` asks for the setting, `{ choice }` sets it; a bad value is named. */
export function parseDisplayArgs(args: string): { choice?: DisplayChoice } | { error: string } | null {
  const words = args.trim().split(/\s+/).filter(w => w !== '')
  if (words[0] !== 'display') return null
  if (words.length > 2) return { error: `display takes one value: ${DISPLAYS.join(', ')}` }
  const value = words[1]
  if (value === undefined) return {}
  if (!isDisplayChoice(value)) return { error: `display must be one of ${DISPLAYS.join(', ')} (got "${value}")` }
  return { choice: value }
}

/** The `layout` values a person sets (view.py's --layout): wrap fits the
 * drawing to the pane and lets it grow down, pan keeps its natural layout and
 * pans across, auto picks whichever overflows less (view.py's pick_layout). */
export const LAYOUTS = ['auto', 'wrap', 'pan'] as const
export type LayoutChoice = (typeof LAYOUTS)[number]

export function isLayoutChoice(value: unknown): value is LayoutChoice {
  return typeof value === 'string' && (LAYOUTS as readonly string[]).includes(value)
}

/** The `layout` option as it applies: a choice as set, anything else auto. */
export function layoutOf(option: unknown): LayoutChoice {
  return isLayoutChoice(option) ? option : 'auto'
}

/** Where a layout setting stands, as pickDisplay does for display. */
export function pickLayout(sources: readonly (readonly [source: string, value: unknown])[], fallback: string):
  { choice: LayoutChoice; source: string } {
  for (const [source, value] of sources) {
    if (typeof value === 'string' && value !== '') return { choice: layoutOf(value), source }
  }
  return { choice: 'auto', source: fallback }
}

/** The layout reply every viewer plugin gives (docs/tools.md, the viewer plugin
 * contract): `layout: auto → pan (the drawing shown) · from SOURCE`, or for a
 * value set outright `layout: wrap · from SOURCE`; `shown`: what the drawing on
 * screen was drawn as, when there is one. */
export function layoutReport(choice: LayoutChoice, source: string, shown?: string): string {
  const now = choice === 'auto' && shown ? ` → ${shown} (the drawing shown)` : ''
  return `layout: ${choice}${now} · from ${source}`
}

/** `/sigil-pane layout [VALUE]`: null when the words are not that command;
 * `{}` asks for the setting, `{ choice }` sets it; a bad value is named. */
export function parseLayoutArgs(args: string): { choice?: LayoutChoice } | { error: string } | null {
  const words = args.trim().split(/\s+/).filter(w => w !== '')
  if (words[0] !== 'layout') return null
  if (words.length > 2) return { error: `layout takes one value: ${LAYOUTS.join(', ')}` }
  const value = words[1]
  if (value === undefined) return {}
  if (!isLayoutChoice(value)) return { error: `layout must be one of ${LAYOUTS.join(', ')} (got "${value}")` }
  return { choice: value }
}

/** frame: a frame of the run (view.py's numbering, -1: the last). */
export type Asked = { request: ViewRequest; frame?: number; play?: boolean }

function wholeOf(value: unknown): number | undefined {
  const n = typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : value
  return typeof n === 'number' && Number.isInteger(n) && n >= 0 ? n : undefined
}

function depthOf(value: unknown): number | undefined {
  if (value === 'all') return ALL_DEPTH
  const n = wholeOf(value)
  return n === undefined ? undefined : Math.min(n, ALL_DEPTH)
}

/** A tool call's (or /sigil's) input over the request shown before: a field
 * left out keeps its value, `scenario: ""` ends the run. */
export function parseRequest(input: Record<string, unknown>, previous: ViewRequest | null): Asked | { error: string } {
  const file = typeof input.file === 'string' && input.file !== '' ? input.file : previous?.file
  if (file === undefined) return { error: 'name the Sigil file to show (file)' }
  const view = input.view ?? previous?.view ?? DEFAULT_VIEW
  if (!VIEWS.includes(view as ViewName)) return { error: `view must be one of ${VIEWS.join(', ')}` }
  const depth = input.depth === undefined ? (previous?.depth ?? 1) : depthOf(input.depth)
  if (depth === undefined) return { error: 'depth must be a whole number or "all"' }
  const kept = input.scenario === undefined && file === previous?.file ? previous.scenario : undefined
  const scenario = typeof input.scenario === 'string' ? input.scenario : kept
  const request: ViewRequest = { file, view: view as ViewName, depth }
  if (scenario) request.scenario = scenario
  const payloads = typeof input.payloads === 'boolean' ? input.payloads : previous?.payloads
  if (payloads) request.payloads = true
  const asked: Asked = { request }
  if (input.frame !== undefined) {
    const frame = wholeOf(input.frame)
    if (frame === undefined && input.frame !== 'last') return { error: 'frame must be a whole number or "last"' }
    asked.frame = input.frame === 'last' ? -1 : frame
  }
  if (typeof input.play === 'boolean') asked.play = input.play
  return asked
}

/** /sigil's words as tool input: `FILE`, a view name, `depth N|all`,
 * `sim SCENARIO`, `frame N|last`, `play`, `payloads`, in any order. `display
 * [VALUE]` and `layout [VALUE]` are commands of their own (parseDisplayArgs,
 * parseLayoutArgs), never a file name. */
export function parseCommandArgs(args: string): Record<string, unknown> {
  const words = args.trim().split(/\s+/).filter(w => w !== '')
  const out: Record<string, unknown> = {}
  for (let i = 0; i < words.length; i++) {
    const word = words[i] ?? ''
    const value = words[i + 1]
    if ((VIEWS as readonly string[]).includes(word)) out.view = word
    else if (word === 'play') out.play = true
    else if (word === 'payloads') out.payloads = true
    else if (word === 'display') {
      out.display = isDisplayChoice(value) ? value : ''
      if (isDisplayChoice(value)) i++
    }
    else if (word === 'layout') {
      out.layout = isLayoutChoice(value) ? value : ''
      if (isLayoutChoice(value)) i++
    }
    else if ((word === 'depth' || word === 'sim' || word === 'frame') && value !== undefined) {
      out[word === 'sim' ? 'scenario' : word] = value
      i++
    } else out.file = word
  }
  return out
}

/** `python3 pane.py draw …` for a request at a width; `layout` (auto when
 * left out) and the pane's `height`, which auto picks by. */
export function drawArgv(script: string, request: ViewRequest, width: number,
                         pane: { layout?: LayoutChoice; height?: number } = {}): string[] {
  const argv = ['python3', script, 'draw', request.file, '--view', request.view, '--depth', String(request.depth), '--width', String(width)]
  if (pane.layout && pane.layout !== 'auto') argv.push('--layout', pane.layout)
  if (pane.height) argv.push('--height', String(pane.height))
  if (request.scenario) argv.push('--scenario', request.scenario)
  if (request.payloads) argv.push('--payloads')
  return argv
}

/** Where the split's view.py starts a request's run, as the pane shows a new
 * run: `frame` (-1: the last), else the last frame, or the first when it plays. */
export function splitStart(asked: Asked): { frame: number; play: boolean } {
  const play = asked.play === true
  return { frame: asked.frame ?? (play ? 0 : -1), play }
}

/** view.py's own flags for the live view the split runs (`layout`: its
 * --layout, left out for auto, view.py's own default; `start`: where its run
 * starts (--frame, --play), for a request with a scenario). */
export function viewArgv(request: ViewRequest, layout: LayoutChoice = 'auto',
                         start?: { frame: number; play: boolean }): string[] {
  const argv = [request.file, '--depth', request.depth >= ALL_DEPTH ? 'all' : String(request.depth)]
  if (request.view !== DEFAULT_VIEW) argv.push(`--${request.view}`)
  if (layout !== 'auto') argv.push('--layout', layout)
  if (request.scenario) argv.push('--sim', request.scenario)
  if (request.scenario && start) {
    argv.push('--frame', start.frame < 0 ? 'last' : String(start.frame))
    if (start.play) argv.push('--play')
  }
  if (request.payloads) argv.push('--payloads')
  return argv
}

/** Packed rows cut to columns from … from+width-1: a panned drawing's window. */
export function cropRows(rows: readonly PackedRow[], from: number, width: number): PackedRow[] {
  if (from <= 0 && rows.every(row => row.reduce((n, [text]) => n + [...text].length, 0) <= width)) return [...rows]
  return rows.map(row => {
    const out: PackedRow = []
    let x = 0
    for (const [text, id] of row) {
      const cells = [...text]
      const lo = Math.max(from - x, 0)
      const hi = Math.min(from + width - x, cells.length)
      if (hi > lo) out.push([cells.slice(lo, hi).join(''), id])
      x += cells.length
    }
    return out
  })
}

/** Where a pan to the right / left by `step` lands, kept within a drawing
 * `drawn` wide in a pane `width` wide. */
export function panTo(at: number, step: number, drawn: number, width: number): number {
  return Math.max(0, Math.min(at + step, Math.max(drawn - width, 0)))
}

/** An argv as one POSIX shell line (herdr runs a pane's command as typed). */
export function shellQuote(argv: readonly string[]): string {
  return argv.map(a => (/^[\w@%+=:,./-]+$/.test(a) ? a : `'${a.replaceAll("'", `'\\''`)}'`)).join(' ')
}

/** The command that opens a split to the right running `follow` (herdr: the
 * split alone; the follow line is then run in the pane it names). */
export function splitArgv(mux: Mux, follow: readonly string[], herdrPane?: string): string[] {
  if (mux === 'tmux') return ['tmux', 'split-window', '-h', '-d', '-P', '-F', '#{pane_id}', '--', ...follow]
  if (mux === 'zellij') return ['zellij', 'run', '--direction', 'right', '--close-on-exit', '--name', 'sigil', '--', ...follow]
  return ['herdr', 'pane', 'split', ...(herdrPane ? [herdrPane] : ['--current']), '--direction', 'right', '--no-focus']
}

/** Waits until a new herdr pane's shell has drawn anything (its prompt): a
 * command sent by `herdr pane run` before then is lost. */
export function herdrReadyArgv(pane: string): string[] {
  return ['herdr', 'pane', 'wait-output', pane, '--regex', '\\S', '--source', 'visible']
}

/** The new pane's id in `herdr pane split`'s JSON reply. */
export function herdrPaneOf(stdout: string): string | undefined {
  try {
    const id = JSON.parse(stdout)?.result?.pane?.pane_id
    return typeof id === 'string' ? id : undefined
  } catch {
    return undefined
  }
}

/** `pane.py draw`'s stdout as a Drawing, or the error it reported. */
export function parseDrawing(stdout: string): Drawing | { error: string } {
  try {
    const data = JSON.parse(stdout)
    if (typeof data?.error === 'string') return { error: data.error }
    if (Array.isArray(data?.frames) && Array.isArray(data?.styles)) return data as Drawing
  } catch {
    // fall through
  }
  return { error: 'pane.py printed no drawing' }
}

/** The frame a playback shows, clamped to the run. */
export function frameIndex(drawing: Drawing, playback: Playback): number {
  return Math.max(0, Math.min(playback.at, drawing.frames.length - 1))
}

/** The drawn frame that shows a frame of the run (`frame`: view.py's numbering,
 * as a request and the split take it; -1 or past the end: the last). A long
 * run is sampled (pane.py's `at`): the latest drawn frame at or before it. */
export function drawnFrame(drawing: Drawing, frame: number): number {
  const last = drawing.frames.length - 1
  if (frame < 0) return last
  if (drawing.at === undefined) return Math.min(frame, last)
  let i = 0
  while (i < last && (drawing.at[i + 1] ?? Infinity) <= frame) i++
  return i
}

/** `frame N/M` in the run's own numbering (from 1) for a drawn frame. */
function frameText(drawing: Drawing, at: number, of: string): string {
  const n = drawing.at?.[at] ?? at
  const all = drawing.last !== undefined ? drawing.last + 1 : drawing.frames.length
  return `frame ${n + 1}${of}${all}`
}

/** The views in `t` order (the viewer's): graph → tree → flow → run → graph. */
export function nextView(view: ViewName): ViewName {
  return VIEWS[(VIEWS.indexOf(view) + 1) % VIEWS.length] ?? 'graph'
}

/** A speed `delta` steps faster (+) or slower (-), kept within SPEEDS. */
export function nextSpeed(speed: number, delta: number): number {
  return Math.max(0, Math.min(speed + delta, SPEEDS.length - 1))
}

/** A played run's frame time in milliseconds at a speed. */
export function frameMs(speed: number): number {
  return 1000 / (SPEEDS[speed] ?? SPEEDS[START_SPEED]!)
}

/** A speed as view.py's status bar writes it: `2 frames/s`, `½ frame/s`. */
export function speedText(speed: number): string {
  const fps = SPEEDS[speed] ?? SPEEDS[START_SPEED]!
  const n = fps === 0.25 ? '¼' : fps === 0.5 ? '½' : String(fps)
  return `${n} frame${fps > 1 ? 's' : ''}/s`
}

/** The depths in `d` order: 0 → 1 → all → 0. */
export function nextDepth(depth: number): number {
  return depth === 0 ? 1 : depth === 1 ? ALL_DEPTH : 0
}

export function colourOf(hex: string | null): number {
  if (hex === null) return DEFAULT_COLOUR
  const m = /^#([0-9a-f]{6}|[0-9a-f]{3})$/i.exec(hex)
  if (m === null || m[1] === undefined) return DEFAULT_COLOUR
  const h = m[1].length === 3 ? [...m[1]].map(c => c + c).join('') : m[1]
  return parseInt(h, 16)
}

/** The widest row of packed rows, in cells. */
export function rowsWidth(rows: readonly PackedRow[]): number {
  let widest = 0
  for (const row of rows) {
    let n = 0
    for (const [text] of row) n += [...text].length
    widest = Math.max(widest, n)
  }
  return widest
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

export function base64(bytes: Uint8Array): string {
  let out = ''
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i] ?? 0
    const b = bytes[i + 1] ?? 0
    const c = bytes[i + 2] ?? 0
    const n = (a << 16) | (b << 8) | c
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]!
    out += i + 1 < bytes.length ? B64[(n >> 6) & 63]! : '='
    out += i + 2 < bytes.length ? B64[n & 63]! : '='
  }
  return out
}

/** Packed rows as a Raster's `cells` over `columns` × rows.length: each
 * character one cell in its style's colours, short rows padded blank. */
export function rasterCells(rows: readonly PackedRow[], styles: readonly Style[], columns: number): string {
  const words = new Uint32Array(columns * rows.length * 3)
  const space = 0x20
  for (let i = 0; i < columns * rows.length; i++) words.set([space, DEFAULT_COLOUR, DEFAULT_COLOUR], i * 3)
  rows.forEach((row, y) => {
    let x = 0
    for (const [text, id] of row) {
      const [fg, bg] = styles[id] ?? [null, null, false]
      const fore = colourOf(fg)
      const back = colourOf(bg)
      for (const ch of text) {
        if (x >= columns) break
        const code = ch.codePointAt(0) ?? space
        words.set([code > 0xffff || code < 0x20 ? 0x3f : code, fore, back], (y * columns + x) * 3)
        x++
      }
    }
  })
  return base64(new Uint8Array(words.buffer))
}

/** Rows cut into Raster-sized slices (a Raster is at most RASTER_ROWS tall). */
export function slices<T>(rows: readonly T[], size: number = RASTER_ROWS): T[][] {
  const out: T[][] = []
  for (let i = 0; i < rows.length; i += size) out.push(rows.slice(i, i + size))
  return out
}

/** The pane's status line for a frame: file · view · depth, then the run:
 * played or paused at its speed (an index into SPEEDS), as view.py's bar. */
export function statusLine(drawing: Drawing, request: ViewRequest, at: number, isPlaying: boolean,
                           speed: number = START_SPEED): string {
  const depth = request.depth >= ALL_DEPTH ? 'all' : String(request.depth)
  const head = `${drawing.file} · ${drawing.view} · depth ${depth}${drawing.layout ? ` · ${drawing.layout}` : ''}`
  const run = drawing.status?.[at]
  if (run === undefined) return head
  return `${head} · ${isPlaying ? '▶' : '❚❚'} ${speedText(speed)} · ${run} · ${frameText(drawing, at, '/')}`
}

/** A run's lines under the drawing at a frame, as view.py's rows under its
 * footer: `path` and the episode's hops so far — view.py's styled rows (the hop
 * now bold) when pane.py sent them, else the text (`trail`) — then `›` and the
 * narration line (the run's log line from a pane.py that has none). null for a
 * still. */
export function runLines(drawing: Drawing, at: number): { trail: string; path: PackedRow[] | null; now: string } | null {
  if (drawing.status === undefined) return null
  const now = drawing.say?.[at] ?? drawing.log?.[at] ?? ''
  return { trail: `path   ${drawing.trail?.[at] ?? ''}`, path: drawing.path?.[at] ?? null, now: `› ${now}` }
}

/** What the tool answers the agent: what is drawn and where, in words. */
export function replyText(drawing: Drawing, at: number, isPlaying: boolean, where: string): string {
  const lines = [where, drawing.summary, ...drawing.lint]
  if (drawing.status !== undefined) {
    lines.push(`${isPlaying ? 'playing' : 'paused at'} ${drawing.status[at] ?? ''} (${frameText(drawing, at, ' of ')})`)
    const say = drawing.say?.[at]
    const log = drawing.log?.[at]
    if (say) lines.push(`now: ${say}`)
    else if (log) lines.push(`log: ${log}`)
    const trail = drawing.trail?.[at]
    if (trail) lines.push(`path: ${trail}`)
    if (drawing.outcome !== undefined) lines.push(`outcome of the whole run: ${drawing.outcome}`)
  }
  if (drawing.scenarios.length > 0) lines.push(`scenarios: ${drawing.scenarios.join(', ')}`)
  return lines.join('\n')
}
