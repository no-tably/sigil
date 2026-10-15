# [Catalog]

Kind: service. Lives in system `07-export` (folder `07-export/`).

## Description

the catalogue: one tree of listings, each item with its price and stock

## Interface

- `[Storefront] -> [Catalog] : lookup({Sku}) => {Item} @fallback("cached") @timeout(500ms)` — sync call

## Requirements

None stated.
