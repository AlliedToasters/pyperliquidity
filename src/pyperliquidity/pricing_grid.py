"""Geometric price ladder generation and level lookup for HIP-2 market making."""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass, field


def _default_round(px: float) -> float:
    """Round to 5 significant figures (Hyperliquid's max precision)."""
    if px == 0:
        return 0.0
    magnitude = math.floor(math.log10(abs(px))) + 1
    return round(px, 5 - magnitude)


@dataclass(frozen=True)
class PricingGrid:
    """Immutable geometric price grid for HIP-2 market making.

    Parameters
    ----------
    start_px : float
        The initial price of the range (px_0).
    n_orders : int
        Number of price levels in the grid.
    tick_size : float
        Multiplicative spacing between levels (default 0.3% per HIP-2).
    round_fn : Callable[[float], float]
        Rounding function applied at each step of the recurrence.
    """

    start_px: float
    n_orders: int
    tick_size: float = 0.003
    round_fn: Callable[[float], float] = _default_round
    _levels: tuple[float, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        prices: list[float] = [self.round_fn(self.start_px)]
        for _ in range(self.n_orders - 1):
            next_px = self.round_fn(prices[-1] * (1 + self.tick_size))
            if next_px == prices[-1]:
                raise ValueError(
                    f"Degenerate grid: rounding collapsed level {len(prices)} "
                    f"to same price as level {len(prices) - 1} ({next_px}). "
                    f"Increase rounding precision or tick_size."
                )
            prices.append(next_px)
        # Bypass frozen restriction for init
        object.__setattr__(self, "_levels", tuple(prices))

    @property
    def levels(self) -> tuple[float, ...]:
        """The complete ordered price ladder, ascending."""
        return self._levels

    def price_at_level(self, i: int) -> float:
        """Price at grid index *i*. Raises IndexError if out of bounds."""
        if i < 0 or i >= len(self._levels):
            raise IndexError(f"Level index {i} out of range [0, {len(self._levels) - 1}]")
        return self._levels[i]

    @property
    def max_price(self) -> float:
        """The highest price on the grid (last level)."""
        return self._levels[-1]

    def level_for_price(self, px: float) -> int | None:
        """Nearest grid level index for *px*, or None if outside the grid range.

        Uses binary search for O(log n) lookup. When *px* falls exactly between
        two levels, the lower index is returned (tie-breaking rule).

        Returns None if *px* is below levels[0] by more than half a tick spacing
        or above levels[-1] by more than half a tick spacing.
        """
        levels = self._levels
        if not levels:
            return None

        half_tick_low = levels[0] * self.tick_size / 2
        half_tick_high = levels[-1] * self.tick_size / 2

        if px < levels[0] - half_tick_low:
            return None
        if px > levels[-1] + half_tick_high:
            return None

        idx = bisect_left(levels, px)

        if idx == 0:
            return 0
        if idx == len(levels):
            return len(levels) - 1

        # Compare distance to left and right neighbors
        left = levels[idx - 1]
        right = levels[idx]
        if px - left <= right - px:  # <= gives lower-index tie-breaking
            return idx - 1
        return idx


def compute_allocation_from_target_px(
    target_px: float,
    start_px: float,
    n_orders: int,
    order_sz: float,
    tick_size: float = 0.003,
) -> tuple[float, float]:
    """Compute (allocated_token, allocated_usdc) to place the cursor at *target_px*.

    The cursor is the boundary between bids (below) and asks (at and above).
    Given a target price, we find the nearest grid level and treat it as the
    cursor: levels from cursor upward become ask levels funded by token,
    levels below cursor become bid levels funded by USDC.

    Parameters
    ----------
    target_px : float
        Desired market price (where the cursor should sit).
    start_px : float
        Grid start price (px_0).
    n_orders : int
        Total number of grid levels.
    order_sz : float
        Size of a full order tranche.
    tick_size : float
        Multiplicative spacing between levels (default 0.3%).

    Returns
    -------
    tuple[float, float]
        ``(allocated_token, allocated_usdc)`` — the token and USDC amounts
        needed so the cursor lands at the grid level nearest to *target_px*.

    Raises
    ------
    ValueError
        If *target_px* is below *start_px* or above the grid's maximum price.
    """
    grid = PricingGrid(start_px=start_px, n_orders=n_orders, tick_size=tick_size)

    if target_px < start_px:
        raise ValueError(
            f"target_px ({target_px}) must be >= start_px ({start_px})"
        )
    if target_px > grid.max_price:
        raise ValueError(
            f"target_px ({target_px}) is above the grid maximum "
            f"({grid.max_price}). Increase n_orders or lower target_px."
        )

    cursor_level = grid.level_for_price(target_px)
    if cursor_level is None:
        raise ValueError(
            f"target_px ({target_px}) could not be mapped to a grid level"
        )

    # Ask levels: from cursor upward
    ask_levels = n_orders - cursor_level
    allocated_token = ask_levels * order_sz

    # Bid levels: from cursor-1 downward, each costing order_sz * price_at_level
    allocated_usdc = sum(
        order_sz * grid.price_at_level(i) for i in range(cursor_level)
    )

    return (allocated_token, allocated_usdc)
