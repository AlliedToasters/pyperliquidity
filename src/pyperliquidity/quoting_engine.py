"""Quoting engine — pure function: inventory → desired orders.

No I/O, no side effects. Price is derived from inventory (USDC / tokens),
grid recenters on mid each tick, and n_orders are placed per side.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pyperliquidity.pricing_grid import (
    _default_round,
    generate_ask_levels,
    generate_bid_levels,
)


@dataclass(frozen=True, slots=True)
class DesiredOrder:
    """An order the quoting engine wants on the book."""

    side: Literal["buy", "sell"]
    level_index: int
    price: float
    size: float


@dataclass(frozen=True, slots=True)
class QuoteResult:
    """Result of the quoting engine computation."""

    mid_price: float
    effective_order_sz: float
    effective_n_orders: int
    orders: list[DesiredOrder]


def compute_desired_orders(
    effective_token: float,
    effective_usdc: float,
    order_sz: float,
    n_orders: int,
    min_notional: float = 0.0,
    tick_size: float = 0.003,
    round_fn: Callable[[float], float] = _default_round,
) -> QuoteResult:
    """Compute desired resting orders from inventory state.

    Price is derived from inventory: ``mid = round(usdc / tokens)``.
    Grid recenters on mid each tick with n_orders per side.

    Parameters
    ----------
    effective_token : float
        Effective token balance available for ask orders.
    effective_usdc : float
        Effective USDC balance available for bid orders.
    order_sz : float
        Size of a full order tranche.
    n_orders : int
        Number of orders **per side**.
    min_notional : float
        Minimum ``price * size`` for an order. When binding, increases
        effective_order_sz and may reduce effective_n_orders.
    tick_size : float
        Multiplicative spacing between levels (default 0.3%).
    round_fn : Callable
        Rounding function applied to prices.

    Returns
    -------
    QuoteResult
        Mid price, effective params, and deterministic list of desired orders.
    """
    # Edge case: need both sides to derive mid
    if effective_token <= 0 or effective_usdc <= 0:
        return QuoteResult(
            mid_price=0.0,
            effective_order_sz=order_sz,
            effective_n_orders=n_orders,
            orders=[],
        )

    mid_price = round_fn(effective_usdc / effective_token)

    # Min notional adjustment
    eff_order_sz = order_sz
    eff_n_orders = n_orders
    if min_notional > 0 and mid_price * order_sz < min_notional:
        eff_order_sz = min_notional / mid_price
        max_asks = math.floor(effective_token / eff_order_sz) if eff_order_sz > 0 else 0
        max_bids = math.floor(effective_usdc / (eff_order_sz * mid_price)) if mid_price > 0 else 0
        eff_n_orders = min(n_orders, max_asks, max_bids)

    if eff_n_orders <= 0:
        return QuoteResult(
            mid_price=mid_price,
            effective_order_sz=eff_order_sz,
            effective_n_orders=0,
            orders=[],
        )

    # Generate price levels
    ask_levels = generate_ask_levels(mid_price, eff_n_orders, tick_size, round_fn)
    bid_levels = generate_bid_levels(mid_price, eff_n_orders, tick_size, round_fn)

    orders: list[DesiredOrder] = []

    # --- Ask side ---
    remaining_token = effective_token
    for i, px in enumerate(ask_levels):
        if remaining_token <= 0:
            break
        sz = min(eff_order_sz, remaining_token)
        orders.append(DesiredOrder(side="sell", level_index=i, price=px, size=sz))
        remaining_token -= sz

    # --- Bid side ---
    remaining_usdc = effective_usdc
    for i, px in enumerate(bid_levels):
        if remaining_usdc <= 0 or px <= 0:
            break
        cost = eff_order_sz * px
        if remaining_usdc >= cost:
            orders.append(DesiredOrder(side="buy", level_index=i, price=px, size=eff_order_sz))
            remaining_usdc -= cost
        else:
            partial_sz = remaining_usdc / px
            orders.append(DesiredOrder(side="buy", level_index=i, price=px, size=partial_sz))
            remaining_usdc = 0

    return QuoteResult(
        mid_price=mid_price,
        effective_order_sz=eff_order_sz,
        effective_n_orders=eff_n_orders,
        orders=orders,
    )
