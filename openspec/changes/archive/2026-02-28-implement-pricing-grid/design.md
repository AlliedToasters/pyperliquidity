## Context

The pricing grid module (`src/pyperliquidity/pricing_grid.py`) is currently an empty file. It is the first domain module to be implemented as it has zero dependencies and is a prerequisite for inventory, quoting engine, and order differ modules.

The spec defines a geometric price ladder with configurable spacing (default 0.3% per HIP-2). The grid is computed once at initialization and is immutable. Prices must be rounded per exchange conventions.

## Goals / Non-Goals

**Goals:**
- Implement `PricingGrid` dataclass with `start_px`, `n_orders`, `tick_size`, and configurable rounding
- Generate the geometric price ladder in `__post_init__`
- Provide `levels`, `level_for_price(px)`, and `price_at_level(i)` APIs
- Detect and reject degenerate grids where rounding collapses adjacent levels
- Full pytest coverage of invariants and edge cases

**Non-Goals:**
- Dynamic grid shifting or rebalancing (grid is immutable per spec)
- Fetching tick size from exchange API (rounding function is injected, I/O stays outside)
- Integration with other modules (tested in isolation)

## Decisions

### 1. Use a frozen dataclass for PricingGrid
**Rationale**: The grid is immutable per spec. A frozen dataclass enforces this at the language level and communicates intent clearly. Use `__post_init__` to compute levels once.
**Alternative**: Regular class with read-only properties — more boilerplate, same effect.

### 2. Accept a rounding callable rather than sig-figs integer
**Rationale**: The spec says rounding is "configurable" and varies per spot pair. A `Callable[[float], float]` is the most flexible approach — callers can inject `lambda px: round(px, 4)` or a sig-fig rounder. This keeps I/O (fetching tick size from exchange) fully outside the module.
**Alternative**: Accept `sig_figs: int` parameter — simpler but less flexible for markets with fixed decimal tick sizes.

### 3. Use a tuple (not list) for internal levels storage
**Rationale**: Immutable container matches the frozen dataclass. Prevents accidental mutation. `tuple[float, ...]` is slightly more memory-efficient than `list[float]`.

### 4. Binary search for `level_for_price`
**Rationale**: Grid is sorted and monotonically increasing — `bisect` gives O(log n) lookup. Return the index of the nearest level (comparing distance to the left and right neighbors). Return `None` if the price is outside the grid range by more than half a tick spacing.

### 5. Validate grid in `__post_init__`
**Rationale**: Fail fast on degenerate inputs. If any `levels[i+1] == levels[i]` after rounding, raise `ValueError`. This catches sub-cent tokens where 0.3% spacing rounds to zero.

## Risks / Trade-offs

- **[Float precision]** → Using native `float` rather than `Decimal`. Acceptable because the grid is rounded to exchange tick sizes anyway, and all downstream consumers work in floats. If precision issues arise, the rounding callable can use `Decimal` internally.
- **[Nearest-level ambiguity]** → When a price falls exactly between two levels, we pick the lower index. This is deterministic but arbitrary. → Document the tie-breaking rule.
- **[Large grids]** → No upper bound on `n_orders`. Memory is O(n) which is fine for practical values (typically < 1000). No mitigation needed.
