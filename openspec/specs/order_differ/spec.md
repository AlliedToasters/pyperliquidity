# Order Differ

## Purpose

Compare desired orders (from quoting engine) against current orders (from order state) and emit the minimum set of mutations (modify, place, cancel) needed to converge. This is the rate-limit conservation core.

## Interface

```
compute_diff(
    desired: list[DesiredOrder],
    current: list[TrackedOrder],
    dead_zone_bps: float,
    price_tolerance_bps: float,
    size_tolerance_pct: float,
) -> OrderDiff
```

Where:
```
OrderDiff:
    modifies: list[tuple[int, DesiredOrder]]   # (existing_oid, new_desired)
    places: list[DesiredOrder]                  # New orders to place
    cancels: list[int]                          # OIDs to cancel
```

## Algorithm

### Step 1: Dead Zone Check
Compute the "center of mass" or mid of both desired and current order sets. If the drift is below `dead_zone_bps`, return an empty diff. This alone suppresses ~99% of mutations on low-volume markets.

Recommended: 10-20 bps for low-volume markets.

### Step 2: Level-Index Matching
Key both desired and current orders by `(side, level_index)`. This provides stable identity across ticks — when fair value shifts, "bid level 3" stays "bid level 3", just at a different price. Match desired to current by this key.

- **Match found**: Candidate for modify (or skip if within tolerance)
- **Desired with no match**: New placement needed
- **Current with no match**: Cancel needed

### Step 3: Per-Order Tolerance
For each matched pair, skip the modify if BOTH:
- Price moved less than `price_tolerance_bps` (recommend 0.5 bps)
- Size changed less than `size_tolerance_pct` (recommend 5%)

### Step 4: Cross-Side Validation
CRITICAL: Hyperliquid rejects cross-side modifications (buy→sell or sell→buy). If a level_index changed sides between current and desired (shouldn't happen in normal operation), emit a cancel + place instead of a modify.

## Output

The diff contains the minimum mutations. The batch emitter decides whether to actually execute them based on budget.

## Invariants

1. If desired == current (within tolerances), diff is empty
2. Modifies never cross sides
3. Level-index identity is stable: a modify always targets the same (side, level_index)
4. Dead zone check is computed BEFORE per-order matching (short-circuit optimization)
5. This module is pure — no I/O, no API calls

## Tuning

| Parameter | Low-Volume Market | High-Volume Market |
|-----------|------------------|-------------------|
| dead_zone_bps | 15-20 | 3-5 |
| price_tolerance_bps | 0.5-1.0 | 0.1-0.3 |
| size_tolerance_pct | 5-10% | 2-5% |

## Dependencies

- None (pure function, operates on data structures from quoting_engine and order_state)
