## 1. WsState class scaffold and startup sequence

- [x] 1.1 Create `WsState` class with constructor accepting config params (`coin`, `start_px`, `n_orders`, `order_sz`, `n_seeded_levels`, `interval_s`, `dead_zone_bps`, `price_tolerance_bps`, `size_tolerance_pct`, `reconcile_every`) and SDK objects (`info`, `exchange`, `address`)
- [x] 1.2 Implement `async _startup()` method: resolve coin to asset_id via `spot_meta()`, seed OrderState from `open_orders()`, seed Inventory from `spot_user_state()`, seed RateLimitBudget from `user_rate_limit()`, construct PricingGrid
- [x] 1.3 Compute initial `boundary_level` from seeded orders

## 2. WebSocket subscription and callback routing

- [x] 2.1 Implement `_subscribe()` method that subscribes to `orderUpdates`, `userFills`, and `webData2` feeds via SDK
- [x] 2.2 Implement sync callback functions that bridge to async via `asyncio.run_coroutine_threadsafe`
- [x] 2.3 Implement async handlers: `_handle_order_update`, `_handle_fill`, `_handle_balance_update` that route to appropriate module methods

## 3. Tick loop

- [x] 3.1 Implement `async _tick()` method: compute boundary_level, get effective balances, compute desired orders, get current orders, compute diff, emit, log rate limit status
- [x] 3.2 Implement `async _tick_loop()` that runs `_tick()` every `interval_s` with `asyncio.sleep`
- [x] 3.3 Implement `async run()` as the main entry point: calls `_startup()`, `_subscribe()`, then runs `_tick_loop()`

## 4. Reconciliation

- [x] 4.1 Implement `async _reconcile()`: REST `open_orders()` → `OrderState.reconcile()` → cancel orphans via BatchEmitter → remove ghosts, REST `spot_user_state()` → `Inventory.on_balance_update()`
- [x] 4.2 Integrate reconciliation into tick loop using tick counter (every `reconcile_every` ticks)

## 5. WS reconnection

- [x] 5.1 Implement reconnection handling: resubscribe to all feeds and trigger immediate full reconciliation

## 6. Tests

- [x] 6.1 Test startup sequence: mock SDK REST calls, verify all modules seeded correctly
- [x] 6.2 Test tick loop: mock modules, verify full pipeline (desired orders → diff → emit) for a simple inventory scenario
- [x] 6.3 Test reconciliation: mock an orphaned order on exchange not in state, verify it gets cancelled
- [x] 6.4 Test WS callback routing: simulate fill/order update messages, verify correct module methods called
