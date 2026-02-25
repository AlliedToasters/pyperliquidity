## Why

The pricing grid is the foundational module for the entire market-making system. All other domains (inventory, quoting engine, order differ) depend on it to determine valid order price levels. Without a working pricing grid, no orders can be placed. It must be implemented first as it has zero dependencies and is a prerequisite for all downstream work.

## What Changes

- Implement `PricingGrid` class in `src/pyperliquidity/pricing_grid.py` that generates a geometric price ladder from `start_px`, `n_orders`, and configurable `tick_size` (default 0.3%)
- Provide `levels` property returning the full ascending price array
- Provide `level_for_price(px)` to find the nearest grid index for a given price
- Provide `price_at_level(i)` to retrieve the price at a specific grid index
- Add configurable rounding (exchange sig-fig rounding) to support varying spot pair tick sizes
- Validate against degenerate grids (adjacent levels collapsing to the same price after rounding)
- Full test suite covering core generation, edge cases, and invariants

## Capabilities

### New Capabilities

### Modified Capabilities
- `pricing_grid`: Implementing the full module per the existing spec — geometric price ladder generation, level lookup, price retrieval, rounding, and invariant enforcement.

## Impact

- **Code**: `src/pyperliquidity/pricing_grid.py` (new implementation), new test file `tests/test_pricing_grid.py`
- **Dependencies**: None — pure math module with zero I/O
- **Downstream**: Unblocks `inventory`, `quoting_engine`, and `order_differ` modules which all reference grid levels
