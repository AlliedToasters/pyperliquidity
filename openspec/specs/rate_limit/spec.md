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
- `SAFETY_MARGIN: int = 500` — Threshold for emergency detection
- `CRITICAL_MARGIN: int = 100` — Near-throttle threshold

### Budget Computation

The `budget` property SHALL compute `10_000 + cum_vlm - n_requests`. The `remaining()` method SHALL return `max(0, budget)`.

- **Fresh instance**: `remaining()` returns `10_000`
- **After requests**: `on_request()` called 5 times → `remaining()` returns `9_995`
- **After fills**: `on_fill(100.0)` → `remaining()` increases by `100`
- **Floor**: when `n_requests` exceeds `10_000 + cum_vlm`, `remaining()` returns `0`

### Utilization Ratio

The `ratio` property SHALL compute `cum_vlm / max(n_requests, 1)`.

- **No requests**: ratio returns `0.0`
- **Healthy**: `cum_vlm=1000, n_requests=800` → ratio `1.25`

## Operations

### Request Tracking

`on_request(n=1)` SHALL increment `n_requests` by `n`. Default increment is 1 (one API call or batch operation of any size).

### Fill Volume Tracking

`on_fill(volume_usd)` SHALL increment `cum_vlm` by the given USD amount. Multiple fills accumulate.

### Exchange Sync

`sync_from_exchange(cum_vlm, n_requests)` SHALL overwrite local `cum_vlm` and `n_requests` with exchange-reported values. The exchange is the authoritative source of truth.

### Health Check

`is_healthy()` SHALL return `True` when `ratio >= 1.0`.

- **Healthy**: `cum_vlm=1000, n_requests=800` → `True`
- **Unhealthy**: `cum_vlm=500, n_requests=800` → `False`

### Emergency Detection

`is_emergency()` SHALL return `True` when `remaining() < SAFETY_MARGIN` (default 500).

- **Normal**: `remaining()=5000` → `False`
- **Emergency**: `remaining()=300` → `True`

### Status Logging

`log_status()` SHALL return a formatted string containing `ratio=`, `budget=`, `vol=`, and `reqs=` with current metrics.

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
