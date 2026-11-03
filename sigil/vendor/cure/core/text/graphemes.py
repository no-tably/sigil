"""[Graphemes]: split text into grapheme clusters: base + marks, ZWJ, VS16, regional pairs.

Kind: service (pure functions).

What it does: cuts a string into the clusters a terminal draws as one glyph. It is
a stated subset of UAX #29 extended grapheme clusters, built on [Width]'s
per-code-point table (so it reads no `unicodedata`, and its answers are frozen with
the release like the widths).

Terms, for a code point `c`:
- control: `width.control(c)`: C0, DEL, C1 (U+0000..U+001F, U+007F..U+009F) or a
  surrogate (U+D800..U+DFFF).
- extender: not a control, and either `width.point(c) == 0` (combining marks Mn/Me,
  format characters Cf such as ZWJ U+200D, ZWNJ, ZWSP U+200B, the variation selectors,
  the tags, and the Hangul medial/final jamo) or a skin-tone modifier
  U+1F3FB..U+1F3FF.
- regional indicator (RI): U+1F1E6..U+1F1FF.
- base: a code point that is neither a control nor an extender.

The rules, between the previous code point `prev` and the current one `cur`, applied
in this order (the first that matches decides):

1. `prev` is CR (U+000D) and `cur` is LF (U+000A): no break (CR LF is one cluster).
2. `prev` or `cur` is a control: break. (Nothing attaches to a control.)
3. `cur` is an extender: no break. An extender at the start of the text, or right
   after a control, begins a cluster of its own (a base-less cluster).
4. `prev` is ZWJ and the current cluster holds a base: no break (emoji ZWJ
   sequences; simplified: any following code point joins, there is no
   Extended_Pictographic check).
5. `prev` and `cur` are both RIs and the current cluster is exactly one RI: no break
   (flags pair up; a third RI starts a new cluster).
6. Otherwise: break.

Not covered (each is its own cluster unless a rule above joins it): spacing marks
(Mc), prepend characters, Hangul L/V/T syllable rules beyond the jamo extenders,
Indic conjuncts.

Bidi: the bidi formatting characters ([Width]'s `BIDI`: U+061C, U+200E, U+200F,
U+202A..U+202E, U+2066..U+2069) are Cf of width 0, so they are extenders here like
any other: `cluster("a\\u202e") == ("a\\u202e",)`, and U+2028 / U+2029 are bases of
width 1. Segmentation keeps those answers (and puts no bound on a cluster's length);
the guarantee is Buffer's Display, which sends a glyph holding any of them, or more
than `MAX_CLUSTER` code points, as U+FFFD. Nothing here filters them.

Inputs: `cluster(text)`: a `str` ({Text}).
Outputs: {Clusters}: a tuple of non-empty `str`, one per cluster, in order, with
  `"".join(cluster(text)) == text`; `cluster("") == ()`.
Errors: `TypeError` when `text` is not a `str`.
Effects: none.

Graphemes reads [Width] through its public names only (`width.control`,
`width.point`), never `width._is_control`: the per-call classing in `cluster` asks
`width.control(cur)` of each code point (a `str` of length 1, so it never raises).

Speed: `cluster` takes the printable-ASCII fast path the package states (a code point
in U+0020..U+007E is a cluster of its own unless an extender follows it or it follows a
ZWJ after a base); the result is the rules' result, law fast_equal of `cure.core.text`.

Usage:
    from cure.core.text.graphemes import cluster
    cluster("e\\u0301x")         # ("e\\u0301", "x")
    cluster("🇺🇸🇬")             # ("🇺🇸", "🇬")
    cluster("👨\\u200d👩")        # ("👨\\u200d👩",)
    cluster("a\\r\\nb")           # ("a", "\\r\\n", "b")
    cluster("\\u0301a")           # ("\\u0301", "a")
"""

from functools import lru_cache

from . import width

ZWJ = "‍"
RI_RANGE = (0x1F1E6, 0x1F1FF)
MODIFIER_RANGE = (0x1F3FB, 0x1F3FF)
_RI_FIRST, _RI_LAST = chr(RI_RANGE[0]), chr(RI_RANGE[1])


def extender(char: str) -> bool:
    """True when code point `char` is an extender (see the module). `TypeError` if
    not a `str`, `ValueError` if `len(char) != 1`."""
    if width.control(char):
        return False
    return width.point(char) == 0 or _within(MODIFIER_RANGE, char)


def cluster(text: str) -> tuple[str, ...]:
    """The grapheme clusters of `text`, by the rules above."""
    if not isinstance(text, str):
        raise TypeError(f"expected a str, got {type(text).__name__}")
    if text.__class__ is str and text.isascii() and text.isprintable():
        return tuple(text)            # Speed: printable ASCII, one cluster per code point
    for char in set(text):
        if not _lone(char):
            break
    else:
        return tuple(text)            # every code point a base no rule joins (rule 6)
    out: list[str] = []
    current = ""
    has_base = False
    prev, prev_ctl = "", False
    classes: dict = {}               # code point -> (control, extender), within this call
    for cur in text:
        # Each code point is classed once per call (control, extender), by `width.control`
        # for every one; a printable-ASCII one is a base without the table (Speed).
        if cur in classes:
            ctl, ext = classes[cur]
        else:
            ctl = width.control(cur)
            ext = not ctl and not " " <= cur <= "~" and (
                width.point(cur) == 0 or _within(MODIFIER_RANGE, cur))
            classes[cur] = (ctl, ext)
        if current:
            # Rules 2-6 in short when nothing joins: neither is a control, `cur` is no
            # extender nor an RI, and `prev` is no ZWJ (so rules 1, 4 and 5 cannot apply).
            if (not (ctl or prev_ctl or ext) and prev != ZWJ
                    and not _RI_FIRST <= cur <= _RI_LAST) or _breaks(
                        current, has_base, prev, prev_ctl, cur, ctl, ext):
                out.append(current)
                current, has_base = "", False
        current += cur
        has_base = has_base or not (ctl or ext)
        prev, prev_ctl = cur, ctl
    if current:
        out.append(current)
    return tuple(out)


@lru_cache(maxsize=4096)
def _lone(char: str) -> bool:
    """A code point that is a cluster of its own wherever it stands: a base (neither a
    control nor an extender, so not ZWJ) that is not an RI. Between two such code points
    only rule 6 applies. Memoised: the answer is the frozen table's."""
    return not (width.control(char) or extender(char) or _within(RI_RANGE, char))


def _breaks(current: str, has_base: bool, prev: str, prev_ctl: bool, cur: str, ctl: bool,
            ext: bool) -> bool:
    """Rules 1-6 between `prev` (the last code point of `current`) and `cur`, given
    whether each is a control and whether `cur` is an extender."""
    if prev == "\r" and cur == "\n":
        return False
    if prev_ctl or ctl:
        return True
    if ext:
        return False
    if prev == ZWJ and has_base:
        return False
    if _within(RI_RANGE, prev) and _within(RI_RANGE, cur) and len(current) == 1:
        return False
    return True


def _within(bounds: tuple[int, int], char: str) -> bool:
    return bounds[0] <= ord(char) <= bounds[1]
