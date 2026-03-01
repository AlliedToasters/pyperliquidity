# CLI

## Purpose

CLI entrypoint that parses config, validates inputs, constructs SDK objects, wires WsState, and starts the market maker.

## Requirements

### Requirement: CLI parses config file and environment variables

The `main()` function SHALL use `argparse` to provide a `run` subcommand with a `--config` argument pointing to a TOML config file. The config file SHALL be parsed with `tomllib`. The private key SHALL be read from `PYPERLIQUIDITY_PRIVATE_KEY` and the wallet address from `PYPERLIQUIDITY_WALLET` environment variables. Secrets SHALL never be read from the config file.

#### Scenario: Successful config parsing
- **WHEN** `pyperliquidity run --config config.toml` is invoked with a valid config file and both env vars set
- **THEN** the config is parsed, env vars are loaded, and the market maker starts

#### Scenario: Missing config file
- **WHEN** the specified config file does not exist
- **THEN** the process exits with a clear error message indicating the file was not found

#### Scenario: Missing private key env var
- **WHEN** `PYPERLIQUIDITY_PRIVATE_KEY` is not set or empty
- **THEN** the process exits with a clear error message before any SDK construction

#### Scenario: Missing wallet env var
- **WHEN** `PYPERLIQUIDITY_WALLET` is not set or empty
- **THEN** the process exits with a clear error message before any SDK construction

### Requirement: CLI validates config values on startup

The CLI SHALL validate that all required config fields are present and have valid values before constructing any modules. Specifically:
- `market.coin` MUST be a non-empty string
- `strategy.start_px` MUST be positive
- `strategy.n_orders` MUST be a positive integer
- `strategy.order_sz` MUST be positive
- `allocation.allocated_token` MUST be positive
- `allocation.allocated_usdc` MUST be positive

Optional tuning parameters SHALL use defaults matching WsState's constructor defaults if omitted.

#### Scenario: Invalid start_px
- **WHEN** config contains `start_px = 0` or a negative value
- **THEN** the process exits with an error message identifying the invalid field

#### Scenario: Missing required field
- **WHEN** a required field (e.g., `market.coin`) is absent from config
- **THEN** the process exits with an error message identifying the missing field

#### Scenario: Optional tuning params omitted
- **WHEN** the `[tuning]` section is omitted or partially filled
- **THEN** defaults are used: `interval_s=3.0`, `dead_zone_bps=5.0`, `price_tolerance_bps=1.0`, `size_tolerance_pct=1.0`, `reconcile_every=20`, `min_notional=0.0`

### Requirement: CLI constructs SDK objects and WsState

The CLI SHALL construct Hyperliquid SDK `Info` and `Exchange` objects using the wallet/private key and the appropriate base URL (testnet or mainnet based on `market.testnet`). It SHALL then construct a `WsState` instance with config params and SDK objects, and run it via `asyncio.run(ws_state.run())`.

#### Scenario: Testnet mode
- **WHEN** config contains `testnet = true`
- **THEN** SDK objects are constructed with the testnet base URL

#### Scenario: Mainnet mode (default)
- **WHEN** config omits `testnet` or sets it to `false`
- **THEN** SDK objects are constructed with the mainnet (default) base URL

### Requirement: CLI logs resolved config at startup

The CLI SHALL log the full resolved configuration at INFO level on startup. The private key MUST be masked or omitted from the log output. The wallet address, coin, all strategy/allocation/tuning params, and testnet flag SHALL be visible in the log.

#### Scenario: Config logged at startup
- **WHEN** the market maker starts successfully
- **THEN** the full config (with private key masked) is logged at INFO level before the tick loop begins
