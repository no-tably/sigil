// The mod's pure half: requests, argv, the display and layout choices, the
// multiplexer commands and the cell packing. No `$` here, so the tests drive it
// directly.

import type { Drawing, Mux, PackedRow, Playback, Style, ViewName, ViewRequest } from '../types'

export const PANE = 'sigil'
export const TOOL = 'view'
export const COMMAND = 'sigil-pane' // /sigil is the skill's own
export const VIEWS: readonly ViewName[] = ['graph', 'tree', 'flow', 'run']
export const DEFAULT_VIEW: ViewName = 'flow' // the viewer's DEFAULT_VIEW: the view it starts in
export const ALL_DEPTH = 99
export const UNASKED_COLUMNS = 144 // the engine's floor for a pane opened unasked
export const DEFAULT_WIDTH = 100 // the width drawn for before the pane has measured
export const SUPERSEDED = 'a later view request replaced this one before it drew'
export const RASTER_ROWS = 256 // a Raster's tallest; a taller drawing is several
export const RASTER_COLUMNS = 512
export const DEFAULT_COLOUR = 0x01000000 // the terminal's own colour
export const SPEEDS: readonly number[] = [0.25, 0.5, 1, 2, 4, 8, 16, 32] // frames a second: the viewer's SIM_SPEEDS
export const START_SPEED = 3 // 2 frames a second, the viewer's start (an index into SPEEDS)
// A run is drawn a window at a time (`sigil frames`' --from / --count), every frame of it.
export const WINDOW = 120 // run frames one draw holds: `sigil frames`' WINDOW
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
export function pickDisplay(sources: Sources, fallback: string): { choice: DisplayChoice; source: string } {
  return pickChoice(sources, fallback, v => (isDisplayChoice(v) ? v : 'auto'), 'auto')
}

/** A setting's sources by precedence: [where it is set, the value there]. */
export type Sources = readonly (readonly [source: string, value: unknown])[]

/** Where a setting stands: the first source that holds a value (`of` reads
 * it as a choice), else `unset` from `fallback`. */
function pickChoice<T>(sources: Sources, fallback: string, of: (value: string) => T, unset: T): { choice: T; source: string } {
  for (const [source, value] of sources) {
    if (typeof value === 'string' && value !== '') return { choice: of(value), source }
  }
  return { choice: unset, source: fallback }
}

/** `/sigil-pane OPTION [VALUE]` for an option taking one of `values`: null when
 * the words are not that command; `{}` asks for the setting, `{ choice }` sets
 * it; a bad value is named. */
function choiceArgs<T extends string>(option: string, values: readonly T[], args: string):
  { choice?: T } | { error: string } | null {
  const words = args.trim().split(/\s+/).filter(w => w !== '')
  if (words[0] !== option) return null
  if (words.length > 2) return { error: `${option} takes one value: ${values.join(', ')}` }
  const value = words[1]
  if (value === undefined) return {}
  if (!(values as readonly string[]).includes(value)) return { error: `${option} must be one of ${values.join(', ')} (got "${value}")` }
  return { choice: value as T }
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
  return choiceArgs('display', DISPLAYS, args)
}

/** The `layout` values a person sets (the viewer's --layout): wrap fits the
 * drawing to the pane and lets it grow down, pan keeps its natural layout and
 * pans across, auto picks whichever overflows less (the viewer's pick_layout). */
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
export function pickLayout(sources: Sources, fallback: string): { choice: LayoutChoice; source: string } {
  return pickChoice(sources, fallback, layoutOf, 'auto')
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
  return choiceArgs('layout', LAYOUTS, args)
}

/** The `placement` values a person sets: where the multiplex display opens
 * `sigil view` — a split beside this session (the default) or a tab of its own. */
export const PLACEMENTS = ['split', 'tab'] as const
export type Placement = (typeof PLACEMENTS)[number]

export function isPlacement(value: unknown): value is Placement {
  return typeof value === 'string' && (PLACEMENTS as readonly string[]).includes(value)
}

/** The `placement` option as it applies: a placement as set, anything else split. */
export function placementOf(option: unknown): Placement {
  return isPlacement(option) ? option : 'split'
}

/** Where a placement setting stands, as pickDisplay does for display. */
export function pickPlacement(sources: Sources, fallback: string): { choice: Placement; source: string } {
  return pickChoice(sources, fallback, placementOf, 'split')
}

/** The placement reply: `placement: tab · from SOURCE`. */
export function placementReport(choice: Placement, source: string): string {
  return `placement: ${choice} · from ${source}`
}

/** `/sigil-pane placement [VALUE]`, as parseDisplayArgs. */
export function parsePlacementArgs(args: string): { choice?: Placement } | { error: string } | null {
  return choiceArgs('placement', PLACEMENTS, args)
}

/** frame: a frame of the run (the viewer's numbering, -1: the last). */
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
 * [VALUE]`, `layout [VALUE]` and `placement [VALUE]` are commands of their own
 * (parseDisplayArgs, parseLayoutArgs, parsePlacementArgs), never a file name. */
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
    else if (word === 'placement') {
      out.placement = isPlacement(value) ? value : ''
      if (isPlacement(value)) i++
    }
    else if ((word === 'depth' || word === 'sim' || word === 'frame') && value !== undefined) {
      out[word === 'sim' ? 'scenario' : word] = value
      i++
    } else out.file = word
  }
  return out
}

/** `python3 bin/sigil frames draw …` for a request at a width; `layout` (auto when
 * left out), the pane's `height`, which auto picks by, and for a run the
 * window's first frame `from` (windowStart; -1: the window that ends the run). */
export function drawArgv(script: string, request: ViewRequest, width: number,
                         pane: { layout?: LayoutChoice; height?: number; from?: number } = {}): string[] {
  const argv = ['python3', script, 'frames', 'draw', request.file, '--view', request.view, '--depth', String(request.depth), '--width', String(width)]
  if (pane.layout && pane.layout !== 'auto') argv.push('--layout', pane.layout)
  if (pane.height) argv.push('--height', String(pane.height))
  if (request.scenario) argv.push('--scenario', request.scenario)
  if (request.scenario && pane.from !== undefined && pane.from !== 0) {
    argv.push('--from', pane.from < 0 ? 'last' : String(pane.from), '--count', String(WINDOW))
  }
  if (request.payloads) argv.push('--payloads')
  return argv
}

/** The split's loop, `python3 bin/sigil frames follow CONTROL`: it runs
 * `sigil view` live with the argv CONTROL holds, restarting it as CONTROL changes. */
export function followArgv(script: string, control: string): string[] {
  return ['python3', script, 'frames', 'follow', control]
}

/** Where the split's `sigil view` starts a request's run, as the pane shows a new
 * run: `frame` (-1: the last), else the last frame, or the first when it plays. */
export function splitStart(asked: Asked): { frame: number; play: boolean } {
  const play = asked.play === true
  return { frame: asked.frame ?? (play ? 0 : -1), play }
}

/** `sigil view`'s own flags for the live view the split runs (`layout`: its
 * --layout, left out for auto, the viewer's own default; `start`: where its run
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

/** The label a view's tab gets in every multiplexer. */
export const TAB_LABEL = 'sigil view'

/** Where a tab opens: the session's directory, herdr's workspace (the session's
 * own, herdrWorkspaceOf; left out, herdr picks), and the zellij layout file
 * that runs the follow line (zellijLayout, written beside the control file). */
export type TabPlace = { cwd: string; workspace?: string; layout: string }

/** The command that opens a tab of its own running `follow`, keeping this
 * session's tab in front where the multiplexer can (herdr: the tab alone; the
 * follow line is then run in the pane it names, as for a split). */
export function tabArgv(mux: Mux, follow: readonly string[], place: TabPlace): string[] {
  if (mux === 'tmux') return ['tmux', 'new-window', '-d', '-P', '-F', '#{pane_id}', '-n', TAB_LABEL, '-c', place.cwd, '--', ...follow]
  if (mux === 'zellij') return ['zellij', 'action', 'new-tab', '--name', TAB_LABEL, '--cwd', place.cwd, '--layout', place.layout]
  const workspace = place.workspace ? ['--workspace', place.workspace] : []
  return ['herdr', 'tab', 'create', ...workspace, '--cwd', place.cwd, '--label', TAB_LABEL, '--no-focus']
}

/** The zellij layout a view's tab opens with: one pane running `follow`,
 * closed when it exits (as the split's `--close-on-exit`). */
export function zellijLayout(follow: readonly string[]): string {
  const [command = '', ...args] = follow.map(a => `"${a.replaceAll('\\', '\\\\').replaceAll('"', '\\"')}"`)
  return `layout {\n    pane name="sigil" command=${command} close_on_exit=true {\n        args ${args.join(' ')}\n    }\n}\n`
}

/** The split's control file. It names the command line `sigil view` runs, and a
 * `--dialect` there is Python code, so a host keeps it private: in a directory of
 * its own only this user can enter (0700, `privateDirArgv` or mkdtemp), with mode
 * 0600 (`privateWriteArgv`); `sigil frames follow` refuses one another user could
 * write. Its directory's name starts with CONTROL_PREFIX, so follow removes it
 * once it has emptied it. */
export const CONTROL_PREFIX = 'sigil-view-'
export const CONTROL_NAME = 'control.json'

/** The control file in the private directory `dir`. */
export function controlPath(dir: string): string {
  return `${dir.trim().replace(/\/$/, '')}/${CONTROL_NAME}`
}

/** `mktemp -d`: a new directory under `tmp` only this user can enter (0700); it
 * prints the directory's path. */
export function privateDirArgv(tmp: string): string[] {
  return ['mktemp', '-d', `${tmp.replace(/\/$/, '') || '/tmp'}/${CONTROL_PREFIX}XXXXXXXXXX`]
}

/** Writes its standard input to `path` with mode 0600 (umask 077), whole: into a
 * file beside it, then renamed over it, so follow never reads half a request. */
export function privateWriteArgv(path: string): string[] {
  return ['sh', '-c', 'umask 077 && cat > "$1.new" && mv -f "$1.new" "$1"', 'sh', path]
}

/** The zellij layout file for a control file: beside it, `.kdl` for `.json`. */
export function zellijLayoutPath(control: string): string {
  return control.replace(/\.json$/, '') + '.kdl'
}

/** `herdr pane get PANE`: the session's pane, whose workspace a tab opens in. */
export function herdrPaneGetArgv(pane: string): string[] {
  return ['herdr', 'pane', 'get', pane]
}

/** The workspace in `herdr pane get`'s JSON reply. */
export function herdrWorkspaceOf(stdout: string): string | undefined {
  try {
    const id = JSON.parse(stdout)?.result?.pane?.workspace_id
    return typeof id === 'string' ? id : undefined
  } catch {
    return undefined
  }
}

/** Waits until a new herdr pane's shell has drawn anything (its prompt): a
 * command sent by `herdr pane run` before then is lost. */
export function herdrReadyArgv(pane: string): [string, ...string[]] {
  return ['herdr', 'pane', 'wait-output', pane, '--regex', '\\S', '--source', 'visible']
}

/** The new pane's id in `herdr pane split`'s JSON reply, or `herdr tab
 * create`'s (its root pane). */
export function herdrPaneOf(stdout: string): string | undefined {
  try {
    const result = JSON.parse(stdout)?.result
    const id = (result?.pane ?? result?.root_pane)?.pane_id
    return typeof id === 'string' ? id : undefined
  } catch {
    return undefined
  }
}

/** `sigil frames draw`'s stdout as a Drawing, or the error it reported. */
export function parseDrawing(stdout: string): Drawing | { error: string } {
  try {
    const data = JSON.parse(stdout)
    if (typeof data?.error === 'string') return { error: data.error }
    if (Array.isArray(data?.frames) && Array.isArray(data?.styles)) return data as Drawing
  } catch {
    // fall through
  }
  return { error: 'sigil frames printed no drawing' }
}

/** The run's last frame (a still: 0). A playback's `at` is a frame of the
 * run, numbered as the viewer numbers them; the drawing holds a window of them. */
export function lastFrame(drawing: Drawing): number {
  return drawing.last ?? drawing.frames.length - 1
}

/** The frame a playback shows, clamped to the run. */
export function frameIndex(drawing: Drawing, playback: Playback): number {
  return Math.max(0, Math.min(playback.at, lastFrame(drawing)))
}

/** The frame of the run a request names (`frame`: the viewer's numbering, as a
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

/** A speed as the viewer's status bar writes it: `2 frames/s`, `½ frame/s`. */
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

// Drawn width, cure's rule for one code point (sigil/present/kit.py char_cells, from
// cure's |WideTable|): a wide character takes two terminal columns, a combining mark,
// joiner, format character or Hangul vowel / final jamo none, any other one. Packed
// rows need none of this — `sigil frames` sends cure's Wire: every code point of a
// packed row is one cell (a wide cluster its first code point then WIDE_TAIL) and the
// row's side table gives a cluster longer than one code point whole — but plain text
// (a status, narration, summary or lint line) keeps its names as written and is
// measured by it, a code point at a time.

/** Inclusive [first, last] code point pairs 2 columns wide, and 0 wide, written from
 * cure's widths by tools/wide_table.py (tests/test_plugin_cells.py checks them). */
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
const ZERO: readonly number[] = [
  0x300, 0x36f, 0x483, 0x489, 0x591, 0x5bd, 0x5bf, 0x5bf, 0x5c1, 0x5c2, 0x5c4, 0x5c5, 0x5c7, 0x5c7,
  0x600, 0x605, 0x610, 0x61a, 0x61c, 0x61c, 0x64b, 0x65f, 0x670, 0x670, 0x6d6, 0x6dd, 0x6df, 0x6e4,
  0x6e7, 0x6e8, 0x6ea, 0x6ed, 0x70f, 0x70f, 0x711, 0x711, 0x730, 0x74a, 0x7a6, 0x7b0, 0x7eb, 0x7f3,
  0x7fd, 0x7fd, 0x816, 0x819, 0x81b, 0x823, 0x825, 0x827, 0x829, 0x82d, 0x859, 0x85b, 0x890, 0x891,
  0x898, 0x89f, 0x8ca, 0x902, 0x93a, 0x93a, 0x93c, 0x93c, 0x941, 0x948, 0x94d, 0x94d, 0x951, 0x957,
  0x962, 0x963, 0x981, 0x981, 0x9bc, 0x9bc, 0x9c1, 0x9c4, 0x9cd, 0x9cd, 0x9e2, 0x9e3, 0x9fe, 0x9fe,
  0xa01, 0xa02, 0xa3c, 0xa3c, 0xa41, 0xa42, 0xa47, 0xa48, 0xa4b, 0xa4d, 0xa51, 0xa51, 0xa70, 0xa71,
  0xa75, 0xa75, 0xa81, 0xa82, 0xabc, 0xabc, 0xac1, 0xac5, 0xac7, 0xac8, 0xacd, 0xacd, 0xae2, 0xae3,
  0xafa, 0xaff, 0xb01, 0xb01, 0xb3c, 0xb3c, 0xb3f, 0xb3f, 0xb41, 0xb44, 0xb4d, 0xb4d, 0xb55, 0xb56,
  0xb62, 0xb63, 0xb82, 0xb82, 0xbc0, 0xbc0, 0xbcd, 0xbcd, 0xc00, 0xc00, 0xc04, 0xc04, 0xc3c, 0xc3c,
  0xc3e, 0xc40, 0xc46, 0xc48, 0xc4a, 0xc4d, 0xc55, 0xc56, 0xc62, 0xc63, 0xc81, 0xc81, 0xcbc, 0xcbc,
  0xcbf, 0xcbf, 0xcc6, 0xcc6, 0xccc, 0xccd, 0xce2, 0xce3, 0xd00, 0xd01, 0xd3b, 0xd3c, 0xd41, 0xd44,
  0xd4d, 0xd4d, 0xd62, 0xd63, 0xd81, 0xd81, 0xdca, 0xdca, 0xdd2, 0xdd4, 0xdd6, 0xdd6, 0xe31, 0xe31,
  0xe34, 0xe3a, 0xe47, 0xe4e, 0xeb1, 0xeb1, 0xeb4, 0xebc, 0xec8, 0xece, 0xf18, 0xf19, 0xf35, 0xf35,
  0xf37, 0xf37, 0xf39, 0xf39, 0xf71, 0xf7e, 0xf80, 0xf84, 0xf86, 0xf87, 0xf8d, 0xf97, 0xf99, 0xfbc,
  0xfc6, 0xfc6, 0x102d, 0x1030, 0x1032, 0x1037, 0x1039, 0x103a, 0x103d, 0x103e, 0x1058, 0x1059,
  0x105e, 0x1060, 0x1071, 0x1074, 0x1082, 0x1082, 0x1085, 0x1086, 0x108d, 0x108d, 0x109d, 0x109d,
  0x1160, 0x11ff, 0x135d, 0x135f, 0x1712, 0x1714, 0x1732, 0x1733, 0x1752, 0x1753, 0x1772, 0x1773,
  0x17b4, 0x17b5, 0x17b7, 0x17bd, 0x17c6, 0x17c6, 0x17c9, 0x17d3, 0x17dd, 0x17dd, 0x180b, 0x180f,
  0x1885, 0x1886, 0x18a9, 0x18a9, 0x1920, 0x1922, 0x1927, 0x1928, 0x1932, 0x1932, 0x1939, 0x193b,
  0x1a17, 0x1a18, 0x1a1b, 0x1a1b, 0x1a56, 0x1a56, 0x1a58, 0x1a5e, 0x1a60, 0x1a60, 0x1a62, 0x1a62,
  0x1a65, 0x1a6c, 0x1a73, 0x1a7c, 0x1a7f, 0x1a7f, 0x1ab0, 0x1ace, 0x1b00, 0x1b03, 0x1b34, 0x1b34,
  0x1b36, 0x1b3a, 0x1b3c, 0x1b3c, 0x1b42, 0x1b42, 0x1b6b, 0x1b73, 0x1b80, 0x1b81, 0x1ba2, 0x1ba5,
  0x1ba8, 0x1ba9, 0x1bab, 0x1bad, 0x1be6, 0x1be6, 0x1be8, 0x1be9, 0x1bed, 0x1bed, 0x1bef, 0x1bf1,
  0x1c2c, 0x1c33, 0x1c36, 0x1c37, 0x1cd0, 0x1cd2, 0x1cd4, 0x1ce0, 0x1ce2, 0x1ce8, 0x1ced, 0x1ced,
  0x1cf4, 0x1cf4, 0x1cf8, 0x1cf9, 0x1dc0, 0x1dff, 0x200b, 0x200f, 0x202a, 0x202e, 0x2060, 0x2064,
  0x2066, 0x206f, 0x20d0, 0x20f0, 0x2cef, 0x2cf1, 0x2d7f, 0x2d7f, 0x2de0, 0x2dff, 0x302a, 0x302d,
  0x3099, 0x309a, 0xa66f, 0xa672, 0xa674, 0xa67d, 0xa69e, 0xa69f, 0xa6f0, 0xa6f1, 0xa802, 0xa802,
  0xa806, 0xa806, 0xa80b, 0xa80b, 0xa825, 0xa826, 0xa82c, 0xa82c, 0xa8c4, 0xa8c5, 0xa8e0, 0xa8f1,
  0xa8ff, 0xa8ff, 0xa926, 0xa92d, 0xa947, 0xa951, 0xa980, 0xa982, 0xa9b3, 0xa9b3, 0xa9b6, 0xa9b9,
  0xa9bc, 0xa9bd, 0xa9e5, 0xa9e5, 0xaa29, 0xaa2e, 0xaa31, 0xaa32, 0xaa35, 0xaa36, 0xaa43, 0xaa43,
  0xaa4c, 0xaa4c, 0xaa7c, 0xaa7c, 0xaab0, 0xaab0, 0xaab2, 0xaab4, 0xaab7, 0xaab8, 0xaabe, 0xaabf,
  0xaac1, 0xaac1, 0xaaec, 0xaaed, 0xaaf6, 0xaaf6, 0xabe5, 0xabe5, 0xabe8, 0xabe8, 0xabed, 0xabed,
  0xd7b0, 0xd7ff, 0xfb1e, 0xfb1e, 0xfe00, 0xfe0f, 0xfe20, 0xfe2f, 0xfeff, 0xfeff, 0xfff9, 0xfffb,
  0x101fd, 0x101fd, 0x102e0, 0x102e0, 0x10376, 0x1037a, 0x10a01, 0x10a03, 0x10a05, 0x10a06,
  0x10a0c, 0x10a0f, 0x10a38, 0x10a3a, 0x10a3f, 0x10a3f, 0x10ae5, 0x10ae6, 0x10d24, 0x10d27,
  0x10eab, 0x10eac, 0x10efd, 0x10eff, 0x10f46, 0x10f50, 0x10f82, 0x10f85, 0x11001, 0x11001,
  0x11038, 0x11046, 0x11070, 0x11070, 0x11073, 0x11074, 0x1107f, 0x11081, 0x110b3, 0x110b6,
  0x110b9, 0x110ba, 0x110bd, 0x110bd, 0x110c2, 0x110c2, 0x110cd, 0x110cd, 0x11100, 0x11102,
  0x11127, 0x1112b, 0x1112d, 0x11134, 0x11173, 0x11173, 0x11180, 0x11181, 0x111b6, 0x111be,
  0x111c9, 0x111cc, 0x111cf, 0x111cf, 0x1122f, 0x11231, 0x11234, 0x11234, 0x11236, 0x11237,
  0x1123e, 0x1123e, 0x11241, 0x11241, 0x112df, 0x112df, 0x112e3, 0x112ea, 0x11300, 0x11301,
  0x1133b, 0x1133c, 0x11340, 0x11340, 0x11366, 0x1136c, 0x11370, 0x11374, 0x11438, 0x1143f,
  0x11442, 0x11444, 0x11446, 0x11446, 0x1145e, 0x1145e, 0x114b3, 0x114b8, 0x114ba, 0x114ba,
  0x114bf, 0x114c0, 0x114c2, 0x114c3, 0x115b2, 0x115b5, 0x115bc, 0x115bd, 0x115bf, 0x115c0,
  0x115dc, 0x115dd, 0x11633, 0x1163a, 0x1163d, 0x1163d, 0x1163f, 0x11640, 0x116ab, 0x116ab,
  0x116ad, 0x116ad, 0x116b0, 0x116b5, 0x116b7, 0x116b7, 0x1171d, 0x1171f, 0x11722, 0x11725,
  0x11727, 0x1172b, 0x1182f, 0x11837, 0x11839, 0x1183a, 0x1193b, 0x1193c, 0x1193e, 0x1193e,
  0x11943, 0x11943, 0x119d4, 0x119d7, 0x119da, 0x119db, 0x119e0, 0x119e0, 0x11a01, 0x11a0a,
  0x11a33, 0x11a38, 0x11a3b, 0x11a3e, 0x11a47, 0x11a47, 0x11a51, 0x11a56, 0x11a59, 0x11a5b,
  0x11a8a, 0x11a96, 0x11a98, 0x11a99, 0x11c30, 0x11c36, 0x11c38, 0x11c3d, 0x11c3f, 0x11c3f,
  0x11c92, 0x11ca7, 0x11caa, 0x11cb0, 0x11cb2, 0x11cb3, 0x11cb5, 0x11cb6, 0x11d31, 0x11d36,
  0x11d3a, 0x11d3a, 0x11d3c, 0x11d3d, 0x11d3f, 0x11d45, 0x11d47, 0x11d47, 0x11d90, 0x11d91,
  0x11d95, 0x11d95, 0x11d97, 0x11d97, 0x11ef3, 0x11ef4, 0x11f00, 0x11f01, 0x11f36, 0x11f3a,
  0x11f40, 0x11f40, 0x11f42, 0x11f42, 0x13430, 0x13440, 0x13447, 0x13455, 0x16af0, 0x16af4,
  0x16b30, 0x16b36, 0x16f4f, 0x16f4f, 0x16f8f, 0x16f92, 0x16fe4, 0x16fe4, 0x1bc9d, 0x1bc9e,
  0x1bca0, 0x1bca3, 0x1cf00, 0x1cf2d, 0x1cf30, 0x1cf46, 0x1d167, 0x1d169, 0x1d173, 0x1d182,
  0x1d185, 0x1d18b, 0x1d1aa, 0x1d1ad, 0x1d242, 0x1d244, 0x1da00, 0x1da36, 0x1da3b, 0x1da6c,
  0x1da75, 0x1da75, 0x1da84, 0x1da84, 0x1da9b, 0x1da9f, 0x1daa1, 0x1daaf, 0x1e000, 0x1e006,
  0x1e008, 0x1e018, 0x1e01b, 0x1e021, 0x1e023, 0x1e024, 0x1e026, 0x1e02a, 0x1e08f, 0x1e08f,
  0x1e130, 0x1e136, 0x1e2ae, 0x1e2ae, 0x1e2ec, 0x1e2ef, 0x1e4ec, 0x1e4ef, 0x1e8d0, 0x1e8d6,
  0x1e944, 0x1e94a, 0xe0001, 0xe0001, 0xe0020, 0xe007f, 0xe0100, 0xe01ef,
]

function within(table: readonly number[], code: number): boolean {
  let lo = 0
  let hi = table.length / 2 - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (code < table[mid * 2]!) hi = mid - 1
    else if (code > table[mid * 2 + 1]!) lo = mid + 1
    else return true
  }
  return false
}

/** The columns one character (one code point) takes: 2, 0 or 1. */
export function charCells(ch: string): number {
  const code = ch.codePointAt(0) ?? 0
  if (code < 0x80) return 1
  if (within(ZERO, code)) return 0
  return within(WIDE, code) ? 2 : 1
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

/** A wide cluster's second cell in a packed row: `sigil frames` writes a wide
 * cluster as its first code point then this (cure's Wire), so every code point of a
 * packed row is one cell and cutting, panning and measuring count code points. */
export const WIDE_TAIL = '\u0000'

/** A packed row's side table: [column, cluster] for each cell whose cluster is
 * longer than one code point (a mark, a ZWJ sequence, a flag), by column. */
export type Clusters = readonly (readonly [number, string])[]

/** The side tables of a drawing's packed rows, one per row ([] for a row with
 * none): `field` frames or path at the frame slot `i`, or the legend. */
export function sideTables(drawing: Drawing, field: 'frames' | 'path' | 'legend', i = 0): Clusters[] {
  const side = drawing.clusters?.[field]
  if (side === undefined) return []
  return (field === 'legend' ? side : (side as Clusters[][])[i] ?? []) as Clusters[]
}

/** A packed row as terminal text, its columns from … from+width-1: each cell its
 * cluster (the side table's, else its own code point), a wide cluster's tail
 * nothing; a tail whose head is left of the window (a pan) and a head whose tail
 * is right of it (the edge) a blank, so the text keeps its cells. Runs keep
 * their style ids; an empty one is left out. */
export function drawnRuns(row: PackedRow, table: Clusters = [], from = 0, width = Infinity): PackedRow {
  const whole = new Map(table)
  const all = row.flatMap(([text, id]) => [...text].map(ch => [ch, id] as const))
  const to = Math.min(from + width, all.length)
  const out: PackedRow = []
  for (let at = Math.max(from, 0); at < to; at++) {
    const [ch, id] = all[at]!
    const glyph = ch === WIDE_TAIL ? (at === from ? ' ' : '')
      : at === to - 1 && all[at + 1]?.[0] === WIDE_TAIL ? ' '
        : whole.get(at) ?? ch
    const last = out[out.length - 1]
    if (last !== undefined && last[1] === id) last[0] += glyph
    else out.push([glyph, id])
  }
  return out.filter(([text]) => text !== '')
}

/** Whether packed rows hold a wide cluster or a cluster longer than one code point
 * (a Raster cell is one column of one code point: such rows are drawn as text). */
export function holdsWide(rows: readonly PackedRow[], tables: readonly Clusters[] = []): boolean {
  return tables.some(t => t.length > 0) || rows.some(row => row.some(([text]) => text.includes(WIDE_TAIL)))
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
 * played or paused at its speed (an index into SPEEDS), as the viewer's bar. */
export function statusLine(drawing: Drawing, request: ViewRequest, at: number, isPlaying: boolean,
                           speed: number = START_SPEED): string {
  const depth = request.depth >= ALL_DEPTH ? 'all' : String(request.depth)
  const head = `${drawing.file} · ${drawing.view} · depth ${depth}${drawing.layout ? ` · ${drawing.layout}` : ''}`
  const run = drawing.status?.[slot(drawing, at)]
  if (run === undefined) return head
  return `${head} · ${isPlaying ? '▶' : '❚❚'} ${speedText(speed)} · ${run} · ${frameText(drawing, at, '/')}`
}

/** A run's lines under the drawing at a frame, as the viewer's rows under its
 * footer: `path` and the episode's hops so far — the viewer's styled rows (the hop
 * now bold) when `sigil frames` sent them, else the text (`trail`) — then `›` and the
 * narration line (the run's log line from an older pane that has none). null for a
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
