## Why

The batch emitter is the only module that performs exchange I/O for order management. Without it, the pure computation pipeline (quoting_engine → order_differ → OrderDiff) has no way to actually execute mutations against the Hyperliquid API. It bridges the pure diff output to the SDK's batch operations while respecting rate-limit budget constraints and prioritizing operations for safety.

## What Changes

- Implement `BatchEmitter` class that accepts an `OrderDiff` and `RateLimitBudget`, gates on budget, prioritizes operations (cancels > modifies > places), and executes via SDK batch ops
- Budget gating: cancel-only mode when budget < mutations + SAFETY_MARGIN (100); trim by priority when over MAX_REQUESTS_PER_TICK (20)
- Response processing for each batch operation type:
  - `bulk_modify`: OID swap detection, ghost order removal on "Cannot modify" errors
  - `bulk_orders`: OID extraction from "resting" responses, cooldown on "Insufficient spot balance" (60s) and consecutive generic rejects (10s)
  - `bulk_cancel`: notify order_state to remove
- Cooldown state: per-(coin, side) expiry timestamps to suppress futile placements
- All orders use ALO time-in-force (`{"limit": {"tif": "Alo"}}`)
- SDK calls wrapped with `asyncio.to_thread()` for async compatibility
- Rate limit notification after each API call via `rate_limit.on_request()`

## Capabilities

### New Capabilities

(none — this implements the existing batch_emitter spec)

### Modified Capabilities

- `batch_emitter`: Implementing the full spec as defined. No requirement changes — this is initial implementation.

## Impact

- New file: `src/pyperliquidity/batch_emitter.py`
- New test file: `tests/test_batch_emitter.py`
- Depends on: `order_state` (notify outcomes), `rate_limit` (query budget, report requests), Hyperliquid SDK (`exchange` object)
- Downstream: `ws_state` or state manager will call `emit()` on each tick
