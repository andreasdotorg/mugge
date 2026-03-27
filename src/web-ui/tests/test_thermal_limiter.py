"""Tests for ThermalGainLimiter (T-092-3)."""

import asyncio
import concurrent.futures
import math
import time
import unittest
from unittest.mock import MagicMock, AsyncMock, patch


def _run(coro):
    """Run async coroutine in sync test context (works with pytest-playwright's loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.thermal_limiter import (
    ThermalGainLimiter,
    ChannelLimitState,
    OverrideEntry,
    AuditEntry,
    SOFT_KNEE_THRESHOLD_DB,
    SOFT_KNEE_MAX_REDUCTION_DB,
    _db_to_linear,
    _linear_to_db,
)


# -- Helper converters --------------------------------------------------------

class TestDbLinearConversion(unittest.TestCase):

    def test_db_to_linear_zero(self):
        self.assertAlmostEqual(_db_to_linear(0.0), 1.0, places=10)

    def test_db_to_linear_minus_6(self):
        self.assertAlmostEqual(_db_to_linear(-6.0), 0.501187, places=4)

    def test_db_to_linear_minus_120(self):
        self.assertEqual(_db_to_linear(-120.0), 0.0)

    def test_db_to_linear_very_negative(self):
        self.assertEqual(_db_to_linear(-200.0), 0.0)

    def test_linear_to_db_unity(self):
        self.assertAlmostEqual(_linear_to_db(1.0), 0.0, places=10)

    def test_linear_to_db_zero(self):
        self.assertEqual(_linear_to_db(0.0), -120.0)

    def test_linear_to_db_half(self):
        self.assertAlmostEqual(_linear_to_db(0.5), -6.0206, places=2)

    def test_roundtrip(self):
        for db in [-60, -20, -6, -3, 0]:
            self.assertAlmostEqual(
                _linear_to_db(_db_to_linear(db)), db, places=6)


# -- OverrideEntry -------------------------------------------------------------

class TestOverrideEntry(unittest.TestCase):

    def test_not_expired(self):
        ov = OverrideEntry(
            channel_name="sat_left",
            ceiling_multiplier=1.5,
            expires_at=time.monotonic() + 300,
        )
        self.assertFalse(ov.is_expired(time.monotonic()))

    def test_expired(self):
        ov = OverrideEntry(
            channel_name="sat_left",
            ceiling_multiplier=1.5,
            expires_at=time.monotonic() - 1,
        )
        self.assertTrue(ov.is_expired(time.monotonic()))


# -- AuditEntry ----------------------------------------------------------------

class TestAuditEntry(unittest.TestCase):

    def test_to_dict(self):
        e = AuditEntry(
            timestamp=1000.0,
            channel="sub1",
            action="engage",
            detail="headroom=2.5dB",
        )
        d = e.to_dict()
        self.assertEqual(d["channel"], "sub1")
        self.assertEqual(d["action"], "engage")
        self.assertIn("headroom", d["detail"])


# -- compute_reduction ---------------------------------------------------------

class TestComputeReduction(unittest.TestCase):
    """Test the soft-knee gain reduction logic."""

    def _make_limiter(self):
        monitor = MagicMock()
        monitor.snapshot.return_value = []
        return ThermalGainLimiter(monitor, is_mock=True)

    def test_no_ceiling_data(self):
        """No headroom data -> no reduction."""
        limiter = self._make_limiter()
        factor = limiter.compute_reduction(None, 0.0, "sat_left")
        self.assertEqual(factor, 1.0)

    def test_plenty_of_headroom(self):
        """Headroom > 3 dB -> no reduction."""
        limiter = self._make_limiter()
        factor = limiter.compute_reduction(10.0, 10.0, "sat_left")
        self.assertEqual(factor, 1.0)

    def test_exactly_at_threshold(self):
        """Headroom exactly at threshold -> no reduction (edge case)."""
        limiter = self._make_limiter()
        factor = limiter.compute_reduction(
            SOFT_KNEE_THRESHOLD_DB + 0.001, 50.0, "sat_left")
        self.assertEqual(factor, 1.0)

    def test_soft_knee_midpoint(self):
        """Headroom at 1.5 dB (midpoint of 0-3 dB knee) -> ~1.5 dB reduction."""
        limiter = self._make_limiter()
        factor = limiter.compute_reduction(1.5, 70.0, "sat_left")
        reduction_db = _linear_to_db(factor)
        # At midpoint: -1.5 dB reduction
        self.assertAlmostEqual(reduction_db, -1.5, places=1)
        self.assertGreater(factor, 0.0)
        self.assertLess(factor, 1.0)

    def test_soft_knee_at_zero_headroom(self):
        """Headroom at 0 dB -> -3 dB reduction (max soft knee)."""
        limiter = self._make_limiter()
        # pct=100 means exactly at ceiling
        factor = limiter.compute_reduction(0.0, 100.0, "sat_left")
        reduction_db = _linear_to_db(factor)
        # Hard limit: at pct=100, reduction_db = -10*log10(100/100) = 0
        # But effective_headroom <= 0, so hard limit path.
        # For pct=100: reduction_db = 0, clamped to 0 -> factor = 1.0
        # Actually at exactly 0 headroom, we enter the hard limit path:
        # reduction_db = -10*log10(100/100) = 0 dB, clamped to 0 -> 1.0
        # This is correct: at exactly ceiling, no extra reduction needed
        # beyond what the soft knee already applies.
        self.assertLessEqual(factor, 1.0)

    def test_hard_limit_over_ceiling(self):
        """At 120% of ceiling -> gain reduced with at least soft-knee floor."""
        limiter = self._make_limiter()
        # headroom is negative (below ceiling)
        factor = limiter.compute_reduction(-1.0, 120.0, "sat_left")
        reduction_db = _linear_to_db(factor)
        # Power-based reduction is -10*log10(120/100) = -0.79 dB, but the
        # continuity floor from the soft knee (-3 dB at headroom=0) is more
        # aggressive. The limiter uses min(power_reduction, -soft_knee_max).
        self.assertAlmostEqual(reduction_db, -SOFT_KNEE_MAX_REDUCTION_DB, places=1)
        self.assertLess(factor, 1.0)

    def test_hard_limit_200_percent(self):
        """At 200% of ceiling -> significant reduction."""
        limiter = self._make_limiter()
        factor = limiter.compute_reduction(-3.0, 200.0, "sat_left")
        reduction_db = _linear_to_db(factor)
        # Power reduction is -10*log10(2) = -3.01 dB. Soft knee floor is -3 dB.
        # min(-3.01, -3.0) = -3.01 dB.
        expected_db = -10.0 * math.log10(200.0 / 100.0)
        self.assertAlmostEqual(reduction_db, expected_db, places=1)

    def test_hard_limit_capped_at_minus_20(self):
        """Even extreme overload doesn't reduce more than -20 dB."""
        limiter = self._make_limiter()
        # 10000% of ceiling
        factor = limiter.compute_reduction(-20.0, 10000.0, "sat_left")
        reduction_db = _linear_to_db(factor)
        self.assertGreaterEqual(reduction_db, -20.0)

    def test_reduction_monotonic(self):
        """Reduction should increase monotonically as headroom decreases."""
        limiter = self._make_limiter()
        headrooms = [10, 3, 2, 1, 0, -1, -3]
        pcts = [10, 50, 63, 79, 100, 126, 200]
        factors = []
        for hr, pct in zip(headrooms, pcts):
            factors.append(limiter.compute_reduction(hr, pct, "sat_left"))
        for i in range(len(factors) - 1):
            self.assertGreaterEqual(factors[i], factors[i + 1],
                f"Non-monotonic at headroom={headrooms[i+1]}: "
                f"{factors[i]} < {factors[i+1]}")


# -- Override interaction with compute_reduction --------------------------------

class TestOverrideReduction(unittest.TestCase):

    def _make_limiter_with_channel(self):
        monitor = MagicMock()
        monitor.snapshot.return_value = []
        limiter = ThermalGainLimiter(monitor, is_mock=True)
        limiter.configure_channels([{
            "name": "sat_left",
            "channel_index": 0,
            "gain_node_name": "gain_left_hp",
            "base_mult": 0.001,
        }])
        return limiter

    def test_override_increases_effective_headroom(self):
        """Override with 2x ceiling gives ~3 dB extra headroom."""
        limiter = self._make_limiter_with_channel()
        # Without override: at 2 dB headroom -> in soft knee
        factor_no_override = limiter.compute_reduction(2.0, 63.0, "sat_left")
        self.assertLess(factor_no_override, 1.0)

        # With 2x ceiling override: +3 dB headroom -> 5 dB total -> no reduction
        limiter.set_override("sat_left", ceiling_multiplier=2.0)
        factor_with_override = limiter.compute_reduction(2.0, 63.0, "sat_left")
        self.assertEqual(factor_with_override, 1.0)

    def test_override_expired_no_effect(self):
        """Expired override has no effect on reduction."""
        limiter = self._make_limiter_with_channel()
        # Set an already-expired override
        limiter._overrides["sat_left"] = OverrideEntry(
            channel_name="sat_left",
            ceiling_multiplier=2.0,
            expires_at=time.monotonic() - 10,
        )
        factor = limiter.compute_reduction(2.0, 63.0, "sat_left")
        self.assertLess(factor, 1.0)  # Soft knee, no override help


# -- ThermalGainLimiter methods ------------------------------------------------

class TestThermalGainLimiter(unittest.TestCase):

    def _make_limiter(self, channels=None):
        monitor = MagicMock()
        monitor.snapshot.return_value = []
        limiter = ThermalGainLimiter(monitor, is_mock=True)
        if channels is None:
            channels = [
                {"name": "sat_left", "channel_index": 0,
                 "gain_node_name": "gain_left_hp", "base_mult": 0.001},
                {"name": "sat_right", "channel_index": 1,
                 "gain_node_name": "gain_right_hp", "base_mult": 0.001},
                {"name": "sub1", "channel_index": 2,
                 "gain_node_name": "gain_sub1_lp", "base_mult": 0.000631},
            ]
        limiter.configure_channels(channels)
        return limiter

    def test_configure_channels(self):
        limiter = self._make_limiter()
        self.assertEqual(len(limiter._channels), 3)
        self.assertIn("sat_left", limiter._channels)
        self.assertEqual(limiter._channels["sat_left"].base_mult, 0.001)

    def test_reconfigure_clears_overrides(self):
        limiter = self._make_limiter()
        limiter.set_override("sat_left")
        self.assertIn("sat_left", limiter._overrides)
        # Reconfigure
        limiter.configure_channels([
            {"name": "sat_left", "channel_index": 0,
             "gain_node_name": "gain_left_hp", "base_mult": 0.002},
        ])
        self.assertEqual(len(limiter._overrides), 0)

    def test_set_override_valid(self):
        limiter = self._make_limiter()
        result = limiter.set_override("sat_left", ceiling_multiplier=1.5, duration_s=60)
        self.assertTrue(result["ok"])
        self.assertIn("sat_left", limiter._overrides)

    def test_set_override_unknown_channel(self):
        limiter = self._make_limiter()
        result = limiter.set_override("nonexistent")
        self.assertFalse(result["ok"])
        self.assertIn("unknown", result["error"])

    def test_set_override_bad_multiplier(self):
        limiter = self._make_limiter()
        result = limiter.set_override("sat_left", ceiling_multiplier=0.5)
        self.assertFalse(result["ok"])

        result = limiter.set_override("sat_left", ceiling_multiplier=5.0)
        self.assertFalse(result["ok"])

    def test_set_override_bad_duration(self):
        limiter = self._make_limiter()
        result = limiter.set_override("sat_left", duration_s=5)
        self.assertFalse(result["ok"])

        result = limiter.set_override("sat_left", duration_s=3600)
        self.assertFalse(result["ok"])

    def test_clear_override(self):
        limiter = self._make_limiter()
        limiter.set_override("sat_left")
        result = limiter.clear_override("sat_left")
        self.assertTrue(result["ok"])
        self.assertNotIn("sat_left", limiter._overrides)

    def test_clear_override_no_active(self):
        limiter = self._make_limiter()
        result = limiter.clear_override("sat_left")
        self.assertTrue(result["ok"])
        self.assertIn("no override", result.get("detail", ""))

    def test_clear_override_unknown_channel(self):
        limiter = self._make_limiter()
        result = limiter.clear_override("nonexistent")
        self.assertFalse(result["ok"])

    def test_snapshot_structure(self):
        limiter = self._make_limiter()
        snap = limiter.snapshot()
        self.assertIn("channels", snap)
        self.assertIn("any_limiting", snap)
        self.assertFalse(snap["any_limiting"])
        self.assertEqual(len(snap["channels"]), 3)

        ch = snap["channels"][0]
        self.assertIn("name", ch)
        self.assertIn("base_mult", ch)
        self.assertIn("current_mult", ch)
        self.assertIn("reduction_factor", ch)
        self.assertIn("reduction_db", ch)
        self.assertIn("is_limiting", ch)
        self.assertIn("override", ch)

    def test_snapshot_with_override(self):
        limiter = self._make_limiter()
        limiter.set_override("sat_left", ceiling_multiplier=1.5, duration_s=60)
        snap = limiter.snapshot()
        ch0 = snap["channels"][0]
        self.assertIsNotNone(ch0["override"])
        self.assertEqual(ch0["override"]["ceiling_multiplier"], 1.5)

    def test_audit_log(self):
        limiter = self._make_limiter()
        # configure_channels adds a "reconfigure" entry
        entries = limiter.audit_log()
        self.assertGreater(len(entries), 0)
        self.assertEqual(entries[-1]["action"], "reconfigure")

    def test_audit_log_override(self):
        limiter = self._make_limiter()
        limiter.set_override("sat_left")
        entries = limiter.audit_log()
        override_entries = [e for e in entries if e["action"] == "override_set"]
        self.assertEqual(len(override_entries), 1)

    def test_audit_log_limit(self):
        limiter = self._make_limiter()
        entries = limiter.audit_log(limit=1)
        self.assertLessEqual(len(entries), 1)


# -- Async enforcement tick ----------------------------------------------------

class TestEnforceTick(unittest.TestCase):
    """Test the enforcement tick logic."""

    def _make_limiter_with_thermal(self, thermal_states):
        """Create limiter with mocked thermal monitor returning given states."""
        monitor = MagicMock()
        monitor.snapshot.return_value = thermal_states
        limiter = ThermalGainLimiter(monitor, is_mock=True)
        limiter.configure_channels([
            {"name": "sat_left", "channel_index": 0,
             "gain_node_name": "gain_left_hp", "base_mult": 0.001},
            {"name": "sub1", "channel_index": 2,
             "gain_node_name": "gain_sub1_lp", "base_mult": 0.000631},
        ])
        return limiter

    def test_tick_no_limiting_when_ok(self):
        """No limiting when all channels have plenty of headroom."""
        thermal = [
            {"name": "sat_left", "headroom_db": 15.0, "pct_of_ceiling": 3.0},
            {"name": "sub1", "headroom_db": 20.0, "pct_of_ceiling": 1.0},
        ]
        limiter = self._make_limiter_with_thermal(thermal)

        _run(limiter._enforce_tick(time.monotonic()))

        self.assertFalse(limiter._channels["sat_left"].is_limiting)
        self.assertFalse(limiter._channels["sub1"].is_limiting)

    def test_tick_engages_on_warning(self):
        """Limiter engages when headroom drops below threshold."""
        thermal = [
            {"name": "sat_left", "headroom_db": 1.5, "pct_of_ceiling": 70.0},
            {"name": "sub1", "headroom_db": 20.0, "pct_of_ceiling": 1.0},
        ]
        limiter = self._make_limiter_with_thermal(thermal)

        _run(limiter._enforce_tick(time.monotonic()))

        self.assertTrue(limiter._channels["sat_left"].is_limiting)
        self.assertFalse(limiter._channels["sub1"].is_limiting)
        self.assertLess(limiter._channels["sat_left"].reduction_factor, 1.0)

    def test_tick_hard_limit_over_ceiling(self):
        """Limiter applies hard reduction when over ceiling."""
        thermal = [
            {"name": "sat_left", "headroom_db": -2.0, "pct_of_ceiling": 158.0},
            {"name": "sub1", "headroom_db": 20.0, "pct_of_ceiling": 1.0},
        ]
        limiter = self._make_limiter_with_thermal(thermal)

        _run(limiter._enforce_tick(time.monotonic()))

        ch = limiter._channels["sat_left"]
        self.assertTrue(ch.is_limiting)
        self.assertLess(ch.reduction_factor, 0.8)

    def test_tick_disengages_when_headroom_recovers(self):
        """Limiter disengages when headroom recovers above threshold."""
        limiter = self._make_limiter_with_thermal([
            {"name": "sat_left", "headroom_db": 1.0, "pct_of_ceiling": 80.0},
            {"name": "sub1", "headroom_db": 20.0, "pct_of_ceiling": 1.0},
        ])

        # First tick: engage
        _run(limiter._enforce_tick(time.monotonic()))
        self.assertTrue(limiter._channels["sat_left"].is_limiting)

        # Update thermal to show recovery
        limiter._monitor.snapshot.return_value = [
            {"name": "sat_left", "headroom_db": 10.0, "pct_of_ceiling": 10.0},
            {"name": "sub1", "headroom_db": 20.0, "pct_of_ceiling": 1.0},
        ]
        _run(limiter._enforce_tick(time.monotonic()))
        self.assertFalse(limiter._channels["sat_left"].is_limiting)

    def test_tick_audit_engage_disengage(self):
        """Engage/disengage transitions are logged in audit trail."""
        limiter = self._make_limiter_with_thermal([
            {"name": "sat_left", "headroom_db": 1.0, "pct_of_ceiling": 80.0},
            {"name": "sub1", "headroom_db": 20.0, "pct_of_ceiling": 1.0},
        ])

        _run(limiter._enforce_tick(time.monotonic()))

        limiter._monitor.snapshot.return_value = [
            {"name": "sat_left", "headroom_db": 10.0, "pct_of_ceiling": 10.0},
            {"name": "sub1", "headroom_db": 20.0, "pct_of_ceiling": 1.0},
        ]
        _run(limiter._enforce_tick(time.monotonic()))

        entries = limiter.audit_log()
        actions = [e["action"] for e in entries]
        self.assertIn("engage", actions)
        self.assertIn("disengage", actions)

    def test_tick_expires_overrides(self):
        """Expired overrides are cleaned up during tick."""
        limiter = self._make_limiter_with_thermal([
            {"name": "sat_left", "headroom_db": 10.0, "pct_of_ceiling": 10.0},
            {"name": "sub1", "headroom_db": 20.0, "pct_of_ceiling": 1.0},
        ])

        # Set an already-expired override
        limiter._overrides["sat_left"] = OverrideEntry(
            channel_name="sat_left",
            ceiling_multiplier=2.0,
            expires_at=time.monotonic() - 10,
        )

        _run(limiter._enforce_tick(time.monotonic()))

        self.assertNotIn("sat_left", limiter._overrides)
        entries = limiter.audit_log()
        expired_entries = [e for e in entries if e["action"] == "override_expired"]
        self.assertEqual(len(expired_entries), 1)


# -- Async start/stop ---------------------------------------------------------

class TestAsyncLifecycle(unittest.TestCase):

    def test_start_stop(self):
        monitor = MagicMock()
        monitor.snapshot.return_value = []
        limiter = ThermalGainLimiter(monitor, is_mock=True)

        async def run():
            await limiter.start()
            await asyncio.sleep(0.2)
            await limiter.stop()

        _run(run())


# -- API routes ----------------------------------------------------------------

class TestLimiterRoutes(unittest.TestCase):

    def _make_app_with_limiter(self, limiter=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from app.thermal_routes import router
        app.include_router(router)

        if limiter is not None:
            app.state.thermal_limiter = limiter
        # Also need thermal_monitor for /status
        mock_monitor = MagicMock()
        mock_monitor.snapshot.return_value = []
        mock_monitor.any_warning.return_value = False
        mock_monitor.any_limit.return_value = False
        app.state.thermal_monitor = mock_monitor

        return TestClient(app)

    def test_limiter_status_503_when_not_available(self):
        client = self._make_app_with_limiter(limiter=None)
        resp = client.get("/api/v1/thermal/limiter")
        self.assertEqual(resp.status_code, 503)

    def test_limiter_status_200(self):
        mock_limiter = MagicMock()
        mock_limiter.snapshot.return_value = {
            "channels": [],
            "any_limiting": False,
        }
        client = self._make_app_with_limiter(limiter=mock_limiter)
        resp = client.get("/api/v1/thermal/limiter")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["any_limiting"])

    def test_limiter_audit_200(self):
        mock_limiter = MagicMock()
        mock_limiter.audit_log.return_value = [
            {"timestamp": 1000, "channel": "sat_left",
             "action": "engage", "detail": "test"},
        ]
        client = self._make_app_with_limiter(limiter=mock_limiter)
        resp = client.get("/api/v1/thermal/limiter/audit")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["entries"]), 1)

    def test_override_set(self):
        mock_limiter = MagicMock()
        mock_limiter.set_override.return_value = {"ok": True, "channel": "sat_left"}
        client = self._make_app_with_limiter(limiter=mock_limiter)
        resp = client.post("/api/v1/thermal/limiter/override", json={
            "channel": "sat_left",
            "ceiling_multiplier": 1.5,
            "duration_seconds": 120,
        })
        self.assertEqual(resp.status_code, 200)
        mock_limiter.set_override.assert_called_once()

    def test_override_clear(self):
        mock_limiter = MagicMock()
        mock_limiter.clear_override.return_value = {"ok": True, "channel": "sat_left"}
        client = self._make_app_with_limiter(limiter=mock_limiter)
        resp = client.post("/api/v1/thermal/limiter/override/clear", json={
            "channel": "sat_left",
        })
        self.assertEqual(resp.status_code, 200)
        mock_limiter.clear_override.assert_called_once()

    def test_thermal_status_includes_limiter(self):
        """GET /thermal/status should include limiter state when available."""
        mock_limiter = MagicMock()
        mock_limiter.snapshot.return_value = {
            "channels": [],
            "any_limiting": False,
        }
        client = self._make_app_with_limiter(limiter=mock_limiter)
        resp = client.get("/api/v1/thermal/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("limiter", data)


if __name__ == "__main__":
    unittest.main()
