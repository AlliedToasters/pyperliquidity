## Context

All pure-computation modules (pricing_grid, inventory, quoting_engine, order_differ) and I/O modules (batch_emitter, rate_limit, order_state) are implemented and tested. The ws_state module is the final piece — the orchestrator that wires everything into a running market maker.

The Hyperliquid Python SDK uses synchronous daemon threads for WebSocket callbacks. The market maker's state modules are not thread-safe, so all state mutations must be serialized through the async event loop.

## Goals / Non-Goals

**Goals:**
- Implement the full ws_state orchestrator per the existing spec
- Startup sequence that seeds all modules from REST data
- WebSocket subscription and callback routing through async bridge
- Tick loop (configurable interval, default 3s) that runs the full quoting pipeline
- Periodic REST reconciliation (~60s) for orphan/ghost detection and balance drift
- WS reconnection with immediate full reconciliation
- Testable with mocked SDK objects

**Non-Goals:**
- CLI integration (handled separately in cli.py)
- Configuration parsing (config will be passed in)
- Graceful shutdown / signal handling (future work)
- Multiple coin support (single coin per instance)
- Logging framework (use stdlib `logging`)

## Decisions

### D1: Single class `WsState` as the orchestrator

The module exposes a single `WsState` class that owns all sub-module instances and the event loop. Constructor takes config params and SDK objects (`info`, `exchange`). A single `async run()` method executes the full lifecycle (startup → subscribe → tick loop).

**Rationale**: Keeps the orchestrator as thin glue. All logic lives in the sub-modules. The class is just wiring and scheduling.

**Alternative**: Functional approach with module-level coroutines. Rejected because the shared state (sub-module instances, loop reference, config) is easier to manage as instance state.

### D2: Thread-to-async bridge via `asyncio.run_coroutine_threadsafe`

WS callbacks are sync functions called from SDK daemon threads. Each callback schedules an async handler on the main event loop using `asyncio.run_coroutine_threadsafe()`. The async handlers then call into the sub-modules.

**Rationale**: This is the standard asyncio pattern for bridging sync callbacks. It serializes all state mutations onto the event loop thread, avoiding locks.

**Alternative**: Using locks/queues. Rejected — adds complexity and doesn't integrate with the async tick loop.

### D3: Tick loop as an `asyncio.Task` with `asyncio.sleep`

The tick loop runs as a long-lived asyncio task. Each iteration: compute desired orders → diff → emit → sleep for `interval_s`. Reconciliation runs on a separate timer counter (every N ticks).

**Rationale**: Simple, no external scheduler needed. `asyncio.sleep` is cancellable for clean shutdown.

### D4: Reconciliation counter, not separate timer

Track tick count and run reconciliation every `reconcile_every` ticks (default 20, i.e. ~60s at 3s interval). This avoids two competing timers.

**Rationale**: Simpler than a separate `asyncio.Task` for reconciliation. Guarantees reconciliation doesn't overlap with a tick.

### D5: `boundary_level` computed from order_state

The quoting engine needs a `boundary_level` — the grid level where asks end and bids begin. This is derived from the current order state: the lowest ask level (or `n_orders` if no asks exist). On startup, it's computed from the seeded orders.

**Rationale**: The boundary is an emergent property of inventory position on the grid, not a config parameter.

## Risks / Trade-offs

- **SDK WS reconnection behavior is opaque** → Wrap subscription in try/except, implement our own reconnect-and-resubscribe logic. If the SDK doesn't expose disconnect events, use a heartbeat timeout.
- **Startup REST calls may fail** → Let exceptions propagate. The caller (CLI) is responsible for retry/backoff at the process level.
- **Tick loop may fall behind if emit takes too long** → The emit call is already budget-constrained. Log a warning if tick duration exceeds `interval_s` but don't skip ticks — just proceed immediately.
- **Fill events during startup** → Subscribe to WS feeds before the first tick, but after seeding state. Any fills that arrive between REST seed and first tick are handled normally by order_state.
