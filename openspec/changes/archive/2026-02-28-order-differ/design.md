## Context

The market maker pipeline is: QuotingEngine → OrderDiffer → BatchEmitter. The quoting engine produces a `list[DesiredOrder]` each tick, and the order state maintains `TrackedOrder` entries for all resting orders. The order differ must bridge these two, computing the minimum mutations to converge current state to desired state.

Hyperliquid's rate limit budget model (`10_000 + volume - requests`) means every unnecessary API call erodes capacity. Batch operations cost 1 regardless of batch size, but each mutation inside a batch still needs to be correct. The differ's job is to minimize the _number of orders that change_, so the emitter can pack them efficiently.

The differ consumes `DesiredOrder` (from quoting_engine) and `TrackedOrder` (from order_state). Both use `(side, level_index)` as stable identity keys, and both carry `price` and `size` fields.

## Goals / Non-Goals

**Goals:**
- Compute minimum mutation set (modifies, places, cancels) to converge current → desired
- Dead-zone suppression: skip entire diff cycle when overall drift is negligible
- Per-order tolerance: skip individual modifies when price/size changes are below threshold
- Cross-side safety: never emit a modify that changes side (buy↔sell); split into cancel + place
- Pure function: no I/O, no side effects, fully deterministic

**Non-Goals:**
- Budget-aware filtering (that's the batch emitter's job)
- Priority ordering of mutations (also batch emitter)
- OID management or order lifecycle tracking (order_state's job)
- Actual API interaction

## Decisions

### 1. Dead zone metric: weighted mid-price comparison

The dead zone check compares the size-weighted average price of desired orders vs current orders. If the absolute difference in basis points is below `dead_zone_bps`, return an empty diff.

**Rationale**: Size-weighted mid captures the economic center of the order set better than simple averages, which could be skewed by a single small partial order at an extreme level.

**Alternative considered**: Compare only the boundary level index. Rejected because size changes (e.g., partial fills changing tranche sizes) wouldn't trigger an update even when they should.

### 2. Matching by (side, level_index) tuple key

Both `DesiredOrder` and `TrackedOrder` carry `level_index`. Build dicts keyed by `(side, level_index)` for O(n) matching.

**Rationale**: Level index is the stable identity across ticks. When fair value shifts, "bid level 3" is still "bid level 3" at a different price. OIDs change on modifies; level_index doesn't.

### 3. Cross-side detection emits cancel + place (not modify)

If a `(side, level_index)` in current doesn't match any desired, and a desired order exists at the same level_index but opposite side, do NOT attempt a modify. Emit a cancel for the current and a place for the desired.

**Rationale**: Hyperliquid rejects cross-side modifications. This situation shouldn't arise in normal operation (the quoting engine places asks and bids on separate level ranges), but must be handled defensively.

### 4. Tolerance uses basis points for price, percentage for size

Price tolerance in bps: `abs(desired_px - current_px) / current_px * 10_000 < price_tolerance_bps`.
Size tolerance in pct: `abs(desired_sz - current_sz) / current_sz * 100 < size_tolerance_pct`.

Both must be within tolerance to skip a modify. If either exceeds threshold, emit the modify.

**Rationale**: Price naturally uses bps (standard in trading). Size uses percentage because absolute size differences aren't meaningful without knowing the order size.

### 5. Data structures use dataclasses

`OrderDiff` is a simple dataclass with three lists: `modifies`, `places`, `cancels`. No methods, no behavior — just a data transfer object from differ to emitter.

**Rationale**: Aligns with project convention (dataclasses for state objects), keeps the module pure.

## Risks / Trade-offs

- **[Dead zone too aggressive]** → Large `dead_zone_bps` suppresses legitimate updates. Mitigation: configurable per-market tuning, recommend 15-20 bps for low-volume and 3-5 bps for high-volume.
- **[Floating point comparison edge cases]** → Price/size tolerance comparisons on floats. Mitigation: use `>=` not `==`, and tolerances are relative (bps/pct) not absolute, so float imprecision is absorbed.
- **[Degenerate case: all orders change]** → If fair value jumps far (e.g., large fill), every order may need modification. Mitigation: this is correct behavior — the emitter's budget filter will throttle if needed.
