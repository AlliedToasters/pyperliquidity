"""Fix spot_meta token index-to-position mismatch.

The Hyperliquid SDK's ``Info.__init__`` uses universe ``tokens`` references
as array indices into the top-level ``tokens`` list.  However, the API
returns token ``index`` field values which can diverge from array positions
(e.g. when tokens are deleted or reordered).  This causes
``IndexError: list index out of range`` during ``Info()`` construction.

This module provides a utility to rewrite the ``spotMeta`` payload so that
universe token references use positions (array offsets) instead of indices.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def fix_spot_meta(spot_meta: dict[str, Any]) -> dict[str, Any]:
    """Rewrite ``spotMeta`` so universe token refs use positions, not indices.

    The API's ``tokens`` list entries each carry an ``index`` field whose
    value may differ from the entry's array position.  Universe entries
    reference tokens by that ``index`` value, but the SDK indexes into the
    array by position.

    This function builds an ``index -> position`` map and rewrites every
    universe entry's ``tokens`` list so values correspond to array positions.

    Parameters
    ----------
    spot_meta:
        Raw ``spotMeta`` payload as returned by the Hyperliquid API.

    Returns
    -------
    dict
        A **shallow-copied** ``spotMeta`` with corrected ``tokens`` refs.
        The top-level ``tokens`` list is left untouched.
    """
    tokens_list: list[dict[str, Any]] = spot_meta.get("tokens", [])
    universe: list[dict[str, Any]] = spot_meta.get("universe", [])

    # Build index → position map.
    # If a token lacks an "index" field, fall back to its array position.
    index_to_position: dict[int, int] = {}
    for position, token in enumerate(tokens_list):
        token_index = token.get("index", position)
        index_to_position[token_index] = position

    # Nothing to rewrite if indices already match positions.
    needs_rewrite = any(idx != pos for idx, pos in index_to_position.items())
    if not needs_rewrite:
        return spot_meta

    logger.info(
        "spot_meta index→position mismatch detected; rewriting %d universe entries",
        len(universe),
    )

    # Shallow-copy top-level dict; deep-copy only universe entries that change.
    fixed = {**spot_meta}
    fixed_universe: list[dict[str, Any]] = []
    for entry in universe:
        old_tokens = entry.get("tokens", [])
        new_tokens = [index_to_position.get(t, t) for t in old_tokens]
        if new_tokens != old_tokens:
            entry = {**entry, "tokens": new_tokens}
        fixed_universe.append(entry)
    fixed["universe"] = fixed_universe

    return fixed


def fetch_fixed_spot_meta(base_url: str) -> dict[str, Any]:
    """Fetch ``spotMeta`` from the API and return a fixed copy.

    Uses a lightweight REST call (bypassing ``Info.__init__``) so that the
    corrected payload can be passed to ``Info(spot_meta=fixed)`` without
    triggering the ``IndexError``.

    Parameters
    ----------
    base_url:
        Hyperliquid API base URL (mainnet or testnet).

    Returns
    -------
    dict
        Fixed ``spotMeta`` payload ready to pass to ``Info(spot_meta=...)``.
    """
    import requests

    resp = requests.post(
        f"{base_url}/info",
        json={"type": "spotMeta"},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    raw: dict[str, Any] = resp.json()
    return fix_spot_meta(raw)


def build_info(
    base_url: str,
    *,
    skip_ws: bool = False,
) -> Any:
    """Build a Hyperliquid ``Info`` object with the spot_meta index fix applied.

    This avoids the ``IndexError`` that occurs when constructing ``Info``
    directly on networks where token indices diverge from array positions.

    Parameters
    ----------
    base_url:
        Hyperliquid API base URL (mainnet or testnet).
    skip_ws:
        If ``True``, skip WebSocket connection (useful for one-shot REST calls).

    Returns
    -------
    hyperliquid.info.Info
        A usable ``Info`` instance.
    """
    from hyperliquid.info import Info

    fixed = fetch_fixed_spot_meta(base_url)
    return Info(base_url=base_url, skip_ws=skip_ws, spot_meta=fixed)


def build_exchange(
    wallet: Any,
    base_url: str,
    *,
    vault_address: str | None = None,
    account_address: str | None = None,
) -> Any:
    """Build a Hyperliquid ``Exchange`` object with the spot_meta index fix applied.

    Parameters
    ----------
    wallet:
        An ``eth_account`` ``LocalAccount`` (from ``Account.from_key(...)``).
    base_url:
        Hyperliquid API base URL (mainnet or testnet).
    vault_address:
        Optional vault address for vault-delegated trading.
    account_address:
        Optional account address override.

    Returns
    -------
    hyperliquid.exchange.Exchange
        A usable ``Exchange`` instance.
    """
    from hyperliquid.exchange import Exchange

    fixed = fetch_fixed_spot_meta(base_url)
    return Exchange(
        wallet,
        base_url=base_url,
        spot_meta=fixed,
        vault_address=vault_address,
        account_address=account_address,
    )
