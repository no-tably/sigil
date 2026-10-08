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
// A run is drawn a window at a time (pane.py's --from / --count), every frame of it.
export const WINDOW = 120 // run frames one draw holds: pane.py's WINDOW
export const WINDOW_BACK = 8 // frames a window keeps before the one it is drawn for (a step back stays in it)
// A playing run draws the window after its own as soon as it plays (`ahead`),
// so the run goes on from it without waiting at the window's end.

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
 * left out), the pane's `height`, which auto picks by, and for a run the
 * window's first frame `from` (windowStart; -1: the window that ends the run). */
export function drawArgv(script: string, request: ViewRequest, width: number,
                         pane: { layout?: LayoutChoice; height?: number; from?: number } = {}): string[] {
  const argv = ['python3', script, 'draw', request.file, '--view', request.view, '--depth', String(request.depth), '--width', String(width)]
  if (pane.layout && pane.layout !== 'auto') argv.push('--layout', pane.layout)
  if (pane.height) argv.push('--height', String(pane.height))
  if (request.scenario) argv.push('--scenario', request.scenario)
  if (request.scenario && pane.from !== undefined && pane.from !== 0) {
    argv.push('--from', pane.from < 0 ? 'last' : String(pane.from), '--count', String(WINDOW))
  }
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

/** The run's last frame (a still: 0). A playback's `at` is a frame of the
 * run, numbered as view.py numbers them; the drawing holds a window of them. */
export function lastFrame(drawing: Drawing): number {
  return drawing.last ?? drawing.frames.length - 1
}

/** The frame a playback shows, clamped to the run. */
export function frameIndex(drawing: Drawing, playback: Playback): number {
  return Math.max(0, Math.min(playback.at, lastFrame(drawing)))
}

/** The frame of the run a request names (`frame`: view.py's numbering, as a
 * request and the split take it; -1 or past the end: the last). */
export function drawnFrame(drawing: Drawing, frame: number): number {
  const last = lastFrame(drawing)
  return frame < 0 || frame > last ? last : frame
}

/** Whether the drawing's window holds a frame of the run. */
export function holds(drawing: Drawing, frame: number): boolean {
  const i = frame - (drawing.first ?? 0)
  return i >= 0 && i < drawing.frames.length
}

/** The index into the drawing's per-frame lists (frames, status, …) of a frame
 * of the run: the nearest frame its window holds. */
export function slot(drawing: Drawing, frame: number): number {
  return Math.max(0, Math.min(frame - (drawing.first ?? 0), drawing.frames.length - 1))
}

/** The window's first frame to draw for showing a frame of the run (-1: the
 * last, so the window that ends the run). */
export function windowStart(frame: number): number {
  return frame < 0 ? -1 : Math.max(0, frame - WINDOW_BACK)
}

/** The last frame of the run the drawing's window holds. */
function windowEnd(drawing: Drawing): number {
  return (drawing.first ?? 0) + drawing.frames.length - 1
}

/** The window to draw for showing `frame` (windowStart), or null when the
 * drawing holds it (or is a still). */
export function windowFor(drawing: Drawing, frame: number): number | null {
  if (drawing.status === undefined || holds(drawing, frame)) return null
  return windowStart(frame)
}

/** The window a playing run draws ahead, while it plays its own: the one
 * after the drawing's (windowStart of the frame past its end), or null —
 * paused, a still, or a window that ends the run. */
export function aheadFrom(drawing: Drawing, isPlaying: boolean): number | null {
  if (!isPlaying || drawing.status === undefined) return null
  const end = windowEnd(drawing)
  return end < lastFrame(drawing) ? windowStart(end + 1) : null
}

/** A window drawn ahead, with the drawKey it was drawn for. */
export type Ahead = { key: string; drawing: Drawing }

/** The drawing to show `frame` from: `shown`, or the window drawn ahead once
 * the frame has left shown's window and ahead (drawn for `key`, what shown is
 * drawn for now) holds it. */
export function heldBy(shown: Drawing, ahead: Ahead | null, key: string, frame: number): Drawing {
  if (holds(shown, frame) || ahead === null || ahead.key !== key || !holds(ahead.drawing, frame)) return shown
  return ahead.drawing
}

/** A playing run's next tick: a frame on, or held where it is while the next
 * frame's window is still being drawn; it stops at the run's end. */
export function playTick(drawing: Drawing, playback: Playback): Playback {
  const last = lastFrame(drawing)
  const at = Math.min(frameIndex(drawing, playback) + 1, last)
  if (!holds(drawing, at)) return playback
  return { at, isPlaying: at < last }
}

/** The frame of the run a request starts at before it is drawn: `frame` (-1:
 * the last), else a new run's first (playing) or last frame, else where it was. */
export function askedFrame(asked: Asked, before: Playback, isNewRun: boolean): number {
  if (asked.frame !== undefined) return asked.frame
  return isNewRun ? (asked.play ? 0 : -1) : before.at
}

/** The playback a request asks for over the drawing: askedFrame, `play` from
 * there (a run played from its end starts again). */
export function playbackFor(asked: Asked, shown: Drawing, before: Playback, isNewRun: boolean): Playback {
  const last = lastFrame(shown)
  const at = drawnFrame(shown, askedFrame(asked, before, isNewRun))
  const isPlaying = asked.play ?? (isNewRun ? false : before.isPlaying)
  return { at: isPlaying && at >= last && asked.frame === undefined ? 0 : at, isPlaying: isPlaying && last > 0 }
}

/** `frame N/M` in the run's own numbering (from 1) for a frame of the run. */
function frameText(drawing: Drawing, at: number, of: string): string {
  return `frame ${at + 1}${of}${lastFrame(drawing) + 1}`
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

// Drawn width, the rule of view.py's viewkit.char_cells: a wide character
// (East Asian Width W or F) takes two terminal columns, a combining mark or a
// zero-width character none, any other one. Packed rows need none of this —
// pane.py already makes every character in them one cell (a wide one itself
// then WIDE_TAIL) — but plain text (a status, narration, summary or lint line)
// keeps its names as written and is measured by it.

/** Inclusive [first, last] code point pairs that are W or F (combining marks
 * left out), written from Python's unicodedata by tools/wide_table.py
 * (tests/test_plugin_cells.py checks it). */
const WIDE: readonly number[] = [
  0x1100, 0x115f, 0x231a, 0x231b, 0x2329, 0x232a, 0x23e9, 0x23ec, 0x23f0, 0x23f0, 0x23f3, 0x23f3,
  0x25fd, 0x25fe, 0x2614, 0x2615, 0x2648, 0x2653, 0x267f, 0x267f, 0x2693, 0x2693, 0x26a1, 0x26a1,
  0x26aa, 0x26ab, 0x26bd, 0x26be, 0x26c4, 0x26c5, 0x26ce, 0x26ce, 0x26d4, 0x26d4, 0x26ea, 0x26ea,
  0x26f2, 0x26f3, 0x26f5, 0x26f5, 0x26fa, 0x26fa, 0x26fd, 0x26fd, 0x2705, 0x2705, 0x270a, 0x270b,
  0x2728, 0x2728, 0x274c, 0x274c, 0x274e, 0x274e, 0x2753, 0x2755, 0x2757, 0x2757, 0x2795, 0x2797,
  0x27b0, 0x27b0, 0x27bf, 0x27bf, 0x2b1b, 0x2b1c, 0x2b50, 0x2b50, 0x2b55, 0x2b55, 0x2e80, 0x2e99,
  0x2e9b, 0x2ef3, 0x2f00, 0x2fd5, 0x2ff0, 0x2ffb, 0x3000, 0x3029, 0x302e, 0x303e, 0x3041, 0x3096,
  0x309b, 0x30ff, 0x3105, 0x312f, 0x3131, 0x318e, 0x3190, 0x31e3, 0x31f0, 0x321e, 0x3220, 0x3247,
  0x3250, 0x4dbf, 0x4e00, 0xa48c, 0xa490, 0xa4c6, 0xa960, 0xa97c, 0xac00, 0xd7a3, 0xf900, 0xfaff,
  0xfe10, 0xfe19, 0xfe30, 0xfe52, 0xfe54, 0xfe66, 0xfe68, 0xfe6b, 0xff01, 0xff60, 0xffe0, 0xffe6,
  0x16fe0, 0x16fe3, 0x16ff0, 0x16ff1, 0x17000, 0x187f7, 0x18800, 0x18cd5, 0x18d00, 0x18d08,
  0x1aff0, 0x1aff3, 0x1aff5, 0x1affb, 0x1affd, 0x1affe, 0x1b000, 0x1b122, 0x1b132, 0x1b132,
  0x1b150, 0x1b152, 0x1b155, 0x1b155, 0x1b164, 0x1b167, 0x1b170, 0x1b2fb, 0x1f004, 0x1f004,
  0x1f0cf, 0x1f0cf, 0x1f18e, 0x1f18e, 0x1f191, 0x1f19a, 0x1f200, 0x1f202, 0x1f210, 0x1f23b,
  0x1f240, 0x1f248, 0x1f250, 0x1f251, 0x1f260, 0x1f265, 0x1f300, 0x1f320, 0x1f32d, 0x1f335,
  0x1f337, 0x1f37c, 0x1f37e, 0x1f393, 0x1f3a0, 0x1f3ca, 0x1f3cf, 0x1f3d3, 0x1f3e0, 0x1f3f0,
  0x1f3f4, 0x1f3f4, 0x1f3f8, 0x1f43e, 0x1f440, 0x1f440, 0x1f442, 0x1f4fc, 0x1f4ff, 0x1f53d,
  0x1f54b, 0x1f54e, 0x1f550, 0x1f567, 0x1f57a, 0x1f57a, 0x1f595, 0x1f596, 0x1f5a4, 0x1f5a4,
  0x1f5fb, 0x1f64f, 0x1f680, 0x1f6c5, 0x1f6cc, 0x1f6cc, 0x1f6d0, 0x1f6d2, 0x1f6d5, 0x1f6d7,
  0x1f6dc, 0x1f6df, 0x1f6eb, 0x1f6ec, 0x1f6f4, 0x1f6fc, 0x1f7e0, 0x1f7eb, 0x1f7f0, 0x1f7f0,
  0x1f90c, 0x1f93a, 0x1f93c, 0x1f945, 0x1f947, 0x1f9ff, 0x1fa70, 0x1fa7c, 0x1fa80, 0x1fa88,
  0x1fa90, 0x1fabd, 0x1fabf, 0x1fac5, 0x1face, 0x1fadb, 0x1fae0, 0x1fae8, 0x1faf0, 0x1faf8,
  0x20000, 0x2fffd, 0x30000, 0x3fffd,
]
const ZERO_WIDTH = /^[\p{Mn}\p{Me}​‌‍⁠﻿]$/u

/** The columns one character (one code point) takes: 2, 0 or 1. */
export function charCells(ch: string): number {
  const code = ch.codePointAt(0) ?? 0
  if (code < 0x80) return 1
  if (ZERO_WIDTH.test(ch)) return 0
  let lo = 0
  let hi = WIDE.length / 2 - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (code < WIDE[mid * 2]!) hi = mid - 1
    else if (code > WIDE[mid * 2 + 1]!) lo = mid + 1
    else return 2
  }
  return 1
}

/** The terminal columns `text` takes. */
export function cellWidth(text: string): number {
  let n = 0
  for (const ch of text) n += charCells(ch)
  return n
}

/** `text` cut to at most `width` columns (a wide character that would cross
 * the edge is left out, with the marks that follow it). */
export function cutCells(text: string, width: number): string {
  let out = ''
  let n = 0
  for (const ch of text) {
    n += charCells(ch)
    if (n > width) break
    out += ch
  }
  return out
}

/** A wide character's second cell in a packed row: pane.py writes a wide
 * character as itself then this, so every character of a packed row is one
 * cell and cutting, panning and measuring count characters. */
export const WIDE_TAIL = '\u0000'

/** A packed row's text (a run of it) as terminal text: each wide character
 * with its WIDE_TAIL as the one glyph; a tail whose glyph was cut off (a pan:
 * the run's first cell) and a glyph whose tail was (the edge: its last) as a
 * blank, so the text keeps its cells. */
export function glyphs(text: string): string {
  const cells = [...text]
  if (cells[0] === WIDE_TAIL) cells[0] = ' '
  const last = cells.length - 1
  if (last >= 0 && charCells(cells[last]!) === 2) cells[last] = ' '
  return cells.join('').replaceAll(WIDE_TAIL, '')
}

/** Whether packed rows hold a wide character (a Raster cell is one column:
 * such rows are drawn as text). */
export function holdsWide(rows: readonly PackedRow[]): boolean {
  return rows.some(row => row.some(([text]) => text.includes(WIDE_TAIL)))
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
 * character one cell in its style's colours, short rows padded blank. A
 * Raster cell takes one-column BMP characters only: a wide character's two
 * cells (holdsWide rows are drawn as text instead) would be `?` and blank. */
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
        const glyph = ch === WIDE_TAIL ? space : code > 0xffff || code < 0x20 || charCells(ch) !== 1 ? 0x3f : code
        words.set([glyph, fore, back], (y * columns + x) * 3)
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
  const run = drawing.status?.[slot(drawing, at)]
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
  const i = slot(drawing, at)
  const now = drawing.say?.[i] ?? drawing.log?.[i] ?? ''
  return { trail: `path   ${drawing.trail?.[i] ?? ''}`, path: drawing.path?.[i] ?? null, now: `› ${now}` }
}

/** What the tool answers the agent: what is drawn and where, in words. */
export function replyText(drawing: Drawing, at: number, isPlaying: boolean, where: string): string {
  const lines = [where, drawing.summary, ...drawing.lint]
  if (drawing.status !== undefined) {
    const i = slot(drawing, at)
    lines.push(`${isPlaying ? 'playing' : 'paused at'} ${drawing.status[i] ?? ''} (${frameText(drawing, at, ' of ')})`)
    const say = drawing.say?.[i]
    const log = drawing.log?.[i]
    if (say) lines.push(`now: ${say}`)
    else if (log) lines.push(`log: ${log}`)
    const trail = drawing.trail?.[i]
    if (trail) lines.push(`path: ${trail}`)
    if (drawing.outcome !== undefined) lines.push(`outcome of the whole run: ${drawing.outcome}`)
  }
  if (drawing.scenarios.length > 0) lines.push(`scenarios: ${drawing.scenarios.join(', ')}`)
  return lines.join('\n')
}
