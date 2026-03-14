"""Automated per-channel gain calibration ramp for measurement.

Slowly ramps from silence to the target SPL level using band-limited pink
noise bursts, with mic-based safety gating. This is run before each
measurement to find the correct digital output level for the desired SPL at
the mic position.

Safety architecture (4-layer defense-in-depth):
  Layer 1: Digital hard cap from thermal_ceiling module (never exceed thermal
           ceiling regardless of target SPL)
  Layer 2: CamillaDSP measurement config attenuation (-20 dB)
  Layer 3: Mic SPL gate (abort if measured SPL > hard_limit_spl_db)
  Layer 4: Slow ramp + operator presence (3 dB max step, 2s bursts)

Design decisions (from Architect + AD safety review):
  - Open-loop ramp: step at fixed dB increments. The mic is a SAFETY GATE
    (abort if too loud), NOT a closed-loop control input.
  - Calibrate with band-limited pink noise (100 Hz - 10 kHz), NOT a sweep.
    A sweep concentrates energy at resonance frequencies.
  - Maximum step size hard-capped at 3 dB in code (not configurable).
  - Per-channel, sequential. All other channels muted during calibration.

Usage:
    from gain_calibration import calibrate_channel

    result = calibrate_channel(
        channel_index=0,
        target_spl_db=75.0,
        thermal_ceiling_dbfs=-20.0,
    )
    if result.passed:
        print(f"Calibrated level: {result.calibrated_level_dbfs:.1f} dBFS")
"""

import dataclasses
import sys
import time

import numpy as np

# Force line-buffered stdout for SSH (same as measure_nearfield.py)
if not sys.stdout.line_buffering:
    sys.stdout.reconfigure(line_buffering=True)
if not sys.stderr.line_buffering:
    sys.stderr.reconfigure(line_buffering=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Starting level for the ramp (effectively silence)
START_LEVEL_DBFS = -60.0

# Step sizes (dB). MAX_STEP_DB is a hard code cap — not configurable.
COARSE_STEP_DB = 3.0
FINE_STEP_DB = 1.0
MAX_STEP_DB = 3.0  # absolute maximum, enforced in code

# Threshold for switching from coarse to fine steps: when measured SPL is
# within this many dB of the target.
FINE_THRESHOLD_DB = 6.0

# Mic silence detection: if recorded peak is below this, the mic is not
# detecting any signal (cable disconnected, wrong device, etc.)
MIC_SILENCE_PEAK_DBFS = -80.0

# SPL target tolerance: if measured SPL is within this many dB of target,
# consider it locked.
SPL_TOLERANCE_DB = 1.0

# Maximum number of ramp steps before giving up (prevents infinite loops)
MAX_RAMP_STEPS = 30

# Pink noise parameters (same as measure_nearfield.py)
PINK_NOISE_F_LOW = 100.0
PINK_NOISE_F_HIGH = 10000.0

SAMPLE_RATE = 48000

# Module-level sounddevice reference. Set to a MockSoundDevice instance in
# mock mode, or left as None for real sounddevice (imported locally).
_sd_override = None


def set_mock_sd(mock_sd):
    """Set a mock sounddevice object for testing without audio hardware.

    Parameters
    ----------
    mock_sd : MockSoundDevice or None
        The mock sounddevice instance. Pass None to revert to real sounddevice.
    """
    global _sd_override
    _sd_override = mock_sd


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class CalibrationResult:
    """Result of a gain calibration ramp.

    Attributes
    ----------
    passed : bool
        True if calibration reached the target SPL without hitting any
        safety limit.
    calibrated_level_dbfs : float
        The digital output level (dBFS) that achieved the target SPL.
        Only meaningful if passed is True.
    measured_spl_db : float
        The SPL measured at the final step.
    steps_taken : int
        Number of ramp steps executed.
    abort_reason : str or None
        If passed is False, describes why calibration was aborted.
    """
    passed: bool
    calibrated_level_dbfs: float
    measured_spl_db: float
    steps_taken: int
    abort_reason: str = None


# ---------------------------------------------------------------------------
# Pink noise generation (band-limited, same algorithm as measure_nearfield.py)
# ---------------------------------------------------------------------------

def _generate_pink_noise(duration_s, sr=SAMPLE_RATE, level_dbfs=-40.0,
                         f_low=PINK_NOISE_F_LOW, f_high=PINK_NOISE_F_HIGH):
    """Generate band-limited pink noise at a specific RMS dBFS level.

    This is a local copy of the algorithm from measure_nearfield.py to avoid
    circular imports. The implementation is identical: frequency-domain 1/f
    shaping followed by Butterworth bandpass and RMS normalization.
    """
    from scipy.signal import butter, sosfilt

    n_samples = int(duration_s * sr)
    white = np.random.randn(n_samples).astype(np.float64)

    # Pad to next power of 2 for FFT efficiency
    n_fft = 1
    while n_fft < n_samples:
        n_fft <<= 1

    spectrum = np.fft.rfft(white, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    # 1/sqrt(f) amplitude = pink spectrum
    freqs_safe = freqs.copy()
    freqs_safe[0] = 1.0
    pink_filter = 1.0 / np.sqrt(freqs_safe)
    spectrum *= pink_filter

    pink = np.fft.irfft(spectrum, n=n_fft)[:n_samples]

    # Band-limit with 4th-order Butterworth
    nyquist = sr / 2.0
    low = f_low / nyquist
    high = min(f_high / nyquist, 0.999)
    sos = butter(4, [low, high], btype='bandpass', output='sos')
    pink = sosfilt(sos, pink)

    # Normalize to target RMS
    rms = np.sqrt(np.mean(pink ** 2))
    if rms > 0:
        target_rms = 10.0 ** (level_dbfs / 20.0)
        pink *= target_rms / rms

    # Hard-clip to prevent any sample exceeding 0 dBFS
    pink = np.clip(pink, -1.0, 1.0)

    return pink


# ---------------------------------------------------------------------------
# SPL computation from UMIK-1 recording
# ---------------------------------------------------------------------------

def _compute_spl_from_recording(recording, sensitivity_dbfs_to_spl):
    """Compute approximate SPL from a UMIK-1 recording.

    Parameters
    ----------
    recording : np.ndarray
        Recorded audio from UMIK-1 (float, mono).
    sensitivity_dbfs_to_spl : float
        UMIK-1 calibration constant: 0 dBFS maps to this SPL value.
        For UMIK-1 serial 7161942: 121.4 dB SPL.

    Returns
    -------
    tuple of (float, float)
        (rms_spl_db, peak_dbfs) where:
        - rms_spl_db: approximate SPL in dB
        - peak_dbfs: peak level in dBFS of the recording
    """
    rms = np.sqrt(np.mean(recording ** 2))
    peak = np.max(np.abs(recording))

    rms_dbfs = 20.0 * np.log10(max(rms, 1e-10))
    peak_dbfs = 20.0 * np.log10(max(peak, 1e-10))

    rms_spl_db = rms_dbfs + sensitivity_dbfs_to_spl

    return rms_spl_db, peak_dbfs


# ---------------------------------------------------------------------------
# Core play-and-record burst
# ---------------------------------------------------------------------------

def _play_burst(noise_signal, channel_index, output_device, input_device,
                sr=SAMPLE_RATE):
    """Play a noise burst on one channel and record from the mic.

    Parameters
    ----------
    noise_signal : np.ndarray
        The pink noise burst to play (mono, float).
    channel_index : int
        0-indexed output channel.
    output_device : int or str or None
        Sounddevice output device identifier.
    input_device : int or str or None
        Sounddevice input device identifier (UMIK-1).
    sr : int
        Sample rate.

    Returns
    -------
    np.ndarray
        Mono recording from the mic (float64).
    """
    sd = _sd_override
    if sd is None:
        import sounddevice as sd

    out_info = sd.query_devices(output_device)
    n_out_channels = out_info['max_output_channels']

    if channel_index >= n_out_channels:
        raise ValueError(
            f"Channel {channel_index} exceeds device capacity "
            f"({n_out_channels} channels on '{out_info['name']}')")

    # Build multi-channel output: target channel only, all others silent
    output_buffer = np.zeros((len(noise_signal), n_out_channels),
                             dtype=np.float32)
    output_buffer[:, channel_index] = noise_signal.astype(np.float32)

    recording = sd.playrec(
        output_buffer,
        samplerate=sr,
        input_mapping=[1],  # UMIK-1 channel 1 (mono)
        device=(input_device, output_device),
        dtype='float32',
    )
    sd.wait()

    return recording[:, 0].astype(np.float64)


# ---------------------------------------------------------------------------
# Main calibration function
# ---------------------------------------------------------------------------

def calibrate_channel(
    channel_index,
    target_spl_db=75.0,
    hard_limit_spl_db=84.0,
    sample_rate=SAMPLE_RATE,
    output_device=None,
    input_device=None,
    umik_sensitivity_dbfs_to_spl=121.4,
    thermal_ceiling_dbfs=-20.0,
    burst_duration_s=2.0,
):
    """Ramp from silence to target SPL. Returns calibrated digital level.

    Open-loop ramp: steps at fixed dB increments. The mic reading is used
    ONLY as a safety gate (abort if too loud or silent), not as a feedback
    signal for gain control.

    Parameters
    ----------
    channel_index : int
        0-indexed output channel.
    target_spl_db : float
        Target SPL in dB at the mic position (default 75 dB).
    hard_limit_spl_db : float
        Abort immediately if measured SPL reaches or exceeds this (default 84 dB).
    sample_rate : int
        Audio sample rate (default 48000).
    output_device : int or str or None
        Sounddevice output device. None = system default.
    input_device : int or str or None
        Sounddevice input device (UMIK-1). None = system default.
    umik_sensitivity_dbfs_to_spl : float
        UMIK-1 sensitivity: 0 dBFS = this many dB SPL (default 121.4).
    thermal_ceiling_dbfs : float
        Maximum digital output level from thermal ceiling computation.
        The ramp will never exceed this level (default -20.0).
    burst_duration_s : float
        Duration of each pink noise burst in seconds (default 2.0).

    Returns
    -------
    CalibrationResult
        Result with calibrated level, measured SPL, and pass/fail status.
    """
    current_level_dbfs = START_LEVEL_DBFS

    print("\n" + "=" * 60)
    print("GAIN CALIBRATION RAMP")
    print("=" * 60)
    print(f"  Channel:          {channel_index}")
    print(f"  Target SPL:       {target_spl_db:.1f} dB")
    print(f"  Hard limit SPL:   {hard_limit_spl_db:.1f} dB")
    print(f"  Thermal ceiling:  {thermal_ceiling_dbfs:.1f} dBFS")
    print(f"  Start level:      {current_level_dbfs:.1f} dBFS")
    print(f"  Burst duration:   {burst_duration_s:.1f}s")
    print()

    last_measured_spl = 0.0

    for step_num in range(1, MAX_RAMP_STEPS + 1):
        # Safety: never exceed thermal ceiling
        if current_level_dbfs > thermal_ceiling_dbfs:
            current_level_dbfs = thermal_ceiling_dbfs

        print(f"  Step {step_num}: playing at {current_level_dbfs:.1f} dBFS ...",
              end="", flush=True)

        # Generate and play pink noise burst
        noise = _generate_pink_noise(
            burst_duration_s, sr=sample_rate, level_dbfs=current_level_dbfs,
            f_low=PINK_NOISE_F_LOW, f_high=PINK_NOISE_F_HIGH)

        recording = _play_burst(
            noise, channel_index, output_device, input_device,
            sr=sample_rate)

        # Compute SPL from recording
        measured_spl, peak_dbfs = _compute_spl_from_recording(
            recording, umik_sensitivity_dbfs_to_spl)
        last_measured_spl = measured_spl

        print(f" measured {measured_spl:.1f} dB SPL "
              f"(mic peak {peak_dbfs:.1f} dBFS)")

        # --- Safety gate checks ---

        # Check 1: Mic silence (cable disconnected, wrong device)
        if peak_dbfs < MIC_SILENCE_PEAK_DBFS:
            reason = (f"mic not detecting signal (peak {peak_dbfs:.1f} dBFS "
                      f"< {MIC_SILENCE_PEAK_DBFS:.0f} dBFS threshold)")
            print(f"\n  ABORT: {reason}")
            return CalibrationResult(
                passed=False,
                calibrated_level_dbfs=current_level_dbfs,
                measured_spl_db=measured_spl,
                steps_taken=step_num,
                abort_reason=reason,
            )

        # Check 2: Hard SPL limit exceeded
        if measured_spl >= hard_limit_spl_db:
            reason = (f"measured SPL {measured_spl:.1f} dB >= hard limit "
                      f"{hard_limit_spl_db:.1f} dB")
            print(f"\n  ABORT: {reason}")
            return CalibrationResult(
                passed=False,
                calibrated_level_dbfs=current_level_dbfs,
                measured_spl_db=measured_spl,
                steps_taken=step_num,
                abort_reason=reason,
            )

        # Check 3: At target (within tolerance)?
        if abs(measured_spl - target_spl_db) <= SPL_TOLERANCE_DB:
            print(f"\n  TARGET REACHED: {measured_spl:.1f} dB SPL "
                  f"(target {target_spl_db:.1f} +/- {SPL_TOLERANCE_DB:.0f})")
            return CalibrationResult(
                passed=True,
                calibrated_level_dbfs=current_level_dbfs,
                measured_spl_db=measured_spl,
                steps_taken=step_num,
            )

        # Check 4: Overshot target (above target + tolerance but below hard limit)
        if measured_spl > target_spl_db + SPL_TOLERANCE_DB:
            # We overshot. Back down by one fine step and report that level.
            backed_off = current_level_dbfs - FINE_STEP_DB
            print(f"\n  OVERSHOT: {measured_spl:.1f} dB > target "
                  f"{target_spl_db:.1f} dB. Backing off to "
                  f"{backed_off:.1f} dBFS.")
            return CalibrationResult(
                passed=True,
                calibrated_level_dbfs=backed_off,
                measured_spl_db=measured_spl,
                steps_taken=step_num,
            )

        # --- Compute next step ---

        # Determine step size based on proximity to target
        distance_to_target = target_spl_db - measured_spl
        if distance_to_target <= FINE_THRESHOLD_DB:
            step_db = FINE_STEP_DB
        else:
            step_db = COARSE_STEP_DB

        # Hard cap: never step by more than MAX_STEP_DB
        step_db = min(step_db, MAX_STEP_DB)

        next_level = current_level_dbfs + step_db

        # Enforce thermal ceiling on next level
        if next_level > thermal_ceiling_dbfs:
            print(f"  (clamped to thermal ceiling {thermal_ceiling_dbfs:.1f} dBFS)")
            next_level = thermal_ceiling_dbfs

            # If we're already at the ceiling and still below target, we
            # can't go any higher — report the best we achieved.
            if current_level_dbfs >= thermal_ceiling_dbfs:
                reason = (f"thermal ceiling reached ({thermal_ceiling_dbfs:.1f} dBFS) "
                          f"but SPL only {measured_spl:.1f} dB "
                          f"(target {target_spl_db:.1f} dB)")
                print(f"\n  ABORT: {reason}")
                return CalibrationResult(
                    passed=False,
                    calibrated_level_dbfs=current_level_dbfs,
                    measured_spl_db=measured_spl,
                    steps_taken=step_num,
                    abort_reason=reason,
                )

        current_level_dbfs = next_level

    # Exhausted maximum steps
    reason = (f"max ramp steps ({MAX_RAMP_STEPS}) exhausted at "
              f"{current_level_dbfs:.1f} dBFS, SPL {last_measured_spl:.1f} dB "
              f"(target {target_spl_db:.1f} dB)")
    print(f"\n  ABORT: {reason}")
    return CalibrationResult(
        passed=False,
        calibrated_level_dbfs=current_level_dbfs,
        measured_spl_db=last_measured_spl,
        steps_taken=MAX_RAMP_STEPS,
        abort_reason=reason,
    )
