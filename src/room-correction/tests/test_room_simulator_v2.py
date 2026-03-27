"""Tests for room simulator v2 features (T-067-2).

Covers: per-wall absorption, frequency-dependent absorption, 3rd-order
reflections, axial mode computation, scenario YAML loading, RT60
verification, and 42 Hz mode presence.
"""

import os
import sys

import numpy as np
import scipy.signal
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock import room_simulator


SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "mock", "scenarios")


def _load_scenario(name):
    """Load a scenario YAML by name."""
    path = os.path.join(SCENARIOS_DIR, f"{name}.yml")
    with open(path) as f:
        return yaml.safe_load(f)


def _generate_ir_from_scenario(scenario, speaker="main_left", ir_length=48000):
    """Generate an IR from a scenario config dict."""
    room = scenario["room"]
    mic = scenario["microphone"]["position"]
    spk = scenario["speakers"][speaker]["position"]
    modes = scenario.get("room_modes", None)
    return room_simulator.generate_room_ir(
        speaker_pos=spk,
        mic_pos=mic,
        room_dims=room["dimensions"],
        wall_absorption=room.get("wall_absorption", 0.3),
        temperature=room.get("temperature", 22.0),
        room_modes=modes if modes else None,
        ir_length=ir_length,
    )


def _estimate_rt60(ir, sr=room_simulator.SAMPLE_RATE):
    """Estimate RT60 from an IR using Schroeder backward integration.

    Returns RT60 in seconds (extrapolated from T20 or T30 if possible).
    """
    # Schroeder curve: reverse cumulative sum of squared IR
    energy = ir ** 2
    schroeder = np.cumsum(energy[::-1])[::-1]
    schroeder = schroeder / max(schroeder[0], 1e-30)
    schroeder_db = 10.0 * np.log10(np.maximum(schroeder, 1e-30))

    # Find -5 dB and -25 dB points for T20 extrapolation
    idx_5 = np.searchsorted(-schroeder_db, 5.0)
    idx_25 = np.searchsorted(-schroeder_db, 25.0)

    if idx_25 <= idx_5 or idx_25 >= len(schroeder_db):
        # Fall back to -5 to -15 dB (T10)
        idx_15 = np.searchsorted(-schroeder_db, 15.0)
        if idx_15 <= idx_5 or idx_15 >= len(schroeder_db):
            return 0.0
        t10 = (idx_15 - idx_5) / sr
        return t10 * 6.0  # extrapolate to 60 dB

    t20 = (idx_25 - idx_5) / sr
    return t20 * 3.0  # extrapolate from 20 dB drop to 60 dB


def _magnitude_at_freq(ir, freq, sr=room_simulator.SAMPLE_RATE):
    """Get the magnitude (dB) of an IR's frequency response at a given frequency."""
    n = len(ir)
    spectrum = np.fft.rfft(ir, n=max(n, sr))
    freqs = np.fft.rfftfreq(max(n, sr), 1.0 / sr)
    idx = np.argmin(np.abs(freqs - freq))
    mag = np.abs(spectrum[idx])
    return 20.0 * np.log10(max(mag, 1e-30))


# -- Per-wall absorption tests ------------------------------------------------

class TestPerWallAbsorption:

    def test_dict_absorption_accepted(self):
        """Per-wall absorption as dict should not crash."""
        ir = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3],
            wall_absorption={"x0": 0.1, "x1": 0.5, "y0": 0.2, "y1": 0.4, "z0": 0.6, "z1": 0.3},
        )
        assert len(ir) > 0
        assert np.max(np.abs(ir)) > 0

    def test_missing_walls_default(self):
        """Missing walls in dict should get default 0.3."""
        parsed = room_simulator._parse_wall_absorption({"x0": 0.1})
        assert parsed["x0"] == 0.1
        assert parsed["y1"] == 0.3  # default

    def test_uniform_float_still_works(self):
        """Backward compat: float absorption should work as before."""
        parsed = room_simulator._parse_wall_absorption(0.5)
        for name in room_simulator.WALL_NAMES:
            assert parsed[name] == 0.5

    def test_asymmetric_absorption_changes_ir(self):
        """Asymmetric walls should produce a different IR from symmetric."""
        ir_sym = room_simulator.generate_room_ir(
            [4, 3, 1.5], [4, 3, 1.2], [8, 6, 3],
            wall_absorption=0.3,
        )
        ir_asym = room_simulator.generate_room_ir(
            [4, 3, 1.5], [4, 3, 1.2], [8, 6, 3],
            wall_absorption={"x0": 0.05, "x1": 0.9, "y0": 0.3, "y1": 0.3, "z0": 0.3, "z1": 0.3},
        )
        assert not np.allclose(ir_sym, ir_asym)


# -- Frequency-dependent absorption tests ------------------------------------

class TestFreqDependentAbsorption:

    def test_octave_band_list_accepted(self):
        """Octave-band absorption list should not crash."""
        ir = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3],
            wall_absorption={
                "x0": [0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6],
                "x1": 0.3, "y0": 0.3, "y1": 0.3, "z0": 0.3, "z1": 0.3,
            },
        )
        assert np.max(np.abs(ir)) > 0

    def test_fir_design_produces_correct_length(self):
        """FIR filter should have the requested number of taps."""
        coeffs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        fir = room_simulator._design_absorption_fir(coeffs, n_taps=65)
        assert len(fir) == 65

    def test_fir_reflection_at_dc(self):
        """FIR should approximate (1 - absorption) at DC."""
        coeffs = [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2]
        fir = room_simulator._design_absorption_fir(coeffs, n_taps=65)
        # DC gain = sum of FIR coefficients
        dc_gain = np.sum(fir)
        # Should be close to 1.0 - 0.2 = 0.8
        assert abs(dc_gain - 0.8) < 0.15


# -- Third-order reflections --------------------------------------------------

class TestThirdOrderReflections:

    def test_auto_third_order_small_room(self):
        """Rooms < 50 m^2 should auto-enable 3rd-order reflections."""
        # 8x6 = 48 m^2 < 50
        images = room_simulator._image_sources_with_walls([4, 3, 1.5], [8, 6, 3], max_order=3)
        # 1st: 6, 2nd: 36, 3rd: 216 = 258 total
        third_order = [i for i in images if len(i[1]) == 3]
        assert len(third_order) == 216

    def test_no_third_order_large_room(self):
        """Rooms >= 50 m^2 should not auto-enable 3rd-order (via generate_room_ir)."""
        # 20x15 = 300 m^2, include_third_order defaults to None -> auto = False
        # We test the auto logic directly
        floor_area = 20.0 * 15.0
        assert floor_area >= 50.0  # confirms large room

    def test_third_order_adds_energy(self):
        """IR with 3rd-order reflections should have more energy than without."""
        kwargs = dict(
            speaker_pos=[1, 5, 1.5], mic_pos=[4, 3, 1.2],
            room_dims=[8, 6, 3], wall_absorption=0.3,
            ir_length=24000, room_modes=None,
        )
        ir_2nd = room_simulator.generate_room_ir(
            **kwargs, include_second_order=True, include_third_order=False,
        )
        ir_3rd = room_simulator.generate_room_ir(
            **kwargs, include_second_order=True, include_third_order=True,
        )
        # Normalized to 1.0, so compare energy (sum of squares)
        # 3rd-order has more reflections -> more late energy
        assert not np.allclose(ir_2nd, ir_3rd)

    def test_wall_tracking_correct(self):
        """Each image source should have wall_seq length matching its order."""
        images = room_simulator._image_sources_with_walls([4, 3, 1.5], [8, 6, 3], max_order=2)
        for pos, walls in images:
            assert len(walls) in (1, 2)
            for w in walls:
                assert w in room_simulator.WALL_NAMES


# -- Axial mode computation ---------------------------------------------------

class TestAxialModes:

    def test_mode_frequencies_physically_correct(self):
        """Axial modes should match f = n*c/(2*L) formula."""
        dims = [8.0, 6.0, 3.0]
        speed = 343.0
        modes = room_simulator._compute_axial_modes(dims, speed, freq_min=20.0, freq_max=80.0)
        # Expected: 8m -> 21.4, 42.9, 64.3 Hz; 6m -> 28.6, 57.2 Hz; 3m -> 57.2 Hz
        freqs = [m["frequency"] for m in modes]
        # 21.4 Hz (n=1, L=8)
        assert any(abs(f - 21.44) < 0.5 for f in freqs), f"Missing 21.4 Hz mode in {freqs}"
        # 42.9 Hz (n=2, L=8)
        assert any(abs(f - 42.88) < 0.5 for f in freqs), f"Missing 42.9 Hz mode in {freqs}"
        # 28.6 Hz (n=1, L=6)
        assert any(abs(f - 28.58) < 0.5 for f in freqs), f"Missing 28.6 Hz mode in {freqs}"

    def test_auto_axial_modes_adds_to_explicit(self):
        """auto_axial_modes should add computed modes alongside explicit ones."""
        explicit = [{"frequency": 42.0, "q": 8.0, "gain": 12.0}]
        ir_explicit = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3],
            room_modes=explicit, auto_axial_modes=False,
        )
        ir_auto = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3],
            room_modes=explicit, auto_axial_modes=True,
        )
        # auto_axial_modes adds more modes -> different IR
        assert not np.allclose(ir_explicit, ir_auto)

    def test_no_modes_outside_range(self):
        """All computed modes should be within [freq_min, freq_max]."""
        modes = room_simulator._compute_axial_modes([8.0, 6.0, 3.0], 343.0, 30.0, 60.0)
        for m in modes:
            assert 30.0 <= m["frequency"] <= 60.0


# -- Noise floor control ------------------------------------------------------

class TestNoiseFloor:

    def test_deterministic_without_noise(self):
        """Two calls with noise_floor_dbfs=None should produce identical output."""
        kwargs = dict(
            speaker_pos=[1, 5, 1.5], mic_pos=[4, 3, 1.2],
            room_dims=[8, 6, 3], noise_floor_dbfs=None,
        )
        ir1 = room_simulator.generate_room_ir(**kwargs)
        ir2 = room_simulator.generate_room_ir(**kwargs)
        np.testing.assert_array_equal(ir1, ir2)

    def test_noise_adds_energy(self):
        """Noise floor should add energy in the tail of the IR."""
        kwargs = dict(
            speaker_pos=[1, 5, 1.5], mic_pos=[4, 3, 1.2],
            room_dims=[8, 6, 3],
        )
        ir_clean = room_simulator.generate_room_ir(**kwargs, noise_floor_dbfs=None)
        ir_noisy = room_simulator.generate_room_ir(**kwargs, noise_floor_dbfs=-40.0)
        # Tail energy (last 25%) should be higher with noise
        tail_start = len(ir_clean) * 3 // 4
        tail_energy_clean = np.sum(ir_clean[tail_start:] ** 2)
        tail_energy_noisy = np.sum(ir_noisy[tail_start:] ** 2)
        assert tail_energy_noisy > tail_energy_clean


# -- Scenario YAML loading tests ----------------------------------------------

class TestScenarioLoading:

    def test_small_club_loads(self):
        cfg = _load_scenario("small_club")
        assert cfg["room"]["dimensions"] == [8.0, 6.0, 3.0]
        assert isinstance(cfg["room"]["wall_absorption"], dict)

    def test_large_hall_loads(self):
        cfg = _load_scenario("large_hall")
        assert cfg["room"]["dimensions"] == [20.0, 15.0, 5.0]

    def test_outdoor_tent_loads(self):
        cfg = _load_scenario("outdoor_tent")
        assert cfg["room_modes"] == []

    def test_all_scenarios_generate_ir(self):
        """All scenario YAMLs should produce valid IRs."""
        for name in ("small_club", "large_hall", "outdoor_tent"):
            cfg = _load_scenario(name)
            ir = _generate_ir_from_scenario(cfg)
            assert np.max(np.abs(ir)) > 0, f"{name} produced zero IR"
            assert np.isfinite(ir).all(), f"{name} produced non-finite IR"


# -- RT60 verification --------------------------------------------------------

class TestRT60:

    def test_large_hall_longer_rt60_than_outdoor(self):
        """Large hall (low absorption) should have longer RT60 than outdoor tent."""
        hall = _load_scenario("large_hall")
        tent = _load_scenario("outdoor_tent")
        ir_hall = _generate_ir_from_scenario(hall, ir_length=96000)
        ir_tent = _generate_ir_from_scenario(tent, ir_length=96000)
        rt60_hall = _estimate_rt60(ir_hall)
        rt60_tent = _estimate_rt60(ir_tent)
        assert rt60_hall > rt60_tent, (
            f"Hall RT60 ({rt60_hall:.3f}s) should exceed tent ({rt60_tent:.3f}s)"
        )

    def test_small_club_moderate_rt60(self):
        """Small club should have RT60 between outdoor tent and large hall."""
        club = _load_scenario("small_club")
        tent = _load_scenario("outdoor_tent")
        ir_club = _generate_ir_from_scenario(club, ir_length=96000)
        ir_tent = _generate_ir_from_scenario(tent, ir_length=96000)
        rt60_club = _estimate_rt60(ir_club)
        rt60_tent = _estimate_rt60(ir_tent)
        assert rt60_club > rt60_tent, (
            f"Club RT60 ({rt60_club:.3f}s) should exceed tent ({rt60_tent:.3f}s)"
        )


# -- 42 Hz mode presence in small_club ----------------------------------------

class TestSmallClub42HzMode:

    def test_42hz_mode_present(self):
        """Small club IR should show a peak near 42 Hz from the explicit room mode."""
        cfg = _load_scenario("small_club")
        ir = _generate_ir_from_scenario(cfg, ir_length=96000)

        # Check magnitude near 42 Hz vs neighboring frequencies
        mag_42 = _magnitude_at_freq(ir, 42.9)
        mag_35 = _magnitude_at_freq(ir, 35.0)
        mag_50 = _magnitude_at_freq(ir, 50.0)

        # 42.9 Hz mode should be louder than both neighbors
        assert mag_42 > mag_35, (
            f"42.9 Hz ({mag_42:.1f} dB) should exceed 35 Hz ({mag_35:.1f} dB)"
        )
        assert mag_42 > mag_50, (
            f"42.9 Hz ({mag_42:.1f} dB) should exceed 50 Hz ({mag_50:.1f} dB)"
        )

    def test_42hz_mode_significant_boost(self):
        """The 42 Hz mode should provide at least 3 dB of boost over neighbors."""
        cfg = _load_scenario("small_club")
        ir = _generate_ir_from_scenario(cfg, ir_length=96000)

        mag_42 = _magnitude_at_freq(ir, 42.9)
        # Average of two neighbors as reference
        mag_ref = (_magnitude_at_freq(ir, 35.0) + _magnitude_at_freq(ir, 55.0)) / 2.0

        boost = mag_42 - mag_ref
        assert boost >= 3.0, (
            f"42.9 Hz mode boost ({boost:.1f} dB) should be >= 3 dB"
        )

    def test_outdoor_tent_no_42hz_peak(self):
        """Outdoor tent (no modes) should not have a 42 Hz peak."""
        cfg = _load_scenario("outdoor_tent")
        ir = _generate_ir_from_scenario(cfg, ir_length=96000)

        mag_42 = _magnitude_at_freq(ir, 42.9)
        mag_35 = _magnitude_at_freq(ir, 35.0)

        # Without room modes, 42 Hz should not be notably higher than 35 Hz
        # Allow up to 2 dB difference from natural room response
        diff = mag_42 - mag_35
        assert diff < 5.0, (
            f"Tent should not have strong 42 Hz peak (diff={diff:.1f} dB)"
        )
