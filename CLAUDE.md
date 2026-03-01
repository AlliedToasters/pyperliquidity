# CLAUDE.md — pyperliquidity

## Project Overview

pyperliquidity is a Python implementation of Hyperliquid's HIP-2 "Hyperliquidity" on-chain market-making algorithm, reimplemented as an off-chain market maker for spot markets where HIP-2 cannot be deployed natively (e.g., bridged assets without genesis token allocations).

**Core concept**: Uniswap V2 / infinite-range liquidity pools, but on a central-limit order book. Pricing emerges from inventory position on a geometric price grid — no oracle needed.

## Spec-Driven Development

This project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for spec-driven development. Before implementing any feature:

1. Read the relevant spec in `openspec/specs/<domain>/spec.md`
2. If no spec exists, create a change proposal first: create a folder under `openspec/changes/<change-name>/` with `proposal.md`, `design.md`, `tasks.md`, and delta specs
3. Implement against the spec, not vibes
4. When done, archive the change (merge delta specs into main specs)

Always open `openspec/AGENTS.md` when a request mentions planning, proposals, specs, or architecture.

## Architecture

```
WebSocket Feeds ──► StateManager ──► QuotingEngine ──► OrderDiffer ──► BatchEmitter ──► API
     ▲                (single source      (pure math,     (dead zone +     (budget-aware,   │
     │                 of truth)           no I/O)         level-index      prioritized)     │
     └──────────── orderUpdates / userFills / webData2 ──────────────────────────────────────┘
```

**Key principle**: Separate computation from I/O completely. The quoting engine is pure math. The differ decides what changed. The emitter decides whether to actually send based on budget.

## Domain Decomposition

| Domain | Path | Responsibility |
|--------|------|----------------|
| `pricing_grid` | `src/pyperliquidity/pricing_grid.py` | Geometric price ladder generation and level lookup |
| `inventory` | `src/pyperliquidity/inventory.py` | Token + USDC balance tracking, tranche math |
| `order_state` | `src/pyperliquidity/order_state.py` | Order lifecycle, OID tracking, ghost detection |
| `quoting_engine` | `src/pyperliquidity/quoting_engine.py` | Pure function: inventory + grid → desired orders |
| `order_differ` | `src/pyperliquidity/order_differ.py` | Dead zone, level-index matching, tolerance filter |
| `batch_emitter` | `src/pyperliquidity/batch_emitter.py` | Budget-aware, prioritized API call emission |
| `ws_state` | `src/pyperliquidity/ws_state.py` | WebSocket subscriptions, state reconciliation |
| `rate_limit` | `src/pyperliquidity/rate_limit.py` | Budget model tracking and conservation |

## Hyperliquid API Critical Knowledge

### Rate Limit Budget Model
```
budget = 10_000 + cumulative_volume_usd - cumulative_requests
```
- Every API mutation costs 1 from budget (place, modify, cancel)
- Every $1 of filled volume earns 1 back
- At budget=0, throttled to 1 request per 10 seconds
- Batch operations (bulk_modify, bulk_orders, bulk_cancel) cost 1 regardless of batch size
- Long-term utilization ratio (volume/requests) must stay >= 1.0

### Order Management Gotchas
- **OID swaps**: `bulk_modify` may assign new OIDs. Always check response statuses and update tracking.
- **Cross-side modify forbidden**: Cannot modify a buy order into a sell or vice versa. Hyperliquid rejects these.
- **ALO rejections are normal**: Add-Liquidity-Only orders that would cross the spread are rejected, not filled. Don't retry — wait for next tick.
- **Ghost orders**: "Cannot modify" errors mean the order was already filled. Remove from state immediately.
- **orderUpdates format**: `status` is at the TOP LEVEL of the update, NOT inside `update["order"]`.
- **Fill deduplication**: On WS reconnect, fills may replay. Deduplicate by `tid`.
- **Spot asset IDs**: `asset_id = spot_index + 10000`. Fetch from `spot_meta()["universe"]`, don't hardcode.

### WebSocket-First Architecture
Subscribe to: `allMids`, `l2Book`, `orderUpdates`, `userFills`, `webData2`.
Only REST calls: startup metadata, `spot_user_state()` for balances (no WS feed), periodic `open_orders()` for reconciliation (~60s).

### ALO (Add Liquidity Only)
All resting orders use `{"limit": {"tif": "Alo"}}`. This ensures maker-only fills which replenish the rate limit budget.

## HIP-2 Algorithm Summary

Hyperliquidity is parametrized by: `startPx`, `nOrders`, `orderSz`, `nSeededLevels`.

**Price grid**: `px_0 = startPx`, `px_i = round(px_{i-1} * 1.003)` — geometric, 0.3% spacing.

**Update logic** (every tick where ≥3s since last update):
1. Compute `nFull = floor(token_balance / orderSz)` full ask orders
2. Place a `token_balance % orderSz` partial ask if remainder > 0
3. Each fully filled tranche flips to an order on the opposite side with available balance

The price is NOT computed from an AMM formula — it emerges from where the inventory sits on the grid. Filled asks become bids at the same grid level; filled bids become asks.

## Code Standards

- Python 3.11+
- Type hints on all public functions
- Dataclasses or Pydantic for state objects
- No I/O in pure computation modules (quoting_engine, order_differ, pricing_grid)
- async/await for all I/O paths
- The Hyperliquid Python SDK uses sync daemon threads for WS callbacks — bridge with `asyncio.run_coroutine_threadsafe()`
- Tests for all pure-math modules (pytest)
- Use `Decimal` or careful float handling for prices — grid levels must be deterministic

## Commands

```bash
# Local venv (already set up at .venv/)
.venv/bin/pytest            # Run tests
.venv/bin/ruff check src/ tests/  # Lint
.venv/bin/mypy src/         # Type check

# Rebuild venv from scratch
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Run the market maker (eventual CLI)
.venv/bin/pyperliquidity run --config config.toml
```

## Key References

- HIP-2 spec: https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-2-hyperliquidity
- Hyperliquid Python SDK: https://github.com/hyperliquid-dex/hyperliquid-python-sdk
- MM guide: see `docs/hyperliquid-mm-guide.md` in this repo
