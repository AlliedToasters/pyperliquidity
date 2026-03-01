# Pricing Grid

## Purpose

Generate and manage the geometric price ladder that defines all valid order price levels. This is the backbone of the HIP-2 algorithm — prices are NOT computed from an AMM formula but from discrete grid positions.

## Parameters

- `start_px: float` — The initial price of the range (px_0)
- `n_orders: int` — Number of price levels in the grid
- `tick_size: float = 0.003` — Multiplicative spacing between levels (0.3% default per HIP-2)
- `round_fn: Callable[[float], float]` — Optional rounding callable applied at each recurrence step. Defaults to Python's `round()` with 8 significant figures.

## Core Function

```
px_0 = start_px
px_i = round_fn(px_{i-1} * (1 + tick_size))    for i in 1..n_orders-1
```

The grid is a fixed tuple computed once at initialization via `__post_init__`. It does NOT shift with market conditions — the market maker's position within the grid shifts instead.

### Grid Generation

The system SHALL generate a geometric price ladder of exactly `n_orders` levels starting from `start_px`, where each successive level is computed as `round_fn(prev_level * (1 + tick_size))`.

- **Standard grid**: `PricingGrid(start_px=1.0, n_orders=5, tick_size=0.003)` → exactly 5 prices, starting at 1.0, each ~0.3% higher
- **Custom tick size**: `tick_size=0.01` → each level ~1% higher
- **Deterministic**: identical parameters always produce identical `levels` tuples

### Configurable Rounding

- **Custom rounding**: `round_fn=lambda px: round(px, 4)` → all levels rounded to 4 decimal places
- **Default rounding**: omitting `round_fn` uses significant-figure rounding

### Degenerate Grid Detection

The system SHALL raise a `ValueError` during initialization if rounding causes any two adjacent levels to have the same price.

- **Degenerate**: `start_px=0.000001, tick_size=0.003, round_fn=lambda px: round(px, 6)` → `ValueError`
- **Valid sub-cent**: `start_px=0.001, tick_size=0.003` with sufficient precision → succeeds

## Outputs

- `levels: tuple[float, ...]` — The complete ordered price ladder, ascending. Returns a tuple (immutable).
- `level_for_price(px: float) -> int | None` — Nearest grid level index for a given price, using `bisect` for O(log n) lookup. Returns `None` if price is outside grid range by more than half a tick spacing. Tie-breaks to lower index.
- `price_at_level(i: int) -> float` — Price at grid index i. Raises `IndexError` if out of bounds.

### Level Lookup Scenarios

- **Exact match**: `level_for_price(levels[3])` → returns `3`
- **Between levels**: price closer to `levels[3]` → returns `3`
- **Below grid**: price far below `levels[0]` → returns `None`
- **Above grid**: price far above `levels[-1]` → returns `None`
- **Tie-breaking**: price equidistant between two levels → returns the lower index

## Invariants

1. `len(levels) == n_orders`
2. `levels[0] == start_px`
3. For all i: `levels[i+1] / levels[i]` ≈ `1 + tick_size` (subject to rounding)
4. Grid is strictly monotonically increasing: for all valid i, `levels[i] < levels[i+1]`
5. Grid is deterministic — same parameters always produce the same levels
6. Grid is computed once and is immutable for the lifetime of the `PricingGrid` instance
7. `levels` is a `tuple`, not a `list`; attribute assignment raises an error (frozen dataclass)

## Dependencies

None. This is a pure math module with zero I/O.
