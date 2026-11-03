"""present: the drawings: kit, themes, views and the viewer app.

Present stands on cure (round 11) at the commit sigil/vendor/cure.lock names
(an archive's own copy, else the shared store: round 12): importing this package
loads it through sigil.vendor, once, so its modules may `import cure...`. Only
Present imports cure; sigil's other layers never do."""

from .. import vendor  # noqa: F401  (cure on sys.path before any `import cure`)
