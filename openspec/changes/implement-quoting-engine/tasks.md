## 1. Core Data Structures

- [x] 1.1 Define `DesiredOrder` frozen dataclass in `src/pyperliquidity/quoting_engine.py` with fields: side (str), level_index (int), price (float), size (float)

## 2. Core Algorithm

- [x] 2.1 Implement `compute_desired_orders()` function signature with parameters: grid, boundary_level, effective_token, effective_usdc, order_sz, min_notional
- [x] 2.2 Implement ask-side order generation: n_full asks ascending from boundary_level, plus optional partial
- [x] 2.3 Implement bid-side order generation: walk descending from boundary_level-1, full bids then partial, deducting USDC
- [x] 2.4 Implement minimum notional filtering on combined order list
- [x] 2.5 Handle grid overflow: truncate asks/bids that exceed grid bounds

## 3. Edge Cases

- [x] 3.1 Handle zero token balance (bids only)
- [x] 3.2 Handle zero USDC balance (asks only)
- [x] 3.3 Handle both balances zero (empty list)
- [x] 3.4 Handle boundary_level at 0 (no bids) and at grid max (no asks)

## 4. Tests

- [x] 4.1 Test DesiredOrder dataclass: creation, immutability, equality, hashing
- [x] 4.2 Test basic ask generation: exact multiples, partials, single partial
- [x] 4.3 Test basic bid generation: full bids, partial at bottom, USDC exhaustion
- [x] 4.4 Test combined ask+bid generation with typical inventory
- [x] 4.5 Test empty/one-sided edge cases: zero tokens, zero USDC, both zero
- [x] 4.6 Test minimum notional filtering: partial below threshold, all above, all below
- [x] 4.7 Test grid overflow: asks truncated at grid max, boundary at 0
- [x] 4.8 Test determinism: identical inputs produce identical outputs across repeated calls
- [x] 4.9 Test boundary walk: simulate fill sequence moving boundary up and down the grid
- [x] 4.10 Verify module has no forbidden imports (order_state, ws_state, batch_emitter, rate_limit)
