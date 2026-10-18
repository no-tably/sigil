# 07-export

The top level of the spec: every component no expansion or tree holds.

a small shop, locked as a spec and ready to export: each expansion and each composition tree becomes a system of its own (try sigil export FILE --out DIR)

Interface hash `f418b361e094547a` · body hash `75979ceff2c70e06`.

## Components

- `(Shopper)` (actor) — [shopper.md](shopper.md)
- `<OrderPlaced>` (event) — [orderplaced.md](orderplaced.md)
- `[Catalog]` (service) — [catalog.md](catalog.md)
- `[Checkout]` (service) — [checkout.md](checkout.md)
- `[Fulfilment]` (service) — [fulfilment.md](fulfilment.md)
- `[Storefront]` (service) — [storefront.md](storefront.md)
- `[Warehouse]` (service) — [warehouse.md](warehouse.md)

## Boundary

The flows that cross into or out of this system: its contract.

- `[Basket] ~> <OrderPlaced>` — async message

## Flows inside

- `[Storefront] !> (Shopper) : <Declined>` — failure route
- `<OrderPlaced> *> [Fulfilment]` — async message
- `(Shopper) -> [Storefront] : browse({Query}) => {Page}` — sync call
- `(Shopper) -> [Storefront] : buy({Basket}) => {Receipt}` — sync call
- `[Storefront] -> [Catalog] : lookup({Sku}) => {Item} @fallback("cached") @timeout(500ms)` — sync call
- `[Storefront] -> [Checkout] : place({Basket}) => {Receipt} @timeout(5s)` — sync call
- `[Checkout] ~> <OrderPlaced>` — async message

## Depends on

- `Catalog` — [catalog/](../catalog/README.md)
- `Checkout` — [checkout/](../checkout/README.md)
- `Fulfilment` — [fulfilment/](../fulfilment/README.md)
- `Warehouse` — [warehouse/](../warehouse/README.md)
