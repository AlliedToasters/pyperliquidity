## Context

The quoting engine is the central pure-math module in the pipeline. Upstream, `Inventory` tracks effective balances and decomposes them into tranches. Downstream, `order_differ` matches desired orders against live orders by `(side, level_index)`. The quoting engine bridges these: it takes inventory state + price grid and emits a deterministic list of `DesiredOrder` objects.

The `PricingGrid` and `Inventory` modules are already implemented. The `order_differ` is also implemented and expects `DesiredOrder` with a `level_index` field for stable identity matching.

## Goals / Non-Goals

**Goals:**
- Implement `compute_desired_orders()` as a pure, deterministic function
- Define `DesiredOrder` dataclass consumed by order_differ
- Handle all edge cases: empty balances, one-sided inventory, partials, minimum notional filtering
- Comprehensive test coverage

**Non-Goals:**
- No I/O, no imports from order_state/ws_state/batch_emitter
- No stored boundary state — boundary is computed from inputs each call
- No AMM formula — pricing emerges from grid position
- No config file parsing — parameters are passed in directly

## Decisions

### 1. Function signature takes primitives, not Inventory

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

**Rationale**: The quoting engine should not import or depend on the `Inventory` class. Passing primitives keeps it a pure function with no coupling. The caller (state manager) extracts values from `Inventory` before calling.

**Alternative considered**: Passing `Inventory` directly — rejected because it creates a coupling and makes testing harder. The engine doesn't need allocation logic, just the numbers.

### 2. Boundary level is an explicit input parameter

The boundary level (lowest ask level index) is passed in, not computed internally. The caller determines it from inventory state — `Inventory` already has the context (n_seeded_levels, fill history) to compute this.

**Rationale**: The spec says "computed not stored", but it must come from somewhere. Inventory is where the state lives. The quoting engine is stateless — it just places asks starting at `boundary_level` ascending and bids starting at `boundary_level - 1` descending.

**Alternative considered**: Having the engine compute boundary from n_seeded_levels + fill count — rejected because that would require the engine to track state, violating its pure-function contract.

### 3. DesiredOrder is a frozen dataclass

```python
@dataclass(frozen=True)
class DesiredOrder:
    side: str       # "buy" | "sell"
    level_index: int
    price: float
    size: float
```

Frozen for immutability and hashability. The order_differ matches on `(side, level_index)`.

### 4. Minimum notional filtering happens at the end

After computing all orders (asks + bids), filter out any where `price * size < min_notional`. This is simpler than trying to redistribute filtered amounts.

**Trade-off**: Filtered partial orders mean slightly less than 100% of balance is quoted. This is acceptable — the alternative (redistributing) adds complexity for marginal benefit.

### 5. Ask-side ordering: ascending from boundary

Asks are placed at levels `boundary_level, boundary_level+1, ...` — full asks first, then partial at the top. This matches HIP-2 behavior where the lowest ask is at the boundary.

### 6. Bid-side ordering: descending from boundary-1

Bids walk down from `boundary_level - 1` to level 0 (or until USDC is exhausted). Full bids first, partial at the bottom.

## Risks / Trade-offs

- **[Float precision]** → Use careful arithmetic; the existing inventory module already handles float clamping. The quoting engine doesn't compound — it reads grid prices directly, so precision is bounded by PricingGrid's rounding.
- **[Grid overflow]** → If `boundary_level + n_full_asks + (1 if partial)` exceeds grid size, asks are truncated at the grid edge. Same for bids below level 0. This is correct behavior — the grid is finite.
- **[Minimum notional kills all orders]** → If min_notional is set very high, all orders could be filtered. The function returns an empty list — this is valid and the caller should handle it.
