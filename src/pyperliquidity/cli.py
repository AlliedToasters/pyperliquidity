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
    """Validate required fields and apply defaults for optional tuning params."""
    errors: list[str] = []

    # Required sections/fields
    market = config.get("market", {})
    strategy = config.get("strategy", {})
    allocation = config.get("allocation", {})

    if not market.get("coin"):
        errors.append("market.coin is required")

    for key in ("start_px", "order_sz"):
        val = strategy.get(key)
        if val is None or val <= 0:
            errors.append(f"strategy.{key} must be positive")

    n_orders = strategy.get("n_orders")
    if n_orders is None or n_orders <= 0:
        errors.append("strategy.n_orders must be a positive integer")

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


def _build_ws_state(config: dict[str, Any], private_key: str, wallet: str) -> Any:
    """Construct SDK objects and WsState."""
    from eth_account import Account
    from hyperliquid.exchange import Exchange  # type: ignore[import-untyped]
    from hyperliquid.info import Info  # type: ignore[import-untyped]
    from hyperliquid.utils.constants import (  # type: ignore[import-untyped]
        MAINNET_API_URL,
        TESTNET_API_URL,
    )

    from pyperliquidity.ws_state import WsState

    testnet = config.get("market", {}).get("testnet", False)
    base_url = TESTNET_API_URL if testnet else MAINNET_API_URL

    info = Info(base_url=base_url, skip_ws=True)
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
        n_seeded_levels=strategy.get("n_seeded_levels", 0),
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
    )


def main() -> None:
    """CLI entrypoint: pyperliquidity run --config config.toml."""
    parser = argparse.ArgumentParser(prog="pyperliquidity")
    sub = parser.add_subparsers(dest="command")
    run_parser = sub.add_parser("run", help="Start the market maker")
    run_parser.add_argument("--config", required=True, help="Path to config.toml")
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

    ws_state = _build_ws_state(config, private_key, wallet)
    asyncio.run(ws_state.run())
