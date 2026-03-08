"""Quoting engine — pure function: fixed grid + inventory → desired orders.

No I/O, no side effects. The cursor (boundary between bids and asks) is
derived from token inventory each tick on a fixed PricingGrid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from pyperliquidity.pricing_grid import PricingGrid


@dataclass(frozen=True, slots=True)
class DesiredOrder:
    """An order the quoting engine wants on the book."""

    side: Literal["buy", "sell"]
    level_index: int
    price: float
    size: float


def compute_desired_orders(
    grid: PricingGrid,
    effective_token: float,
    effective_usdc: float,
    order_sz: float,
    min_notional: float = 0.0,
    active_levels: int | None = None,
) -> list[DesiredOrder]:
    """Compute desired resting orders from a fixed grid and effective balances.

    The cursor (boundary between bids and asks) is derived from token balance:
        n_full_asks = floor(effective_token / order_sz)
        partial_ask_sz = effective_token % order_sz
        total_ask_levels = min(n_full_asks + (1 if partial > 0 else 0), grid.n_orders)
        cursor = grid.n_orders - total_ask_levels

    Asks are placed ascending from cursor. Bids descend from cursor-1,
    funded by USDC.

    Parameters
    ----------
    grid : PricingGrid
        Fixed price grid (constructed once, immutable).
    effective_token : float
        Effective token balance available for ask orders.
    effective_usdc : float
        Effective USDC balance available for bid orders.
    order_sz : float
        Size of a full order tranche.
    min_notional : float
        Minimum ``price * size`` for an order. Orders below this are excluded.
    active_levels : int | None
        Maximum number of levels to place per side of the cursor.
        When ``None``, all available levels get orders (current behavior).

    Returns
    -------
    list[DesiredOrder]
        Deterministic list of desired orders on the grid.
    """
    if effective_token <= 0 and effective_usdc <= 0:
        return []

    # --- Cursor derivation ---
    n_full_asks = math.floor(effective_token / order_sz) if effective_token > 0 else 0
    partial_ask_sz = effective_token % order_sz if effective_token > 0 else 0.0
    total_ask_levels = min(
        n_full_asks + (1 if partial_ask_sz > 0 else 0),
        grid.n_orders,
    )
    cursor = grid.n_orders - total_ask_levels

    orders: list[DesiredOrder] = []

    # --- Ask placement: ascending from cursor ---
    ask_limit = active_levels if active_levels is not None else grid.n_orders
    if effective_token > 0:
        level = cursor
        ask_count = 0
        # Partial ask at cursor level (if remainder > 0)
        if partial_ask_sz > 0 and level < grid.n_orders and ask_count < ask_limit:
            px = grid.price_at_level(level)
            if min_notional <= 0 or px * partial_ask_sz >= min_notional:
                orders.append(DesiredOrder(
                    side="sell", level_index=level, price=px, size=partial_ask_sz,
                ))
            ask_count += 1
            level += 1

        # Full asks ascending
        asks_placed = 0
        while asks_placed < n_full_asks and level < grid.n_orders and ask_count < ask_limit:
            px = grid.price_at_level(level)
            if min_notional <= 0 or px * order_sz >= min_notional:
                orders.append(DesiredOrder(
                    side="sell", level_index=level, price=px, size=order_sz,
                ))
            asks_placed += 1
            ask_count += 1
            level += 1

    # --- Bid placement: descending from cursor-1 ---
    bid_limit = active_levels if active_levels is not None else grid.n_orders
    remaining_usdc = effective_usdc
    bid_count = 0
    level = cursor - 1
    while level >= 0 and remaining_usdc > 0 and bid_count < bid_limit:
        px = grid.price_at_level(level)
        cost = px * order_sz
        if remaining_usdc >= cost:
            # Full bid
            if min_notional <= 0 or px * order_sz >= min_notional:
                orders.append(DesiredOrder(
                    side="buy", level_index=level, price=px, size=order_sz,
                ))
            remaining_usdc -= cost
        else:
            # Partial bid — remaining USDC can't cover a full order
            partial_sz = remaining_usdc / px
            if min_notional <= 0 or px * partial_sz >= min_notional:
                orders.append(DesiredOrder(
                    side="buy", level_index=level, price=px, size=partial_sz,
                ))
            remaining_usdc = 0
        bid_count += 1
        level -= 1

    return orders
