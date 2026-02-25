# Order State

## Purpose

Single source of truth for all resting orders. Tracks order lifecycle, handles OID swaps from modify operations, detects ghost orders, and provides the "current orders" snapshot that the order differ compares against.

## State

Each tracked order:
```
TrackedOrder:
    oid: int                # Exchange-assigned order ID (may change on modify)
    side: "buy" | "sell"
    level_index: int        # Stable identity — position on the price grid
    price: float
    size: float
    status: "resting" | "pending_modify" | "pending_cancel" | "pending_place"
```

- `orders_by_oid: dict[int, TrackedOrder]`
- `orders_by_key: dict[tuple[str, int], TrackedOrder]` — keyed by `(side, level_index)`

## Operations

### Place Confirmation
On `orderUpdates` with status `"resting"` for a newly placed order:
- Create TrackedOrder, index by OID and by (side, level_index)
- Set status to `"resting"`

### Modify Response Handling
On `bulk_modify` response:
- If `"resting"` in status: check if OID changed. If so, re-key the order under the new OID.
- If `"error"` containing `"Cannot modify"`: order was already filled. Remove from state immediately — do NOT retry.

### Fill Handling
On `userFills`:
- Deduplicate by `tid` (trade ID). Maintain a bounded `seen_tids` set.
- Remove filled order from state (or reduce size for partial fills).
- Notify inventory module of the fill.

### Reconciliation (every ~60s)
Poll `open_orders()` via REST:
- **Orphaned orders** (on exchange but not in state): cancel them — these are leaked orders
- **Ghost orders** (in state but not on exchange): remove from state — stale entries

## Invariants

1. Every resting order on the exchange has exactly one TrackedOrder in state
2. (side, level_index) is unique — at most one order per grid level per side
3. OID changes are tracked atomically on modify responses
4. `seen_tids` set is pruned periodically to prevent unbounded growth (keep most recent ~5000)

## Edge Cases

- Modify response arrives before orderUpdate websocket event — handle both paths idempotently
- Rapid fills during a modify — the modify returns "Cannot modify", fill arrives shortly after
- WS reconnection replays fills — tid deduplication prevents double-counting

## Dependencies

- `inventory`: Notified on fills to update balances
- `pricing_grid`: Level index mapping for order identity
