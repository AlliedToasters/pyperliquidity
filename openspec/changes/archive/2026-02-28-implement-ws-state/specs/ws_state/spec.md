## ADDED Requirements

### Requirement: Startup sequence seeds all modules from REST data

The WsState orchestrator SHALL execute a startup sequence that:
1. Calls `spot_meta()` to resolve the configured coin to its `asset_id` (spot_index + 10000)
2. Calls `open_orders(address)` to seed `OrderState` with existing resting orders
3. Calls `spot_user_state(address)` to seed `Inventory` with account balances
4. Calls `user_rate_limit(address)` to seed `RateLimitBudget`
5. Constructs a `PricingGrid` from config parameters

All REST calls MUST complete before WS subscriptions or the tick loop begin.

#### Scenario: Clean startup with no existing orders
- **WHEN** the market maker starts with no resting orders on the exchange
- **THEN** OrderState is initialized empty, Inventory is seeded from REST balances, PricingGrid is constructed, and the tick loop begins

#### Scenario: Startup with existing resting orders
- **WHEN** the market maker starts with resting orders on the exchange
- **THEN** each resting order is registered in OrderState via `on_place_confirmed`, and the first tick uses them as current state for diffing

### Requirement: WebSocket subscriptions route callbacks to correct modules

The orchestrator SHALL subscribe to `orderUpdates`, `userFills`, and `webData2` feeds. Each WS callback MUST be bridged from the SDK's sync daemon thread to the async event loop via `asyncio.run_coroutine_threadsafe`.

Routing:
- `orderUpdates` → `OrderState.on_modify_response` or `on_place_confirmed` based on update type
- `userFills` → `OrderState.on_fill` → if result, `Inventory.on_ask_fill` or `on_bid_fill`
- `webData2` → `Inventory.on_balance_update`

#### Scenario: Order fill arrives via WebSocket
- **WHEN** a `userFills` message arrives with a fill for a tracked order
- **THEN** `OrderState.on_fill` is called with the fill's `tid`, `oid`, and `sz`, and the resulting `FillResult` is forwarded to the appropriate `Inventory.on_ask_fill` or `on_bid_fill`

#### Scenario: Duplicate fill is ignored
- **WHEN** a `userFills` message arrives with a `tid` that was already processed
- **THEN** `OrderState.on_fill` returns `None` and no inventory update occurs

#### Scenario: Balance update via webData2
- **WHEN** a `webData2` message arrives with updated balances
- **THEN** `Inventory.on_balance_update` is called with the new token and USDC balances

### Requirement: Tick loop runs the full quoting pipeline at configured interval

The orchestrator SHALL run a tick loop every `interval_s` seconds (default 3). Each tick:
1. Computes the boundary level from current OrderState
2. Gets effective balances from Inventory
3. Calls `compute_desired_orders` with grid, boundary, balances, and order_sz
4. Gets current orders from `OrderState.get_current_orders`
5. Calls `compute_diff(desired, current, dead_zone_bps, price_tolerance_bps, size_tolerance_pct)`
6. Calls `BatchEmitter.emit(diff, rate_limit_budget)`
7. Logs rate limit status

#### Scenario: Normal tick with inventory change
- **WHEN** a tick runs after a fill has changed inventory
- **THEN** the quoting engine produces updated desired orders, the differ computes the delta, and the emitter sends the appropriate API calls

#### Scenario: Tick with no changes needed
- **WHEN** a tick runs and the differ produces an empty diff (no modifies, places, or cancels)
- **THEN** the emitter is called with the empty diff and no API calls are made

### Requirement: Periodic reconciliation detects orphaned and ghost orders

Every `reconcile_every` ticks (default 20, ~60s), the orchestrator SHALL:
1. Call `open_orders(address)` via REST
2. Call `OrderState.reconcile(exchange_oids)` to detect orphaned and ghost orders
3. Cancel orphaned orders (on exchange but not in state) via BatchEmitter
4. Remove ghost orders (in state but not on exchange) from OrderState
5. Call `spot_user_state(address)` and update Inventory balances

#### Scenario: Orphaned order detected during reconciliation
- **WHEN** reconciliation finds an order on the exchange that is not tracked in OrderState
- **THEN** the order is cancelled via a cancel API call

#### Scenario: Ghost order detected during reconciliation
- **WHEN** reconciliation finds an order in OrderState that is not on the exchange
- **THEN** the order is removed from OrderState via `remove_ghost`

#### Scenario: Balance drift corrected during reconciliation
- **WHEN** REST balance data differs from Inventory state
- **THEN** `Inventory.on_balance_update` is called with the REST values

### Requirement: WS reconnection triggers immediate reconciliation

On WebSocket disconnection or reconnection, the orchestrator SHALL:
1. Resubscribe to all WS feeds
2. Immediately run a full reconciliation (fills may have been missed during disconnect)

Fill deduplication via `tid` in OrderState handles any replayed events.

#### Scenario: Reconnection after brief disconnect
- **WHEN** the WebSocket reconnects after a disconnect
- **THEN** all feeds are resubscribed and a full reconciliation runs immediately

### Requirement: Thread-safe callback bridging

All WS callbacks MUST be bridged to the async event loop via `asyncio.run_coroutine_threadsafe`. No WS callback SHALL directly mutate OrderState, Inventory, or any other module state. This ensures all state mutations are serialized on the event loop thread.

#### Scenario: Concurrent WS callbacks are serialized
- **WHEN** multiple WS callbacks arrive simultaneously from different SDK threads
- **THEN** their corresponding async handlers execute sequentially on the event loop, never concurrently
