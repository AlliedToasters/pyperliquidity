"""Tests for the quoting engine module — inventory-derived pricing, n_orders per side."""

from __future__ import annotations

import ast
import inspect

import pytest

from pyperliquidity.quoting_engine import DesiredOrder, compute_desired_orders

# --- DesiredOrder dataclass ---


class TestDesiredOrder:
    def test_creation(self) -> None:
        o = DesiredOrder(side="sell", level_index=5, price=1.003, size=10.0)
        assert o.side == "sell"
        assert o.level_index == 5
        assert o.price == 1.003
        assert o.size == 10.0

    def test_immutability(self) -> None:
        o = DesiredOrder(side="buy", level_index=3, price=0.99, size=5.0)
        with pytest.raises(AttributeError):
            o.side = "sell"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            o.price = 1.0  # type: ignore[misc]

    def test_equality(self) -> None:
        a = DesiredOrder(side="sell", level_index=5, price=1.003, size=10.0)
        b = DesiredOrder(side="sell", level_index=5, price=1.003, size=10.0)
        assert a == b

    def test_inequality(self) -> None:
        a = DesiredOrder(side="sell", level_index=5, price=1.003, size=10.0)
        b = DesiredOrder(side="buy", level_index=5, price=1.003, size=10.0)
        assert a != b

    def test_hashing(self) -> None:
        a = DesiredOrder(side="sell", level_index=5, price=1.003, size=10.0)
        b = DesiredOrder(side="sell", level_index=5, price=1.003, size=10.0)
        assert hash(a) == hash(b)
        s = {a, b}
        assert len(s) == 1


# --- Price from inventory ---


class TestPriceFromInventory:
    def test_balanced_inventory(self) -> None:
        """100 tokens, $10,000 USDC → mid = 100.0"""
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        assert result.mid_price == 100.0

    def test_after_ask_fill(self) -> None:
        """Buy 1 token for $101 → 99 tokens, $10,101 USDC → mid ≈ 102.03"""
        result = compute_desired_orders(
            effective_token=99.0,
            effective_usdc=10_101.0,
            order_sz=1.0,
            n_orders=5,
        )
        assert abs(result.mid_price - 102.03) < 0.01

    def test_scales_linearly(self) -> None:
        """2x tokens, 2x USDC → same mid."""
        r1 = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        r2 = compute_desired_orders(
            effective_token=200.0,
            effective_usdc=20_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        assert r1.mid_price == r2.mid_price


# --- n_orders per side ---


class TestNOrdersPerSide:
    def test_n_orders_asks(self) -> None:
        """Exactly n_orders asks above mid."""
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        asks = [o for o in result.orders if o.side == "sell"]
        assert len(asks) == 5

    def test_n_orders_bids(self) -> None:
        """Exactly n_orders bids below mid."""
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        bids = [o for o in result.orders if o.side == "buy"]
        assert len(bids) == 5

    def test_all_full_size(self) -> None:
        """With ample balance, all orders are order_sz."""
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        for o in result.orders:
            assert o.size == 1.0

    def test_ask_0_at_mid(self) -> None:
        """Best ask (level_index=0) is at round(mid)."""
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        asks = sorted(
            [o for o in result.orders if o.side == "sell"],
            key=lambda o: o.level_index,
        )
        assert asks[0].level_index == 0
        assert asks[0].price == result.mid_price

    def test_bid_0_below_mid(self) -> None:
        """Best bid (level_index=0) is below mid."""
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        bids = sorted(
            [o for o in result.orders if o.side == "buy"],
            key=lambda o: o.level_index,
        )
        assert bids[0].level_index == 0
        assert bids[0].price < result.mid_price

    def test_spread_one_tick(self) -> None:
        """Best ask / best bid ≈ 1.003 (one tick)."""
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        asks = [o for o in result.orders if o.side == "sell"]
        bids = [o for o in result.orders if o.side == "buy"]
        best_ask = min(asks, key=lambda o: o.price)
        best_bid = max(bids, key=lambda o: o.price)
        ratio = best_ask.price / best_bid.price
        assert abs(ratio - 1.003) < 0.001


# --- Requote after fill ---


class TestRequoteAfterFill:
    def test_asks_above_new_mid(self) -> None:
        """After fill, all asks are at or above new mid."""
        result = compute_desired_orders(
            effective_token=99.0,
            effective_usdc=10_101.0,
            order_sz=1.0,
            n_orders=5,
        )
        asks = [o for o in result.orders if o.side == "sell"]
        for a in asks:
            assert a.price >= result.mid_price

    def test_bids_below_new_mid(self) -> None:
        """After fill, all bids are below new mid."""
        result = compute_desired_orders(
            effective_token=99.0,
            effective_usdc=10_101.0,
            order_sz=1.0,
            n_orders=5,
        )
        bids = [o for o in result.orders if o.side == "buy"]
        for b in bids:
            assert b.price < result.mid_price

    def test_still_n_orders_per_side(self) -> None:
        """After fill, still n_orders on each side."""
        result = compute_desired_orders(
            effective_token=99.0,
            effective_usdc=10_101.0,
            order_sz=1.0,
            n_orders=5,
        )
        asks = [o for o in result.orders if o.side == "sell"]
        bids = [o for o in result.orders if o.side == "buy"]
        assert len(asks) == 5
        assert len(bids) == 5


# --- Min notional ---


class TestMinNotional:
    def test_increases_order_sz(self) -> None:
        """When mid * order_sz < min_notional, effective_order_sz increases."""
        result = compute_desired_orders(
            effective_token=10_000.0,
            effective_usdc=100.0,
            order_sz=1.0,
            n_orders=5,
            min_notional=10.0,
        )
        # mid = 100/10000 = 0.01, order_sz=1.0, notional=0.01 < 10.0
        # eff_order_sz = max(1.0, 10.0/0.01) = 1000.0
        assert result.effective_order_sz == 1000.0

    def test_reduces_n_orders(self) -> None:
        """When effective_order_sz increases, effective_n_orders decreases."""
        result = compute_desired_orders(
            effective_token=10_000.0,
            effective_usdc=100.0,
            order_sz=1.0,
            n_orders=5,
            min_notional=10.0,
        )
        # eff_order_sz=1000, tokens=10000 → max 10 asks, usdc=100, mid=0.01 → max 10 bids
        # eff_n_orders = min(5, 10, 10) = 5
        assert result.effective_n_orders <= 5

    def test_no_effect_when_not_binding(self) -> None:
        """When notional is already above min_notional, no change."""
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
            min_notional=0.01,
        )
        assert result.effective_order_sz == 1.0
        assert result.effective_n_orders == 5


# --- Inventory collapse ---


class TestInventoryCollapse:
    def test_extreme_ratio(self) -> None:
        """10,000 tokens, $100 USDC → mid=0.01, min_notional binds."""
        result = compute_desired_orders(
            effective_token=10_000.0,
            effective_usdc=100.0,
            order_sz=1.0,
            n_orders=10,
            min_notional=10.0,
        )
        # mid = 0.01
        assert abs(result.mid_price - 0.01) < 0.001
        # Must still have orders on both sides
        asks = [o for o in result.orders if o.side == "sell"]
        bids = [o for o in result.orders if o.side == "buy"]
        assert len(asks) > 0
        assert len(bids) > 0
        # Ask notionals are at or above min_notional (at mid or above)
        for a in asks:
            assert a.price * a.size >= 10.0 - 1e-6
        # effective_order_sz was increased
        assert result.effective_order_sz > 1.0


# --- Edge cases ---


class TestEdgeCases:
    def test_zero_tokens(self) -> None:
        result = compute_desired_orders(
            effective_token=0.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        assert result.orders == []

    def test_zero_usdc(self) -> None:
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=0.0,
            order_sz=1.0,
            n_orders=5,
        )
        assert result.orders == []

    def test_both_zero(self) -> None:
        result = compute_desired_orders(
            effective_token=0.0,
            effective_usdc=0.0,
            order_sz=1.0,
            n_orders=5,
        )
        assert result.orders == []

    def test_balance_caps_asks(self) -> None:
        """If tokens < n_orders * order_sz, fewer asks or partial at end."""
        result = compute_desired_orders(
            effective_token=3.5,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        asks = [o for o in result.orders if o.side == "sell"]
        total_ask_sz = sum(a.size for a in asks)
        assert abs(total_ask_sz - 3.5) < 1e-10

    def test_balance_caps_bids(self) -> None:
        """If usdc < n_orders * order_sz * mid, fewer bids or partial at end."""
        result = compute_desired_orders(
            effective_token=100.0,
            effective_usdc=200.0,
            order_sz=1.0,
            n_orders=5,
        )
        bids = [o for o in result.orders if o.side == "buy"]
        total_bid_cost = sum(b.price * b.size for b in bids)
        assert total_bid_cost <= 200.0 + 1e-6

    def test_determinism(self) -> None:
        """Repeated calls with same inputs produce identical results."""
        kwargs = dict(
            effective_token=100.0,
            effective_usdc=10_000.0,
            order_sz=1.0,
            n_orders=5,
        )
        r1 = compute_desired_orders(**kwargs)
        r2 = compute_desired_orders(**kwargs)
        assert r1.orders == r2.orders
        assert r1.mid_price == r2.mid_price


# --- No forbidden imports ---


class TestModuleImports:
    def test_no_forbidden_imports(self) -> None:
        """The quoting_engine module must not import I/O modules."""
        import pyperliquidity.quoting_engine as mod

        source = inspect.getsource(mod)
        tree = ast.parse(source)
        forbidden = {"order_state", "ws_state", "batch_emitter", "rate_limit"}

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.add(node.module.split(".")[-1])

        violations = imported_names & forbidden
        assert not violations, f"Forbidden imports found: {violations}"
