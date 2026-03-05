"""Tests for the Inventory module."""

from __future__ import annotations

import pytest

from pyperliquidity.inventory import Inventory

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
# 3. Fill Event Handlers
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

    def test_fill_sequence(self) -> None:
        inv = _make_inv(
            order_sz=10.0,
            acct_token=50.0, alloc_token=50.0,
            acct_usdc=50.0, alloc_usdc=50.0,
        )

        # Sell 20 tokens (2 ask fills)
        inv.on_ask_fill(px=1.05, sz=10.0)
        inv.on_ask_fill(px=1.06, sz=10.0)

        assert inv.effective_token == pytest.approx(30.0)
        # account_usdc increased but effective is capped by allocation
        assert inv.account_usdc > 50.0
        assert inv.effective_usdc == 50.0  # clamped to allocation


# ===========================================================================
# 4. Balance Reconciliation
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
# 5. Edge Cases and Integration
# ===========================================================================


class TestEdgeCases:
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
