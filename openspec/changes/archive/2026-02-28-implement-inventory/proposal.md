## Why

The inventory module is the second layer of the computation pipeline, sitting between `pricing_grid` (already implemented) and `quoting_engine` (downstream consumer). Without it, the quoting engine has no way to determine how many orders to place, what sizes they should be, or where the bid/ask boundary sits on the grid. The existing spec defines raw balance tracking but needs an allocation model so the strategy operates on capped effective balances rather than raw account balances.

## What Changes

- Implement `Inventory` dataclass with allocation-aware balance tracking
- `effective = min(allocated, account)` as the core invariant — downstream consumers never see raw account balances
- Ask-side tranche decomposition: `n_full_asks`, `partial_ask_sz` from effective token balance
- Bid-side tranche decomposition: walk grid levels descending from boundary, accumulating USDC cost per level
- Fill event handlers (`on_ask_fill`, `on_bid_fill`) that update both account and effective balances with effective clamped to allocation ceiling
- Balance reconciliation (`on_balance_update`) that resets account balances and recomputes effective
- Import `PriceGrid` from `pricing_grid` for bid cost computation
- Comprehensive pytest test suite

## Capabilities

### New Capabilities

(none — inventory is an existing spec)

### Modified Capabilities

- `inventory`: Add allocation model section — effective = min(allocated, account) invariant, allocation capping on fills and reconciliation, tranche decomposition operates on effective balances only

## Impact

- New file: `src/pyperliquidity/inventory.py`
- New file: `tests/test_inventory.py`
- Modified spec: `openspec/specs/inventory/spec.md` (delta spec adds allocation model)
- Downstream: `quoting_engine` will consume `Inventory` to get tranche decomposition and boundary info
- Dependency: imports `PriceGrid` from `pricing_grid`
