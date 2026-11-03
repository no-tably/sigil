"""[Solver]: fixed, min, max, percent, ratio, fill, auto; largest remainder, no residue.

Kind: service (pure functions over plain values; the constraint values are frozen
dataclasses, checked on construction). Rects first: every node gets its rect before
anything paints, and this is the one place a length is divided among children. Flex
(`row`), Scaffold (`regions`) and, from L2, Splits (`panes`) call it; it knows nothing
of nodes, rects or text. A direct greedy solver (no cassowary), in ratatui's
vocabulary.

Constraints (frozen dataclasses; equality is field by field):
- `Fixed(n)`: exactly `n` cells (n >= 0). Shrinks last.
- `Min(n)`: at least `n` cells (n >= 0); takes a share of spare room when no `Fill` is
  present. Shrinks after the soft ones, before `Fixed`.
- `Max(n)`: up to `n` cells (n >= 0): it asks for `n`, never gets more, shrinks first.
- `Percent(p)`: `p` percent of the available length (0 <= p <= 100). Soft.
- `Ratio(a, b)`: `a / b` of the available length (0 <= a <= b, b >= 1). Soft.
- `Fill(weight=1)`: whatever is left, shared among the fills by weight (weight >= 1).
- `Auto()`: the item's natural size, which the caller's `measure` gives (Layout never
  measures anything itself). Soft: it asks for its natural size and shrinks first.
`Constraint` is the tuple of these seven classes (for `isinstance`).

The available length. `gaps(count, gap, space)` are reserved first; the items share
`avail = max(space, 0) - sum(gaps(...))`. A negative `space` counts as 0.

The algorithm, `solve(constraints, space, *, gap=0, measure=None)`:

1. Targets (exact rationals, `fractions.Fraction`): `Fixed(n)` and `Min(n)` ask `n`;
   `Max(n)` asks `n`; `Percent(p)` asks `p * avail / 100`; `Ratio(a, b)` asks
   `a * avail / b`; `Auto()` asks `measure(i)`; `Fill` asks 0. `T` is their sum.
2. Spare (`T <= avail`): every item gets its target, then the spare `avail - T` goes
   to the fills, item i getting `spare * weight_i / total_weight`. With no fill it goes
   to the `Min` items in equal shares. With neither, it is left over: no item grows,
   and the sizes sum to less than `avail` (Flex's `justify` places the rest).
3. Short (`T > avail`): the deficit `D = T - avail` is taken from the tiers in this
   order, each tier shrunk in proportion to its items' targets, a tier reaching 0
   before the next is touched:
   - soft: `Max`, `Percent`, `Ratio`, `Auto`;
   - floors: `Min`;
   - hard: `Fixed`.
   Within a tier with total `S` that must give up `d <= S`, item i keeps
   `t_i * (S - d) / S`. Fills stay at 0. The exact sizes then sum to exactly `avail`.
4. Whole cells, by largest remainder: each item gets the floor of its exact size; the
   `N - sum(floors)` cells left over, where `N` is the floor of the exact sizes' sum,
   go one each to the items with the largest fractional parts; equal fractional
   parts go to the LOWER index first. An item whose exact size is a whole number never
   gets a cell more, so `Fixed`, `Min` and `Max` bounds hold after rounding.

Laws (each true for every input; a test can loop over them):
- `len(solve(cs, s, ...)) == len(cs)` and every size is an int >= 0.
- `sum(sizes) + sum(gaps(len(cs), gap, s)) <= max(s, 0)`.
- No residue: `sum(sizes) == avail` whenever `cs` holds a `Fill` or a `Min`, or the
  exact targets sum to `avail` or more. Rounding never loses or invents a cell.
- `Fixed(n)` gets exactly `n` whenever the `Fixed` items' `n` sum to `avail` or less.
- `Min(n)` gets at least `n` whenever the `Fixed` and `Min` items' `n` sum to `avail`
  or less.
- `Max(n)` never gets more than `n`; a soft item never more than the ceiling of its
  target; a `Fill` gets 0 whenever the exact targets sum to `avail` or more.
- Equal constraints with equal targets get sizes that differ by at most 1, the larger
  ones first (the lower-index tie-break).
- The same arguments always give the same sizes.

Other operations:
- `apportion(total, weights) -> tuple[int, ...]`: `total` cells split in proportion to
  `weights` by largest remainder: item i's exact share is `total * w_i / W` (`W` the
  sum), floored, and the cells left over go to the largest fractional parts, the lower
  index first on a tie. The shares sum to exactly `total`, except when `W == 0`, which
  gives all zeros. A weight of 0 always gets 0. `()` for no weights.
- `gaps(count, gap, space) -> tuple[int, ...]`: the `max(count - 1, 0)` gaps between
  `count` items: each `gap` when `gap * (count - 1) <= max(space, 0)`, else
  `apportion(max(space, 0), (1,) * (count - 1))` (the gaps take all the space, earlier
  gaps one cell wider, and every item gets 0).

Inputs: `constraints`: an iterable of constraint values; `space`, `gap`, `total`,
  `count`: ints (never `bool`), `gap`, `total`, `count` >= 0; `weights`: an iterable of
  ints or `fractions.Fraction` >= 0; `measure`: `None` or a callable `measure(i) -> int`,
  called exactly once for each `Auto` item i, in ascending index order, before any
  sizing.
Outputs: a tuple of ints, one per item (per gap for `gaps`).
Errors: `TypeError` when a constraint field, `space`, `gap`, `count` or `total` is not
  an int (a `bool` included), an item of `constraints` is not a constraint value, a
  weight is not an int or Fraction, or `measure` returns a non-int; `ValueError` when a
  constraint field is out of range (as listed above), `gap`, `count`, `total` or a
  weight is negative, `measure` returns a negative int, or an `Auto` item is given no
  `measure`. Assigning a field raises `dataclasses.FrozenInstanceError`.
Effects: none (beyond calling `measure`).

Usage:
    from cure.draw.layout.solver import Fixed, Min, Max, Percent, Fill, Auto, solve
    solve([Fixed(3), Fill(1), Fixed(3)], 20)        # (3, 14, 3)
    solve([Fill(1), Fill(1), Fill(1)], 10)          # (4, 3, 3): the tie to the lower index
    solve([Fill(1), Fill(2)], 10)                   # (3, 7)
    solve([Percent(50), Percent(50)], 7)            # (4, 3): no residue
    solve([Percent(33)] * 3, 100)                   # (33, 33, 33): no grower, 1 cell left over
    solve([Fixed(10), Fixed(10)], 15)               # (8, 7): the hard tier shrinks last
    solve([Min(5), Percent(50)], 8)                 # (5, 3): soft shrinks before the floor
    solve([Min(5), Percent(50)], 20)                # (10, 10): no fill, so Min takes the spare
    solve([Max(4), Fill(1)], 10)                    # (4, 6)
    solve([Max(4), Fixed(8)], 10)                   # (2, 8)
    solve([Fill(1), Fill(1)], 11, gap=1)            # (5, 5)
    solve([Fixed(2)] * 3, 1, gap=1)                 # (0, 0, 0): gaps (1, 0) take the space
    solve([Auto(), Fill(1)], 10, measure=lambda i: 3)   # (3, 7)
    solve([Fill(1)], -5)                            # (0,)
    apportion(10, (1, 1, 1))                        # (4, 3, 3)
    apportion(7, (2, 1))                            # (5, 2)
    gaps(3, 1, 10), gaps(3, 2, 3)                   # ((1, 1), (2, 1))
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fractions import Fraction


def _int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def _at_least(value: object, low: int, name: str) -> None:
    _int(value, name)
    if value < low:
        raise ValueError(f"{name} must be >= {low}, got {value}")


@dataclass(frozen=True)
class Fixed:
    """Exactly `n` cells; shrinks last."""

    n: int

    def __post_init__(self) -> None:
        _at_least(self.n, 0, "n")


@dataclass(frozen=True)
class Min:
    """At least `n` cells; grows into spare room when no Fill is present."""

    n: int

    def __post_init__(self) -> None:
        _at_least(self.n, 0, "n")


@dataclass(frozen=True)
class Max:
    """Up to `n` cells: asks for `n`, never more; shrinks first."""

    n: int

    def __post_init__(self) -> None:
        _at_least(self.n, 0, "n")


@dataclass(frozen=True)
class Percent:
    """`p` percent of the available length (0..100); shrinks first."""

    p: int

    def __post_init__(self) -> None:
        _at_least(self.p, 0, "p")
        if self.p > 100:
            raise ValueError(f"p must be <= 100, got {self.p}")


@dataclass(frozen=True)
class Ratio:
    """`a / b` of the available length (0 <= a <= b, b >= 1); shrinks first."""

    a: int
    b: int

    def __post_init__(self) -> None:
        _at_least(self.a, 0, "a")
        _at_least(self.b, 1, "b")
        if self.a > self.b:
            raise ValueError(f"a must be <= b, got {self.a}/{self.b}")


@dataclass(frozen=True)
class Fill:
    """What is left, shared among the fills by `weight` (>= 1)."""

    weight: int = 1

    def __post_init__(self) -> None:
        _at_least(self.weight, 1, "weight")


@dataclass(frozen=True)
class Auto:
    """The natural size the caller's `measure` gives; shrinks first."""


Constraint = (Fixed, Min, Max, Percent, Ratio, Fill, Auto)


def solve(constraints: Iterable, space: int, *, gap: int = 0,
          measure: "Callable[[int], int] | None" = None) -> tuple[int, ...]:
    """The sizes of the items along `space` cells, by the algorithm above."""
    items = tuple(constraints)
    for item in items:
        if not isinstance(item, Constraint):
            raise TypeError(f"constraints must hold constraint values, got {type(item).__name__}")
    _int(space, "space")
    _at_least(gap, 0, "gap")
    avail = max(space, 0) - sum(gaps(len(items), gap, space))
    targets = _targets(items, avail, measure)
    total = sum(targets, Fraction(0))
    if total <= avail:
        exact = _grow(items, targets, avail - total)
    else:
        exact = _shrink(items, targets, total - avail)
    return _whole(exact)


def apportion(total: int, weights: "Iterable[int | Fraction]") -> tuple[int, ...]:
    """`total` split in proportion to `weights` by largest remainder (ties: lower index)."""
    _at_least(total, 0, "total")
    shares = tuple(weights)
    for w in shares:
        if isinstance(w, bool) or not isinstance(w, (int, Fraction)):
            raise TypeError(f"a weight must be an int or Fraction, got {type(w).__name__}")
        if w < 0:
            raise ValueError(f"a weight must be >= 0, got {w}")
    whole = sum(shares, Fraction(0))
    if whole == 0:
        return (0,) * len(shares)
    return _whole([Fraction(total) * w / whole for w in shares])


def gaps(count: int, gap: int, space: int) -> tuple[int, ...]:
    """The gaps between `count` items: `gap` each, or the space shared when it is short."""
    _at_least(count, 0, "count")
    _at_least(gap, 0, "gap")
    _int(space, "space")
    n = max(count - 1, 0)
    room = max(space, 0)
    if gap * n <= room:
        return (gap,) * n
    return apportion(room, (1,) * n)


_SOFT = (Max, Percent, Ratio, Auto)


def _measured(measure: "Callable[[int], int]", i: int) -> int:
    value = measure(i)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"measure must return an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"measure must return an int >= 0, got {value}")
    return value


def _targets(items: tuple, avail: int, measure: "Callable[[int], int] | None") -> list:
    """Each item's exact target (step 1); `measure` called once per Auto, in order."""
    if measure is None and any(isinstance(c, Auto) for c in items):
        raise ValueError("an Auto constraint needs a measure")
    out = []
    for i, c in enumerate(items):
        if isinstance(c, (Fixed, Min, Max)):
            out.append(Fraction(c.n))
        elif isinstance(c, Percent):
            out.append(Fraction(c.p * avail, 100))
        elif isinstance(c, Ratio):
            out.append(Fraction(c.a * avail, c.b))
        elif isinstance(c, Auto):
            out.append(Fraction(_measured(measure, i)))
        else:
            out.append(Fraction(0))
    return out


def _grow(items: tuple, targets: list, spare: Fraction) -> list:
    """Step 2: the spare to the fills by weight, else to the Mins equally, else left over."""
    fills = [i for i, c in enumerate(items) if isinstance(c, Fill)]
    exact = list(targets)
    if fills:
        weight = sum(items[i].weight for i in fills)
        for i in fills:
            exact[i] += spare * items[i].weight / weight
        return exact
    mins = [i for i, c in enumerate(items) if isinstance(c, Min)]
    for i in mins:
        exact[i] += spare / len(mins)
    return exact


def _shrink(items: tuple, targets: list, deficit: Fraction) -> list:
    """Step 3: the deficit taken tier by tier (soft, Min, Fixed), each in proportion."""
    exact = list(targets)
    for tier in (_SOFT, (Min,), (Fixed,)):
        if deficit <= 0:
            break
        members = [i for i, c in enumerate(items) if isinstance(c, tier)]
        size = sum((targets[i] for i in members), Fraction(0))
        if size == 0:
            continue
        taken = min(deficit, size)
        for i in members:
            exact[i] = targets[i] * (size - taken) / size
        deficit -= taken
    return exact


def _whole(exact: "list[Fraction]") -> tuple[int, ...]:
    """Step 4: floors, then the floor of the sum's leftover cells by largest remainder."""
    floors = [e.numerator // e.denominator for e in exact]
    total = sum(exact, Fraction(0))
    left = total.numerator // total.denominator - sum(floors)
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:left]:
        floors[i] += 1
    return tuple(floors)
