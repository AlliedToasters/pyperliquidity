## MODIFIED Requirements

### Requirement: Grid Generation
The system SHALL generate a geometric price ladder of exactly `n_orders` levels starting from `start_px`, where each successive level is computed as `round(prev_level * (1 + tick_size))` using a configurable rounding function.

The grid SHALL be computed once at initialization and SHALL be immutable for the lifetime of the `PricingGrid` instance.

The default `tick_size` SHALL be `0.003` (0.3% per HIP-2).

#### Scenario: Standard grid generation
- **WHEN** `PricingGrid` is created with `start_px=1.0`, `n_orders=5`, `tick_size=0.003`, and default rounding
- **THEN** `levels` contains exactly 5 prices, starting at `1.0`, each successive price approximately 0.3% higher than the previous

#### Scenario: Custom tick size
- **WHEN** `PricingGrid` is created with `tick_size=0.01`
- **THEN** each successive level is approximately 1% higher than the previous

#### Scenario: Deterministic output
- **WHEN** `PricingGrid` is created twice with identical parameters
- **THEN** the resulting `levels` tuples are exactly equal

### Requirement: Configurable Rounding
The system SHALL accept an optional rounding callable `round_fn: Callable[[float], float]` that is applied at each step of the recurrence. If not provided, the system SHALL use Python's built-in `round()` with 8 significant figures as the default.

#### Scenario: Custom rounding function
- **WHEN** `PricingGrid` is created with `round_fn=lambda px: round(px, 4)`
- **THEN** all levels are rounded to 4 decimal places

#### Scenario: Default rounding
- **WHEN** `PricingGrid` is created without specifying `round_fn`
- **THEN** levels use the default significant-figure rounding

### Requirement: Degenerate Grid Detection
The system SHALL raise a `ValueError` during initialization if rounding causes any two adjacent levels to have the same price.

#### Scenario: Sub-cent token causes degenerate grid
- **WHEN** `PricingGrid` is created with `start_px=0.000001`, `tick_size=0.003`, and `round_fn=lambda px: round(px, 6)`
- **THEN** a `ValueError` is raised indicating the grid is degenerate

#### Scenario: Valid sub-cent token
- **WHEN** `PricingGrid` is created with `start_px=0.001`, `tick_size=0.003`, and sufficient rounding precision
- **THEN** the grid is created successfully with all levels strictly increasing

### Requirement: Monotonic Ordering
The grid SHALL be strictly monotonically increasing: for all valid indices `i`, `levels[i] < levels[i+1]`.

#### Scenario: All levels ascending
- **WHEN** any valid `PricingGrid` is created
- **THEN** every level is strictly greater than the previous level

### Requirement: Level Lookup by Price
The system SHALL provide `level_for_price(px: float) -> int | None` that returns the index of the nearest grid level to the given price. If the price is below `levels[0]` by more than half a tick spacing or above `levels[-1]` by more than half a tick spacing, it SHALL return `None`. When a price falls exactly between two levels, the lower index SHALL be returned.

#### Scenario: Exact match
- **WHEN** `level_for_price` is called with a price exactly equal to `levels[3]`
- **THEN** it returns `3`

#### Scenario: Between two levels
- **WHEN** `level_for_price` is called with a price between `levels[2]` and `levels[3]`, closer to `levels[3]`
- **THEN** it returns `3`

#### Scenario: Price below grid range
- **WHEN** `level_for_price` is called with a price far below `levels[0]`
- **THEN** it returns `None`

#### Scenario: Price above grid range
- **WHEN** `level_for_price` is called with a price far above `levels[-1]`
- **THEN** it returns `None`

#### Scenario: Tie-breaking between levels
- **WHEN** `level_for_price` is called with a price exactly equidistant between two levels
- **THEN** it returns the lower index

### Requirement: Price at Level Index
The system SHALL provide `price_at_level(i: int) -> float` that returns the price at grid index `i`. It SHALL raise an `IndexError` if `i` is out of bounds.

#### Scenario: Valid index
- **WHEN** `price_at_level(0)` is called
- **THEN** it returns `start_px`

#### Scenario: Out of bounds index
- **WHEN** `price_at_level(n_orders)` is called (one past the end)
- **THEN** an `IndexError` is raised

### Requirement: Immutability
The `PricingGrid` instance and its `levels` SHALL be immutable after construction. The `levels` property SHALL return a `tuple[float, ...]`.

#### Scenario: Levels is a tuple
- **WHEN** `levels` is accessed on a `PricingGrid`
- **THEN** it returns a `tuple`, not a `list`

#### Scenario: Cannot mutate grid
- **WHEN** a caller attempts to assign to any attribute of a constructed `PricingGrid`
- **THEN** the assignment raises an error
