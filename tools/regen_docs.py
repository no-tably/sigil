#!/usr/bin/env python3
"""
regen_docs.py — regenerate the drawings embedded in the docs from view.py.

    tools/regen_docs.py           # rewrite them in place, report what changed
    tools/regen_docs.py --check   # exit 1 if any drawing is stale (for tests / CI)

- examples.md: each ```text block (a `--tree` drawing) is redrawn from the Sigil
  block just above it (`view.py --once --tree --no-lint --width 200`, the drawing
  part only — no legend or summary);
- README.md: the drawing after "`view.py` draws it in the terminal:" is redrawn
  from the README's first ```sigil block (`view.py --once`, summary included).

Standard library only.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(src: str, *args: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".sigil", delete=False) as f:
        f.write(src)
        name = f.name
    try:
        r = subprocess.run([sys.executable, str(ROOT / "view.py"), name, "--once",
                            "--color", "never", *args], capture_output=True, text=True,
                           check=True)
    finally:
        os.unlink(name)
    return r.stdout.replace(os.path.basename(name), "checkout.sigil")


def tidy(text: str) -> str:
    return "\n".join(ln.rstrip() for ln in text.split("\n")).strip("\n") + "\n"


def examples(text: str) -> tuple[str, int]:
    blocks = list(re.finditer(r"```(\w*)\n(.*?)```", text, re.S))
    out, changed = text, 0
    for k, m in enumerate(blocks):
        if m.group(1) != "text":
            continue
        src = next((b for b in reversed(blocks[:k]) if b.group(1) != "text"), None)
        if src is None:
            continue
        lines = run(src.group(2), "--tree", "--no-lint", "--width", "200").split("\n")
        cut = next((i for i, ln in enumerate(lines) if ln.startswith("tree ")), len(lines))
        draw = tidy("\n".join(lines[:cut]))
        if draw != m.group(2):
            changed += 1
            out = out.replace("```text\n" + m.group(2) + "```", "```text\n" + draw + "```", 1)
    return out, changed


def readme(text: str) -> tuple[str, int]:
    src = re.search(r"```sigil\n(.*?)```", text, re.S)
    old = re.search(r"`view.py` draws it in the terminal:\n\n```\n(.*?)```", text, re.S)
    if not src or not old:
        return text, 0
    new = tidy(run(src.group(1)))
    if new == old.group(1):
        return text, 0
    return text.replace(old.group(0), old.group(0).replace(old.group(1), new)), 1


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = 0
    for name, fn in (("examples.md", examples), ("README.md", readme)):
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        new, changed = fn(text)
        stale += changed
        if changed and not check:
            path.write_text(new, encoding="utf-8")
        print(f"{name}: {changed} drawing(s) {'stale' if check else 'updated'}")
    return 1 if check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
