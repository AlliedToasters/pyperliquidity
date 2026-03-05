"""Token and USDC balance tracking with allocation-aware effective balances."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Inventory:
    """Allocation-aware balance tracker for HIP-2 market making.

    Maintains three balance layers per asset:
    - *allocated*: operator-configured ceiling
    - *account*: actual exchange balance
    - *effective*: ``min(allocated, account)`` — the only value quoting uses

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
