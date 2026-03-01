## Context

The order state module sits between pure computation (quoting_engine produces desired orders, order_differ computes deltas) and I/O (batch_emitter sends API calls, ws_state delivers exchange events). It must maintain an accurate in-memory representation of all resting orders, handling the complexities of OID swaps, ghost orders, and fill deduplication.

Existing modules (inventory, quoting_engine, pricing_grid) use frozen dataclasses and pure functions with no I/O. Order state follows the same pattern for its data types but is inherently mutable — it's a state container.

## Goals / Non-Goals

**Goals:**
- Provide a single, consistent view of all tracked orders via dual indexing
- Handle OID swaps atomically when modify responses assign new OIDs
- Detect and report ghost orders (in state but not on exchange) and orphaned orders (on exchange but not in state)
- Deduplicate fills by trade ID to prevent double-counting on WS reconnect
- Return fill information so inventory can update balances
- Keep the module pure of I/O — it receives events, it doesn't fetch them

**Non-Goals:**
- Deciding what to do with orphaned/ghost orders (that's batch_emitter/ws_state's job)
- Rate limiting or API call budgeting
- Price or size computation
- WebSocket subscription management

## Decisions

### 1. Dual-index data structure

Use two dicts: `orders_by_oid: dict[int, TrackedOrder]` and `orders_by_key: dict[tuple[str, int], TrackedOrder]` where the key is `(side, level_index)`.

**Rationale**: OID is the exchange's identifier (needed for modify/cancel API calls), but `(side, level_index)` is the grid's stable identity (needed for order differ matching). Both lookups must be O(1).

**Alternative considered**: Single dict with secondary index — rejected because keeping two explicit dicts makes the consistency invariant visible and testable.

### 2. Mutable TrackedOrder dataclass (not frozen)

TrackedOrder needs its oid, size, and status mutated in place. Using a mutable dataclass avoids the overhead of creating new instances on every status change.

**Rationale**: The same TrackedOrder object is referenced from both dicts. Mutation ensures both dicts always see the same state without re-insertion.

### 3. Bounded seen_tids set with half-pruning

Maintain a set of seen trade IDs capped at ~5000. When full, convert to a sorted list and keep the newest half (2500).

**Rationale**: Tids are monotonically increasing integers, so keeping the newest half preserves dedup coverage for recent fills while bounding memory. Replayed fills from WS reconnect are recent.

**Alternative considered**: LRU cache — more complex, no benefit since we only need membership testing.

### 4. Fill return type as a dataclass

`on_fill` returns a `FillResult` dataclass containing side, price, size, and whether the order was fully filled. This gives inventory all the info it needs to call `on_ask_fill` or `on_bid_fill`.

**Rationale**: Returning a structured result is cleaner than having order_state call into inventory directly (which would create a circular dependency concern and violate separation).

### 5. Reconcile returns named tuple of sets

`reconcile` returns `ReconcileResult(orphaned_oids: set[int], ghost_oids: set[int])` — the caller decides what to do with each set.

**Rationale**: Keeps order_state free of I/O decisions. The ws_state or state_manager layer handles canceling orphans and removing ghosts.

## Risks / Trade-offs

- **[Risk] OID swap race condition**: A modify response and an orderUpdate WS event may arrive in either order for the same OID change. → Mitigation: Both paths are idempotent — if the OID is already updated, the second event is a no-op.
- **[Risk] Fill arrives for unknown OID**: After a ghost removal or rapid fill, a fill event may reference an OID no longer in state. → Mitigation: `on_fill` returns `None` for unknown OIDs (no crash, caller logs a warning).
- **[Risk] seen_tids pruning removes a tid that replays**: Theoretically possible if WS reconnect replays very old fills. → Mitigation: Acceptable — the fill would double-count once. The 5000 cap provides ample coverage for normal reconnects.
