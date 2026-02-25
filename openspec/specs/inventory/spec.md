# Inventory

## Purpose

Track the market maker's token and USDC balances, compute tranche decomposition (how many full and partial orders the current balance supports), and determine the bid/ask boundary on the price grid.

## State

- `token_balance: float` — Current token holdings
- `usdc_balance: float` — Current USDC holdings
- `order_sz: float` — Size of a full order tranche (HIP-2 parameter)

## Core Computations

### Ask-Side Tranche Decomposition
```
n_full_asks = floor(token_balance / order_sz)
partial_ask_sz = token_balance % order_sz    # 0 if evenly divisible
```

### Bid-Side Tranche Decomposition
For each grid level below the current position, a bid requires `px * order_sz` USDC:
```
available_usdc = usdc_balance
n_full_bids = 0
for level in grid_descending_from_boundary:
    cost = grid.price_at_level(level) * order_sz
    if available_usdc >= cost:
        n_full_bids += 1
        available_usdc -= cost
    else:
        partial_bid_sz = available_usdc / grid.price_at_level(level)
        break
```

### Grid Boundary
The boundary between bids and asks is determined by the current inventory state. As tokens are sold (asks filled), the boundary moves up. As tokens are bought (bids filled), the boundary moves down.

## Invariants

1. `n_full_asks * order_sz + partial_ask_sz == token_balance` (within float precision)
2. Total USDC committed to bids ≤ `usdc_balance`
3. Ask levels are always above bid levels on the grid (no overlap)
4. When a tranche fills, balances update atomically: an ask fill decreases token_balance and increases usdc_balance by `fill_px * fill_sz`

## Events

- `on_ask_fill(px, sz)`: `token_balance -= sz`, `usdc_balance += px * sz`, recompute tranches
- `on_bid_fill(px, sz)`: `token_balance += sz`, `usdc_balance -= px * sz`, recompute tranches
- `on_balance_update(token, usdc)`: Full state reset from exchange data (reconciliation)

## Edge Cases

- Balance insufficient for even one full order on either side — place only the partial
- Zero balance on one side — no orders on that side, all orders on the other
- Fill arrives before balance update — use fill data to update optimistically, reconcile later

## Dependencies

- `pricing_grid`: Needs grid levels for bid cost computation and boundary placement
