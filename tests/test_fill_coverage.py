"""Integration tests: verify pricing recenters on fills and maintains 2n orders.

Uses MockExchange/MockInfo for realistic multi-tick simulation of the
fill → inventory update → requote → emit pipeline.
"""

from __future__ import annotations

from pyperliquidity.ws_state import WsState
from tests.mock_exchange import MockExchange, MockInfo

# --- Config -------------------------------------------------------------------

N_ORDERS = 10  # per side
ORDER_SZ = 10.0
TOKEN_BAL = 10_000.0  # generous — never balance-limited
USDC_BAL = 100_000.0

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
    )
    return ws, ex, info


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
    """Find the OID of an ask order (lowest level_index = closest to mid)."""
    asks = [o for o in ws.order_state.orders_by_oid.values() if o.side == "sell"]
    if not asks:
        raise ValueError("No ask orders found")
    return min(asks, key=lambda o: o.level_index).oid


def _find_bid_oid(ws: WsState) -> int:
    """Find the OID of a bid order (lowest level_index = closest to mid)."""
    bids = [o for o in ws.order_state.orders_by_oid.values() if o.side == "buy"]
    if not bids:
        raise ValueError("No bid orders found")
    return min(bids, key=lambda o: o.level_index).oid


# --- Tests --------------------------------------------------------------------


async def test_initial_2n_orders():
    """After startup + tick, should have n_orders asks + n_orders bids = 2n total."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)

    n_asks, n_bids = _count_orders_by_side(ws)
    assert n_asks == N_ORDERS
    assert n_bids == N_ORDERS


async def test_ask_fill_reprices():
    """Fill an ask → mid shifts up → requote places new grid around new mid."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)

    mid_before = ws._last_mid
    ask_oid = _find_ask_oid(ws)

    # Fill the closest ask
    fill_event = ex.fill_order(ask_oid, tid=1)
    await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})

    # Tick to requote
    await ws._tick()

    # Mid should have shifted (sold tokens → less tokens, more USDC → higher mid)
    assert ws._last_mid > mid_before

    # Should still have orders on both sides
    n_asks, n_bids = _count_orders_by_side(ws)
    assert n_asks > 0
    assert n_bids > 0


async def test_sequential_fills_symmetric():
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
    """Sell then buy back → mid returns close to original."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)

    mid_initial = ws._last_mid

    # Sell one tranche
    ask_oid = _find_ask_oid(ws)
    fill_event = ex.fill_order(ask_oid, tid=300)
    await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})
    await ws._tick()

    mid_after_sell = ws._last_mid
    assert mid_after_sell > mid_initial

    # Buy one tranche
    bid_oid = _find_bid_oid(ws)
    fill_event = ex.fill_order(bid_oid, tid=301)
    await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})
    await ws._tick()

    mid_after_buy = ws._last_mid
    # Mid should be close to initial (not exact due to spread)
    assert abs(mid_after_buy - mid_initial) / mid_initial < 0.01
