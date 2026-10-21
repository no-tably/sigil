"""The system kind: the `#%` line after the mode line (`#% library deterministic`).

A kind is three choices, each with a default — shape (service, library, daemon,
job), reach (networked, in-process), concurrency (concurrent, deterministic). A
document without the line is the defaults and checks as it always has. Each
word names the rule groups it turns off; which rule is in which group is the
checks' (sigil.analyse.check.RULE_GROUPS). A table, no rules: lint reports a
malformed line, check reads the groups off."""

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


class Kind(NamedTuple):
    """A document's kind: the word of each choice (the default where the line
    names none), the words as written, and the 0-based line of the `#%` (None:
    no line)."""
    shape: str = "service"
    reach: str = "networked"
    concurrency: str = "concurrent"
    words: tuple = ()
    line: Optional[int] = None

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


def read_kind(lines: list) -> Kind:
    """The kind of a document (its `lines`): the first well-placed `#%` line's
    known words, one per choice (the first wins; lint reports the rest)."""
    at = next((k for k in kind_lines(lines) if placed(lines, k)), None)
    if at is None:
        return Kind()
    words = kind_words(lines[at])
    chosen = {}
    for w in words:
        c = CHOICE_OF.get(w)
        if c is not None:
            chosen.setdefault(c, w)
    return Kind(**chosen, words=tuple(words), line=at)
