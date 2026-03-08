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
    exchange = Exchange(account, base_url=base_url, spot_meta=fixed_spot_meta)

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


def _config_to_toml(config: dict[str, Any]) -> str:
    """Serialize a config dict to TOML format.

    Uses a simple f-string formatter — no external dependency needed since
    the config structure is flat and known.
    """
    lines: list[str] = []

    # [market]
    m = config["market"]
    lines.append("[market]")
    lines.append(f'coin = "{m["coin"]}"')
    lines.append(f"testnet = {'true' if m.get('testnet') else 'false'}")
    lines.append("")

    # [strategy]
    s = config["strategy"]
    lines.append("[strategy]")
    lines.append(f"n_orders = {s['n_orders']}  # total grid levels")
    lines.append(f"order_sz = {s['order_sz']}  # tokens per tranche")
    lines.append(f"start_px = {s['start_px']}  # grid bottom price")
    lines.append(f"target_px = {s['target_px']}  # initial cursor price")
    if "active_levels" in s:
        lines.append(f"active_levels = {s['active_levels']}  # max levels per side")
    lines.append("")

    # [allocation]
    a = config["allocation"]
    lines.append("[allocation]")
    lines.append(f"allocated_token = {a['allocated_token']}")
    lines.append(f"allocated_usdc = {a['allocated_usdc']}")
    lines.append("")

    # [tuning]
    t = config.get("tuning", {})
    if t:
        lines.append("[tuning]")
        for key, val in t.items():
            lines.append(f"{key} = {val}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _print_grid_summary(config: dict[str, Any], warnings: list[Any]) -> None:
    """Print a human-readable grid summary to stderr."""
    s = config["strategy"]
    a = config["allocation"]
    m = config["market"]

    print(f"Grid config for {m['coin']}:", file=sys.stderr)
    print(f"  Price range: {s['start_px']} → (level {s['n_orders'] - 1})", file=sys.stderr)
    print(f"  Grid levels: {s['n_orders']}", file=sys.stderr)
    print(f"  Order size:  {s['order_sz']} tokens/tranche", file=sys.stderr)
    print(f"  Target px:   {s['target_px']}", file=sys.stderr)
    if "active_levels" in s:
        print(f"  Active lvls: {s['active_levels']} per side", file=sys.stderr)
    print(f"  Token alloc: {a['allocated_token']}", file=sys.stderr)
    print(f"  USDC alloc:  {a['allocated_usdc']:.2f}", file=sys.stderr)
    if m.get("testnet"):
        print("  Network:     TESTNET", file=sys.stderr)

    for w in warnings:
        print(f"  WARNING [{w.code}]: {w.message}", file=sys.stderr)


def _cmd_run(args: argparse.Namespace) -> None:
    """Handle the 'run' subcommand."""
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


def _cmd_grid(args: argparse.Namespace) -> None:
    """Handle the 'grid' subcommand — generate a config from market parameters."""
    from pyperliquidity.grid_generator import generate_grid_config

    min_px, max_px = args.price_range

    try:
        config, warnings = generate_grid_config(
            coin=args.coin,
            min_px=min_px,
            max_px=max_px,
            liquidity_token=args.liquidity_token,
            target_px=args.target_px,
            tick_size=args.tick_size,
            active_levels=args.active_levels,
            testnet=args.testnet,
            sz_decimals=args.sz_decimals,
            min_notional=args.min_notional,
        )
    except ValueError as exc:
        sys.exit(f"Error: {exc}")

    _print_grid_summary(config, warnings)

    toml_str = _config_to_toml(config)
    if args.output:
        Path(args.output).write_text(toml_str)
        print(f"Config written to {args.output}", file=sys.stderr)
    else:
        print(toml_str)


def main() -> None:
    """CLI entrypoint: pyperliquidity {run,grid}."""
    parser = argparse.ArgumentParser(prog="pyperliquidity")
    sub = parser.add_subparsers(dest="command")

    # --- run subcommand ---
    run_parser = sub.add_parser("run", help="Start the market maker")
    run_parser.add_argument("--config", required=True, help="Path to config.toml")
    run_parser.add_argument(
        "--keep-orders",
        action="store_true",
        default=False,
        help="Skip cancellation of resting orders on shutdown",
    )

    # --- grid subcommand ---
    grid_parser = sub.add_parser("grid", help="Generate a config from market parameters")
    grid_parser.add_argument("--coin", required=True, help="Market identifier (e.g. @1434)")
    grid_parser.add_argument(
        "--price-range", nargs=2, type=float, required=True, metavar=("MIN", "MAX"),
        help="Price range for the grid (min max)",
    )
    grid_parser.add_argument(
        "--liquidity-token", type=float, required=True,
        help="Total token amount to allocate as ask liquidity",
    )
    grid_parser.add_argument("--target-px", type=float, default=None, help="Initial market price")
    grid_parser.add_argument(
        "--tick-size", type=float, default=0.003, help="Tick spacing (default 0.003)",
    )
    grid_parser.add_argument("--active-levels", type=int, default=None, help="Max levels per side")
    grid_parser.add_argument("--testnet", action="store_true", default=False, help="Target testnet")
    grid_parser.add_argument("--output", "-o", type=str, default=None, help="Write TOML to file")
    grid_parser.add_argument(
        "--sz-decimals", type=int, default=None, help="Round order_sz to N decimals",
    )
    grid_parser.add_argument(
        "--min-notional", type=float, default=10.0, help="Min notional (default 10)",
    )

    args = parser.parse_args()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "grid":
        _cmd_grid(args)
    else:
        parser.print_help()
        sys.exit(1)
