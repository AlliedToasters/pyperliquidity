"""Order differ — dead-zone filtered, level-index matched order diffing.

Pure function: no I/O, no side effects. Computes the minimum set of
mutations (modify, place, cancel) to converge current orders to desired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from pyperliquidity.order_state import TrackedOrder
from pyperliquidity.quoting_engine import DesiredOrder


@dataclass(frozen=True, slots=True)
class OrderDiff:
    """Minimum mutations to converge current orders to desired orders."""

    modifies: list[tuple[int, DesiredOrder]] = field(default_factory=list)
    places: list[DesiredOrder] = field(default_factory=list)
    cancels: list[int] = field(default_factory=list)


_EMPTY = OrderDiff()


def _weighted_mid_price(
    prices: Sequence[float], sizes: Sequence[float]
) -> float:
    """Size-weighted average price. Returns 0.0 if total size is zero."""
    total_size = 0.0
    weighted_sum = 0.0
    for px, sz in zip(prices, sizes):
        weighted_sum += px * sz
        total_size += sz
    if total_size == 0.0:
        return 0.0
    return weighted_sum / total_size


def compute_diff(
    desired: list[DesiredOrder],
    current: list[TrackedOrder],
    dead_zone_bps: float,
    price_tolerance_bps: float,
    size_tolerance_pct: float,
) -> OrderDiff:
    """Compute the minimum mutation set to converge *current* → *desired*.

    Algorithm:
      1. Dead-zone check (short-circuit if drift is negligible)
      2. Level-index matching by ``(side, level_index)``
      3. Per-order tolerance filter
      4. Cross-side validation (cancel + place, never cross-side modify)
    """
    # --- Bypass: empty lists skip dead-zone ---
    if not desired and not current:
        return _EMPTY
    if not current:
        return OrderDiff(places=list(desired))
    if not desired:
        return OrderDiff(cancels=[t.oid for t in current])

    # --- Step 1: Dead-zone check ---
    desired_mid = _weighted_mid_price(
        [d.price for d in desired], [d.size for d in desired]
    )
    current_mid = _weighted_mid_price(
        [c.price for c in current], [c.size for c in current]
    )
    if current_mid > 0.0:
        drift_bps = abs(desired_mid - current_mid) / current_mid * 10_000
        if drift_bps < dead_zone_bps:
            return _EMPTY

    # --- Step 2: Level-index matching ---
    desired_by_key: dict[tuple[str, int], DesiredOrder] = {
        (d.side, d.level_index): d for d in desired
    }
    current_by_key: dict[tuple[str, int], TrackedOrder] = {
        (c.side, c.level_index): c for c in current
    }

    # Also index current orders by level_index alone for cross-side detection
    current_by_level: dict[int, TrackedOrder] = {c.level_index: c for c in current}

    modifies: list[tuple[int, DesiredOrder]] = []
    places: list[DesiredOrder] = []
    cancels: list[int] = []

    matched_current_keys: set[tuple[str, int]] = set()

    for key, d in desired_by_key.items():
        side, level_idx = key
        if key in current_by_key:
            # --- Same-side match ---
            c = current_by_key[key]
            matched_current_keys.add(key)

            # Step 3: Per-order tolerance filter
            if c.price > 0.0:
                px_diff_bps = abs(d.price - c.price) / c.price * 10_000
            else:
                px_diff_bps = float("inf")

            if c.size > 0.0:
                sz_diff_pct = abs(d.size - c.size) / c.size * 100
            else:
                sz_diff_pct = float("inf")

            if px_diff_bps <= price_tolerance_bps and sz_diff_pct <= size_tolerance_pct:
                continue  # Within tolerance — skip

            modifies.append((c.oid, d))
        else:
            # --- Step 4: Cross-side check ---
            # Is there a current order at the same level_index on the opposite side?
            opposite_key = ("sell" if side == "buy" else "buy", level_idx)
            if opposite_key in current_by_key and opposite_key not in matched_current_keys:
                c = current_by_key[opposite_key]
                matched_current_keys.add(opposite_key)
                cancels.append(c.oid)
                places.append(d)
            else:
                # No match at all — new placement
                places.append(d)

    # Unmatched current orders → cancels
    for key, c in current_by_key.items():
        if key not in matched_current_keys:
            cancels.append(c.oid)

    return OrderDiff(modifies=modifies, places=places, cancels=cancels)
