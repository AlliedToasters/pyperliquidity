## ADDED Requirements

### Requirement: Budget computation
The `RateLimitBudget` class SHALL compute the current budget as `10_000 + cum_vlm - n_requests`. The budget SHALL be exposed via a `remaining()` method that returns `max(0, budget)`.

#### Scenario: Fresh instance has full budget
- **WHEN** a new `RateLimitBudget` is created with default state
- **THEN** `remaining()` SHALL return `10_000`

#### Scenario: Budget decreases with requests
- **WHEN** `on_request()` is called 5 times
- **THEN** `remaining()` SHALL return `9_995`

#### Scenario: Budget increases with fill volume
- **WHEN** `on_fill(100.0)` is called
- **THEN** `remaining()` SHALL increase by `100`

#### Scenario: Budget floor is zero
- **WHEN** `n_requests` exceeds `10_000 + cum_vlm`
- **THEN** `remaining()` SHALL return `0`, not a negative number

### Requirement: Utilization ratio
The class SHALL compute a utilization ratio as `cum_vlm / max(n_requests, 1)`. The ratio SHALL be exposed via a `ratio` property.

#### Scenario: Ratio with no requests
- **WHEN** no requests or fills have occurred
- **THEN** `ratio` SHALL return `0.0`

#### Scenario: Healthy ratio
- **WHEN** `cum_vlm` is `1000.0` and `n_requests` is `800`
- **THEN** `ratio` SHALL return `1.25`

### Requirement: Request tracking
`on_request(n=1)` SHALL increment `n_requests` by `n`. The default increment is 1, representing a single API call or a batch operation of any size.

#### Scenario: Single request
- **WHEN** `on_request()` is called with no arguments
- **THEN** `n_requests` SHALL increase by `1`

#### Scenario: Explicit count
- **WHEN** `on_request(n=3)` is called
- **THEN** `n_requests` SHALL increase by `3`

### Requirement: Fill volume tracking
`on_fill(volume_usd)` SHALL increment `cum_vlm` by the given amount in USD.

#### Scenario: Single fill
- **WHEN** `on_fill(50.0)` is called
- **THEN** `cum_vlm` SHALL increase by `50.0`

#### Scenario: Multiple fills accumulate
- **WHEN** `on_fill(100.0)` then `on_fill(200.0)` are called
- **THEN** `cum_vlm` SHALL be `300.0`

### Requirement: Exchange sync
`sync_from_exchange(cum_vlm, n_requests)` SHALL overwrite the local `cum_vlm` and `n_requests` with exchange-reported values. The exchange is the authoritative source of truth.

#### Scenario: Sync corrects drift
- **WHEN** local state has `cum_vlm=500, n_requests=400` and `sync_from_exchange(600, 450)` is called
- **THEN** `cum_vlm` SHALL be `600` and `n_requests` SHALL be `450`

### Requirement: Health check
`is_healthy()` SHALL return `True` when `ratio >= 1.0`.

#### Scenario: Healthy state
- **WHEN** `cum_vlm=1000` and `n_requests=800`
- **THEN** `is_healthy()` SHALL return `True`

#### Scenario: Unhealthy state
- **WHEN** `cum_vlm=500` and `n_requests=800`
- **THEN** `is_healthy()` SHALL return `False`

### Requirement: Emergency detection
`is_emergency()` SHALL return `True` when `remaining() < SAFETY_MARGIN`. The default `SAFETY_MARGIN` SHALL be `500`.

#### Scenario: Normal budget
- **WHEN** `remaining()` returns `5000`
- **THEN** `is_emergency()` SHALL return `False`

#### Scenario: Emergency budget
- **WHEN** `remaining()` returns `300`
- **THEN** `is_emergency()` SHALL return `True`

### Requirement: Status logging
A `log_status()` method SHALL return a formatted string with current utilization metrics: ratio, budget, cumulative volume, and cumulative requests.

#### Scenario: Status format
- **WHEN** `cum_vlm=583479, n_requests=522489`
- **THEN** `log_status()` SHALL return a string containing `ratio=`, `budget=`, `vol=`, and `reqs=`
