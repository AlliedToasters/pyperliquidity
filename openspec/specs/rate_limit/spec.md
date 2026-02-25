# Rate Limit

## Purpose

Track the Hyperliquid rate-limit budget model and expose budget queries for the batch emitter. Provide monitoring metrics.

## Budget Model

```
budget = 10_000 + cumulative_volume_usd - cumulative_requests
```

- Each API mutation (place, modify, cancel) costs 1 from budget — batch ops cost 1 total
- Each $1 of maker fill volume earns 1 back
- At budget ≤ 0: throttled to 1 request per 10 seconds

## State

- `cum_vlm: float` — Cumulative fill volume in USD
- `n_requests: int` — Cumulative API requests made
- `budget: int` — Computed: `10_000 + cum_vlm - n_requests`
- `ratio: float` — Computed: `cum_vlm / max(n_requests, 1)`

## Operations

- `on_request(n=1)`: Increment n_requests (called by batch_emitter after each API call)
- `on_fill(volume_usd)`: Increment cum_vlm
- `sync_from_exchange(rate_limit_response)`: Reset from REST `user_rate_limit()` data
- `remaining() -> int`: Current budget
- `is_healthy() -> bool`: `ratio >= 1.0`
- `is_emergency() -> bool`: `budget < SAFETY_MARGIN`

## Monitoring

Log every ~60s:
```
Utilization: ratio=1.12 budget=70985 vol=$583479 reqs=522489
```

Alert conditions:
- `ratio < 1.0` — Spending faster than earning. Widen dead zones or reduce levels.
- `budget < 500` — Approaching throttle. Emergency mode.
- `budget < 100` — Near-throttle. Cancel-only mode.

## Invariants

1. Budget is never negative in our tracking (exchange may already be throttling)
2. Batch operations (regardless of batch size) increment n_requests by 1
3. Ratio is a long-term health metric — short-term dips are normal
4. Exchange sync overrides local tracking (source of truth is the exchange)

## Dependencies

- None for core tracking
- Seeded by `ws_state` at startup via REST
- Updated by `batch_emitter` (requests) and `order_state` (fill volumes)
