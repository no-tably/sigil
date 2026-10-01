#!/usr/bin/env python3
"""
banner.py — render the README banner (assets/banner.svg) from the coin logo.

    site/banner.py [--logo coin] [--theme sigil] [--out assets/banner.svg]

The banner is the page's logo as an SVG: the same characters (site/logos/<logo>.txt)
coloured by the same per-cell codes (<logo>.mask) and theme (themes/<theme>.yaml)
as the web page, beside the wordmark. Departure Mono (site/fonts, SIL OFL) is
embedded as a data URI, so the SVG looks the same wherever it is shown. Re-run it
after changing the logo or the theme; the output is deterministic.

Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import html
import importlib.util
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
FONT = SITE / "fonts" / "DepartureMono-Regular.woff2"
ADVANCE = 0.636                       # Departure Mono: advance width / em
LINE = 1.15                           # line height / em (as on the page)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


themes = _load("sigil_themes_banner", ROOT / "themes.py")


def mix(a: str, b: str, p: float) -> str:
    """CSS color-mix(in srgb, a p, b): channel-wise, in gamma-encoded sRGB."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x * p + y * (1 - p)) for x, y in zip(ca, cb))


def code_colours(theme: dict) -> dict:
    """The mask codes' colours — the same mixes as site.css's .logo .k-* rules."""
    site, pal, ui = theme["site"], theme["palette"], theme["ui"]
    bg, strong = pal["bg"], ui["strong"]
    thread, metal, field = site["coin_thread"], site["coin_metal"], site["coin_field"]
    return {
        "1": mix(thread, bg, 0.50), "2": mix(thread, bg, 0.62), "3": mix(thread, bg, 0.86),
        "4": thread, "5": mix(thread, strong, 0.50),
        "r": mix(metal, bg, 0.34), "s": mix(metal, bg, 0.58), "t": metal,
        "u": mix(metal, strong, 0.50),
        "f": mix(field, bg, 0.18), "g": mix(field, bg, 0.30), "z": mix(field, bg, 0.08),
        "a": site["accent"],
    }


def runs(line: str, codes: str):
    """Split a row into (text, code) runs of equal code."""
    out, i = [], 0
    while i < len(line):
        j = i
        code = codes[i] if i < len(codes) else " "
        while j < len(line) and (codes[j] if j < len(codes) else " ") == code:
            j += 1
        out.append((line[i:j], code))
        i = j
    return out


def banner(logo: str, theme_name: str) -> str:
    theme = themes.load(theme_name)
    colours = code_colours(theme)
    art = (SITE / "logos" / f"{logo}.txt").read_text(encoding="utf-8").rstrip("\n").split("\n")
    mask_path = SITE / "logos" / f"{logo}.mask"
    mask = mask_path.read_text(encoding="utf-8").split("\n") if mask_path.is_file() else []

    fs = 18                                   # logo font size (px)
    cw, lh = fs * ADVANCE, fs * LINE
    pad = 36
    cols = max(len(r) for r in art)
    logo_w, logo_h = cols * cw, len(art) * lh
    text_x = pad + logo_w + 48
    width = round(text_x + 470)
    height = round(logo_h + 2 * pad)
    bg, kinds, ui = theme["palette"]["bg"], theme["kinds"], theme["ui"]

    font = base64.b64encode(FONT.read_bytes()).decode("ascii")
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Sigil">',
        "<style>",
        f'@font-face{{font-family:"Departure Mono";src:url(data:font/woff2;base64,{font}) format("woff2")}}',
        'text{font-family:"Departure Mono",monospace;white-space:pre}',
        "</style>",
        f'<rect width="{width}" height="{height}" rx="18" fill="{bg}"/>',
    ]
    for y, line in enumerate(art):
        codes = mask[y] if y < len(mask) else ""
        baseline = pad + y * lh + fs * 0.92
        spans, x = [], 0
        for text, code in runs(line, codes):
            if text.strip():
                fill = colours.get(code, ui["text"])
                spans.append(f'<tspan x="{pad + x * cw:.2f}" fill="{fill}">{html.escape(text)}</tspan>')
            x += len(text)
        if spans:
            out.append(f'<text y="{baseline:.2f}" font-size="{fs}">{"".join(spans)}</text>')

    # the wordmark: the five glyphs form the name, each in its kind's colour
    mark = [("[", "S", "]", "service"), ("{", "I", "}", "data"), ("<", "G", ">", "event"),
            ("(", "I", ")", "actor"), ("|", "L", "|", "store")]
    wfs = 44
    wy = height / 2 - 6
    spans, x = [], text_x
    for open_, letter, close, kind in mark:
        for ch, fill in ((open_, kinds[kind]), (letter, ui["strong"]), (close, kinds[kind])):
            spans.append(f'<tspan x="{x:.2f}" fill="{fill}">{html.escape(ch)}</tspan>')
            x += wfs * ADVANCE
    out.append(f'<text y="{wy:.2f}" font-size="{wfs}">{"".join(spans)}</text>')
    tag = "a compact notation for system designs"
    out.append(f'<text x="{text_x:.2f}" y="{wy + 40:.2f}" font-size="16.5" '
               f'fill="{ui["muted"]}">{tag}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the README banner SVG.")
    ap.add_argument("--logo", default="coin")
    ap.add_argument("--theme", default="sigil")
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "banner.svg")
    a = ap.parse_args()
    svg = banner(a.logo, a.theme)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(svg, encoding="utf-8")
    print(f"banner: {a.out} ({len(svg) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
