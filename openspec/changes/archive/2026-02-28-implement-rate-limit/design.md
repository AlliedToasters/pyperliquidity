## Context

The market maker sends order mutations (place, modify, cancel) to the Hyperliquid API. The exchange tracks a per-user rate-limit budget:

```
budget = 10_000 + cumulative_volume_usd - cumulative_requests
```

At budget ≤ 0, the user is throttled to 1 request per 10 seconds — effectively killing market-making. The `batch_emitter` needs real-time budget visibility to throttle proactively.

Currently `rate_limit.py` is an empty stub. No budget tracking exists.

## Goals / Non-Goals

**Goals:**
- Track budget locally using `on_request()` / `on_fill()` increments
- Sync from exchange via REST `user_rate_limit()` to correct drift
- Expose query methods (`remaining()`, `is_healthy()`, `is_emergency()`) for batch emitter
- Log utilization metrics periodically
- Pure state module — no I/O, no async

**Non-Goals:**
- Automatic throttling logic (that's `batch_emitter`'s job)
- Persisting budget across restarts (exchange is source of truth)
- WebSocket-based budget updates (no such feed exists)

## Decisions

### 1. Single dataclass, no async

`RateLimitBudget` is a plain dataclass with mutation and query methods. It holds `cum_vlm`, `n_requests`, and derives `budget` / `ratio` on the fly. No locks needed — the event loop is single-threaded.

**Alternative**: Make it an async context manager. Rejected — unnecessary complexity for a pure state tracker.

### 2. Computed properties for budget and ratio

`budget` and `ratio` are `@property` computed from `cum_vlm` and `n_requests` rather than stored. This eliminates stale-state bugs.

**Alternative**: Store and update on every mutation. Rejected — two extra fields to keep in sync for no performance benefit.

### 3. Safety margin constants as class-level defaults

`SAFETY_MARGIN = 500` and `CRITICAL_MARGIN = 100` are class attributes with constructor override. This keeps the common case simple while allowing tests and config to customize.

### 4. Exchange sync overwrites local state

`sync_from_exchange()` replaces `cum_vlm` and `n_requests` with exchange-reported values. The exchange is the source of truth — local tracking drifts over time due to fill timing and reconnects.

### 5. Logging via callback

The module accepts an optional logger. Periodic logging (~60s) is the caller's responsibility (e.g., a timer in the main loop calls a `log_status()` method). The module itself has no timers or I/O.

## Risks / Trade-offs

- **Local tracking drift** → Mitigated by periodic `sync_from_exchange()` calls (~60s via REST)
- **Budget goes negative between syncs** → We clamp `remaining()` to 0 minimum; real throttling happens exchange-side regardless
- **Batch size ambiguity** → Spec says batch ops cost 1 regardless of size. `on_request(n=1)` default handles this; caller passes n=1 for batches.
