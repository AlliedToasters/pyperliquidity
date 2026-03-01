## 1. Data Structures

- [x] 1.1 Define `TrancheDecomposition` frozen dataclass with fields: `n_full` (int), `partial_sz` (float), `levels` (tuple of grid level indices used)
- [x] 1.2 Define `Inventory` mutable dataclass with fields: `order_sz`, `allocated_token`, `allocated_usdc`, `account_token`, `account_usdc`, `effective_token`, `effective_usdc`
- [x] 1.3 Implement `_recompute_effective()` private method that sets `effective = min(allocated, account)` for both token and USDC

## 2. Allocation Management

- [x] 2.1 Implement `update_allocation(token: float, usdc: float)` that sets allocated values and calls `_recompute_effective()`
- [x]2.2 Write tests for allocation update: decrease below account, increase above account, equal to account

## 3. Ask-Side Tranche Decomposition

- [x] 3.1 Implement `compute_ask_tranches() -> TrancheDecomposition` using `effective_token` and `order_sz`
- [x]3.2 Write tests: even division, remainder partial, less than one tranche, zero balance, invariant check (`n_full * order_sz + partial == effective_token`)

## 4. Bid-Side Tranche Decomposition

- [x] 4.1 Implement `compute_bid_tranches(grid: PriceGrid, boundary_level: int) -> TrancheDecomposition` walking grid levels descending from boundary using `effective_usdc`
- [x]4.2 Write tests: multiple full bids with partial, insufficient for one full bid, zero USDC, boundary at grid edge, USDC exhausted exactly at a level

## 5. Fill Event Handlers

- [x] 5.1 Implement `on_ask_fill(px: float, sz: float)` — decreases account_token, increases account_usdc, recomputes effective
- [x] 5.2 Implement `on_bid_fill(px: float, sz: float)` — increases account_token, decreases account_usdc, recomputes effective
- [x]5.3 Write tests: basic ask fill, basic bid fill, fill that pushes account above allocation (effective clamped), sequence of fills shifting boundary

## 6. Balance Reconciliation

- [x] 6.1 Implement `on_balance_update(token: float, usdc: float)` — resets account balances, recomputes effective
- [x]6.2 Write tests: reconciliation with account above allocation, below allocation, both sides, zero balances

## 7. Edge Cases and Integration

- [x]7.1 Write tests for zero balance on one side (all orders on other side)
- [x]7.2 Write tests verifying effective never exceeds min(allocated, account) across all mutation paths
- [x]7.3 Verify all public functions have type hints, run pytest and mypy pass
