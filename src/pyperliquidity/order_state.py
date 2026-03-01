"""Order state — tracks order lifecycle, OID swaps, ghost detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class TrackedOrder:
    """A resting order tracked by the order state manager."""

    oid: int
    side: Literal["buy", "sell"]
    level_index: int
    price: float
    size: float
    status: Literal["resting", "pending_modify", "pending_cancel", "pending_place"] = "resting"
