# <OrderPlaced>

Kind: event. Lives in system `Checkout` (folder `checkout/`). Also written in: `07-export`.

## Interface

- `<OrderPlaced> *> [Fulfilment]` — async message
- `[Basket] ~> <OrderPlaced>` — async message
- `[Checkout] ~> <OrderPlaced>` — async message

## Requirements

None stated.
