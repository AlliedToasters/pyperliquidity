"""Order state — single source of truth for all resting orders.

Tracks order lifecycle, handles OID swaps from modify operations, detects
ghost orders, and provides the "current orders" snapshot that the order
differ compares against.  No I/O — receives events, doesn't fetch them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class OrderStatus(Enum):
    """Lifecycle status of a tracked order."""

    RESTING = "resting"
    PENDING_PLACE = "pending_place"
    PENDING_MODIFY = "pending_modify"
    PENDING_CANCEL = "pending_cancel"


@dataclass(slots=True)
class TrackedOrder:
    """A resting order tracked by the order state manager."""

    oid: int
    side: Literal["buy", "sell"]
    level_index: int
    price: float
    size: float
    status: OrderStatus = OrderStatus.RESTING


@dataclass(frozen=True, slots=True)
class FillResult:
    """Returned by on_fill so the caller can update inventory."""

    side: Literal["buy", "sell"]
    price: float
    size: float
    fully_filled: bool


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Result of reconciling tracked state against exchange state."""

    orphaned_oids: frozenset[int]
    ghost_oids: frozenset[int]


# Upper bound for the seen_tids dedup set.
_SEEN_TIDS_CAP = 5000

# Orders with remaining size below this are treated as fully filled.
_SIZE_EPSILON = 1e-12


class OrderState:
    """Dual-indexed order tracker with fill dedup and reconciliation.

    Parameters
    ----------
    seen_tids_cap : int
        Maximum number of trade IDs retained for dedup (default 5000).
    """

    def __init__(self, seen_tids_cap: int = _SEEN_TIDS_CAP) -> None:
        self.orders_by_oid: dict[int, TrackedOrder] = {}
        self.orders_by_key: dict[tuple[str, int], TrackedOrder] = {}
        self._seen_tids: set[int] = set()
        self._seen_tids_cap = seen_tids_cap

    # -- Place confirmation ---------------------------------------------------

    def on_place_confirmed(
        self,
        oid: int,
        side: Literal["buy", "sell"],
        level_index: int,
        price: float,
        size: float,
    ) -> None:
        """Record a newly confirmed resting order.

        If an order already exists at the same (side, level_index), the old
        order is evicted from both indices before inserting the new one.
        """
        key = (side, level_index)

        # Evict any existing order at this grid level.
        existing = self.orders_by_key.get(key)
        if existing is not None:
            self.orders_by_oid.pop(existing.oid, None)

        order = TrackedOrder(
            oid=oid,
            side=side,
            level_index=level_index,
            price=price,
            size=size,
            status=OrderStatus.RESTING,
        )
        self.orders_by_oid[oid] = order
        self.orders_by_key[key] = order

    # -- Pending state management ---------------------------------------------

    def mark_pending_modify(self, oid: int) -> None:
        """Mark an order as pending modify.  Called before sending the request."""
        order = self.orders_by_oid.get(oid)
        if order is not None:
            order.status = OrderStatus.PENDING_MODIFY

    def mark_pending_cancel(self, oid: int) -> None:
        """Mark an order as pending cancel.  Called before sending the request."""
        order = self.orders_by_oid.get(oid)
        if order is not None:
            order.status = OrderStatus.PENDING_CANCEL

    # -- Modify response ------------------------------------------------------

    def on_modify_response(
        self,
        original_oid: int,
        new_oid: int | None,
        status: str,
    ) -> None:
        """Handle a modify response from the exchange.

        - "resting" with a new OID → atomic re-key in orders_by_oid.
        - "Cannot modify" error → remove the ghost immediately.
        - Unknown original_oid → no-op (idempotent).
        """
        order = self.orders_by_oid.get(original_oid)

        if "Cannot modify" in status:
            # Ghost — already filled on exchange.  Remove from both indices.
            if order is not None:
                self.orders_by_oid.pop(original_oid, None)
                key = (order.side, order.level_index)
                self.orders_by_key.pop(key, None)
            return

        if order is None:
            return  # Unknown OID, no-op.

        order.status = OrderStatus.RESTING

        if new_oid is not None and new_oid != original_oid:
            # OID swap: insert new key first so the order is always reachable,
            # then remove old key.  orders_by_key is untouched — same object.
            order.oid = new_oid
            self.orders_by_oid[new_oid] = order
            del self.orders_by_oid[original_oid]

    # -- Fill handling --------------------------------------------------------

    def on_fill(
        self,
        tid: int,
        oid: int,
        fill_sz: float,
    ) -> FillResult | None:
        """Process a fill event, deduplicating by trade ID.

        Returns a :class:`FillResult` on the first occurrence of a tid, or
        ``None`` if the tid is a duplicate or the OID is unknown.
        """
        if tid in self._seen_tids:
            return None

        self._seen_tids.add(tid)
        if len(self._seen_tids) > self._seen_tids_cap:
            self._prune_seen_tids()

        order = self.orders_by_oid.get(oid)
        if order is None:
            return None

        remaining = order.size - fill_sz
        fully_filled = remaining <= _SIZE_EPSILON

        result = FillResult(
            side=order.side,
            price=order.price,
            size=fill_sz,
            fully_filled=fully_filled,
        )

        if fully_filled:
            self.orders_by_oid.pop(oid, None)
            key = (order.side, order.level_index)
            self.orders_by_key.pop(key, None)
        else:
            order.size = remaining

        return result

    def _prune_seen_tids(self) -> None:
        """Keep the newest half of seen tids (tids are monotonically increasing)."""
        sorted_tids = sorted(self._seen_tids)
        half = len(sorted_tids) // 2
        self._seen_tids = set(sorted_tids[half:])

    # -- Reconciliation -------------------------------------------------------

    def reconcile(self, exchange_oids: set[int]) -> ReconcileResult:
        """Compare tracked state against the exchange's reported open orders.

        Returns orphaned OIDs (on exchange, not in state → cancel) and ghost
        OIDs (in state, not on exchange → remove from state).

        Orders in pending states (PENDING_MODIFY, PENDING_CANCEL) are excluded
        from ghost detection because their OIDs may be in flux (e.g., an OID
        swap from a modify that hasn't been processed yet).
        """
        pending_statuses = {OrderStatus.PENDING_MODIFY, OrderStatus.PENDING_CANCEL}
        tracked_oids = set(self.orders_by_oid.keys())
        pending_oids = {
            oid for oid, order in self.orders_by_oid.items()
            if order.status in pending_statuses
        }
        # Pending orders are excluded from ghost detection — their exchange-side
        # OID may differ from what we're tracking.
        eligible_for_ghost = tracked_oids - pending_oids
        return ReconcileResult(
            orphaned_oids=frozenset(exchange_oids - tracked_oids),
            ghost_oids=frozenset(eligible_for_ghost - exchange_oids),
        )

    def remove_ghost(self, oid: int) -> None:
        """Remove a ghost order from both indices.  Idempotent."""
        order = self.orders_by_oid.pop(oid, None)
        if order is not None:
            key = (order.side, order.level_index)
            self.orders_by_key.pop(key, None)

    # -- Queries --------------------------------------------------------------

    def get_current_orders(self) -> list[TrackedOrder]:
        """Return a snapshot of all currently tracked orders."""
        return list(self.orders_by_oid.values())
