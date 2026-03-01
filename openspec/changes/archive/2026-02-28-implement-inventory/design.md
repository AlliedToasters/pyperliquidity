## Context

The inventory module sits between `pricing_grid` (implemented) and `quoting_engine` (not yet implemented) in the computation pipeline. It is a pure-math module: no I/O, no async. Its job is to track balances and decompose them into tranches that the quoting engine consumes.

The existing inventory spec defines raw balance tracking. This change adds an allocation model so the strategy operates on capped effective balances — the operator allocates a ceiling for token and USDC, and the module enforces `effective = min(allocated, account)` as the invariant downstream consumers see.

`PriceGrid` from `pricing_grid` is the only dependency — needed for bid-side cost computation (walking grid levels descending to compute USDC cost per bid tranche).

## Goals / Non-Goals

**Goals:**
- Implement `Inventory` dataclass with allocation-aware balance tracking
- Expose tranche decomposition (ask-side and bid-side) computed from effective balances
- Handle fill events and balance reconciliation, always clamping effective to allocation ceiling
- Provide a clean API surface for `quoting_engine` to consume
- Thorough test coverage of all computations and edge cases

**Non-Goals:**
- No I/O, no WebSocket integration — that's `ws_state`'s job
- No order tracking — that's `order_state`'s job
- No grid construction — caller passes in a `PriceGrid`
- No persistence or serialization

## Decisions

### 1. Mutable dataclass (not frozen)

The inventory tracks balances that change on every fill and reconciliation. A frozen dataclass would require creating a new instance for every event, which is unnecessary overhead for an internal state object. Methods mutate in-place.

**Alternative**: Frozen dataclass with copy-on-write — rejected because inventory is owned by a single state manager, not shared. Immutability adds ceremony without safety benefit here.

### 2. Separate account vs. allocated vs. effective fields

Three balance layers per asset (token, USDC):
- `allocated_*`: operator-configured ceiling, set at construction, adjustable
- `account_*`: actual exchange balance from reconciliation / fill tracking
- `effective_*`: `min(allocated, account)` — the only value tranche math uses

**Alternative**: Single balance with a cap check — rejected because it loses observability. The operator needs to see when account exceeds allocation (idle capital) vs. when account is below allocation (allocation too high).

### 3. Tranche decomposition as a computed snapshot

`TrancheDecomposition` is a frozen dataclass returned by a method, not stored as state. This keeps the `Inventory` state minimal (just balances) and ensures tranche math is always fresh.

**Alternative**: Cache tranches and invalidate on balance change — rejected as premature optimization. Tranche math is O(n_orders) at most, called once per tick.

### 4. Bid walk takes boundary_level as parameter

The bid-side tranche walk needs to know where to start descending on the grid. The boundary is determined by the quoting engine (it depends on which grid levels have active asks). So `compute_bid_tranches` takes a `boundary_level` parameter rather than computing it internally.

**Alternative**: Have inventory own the boundary — rejected because the boundary depends on order state, not just balances.

### 5. Float arithmetic (not Decimal)

Following the same pattern as `pricing_grid`. The grid levels are pre-computed floats, and tranche math inherits that precision. The spec notes "careful float handling" — we use the grid's pre-rounded prices for cost computation, avoiding cascading rounding errors.

## Risks / Trade-offs

- **Float precision in bid walk**: Subtracting `px * order_sz` repeatedly can accumulate error. → Mitigation: Use grid's pre-rounded prices. For typical grid sizes (< 100 levels), error stays well under a cent.
- **Stale account balance**: Between reconciliation ticks, fill-based tracking can drift from exchange reality. → Mitigation: This is by design — optimistic updates between reconciliation. The `on_balance_update` method is the authoritative reset.
- **Allocation changes at runtime**: If the operator changes allocation while orders are live, effective balances jump. → Mitigation: The quoting engine handles this naturally — next tick recomputes desired orders from new effective balances. The differ handles the transition.
