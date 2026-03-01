"""Quoting engine — pure function: inventory + grid → desired orders.

No I/O, no side effects. This is the HIP-2 algorithm: given a price grid,
current balances, and boundary level, produce the deterministic set of
desired resting orders.
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
    boundary_level: int,
    effective_token: float,
    effective_usdc: float,
    order_sz: float,
    min_notional: float = 0.0,
) -> list[DesiredOrder]:
    """Compute the desired set of resting orders from inventory state.

    Parameters
    ----------
    grid : PricingGrid
        The geometric price grid.
    boundary_level : int
        Grid index of the lowest ask level.  Asks are placed at
        ``boundary_level`` and above; bids at ``boundary_level - 1`` and below.
    effective_token : float
        Effective token balance available for ask orders.
    effective_usdc : float
        Effective USDC balance available for bid orders.
    order_sz : float
        Size of a full order tranche.
    min_notional : float
        Minimum ``price * size`` for an order to be emitted.  Orders below
        this threshold are filtered out.

    Returns
    -------
    list[DesiredOrder]
        Deterministic list of desired orders (asks then bids).
    """
    orders: list[DesiredOrder] = []

    max_level = len(grid.levels) - 1

    # --- Ask side: ascending from boundary_level ---
    if effective_token > 0 and order_sz > 0:
        n_full = math.floor(effective_token / order_sz)
        partial = effective_token - n_full * order_sz
        # Clamp tiny negatives from float arithmetic
        if partial < 0:
            partial = 0.0

        for i in range(n_full):
            lvl = boundary_level + i
            if lvl > max_level:
                break
            px = grid.price_at_level(lvl)
            orders.append(DesiredOrder(side="sell", level_index=lvl, price=px, size=order_sz))

        if partial > 0:
            partial_lvl = boundary_level + n_full
            if partial_lvl <= max_level:
                px = grid.price_at_level(partial_lvl)
                orders.append(
                    DesiredOrder(side="sell", level_index=partial_lvl, price=px, size=partial)
                )

    # --- Bid side: descending from boundary_level - 1 ---
    if effective_usdc > 0 and order_sz > 0:
        available = effective_usdc
        for lvl in range(boundary_level - 1, -1, -1):
            px = grid.price_at_level(lvl)
            cost = px * order_sz
            if available >= cost:
                orders.append(
                    DesiredOrder(side="buy", level_index=lvl, price=px, size=order_sz)
                )
                available -= cost
            else:
                if available > 0 and px > 0:
                    partial_sz = available / px
                    orders.append(
                        DesiredOrder(side="buy", level_index=lvl, price=px, size=partial_sz)
                    )
                break

    # --- Minimum notional filter ---
    if min_notional > 0:
        orders = [o for o in orders if o.price * o.size >= min_notional]

    return orders
