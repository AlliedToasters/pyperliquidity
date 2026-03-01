## 1. PricingGrid Dataclass

- [x] 1.1 Define frozen `PricingGrid` dataclass with fields: `start_px: float`, `n_orders: int`, `tick_size: float = 0.003`, `round_fn: Callable[[float], float]` (with default sig-fig rounder)
- [x] 1.2 Implement `__post_init__` to compute the geometric price ladder using the recurrence `px_i = round_fn(px_{i-1} * (1 + tick_size))` and store as `tuple[float, ...]`
- [x] 1.3 Add degenerate grid validation in `__post_init__` — raise `ValueError` if any adjacent levels are equal after rounding

## 2. Public API Methods

- [x] 2.1 Implement `levels` property returning the `tuple[float, ...]` of all price levels
- [x] 2.2 Implement `price_at_level(i: int) -> float` with `IndexError` on out-of-bounds
- [x] 2.3 Implement `level_for_price(px: float) -> int | None` using `bisect` for O(log n) lookup, returning nearest index or `None` if outside grid range by more than half a tick spacing, with lower-index tie-breaking

## 3. Tests

- [x] 3.1 Test standard grid generation: correct length, starts at `start_px`, monotonically increasing
- [x] 3.2 Test determinism: identical params produce identical levels
- [x] 3.3 Test custom `tick_size` and custom `round_fn`
- [x] 3.4 Test degenerate grid detection raises `ValueError`
- [x] 3.5 Test `level_for_price`: exact match, between levels, out of range (below/above), tie-breaking
- [x] 3.6 Test `price_at_level`: valid index returns correct price, out-of-bounds raises `IndexError`
- [x] 3.7 Test immutability: `levels` returns tuple, attribute assignment raises error
