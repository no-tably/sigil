# [Checkout]

Kind: service. Lives in system `07-export` (folder `07-export/`).

## Interface

- `[Storefront] -> [Checkout] : place({Basket}) => {Receipt} @timeout(5s)` — sync call
- `[Checkout] ~> <OrderPlaced>` — async message

## Requirements

None stated.
