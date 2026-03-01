## ADDED Requirements

### Requirement: TrackedOrder data model
The system SHALL represent each tracked order as a `TrackedOrder` dataclass with fields: `oid` (int), `side` (Literal["buy", "sell"]), `level_index` (int), `price` (float), `size` (float), `status` (OrderStatus enum). The `OrderStatus` enum SHALL have values: `RESTING`, `PENDING_PLACE`, `PENDING_MODIFY`, `PENDING_CANCEL`.

#### Scenario: TrackedOrder creation
- **WHEN** a TrackedOrder is created with oid=100, side="buy", level_index=5, price=1.50, size=10.0, status=RESTING
- **THEN** all fields are accessible and the dataclass is mutable (oid, size, and status can be updated)

### Requirement: Dual-index order tracking
The system SHALL maintain two synchronized indices: `orders_by_oid` (keyed by OID) and `orders_by_key` (keyed by (side, level_index) tuple). Both dicts SHALL reference the same TrackedOrder instances. At most one order SHALL exist per (side, level_index) key.

#### Scenario: Dual-index consistency on insert
- **WHEN** a new order is tracked with oid=100, side="sell", level_index=3
- **THEN** `orders_by_oid[100]` and `orders_by_key[("sell", 3)]` reference the same TrackedOrder object

#### Scenario: Unique level constraint
- **WHEN** an order already exists at ("buy", 5) and a new order is placed at ("buy", 5)
- **THEN** the old order is replaced and removed from orders_by_oid

### Requirement: Place confirmation handling
The system SHALL provide an `on_place_confirmed` method that creates a TrackedOrder with status RESTING and inserts it into both indices. If an order already exists at the same (side, level_index), it SHALL be replaced.

#### Scenario: New order placed
- **WHEN** `on_place_confirmed(oid=200, side="sell", level_index=7, price=2.10, size=5.0)` is called
- **THEN** a TrackedOrder with status RESTING exists in both orders_by_oid[200] and orders_by_key[("sell", 7)]

#### Scenario: Replace existing order at same level
- **WHEN** an order with oid=100 exists at ("sell", 7) and `on_place_confirmed(oid=200, side="sell", level_index=7, price=2.13, size=5.0)` is called
- **THEN** oid=100 is removed from orders_by_oid, and oid=200 is in both indices at ("sell", 7)

### Requirement: Modify response handling with OID swap
The system SHALL provide an `on_modify_response` method that handles OID swaps: when a modify response indicates a new OID, the order SHALL be re-keyed in orders_by_oid while orders_by_key remains unchanged (same TrackedOrder object, just the oid field updated). The operation SHALL be atomic — at no point shall both old and new OIDs exist simultaneously.

#### Scenario: OID swap on successful modify
- **WHEN** an order exists with oid=100 at ("buy", 5) and `on_modify_response(original_oid=100, new_oid=150, status="resting")` is called
- **THEN** orders_by_oid[100] no longer exists, orders_by_oid[150] references the same TrackedOrder, and that order's oid field equals 150

#### Scenario: OID unchanged on modify
- **WHEN** an order exists with oid=100 and `on_modify_response(original_oid=100, new_oid=100, status="resting")` is called
- **THEN** the order remains unchanged in both indices

### Requirement: Ghost detection on modify error
The system SHALL remove an order from both indices when a modify response contains a "Cannot modify" error, as this indicates the order was already filled on the exchange.

#### Scenario: Cannot modify error removes order
- **WHEN** an order exists with oid=100 at ("sell", 3) and `on_modify_response(original_oid=100, new_oid=None, status="error: Cannot modify")` is called
- **THEN** orders_by_oid[100] no longer exists and orders_by_key[("sell", 3)] no longer exists

#### Scenario: Modify error for unknown OID
- **WHEN** `on_modify_response(original_oid=999, new_oid=None, status="error: Cannot modify")` is called for an OID not in state
- **THEN** no error is raised (idempotent)

### Requirement: Fill handling with deduplication
The system SHALL provide an `on_fill` method that deduplicates fills by trade ID (`tid`). It SHALL maintain a bounded `seen_tids` set capped at 5000 entries. When the cap is reached, the oldest half SHALL be pruned. For non-duplicate fills: fully filled orders SHALL be removed from both indices; partial fills SHALL reduce the order's size. The method SHALL return a `FillResult` or `None` (if duplicate or unknown OID).

#### Scenario: Full fill removes order
- **WHEN** an order with oid=100, size=10.0 exists and `on_fill(tid=1001, oid=100, fill_sz=10.0)` is called
- **THEN** the order is removed from both indices and a FillResult is returned with the order's side, price, fill size, and fully_filled=True

#### Scenario: Partial fill reduces size
- **WHEN** an order with oid=100, size=10.0 exists and `on_fill(tid=1002, oid=100, fill_sz=3.0)` is called
- **THEN** the order remains in both indices with size=7.0 and a FillResult is returned with fully_filled=False

#### Scenario: Duplicate tid is ignored
- **WHEN** `on_fill(tid=1001, oid=100, fill_sz=10.0)` is called twice
- **THEN** the second call returns None and has no effect on state

#### Scenario: Fill for unknown OID
- **WHEN** `on_fill(tid=1003, oid=999, fill_sz=5.0)` is called for an OID not in state
- **THEN** the method returns None (no error)

#### Scenario: Seen tids pruning
- **WHEN** 5000 unique tids have been recorded and another fill arrives
- **THEN** the oldest 2500 tids are pruned, the new tid is added, and the fill is processed normally

### Requirement: Reconciliation against exchange state
The system SHALL provide a `reconcile` method that compares tracked orders against a list of exchange orders (each with oid and optionally side/level info). It SHALL return a `ReconcileResult` containing `orphaned_oids` (on exchange but not in state — need canceling) and `ghost_oids` (in state but not on exchange — need removal from state).

#### Scenario: Detect orphaned orders
- **WHEN** exchange reports orders [oid=100, oid=200, oid=300] and state tracks [oid=100, oid=200]
- **THEN** reconcile returns orphaned_oids={300}

#### Scenario: Detect ghost orders
- **WHEN** exchange reports orders [oid=100] and state tracks [oid=100, oid=200]
- **THEN** reconcile returns ghost_oids={200}

#### Scenario: Clean state
- **WHEN** exchange and state have identical OID sets
- **THEN** reconcile returns empty orphaned_oids and ghost_oids

### Requirement: Current orders snapshot
The system SHALL provide a `get_current_orders` method that returns a list of all currently tracked TrackedOrder objects, suitable for the order differ to compare against desired orders.

#### Scenario: Snapshot returns all orders
- **WHEN** state contains 3 tracked orders
- **THEN** `get_current_orders()` returns a list of 3 TrackedOrder objects

### Requirement: Remove ghost orders
The system SHALL provide a `remove_ghost` method that removes an order by OID from both indices. It SHALL be idempotent — removing a non-existent OID is a no-op.

#### Scenario: Remove existing ghost
- **WHEN** an order with oid=100 exists at ("buy", 5) and `remove_ghost(100)` is called
- **THEN** both orders_by_oid[100] and orders_by_key[("buy", 5)] are removed

#### Scenario: Remove non-existent ghost
- **WHEN** `remove_ghost(999)` is called for an OID not in state
- **THEN** no error is raised
