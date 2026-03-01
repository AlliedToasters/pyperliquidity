"""WebSocket state manager — orchestrator wiring all modules together.

This is the I/O boundary: startup REST calls, WebSocket subscriptions,
tick loop, and periodic reconciliation.  Keeps logic minimal — thin glue
calling into the pure-computation and I/O modules.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from pyperliquidity.batch_emitter import BatchEmitter
from pyperliquidity.inventory import Inventory
from pyperliquidity.order_differ import OrderDiff, compute_diff
from pyperliquidity.order_state import OrderState
from pyperliquidity.pricing_grid import PricingGrid
from pyperliquidity.quoting_engine import compute_desired_orders
from pyperliquidity.rate_limit import RateLimitBudget

logger = logging.getLogger(__name__)


class WsState:
    """Orchestrator that wires all modules into a running market maker.

    Parameters
    ----------
    coin : str
        Spot coin name (e.g. ``"PURR"``).
    start_px : float
        Starting price for the geometric grid.
    n_orders : int
        Number of price levels.
    order_sz : float
        Size of a full order tranche.
    n_seeded_levels : int
        Number of initially seeded ask levels.
    info : object
        Hyperliquid SDK info object (REST + WS).
    exchange : object
        Hyperliquid SDK exchange object (mutations).
    address : str
        User's wallet address.
    interval_s : float
        Tick loop interval in seconds.
    dead_zone_bps : float
        Dead zone threshold for the order differ.
    price_tolerance_bps : float
        Price tolerance for the order differ.
    size_tolerance_pct : float
        Size tolerance for the order differ.
    reconcile_every : int
        Run reconciliation every N ticks.
    min_notional : float
        Minimum notional value for an order.
    allocated_token : float
        Maximum token balance the strategy may use (``inf`` = full account).
    allocated_usdc : float
        Maximum USDC balance the strategy may use (``inf`` = full account).
    """

    def __init__(
        self,
        coin: str,
        start_px: float,
        n_orders: int,
        order_sz: float,
        n_seeded_levels: int,
        info: Any,
        exchange: Any,
        address: str,
        interval_s: float = 3.0,
        dead_zone_bps: float = 5.0,
        price_tolerance_bps: float = 1.0,
        size_tolerance_pct: float = 1.0,
        reconcile_every: int = 20,
        min_notional: float = 0.0,
        allocated_token: float = float("inf"),
        allocated_usdc: float = float("inf"),
    ) -> None:
        self.coin = coin
        self.start_px = start_px
        self.n_orders = n_orders
        self.order_sz = order_sz
        self.n_seeded_levels = n_seeded_levels
        self.interval_s = interval_s
        self.dead_zone_bps = dead_zone_bps
        self.price_tolerance_bps = price_tolerance_bps
        self.size_tolerance_pct = size_tolerance_pct
        self.reconcile_every = reconcile_every
        self.min_notional = min_notional
        self._allocated_token = allocated_token
        self._allocated_usdc = allocated_usdc

        self._info = info
        self._exchange = exchange
        self._address = address

        # Modules — initialized during startup
        self.grid: PricingGrid | None = None
        self.order_state: OrderState = OrderState()
        self.inventory: Inventory | None = None
        self.rate_limit: RateLimitBudget = RateLimitBudget()
        self.emitter: BatchEmitter | None = None
        self.asset_id: int = 0
        self.boundary_level: int = 0
        self._balance_coin: str = ""  # resolved during _startup from spot_meta

        self._loop: asyncio.AbstractEventLoop | None = None
        self._tick_count: int = 0
        self._ws_alive: bool = True

    # -- Startup ---------------------------------------------------------------

    async def _startup(self) -> None:
        """Seed all modules from REST data."""
        self._loop = asyncio.get_running_loop()

        # 1. Resolve coin → asset_id and base token name for balance lookups
        spot_meta = await asyncio.to_thread(self._info.spot_meta)
        universe = spot_meta["universe"]
        spot_entry: dict | None = None
        for token in universe:
            if token["name"] == self.coin:
                spot_entry = token
                break
        if spot_entry is None:
            raise ValueError(f"Coin {self.coin!r} not found in spot_meta universe")
        self.asset_id = spot_entry["index"] + 10_000
        # Resolve base token name (e.g. "@1434" → "THC") for balance lookups
        base_token_idx = spot_entry["tokens"][0]
        self._balance_coin = spot_meta["tokens"][base_token_idx]["name"]

        # 2. Construct PricingGrid
        self.grid = PricingGrid(
            start_px=self.start_px,
            n_orders=self.n_orders,
        )

        # 3. Seed OrderState from open_orders
        open_orders = await asyncio.to_thread(self._info.open_orders, self._address)
        for order in open_orders:
            if order.get("coin") != self.coin:
                continue
            oid = order["oid"]
            side: Literal["buy", "sell"] = "buy" if order["side"] == "B" else "sell"
            px = float(order["limitPx"])
            sz = float(order["sz"])
            level_index = self.grid.level_for_price(px)
            if level_index is not None:
                self.order_state.on_place_confirmed(
                    oid=oid, side=side, level_index=level_index, price=px, size=sz,
                )

        # 4. Seed Inventory from spot_user_state
        spot_state = await asyncio.to_thread(
            self._info.spot_user_state, self._address,
        )
        token_bal = 0.0
        usdc_bal = 0.0
        for bal in spot_state.get("balances", []):
            if bal["coin"] == self._balance_coin:
                token_bal = float(bal["total"])
            elif bal["coin"] == "USDC":
                usdc_bal = float(bal["total"])

        self.inventory = Inventory(
            order_sz=self.order_sz,
            allocated_token=self._allocated_token,
            allocated_usdc=self._allocated_usdc,
            account_token=token_bal,
            account_usdc=usdc_bal,
        )

        # 5. Seed RateLimitBudget from user_rate_limit
        rate_info = await asyncio.to_thread(
            self._info.user_rate_limit, self._address,
        )
        self.rate_limit.sync_from_exchange(
            cum_vlm=float(rate_info.get("cumVlm", 0)),
            n_requests=int(rate_info.get("nRequestsUsed", 0)),
        )

        # 6. Construct BatchEmitter
        self.emitter = BatchEmitter(
            coin=self.coin,
            asset_id=self.asset_id,
            exchange=self._exchange,
            order_state=self.order_state,
        )

        # 7. Compute initial boundary_level from seeded orders
        self.boundary_level = self._compute_boundary_level()

        logger.info(
            "Startup complete: coin=%s asset_id=%d boundary=%d orders=%d",
            self.coin, self.asset_id, self.boundary_level,
            len(self.order_state.orders_by_oid),
        )

    def _compute_boundary_level(self) -> int:
        """Derive boundary_level from current order state.

        The boundary is the lowest ask level.  If no asks exist,
        defaults to n_seeded_levels.
        """
        ask_levels = [
            o.level_index for o in self.order_state.orders_by_oid.values()
            if o.side == "sell"
        ]
        if ask_levels:
            return min(ask_levels)
        return self.n_seeded_levels

    # -- WebSocket subscriptions -----------------------------------------------

    def _subscribe(self) -> None:
        """Subscribe to WS feeds via the SDK."""
        self._info.subscribe(
            {"type": "orderUpdates", "user": self._address},
            self._on_order_update_sync,
        )
        self._info.subscribe(
            {"type": "userFills", "user": self._address},
            self._on_fill_sync,
        )
        self._info.subscribe(
            {"type": "webData2", "user": self._address},
            self._on_balance_sync,
        )

    # -- Sync → async bridge ---------------------------------------------------

    def _on_order_update_sync(self, msg: Any) -> None:
        """Sync callback from SDK WS thread → async handler."""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._handle_order_update(msg), self._loop,
            )

    def _on_fill_sync(self, msg: Any) -> None:
        """Sync callback from SDK WS thread → async handler."""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._handle_fill(msg), self._loop,
            )

    def _on_balance_sync(self, msg: Any) -> None:
        """Sync callback from SDK WS thread → async handler."""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._handle_balance_update(msg), self._loop,
            )

    # -- Async handlers --------------------------------------------------------

    async def _handle_order_update(self, msg: Any) -> None:
        """Route orderUpdates to OrderState."""
        if not isinstance(msg, list):
            msg = [msg]
        for update in msg:
            status = update.get("status", "")
            order = update.get("order", {})
            oid = order.get("oid")
            if oid is None:
                continue

            if status == "resting":
                side: Literal["buy", "sell"] = "buy" if order.get("side") == "B" else "sell"
                px = float(order.get("limitPx", 0))
                sz = float(order.get("sz", 0))
                level_index = self.grid.level_for_price(px) if self.grid else None
                if level_index is not None:
                    self.order_state.on_place_confirmed(
                        oid=oid, side=side, level_index=level_index,
                        price=px, size=sz,
                    )
            elif "Cannot modify" in status:
                self.order_state.on_modify_response(
                    original_oid=oid, new_oid=None, status=status,
                )
            elif status == "canceled":
                self.order_state.remove_ghost(oid)

    async def _handle_fill(self, msg: Any) -> None:
        """Route userFills to OrderState → Inventory."""
        if not isinstance(msg, list):
            msg = [msg]
        for fill in msg:
            tid = fill.get("tid")
            oid = fill.get("oid")
            sz = float(fill.get("sz", 0))
            px = float(fill.get("px", 0))
            if tid is None or oid is None:
                continue

            result = self.order_state.on_fill(tid=tid, oid=oid, fill_sz=sz)
            if result is not None and self.inventory is not None:
                volume_usd = px * sz
                self.rate_limit.on_fill(volume_usd)
                if result.side == "sell":
                    self.inventory.on_ask_fill(px=px, sz=sz)
                else:
                    self.inventory.on_bid_fill(px=px, sz=sz)

    async def _handle_balance_update(self, msg: Any) -> None:
        """Route webData2 balance updates to Inventory."""
        if self.inventory is None:
            return
        balances = msg if isinstance(msg, dict) else {}
        # webData2 typically has a "clearinghouseState" or similar structure.
        # Extract spot balances from the message.
        spot_balances = balances.get("spotBalances", balances.get("balances", []))
        if not isinstance(spot_balances, list):
            return
        token_bal: float | None = None
        usdc_bal: float | None = None
        for bal in spot_balances:
            coin = bal.get("coin", "")
            if coin == self.coin:
                token_bal = float(bal.get("total", 0))
            elif coin == "USDC":
                usdc_bal = float(bal.get("total", 0))
        if token_bal is not None and usdc_bal is not None:
            self.inventory.on_balance_update(token=token_bal, usdc=usdc_bal)

    # -- Tick loop -------------------------------------------------------------

    async def _tick(self) -> None:
        """Run one iteration of the quoting pipeline."""
        assert self.grid is not None
        assert self.inventory is not None
        assert self.emitter is not None

        self.boundary_level = self._compute_boundary_level()

        desired = compute_desired_orders(
            grid=self.grid,
            boundary_level=self.boundary_level,
            effective_token=self.inventory.effective_token,
            effective_usdc=self.inventory.effective_usdc,
            order_sz=self.order_sz,
            min_notional=self.min_notional,
        )

        current = self.order_state.get_current_orders()

        diff = compute_diff(
            desired=desired,
            current=current,
            dead_zone_bps=self.dead_zone_bps,
            price_tolerance_bps=self.price_tolerance_bps,
            size_tolerance_pct=self.size_tolerance_pct,
        )

        result = await self.emitter.emit(diff, self.rate_limit)

        logger.debug(
            "Tick %d: boundary=%d desired=%d current=%d | "
            "placed=%d modified=%d cancelled=%d errors=%d | %s",
            self._tick_count, self.boundary_level, len(desired), len(current),
            result.n_placed, result.n_modified, result.n_cancelled, result.n_errors,
            self.rate_limit.log_status(),
        )

    async def _tick_loop(self) -> None:
        """Run the tick loop forever at interval_s."""
        while True:
            self._tick_count += 1

            # Check WS health every tick (~3s)
            await self._check_ws_health()

            try:
                await self._tick()
            except Exception:
                logger.exception("Tick %d failed", self._tick_count)

            # Periodic reconciliation
            if self._tick_count % self.reconcile_every == 0:
                try:
                    await self._reconcile()
                except Exception:
                    logger.exception("Reconciliation failed at tick %d", self._tick_count)

            await asyncio.sleep(self.interval_s)

    # -- Reconciliation --------------------------------------------------------

    async def _reconcile(self) -> None:
        """REST-based state reconciliation."""
        assert self.emitter is not None
        assert self.inventory is not None

        # 1. Reconcile orders
        open_orders = await asyncio.to_thread(self._info.open_orders, self._address)
        exchange_oids: set[int] = set()
        for order in open_orders:
            if order.get("coin") == self.coin:
                exchange_oids.add(order["oid"])

        result = self.order_state.reconcile(exchange_oids)

        # Cancel orphaned orders
        if result.orphaned_oids:
            orphan_diff = OrderDiff(cancels=list(result.orphaned_oids))
            await self.emitter.emit(orphan_diff, self.rate_limit)
            logger.info("Reconciliation: cancelled %d orphans", len(result.orphaned_oids))

        # Remove ghost orders
        for oid in result.ghost_oids:
            self.order_state.remove_ghost(oid)
        if result.ghost_oids:
            logger.info("Reconciliation: removed %d ghosts", len(result.ghost_oids))

        # 2. Reconcile balances
        spot_state = await asyncio.to_thread(
            self._info.spot_user_state, self._address,
        )
        token_bal = 0.0
        usdc_bal = 0.0
        for bal in spot_state.get("balances", []):
            if bal["coin"] == self._balance_coin:
                token_bal = float(bal["total"])
            elif bal["coin"] == "USDC":
                usdc_bal = float(bal["total"])
        self.inventory.on_balance_update(token=token_bal, usdc=usdc_bal)

    # -- WS health monitoring --------------------------------------------------

    async def _check_ws_health(self) -> None:
        """Detect WS disconnect/reconnect via ws_manager.is_alive().

        On dead→alive transition, triggers resubscribe + full reconciliation.
        """
        try:
            alive = self._info.ws_manager.is_alive()
        except AttributeError:
            return  # SDK object doesn't expose ws_manager

        if alive and not self._ws_alive:
            # Was dead, now alive — reconnection detected
            self._ws_alive = True
            logger.info("WebSocket reconnected, running reconciliation")
            await self._on_reconnect()
        elif not alive and self._ws_alive:
            logger.warning("WebSocket disconnected")
            self._ws_alive = False

    # -- Reconnection ----------------------------------------------------------

    async def _on_reconnect(self) -> None:
        """Handle WS reconnection: resubscribe + immediate reconciliation."""
        self._subscribe()
        await self._reconcile()
        logger.info("WS reconnected: resubscribed and reconciled")

    # -- Main entry point ------------------------------------------------------

    async def run(self) -> None:
        """Start the market maker: startup → subscribe → tick loop."""
        await self._startup()
        self._subscribe()
        await self._tick_loop()
