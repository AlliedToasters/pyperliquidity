# pyperliquidity

[![PyPI version](https://img.shields.io/pypi/v/pyperliquidity.svg)](https://pypi.org/project/pyperliquidity/)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/pyperliquidity.svg)](https://pypi.org/project/pyperliquidity/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Python implementation of [HIP-2 "Hyperliquidity"](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-2-hyperliquidity) market-making algorithm. While HIP-2's logic runs fully on-chain, certain spot markets (especially bridged assets) are unable to use this feature. pyperliquidity recovers HIP-2 behavior using an off-chain market maker.

**Core concept**: Uniswap V2 / infinite-range liquidity pools, but on an order book.

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

## Quick Start

1. **Create a config file** — copy and edit the example:

```bash
cp config.example.toml config.toml
```

Key parameters in `config.toml`:

```toml
[strategy]
coin = "@1434"          # Spot pair symbol
start_px = 0.01         # Initial price (bottom of the grid)
n_orders = 100          # Number of price levels
order_sz = 1000.0       # Tokens per tranche

[allocation]
allocated_token = 1000.0
allocated_usdc = 500.0
```

2. **Set environment variables** for your Hyperliquid wallet:

```bash
export PYPERLIQUIDITY_PRIVATE_KEY="0x..."
export PYPERLIQUIDITY_WALLET="0x..."
```

3. **Run the market maker**:

```bash
pyperliquidity run --config config.toml
```

See [`config.example.toml`](config.example.toml) for all available parameters including tuning, rate limit, and reconciliation settings.

## Architecture

```
WebSocket Feeds ──► StateManager ──► QuotingEngine ──► OrderDiffer ──► BatchEmitter ──► API
     ▲                (single source      (pure math,     (dead zone +     (budget-aware,   │
     │                 of truth)           no I/O)         level-index      prioritized)     │
     └──────────── orderUpdates / userFills / webData2 ──────────────────────────────────────┘
```

- **QuotingEngine** — pure math, no I/O. Translates inventory position on a geometric price grid into desired orders.
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
