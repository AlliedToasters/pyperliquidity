## Why

The order differ is the rate-limit conservation core of the market maker. Without it, the quoting engine's desired orders cannot be reconciled against current resting orders, meaning every tick would require cancelling and replacing all orders — quickly exhausting the Hyperliquid API budget. The differ computes the minimum set of mutations (modify, place, cancel) needed to converge desired state to actual state, using dead-zone suppression, level-index matching, and per-order tolerance filtering.

## What Changes

- Implement `compute_diff()` pure function that compares desired orders against tracked orders
- Implement dead-zone check to short-circuit when overall position drift is negligible
- Implement level-index matching using `(side, level_index)` keys for stable order identity
- Implement per-order tolerance filtering (price and size) to suppress unnecessary modifications
- Implement cross-side validation to split would-be cross-side modifies into cancel + place pairs
- Define `OrderDiff` data structure containing modifies, places, and cancels lists

## Capabilities

### New Capabilities
- `order_differ`: Dead-zone filtered, level-index matched order diffing that produces minimum mutation sets

### Modified Capabilities

(none — this is a new module implementing an existing spec)

## Impact

- **New code**: `src/pyperliquidity/order_differ.py` — pure computation module, no I/O
- **New tests**: `tests/test_order_differ.py`
- **Consumes**: `DesiredOrder` from quoting_engine, `TrackedOrder` from order_state
- **Consumed by**: batch_emitter (receives `OrderDiff` to decide what to actually send)
- **No API/dependency changes**: Pure function, no new external dependencies
