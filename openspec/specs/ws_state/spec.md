# WebSocket State

## Purpose

Manage WebSocket subscriptions to Hyperliquid feeds, maintain the real-time state snapshot, and perform periodic REST reconciliation. This is the I/O boundary — all exchange data enters the system through this module.

## Subscriptions

| Feed | Channel | Updates |
|------|---------|---------|
| Mid prices | `{"type": "allMids"}` | All markets, every block |
| Order book | `{"type": "l2Book", "coin": "<coin>"}` | Per-market L2 snapshots |
| Order lifecycle | `{"type": "orderUpdates", "user": "<addr>"}` | Place/modify/fill/cancel confirmations |
| Fill confirmations | `{"type": "userFills", "user": "<addr>"}` | Fill details with tid |
| Account state | `{"type": "webData2", "user": "<addr>"}` | Equity, positions, margin |

## Startup Sequence

1. REST: `meta()`, `spot_meta()` → cache asset metadata, compute asset IDs
2. REST: `open_orders(addr)` → seed order_state with current resting orders
3. REST: `user_state(addr)`, `spot_user_state(addr)` → seed inventory balances
4. REST: `user_rate_limit(addr)` → seed rate_limit budget
5. Subscribe to all WS feeds
6. Begin tick loop

## Callback Routing

WS callbacks arrive on the SDK's synchronous daemon thread. Bridge to async:
```python
def on_ws_message(msg):
    asyncio.run_coroutine_threadsafe(handle(msg), main_loop)
```

Route by message type:
- `orderUpdates` → `order_state.on_order_update()`
- `userFills` → `order_state.on_fill()` → `inventory.on_fill()`
- `webData2` → `inventory.on_balance_update()`
- `allMids` → update cached mid price (informational — not used for quoting)
- `l2Book` → update cached book snapshot (informational)

## Reconciliation (every ~60s)

1. REST: `open_orders(addr)` → compare with order_state
   - Orphaned orders (on exchange, not in state): bulk_cancel
   - Ghost orders (in state, not on exchange): remove from state
2. REST: `spot_user_state(addr)` → compare with inventory
   - Drift > threshold: reset inventory from REST data

## Reconnection

On WS disconnect:
- Resubscribe to all feeds
- Immediately run full reconciliation (fills may have been missed)
- Fill deduplication (via tid) handles any replayed events

## Invariants

1. All exchange data enters through this module — no other module makes API calls except batch_emitter
2. WS feeds are the primary state source; REST is only for startup and reconciliation
3. Reconciliation runs even when WS appears healthy (belt and suspenders)
4. Callbacks are bridged to async — no blocking the tick loop

## Dependencies

- `order_state`: Receives order updates and fills
- `inventory`: Receives balance updates and fill notifications
- `rate_limit`: Seeded at startup
- `batch_emitter`: Reconciliation may trigger cancels for orphaned orders
- Hyperliquid SDK: `info` (REST + WS) and `exchange` (mutations)
