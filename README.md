# pyperliquidity

A Python implementation of [HIP-2 "Hyperliquidity"](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-2-hyperliquidity) market-making algorithm. While HIP-2's logic runs fully on-chain, certain spot markets (especially bridged assets) are unable to use this feature. pyperliquidity recovers HIP-2 behavior using an off-chain market maker.

**Core concept**: Uniswap V2 / infinite-range liquidity pools, but on an order book.

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
pyperliquidity run --config config.toml
```

## Architecture

```
WebSocket Feeds ──► StateManager ──► QuotingEngine ──► OrderDiffer ──► BatchEmitter ──► API
     ▲                (single source      (pure math,     (dead zone +     (budget-aware,   │
     │                 of truth)           no I/O)         level-index      prioritized)     │
     └──────────── orderUpdates / userFills / webData2 ──────────────────────────────────────┘
```

## Configuration

See `config.example.toml` for all available parameters.

## Development

This project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for spec-driven development. Domain specs live in `openspec/specs/`. Read them before implementing.

```bash
pytest                # Run tests
mypy src/             # Type check
ruff check src/       # Lint
```

## License

MIT
