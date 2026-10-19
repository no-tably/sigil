# 07-export

The top level of the spec: every component no expansion or tree holds.

a small shop, locked as a spec and ready to export: each expansion and each composition tree becomes a system of its own (try sigil export FILE --out DIR)

Interface hash `1468c8fefdc59fa0` · body hash `91b43631411f44b9`.

## Components

- `(Shopper)` (actor) — [shopper.md](shopper.md)
- `[Catalog]` (service) — [catalog.md](catalog.md)
- `[Checkout]` (service) — [checkout.md](checkout.md)
- `[Fulfilment]` (service) — [fulfilment.md](fulfilment.md)
- `[Storefront]` (service) — [storefront.md](storefront.md)
- `[Warehouse]` (service) — [warehouse.md](warehouse.md)

## Boundary

The flows that cross into or out of this system: its contract.

- `<OrderPlaced> *> [Fulfilment]` — async message
- `[Checkout] ~> <OrderPlaced>` — async message

## Flows inside

- `[Storefront] !> (Shopper) : <Declined>` — failure route
- `(Shopper) -> [Storefront] : browse({Query}) => {Page}` — sync call
- `(Shopper) -> [Storefront] : buy({Basket}) => {Receipt}` — sync call
- `[Storefront] -> [Catalog] : lookup({Sku}) => {Item} @fallback("cached") @timeout(500ms)` — sync call
- `[Storefront] -> [Checkout] : place({Basket}) => {Receipt} @timeout(5s)` — sync call

## Depends on

- `Catalog` — [catalog/](../catalog/README.md)
- `Checkout` — [checkout/](../checkout/README.md)
- `Fulfilment` — [fulfilment/](../fulfilment/README.md)
- `Warehouse` — [warehouse/](../warehouse/README.md)
