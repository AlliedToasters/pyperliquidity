## Why

There is no entrypoint to actually run the market maker. All domain modules (pricing_grid, inventory, order_state, quoting_engine, order_differ, batch_emitter, ws_state, rate_limit) are implemented, but nothing parses a config file, constructs the SDK objects, wires them into `WsState`, and calls `run()`. The `pyproject.toml` already declares a `pyperliquidity` console script pointing at `pyperliquidity.cli:main`, but `cli.py` is empty.

## What Changes

- Implement `cli.py` with a `main()` function that:
  - Parses `config.toml` via `tomllib` (stdlib in Python 3.11+)
  - Reads private key from `PYPERLIQUIDITY_PRIVATE_KEY` env var (never from config)
  - Reads wallet address from `PYPERLIQUIDITY_WALLET` env var
  - Validates all required config fields and env vars on startup
  - Constructs Hyperliquid SDK `Info` and `Exchange` objects (with testnet flag)
  - Constructs `WsState` with config params and SDK objects
  - Calls `asyncio.run(ws_state.run())`
- CLI interface: `pyperliquidity run --config config.toml` via argparse with one subcommand
- Logs full config (minus private key) at startup for debuggability

## Capabilities

### New Capabilities
- `cli`: CLI entrypoint that parses config, validates inputs, constructs SDK objects, wires WsState, and starts the market maker

### Modified Capabilities

_(none — WsState already handles all internal module construction and orchestration)_

## Impact

- **New file**: `src/pyperliquidity/cli.py` (currently empty, entrypoint already wired in pyproject.toml)
- **Dependencies**: Uses `hyperliquid-python-sdk` (already in project deps) for `Info`/`Exchange` objects
- **Config format**: Introduces a `config.toml` schema that users must provide
- **Environment**: Requires `PYPERLIQUIDITY_PRIVATE_KEY` and `PYPERLIQUIDITY_WALLET` env vars at runtime
