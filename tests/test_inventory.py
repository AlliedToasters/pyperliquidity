"""Tests for the Inventory module — virtual isolated balances."""

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
# 1. Virtual Balance Initialization
# ===========================================================================


class TestVirtualBalanceInit:
    def test_virtual_starts_at_allocation(self) -> None:
        inv = _make_inv(alloc_token=50.0, alloc_usdc=1250.0)
        assert inv.virtual_token == 50.0
        assert inv.virtual_usdc == 1250.0

    def test_effective_is_min_virtual_account(self) -> None:
        """When account >> allocation, effective = virtual (= allocation)."""
        inv = _make_inv(
            alloc_token=5.0, alloc_usdc=1250.0,
            acct_token=81.0, acct_usdc=489_000.0,
        )
        assert inv.effective_token == 5.0
        assert inv.effective_usdc == 1250.0

    def test_effective_capped_by_account_when_account_lower(self) -> None:
        inv = _make_inv(
            alloc_token=100.0, alloc_usdc=1000.0,
            acct_token=30.0, acct_usdc=500.0,
        )
        assert inv.effective_token == 30.0
        assert inv.effective_usdc == 500.0


# ===========================================================================
# 2. Fills Move Virtual Balances (Core Fix)
# ===========================================================================


class TestFillsMovePricing:
    def test_ask_fill_moves_mid(self) -> None:
        """The whole point: fills must change effective balances → mid moves."""
        inv = _make_inv(
            alloc_token=5.0, alloc_usdc=1250.0,
            acct_token=81.0, acct_usdc=489_000.0,
        )
        mid_before = inv.effective_usdc / inv.effective_token  # 250.0
        inv.on_ask_fill(px=250.75, sz=1.0)
        mid_after = inv.effective_usdc / inv.effective_token
        assert mid_after > mid_before  # sold tokens → more USDC, less token → higher mid

    def test_bid_fill_moves_mid(self) -> None:
        inv = _make_inv(
            alloc_token=5.0, alloc_usdc=1250.0,
            acct_token=81.0, acct_usdc=489_000.0,
        )
        mid_before = inv.effective_usdc / inv.effective_token
        inv.on_bid_fill(px=249.25, sz=1.0)
        mid_after = inv.effective_usdc / inv.effective_token
        assert mid_after < mid_before  # bought tokens → less USDC, more token → lower mid

    def test_ask_fill_virtual_balances(self) -> None:
        inv = _make_inv(
            alloc_token=5.0, alloc_usdc=1250.0,
            acct_token=81.0, acct_usdc=489_000.0,
        )
        inv.on_ask_fill(px=250.75, sz=1.0)
        assert inv.virtual_token == pytest.approx(4.0)
        assert inv.virtual_usdc == pytest.approx(1500.75)
        assert inv.effective_token == pytest.approx(4.0)
        assert inv.effective_usdc == pytest.approx(1500.75)

    def test_bid_fill_virtual_balances(self) -> None:
        inv = _make_inv(
            alloc_token=5.0, alloc_usdc=1250.0,
            acct_token=81.0, acct_usdc=489_000.0,
        )
        inv.on_bid_fill(px=249.25, sz=1.0)
        assert inv.virtual_token == pytest.approx(6.0)
        assert inv.virtual_usdc == pytest.approx(1000.75)
        assert inv.effective_token == pytest.approx(6.0)
        assert inv.effective_usdc == pytest.approx(1000.75)


# ===========================================================================
# 3. Fee Accounting
# ===========================================================================


class TestFeeAccounting:
    def test_ask_fill_usdc_fee(self) -> None:
        inv = _make_inv(alloc_token=10.0, alloc_usdc=0.0, acct_token=10.0, acct_usdc=500.0)
        inv.on_ask_fill(px=100.0, sz=1.0, fee=0.05, fee_token="USDC")
        assert inv.virtual_token == pytest.approx(9.0)
        assert inv.virtual_usdc == pytest.approx(99.95)  # 100 - 0.05

    def test_bid_fill_usdc_fee(self) -> None:
        inv = _make_inv(alloc_token=0.0, alloc_usdc=500.0, acct_token=100.0, acct_usdc=500.0)
        inv.on_bid_fill(px=100.0, sz=1.0, fee=0.05, fee_token="USDC")
        assert inv.virtual_token == pytest.approx(1.0)
        assert inv.virtual_usdc == pytest.approx(399.95)  # 500 - 100 - 0.05

    def test_ask_fill_token_fee(self) -> None:
        inv = _make_inv(alloc_token=10.0, alloc_usdc=0.0, acct_token=10.0, acct_usdc=500.0)
        inv.on_ask_fill(px=100.0, sz=1.0, fee=0.01, fee_token="THC")
        assert inv.virtual_token == pytest.approx(8.99)  # 10 - 1.0 - 0.01
        assert inv.virtual_usdc == pytest.approx(100.0)  # no USDC fee deducted

    def test_bid_fill_token_fee(self) -> None:
        inv = _make_inv(alloc_token=0.0, alloc_usdc=500.0, acct_token=100.0, acct_usdc=500.0)
        inv.on_bid_fill(px=100.0, sz=1.0, fee=0.01, fee_token="THC")
        assert inv.virtual_token == pytest.approx(0.99)  # 1.0 - 0.01
        assert inv.virtual_usdc == pytest.approx(400.0)

    def test_zero_fee_default(self) -> None:
        """Fills without fee args should work (backwards compatible)."""
        inv = _make_inv(alloc_token=10.0, alloc_usdc=0.0, acct_token=10.0, acct_usdc=500.0)
        inv.on_ask_fill(px=100.0, sz=1.0)
        assert inv.virtual_token == pytest.approx(9.0)
        assert inv.virtual_usdc == pytest.approx(100.0)


# ===========================================================================
# 4. Balance Reconciliation Does NOT Reset Virtual
# ===========================================================================


class TestBalanceReconciliation:
    def test_balance_update_does_not_reset_virtual(self) -> None:
        """Critical: reconciliation must not touch virtual balances."""
        inv = _make_inv(
            alloc_token=5.0, alloc_usdc=1250.0,
            acct_token=81.0, acct_usdc=489_000.0,
        )
        # Simulate a fill
        inv.on_ask_fill(px=250.0, sz=1.0)
        assert inv.virtual_token == pytest.approx(4.0)
        assert inv.virtual_usdc == pytest.approx(1500.0)

        # Reconciliation updates account balances
        inv.on_balance_update(token=80.0, usdc=489_250.0)
        # Virtual must be UNCHANGED
        assert inv.virtual_token == pytest.approx(4.0)
        assert inv.virtual_usdc == pytest.approx(1500.0)
        # Effective = min(virtual, account) — virtual is lower
        assert inv.effective_token == pytest.approx(4.0)
        assert inv.effective_usdc == pytest.approx(1500.0)

    def test_balance_update_caps_effective_when_account_low(self) -> None:
        inv = _make_inv(
            alloc_token=5.0, alloc_usdc=1250.0,
            acct_token=81.0, acct_usdc=489_000.0,
        )
        # Account drops below virtual (e.g., other strategy spent funds)
        inv.on_balance_update(token=3.0, usdc=800.0)
        assert inv.virtual_token == pytest.approx(5.0)  # unchanged
        assert inv.virtual_usdc == pytest.approx(1250.0)  # unchanged
        assert inv.effective_token == pytest.approx(3.0)  # capped by account
        assert inv.effective_usdc == pytest.approx(800.0)

    def test_zero_account_balances(self) -> None:
        inv = _make_inv(alloc_token=100.0, alloc_usdc=100.0)
        inv.on_balance_update(token=0.0, usdc=0.0)
        assert inv.effective_token == 0.0
        assert inv.effective_usdc == 0.0
        # Virtual unchanged
        assert inv.virtual_token == 100.0
        assert inv.virtual_usdc == 100.0


# ===========================================================================
# 5. Allocation Management
# ===========================================================================


class TestAllocationUpdate:
    def test_increase_allocation(self) -> None:
        inv = _make_inv(alloc_token=100.0, alloc_usdc=100.0, acct_token=200.0, acct_usdc=200.0)
        inv.update_allocation(token=150.0, usdc=150.0)
        # Virtual should increase by the delta
        assert inv.virtual_token == pytest.approx(150.0)
        assert inv.virtual_usdc == pytest.approx(150.0)
        assert inv.effective_token == pytest.approx(150.0)

    def test_decrease_allocation(self) -> None:
        inv = _make_inv(alloc_token=100.0, alloc_usdc=100.0, acct_token=200.0, acct_usdc=200.0)
        inv.update_allocation(token=60.0, usdc=60.0)
        assert inv.virtual_token == pytest.approx(60.0)
        assert inv.virtual_usdc == pytest.approx(60.0)

    def test_allocation_update_after_fills(self) -> None:
        inv = _make_inv(alloc_token=100.0, alloc_usdc=0.0, acct_token=100.0, acct_usdc=500.0)
        inv.on_ask_fill(px=10.0, sz=5.0)
        # virtual: token=95, usdc=50
        inv.update_allocation(token=120.0, usdc=20.0)
        # delta: token +20, usdc +20
        assert inv.virtual_token == pytest.approx(115.0)
        assert inv.virtual_usdc == pytest.approx(70.0)


# ===========================================================================
# 6. Fill Sequence — Realistic Scenario
# ===========================================================================


class TestFillSequence:
    def test_alternating_fills_change_mid(self) -> None:
        """Simulate the HIP-2 grid: fills should move mid back and forth."""
        inv = _make_inv(
            alloc_token=5.0, alloc_usdc=1250.0,
            acct_token=81.0, acct_usdc=489_000.0,
        )
        initial_mid = inv.effective_usdc / inv.effective_token  # 250.0

        # Sell 1 token
        inv.on_ask_fill(px=250.75, sz=1.0)
        mid_after_sell = inv.effective_usdc / inv.effective_token
        assert mid_after_sell > initial_mid

        # Buy 1 token back
        inv.on_bid_fill(px=249.25, sz=1.0)
        mid_after_buy = inv.effective_usdc / inv.effective_token
        assert mid_after_buy < mid_after_sell

    def test_many_fills_with_fees(self) -> None:
        inv = _make_inv(
            alloc_token=10.0, alloc_usdc=2500.0,
            acct_token=100.0, acct_usdc=100_000.0,
        )
        # Sell 3 tokens at different prices
        inv.on_ask_fill(px=250.0, sz=1.0, fee=0.025, fee_token="USDC")
        inv.on_ask_fill(px=250.75, sz=1.0, fee=0.025, fee_token="USDC")
        inv.on_ask_fill(px=251.50, sz=1.0, fee=0.025, fee_token="USDC")

        assert inv.virtual_token == pytest.approx(7.0)
        expected_usdc = 2500.0 + (250.0 - 0.025) + (250.75 - 0.025) + (251.50 - 0.025)
        assert inv.virtual_usdc == pytest.approx(expected_usdc)

        # Account is untouched by fills
        assert inv.account_token == 100.0
        assert inv.account_usdc == 100_000.0


# ===========================================================================
# 7. Edge Cases & Invariants
# ===========================================================================


class TestEdgeCases:
    def test_effective_never_exceeds_min_virtual_account(self) -> None:
        for at, al in [(100, 50), (50, 100), (0, 100), (100, 0)]:
            inv = _make_inv(acct_token=float(at), alloc_token=float(al))
            assert inv.effective_token <= min(inv.virtual_token, inv.account_token)

    def test_effective_invariant_after_fills(self) -> None:
        inv = _make_inv(
            acct_token=50.0, alloc_token=60.0,
            acct_usdc=100.0, alloc_usdc=100.0,
        )
        for _ in range(10):
            inv.on_bid_fill(px=1.0, sz=5.0)
            assert inv.effective_token <= min(inv.virtual_token, inv.account_token)
            assert inv.effective_usdc <= min(inv.virtual_usdc, inv.account_usdc)

    def test_effective_invariant_after_ask_fills(self) -> None:
        inv = _make_inv(
            acct_token=100.0, alloc_token=100.0,
            acct_usdc=0.0, alloc_usdc=500.0,
        )
        for _ in range(5):
            inv.on_ask_fill(px=1.0, sz=10.0)
            assert inv.effective_token <= min(inv.virtual_token, inv.account_token)
            assert inv.effective_usdc <= min(inv.virtual_usdc, inv.account_usdc)

    def test_effective_invariant_after_reconciliation(self) -> None:
        inv = _make_inv(alloc_token=80.0, alloc_usdc=80.0)
        for t, u in [(200, 200), (50, 50), (0, 0), (80, 80), (1000, 10)]:
            inv.on_balance_update(token=float(t), usdc=float(u))
            assert inv.effective_token <= min(inv.virtual_token, inv.account_token)
            assert inv.effective_usdc <= min(inv.virtual_usdc, inv.account_usdc)

    def test_effective_invariant_after_allocation_update(self) -> None:
        inv = _make_inv(acct_token=100.0, acct_usdc=100.0)
        for al_t, al_u in [(50, 50), (200, 200), (0, 0), (100, 100)]:
            inv.update_allocation(token=float(al_t), usdc=float(al_u))
            assert inv.effective_token <= min(inv.virtual_token, inv.account_token)
            assert inv.effective_usdc <= min(inv.virtual_usdc, inv.account_usdc)

    def test_account_balances_not_changed_by_fills(self) -> None:
        """Fills should only move virtual balances, not account balances."""
        inv = _make_inv(acct_token=100.0, acct_usdc=5000.0)
        inv.on_ask_fill(px=50.0, sz=2.0)
        assert inv.account_token == 100.0
        assert inv.account_usdc == 5000.0
        inv.on_bid_fill(px=49.0, sz=3.0)
        assert inv.account_token == 100.0
        assert inv.account_usdc == 5000.0
