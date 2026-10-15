# Fulfilment

The expansion of `[Fulfilment]` (inside system `07-export`).

Interface hash `f4c9217ea2e53929` · body hash `13deb10563612e66`.

## Components

- `<Shipped>` (event) — [shipped.md](shipped.md)
- `[Packer]` (service) — [packer.md](packer.md)
- `[Picker]` (service) — [picker.md](picker.md)

## Boundary

The flows that cross into or out of this system: its contract.

- `<OrderPlaced> *> [Fulfilment]` — async message

## Flows inside

- `[Picker] -> [Packer] : pack({Order}) => {Parcel}` — sync call
- `[Packer] ~> <Shipped>` — async message

## Depends on

Nothing.
