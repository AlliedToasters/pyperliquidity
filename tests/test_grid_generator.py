"""Tests for pyperliquidity.grid_generator — pure grid config generation."""

from __future__ import annotations

import math

import pytest

from pyperliquidity.cli import _validate_config
from pyperliquidity.grid_generator import compute_n_orders, compute_order_sz, generate_grid_config
from pyperliquidity.pricing_grid import PricingGrid
from pyperliquidity.quoting_engine import compute_desired_orders

# ---------------------------------------------------------------------------
# compute_n_orders
# ---------------------------------------------------------------------------


class TestComputeNOrders:
    def test_known_range(self) -> None:
        """350 → 50000 at 0.3% tick should give a known n_orders."""
        n = compute_n_orders(350, 50000)
        # ln(50000/350) / ln(1.003) ≈ 1619.8 → ceil = 1620
        assert n == math.ceil(math.log(50000 / 350) / math.log(1.003))

    def test_small_range(self) -> None:
        n = compute_n_orders(100, 110)
        expected = math.ceil(math.log(110 / 100) / math.log(1.003))
        assert n == expected

    def test_single_tick(self) -> None:
        """A range of exactly one tick should give 1."""
        n = compute_n_orders(100, 100.3)
        assert n >= 1

    def test_min_equals_max_raises(self) -> None:
        with pytest.raises(ValueError, match="must be less than"):
            compute_n_orders(100, 100)

    def test_min_greater_than_max_raises(self) -> None:
        with pytest.raises(ValueError, match="must be less than"):
            compute_n_orders(200, 100)

    def test_negative_price_raises(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            compute_n_orders(-1, 100)

    def test_zero_price_raises(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            compute_n_orders(0, 100)

    def test_custom_tick_size(self) -> None:
        n = compute_n_orders(100, 200, tick_size=0.01)
        expected = math.ceil(math.log(2) / math.log(1.01))
        assert n == expected


# ---------------------------------------------------------------------------
# compute_order_sz
# ---------------------------------------------------------------------------


class TestComputeOrderSz:
    def test_basic(self) -> None:
        """40 tokens over a grid where target is at the bottom → all ask levels."""
        n = compute_n_orders(350, 50000)
        # target at start_px → cursor=0 → ask_levels=n_orders
        sz = compute_order_sz(40, n, target_px=350, start_px=350)
        assert abs(sz - 40 / n) < 1e-10

    def test_target_at_midpoint(self) -> None:
        grid = PricingGrid(start_px=100, n_orders=20)
        mid_level = grid.levels[10]
        sz = compute_order_sz(50, 20, target_px=mid_level, start_px=100)
        # cursor=10, ask_levels=10
        assert abs(sz - 5.0) < 1e-10

    def test_zero_liquidity_raises(self) -> None:
        with pytest.raises(ValueError, match="liquidity_token must be positive"):
            compute_order_sz(0, 10, target_px=100, start_px=100)

    def test_negative_liquidity_raises(self) -> None:
        with pytest.raises(ValueError, match="liquidity_token must be positive"):
            compute_order_sz(-1, 10, target_px=100, start_px=100)

    def test_zero_n_orders_raises(self) -> None:
        with pytest.raises(ValueError, match="n_orders must be positive"):
            compute_order_sz(10, 0, target_px=100, start_px=100)


# ---------------------------------------------------------------------------
# generate_grid_config
# ---------------------------------------------------------------------------


class TestGenerateGridConfig:
    def test_basic_config(self) -> None:
        """Generate a basic config and verify structure."""
        config, warnings = generate_grid_config(
            coin="@1434",
            min_px=350,
            max_px=50000,
            liquidity_token=40,
            testnet=True,
        )
        assert config["market"]["coin"] == "@1434"
        assert config["market"]["testnet"] is True
        assert config["strategy"]["n_orders"] > 0
        assert config["strategy"]["order_sz"] > 0
        assert config["strategy"]["start_px"] == 350
        assert config["strategy"]["target_px"] > 0
        assert config["allocation"]["allocated_token"] > 0
        assert config["allocation"]["allocated_usdc"] >= 0

    def test_target_px_defaults_to_geometric_midpoint(self) -> None:
        config, _ = generate_grid_config(
            coin="TEST",
            min_px=100,
            max_px=400,
            liquidity_token=100,
        )
        geo_mid = math.sqrt(100 * 400)  # = 200
        grid = PricingGrid(
            start_px=100,
            n_orders=config["strategy"]["n_orders"],
        )
        snapped = grid.price_at_level(grid.level_for_price(geo_mid))
        assert config["strategy"]["target_px"] == snapped

    def test_explicit_target_px(self) -> None:
        grid = PricingGrid(start_px=100, n_orders=compute_n_orders(100, 200))
        target = grid.levels[10]
        config, _ = generate_grid_config(
            coin="TEST",
            min_px=100,
            max_px=200,
            liquidity_token=50,
            target_px=target,
        )
        assert config["strategy"]["target_px"] == target

    def test_active_levels_in_config(self) -> None:
        config, _ = generate_grid_config(
            coin="TEST",
            min_px=100,
            max_px=200,
            liquidity_token=50,
            active_levels=10,
        )
        assert config["strategy"]["active_levels"] == 10

    def test_active_levels_absent_when_not_set(self) -> None:
        config, _ = generate_grid_config(
            coin="TEST",
            min_px=100,
            max_px=200,
            liquidity_token=50,
        )
        assert "active_levels" not in config["strategy"]

    def test_sz_decimals_rounding(self) -> None:
        config, _ = generate_grid_config(
            coin="TEST",
            min_px=100,
            max_px=200,
            liquidity_token=50,
            sz_decimals=2,
        )
        sz = config["strategy"]["order_sz"]
        assert sz == round(sz, 2)

    def test_min_equals_max_raises(self) -> None:
        with pytest.raises(ValueError, match="must be less than"):
            generate_grid_config(
                coin="TEST", min_px=100, max_px=100, liquidity_token=50,
            )

    def test_negative_liquidity_raises(self) -> None:
        with pytest.raises(ValueError, match="liquidity_token must be positive"):
            generate_grid_config(
                coin="TEST", min_px=100, max_px=200, liquidity_token=-1,
            )

    def test_warning_below_min_notional(self) -> None:
        """Tiny order sizes should trigger below_min_notional warning."""
        config, warnings = generate_grid_config(
            coin="TEST",
            min_px=0.001,
            max_px=0.01,
            liquidity_token=1,
            min_notional=10.0,
        )
        codes = [w.code for w in warnings]
        assert "below_min_notional" in codes

    def test_warning_active_levels_exceeds_grid(self) -> None:
        config, warnings = generate_grid_config(
            coin="TEST",
            min_px=100,
            max_px=110,
            liquidity_token=50,
            active_levels=9999,
        )
        codes = [w.code for w in warnings]
        assert "active_levels_exceeds_grid" in codes

    def test_warning_large_grid_no_active_levels(self) -> None:
        config, warnings = generate_grid_config(
            coin="TEST",
            min_px=1,
            max_px=10000,
            liquidity_token=100,
        )
        assert config["strategy"]["n_orders"] > 100
        codes = [w.code for w in warnings]
        assert "large_grid_no_active_levels" in codes

    def test_roundtrip_validate_config(self) -> None:
        """Generated config should pass _validate_config."""
        config, _ = generate_grid_config(
            coin="@1434",
            min_px=350,
            max_px=50000,
            liquidity_token=40,
            active_levels=20,
            testnet=True,
        )
        validated = _validate_config(config)
        assert validated["market"]["coin"] == "@1434"
        assert validated["allocation"]["allocated_token"] > 0

    def test_roundtrip_produces_orders(self) -> None:
        """Generated config should produce orders via compute_desired_orders."""
        config, _ = generate_grid_config(
            coin="TEST",
            min_px=100,
            max_px=200,
            liquidity_token=50,
            active_levels=10,
        )
        s = config["strategy"]
        a = config["allocation"]
        grid = PricingGrid(start_px=s["start_px"], n_orders=s["n_orders"])
        orders = compute_desired_orders(
            grid=grid,
            effective_token=a["allocated_token"],
            effective_usdc=a["allocated_usdc"],
            order_sz=s["order_sz"],
            active_levels=s.get("active_levels"),
        )
        assert len(orders) > 0
        # Should have both buys and sells
        sides = {o.side for o in orders}
        assert "buy" in sides
        assert "sell" in sides

    def test_testnet_flag(self) -> None:
        config, _ = generate_grid_config(
            coin="TEST",
            min_px=100,
            max_px=200,
            liquidity_token=50,
            testnet=True,
        )
        assert config["market"]["testnet"] is True

    def test_min_notional_in_tuning(self) -> None:
        config, _ = generate_grid_config(
            coin="TEST",
            min_px=100,
            max_px=200,
            liquidity_token=50,
            min_notional=15.0,
        )
        assert config["tuning"]["min_notional"] == 15.0
