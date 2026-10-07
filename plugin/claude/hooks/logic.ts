// The mod's pure half: requests, argv, the display choice, the multiplexer
// commands and the cell packing. No `$` here, so the tests drive it directly.

import type { Drawing, Mux, PackedRow, Playback, Style, ViewName, ViewRequest } from '../types'

export const PANE = 'sigil'
export const TOOL = 'view'
export const COMMAND = 'sigil-pane' // /sigil is the skill's own
export const VIEWS: readonly ViewName[] = ['graph', 'tree', 'flow']
export const ALL_DEPTH = 99
export const UNASKED_COLUMNS = 144 // the engine's floor for a pane opened unasked
export const DEFAULT_WIDTH = 100 // the width drawn for before the pane has measured
export const RASTER_ROWS = 256 // a Raster's tallest; a taller drawing is several
export const RASTER_COLUMNS = 512
export const DEFAULT_COLOUR = 0x01000000 // the terminal's own colour

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

export type Asked = { request: ViewRequest; frame?: number; play?: boolean }

function depthOf(value: unknown): number | undefined {
  if (value === 'all') return ALL_DEPTH
  const n = typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : value
  return typeof n === 'number' && Number.isInteger(n) && n >= 0 ? Math.min(n, ALL_DEPTH) : undefined
}

/** A tool call's (or /sigil's) input over the request shown before: a field
 * left out keeps its value, `scenario: ""` ends the run. */
export function parseRequest(input: Record<string, unknown>, previous: ViewRequest | null): Asked | { error: string } {
  const file = typeof input.file === 'string' && input.file !== '' ? input.file : previous?.file
  if (file === undefined) return { error: 'name the Sigil file to show (file)' }
  const view = input.view ?? previous?.view ?? 'graph'
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
    const frame = depthOf(input.frame)
    if (frame === undefined && input.frame !== 'last') return { error: 'frame must be a whole number or "last"' }
    asked.frame = input.frame === 'last' ? -1 : frame
  }
  if (typeof input.play === 'boolean') asked.play = input.play
  return asked
}

/** /sigil's words as tool input: `FILE`, a view name, `depth N|all`,
 * `sim SCENARIO`, `frame N|last`, `play`, `payloads`, in any order. */
export function parseCommandArgs(args: string): Record<string, unknown> {
  const words = args.trim().split(/\s+/).filter(w => w !== '')
  const out: Record<string, unknown> = {}
  for (let i = 0; i < words.length; i++) {
    const word = words[i] ?? ''
    const value = words[i + 1]
    if ((VIEWS as readonly string[]).includes(word)) out.view = word
    else if (word === 'play') out.play = true
    else if (word === 'payloads') out.payloads = true
    else if ((word === 'depth' || word === 'sim' || word === 'frame') && value !== undefined) {
      out[word === 'sim' ? 'scenario' : word] = value
      i++
    } else out.file = word
  }
  return out
}

/** `python3 pane.py draw …` for a request at a width. */
export function drawArgv(script: string, request: ViewRequest, width: number): string[] {
  const argv = ['python3', script, 'draw', request.file, '--view', request.view, '--depth', String(request.depth), '--width', String(width)]
  if (request.scenario) argv.push('--scenario', request.scenario)
  if (request.payloads) argv.push('--payloads')
  return argv
}

/** view.py's own flags for the live view the split runs. */
export function viewArgv(request: ViewRequest): string[] {
  const argv = [request.file, '--depth', request.depth >= ALL_DEPTH ? 'all' : String(request.depth)]
  if (request.view !== 'graph') argv.push(`--${request.view}`)
  if (request.scenario) argv.push('--sim', request.scenario)
  if (request.payloads) argv.push('--payloads')
  return argv
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

/** The views in `t` order: tree → graph → flow → tree. */
export function nextView(view: ViewName): ViewName {
  return view === 'tree' ? 'graph' : view === 'graph' ? 'flow' : 'tree'
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

/** The pane's status line for a frame: file · view · depth, then the run. */
export function statusLine(drawing: Drawing, request: ViewRequest, at: number, isPlaying: boolean): string {
  const depth = request.depth >= ALL_DEPTH ? 'all' : String(request.depth)
  const head = `${drawing.file} · ${drawing.view} · depth ${depth}`
  const run = drawing.status?.[at]
  if (run === undefined) return head
  return `${head} · ${isPlaying ? '▶' : '❚❚'} ${run} · frame ${at + 1}/${drawing.frames.length}`
}

/** A run's lines under the drawing at a frame, as view.py's rows under its
 * footer: `trail` and the episode's hops so far, then `›` and the narration
 * line (the run's log line from a pane.py that has none). null for a still. */
export function runLines(drawing: Drawing, at: number): { trail: string; now: string } | null {
  if (drawing.status === undefined) return null
  const now = drawing.say?.[at] ?? drawing.log?.[at] ?? ''
  return { trail: `trail  ${drawing.trail?.[at] ?? ''}`, now: `› ${now}` }
}

/** What the tool answers the agent: what is drawn and where, in words. */
export function replyText(drawing: Drawing, at: number, isPlaying: boolean, where: string): string {
  const lines = [where, drawing.summary, ...drawing.lint]
  if (drawing.status !== undefined) {
    lines.push(`${isPlaying ? 'playing' : 'paused at'} ${drawing.status[at] ?? ''} (frame ${at + 1} of ${drawing.frames.length})`)
    const say = drawing.say?.[at]
    const log = drawing.log?.[at]
    if (say) lines.push(`now: ${say}`)
    else if (log) lines.push(`log: ${log}`)
    const trail = drawing.trail?.[at]
    if (trail) lines.push(`trail: ${trail}`)
    if (drawing.outcome !== undefined) lines.push(`outcome of the whole run: ${drawing.outcome}`)
  }
  if (drawing.scenarios.length > 0) lines.push(`scenarios: ${drawing.scenarios.join(', ')}`)
  return lines.join('\n')
}
