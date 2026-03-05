"""Stateful mock exchange and info objects for integration tests.

Provides MockExchange (order management with OID tracking) and MockInfo
(REST endpoints) that are more realistic than MagicMock for multi-tick
tests where order state must be consistent across calls.
"""

from __future__ import annotations

from typing import Any


class MockExchange:
    """Stateful mock of the Hyperliquid SDK exchange object.

    Tracks resting orders with auto-incrementing OIDs so that
    multi-tick integration tests can verify order lifecycle end-to-end.
    """

    def __init__(self, starting_oid: int = 1000) -> None:
        self._next_oid = starting_oid
        # oid → {coin, is_buy, sz, limit_px, ...}
        self.resting: dict[int, dict[str, Any]] = {}

    def _alloc_oid(self) -> int:
        oid = self._next_oid
        self._next_oid += 1
        return oid

    # -- SDK-compatible batch methods ------------------------------------------

    def bulk_orders(self, reqs: list[dict[str, Any]]) -> dict[str, Any]:
        """Place orders. Returns SDK-format response with statuses."""
        statuses: list[dict[str, Any]] = []
        for req in reqs:
            oid = self._alloc_oid()
            self.resting[oid] = {
                "coin": req["coin"],
                "is_buy": req["is_buy"],
                "sz": req["sz"],
                "limit_px": req["limit_px"],
            }
            statuses.append({"resting": {"oid": oid}})
        return {"status": "ok", "response": {"data": {"statuses": statuses}}}

    def bulk_modify_orders_new(self, reqs: list[dict[str, Any]]) -> dict[str, Any]:
        """Modify orders. Assigns new OIDs (mirrors real exchange behavior)."""
        statuses: list[dict[str, Any]] = []
        for req in reqs:
            old_oid = req["oid"]
            order_spec = req["order"]
            if old_oid not in self.resting:
                statuses.append({"error": "Cannot modify order"})
                continue
            # Remove old, insert new with fresh OID
            del self.resting[old_oid]
            new_oid = self._alloc_oid()
            self.resting[new_oid] = {
                "coin": order_spec["coin"],
                "is_buy": order_spec["is_buy"],
                "sz": order_spec["sz"],
                "limit_px": order_spec["limit_px"],
            }
            statuses.append({"resting": {"oid": new_oid}})
        return {"status": "ok", "response": {"data": {"statuses": statuses}}}

    def bulk_cancel(self, reqs: list[dict[str, Any]]) -> dict[str, Any]:
        """Cancel orders by OID."""
        statuses: list[dict[str, Any]] = []
        for req in reqs:
            oid = req["o"]
            if oid in self.resting:
                del self.resting[oid]
                statuses.append({"success": True})
            else:
                statuses.append({"error": "Order not found"})
        return {"status": "ok", "response": {"data": {"statuses": statuses}}}

    # -- Test helpers ----------------------------------------------------------

    def fill_order(
        self, oid: int, fill_sz: float | None = None, tid: int = 0,
    ) -> dict[str, Any]:
        """Simulate a fill. Returns a fill event dict for _handle_fill().

        If *fill_sz* is None, the entire order is filled.
        """
        order = self.resting.get(oid)
        if order is None:
            raise KeyError(f"OID {oid} not resting")

        sz = fill_sz if fill_sz is not None else order["sz"]
        px = order["limit_px"]
        side = "B" if order["is_buy"] else "A"

        remaining = order["sz"] - sz
        if remaining <= 1e-12:
            del self.resting[oid]
        else:
            order["sz"] = remaining

        return {
            "tid": tid,
            "oid": oid,
            "sz": str(sz),
            "px": str(px),
            "side": side,
        }

    def open_orders_list(self, coin: str) -> list[dict[str, Any]]:
        """Return open_orders in SDK REST format for a given coin."""
        result = []
        for oid, o in self.resting.items():
            if o["coin"] == coin:
                result.append({
                    "coin": coin,
                    "oid": oid,
                    "side": "B" if o["is_buy"] else "A",
                    "limitPx": str(o["limit_px"]),
                    "sz": str(o["sz"]),
                })
        return result


class MockInfo:
    """Stateful mock of the Hyperliquid SDK info object.

    Delegates open_orders to MockExchange for consistency.
    """

    def __init__(
        self,
        mock_exchange: MockExchange,
        coin: str = "TEST",
        spot_index: int = 5,
        base_token_name: str = "TESTBASE",
        token_bal: float = 100.0,
        usdc_bal: float = 500.0,
        cum_vlm: float = 1000.0,
        n_requests: int = 200,
    ) -> None:
        self._exchange = mock_exchange
        self.coin = coin
        self._spot_index = spot_index
        self._base_token_name = base_token_name
        self.token_bal = token_bal
        self.usdc_bal = usdc_bal
        self._cum_vlm = cum_vlm
        self._n_requests = n_requests

    def spot_meta(self) -> dict[str, Any]:
        base_token_idx = 0
        universe = [
            {"name": f"COIN{i}", "index": i, "tokens": [i + 1]}
            for i in range(self._spot_index)
        ]
        universe.append({
            "name": self.coin,
            "index": self._spot_index,
            "tokens": [base_token_idx],
        })
        return {
            "universe": universe,
            "tokens": [{"name": self._base_token_name}],
        }

    def open_orders(self, addr: str) -> list[dict[str, Any]]:
        return self._exchange.open_orders_list(self.coin)

    def spot_user_state(self, addr: str) -> dict[str, Any]:
        return {
            "balances": [
                {"coin": self._base_token_name, "total": str(self.token_bal)},
                {"coin": "USDC", "total": str(self.usdc_bal)},
            ],
        }

    def user_rate_limit(self, addr: str) -> dict[str, Any]:
        return {
            "cumVlm": str(self._cum_vlm),
            "nRequestsUsed": str(self._n_requests),
        }

    def subscribe(self, sub: dict[str, Any], cb: Any) -> None:
        pass  # no-op
