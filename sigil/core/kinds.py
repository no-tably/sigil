"""The system kind: the `#%` line after the mode line (`#% library deterministic`).

A kind is three choices, each with a default — shape (service, library, daemon,
job), reach (networked, in-process), concurrency (concurrent, deterministic). A
document without the line is the defaults and checks as it always has. Each
word names the rule groups it turns off; which rule is in which group is the
checks' (sigil.analyse.check.RULE_GROUPS). A table, no rules: lint reports a
malformed line, check reads the groups off.

The line is read once, by Core's walk (sigil.core.statements.read_lines calls
read_kind): the Kind rides on the Walk (`walk.kind`) and on the Graph
(`graph.kind`), with every `#%` line as written (Kind.written), so lint and check
read the record, never the text again."""

from __future__ import annotations

from typing import NamedTuple, Optional

from sigil.core.lex import first_content, is_mode_line

KIND_MARK = "#%"

# choice → its words, the default first
CHOICES = {
    "shape": ("service", "library", "daemon", "job"),
    "reach": ("networked", "in-process"),
    "concurrency": ("concurrent", "deterministic"),
}

# word → the rule groups it turns off (the defaults turn off none)
OFF = {
    "library": ("entry", "traffic"),
    "job": ("traffic",),
    "daemon": ("ending",),
    "in-process": ("network",),
    "deterministic": ("concurrency",),
}

GROUPS = ("global", "network", "concurrency", "traffic", "ending", "entry")

CHOICE_OF = {w: c for c, words in CHOICES.items() for w in words}


class KindLine(NamedTuple):
    """One `#%` line as written: its 0-based `line`, its `words` (every word, in
    order, its trailing `# …` comment cut; kind_words) and whether it is
    `placed` where a kind is read (placed()). Only the first placed one is read;
    lint reports the others."""
    line: int
    words: tuple
    placed: bool


class Kind(NamedTuple):
    """A document's kind: the word of each choice (the default where the line
    names none), the read line's words as written, the 0-based line of that
    `#%` (None: none read), and `written`: every `#%` line of the document
    (KindLine), in order, read or not. A reading of the words that is not a
    choice (a word naming no kind, a later `name=N` pair) keeps to `words`:
    the choices take only the words CHOICE_OF knows."""
    shape: str = "service"
    reach: str = "networked"
    concurrency: str = "concurrent"
    words: tuple = ()
    line: Optional[int] = None
    written: tuple = ()

    @property
    def read(self) -> Optional[KindLine]:
        """The `#%` line this kind was read from (None: none placed)."""
        return next((w for w in self.written if w.line == self.line), None)

    @property
    def ignored(self) -> tuple:
        """The `#%` lines not read (misplaced, or after the one read)."""
        return tuple(w for w in self.written if w.line != self.line)

    @property
    def off(self) -> tuple:
        """The groups this kind turns off, in GROUPS order."""
        named = {g for w in (self.shape, self.reach, self.concurrency) for g in OFF.get(w, ())}
        return tuple(g for g in GROUPS if g in named)

    @property
    def text(self) -> str:
        """The kind as written after `#%` (the words the line names)."""
        return " ".join(self.words)


def is_kind_line(line: str) -> bool:
    """Whether the line is a `#%` kind line (indented or not)."""
    return line.lstrip().startswith(KIND_MARK)


def kind_lines(lines: list) -> list:
    """The 0-based index of every `#%` line."""
    return [k for k, line in enumerate(lines) if is_kind_line(line)]


def kind_words(line: str) -> list:
    """The words of a `#%` line, its trailing `# …` comment cut."""
    body = line.lstrip()[len(KIND_MARK):]
    return body.split("#", 1)[0].split()


def placed(lines: list, k: int) -> bool:
    """Whether the `#%` line at `k` sits where it is read: after the mode line
    and before the first statement (comment and blank lines between are fine)."""
    first = first_content(lines)
    return (first is not None and is_mode_line(lines[first]) and first < k
            and not any(lines[j].strip() and j != k and not lines[j].lstrip().startswith("#")
                        for j in range(first + 1, k)))


def written_lines(lines: list) -> tuple:
    """Every `#%` line of a document (its `lines`) as a KindLine, in order."""
    return tuple(KindLine(k, tuple(kind_words(lines[k])), placed(lines, k))
                 for k in kind_lines(lines))


def kind_of(read: Optional[KindLine], written: tuple = ()) -> Kind:
    """The Kind a `#%` line says (`read`; None: the defaults): its known words,
    one per choice (the first wins; lint reports the rest). `written`: every
    `#%` line, carried as Kind.written."""
    if read is None:
        return Kind(written=written)
    chosen = {}
    for w in read.words:
        c = CHOICE_OF.get(w)
        if c is not None:
            chosen.setdefault(c, w)
    return Kind(**chosen, words=read.words, line=read.line, written=written)


def read_kind(lines: list) -> Kind:
    """The kind of a document (its `lines`): the first well-placed `#%` line's
    (kind_of), with every `#%` line it has. Core's walk calls it once
    (Walk.kind); everything else reads that record."""
    written = written_lines(lines)
    return kind_of(next((w for w in written if w.placed), None), written)
