## Why

Our quoting engine diverges fundamentally from real HIP-2 behavior. Reverse engineering of live testnet/mainnet HIP-2 markets (documented in `docs/hip2-reverse-engineering.md`) reveals that HIP-2 uses a **fixed price grid anchored at `startPx`** with a **boundary cursor** that shifts as fills occur. Our implementation instead regenerates the grid each tick centered on a floating `mid = usdc / tokens` — this produces different quoting behavior, different spread characteristics, and different price impact profiles than real HIP-2.

Since the project's highest-level goal is to replicate HIP-2 as closely as possible, the core pricing and quoting model must be corrected to match observed behavior.

## What Changes

- **BREAKING** — `quoting_engine` switches from floating-mid symmetric placement to fixed-grid boundary cursor model. Asks are placed ascending from the cursor; bids descending. Filled levels flip sides. Exactly one partial level exists at the cursor.
- **BREAKING** — `pricing_grid` rounding changes from 8 significant figures to 5 significant figures, matching observed HIP-2 ladder prices.
- **BREAKING** — `startPx` becomes a required configuration parameter (static grid anchor). The grid is generated once at startup and never regenerated.
- `cli` and `ws_state` updated to pass `startPx` and `PricingGrid` through the pipeline.
- `order_differ` level-index semantics change: level indices are now absolute positions on the fixed grid (not relative to a per-tick generated grid).

## Capabilities

### New Capabilities

_(none — all changes modify existing capabilities)_

### Modified Capabilities

- `pricing_grid`: Rounding changes to 5 significant figures. Grid becomes a long-lived object generated once from `startPx` + `n_orders`, not regenerated per tick. The `PricingGrid` class is now used directly in the quoting pipeline (currently unused).
- `quoting_engine`: Complete interface and algorithm change. Accepts `PricingGrid` + effective balances from inventory, computes boundary cursor as a derived value (`n_full_asks = floor(effective_tokens / order_sz)`), places asks ascending from cursor and bids descending. Partial level at cursor. No more floating mid derivation. The cursor is computed every tick, not stored — inventory balances are the single source of truth.
- `cli`: Adds `start_px` as a required configuration parameter.
- `ws_state`: Passes `PricingGrid` instance through the pipeline; grid is constructed once at startup from config.
- `order_differ`: Level indices become absolute grid positions (0 to n_orders-1) rather than relative per-tick indices. Dead zone and tolerance logic unchanged.

## Impact

- **Core pipeline**: `PricingGrid` → `QuotingEngine` → `OrderDiffer` data flow changes. Grid is constructed once, quoting engine receives it as input.
- **Configuration**: New required `start_px` field in config. Existing deployments must add this.
- **State management**: Cursor is derived each tick from inventory effective balances + grid — no new stored state. `ws_state` constructs the `PricingGrid` once at startup from config.
- **Tests**: All quoting engine tests need rewriting. Pricing grid tests need 5sf rounding updates. Inventory tests unchanged.
- **No API changes**: Rate limit, batch emitter, and order state modules are unaffected — they operate on `DesiredOrder` objects regardless of how they're computed.
