# Catalog

The composition tree rooted at `[Catalog]` (inside system `07-export`).

the catalogue: one tree of listings, each item with its price and stock

Interface hash `6ee737df5791f50f` · body hash `047fc4d040438706`.

## Components

- `|Listings|` (store) — [listings.md](listings.md)
- `|Prices|` (store) — [prices.md](prices.md)

## Boundary

The flows that cross into or out of this system: its contract.

- `[Stock] -> |Prices| : reprice({Sku}) => {Ack}` — sync call
- `[Storefront] -> [Catalog] : lookup({Sku}) => {Item} @fallback("cached") @timeout(500ms)` — sync call

## Depends on

Nothing.
