"""Quoting engine — pure function: inventory + grid → desired orders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class DesiredOrder:
    """An order the quoting engine wants on the book."""

    side: Literal["buy", "sell"]
    level_index: int
    price: float
    size: float
