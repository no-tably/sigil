# [Storefront]

Kind: service. Lives in system `07-export` (folder `07-export/`).

## Interface

- `[Storefront] !> (Shopper) : <Declined>` — failure route
- `(Shopper) -> [Storefront] : browse({Query}) => {Page}` — sync call
- `(Shopper) -> [Storefront] : buy({Basket}) => {Receipt}` — sync call
- `[Storefront] -> [Catalog] : lookup({Sku}) => {Item} @fallback("cached") @timeout(500ms)` — sync call
- `[Storefront] -> [Checkout] : place({Basket}) => {Receipt} @timeout(5s)` — sync call

## Requirements

- `@sla(p99<200ms)`
