## 1. Config Parsing & Validation

- [x] 1.1 Implement `_load_config(path)` — read TOML file with `tomllib`, return parsed dict. Exit with clear error if file missing or malformed.
- [x] 1.2 Implement `_load_env()` — read `PYPERLIQUIDITY_PRIVATE_KEY` and `PYPERLIQUIDITY_WALLET` from env. Exit with clear error if missing or empty.
- [x] 1.3 Implement `_validate_config(config)` — check required fields (`market.coin`, `strategy.start_px`, `strategy.n_orders`, `strategy.order_sz`, `allocation.allocated_token`, `allocation.allocated_usdc`) are present and valid (positive numerics, non-empty strings). Apply defaults for optional `[tuning]` params.

## 2. SDK & WsState Construction

- [x] 2.1 Implement `_build_ws_state(config, private_key, wallet)` — construct SDK `Info` and `Exchange` objects (testnet-aware base URL), then construct and return a `WsState` with all config params and SDK objects.

## 3. CLI Entrypoint

- [x] 3.1 Implement `main()` — argparse with `run` subcommand and `--config` argument. Wire together load → validate → log config → build → `asyncio.run()`.
- [x] 3.2 Add startup logging — log resolved config at INFO level with private key masked.

## 4. Testing

- [x] 4.1 Write tests for config validation (missing fields, invalid values, defaults applied).
- [x] 4.2 Write tests for env var loading (missing, empty).
- [x] 4.3 Run full test suite, lint, and type check to verify no regressions.
