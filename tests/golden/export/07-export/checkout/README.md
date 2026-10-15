# Checkout

The expansion of `[Checkout]` (inside system `07-export`).

Interface hash `c5e61598f9c8e9b7` · body hash `4a4cefe89c2592b6`.

## Components

- `[Basket]` (service) — [basket.md](basket.md)
- `[Payments]` (service) — [payments.md](payments.md)
- `|Orders|` (store) — [orders.md](orders.md)

## Boundary

The flows that cross into or out of this system: its contract.

- `[Storefront] -> [Checkout] : place({Basket}) => {Receipt} @timeout(5s)` — sync call
- `[Basket] ~> <OrderPlaced>` — async message
- `[Checkout] ~> <OrderPlaced>` — async message

## Flows inside

- `[Basket] -> [Payments] : charge({Total}) => {Receipt} @after(1s) @inv idempotent(order) ×3` — sync call
- `[Basket] -> |Orders| : save({Order}) => {Ack}` — sync call

## Depends on

- `07-export` — [07-export/](../07-export/README.md)
