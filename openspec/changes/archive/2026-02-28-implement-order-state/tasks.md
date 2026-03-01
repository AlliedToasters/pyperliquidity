## 1. Data Model

- [x] 1.1 Implement OrderStatus enum (RESTING, PENDING_PLACE, PENDING_MODIFY, PENDING_CANCEL)
- [x] 1.2 Implement TrackedOrder mutable dataclass (oid, side, level_index, price, size, status)
- [x] 1.3 Implement FillResult frozen dataclass (side, price, size, fully_filled)
- [x] 1.4 Implement ReconcileResult frozen dataclass (orphaned_oids: set[int], ghost_oids: set[int])

## 2. OrderState Core

- [x] 2.1 Implement OrderState class with dual-index dicts (orders_by_oid, orders_by_key) and seen_tids set
- [x] 2.2 Implement on_place_confirmed — create TrackedOrder, insert into both indices, handle replacement of existing order at same (side, level_index)
- [x] 2.3 Implement on_modify_response — handle OID swap (re-key atomically), handle "Cannot modify" error (remove from both indices), idempotent for unknown OIDs
- [x] 2.4 Implement on_fill — tid dedup, full fill removal, partial fill size reduction, return FillResult or None
- [x] 2.5 Implement _prune_seen_tids — sort and keep newest half when cap reached

## 3. Reconciliation and Queries

- [x] 3.1 Implement reconcile — compare exchange OIDs vs tracked OIDs, return ReconcileResult with orphaned and ghost sets
- [x] 3.2 Implement remove_ghost — remove order by OID from both indices, idempotent
- [x] 3.3 Implement get_current_orders — return list of all TrackedOrder objects

## 4. Tests

- [x] 4.1 Test place confirmation and dual-index consistency
- [x] 4.2 Test OID swap handling (modify response with new OID, verify re-keying)
- [x] 4.3 Test ghost detection via "Cannot modify" error
- [x] 4.4 Test fill deduplication (same tid twice, assert single effect)
- [x] 4.5 Test partial fill reduces size, order remains in both indices
- [x] 4.6 Test full fill removes order from both indices
- [x] 4.7 Test reconcile detects orphaned and ghost orders
- [x] 4.8 Test seen_tids pruning at capacity
- [x] 4.9 Test replace existing order at same (side, level_index) on place
- [x] 4.10 Test fill for unknown OID returns None
