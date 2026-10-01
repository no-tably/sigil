#!/usr/bin/env python3
"""
coin.py — draw the Sigil coin logo: an embossed, embroidered `&` on a coin,
pixel-art style, one character per pixel, stitched from Sigil's own glyph
characters.

    site/logos/coin.py [--rows N] [--rim F] [--curl] [--name NAME]

Writes <name>.txt (the characters) and <name>.mask (one colour code per cell,
same shape) next to this file, and prints the coin. The committed files come
from exactly these commands:

    site/logos/coin.py                              # coin.txt, coin.mask
    site/logos/coin.py --rows 15 --name coin-small  # coin-small.txt, .mask

The defaults are the plain `&` (two crossings), 19 rows, the rim's inner edge
at 0.92 of the radius; --curl draws the flourished `&` with a third crossing.

How it is drawn:
  - a height map: a bevelled rim, a flat woven field, the `&` raised on it;
  - the `&` is one cord along a spline; it twists (rope shading along its
    length) and where it crosses itself the passes alternate over and under,
    with a groove cut around the over-pass — knotwork;
  - light comes from the top left: each cell's shade is the cord's or the
    rim's slope toward the light, and the `&` casts a shadow down-right;
  - the character follows the stroke like satin stitches, darkest to
    brightest: - ~ = along, : | ] across, \\ \\ & and / / & on the diagonals
    (the brightest diagonal stitch is an `&` itself);
  - the field is a faint weave of glyph brackets and ·, with . in shadow;
  - the rim is - ~ = across the top and bottom and ( ) at the sides,
    [ ] where a side catches the light.

Mask codes (the contract with site.css, .logo .k-<code>), darkest first:

    r s t u      rim
    1 2 3 4 5    cord
    f g          field: the · / a weave bracket
    z            field in the `&`'s shadow
    (space)      outside the coin

Standard library only.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

DEFAULT_ROWS = 19
DEFAULT_RIM = 0.92
MIN_ROWS = 6                     # smaller, and the & is too small to cross itself cleanly

# The `&` as one stroke in a unit box (x 0..1, y 0..1.25): tail at the bottom
# right, up the diagonal into the top loop, down through the bowl, up to the arm.
AMP = [(0.98, 1.22), (0.80, 1.02), (0.58, 0.80), (0.36, 0.58), (0.22, 0.38), (0.24, 0.14),
       (0.44, 0.02), (0.64, 0.10), (0.68, 0.30), (0.54, 0.48), (0.28, 0.68), (0.12, 0.94),
       (0.22, 1.17), (0.48, 1.25), (0.72, 1.10), (0.88, 0.86), (1.00, 0.72)]

# The same & with a flourish: the tail starts inside the bowl and runs out
# under the rising stroke before hooking into the diagonal — a third crossing.
AMP_CURL = [(0.34, 0.96), (0.52, 1.08), (0.74, 1.20), (0.94, 1.22), (0.98, 1.10)] + AMP[1:]

LIGHT = (-0.62, -0.78)           # toward the light: top left (x right, y down)

# Geometry, in visual units (1 unit = 1 column = half a row).
AMP_HEIGHT = 0.60                # the & is this fraction of the coin's diameter
AMP_NUDGE = 0.4                  # and sits this much low, so it reads as centred
CORD_MIN_HALF_WIDTH = 1.8        # the cord is never thinner than this ...
CORD_WIDTH_PER_ROW = 0.15        # ... and otherwise grows with the coin
CROSS_REACH = 0.5                # two passes cross when closer than this many stroke widths
CROSS_SEP = 10                   # passes count as two when 1/10 of the cord apart
BUMP_WIDTH = 16                  # an over/under bump spans +-1/16 of the cord
GROOVE = 0.9                     # an under-pass is cut away this far beyond an over-pass
SEARCH_PAD = 1.6                 # bounding-box margin beyond the half-width
RIM_TOP_SINE = 0.72              # rim cells with |sin(angle)| above this are top/bottom
RIM_SIDE_BRIGHT = 0.75           # a side this lit swaps ( ) for [ ]
SHADOW = (1.2, 1.4)              # the & casts its shadow this far right and down

# Cord shading: base + roundness * slope toward the light - edge falloff,
# then a rope twist along the cord and a lift on the over-passes.
SHADE_BASE, SHADE_ROUND, SHADE_EDGE = 0.62, 0.42, 0.18
TWIST_SLANT, TWIST_FREQ, TWIST_DEPTH = 1.4, 1.25, 0.16
OVER_LIFT = 0.12

# Stitch direction: the cord's angle (degrees, 0..180, y down) picks a ramp;
# under ALONG (or from 180 - ALONG) is along, then \ diagonal, across, / diagonal.
ALONG, DIAGONAL, ACROSS = 25, 65, 115
RAMP_ALONG, RAMP_BACK, RAMP_ACROSS, RAMP_FORWARD = "-~=", "\\\\&", ":|]", "//&"
RAMP_RIM_TOP = "-~="
WEAVE = "[]{}<>()|"


def catmull(pts: list[tuple[float, float]], n: int = 60) -> list[tuple[float, float]]:
    """Uniform Catmull-Rom spline through pts, n samples per segment; the end
    points are duplicated so the curve starts and ends on them."""
    out = []
    padded = [pts[0]] + pts + [pts[-1]]
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
        for k in range(n):
            t = k / n
            sq, cu = t * t, t * t * t
            out.append(tuple(0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t
                                    + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * sq
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * cu)
                             for j in (0, 1)))
    out.append(pts[-1])
    return out


def pick(ramp: str, v: float) -> str:
    v = min(max(v, 0.0), 0.999)
    return ramp[int(v * len(ramp))]


def cord_path(rows: int, curl: bool) -> list[tuple[float, float]]:
    """The `&` cord as spline samples in visual units, centred on the coin."""
    size = rows * 2 * AMP_HEIGHT             # & height
    pts = catmull(AMP_CURL if curl else AMP)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    s = size / (max(ys) - min(ys))
    ox = rows - (max(xs) + min(xs)) / 2 * s
    oy = rows - (max(ys) + min(ys)) / 2 * s + AMP_NUDGE
    return [(ox + x * s, oy + y * s) for x, y in pts]


def crossings(path: list[tuple[float, float]], rows: int) -> list[tuple[int, int]]:
    """Where the cord crosses itself: pairs of sample indices far apart along
    the cord but close in space, one pair per crossing."""
    # The reach follows the stroke's natural width (before the half-width
    # floor), so a small coin doesn't find a crossing in every tight curve.
    reach = CROSS_REACH * min(rows * CORD_WIDTH_PER_ROW, CORD_MIN_HALF_WIDTH)
    tsep = len(path) // CROSS_SEP
    cross = []
    for i in range(0, len(path), 2):
        for j in range(i + tsep, len(path), 2):
            if math.dist(path[i], path[j]) < reach and not any(
                    abs(i - a) < tsep and abs(j - b) < tsep for a, b in cross):
                cross.append((i, j))
    return cross


def coin(rows: int = DEFAULT_ROWS, curl: bool = False,
         rim: float = DEFAULT_RIM) -> tuple[list[str], list[str], int]:
    """Draw the coin: (character rows, mask rows, number of crossings)."""
    if rows < MIN_ROWS:
        raise ValueError(f"rows must be >= {MIN_ROWS}")
    if not 0 < rim < 1:
        raise ValueError("rim must be between 0 and 1")
    cols = rows * 2                          # cells are twice as tall as wide
    # Everything below is in visual units: the coin's radius is `rows` and its
    # centre (rows, rows); cell (x, y) sits at (x + 0.5, (y + 0.5) * 2).

    path = cord_path(rows, curl)
    n_samples = len(path)
    arc = [0.0]
    for i in range(1, n_samples):
        arc.append(arc[-1] + math.dist(path[i - 1], path[i]))

    w = max(CORD_MIN_HALF_WIDTH, rows * CORD_WIDTH_PER_ROW)     # cord half-width
    tsep = n_samples // CROSS_SEP
    cross = crossings(path, rows)

    # Over/under alternates by event order along the cord: each pass through
    # a crossing raises (even) or sinks (odd) a tent-shaped bump. Bumps closer
    # than 2 * win overlap, and where they do the later one wins.
    events = sorted(t for c in cross for t in c)
    z = [0.0] * n_samples
    win = n_samples // BUMP_WIDTH
    for k, t in enumerate(events):
        for d in range(-win, win + 1):
            if 0 <= t + d < n_samples:
                bump = 1 - abs(d) / win
                z[t + d] = max(z[t + d], bump) if k % 2 == 0 else min(z[t + d], -bump)

    over = [j for j in range(n_samples) if z[j] > 0]
    pad = w + SEARCH_PAD
    x_lo, x_hi = min(p[0] for p in path) - pad, max(p[0] for p in path) + pad
    y_lo, y_hi = min(p[1] for p in path) - pad, max(p[1] for p in path) + pad
    # samples bucketed on a grid of side w: anything within w of a point is in
    # the 3 x 3 buckets around it (kept in cord order, so ties break as before)
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, (sx, sy) in enumerate(path):
        buckets.setdefault((math.floor(sx / w), math.floor(sy / w)), []).append(i)
    near: dict[tuple[int, int], list[int]] = {}

    def nearby(px, py):
        key = (math.floor(px / w), math.floor(py / w))
        if key not in near:
            near[key] = sorted(i for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                               for i in buckets.get((key[0] + dx, key[1] + dy), ()))
        return near[key]

    def cord(px, py):
        """Nearest visible cord sample at (px, py), or None:
        (dist, index, signed offset across the cord, tangent, normal)."""
        if not (x_lo < px < x_hi and y_lo < py < y_hi):
            return None
        best = None
        for i in nearby(px, py):
            d = math.hypot(px - path[i][0], py - path[i][1])
            if d < w:
                key = (z[i], -d)             # the highest pass wins, then the nearest
                if best is None or key > best[0]:
                    best = (key, d, i)
        if best is None:
            return None
        _, d, i = best
        # a groove: an under-pass is hidden where an over-pass runs close by
        if z[i] < 0:
            for j in over:
                if abs(j - i) > tsep and math.hypot(px - path[j][0], py - path[j][1]) < w + GROOVE:
                    return None
        prev, next_ = path[max(i - 1, 0)], path[min(i + 1, n_samples - 1)]
        tx, ty = next_[0] - prev[0], next_[1] - prev[1]
        length = math.hypot(tx, ty) or 1
        tx, ty = tx / length, ty / length
        nx, ny = -ty, tx
        off = (px - path[i][0]) * nx + (py - path[i][1]) * ny
        return d, i, off, (tx, ty), (nx, ny)

    chars, mask = [], []
    for y in range(rows):
        crow, mrow = [], []
        for x in range(cols):
            px, py = x + 0.5, (y + 0.5) * 2
            u, v = (px - rows) / rows, (py - rows) / rows    # on the unit disc
            r = math.hypot(u, v)
            if r > 1.0:
                crow.append(" ")
                mrow.append(" ")
                continue
            if r > rim:
                # bevelled rim: the slope faces the light on the top-left
                rx, ry = u / (r or 1), v / (r or 1)
                lit = 0.5 + 0.5 * (rx * LIGHT[0] + ry * LIGHT[1])
                ang = math.atan2(v, u)
                if abs(math.sin(ang)) > RIM_TOP_SINE:        # top / bottom
                    ch = pick(RAMP_RIM_TOP, lit)
                else:                                        # sides
                    ch = "(" if u < 0 else ")"
                    if lit > RIM_SIDE_BRIGHT:
                        ch = "[" if u < 0 else "]"
                crow.append(ch)
                mrow.append(pick("rstu", lit))
                continue
            hit = cord(px, py)
            if hit:
                d, i, off, (tx, ty), (nx, ny) = hit
                # rounded profile lit from the top left, plus a rope twist
                slope = off / w
                facing = nx * LIGHT[0] + ny * LIGHT[1]
                lit = SHADE_BASE + SHADE_ROUND * slope * facing - SHADE_EDGE * (d / w) ** 2
                twist = math.sin((arc[i] + off * TWIST_SLANT) * TWIST_FREQ)
                lit += TWIST_DEPTH * twist + OVER_LIFT * max(z[i], 0)
                ang = math.degrees(math.atan2(ty, tx)) % 180
                if ang < ALONG or ang >= 180 - ALONG:
                    ramp = RAMP_ALONG
                elif ang < DIAGONAL:
                    ramp = RAMP_BACK
                elif ang < ACROSS:
                    ramp = RAMP_ACROSS
                else:
                    ramp = RAMP_FORWARD
                crow.append(pick(ramp, lit))
                mrow.append(pick("12345", lit))
                continue
            # field: a faint weave; the & casts a shadow down-right. The shadow
            # reuses cord(), groove included, so it breaks where the cord does.
            if cord(px - SHADOW[0], py - SHADOW[1]) is not None:
                crow.append(".")
                mrow.append("z")
            elif (x + y) % 2 == 0:
                crow.append(WEAVE[(x + 3 * y) % len(WEAVE)])
                mrow.append("g")
            else:
                crow.append("·")
                mrow.append("f")
        chars.append("".join(crow).rstrip())
        mask.append("".join(mrow).rstrip())
    return chars, mask, len(cross)


def _rows(text: str) -> int:
    n = int(text)
    if n < MIN_ROWS:
        raise argparse.ArgumentTypeError(f"must be >= {MIN_ROWS}")
    return n


def _rim(text: str) -> float:
    f = float(text)
    if not 0 < f < 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1, exclusive")
    return f


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Draw the Sigil coin logo.")
    ap.add_argument("--rows", type=_rows, default=DEFAULT_ROWS,
                    help=f"height in rows, >= {MIN_ROWS} (default {DEFAULT_ROWS})")
    ap.add_argument("--rim", type=_rim, default=DEFAULT_RIM,
                    help=f"inner edge of the rim, 0..1 of the radius (default {DEFAULT_RIM})")
    ap.add_argument("--curl", action="store_true", help="the flourished & (three crossings)")
    ap.add_argument("--name", default="coin",
                    help="output base name, written next to this file (default coin)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    name = Path(args.name).name              # never write outside this directory
    if not name:
        raise SystemExit("coin.py: --name must be a file name")
    chars, mask, n = coin(args.rows, args.curl, args.rim)
    (HERE / f"{name}.txt").write_text("\n".join(chars) + "\n", encoding="utf-8")
    (HERE / f"{name}.mask").write_text("\n".join(mask) + "\n", encoding="utf-8")
    print("\n".join(chars))
    print(f"{name}: {args.rows} rows, {n} crossings")
    return 0                                 # every failure above raises


if __name__ == "__main__":
    raise SystemExit(main())
