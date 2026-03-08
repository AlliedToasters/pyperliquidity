"""Grid generator — pure functions to derive HIP-2 config from high-level market parameters.

No I/O. Takes price range + token liquidity and produces a ready-to-use config dict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from pyperliquidity.pricing_grid import PricingGrid, compute_allocation_from_target_px


@dataclass(frozen=True, slots=True)
class GridWarning:
    """Non-fatal warning emitted during grid config generation."""

    code: str
    message: str


def compute_n_orders(min_px: float, max_px: float, tick_size: float = 0.003) -> int:
    """Compute the number of grid levels to span [min_px, max_px].

    Uses ``ceil(ln(max_px / min_px) / ln(1 + tick_size))``.

    Raises
    ------
    ValueError
        If min_px >= max_px or either is non-positive.
    """
    if min_px <= 0 or max_px <= 0:
        raise ValueError(f"Prices must be positive (got min_px={min_px}, max_px={max_px})")
    if min_px >= max_px:
        raise ValueError(f"min_px ({min_px}) must be less than max_px ({max_px})")
    return math.ceil(math.log(max_px / min_px) / math.log(1 + tick_size))


def compute_order_sz(
    liquidity_token: float,
    n_orders: int,
    target_px: float,
    start_px: float,
    tick_size: float = 0.003,
) -> float:
    """Derive tranche size from token liquidity and ask-level count.

    The cursor sits at the grid level nearest to ``target_px``.  Ask levels
    are everything from the cursor upward, so::

        ask_levels = n_orders - cursor_level
        order_sz   = liquidity_token / ask_levels

    Raises
    ------
    ValueError
        If inputs are invalid or target_px resolves to no ask levels.
    """
    if liquidity_token <= 0:
        raise ValueError(f"liquidity_token must be positive (got {liquidity_token})")
    if n_orders <= 0:
        raise ValueError(f"n_orders must be positive (got {n_orders})")

    grid = PricingGrid(start_px=start_px, n_orders=n_orders, tick_size=tick_size)
    cursor_level = grid.level_for_price(target_px)
    if cursor_level is None:
        raise ValueError(
            f"target_px ({target_px}) is outside the grid range "
            f"[{grid.levels[0]}, {grid.levels[-1]}]"
        )
    ask_levels = n_orders - cursor_level
    if ask_levels <= 0:
        raise ValueError(
            f"target_px ({target_px}) is at the top of the grid — no ask levels available"
        )
    return liquidity_token / ask_levels


def generate_grid_config(
    *,
    coin: str,
    min_px: float,
    max_px: float,
    liquidity_token: float,
    target_px: float | None = None,
    tick_size: float = 0.003,
    active_levels: int | None = None,
    testnet: bool = False,
    sz_decimals: int | None = None,
    min_notional: float = 10.0,
) -> tuple[dict[str, Any], list[GridWarning]]:
    """Generate a complete HIP-2 config dict from high-level market parameters.

    Parameters
    ----------
    coin : str
        Market identifier (e.g. ``"@1434"``).
    min_px, max_px : float
        Price range for the grid.
    liquidity_token : float
        Total token amount to allocate as ask liquidity.
    target_px : float | None
        Desired initial market price.  Defaults to geometric midpoint
        ``sqrt(min_px * max_px)``, snapped to the nearest grid level.
    tick_size : float
        Multiplicative spacing between levels (default 0.3%).
    active_levels : int | None
        Maximum levels per side to keep active.
    testnet : bool
        Whether this config targets testnet.
    sz_decimals : int | None
        If provided, round order_sz to this many decimal places.
    min_notional : float
        Minimum notional value (price * size) for an order.

    Returns
    -------
    tuple[dict, list[GridWarning]]
        Config dict suitable for TOML serialization + list of warnings.
    """
    if min_px <= 0 or max_px <= 0:
        raise ValueError(f"Prices must be positive (got min_px={min_px}, max_px={max_px})")
    if min_px >= max_px:
        raise ValueError(f"min_px ({min_px}) must be less than max_px ({max_px})")
    if liquidity_token <= 0:
        raise ValueError(f"liquidity_token must be positive (got {liquidity_token})")

    warnings: list[GridWarning] = []

    # 1. Compute grid dimensions
    n_orders = compute_n_orders(min_px, max_px, tick_size)
    start_px = min_px

    # 2. Build grid to validate non-degenerate
    grid = PricingGrid(start_px=start_px, n_orders=n_orders, tick_size=tick_size)

    # 3. Default target_px to geometric midpoint, snap to nearest grid level
    if target_px is None:
        target_px = math.sqrt(min_px * max_px)
    cursor_level = grid.level_for_price(target_px)
    if cursor_level is None:
        raise ValueError(
            f"target_px ({target_px}) is outside the grid range "
            f"[{grid.levels[0]}, {grid.levels[-1]}]"
        )
    snapped_target_px = grid.price_at_level(cursor_level)

    # 4. Compute order_sz from ask-level count
    ask_levels = n_orders - cursor_level
    if ask_levels <= 0:
        raise ValueError(
            f"target_px ({target_px}) is at the top of the grid — no ask levels available"
        )
    order_sz = liquidity_token / ask_levels
    if sz_decimals is not None:
        order_sz = round(order_sz, sz_decimals)

    # 5. Compute allocations
    allocated_token, allocated_usdc = compute_allocation_from_target_px(
        target_px=snapped_target_px,
        start_px=start_px,
        n_orders=n_orders,
        order_sz=order_sz,
        tick_size=tick_size,
    )

    # 6. Collect warnings
    lowest_ask_notional = grid.price_at_level(cursor_level) * order_sz
    if lowest_ask_notional < min_notional:
        warnings.append(GridWarning(
            code="below_min_notional",
            message=(
                f"Lowest ask notional ${lowest_ask_notional:.2f} is below "
                f"min_notional ${min_notional:.2f}. Orders near the cursor "
                f"may be filtered out at runtime."
            ),
        ))

    if cursor_level > 0:
        lowest_bid_notional = grid.price_at_level(cursor_level - 1) * order_sz
        if lowest_bid_notional < min_notional:
            warnings.append(GridWarning(
                code="below_min_notional_bid",
                message=(
                    f"Lowest bid notional ${lowest_bid_notional:.2f} is below "
                    f"min_notional ${min_notional:.2f}. Orders near the cursor "
                    f"may be filtered out at runtime."
                ),
            ))

    if active_levels is not None and active_levels > n_orders:
        warnings.append(GridWarning(
            code="active_levels_exceeds_grid",
            message=(
                f"active_levels ({active_levels}) exceeds n_orders ({n_orders}). "
                f"All levels will be active."
            ),
        ))

    if n_orders > 100 and active_levels is None:
        warnings.append(GridWarning(
            code="large_grid_no_active_levels",
            message=(
                f"Grid has {n_orders} levels but no active_levels limit. "
                f"Consider setting --active-levels to reduce open orders."
            ),
        ))

    # 7. Build config dict
    config: dict[str, Any] = {
        "market": {
            "coin": coin,
            "testnet": testnet,
        },
        "strategy": {
            "n_orders": n_orders,
            "order_sz": order_sz,
            "start_px": start_px,
            "target_px": snapped_target_px,
        },
        "allocation": {
            "allocated_token": allocated_token,
            "allocated_usdc": allocated_usdc,
        },
        "tuning": {
            "min_notional": min_notional,
        },
    }
    if active_levels is not None:
        config["strategy"]["active_levels"] = active_levels

    return config, warnings
