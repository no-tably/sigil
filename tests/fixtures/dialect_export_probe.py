"""A probe dialect for the export (tests/test_export_dialect.py): it declares a
`#& probe` block, defines a VERSION (recorded in the export's manifest), knows
one modifier (`@at(path)`, listed with its `@`) and reads `[[Name]]` as a glyph
of its own kind, `ref`, carrying metadata in Node.attrs (exported as `attrs`).
Standard library only; loaded with dialects.load(<this path>).
"""

import re

NAME = "export-probe"
VERSION = "1.2"
DECLARATIONS = {"probe"}
KNOWN_MODIFIERS = {"@at"}
NODE_KINDS = {"ref": {"open": "[[", "close": "]]", "mermaid_shape": ("[[", "]]"),
                      "mermaid_class": "ref", "classdef": "fill:#eeeeee"}}

_REF_RE = re.compile(r"\[\[([A-Za-z][A-Za-z0-9]*)\]\]")


def _ref(s, i, prev, layer, Node):
    m = _REF_RE.match(s, i)
    if not m:
        return None
    node = Node(id=m.group(1) + "_ref", name=m.group(1), kind="ref", layer=layer,
                attrs={"pinned": True, "tags": ("a", "b")})
    return [("glyph", node)], m.end(), True


def tokenizers():
    return [_ref]
