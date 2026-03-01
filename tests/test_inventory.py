"""Tests for the Inventory module."""

from __future__ import annotations

import math

import pytest

from pyperliquidity.inventory import Inventory, TrancheDecomposition
from pyperliquidity.pricing_grid import PricingGrid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inv(
    order_sz: float = 10.0,
    alloc_token: float = 100.0,
    alloc_usdc: float = 100.0,
    acct_token: float = 100.0,
    acct_usdc: float = 100.0,
) -> Inventory:
    return Inventory(
        order_sz=order_sz,
        allocated_token=alloc_token,
        allocated_usdc=alloc_usdc,
        account_token=acct_token,
        account_usdc=acct_usdc,
    )


def _make_grid(start_px: float = 1.0, n_orders: int = 20) -> PricingGrid:
    return PricingGrid(start_px=start_px, n_orders=n_orders)


# ===========================================================================
# 1. Data Structures & Effective Balance Invariant
# ===========================================================================


class TestEffectiveBalance:
    def test_account_exceeds_allocation(self) -> None:
        inv = _make_inv(acct_token=150.0, alloc_token=100.0)
        assert inv.effective_token == 100.0

    def test_account_below_allocation(self) -> None:
        inv = _make_inv(acct_token=80.0, alloc_token=100.0)
        assert inv.effective_token == 80.0

    def test_account_equals_allocation(self) -> None:
        inv = _make_inv(acct_token=100.0, alloc_token=100.0)
        assert inv.effective_token == 100.0

    def test_zero_account(self) -> None:
        inv = _make_inv(acct_token=0.0, alloc_token=100.0)
        assert inv.effective_token == 0.0

    def test_usdc_effective(self) -> None:
        inv = _make_inv(acct_usdc=50.0, alloc_usdc=80.0)
        assert inv.effective_usdc == 50.0

    def test_usdc_capped_by_allocation(self) -> None:
        inv = _make_inv(acct_usdc=200.0, alloc_usdc=80.0)
        assert inv.effective_usdc == 80.0


# ===========================================================================
# 2. Allocation Management
# ===========================================================================


class TestAllocationUpdate:
    def test_decrease_below_account(self) -> None:
        inv = _make_inv(acct_token=100.0, alloc_token=150.0)
        assert inv.effective_token == 100.0
        inv.update_allocation(token=80.0, usdc=inv.allocated_usdc)
        assert inv.allocated_token == 80.0
        assert inv.effective_token == 80.0

    def test_increase_above_account(self) -> None:
        inv = _make_inv(acct_token=100.0, alloc_token=80.0)
        assert inv.effective_token == 80.0
        inv.update_allocation(token=150.0, usdc=inv.allocated_usdc)
        assert inv.allocated_token == 150.0
        assert inv.effective_token == 100.0  # still capped by account

    def test_equal_to_account(self) -> None:
        inv = _make_inv(acct_token=100.0, alloc_token=50.0)
        inv.update_allocation(token=100.0, usdc=inv.allocated_usdc)
        assert inv.effective_token == 100.0

    def test_usdc_allocation_update(self) -> None:
        inv = _make_inv(acct_usdc=100.0, alloc_usdc=200.0)
        inv.update_allocation(token=inv.allocated_token, usdc=60.0)
        assert inv.effective_usdc == 60.0


# ===========================================================================
# 3. Ask-Side Tranche Decomposition
# ===========================================================================


class TestAskTranches:
    def test_even_division(self) -> None:
        inv = _make_inv(order_sz=10.0, acct_token=30.0, alloc_token=30.0)
        t = inv.compute_ask_tranches()
        assert t.n_full == 3
        assert t.partial_sz == pytest.approx(0.0)

    def test_remainder_partial(self) -> None:
        inv = _make_inv(order_sz=10.0, acct_token=25.0, alloc_token=25.0)
        t = inv.compute_ask_tranches()
        assert t.n_full == 2
        assert t.partial_sz == pytest.approx(5.0)

    def test_less_than_one_tranche(self) -> None:
        inv = _make_inv(order_sz=10.0, acct_token=3.0, alloc_token=3.0)
        t = inv.compute_ask_tranches()
        assert t.n_full == 0
        assert t.partial_sz == pytest.approx(3.0)

    def test_zero_balance(self) -> None:
        inv = _make_inv(order_sz=10.0, acct_token=0.0, alloc_token=100.0)
        t = inv.compute_ask_tranches()
        assert t.n_full == 0
        assert t.partial_sz == pytest.approx(0.0)

    def test_invariant_n_full_times_order_sz_plus_partial(self) -> None:
        for token in [0.0, 3.7, 10.0, 25.0, 100.0, 99.99]:
            inv = _make_inv(order_sz=10.0, acct_token=token, alloc_token=token)
            t = inv.compute_ask_tranches()
            reconstructed = t.n_full * inv.order_sz + t.partial_sz
            assert reconstructed == pytest.approx(inv.effective_token, abs=1e-10)

    def test_effective_capped_by_allocation(self) -> None:
        inv = _make_inv(order_sz=10.0, acct_token=100.0, alloc_token=25.0)
        t = inv.compute_ask_tranches()
        assert t.n_full == 2
        assert t.partial_sz == pytest.approx(5.0)

    def test_levels_empty(self) -> None:
        inv = _make_inv(order_sz=10.0, acct_token=30.0, alloc_token=30.0)
        t = inv.compute_ask_tranches()
        assert t.levels == ()


# ===========================================================================
# 4. Bid-Side Tranche Decomposition
# ===========================================================================


class TestBidTranches:
    @pytest.fixture()
    def grid(self) -> PricingGrid:
        return _make_grid(start_px=1.0, n_orders=20)

    def test_multiple_full_bids_with_partial(self, grid: PricingGrid) -> None:
        # Grid level 9 is the boundary; bids at levels 8, 7, 6, ...
        inv = _make_inv(order_sz=10.0, acct_usdc=25.0, alloc_usdc=25.0)
        t = inv.compute_bid_tranches(grid, boundary_level=10)
        assert t.n_full == 2
        assert t.partial_sz > 0.0
        # Levels should be descending from boundary - 1
        assert t.levels[0] == 9
        assert t.levels[1] == 8
        assert len(t.levels) == 3  # 2 full + 1 partial

    def test_insufficient_for_one_full_bid(self, grid: PricingGrid) -> None:
        inv = _make_inv(order_sz=10.0, acct_usdc=5.0, alloc_usdc=5.0)
        t = inv.compute_bid_tranches(grid, boundary_level=10)
        assert t.n_full == 0
        assert t.partial_sz > 0.0
        assert len(t.levels) == 1

    def test_zero_usdc(self, grid: PricingGrid) -> None:
        inv = _make_inv(order_sz=10.0, acct_usdc=0.0, alloc_usdc=100.0)
        t = inv.compute_bid_tranches(grid, boundary_level=10)
        assert t.n_full == 0
        assert t.partial_sz == 0.0

    def test_boundary_at_grid_edge_zero(self, grid: PricingGrid) -> None:
        # Boundary at level 0 means no room for bids below
        inv = _make_inv(order_sz=10.0, acct_usdc=100.0, alloc_usdc=100.0)
        t = inv.compute_bid_tranches(grid, boundary_level=0)
        assert t.n_full == 0
        assert t.partial_sz == 0.0
        assert t.levels == ()

    def test_boundary_at_level_1(self, grid: PricingGrid) -> None:
        # Only level 0 available for bids
        px0 = grid.price_at_level(0)
        inv = _make_inv(order_sz=10.0, acct_usdc=px0 * 10.0, alloc_usdc=px0 * 10.0)
        t = inv.compute_bid_tranches(grid, boundary_level=1)
        assert t.n_full == 1
        assert t.partial_sz == pytest.approx(0.0)
        assert t.levels == (0,)

    def test_usdc_exhausted_exactly_at_level(self, grid: PricingGrid) -> None:
        # Give exactly enough for 2 levels
        px_9 = grid.price_at_level(9)
        px_8 = grid.price_at_level(8)
        exact_usdc = (px_9 + px_8) * 10.0
        inv = _make_inv(order_sz=10.0, acct_usdc=exact_usdc, alloc_usdc=exact_usdc)
        t = inv.compute_bid_tranches(grid, boundary_level=10)
        assert t.n_full == 2
        assert t.partial_sz == pytest.approx(0.0, abs=1e-8)

    def test_levels_descending(self, grid: PricingGrid) -> None:
        inv = _make_inv(order_sz=10.0, acct_usdc=1000.0, alloc_usdc=1000.0)
        t = inv.compute_bid_tranches(grid, boundary_level=10)
        full_levels = t.levels[: t.n_full]
        for i in range(len(full_levels) - 1):
            assert full_levels[i] > full_levels[i + 1]

    def test_effective_usdc_capped(self, grid: PricingGrid) -> None:
        inv = _make_inv(order_sz=10.0, acct_usdc=500.0, alloc_usdc=25.0)
        t = inv.compute_bid_tranches(grid, boundary_level=10)
        # Same result as 25.0 USDC
        inv2 = _make_inv(order_sz=10.0, acct_usdc=25.0, alloc_usdc=25.0)
        t2 = inv2.compute_bid_tranches(grid, boundary_level=10)
        assert t.n_full == t2.n_full
        assert t.partial_sz == pytest.approx(t2.partial_sz)


# ===========================================================================
# 5. Fill Event Handlers
# ===========================================================================


class TestFillEvents:
    def test_ask_fill_basic(self) -> None:
        inv = _make_inv(acct_token=100.0, alloc_token=100.0, acct_usdc=0.0, alloc_usdc=200.0)
        inv.on_ask_fill(px=1.5, sz=10.0)
        assert inv.account_token == pytest.approx(90.0)
        assert inv.account_usdc == pytest.approx(15.0)
        assert inv.effective_token == pytest.approx(90.0)
        assert inv.effective_usdc == pytest.approx(15.0)

    def test_bid_fill_basic(self) -> None:
        inv = _make_inv(acct_token=0.0, alloc_token=200.0, acct_usdc=100.0, alloc_usdc=100.0)
        inv.on_bid_fill(px=1.5, sz=10.0)
        assert inv.account_token == pytest.approx(10.0)
        assert inv.account_usdc == pytest.approx(85.0)
        assert inv.effective_token == pytest.approx(10.0)
        assert inv.effective_usdc == pytest.approx(85.0)

    def test_fill_pushes_account_above_allocation(self) -> None:
        inv = _make_inv(acct_token=95.0, alloc_token=100.0, acct_usdc=200.0, alloc_usdc=200.0)
        inv.on_bid_fill(px=1.0, sz=10.0)
        assert inv.account_token == pytest.approx(105.0)
        assert inv.effective_token == pytest.approx(100.0)  # clamped

    def test_fill_sequence_shifting_boundary(self) -> None:
        grid = _make_grid(start_px=1.0, n_orders=20)
        inv = _make_inv(
            order_sz=10.0,
            acct_token=50.0, alloc_token=50.0,
            acct_usdc=50.0, alloc_usdc=50.0,
        )
        # Initial state
        asks_before = inv.compute_ask_tranches()
        assert asks_before.n_full == 5

        # Sell 20 tokens (2 ask fills)
        inv.on_ask_fill(px=1.05, sz=10.0)
        inv.on_ask_fill(px=1.06, sz=10.0)

        asks_after = inv.compute_ask_tranches()
        assert asks_after.n_full == 3
        # account_usdc increased but effective is capped by allocation
        assert inv.account_usdc > 50.0
        assert inv.effective_usdc == 50.0  # clamped to allocation


# ===========================================================================
# 6. Balance Reconciliation
# ===========================================================================


class TestBalanceReconciliation:
    def test_account_above_allocation(self) -> None:
        inv = _make_inv(alloc_token=100.0, alloc_usdc=180.0)
        inv.on_balance_update(token=150.0, usdc=200.0)
        assert inv.account_token == 150.0
        assert inv.effective_token == 100.0
        assert inv.account_usdc == 200.0
        assert inv.effective_usdc == 180.0

    def test_account_below_allocation(self) -> None:
        inv = _make_inv(alloc_token=100.0, alloc_usdc=200.0)
        inv.on_balance_update(token=50.0, usdc=100.0)
        assert inv.account_token == 50.0
        assert inv.effective_token == 50.0
        assert inv.account_usdc == 100.0
        assert inv.effective_usdc == 100.0

    def test_both_sides_mixed(self) -> None:
        inv = _make_inv(alloc_token=80.0, alloc_usdc=150.0)
        inv.on_balance_update(token=100.0, usdc=120.0)
        # token above alloc, usdc below alloc
        assert inv.effective_token == 80.0
        assert inv.effective_usdc == 120.0

    def test_zero_balances(self) -> None:
        inv = _make_inv(alloc_token=100.0, alloc_usdc=100.0)
        inv.on_balance_update(token=0.0, usdc=0.0)
        assert inv.effective_token == 0.0
        assert inv.effective_usdc == 0.0


# ===========================================================================
# 7. Edge Cases and Integration
# ===========================================================================


class TestEdgeCases:
    def test_zero_token_all_bids(self) -> None:
        grid = _make_grid(start_px=1.0, n_orders=20)
        inv = _make_inv(
            order_sz=10.0,
            acct_token=0.0, alloc_token=100.0,
            acct_usdc=100.0, alloc_usdc=100.0,
        )
        asks = inv.compute_ask_tranches()
        assert asks.n_full == 0
        assert asks.partial_sz == 0.0

        bids = inv.compute_bid_tranches(grid, boundary_level=10)
        assert bids.n_full > 0

    def test_zero_usdc_all_asks(self) -> None:
        grid = _make_grid(start_px=1.0, n_orders=20)
        inv = _make_inv(
            order_sz=10.0,
            acct_token=50.0, alloc_token=50.0,
            acct_usdc=0.0, alloc_usdc=100.0,
        )
        asks = inv.compute_ask_tranches()
        assert asks.n_full == 5

        bids = inv.compute_bid_tranches(grid, boundary_level=10)
        assert bids.n_full == 0
        assert bids.partial_sz == 0.0

    def test_effective_never_exceeds_min_after_construction(self) -> None:
        for at, al in [(100, 50), (50, 100), (0, 100), (100, 0)]:
            inv = _make_inv(acct_token=float(at), alloc_token=float(al))
            assert inv.effective_token <= min(inv.allocated_token, inv.account_token)

    def test_effective_never_exceeds_min_after_fill(self) -> None:
        inv = _make_inv(
            acct_token=50.0, alloc_token=60.0,
            acct_usdc=100.0, alloc_usdc=100.0,
        )
        for _ in range(10):
            inv.on_bid_fill(px=1.0, sz=5.0)
            assert inv.effective_token <= min(inv.allocated_token, inv.account_token)
            assert inv.effective_usdc <= min(inv.allocated_usdc, inv.account_usdc)

    def test_effective_never_exceeds_min_after_ask_fill(self) -> None:
        inv = _make_inv(
            acct_token=100.0, alloc_token=100.0,
            acct_usdc=0.0, alloc_usdc=50.0,
        )
        for _ in range(5):
            inv.on_ask_fill(px=1.0, sz=10.0)
            assert inv.effective_token <= min(inv.allocated_token, inv.account_token)
            assert inv.effective_usdc <= min(inv.allocated_usdc, inv.account_usdc)

    def test_effective_never_exceeds_min_after_reconciliation(self) -> None:
        inv = _make_inv(alloc_token=80.0, alloc_usdc=80.0)
        for t, u in [(200, 200), (50, 50), (0, 0), (80, 80), (1000, 10)]:
            inv.on_balance_update(token=float(t), usdc=float(u))
            assert inv.effective_token <= min(inv.allocated_token, inv.account_token)
            assert inv.effective_usdc <= min(inv.allocated_usdc, inv.account_usdc)

    def test_effective_never_exceeds_min_after_allocation_update(self) -> None:
        inv = _make_inv(acct_token=100.0, acct_usdc=100.0)
        for al_t, al_u in [(50, 50), (200, 200), (0, 0), (100, 100)]:
            inv.update_allocation(token=float(al_t), usdc=float(al_u))
            assert inv.effective_token <= min(inv.allocated_token, inv.account_token)
            assert inv.effective_usdc <= min(inv.allocated_usdc, inv.account_usdc)


class TestTrancheDecompositionDataclass:
    def test_frozen(self) -> None:
        t = TrancheDecomposition(n_full=3, partial_sz=1.5, levels=(0, 1, 2))
        with pytest.raises(AttributeError):
            t.n_full = 5  # type: ignore[misc]

    def test_fields(self) -> None:
        t = TrancheDecomposition(n_full=2, partial_sz=3.0, levels=(5, 4))
        assert t.n_full == 2
        assert t.partial_sz == 3.0
        assert t.levels == (5, 4)
