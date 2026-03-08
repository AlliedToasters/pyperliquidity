"""CLI entrypoint — parse config, construct modules, boot ws_state."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_config(path: str) -> dict[str, Any]:
    """Read and parse a TOML config file."""
    p = Path(path)
    if not p.exists():
        sys.exit(f"Config file not found: {path}")
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"Failed to parse config file: {exc}")


def _load_env() -> tuple[str, str]:
    """Read private key and wallet address from environment variables."""
    private_key = os.environ.get("PYPERLIQUIDITY_PRIVATE_KEY", "").strip()
    if not private_key:
        sys.exit("PYPERLIQUIDITY_PRIVATE_KEY env var is not set or empty")
    wallet = os.environ.get("PYPERLIQUIDITY_WALLET", "").strip()
    if not wallet:
        sys.exit("PYPERLIQUIDITY_WALLET env var is not set or empty")
    return private_key, wallet


def _validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate required fields and apply defaults for optional tuning params.

    When ``strategy.target_px`` is provided, ``allocation.allocated_token`` and
    ``allocation.allocated_usdc`` are computed automatically and the
    ``[allocation]`` section becomes optional.  When ``target_px`` is absent,
    both allocation fields are required (backward compatible).
    """
    from pyperliquidity.pricing_grid import compute_allocation_from_target_px

    errors: list[str] = []

    # Required sections/fields
    market = config.get("market", {})
    strategy = config.get("strategy", {})
    allocation = config.get("allocation", {})

    if not market.get("coin"):
        errors.append("market.coin is required")

    for key in ("order_sz", "start_px"):
        val = strategy.get(key)
        if val is None or val <= 0:
            errors.append(f"strategy.{key} must be positive")

    n_orders = strategy.get("n_orders")
    if n_orders is None or n_orders <= 0:
        errors.append("strategy.n_orders must be a positive integer (total grid levels)")

    active_levels = strategy.get("active_levels")
    if active_levels is not None and (not isinstance(active_levels, int) or active_levels <= 0):
        errors.append("strategy.active_levels must be a positive integer when provided")

    # --- target_px vs allocation validation ---
    target_px = strategy.get("target_px")

    if target_px is not None:
        # target_px must be positive
        if target_px <= 0:
            errors.append("strategy.target_px must be positive")

        # target_px must be >= start_px (validated after core strategy fields pass)
        start_px = strategy.get("start_px")
        if start_px is not None and start_px > 0 and target_px > 0:
            if target_px < start_px:
                errors.append(
                    f"strategy.target_px ({target_px}) must be >= "
                    f"strategy.start_px ({start_px})"
                )

        # Bail early if there are errors before trying to compute allocations
        if errors:
            sys.exit("Config validation failed:\n  " + "\n  ".join(errors))

        # Compute allocations from target_px
        order_sz = strategy["order_sz"]
        start_px = strategy["start_px"]
        try:
            token, usdc = compute_allocation_from_target_px(
                target_px=target_px,
                start_px=start_px,
                n_orders=n_orders,
                order_sz=order_sz,
            )
        except ValueError as exc:
            sys.exit(f"Config validation failed:\n  strategy.target_px: {exc}")

        # Populate allocation section with computed values
        config["allocation"] = {
            "allocated_token": token,
            "allocated_usdc": usdc,
        }
    else:
        # No target_px — require explicit allocations (backward compatible)
        for key in ("allocated_token", "allocated_usdc"):
            val = allocation.get(key)
            if val is None or val <= 0:
                errors.append(f"allocation.{key} must be positive")

    if errors:
        sys.exit("Config validation failed:\n  " + "\n  ".join(errors))

    # Apply defaults for optional tuning params
    tuning = config.get("tuning", {})
    config["tuning"] = {
        "interval_s": tuning.get("interval_s", 3.0),
        "dead_zone_bps": tuning.get("dead_zone_bps", 5.0),
        "price_tolerance_bps": tuning.get("price_tolerance_bps", 1.0),
        "size_tolerance_pct": tuning.get("size_tolerance_pct", 1.0),
        "reconcile_every": tuning.get("reconcile_every", 20),
        "min_notional": tuning.get("min_notional", 0.0),
    }
    return config


def _build_ws_state(
    config: dict[str, Any],
    private_key: str,
    wallet: str,
    cancel_on_shutdown: bool = True,
) -> Any:
    """Construct SDK objects and WsState."""
    from eth_account import Account
    from hyperliquid.exchange import Exchange  # type: ignore[import-untyped]
    from hyperliquid.info import Info  # type: ignore[import-untyped]
    from hyperliquid.utils.constants import (  # type: ignore[import-untyped]
        MAINNET_API_URL,
        TESTNET_API_URL,
    )

    from pyperliquidity.spot_meta_fix import fetch_fixed_spot_meta
    from pyperliquidity.ws_state import WsState

    testnet = config.get("market", {}).get("testnet", False)
    base_url = TESTNET_API_URL if testnet else MAINNET_API_URL

    # Fetch and fix spot_meta before constructing Info to avoid IndexError
    # when token index values diverge from array positions.
    fixed_spot_meta = fetch_fixed_spot_meta(base_url)
    info = Info(base_url=base_url, skip_ws=False, spot_meta=fixed_spot_meta)
    account = Account.from_key(private_key)
    exchange = Exchange(account, base_url=base_url)

    strategy = config["strategy"]
    tuning = config["tuning"]
    allocation = config["allocation"]

    return WsState(
        coin=config["market"]["coin"],
        start_px=strategy["start_px"],
        n_orders=strategy["n_orders"],
        order_sz=strategy["order_sz"],
        info=info,
        exchange=exchange,
        address=wallet,
        interval_s=tuning["interval_s"],
        dead_zone_bps=tuning["dead_zone_bps"],
        price_tolerance_bps=tuning["price_tolerance_bps"],
        size_tolerance_pct=tuning["size_tolerance_pct"],
        reconcile_every=tuning["reconcile_every"],
        min_notional=tuning["min_notional"],
        allocated_token=allocation["allocated_token"],
        allocated_usdc=allocation["allocated_usdc"],
        active_levels=strategy.get("active_levels"),
        cancel_on_shutdown=cancel_on_shutdown,
    )


def main() -> None:
    """CLI entrypoint: pyperliquidity run --config config.toml."""
    parser = argparse.ArgumentParser(prog="pyperliquidity")
    sub = parser.add_subparsers(dest="command")
    run_parser = sub.add_parser("run", help="Start the market maker")
    run_parser.add_argument("--config", required=True, help="Path to config.toml")
    run_parser.add_argument(
        "--keep-orders",
        action="store_true",
        default=False,
        help="Skip cancellation of resting orders on shutdown",
    )
    args = parser.parse_args()

    if args.command != "run":
        parser.print_help()
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    config = _load_config(args.config)
    private_key, wallet = _load_env()
    config = _validate_config(config)

    # Log config (mask private key)
    safe = {**config, "_wallet": wallet, "_testnet": config.get("market", {}).get("testnet", False)}
    logger.info("Starting pyperliquidity with config: %s", safe)

    cancel_on_shutdown = not args.keep_orders
    ws_state = _build_ws_state(config, private_key, wallet, cancel_on_shutdown=cancel_on_shutdown)
    asyncio.run(ws_state.run())
