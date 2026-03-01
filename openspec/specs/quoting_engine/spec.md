# Quoting Engine

## Purpose

Pure function that computes the desired set of orders given current inventory and the price grid. Zero I/O, zero side effects. This is the HIP-2 algorithm logic.

## Interface

```python
compute_desired_orders(
    grid: PricingGrid,
    boundary_level: int,
    effective_token: float,
    effective_usdc: float,
    order_sz: float,
    min_notional: float = 0.0,
) -> list[DesiredOrder]
```

Where `boundary_level` is the lowest ask level index on the grid, passed as an explicit parameter. `min_notional` defaults to 0.0 (no filtering).

### DesiredOrder

A frozen dataclass:
```
DesiredOrder:
    side: "buy" | "sell"
    level_index: int
    price: float
    size: float
```

`DesiredOrder` is immutable and hashable. Two instances with identical fields are equal and share the same hash.

## Algorithm

1. **Compute ask tranches**:
   - `n_full = floor(effective_token / order_sz)`
   - `partial = effective_token - n_full * order_sz`
   - Place `n_full` asks of size `order_sz` at ascending grid levels starting from `boundary_level`
   - If `partial > 0`, place one partial ask at level `boundary_level + n_full`
   - If any ask level exceeds the grid's maximum index, truncate (do not place that order)

2. **Compute bid tranches**:
   - Walk grid levels descending from `boundary_level - 1`
   - At each level, compute cost = `grid.price_at_level(level) * order_sz`
   - If `effective_usdc >= cost`, place a full bid (size `order_sz`) and deduct cost
   - If remaining USDC cannot cover a full bid but is > 0, place a partial bid with `remaining_usdc / price`
   - Stop when USDC is exhausted or level 0 is reached

3. **Minimum notional filtering**: Remove any order where `price * size < min_notional` from the result (both asks and bids, including partials).

4. **Return**: All desired orders (asks + bids), each tagged with their grid level_index

## Invariants

1. Output is deterministic: same inputs always produce the same orders in the same order
2. No ask and bid share the same grid level (guaranteed 0.3% spread minimum)
3. Total ask size == effective_token (all tokens are quoted, before min_notional filtering)
4. Total bid cost (sum of px * sz for bids) ≤ effective_usdc
5. Orders are contiguous on the grid — no gaps between the lowest ask and highest bid
6. No side effects, no I/O, no dependency on external mutable state

## Boundary Tracking

The boundary is the lowest ask level index, passed explicitly as `boundary_level`. As fills occur, the boundary shifts naturally. The "price" of the market maker is an emergent property of its inventory position on the grid, just like a constant-product AMM.

## Edge Cases

- All tokens sold (effective_token = 0): Only bids, no asks.
- All USDC spent (effective_usdc = 0): Only asks, no bids.
- Both balances zero: Return an empty list.
- boundary_level at 0: No bids (no levels below boundary).
- boundary_level at grid max: No asks (no room on the grid).
- order_sz larger than total balance: Single partial order on one side.
- Grid overflow: Asks that exceed the grid's maximum level index are truncated.
- Minimum notional filtering: Orders below `min_notional` are excluded from the result.

## Dependencies

- `pricing_grid.PricingGrid`: Grid levels and prices
- Standard library and typing only
- NO dependency on `order_state`, `ws_state`, `batch_emitter`, `rate_limit`, or any I/O module
