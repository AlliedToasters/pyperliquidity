## Why

The quoting engine is the core HIP-2 algorithm — the pure function that turns inventory state and a price grid into a set of desired orders. Without it, the pipeline from StateManager → OrderDiffer → BatchEmitter has no input. This is the last missing pure-math module before the system can produce quotes.

## What Changes

- Implement `compute_desired_orders()` as a pure, deterministic function: given a `PriceGrid`, effective balances, `order_sz`, boundary level, and minimum notional — return a list of `DesiredOrder` dataclasses
- Define the `DesiredOrder` dataclass with `side`, `level_index`, `price`, and `size` fields
- Ask-side: place full asks ascending from boundary, plus one partial if remainder > 0
- Bid-side: place full bids descending from boundary-1 until USDC exhausted, plus one partial
- Filter out orders below minimum notional threshold
- Comprehensive pytest test suite covering all edge cases

## Capabilities

### New Capabilities

_(none — the quoting_engine spec already exists)_

### Modified Capabilities

- `quoting_engine`: Adding `boundary_level` and `min_notional` as explicit parameters to the interface; spec currently omits these details

## Impact

- New file: `src/pyperliquidity/quoting_engine.py`
- New file: `tests/test_quoting_engine.py`
- Depends on: `pricing_grid.PricingGrid`, `inventory.Inventory` (for type context only — no runtime import of Inventory needed, just its output values)
- Downstream consumer: `order_differ` will match on `(side, level_index)` from `DesiredOrder`
