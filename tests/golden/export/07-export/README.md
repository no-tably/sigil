# Export of 07-export.sigil

Exported from `07-export.sigil` (spec hash `42c36c489b8429a2`) by sigil export.

- `manifest.json` is the contract: per system, its interface hash, body hash, components and what it depends on. It is written last; a folder without it is no finished export.
- `<system>/README.md` describes a system: its components, its boundary (the flows that cross it) and what it depends on.
- `<system>/<component>.md` states one component: kind, description, interface, requirements and lifecycle, as the spec writes them.
- `<system>/system.json` holds the same, machine-readable.

## Systems

- `07-export` (top) — [07-export/](07-export/README.md) — depends on `Catalog`, `Checkout`, `Fulfilment`, `Warehouse`
- `Catalog` (tree) — [catalog/](catalog/README.md) — depends on nothing
- `Checkout` (expansion) — [checkout/](checkout/README.md) — depends on `Fulfilment`
- `Fulfilment` (expansion) — [fulfilment/](fulfilment/README.md) — depends on nothing
- `Warehouse` (tree) — [warehouse/](warehouse/README.md) — depends on `Catalog`
