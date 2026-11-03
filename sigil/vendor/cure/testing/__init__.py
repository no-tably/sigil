"""[Testing]: Virtual, Pilot, Snapshot, Sweep.

Kind: system (the expansion of [Testing] in cure). Milestone A builds [Snapshot]
(`cure.testing.snapshot`: plain and styled snapshots of a frame, goldens updated only
on the caller's `update=True`); milestone B (PLAN.md) adds [Virtual]
(`cure.testing.virtual`: a frame's bytes replayed through Vt, the screen checked
against the buffer), [Pilot] (`cure.testing.pilot`: scripted keys and clicks through
real decoding and routing, with fake time) and [Sweep] (`cure.testing.sweep`: one view
over widths × heights). Re-exported from Snapshot: `Label`, `Diff`, `KEYS`, `plain`,
`styled`, `label`, `labelled`, `parse`, `match`, `assert_snapshot`, `golden`,
`assert_golden`; from Virtual: `Virtual`, `Mismatch`, `realized`, `realized_style`;
from Pilot: `Pilot`, `MODES`; from Sweep: `Jump`, `WHATS`, `sweep`, `assert_sweep`.

Effects: none on import (Snapshot's `golden` reads and writes the file it is given).
"""

from .snapshot import (KEYS, Diff, Label, assert_golden, assert_snapshot, golden, label,
                       labelled, match, parse, plain, styled)
from .pilot import MODES, Pilot
from .sweep import WHATS, Jump, assert_sweep, sweep
from .virtual import Mismatch, Virtual, realized, realized_style
