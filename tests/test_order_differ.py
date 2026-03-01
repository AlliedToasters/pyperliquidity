"""Tests for the order_differ module."""

from pyperliquidity.order_differ import OrderDiff, compute_diff
from pyperliquidity.order_state import TrackedOrder
from pyperliquidity.quoting_engine import DesiredOrder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _desired(side: str, level: int, price: float, size: float) -> DesiredOrder:
    return DesiredOrder(side=side, level_index=level, price=price, size=size)


def _tracked(oid: int, side: str, level: int, price: float, size: float) -> TrackedOrder:
    return TrackedOrder(oid=oid, side=side, level_index=level, price=price, size=size)


# Default tolerances: tight enough to detect any real change
TIGHT = dict(dead_zone_bps=0.0, price_tolerance_bps=0.0, size_tolerance_pct=0.0)
# Generous tolerances for dead-zone / tolerance tests
LOOSE = dict(dead_zone_bps=15.0, price_tolerance_bps=1.0, size_tolerance_pct=5.0)


# ---------------------------------------------------------------------------
# 3.1  Identical desired and current → empty diff
# ---------------------------------------------------------------------------

class TestIdentical:
    def test_identical_orders_produce_empty_diff(self):
        desired = [
            _desired("buy", 0, 100.0, 10.0),
            _desired("sell", 5, 101.5, 10.0),
        ]
        current = [
            _tracked(1, "buy", 0, 100.0, 10.0),
            _tracked(2, "sell", 5, 101.5, 10.0),
        ]
        diff = compute_diff(desired, current, **TIGHT)
        assert diff.modifies == []
        assert diff.places == []
        assert diff.cancels == []


# ---------------------------------------------------------------------------
# 3.2  Dead zone suppression
# ---------------------------------------------------------------------------

class TestDeadZone:
    def test_drift_below_threshold_returns_empty(self):
        # Current mid ≈ 100, desired mid ≈ 100.01 → ~1 bps drift
        desired = [_desired("buy", 0, 100.01, 10.0)]
        current = [_tracked(1, "buy", 0, 100.0, 10.0)]
        diff = compute_diff(desired, current, dead_zone_bps=15.0,
                            price_tolerance_bps=0.0, size_tolerance_pct=0.0)
        assert diff == OrderDiff()

    def test_drift_above_threshold_returns_mutations(self):
        # Current mid = 100, desired mid = 100.20 → 20 bps drift
        desired = [_desired("buy", 0, 100.20, 10.0)]
        current = [_tracked(1, "buy", 0, 100.0, 10.0)]
        diff = compute_diff(desired, current, dead_zone_bps=15.0,
                            price_tolerance_bps=0.0, size_tolerance_pct=0.0)
        assert len(diff.modifies) == 1
        assert diff.modifies[0] == (1, desired[0])


# ---------------------------------------------------------------------------
# 3.3  Dead zone bypass: empty lists
# ---------------------------------------------------------------------------

class TestDeadZoneBypass:
    def test_empty_current_returns_all_places(self):
        desired = [
            _desired("buy", 0, 100.0, 10.0),
            _desired("sell", 5, 101.5, 10.0),
        ]
        diff = compute_diff(desired, [], **LOOSE)
        assert len(diff.places) == 2
        assert diff.modifies == []
        assert diff.cancels == []

    def test_empty_desired_returns_all_cancels(self):
        current = [
            _tracked(1, "buy", 0, 100.0, 10.0),
            _tracked(2, "sell", 5, 101.5, 10.0),
        ]
        diff = compute_diff([], current, **LOOSE)
        assert set(diff.cancels) == {1, 2}
        assert diff.modifies == []
        assert diff.places == []

    def test_both_empty_returns_empty_diff(self):
        diff = compute_diff([], [], **LOOSE)
        assert diff == OrderDiff()


# ---------------------------------------------------------------------------
# 3.4  Level-index matching: unmatched → places / cancels
# ---------------------------------------------------------------------------

class TestLevelIndexMatching:
    def test_unmatched_desired_becomes_place(self):
        desired = [
            _desired("buy", 0, 100.0, 10.0),
            _desired("buy", 1, 99.7, 10.0),  # no match
        ]
        current = [_tracked(1, "buy", 0, 100.0, 10.0)]
        diff = compute_diff(desired, current, **TIGHT)
        assert len(diff.places) == 1
        assert diff.places[0].level_index == 1

    def test_unmatched_current_becomes_cancel(self):
        desired = [_desired("buy", 0, 100.0, 10.0)]
        current = [
            _tracked(1, "buy", 0, 100.0, 10.0),
            _tracked(2, "buy", 1, 99.7, 10.0),  # no match
        ]
        diff = compute_diff(desired, current, **TIGHT)
        assert diff.cancels == [2]


# ---------------------------------------------------------------------------
# 3.5  Per-order tolerance
# ---------------------------------------------------------------------------

class TestPerOrderTolerance:
    def test_within_tolerance_skips_modify(self):
        # Price diff = 0.005 / 100 * 10000 = 0.5 bps (< 1.0)
        # Size diff = 0.04 / 10 * 100 = 0.4% (< 5.0%)
        desired = [_desired("buy", 0, 100.005, 10.04)]
        current = [_tracked(1, "buy", 0, 100.0, 10.0)]
        diff = compute_diff(desired, current, dead_zone_bps=0.0,
                            price_tolerance_bps=1.0, size_tolerance_pct=5.0)
        assert diff.modifies == []

    def test_exceeds_price_tolerance_emits_modify(self):
        # Price diff = 0.02 / 100 * 10000 = 2 bps (> 1.0)
        desired = [_desired("buy", 0, 100.02, 10.0)]
        current = [_tracked(1, "buy", 0, 100.0, 10.0)]
        diff = compute_diff(desired, current, dead_zone_bps=0.0,
                            price_tolerance_bps=1.0, size_tolerance_pct=5.0)
        assert len(diff.modifies) == 1

    def test_exceeds_size_tolerance_emits_modify(self):
        # Size diff = 1.0 / 10 * 100 = 10% (> 5.0%)
        desired = [_desired("buy", 0, 100.0, 11.0)]
        current = [_tracked(1, "buy", 0, 100.0, 10.0)]
        diff = compute_diff(desired, current, dead_zone_bps=0.0,
                            price_tolerance_bps=1.0, size_tolerance_pct=5.0)
        assert len(diff.modifies) == 1


# ---------------------------------------------------------------------------
# 3.6  Cross-side validation
# ---------------------------------------------------------------------------

class TestCrossSide:
    def test_cross_side_emits_cancel_and_place(self):
        desired = [_desired("sell", 5, 101.5, 10.0)]
        current = [_tracked(1, "buy", 5, 99.5, 10.0)]
        diff = compute_diff(desired, current, **TIGHT)
        # Must NOT be a modify — should be cancel + place
        assert diff.modifies == []
        assert diff.cancels == [1]
        assert len(diff.places) == 1
        assert diff.places[0].side == "sell"

    def test_same_side_modify_not_split(self):
        desired = [_desired("buy", 3, 100.5, 10.0)]
        current = [_tracked(1, "buy", 3, 100.0, 10.0)]
        diff = compute_diff(desired, current, **TIGHT)
        assert len(diff.modifies) == 1
        assert diff.cancels == []
        assert diff.places == []


# ---------------------------------------------------------------------------
# 3.7  Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_inputs_same_output(self):
        desired = [
            _desired("buy", 0, 100.0, 10.0),
            _desired("sell", 5, 101.5, 8.0),
            _desired("sell", 6, 101.8, 10.0),
        ]
        current = [
            _tracked(1, "buy", 0, 99.5, 10.0),
            _tracked(2, "sell", 5, 101.5, 10.0),
        ]
        results = [compute_diff(desired, current, **TIGHT) for _ in range(10)]
        for r in results[1:]:
            assert r.modifies == results[0].modifies
            assert r.places == results[0].places
            assert r.cancels == results[0].cancels


# ---------------------------------------------------------------------------
# 3.8  Edge case: single order per side, partial size changes
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_order_each_side_with_partial_fill(self):
        desired = [
            _desired("buy", 2, 99.0, 7.5),   # was 10, partially filled
            _desired("sell", 3, 101.0, 10.0),
        ]
        current = [
            _tracked(10, "buy", 2, 99.0, 10.0),
            _tracked(11, "sell", 3, 101.0, 10.0),
        ]
        diff = compute_diff(desired, current, dead_zone_bps=0.0,
                            price_tolerance_bps=0.0, size_tolerance_pct=0.0)
        # Buy size changed (10 → 7.5), sell unchanged
        assert len(diff.modifies) == 1
        assert diff.modifies[0][0] == 10  # buy order OID
        assert diff.places == []
        assert diff.cancels == []

    def test_both_lists_empty(self):
        diff = compute_diff([], [], **TIGHT)
        assert diff == OrderDiff()
