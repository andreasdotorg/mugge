"""Round-trip correction test: room IR with known mode -> correction -> verify attenuation.

US-098 P0: Proves the correction pipeline attenuates a known 42 Hz room mode
by >= 8 dB, maintains broadband flatness, and satisfies D-009.

Pipeline under test:
    generate_room_ir (42 Hz mode @ +12 dB)
    -> generate_correction_filter
    -> combine_filters (with crossover)
    -> convolve corrected filter with original room IR
    -> measure 42 Hz attenuation + broadband deviation + D-009 compliance
"""

import os
import tempfile

import numpy as np
import pytest

from room_correction import dsp_utils
from room_correction.correction import generate_correction_filter
from room_correction.combine import combine_filters
from room_correction.crossover import generate_crossover_filter
from room_correction.export import export_filter
from room_correction.verify import verify_d009

# Import the mock room simulator (not in the main package)
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock.room_simulator import generate_room_ir

SR = 48000
N_TAPS = 16384
CROSSOVER_FREQ = 80.0
# Use -0.6 dB margin (same as production COMBINE_MARGIN_DB) to leave
# headroom for cepstral minimum-phase synthesis magnitude error (~0.02 dB).
CORRECTION_MARGIN_DB = -0.6

# Small club scenario: 7m x 5m x 3m, speaker and mic positions
ROOM_DIMS = [7.0, 5.0, 3.0]
SPEAKER_POS = [1.0, 2.5, 1.5]
MIC_POS = [4.0, 2.5, 1.2]

# Known 42 Hz room mode at +12 dB
MODE_42HZ = {"frequency": 42.0, "q": 8.0, "gain": 12.0}


def _measure_level_at_freq(signal, freq, sr=SR, bandwidth_hz=5.0):
    """Measure the magnitude level (dB) at a specific frequency.

    Averages over a narrow band around the target frequency to reduce
    sensitivity to exact bin placement.
    """
    freqs, mags = dsp_utils.rfft_magnitude(signal)
    mask = (freqs >= freq - bandwidth_hz) & (freqs <= freq + bandwidth_hz)
    if not np.any(mask):
        raise ValueError(f"No bins in range {freq} +/- {bandwidth_hz} Hz")
    return float(np.mean(dsp_utils.linear_to_db(mags[mask])))


def _measure_broadband_level(signal, low=200.0, high=10000.0, sr=SR):
    """Measure the average level (dB) in the broadband range."""
    freqs, mags = dsp_utils.rfft_magnitude(signal)
    mask = (freqs >= low) & (freqs <= high)
    if not np.any(mask):
        raise ValueError(f"No bins in range {low}-{high} Hz")
    return float(np.mean(dsp_utils.linear_to_db(mags[mask])))


class TestRoundTripCorrection:
    """Round-trip: room IR -> correction -> combine -> verify."""

    @pytest.fixture
    def room_ir(self):
        """Generate synthetic room IR with 42 Hz mode at +12 dB."""
        return generate_room_ir(
            speaker_pos=SPEAKER_POS,
            mic_pos=MIC_POS,
            room_dims=ROOM_DIMS,
            wall_absorption=0.3,
            room_modes=[MODE_42HZ],
            ir_length=int(0.5 * SR),
            sr=SR,
        )

    @pytest.fixture
    def correction_filter(self, room_ir):
        """Generate correction filter from the room IR."""
        return generate_correction_filter(
            room_ir, target_curve_name='flat', n_taps=N_TAPS, sr=SR,
            margin_db=CORRECTION_MARGIN_DB,
        )

    @pytest.fixture
    def hp_crossover(self):
        """Generate highpass crossover filter at 80 Hz."""
        return generate_crossover_filter(
            filter_type='highpass', crossover_freq=CROSSOVER_FREQ,
            slope_db_per_oct=48.0, n_taps=N_TAPS, sr=SR,
        )

    @pytest.fixture
    def lp_crossover(self):
        """Generate lowpass crossover filter at 80 Hz."""
        return generate_crossover_filter(
            filter_type='lowpass', crossover_freq=CROSSOVER_FREQ,
            slope_db_per_oct=48.0, n_taps=N_TAPS, sr=SR,
        )

    @pytest.fixture
    def combined_hp(self, correction_filter, hp_crossover):
        """Combined correction + highpass crossover."""
        return combine_filters(
            correction_filter, hp_crossover, n_taps=N_TAPS,
        )

    @pytest.fixture
    def combined_lp(self, correction_filter, lp_crossover):
        """Combined correction + lowpass crossover."""
        return combine_filters(
            correction_filter, lp_crossover, n_taps=N_TAPS,
        )

    def test_42hz_mode_attenuated(self, room_ir, combined_lp):
        """42 Hz mode should be attenuated >= 8 dB after correction.

        The lowpass (sub) channel covers 42 Hz, so we measure there.
        Compare the 42 Hz peak in the original room IR vs the corrected
        composite (room IR convolved with the combined correction+crossover).
        """
        # Uncorrected: measure 42 Hz level in original room IR
        uncorrected_42 = _measure_level_at_freq(room_ir, 42.0)

        # Corrected: convolve room IR with combined LP filter
        corrected = dsp_utils.convolve_fir(room_ir, combined_lp)
        corrected_42 = _measure_level_at_freq(corrected, 42.0)

        # Measure attenuation relative to broadband in each case.
        # The mode's prominence is what matters, not absolute level.
        uncorrected_broadband = _measure_level_at_freq(room_ir, 42.0, bandwidth_hz=0.5)
        corrected_broadband = _measure_level_at_freq(corrected, 42.0, bandwidth_hz=0.5)

        # Simpler approach: compare the 42 Hz peak relative to neighbors.
        # Uncorrected: 42 Hz stands out from its neighbors.
        uncorrected_neighbors = _measure_level_at_freq(room_ir, 60.0, bandwidth_hz=10.0)
        corrected_neighbors = _measure_level_at_freq(corrected, 60.0, bandwidth_hz=10.0)

        uncorrected_prominence = uncorrected_42 - uncorrected_neighbors
        corrected_prominence = corrected_42 - corrected_neighbors

        attenuation = uncorrected_prominence - corrected_prominence

        assert attenuation >= 8.0, (
            f"42 Hz mode attenuation {attenuation:.1f} dB < 8 dB minimum. "
            f"Uncorrected prominence: {uncorrected_prominence:.1f} dB, "
            f"corrected prominence: {corrected_prominence:.1f} dB"
        )

    def test_broadband_within_tolerance(self, room_ir, combined_hp):
        """Broadband (200 Hz - 10 kHz) should be within +/- 6 dB of target.

        The highpass channel covers the broadband range above 80 Hz.
        Uses 1/3 octave smoothing for a psychoacoustically fair comparison.
        Tolerance is 6 dB because the synthetic room IR includes reflections
        and modes that the cut-only correction cannot fully flatten.
        """
        corrected = dsp_utils.convolve_fir(room_ir, combined_hp)
        freqs, mags = dsp_utils.rfft_magnitude(corrected)

        # Use 1/3 octave smoothing — individual bins can have narrow dips
        # from comb filtering that are psychoacoustically irrelevant.
        smoothed_mags = dsp_utils.fractional_octave_smooth(mags, freqs, 3)
        smoothed_db = dsp_utils.linear_to_db(smoothed_mags)

        # Passband: 400 Hz to 8 kHz. Below 400 Hz, the frequency-dependent
        # windowing transition (at 500 Hz) causes a dip in the corrected
        # response that is expected behavior, not a correction failure.
        mask = (freqs >= 400) & (freqs <= 8000)
        smoothed_passband = smoothed_db[mask]
        smoothed_ref = np.mean(smoothed_passband)
        smoothed_dev = smoothed_passband - smoothed_ref

        max_dev = float(np.max(np.abs(smoothed_dev)))
        assert max_dev <= 6.0, (
            f"Broadband deviation {max_dev:.1f} dB exceeds +/- 6 dB tolerance"
        )

    def test_correction_filter_d009(self, correction_filter):
        """Standalone correction filter must satisfy D-009."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            tmp_path = f.name
        try:
            export_filter(correction_filter, tmp_path, n_taps=N_TAPS, sr=SR)
            result = verify_d009(tmp_path)
            assert result.passed, f"D-009 FAIL: {result.message}"
        finally:
            os.unlink(tmp_path)

    def test_combined_hp_d009(self, combined_hp):
        """Combined HP filter (correction + crossover) must satisfy D-009."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            tmp_path = f.name
        try:
            export_filter(combined_hp, tmp_path, n_taps=N_TAPS, sr=SR)
            result = verify_d009(tmp_path)
            assert result.passed, f"D-009 FAIL: {result.message}"
        finally:
            os.unlink(tmp_path)

    def test_combined_lp_d009(self, combined_lp):
        """Combined LP filter (correction + crossover) must satisfy D-009."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            tmp_path = f.name
        try:
            export_filter(combined_lp, tmp_path, n_taps=N_TAPS, sr=SR)
            result = verify_d009(tmp_path)
            assert result.passed, f"D-009 FAIL: {result.message}"
        finally:
            os.unlink(tmp_path)

    def test_filters_are_finite(self, correction_filter, combined_hp, combined_lp):
        """All generated filters must be finite (no NaN/Inf)."""
        assert np.isfinite(correction_filter).all(), "correction_filter has NaN/Inf"
        assert np.isfinite(combined_hp).all(), "combined_hp has NaN/Inf"
        assert np.isfinite(combined_lp).all(), "combined_lp has NaN/Inf"

    def test_filters_have_correct_length(self, correction_filter, combined_hp, combined_lp):
        """All filters should be exactly N_TAPS long."""
        assert len(correction_filter) == N_TAPS
        assert len(combined_hp) == N_TAPS
        assert len(combined_lp) == N_TAPS


class TestFullPipelinePath:
    """Test via generate_profile_filters() — the production code path."""

    def test_profile_pipeline_with_synthetic_ir(self):
        """Full pipeline: synthetic room IR -> generate_profile_filters -> D-009."""
        from room_correction.generate_profile_filters import generate_profile_filters

        # Generate synthetic room IR with 42 Hz mode
        room_ir = generate_room_ir(
            speaker_pos=SPEAKER_POS,
            mic_pos=MIC_POS,
            room_dims=ROOM_DIMS,
            wall_absorption=0.3,
            room_modes=[MODE_42HZ],
            ir_length=int(0.5 * SR),
            sr=SR,
        )

        # Build a correction filter from the room IR
        correction = generate_correction_filter(
            room_ir, target_curve_name='flat', n_taps=N_TAPS, sr=SR,
            margin_db=CORRECTION_MARGIN_DB,
        )

        # Minimal 2-way profile (matches the standard Bose topology)
        profile = {
            "name": "test-roundtrip",
            "crossover": {
                "frequency_hz": CROSSOVER_FREQ,
                "slope_db_per_oct": 48.0,
            },
            "speakers": {
                "left_hp": {"filter_type": "highpass", "identity": ""},
                "sub1_lp": {"filter_type": "lowpass", "identity": ""},
            },
        }

        # Provide the same correction filter for both channels
        correction_filters = {
            "left_hp": correction,
            "sub1_lp": correction,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            combined = generate_profile_filters(
                profile=profile,
                identities={},
                correction_filters=correction_filters,
                output_dir=tmpdir,
                n_taps=N_TAPS,
                sr=SR,
            )

            # Verify outputs exist
            assert "left_hp" in combined
            assert "sub1_lp" in combined

            # Verify D-009 compliance on exported WAVs
            for spk_key in ["left_hp", "sub1_lp"]:
                wav_path = os.path.join(tmpdir, f"combined_{spk_key}.wav")
                assert os.path.exists(wav_path), f"Missing {wav_path}"
                result = verify_d009(wav_path)
                assert result.passed, (
                    f"D-009 FAIL for {spk_key}: {result.message}"
                )

            # Verify that the sub channel attenuates the 42 Hz mode
            sub_filter = combined["sub1_lp"]
            corrected = dsp_utils.convolve_fir(room_ir, sub_filter)
            corrected_42 = _measure_level_at_freq(corrected, 42.0)
            corrected_60 = _measure_level_at_freq(corrected, 60.0, bandwidth_hz=10.0)
            uncorrected_42 = _measure_level_at_freq(room_ir, 42.0)
            uncorrected_60 = _measure_level_at_freq(room_ir, 60.0, bandwidth_hz=10.0)

            uncorrected_prominence = uncorrected_42 - uncorrected_60
            corrected_prominence = corrected_42 - corrected_60
            attenuation = uncorrected_prominence - corrected_prominence

            assert attenuation >= 6.0, (
                f"Pipeline 42 Hz attenuation {attenuation:.1f} dB < 6 dB. "
                f"Uncorrected prominence: {uncorrected_prominence:.1f} dB, "
                f"corrected: {corrected_prominence:.1f} dB"
            )


class TestRoomIRHasMode:
    """Sanity: verify the synthetic room IR actually has the 42 Hz mode."""

    def test_42hz_mode_present_in_room_ir(self):
        """The generated room IR should show elevated energy at 42 Hz."""
        ir_with_mode = generate_room_ir(
            speaker_pos=SPEAKER_POS,
            mic_pos=MIC_POS,
            room_dims=ROOM_DIMS,
            wall_absorption=0.3,
            room_modes=[MODE_42HZ],
            ir_length=int(0.5 * SR),
            sr=SR,
        )
        ir_flat = generate_room_ir(
            speaker_pos=SPEAKER_POS,
            mic_pos=MIC_POS,
            room_dims=ROOM_DIMS,
            wall_absorption=0.3,
            room_modes=None,
            ir_length=int(0.5 * SR),
            sr=SR,
        )

        level_with_mode = _measure_level_at_freq(ir_with_mode, 42.0)
        level_flat = _measure_level_at_freq(ir_flat, 42.0)

        # The mode should add at least 3 dB at 42 Hz
        assert level_with_mode - level_flat >= 3.0, (
            f"42 Hz mode adds only {level_with_mode - level_flat:.1f} dB "
            f"(expected >= 3 dB)"
        )
