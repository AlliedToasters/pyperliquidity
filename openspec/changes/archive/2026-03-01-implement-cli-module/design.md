## Context

All domain modules are implemented and tested. `WsState` serves as the orchestrator — it constructs `PricingGrid`, `Inventory`, `OrderState`, `RateLimitBudget`, and `BatchEmitter` internally during its startup sequence. The missing piece is a CLI entrypoint that:

1. Reads a TOML config file
2. Loads secrets from environment variables
3. Constructs the Hyperliquid SDK objects (`Info`, `Exchange`)
4. Constructs `WsState` with config params and SDK objects
5. Runs the async event loop

The `pyproject.toml` already declares `pyperliquidity = "pyperliquidity.cli:main"` as a console script. The `cli.py` file exists but is empty.

## Goals / Non-Goals

**Goals:**
- Provide a working `pyperliquidity run --config config.toml` command
- Validate config and env vars with clear error messages before starting
- Log the resolved config (minus private key) at startup for debuggability
- Keep the module under ~100 lines — thin glue, no business logic

**Non-Goals:**
- Daemon mode, signal handling, hot reload
- Multiple subcommands (only `run` for now)
- Config file generation or interactive setup
- Any business logic — that all lives in WsState and its dependencies

## Decisions

### 1. Config parsing: `tomllib` (stdlib)

Use `tomllib` from Python 3.11+ stdlib. No external dependency needed. TOML is already the stated config format in CLAUDE.md.

**Alternative considered**: YAML, JSON, env-only config. TOML is already specified and has stdlib support.

### 2. Secrets from env vars only

Private key via `PYPERLIQUIDITY_PRIVATE_KEY`, wallet address via `PYPERLIQUIDITY_WALLET`. Never read secrets from config files.

**Rationale**: Prevents accidental secret commits. Standard practice for production deployments.

### 3. SDK construction in CLI, not WsState

The CLI constructs `Info(base_url, skip_ws=True)` and `Exchange(wallet, base_url)` and passes them to WsState. WsState already accepts `info` and `exchange` as constructor params.

**Rationale**: WsState shouldn't know about private keys or SDK construction. CLI is the I/O boundary for secrets.

### 4. Config schema — flat TOML sections

```toml
[market]
coin = "PURR"        # spot coin name
testnet = false      # use testnet base URL

[strategy]
start_px = 0.10      # initial price (px_0)
n_orders = 10        # number of grid levels
order_sz = 100.0     # tokens per order tranche
n_seeded_levels = 5  # initial seeded levels

[allocation]
allocated_token = 1000.0   # token inventory budget
allocated_usdc = 500.0     # USDC inventory budget

[tuning]
interval_s = 3.0           # tick interval
dead_zone_bps = 5.0        # order differ dead zone
price_tolerance_bps = 1.0  # price tolerance for modify vs cancel/place
size_tolerance_pct = 1.0   # size tolerance
reconcile_every = 20       # ticks between reconciliation
min_notional = 0.0         # minimum order notional
```

**Rationale**: Matches WsState constructor params directly. Flat structure avoids over-nesting.

### 5. Validation: fail fast with `SystemExit`

Validate before any SDK construction:
- Env vars set and non-empty
- Config file exists and parses
- Positive numerics: `allocated_token`, `allocated_usdc`, `n_orders`, `order_sz`, `start_px`

Use `sys.exit(message)` for validation failures — clean error, no traceback.

### 6. Logging: stdlib `logging`

Use Python's `logging` module at INFO level. Log the full resolved config (with private key masked) at startup.

## Risks / Trade-offs

- **[Risk] SDK API changes** → The SDK's `Info` and `Exchange` constructors may change. Mitigation: pin SDK version in deps; the CLI is thin enough to update easily.
- **[Risk] Missing config keys** → If user omits optional keys, `tomllib` won't fill defaults. Mitigation: Use `.get()` with defaults matching WsState's defaults for optional tuning params.
- **[Trade-off] No config validation library** → We do manual validation instead of pydantic/attrs. Keeps deps minimal; the config is small enough that manual checks are clear.
