## Why

The order state module is the single source of truth for all resting orders, bridging the pure computation layer (quoting_engine, order_differ) with the I/O layer (batch_emitter, ws_state). Without it, the system has no way to track what orders are actually live on the exchange, handle OID swaps from modify operations, detect ghost orders, or provide the "current orders" snapshot needed by the order differ.

## What Changes

- Implement `TrackedOrder` dataclass with oid, side, level_index, price, size, and status fields
- Implement `OrderStatus` enum: resting, pending_modify, pending_cancel, pending_place
- Implement `OrderState` class with dual-indexed state (orders_by_oid + orders_by_key)
- Place confirmation handling with dual-index insertion
- Modify response handling with atomic OID swap support and ghost detection ("Cannot modify" errors)
- Fill handling with tid-based deduplication (bounded set, ~5000 cap, prune oldest half)
- Reconciliation against exchange state returning orphaned and ghost OIDs
- `get_current_orders()` snapshot method for the order differ
- Comprehensive test suite covering OID swaps, ghost detection, fill dedup, partial fills, and dual-index consistency

## Capabilities

### New Capabilities

(none — this implements the existing order_state spec)

### Modified Capabilities

- `order_state`: Implementing the full spec as defined. No requirement changes — this is initial implementation.

## Impact

- New file: `src/pyperliquidity/order_state.py`
- New test file: `tests/test_order_state.py`
- Downstream consumers (batch_emitter, ws_state, order_differ) will depend on this module's API
- inventory module will receive fill notifications through the returned fill info
