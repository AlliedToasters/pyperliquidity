## MODIFIED Requirements

### Requirement: Startup sequence seeds all modules from REST data

The WsState orchestrator SHALL execute a startup sequence that:
1. Calls `spot_meta()` to resolve the configured coin to its `asset_id` (spot_index + 10000)
2. Constructs a `PricingGrid` from `start_px` and `n_orders` config parameters — this grid is immutable and persists for the strategy's lifetime
3. Calls `open_orders(address)` to seed `OrderState` with existing resting orders, using `grid.level_for_price(px)` to assign absolute level indices
4. Calls `spot_user_state(address)` to seed `Inventory` with account balances
5. Calls `user_rate_limit(address)` to seed `RateLimitBudget`

All REST calls MUST complete before WS subscriptions or the tick loop begin.

#### Scenario: Clean startup with no existing orders
- **WHEN** the market maker starts with no resting orders on the exchange
- **THEN** OrderState is initialized empty, Inventory is seeded from REST balances, PricingGrid is constructed from start_px/n_orders, and the tick loop begins

#### Scenario: Startup with existing resting orders
- **WHEN** the market maker starts with resting orders on the exchange
- **THEN** each resting order is registered in OrderState via `on_place_confirmed` with `level_index` resolved by `grid.level_for_price(px)`, and the first tick uses them as current state for diffing

#### Scenario: Resting order outside grid range
- **WHEN** a resting order's price does not match any grid level (`grid.level_for_price` returns `None`)
- **THEN** the order is still registered in OrderState (it will be cancelled by the differ on the first tick as unmatched)

### Requirement: Tick loop runs the full quoting pipeline at configured interval

The orchestrator SHALL run a tick loop every `interval_s` seconds (default 3). Each tick:
1. Gets effective balances from Inventory
2. Calls `compute_desired_orders(grid, effective_token, effective_usdc, order_sz, min_notional)`
3. Gets current orders from `OrderState.get_current_orders`
4. Calls `compute_diff(desired, current, dead_zone_bps, price_tolerance_bps, size_tolerance_pct)`
5. Calls `BatchEmitter.emit(diff, rate_limit_budget)`
6. Logs cursor level and rate limit status

The cursor level is not passed to the quoting engine — it is computed internally. For logging, the cursor MAY be derived externally: `cursor = grid.n_orders - min(floor(eff_token / order_sz) + (1 if eff_token % order_sz > 0 else 0), grid.n_orders)`.

#### Scenario: Normal tick with inventory change
- **WHEN** a tick runs after a fill has changed inventory
- **THEN** the quoting engine produces updated desired orders reflecting the new cursor position, the differ computes the delta, and the emitter sends the appropriate API calls

#### Scenario: Tick with no changes needed
- **WHEN** a tick runs and the differ produces an empty diff (no modifies, places, or cancels)
- **THEN** the emitter is called with the empty diff and no API calls are made

## REMOVED Requirements

### Requirement: Floating mid price tracking
**Reason**: The `_last_mid` field (derived as `usdc / tokens`) was used to center the grid each tick and as a reference for per-side level index computation. With a fixed grid, there is no floating mid. The cursor level on the grid serves as the reference point.
**Migration**: Remove `_last_mid`. For logging, use `grid.price_at_level(cursor)`. For level index assignment at startup, use `grid.level_for_price(px)` instead of the log-ratio heuristic `_price_to_level_index`.
