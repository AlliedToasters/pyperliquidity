# Quoting Engine

## Purpose

Pure function that computes the desired set of orders given current inventory and the price grid. Zero I/O, zero side effects. This is the HIP-2 algorithm logic.

## Interface

```
compute_desired_orders(
    grid: PriceGrid,
    token_balance: float,
    usdc_balance: float,
    order_sz: float,
) -> list[DesiredOrder]
```

Where:
```
DesiredOrder:
    side: "buy" | "sell"
    level_index: int
    price: float
    size: float
```

## Algorithm

1. **Compute ask tranches**:
   - `n_full = floor(token_balance / order_sz)`
   - `partial = token_balance % order_sz`
   - Place `n_full` asks of size `order_sz` at ascending grid levels starting from the boundary
   - If `partial > 0`, place one partial ask above the full asks (or at the boundary+n_full level)

2. **Determine boundary**: The boundary level is the lowest ask level. All levels below are potential bids.

3. **Compute bid tranches**:
   - Walk grid levels descending from `boundary - 1`
   - At each level, if `usdc_balance >= price * order_sz`, place a full bid and deduct the cost
   - If remaining USDC can't cover a full bid, place a partial bid with `remaining_usdc / price`
   - Stop when USDC is exhausted

4. **Return**: All desired orders (bids + asks), each tagged with their grid level_index

## Invariants

1. Output is deterministic: same inputs always produce the same orders
2. No ask and bid share the same grid level (guaranteed 0.3% spread minimum)
3. Total ask size == token_balance (all tokens are quoted)
4. Total bid cost (sum of px * sz for bids) ≤ usdc_balance
5. Orders are contiguous on the grid — no gaps between the lowest ask and highest bid

## Boundary Tracking

The boundary is NOT a stored parameter — it is computed from the inventory decomposition. As fills occur, the boundary shifts naturally. This is the key insight: the "price" of the market maker is an emergent property of its inventory, just like a constant-product AMM.

## Edge Cases

- All tokens sold (token_balance ≈ 0): Only bids, no asks. Boundary is at the top of filled levels.
- All USDC spent (usdc_balance ≈ 0): Only asks, no bids. Boundary is at the bottom.
- order_sz larger than total balance: Single partial order on one side.
- Minimum order size enforcement: Exchange may reject orders below a minimum notional. Filter these out.

## Dependencies

- `pricing_grid`: Grid levels and prices
- NO dependency on order_state, ws_state, or any I/O module
