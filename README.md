# pyperliquidity

[![PyPI version](https://img.shields.io/pypi/v/pyperliquidity.svg)](https://pypi.org/project/pyperliquidity/)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/pyperliquidity.svg)](https://pypi.org/project/pyperliquidity/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Python implementation of [HIP-2 "Hyperliquidity"](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-2-hyperliquidity) market-making algorithm. While HIP-2's logic runs fully on-chain, certain spot markets (especially bridged assets) are unable to use this feature. pyperliquidity recovers HIP-2 behavior using an off-chain market maker.

**Core concept**: Uniswap V2 / infinite-range liquidity pools, but on an order book. Pricing emerges from inventory position on a geometric price grid — no oracle needed.

## Installation

```bash
pip install pyperliquidity
```

For development:

```bash
git clone https://github.com/AlliedToasters/pyperliquidity.git
cd pyperliquidity
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## How It Works

### The Price Grid

The grid is a fixed geometric ladder of price levels, set once at deployment:

```
Level 0:  start_px
Level 1:  start_px * 1.003
Level 2:  start_px * 1.003^2
...
Level N:  start_px * 1.003^N
```

The grid does **not** move. Price discovery comes from where your inventory sits on it.

### The Cursor

The cursor is the boundary between bids and asks, derived from token inventory each tick:

```
total_ask_levels = min(floor(token / order_sz) + (1 if remainder), n_orders)
cursor = n_orders - total_ask_levels
```

- **More tokens** → cursor lower → more asks → lower effective price
- **Fewer tokens** → cursor higher → more bids → higher effective price

As people buy your token (filling asks), the cursor rises and bids appear at lower levels. As people sell (filling bids), the cursor drops and asks appear above. The price is never set explicitly — it emerges from inventory.

### Deployment Styles

| Style | Token allocation | start_px | Behavior |
|-------|-----------------|----------|----------|
| **Full deploy** (HIP-2 genesis) | Fill the whole grid | = current price | All asks initially, bids appear as people buy |
| **Balanced** | Use `target_px` | Below current price | Bids and asks from the start |

## Quick Start

### 1. Set environment variables

These are **required**:

```bash
export PYPERLIQUIDITY_PRIVATE_KEY="0x..."   # Ethereum private key (hex)
export PYPERLIQUIDITY_WALLET="0x..."        # Wallet address
```

### 2. Create a config file

```bash
cp config.example.toml config.toml
```

### 3. Configure your strategy

There are two ways to set your initial position:

**Option A: `target_px` (recommended)** — set where you want the cursor to start. Token and USDC allocations are computed automatically:

```toml
[market]
coin = "@1434"            # Spot pair (find via Hyperliquid spotMeta API)
testnet = true            # Use testnet API

[strategy]
n_orders = 1656           # Total grid levels ($350-$50k at 0.3% spacing)
order_sz = 0.0286         # Tokens per level (must clear $10 min at start_px)
start_px = 350.0          # Bottom of grid — fixed forever
active_levels = 20        # Only 20 bids + 20 asks on the book at a time
target_px = 557.0         # Start cursor here (auto-computes allocations)

[tuning]
interval_s = 0.5          # Tick every 500ms (safe with dead zone)
# dead_zone_bps = 5.0     # Skip requote if mid drifted less than this (default)
# price_tolerance_bps = 1.0  # Skip modify if price moved less than this (default)
# size_tolerance_pct = 1.0   # Skip modify if size changed less than this (default)
# reconcile_every = 20    # REST reconciliation interval (default)
```

When using `target_px`, the `[allocation]` section is not needed. The target level is computed as:

```
target_level = ln(target_px / start_px) / ln(1.003)
```

**Option B: Manual allocation** — calculate `allocated_token` and `allocated_usdc` yourself:

```toml
[strategy]
n_orders = 100
order_sz = 1000.0
start_px = 0.01

[allocation]
allocated_token = 1000.0
allocated_usdc = 500.0
```

### 4. Run

```bash
pyperliquidity run --config config.toml
```

## Key Concepts

### `active_levels` — Essential for Wide Grids

Without `active_levels`, orders are placed on **every** grid level. For a wide grid (e.g., 1,656 levels covering $350-$50k), that's far too many resting orders.

With `active_levels = 20`, only 20 bids + 20 asks nearest the cursor are placed on the exchange. The window slides automatically as fills move the cursor.

### Sizing Considerations

Hyperliquid enforces a **$10 minimum order** notional. This constrains `order_sz` at the bottom of the grid:

```
order_sz * start_px >= $10
```

For wide grids starting at a low price, `order_sz = $10 / start_px` is the minimum viable size. Orders below the minimum notional are automatically filtered out.

### Rate Limit Budget

Hyperliquid uses a budget model:

```
budget = 10,000 + cumulative_volume_usd - cumulative_requests
```

- Every API mutation (place, modify, cancel) costs 1 from budget
- Every $1 of filled volume earns 1 back
- Batch operations (bulk_modify, bulk_cancel) cost 1 regardless of batch size
- At budget=0, throttled to 1 request per 10 seconds

The dead zone and tolerance filters prevent unnecessary API calls. A faster `interval_s` is safe because updates are only sent when orders actually need to change. `active_levels` keeps the resting order count manageable.

All resting orders use ALO (Add Liquidity Only) to ensure maker-only fills, which replenish the budget.

## Architecture

```
WebSocket Feeds ──► StateManager ──► QuotingEngine ──► OrderDiffer ──► BatchEmitter ──► API
     ^                (single source      (pure math,     (dead zone +     (budget-aware,   |
     |                 of truth)           no I/O)         level-index      prioritized)     |
     └──────────── orderUpdates / userFills / webData2 ──────────────────────────────────────┘
```

- **QuotingEngine** — pure math, no I/O. Translates inventory position on the grid into desired orders.
- **OrderDiffer** — dead-zone filtering and tolerance checks to minimize unnecessary API calls.
- **BatchEmitter** — budget-aware, prioritized order emission that respects Hyperliquid's rate limit model.
- **WsState** — WebSocket-first state management with periodic REST reconciliation.

## Development

This project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for spec-driven development. Domain specs live in `openspec/specs/`.

```bash
.venv/bin/pytest              # Run tests
.venv/bin/mypy src/           # Type check
.venv/bin/ruff check src/     # Lint
```

## License

MIT
