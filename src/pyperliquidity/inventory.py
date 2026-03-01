"""Token and USDC balance tracking with allocation-aware tranche decomposition."""

from __future__ import annotations

import math
from dataclasses import dataclass

from pyperliquidity.pricing_grid import PricingGrid


@dataclass(frozen=True)
class TrancheDecomposition:
    """Immutable snapshot of how a balance decomposes into order tranches.

    Parameters
    ----------
    n_full : int
        Number of full-sized order tranches.
    partial_sz : float
        Size of the remaining partial tranche (0.0 if evenly divisible).
    levels : tuple[int, ...]
        Grid level indices consumed by the tranches (ascending for asks,
        descending for bids).
    """

    n_full: int
    partial_sz: float
    levels: tuple[int, ...]


@dataclass
class Inventory:
    """Allocation-aware balance tracker for HIP-2 market making.

    Maintains three balance layers per asset:
    - *allocated*: operator-configured ceiling
    - *account*: actual exchange balance
    - *effective*: ``min(allocated, account)`` — the only value tranche math uses

    Parameters
    ----------
    order_sz : float
        Size of a full order tranche (HIP-2 parameter).
    allocated_token : float
        Maximum token balance the strategy may use.
    allocated_usdc : float
        Maximum USDC balance the strategy may use.
    account_token : float
        Current token holdings on the exchange.
    account_usdc : float
        Current USDC holdings on the exchange.
    """

    order_sz: float
    allocated_token: float
    allocated_usdc: float
    account_token: float
    account_usdc: float

    # Effective balances — set by __post_init__ and _recompute_effective
    effective_token: float = 0.0
    effective_usdc: float = 0.0

    def __post_init__(self) -> None:
        self._recompute_effective()

    # -- Private helpers ------------------------------------------------------

    def _recompute_effective(self) -> None:
        """Set effective = min(allocated, account) for both assets."""
        self.effective_token = min(self.allocated_token, self.account_token)
        self.effective_usdc = min(self.allocated_usdc, self.account_usdc)

    # -- Allocation management ------------------------------------------------

    def update_allocation(self, token: float, usdc: float) -> None:
        """Update allocation ceilings and recompute effective balances."""
        self.allocated_token = token
        self.allocated_usdc = usdc
        self._recompute_effective()

    # -- Tranche decomposition ------------------------------------------------

    def compute_ask_tranches(self) -> TrancheDecomposition:
        """Decompose effective token balance into ask-side tranches.

        Returns a :class:`TrancheDecomposition` where ``levels`` is empty
        (ask level assignment is the quoting engine's responsibility).
        """
        n_full = math.floor(self.effective_token / self.order_sz) if self.order_sz > 0 else 0
        partial_sz = self.effective_token - n_full * self.order_sz
        # Clamp tiny negatives from float arithmetic
        if partial_sz < 0:
            partial_sz = 0.0
        return TrancheDecomposition(n_full=n_full, partial_sz=partial_sz, levels=())

    def compute_bid_tranches(
        self, grid: PricingGrid, boundary_level: int
    ) -> TrancheDecomposition:
        """Decompose effective USDC balance into bid-side tranches.

        Walks grid levels descending from *boundary_level* (exclusive — the
        boundary itself is the lowest ask, so bids start one level below).

        Parameters
        ----------
        grid : PricingGrid
            The price grid for cost computation.
        boundary_level : int
            Grid index of the bid/ask boundary.  Bids are placed at levels
            ``boundary_level - 1`` down to ``0``.
        """
        available = self.effective_usdc
        n_full = 0
        levels: list[int] = []
        partial_sz = 0.0

        for lvl in range(boundary_level - 1, -1, -1):
            px = grid.price_at_level(lvl)
            cost = px * self.order_sz
            if available >= cost:
                n_full += 1
                available -= cost
                levels.append(lvl)
            else:
                if available > 0 and px > 0:
                    partial_sz = available / px
                    levels.append(lvl)
                break

        return TrancheDecomposition(
            n_full=n_full, partial_sz=partial_sz, levels=tuple(levels)
        )

    # -- Event handlers -------------------------------------------------------

    def on_ask_fill(self, px: float, sz: float) -> None:
        """Process an ask-side fill: sold *sz* tokens at price *px*."""
        self.account_token -= sz
        self.account_usdc += px * sz
        self._recompute_effective()

    def on_bid_fill(self, px: float, sz: float) -> None:
        """Process a bid-side fill: bought *sz* tokens at price *px*."""
        self.account_token += sz
        self.account_usdc -= px * sz
        self._recompute_effective()

    def on_balance_update(self, token: float, usdc: float) -> None:
        """Authoritative balance reset from exchange reconciliation."""
        self.account_token = token
        self.account_usdc = usdc
        self._recompute_effective()
