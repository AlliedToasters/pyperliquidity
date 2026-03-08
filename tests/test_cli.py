"""Tests for pyperliquidity.cli — config parsing, validation, env loading."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyperliquidity.cli import _build_ws_state, _load_config, _load_env, _validate_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CONFIG = {
    "market": {"coin": "PURR", "testnet": False},
    "strategy": {"n_orders": 10, "order_sz": 100.0, "start_px": 1.0},
    "allocation": {"allocated_token": 1000.0, "allocated_usdc": 500.0},
}


def _write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_missing_file(self) -> None:
        with pytest.raises(SystemExit, match="Config file not found"):
            _load_config("/nonexistent/config.toml")

    def test_malformed_toml(self, tmp_path: Path) -> None:
        p = _write_toml(tmp_path, "[[invalid\n")
        with pytest.raises(SystemExit, match="Failed to parse"):
            _load_config(str(p))

    def test_valid_toml(self, tmp_path: Path) -> None:
        p = _write_toml(
            tmp_path,
            """\
            [market]
            coin = "PURR"
            """,
        )
        result = _load_config(str(p))
        assert result["market"]["coin"] == "PURR"


# ---------------------------------------------------------------------------
# _load_env
# ---------------------------------------------------------------------------


class TestLoadEnv:
    def test_missing_private_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PYPERLIQUIDITY_PRIVATE_KEY", raising=False)
        monkeypatch.delenv("PYPERLIQUIDITY_WALLET", raising=False)
        with pytest.raises(SystemExit, match="PRIVATE_KEY"):
            _load_env()

    def test_empty_private_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYPERLIQUIDITY_PRIVATE_KEY", "  ")
        monkeypatch.setenv("PYPERLIQUIDITY_WALLET", "0xabc")
        with pytest.raises(SystemExit, match="PRIVATE_KEY"):
            _load_env()

    def test_missing_wallet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYPERLIQUIDITY_PRIVATE_KEY", "0xdeadbeef")
        monkeypatch.delenv("PYPERLIQUIDITY_WALLET", raising=False)
        with pytest.raises(SystemExit, match="WALLET"):
            _load_env()

    def test_empty_wallet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYPERLIQUIDITY_PRIVATE_KEY", "0xdeadbeef")
        monkeypatch.setenv("PYPERLIQUIDITY_WALLET", "")
        with pytest.raises(SystemExit, match="WALLET"):
            _load_env()

    def test_both_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYPERLIQUIDITY_PRIVATE_KEY", "0xdeadbeef")
        monkeypatch.setenv("PYPERLIQUIDITY_WALLET", "0xabc")
        pk, w = _load_env()
        assert pk == "0xdeadbeef"
        assert w == "0xabc"


# ---------------------------------------------------------------------------
# _validate_config
# ---------------------------------------------------------------------------


class TestValidateConfig:
    def test_valid_config_passes(self) -> None:
        result = _validate_config({**VALID_CONFIG})
        assert result["tuning"]["interval_s"] == 3.0

    def test_missing_coin(self) -> None:
        cfg = {**VALID_CONFIG, "market": {}}
        with pytest.raises(SystemExit, match="market.coin"):
            _validate_config(cfg)

    def test_negative_order_sz(self) -> None:
        cfg = {**VALID_CONFIG, "strategy": {**VALID_CONFIG["strategy"], "order_sz": -1}}
        with pytest.raises(SystemExit, match="order_sz"):
            _validate_config(cfg)

    def test_zero_n_orders(self) -> None:
        cfg = {**VALID_CONFIG, "strategy": {**VALID_CONFIG["strategy"], "n_orders": 0}}
        with pytest.raises(SystemExit, match="n_orders"):
            _validate_config(cfg)

    def test_missing_allocated_token(self) -> None:
        cfg = {**VALID_CONFIG, "allocation": {"allocated_usdc": 500.0}}
        with pytest.raises(SystemExit, match="allocated_token"):
            _validate_config(cfg)

    def test_negative_allocated_usdc(self) -> None:
        cfg = {**VALID_CONFIG, "allocation": {**VALID_CONFIG["allocation"], "allocated_usdc": -10}}
        with pytest.raises(SystemExit, match="allocated_usdc"):
            _validate_config(cfg)

    def test_defaults_applied(self) -> None:
        """Omitted [tuning] section should get defaults."""
        result = _validate_config({**VALID_CONFIG})
        tuning = result["tuning"]
        assert tuning["interval_s"] == 3.0
        assert tuning["dead_zone_bps"] == 5.0
        assert tuning["price_tolerance_bps"] == 1.0
        assert tuning["size_tolerance_pct"] == 1.0
        assert tuning["reconcile_every"] == 20
        assert tuning["min_notional"] == 0.0

    def test_custom_tuning_preserved(self) -> None:
        """Provided tuning values should not be overwritten."""
        cfg = {**VALID_CONFIG, "tuning": {"interval_s": 5.0, "dead_zone_bps": 10.0}}
        result = _validate_config(cfg)
        assert result["tuning"]["interval_s"] == 5.0
        assert result["tuning"]["dead_zone_bps"] == 10.0
        # Others get defaults
        assert result["tuning"]["reconcile_every"] == 20

    def test_missing_start_px(self) -> None:
        cfg = {**VALID_CONFIG, "strategy": {"n_orders": 10, "order_sz": 100.0}}
        with pytest.raises(SystemExit, match="start_px"):
            _validate_config(cfg)

    def test_zero_start_px(self) -> None:
        cfg = {**VALID_CONFIG, "strategy": {**VALID_CONFIG["strategy"], "start_px": 0}}
        with pytest.raises(SystemExit, match="start_px"):
            _validate_config(cfg)

    def test_negative_start_px(self) -> None:
        cfg = {**VALID_CONFIG, "strategy": {**VALID_CONFIG["strategy"], "start_px": -1.0}}
        with pytest.raises(SystemExit, match="start_px"):
            _validate_config(cfg)

    def test_active_levels_optional(self) -> None:
        """active_levels is optional — omitting it should pass validation."""
        result = _validate_config({**VALID_CONFIG})
        assert result["strategy"].get("active_levels") is None

    def test_active_levels_valid(self) -> None:
        """Positive integer active_levels passes validation."""
        cfg = {**VALID_CONFIG, "strategy": {**VALID_CONFIG["strategy"], "active_levels": 5}}
        result = _validate_config(cfg)
        assert result["strategy"]["active_levels"] == 5

    def test_active_levels_zero_rejected(self) -> None:
        """active_levels=0 is rejected."""
        cfg = {**VALID_CONFIG, "strategy": {**VALID_CONFIG["strategy"], "active_levels": 0}}
        with pytest.raises(SystemExit, match="active_levels"):
            _validate_config(cfg)

    def test_active_levels_negative_rejected(self) -> None:
        """Negative active_levels is rejected."""
        cfg = {**VALID_CONFIG, "strategy": {**VALID_CONFIG["strategy"], "active_levels": -1}}
        with pytest.raises(SystemExit, match="active_levels"):
            _validate_config(cfg)

    def test_multiple_errors_reported(self) -> None:
        """All validation errors should be reported at once."""
        cfg = {"market": {}, "strategy": {}, "allocation": {}}
        with pytest.raises(SystemExit, match="market.coin") as exc_info:
            _validate_config(cfg)
        msg = str(exc_info.value)
        assert "n_orders" in msg


# ---------------------------------------------------------------------------
# _build_ws_state — allocation passthrough
# ---------------------------------------------------------------------------


class TestBuildWsStateAllocation:
    """Verify that allocation config values are passed to WsState."""

    @patch("eth_account.Account")
    @patch("hyperliquid.exchange.Exchange")
    @patch("hyperliquid.info.Info")
    def test_allocation_passed_to_ws_state(
        self, mock_info_cls: MagicMock, mock_exchange_cls: MagicMock, mock_account_cls: MagicMock,
    ) -> None:
        mock_info_cls.return_value = MagicMock()
        mock_exchange_cls.return_value = MagicMock()
        mock_account_cls.from_key.return_value = MagicMock()

        config = _validate_config({**VALID_CONFIG})
        ws = _build_ws_state(config, private_key="0xdeadbeef", wallet="0xabc")

        assert ws._allocated_token == 1000.0
        assert ws._allocated_usdc == 500.0
        assert ws.active_levels is None

    @patch("eth_account.Account")
    @patch("hyperliquid.exchange.Exchange")
    @patch("hyperliquid.info.Info")
    def test_active_levels_passed_to_ws_state(
        self, mock_info_cls: MagicMock, mock_exchange_cls: MagicMock, mock_account_cls: MagicMock,
    ) -> None:
        mock_info_cls.return_value = MagicMock()
        mock_exchange_cls.return_value = MagicMock()
        mock_account_cls.from_key.return_value = MagicMock()

        cfg = {**VALID_CONFIG, "strategy": {**VALID_CONFIG["strategy"], "active_levels": 10}}
        config = _validate_config(cfg)
        ws = _build_ws_state(config, private_key="0xdeadbeef", wallet="0xabc")

        assert ws.active_levels == 10


# ---------------------------------------------------------------------------
# target_px config option
# ---------------------------------------------------------------------------


# Config with target_px instead of explicit allocations
TARGET_PX_CONFIG = {
    "market": {"coin": "PURR", "testnet": False},
    "strategy": {"n_orders": 10, "order_sz": 100.0, "start_px": 1.0, "target_px": 1.009},
}


class TestTargetPxValidation:
    def test_target_px_replaces_allocation_requirement(self) -> None:
        """When target_px is set, allocation section is not required."""
        result = _validate_config({**TARGET_PX_CONFIG})
        assert result["allocation"]["allocated_token"] > 0
        assert result["allocation"]["allocated_usdc"] > 0

    def test_target_px_computes_correct_allocations(self) -> None:
        """target_px auto-computes allocation that places cursor correctly."""
        cfg = {
            "market": {"coin": "PURR"},
            "strategy": {
                "n_orders": 20,
                "order_sz": 50.0,
                "start_px": 1.0,
                "target_px": 1.0,  # cursor at level 0 = all asks
            },
        }
        result = _validate_config(cfg)
        # cursor=0 means all 20 levels are asks
        assert result["allocation"]["allocated_token"] == 20 * 50.0
        assert result["allocation"]["allocated_usdc"] == 0.0

    def test_target_px_at_middle_of_grid(self) -> None:
        """target_px in the middle of the grid splits allocations."""
        from pyperliquidity.pricing_grid import PricingGrid

        grid = PricingGrid(start_px=1.0, n_orders=20)
        target = grid.levels[10]
        cfg = {
            "market": {"coin": "PURR"},
            "strategy": {
                "n_orders": 20,
                "order_sz": 50.0,
                "start_px": 1.0,
                "target_px": target,
            },
        }
        result = _validate_config(cfg)
        assert result["allocation"]["allocated_token"] == 10 * 50.0
        expected_usdc = sum(50.0 * grid.price_at_level(i) for i in range(10))
        assert abs(result["allocation"]["allocated_usdc"] - expected_usdc) < 1e-10

    def test_target_px_below_start_px_rejected(self) -> None:
        """target_px < start_px is rejected."""
        cfg = {
            "market": {"coin": "PURR"},
            "strategy": {
                "n_orders": 10,
                "order_sz": 100.0,
                "start_px": 1.0,
                "target_px": 0.5,
            },
        }
        with pytest.raises(SystemExit, match="target_px.*must be >= .*start_px"):
            _validate_config(cfg)

    def test_target_px_above_grid_rejected(self) -> None:
        """target_px above grid max is rejected."""
        cfg = {
            "market": {"coin": "PURR"},
            "strategy": {
                "n_orders": 10,
                "order_sz": 100.0,
                "start_px": 1.0,
                "target_px": 999.0,
            },
        }
        with pytest.raises(SystemExit, match="target_px"):
            _validate_config(cfg)

    def test_target_px_zero_rejected(self) -> None:
        """target_px=0 is rejected."""
        cfg = {
            "market": {"coin": "PURR"},
            "strategy": {
                "n_orders": 10,
                "order_sz": 100.0,
                "start_px": 1.0,
                "target_px": 0,
            },
        }
        with pytest.raises(SystemExit, match="target_px must be positive"):
            _validate_config(cfg)

    def test_target_px_negative_rejected(self) -> None:
        """Negative target_px is rejected."""
        cfg = {
            "market": {"coin": "PURR"},
            "strategy": {
                "n_orders": 10,
                "order_sz": 100.0,
                "start_px": 1.0,
                "target_px": -1.0,
            },
        }
        with pytest.raises(SystemExit, match="target_px must be positive"):
            _validate_config(cfg)

    def test_backward_compatible_without_target_px(self) -> None:
        """Without target_px, allocation fields are still required."""
        result = _validate_config({**VALID_CONFIG})
        assert result["allocation"]["allocated_token"] == 1000.0
        assert result["allocation"]["allocated_usdc"] == 500.0

    def test_no_target_px_missing_allocation_rejected(self) -> None:
        """Without target_px, missing allocations are still an error."""
        cfg = {
            "market": {"coin": "PURR"},
            "strategy": {"n_orders": 10, "order_sz": 100.0, "start_px": 1.0},
        }
        with pytest.raises(SystemExit, match="allocated_token"):
            _validate_config(cfg)

    def test_target_px_optional(self) -> None:
        """target_px is optional — omitting it should work with explicit allocations."""
        result = _validate_config({**VALID_CONFIG})
        # No target_px in the valid config
        assert result["strategy"].get("target_px") is None
        assert result["allocation"]["allocated_token"] == 1000.0


class TestBuildWsStateWithTargetPx:
    """Verify target_px computed allocations flow through to WsState."""

    @patch("eth_account.Account")
    @patch("hyperliquid.exchange.Exchange")
    @patch("hyperliquid.info.Info")
    def test_target_px_allocation_passed_to_ws_state(
        self, mock_info_cls: MagicMock, mock_exchange_cls: MagicMock, mock_account_cls: MagicMock,
    ) -> None:
        mock_info_cls.return_value = MagicMock()
        mock_exchange_cls.return_value = MagicMock()
        mock_account_cls.from_key.return_value = MagicMock()

        from pyperliquidity.pricing_grid import PricingGrid

        grid = PricingGrid(start_px=1.0, n_orders=10)
        target = grid.levels[5]
        cfg = {
            "market": {"coin": "PURR"},
            "strategy": {
                "n_orders": 10,
                "order_sz": 100.0,
                "start_px": 1.0,
                "target_px": target,
            },
        }
        config = _validate_config(cfg)
        ws = _build_ws_state(config, private_key="0xdeadbeef", wallet="0xabc")

        # cursor=5: 5 ask levels * 100 = 500 tokens
        assert ws._allocated_token == 500.0
        # 5 bid levels
        expected_usdc = sum(100.0 * grid.price_at_level(i) for i in range(5))
        assert abs(ws._allocated_usdc - expected_usdc) < 1e-10
