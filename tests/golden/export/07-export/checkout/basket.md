# [Basket]

Kind: service. Lives in system `Checkout` (folder `checkout/`).

## Description

holds the basket until it is paid

## Interface

- `[Basket] -> [Payments] : charge({Total}) => {Receipt} @after(1s) @inv idempotent(order) ×3` — sync call
- `[Basket] -> |Orders| : save({Order}) => {Ack}` — sync call
- `[Basket] ~> <OrderPlaced>` — async message

## Requirements

None stated.
