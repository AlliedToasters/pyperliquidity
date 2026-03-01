"""Geometric price ladder generation and level lookup for HIP-2 market making."""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass, field


def _default_round(px: float) -> float:
    """Round to 8 significant figures."""
    if px == 0:
        return 0.0
    magnitude = math.floor(math.log10(abs(px))) + 1
    return round(px, 8 - magnitude)


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
