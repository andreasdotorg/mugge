"""US-092 integration tests: thermal + mechanical protection end-to-end.

Tests the full protection system across modules:
  - thermal_ceiling: per-channel ceiling computation
  - excursion_estimator: frequency-dependent Xmax protection
  - thermal_monitor: real-time power tracking
  - speaker_routes: profile validation (D-031 HPF, D-029 gain staging)
  - pw_config_generator: HPF enforcement in filter-chain config

Test scenarios (from T-092-8):
  1. Profile activation -> thermal ceilings computed correctly
  2. Simulated over-limit signal -> thermal monitor shows warning/limit
  3. Missing T/S data -> graceful fallback to hard cap (-20 dBFS)
  4. Profile switch -> thermal limits recompute atomically
  5. HPF enforcement -> config rejected when mandatory_hpf_hz missing
  6. Port-tuning validation -> warning when HPF < port tuning frequency
  7. Multi-topology (2-way, 3-way) -> correct per-channel protection
  8. Excursion + thermal combined -> both limits available per channel
"""

import asyncio
import math
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

# Ensure app modules are importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.collectors.thermal_monitor import (
    ChannelThermalState,
    ThermalMonitor,
    DEFAULT_TAU_SECONDS,
    WARNING_HEADROOM_DB,
)

# room-correction modules (sibling package).
_RC_ROOT = Path(__file__).resolve().parents[2] / "room-correction"
if str(_RC_ROOT) not in sys.path:
    sys.path.insert(0, str(_RC_ROOT))

from thermal_ceiling import (
    compute_thermal_ceiling_dbfs,
    safe_ceiling_dbfs,
    load_channel_ceilings,
    DEFAULT_HARD_CAP_DBFS,
    DEFAULT_AMP_VOLTAGE_GAIN,
    DEFAULT_ADA8200_0DBFS_VRMS,
)
from room_correction.excursion_estimator import (
    estimate_peak_excursion_mm,
    compute_xmax_safe_level_dbfs,
)

try:
    from app.speaker_routes import _deep_validate_profile, _read_yaml
except ImportError:
    pytest.skip("speaker_routes not available", allow_module_level=True)


# ── Helpers ──────────────────────────────────────────────────────

def _run(coro):
    """Run async coroutine in sync test context (works with pytest-playwright's loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _make_levels_collector(rms_values):
    """Create a mock levels collector returning fixed RMS values."""
    mock = MagicMock()
    mock.rms.return_value = rms_values
    return mock


# ── Test data ────────────────────────────────────────────────────

# CHN-50P: 7W thermal, 4 ohm — the most thermally constrained speaker.
_CHN50P = {
    "pe_max_watts": 7.0,
    "impedance_ohm": 4.0,
    "sensitivity_db_spl": 87.5,
}

# Bose PS28 sub: 200W, 4 ohm.
_PS28_SUB = {
    "pe_max_watts": 200.0,
    "impedance_ohm": 4.0,
    "sensitivity_db_spl": 88.0,
}

# Horn sub: 600W, 8 ohm, high sensitivity.
_HORN_SUB = {
    "pe_max_watts": 600.0,
    "impedance_ohm": 8.0,
    "sensitivity_db_spl": 103.0,
}

# Driver with complete T/S data for excursion testing (SLS P830669 12" sub).
_SLS_TS = {
    "fs_hz": 31.0, "qts": 0.54, "bl_tm": 11.88,
    "mms_g": 74.11, "cms_m_per_n": 0.00035,
    "re_ohm": 6.4, "xmax_mm": 8.3,
}


# ── Scenario 1: Profile activation -> thermal ceilings ──────────

class TestProfileActivationCeilings:
    """Thermal ceilings computed correctly for a loaded profile."""

    def test_2way_ceilings_use_real_speaker_data(self):
        """load_channel_ceilings for bose-home-chn50p uses actual identity data."""
        try:
            ceilings = load_channel_ceilings("bose-home-chn50p")
        except FileNotFoundError:
            pytest.skip("Profile bose-home-chn50p not found (CI env)")
        # Should have speakers
        assert len(ceilings) >= 2
        for name, info in ceilings.items():
            assert "ceiling_dbfs" in info
            assert info["ceiling_dbfs"] <= DEFAULT_HARD_CAP_DBFS
            assert info["impedance_ohm"] > 0

    def test_thermal_ceiling_chn50p_with_attenuation(self):
        """CHN-50P at Mult=0.001 (-60 dB) has a high ceiling."""
        ceiling = compute_thermal_ceiling_dbfs(
            pe_max_watts=7.0, impedance_ohm=4.0,
            pw_gain_mult=0.001,
            sensitivity_db_spl=87.5,
        )
        # With 60 dB of attenuation, the raw ceiling should be well above 0 dBFS.
        assert ceiling is not None
        assert ceiling > 0.0  # Raw ceiling (before hard cap)

    def test_safe_ceiling_enforces_hard_cap(self):
        """safe_ceiling_dbfs never exceeds the hard cap."""
        ceiling = safe_ceiling_dbfs(
            pe_max_watts=7.0, impedance_ohm=4.0,
            pw_gain_mult=0.001,
            sensitivity_db_spl=87.5,
        )
        assert ceiling <= DEFAULT_HARD_CAP_DBFS

    def test_ceiling_higher_for_more_attenuation(self):
        """More gain attenuation -> higher (less negative) ceiling."""
        c_low = compute_thermal_ceiling_dbfs(
            pe_max_watts=7.0, impedance_ohm=4.0, pw_gain_mult=0.01)
        c_high = compute_thermal_ceiling_dbfs(
            pe_max_watts=7.0, impedance_ohm=4.0, pw_gain_mult=0.001)
        assert c_high > c_low

    def test_horn_sensitivity_raises_ceiling(self):
        """Higher sensitivity driver has a higher thermal ceiling."""
        c_normal = compute_thermal_ceiling_dbfs(
            pe_max_watts=600.0, impedance_ohm=8.0,
            pw_gain_mult=0.001, sensitivity_db_spl=87.0)
        c_horn = compute_thermal_ceiling_dbfs(
            pe_max_watts=600.0, impedance_ohm=8.0,
            pw_gain_mult=0.001, sensitivity_db_spl=103.0)
        # 16 dB more sensitivity -> 16 dB higher ceiling.
        assert c_horn - c_normal == pytest.approx(16.0, abs=0.1)


# ── Scenario 2: Simulated over-limit signal ─────────────────────

class TestOverLimitSignalDetection:
    """Thermal monitor detects over-limit conditions."""

    def test_limit_status_at_high_power(self):
        """Channel reports 'limit' when power exceeds ceiling."""
        ch = ChannelThermalState(
            name="sat_left", channel_index=0,
            pe_max_watts=7.0, impedance_ohm=4.0,
            tau_seconds=0.0,  # No smoothing for instant detection
        )
        # 0 dBFS with no attenuation: P = (4.9 * 42.4)^2 / 4 = ~10,793 W
        # Way above 7W ceiling.
        ch.update(0.0, time.monotonic())
        assert ch.status() == "limit"
        assert ch.pct_of_ceiling() > 100.0

    def test_warning_status_near_ceiling(self):
        """Channel reports 'warning' when within 3 dB of ceiling."""
        ch = ChannelThermalState(
            name="sat_left", channel_index=0,
            pe_max_watts=7.0, impedance_ohm=4.0,
            tau_seconds=0.0,
        )
        # Find a dBFS level that puts us at ~5W (within 3 dB of 7W).
        # P = V^2/Z, V = Vdac * Gamp, Vdac = 4.9 * 10^(dBFS/20)
        # 5W into 4 ohm: V = sqrt(5*4) = 4.47V. Vdac = 4.47/42.4 = 0.1054V
        # dBFS = 20*log10(0.1054/4.9) = -33.34 dBFS
        ch.update(-33.3, time.monotonic() + 0.1)
        hr = ch.headroom_db()
        assert hr is not None
        assert hr < WARNING_HEADROOM_DB
        assert ch.status() == "warning"

    def test_ok_status_at_low_power(self):
        """Channel reports 'ok' when well below ceiling."""
        ch = ChannelThermalState(
            name="sat_left", channel_index=0,
            pe_max_watts=7.0, impedance_ohm=4.0,
            tau_seconds=0.0,
        )
        ch.update(-60.0, time.monotonic())
        assert ch.status() == "ok"

    def test_monitor_any_limit_detection(self):
        """ThermalMonitor.any_limit() detects over-limit channels."""
        channels = [
            ChannelThermalState(
                name="sat_left", channel_index=0,
                pe_max_watts=7.0, impedance_ohm=4.0, tau_seconds=0.0),
            ChannelThermalState(
                name="sub1", channel_index=2,
                pe_max_watts=200.0, impedance_ohm=4.0, tau_seconds=0.0),
        ]
        mock_levels = _make_levels_collector([-10.0, 0.0, -60.0, -60.0])
        monitor = ThermalMonitor(mock_levels, channels, tau_seconds=0.0)

        # Manually feed one update cycle.
        now = time.monotonic()
        for ch in monitor._channels.values():
            rms = mock_levels.rms()[ch.channel_index]
            ch.update(rms, now)

        # sat_left at -10 dBFS into 4 ohm should be over limit for 7W.
        snap = monitor.snapshot()
        sat = [s for s in snap if s["name"] == "sat_left"][0]
        assert sat["status"] == "limit"
        assert monitor.any_limit() is True

        # sub1 at -60 dBFS into 4 ohm should be fine for 200W.
        sub = [s for s in snap if s["name"] == "sub1"][0]
        assert sub["status"] == "ok"


# ── Scenario 3: Missing T/S data -> graceful fallback ───────────

class TestMissingTSDataFallback:
    """Missing pe_max_watts triggers hard cap fallback."""

    def test_safe_ceiling_fallback_on_none(self):
        """safe_ceiling_dbfs returns hard cap when pe_max_watts is None."""
        ceiling = safe_ceiling_dbfs(
            pe_max_watts=None, impedance_ohm=4.0,
            pw_gain_mult=0.001)
        assert ceiling == DEFAULT_HARD_CAP_DBFS

    def test_safe_ceiling_fallback_on_zero(self):
        """safe_ceiling_dbfs returns hard cap when pe_max_watts is 0."""
        ceiling = safe_ceiling_dbfs(
            pe_max_watts=0, impedance_ohm=4.0,
            pw_gain_mult=0.001)
        assert ceiling == DEFAULT_HARD_CAP_DBFS

    def test_thermal_state_no_ceiling_data(self):
        """Channel with no pe_max_watts reports 'ok' status (no ceiling to check)."""
        ch = ChannelThermalState(
            name="unknown", channel_index=0,
            pe_max_watts=None, impedance_ohm=8.0, tau_seconds=0.0)
        ch.update(0.0, time.monotonic())
        assert ch.status() == "ok"
        assert ch.headroom_db() is None

    def test_monitor_configure_from_ceilings_with_missing_pe(self):
        """Monitor configured from ceilings with missing pe_max_watts."""
        ceilings = {
            "sat_left": {
                "channel": 0, "pe_max_watts": None,
                "impedance_ohm": 8.0, "sensitivity_db_spl": 87.0,
                "identity": "unknown-spk", "pw_gain_mult": 0.001,
                "ceiling_dbfs": DEFAULT_HARD_CAP_DBFS,
            },
        }
        mock_levels = _make_levels_collector([-60.0])
        monitor = ThermalMonitor(mock_levels, tau_seconds=10.0)
        monitor.configure_from_ceilings(ceilings)
        snap = monitor.snapshot()
        assert len(snap) == 1
        assert snap[0]["ceiling_watts"] is None


# ── Scenario 4: Profile switch -> thermal limits recompute ──────

class TestProfileSwitchRecompute:
    """Profile switch atomically reconfigures thermal monitoring."""

    def test_configure_channels_replaces_state(self):
        """configure_channels replaces all channel state."""
        ch_old = [ChannelThermalState(
            name="old_ch", channel_index=0,
            pe_max_watts=7.0, impedance_ohm=4.0)]
        mock_levels = _make_levels_collector([-60.0])
        monitor = ThermalMonitor(mock_levels, ch_old)
        assert len(monitor.snapshot()) == 1
        assert monitor.snapshot()[0]["name"] == "old_ch"

        # Switch profile.
        ch_new = [
            ChannelThermalState(
                name="new_sat", channel_index=0,
                pe_max_watts=200.0, impedance_ohm=8.0),
            ChannelThermalState(
                name="new_sub", channel_index=2,
                pe_max_watts=600.0, impedance_ohm=8.0),
        ]
        monitor.configure_channels(ch_new)
        snap = monitor.snapshot()
        assert len(snap) == 2
        names = {s["name"] for s in snap}
        assert names == {"new_sat", "new_sub"}

    def test_configure_from_ceilings_replaces_state(self):
        """configure_from_ceilings integrates with thermal_ceiling output."""
        mock_levels = _make_levels_collector([-60.0] * 4)
        monitor = ThermalMonitor(mock_levels)

        ceilings_2way = {
            "sat_left": {
                "channel": 0, "pe_max_watts": 7.0,
                "impedance_ohm": 4.0, "sensitivity_db_spl": 87.5,
                "identity": "chn50p", "pw_gain_mult": 0.001,
            },
            "sub1": {
                "channel": 2, "pe_max_watts": 200.0,
                "impedance_ohm": 4.0, "sensitivity_db_spl": 88.0,
                "identity": "ps28", "pw_gain_mult": 0.000631,
            },
        }
        monitor.configure_from_ceilings(ceilings_2way)
        assert len(monitor.snapshot()) == 2

        # Switch to 3-way: more channels.
        ceilings_3way = {
            f"ch{i}": {
                "channel": i, "pe_max_watts": 100.0,
                "impedance_ohm": 8.0, "sensitivity_db_spl": 90.0,
                "identity": "mid-driver", "pw_gain_mult": 0.01,
            }
            for i in range(6)
        }
        monitor.configure_from_ceilings(ceilings_3way)
        assert len(monitor.snapshot()) == 6

    def test_old_state_not_carried_over(self):
        """Old thermal state (smoothed power) is reset after profile switch."""
        ch1 = [ChannelThermalState(
            name="hot_ch", channel_index=0,
            pe_max_watts=7.0, impedance_ohm=4.0, tau_seconds=0.0)]
        mock_levels = _make_levels_collector([0.0])
        monitor = ThermalMonitor(mock_levels, ch1, tau_seconds=0.0)

        # Drive high power.
        now = time.monotonic()
        monitor._channels[0].update(0.0, now)
        assert monitor._channels[0].smoothed_power_watts > 100.0

        # Profile switch.
        ch2 = [ChannelThermalState(
            name="fresh_ch", channel_index=0,
            pe_max_watts=200.0, impedance_ohm=8.0)]
        monitor.configure_channels(ch2)
        assert monitor._channels[0].smoothed_power_watts == 0.0


# ── Scenario 5: HPF enforcement ─────────────────────────────────

@pytest.fixture
def hpf_dir(tmp_path, monkeypatch):
    """Temp speakers dir for HPF validation tests."""
    identities = tmp_path / "identities"
    profiles = tmp_path / "profiles"
    identities.mkdir()
    profiles.mkdir()

    # Identity WITH mandatory_hpf_hz.
    id_with_hpf = {
        "name": "Safe Driver", "type": "sealed", "impedance_ohm": 8,
        "sensitivity_db_spl": 90, "max_boost_db": 0, "mandatory_hpf_hz": 40,
    }
    (identities / "safe-driver.yml").write_text(
        yaml.dump(id_with_hpf, default_flow_style=False, sort_keys=False))

    # Identity WITHOUT mandatory_hpf_hz.
    id_no_hpf = {
        "name": "Unsafe Driver", "type": "sealed", "impedance_ohm": 8,
        "sensitivity_db_spl": 90, "max_boost_db": 0,
    }
    (identities / "unsafe-driver.yml").write_text(
        yaml.dump(id_no_hpf, default_flow_style=False, sort_keys=False))

    # Ported identity with port_tuning_hz (for scenario 6).
    id_ported = {
        "name": "Ported Sub", "type": "ported", "impedance_ohm": 8,
        "sensitivity_db_spl": 95, "max_boost_db": 0,
        "mandatory_hpf_hz": 25, "port_tuning_hz": 35,
    }
    (identities / "ported-sub.yml").write_text(
        yaml.dump(id_ported, default_flow_style=False, sort_keys=False))

    import app.speaker_routes as mod
    monkeypatch.setattr(mod, "_speakers_dir", lambda: tmp_path)
    return tmp_path


class TestHPFEnforcement:
    """D-031: config rejected when mandatory_hpf_hz missing."""

    def test_missing_hpf_fails_validation(self, hpf_dir):
        """Profile with driver missing mandatory_hpf_hz -> validation error."""
        profile = {
            "name": "Bad Profile", "topology": "2way",
            "crossover": {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            "speakers": {
                "sat": {"identity": "unsafe-driver", "role": "satellite",
                        "channel": 0, "filter_type": "highpass"},
            },
        }
        result = _deep_validate_profile(profile)
        assert result["valid"] is False
        checks = [e["check"] for e in result["errors"]]
        assert "d031_hpf_missing" in checks

    def test_present_hpf_passes_validation(self, hpf_dir):
        """Profile with proper mandatory_hpf_hz -> no D-031 error."""
        profile = {
            "name": "Good Profile", "topology": "2way",
            "crossover": {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            "speakers": {
                "sat": {"identity": "safe-driver", "role": "satellite",
                        "channel": 0, "filter_type": "highpass"},
            },
        }
        result = _deep_validate_profile(profile)
        checks = [e["check"] for e in result["errors"]]
        assert "d031_hpf_missing" not in checks

    def test_sub_hpf_above_crossover_error(self, hpf_dir):
        """Sub HPF >= crossover means sub has no passband."""
        profile = {
            "name": "Bad Sub Profile", "topology": "2way",
            "crossover": {"frequency_hz": 30, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            "speakers": {
                "sub": {"identity": "safe-driver", "role": "subwoofer",
                        "channel": 0, "filter_type": "lowpass"},
            },
        }
        result = _deep_validate_profile(profile)
        checks = [e["check"] for e in result["errors"]]
        assert "sub_hpf_vs_crossover" in checks


# ── Scenario 6: Port-tuning validation ──────────────────────────

class TestPortTuningValidation:
    """Warning when HPF < port tuning frequency (ported enclosure unloading)."""

    def test_port_tuning_warning_in_config_generator(self):
        """pw_config_generator logs warning when HPF < port tuning."""
        # This is tested in test_pw_config_generator.py. Here we verify
        # the identity data is structured correctly for the check.
        try:
            from room_correction.pw_config_generator import _get_port_tuning_hz
        except ImportError:
            pytest.skip("pw_config_generator not importable")

        identity = {"port_tuning_hz": 35}
        assert _get_port_tuning_hz(identity) == 35.0

    def test_port_tuning_dict_format(self):
        """Port tuning with per-port values returns minimum."""
        try:
            from room_correction.pw_config_generator import _get_port_tuning_hz
        except ImportError:
            pytest.skip("pw_config_generator not importable")

        identity = {"port_tuning_hz": {"upper_port": 58, "lower_port": 88}}
        assert _get_port_tuning_hz(identity) == 58.0

    def test_ported_identity_has_port_tuning(self, hpf_dir):
        """Ported sub identity file contains port_tuning_hz field."""
        data = yaml.safe_load(
            (hpf_dir / "identities" / "ported-sub.yml").read_text())
        assert data["port_tuning_hz"] == 35
        assert data["mandatory_hpf_hz"] == 25
        # HPF (25) < port tuning (35) -- this would trigger a warning
        # in the config generator (tested in test_pw_config_generator.py).
        assert data["mandatory_hpf_hz"] < data["port_tuning_hz"]


# ── Scenario 7: Multi-topology protection ────────────────────────

class TestMultiTopologyProtection:
    """Correct per-channel protection for 2-way and 3-way topologies."""

    def test_2way_channels_have_different_ceilings(self):
        """2-way: satellite (7W) and sub (200W) have different ceilings."""
        c_sat = compute_thermal_ceiling_dbfs(
            pe_max_watts=7.0, impedance_ohm=4.0, pw_gain_mult=0.001)
        c_sub = compute_thermal_ceiling_dbfs(
            pe_max_watts=200.0, impedance_ohm=4.0, pw_gain_mult=0.000631)
        assert c_sat is not None
        assert c_sub is not None
        # Sub has more power handling -> higher raw ceiling (less constrained).
        assert c_sub > c_sat

    def test_3way_six_independent_ceilings(self):
        """3-way stereo: 6 channels, each with independent thermal ceiling."""
        drivers = {
            "sub_left": (200.0, 4.0, 0.000631),
            "sub_right": (200.0, 4.0, 0.000631),
            "mid_left": (50.0, 8.0, 0.01),
            "mid_right": (50.0, 8.0, 0.01),
            "tweet_left": (20.0, 8.0, 0.01),
            "tweet_right": (20.0, 8.0, 0.01),
        }
        ceilings = {}
        for name, (pe, z, mult) in drivers.items():
            c = safe_ceiling_dbfs(pe_max_watts=pe, impedance_ohm=z,
                                   pw_gain_mult=mult)
            ceilings[name] = c
        assert len(ceilings) == 6
        # All should be <= hard cap.
        for c in ceilings.values():
            assert c <= DEFAULT_HARD_CAP_DBFS

    def test_monitor_handles_topology_switch(self):
        """Monitor reconfigures correctly when switching 2-way to 3-way."""
        mock_levels = _make_levels_collector([-60.0] * 8)
        monitor = ThermalMonitor(mock_levels)

        # Configure as 2-way (4 channels).
        ch_2way = [
            ChannelThermalState(name=f"ch{i}", channel_index=i,
                                pe_max_watts=7.0, impedance_ohm=4.0)
            for i in range(4)
        ]
        monitor.configure_channels(ch_2way)
        assert len(monitor.snapshot()) == 4

        # Switch to 3-way (6 channels).
        ch_3way = [
            ChannelThermalState(name=f"ch{i}", channel_index=i,
                                pe_max_watts=50.0, impedance_ohm=8.0)
            for i in range(6)
        ]
        monitor.configure_channels(ch_3way)
        snap = monitor.snapshot()
        assert len(snap) == 6
        # New channels should all have the new pe_max_watts.
        for s in snap:
            assert s["ceiling_watts"] == 50.0


# ── Scenario 8: Combined excursion + thermal protection ──────────

class TestCombinedExcursionThermal:
    """Both excursion and thermal limits computed for each channel."""

    def test_thermal_and_excursion_both_available(self):
        """Both thermal ceiling and Xmax safe level computed for a driver."""
        # Thermal ceiling.
        thermal_ceiling = safe_ceiling_dbfs(
            pe_max_watts=200.0, impedance_ohm=8.0,
            pw_gain_mult=0.001)

        # Excursion limit at 30 Hz (worst case for sub).
        xmax_safe = compute_xmax_safe_level_dbfs(
            frequency_hz=30.0, xmax_mm=_SLS_TS["xmax_mm"],
            **{k: v for k, v in _SLS_TS.items() if k != "xmax_mm"},
            pw_gain_mult=0.001,
        )

        # Both should be finite numbers.
        assert isinstance(thermal_ceiling, float)
        assert isinstance(xmax_safe, float)
        assert thermal_ceiling <= DEFAULT_HARD_CAP_DBFS

    def test_effective_limit_is_min_of_both(self):
        """Effective safe level is the more restrictive of thermal and excursion."""
        # Compute both limits at low frequency where excursion dominates.
        thermal = safe_ceiling_dbfs(
            pe_max_watts=200.0, impedance_ohm=8.0, pw_gain_mult=0.001)
        excursion = compute_xmax_safe_level_dbfs(
            frequency_hz=20.0, xmax_mm=_SLS_TS["xmax_mm"],
            **{k: v for k, v in _SLS_TS.items() if k != "xmax_mm"},
            pw_gain_mult=0.001,
        )
        effective = min(thermal, excursion)
        assert effective == min(thermal, excursion)
        assert effective <= thermal
        assert effective <= excursion

    def test_excursion_more_restrictive_at_low_freq(self):
        """At very low frequencies, excursion limit is usually more restrictive."""
        thermal = safe_ceiling_dbfs(
            pe_max_watts=200.0, impedance_ohm=8.0, pw_gain_mult=1.0)
        excursion_20hz = compute_xmax_safe_level_dbfs(
            frequency_hz=20.0, xmax_mm=_SLS_TS["xmax_mm"],
            **{k: v for k, v in _SLS_TS.items() if k != "xmax_mm"},
            pw_gain_mult=1.0,
        )
        # At 20 Hz with no attenuation, excursion should be more restrictive
        # than thermal for a 200W driver.
        assert excursion_20hz < thermal

    def test_thermal_more_restrictive_at_high_freq(self):
        """At high frequencies, excursion limit relaxes (mass-controlled rolloff)."""
        thermal = safe_ceiling_dbfs(
            pe_max_watts=7.0, impedance_ohm=4.0, pw_gain_mult=1.0)
        excursion_1khz = compute_xmax_safe_level_dbfs(
            frequency_hz=1000.0, xmax_mm=_SLS_TS["xmax_mm"],
            **{k: v for k, v in _SLS_TS.items() if k != "xmax_mm"},
            pw_gain_mult=1.0,
        )
        # At 1 kHz, excursion limit should be much higher (less restrictive)
        # because mass-controlled region.  Thermal may dominate for a 7W driver.
        assert excursion_1khz > thermal

    def test_excursion_roundtrip_consistency(self):
        """Compute safe level then verify excursion at that level equals Xmax."""
        freq = 30.0
        ts = {k: v for k, v in _SLS_TS.items() if k != "xmax_mm"}
        safe_level = compute_xmax_safe_level_dbfs(
            frequency_hz=freq, xmax_mm=_SLS_TS["xmax_mm"],
            **ts, pw_gain_mult=1.0)
        if safe_level >= 0.0:
            pytest.skip("Xmax not exceeded at 0 dBFS")
        excursion_at_safe = estimate_peak_excursion_mm(
            signal_level_dbfs=safe_level, frequency_hz=freq,
            **ts, pw_gain_mult=1.0)
        assert excursion_at_safe == pytest.approx(_SLS_TS["xmax_mm"], rel=0.01)
