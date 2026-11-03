"""present: the drawings: kit, themes, views and the viewer app.

Present stands on cure (round 11), vendored under sigil/vendor: importing this
package puts it on the path once, so its modules may `import cure...`. Only
Present imports cure; sigil's other layers never do."""

from .. import vendor  # noqa: F401  (cure on sys.path before any `import cure`)
