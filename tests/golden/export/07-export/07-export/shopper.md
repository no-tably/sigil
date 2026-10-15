# (Shopper)

Kind: actor. Lives in system `07-export` (folder `07-export/`).

## Description

signed-in shoppers only; the storefront answers every request

a failed payment reaches the shopper

## Interface

- `[Storefront] !> (Shopper) : <Declined>` — failure route
- `(Shopper) -> [Storefront] : browse({Query}) => {Page}` — sync call
- `(Shopper) -> [Storefront] : buy({Basket}) => {Receipt}` — sync call

## Requirements

None stated.
