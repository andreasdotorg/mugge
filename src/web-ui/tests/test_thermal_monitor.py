"""Tests for ThermalMonitor (T-092-2)."""

import asyncio
import concurrent.futures
import math
import time
import unittest
from unittest.mock import MagicMock


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

from app.collectors.thermal_monitor import (
    ChannelThermalState,
    ThermalMonitor,
    DEFAULT_TAU_SECONDS,
    WARNING_HEADROOM_DB,
    _DEFAULT_AMP_VOLTAGE_GAIN,
    _DEFAULT_ADA8200_0DBFS_VRMS,
)


class TestChannelThermalState(unittest.TestCase):
    """Tests for the per-channel thermal state tracking."""

    def _make_channel(self, **kwargs):
        defaults = {
            "name": "sat_left",
            "channel_index": 0,
            "identity": "test-driver",
            "pe_max_watts": 7.0,
            "impedance_ohm": 4.0,
            "sensitivity_db_spl": 87.0,
            "pw_gain_mult": 1.0,
            "tau_seconds": 10.0,
        }
        defaults.update(kwargs)
        return ChannelThermalState(**defaults)

    def test_rms_to_power_silent(self):
        """RMS at -120 dBFS should produce 0 watts."""
        ch = self._make_channel()
        self.assertEqual(ch._rms_to_power(-120.0), 0.0)
        self.assertEqual(ch._rms_to_power(-200.0), 0.0)

    def test_rms_to_power_zero_dbfs(self):
        """0 dBFS -> DAC at full output -> high power."""
        ch = self._make_channel(impedance_ohm=4.0)
        power = ch._rms_to_power(0.0)
        # V_dac = 4.9 Vrms, V_speaker = 4.9 * 42.4 = 207.76 V
        # P = 207.76^2 / 4 = 10791.2 W
        expected = (_DEFAULT_ADA8200_0DBFS_VRMS * _DEFAULT_AMP_VOLTAGE_GAIN) ** 2 / 4.0
        self.assertAlmostEqual(power, expected, places=0)

    def test_rms_to_power_minus_60(self):
        """At -60 dBFS the power should be very low."""
        ch = self._make_channel(impedance_ohm=4.0)
        power = ch._rms_to_power(-60.0)
        # V_dac = 4.9 * 10^(-60/20) = 4.9 * 0.001 = 0.0049 V
        # V_speaker = 0.0049 * 42.4 = 0.20776 V
        # P = 0.20776^2 / 4 = 0.01079 W
        self.assertAlmostEqual(power, 0.01079, places=4)

    def test_update_first_sample(self):
        """First update should initialize smoothed power directly."""
        ch = self._make_channel()
        ch.update(-60.0, 1.0)
        self.assertGreater(ch.smoothed_power_watts, 0)
        self.assertEqual(ch.last_update_time, 1.0)

    def test_update_exponential_decay(self):
        """Subsequent updates should apply exponential smoothing."""
        ch = self._make_channel(tau_seconds=1.0)

        # Initialize with some power
        ch.update(-30.0, 0.0)
        initial_power = ch.smoothed_power_watts
        self.assertGreater(initial_power, 0)

        # Feed silence for 5 tau — should decay to near zero
        for i in range(50):
            ch.update(-120.0, 0.1 * (i + 1))
        self.assertLess(ch.smoothed_power_watts, initial_power * 0.01)

    def test_update_convergence(self):
        """Sustained signal should converge smoothed power to steady state."""
        ch = self._make_channel(tau_seconds=1.0)
        target_dbfs = -40.0
        target_power = ch._rms_to_power(target_dbfs)

        # Feed constant signal for 10 tau
        for i in range(100):
            ch.update(target_dbfs, 0.1 * i)

        # Should be very close to steady-state power
        self.assertAlmostEqual(
            ch.smoothed_power_watts, target_power, places=4)

    def test_headroom_db_with_pe_max(self):
        """Headroom should be positive when power is below ceiling."""
        ch = self._make_channel(pe_max_watts=7.0)
        ch.smoothed_power_watts = 0.7  # 10% of ceiling
        hr = ch.headroom_db()
        # 10 * log10(7 / 0.7) = 10 dB
        self.assertAlmostEqual(hr, 10.0, places=1)

    def test_headroom_db_none_when_no_pe_max(self):
        """Headroom should be None when pe_max_watts is None."""
        ch = self._make_channel(pe_max_watts=None)
        ch.smoothed_power_watts = 1.0
        self.assertIsNone(ch.headroom_db())

    def test_headroom_db_none_when_zero_power(self):
        """Headroom should be None when smoothed power is zero."""
        ch = self._make_channel(pe_max_watts=7.0)
        ch.smoothed_power_watts = 0.0
        self.assertIsNone(ch.headroom_db())

    def test_pct_of_ceiling(self):
        ch = self._make_channel(pe_max_watts=7.0)
        ch.smoothed_power_watts = 3.5
        self.assertAlmostEqual(ch.pct_of_ceiling(), 50.0)

    def test_pct_of_ceiling_no_pe_max(self):
        ch = self._make_channel(pe_max_watts=None)
        ch.smoothed_power_watts = 10.0
        self.assertEqual(ch.pct_of_ceiling(), 0.0)

    def test_status_ok(self):
        ch = self._make_channel(pe_max_watts=7.0)
        ch.smoothed_power_watts = 0.01  # Very low
        self.assertEqual(ch.status(), "ok")

    def test_status_warning(self):
        """Status should be 'warning' when within 3 dB of ceiling."""
        ch = self._make_channel(pe_max_watts=7.0)
        # 2 dB below ceiling: P = 7 / 10^(2/10) = 7 / 1.585 = 4.42
        ch.smoothed_power_watts = 4.42
        self.assertEqual(ch.status(), "warning")

    def test_status_limit(self):
        """Status should be 'limit' when at or above ceiling."""
        ch = self._make_channel(pe_max_watts=7.0)
        ch.smoothed_power_watts = 7.0
        self.assertEqual(ch.status(), "limit")

        ch.smoothed_power_watts = 10.0
        self.assertEqual(ch.status(), "limit")

    def test_status_ok_no_pe_max(self):
        """Status should be 'ok' when no pe_max data available."""
        ch = self._make_channel(pe_max_watts=None)
        ch.smoothed_power_watts = 999.0
        self.assertEqual(ch.status(), "ok")

    def test_to_dict(self):
        ch = self._make_channel(pe_max_watts=7.0)
        ch.smoothed_power_watts = 1.0
        d = ch.to_dict()
        self.assertEqual(d["name"], "sat_left")
        self.assertEqual(d["channel"], 0)
        self.assertEqual(d["ceiling_watts"], 7.0)
        self.assertIsInstance(d["headroom_db"], float)
        self.assertIsInstance(d["pct_of_ceiling"], float)
        self.assertEqual(d["status"], "ok")


class TestThermalMonitor(unittest.TestCase):
    """Tests for the ThermalMonitor service."""

    def _make_mock_levels(self, rms_values=None):
        """Create a mock LevelsCollector that returns fixed RMS values."""
        mock = MagicMock()
        if rms_values is None:
            rms_values = [-120.0] * 8
        mock.rms.return_value = rms_values
        return mock

    def _make_channels(self, n=4):
        channels = []
        for i in range(n):
            channels.append(ChannelThermalState(
                name=f"ch{i}",
                channel_index=i,
                pe_max_watts=7.0 if i < 2 else 62.0,
                impedance_ohm=4.0 if i < 2 else 2.33,
                tau_seconds=1.0,
            ))
        return channels

    def test_init_with_channels(self):
        levels = self._make_mock_levels()
        channels = self._make_channels(4)
        monitor = ThermalMonitor(levels, channels=channels, tau_seconds=2.0)
        snap = monitor.snapshot()
        self.assertEqual(len(snap), 4)
        self.assertEqual(snap[0]["name"], "ch0")

    def test_configure_channels(self):
        levels = self._make_mock_levels()
        monitor = ThermalMonitor(levels)
        self.assertEqual(len(monitor.snapshot()), 0)

        channels = self._make_channels(2)
        monitor.configure_channels(channels)
        self.assertEqual(len(monitor.snapshot()), 2)

    def test_configure_from_ceilings(self):
        """Configure from thermal_ceiling.load_channel_ceilings() output format."""
        levels = self._make_mock_levels()
        monitor = ThermalMonitor(levels)

        ceilings = {
            "sat_left": {
                "channel": 0,
                "ceiling_dbfs": -20.0,
                "identity": "chn50p",
                "pe_max_watts": 7,
                "impedance_ohm": 4,
                "sensitivity_db_spl": 87.5,
                "pw_gain_mult": 0.001,
                "pw_gain_db": -60.0,
            },
            "sub1": {
                "channel": 2,
                "ceiling_dbfs": -20.0,
                "identity": "ps28",
                "pe_max_watts": 62,
                "impedance_ohm": 2.33,
                "sensitivity_db_spl": 85.0,
                "pw_gain_mult": 0.000631,
                "pw_gain_db": -64.0,
            },
        }
        monitor.configure_from_ceilings(ceilings)
        snap = monitor.snapshot()
        self.assertEqual(len(snap), 2)
        self.assertEqual(snap[0]["name"], "sat_left")
        self.assertEqual(snap[0]["ceiling_watts"], 7)
        self.assertEqual(snap[1]["name"], "sub1")
        self.assertEqual(snap[1]["ceiling_watts"], 62)

    def test_snapshot_sorted_by_channel(self):
        levels = self._make_mock_levels()
        channels = [
            ChannelThermalState(name="sub1", channel_index=2, pe_max_watts=62),
            ChannelThermalState(name="sat_left", channel_index=0, pe_max_watts=7),
        ]
        monitor = ThermalMonitor(levels, channels=channels)
        snap = monitor.snapshot()
        self.assertEqual(snap[0]["channel"], 0)
        self.assertEqual(snap[1]["channel"], 2)

    def test_channel_state(self):
        levels = self._make_mock_levels()
        channels = self._make_channels(2)
        monitor = ThermalMonitor(levels, channels=channels)
        state = monitor.channel_state(0)
        self.assertIsNotNone(state)
        self.assertEqual(state["name"], "ch0")
        self.assertIsNone(monitor.channel_state(99))

    def test_any_warning_false_initially(self):
        levels = self._make_mock_levels()
        channels = self._make_channels(2)
        monitor = ThermalMonitor(levels, channels=channels)
        self.assertFalse(monitor.any_warning())
        self.assertFalse(monitor.any_limit())

    def test_any_warning_true(self):
        levels = self._make_mock_levels()
        channels = self._make_channels(2)
        monitor = ThermalMonitor(levels, channels=channels)
        # Force a channel into warning state
        monitor._channels[0].smoothed_power_watts = 5.0  # >50% of 7W
        self.assertTrue(monitor.any_warning())
        self.assertFalse(monitor.any_limit())

    def test_any_limit_true(self):
        levels = self._make_mock_levels()
        channels = self._make_channels(2)
        monitor = ThermalMonitor(levels, channels=channels)
        monitor._channels[0].smoothed_power_watts = 8.0  # >7W ceiling
        self.assertTrue(monitor.any_warning())
        self.assertTrue(monitor.any_limit())


class TestThermalMonitorAsync(unittest.TestCase):
    """Async tests for ThermalMonitor loop."""

    def test_monitor_loop_updates_channels(self):
        """The monitor loop should read RMS and update thermal state."""
        # Feed -40 dBFS on all channels
        rms_values = [-40.0] * 8
        levels = MagicMock()
        levels.rms.return_value = rms_values

        channels = [
            ChannelThermalState(
                name="sat_left", channel_index=0,
                pe_max_watts=7.0, impedance_ohm=4.0,
                tau_seconds=0.1),
        ]
        monitor = ThermalMonitor(levels, channels=channels, tau_seconds=0.1)

        async def run():
            await monitor.start()
            # Let it run a few cycles
            await asyncio.sleep(0.5)
            await monitor.stop()
            return monitor.snapshot()

        snap = _run(run())
        # Channel should have accumulated some power
        self.assertGreater(snap[0]["power_watts"], 0)

    def test_monitor_start_stop(self):
        """Monitor should start and stop cleanly."""
        levels = MagicMock()
        levels.rms.return_value = [-120.0] * 8
        monitor = ThermalMonitor(levels)

        async def run():
            await monitor.start()
            await asyncio.sleep(0.1)
            await monitor.stop()

        _run(run())


class TestThermalRoutes(unittest.TestCase):
    """Tests for the thermal API endpoint."""

    def test_thermal_status_no_monitor(self):
        """Should return 503 when thermal monitor is not available."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()
        from app.thermal_routes import router
        app.include_router(router)

        client = TestClient(app)
        resp = client.get("/api/v1/thermal/status")
        self.assertEqual(resp.status_code, 503)

    def test_thermal_status_with_monitor(self):
        """Should return thermal state when monitor is available."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()
        from app.thermal_routes import router
        app.include_router(router)

        # Create mock monitor
        mock_monitor = MagicMock()
        mock_monitor.snapshot.return_value = [
            {"name": "sat_left", "channel": 0, "power_watts": 0.1,
             "ceiling_watts": 7, "headroom_db": 18.5, "pct_of_ceiling": 1.4,
             "status": "ok", "impedance_ohm": 4, "sensitivity_db_spl": 87.5},
        ]
        mock_monitor.any_warning.return_value = False
        mock_monitor.any_limit.return_value = False

        app.state.thermal_monitor = mock_monitor

        client = TestClient(app)
        resp = client.get("/api/v1/thermal/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["channels"]), 1)
        self.assertFalse(data["any_warning"])
        self.assertFalse(data["any_limit"])
        self.assertEqual(data["channels"][0]["name"], "sat_left")


if __name__ == "__main__":
    unittest.main()
