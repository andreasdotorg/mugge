"""Tests for speaker simulation FIR generator (T-067-1, US-067).

Verifies:
- Sealed enclosure: 2nd-order HP shape (flat passband, 12 dB/oct roll-off)
- Ported enclosure: 4th-order bandpass (24 dB/oct below tuning)
- Fallback model: gentle roll-off when T/S unavailable
- Baffle-step diffraction: 6 dB shelf
- Sensitivity normalization
- Minimum-phase property of output FIR
- Identity-based generation with real config files
"""

import math

import numpy as np
import pytest

from room_correction.speaker_sim import (
    sealed_response,
    ported_response,
    baffle_step,
    sensitivity_gain,
    generate_speaker_fir,
    generate_fir_from_identity,
    DEFAULT_N_TAPS,
)
from room_correction.dsp_utils import SAMPLE_RATE, to_minimum_phase


# -- Test fixtures -----------------------------------------------------------

# Markaudio CHN-50 T/S parameters (from driver.yml)
CHN50_FS = 113.6
CHN50_QTS = 0.55
CHN50_VAS = 1.0965  # liters
CHN50_VB = 1.16     # liters (sealed enclosure)
CHN50_SENSITIVITY = 87.5

# Derived sealed-box parameters for verification
CHN50_ALPHA = CHN50_VAS / CHN50_VB
CHN50_QTC = CHN50_QTS * math.sqrt(1.0 + CHN50_ALPHA)
CHN50_FC = CHN50_FS * math.sqrt(1.0 + CHN50_ALPHA)


def _mag_at_freq(freqs, mag, target_hz):
    """Find magnitude at the nearest frequency bin."""
    idx = np.argmin(np.abs(freqs - target_hz))
    return mag[idx]


def _fir_magnitude(fir, sr=SAMPLE_RATE):
    """Compute magnitude spectrum of a FIR."""
    n_fft = len(fir) * 4
    spectrum = np.fft.rfft(fir, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    return freqs, np.abs(spectrum)


# -- Sealed enclosure tests --------------------------------------------------

class TestSealedResponse:

    def test_passband_flat(self):
        """Well above Fc, the response should be approximately flat (0 dB)."""
        freqs = np.linspace(1, 20000, 10000)
        mag = sealed_response(freqs, CHN50_FS, CHN50_QTS, CHN50_VAS, CHN50_VB)
        # At 1 kHz (well above Fc ~157 Hz), magnitude should be ~1.0
        mag_1k = _mag_at_freq(freqs, mag, 1000.0)
        assert abs(mag_1k - 1.0) < 0.05, f"Passband not flat: {mag_1k}"

    def test_rolloff_below_fc(self):
        """Below Fc, response should roll off at ~12 dB/oct (2nd order)."""
        freqs = np.linspace(1, 20000, 10000)
        mag = sealed_response(freqs, CHN50_FS, CHN50_QTS, CHN50_VAS, CHN50_VB)

        # Check roll-off between 20 Hz and 40 Hz (both well below Fc ~157 Hz)
        mag_20 = _mag_at_freq(freqs, mag, 20.0)
        mag_40 = _mag_at_freq(freqs, mag, 40.0)

        # 1 octave apart, expect ~12 dB difference for 2nd-order HP
        db_diff = 20.0 * np.log10(mag_40 / max(mag_20, 1e-10))
        assert 9.0 < db_diff < 15.0, (
            f"Roll-off slope {db_diff:.1f} dB/oct, expected ~12"
        )

    def test_response_at_fc(self):
        """At Fc, response depends on Qtc. For Qtc=0.764, expect ~-2 to -4 dB."""
        freqs = np.linspace(1, 20000, 10000)
        mag = sealed_response(freqs, CHN50_FS, CHN50_QTS, CHN50_VAS, CHN50_VB)
        mag_fc = _mag_at_freq(freqs, mag, CHN50_FC)
        db_fc = 20.0 * np.log10(max(mag_fc, 1e-10))
        # At Fc with Qtc=0.764 (slightly underdamped): expect ~-2 to -4 dB
        assert -6.0 < db_fc < 0.0, f"Response at Fc: {db_fc:.1f} dB"

    def test_dc_is_zero(self):
        """DC response must be zero for a high-pass system."""
        freqs = np.array([0.0, 10.0, 100.0, 1000.0])
        mag = sealed_response(freqs, CHN50_FS, CHN50_QTS, CHN50_VAS, CHN50_VB)
        assert mag[0] == 0.0 or mag[0] < 1e-10


# -- Ported enclosure tests --------------------------------------------------

class TestPortedResponse:

    def test_passband_flat(self):
        """Above port tuning and Fs, the response should be approximately flat."""
        freqs = np.linspace(1, 20000, 10000)
        # Use typical 15" woofer in ported box
        mag = ported_response(freqs, fs_hz=30.0, qts=0.35,
                              vas_liters=200.0, vb_liters=200.0, fb_hz=35.0)
        mag_1k = _mag_at_freq(freqs, mag, 1000.0)
        assert abs(mag_1k - 1.0) < 0.1, f"Passband not flat: {mag_1k}"

    def test_steeper_rolloff_than_sealed(self):
        """Ported should have steeper roll-off (~24 dB/oct) below port tuning."""
        freqs = np.linspace(1, 20000, 10000)
        mag = ported_response(freqs, fs_hz=30.0, qts=0.35,
                              vas_liters=200.0, vb_liters=200.0, fb_hz=35.0)

        # Check deep below port tuning: 5 Hz vs 10 Hz
        mag_5 = _mag_at_freq(freqs, mag, 5.0)
        mag_10 = _mag_at_freq(freqs, mag, 10.0)

        db_diff = 20.0 * np.log10(mag_10 / max(mag_5, 1e-10))
        # 1 octave, expect ~24 dB for 4th-order
        assert db_diff > 15.0, (
            f"Roll-off {db_diff:.1f} dB/oct, expected >15 for ported"
        )

    def test_dc_is_zero(self):
        """DC response must be zero."""
        freqs = np.array([0.0, 10.0, 100.0, 1000.0])
        mag = ported_response(freqs, fs_hz=30.0, qts=0.35,
                              vas_liters=200.0, vb_liters=200.0, fb_hz=35.0)
        assert mag[0] < 1e-10


# -- Baffle step tests -------------------------------------------------------

class TestBaffleStep:

    def test_high_freq_unity(self):
        """At high frequencies (small wavelength), baffle step = 0 dB."""
        freqs = np.array([5000.0, 10000.0, 20000.0])
        bs = baffle_step(freqs, baffle_width_m=0.2)
        np.testing.assert_allclose(bs, 1.0, atol=0.05)

    def test_low_freq_minus_6db(self):
        """At very low frequencies, baffle step = -6 dB (half amplitude)."""
        freqs = np.array([5.0, 10.0])
        bs = baffle_step(freqs, baffle_width_m=0.2)
        db = 20.0 * np.log10(bs)
        np.testing.assert_allclose(db, -6.0, atol=1.5)

    def test_zero_baffle_returns_unity(self):
        """Zero baffle width -> no baffle step effect."""
        freqs = np.array([100.0, 1000.0])
        bs = baffle_step(freqs, baffle_width_m=0.0)
        np.testing.assert_array_equal(bs, 1.0)

    def test_transition_frequency(self):
        """At the step frequency, expect ~-3 dB."""
        width = 0.2  # 200mm baffle
        f_step = 343.0 / (math.pi * width)  # ~546 Hz
        freqs = np.array([f_step])
        bs = baffle_step(freqs, baffle_width_m=width)
        db = 20.0 * np.log10(bs[0])
        assert -4.5 < db < -1.5, f"At f_step: {db:.1f} dB, expected ~-3"


# -- Sensitivity normalization -----------------------------------------------

class TestSensitivityGain:

    def test_reference_sensitivity_unity(self):
        """At reference sensitivity, gain should be 1.0."""
        assert sensitivity_gain(90.0, 90.0) == pytest.approx(1.0)

    def test_higher_sensitivity_attenuated(self):
        """Higher sensitivity -> lower gain (attenuated in sim)."""
        gain = sensitivity_gain(96.0, 90.0)
        assert gain < 1.0
        # 6 dB higher -> 0.5x gain
        assert gain == pytest.approx(0.5012, abs=0.01)

    def test_lower_sensitivity_boosted(self):
        """Lower sensitivity -> higher gain (boosted in sim)."""
        gain = sensitivity_gain(84.0, 90.0)
        assert gain > 1.0


# -- FIR generation tests ----------------------------------------------------

class TestGenerateSpeakerFir:

    def test_sealed_fir_length(self):
        """Output FIR should have requested length."""
        fir = generate_speaker_fir(
            "sealed", fs_hz=CHN50_FS, qts=CHN50_QTS,
            vas_liters=CHN50_VAS, vb_liters=CHN50_VB,
            n_taps=4096,
        )
        assert len(fir) == 4096

    def test_sealed_fir_is_minimum_phase(self):
        """Sealed FIR should be minimum-phase (energy concentrated at start)."""
        fir = generate_speaker_fir(
            "sealed", fs_hz=CHN50_FS, qts=CHN50_QTS,
            vas_liters=CHN50_VAS, vb_liters=CHN50_VB,
        )
        # Energy in first quarter should be > 90% of total
        total_energy = np.sum(fir ** 2)
        first_quarter = np.sum(fir[:len(fir) // 4] ** 2)
        assert first_quarter / total_energy > 0.9

    def test_sealed_fir_hp_shape(self):
        """Sealed FIR frequency response should show HP roll-off."""
        fir = generate_speaker_fir(
            "sealed", fs_hz=CHN50_FS, qts=CHN50_QTS,
            vas_liters=CHN50_VAS, vb_liters=CHN50_VB,
        )
        freqs, mag = _fir_magnitude(fir)
        mag_1k = _mag_at_freq(freqs, mag, 1000.0)
        mag_30 = _mag_at_freq(freqs, mag, 30.0)
        # 30 Hz should be much lower than 1 kHz
        db_diff = 20.0 * np.log10(mag_1k / max(mag_30, 1e-10))
        assert db_diff > 10.0, f"Expected HP roll-off, got {db_diff:.1f} dB"

    def test_ported_fir_shape(self):
        """Ported FIR should show bandpass behavior."""
        fir = generate_speaker_fir(
            "ported", fs_hz=30.0, qts=0.35,
            vas_liters=200.0, vb_liters=200.0, fb_hz=35.0,
        )
        freqs, mag = _fir_magnitude(fir)
        mag_1k = _mag_at_freq(freqs, mag, 1000.0)
        mag_5 = _mag_at_freq(freqs, mag, 5.0)
        # 5 Hz should be much lower than 1 kHz
        db_diff = 20.0 * np.log10(mag_1k / max(mag_5, 1e-10))
        assert db_diff > 20.0

    def test_fallback_fir_shape(self):
        """Fallback should have gentle roll-off below 50 Hz."""
        fir = generate_speaker_fir("fallback")
        freqs, mag = _fir_magnitude(fir)
        mag_1k = _mag_at_freq(freqs, mag, 1000.0)
        mag_10 = _mag_at_freq(freqs, mag, 10.0)
        # 10 Hz should be lower than 1 kHz
        db_diff = 20.0 * np.log10(mag_1k / max(mag_10, 1e-10))
        assert db_diff > 5.0

    def test_peak_normalized_to_unity(self):
        """Peak magnitude should be <= 0 dB (D-009 safety)."""
        fir = generate_speaker_fir(
            "sealed", fs_hz=CHN50_FS, qts=CHN50_QTS,
            vas_liters=CHN50_VAS, vb_liters=CHN50_VB,
        )
        freqs, mag = _fir_magnitude(fir)
        peak_db = 20.0 * np.log10(np.max(mag))
        # Allow small overshoot from windowing artifacts
        assert peak_db < 1.0, f"Peak {peak_db:.1f} dB, expected <= 0"

    def test_invalid_enclosure_type(self):
        with pytest.raises(ValueError, match="Unknown enclosure_type"):
            generate_speaker_fir("horn")

    def test_sealed_missing_params(self):
        with pytest.raises(ValueError, match="sealed.*requires"):
            generate_speaker_fir("sealed", fs_hz=100.0)

    def test_ported_missing_params(self):
        with pytest.raises(ValueError, match="ported.*requires"):
            generate_speaker_fir("ported", fs_hz=30.0)

    def test_custom_tap_count(self):
        fir = generate_speaker_fir("fallback", n_taps=8192)
        assert len(fir) == 8192

    def test_with_baffle_step(self):
        """Baffle step should reduce low-frequency energy."""
        fir_no_bs = generate_speaker_fir(
            "sealed", fs_hz=CHN50_FS, qts=CHN50_QTS,
            vas_liters=CHN50_VAS, vb_liters=CHN50_VB,
            baffle_width_m=0.0,
        )
        fir_with_bs = generate_speaker_fir(
            "sealed", fs_hz=CHN50_FS, qts=CHN50_QTS,
            vas_liters=CHN50_VAS, vb_liters=CHN50_VB,
            baffle_width_m=0.2,
        )
        freqs1, mag1 = _fir_magnitude(fir_no_bs)
        freqs2, mag2 = _fir_magnitude(fir_with_bs)
        # At low frequencies, baffle step version should have relatively
        # less energy compared to high frequencies
        ratio_no_bs = _mag_at_freq(freqs1, mag1, 50.0) / _mag_at_freq(freqs1, mag1, 5000.0)
        ratio_with_bs = _mag_at_freq(freqs2, mag2, 50.0) / _mag_at_freq(freqs2, mag2, 5000.0)
        assert ratio_with_bs < ratio_no_bs


# -- Identity-based generation -----------------------------------------------

class TestGenerateFromIdentity:

    def test_sealed_identity(self):
        """CHN-50P sealed identity should produce valid sealed FIR."""
        fir = generate_fir_from_identity("markaudio-chn-50p-sealed-1l16")
        assert len(fir) == DEFAULT_N_TAPS
        assert np.max(np.abs(fir)) > 0  # Not all zeros

    def test_fallback_when_no_ts(self):
        """Bose PS28 III has no T/S data -> should use fallback."""
        fir = generate_fir_from_identity("bose-ps28-iii-sub")
        assert len(fir) == DEFAULT_N_TAPS
        assert np.max(np.abs(fir)) > 0

    def test_identity_not_found(self):
        with pytest.raises(FileNotFoundError):
            generate_fir_from_identity("nonexistent-speaker")

    def test_custom_n_taps(self):
        fir = generate_fir_from_identity(
            "markaudio-chn-50p-sealed-1l16", n_taps=2048
        )
        assert len(fir) == 2048
