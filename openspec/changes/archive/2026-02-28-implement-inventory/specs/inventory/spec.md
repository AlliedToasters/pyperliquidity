## ADDED Requirements

### Requirement: Allocation model with effective balance invariant
The Inventory SHALL maintain three balance layers per asset (token and USDC): `allocated` (operator-configured ceiling), `account` (actual exchange balance), and `effective` (computed as `min(allocated, account)`). All tranche decomposition and downstream consumers SHALL operate on effective balances only. The `effective` balance MUST never exceed `min(allocated, account)`.

#### Scenario: Effective balance when account exceeds allocation
- **WHEN** `allocated_token = 100.0` and `account_token = 150.0`
- **THEN** `effective_token` SHALL be `100.0`

#### Scenario: Effective balance when account is below allocation
- **WHEN** `allocated_token = 100.0` and `account_token = 80.0`
- **THEN** `effective_token` SHALL be `80.0`

#### Scenario: Effective balance when account equals allocation
- **WHEN** `allocated_token = 100.0` and `account_token = 100.0`
- **THEN** `effective_token` SHALL be `100.0`

#### Scenario: Effective balance with zero account
- **WHEN** `allocated_token = 100.0` and `account_token = 0.0`
- **THEN** `effective_token` SHALL be `0.0`

### Requirement: Allocation update recomputes effective
The Inventory SHALL allow updating allocation values at runtime. When allocation changes, effective balances MUST be recomputed immediately.

#### Scenario: Allocation decreased below current account
- **WHEN** `account_token = 100.0` and allocation is changed from `150.0` to `80.0`
- **THEN** `effective_token` SHALL be `80.0`

#### Scenario: Allocation increased above current account
- **WHEN** `account_token = 100.0` and allocation is changed from `80.0` to `150.0`
- **THEN** `effective_token` SHALL be `100.0`

### Requirement: Ask-side tranche decomposition uses effective balance
The Inventory SHALL compute ask-side tranches from `effective_token` balance:
- `n_full_asks = floor(effective_token / order_sz)`
- `partial_ask_sz = effective_token % order_sz` (0 if evenly divisible)
The invariant `n_full_asks * order_sz + partial_ask_sz == effective_token` MUST hold within float precision.

#### Scenario: Even division into full tranches
- **WHEN** `effective_token = 30.0` and `order_sz = 10.0`
- **THEN** `n_full_asks` SHALL be `3` and `partial_ask_sz` SHALL be `0.0`

#### Scenario: Remainder produces partial tranche
- **WHEN** `effective_token = 25.0` and `order_sz = 10.0`
- **THEN** `n_full_asks` SHALL be `2` and `partial_ask_sz` SHALL be `5.0`

#### Scenario: Less than one full tranche
- **WHEN** `effective_token = 3.0` and `order_sz = 10.0`
- **THEN** `n_full_asks` SHALL be `0` and `partial_ask_sz` SHALL be `3.0`

#### Scenario: Zero effective token balance
- **WHEN** `effective_token = 0.0`
- **THEN** `n_full_asks` SHALL be `0` and `partial_ask_sz` SHALL be `0.0`

### Requirement: Bid-side tranche decomposition walks grid descending
The Inventory SHALL compute bid-side tranches by walking grid levels descending from a given boundary level. For each level, the cost is `grid.price_at_level(level) * order_sz`. The walk continues while `effective_usdc >= cost`. If remaining USDC is insufficient for a full bid, a partial bid size SHALL be computed as `remaining_usdc / grid.price_at_level(level)`.

#### Scenario: Multiple full bids with partial remainder
- **WHEN** `effective_usdc = 25.0`, `order_sz = 10.0`, and grid levels descending from boundary are priced at `[1.0, 0.997, 0.994]`
- **THEN** `n_full_bids` SHALL be `2` (costing 10.0 + 9.97 = 19.97) and `partial_bid_sz` SHALL be approximately `5.06` (remaining 5.03 / 0.994)

#### Scenario: USDC insufficient for any full bid
- **WHEN** `effective_usdc = 5.0`, `order_sz = 10.0`, and first grid level price is `1.0`
- **THEN** `n_full_bids` SHALL be `0` and `partial_bid_sz` SHALL be `5.0`

#### Scenario: Zero effective USDC balance
- **WHEN** `effective_usdc = 0.0`
- **THEN** `n_full_bids` SHALL be `0` and `partial_bid_sz` SHALL be `0.0`

### Requirement: Fill events update account and effective balances
On fill events, the Inventory SHALL update account balances and recompute effective balances with effective clamped to allocation ceiling.

#### Scenario: Ask fill decreases token, increases USDC
- **WHEN** an ask fill occurs with `px = 1.5` and `sz = 10.0`
- **THEN** `account_token` SHALL decrease by `10.0` and `account_usdc` SHALL increase by `15.0`, and effective balances SHALL be recomputed

#### Scenario: Bid fill increases token, decreases USDC
- **WHEN** a bid fill occurs with `px = 1.5` and `sz = 10.0`
- **THEN** `account_token` SHALL increase by `10.0` and `account_usdc` SHALL decrease by `15.0`, and effective balances SHALL be recomputed

#### Scenario: Fill that pushes account above allocation
- **WHEN** `allocated_token = 100.0`, `account_token = 95.0`, and a bid fill adds `10.0` tokens
- **THEN** `account_token` SHALL be `105.0` but `effective_token` SHALL be `100.0`

### Requirement: Balance reconciliation resets account and recomputes effective
The `on_balance_update` method SHALL accept authoritative token and USDC balances from the exchange, reset account balances to those values, and recompute effective balances.

#### Scenario: Reconciliation with account above allocation
- **WHEN** reconciliation reports `token = 150.0`, `usdc = 200.0` and `allocated_token = 100.0`, `allocated_usdc = 180.0`
- **THEN** `account_token` SHALL be `150.0`, `effective_token` SHALL be `100.0`, `account_usdc` SHALL be `200.0`, `effective_usdc` SHALL be `180.0`

#### Scenario: Reconciliation with account below allocation
- **WHEN** reconciliation reports `token = 50.0`, `usdc = 100.0` and `allocated_token = 100.0`, `allocated_usdc = 200.0`
- **THEN** `account_token` SHALL be `50.0`, `effective_token` SHALL be `50.0`, `account_usdc` SHALL be `100.0`, `effective_usdc` SHALL be `100.0`

## MODIFIED Requirements

### Requirement: Ask-Side Tranche Decomposition
Ask-side tranche decomposition SHALL operate on effective token balance (not raw account balance):
```
n_full_asks = floor(effective_token / order_sz)
partial_ask_sz = effective_token % order_sz    # 0 if evenly divisible
```

#### Scenario: Even division into full tranches
- **WHEN** `effective_token = 30.0` and `order_sz = 10.0`
- **THEN** `n_full_asks` SHALL be `3` and `partial_ask_sz` SHALL be `0.0`

#### Scenario: Remainder produces partial tranche
- **WHEN** `effective_token = 25.0` and `order_sz = 10.0`
- **THEN** `n_full_asks` SHALL be `2` and `partial_ask_sz` SHALL be `5.0`

### Requirement: Bid-Side Tranche Decomposition
Bid-side tranche decomposition SHALL operate on effective USDC balance (not raw account balance). For each grid level below the current position, a bid requires `px * order_sz` USDC:
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

#### Scenario: Multiple full bids with remainder
- **WHEN** `effective_usdc` is sufficient for 2 full bids and a partial
- **THEN** `n_full_bids` SHALL be `2` and `partial_bid_sz` SHALL reflect remaining USDC at next level price

#### Scenario: Zero effective USDC
- **WHEN** `effective_usdc = 0.0`
- **THEN** `n_full_bids` SHALL be `0` and `partial_bid_sz` SHALL be `0.0`

### Requirement: Events update balances
Fill events and balance reconciliation SHALL update account balances and recompute effective balances, with effective always clamped to `min(allocated, account)`.

#### Scenario: Ask fill
- **WHEN** an ask fill occurs with `px` and `sz`
- **THEN** `account_token -= sz`, `account_usdc += px * sz`, effective balances recomputed

#### Scenario: Bid fill
- **WHEN** a bid fill occurs with `px` and `sz`
- **THEN** `account_token += sz`, `account_usdc -= px * sz`, effective balances recomputed

#### Scenario: Balance reconciliation
- **WHEN** `on_balance_update(token, usdc)` is called
- **THEN** account balances are set to provided values and effective balances are recomputed
