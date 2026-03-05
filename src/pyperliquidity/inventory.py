"""Token and USDC balance tracking with isolated virtual balances."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Inventory:
    """Isolated virtual balance tracker for HIP-2 market making.

    Maintains four balance layers per asset:
    - *allocated*: operator-configured starting balance (also the ceiling)
    - *virtual*: isolated running balance, starts at allocation, adjusted by fills only
    - *account*: actual exchange balance (hard safety cap)
    - *effective*: ``min(virtual, account)`` — the only value quoting uses

    Virtual balances track the strategy's isolated inventory independent of
    the account-wide balance.  This allows multiple strategies to share a
    single exchange wallet without interfering with each other's pricing.

    Parameters
    ----------
    order_sz : float
        Size of a full order tranche (HIP-2 parameter).
    allocated_token : float
        Initial token balance for this strategy (also the ceiling).
    allocated_usdc : float
        Initial USDC balance for this strategy (also the ceiling).
    account_token : float
        Current token holdings on the exchange (safety cap).
    account_usdc : float
        Current USDC holdings on the exchange (safety cap).
    """

    order_sz: float
    allocated_token: float
    allocated_usdc: float
    account_token: float
    account_usdc: float

    # Virtual balances — isolated, fill-driven.  Initialized from allocation.
    virtual_token: float = field(init=False, default=0.0)
    virtual_usdc: float = field(init=False, default=0.0)

    # Effective balances — set by __post_init__ and _recompute_effective
    effective_token: float = field(init=False, default=0.0)
    effective_usdc: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.virtual_token = self.allocated_token
        self.virtual_usdc = self.allocated_usdc
        self._recompute_effective()

    # -- Private helpers ------------------------------------------------------

    def _recompute_effective(self) -> None:
        """Set effective = min(virtual, account) for both assets.

        Virtual tracks the isolated inventory; account is a hard safety cap
        to prevent placing orders that exceed actual exchange holdings.
        """
        self.effective_token = min(self.virtual_token, self.account_token)
        self.effective_usdc = min(self.virtual_usdc, self.account_usdc)

    # -- Allocation management ------------------------------------------------

    def update_allocation(self, token: float, usdc: float) -> None:
        """Update allocation ceilings and recompute effective balances.

        Adjusts virtual balances proportionally: the delta between old and new
        allocation is applied to virtual balances.
        """
        token_delta = token - self.allocated_token
        usdc_delta = usdc - self.allocated_usdc
        self.allocated_token = token
        self.allocated_usdc = usdc
        self.virtual_token += token_delta
        self.virtual_usdc += usdc_delta
        self._recompute_effective()

    # -- Event handlers -------------------------------------------------------

    def on_ask_fill(
        self, px: float, sz: float, fee: float = 0.0, fee_token: str = "USDC",
    ) -> None:
        """Process an ask-side fill: sold *sz* tokens at price *px*.

        Adjusts virtual balances (the isolated inventory).  Account balances
        are updated separately via ``on_balance_update``.
        """
        self.virtual_token -= sz
        if fee_token == "USDC":
            self.virtual_usdc += px * sz - fee
        else:
            self.virtual_usdc += px * sz
            self.virtual_token -= fee
        self._recompute_effective()

    def on_bid_fill(
        self, px: float, sz: float, fee: float = 0.0, fee_token: str = "USDC",
    ) -> None:
        """Process a bid-side fill: bought *sz* tokens at price *px*.

        Adjusts virtual balances (the isolated inventory).  Account balances
        are updated separately via ``on_balance_update``.
        """
        self.virtual_usdc -= px * sz
        if fee_token == "USDC":
            self.virtual_usdc -= fee
            self.virtual_token += sz
        else:
            self.virtual_token += sz - fee
        self._recompute_effective()

    def on_balance_update(self, token: float, usdc: float) -> None:
        """Update account-wide balances (hard safety cap).

        This does NOT reset virtual balances.  Virtual balances are only
        adjusted by fills.  Account balances serve as a safety cap to
        prevent placing orders that exceed actual exchange holdings.
        """
        self.account_token = token
        self.account_usdc = usdc
        self._recompute_effective()
