# Pricing Grid

## Purpose

Generate and manage the geometric price ladder that defines all valid order price levels. This is the backbone of the HIP-2 algorithm — prices are NOT computed from an AMM formula but from discrete grid positions.

## Parameters

- `start_px: float` — The initial price of the range (px_0)
- `n_orders: int` — Number of price levels in the grid
- `tick_size: float = 0.003` — Multiplicative spacing between levels (0.3% default per HIP-2)

## Core Function

```
px_0 = start_px
px_i = round(px_{i-1} * (1 + tick_size))    for i in 1..n_orders-1
```

The grid is a fixed array computed once at initialization. It does NOT shift with market conditions — the market maker's position within the grid shifts instead.

## Outputs

- `levels: list[float]` — The complete ordered price ladder, ascending
- `level_for_price(px) -> int | None` — Nearest grid level index for a given price
- `price_at_level(i) -> float` — Price at grid index i

## Invariants

1. `len(levels) == n_orders`
2. `levels[0] == start_px`
3. For all i: `levels[i+1] / levels[i]` ≈ `1 + tick_size` (subject to rounding)
4. Grid is strictly monotonically increasing
5. Grid is deterministic — same parameters always produce the same levels
6. Grid is computed once and is immutable for the lifetime of a strategy instance

## Precision

Prices must be rounded to the market's tick size (varies per spot pair — fetch from `spot_meta()`). Use the exchange's rounding convention, not arbitrary precision. The `round()` in the recurrence refers to the exchange's significant-figure rounding, which should be configurable.

## Edge Cases

- Very small `start_px` (sub-cent tokens): Ensure rounding doesn't collapse adjacent levels to the same price. If `round(px_{i-1} * 1.003) == px_{i-1}`, the grid is degenerate — raise an error.
- Very large `n_orders`: Grid extends to very high prices. No inherent limit, but memory is linear in n_orders.

## Dependencies

None. This is a pure math module with zero I/O.
