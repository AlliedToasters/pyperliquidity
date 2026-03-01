"""Batch emitter — budget-aware, prioritized order emission.

The only module that performs exchange I/O for order management.
Receives an OrderDiff and executes it against the Hyperliquid API
via batch operations, respecting rate-limit budget constraints.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from pyperliquidity.order_differ import OrderDiff
from pyperliquidity.order_state import OrderState
from pyperliquidity.quoting_engine import DesiredOrder
from pyperliquidity.rate_limit import RateLimitBudget

logger = logging.getLogger(__name__)

# --- Constants ----------------------------------------------------------------

SAFETY_MARGIN: int = 100
MAX_MUTATIONS_PER_TICK: int = 20
BALANCE_COOLDOWN_S: float = 60.0
REJECT_COOLDOWN_S: float = 10.0
CONSECUTIVE_REJECT_THRESHOLD: int = 3

_ALO_ORDER_TYPE: dict[str, Any] = {"limit": {"tif": "Alo"}}


# --- Result type --------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EmitResult:
    """Summary of a single emit() call."""

    n_cancelled: int
    n_modified: int
    n_placed: int
    n_errors: int
    cancel_only_mode: bool


# --- Response parsing ---------------------------------------------------------

def _parse_statuses(response: Any) -> list[dict[str, Any]]:
    """Extract the statuses array from an SDK batch response."""
    if isinstance(response, dict) and response.get("status") == "ok":
        data = response.get("response", {}).get("data", {})
        statuses: list[dict[str, Any]] = data.get("statuses", [])
        return statuses
    return []


def _is_alo_rejection(error_msg: str) -> bool:
    """True if the error indicates an ALO order would have crossed the spread."""
    return "Post-only would take" in error_msg


# --- Emitter ------------------------------------------------------------------

class BatchEmitter:
    """Budget-aware, prioritized batch order emitter.

    Parameters
    ----------
    coin : str
        The coin/market name (e.g., ``"@1434"``).
    asset_id : int
        Spot asset ID (``spot_index + 10000``).
    exchange : object
        Hyperliquid SDK exchange object exposing ``bulk_orders``,
        ``bulk_modify_orders_new``, and ``bulk_cancel``.
    order_state : OrderState
        Order state tracker for lifecycle notifications.
    clock : callable
        Monotonic clock (default ``time.monotonic``).
    """

    def __init__(
        self,
        coin: str,
        asset_id: int,
        exchange: Any,
        order_state: OrderState,
        clock: Any = time.monotonic,
    ) -> None:
        self.coin = coin
        self.asset_id = asset_id
        self._exchange = exchange
        self._order_state = order_state
        self._clock = clock
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._consecutive_rejects: dict[str, int] = {}

    # -- Cooldown management ---------------------------------------------------

    def _is_cooled_down(self, side: str, now: float) -> bool:
        key = (self.coin, side)
        expiry = self._cooldowns.get(key)
        if expiry is None:
            return False
        if now >= expiry:
            del self._cooldowns[key]
            return False
        return True

    def _set_cooldown(self, side: str, duration: float) -> None:
        self._cooldowns[(self.coin, side)] = self._clock() + duration

    def _clear_cooldown(self, side: str) -> None:
        self._cooldowns.pop((self.coin, side), None)

    # -- Main entry point ------------------------------------------------------

    async def emit(self, diff: OrderDiff, budget: RateLimitBudget) -> EmitResult:
        """Execute an OrderDiff against the exchange.

        Flow: budget gating → priority trimming → cooldown filter →
        execute cancels → execute modifies → execute places.
        """
        n_cancel = len(diff.cancels)
        n_modify = len(diff.modifies)
        n_place = len(diff.places)
        total = n_cancel + n_modify + n_place

        if total == 0:
            return EmitResult(0, 0, 0, 0, cancel_only_mode=False)

        # Budget gating
        cancel_only = budget.remaining() < total + SAFETY_MARGIN

        cancels = list(diff.cancels)
        modifies: list[tuple[int, DesiredOrder]] = (
            [] if cancel_only else list(diff.modifies)
        )
        places: list[DesiredOrder] = [] if cancel_only else list(diff.places)

        # Priority trimming (cancels never trimmed)
        if not cancel_only:
            mut_total = len(cancels) + len(modifies) + len(places)
            if mut_total > MAX_MUTATIONS_PER_TICK:
                room = MAX_MUTATIONS_PER_TICK - len(cancels)
                if room <= 0:
                    modifies = []
                    places = []
                elif len(modifies) <= room:
                    places = places[: room - len(modifies)]
                else:
                    modifies = modifies[:room]
                    places = []

        # Cooldown filter on places
        if places:
            now = self._clock()
            places = [p for p in places if not self._is_cooled_down(p.side, now)]

        # Execute in priority order
        n_cancelled = n_modified = n_placed = n_errors = 0

        if cancels:
            ok, err = await self._execute_cancels(cancels, budget)
            n_cancelled += ok
            n_errors += err

        if modifies:
            ok, err = await self._execute_modifies(modifies, budget)
            n_modified += ok
            n_errors += err

        if places:
            ok, err = await self._execute_places(places, budget)
            n_placed += ok
            n_errors += err

        return EmitResult(
            n_cancelled=n_cancelled,
            n_modified=n_modified,
            n_placed=n_placed,
            n_errors=n_errors,
            cancel_only_mode=cancel_only,
        )

    # -- Batch executors -------------------------------------------------------

    async def _execute_cancels(
        self,
        cancel_oids: list[int],
        budget: RateLimitBudget,
    ) -> tuple[int, int]:
        reqs = [{"a": self.asset_id, "o": oid} for oid in cancel_oids]

        try:
            response = await asyncio.to_thread(self._exchange.bulk_cancel, reqs)
        finally:
            budget.on_request()

        statuses = _parse_statuses(response)
        n_ok = n_err = 0

        for i, oid in enumerate(cancel_oids):
            status = statuses[i] if i < len(statuses) else {}
            if "error" in status:
                n_err += 1
                logger.debug("Cancel error oid=%d: %s", oid, status["error"])
            else:
                n_ok += 1
            # Always remove — a cancel error means it was already filled.
            self._order_state.remove_ghost(oid)

        return n_ok, n_err

    async def _execute_modifies(
        self,
        modifies: list[tuple[int, DesiredOrder]],
        budget: RateLimitBudget,
    ) -> tuple[int, int]:
        # Cross-side assertion
        for oid, desired in modifies:
            tracked = self._order_state.orders_by_oid.get(oid)
            assert tracked is None or tracked.side == desired.side, (
                f"Cross-side modify: oid={oid} tracked_side="
                f"{tracked.side if tracked else None} desired_side={desired.side}"
            )

        reqs = [
            {
                "oid": oid,
                "order": {
                    "a": self.asset_id,
                    "b": desired.side == "buy",
                    "p": str(desired.price),
                    "s": str(desired.size),
                    "r": False,
                    "t": _ALO_ORDER_TYPE,
                },
            }
            for oid, desired in modifies
        ]

        try:
            response = await asyncio.to_thread(
                self._exchange.bulk_modify_orders_new, reqs
            )
        finally:
            budget.on_request()

        statuses = _parse_statuses(response)
        n_ok = n_err = 0

        for i, (original_oid, desired) in enumerate(modifies):
            status = statuses[i] if i < len(statuses) else {}

            if "resting" in status:
                new_oid = status["resting"].get("oid", original_oid)
                self._order_state.on_modify_response(
                    original_oid=original_oid,
                    new_oid=new_oid,
                    status="resting",
                )
                # Update price/size on the tracked order after successful modify.
                order = self._order_state.orders_by_oid.get(new_oid)
                if order is not None:
                    order.price = desired.price
                    order.size = desired.size
                n_ok += 1
            elif "error" in status:
                self._order_state.on_modify_response(
                    original_oid=original_oid,
                    new_oid=None,
                    status=f"error: {status['error']}",
                )
                n_err += 1
            else:
                logger.warning(
                    "Unhandled modify status oid=%d: %s", original_oid, status,
                )
                self._order_state.remove_ghost(original_oid)
                n_err += 1

        return n_ok, n_err

    async def _execute_places(
        self,
        places: list[DesiredOrder],
        budget: RateLimitBudget,
    ) -> tuple[int, int]:
        reqs = [
            {
                "a": self.asset_id,
                "b": d.side == "buy",
                "p": str(d.price),
                "s": str(d.size),
                "r": False,
                "t": _ALO_ORDER_TYPE,
            }
            for d in places
        ]

        try:
            response = await asyncio.to_thread(self._exchange.bulk_orders, reqs)
        finally:
            budget.on_request()

        statuses = _parse_statuses(response)
        n_ok = n_err = 0

        for i, desired in enumerate(places):
            status = statuses[i] if i < len(statuses) else {}

            if "resting" in status:
                new_oid = status["resting"]["oid"]
                self._order_state.on_place_confirmed(
                    oid=new_oid,
                    side=desired.side,
                    level_index=desired.level_index,
                    price=desired.price,
                    size=desired.size,
                )
                self._clear_cooldown(desired.side)
                self._consecutive_rejects[desired.side] = 0
                n_ok += 1
            elif "error" in status:
                error_msg = status["error"]

                if "Insufficient spot balance" in error_msg:
                    self._set_cooldown(desired.side, BALANCE_COOLDOWN_S)
                elif _is_alo_rejection(error_msg):
                    pass  # Expected — no cooldown, no reject counter increment.
                else:
                    count = self._consecutive_rejects.get(desired.side, 0) + 1
                    self._consecutive_rejects[desired.side] = count
                    if count >= CONSECUTIVE_REJECT_THRESHOLD:
                        self._set_cooldown(desired.side, REJECT_COOLDOWN_S)
                        self._consecutive_rejects[desired.side] = 0
                n_err += 1
            else:
                logger.warning(
                    "Unhandled place status side=%s level=%d: %s",
                    desired.side, desired.level_index, status,
                )
                n_err += 1

        return n_ok, n_err
