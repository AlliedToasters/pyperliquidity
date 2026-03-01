## 1. Data Structures

- [x] 1.1 Define `DesiredOrder` dataclass with fields: side, level_index, price, size (in quoting_engine module or shared types)
- [x] 1.2 Define `TrackedOrder` dataclass with fields: oid, side, level_index, price, size, status (in order_state module or shared types)
- [x] 1.3 Define `OrderDiff` dataclass with fields: modifies (list[tuple[int, DesiredOrder]]), places (list[DesiredOrder]), cancels (list[int])

## 2. Core Algorithm

- [x] 2.1 Implement `_weighted_mid_price(orders)` helper that computes size-weighted average price for a list of orders
- [x] 2.2 Implement dead zone check: compare weighted mid prices of desired vs current, short-circuit with empty OrderDiff if drift < dead_zone_bps; bypass when either list is empty
- [x] 2.3 Implement level-index matching: build dicts keyed by (side, level_index) for both desired and current, classify into matched/unmatched-desired/unmatched-current
- [x] 2.4 Implement per-order tolerance filter: for matched pairs, skip modify if price diff < price_tolerance_bps AND size diff < size_tolerance_pct
- [x] 2.5 Implement cross-side validation: detect matched-by-level_index but different-side pairs, emit cancel + place instead of modify
- [x] 2.6 Implement `compute_diff()` main function composing steps 2.2-2.5, returning OrderDiff

## 3. Tests

- [x] 3.1 Test identical desired and current orders → empty diff
- [x] 3.2 Test dead zone suppression: drift below threshold → empty diff; drift above → non-empty
- [x] 3.3 Test dead zone bypass: empty current → all places; empty desired → all cancels
- [x] 3.4 Test level-index matching: unmatched desired → places, unmatched current → cancels
- [x] 3.5 Test per-order tolerance: within tolerance → skip; exceeds price tolerance → modify; exceeds size tolerance → modify
- [x] 3.6 Test cross-side validation: same level_index different side → cancel + place (not modify)
- [x] 3.7 Test determinism: same inputs produce identical output across multiple calls
- [x] 3.8 Test edge case: single order on each side, partial fills changing sizes
