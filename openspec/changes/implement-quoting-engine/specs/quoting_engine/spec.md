## MODIFIED Requirements

### Requirement: compute_desired_orders interface
The system SHALL expose a `compute_desired_orders` function with the following signature:

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

The function SHALL accept `boundary_level` as an explicit integer parameter representing the lowest ask level index on the grid. The function SHALL accept `min_notional` as a parameter for filtering orders below the exchange minimum.

#### Scenario: Basic invocation with all parameters
- **WHEN** `compute_desired_orders` is called with a valid grid, boundary_level=5, effective_token=3.0, effective_usdc=100.0, order_sz=1.0, min_notional=0.0
- **THEN** the function SHALL return a list of `DesiredOrder` objects with asks starting at level 5 ascending and bids starting at level 4 descending

#### Scenario: Default min_notional
- **WHEN** `compute_desired_orders` is called without specifying min_notional
- **THEN** min_notional SHALL default to 0.0 (no filtering)

## ADDED Requirements

### Requirement: DesiredOrder dataclass
The system SHALL define a `DesiredOrder` frozen dataclass with fields: `side` (str, "buy" or "sell"), `level_index` (int), `price` (float), and `size` (float). `DesiredOrder` SHALL be immutable and hashable.

#### Scenario: DesiredOrder creation
- **WHEN** a `DesiredOrder` is created with side="sell", level_index=5, price=1.003, size=10.0
- **THEN** all fields SHALL be accessible and the object SHALL be immutable

#### Scenario: DesiredOrder equality
- **WHEN** two `DesiredOrder` objects are created with identical fields
- **THEN** they SHALL be equal and have the same hash

### Requirement: Ask-side order generation
The function SHALL compute ask orders as follows:
1. Compute `n_full = floor(effective_token / order_sz)`
2. Place `n_full` asks of size `order_sz` at ascending grid levels starting from `boundary_level`
3. Compute `partial = effective_token - n_full * order_sz`
4. If `partial > 0`, place one partial ask at level `boundary_level + n_full`
5. If any ask level exceeds the grid's maximum index, truncate (do not place that order)

Each ask order SHALL have `side="sell"`, the grid level's price, and the appropriate size.

#### Scenario: Three full asks and one partial
- **WHEN** effective_token=3.5, order_sz=1.0, boundary_level=2
- **THEN** the function SHALL produce asks at levels 2, 3, 4 (size 1.0 each) and level 5 (size 0.5)

#### Scenario: Exact multiple of order_sz
- **WHEN** effective_token=3.0, order_sz=1.0, boundary_level=2
- **THEN** the function SHALL produce exactly 3 asks at levels 2, 3, 4 with no partial

#### Scenario: Token balance less than one order_sz
- **WHEN** effective_token=0.3, order_sz=1.0, boundary_level=2
- **THEN** the function SHALL produce one partial ask at level 2 (size 0.3)

#### Scenario: Grid overflow on ask side
- **WHEN** boundary_level is near the top of the grid and n_full asks would exceed grid bounds
- **THEN** asks SHALL be truncated at the grid's maximum level index

### Requirement: Bid-side order generation
The function SHALL compute bid orders by walking grid levels descending from `boundary_level - 1`:
1. At each level, compute cost = `grid.price_at_level(level) * order_sz`
2. If `effective_usdc >= cost`, place a full bid (size `order_sz`) and deduct cost
3. If remaining USDC cannot cover a full bid but is > 0, place a partial bid with size `remaining_usdc / price`
4. Stop when USDC is exhausted or level 0 is reached

Each bid order SHALL have `side="buy"`, the grid level's price, and the appropriate size.

#### Scenario: Two full bids and one partial
- **WHEN** effective_usdc is enough for 2 full bids at levels below boundary with some remainder
- **THEN** the function SHALL produce 2 full bids and 1 partial bid at descending levels

#### Scenario: USDC exhausted before reaching level 0
- **WHEN** effective_usdc covers fewer bids than levels available below the boundary
- **THEN** the function SHALL stop placing bids when USDC is exhausted

#### Scenario: Boundary at level 0
- **WHEN** boundary_level=0
- **THEN** there SHALL be no bid orders (no levels below boundary)

### Requirement: Minimum notional filtering
After computing all orders, the function SHALL remove any order where `price * size < min_notional`. This applies to both asks and bids, including partial orders.

#### Scenario: Partial order below minimum notional
- **WHEN** a partial ask has price=1.0, size=0.001, and min_notional=0.01
- **THEN** that order SHALL be excluded from the result

#### Scenario: All orders above minimum notional
- **WHEN** all computed orders have notional >= min_notional
- **THEN** all orders SHALL be included in the result

### Requirement: Determinism
The function SHALL be deterministic: given identical inputs, it SHALL always produce identical output in the same order. The function SHALL have no side effects, no I/O, and no dependency on external mutable state.

#### Scenario: Repeated invocation
- **WHEN** `compute_desired_orders` is called twice with the same arguments
- **THEN** both calls SHALL return identical lists of DesiredOrder objects

### Requirement: Empty and one-sided edge cases
The function SHALL handle degenerate inventory states:
- Zero token balance: return only bid orders
- Zero USDC balance: return only ask orders
- Both zero: return an empty list

#### Scenario: All tokens sold
- **WHEN** effective_token=0.0 and effective_usdc > 0
- **THEN** the function SHALL return only buy orders

#### Scenario: All USDC spent
- **WHEN** effective_usdc=0.0 and effective_token > 0
- **THEN** the function SHALL return only sell orders

#### Scenario: Both balances zero
- **WHEN** effective_token=0.0 and effective_usdc=0.0
- **THEN** the function SHALL return an empty list

### Requirement: No I/O module dependencies
The quoting engine module SHALL NOT import or reference `order_state`, `ws_state`, `batch_emitter`, `rate_limit`, or any I/O modules. Its only dependency SHALL be `pricing_grid.PricingGrid`.

#### Scenario: Module imports
- **WHEN** the quoting_engine module is inspected
- **THEN** it SHALL only import from `pricing_grid`, standard library, and typing modules
