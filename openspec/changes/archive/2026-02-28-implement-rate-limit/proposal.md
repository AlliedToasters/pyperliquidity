## Why

The batch emitter needs to know the current rate-limit budget before deciding whether to send API calls. Without budget tracking, the market maker risks hitting Hyperliquid's throttle (1 req/10s at budget=0), causing stale quotes and missed fills. We need a module that tracks the budget model locally and provides health queries.

## What Changes

- Implement `RateLimitBudget` dataclass tracking cumulative volume, cumulative requests, and derived budget/ratio
- Expose `on_request()`, `on_fill()`, `sync_from_exchange()` mutation methods
- Expose `remaining()`, `is_healthy()`, `is_emergency()` query methods
- Add periodic logging of utilization metrics (~60s interval)
- Define alert thresholds: ratio < 1.0 (warning), budget < 500 (emergency), budget < 100 (cancel-only)

## Capabilities

### New Capabilities

_None — the `rate_limit` spec already exists._

### Modified Capabilities

- `rate_limit`: Implementing the full spec. No requirement changes — this is the initial implementation of the existing spec.

## Impact

- **New code**: `src/pyperliquidity/rate_limit.py` (currently empty stub)
- **New tests**: `tests/test_rate_limit.py`
- **Consumers**: `batch_emitter` will call `on_request()` and query `remaining()` / `is_emergency()`. `order_state` or `ws_state` will call `on_fill()`. `ws_state` will call `sync_from_exchange()` at startup.
- **No external dependencies** beyond the standard library and project internals.
