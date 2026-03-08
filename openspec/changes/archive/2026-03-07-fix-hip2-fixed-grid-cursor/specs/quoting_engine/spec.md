## MODIFIED Requirements

### Requirement: Quoting engine interface accepts PricingGrid and effective balances

The quoting engine SHALL expose a single pure function:

```python
compute_desired_orders(
    grid: PricingGrid,
    effective_token: float,
    effective_usdc: float,
    order_sz: float,
    min_notional: float = 0.0,
) -> list[DesiredOrder]
```

The function accepts a `PricingGrid` (constructed once, fixed for the strategy's lifetime), effective balances from inventory, the order size, and an optional minimum notional threshold.

The function SHALL NOT accept a `boundary_level` parameter. The boundary (cursor) is derived internally from `effective_token` and `order_sz` (see cursor computation requirement).

The function SHALL return a plain `list[DesiredOrder]`. There is no `QuoteResult` wrapper — `mid_price`, `effective_order_sz`, and `effective_n_orders` are artifacts of the removed floating-mid approach and are not computed.

#### Scenario: Function signature
- **WHEN** `compute_desired_orders` is called with `(grid, effective_token, effective_usdc, order_sz)`
- **THEN** it returns a `list[DesiredOrder]` without requiring a boundary_level parameter

#### Scenario: Deterministic output
- **WHEN** `compute_desired_orders` is called twice with identical arguments
- **THEN** both calls return identical lists of DesiredOrder

### Requirement: Cursor is derived from token balance each tick

The quoting engine SHALL compute the cursor (boundary between bids and asks) from effective token balance:

```
n_full_asks = floor(effective_token / order_sz)
partial_ask_sz = effective_token % order_sz
total_ask_levels = min(n_full_asks + (1 if partial_ask_sz > 0 else 0), grid.n_orders)
cursor = grid.n_orders - total_ask_levels
```

The cursor is the grid level index of the lowest ask. All levels below the cursor are bid candidates. The cursor is NOT stored as state — it is recomputed every tick from current effective balances.

#### Scenario: Cursor at initial deployment
- **WHEN** `effective_token = 97941.26`, `order_sz = 1000`, `grid.n_orders = 100`
- **THEN** `n_full_asks = 97`, `partial = 941.26`, `total_ask_levels = 98`, `cursor = 2`

#### Scenario: Cursor shifts up after sell (user buys from MM)
- **WHEN** effective_token decreases from 97941.26 to 95991.26 (user bought 1950 tokens)
- **THEN** `n_full_asks = 95`, `partial = 991.26`, `total_ask_levels = 96`, `cursor = 4`

#### Scenario: Cursor at grid extremes
- **WHEN** `effective_token = 0` (all tokens sold)
- **THEN** `cursor = grid.n_orders` (all levels are bid candidates, no asks)

#### Scenario: Cursor capped at grid size
- **WHEN** `effective_token` is large enough for more ask levels than `grid.n_orders`
- **THEN** `total_ask_levels` is capped at `grid.n_orders`, `cursor = 0` (all levels are asks)

### Requirement: Ask placement ascending from cursor

The quoting engine SHALL place asks on the grid starting at the cursor level and ascending:

1. If `partial_ask_sz > 0`, place one partial ask at level `cursor` with size `partial_ask_sz`
2. Place `n_full_asks` full asks (size `order_sz`) at levels ascending from `cursor + (1 if partial else 0)`
3. If any ask level would exceed `grid.n_orders - 1`, truncate (do not place)

Asks are placed at the LOWEST available price levels (tightest spread), matching observed HIP-2 behavior.

#### Scenario: Partial ask at cursor
- **WHEN** `effective_token = 2500`, `order_sz = 1000`, `cursor = 7`
- **THEN** asks are: level 7 (partial, size 500), level 8 (full, 1000), level 9 (full, 1000)

#### Scenario: No partial (exact multiple)
- **WHEN** `effective_token = 3000`, `order_sz = 1000`, `cursor = 7`
- **THEN** asks are: level 7 (full, 1000), level 8 (full, 1000), level 9 (full, 1000) — no partial

#### Scenario: Grid overflow truncation
- **WHEN** cursor is at level 98 on a 100-level grid and there are 5 full asks needed
- **THEN** only 2 asks are placed (levels 98, 99) — remaining 3 are truncated

### Requirement: Bid placement descending from cursor

The quoting engine SHALL place bids descending from `cursor - 1` through level 0, funded by USDC:

1. Walk levels descending from `cursor - 1`
2. At each level, compute cost = `grid.price_at_level(level) * order_sz`
3. If `effective_usdc >= cost`, place a full bid (size `order_sz`), deduct cost
4. If remaining USDC cannot cover a full bid but is > 0, place a partial bid with `remaining_usdc / price`
5. Stop when USDC is exhausted or level 0 is reached

Bids are placed at the HIGHEST remaining price levels (tightest spread), matching observed HIP-2 behavior.

#### Scenario: Full bids with USDC
- **WHEN** `cursor = 4`, `order_sz = 1000`, grid prices at levels 0-3 are [1.000, 1.003, 1.006, 1.009], and `effective_usdc = 5000`
- **THEN** bids are placed at levels 3, 2, 1, 0 (descending from cursor), each size 1000, until USDC is exhausted

#### Scenario: Partial bid when USDC runs out
- **WHEN** `cursor = 3`, USDC is sufficient for levels 2 and 1 but only partially for level 0
- **THEN** levels 2 and 1 get full bids, level 0 gets a partial bid with `remaining_usdc / price_at_level(0)`

#### Scenario: No bids when cursor is at 0
- **WHEN** `cursor = 0` (all levels are asks)
- **THEN** no bids are placed regardless of USDC balance

### Requirement: No ask and bid share the same grid level

The quoting engine SHALL guarantee that no grid level has both a bid and an ask order. The cursor cleanly separates asks (at cursor and above) from bids (below cursor). This ensures a minimum spread of one grid level spacing (~30 bps for tick_size=0.003).

#### Scenario: Minimum spread maintained
- **WHEN** the cursor is at level 5
- **THEN** the tightest ask is at level 5 and the tightest bid is at level 4 — spread equals one tick

### Requirement: Minimum notional filtering

The quoting engine SHALL exclude any order where `price * size < min_notional` from the returned list. This applies to both asks and bids, including partial orders.

When `min_notional` is 0.0 (default), no filtering occurs.

#### Scenario: Partial order filtered by min_notional
- **WHEN** a partial ask has `price = 1.006` and `size = 5.0`, and `min_notional = 10.0`
- **THEN** the partial ask (`1.006 * 5.0 = 5.03 < 10.0`) is excluded from the result

#### Scenario: Full order passes min_notional
- **WHEN** a full ask has `price = 1.006` and `size = 1000`, and `min_notional = 10.0`
- **THEN** the order (`1.006 * 1000 = 1006 >= 10.0`) is included in the result

#### Scenario: No filtering when min_notional is zero
- **WHEN** `min_notional = 0.0`
- **THEN** all orders (including partials) are included in the result

### Requirement: DesiredOrder uses absolute grid level indices

Each `DesiredOrder` SHALL have a `level_index` that is an absolute position on the `PricingGrid` (0 = `start_px`, `n_orders - 1` = highest price). Both bids and asks share the same index space.

`DesiredOrder` is a frozen, hashable dataclass:
```
DesiredOrder:
    side: "buy" | "sell"
    level_index: int    # absolute grid position
    price: float
    size: float
```

#### Scenario: Ask level index
- **WHEN** the cursor is at level 5 on a 10-level grid
- **THEN** asks have `level_index` values 5, 6, 7, 8, 9

#### Scenario: Bid level index
- **WHEN** the cursor is at level 5
- **THEN** bids have `level_index` values 4, 3, 2, 1, 0 (descending from cursor)

### Requirement: Edge cases

- **Both balances zero**: Return an empty list.
- **All tokens sold** (`effective_token = 0`): Cursor at `n_orders`. Only bids, no asks.
- **All USDC spent** (`effective_usdc = 0`): Only asks, no bids.
- **order_sz larger than total token balance**: Single partial ask at the top of the grid.
- **Grid overflow**: Asks exceeding the grid's maximum level index are truncated.
- **Total ask size**: Equals `effective_token` (all tokens are quoted, before min_notional filtering).
- **Total bid cost**: Sum of `px * sz` for all bids ≤ `effective_usdc`.

#### Scenario: Both balances zero
- **WHEN** `effective_token = 0` and `effective_usdc = 0`
- **THEN** an empty list is returned

#### Scenario: All tokens sold
- **WHEN** `effective_token = 0` and `effective_usdc = 5000`
- **THEN** cursor is at `n_orders`, only bid orders are returned

#### Scenario: Single partial ask
- **WHEN** `effective_token = 50` and `order_sz = 1000`
- **THEN** one partial ask of size 50 is placed at `n_orders - 1`

## REMOVED Requirements

### Requirement: QuoteResult return type
**Reason**: The `QuoteResult` wrapper (containing `mid_price`, `effective_order_sz`, `effective_n_orders`) is an artifact of the floating-mid approach. With a fixed grid and cursor derivation, there is no floating mid to report, and the effective_order_sz/n_orders adjustments are replaced by min_notional filtering.
**Migration**: Callers receive `list[DesiredOrder]` directly. For logging a reference price, use `grid.price_at_level(cursor)` where cursor is derived from `floor(effective_token / order_sz)`.

### Requirement: Floating mid price derivation
**Reason**: The floating-mid approach (`mid = usdc / tokens`) with per-tick grid regeneration does not match HIP-2 behavior. HIP-2 uses a fixed grid with a boundary cursor.
**Migration**: Replace with fixed `PricingGrid` constructed once from `start_px`. Price emerges from inventory position on the grid, not from a ratio.
