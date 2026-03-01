"""Tests for the OrderState module."""

from __future__ import annotations

from pyperliquidity.order_state import (
    FillResult,
    OrderState,
    OrderStatus,
    ReconcileResult,
    TrackedOrder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**kwargs) -> OrderState:  # type: ignore[no-untyped-def]
    return OrderState(**kwargs)


def _place(state: OrderState, oid: int = 100, side: str = "buy",
           level_index: int = 5, price: float = 1.50, size: float = 10.0) -> None:
    state.on_place_confirmed(oid=oid, side=side, level_index=level_index,
                             price=price, size=size)


# ===========================================================================
# 4.1 Place confirmation and dual-index consistency
# ===========================================================================


class TestPlaceConfirmation:
    def test_new_order_in_both_indices(self) -> None:
        state = _make_state()
        _place(state, oid=200, side="sell", level_index=7, price=2.10, size=5.0)

        assert 200 in state.orders_by_oid
        assert ("sell", 7) in state.orders_by_key
        # Same object in both dicts.
        assert state.orders_by_oid[200] is state.orders_by_key[("sell", 7)]

    def test_order_fields(self) -> None:
        state = _make_state()
        _place(state, oid=200, side="sell", level_index=7, price=2.10, size=5.0)
        order = state.orders_by_oid[200]
        assert order.oid == 200
        assert order.side == "sell"
        assert order.level_index == 7
        assert order.price == 2.10
        assert order.size == 5.0
        assert order.status == OrderStatus.RESTING

    def test_dual_index_consistency_multiple_orders(self) -> None:
        state = _make_state()
        _place(state, oid=1, side="buy", level_index=0, price=1.0, size=10.0)
        _place(state, oid=2, side="sell", level_index=3, price=1.5, size=10.0)
        _place(state, oid=3, side="buy", level_index=2, price=1.2, size=10.0)

        assert len(state.orders_by_oid) == 3
        assert len(state.orders_by_key) == 3
        for oid, order in state.orders_by_oid.items():
            key = (order.side, order.level_index)
            assert state.orders_by_key[key] is order


# ===========================================================================
# 4.2 OID swap handling
# ===========================================================================


class TestOIDSwap:
    def test_oid_swap_rekeys(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=5)
        order_before = state.orders_by_oid[100]

        state.on_modify_response(original_oid=100, new_oid=150, status="resting")

        assert 100 not in state.orders_by_oid
        assert 150 in state.orders_by_oid
        order_after = state.orders_by_oid[150]
        # Same object, just re-keyed.
        assert order_after is order_before
        assert order_after.oid == 150
        assert order_after.status == OrderStatus.RESTING

    def test_oid_swap_key_dict_unchanged(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=5)
        order = state.orders_by_key[("buy", 5)]

        state.on_modify_response(original_oid=100, new_oid=150, status="resting")

        assert state.orders_by_key[("buy", 5)] is order
        assert order.oid == 150

    def test_oid_unchanged_noop(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=5)

        state.on_modify_response(original_oid=100, new_oid=100, status="resting")

        assert 100 in state.orders_by_oid
        assert state.orders_by_oid[100].status == OrderStatus.RESTING

    def test_modify_unknown_oid_noop(self) -> None:
        state = _make_state()
        # Should not raise.
        state.on_modify_response(original_oid=999, new_oid=1000, status="resting")
        assert len(state.orders_by_oid) == 0


# ===========================================================================
# 4.3 Ghost detection via "Cannot modify" error
# ===========================================================================


class TestGhostDetection:
    def test_cannot_modify_removes_order(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="sell", level_index=3)

        state.on_modify_response(
            original_oid=100, new_oid=None, status="error: Cannot modify"
        )

        assert 100 not in state.orders_by_oid
        assert ("sell", 3) not in state.orders_by_key

    def test_cannot_modify_unknown_oid_noop(self) -> None:
        state = _make_state()
        # Idempotent — no crash.
        state.on_modify_response(
            original_oid=999, new_oid=None, status="error: Cannot modify"
        )
        assert len(state.orders_by_oid) == 0


# ===========================================================================
# 4.4 Fill deduplication
# ===========================================================================


class TestFillDedup:
    def test_duplicate_tid_returns_none(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=5, size=10.0)

        result1 = state.on_fill(tid=1001, oid=100, fill_sz=5.0)
        result2 = state.on_fill(tid=1001, oid=100, fill_sz=5.0)

        assert result1 is not None
        assert result2 is None
        # Only one fill applied — size should be 5.0, not 0.0.
        assert state.orders_by_oid[100].size == 5.0

    def test_different_tids_both_applied(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=5, size=10.0)

        r1 = state.on_fill(tid=1001, oid=100, fill_sz=3.0)
        r2 = state.on_fill(tid=1002, oid=100, fill_sz=3.0)

        assert r1 is not None
        assert r2 is not None
        assert state.orders_by_oid[100].size == 4.0


# ===========================================================================
# 4.5 Partial fill reduces size
# ===========================================================================


class TestPartialFill:
    def test_partial_fill_reduces_size(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="sell", level_index=3, price=2.0, size=10.0)

        result = state.on_fill(tid=2001, oid=100, fill_sz=3.0)

        assert result is not None
        assert result.fully_filled is False
        assert result.size == 3.0
        assert result.side == "sell"
        assert result.price == 2.0
        # Order still in both indices with reduced size.
        assert 100 in state.orders_by_oid
        assert ("sell", 3) in state.orders_by_key
        assert state.orders_by_oid[100].size == 7.0


# ===========================================================================
# 4.6 Full fill removes order
# ===========================================================================


class TestFullFill:
    def test_full_fill_removes_order(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=5, price=1.50, size=10.0)

        result = state.on_fill(tid=3001, oid=100, fill_sz=10.0)

        assert result is not None
        assert result.fully_filled is True
        assert result.size == 10.0
        assert result.side == "buy"
        assert result.price == 1.50
        assert 100 not in state.orders_by_oid
        assert ("buy", 5) not in state.orders_by_key

    def test_overfill_treated_as_full(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=5, size=10.0)

        result = state.on_fill(tid=3002, oid=100, fill_sz=15.0)

        assert result is not None
        assert result.fully_filled is True
        assert 100 not in state.orders_by_oid


# ===========================================================================
# 4.7 Reconcile detects orphaned and ghost orders
# ===========================================================================


class TestReconcile:
    def test_detect_orphaned(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=1)
        _place(state, oid=200, side="sell", level_index=2)

        result = state.reconcile({100, 200, 300})

        assert result.orphaned_oids == frozenset({300})
        assert result.ghost_oids == frozenset()

    def test_detect_ghosts(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=1)
        _place(state, oid=200, side="sell", level_index=2)

        result = state.reconcile({100})

        assert result.orphaned_oids == frozenset()
        assert result.ghost_oids == frozenset({200})

    def test_clean_state(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=1)
        _place(state, oid=200, side="sell", level_index=2)

        result = state.reconcile({100, 200})

        assert result.orphaned_oids == frozenset()
        assert result.ghost_oids == frozenset()

    def test_mixed_orphans_and_ghosts(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=1)
        _place(state, oid=200, side="sell", level_index=2)

        result = state.reconcile({100, 300})

        assert result.orphaned_oids == frozenset({300})
        assert result.ghost_oids == frozenset({200})


# ===========================================================================
# 4.8 Seen tids pruning at capacity
# ===========================================================================


class TestSeenTidsPruning:
    def test_prune_at_capacity(self) -> None:
        cap = 100
        state = _make_state(seen_tids_cap=cap)

        # Fill up seen_tids beyond cap.
        for tid in range(cap + 1):
            _place(state, oid=tid + 1000, side="buy", level_index=tid)
            state.on_fill(tid=tid, oid=tid + 1000, fill_sz=10.0)

        # After pruning, should have kept the newest half.
        assert len(state._seen_tids) <= cap
        # The newest tids should still be present.
        assert cap in state._seen_tids
        # Old tids should be pruned.
        assert 0 not in state._seen_tids

    def test_prune_keeps_newest_half(self) -> None:
        cap = 10
        state = _make_state(seen_tids_cap=cap)

        for tid in range(cap + 1):
            _place(state, oid=tid + 1000, side="buy", level_index=tid)
            state.on_fill(tid=tid, oid=tid + 1000, fill_sz=10.0)

        # After pruning: should have ~6 tids (kept 5 newest + new one).
        assert len(state._seen_tids) <= cap
        # Newest tid present.
        assert cap in state._seen_tids


# ===========================================================================
# 4.9 Replace existing order at same (side, level_index) on place
# ===========================================================================


class TestReplaceOnPlace:
    def test_replace_evicts_old_oid(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="sell", level_index=7, price=2.10, size=5.0)
        _place(state, oid=200, side="sell", level_index=7, price=2.13, size=5.0)

        assert 100 not in state.orders_by_oid
        assert 200 in state.orders_by_oid
        assert state.orders_by_key[("sell", 7)].oid == 200
        assert state.orders_by_key[("sell", 7)].price == 2.13
        assert len(state.orders_by_oid) == 1
        assert len(state.orders_by_key) == 1


# ===========================================================================
# 4.10 Fill for unknown OID returns None
# ===========================================================================


class TestFillUnknownOID:
    def test_unknown_oid_returns_none(self) -> None:
        state = _make_state()
        result = state.on_fill(tid=9001, oid=999, fill_sz=5.0)
        assert result is None

    def test_unknown_oid_no_state_change(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=5)
        state.on_fill(tid=9002, oid=999, fill_sz=5.0)
        # Existing order unaffected.
        assert 100 in state.orders_by_oid
        assert len(state.orders_by_oid) == 1


# ===========================================================================
# Additional: remove_ghost and get_current_orders
# ===========================================================================


class TestRemoveGhost:
    def test_remove_existing(self) -> None:
        state = _make_state()
        _place(state, oid=100, side="buy", level_index=5)
        state.remove_ghost(100)
        assert 100 not in state.orders_by_oid
        assert ("buy", 5) not in state.orders_by_key

    def test_remove_nonexistent_noop(self) -> None:
        state = _make_state()
        state.remove_ghost(999)  # Should not raise.
        assert len(state.orders_by_oid) == 0


class TestGetCurrentOrders:
    def test_returns_all_orders(self) -> None:
        state = _make_state()
        _place(state, oid=1, side="buy", level_index=0)
        _place(state, oid=2, side="sell", level_index=3)
        _place(state, oid=3, side="buy", level_index=2)

        orders = state.get_current_orders()
        assert len(orders) == 3
        oids = {o.oid for o in orders}
        assert oids == {1, 2, 3}

    def test_empty_state(self) -> None:
        state = _make_state()
        assert state.get_current_orders() == []
