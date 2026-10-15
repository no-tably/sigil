# [Payments]

Kind: service. Lives in system `Checkout` (folder `checkout/`).

## Interface

- `[Basket] -> [Payments] : charge({Total}) => {Receipt} @after(1s) @inv idempotent(order) ×3` — sync call

## Requirements

None stated.
