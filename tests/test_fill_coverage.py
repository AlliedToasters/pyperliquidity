"""Integration tests: verify all n_orders levels stay covered after fills.

Uses MockExchange/MockInfo for realistic multi-tick simulation of the
fill → boundary shift → requote → emit pipeline.
"""

from __future__ import annotations

from pyperliquidity.ws_state import WsState
from tests.mock_exchange import MockExchange, MockInfo

# --- Config -------------------------------------------------------------------

N_ORDERS = 20
N_SEEDED = 10
ORDER_SZ = 10.0
START_PX = 1.0
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
        start_px=START_PX,
        n_orders=N_ORDERS,
        order_sz=ORDER_SZ,
        n_seeded_levels=N_SEEDED,
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


def _assert_full_coverage(ws: WsState, n_orders: int) -> None:
    """Assert every level 0..n_orders-1 has exactly one order in order_state."""
    covered_levels: dict[int, str] = {}
    for o in ws.order_state.orders_by_oid.values():
        assert o.level_index not in covered_levels, (
            f"Duplicate order at level {o.level_index}: "
            f"side={o.side} vs {covered_levels[o.level_index]}"
        )
        covered_levels[o.level_index] = o.side

    total = len(covered_levels)
    assert total == n_orders, (
        f"Expected {n_orders} covered levels, got {total}. "
        f"Missing: {set(range(n_orders)) - set(covered_levels.keys())}"
    )

    # Verify structural consistency: asks at boundary and above, bids below
    for lvl, side in covered_levels.items():
        if lvl >= ws.boundary_level:
            assert side == "sell", (
                f"Level {lvl} >= boundary {ws.boundary_level} should be sell, got {side}"
            )
        else:
            assert side == "buy", (
                f"Level {lvl} < boundary {ws.boundary_level} should be buy, got {side}"
            )


async def _startup_and_initial_tick(ws: WsState) -> None:
    """Run startup and one tick to place initial orders."""
    await ws._startup()
    await ws._tick()


def _find_oid_at_level(ws: WsState, level: int) -> int:
    """Find the OID of the order at a given level."""
    for o in ws.order_state.orders_by_oid.values():
        if o.level_index == level:
            return o.oid
    raise ValueError(f"No order at level {level}")


async def _fill_boundary_ask(
    ws: WsState, ex: MockExchange, tid: int,
) -> None:
    """Fill the ask at the current boundary level and process it."""
    oid = _find_oid_at_level(ws, ws.boundary_level)
    fill_event = ex.fill_order(oid, tid=tid)
    await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})


async def _fill_boundary_bid(
    ws: WsState, ex: MockExchange, tid: int,
) -> None:
    """Fill the bid at boundary_level - 1 and process it."""
    bid_level = ws.boundary_level - 1
    oid = _find_oid_at_level(ws, bid_level)
    fill_event = ex.fill_order(oid, tid=tid)
    await ws._handle_fill({"user": "0xtest", "fills": [fill_event]})


# --- Tests --------------------------------------------------------------------

async def test_single_ask_fill_maintains_coverage():
    """Fill 1 ask at boundary → 20 orders remain after requote."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)
    _assert_full_coverage(ws, N_ORDERS)

    # Fill the ask at the boundary
    await _fill_boundary_ask(ws, ex, tid=1)
    # Tick to requote
    await ws._tick()
    _assert_full_coverage(ws, N_ORDERS)


async def test_sequential_ask_fills_walk_boundary_up():
    """Fill 5 asks sequentially → coverage maintained at each step."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)
    _assert_full_coverage(ws, N_ORDERS)

    for i in range(5):
        await _fill_boundary_ask(ws, ex, tid=100 + i)
        await ws._tick()
        _assert_full_coverage(ws, N_ORDERS)


async def test_sequential_bid_fills_walk_boundary_down():
    """Fill 5 bids sequentially → coverage maintained at each step."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)
    _assert_full_coverage(ws, N_ORDERS)

    for i in range(5):
        await _fill_boundary_bid(ws, ex, tid=200 + i)
        await ws._tick()
        _assert_full_coverage(ws, N_ORDERS)


async def test_round_trip_coverage():
    """Walk 3 up (ask fills), then 3 down (bid fills) → coverage at every step."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)
    _assert_full_coverage(ws, N_ORDERS)

    # Walk up 3
    for i in range(3):
        await _fill_boundary_ask(ws, ex, tid=300 + i)
        await ws._tick()
        _assert_full_coverage(ws, N_ORDERS)

    # Walk down 3
    for i in range(3):
        await _fill_boundary_bid(ws, ex, tid=400 + i)
        await ws._tick()
        _assert_full_coverage(ws, N_ORDERS)


async def test_all_asks_filled_becomes_all_bids():
    """Fill all asks → boundary=n_orders, all orders are bids."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)

    n_asks = N_ORDERS - N_SEEDED  # 10 asks initially
    for i in range(n_asks):
        await _fill_boundary_ask(ws, ex, tid=500 + i)
        await ws._tick()

    assert ws.boundary_level == N_ORDERS
    # All orders should be bids
    for o in ws.order_state.orders_by_oid.values():
        assert o.side == "buy", f"Expected all bids, got {o.side} at level {o.level_index}"
    assert len(ws.order_state.orders_by_oid) == N_ORDERS


async def test_all_bids_filled_becomes_all_asks():
    """Fill all bids → boundary=0, all orders are asks."""
    ws, ex, info = _make_system()
    await _startup_and_initial_tick(ws)

    n_bids = N_SEEDED  # 10 bids initially
    for i in range(n_bids):
        await _fill_boundary_bid(ws, ex, tid=600 + i)
        await ws._tick()

    assert ws.boundary_level == 0
    # All orders should be asks
    for o in ws.order_state.orders_by_oid.values():
        assert o.side == "sell", f"Expected all asks, got {o.side} at level {o.level_index}"
    assert len(ws.order_state.orders_by_oid) == N_ORDERS
