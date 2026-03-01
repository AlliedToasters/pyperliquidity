# Inventory

## Purpose

Track the market maker's token and USDC balances, compute tranche decomposition (how many full and partial orders the current balance supports), and determine the bid/ask boundary on the price grid.

## Allocation Model

The Inventory maintains three balance layers per asset (token and USDC):

- `allocated` — Operator-configured ceiling. The maximum balance the strategy may use.
- `account` — Actual exchange balance from reconciliation or fill tracking.
- `effective` — Computed as `min(allocated, account)`. The only value tranche math and downstream consumers use.

The core invariant: `effective` MUST never exceed `min(allocated, account)`.

Allocation values may be updated at runtime. When allocation changes, effective balances are recomputed immediately.

## State

- `order_sz: float` — Size of a full order tranche (HIP-2 parameter)
- `allocated_token: float` — Maximum token balance the strategy may use
- `allocated_usdc: float` — Maximum USDC balance the strategy may use
- `account_token: float` — Actual token holdings on the exchange
- `account_usdc: float` — Actual USDC holdings on the exchange
- `effective_token: float` — `min(allocated_token, account_token)`
- `effective_usdc: float` — `min(allocated_usdc, account_usdc)`

## Core Computations

### Ask-Side Tranche Decomposition

Ask-side tranche decomposition operates on effective token balance (not raw account balance):
```
n_full_asks = floor(effective_token / order_sz)
partial_ask_sz = effective_token % order_sz    # 0 if evenly divisible
```

Invariant: `n_full_asks * order_sz + partial_ask_sz == effective_token` (within float precision)

### Bid-Side Tranche Decomposition

Bid-side tranche decomposition operates on effective USDC balance (not raw account balance). For each grid level below the current position, a bid requires `px * order_sz` USDC:
```
available_usdc = effective_usdc
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

1. `n_full_asks * order_sz + partial_ask_sz == effective_token` (within float precision)
2. Total USDC committed to bids ≤ `effective_usdc`
3. Ask levels are always above bid levels on the grid (no overlap)
4. When a tranche fills, account balances update atomically and effective balances are recomputed
5. `effective` never exceeds `min(allocated, account)` across all mutation paths

## Events

Fill events and balance reconciliation update account balances and recompute effective balances, with effective always clamped to `min(allocated, account)`.

- `on_ask_fill(px, sz)`: `account_token -= sz`, `account_usdc += px * sz`, recompute effective and tranches
- `on_bid_fill(px, sz)`: `account_token += sz`, `account_usdc -= px * sz`, recompute effective and tranches
- `on_balance_update(token, usdc)`: Full state reset from exchange data (reconciliation), recompute effective
- `update_allocation(token, usdc)`: Update allocation ceilings, recompute effective

## Edge Cases

- Balance insufficient for even one full order on either side — place only the partial
- Zero balance on one side — no orders on that side, all orders on the other
- Fill arrives before balance update — use fill data to update optimistically, reconcile later
- Fill pushes account above allocation — account tracks the real value, effective remains clamped
- Allocation decreased below current account — effective drops to new allocation ceiling

## Dependencies

- `pricing_grid`: Needs grid levels for bid cost computation and boundary placement
