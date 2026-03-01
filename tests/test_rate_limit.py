"""Tests for the rate_limit module."""

from pyperliquidity.rate_limit import RateLimitBudget


class TestBudgetComputation:
    def test_fresh_instance_has_full_budget(self):
        rl = RateLimitBudget()
        assert rl.remaining() == 10_000

    def test_budget_decreases_with_requests(self):
        rl = RateLimitBudget()
        for _ in range(5):
            rl.on_request()
        assert rl.remaining() == 9_995

    def test_budget_increases_with_fills(self):
        rl = RateLimitBudget()
        rl.on_request(100)
        before = rl.remaining()
        rl.on_fill(100.0)
        assert rl.remaining() == before + 100

    def test_budget_floor_clamps_to_zero(self):
        rl = RateLimitBudget()
        rl.on_request(20_000)
        assert rl.remaining() == 0


class TestRatio:
    def test_ratio_zero_requests(self):
        rl = RateLimitBudget()
        assert rl.ratio == 0.0

    def test_ratio_healthy(self):
        rl = RateLimitBudget(cum_vlm=1000.0, n_requests=800)
        assert rl.ratio == 1.25

    def test_ratio_unhealthy(self):
        rl = RateLimitBudget(cum_vlm=500.0, n_requests=800)
        assert rl.ratio == 0.625


class TestMutations:
    def test_on_request_default(self):
        rl = RateLimitBudget()
        rl.on_request()
        assert rl.n_requests == 1

    def test_on_request_explicit(self):
        rl = RateLimitBudget()
        rl.on_request(n=3)
        assert rl.n_requests == 3

    def test_on_fill_single(self):
        rl = RateLimitBudget()
        rl.on_fill(50.0)
        assert rl.cum_vlm == 50.0

    def test_on_fill_accumulates(self):
        rl = RateLimitBudget()
        rl.on_fill(100.0)
        rl.on_fill(200.0)
        assert rl.cum_vlm == 300.0

    def test_sync_from_exchange(self):
        rl = RateLimitBudget(cum_vlm=500.0, n_requests=400)
        rl.sync_from_exchange(600.0, 450)
        assert rl.cum_vlm == 600.0
        assert rl.n_requests == 450


class TestHealthChecks:
    def test_is_healthy_true(self):
        rl = RateLimitBudget(cum_vlm=1000.0, n_requests=800)
        assert rl.is_healthy() is True

    def test_is_healthy_false(self):
        rl = RateLimitBudget(cum_vlm=500.0, n_requests=800)
        assert rl.is_healthy() is False

    def test_is_emergency_false(self):
        rl = RateLimitBudget()
        assert rl.is_emergency() is False

    def test_is_emergency_true(self):
        rl = RateLimitBudget()
        rl.on_request(9_800)  # budget = 200, below SAFETY_MARGIN of 500
        assert rl.is_emergency() is True

    def test_is_emergency_custom_margin(self):
        rl = RateLimitBudget(SAFETY_MARGIN=50)
        rl.on_request(9_960)  # budget = 40, below custom margin of 50
        assert rl.is_emergency() is True


class TestLogStatus:
    def test_log_status_format(self):
        rl = RateLimitBudget(cum_vlm=583479.0, n_requests=522489)
        status = rl.log_status()
        assert "ratio=" in status
        assert "budget=" in status
        assert "vol=" in status
        assert "reqs=" in status

    def test_log_status_values(self):
        rl = RateLimitBudget(cum_vlm=583479.0, n_requests=522489)
        status = rl.log_status()
        assert "ratio=1.12" in status
        assert "reqs=522489" in status
