## Why

The ws_state module is the last unimplemented domain in pyperliquidity. All pure-computation modules (pricing_grid, inventory, quoting_engine, order_differ) and I/O modules (batch_emitter, rate_limit, order_state) are implemented and tested. Without ws_state, there is no orchestrator to wire them together into a running market maker — no startup sequence, no WebSocket subscriptions, no tick loop, and no periodic reconciliation.

## What Changes

- Implement `ws_state.py` as the orchestrator module that:
  - Runs a startup sequence (REST calls to seed all module state)
  - Subscribes to Hyperliquid WebSocket feeds and routes callbacks to the appropriate modules
  - Runs a periodic tick loop (default 3s) that computes desired orders, diffs them, and emits via batch_emitter
  - Runs periodic REST reconciliation (~60s) to detect orphaned/ghost orders and balance drift
  - Handles WS reconnection with immediate full reconciliation
  - Bridges sync SDK WS callbacks into the async event loop via `asyncio.run_coroutine_threadsafe`
- Add tests with mocked SDK info/exchange objects covering startup, tick loop, and reconciliation

## Capabilities

### New Capabilities

_(none — ws_state spec already exists)_

### Modified Capabilities

- `ws_state`: Implementing the full orchestrator contract defined in the existing spec. No requirement changes — this is pure implementation against the existing spec.

## Impact

- **New code**: `src/pyperliquidity/ws_state.py` (implementation), `tests/test_ws_state.py` (tests)
- **Dependencies**: All existing modules (order_state, inventory, quoting_engine, order_differ, batch_emitter, rate_limit, pricing_grid), Hyperliquid Python SDK (`hyperliquid.info`, `hyperliquid.exchange`)
- **No breaking changes** to existing modules — ws_state is a consumer of their public APIs
