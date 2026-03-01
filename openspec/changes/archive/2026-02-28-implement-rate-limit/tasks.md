## 1. Core Data Structure

- [x] 1.1 Implement `RateLimitBudget` dataclass with `cum_vlm: float`, `n_requests: int`, `SAFETY_MARGIN: int = 500`, `CRITICAL_MARGIN: int = 100` fields
- [x] 1.2 Implement `budget` property computing `10_000 + cum_vlm - n_requests`
- [x] 1.3 Implement `ratio` property computing `cum_vlm / max(n_requests, 1)`
- [x] 1.4 Implement `remaining()` method returning `max(0, budget)`

## 2. Mutation Methods

- [x] 2.1 Implement `on_request(n=1)` incrementing `n_requests` by `n`
- [x] 2.2 Implement `on_fill(volume_usd: float)` incrementing `cum_vlm`
- [x] 2.3 Implement `sync_from_exchange(cum_vlm, n_requests)` overwriting local state

## 3. Query Methods

- [x] 3.1 Implement `is_healthy()` returning `ratio >= 1.0`
- [x] 3.2 Implement `is_emergency()` returning `remaining() < SAFETY_MARGIN`
- [x] 3.3 Implement `log_status()` returning formatted utilization string

## 4. Tests

- [x] 4.1 Test fresh instance has budget of 10,000
- [x] 4.2 Test budget decreases with requests and increases with fills
- [x] 4.3 Test budget floor clamps to zero
- [x] 4.4 Test ratio computation including zero-request edge case
- [x] 4.5 Test `sync_from_exchange()` overwrites local state
- [x] 4.6 Test `is_healthy()` and `is_emergency()` thresholds
- [x] 4.7 Test `log_status()` output format
