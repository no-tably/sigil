# Warehouse

The composition tree rooted at `[Warehouse]` (inside system `07-export`).

the warehouse: its stock counts set the prices of scarce items

Interface hash `2e16d14892b8eed5` · body hash `43fb9956b782789c`.

## Components

- `[Stock]` (service) — [stock.md](stock.md)

## Boundary

The flows that cross into or out of this system: its contract.

- `[Stock] -> |Prices| : reprice({Sku}) => {Ack}` — sync call

## Depends on

- `Catalog` — [catalog/](../catalog/README.md)
