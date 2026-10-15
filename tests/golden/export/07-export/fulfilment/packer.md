# [Packer]

Kind: service. Lives in system `Fulfilment` (folder `fulfilment/`).

## Description

the packer's modes

## Interface

- `[Picker] -> [Packer] : pack({Order}) => {Parcel}` — sync call
- `[Packer] ~> <Shipped>` — async message

## Requirements

- `@inv ordered(order)`
- `@inv retention(1h)`

## Lifecycle

States: `Idle`, `Packing`.
Initial: `Packing`.
Terminal: none.

- `+` → `Packing` on `<OrderPlaced>`
- `Idle` → `Packing` on `<OrderPlaced>`
- `Packing` → `Idle` on `<Shipped>`
- `Packing` → `Packing` on `<OrderPlaced>`
