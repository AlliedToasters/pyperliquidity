"""Tests for the PricingGrid module."""

import pytest

from pyperliquidity.pricing_grid import PricingGrid

# --- 3.1 Standard grid generation ---


class TestGridGeneration:
    def test_correct_length(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=10)
        assert len(grid.levels) == 10

    def test_starts_at_start_px(self) -> None:
        grid = PricingGrid(start_px=2.5, n_orders=5)
        assert grid.levels[0] == 2.5

    def test_monotonically_increasing(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=100)
        for i in range(len(grid.levels) - 1):
            assert grid.levels[i] < grid.levels[i + 1], (
                f"Level {i} ({grid.levels[i]}) not less than level {i+1} ({grid.levels[i+1]})"
            )

    def test_spacing_approximately_tick_size(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=50, tick_size=0.003)
        for i in range(len(grid.levels) - 1):
            ratio = grid.levels[i + 1] / grid.levels[i]
            assert abs(ratio - 1.003) < 0.001


# --- 3.2 Determinism ---


class TestDeterminism:
    def test_identical_params_produce_identical_levels(self) -> None:
        g1 = PricingGrid(start_px=1.0, n_orders=50, tick_size=0.003)
        g2 = PricingGrid(start_px=1.0, n_orders=50, tick_size=0.003)
        assert g1.levels == g2.levels

    def test_deterministic_with_custom_round_fn(self) -> None:
        def rfn(px: float) -> float:
            return round(px, 4)

        g1 = PricingGrid(start_px=0.5, n_orders=20, round_fn=rfn)
        g2 = PricingGrid(start_px=0.5, n_orders=20, round_fn=rfn)
        assert g1.levels == g2.levels


# --- 3.3 Custom tick_size and round_fn ---


class TestCustomParameters:
    def test_custom_tick_size(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=10, tick_size=0.01)
        for i in range(len(grid.levels) - 1):
            ratio = grid.levels[i + 1] / grid.levels[i]
            assert abs(ratio - 1.01) < 0.001

    def test_custom_round_fn(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=5, round_fn=lambda px: round(px, 4))
        for level in grid.levels:
            assert level == round(level, 4)


# --- 3.4 Degenerate grid detection ---


class TestDegenerateGrid:
    def test_degenerate_raises_value_error(self) -> None:
        # 0.000001 * 1.003 = 0.000001003, rounded to 6 decimals = 0.000001
        with pytest.raises(ValueError, match="Degenerate grid"):
            PricingGrid(
                start_px=0.000001,
                n_orders=5,
                tick_size=0.003,
                round_fn=lambda px: round(px, 6),
            )

    def test_valid_sub_cent_token(self) -> None:
        # 0.001 with sufficient precision should work
        grid = PricingGrid(
            start_px=0.001,
            n_orders=10,
            tick_size=0.003,
            round_fn=lambda px: round(px, 8),
        )
        assert len(grid.levels) == 10
        for i in range(len(grid.levels) - 1):
            assert grid.levels[i] < grid.levels[i + 1]


# --- 3.5 level_for_price ---


class TestLevelForPrice:
    @pytest.fixture()
    def grid(self) -> PricingGrid:
        return PricingGrid(start_px=1.0, n_orders=10, tick_size=0.003)

    def test_exact_match(self, grid: PricingGrid) -> None:
        for i, level in enumerate(grid.levels):
            assert grid.level_for_price(level) == i

    def test_between_levels_closer_to_right(self, grid: PricingGrid) -> None:
        # Price closer to levels[3] than levels[2]
        px = grid.levels[2] * 0.2 + grid.levels[3] * 0.8
        assert grid.level_for_price(px) == 3

    def test_between_levels_closer_to_left(self, grid: PricingGrid) -> None:
        # Price closer to levels[2] than levels[3]
        px = grid.levels[2] * 0.8 + grid.levels[3] * 0.2
        assert grid.level_for_price(px) == 2

    def test_price_below_range(self, grid: PricingGrid) -> None:
        assert grid.level_for_price(0.5) is None

    def test_price_above_range(self, grid: PricingGrid) -> None:
        assert grid.level_for_price(999.0) is None

    def test_tie_breaking_returns_lower_index(self, grid: PricingGrid) -> None:
        # Exactly between levels[2] and levels[3]
        midpoint = (grid.levels[2] + grid.levels[3]) / 2
        assert grid.level_for_price(midpoint) == 2

    def test_just_below_min_returns_level_0(self, grid: PricingGrid) -> None:
        # Slightly below levels[0] but within half-tick
        px = grid.levels[0] - grid.levels[0] * grid.tick_size * 0.1
        assert grid.level_for_price(px) == 0

    def test_just_above_max_returns_last_level(self, grid: PricingGrid) -> None:
        # Slightly above levels[-1] but within half-tick
        px = grid.levels[-1] + grid.levels[-1] * grid.tick_size * 0.1
        assert grid.level_for_price(px) == len(grid.levels) - 1


# --- 3.6 price_at_level ---


class TestPriceAtLevel:
    def test_valid_index(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=5)
        assert grid.price_at_level(0) == grid.levels[0]
        assert grid.price_at_level(4) == grid.levels[4]

    def test_out_of_bounds_raises_index_error(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=5)
        with pytest.raises(IndexError):
            grid.price_at_level(5)

    def test_negative_index_raises_index_error(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=5)
        with pytest.raises(IndexError):
            grid.price_at_level(-1)


# --- 3.7 Immutability ---


class TestImmutability:
    def test_levels_is_tuple(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=5)
        assert isinstance(grid.levels, tuple)

    def test_cannot_assign_attribute(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=5)
        with pytest.raises(AttributeError):
            grid.start_px = 2.0  # type: ignore[misc]

    def test_cannot_assign_levels(self) -> None:
        grid = PricingGrid(start_px=1.0, n_orders=5)
        with pytest.raises(AttributeError):
            grid._levels = (1.0, 2.0)  # type: ignore[misc]
