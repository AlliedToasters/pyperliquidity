"""Tests for the quoting engine module."""

from __future__ import annotations

import ast
import inspect

import pytest

from pyperliquidity.pricing_grid import PricingGrid
from pyperliquidity.quoting_engine import DesiredOrder, compute_desired_orders

# --- Shared fixtures ---


@pytest.fixture()
def grid() -> PricingGrid:
    """A 20-level grid starting at 1.0 with default 0.3% spacing."""
    return PricingGrid(start_px=1.0, n_orders=20)


@pytest.fixture()
def small_grid() -> PricingGrid:
    """A 5-level grid for overflow testing."""
    return PricingGrid(start_px=1.0, n_orders=5)


# --- 4.1 DesiredOrder dataclass ---


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
        # Can be used in sets/dicts
        s = {a, b}
        assert len(s) == 1


# --- 4.2 Basic ask generation ---


class TestAskGeneration:
    def test_exact_multiple(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=3.0,
            effective_usdc=0.0, order_sz=1.0,
        )
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 3
        assert all(a.size == 1.0 for a in asks)
        assert [a.level_index for a in asks] == [5, 6, 7]

    def test_partial_ask(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=3.5,
            effective_usdc=0.0, order_sz=1.0,
        )
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 4
        # First 3 are full
        for a in asks[:3]:
            assert a.size == 1.0
        # Last is partial
        assert abs(asks[3].size - 0.5) < 1e-10
        assert [a.level_index for a in asks] == [5, 6, 7, 8]

    def test_single_partial(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=2, effective_token=0.3,
            effective_usdc=0.0, order_sz=1.0,
        )
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 1
        assert abs(asks[0].size - 0.3) < 1e-10
        assert asks[0].level_index == 2

    def test_ask_prices_match_grid(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=3, effective_token=2.0,
            effective_usdc=0.0, order_sz=1.0,
        )
        asks = [o for o in orders if o.side == "sell"]
        for a in asks:
            assert a.price == grid.price_at_level(a.level_index)


# --- 4.3 Basic bid generation ---


class TestBidGeneration:
    def test_full_bids(self, grid: PricingGrid) -> None:
        # Give enough USDC for several full bids below boundary 5
        # Levels 4, 3, 2, 1, 0 are available
        usdc = sum(grid.price_at_level(i) * 1.0 for i in range(4, -1, -1))
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=0.0,
            effective_usdc=usdc, order_sz=1.0,
        )
        bids = [o for o in orders if o.side == "buy"]
        assert len(bids) == 5
        assert all(b.size == 1.0 for b in bids)
        # Descending level order
        assert [b.level_index for b in bids] == [4, 3, 2, 1, 0]

    def test_partial_bid_at_bottom(self, grid: PricingGrid) -> None:
        # Give just enough for 2 full bids plus some remainder
        cost_4 = grid.price_at_level(4) * 1.0
        cost_3 = grid.price_at_level(3) * 1.0
        extra = grid.price_at_level(2) * 0.5  # Half a bid at level 2
        usdc = cost_4 + cost_3 + extra
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=0.0,
            effective_usdc=usdc, order_sz=1.0,
        )
        bids = [o for o in orders if o.side == "buy"]
        assert len(bids) == 3
        assert bids[0].size == 1.0  # level 4
        assert bids[1].size == 1.0  # level 3
        assert abs(bids[2].size - 0.5) < 1e-6  # level 2 partial
        assert bids[2].level_index == 2

    def test_usdc_exhaustion(self, grid: PricingGrid) -> None:
        # Very little USDC — only partial at first level
        usdc = grid.price_at_level(4) * 0.1
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=0.0,
            effective_usdc=usdc, order_sz=1.0,
        )
        bids = [o for o in orders if o.side == "buy"]
        assert len(bids) == 1
        assert bids[0].level_index == 4
        assert abs(bids[0].size - 0.1) < 1e-6

    def test_bid_prices_match_grid(self, grid: PricingGrid) -> None:
        usdc = sum(grid.price_at_level(i) * 1.0 for i in range(3))
        orders = compute_desired_orders(
            grid=grid, boundary_level=4, effective_token=0.0,
            effective_usdc=usdc, order_sz=1.0,
        )
        bids = [o for o in orders if o.side == "buy"]
        for b in bids:
            assert b.price == grid.price_at_level(b.level_index)


# --- 4.4 Combined ask + bid generation ---


class TestCombinedGeneration:
    def test_typical_inventory(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=10, effective_token=3.0,
            effective_usdc=50.0, order_sz=1.0,
        )
        asks = [o for o in orders if o.side == "sell"]
        bids = [o for o in orders if o.side == "buy"]
        assert len(asks) == 3
        assert len(bids) > 0
        # Asks start at boundary, ascending
        assert asks[0].level_index == 10
        # Bids start just below boundary, descending
        assert bids[0].level_index == 9
        # No overlap
        ask_levels = {a.level_index for a in asks}
        bid_levels = {b.level_index for b in bids}
        assert ask_levels.isdisjoint(bid_levels)

    def test_contiguous_orders(self, grid: PricingGrid) -> None:
        """No gaps between highest bid and lowest ask."""
        orders = compute_desired_orders(
            grid=grid, boundary_level=10, effective_token=3.0,
            effective_usdc=100.0, order_sz=1.0,
        )
        asks = sorted([o for o in orders if o.side == "sell"], key=lambda o: o.level_index)
        bids = sorted(
            [o for o in orders if o.side == "buy"], key=lambda o: o.level_index, reverse=True
        )
        if asks and bids:
            lowest_ask = asks[0].level_index
            highest_bid = bids[0].level_index
            assert lowest_ask == highest_bid + 1

    def test_total_ask_size_equals_token_balance(self, grid: PricingGrid) -> None:
        token = 5.7
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=token,
            effective_usdc=0.0, order_sz=1.0,
        )
        total_ask_sz = sum(o.size for o in orders if o.side == "sell")
        assert abs(total_ask_sz - token) < 1e-10

    def test_total_bid_cost_within_usdc(self, grid: PricingGrid) -> None:
        usdc = 50.0
        orders = compute_desired_orders(
            grid=grid, boundary_level=10, effective_token=0.0,
            effective_usdc=usdc, order_sz=1.0,
        )
        total_cost = sum(o.price * o.size for o in orders if o.side == "buy")
        assert total_cost <= usdc + 1e-10


# --- 4.5 Empty and one-sided edge cases ---


class TestEdgeCases:
    def test_zero_tokens_bids_only(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=10, effective_token=0.0,
            effective_usdc=50.0, order_sz=1.0,
        )
        assert all(o.side == "buy" for o in orders)
        assert len(orders) > 0

    def test_zero_usdc_asks_only(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=3.0,
            effective_usdc=0.0, order_sz=1.0,
        )
        assert all(o.side == "sell" for o in orders)
        assert len(orders) == 3

    def test_both_zero_empty_list(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=0.0,
            effective_usdc=0.0, order_sz=1.0,
        )
        assert orders == []

    def test_order_sz_larger_than_balance(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=0.5,
            effective_usdc=0.0, order_sz=10.0,
        )
        assert len(orders) == 1
        assert orders[0].side == "sell"
        assert abs(orders[0].size - 0.5) < 1e-10


# --- 4.6 Minimum notional filtering ---


class TestMinNotionalFiltering:
    def test_partial_below_threshold(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=1.001,
            effective_usdc=0.0, order_sz=1.0, min_notional=0.01,
        )
        # The 0.001-size partial should be filtered (notional ~0.001)
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 1
        assert asks[0].size == 1.0

    def test_all_above_threshold(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=3.0,
            effective_usdc=50.0, order_sz=1.0, min_notional=0.01,
        )
        # All full orders should pass
        assert len(orders) > 0
        for o in orders:
            assert o.price * o.size >= 0.01

    def test_all_below_threshold(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=0.001,
            effective_usdc=0.001, order_sz=1.0, min_notional=10.0,
        )
        assert orders == []

    def test_bid_partial_filtered(self, grid: PricingGrid) -> None:
        # Give just a tiny bit of USDC, partial bid should be below min notional
        usdc = 0.001
        orders = compute_desired_orders(
            grid=grid, boundary_level=5, effective_token=0.0,
            effective_usdc=usdc, order_sz=1.0, min_notional=0.01,
        )
        assert orders == []


# --- 4.7 Grid overflow ---


class TestGridOverflow:
    def test_asks_truncated_at_grid_max(self, small_grid: PricingGrid) -> None:
        # 5-level grid (0-4), boundary at 3, 5 tokens → only 2 fit
        orders = compute_desired_orders(
            grid=small_grid, boundary_level=3, effective_token=5.0,
            effective_usdc=0.0, order_sz=1.0,
        )
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 2  # levels 3 and 4 only
        assert [a.level_index for a in asks] == [3, 4]

    def test_boundary_at_zero_no_bids(self, grid: PricingGrid) -> None:
        orders = compute_desired_orders(
            grid=grid, boundary_level=0, effective_token=3.0,
            effective_usdc=100.0, order_sz=1.0,
        )
        bids = [o for o in orders if o.side == "buy"]
        assert len(bids) == 0

    def test_boundary_at_max_no_asks(self, grid: PricingGrid) -> None:
        max_lvl = len(grid.levels) - 1
        # boundary beyond max — no asks possible
        orders = compute_desired_orders(
            grid=grid, boundary_level=max_lvl + 1,
            effective_token=3.0, effective_usdc=100.0, order_sz=1.0,
        )
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 0

    def test_partial_truncated_at_grid_max(self, small_grid: PricingGrid) -> None:
        # Boundary at 4 (last level), 1.5 tokens → 1 full at 4, partial at 5 (overflow)
        orders = compute_desired_orders(
            grid=small_grid, boundary_level=4, effective_token=1.5,
            effective_usdc=0.0, order_sz=1.0,
        )
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 1  # Only the full at level 4
        assert asks[0].level_index == 4
        assert asks[0].size == 1.0


# --- 4.8 Determinism ---


class TestDeterminism:
    def test_repeated_calls_identical(self, grid: PricingGrid) -> None:
        kwargs = dict(
            grid=grid, boundary_level=10, effective_token=5.5,
            effective_usdc=80.0, order_sz=1.0, min_notional=0.01,
        )
        result1 = compute_desired_orders(**kwargs)
        result2 = compute_desired_orders(**kwargs)
        assert result1 == result2

    def test_many_repeated_calls(self, grid: PricingGrid) -> None:
        kwargs = dict(
            grid=grid, boundary_level=7, effective_token=2.3,
            effective_usdc=30.0, order_sz=0.5,
        )
        results = [compute_desired_orders(**kwargs) for _ in range(100)]
        assert all(r == results[0] for r in results)


# --- 4.9 Boundary walk: fill sequence ---


class TestBoundaryWalk:
    def test_fill_walks_boundary_up(self, grid: PricingGrid) -> None:
        """Simulate selling tokens: boundary moves up the grid."""
        order_sz = 1.0
        total_token = 5.0
        usdc = 0.0
        boundary = 5

        # Initial state
        orders = compute_desired_orders(
            grid=grid, boundary_level=boundary, effective_token=total_token,
            effective_usdc=usdc, order_sz=order_sz,
        )
        assert orders[0].level_index == 5  # lowest ask at boundary

        # Simulate selling 1 token (ask fill at boundary)
        fill_px = grid.price_at_level(boundary)
        total_token -= order_sz
        usdc += fill_px * order_sz
        boundary += 1  # boundary moves up

        orders = compute_desired_orders(
            grid=grid, boundary_level=boundary, effective_token=total_token,
            effective_usdc=usdc, order_sz=order_sz,
        )
        asks = [o for o in orders if o.side == "sell"]
        bids = [o for o in orders if o.side == "buy"]
        assert asks[0].level_index == 6  # boundary shifted up
        assert bids[0].level_index == 5  # old boundary is now a bid

    def test_fill_walks_boundary_down(self, grid: PricingGrid) -> None:
        """Simulate buying tokens: boundary moves down the grid."""
        order_sz = 1.0
        total_token = 0.0
        boundary = 10
        # Give enough USDC for several bids
        usdc = sum(grid.price_at_level(i) * order_sz for i in range(boundary))

        orders = compute_desired_orders(
            grid=grid, boundary_level=boundary, effective_token=total_token,
            effective_usdc=usdc, order_sz=order_sz,
        )
        bids = [o for o in orders if o.side == "buy"]
        assert bids[0].level_index == 9  # highest bid

        # Simulate buying 1 token (bid fill at level 9)
        fill_px = grid.price_at_level(9)
        total_token += order_sz
        usdc -= fill_px * order_sz
        boundary -= 1  # boundary moves down

        orders = compute_desired_orders(
            grid=grid, boundary_level=boundary, effective_token=total_token,
            effective_usdc=usdc, order_sz=order_sz,
        )
        asks = [o for o in orders if o.side == "sell"]
        bids = [o for o in orders if o.side == "buy"]
        assert asks[0].level_index == 9  # old bid level is now lowest ask
        assert bids[0].level_index == 8  # bids moved down

    def test_round_trip(self, grid: PricingGrid) -> None:
        """Sell then buy back — boundary returns to original position."""
        order_sz = 1.0
        token = 5.0
        usdc = 0.0
        boundary = 5

        initial = compute_desired_orders(
            grid=grid, boundary_level=boundary, effective_token=token,
            effective_usdc=usdc, order_sz=order_sz,
        )

        # Sell one
        px = grid.price_at_level(boundary)
        token -= order_sz
        usdc += px * order_sz
        boundary += 1

        # Buy it back (bid fill at boundary - 1 = original boundary)
        px_buy = grid.price_at_level(boundary - 1)
        token += order_sz
        usdc -= px_buy * order_sz
        boundary -= 1

        final = compute_desired_orders(
            grid=grid, boundary_level=boundary, effective_token=token,
            effective_usdc=usdc, order_sz=order_sz,
        )

        # Same boundary, same token balance → same asks
        initial_asks = [o for o in initial if o.side == "sell"]
        final_asks = [o for o in final if o.side == "sell"]
        assert initial_asks == final_asks


# --- 4.10 No forbidden imports ---


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
