"""Tests for the PricingGrid module."""

import pytest

from pyperliquidity.pricing_grid import (
    PricingGrid,
    _default_round,
    compute_allocation_from_target_px,
)

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


# --- 3.8 5sf rounding verification against HIP-2 ---


class TestDefaultRounding5sf:
    def test_default_round_produces_5sf(self) -> None:
        """_default_round rounds to 5 significant figures."""
        assert _default_round(0.020777) == 0.020777
        # 0.020777 * 1.003 = 0.020839331 → 5sf = 0.020839
        assert _default_round(0.020777 * 1.003) == 0.020839

    def test_grid_level_1_matches_hip2(self) -> None:
        """Level 1 of @67 BLOKED2 grid matches observed HIP-2 value."""
        grid = PricingGrid(start_px=0.020777, n_orders=40)
        assert grid.levels[0] == 0.020777
        assert grid.levels[1] == 0.020839

    def test_grid_level_20_matches_hip2(self) -> None:
        """Level 20 of @67 BLOKED2 grid matches observed value 0.022060."""
        grid = PricingGrid(start_px=0.020777, n_orders=40)
        assert grid.levels[20] == 0.022060

    def test_all_levels_are_5sf(self) -> None:
        """Every level in the grid is rounded to 5 significant figures."""
        grid = PricingGrid(start_px=0.020777, n_orders=40)
        for i, px in enumerate(grid.levels):
            assert px == _default_round(px), (
                f"Level {i} ({px}) is not 5sf-rounded"
            )

    def test_5sf_rounding_various_magnitudes(self) -> None:
        """5sf rounding works across different price magnitudes."""
        assert _default_round(123.456789) == 123.46
        assert _default_round(1.23456789) == 1.2346
        assert _default_round(0.00123456789) == 0.0012346
        assert _default_round(12345.6789) == 12346.0


# --- compute_allocation_from_target_px ---


class TestComputeAllocationFromTargetPx:
    def test_cursor_at_start_px(self) -> None:
        """target_px == start_px → cursor=0, all levels are asks, no USDC needed."""
        token, usdc = compute_allocation_from_target_px(
            target_px=1.0, start_px=1.0, n_orders=10, order_sz=100.0,
        )
        assert token == 10 * 100.0  # all 10 levels are asks
        assert usdc == 0.0  # no bid levels

    def test_cursor_at_last_level(self) -> None:
        """target_px at the last level → cursor=n_orders-1, 1 ask level, rest bids."""
        grid = PricingGrid(start_px=1.0, n_orders=10)
        last_px = grid.levels[-1]
        token, usdc = compute_allocation_from_target_px(
            target_px=last_px, start_px=1.0, n_orders=10, order_sz=100.0,
        )
        # cursor = 9, ask_levels = 10 - 9 = 1
        assert token == 1 * 100.0
        # bid_levels = 9 (levels 0..8)
        expected_usdc = sum(100.0 * grid.price_at_level(i) for i in range(9))
        assert abs(usdc - expected_usdc) < 1e-10

    def test_cursor_at_middle(self) -> None:
        """target_px near the middle places cursor at midpoint."""
        grid = PricingGrid(start_px=1.0, n_orders=10)
        mid_px = grid.levels[5]
        token, usdc = compute_allocation_from_target_px(
            target_px=mid_px, start_px=1.0, n_orders=10, order_sz=100.0,
        )
        # cursor = 5, ask_levels = 5, bid_levels = 5
        assert token == 5 * 100.0
        expected_usdc = sum(100.0 * grid.price_at_level(i) for i in range(5))
        assert abs(usdc - expected_usdc) < 1e-10

    def test_target_below_start_px_raises(self) -> None:
        """target_px < start_px raises ValueError."""
        with pytest.raises(ValueError, match="must be >= start_px"):
            compute_allocation_from_target_px(
                target_px=0.5, start_px=1.0, n_orders=10, order_sz=100.0,
            )

    def test_target_above_grid_raises(self) -> None:
        """target_px above grid maximum raises ValueError."""
        grid = PricingGrid(start_px=1.0, n_orders=10)
        above_max = grid.levels[-1] * 1.1  # well above max
        with pytest.raises(ValueError, match="above the grid maximum"):
            compute_allocation_from_target_px(
                target_px=above_max, start_px=1.0, n_orders=10, order_sz=100.0,
            )

    def test_token_plus_usdc_cover_full_grid(self) -> None:
        """allocated_token * price + allocated_usdc should cover the entire grid's value."""
        grid = PricingGrid(start_px=1.0, n_orders=20)
        target_px = grid.levels[10]
        token, usdc = compute_allocation_from_target_px(
            target_px=target_px, start_px=1.0, n_orders=20, order_sz=50.0,
        )
        # The token allocation covers ask levels (10 levels * 50 = 500 tokens)
        assert token == 10 * 50.0
        # The USDC allocation covers bid levels (levels 0..9)
        expected_usdc = sum(50.0 * grid.price_at_level(i) for i in range(10))
        assert abs(usdc - expected_usdc) < 1e-10

    def test_snaps_to_nearest_level(self) -> None:
        """target_px between two levels snaps to the nearest one."""
        grid = PricingGrid(start_px=1.0, n_orders=10)
        # Price between level 3 and level 4, closer to level 3
        between_px = grid.levels[3] * 0.8 + grid.levels[4] * 0.2
        token, usdc = compute_allocation_from_target_px(
            target_px=between_px, start_px=1.0, n_orders=10, order_sz=100.0,
        )
        # Should snap to level 3: cursor=3, ask_levels=7
        assert token == 7 * 100.0

    def test_roundtrip_with_quoting_engine(self) -> None:
        """Computed allocations should produce the expected cursor in the quoting engine."""
        from pyperliquidity.quoting_engine import compute_desired_orders

        grid = PricingGrid(start_px=1.0, n_orders=20)
        target_level = 8
        target_px = grid.levels[target_level]
        token, usdc = compute_allocation_from_target_px(
            target_px=target_px, start_px=1.0, n_orders=20, order_sz=100.0,
        )
        orders = compute_desired_orders(
            grid=grid, effective_token=token, effective_usdc=usdc, order_sz=100.0,
        )
        asks = [o for o in orders if o.side == "sell"]
        bids = [o for o in orders if o.side == "buy"]
        # Cursor should be at target_level
        min_ask_level = min(a.level_index for a in asks)
        max_bid_level = max(b.level_index for b in bids)
        assert min_ask_level == target_level
        assert max_bid_level == target_level - 1

    def test_custom_tick_size(self) -> None:
        """Works correctly with a non-default tick_size."""
        grid = PricingGrid(start_px=1.0, n_orders=10, tick_size=0.01)
        target_px = grid.levels[5]
        token, usdc = compute_allocation_from_target_px(
            target_px=target_px, start_px=1.0, n_orders=10,
            order_sz=100.0, tick_size=0.01,
        )
        assert token == 5 * 100.0
        expected_usdc = sum(100.0 * grid.price_at_level(i) for i in range(5))
        assert abs(usdc - expected_usdc) < 1e-10
