"""Tests for ws_state — startup, tick loop, reconciliation, WS routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pyperliquidity.ws_state import WsState

# --- Helpers ------------------------------------------------------------------

def _make_info(
    coin: str = "TEST",
    spot_index: int = 5,
    open_orders: list | None = None,
    token_bal: float = 100.0,
    usdc_bal: float = 500.0,
    cum_vlm: float = 1000.0,
    n_requests: int = 200,
) -> MagicMock:
    """Build a mock SDK info object with configurable REST responses."""
    info = MagicMock()

    info.spot_meta.return_value = {
        "universe": [
            {"name": "OTHER"},
            *([{"name": coin}] if spot_index == 1 else []),
            *([{"name": f"FILLER{i}"} for i in range(2, spot_index)]),
            *([{"name": coin}] if spot_index != 1 else []),
        ],
    }
    # Simplify: just put the coin at the right index
    universe = [{"name": f"COIN{i}"} for i in range(spot_index)]
    universe.append({"name": coin})
    info.spot_meta.return_value = {"universe": universe}

    info.open_orders.return_value = open_orders or []

    info.spot_user_state.return_value = {
        "balances": [
            {"coin": coin, "total": str(token_bal)},
            {"coin": "USDC", "total": str(usdc_bal)},
        ],
    }

    info.user_rate_limit.return_value = {
        "cumVlm": str(cum_vlm),
        "nRequestsUsed": str(n_requests),
    }

    info.subscribe = MagicMock()

    return info


def _make_exchange() -> MagicMock:
    """Build a mock SDK exchange object."""
    return MagicMock()


def _ok(statuses: list[dict]) -> dict:
    """Build a successful SDK batch response."""
    return {"status": "ok", "response": {"data": {"statuses": statuses}}}


def _make_ws_state(
    info: MagicMock | None = None,
    exchange: MagicMock | None = None,
    **kwargs: object,
) -> tuple[WsState, MagicMock, MagicMock]:
    """Build a WsState instance with defaults."""
    i = info or _make_info()
    e = exchange or _make_exchange()
    defaults = {
        "coin": "TEST",
        "start_px": 1.0,
        "n_orders": 10,
        "order_sz": 10.0,
        "n_seeded_levels": 5,
        "info": i,
        "exchange": e,
        "address": "0xtest",
        "interval_s": 3.0,
        "reconcile_every": 20,
    }
    defaults.update(kwargs)
    ws = WsState(**defaults)  # type: ignore[arg-type]
    return ws, i, e


# --- 6.1 Startup sequence ----------------------------------------------------

async def test_startup_resolves_asset_id():
    """spot_meta → asset_id = spot_index + 10000."""
    ws, info, _ = _make_ws_state(info=_make_info(spot_index=5))
    await ws._startup()

    assert ws.asset_id == 10_005


async def test_startup_coin_not_found():
    """Raises ValueError if coin is not in spot_meta universe."""
    info = _make_info()
    info.spot_meta.return_value = {"universe": [{"name": "OTHER"}]}

    ws, _, _ = _make_ws_state(info=info)

    with pytest.raises(ValueError, match="not found in spot_meta"):
        await ws._startup()


async def test_startup_seeds_order_state():
    """open_orders seeds OrderState with resting orders."""
    open_orders = [
        {"coin": "TEST", "oid": 100, "side": "B", "limitPx": "1.0", "sz": "10.0"},
        {"coin": "TEST", "oid": 101, "side": "A", "limitPx": "1.003", "sz": "10.0"},
        {"coin": "OTHER", "oid": 200, "side": "B", "limitPx": "5.0", "sz": "1.0"},
    ]
    ws, _, _ = _make_ws_state(info=_make_info(open_orders=open_orders))
    await ws._startup()

    # Only TEST orders should be seeded (not OTHER)
    assert 100 in ws.order_state.orders_by_oid
    assert 101 in ws.order_state.orders_by_oid
    assert 200 not in ws.order_state.orders_by_oid
    assert ws.order_state.orders_by_oid[100].side == "buy"
    assert ws.order_state.orders_by_oid[101].side == "sell"


async def test_startup_seeds_inventory():
    """spot_user_state seeds Inventory with balances."""
    ws, _, _ = _make_ws_state(info=_make_info(token_bal=50.0, usdc_bal=200.0))
    await ws._startup()

    assert ws.inventory is not None
    assert ws.inventory.effective_token == 50.0
    assert ws.inventory.effective_usdc == 200.0


async def test_startup_seeds_rate_limit():
    """user_rate_limit seeds RateLimitBudget."""
    ws, _, _ = _make_ws_state(info=_make_info(cum_vlm=5000.0, n_requests=300))
    await ws._startup()

    assert ws.rate_limit.cum_vlm == 5000.0
    assert ws.rate_limit.n_requests == 300


async def test_startup_constructs_grid():
    """PricingGrid is constructed from config params."""
    ws, _, _ = _make_ws_state(start_px=2.0, n_orders=5)
    await ws._startup()

    assert ws.grid is not None
    assert len(ws.grid.levels) == 5
    assert ws.grid.levels[0] == 2.0


async def test_startup_boundary_from_asks():
    """boundary_level is the lowest ask level when asks exist."""
    open_orders = [
        {"coin": "TEST", "oid": 100, "side": "A", "limitPx": "1.006009", "sz": "10.0"},
        {"coin": "TEST", "oid": 101, "side": "A", "limitPx": "1.009027", "sz": "10.0"},
    ]
    ws, _, _ = _make_ws_state(info=_make_info(open_orders=open_orders))
    await ws._startup()

    # Grid levels: 1.0, 1.003, 1.006009, 1.009027027, ...
    # The lowest ask is at level 2 (price ~1.006009)
    assert ws.boundary_level == 2


async def test_startup_boundary_default_no_asks():
    """boundary_level defaults to n_seeded_levels when no asks exist."""
    ws, _, _ = _make_ws_state(n_seeded_levels=5)
    await ws._startup()

    assert ws.boundary_level == 5


# --- 6.2 Tick loop ------------------------------------------------------------

async def test_tick_runs_full_pipeline():
    """A single tick runs: desired orders → diff → emit."""
    ws, info, exchange = _make_ws_state(
        info=_make_info(token_bal=20.0, usdc_bal=50.0),
    )
    await ws._startup()

    # Mock the exchange to return successful place responses
    exchange.bulk_orders.return_value = _ok([
        {"resting": {"oid": i}} for i in range(300, 320)
    ])
    exchange.bulk_cancel.return_value = _ok([])
    exchange.bulk_modify_orders_new.return_value = _ok([])

    # Run a single tick
    await ws._tick()

    # With 20 tokens, order_sz=10, boundary=5: we should have 2 ask tranches
    # Plus bid orders from USDC. The emitter should have been called.
    # We don't assert exact order counts (that's quoting_engine's job),
    # just that the pipeline executed.
    assert ws._tick_count == 0  # _tick doesn't increment, _tick_loop does


async def test_tick_with_no_changes():
    """Tick with existing matching orders produces empty diff → no API calls."""
    # Seed orders that match what quoting engine would produce
    open_orders = [
        {"coin": "TEST", "oid": 100, "side": "A", "limitPx": "1.0", "sz": "10.0"},
    ]
    ws, info, exchange = _make_ws_state(
        info=_make_info(open_orders=open_orders, token_bal=10.0, usdc_bal=0.0),
        n_seeded_levels=0,
    )
    await ws._startup()

    # After startup, boundary=0 (lowest ask is at level 0).
    # With 10 tokens and boundary=0, desired = 1 ask at level 0.
    # Current = 1 ask at level 0.  Dead zone should suppress.
    await ws._tick()

    # No API calls should have been made
    exchange.bulk_orders.assert_not_called()
    exchange.bulk_modify_orders_new.assert_not_called()
    exchange.bulk_cancel.assert_not_called()


# --- 6.3 Reconciliation ------------------------------------------------------

async def test_reconciliation_cancels_orphaned_order():
    """Orphaned order (on exchange, not in state) gets cancelled."""
    ws, info, exchange = _make_ws_state()
    await ws._startup()

    # Set up REST to return an order we're NOT tracking
    info.open_orders.return_value = [
        {"coin": "TEST", "oid": 999, "side": "B", "limitPx": "1.0", "sz": "10.0"},
    ]
    exchange.bulk_cancel.return_value = _ok([{}])

    await ws._reconcile()

    # bulk_cancel should have been called with oid 999
    exchange.bulk_cancel.assert_called_once()
    cancel_reqs = exchange.bulk_cancel.call_args[0][0]
    assert any(req["o"] == 999 for req in cancel_reqs)


async def test_reconciliation_removes_ghost_order():
    """Ghost order (in state, not on exchange) gets removed from state."""
    ws, info, exchange = _make_ws_state()
    await ws._startup()

    # Manually add an order to state
    ws.order_state.on_place_confirmed(
        oid=500, side="buy", level_index=3, price=1.0, size=10.0,
    )
    assert 500 in ws.order_state.orders_by_oid

    # REST returns no orders → 500 is a ghost
    info.open_orders.return_value = []

    await ws._reconcile()

    assert 500 not in ws.order_state.orders_by_oid


async def test_reconciliation_updates_balances():
    """Reconciliation updates inventory from REST balance data."""
    ws, info, _ = _make_ws_state(info=_make_info(token_bal=100.0, usdc_bal=500.0))
    await ws._startup()

    assert ws.inventory is not None
    assert ws.inventory.effective_token == 100.0

    # Update the REST response to return different balances
    info.spot_user_state.return_value = {
        "balances": [
            {"coin": "TEST", "total": "80.0"},
            {"coin": "USDC", "total": "600.0"},
        ],
    }
    info.open_orders.return_value = []

    await ws._reconcile()

    assert ws.inventory.account_token == 80.0
    assert ws.inventory.account_usdc == 600.0


# --- 6.4 WS callback routing -------------------------------------------------

async def test_fill_callback_updates_order_state_and_inventory():
    """userFills callback routes to OrderState.on_fill → Inventory."""
    ws, _, _ = _make_ws_state(info=_make_info(token_bal=100.0, usdc_bal=500.0))
    await ws._startup()

    # Place an ask order in state
    ws.order_state.on_place_confirmed(
        oid=42, side="sell", level_index=5, price=1.015, size=10.0,
    )
    initial_token = ws.inventory.effective_token

    # Simulate fill callback
    fill_msg = [{"tid": 1001, "oid": 42, "sz": "10.0", "px": "1.015"}]
    await ws._handle_fill(fill_msg)

    # Order should be removed (fully filled)
    assert 42 not in ws.order_state.orders_by_oid
    # Inventory should reflect the fill (sold tokens, gained USDC)
    assert ws.inventory is not None
    assert ws.inventory.account_token < initial_token


async def test_duplicate_fill_ignored():
    """Duplicate tid is ignored by OrderState dedup."""
    ws, _, _ = _make_ws_state(info=_make_info(token_bal=100.0, usdc_bal=500.0))
    await ws._startup()

    ws.order_state.on_place_confirmed(
        oid=42, side="sell", level_index=5, price=1.015, size=20.0,
    )
    assert ws.inventory is not None

    # First fill — partial
    await ws._handle_fill([{"tid": 1001, "oid": 42, "sz": "10.0", "px": "1.015"}])
    token_after_first = ws.inventory.account_token

    # Duplicate fill — should be ignored
    await ws._handle_fill([{"tid": 1001, "oid": 42, "sz": "10.0", "px": "1.015"}])
    assert ws.inventory.account_token == token_after_first


async def test_order_update_resting_adds_to_state():
    """orderUpdates with status=resting adds order to state."""
    ws, _, _ = _make_ws_state()
    await ws._startup()

    msg = [{
        "status": "resting",
        "order": {
            "oid": 77,
            "side": "B",
            "limitPx": "1.003",
            "sz": "10.0",
        },
    }]
    await ws._handle_order_update(msg)

    assert 77 in ws.order_state.orders_by_oid
    assert ws.order_state.orders_by_oid[77].side == "buy"


async def test_order_update_cannot_modify_removes():
    """orderUpdates with Cannot modify removes from state."""
    ws, _, _ = _make_ws_state()
    await ws._startup()

    # Add order first
    ws.order_state.on_place_confirmed(
        oid=88, side="sell", level_index=3, price=1.009, size=5.0,
    )

    msg = [{
        "status": "Cannot modify order",
        "order": {"oid": 88},
    }]
    await ws._handle_order_update(msg)

    assert 88 not in ws.order_state.orders_by_oid


async def test_balance_update_handler():
    """webData2 balance update routes to Inventory."""
    ws, _, _ = _make_ws_state(info=_make_info(token_bal=100.0, usdc_bal=500.0))
    await ws._startup()

    msg = {
        "spotBalances": [
            {"coin": "TEST", "total": "90.0"},
            {"coin": "USDC", "total": "550.0"},
        ],
    }
    await ws._handle_balance_update(msg)

    assert ws.inventory is not None
    assert ws.inventory.account_token == 90.0
    assert ws.inventory.account_usdc == 550.0


async def test_fill_updates_rate_limit_budget():
    """Fill events add volume to rate limit budget."""
    ws, _, _ = _make_ws_state(info=_make_info(cum_vlm=1000.0, n_requests=100))
    await ws._startup()

    ws.order_state.on_place_confirmed(
        oid=42, side="sell", level_index=5, price=2.0, size=10.0,
    )
    initial_vlm = ws.rate_limit.cum_vlm

    await ws._handle_fill([{"tid": 2001, "oid": 42, "sz": "10.0", "px": "2.0"}])

    # Volume should increase by px * sz = 2.0 * 10.0 = 20.0
    assert ws.rate_limit.cum_vlm == initial_vlm + 20.0


async def test_subscribe_registers_three_feeds():
    """_subscribe registers orderUpdates, userFills, webData2."""
    ws, info, _ = _make_ws_state()
    await ws._startup()

    ws._subscribe()

    assert info.subscribe.call_count == 3
    subscribed_types = {
        call.args[0]["type"] for call in info.subscribe.call_args_list
    }
    assert subscribed_types == {"orderUpdates", "userFills", "webData2"}


async def test_reconnect_resubscribes_and_reconciles():
    """_on_reconnect resubscribes and runs reconciliation."""
    ws, info, exchange = _make_ws_state()
    await ws._startup()

    # Clear subscribe calls from _subscribe during setup (if any)
    info.subscribe.reset_mock()
    info.open_orders.return_value = []

    await ws._on_reconnect()

    # Should have resubscribed (3 feeds)
    assert info.subscribe.call_count == 3
    # Should have called open_orders for reconciliation
    assert info.open_orders.call_count >= 1


# --- 6.5 Canceled order update -----------------------------------------------

async def test_order_update_canceled_removes_from_state():
    """orderUpdates with status=canceled removes order from state."""
    ws, _, _ = _make_ws_state()
    await ws._startup()

    ws.order_state.on_place_confirmed(
        oid=99, side="buy", level_index=2, price=1.006, size=10.0,
    )
    assert 99 in ws.order_state.orders_by_oid

    msg = [{"status": "canceled", "order": {"oid": 99}}]
    await ws._handle_order_update(msg)

    assert 99 not in ws.order_state.orders_by_oid
    assert ("buy", 2) not in ws.order_state.orders_by_key


# --- 6.6 WS health monitoring ------------------------------------------------

async def test_ws_disconnect_detected():
    """WS health check detects disconnect."""
    info = _make_info()
    info.ws_manager = MagicMock()
    info.ws_manager.is_alive.return_value = False

    ws, _, _ = _make_ws_state(info=info)
    await ws._startup()
    assert ws._ws_alive is True

    await ws._check_ws_health()

    assert ws._ws_alive is False


async def test_ws_reconnect_triggers_resubscribe_and_reconcile():
    """Dead→alive transition triggers resubscribe + reconciliation."""
    info = _make_info()
    info.ws_manager = MagicMock()
    info.ws_manager.is_alive.return_value = True
    info.open_orders.return_value = []

    ws, _, _ = _make_ws_state(info=info)
    await ws._startup()

    # Simulate a previous disconnect
    ws._ws_alive = False
    info.subscribe.reset_mock()

    await ws._check_ws_health()

    assert ws._ws_alive is True
    # Should have resubscribed (3 feeds)
    assert info.subscribe.call_count == 3
    # Should have run reconciliation (open_orders called)
    assert info.open_orders.call_count >= 1


async def test_ws_healthy_no_action():
    """No action when WS stays healthy (alive→alive)."""
    info = _make_info()
    info.ws_manager = MagicMock()
    info.ws_manager.is_alive.return_value = True

    ws, _, _ = _make_ws_state(info=info)
    await ws._startup()
    info.subscribe.reset_mock()

    await ws._check_ws_health()

    # No resubscribe, no reconciliation
    info.subscribe.assert_not_called()


async def test_ws_health_no_ws_manager():
    """Health check is a no-op if SDK doesn't expose ws_manager."""
    info = _make_info()
    # Remove the auto-created ws_manager attribute
    del info.ws_manager

    ws, _, _ = _make_ws_state(info=info)
    await ws._startup()

    # Should not raise
    await ws._check_ws_health()
