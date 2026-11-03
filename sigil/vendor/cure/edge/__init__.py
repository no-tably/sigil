"""[Edge]: Term, Clock, Files, Embed, Remote; a pane's program, through Vt.

Kind: system (the expansion of [Edge] in cure): the only parts of cure that touch the
OS, each called from the app's own loop, none running one. [Term] (`cure.edge.term`:
the tty, its paired modes, probe, reader, the one writer, signals), [Clock]
(`cure.edge.clock`: waiting on fds, timers, playback), [Files] (`cure.edge.files`:
themes found and read on the app's search path, a file watched), [Embed]
(`cure.edge.embed`: a program in a pane, on its own pty) and [Remote]
(`cure.edge.remote`: serve sessions to clients, cell diffs only). Depends on Core and
Interact (Term and Clock also on top-level `cure`'s `<Closed>`, `cure/closed.py`), never
on Draw or Testing.

Edge provides no op of its own at this level: the ops the app and the other packages
call are its systems' and live in their packages (`open` in Term, `spawn` in Embed,
`read` and `watch` in Files, `serve` and `connect` in Remote, `select` in Clock). The
ops it calls across the package line are:

- `[Edge] -> [Interact] : apply({Bytes}) => {Grid}`: a pane's program performed on
  its Vt screen; Interact's `apply` (`cure.interact`, Vt's op re-exported), which
  Embed's [Pty] calls (`[Pty] -> [Vt] : apply`).
- `[Edge] -> [Core] : show({Buffer}) => {Bytes}`: a frame's bytes for a terminal;
  Core's `show` (`cure.core`), which Term's handle calls through its own Core
  `Display`. Remote's server holds no {Display}: it sends each client a cell diff
  (Buffer's `diff`), and the client's [Attach] draws it through its own Term.

Effects: none on import (importing `cure.edge` imports none of its systems; each is
imported by its own package path).

Usage:
    from cure.edge.term import Term
    from cure.edge.embed import spawn, SpawnFailed
    from cure.edge.clock import select, Closed
"""
