"""Integration tests: verify cursor shifts on fills and maintains orders.

Uses MockExchange/MockInfo for realistic multi-tick simulation of the
fill → inventory update → requote → emit pipeline on a fixed grid.
"""

from __future__ import annotations

import math

from pyperliquidity.ws_state import WsState
from tests.mock_exchange import MockExchange, MockInfo

# --- Config -------------------------------------------------------------------

N_ORDERS = 20  # total grid levels
ORDER_SZ = 10.0
# Token balance chosen so cursor sits mid-grid: 100 tokens / 10 sz = 10 asks, cursor=10
TOKEN_BAL = 100.0
USDC_BAL = 10_000.0  # generous — enough for all bid levels
START_PX = 10.0

# --- Helpers ------------------------------------------------------------------


def _make_system() -> tuple[WsState, MockExchange, MockInfo]:
    """Build a WsState wired to MockExchange/MockInfo."""
    ex = MockExchange()
    info = MockInfo(
        mock_exchange=ex,
        coin="TEST",
        spot_index=5,
        token_bal=TOKEN_BAL,
        usdc_bal=USDC_BAL,
    )
    ws = WsState(
        coin="TEST",
        start_px=START_PX,
        n_orders=N_ORDERS,
        order_sz=ORDER_SZ,
        info=info,
        exchange=ex,
        address="0xtest",
        interval_s=3.0,
        dead_zone_bps=5.0,
        price_tolerance_bps=1.0,
        size_tolerance_pct=1.0,
        reconcile_every=100,
        allocated_token=TOKEN_BAL,
        allocated_usdc=USDC_BAL,
    )
    return ws, ex, info


def _cursor(ws: WsState) -> int:
    """Derive cursor from current inventory state."""
    assert ws.inventory is not None
    assert ws.grid is not None
    eff = ws.inventory.effective_token
    n_full = math.floor(eff / ws.order_sz) if eff > 0 else 0
    partial = eff % ws.order_sz if eff > 0 else 0.0
    total_ask = min(n_full + (1 if partial > 0 else 0), ws.grid.n_orders)
    return ws.grid.n_orders - total_ask


async def _startup_and_initial_tick(ws: WsState) -> None:
    """Run startup and one tick to place initial orders."""
    await ws._startup()
    await ws._tick()


def _count_orders_by_side(ws: WsState) -> tuple[int, int]:
    """Return (n_asks, n_bids) from current order state."""
    asks = sum(1 for o in ws.order_state.orders_by_oid.values() if o.side == "sell")
    bids = sum(1 for o in ws.order_state.orders_by_oid.values() if o.side == "buy")
    return asks, bids


def _find_ask_oid(ws: WsState) -> int:
    """Find the OID of the closest-to-cursor ask order (lowest level_index)."""
    asks = [o for o in ws.order_state.orders_by_oid.values() if o.side == "sell"]
    if not asks:
        raise ValueError("No ask orders found")
    return min(asks, key=lambda o: o.level_index).oid


def _find_bid_oid(ws: WsState) -> int:
    """Find the OID of the closest-to-cursor bid order (highest level_index)."""
    bids = [o for o in ws.order_state.orders_by_oid.values() if o.side == "buy"]
    if not bids:
        raise ValueError("No bid orders found")
    return max(bids, key=lambda o: o.level_index).oid


# --- Tests --------------------------------------------------------------------


async def test_initial_orders_fill_grid():
    """After startup + tick, should have asks + bids = n_orders total."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)

    n_asks, n_bids = _count_orders_by_side(ws)
    assert n_asks == 10  # cursor=10, levels 10-19
    assert n_bids == 10  # levels 0-9
    assert n_asks + n_bids == N_ORDERS


async def test_ask_fill_shifts_cursor():
    """Fill an ask → tokens decrease → cursor shifts up."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)

    cursor_before = _cursor(ws)
    ask_oid = _find_ask_oid(ws)

    # Fill the closest ask
    fill_event = ex.fill_order(ask_oid, tid=1)
    await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})

    # Tick to requote
    await ws._tick()

    # Cursor should have shifted up (fewer tokens → fewer asks)
    assert _cursor(ws) > cursor_before

    # Should still have orders on both sides
    n_asks, n_bids = _count_orders_by_side(ws)
    assert n_asks > 0
    assert n_bids > 0


async def test_sequential_fills_maintain_orders():
    """Fill 3 asks then 3 bids → orders exist on both sides throughout."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)

    # Fill 3 asks
    for tid in range(100, 103):
        ask_oid = _find_ask_oid(ws)
        fill_event = ex.fill_order(ask_oid, tid=tid)
        await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})
        await ws._tick()

        n_asks, n_bids = _count_orders_by_side(ws)
        assert n_asks > 0, f"No asks after fill tid={tid}"
        assert n_bids > 0, f"No bids after fill tid={tid}"

    # Fill 3 bids
    for tid in range(200, 203):
        bid_oid = _find_bid_oid(ws)
        fill_event = ex.fill_order(bid_oid, tid=tid)
        await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})
        await ws._tick()

        n_asks, n_bids = _count_orders_by_side(ws)
        assert n_asks > 0, f"No asks after fill tid={tid}"
        assert n_bids > 0, f"No bids after fill tid={tid}"


async def test_round_trip():
    """Sell then buy back → cursor returns to original position."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)

    cursor_initial = _cursor(ws)

    # Sell one tranche (ask fill → tokens decrease → cursor moves up)
    ask_oid = _find_ask_oid(ws)
    fill_event = ex.fill_order(ask_oid, tid=300)
    await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})
    await ws._tick()

    cursor_after_sell = _cursor(ws)
    assert cursor_after_sell > cursor_initial

    # Buy one tranche (bid fill → tokens increase → cursor moves down)
    bid_oid = _find_bid_oid(ws)
    fill_event = ex.fill_order(bid_oid, tid=301)
    await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})
    await ws._tick()

    cursor_after_buy = _cursor(ws)
    # Cursor should return close to initial (may not be exact due to fee deductions)
    assert abs(cursor_after_buy - cursor_initial) <= 1
