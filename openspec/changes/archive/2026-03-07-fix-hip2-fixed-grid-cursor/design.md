## Context

The current quoting pipeline works as follows:

1. **QuotingEngine** computes `mid = usdc / tokens` each tick, generates a fresh grid centered on mid (`generate_ask_levels` / `generate_bid_levels`), and places `n_orders` per side symmetrically around mid.
2. **PricingGrid** exists as a class but is **unused** — the quoting engine calls standalone functions instead.
3. **Level indices** are per-side (0 = closest to mid, ascending away), regenerated each tick.
4. **n_orders** means "per side" (e.g., n_orders=5 → 5 bids + 5 asks).

Reverse engineering of live HIP-2 markets reveals a fundamentally different model:

1. A **fixed grid** of `n_orders` total levels is built once from `start_px`.
2. The **cursor** (boundary between bids and asks) is derived from token inventory each tick: `cursor = n_orders - (n_full_asks + has_partial)`.
3. Asks fill ascending from the cursor; bids fill descending from below the cursor.
4. Level indices are **absolute grid positions** (0 to n_orders-1), permanent for the strategy's lifetime.

## Goals / Non-Goals

**Goals:**
- Quoting engine produces orders on a fixed grid with a cursor derived from effective balances
- PricingGrid becomes the central pricing object, constructed once, passed to quoting engine
- Level indices are absolute grid positions, stable across ticks
- `n_orders` means total grid levels (matching HIP-2 semantics)
- 5 significant figure rounding (matching observed HIP-2 ladder prices)
- `start_px` is a required config parameter

**Non-Goals:**
- Rebalancing timing (two-phase behavior, 3s block interval) — already handled by the tick loop
- Changes to inventory, order_state, batch_emitter, or rate_limit internal logic
- Multi-grid or multi-strategy support
- Oracle or external price reference integration

## Decisions

### 1. Cursor derivation from token balance

The cursor position is computed every tick from `effective_tokens`:

```python
n_full_asks = floor(effective_tokens / order_sz)
partial_ask_sz = effective_tokens % order_sz
total_ask_levels = min(n_full_asks + (1 if partial_ask_sz > 0 else 0), n_orders)
cursor = n_orders - total_ask_levels
```

Asks are placed ascending from `cursor` through `n_orders - 1`. The partial (if any) is at the cursor level. Bids are placed descending from `cursor - 1` through `0`, funded by USDC. If USDC is insufficient for all bid levels, the lowest-priced levels are omitted.

**Why token balance determines the cursor**: In HIP-2, the token supply is the finite resource — it was allocated at deployment. USDC accumulates from sells and is spent on buys, but the grid structure is token-anchored. This matches observed behavior: when HIP-2 sells tokens (user buys), the cursor moves up; when HIP-2 buys tokens (user sells), it moves down. The token balance is the single variable that determines the cursor; USDC fills whatever's left.

**Alternative considered**: Store cursor as separate state, update on fills. Rejected because it creates two sources of truth that can drift. The cursor is always derivable from `(effective_tokens, order_sz, n_orders)`.

### 2. PricingGrid as the single grid object

`PricingGrid` is constructed once in `WsState._startup()` from `start_px` and `n_orders` and passed to the quoting engine each tick. The standalone `generate_ask_levels` / `generate_bid_levels` functions are removed.

The quoting engine's interface becomes:

```python
def compute_desired_orders(
    grid: PricingGrid,
    effective_token: float,
    effective_usdc: float,
    order_sz: float,
    min_notional: float = 0.0,
) -> list[DesiredOrder]
```

**Why remove QuoteResult**: The current `QuoteResult` wrapper returns `mid_price`, `effective_order_sz`, and `effective_n_orders` — all artifacts of the floating-mid approach. With a fixed grid, `mid_price` is not computed (there's no mid; the cursor is a level index), and `effective_order_sz` / `effective_n_orders` adjustments for min_notional no longer apply (see decision 5). A plain `list[DesiredOrder]` is sufficient.

### 3. n_orders semantics: total levels (not per-side)

HIP-2's `nOrders` is the total number of price levels in the grid. Our current `n_orders` means "per side." This changes to match HIP-2: `n_orders = 100` means 100 total levels, split between bids and asks by the cursor.

**Migration**: Config files need updating. If a user previously set `n_orders = 5` (meaning 5 per side = 10 total), they now set `n_orders = 10`.

### 4. Level index semantics: absolute grid position

Level indices become absolute positions on the fixed grid: `0` = lowest price (`start_px`), `n_orders - 1` = highest price. Both bids and asks share the same index space.

The `DesiredOrder.level_index` field now means: "this order belongs at grid level `i`." The order differ matches on `(side, level_index)` as before — the matching logic is unchanged, but the indices are now stable across ticks.

**Impact on WsState._price_to_level_index**: This startup heuristic (log-based relative index calculation) is replaced by `grid.level_for_price(px)` — a direct lookup against the fixed grid.

### 5. min_notional handling

With a fixed grid starting at `start_px`, the lowest-priced levels are at the bottom. If `order_sz * start_px < min_notional`, those bottom levels would violate the exchange's minimum notional constraint.

New approach: filter out any order where `price * size < min_notional`. This handles both partial orders (which may be small) and low-price levels naturally. No need for the current `effective_order_sz` / `effective_n_orders` adjustment.

### 6. Rounding: 5 significant figures

The `_default_round` function already rounds to 5 significant figures. The `PricingGrid` spec claims 8sf but the implementation uses 5sf via `_default_round`. The spec is simply corrected to match both the implementation and observed HIP-2 behavior.

### 7. WsState wiring changes

- Constructor accepts `start_px: float`
- `_startup()` constructs `self.grid = PricingGrid(start_px, n_orders)`
- `_tick()` calls `compute_desired_orders(self.grid, inv.effective_token, inv.effective_usdc, self.order_sz)`
- `_price_to_level_index()` replaced by `self.grid.level_for_price(px)` — returns absolute grid index or `None` (orders outside the grid are ignored during startup seeding)
- `_last_mid` is removed (no floating mid)

## Risks / Trade-offs

**[Risk: Edge state — all tokens or all USDC]** When effective_tokens is 0 or very small, all levels become bids (or empty). When USDC is 0, all levels become asks with no bids. This is correct HIP-2 behavior (the market is fully one-sided at grid extremes) but may look alarming in logs.
→ Mitigation: Log a warning when cursor hits 0 or n_orders. This is informational, not an error.

**[Risk: start_px misconfiguration]** If start_px is set too far from the current market price, the grid may be entirely one-sided (all bids or all asks) with no orders near the current price.
→ Mitigation: At startup, log the grid range (`start_px` to `start_px * 1.003^(n_orders-1)`) and warn if current balances imply a cursor at either extreme.

**[Risk: n_orders semantic change breaks existing configs]** Users who configured n_orders=5 (meaning 5 per side) now get 5 total levels.
→ Mitigation: Document the change. Validate that n_orders >= 2 (need at least 1 bid + 1 ask for a meaningful market).

**[Trade-off: No mid_price for logging]** The current pipeline logs `mid_price` each tick. With the fixed grid, there's no mid. The cursor level's price serves a similar purpose.
→ Use `grid.price_at_level(cursor)` as the "reference price" in logs.

**[Trade-off: Grid can't be changed without restart]** The PricingGrid is immutable and built once. Changing `start_px` or `n_orders` requires a restart.
→ This matches HIP-2 (deployment parameters are fixed at token genesis). Acceptable for our use case.
