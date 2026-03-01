## ADDED Requirements

### Requirement: compute_diff returns minimum mutation set
The `compute_diff` function SHALL accept a list of `DesiredOrder`, a list of `TrackedOrder`, and tolerance parameters (`dead_zone_bps`, `price_tolerance_bps`, `size_tolerance_pct`), and SHALL return an `OrderDiff` containing the minimum set of modifies, places, and cancels needed to converge current orders to desired orders.

#### Scenario: Identical desired and current orders
- **WHEN** desired orders match current orders exactly (same side, level_index, price, size for all)
- **THEN** the returned `OrderDiff` SHALL have empty modifies, places, and cancels lists

#### Scenario: Desired orders differ from current
- **WHEN** desired orders have different prices or sizes than current orders at the same (side, level_index) keys
- **THEN** the returned `OrderDiff` SHALL contain modify entries pairing each current OID with its new desired values

#### Scenario: New desired orders with no current match
- **WHEN** a desired order exists at a (side, level_index) with no corresponding current order
- **THEN** the returned `OrderDiff` SHALL contain a place entry for that desired order

#### Scenario: Current orders with no desired match
- **WHEN** a current order exists at a (side, level_index) with no corresponding desired order
- **THEN** the returned `OrderDiff` SHALL contain a cancel entry with that order's OID

### Requirement: Dead zone suppression
The differ SHALL compute the size-weighted average price of both desired and current order sets. If the absolute difference in basis points is below `dead_zone_bps`, the function SHALL return an empty `OrderDiff` without performing per-order matching.

#### Scenario: Drift below dead zone
- **WHEN** the size-weighted mid-price drift between desired and current is 5 bps and `dead_zone_bps` is 15
- **THEN** the returned `OrderDiff` SHALL be empty (no modifies, places, or cancels)

#### Scenario: Drift above dead zone
- **WHEN** the size-weighted mid-price drift between desired and current is 20 bps and `dead_zone_bps` is 15
- **THEN** the differ SHALL proceed to per-order level-index matching and return the appropriate mutations

#### Scenario: Empty current orders bypass dead zone
- **WHEN** the current order list is empty and desired orders exist
- **THEN** the differ SHALL skip the dead zone check and return place entries for all desired orders

#### Scenario: Empty desired orders bypass dead zone
- **WHEN** the desired order list is empty and current orders exist
- **THEN** the differ SHALL skip the dead zone check and return cancel entries for all current orders

### Requirement: Level-index matching
The differ SHALL match desired orders to current orders by `(side, level_index)` tuple key. This key provides stable identity across ticks — when fair value shifts, a given level_index retains its logical position.

#### Scenario: Matched pair within tolerance
- **WHEN** a desired order and current order share the same (side, level_index), and price differs by less than `price_tolerance_bps` AND size differs by less than `size_tolerance_pct`
- **THEN** the differ SHALL skip this pair (no modify emitted)

#### Scenario: Matched pair exceeds price tolerance
- **WHEN** a desired order and current order share the same (side, level_index), and price differs by more than `price_tolerance_bps`
- **THEN** the differ SHALL emit a modify for this pair

#### Scenario: Matched pair exceeds size tolerance
- **WHEN** a desired order and current order share the same (side, level_index), and size differs by more than `size_tolerance_pct`
- **THEN** the differ SHALL emit a modify for this pair

### Requirement: Cross-side validation
The differ SHALL NEVER emit a modify that changes an order's side (buy to sell or sell to buy). If a current order and desired order share the same `level_index` but have different sides, the differ SHALL emit a cancel for the current order and a place for the desired order.

#### Scenario: Cross-side detected
- **WHEN** a current buy order exists at level_index 5 and the desired order at level_index 5 is a sell
- **THEN** the differ SHALL emit a cancel for the current buy order's OID AND a place for the desired sell order (not a modify)

#### Scenario: Same-side modify
- **WHEN** a current buy order and desired buy order share the same level_index but differ in price or size beyond tolerance
- **THEN** the differ SHALL emit a modify (not a cancel + place)

### Requirement: Pure function with no I/O
The `compute_diff` function SHALL perform no I/O operations (no network calls, no file access, no logging side effects). It SHALL be fully deterministic: the same inputs SHALL always produce the same output.

#### Scenario: Deterministic output
- **WHEN** `compute_diff` is called twice with identical inputs
- **THEN** the returned `OrderDiff` SHALL be identical in both calls

### Requirement: OrderDiff data structure
The `OrderDiff` dataclass SHALL contain exactly three fields: `modifies` (list of tuples of existing OID and desired order), `places` (list of desired orders to create), and `cancels` (list of OIDs to remove).

#### Scenario: Structure validation
- **WHEN** an `OrderDiff` is constructed
- **THEN** it SHALL have `modifies: list[tuple[int, DesiredOrder]]`, `places: list[DesiredOrder]`, and `cancels: list[int]`
