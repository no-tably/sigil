"""[Edit]: a text-edit value: cursor, selection, words, history, undo.

Kind: service (the `Edit` value, its undo `Snapshot`, the edit commands and their
default keys as plain [Bindings] entries, and the pure ops that make a new `Edit`
from an old one); pure. An edit value is the app's (TextInput, "one line or an area;
its edit state is the app's"): the app keeps one per input, the Router hands the
focused one a typed key, a paste or an edit command, and every op returns a new value;
none changes its argument.

It provides `keys` for the Router (`[Router] -> [Edit] : keys({Key}) => {Edit}`: a
focused input owns ordinary keys): a key that types text, or a paste, to the next
`Edit`. Every other key reaches an edit through the app's ONE bindings table: the
default keys below are `Binding`s whose actions are `(EDIT, command)`, which the app
puts in its table (like [Focus]' `FOCUS_BINDINGS`) and the Router applies with
`apply`; so the table's higher layers rebind or mask them, and `hints` and `help`
show them.

## One line or an area

`area` (a field, `False` by default) says whether newlines are text:
- One line (`area` False): the value is one line. Enter, tab, escape and the keys it
  does not own go on to the app's bindings (submit, focus, cancel); "newline",
  "select_up" and "select_down" are not owned; up and down recall the history
  ("older" / "newer"), and are not owned when the history is empty. A pasted newline
  is kept as it is, as every pasted character is (pasted text is text, never keys):
  in a one-line edit it is no line break but one ordinary cluster, one cell wide (as
  Text's `width` gives a control, and Text's `cell` draws it, as U+FFFD), which the
  motions step over like any other.
- An area (`area` True): the text is lines. A break is a cluster "\\n" or "\\r\\n" (one
  cluster, as Text cuts it; a pasted "\\r\\n" stays as it is); a lone "\\r" is no
  break. "newline" (enter by default) inserts "\\n"; up and down move by line keeping a
  goal column; home and end (and their selecting and deleting forms) are per line;
  word motions cross lines (a break is a non-word cluster); a paste keeps its
  newlines.

## Clusters, never code points

Everything is counted in grapheme clusters, as Core's Text cuts them (`cluster`), and
measured in cells with Text's `width`: "e\\u0301" is one cluster, one column; "中" is
one cluster, two columns. With `cl = cluster(text)` and `n = len(cl)`:
- the cursor is a cluster boundary, an `int` in `0..n` (0 before the first cluster,
  `n` after the last);
- the selection runs between `anchor` and `cursor`;
- a change cuts and joins whole clusters (a splice, below); clusters may merge at the
  seam ("e" typed before a lone "\\u0301" makes one cluster), and the cursor lands on a
  boundary of the result;
- the breaks are the indices `b` with `cl[b]` a break, in an area; there are none in
  a one-line edit. For a boundary `i`: its line `L(i)` is the number of breaks `< i`;
  its line start `S(i)` is `b + 1` for the last break `b < i`, else 0; its line end
  `E(i)` is the first break `b >= i`, else `n`. A line's clusters are `cl[S:E]`, its
  break (if any) at `E`.
- the column of a boundary is `width("".join(cl[S(i):i]))`, the cells from its line's
  start; `at(s, e, g)` is the largest `k` in `s..e` with `width("".join(cl[s:k])) <=
  g` (a column lands before a cluster it would split: column 1 of "中" is 0).

## The value

- `Edit(text="", cursor=None, *, area=False, anchor=None, goal=None, limit=None,
  history=(), recall=None, draft="", undo=(), redo=(), typing=False, depth=100)`
  (frozen dataclass):
  - `text`: the text, a `str`.
  - `cursor`: `None` (the end: stored as `n`) or an `int` in `0..n`.
  - `area`: a `bool`, see "One line or an area".
  - `anchor`: `None` (no selection) or an `int` in `0..n`, the selection's fixed end;
    an anchor equal to the cursor is stored as `None` (an empty selection is none).
  - `goal`: `None` or an `int` >= 0, the column up and down aim for (kept from one
    vertical move to the next; every other op sets it to `None`).
  - `limit`: `None` (no limit) or an `int` >= 0, the most clusters `text` may hold
    (breaks included); inserts are cut to fit.
  - `history`: the texts submitted before, a tuple of `str`, oldest first (recalled
    with "older" / "newer"; `submit` adds to it).
  - `recall`: `None` (editing a fresh text) or the index in `history` of the entry
    being shown; `draft`: the text that was being edited when recall began (`""`
    whenever `recall` is `None`).
  - `undo`, `redo`: tuples of `Snapshot`, oldest first, the last one next; each at
    most `depth` long.
  - `typing`: a `bool`, whether the last op was a typed insert (typed keys coalesce
    into one undo step, see "Undo").
  - `depth`: an `int` >= 0, how many undo (and redo) steps are kept.
  `TypeError` when a field has the wrong type (`text`, `draft` not a `str`; `cursor`,
  `anchor`, `goal`, `limit`, `recall` neither `None` nor an `int`, a `bool` included;
  `area`, `typing` not a `bool`; `history` not a tuple of `str`; `undo`, `redo` not
  tuples of `Snapshot`; `depth` not an `int`); `ValueError` when `cursor` or `anchor`
  is outside `0..n`, `goal`, `limit` or `depth` is negative, `text` holds more than
  `limit` clusters, `recall` is outside `0..len(history) - 1`, `draft` is not `""`
  while `recall` is `None`, or `undo` or `redo` is longer than `depth`. Equality is by
  value, field by field (two edits with the same text but different histories differ).
- `Snapshot(text, cursor, anchor=None)` (frozen dataclass): one undo step, the
  `text`, `cursor` and `anchor` before a change. `TypeError` / `ValueError` as for
  `Edit`'s fields of those names.

Properties, read by TextInput and the app:
- `clusters -> tuple[str, ...]`: `cluster(text)`.
- `before -> str`, `after -> str`: `"".join(clusters[:cursor])` and
  `"".join(clusters[cursor:])`.
- `rows -> tuple[str, ...]`: the lines a TextInput draws: in an area, the text cut at
  its breaks, the breaks dropped (`len(rows)` is the number of breaks + 1; `""` gives
  `("",)`, `"a\\n"` gives `("a", "")`); in a one-line edit, `(text,)`.
- `line -> int`: `L(cursor)`, the cursor's row in `rows` (always 0 in a one-line edit).
- `column -> int`: the cursor's column in its row (see above); in a one-line edit
  `width(before)`.
- `position -> tuple[int, int]`: `(line, column)`, where a TextInput puts the
  terminal cursor (less its own scroll).
- `selection -> tuple[int, int] | None`: `(min(anchor, cursor), max(anchor, cursor))`,
  or `None` when `anchor` is `None`.
- `selected -> str`: the selected clusters joined, `""` with no selection.

## Splices: every change

A change replaces the clusters `[i, j)` with a text `s` (as given, never re-cut): the
new text is `t2 = "".join(cl[:i]) + s + "".join(cl[j:])`, the new cursor
`min(len(cluster("".join(cl[:i]) + s)), len(cluster(t2)))`, the anchor and goal
`None`, `recall` `None` and `draft` `""` (an edited recalled text is a fresh one). A
splice changes the edit when `i < j` or `s != ""`; one that does not leaves the text,
cursor, anchor, history and undo as they were.

## Undo

Before a change, `Snapshot(text, cursor, anchor)` of the edit is appended to `undo`
(the oldest dropped beyond `depth`; with `depth` 0 `undo` stays `()`), and `redo`
becomes `()`. Typed keys coalesce: a typed insert (a typed `Key`'s text through
`keys`, not a paste, "newline" or `insert`) made while `typing` is True and with no
selection pushes nothing, so a run of typed characters undoes as one step. After a
typed insert `typing` is True; after every other op (a motion, a delete, a paste,
undo, a command that changes nothing) it is False.
- "undo": with `undo` empty, the edit with `typing` False; else the text, cursor and
  anchor of `undo[-1]`, `undo` without it, `Snapshot` of the current state appended to
  `redo` (kept to `depth`), `goal` `None`, `typing` False. History, `recall` and
  `draft` unchanged.
- "redo": the same with `undo` and `redo` swapped.

## Commands

`COMMANDS`, each a `str`. With `i` the cursor, `sel = selection`, and `S`, `E`, `L`,
`at` as above (in a one-line edit `S(i)` is 0 and `E(i)` is `n`):
- motions, which never change the text, `undo` or `redo`, and leave `anchor` `None`:
  - "left": with a selection, the cursor to its start; else `max(0, i - 1)`.
  - "right": with a selection, to its end; else `min(n, i + 1)`.
  - "home": `S(i)`. "end": `E(i)`. "top": 0. "bottom": `n`.
  - "word_left": back over the non-word clusters, then the word clusters, before the
    cursor; "word_right": forward over the non-word clusters, then the word clusters,
    after it (Emacs' forward-word: it stops at a word's end). A word cluster is one
    whose first code point is `str.isalnum()` or `"_"`; a break is a non-word cluster,
    so word motions cross lines. (`word_left` / `word_right` below are these targets
    from `i`, a selection ignored.)
  - "up" (an area): with `g = goal` if not `None` else the cursor's column: on line 0
    the cursor goes to 0; else to `at(S(p), p, g)` for `p` the break that ends the
    line above (`p = S(i) - 1`); `goal` becomes `g`. "down" (an area): on the last
    line the cursor goes to `n`; else to `at(q + 1, E(q + 1), g)` for `q = E(i)`, the
    break ending this line; `goal` becomes `g`. In a one-line edit "up" is "older"
    and "down" is "newer".
- selecting motions: the anchor is kept, or set to `i` when there is none; the cursor
  moves as the plain motion would with no selection; an anchor that ends equal to the
  cursor becomes `None`: "select_left", "select_right", "select_home", "select_end",
  "select_word_left", "select_word_right", and in an area "select_up",
  "select_down" (which keep the goal as "up" / "down" do). "select_all": anchor 0,
  cursor `n` (no selection when `n` is 0).
- deletes: with a selection, every delete splices `[sel[0], sel[1])` with `""`; else
  "delete_left" `[i - 1, i)` (nothing at 0), "delete_right" `[i, i + 1)` (nothing at
  `n`), "delete_word_left" `[word_left, i)`, "delete_word_right" `[i, word_right)`,
  "delete_home" `[S(i), i)`, or the break before, `[i - 1, i)`, when `i == S(i) > 0`
  (it joins the line to the one above); "delete_end" `[i, E(i))`, or the break,
  `[i, i + 1)`, when `i == E(i) < n` (Emacs' kill-line at a line's end joins the
  next).
- "newline" (an area): the splice `[i, i)` (or the selection) with `"\\n"`, cut to the
  limit as `insert` cuts; one undo step, never coalesced.
- "undo", "redo": see "Undo".
- history recall, which empties `undo` and `redo`, leaves the anchor and goal `None`
  and puts the cursor at the end of the new text:
  - "older": with `recall` `None`, `draft` becomes `text` and `recall` the last index;
    else `recall` goes one back (staying at 0); the text becomes `history[recall]`.
  - "newer": with `recall` `None`, nothing changes; at the last index the text becomes
    `draft`, `recall` `None` and `draft` `""`; else `recall` goes one forward and the
    text becomes `history[recall]`.
`typing` is False after every command.

Not owned (`apply` gives `None`, and the Router lets the key go on through the
table): "newline", "select_up" and "select_down" in a one-line edit; "older" and
"newer", and in a one-line edit "up" and "down", while `history` is `()`. Every other
command is owned, even when it changes nothing (backspace at 0): owned is not changed.

## The default keys: entries of the one table

`EDIT = "edit"`: an edit action is the 2-tuple `(EDIT, command)`, `command` one of
`COMMANDS`. `EDIT_SCOPE = "edit"`: the [Bindings] scope the Router adds to the focus
chain while a text input is focused, right after the focused stop's own id (see
[Router]'s `scopes`), so these keys are active only in an input, rank before the
app's unscoped and outer-scoped bindings, and leave lists their arrows elsewhere. A
focus tree must not use it as an id.

`EDIT_BINDINGS`, a tuple of `Binding`, each `Binding(keys, (EDIT, command), label,
group="edit", scope=EDIT_SCOPE)` (not hidden: `help` lists them), for the app's
default layer:
left, ctrl+b: "left"; right, ctrl+f: "right"; home, ctrl+a: "home"; end, ctrl+e:
"end"; ctrl+home: "top"; ctrl+end: "bottom"; ctrl+left, alt+b: "word_left";
ctrl+right, alt+f: "word_right"; up: "up"; down: "down"; shift+left: "select_left";
shift+right: "select_right"; shift+home: "select_home"; shift+end: "select_end";
shift+up: "select_up"; shift+down: "select_down"; ctrl+shift+left:
"select_word_left"; ctrl+shift+right: "select_word_right"; backspace, ctrl+h:
"delete_left"; delete, ctrl+d: "delete_right"; ctrl+w, alt+backspace,
ctrl+backspace: "delete_word_left"; alt+d, ctrl+delete: "delete_word_right"; ctrl+u:
"delete_home"; ctrl+k: "delete_end"; enter: "newline"; ctrl+z: "undo"; ctrl+y,
ctrl+shift+z: "redo". "select_all", "older" and "newer" have no default key.
A person rebinds or masks one in a higher layer with the same scope:
`Binding("ctrl+a", ("edit", "select_all"), scope=EDIT_SCOPE)`, `Binding("ctrl+b",
None, scope=EDIT_SCOPE)`. [Bindings] refuses a table where a bound edit key is the
start of a bound chord ("ctrl+k" and "ctrl+k ctrl+c"; a prefix key "ctrl+b"): the app
masks that edit key, as above. There is no kill ring and no clipboard: copy, cut and
paste are the app's (`selected`, `cut`, `insert`, its own bindings and OSC 52).

## Ops

- `keys(edit, event) -> Edit | None`: a typed key or a paste into the edit.
  - a `Paste`: `insert(edit, event.text)` (always owned);
  - a typed key (`typed(event)`): its `text` inserted as a typed insert (as `insert`,
    then coalesced, see "Undo");
  - any other `Key`: `None` (not owned here: commands come through the table, as
    `(EDIT, command)` actions, and `apply`).
  `TypeError` when `edit` is not an `Edit` or `event` not a `Key` or `Paste`.
- `typed(key) -> bool`: whether a key types text: a "press" or "repeat" `Key` with a
  non-empty `text` and none of "ctrl", "alt", "super", "hyper", "meta" held (so
  "space" types " ", "shift+a" types "A", enter and tab type nothing). The Router
  gives such a key to a focused input before the table, and never takes it as a
  chord's start. `TypeError` when `key` is not a `Key`.
- `command(action) -> str | None`: the command of an edit action: `c` for `(EDIT, c)`
  with `c` one of `COMMANDS`, else `None` (any other action, hashable or not, is no
  edit action).
- `apply(edit, command) -> Edit | None`: one command (see "Commands"); `None` when the
  edit does not own it. `TypeError` when `edit` is not an `Edit` or `command` not a
  `str`; `ValueError` when it is not one of `COMMANDS`.
- `insert(edit, text) -> Edit`: `text` inserted as it is, replacing the selection:
  the splice `[sel[0], sel[1])` (or `[i, i)`) with the longest prefix of `cluster(text)`,
  joined, that keeps the result within `limit` clusters (all of it with no limit). One
  undo step, `typing` False. With nothing left to insert and no selection: the edit
  unchanged but `typing` False and `goal` `None`. `TypeError` when `edit` is not an
  `Edit` or `text` not a `str`.
- `cut(edit) -> tuple[Edit, str]`: with a selection, `(the selection spliced with "",
  edit.selected)`, one undo step; else `(edit with typing False and goal None, "")`.
  `TypeError` when `edit` is not an `Edit`.
- `place(edit, column, *, line=0, select=False) -> Edit`: the cursor put at a cell (a
  click in a TextInput; the app subtracts the input's top-left corner and adds its
  scroll): on row `r = min(max(line, 0), len(rows) - 1)`, whose clusters run from `s`
  to `e`, the cursor goes to `at(s, e, max(column, 0))`. `select` False: the anchor
  `None`; True (a drag, a shift+click): the anchor kept, or set to the old cursor when
  there is none (`None` again when it equals the new cursor). Text and undo
  unchanged, `goal` `None`, `typing` False. `TypeError` when `edit` is not an `Edit`,
  `column` or `line` not an `int` (a `bool` included) or `select` not a `bool`.
- `submit(edit, *, keep=None) -> Edit`: the text done (the app's enter): `text`
  appended to `history` unless it is `""` or equal to `history[-1]`, then only the
  last `keep` entries kept (`keep` `None`: all; 0: none); text `""`, cursor 0, anchor
  and goal `None`, `recall` `None`, `draft` `""`, `undo` and `redo` `()`, `typing`
  False; `area`, `limit` and `depth` kept. `TypeError` when `edit` is not an `Edit`
  or `keep` not `None` or an `int`; `ValueError` when `keep` is negative.

Laws (for any `Edit` `e`, text `s`, command `c`; a test can loop over them):
- every op's result is a valid `Edit`: `0 <= cursor <= len(clusters)`, and
  `len(clusters) <= limit` when `limit` is not `None`.
- `insert(e, s).text == e.before + s + e.after` when `e` has no selection and no
  limit, in either mode (newlines kept); `keys(e, Paste(s)) == insert(e, s)`.
- a typed key with text `t` gives the text, cursor and anchor of `insert(e, t)`.
- motions keep the text: `apply(e, c).text == e.text` for every motion and selecting
  motion `c` that `e` owns.
- `apply(insert(e, s), "undo")` has the text, cursor and anchor of `e` when `s != ""`,
  `e.depth > 0` and `e.limit` is `None`; `apply(apply(x, "undo"), "redo")` has the
  text, cursor and anchor of `x` when `x.undo` is not `()`.
- rows: `0 <= e.line < len(e.rows)` and `e.position == (e.line, e.column)`; in an
  area `"\n".join(e.rows) == e.text` when the text holds no "\r\n"; in a one-line
  edit `e.rows == (e.text,)` and `e.line == 0`.
- up and down keep a column (an area): for `e` with `goal` `None` whose cluster just
  after the cursor, if any and not a break, has width > 0:
  `apply(apply(e, "up"), "down").cursor == e.cursor` when `e.line > 0`, and
  `apply(apply(e, "down"), "up").cursor == e.cursor` when `e.line < len(e.rows) - 1`
  (a shorter line in between lands at its end; the goal brings the cursor back). A
  vertical move changes `line` by at most 1, and off the first line
  `apply(e, "up").column <= (e.goal if e.goal is not None else e.column)`.
- `place(e, e.column, line=e.line).cursor == e.cursor` when the cluster just after
  the cursor, if any and not a break, has a width > 0 (a 0-width cluster rides its
  base).
- a one-line edit owns "up" / "down" exactly when its history is not `()`, and never
  owns "newline".

Inputs: [Events]' `Key` and `Paste`, commands, strings, cells. Outputs: an `Edit` (or
`None`: not owned), a `bool`, a command, a cut text. Errors: as stated. Effects: none.

The clusters cache (the module's one shared state, `_CUTS`): it is owned by `_cut`
alone, and `_cut` computes every answer it holds; no caller puts an answer in it.
- `_cut(text) -> tuple[str, ...]`: exactly `cluster(text)` (Text's [Graphemes], `==`
  and a tuple of `str`), memoised: the last 64 texts cut are kept, the oldest entry
  dropped when a 65th is added (insertion order). Every entry `_CUTS[t]` is
  `cluster(t)` as `_cut` computed it, so a hit gives the answer a miss would.
  `TypeError` as `cluster` gives it when `text` is not a `str` (nothing stored). It
  takes no known answer: the old `cl=` argument is gone, and the splice no longer
  seeds the cache with `_recut`'s clusters (`edit.py`, `_splice`): the new `Edit`
  cuts its text through `_cut` like any other, and `_recut` gives only the cursor.
  Law recut_is_cluster (the implementer adds a test named for it; none exists yet):
  `_recut(cl, i, j, s)[0] == cluster(t2)` for the splice's `t2`, over random splices
  with marks, joiners and regional indicators at the seam, so dropping the seed
  changes no Edit (its `_cl`, cursor and every op's answer are the same); a change
  costs one `cluster(t2)` of its text.

Usage:
    from cure.interact.input.edit import Edit, keys, apply, insert, cut, place, submit
    from cure.interact.input.edit import command, EDIT_BINDINGS
    from cure.interact.input.events import Key, Paste, key
    e = Edit("héllo")                     # cursor 5: the end
    apply(e, "word_left").cursor          # 0
    apply(Edit("ab"), "left").cursor      # 1
    keys(Edit("ab"), key("ctrl+s"))       # None: not typed; commands come from the table
    keys(Edit("ab"), Paste("x\\ny")).text  # "abx\\ny": pasted as it is, one line or not
    e = keys(keys(Edit(""), key("h")), key("i"))
    e.text, len(e.undo)                   # ("hi", 1): typed keys coalesce
    apply(e, "undo").text                 # ""
    Edit("中a").column                    # 3
    Edit("e\\u0301x", 1).before            # "e\\u0301": one cluster
    insert(Edit("abc", limit=4), "xyz").text      # "abcx"
    cut(apply(Edit("one two"), "select_word_left"))   # (Edit("one ", ...), "two")
    place(Edit("中a"), 1).cursor          # 0: column 1 is inside "中"
    apply(Edit("ab"), "newline")          # None: a one-line edit
    a = Edit("hello\\nhi\\nworld", 4, area=True)   # line 0, column 4
    a.rows, a.position                    # (("hello", "hi", "world"), (0, 4))
    b = apply(a, "down")
    b.position, b.goal                    # ((1, 2), 4): "hi" is short, the goal stays
    apply(b, "down").position             # (2, 4): back on the goal column
    apply(a, "end").cursor                # 5: the end of the line
    command(("edit", "left")), command("quit")    # ("left", None)
    submit(Edit("ls")).history            # ("ls",)
"""

from dataclasses import dataclass, field

from cure.core.text import cluster, width  # noqa: F401 (clusters and cells: see the module)

from .bindings import Binding
from .events import Key, Paste

EDIT = "edit"

EDIT_SCOPE = "edit"

COMMANDS = (
    "left", "right", "home", "end", "top", "bottom", "word_left", "word_right",
    "up", "down",
    "select_left", "select_right", "select_home", "select_end", "select_up",
    "select_down", "select_word_left", "select_word_right", "select_all",
    "delete_left", "delete_right", "delete_word_left", "delete_word_right",
    "delete_home", "delete_end", "newline",
    "undo", "redo", "older", "newer",
)


def _b(keys: "str | tuple[str, ...]", name: str, label: str) -> Binding:
    return Binding(keys, (EDIT, name), label, group="edit", scope=EDIT_SCOPE)


EDIT_BINDINGS = (
    _b(("left", "ctrl+b"), "left", "left"),
    _b(("right", "ctrl+f"), "right", "right"),
    _b(("home", "ctrl+a"), "home", "line start"),
    _b(("end", "ctrl+e"), "end", "line end"),
    _b("ctrl+home", "top", "start"),
    _b("ctrl+end", "bottom", "end"),
    _b(("ctrl+left", "alt+b"), "word_left", "word left"),
    _b(("ctrl+right", "alt+f"), "word_right", "word right"),
    _b("up", "up", "up"),
    _b("down", "down", "down"),
    _b("shift+left", "select_left", "select left"),
    _b("shift+right", "select_right", "select right"),
    _b("shift+home", "select_home", "select to line start"),
    _b("shift+end", "select_end", "select to line end"),
    _b("shift+up", "select_up", "select up"),
    _b("shift+down", "select_down", "select down"),
    _b("ctrl+shift+left", "select_word_left", "select word left"),
    _b("ctrl+shift+right", "select_word_right", "select word right"),
    _b(("backspace", "ctrl+h"), "delete_left", "delete left"),
    _b(("delete", "ctrl+d"), "delete_right", "delete right"),
    _b(("ctrl+w", "alt+backspace", "ctrl+backspace"), "delete_word_left", "delete word left"),
    _b(("alt+d", "ctrl+delete"), "delete_word_right", "delete word right"),
    _b("ctrl+u", "delete_home", "delete to line start"),
    _b("ctrl+k", "delete_end", "delete to line end"),
    _b("enter", "newline", "new line"),
    _b("ctrl+z", "undo", "undo"),
    _b(("ctrl+y", "ctrl+shift+z"), "redo", "redo"),
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _opt_int(value: object, name: str) -> None:
    if value is not None and not _is_int(value):
        raise TypeError(f"{name} must be None or an int, got {type(value).__name__}")


def _need_bool(value: object, name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool, got {type(value).__name__}")


def _snapshots(value: object, name: str) -> None:
    if not isinstance(value, tuple) or not all(isinstance(s, Snapshot) for s in value):
        raise TypeError(f"Edit.{name} must be a tuple of Snapshot")


_CUTS: dict = {}


def _cut(text: str) -> "tuple[str, ...]":
    """`cluster(text)`, memoised for the last texts seen (an edit's text is cut once per
    change, not once per check). Contract (Q9a, see the module): `_cut(text)` alone,
    every entry computed here; the `cl` argument goes, and `_splice` stops passing one."""
    got = _CUTS.get(text) if text.__class__ is str else None
    if got is None:
        got = cluster(text)          # TypeError as `cluster` gives it, nothing stored
        if len(_CUTS) >= 64:
            del _CUTS[next(iter(_CUTS))]
        _CUTS[text] = got
    return got


_WIDTHS: dict = {}


def _w(c: str) -> int:
    """One cluster's cells (memoised: route runs on every key)."""
    got = _WIDTHS.get(c)
    if got is None:
        got = width(c)
        if len(_WIDTHS) < 4096:
            _WIDTHS[c] = got
    return got


def _word(c: str) -> bool:
    return c[0].isalnum() or c[0] == "_"


def _is_break(c: str) -> bool:
    return c == "\n" or c == "\r\n"


@dataclass(frozen=True)
class Snapshot:
    """One undo step: the text, cursor and anchor before a change."""

    text: str
    cursor: int
    anchor: "int | None" = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError(f"Snapshot.text must be a str, got {type(self.text).__name__}")
        if not _is_int(self.cursor):
            raise TypeError(f"Snapshot.cursor must be an int, got {type(self.cursor).__name__}")
        _opt_int(self.anchor, "Snapshot.anchor")
        n = len(_cut(self.text))
        if not 0 <= self.cursor <= n:
            raise ValueError(f"Snapshot.cursor {self.cursor} outside 0..{n}")
        if self.anchor is not None and not 0 <= self.anchor <= n:
            raise ValueError(f"Snapshot.anchor {self.anchor} outside 0..{n}")


_KEPT = frozenset(("_rows", "_line", "_column", "_position"))


@dataclass(frozen=True)
class Edit:
    """A text-edit value, one line or an area: text, cursor and selection in clusters, history, undo."""

    text: str = ""
    cursor: "int | None" = None
    area: bool = field(default=False, kw_only=True)
    anchor: "int | None" = field(default=None, kw_only=True)
    goal: "int | None" = field(default=None, kw_only=True)
    limit: "int | None" = field(default=None, kw_only=True)
    history: "tuple[str, ...]" = field(default=(), kw_only=True)
    recall: "int | None" = field(default=None, kw_only=True)
    draft: str = field(default="", kw_only=True)
    undo: "tuple[Snapshot, ...]" = field(default=(), kw_only=True)
    redo: "tuple[Snapshot, ...]" = field(default=(), kw_only=True)
    typing: bool = field(default=False, kw_only=True)
    depth: int = field(default=100, kw_only=True)

    # `rows`, `line`, `column` and `position`, kept on the instance at their first read
    # (an Edit never changes); not fields, so ==, hash, repr and replace never see them.
    _rows = _line = _column = _position = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError(f"Edit.text must be a str, got {type(self.text).__name__}")
        if not isinstance(self.draft, str):
            raise TypeError(f"Edit.draft must be a str, got {type(self.draft).__name__}")
        for name in ("cursor", "anchor", "goal", "limit", "recall"):
            _opt_int(getattr(self, name), f"Edit.{name}")
        _need_bool(self.area, "Edit.area")
        _need_bool(self.typing, "Edit.typing")
        if not isinstance(self.history, tuple) or not all(isinstance(h, str) for h in self.history):
            raise TypeError("Edit.history must be a tuple of str")
        _snapshots(self.undo, "undo")
        _snapshots(self.redo, "redo")
        if not _is_int(self.depth):
            raise TypeError(f"Edit.depth must be an int, got {type(self.depth).__name__}")
        cl = _cut(self.text)
        n = len(cl)
        object.__setattr__(self, "_cl", cl)
        if self.cursor is None:
            object.__setattr__(self, "cursor", n)
        elif not 0 <= self.cursor <= n:
            raise ValueError(f"Edit.cursor {self.cursor} outside 0..{n}")
        if self.anchor is not None:
            if not 0 <= self.anchor <= n:
                raise ValueError(f"Edit.anchor {self.anchor} outside 0..{n}")
            if self.anchor == self.cursor:
                object.__setattr__(self, "anchor", None)
        for name in ("goal", "limit", "depth"):
            v = getattr(self, name)
            if v is not None and v < 0:
                raise ValueError(f"Edit.{name} must be >= 0, got {v}")
        if self.limit is not None and n > self.limit:
            raise ValueError(f"Edit.text holds {n} clusters, more than the limit {self.limit}")
        if self.recall is not None and not 0 <= self.recall < len(self.history):
            raise ValueError(f"Edit.recall {self.recall} outside the history")
        if self.recall is None and self.draft != "":
            raise ValueError("Edit.draft must be \"\" while recall is None")
        if len(self.undo) > self.depth or len(self.redo) > self.depth:
            raise ValueError(f"Edit.undo and Edit.redo hold at most depth ({self.depth}) steps")

    def __getstate__(self) -> dict:
        # The kept reads are not state: a read Edit pickles (and copies) as an unread one.
        return {k: v for k, v in self.__dict__.items() if k not in _KEPT}

    @property
    def clusters(self) -> "tuple[str, ...]":
        """The text's grapheme clusters."""
        return self._cl

    @property
    def before(self) -> str:
        """The text before the cursor."""
        return "".join(self._cl[:self.cursor])

    @property
    def after(self) -> str:
        """The text after the cursor."""
        return "".join(self._cl[self.cursor:])

    @property
    def rows(self) -> "tuple[str, ...]":
        """The lines a TextInput draws: cut at the breaks in an area, (text,) on one line."""
        got = self._rows
        if got is not None:
            return got
        if not self.area:
            got = (self.text,)
        else:
            out, cur = [], []
            for c in self._cl:
                if _is_break(c):
                    out.append("".join(cur))
                    cur = []
                else:
                    cur.append(c)
            out.append("".join(cur))
            got = tuple(out)
        object.__setattr__(self, "_rows", got)
        return got

    @property
    def line(self) -> int:
        """The cursor's row in `rows` (0 on one line)."""
        got = self._line
        if got is None:
            got = sum(1 for c in self._cl[:self.cursor] if _is_break(c)) if self.area else 0
            object.__setattr__(self, "_line", got)
        return got

    @property
    def column(self) -> int:
        """The cursor's column: the cells from its row's start."""
        got = self._column
        if got is None:
            cl = self._cl
            got = _cells(cl, _start(cl, self.area, self.cursor), self.cursor)
            object.__setattr__(self, "_column", got)
        return got

    @property
    def position(self) -> "tuple[int, int]":
        """(line, column): where a TextInput puts the terminal cursor."""
        got = self._position
        if got is None:
            got = (self.line, self.column)
            object.__setattr__(self, "_position", got)
        return got

    @property
    def selection(self) -> "tuple[int, int] | None":
        """The selected cluster range (start, end), or None."""
        if self.anchor is None:
            return None
        return (min(self.anchor, self.cursor), max(self.anchor, self.cursor))

    @property
    def selected(self) -> str:
        """The selected text, "" with no selection."""
        sel = self.selection
        return "" if sel is None else "".join(self._cl[sel[0]:sel[1]])


# -- lines, columns and words, over a cluster tuple --------------------------------------

def _start(cl: "tuple[str, ...]", area: bool, i: int) -> int:
    """S(i): just after the last break before i, else 0."""
    if area:
        for b in range(i - 1, -1, -1):
            if _is_break(cl[b]):
                return b + 1
    return 0


def _end(cl: "tuple[str, ...]", area: bool, i: int) -> int:
    """E(i): the first break at or after i, else n."""
    if area:
        for b in range(i, len(cl)):
            if _is_break(cl[b]):
                return b
    return len(cl)


def _cells(cl: "tuple[str, ...]", s: int, i: int) -> int:
    return sum(_w(c) for c in cl[s:i])


def _at(cl: "tuple[str, ...]", s: int, e: int, g: int) -> int:
    """The largest k in s..e whose cells from s fit in g."""
    w, k = 0, s
    while k < e:
        w += _w(cl[k])
        if w > g:
            break
        k += 1
    return k


def _word_left(cl: "tuple[str, ...]", i: int) -> int:
    while i > 0 and not _word(cl[i - 1]):
        i -= 1
    while i > 0 and _word(cl[i - 1]):
        i -= 1
    return i


def _word_right(cl: "tuple[str, ...]", i: int) -> int:
    n = len(cl)
    while i < n and not _word(cl[i]):
        i += 1
    while i < n and _word(cl[i]):
        i += 1
    return i


# -- changes --------------------------------------------------------------------------

def _keep(steps: "tuple[Snapshot, ...]", depth: int) -> "tuple[Snapshot, ...]":
    return steps[-depth:] if depth > 0 else ()


def _recut(cl: "tuple[str, ...]", i: int, j: int, s: str) -> "tuple[tuple[str, ...], int]":
    """`(cluster(t2), len(cluster(head)))` for the splice of [i, j) with s, re-cutting only
    near the seam. Text cuts greedily, left to right, each break decided by the cluster so
    far and the next code point; so the clusters before cl[i - 1] stand, a prefix of the
    text is cut as the whole is up to its last cluster, and once the new text breaks
    where an old cluster cl[k] (k >= j) began, cl[k:] stand too."""
    a = max(0, i - 1)
    lead = cl[a] if i > 0 else ""
    seam = len(lead) + len(s)          # where the old tail starts in the piece
    n, m = len(cl), j
    while True:
        m = min(n, m + 4)
        mid = cluster(lead + s + "".join(cl[j:m]))
        if m == n:
            new, k = mid, n
            break
        old, off = {}, seam            # an old tail cluster's start -> its index
        for k in range(j, m):
            old[off] = k
            off += len(cl[k])
        pos, found = 0, None
        for idx, c in enumerate(mid):
            if pos in old:
                found = (idx, old[pos])
                break
            pos += len(c)
        if found is not None:
            new, k = mid[:found[0]], found[1]
            break
    head, pos = 0, 0                   # t2's clusters that start inside head
    for c in new:
        if pos >= seam:
            break
        head += 1
        pos += len(c)
    return cl[:a] + new + cl[k:], a + head


def _splice(e: Edit, i: int, j: int, s: str, *, typed: bool = False) -> Edit:
    """Replace clusters [i, j) with s (see "Splices"); one undo step unless coalesced.
    Contract (Q9a): `t2` and the cursor come from `_recut`; the new Edit cuts `t2`
    through `_cut(t2)` (computed there), and `_splice` writes nothing to `_CUTS`."""
    if i >= j and s == "":
        return _make(e, goal=None, typing=False)
    cl = e._cl
    t2_cl, cursor = _recut(cl, i, j, s)
    t2 = "".join(t2_cl)
    cursor = min(cursor, len(t2_cl))
    if typed and e.typing and e.anchor is None:
        undo = e.undo
    else:
        undo = _keep(e.undo + (Snapshot(e.text, e.cursor, e.anchor),), e.depth)
    return _make(e, text=t2, cursor=cursor, anchor=None, goal=None, recall=None,
                 draft="", undo=undo, redo=(), typing=typed)


def _make(e: Edit, **changes) -> Edit:
    """A new Edit with some fields changed, every check run."""
    f = {"text": e.text, "cursor": e.cursor, "area": e.area, "anchor": e.anchor,
         "goal": e.goal, "limit": e.limit, "history": e.history, "recall": e.recall,
         "draft": e.draft, "undo": e.undo, "redo": e.redo, "typing": e.typing,
         "depth": e.depth}
    f.update(changes)
    return Edit(f.pop("text"), f.pop("cursor"), **f)


def _fit(e: Edit, i: int, j: int, text: str) -> str:
    """The longest prefix of text's clusters, joined, that keeps the result within the limit."""
    if e.limit is None:
        return text
    parts = cluster(text)
    cl = e._cl
    rest = len(cl) - (j - i)
    safe = max(0, min(len(parts), e.limit - rest))   # never more clusters than rest + k
    head, tail = "".join(cl[:i]), "".join(cl[j:])
    for k in range(min(len(parts), safe + 8), safe, -1):   # merges at the seams may fit more
        if len(cluster(head + "".join(parts[:k]) + tail)) <= e.limit:
            return "".join(parts[:k])
    return "".join(parts[:safe])


def _insert(e: Edit, text: str, *, typed: bool = False) -> Edit:
    sel = e.selection
    i, j = sel if sel is not None else (e.cursor, e.cursor)
    s = _fit(e, i, j, text)
    if s == "" and sel is None:
        return _make(e, goal=None, typing=False)
    return _splice(e, i, j, s, typed=typed)


def _move(e: Edit, cursor: int, goal: "int | None" = None) -> Edit:
    return _make(e, cursor=cursor, anchor=None, goal=goal, typing=False)


def _vertical(e: Edit, i: int, up: bool) -> "tuple[int, int]":
    """The cursor after up / down from i (an area), and the goal kept."""
    cl, n = e._cl, len(e._cl)
    s = _start(cl, True, i)
    g = e.goal if e.goal is not None else _cells(cl, s, i)
    if up:
        if s == 0:
            return 0, g
        p = s - 1
        return _at(cl, _start(cl, True, p), p, g), g
    q = _end(cl, True, i)
    if q == n:
        return n, g
    return _at(cl, q + 1, _end(cl, True, q + 1), g), g


def _plain(e: Edit, name: str, i: int) -> int:
    """Where a plain motion (no selection) takes the cursor from i."""
    cl, n, area = e._cl, len(e._cl), e.area
    if name == "left":
        return max(0, i - 1)
    if name == "right":
        return min(n, i + 1)
    if name == "home":
        return _start(cl, area, i)
    if name == "end":
        return _end(cl, area, i)
    if name == "top":
        return 0
    if name == "bottom":
        return n
    if name == "word_left":
        return _word_left(cl, i)
    return _word_right(cl, i)


def _recall(e: Edit, recall: "int | None", text: str, draft: str) -> Edit:
    if e.limit is not None:
        cl = cluster(text)
        if len(cl) > e.limit:          # an entry longer than this edit's limit: cut to fit
            text = "".join(cl[:e.limit])
    return _make(e, text=text, cursor=None, anchor=None, goal=None, recall=recall,
                 draft=draft, undo=(), redo=(), typing=False)


def _older(e: Edit) -> Edit:
    if e.recall is None:
        r = len(e.history) - 1
        return _recall(e, r, e.history[r], e.text)
    r = max(0, e.recall - 1)
    return _recall(e, r, e.history[r], e.draft)


def _newer(e: Edit) -> Edit:
    if e.recall is None:
        return _make(e, goal=None, typing=False)
    if e.recall == len(e.history) - 1:
        return _recall(e, None, e.draft, "")
    r = e.recall + 1
    return _recall(e, r, e.history[r], e.draft)


def _undo(e: Edit, back: bool) -> Edit:
    steps, other = (e.undo, e.redo) if back else (e.redo, e.undo)
    if not steps:
        return _make(e, goal=None, typing=False)
    top = steps[-1]
    other = _keep(other + (Snapshot(e.text, e.cursor, e.anchor),), e.depth)
    steps = steps[:-1]
    undo, redo = (steps, other) if back else (other, steps)
    return _make(e, text=top.text, cursor=top.cursor, anchor=top.anchor, goal=None,
                 undo=undo, redo=redo, typing=False)


_MOTIONS = frozenset({"left", "right", "home", "end", "top", "bottom", "word_left",
                      "word_right"})
_DELETES = frozenset({"delete_left", "delete_right", "delete_word_left",
                      "delete_word_right", "delete_home", "delete_end"})


def _apply(e: Edit, c: str) -> "Edit | None":
    """`apply` with its arguments checked."""
    i, sel, cl, n = e.cursor, e.selection, e._cl, len(e._cl)
    if c in _MOTIONS:
        if sel is not None and c == "left":
            return _move(e, sel[0])
        if sel is not None and c == "right":
            return _move(e, sel[1])
        return _move(e, _plain(e, c, i))
    if c == "up" or c == "down":
        if not e.area:
            if not e.history:
                return None
            return _older(e) if c == "up" else _newer(e)
        to, g = _vertical(e, i, c == "up")
        return _move(e, to, g)
    if c.startswith("select_"):
        if c == "select_all":
            return _make(e, cursor=n, anchor=0 if n else None, goal=None, typing=False)
        base = c[len("select_"):]
        anchor = e.anchor if e.anchor is not None else i
        goal = None
        if base in ("up", "down"):
            if not e.area:
                return None
            to, goal = _vertical(e, i, base == "up")
        else:
            to = _plain(e, base, i)
        return _make(e, cursor=to, anchor=None if anchor == to else anchor, goal=goal,
                     typing=False)
    if c in _DELETES:
        if sel is not None:
            return _splice(e, sel[0], sel[1], "")
        if c == "delete_left":
            return _splice(e, max(0, i - 1), i, "")
        if c == "delete_right":
            return _splice(e, i, min(n, i + 1), "")
        if c == "delete_word_left":
            return _splice(e, _word_left(cl, i), i, "")
        if c == "delete_word_right":
            return _splice(e, i, _word_right(cl, i), "")
        if c == "delete_home":
            s = _start(cl, e.area, i)
            return _splice(e, i - 1 if i == s > 0 else s, i, "")
        end = _end(cl, e.area, i)
        return _splice(e, i, i + 1 if i == end < n else end, "")
    if c == "newline":
        return _insert(e, "\n") if e.area else None
    if c == "undo" or c == "redo":
        return _undo(e, c == "undo")
    if not e.history:
        return None
    return _older(e) if c == "older" else _newer(e)


def _edit(edit: object) -> None:
    if not isinstance(edit, Edit):
        raise TypeError(f"edit must be an Edit, got {type(edit).__name__}")


_NO_TEXT = frozenset({"ctrl", "alt", "super", "hyper", "meta"})


def _typed(key: Key) -> bool:
    return (key.event != "release" and key.text != ""
            and not (key.mods and not _NO_TEXT.isdisjoint(key.mods)))


def keys(edit: Edit, event: "Key | Paste") -> "Edit | None":
    """A typed key or a paste into the edit, or None for any other key (see the module)."""
    _edit(edit)
    if isinstance(event, Paste):
        return _insert(edit, event.text)
    if not isinstance(event, Key):
        raise TypeError(f"event must be a Key or Paste, got {type(event).__name__}")
    if not _typed(event):
        return None
    return _insert(edit, event.text, typed=True)


def typed(key: Key) -> bool:
    """Whether a key types text (see the module)."""
    if not isinstance(key, Key):
        raise TypeError(f"key must be a Key, got {type(key).__name__}")
    return _typed(key)


_COMMANDS = frozenset(COMMANDS)


def command(action: object) -> "str | None":
    """The command of an (EDIT, command) action, else None (see the module)."""
    if (isinstance(action, tuple) and len(action) == 2 and action[0] == EDIT
            and isinstance(action[1], str) and action[1] in _COMMANDS):
        return action[1]
    return None


def apply(edit: Edit, command: str) -> "Edit | None":
    """One edit command, or None when the edit does not own it (see the module)."""
    _edit(edit)
    if not isinstance(command, str):
        raise TypeError(f"command must be a str, got {type(command).__name__}")
    if command not in _COMMANDS:
        raise ValueError(f"unknown edit command {command!r}")
    return _apply(edit, command)


def insert(edit: Edit, text: str) -> Edit:
    """Text inserted as it is, replacing the selection, cut to the limit (see the module)."""
    _edit(edit)
    if not isinstance(text, str):
        raise TypeError(f"text must be a str, got {type(text).__name__}")
    return _insert(edit, text)


def cut(edit: Edit) -> "tuple[Edit, str]":
    """The selection removed, and its text (see the module)."""
    _edit(edit)
    sel = edit.selection
    if sel is None:
        return _make(edit, goal=None, typing=False), ""
    return _splice(edit, sel[0], sel[1], ""), edit.selected


def place(edit: Edit, column: int, *, line: int = 0, select: bool = False) -> Edit:
    """The cursor put at a cell (row, column), selecting from the old one or not (see the module)."""
    _edit(edit)
    if not _is_int(column):
        raise TypeError(f"column must be an int, got {type(column).__name__}")
    if not _is_int(line):
        raise TypeError(f"line must be an int, got {type(line).__name__}")
    _need_bool(select, "select")
    cl, n = edit._cl, len(edit._cl)
    if edit.area:
        breaks = [b for b, c in enumerate(cl) if _is_break(c)]
        r = min(max(line, 0), len(breaks))
        s = breaks[r - 1] + 1 if r > 0 else 0
        e = breaks[r] if r < len(breaks) else n
    else:
        s, e = 0, n
    to = _at(cl, s, e, max(column, 0))
    if select:
        anchor = edit.anchor if edit.anchor is not None else edit.cursor
        anchor = None if anchor == to else anchor
    else:
        anchor = None
    return _make(edit, cursor=to, anchor=anchor, goal=None, typing=False)


def submit(edit: Edit, *, keep: "int | None" = None) -> Edit:
    """The text done: into the history, the edit emptied (see the module)."""
    _edit(edit)
    if keep is not None and not _is_int(keep):
        raise TypeError(f"keep must be None or an int, got {type(keep).__name__}")
    if keep is not None and keep < 0:
        raise ValueError(f"keep must be >= 0, got {keep}")
    history = edit.history
    if edit.text != "" and (not history or history[-1] != edit.text):
        history = history + (edit.text,)
    if keep is not None:
        history = history[-keep:] if keep else ()
    return Edit("", 0, area=edit.area, limit=edit.limit, history=history, depth=edit.depth)
