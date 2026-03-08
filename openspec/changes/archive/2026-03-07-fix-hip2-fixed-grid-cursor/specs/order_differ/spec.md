## MODIFIED Requirements

### Requirement: Level-index matching uses absolute grid positions

The differ SHALL key both desired and current orders by `(side, level_index)` where `level_index` is an absolute position on the fixed `PricingGrid` (0 = `start_px`, `n_orders - 1` = highest price). Both bids and asks share the same index space.

Because the grid is fixed, a given `level_index` always maps to the same price. Identity is stable across ticks — "bid at level 3" is always at `grid.price_at_level(3)`.

As the cursor shifts (inventory changes), levels may flip sides (e.g., level 5 changes from ask to bid). The cross-side validation rule (Step 4) handles this: when a level flips, the differ emits a cancel + place, never a cross-side modify.

- **Match found**: Candidate for modify (or skip if within tolerance)
- **Desired with no match**: New placement needed
- **Current with no match**: Cancel needed

#### Scenario: Same-side match at fixed level
- **WHEN** current has a buy at level 3 and desired has a buy at level 3 with different size
- **THEN** a modify is emitted (same level, same side, size changed)

#### Scenario: Level flips side (cursor shift)
- **WHEN** current has a sell at level 5 and desired has a buy at level 5 (cursor moved above level 5)
- **THEN** a cancel for the sell and a place for the buy are emitted (cross-side, no modify)

#### Scenario: New level enters range
- **WHEN** desired includes a buy at level 2 but current has no order at level 2
- **THEN** a new placement is emitted for the buy at level 2
