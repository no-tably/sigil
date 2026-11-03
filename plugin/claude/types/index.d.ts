// The mod's own shapes and the session state its pane draws from.

/** What the agent's tool call or /sigil asked to see. */
export type ViewRequest = {
  file: string
  view: ViewName
  depth: number
  scenario?: string
  payloads?: boolean
}

export type ViewName = 'graph' | 'tree' | 'flow' | 'run'

/** One packed row: [text, style id] runs (`sigil frames`' packing: cure's Wire),
 * each code point one terminal cell (a wide cluster its first code point then
 * WIDE_TAIL, its second cell; a cluster longer than one code point is whole in the
 * row's side table, Drawing.clusters). */
export type PackedRow = [string, number][]

/** A style: [foreground hex | null, background hex | null, bold]. */
export type Style = [string | null, string | null, boolean]

/** What `sigil frames draw` printed, plus the width it was drawn for. */
export type Drawing = {
  file: string
  view: ViewName
  width: number | null
  layout?: 'wrap' | 'pan' // what `sigil frames` drew: fitted to the width, or the natural layout
  height?: number // the pane rows auto picked the layout by (0: not auto)
  styles: Style[]
  frames: PackedRow[][]
  legend: PackedRow[]
  summary: string
  lint: string[]
  scenarios: string[]
  scenario?: string
  status?: string[]
  log?: string[]
  say?: string[]
  trail?: string[]
  path?: PackedRow[][]
  outcome?: string
  choice?: string
  first?: number // the run's frame the drawn frames start at (a run is drawn a window at a time)
  last?: number // the run's last frame
  // the side tables of the packed rows that hold a cluster longer than one code point:
  // per frame (frames, path) or for the legend, one [column, cluster][] per row
  clusters?: { frames?: [number, string][][][]; path?: [number, string][][][]; legend?: [number, string][][] }
}

/** The run's playback: the frame of the run shown (the viewer's numbering) and whether it plays. */
export type Playback = { at: number; isPlaying: boolean }

/** The multiplexer split (or tab: `placement`, left out for a split) the mod
 * drives, by the control file it writes. */
export type Split = { mux: Mux; control: string; pane?: string; placement?: 'split' | 'tab' }

export type Mux = 'herdr' | 'tmux' | 'zellij'

declare module 'claude-code' {
  interface PluginState {
    sigil: {
      request: ViewRequest | null
      drawing: Drawing | null
      error: string | null
      playback: Playback
      split: Split | null
      panX: number // the first column a panned drawing shows
      /** The played run's speed: an index into logic.ts's SPEEDS. */
      speed: number
    }
  }
}
