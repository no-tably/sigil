# Checkout

The expansion of `[Checkout]` (inside system `07-export`).

Interface hash `fffc59f5459c4cb1` · body hash `d0693387d15a8f92`.

## Components

- `<OrderPlaced>` (event) — [orderplaced.md](orderplaced.md)
- `[Basket]` (service) — [basket.md](basket.md)
- `[Payments]` (service) — [payments.md](payments.md)
- `|Orders|` (store) — [orders.md](orders.md)

## Boundary

The flows that cross into or out of this system: its contract.

- `<OrderPlaced> *> [Fulfilment]` — async message
- `[Storefront] -> [Checkout] : place({Basket}) => {Receipt} @timeout(5s)` — sync call

## Flows inside

- `[Basket] -> [Payments] : charge({Total}) => {Receipt} @after(1s) @inv idempotent(order) ×3` — sync call
- `[Basket] -> |Orders| : save({Order}) => {Ack}` — sync call
- `[Basket] ~> <OrderPlaced>` — async message
- `[Checkout] ~> <OrderPlaced>` — async message

## Depends on

- `Fulfilment` — [fulfilment/](../fulfilment/README.md)
