"""Rate-limit budget tracking for the Hyperliquid API.

Tracks the exchange's budget model locally and exposes queries
for the batch emitter to throttle proactively.

Budget model:  budget = 10_000 + cumulative_volume_usd - cumulative_requests
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RateLimitBudget:
    """Tracks the Hyperliquid rate-limit budget model.

    Pure state — no I/O, no async. Mutation via on_request / on_fill /
    sync_from_exchange; queries via remaining / is_healthy / is_emergency.
    """

    cum_vlm: float = 0.0
    n_requests: int = 0

    SAFETY_MARGIN: int = field(default=500, repr=False)
    CRITICAL_MARGIN: int = field(default=100, repr=False)

    _INITIAL_BUDGET: int = field(default=10_000, repr=False)

    # -- computed properties --------------------------------------------------

    @property
    def budget(self) -> float:
        """Raw budget value (may be negative)."""
        return self._INITIAL_BUDGET + self.cum_vlm - self.n_requests

    @property
    def ratio(self) -> float:
        """Long-term utilization ratio (volume / requests)."""
        return self.cum_vlm / max(self.n_requests, 1)

    # -- queries --------------------------------------------------------------

    def remaining(self) -> int:
        """Current usable budget, clamped to >= 0."""
        return max(0, int(self.budget))

    def is_healthy(self) -> bool:
        """True when earning volume faster than spending requests."""
        return self.ratio >= 1.0

    def is_emergency(self) -> bool:
        """True when budget is below the safety margin."""
        return self.remaining() < self.SAFETY_MARGIN

    # -- mutations ------------------------------------------------------------

    def on_request(self, n: int = 1) -> None:
        """Record *n* API requests (batch ops count as 1)."""
        self.n_requests += n

    def on_fill(self, volume_usd: float) -> None:
        """Record maker fill volume in USD."""
        self.cum_vlm += volume_usd

    def sync_from_exchange(self, cum_vlm: float, n_requests: int) -> None:
        """Overwrite local state with exchange-reported values."""
        self.cum_vlm = cum_vlm
        self.n_requests = n_requests

    # -- logging --------------------------------------------------------------

    def log_status(self) -> str:
        """Formatted utilization string for periodic logging."""
        return (
            f"Utilization: ratio={self.ratio:.2f} budget={self.remaining()} "
            f"vol=${self.cum_vlm:.0f} reqs={self.n_requests}"
        )
