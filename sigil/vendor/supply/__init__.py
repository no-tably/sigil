"""[Supply]: Store, Loader; one cure, from one pinned commit.

Kind: system (the expansion of [Supply] in cure): outside the library. Sigil and
construct share ONE cure implementation from one pinned source: each consumer commits
only a lock naming a commit (`commit: <40 hex>`, optionally `source: <URL>`, VENDORED's
format) and loads that commit's tree. [Loader] (`cure.supply.loader`: `read_lock`,
`store_root`, `find`, `load`; reads the disk, never the network) finds the tree, a
bundled `vendor/cure` at the lock's commit first, then `$CURE_STORE/<commit>`, and puts
its folder on `sys.path`. [Store] (`cure/supply/store.py`: `install`, `fetch`, `bundle`,
and a CLI; the only place git and the network are touched) installs a commit's `cure/`
into the store and copies it into a release's `vendor/`. Depends on nothing: neither
module imports cure, so a consumer copies the two files verbatim, and in a store tree
they are present but never imported by an app.

Effects: none on import (this file imports nothing).

Usage:
    python3 cure/supply/store.py install <commit> --from <origin URL>
    python3 cure/supply/store.py bundle cure.lock release/vendor
    python3 cure/supply/store.py where cure.lock --vendor vendor
"""
