"""Tests for batch_emitter — budget gating, priority, response handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pyperliquidity.batch_emitter import (
    BALANCE_COOLDOWN_S,
    REJECT_COOLDOWN_S,
    BatchEmitter,
    EmitResult,
)
from pyperliquidity.order_differ import OrderDiff
from pyperliquidity.order_state import OrderState
from pyperliquidity.quoting_engine import DesiredOrder
from pyperliquidity.rate_limit import RateLimitBudget

# --- Helpers ------------------------------------------------------------------

def _ok(statuses: list[dict]) -> dict:
    """Build a successful SDK batch response."""
    return {"status": "ok", "response": {"data": {"statuses": statuses}}}


def _desired(side: str = "buy", level: int = 0, px: float = 1.0, sz: float = 10.0):
    return DesiredOrder(side=side, level_index=level, price=px, size=sz)


def _make_emitter(
    exchange: MagicMock | None = None,
    order_state: OrderState | None = None,
    clock_time: float = 0.0,
) -> tuple[BatchEmitter, MagicMock, OrderState, MagicMock]:
    """Build a BatchEmitter with defaults and return all components."""
    ex = exchange or MagicMock()
    os = order_state or OrderState()
    clock = MagicMock(return_value=clock_time)
    emitter = BatchEmitter(
        coin="TEST", asset_id=10001, exchange=ex, order_state=os, clock=clock,
    )
    return emitter, ex, os, clock


def _budget(remaining: int = 10_000) -> RateLimitBudget:
    """Create a RateLimitBudget with approx *remaining* budget."""
    b = RateLimitBudget()
    if remaining < 10_000:
        b.n_requests = 10_000 - remaining
    return b


# --- 5.1 Budget gating -------------------------------------------------------

async def test_cancel_only_mode_suppresses_modifies_and_places():
    emitter, ex, os, _ = _make_emitter()
    # Pre-populate order state for the cancel
    os.on_place_confirmed(oid=1, side="buy", level_index=0, price=1.0, size=10.0)

    ex.bulk_cancel.return_value = _ok([{}])

    diff = OrderDiff(
        cancels=[1],
        modifies=[(1, _desired())],
        places=[_desired(level=1)],
    )
    # remaining=150 < 3 (mutations) + 100 (safety) = 103 → just above,
    # but let's set it so remaining < total + SAFETY_MARGIN
    budget = _budget(remaining=102)  # 102 < 3 + 100 = 103

    result = await emitter.emit(diff, budget)

    assert result.cancel_only_mode is True
    assert result.n_cancelled == 1
    assert result.n_modified == 0
    assert result.n_placed == 0
    ex.bulk_cancel.assert_called_once()
    ex.bulk_modify_orders_new.assert_not_called()
    ex.bulk_orders.assert_not_called()


async def test_budget_sufficient_emits_all():
    emitter, ex, os, _ = _make_emitter()
    os.on_place_confirmed(oid=1, side="buy", level_index=0, price=1.0, size=10.0)

    ex.bulk_cancel.return_value = _ok([{}])
    ex.bulk_modify_orders_new.return_value = _ok([{"resting": {"oid": 1}}])
    ex.bulk_orders.return_value = _ok([{"resting": {"oid": 2}}])

    diff = OrderDiff(
        cancels=[1],
        modifies=[(1, _desired())],
        places=[_desired(level=2)],
    )
    budget = _budget(remaining=5000)
    result = await emitter.emit(diff, budget)

    assert result.cancel_only_mode is False
    # Cancel removes oid=1, then modify targets oid=1 which no longer exists
    # but that's fine for budget gating test — the point is all 3 calls happen.
    ex.bulk_cancel.assert_called_once()
    ex.bulk_modify_orders_new.assert_called_once()
    ex.bulk_orders.assert_called_once()


# --- 5.2 Priority trimming ---------------------------------------------------

async def test_priority_trimming_drops_places_first():
    emitter, ex, os, _ = _make_emitter()

    ex.bulk_cancel.return_value = _ok([{}] * 5)
    ex.bulk_modify_orders_new.return_value = _ok(
        [{"resting": {"oid": i}} for i in range(100, 110)]
    )
    ex.bulk_orders.return_value = _ok(
        [{"resting": {"oid": i}} for i in range(200, 205)]
    )

    # Seed order_state for modifies
    for i in range(10):
        os.on_place_confirmed(oid=i + 10, side="buy", level_index=i, price=1.0, size=10.0)

    cancels = list(range(1, 6))  # 5 cancels
    modifies = [(i + 10, _desired(level=i)) for i in range(10)]  # 10 modifies
    places = [_desired(level=i + 20) for i in range(10)]  # 10 places
    # Total = 25, exceeds 20. Trim places to 20 - 5 - 10 = 5.

    diff = OrderDiff(cancels=cancels, modifies=modifies, places=places)
    budget = _budget(remaining=5000)
    await emitter.emit(diff, budget)

    # Check that bulk_orders was called with only 5 orders (trimmed from 10)
    placed_reqs = ex.bulk_orders.call_args[0][0]
    assert len(placed_reqs) == 5


async def test_cancels_never_trimmed():
    emitter, ex, os, _ = _make_emitter()

    ex.bulk_cancel.return_value = _ok([{}] * 25)

    cancels = list(range(25))
    diff = OrderDiff(cancels=cancels, modifies=[], places=[])
    budget = _budget(remaining=5000)
    result = await emitter.emit(diff, budget)

    cancel_reqs = ex.bulk_cancel.call_args[0][0]
    assert len(cancel_reqs) == 25
    assert result.n_cancelled == 25


# --- 5.3 Emission ordering ---------------------------------------------------

async def test_emission_order_cancel_modify_place():
    emitter, ex, os, _ = _make_emitter()
    os.on_place_confirmed(oid=10, side="buy", level_index=0, price=1.0, size=10.0)
    os.on_place_confirmed(oid=11, side="buy", level_index=5, price=1.0, size=10.0)

    call_order: list[str] = []

    def track_cancel(reqs):
        call_order.append("cancel")
        return _ok([{}])

    def track_modify(reqs):
        call_order.append("modify")
        return _ok([{"resting": {"oid": 10}}])

    def track_place(reqs):
        call_order.append("place")
        return _ok([{"resting": {"oid": 300}}])

    ex.bulk_cancel.side_effect = track_cancel
    ex.bulk_modify_orders_new.side_effect = track_modify
    ex.bulk_orders.side_effect = track_place

    diff = OrderDiff(
        cancels=[11],
        modifies=[(10, _desired(level=0))],
        places=[_desired(level=2)],
    )
    budget = _budget(remaining=5000)
    await emitter.emit(diff, budget)

    assert call_order == ["cancel", "modify", "place"]


# --- 5.4 OID swap forwarding -------------------------------------------------

async def test_oid_swap_forwarded_to_order_state():
    emitter, ex, os, _ = _make_emitter()
    os.on_place_confirmed(oid=100, side="buy", level_index=5, price=1.50, size=10.0)

    ex.bulk_modify_orders_new.return_value = _ok([{"resting": {"oid": 200}}])

    diff = OrderDiff(modifies=[(100, _desired(side="buy", level=5, px=1.55))])
    budget = _budget()
    await emitter.emit(diff, budget)

    # The old OID should be gone, new OID present
    assert 100 not in os.orders_by_oid
    assert 200 in os.orders_by_oid
    assert os.orders_by_oid[200].side == "buy"
    assert os.orders_by_oid[200].level_index == 5
    assert os.orders_by_oid[200].price == 1.55


# --- 5.5 Ghost detection on modify -------------------------------------------

async def test_cannot_modify_removes_ghost():
    emitter, ex, os, _ = _make_emitter()
    os.on_place_confirmed(oid=100, side="sell", level_index=3, price=2.0, size=5.0)

    ex.bulk_modify_orders_new.return_value = _ok(
        [{"error": "Cannot modify order"}]
    )

    diff = OrderDiff(modifies=[(100, _desired(side="sell", level=3, px=2.1))])
    budget = _budget()
    result = await emitter.emit(diff, budget)

    assert 100 not in os.orders_by_oid
    assert ("sell", 3) not in os.orders_by_key
    assert result.n_errors == 1


# --- 5.6 bulk_orders response handling ----------------------------------------

async def test_resting_place_calls_on_place_confirmed():
    emitter, ex, os, _ = _make_emitter()

    ex.bulk_orders.return_value = _ok([{"resting": {"oid": 300}}])

    diff = OrderDiff(places=[_desired(side="buy", level=5, px=1.50, sz=10.0)])
    budget = _budget()
    result = await emitter.emit(diff, budget)

    assert result.n_placed == 1
    assert 300 in os.orders_by_oid
    order = os.orders_by_oid[300]
    assert order.side == "buy"
    assert order.level_index == 5
    assert order.price == 1.50


async def test_insufficient_balance_sets_cooldown():
    emitter, ex, os, clock = _make_emitter(clock_time=100.0)

    ex.bulk_orders.return_value = _ok(
        [{"error": "Insufficient spot balance for order"}]
    )

    diff = OrderDiff(places=[_desired(side="sell", level=1)])
    budget = _budget()
    await emitter.emit(diff, budget)

    # Cooldown should be set for (TEST, sell)
    assert (emitter.coin, "sell") in emitter._cooldowns
    expiry = emitter._cooldowns[(emitter.coin, "sell")]
    assert expiry == pytest.approx(100.0 + BALANCE_COOLDOWN_S)


# --- 5.7 Cooldown behavior ---------------------------------------------------

async def test_cooldown_suppresses_placements():
    emitter, ex, os, clock = _make_emitter(clock_time=100.0)
    # Set a cooldown on sell side that expires at 160
    emitter._cooldowns[(emitter.coin, "sell")] = 160.0

    ex.bulk_orders.return_value = _ok([{"resting": {"oid": 400}}])

    # Diff has both buy and sell places
    diff = OrderDiff(
        places=[
            _desired(side="sell", level=1),
            _desired(side="buy", level=2),
        ]
    )
    budget = _budget()
    result = await emitter.emit(diff, budget)

    # Only the buy should have been placed (sell cooled down)
    assert result.n_placed == 1
    placed_reqs = ex.bulk_orders.call_args[0][0]
    assert len(placed_reqs) == 1
    assert placed_reqs[0]["b"] is True  # buy


async def test_successful_placement_clears_cooldown():
    emitter, ex, os, clock = _make_emitter(clock_time=200.0)
    # Cooldown already expired (set expiry in the past so it clears on check)
    # Actually, let's test: place succeeds → cooldown is cleared
    emitter._cooldowns[(emitter.coin, "buy")] = 190.0  # already expired

    ex.bulk_orders.return_value = _ok([{"resting": {"oid": 500}}])

    diff = OrderDiff(places=[_desired(side="buy", level=3)])
    budget = _budget()
    await emitter.emit(diff, budget)

    assert (emitter.coin, "buy") not in emitter._cooldowns


# --- 5.8 ALO rejections not counted ------------------------------------------

async def test_alo_rejection_not_counted_as_generic_reject():
    emitter, ex, os, clock = _make_emitter(clock_time=0.0)

    # 3 ALO rejections should NOT trigger a cooldown
    ex.bulk_orders.return_value = _ok([
        {"error": "Post-only would take"},
        {"error": "Post-only would take"},
        {"error": "Post-only would take"},
    ])

    diff = OrderDiff(
        places=[_desired(level=i) for i in range(3)]
    )
    budget = _budget()
    result = await emitter.emit(diff, budget)

    assert result.n_errors == 3
    assert result.n_placed == 0
    # No cooldown should be set
    assert len(emitter._cooldowns) == 0
    # Consecutive rejects counter should be 0
    assert emitter._consecutive_rejects.get("buy", 0) == 0


async def test_generic_rejects_trigger_cooldown_at_threshold():
    emitter, ex, os, clock = _make_emitter(clock_time=0.0)

    ex.bulk_orders.return_value = _ok([
        {"error": "some generic error"},
        {"error": "some generic error"},
        {"error": "some generic error"},
    ])

    diff = OrderDiff(places=[_desired(level=i) for i in range(3)])
    budget = _budget()
    await emitter.emit(diff, budget)

    # 3 consecutive generic rejects → cooldown
    assert (emitter.coin, "buy") in emitter._cooldowns
    expiry = emitter._cooldowns[(emitter.coin, "buy")]
    assert expiry == pytest.approx(0.0 + REJECT_COOLDOWN_S)


# --- 5.9 Rate limit notification ---------------------------------------------

async def test_budget_on_request_called_per_batch():
    emitter, ex, os, _ = _make_emitter()
    os.on_place_confirmed(oid=10, side="buy", level_index=0, price=1.0, size=10.0)

    ex.bulk_cancel.return_value = _ok([{}])
    ex.bulk_modify_orders_new.return_value = _ok([{"resting": {"oid": 10}}])
    ex.bulk_orders.return_value = _ok([{"resting": {"oid": 20}}])

    diff = OrderDiff(
        cancels=[10],
        modifies=[(10, _desired(level=0))],
        places=[_desired(level=1)],
    )
    budget = _budget()
    initial_requests = budget.n_requests

    await emitter.emit(diff, budget)

    # 3 batch calls = 3 on_request() calls
    assert budget.n_requests == initial_requests + 3


async def test_single_batch_type_one_request():
    emitter, ex, os, _ = _make_emitter()

    ex.bulk_orders.return_value = _ok([{"resting": {"oid": 1}}])

    diff = OrderDiff(places=[_desired()])
    budget = _budget()
    initial_requests = budget.n_requests

    await emitter.emit(diff, budget)

    assert budget.n_requests == initial_requests + 1


# --- 5.10 Cross-side modify assertion ----------------------------------------

async def test_cross_side_modify_raises():
    emitter, ex, os, _ = _make_emitter()
    # Track a buy order at level 5
    os.on_place_confirmed(oid=100, side="buy", level_index=5, price=1.0, size=10.0)

    # Try to modify it into a sell
    diff = OrderDiff(modifies=[(100, _desired(side="sell", level=5))])
    budget = _budget()

    with pytest.raises(AssertionError, match="Cross-side modify"):
        await emitter.emit(diff, budget)


# --- 5.11 Empty diff ---------------------------------------------------------

async def test_empty_diff_no_api_calls():
    emitter, ex, os, _ = _make_emitter()

    diff = OrderDiff()
    budget = _budget()
    result = await emitter.emit(diff, budget)

    assert result == EmitResult(0, 0, 0, 0, cancel_only_mode=False)
    ex.bulk_cancel.assert_not_called()
    ex.bulk_modify_orders_new.assert_not_called()
    ex.bulk_orders.assert_not_called()


# --- 5.12 Cancel errors still remove from state ------------------------------

async def test_cancel_error_still_removes_from_state():
    emitter, ex, os, _ = _make_emitter()
    os.on_place_confirmed(oid=100, side="buy", level_index=5, price=1.0, size=10.0)

    ex.bulk_cancel.return_value = _ok([{"error": "Order already filled"}])

    diff = OrderDiff(cancels=[100])
    budget = _budget()
    result = await emitter.emit(diff, budget)

    assert result.n_errors == 1
    assert result.n_cancelled == 0
    # The order should be removed from state regardless of the error
    assert 100 not in os.orders_by_oid
    assert ("buy", 5) not in os.orders_by_key


# --- 5.13 Unknown modify status removes order --------------------------------

async def test_unknown_modify_status_removes_from_state():
    emitter, ex, os, _ = _make_emitter()
    os.on_place_confirmed(oid=100, side="buy", level_index=5, price=1.0, size=10.0)

    # Return an unexpected status (e.g., "filled" or empty dict)
    ex.bulk_modify_orders_new.return_value = _ok([{"filled": {"totalSz": "10.0"}}])

    diff = OrderDiff(modifies=[(100, _desired(side="buy", level=5, px=1.1))])
    budget = _budget()
    result = await emitter.emit(diff, budget)

    # Unhandled status → order removed from state as safety measure
    assert 100 not in os.orders_by_oid
    assert ("buy", 5) not in os.orders_by_key
    assert result.n_errors == 1


async def test_truncated_modify_response_removes_from_state():
    emitter, ex, os, _ = _make_emitter()
    os.on_place_confirmed(oid=100, side="buy", level_index=5, price=1.0, size=10.0)

    # Fewer statuses than requests → empty dict fallback → else branch
    ex.bulk_modify_orders_new.return_value = _ok([])

    diff = OrderDiff(modifies=[(100, _desired(side="buy", level=5, px=1.1))])
    budget = _budget()
    result = await emitter.emit(diff, budget)

    assert 100 not in os.orders_by_oid
    assert result.n_errors == 1


# --- 5.14 Budget debited on SDK exception ------------------------------------

async def test_budget_debited_on_sdk_exception():
    emitter, ex, os, _ = _make_emitter()

    ex.bulk_orders.side_effect = ConnectionError("network error")

    diff = OrderDiff(places=[_desired(level=0)])
    budget = _budget()
    initial_requests = budget.n_requests

    with pytest.raises(ConnectionError):
        await emitter.emit(diff, budget)

    # Budget should still be debited even though the call raised
    assert budget.n_requests == initial_requests + 1
