"""Sigil: a compact notation for system designs, and its tools.

Layers, each importing only the ones before it:

    core      the notation read: dialects, the parser and its graph
    model     what the design does: the scene, the simulator
    analyse   is it sound: lint, check and its rule modules
    publish   what leaves sigil: the export folder, Mermaid
    present   the drawings: kit, themes, views, the viewer app

`sigil.cli` is the one command (`bin/sigil`, `python3 -m sigil`).

`__version__` is the one version (`sigil --version`, an export's manifest); a test
keeps it equal to plugin/meta.json's, which packaging reads.
"""

__version__ = "0.6.11"
