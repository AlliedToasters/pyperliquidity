"""Tests for pyperliquidity.cli — config parsing, validation, env loading."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pyperliquidity.cli import _load_config, _load_env, _validate_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CONFIG = {
    "market": {"coin": "PURR", "testnet": False},
    "strategy": {"start_px": 0.10, "n_orders": 10, "order_sz": 100.0, "n_seeded_levels": 5},
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

    def test_zero_start_px(self) -> None:
        cfg = {**VALID_CONFIG, "strategy": {**VALID_CONFIG["strategy"], "start_px": 0}}
        with pytest.raises(SystemExit, match="start_px"):
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

    def test_multiple_errors_reported(self) -> None:
        """All validation errors should be reported at once."""
        cfg = {"market": {}, "strategy": {}, "allocation": {}}
        with pytest.raises(SystemExit, match="market.coin") as exc_info:
            _validate_config(cfg)
        msg = str(exc_info.value)
        assert "start_px" in msg
        assert "n_orders" in msg
