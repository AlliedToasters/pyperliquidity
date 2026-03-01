## ADDED Requirements

### Requirement: BatchEmitter initialization
The system SHALL provide a `BatchEmitter` class that accepts a `coin` (str), `asset_id` (int), an `exchange` object (Hyperliquid SDK), an `OrderState` instance, and a `clock` callable (defaulting to `time.monotonic`). The `asset_id` SHALL be passed at init (not hardcoded). The emitter SHALL maintain internal cooldown state as a `dict[tuple[str, str], float]` mapping `(coin, side)` to expiry timestamps.

#### Scenario: Construction with required parameters
- **WHEN** `BatchEmitter(coin="PURR", asset_id=10004, exchange=exchange, order_state=state)` is constructed
- **THEN** the emitter is ready with empty cooldown state and the provided dependencies stored

#### Scenario: Asset ID is configurable
- **WHEN** a BatchEmitter is created with `asset_id=10042`
- **THEN** all SDK calls use asset_id 10042 (not a hardcoded value)

### Requirement: Budget gating — cancel-only emergency mode
The system SHALL switch to cancel-only mode when `budget.remaining() < total_individual_mutations + SAFETY_MARGIN` where `SAFETY_MARGIN=100`. In cancel-only mode, only cancels from the diff SHALL be emitted; modifies and places SHALL be suppressed entirely.

#### Scenario: Budget below safety margin triggers cancel-only
- **WHEN** budget.remaining() is 150 and the diff contains 5 cancels, 3 modifies, and 4 places (12 total mutations)
- **THEN** only the 5 cancels are emitted; modifies and places are suppressed
- **AND** EmitResult.cancel_only_mode is True

#### Scenario: Budget sufficient for all mutations
- **WHEN** budget.remaining() is 5000 and the diff contains 3 cancels, 5 modifies, and 4 places
- **THEN** all mutations are emitted normally

#### Scenario: Empty diff with low budget
- **WHEN** budget.remaining() is 50 and the diff is empty
- **THEN** no API calls are made and EmitResult shows zero counts

### Requirement: Per-tick mutation cap with priority trimming
The system SHALL enforce a `MAX_MUTATIONS_PER_TICK=20` limit on total individual order mutations. When the diff exceeds this cap, mutations SHALL be trimmed by priority: places are dropped first, then modifies, then cancels. Cancels SHALL never be trimmed.

#### Scenario: Diff exceeds per-tick cap
- **WHEN** the diff contains 5 cancels, 10 modifies, and 10 places (25 total)
- **THEN** 5 cancels are kept, 10 modifies are kept, and places are trimmed to 5
- **AND** total mutations equal 20

#### Scenario: Only cancels exceed cap
- **WHEN** the diff contains 25 cancels, 0 modifies, and 0 places
- **THEN** all 25 cancels are emitted (cancels are never trimmed)

### Requirement: Emission priority ordering
The system SHALL execute batch operations in priority order: bulk_cancel first, then bulk_modify, then bulk_orders. Each non-empty batch is exactly one API request.

#### Scenario: Full diff executes in order
- **WHEN** the diff contains cancels, modifies, and places
- **THEN** bulk_cancel is called first, bulk_modify second, bulk_orders third

#### Scenario: Empty batch types are skipped
- **WHEN** the diff contains only modifies (no cancels or places)
- **THEN** only bulk_modify is called (1 API request total)

### Requirement: ALO time-in-force on all orders
The system SHALL use `{"limit": {"tif": "Alo"}}` for all placed and modified orders. This ensures maker-only fills which replenish the rate-limit budget.

#### Scenario: Placed order uses ALO
- **WHEN** a new order is placed via bulk_orders
- **THEN** the order parameters include `{"limit": {"tif": "Alo"}}`

#### Scenario: Modified order uses ALO
- **WHEN** an existing order is modified via bulk_modify
- **THEN** the modify parameters include `{"limit": {"tif": "Alo"}}`

### Requirement: bulk_modify response handling
The system SHALL process each status in the bulk_modify response. For "resting" statuses, it SHALL check if the OID changed and call `order_state.on_modify_response()` with the original and new OID. For errors containing "Cannot modify", it SHALL call `order_state.on_modify_response()` to trigger ghost removal.

#### Scenario: OID swap on successful modify
- **WHEN** bulk_modify returns status "resting" with oid=200 for an order originally at oid=100
- **THEN** `order_state.on_modify_response(original_oid=100, new_oid=200, status="resting")` is called

#### Scenario: Ghost detection on modify error
- **WHEN** bulk_modify returns "error: Cannot modify order" for oid=100
- **THEN** `order_state.on_modify_response(original_oid=100, new_oid=None, status="error: Cannot modify order")` is called

#### Scenario: Modify with unchanged OID
- **WHEN** bulk_modify returns status "resting" with oid=100 for original oid=100
- **THEN** `order_state.on_modify_response(original_oid=100, new_oid=100, status="resting")` is called

### Requirement: bulk_orders response handling
The system SHALL process each status in the bulk_orders response. For "resting" statuses, it SHALL extract the OID and call `order_state.on_place_confirmed()`. For "Insufficient spot balance" errors, it SHALL set a 60-second cooldown on that side. For 3+ consecutive generic rejection errors, it SHALL set a 10-second cooldown.

#### Scenario: Successful placement
- **WHEN** bulk_orders returns "resting" with oid=300 for a buy order at level_index=5, price=1.50, size=10.0
- **THEN** `order_state.on_place_confirmed(oid=300, side="buy", level_index=5, price=1.50, size=10.0)` is called

#### Scenario: Insufficient balance triggers cooldown
- **WHEN** bulk_orders returns "Insufficient spot balance" for a sell order
- **THEN** a 60-second cooldown is set for (coin, "sell")
- **AND** subsequent sell placements are suppressed until cooldown expires

#### Scenario: Consecutive generic rejects trigger cooldown
- **WHEN** 3 consecutive place responses are generic errors (not ALO rejections, not "Insufficient spot balance")
- **THEN** a 10-second cooldown is set for the affected side

#### Scenario: ALO rejection is not counted as generic error
- **WHEN** bulk_orders returns an ALO rejection (order would cross the spread)
- **THEN** no cooldown is set and the rejection is not counted toward the consecutive reject counter

### Requirement: bulk_cancel response handling
The system SHALL notify order_state to remove each cancelled order. For cancel errors, the order SHALL also be removed (it was likely already filled).

#### Scenario: Successful cancel
- **WHEN** bulk_cancel succeeds for oid=100
- **THEN** `order_state.remove_ghost(oid=100)` is called

#### Scenario: Cancel error removes order anyway
- **WHEN** bulk_cancel returns an error for oid=100
- **THEN** `order_state.remove_ghost(oid=100)` is called (order was likely filled)

### Requirement: Rate limit notification
The system SHALL call `budget.on_request()` after each API call (bulk_cancel, bulk_modify, bulk_orders). Each batch call counts as 1 request regardless of batch size.

#### Scenario: Full diff costs 3 requests
- **WHEN** a diff with cancels, modifies, and places is emitted
- **THEN** `budget.on_request()` is called 3 times (once per batch type)

#### Scenario: Partial diff costs fewer requests
- **WHEN** a diff with only cancels is emitted
- **THEN** `budget.on_request()` is called 1 time

### Requirement: Cooldown state management
The system SHALL maintain per-(coin, side) cooldown state. Before including a DesiredOrder in the places batch, the system SHALL check if a cooldown is active for that side. Cooldowns SHALL be cleared when a placement on that side succeeds.

#### Scenario: Cooled-down side suppresses placements
- **WHEN** a 60-second cooldown is active for (coin, "sell") and the diff contains sell placements
- **THEN** sell placements are excluded from the bulk_orders batch

#### Scenario: Buy side unaffected by sell cooldown
- **WHEN** a cooldown is active for (coin, "sell") and the diff contains buy placements
- **THEN** buy placements are included normally

#### Scenario: Successful placement clears cooldown
- **WHEN** a cooldown was active for (coin, "buy") and a buy order is successfully placed
- **THEN** the cooldown for (coin, "buy") is cleared

### Requirement: Cross-side modify assertion
The system SHALL assert that no modify in the diff changes an order's side. If a cross-side modify is detected, the system SHALL raise an AssertionError.

#### Scenario: Cross-side modify raises error
- **WHEN** a modify targets oid=100 (currently a buy) with a desired sell order
- **THEN** an AssertionError is raised before any API call is made

### Requirement: Async SDK wrapping
The system SHALL wrap all synchronous SDK calls with `asyncio.to_thread()` to avoid blocking the event loop.

#### Scenario: SDK call runs in thread
- **WHEN** `emit()` calls `exchange.bulk_modify()`
- **THEN** the call is dispatched via `asyncio.to_thread()` and the event loop is not blocked

### Requirement: EmitResult return type
The system SHALL return an `EmitResult` dataclass from `emit()` containing: `n_cancelled` (int), `n_modified` (int), `n_placed` (int), `n_errors` (int), and `cancel_only_mode` (bool).

#### Scenario: EmitResult reflects actual execution
- **WHEN** 3 cancels succeed, 2 modifies succeed (1 errors), and 4 places succeed
- **THEN** EmitResult has n_cancelled=3, n_modified=2, n_placed=4, n_errors=1, cancel_only_mode=False
