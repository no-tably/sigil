// The mod's own shapes and the session state its pane draws from.

/** What the agent's tool call or /sigil asked to see. */
export type ViewRequest = {
  file: string
  view: ViewName
  depth: number
  scenario?: string
  payloads?: boolean
}

export type ViewName = 'graph' | 'tree' | 'flow'

/** One packed row: [text, style id] runs (site/frames.py's packing). */
export type PackedRow = [string, number][]

/** A style: [foreground hex | null, background hex | null, bold]. */
export type Style = [string | null, string | null, boolean]

/** What `pane.py draw` printed, plus the width it was drawn for. */
export type Drawing = {
  file: string
  view: ViewName
  width: number | null
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
}

/** The run's playback: the frame shown and whether it plays. */
export type Playback = { at: number; isPlaying: boolean }

/** The multiplexer split the mod drives, by the control file it writes. */
export type Split = { mux: Mux; control: string; pane?: string }

export type Mux = 'herdr' | 'tmux' | 'zellij'

declare module 'claude-code' {
  interface PluginState {
    sigil: {
      request: ViewRequest | null
      drawing: Drawing | null
      error: string | null
      playback: Playback
      split: Split | null
    }
  }
}
