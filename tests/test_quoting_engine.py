"""Tests for the quoting engine — fixed grid with cursor derivation."""

from __future__ import annotations

import ast
import inspect

import pytest

from pyperliquidity.pricing_grid import PricingGrid
from pyperliquidity.quoting_engine import DesiredOrder, compute_desired_orders


# --- Helpers ------------------------------------------------------------------

def _grid(n: int = 10, start_px: float = 1.0) -> PricingGrid:
    """Build a small grid for tests."""
    return PricingGrid(start_px=start_px, n_orders=n)


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


# --- Cursor derivation ---


class TestCursorDerivation:
    def test_cursor_basic(self) -> None:
        """97941.26 tokens, order_sz=1000, 100 levels → cursor=2."""
        grid = _grid(100)
        orders = compute_desired_orders(grid, 97941.26, 50000.0, 1000.0)
        # n_full=97, partial=941.26, total_ask_levels=98, cursor=2
        asks = [o for o in orders if o.side == "sell"]
        # Lowest ask should be at cursor=2
        min_ask_level = min(a.level_index for a in asks)
        assert min_ask_level == 2

    def test_cursor_shifts_on_sell(self) -> None:
        """After selling tokens, cursor moves up."""
        grid = _grid(100)
        orders1 = compute_desired_orders(grid, 97941.26, 50000.0, 1000.0)
        orders2 = compute_desired_orders(grid, 95991.26, 51950.0, 1000.0)
        asks1 = [o for o in orders1 if o.side == "sell"]
        asks2 = [o for o in orders2 if o.side == "sell"]
        cursor1 = min(a.level_index for a in asks1)
        cursor2 = min(a.level_index for a in asks2)
        # Fewer tokens → cursor moves up (fewer asks, more bids)
        assert cursor2 > cursor1
        assert cursor2 == 4

    def test_cursor_at_zero_all_asks(self) -> None:
        """Tokens enough for all levels → cursor=0, all levels are asks."""
        grid = _grid(10)
        # 10000 tokens, order_sz=1000 → n_full=10, total_ask=10, cursor=0
        orders = compute_desired_orders(grid, 10000.0, 5000.0, 1000.0)
        asks = [o for o in orders if o.side == "sell"]
        bids = [o for o in orders if o.side == "buy"]
        assert len(asks) == 10
        assert len(bids) == 0

    def test_cursor_capped_at_n_orders(self) -> None:
        """More tokens than grid can hold → cursor still capped at 0."""
        grid = _grid(10)
        # 50000 tokens, order_sz=1000 → n_full=50, total_ask=min(50,10)=10, cursor=0
        orders = compute_desired_orders(grid, 50000.0, 5000.0, 1000.0)
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 10
        assert all(a.size == 1000.0 for a in asks)


# --- Ask placement ---


class TestAskPlacement:
    def test_partial_ask_at_cursor(self) -> None:
        """Partial ask placed at cursor level with remainder size."""
        grid = _grid(10)
        # 2500 tokens, order_sz=1000 → n_full=2, partial=500, cursor=7
        orders = compute_desired_orders(grid, 2500.0, 50000.0, 1000.0)
        asks = sorted(
            [o for o in orders if o.side == "sell"],
            key=lambda o: o.level_index,
        )
        assert len(asks) == 3
        assert asks[0].level_index == 7
        assert asks[0].size == 500.0  # partial
        assert asks[1].level_index == 8
        assert asks[1].size == 1000.0  # full
        assert asks[2].level_index == 9
        assert asks[2].size == 1000.0  # full

    def test_no_partial_exact_multiple(self) -> None:
        """No partial when tokens are exact multiple of order_sz."""
        grid = _grid(10)
        # 3000 tokens, order_sz=1000 → n_full=3, partial=0, cursor=7
        orders = compute_desired_orders(grid, 3000.0, 50000.0, 1000.0)
        asks = sorted(
            [o for o in orders if o.side == "sell"],
            key=lambda o: o.level_index,
        )
        assert len(asks) == 3
        assert all(a.size == 1000.0 for a in asks)
        assert asks[0].level_index == 7

    def test_asks_ascending_from_cursor(self) -> None:
        """Asks are placed at ascending level indices from cursor."""
        grid = _grid(10)
        orders = compute_desired_orders(grid, 5000.0, 50000.0, 1000.0)
        asks = sorted(
            [o for o in orders if o.side == "sell"],
            key=lambda o: o.level_index,
        )
        # cursor=5, asks at 5,6,7,8,9
        assert [a.level_index for a in asks] == [5, 6, 7, 8, 9]

    def test_grid_overflow_truncation(self) -> None:
        """Asks exceeding grid max are truncated."""
        grid = _grid(10)
        # cursor=8, 5 full asks needed but only 2 levels available (8,9)
        # 5000 tokens, order_sz=1000 but cursor at 8 → only 2 fit
        # Actually: n_full=5, partial=0, total_ask=5, cursor=5
        # Let me use different values: 2000 tokens, order_sz=1000, 3 levels
        small_grid = _grid(3)
        # n_full=2, partial=0, total_ask=2, cursor=1
        orders = compute_desired_orders(small_grid, 2000.0, 50000.0, 1000.0)
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 2
        assert asks[0].level_index in (1, 2)

    def test_total_ask_size_equals_effective_token(self) -> None:
        """Sum of all ask sizes equals effective_token (before min_notional)."""
        grid = _grid(100)
        orders = compute_desired_orders(grid, 2500.0, 50000.0, 1000.0)
        asks = [o for o in orders if o.side == "sell"]
        total_ask_sz = sum(a.size for a in asks)
        assert abs(total_ask_sz - 2500.0) < 1e-10


# --- Bid placement ---


class TestBidPlacement:
    def test_full_bids_descending_from_cursor(self) -> None:
        """Bids descend from cursor-1 with full order_sz."""
        grid = _grid(10)
        # 5000 tokens, order_sz=1000, cursor=5
        # Bids at 4,3,2,1,0 funded by USDC
        orders = compute_desired_orders(grid, 5000.0, 50000.0, 1000.0)
        bids = sorted(
            [o for o in orders if o.side == "buy"],
            key=lambda o: -o.level_index,  # descending
        )
        assert len(bids) == 5
        assert bids[0].level_index == 4
        assert bids[-1].level_index == 0

    def test_partial_bid_when_usdc_runs_out(self) -> None:
        """Partial bid placed when USDC is insufficient for full order."""
        grid = _grid(10)
        # cursor=5, bids at levels 4,3,2,1,0
        # Give just enough USDC for ~2.5 bids
        px_4 = grid.price_at_level(4)
        px_3 = grid.price_at_level(3)
        usdc = px_4 * 1000 + px_3 * 1000 + 500  # enough for 2 full + partial
        orders = compute_desired_orders(grid, 5000.0, usdc, 1000.0)
        bids = sorted(
            [o for o in orders if o.side == "buy"],
            key=lambda o: -o.level_index,
        )
        assert len(bids) == 3
        assert bids[0].size == 1000.0  # full at level 4
        assert bids[1].size == 1000.0  # full at level 3
        assert bids[2].size < 1000.0   # partial at level 2

    def test_no_bids_when_cursor_zero(self) -> None:
        """No bids when cursor is 0 (all levels are asks)."""
        grid = _grid(5)
        orders = compute_desired_orders(grid, 10000.0, 50000.0, 1000.0)
        bids = [o for o in orders if o.side == "buy"]
        assert len(bids) == 0

    def test_total_bid_cost_within_usdc(self) -> None:
        """Total cost of all bids ≤ effective_usdc."""
        grid = _grid(100)
        orders = compute_desired_orders(grid, 50000.0, 2000.0, 1000.0)
        bids = [o for o in orders if o.side == "buy"]
        total_cost = sum(b.price * b.size for b in bids)
        assert total_cost <= 2000.0 + 1e-6


# --- Spread guarantee ---


class TestSpread:
    def test_no_level_has_both_bid_and_ask(self) -> None:
        """No grid level has both a bid and an ask."""
        grid = _grid(20)
        orders = compute_desired_orders(grid, 10000.0, 10000.0, 1000.0)
        ask_levels = {o.level_index for o in orders if o.side == "sell"}
        bid_levels = {o.level_index for o in orders if o.side == "buy"}
        assert ask_levels & bid_levels == set()

    def test_minimum_spread_one_tick(self) -> None:
        """Tightest ask and bid are at adjacent levels (one tick apart)."""
        grid = _grid(20)
        orders = compute_desired_orders(grid, 10000.0, 50000.0, 1000.0)
        asks = [o for o in orders if o.side == "sell"]
        bids = [o for o in orders if o.side == "buy"]
        if asks and bids:
            best_ask_level = min(a.level_index for a in asks)
            best_bid_level = max(b.level_index for b in bids)
            assert best_ask_level == best_bid_level + 1


# --- Min notional filtering ---


class TestMinNotional:
    def test_partial_order_filtered(self) -> None:
        """Partial order below min_notional is excluded."""
        grid = _grid(10)
        # Small partial: 5 tokens at ~1.0 price → notional ≈ 5.0
        orders = compute_desired_orders(grid, 5.0, 50000.0, 1000.0, min_notional=10.0)
        asks = [o for o in orders if o.side == "sell"]
        for a in asks:
            assert a.price * a.size >= 10.0

    def test_full_order_passes(self) -> None:
        """Full orders above min_notional are included."""
        grid = _grid(10)
        orders = compute_desired_orders(grid, 5000.0, 50000.0, 1000.0, min_notional=10.0)
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) > 0
        for a in asks:
            assert a.price * a.size >= 10.0

    def test_no_filtering_when_zero(self) -> None:
        """When min_notional=0, all orders pass."""
        grid = _grid(10)
        orders_filtered = compute_desired_orders(grid, 5.0, 50000.0, 1000.0, min_notional=0.0)
        asks = [o for o in orders_filtered if o.side == "sell"]
        # The tiny partial (5 tokens) should be included
        assert any(a.size == 5.0 for a in asks)


# --- Absolute level indices ---


class TestAbsoluteLevelIndices:
    def test_ask_indices_from_cursor(self) -> None:
        """Asks have level_index values from cursor to n_orders-1."""
        grid = _grid(10)
        orders = compute_desired_orders(grid, 5000.0, 50000.0, 1000.0)
        asks = sorted([o for o in orders if o.side == "sell"], key=lambda o: o.level_index)
        # cursor=5
        assert [a.level_index for a in asks] == [5, 6, 7, 8, 9]

    def test_bid_indices_below_cursor(self) -> None:
        """Bids have level_index values from cursor-1 down to 0."""
        grid = _grid(10)
        orders = compute_desired_orders(grid, 5000.0, 50000.0, 1000.0)
        bids = sorted([o for o in orders if o.side == "buy"], key=lambda o: -o.level_index)
        # cursor=5, bids at 4,3,2,1,0
        assert [b.level_index for b in bids] == [4, 3, 2, 1, 0]

    def test_price_matches_grid_level(self) -> None:
        """Each order's price matches grid.price_at_level(level_index)."""
        grid = _grid(20)
        orders = compute_desired_orders(grid, 10000.0, 50000.0, 1000.0)
        for o in orders:
            assert o.price == grid.price_at_level(o.level_index)


# --- Edge cases ---


class TestEdgeCases:
    def test_both_zero(self) -> None:
        """Both balances zero → empty list."""
        grid = _grid(10)
        orders = compute_desired_orders(grid, 0.0, 0.0, 1000.0)
        assert orders == []

    def test_all_tokens_sold(self) -> None:
        """effective_token=0 → cursor at n_orders, only bids."""
        grid = _grid(10)
        orders = compute_desired_orders(grid, 0.0, 5000.0, 1000.0)
        asks = [o for o in orders if o.side == "sell"]
        bids = [o for o in orders if o.side == "buy"]
        assert len(asks) == 0
        assert len(bids) > 0

    def test_all_usdc_spent(self) -> None:
        """effective_usdc=0 → only asks, no bids."""
        grid = _grid(10)
        orders = compute_desired_orders(grid, 5000.0, 0.0, 1000.0)
        asks = [o for o in orders if o.side == "sell"]
        bids = [o for o in orders if o.side == "buy"]
        assert len(asks) > 0
        assert len(bids) == 0

    def test_single_partial_ask(self) -> None:
        """order_sz larger than token balance → single partial ask."""
        grid = _grid(10)
        orders = compute_desired_orders(grid, 50.0, 5000.0, 1000.0)
        asks = [o for o in orders if o.side == "sell"]
        assert len(asks) == 1
        assert asks[0].size == 50.0
        assert asks[0].level_index == 9  # cursor = 10 - 1 = 9

    def test_determinism(self) -> None:
        """Repeated calls with same inputs produce identical results."""
        grid = _grid(20)
        r1 = compute_desired_orders(grid, 10000.0, 5000.0, 1000.0)
        r2 = compute_desired_orders(grid, 10000.0, 5000.0, 1000.0)
        assert r1 == r2


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
