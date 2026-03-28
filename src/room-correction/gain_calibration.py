"""Automated per-channel gain calibration ramp for measurement.

Slowly ramps from silence to the target SPL level using band-limited pink
noise bursts, with mic-based safety gating. This is run before each
measurement to find the correct digital output level for the desired SPL at
the mic position.

Safety architecture (5-layer defense-in-depth):
  Layer 1: Digital hard cap from thermal_ceiling module (never exceed thermal
           ceiling regardless of target SPL)
  Layer 2: GraphManager measurement mode routing (D-040) — signal-gen only
           outputs on the test channel; all others are silent
  Layer 3: Mic input near-clipping detection (abort if peak >= -3.0 dBFS)
  Layer 4: Mic SPL gate (abort if measured SPL > hard_limit_spl_db)
  Layer 5: Slow ramp + operator presence (3 dB max step, 2s bursts)

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
import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Optional

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

# Maximum overshoot back-off verification attempts (GC-01)
MAX_OVERSHOOT_RETRIES = 3

# Maximum xrun retries per burst before aborting (GC-02)
MAX_XRUN_RETRIES = 2

# Expected measurement attenuation (GC-07/11). In D-040 architecture,
# this is applied by the signal generator's output level, not by a DSP
# config. Retained for the safety verification logic.
EXPECTED_MEASUREMENT_ATTENUATION_DB = -20.0

# Pink noise parameters (same as measure_nearfield.py)
PINK_NOISE_F_LOW = 100.0
PINK_NOISE_F_HIGH = 10000.0

SAMPLE_RATE = 48000

# Ambient noise baseline constants (TK-200)
AMBIENT_RECORD_DURATION_S = 2.0
AMBIENT_SPL_ABORT_THRESHOLD = 81.0   # Abort if ambient SPL > 81 dB
AMBIENT_SPL_WARN_THRESHOLD = 60.0    # Warn if ambient SPL > 60 dB
BURST_SNR_MIN_DB = 10.0              # Minimum burst SNR above ambient
BURST_SNR_LEVEL_THRESHOLD_DBFS = -40.0  # Only check SNR above this output level

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
    abort_reason: Optional[str] = None


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

    # 10ms cosine taper fade-in/fade-out to avoid click transients at buffer edges
    fade_samples = int(0.01 * sr)  # 10ms
    if fade_samples > 0 and len(pink) > 2 * fade_samples:
        fade_in = np.cos(np.linspace(np.pi, 2 * np.pi, fade_samples)) * 0.5 + 0.5
        fade_out = fade_in[::-1]
        pink[:fade_samples] *= fade_in
        pink[-fade_samples:] *= fade_out

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
# PipeWire xrun detection (GC-02, extracted from measure_nearfield.py)
# ---------------------------------------------------------------------------

def get_pipewire_xrun_count():
    """Query PipeWire xrun counter via pw-cli or pw-dump.

    Returns
    -------
    int or None
        Xrun count, or None if not determinable (mock mode, missing tools).
    """
    # Method 1: pw-cli info all
    try:
        result = subprocess.run(
            ["pw-cli", "info", "all"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            xrun_total = 0
            for line in result.stdout.split('\n'):
                line_stripped = line.strip()
                if 'xrun' in line_stripped.lower():
                    parts = line_stripped.split('=')
                    if len(parts) >= 2:
                        try:
                            xrun_total += int(parts[-1].strip().strip('"'))
                        except ValueError:
                            pass
            return xrun_total
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Method 2: pw-dump JSON output
    try:
        result = subprocess.run(
            ["pw-dump"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            xrun_total = 0
            for obj in data:
                props = obj.get('info', {}).get('props', {})
                xruns = props.get('clock.xrun-count', 0)
                if isinstance(xruns, int):
                    xrun_total += xruns
            return xrun_total
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    return None


# ---------------------------------------------------------------------------
# GraphManager measurement mode verification (GC-07/11, D-040)
# ---------------------------------------------------------------------------

def verify_measurement_mode(gm_client):
    """Verify GraphManager is in measurement mode (D-040).

    In the D-040 architecture, measurement attenuation is handled by the
    signal generator (only emitting on the test channel) rather than a
    DSP config. This function verifies that the GraphManager has established
    the measurement routing topology.

    Parameters
    ----------
    gm_client : GraphManagerClient or MockGraphManagerClient
        Connected GraphManager client.

    Raises
    ------
    RuntimeError
        If GraphManager is not in measurement mode.
    """
    gm_client.verify_measurement_mode()


# ---------------------------------------------------------------------------
# Core play-and-record burst
# ---------------------------------------------------------------------------

def _play_burst(noise_signal, channel_index, output_device, input_device,
                sr=SAMPLE_RATE, pre_roll_s=0.5, signal_gen=None,
                capture_target=None):
    """Play a noise burst on one channel and record from the mic.

    Two modes of operation:

    **pw-record mode** (when ``signal_gen`` is provided):
        Uses ``pw_capture.start_capture()`` to record from the UMIK-1 PW
        source node via ``pw-record``, then ``signal_gen.play()`` to send
        pink noise through the signal generator RPC.  This is the
        production and local-demo path (US-067 Track A).

    **Legacy sd.playrec mode** (when ``signal_gen`` is None):
        Falls back to the old sounddevice ``playrec()`` pattern for mock
        mode and standalone CLI use.

    Parameters
    ----------
    noise_signal : np.ndarray
        The pink noise burst to play (mono, float).
    channel_index : int
        0-indexed output channel.
    output_device : int or str or None
        Sounddevice output device identifier (legacy mode only).
    input_device : int or str or None
        Sounddevice input device identifier (legacy mode only).
    sr : int
        Sample rate.
    pre_roll_s : float
        Seconds of silence before signal (legacy mode).  In pw-record
        mode, pw-record is started before play begins so no pre-roll
        is needed in the output buffer.
    signal_gen : SignalGenClient or None
        When provided, uses separated play + pw-record capture pattern.
    capture_target : str or None
        PipeWire node name for pw-record capture (e.g.
        ``"alsa_input.usb-miniDSP_UMIK-1"``).  Required when
        ``signal_gen`` is not None.

    Returns
    -------
    np.ndarray
        Mono recording from the mic (float64), trimmed to signal portion.
    """
    if signal_gen is not None:
        return _play_burst_pw_capture(
            noise_signal, channel_index, sr, signal_gen, capture_target)

    # Legacy sd.playrec path (mock mode / standalone CLI)
    sd = _sd_override
    if sd is None:
        import sounddevice as sd

    if output_device is None:
        out_info = sd.query_devices(kind='output')
    else:
        out_info = sd.query_devices(output_device)
    n_out_channels = out_info['max_output_channels']

    if channel_index >= n_out_channels:
        raise ValueError(
            f"Channel {channel_index} exceeds device capacity "
            f"({n_out_channels} channels on '{out_info['name']}')")

    pre_roll_samples = int(pre_roll_s * sr)

    # Build multi-channel output: pre-roll silence + signal on target channel
    output_buffer = np.zeros((pre_roll_samples + len(noise_signal), n_out_channels),
                             dtype=np.float32)
    output_buffer[pre_roll_samples:, channel_index] = noise_signal.astype(np.float32)

    recording = sd.playrec(
        output_buffer,
        samplerate=sr,
        input_mapping=[1],  # UMIK-1 channel 1 (mono)
        device=(input_device, output_device),
        dtype='float32',
    )
    sd.wait()

    # Trim pre-roll: return only the signal-aligned recording
    return recording[pre_roll_samples:, 0].astype(np.float64)


def _play_burst_pw_capture(noise_signal, channel_index, sr, signal_gen,
                           capture_target):
    """Play a burst via signal-gen RPC and capture via pw-record.

    Separated play + capture pattern (US-067 Track A).  The signal
    generator plays the noise on the specified channel while pw-record
    captures from the UMIK-1 PW source node simultaneously.
    """
    from pw_capture import start_capture, stop_capture, load_wav

    duration_s = len(noise_signal) / sr

    # Compute signal level (RMS in dBFS) for the signal-gen play RPC.
    rms = np.sqrt(np.mean(noise_signal.astype(np.float64) ** 2))
    if rms > 0:
        level_dbfs = float(np.floor(20.0 * np.log10(rms) * 10) / 10)
    else:
        level_dbfs = -60.0
    level_dbfs = max(-60.0, min(-0.5, level_dbfs))

    # Create a temporary WAV file for pw-record output.
    cap_fd, cap_path = tempfile.mkstemp(suffix=".wav", prefix="gc_cap_")
    os.close(cap_fd)

    try:
        # 1. Start capture (pw-record begins writing to WAV file)
        proc = start_capture(
            output_path=cap_path,
            target=capture_target or "alsa_input.usb-miniDSP_UMIK-1",
            sample_rate=sr,
            channels=1,
        )

        try:
            # 2. Play pink noise via signal-gen RPC (play-only, no record)
            signal_gen.play(
                signal="pink",
                channels=[channel_index + 1],  # 1-indexed for RPC
                level_dbfs=level_dbfs,
                duration=duration_s,
            )

            # 3. Wait for playback to complete + decay margin
            time.sleep(duration_s + 0.3)
        finally:
            # 4. Stop capture (SIGINT -> pw-record finalizes WAV)
            stop_capture(proc)

        # 5. Load the captured audio
        recording = load_wav(cap_path)
        # Return mono float64, trimmed to signal duration
        n_signal = len(noise_signal)
        rec = recording[:, 0].astype(np.float64)
        if len(rec) > n_signal:
            rec = rec[:n_signal]
        return rec
    finally:
        try:
            os.unlink(cap_path)
        except OSError:
            pass


def _play_burst_with_xrun_check(noise_signal, channel_index, output_device,
                                input_device, sr=SAMPLE_RATE,
                                signal_gen=None, capture_target=None):
    """Play a burst with PipeWire xrun detection and retry (GC-02).

    Wraps ``_play_burst`` with xrun counter checks. If an xrun is detected
    during playback, retries the same burst (same level, NOT the next step)
    up to MAX_XRUN_RETRIES times.

    Parameters
    ----------
    noise_signal : np.ndarray
        The pink noise burst to play (mono, float).
    channel_index : int
        0-indexed output channel.
    output_device : int or str or None
        Sounddevice output device identifier (legacy mode only).
    input_device : int or str or None
        Sounddevice input device identifier (legacy mode only).
    sr : int
        Sample rate.
    signal_gen : SignalGenClient or None
        When provided, uses separated play + pw-record capture pattern.
    capture_target : str or None
        PipeWire node name for pw-record capture.

    Returns
    -------
    np.ndarray or None
        Mono recording from the mic (float64), or None if xruns persisted
        after all retries.
    """
    for attempt in range(1, MAX_XRUN_RETRIES + 2):  # +2: 1 initial + retries
        xrun_before = get_pipewire_xrun_count()

        recording = _play_burst(
            noise_signal, channel_index, output_device, input_device, sr=sr,
            signal_gen=signal_gen, capture_target=capture_target)

        xrun_after = get_pipewire_xrun_count()

        # If xrun counting is unavailable, accept the recording
        if xrun_before is None or xrun_after is None:
            return recording

        xrun_delta = xrun_after - xrun_before
        if xrun_delta <= 0:
            return recording

        # Xrun detected — retry if we have attempts remaining
        if attempt <= MAX_XRUN_RETRIES:
            print(f" [xrun detected (+{xrun_delta}), retrying {attempt}/{MAX_XRUN_RETRIES}]",
                  end="", flush=True)
            time.sleep(0.5)  # Brief pause before retry
        else:
            print(f" [xrun detected (+{xrun_delta}), retries exhausted]",
                  end="", flush=True)
            return None

    return None  # Should not reach here, but satisfy type checker


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
    gm_client=None,
    ws_server=None,
    channel_name=None,
    measurement_attenuation_db=0.0,
    signal_gen=None,
    capture_target=None,
    mic_clip_threshold_dbfs=-3.0,
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
    gm_client : GraphManagerClient or MockGraphManagerClient or None
        Connected GraphManager client for measurement mode verification
        (GC-07/11, D-040). If provided, the GM mode is checked to verify
        measurement routing is active before calibration starts. If None,
        the mode check is skipped (backwards-compatible standalone mode).
    ws_server : MeasurementWSServer or None
        Optional WebSocket server for broadcasting gain_cal progress
        messages to connected clients. When provided, broadcasts after
        each ramp step and checks for abort commands.
    channel_name : str or None
        Human-readable channel name (e.g., "Sub1") for WS messages.
        Defaults to "ch{channel_index}" if not provided.
    measurement_attenuation_db : float
        Measurement attenuation in dB (default 0.0, meaning no
        attenuation in standalone mode).  When called from the
        measurement session, pass the expected attenuation (e.g. -20.0).
        The ramp start level and SNR threshold are adjusted to
        compensate so the speaker sees the originally-designed levels.

    Returns
    -------
    CalibrationResult
        Result with calibrated level, measured SPL, and pass/fail status.

    Raises
    ------
    ValueError
        If target_spl_db >= hard_limit_spl_db (GC-05).
    RuntimeError
        If GraphManager is not in measurement mode (GC-07/11).
    """
    # GC-05: Validate that target is below hard limit
    if target_spl_db >= hard_limit_spl_db:
        raise ValueError(
            f"target_spl_db ({target_spl_db:.1f}) must be less than "
            f"hard_limit_spl_db ({hard_limit_spl_db:.1f})")

    # GC-07/11: Verify GraphManager measurement mode if client provided
    if gm_client is not None:
        print("  Verifying GraphManager measurement mode...")
        verify_measurement_mode(gm_client)
        print("  GraphManager measurement mode verified (routing active)")

    # Compensate for measurement attenuation so the speaker sees
    # the originally-designed levels.  E.g. with -20 dB attenuation, output
    # -40 dBFS → speaker -60 dBFS (the original START_LEVEL_DBFS intent).
    actual_start = START_LEVEL_DBFS - measurement_attenuation_db
    current_level_dbfs = actual_start

    # SNR threshold also shifts: check when the *speaker* level is above the
    # original design threshold, not the raw digital output level.
    effective_snr_threshold = BURST_SNR_LEVEL_THRESHOLD_DBFS - measurement_attenuation_db

    _ch_name = channel_name or f"ch{channel_index}"

    print("\n" + "=" * 60)
    print("GAIN CALIBRATION RAMP")
    print("=" * 60)
    print(f"  Channel:          {channel_index}")
    print(f"  Target SPL:       {target_spl_db:.1f} dB")
    print(f"  Hard limit SPL:   {hard_limit_spl_db:.1f} dB")
    print(f"  Thermal ceiling:  {thermal_ceiling_dbfs:.1f} dBFS")
    print(f"  Start level:      {current_level_dbfs:.1f} dBFS "
          f"(speaker: {current_level_dbfs + measurement_attenuation_db:.1f} dBFS)")
    print(f"  Burst duration:   {burst_duration_s:.1f}s")
    print()

    last_measured_spl = 0.0

    # Helper to broadcast gain_cal WS messages when server is available.
    def _ws_broadcast_gain_cal(step, spl_db, state, xrun_count=0):
        if ws_server is not None:
            ws_server.broadcast({
                "type": "gain_cal",
                "channel": channel_index,
                "channel_name": _ch_name,
                "step": step,
                "level_dbfs": current_level_dbfs,
                "spl_db": spl_db,
                "target_spl_db": target_spl_db,
                "hard_limit_spl_db": hard_limit_spl_db,
                "thermal_ceiling_dbfs": thermal_ceiling_dbfs,
                "state": state,
                "xrun_count": xrun_count,
            })

    # TK-200: Record ambient noise baseline before ramp loop.
    # F-165: Ensure signal-gen is silent before measuring ambient noise.
    # Without this, pw-record's settle time captures residual audio from
    # any previous signal-gen state (e.g. test tab WebSocket proxy).
    if signal_gen is not None:
        signal_gen.stop()
        time.sleep(0.3)  # Let PW graph settle after stop

    print("  Recording ambient noise baseline (2s silence)...", end="", flush=True)
    ambient_silence = np.zeros(int(AMBIENT_RECORD_DURATION_S * sample_rate),
                               dtype=np.float64)
    ambient_recording = _play_burst(
        ambient_silence, channel_index, output_device, input_device,
        sr=sample_rate, signal_gen=signal_gen, capture_target=capture_target)
    ambient_rms = np.sqrt(np.mean(ambient_recording ** 2))
    ambient_rms_dbfs = 20.0 * np.log10(max(ambient_rms, 1e-10))
    ambient_spl = ambient_rms_dbfs + umik_sensitivity_dbfs_to_spl
    print(f" ambient: {ambient_spl:.1f} dB SPL ({ambient_rms_dbfs:.1f} dBFS RMS)")

    if ambient_spl > AMBIENT_SPL_ABORT_THRESHOLD:
        reason = (f"ambient noise too high ({ambient_spl:.1f} dB SPL "
                  f"> {AMBIENT_SPL_ABORT_THRESHOLD:.0f} dB threshold)")
        print(f"\n  ABORT: {reason}")
        _ws_broadcast_gain_cal(0, ambient_spl, "ambient_too_high")
        return CalibrationResult(
            passed=False,
            calibrated_level_dbfs=current_level_dbfs,
            measured_spl_db=ambient_spl,
            steps_taken=0,
            abort_reason=reason,
        )

    if ambient_spl > AMBIENT_SPL_WARN_THRESHOLD:
        print(f"  WARNING: Elevated ambient noise ({ambient_spl:.1f} dB SPL "
              f"> {AMBIENT_SPL_WARN_THRESHOLD:.0f} dB)")
        if ws_server is not None:
            ws_server.broadcast({
                "type": "gain_cal_warning",
                "channel": channel_index,
                "channel_name": _ch_name,
                "warning": f"Elevated ambient noise: {ambient_spl:.1f} dB SPL",
                "ambient_spl": ambient_spl,
            })

    # Pre-generate reference pink noise buffer at a safe level, then scale per step.
    # This avoids CPU-expensive FFT + Butterworth filter per ramp step on the Pi.
    # Use -20 dBFS to avoid clipping (pink noise crest factor ~12 dB).
    _REFERENCE_LEVEL_DBFS = -20.0
    reference_noise = _generate_pink_noise(burst_duration_s, sr=sample_rate,
                                           level_dbfs=_REFERENCE_LEVEL_DBFS,
                                           f_low=PINK_NOISE_F_LOW,
                                           f_high=PINK_NOISE_F_HIGH)

    # GC-07/11: Wrap in try/finally for cleanup on abort
    try:
        for step_num in range(1, MAX_RAMP_STEPS + 1):
            # Check for WS abort before each step
            if ws_server is not None and ws_server.abort_requested:
                reason = "operator abort"
                print(f"\n  ABORT: {reason}")
                _ws_broadcast_gain_cal(step_num, last_measured_spl, "aborted")
                return CalibrationResult(
                    passed=False,
                    calibrated_level_dbfs=current_level_dbfs,
                    measured_spl_db=last_measured_spl,
                    steps_taken=step_num,
                    abort_reason=reason,
                )

            # Safety: never exceed thermal ceiling
            if current_level_dbfs > thermal_ceiling_dbfs:
                current_level_dbfs = thermal_ceiling_dbfs

            print(f"  Step {step_num}: playing at {current_level_dbfs:.1f} dBFS ...",
                  end="", flush=True)

            # Scale pre-generated reference noise to this level
            scale = 10.0 ** ((current_level_dbfs - _REFERENCE_LEVEL_DBFS) / 20.0)
            noise = np.clip(reference_noise * scale, -1.0, 1.0)

            # GC-02: Play burst with xrun detection and retry
            recording = _play_burst_with_xrun_check(
                noise, channel_index, output_device, input_device,
                sr=sample_rate, signal_gen=signal_gen,
                capture_target=capture_target)
            if recording is None:
                reason = "persistent xruns during calibration"
                print(f"\n  ABORT: {reason}")
                return CalibrationResult(
                    passed=False,
                    calibrated_level_dbfs=current_level_dbfs,
                    measured_spl_db=last_measured_spl,
                    steps_taken=step_num,
                    abort_reason=reason,
                )

            # Compute SPL from recording
            measured_spl, peak_dbfs = _compute_spl_from_recording(
                recording, umik_sensitivity_dbfs_to_spl)
            last_measured_spl = measured_spl

            # TK-200: Compute burst RMS dBFS for SNR check against ambient.
            burst_rms = np.sqrt(np.mean(recording ** 2))
            burst_rms_dbfs = 20.0 * np.log10(max(burst_rms, 1e-10))
            burst_snr = burst_rms_dbfs - ambient_rms_dbfs

            print(f" measured {measured_spl:.1f} dB SPL "
                  f"(mic peak {peak_dbfs:.1f} dBFS, SNR {burst_snr:.1f} dB)")

            # TK-200: Check burst SNR against ambient baseline.
            # Only check when effective speaker level is above the design
            # threshold (accounting for measurement attenuation).
            if (burst_snr < BURST_SNR_MIN_DB
                    and current_level_dbfs > effective_snr_threshold):
                reason = ("Speaker output not detected above ambient noise. "
                          "Verify PA is on and output routing is correct.")
                print(f"\n  ABORT: {reason} "
                      f"(SNR {burst_snr:.1f} dB < {BURST_SNR_MIN_DB:.0f} dB "
                      f"at {current_level_dbfs:.1f} dBFS)")
                _ws_broadcast_gain_cal(step_num, measured_spl, "low_snr")
                return CalibrationResult(
                    passed=False,
                    calibrated_level_dbfs=current_level_dbfs,
                    measured_spl_db=measured_spl,
                    steps_taken=step_num,
                    abort_reason=reason,
                )

            # Determine ramp state for WS message
            _distance = target_spl_db - measured_spl
            if _distance > FINE_THRESHOLD_DB:
                _ws_state = "ramping"
            else:
                _ws_state = "fine_stepping"

            # --- Safety gate checks ---

            # Check 1: Mic input near clipping (ADC saturation)
            _effective_clip = mic_clip_threshold_dbfs
            if peak_dbfs >= _effective_clip:
                reason = "mic input near clipping"
                print(f"\n  ABORT: {reason} (peak {peak_dbfs:.1f} dBFS >= {_effective_clip:.1f} dBFS)")
                _ws_broadcast_gain_cal(step_num, measured_spl, "mic_clipping")
                return CalibrationResult(
                    passed=False,
                    calibrated_level_dbfs=current_level_dbfs,
                    measured_spl_db=measured_spl,
                    steps_taken=step_num,
                    abort_reason=reason,
                )

            # Check 2: Mic silence (cable disconnected, wrong device)
            if peak_dbfs < MIC_SILENCE_PEAK_DBFS:
                reason = (f"mic not detecting signal (peak {peak_dbfs:.1f} dBFS "
                          f"< {MIC_SILENCE_PEAK_DBFS:.0f} dBFS threshold)")
                print(f"\n  ABORT: {reason}")
                _ws_broadcast_gain_cal(step_num, measured_spl, "mic_lost")
                return CalibrationResult(
                    passed=False,
                    calibrated_level_dbfs=current_level_dbfs,
                    measured_spl_db=measured_spl,
                    steps_taken=step_num,
                    abort_reason=reason,
                )

            # Check 3: Hard SPL limit exceeded
            if measured_spl >= hard_limit_spl_db:
                reason = (f"measured SPL {measured_spl:.1f} dB >= hard limit "
                          f"{hard_limit_spl_db:.1f} dB")
                print(f"\n  ABORT: {reason}")
                _ws_broadcast_gain_cal(step_num, measured_spl, "spl_limit")
                return CalibrationResult(
                    passed=False,
                    calibrated_level_dbfs=current_level_dbfs,
                    measured_spl_db=measured_spl,
                    steps_taken=step_num,
                    abort_reason=reason,
                )

            # Check 4: At target (within tolerance)?
            if abs(measured_spl - target_spl_db) <= SPL_TOLERANCE_DB:
                print(f"\n  TARGET REACHED: {measured_spl:.1f} dB SPL "
                      f"(target {target_spl_db:.1f} +/- {SPL_TOLERANCE_DB:.0f})")
                _ws_broadcast_gain_cal(step_num, measured_spl, "converged")
                return CalibrationResult(
                    passed=True,
                    calibrated_level_dbfs=current_level_dbfs,
                    measured_spl_db=measured_spl,
                    steps_taken=step_num,
                )

            # Check 5: Overshot target (above target + tolerance but below
            # hard limit). GC-01: verify the backed-off level before accepting.
            if measured_spl > target_spl_db + SPL_TOLERANCE_DB:
                backed_off = current_level_dbfs - FINE_STEP_DB
                print(f"\n  OVERSHOT: {measured_spl:.1f} dB > target "
                      f"{target_spl_db:.1f} dB. Backing off to "
                      f"{backed_off:.1f} dBFS.")

                # GC-01: Play verification bursts at backed-off level
                for verify_attempt in range(1, MAX_OVERSHOOT_RETRIES + 1):
                    print(f"  Verification burst {verify_attempt}/{MAX_OVERSHOOT_RETRIES} "
                          f"at {backed_off:.1f} dBFS ...", end="", flush=True)

                    verify_scale = 10.0 ** ((backed_off - _REFERENCE_LEVEL_DBFS) / 20.0)
                    verify_noise = np.clip(reference_noise * verify_scale, -1.0, 1.0)

                    verify_rec = _play_burst_with_xrun_check(
                        verify_noise, channel_index, output_device,
                        input_device, sr=sample_rate,
                        signal_gen=signal_gen,
                        capture_target=capture_target)
                    if verify_rec is None:
                        reason = "persistent xruns during calibration"
                        print(f"\n  ABORT: {reason}")
                        return CalibrationResult(
                            passed=False,
                            calibrated_level_dbfs=backed_off,
                            measured_spl_db=last_measured_spl,
                            steps_taken=step_num,
                            abort_reason=reason,
                        )

                    verify_spl, verify_peak = _compute_spl_from_recording(
                        verify_rec, umik_sensitivity_dbfs_to_spl)
                    last_measured_spl = verify_spl

                    print(f" measured {verify_spl:.1f} dB SPL")

                    # Check if verification burst is within tolerance
                    if abs(verify_spl - target_spl_db) <= SPL_TOLERANCE_DB:
                        print(f"\n  VERIFIED: {verify_spl:.1f} dB SPL at "
                              f"{backed_off:.1f} dBFS")
                        return CalibrationResult(
                            passed=True,
                            calibrated_level_dbfs=backed_off,
                            measured_spl_db=verify_spl,
                            steps_taken=step_num,
                        )

                    # Check if still too high
                    if verify_spl > target_spl_db + SPL_TOLERANCE_DB:
                        backed_off -= FINE_STEP_DB
                        print(f"  Still too high. Backing off further to "
                              f"{backed_off:.1f} dBFS.")
                        continue

                    # Below target after back-off — accept this level
                    # (we're within a reasonable range)
                    if verify_spl < target_spl_db - SPL_TOLERANCE_DB:
                        print(f"\n  VERIFIED (below target): {verify_spl:.1f} dB SPL "
                              f"at {backed_off:.1f} dBFS")
                        return CalibrationResult(
                            passed=True,
                            calibrated_level_dbfs=backed_off,
                            measured_spl_db=verify_spl,
                            steps_taken=step_num,
                        )

                # Exhausted verification retries
                reason = "could not converge to target after overshoot"
                print(f"\n  ABORT: {reason}")
                return CalibrationResult(
                    passed=False,
                    calibrated_level_dbfs=backed_off,
                    measured_spl_db=last_measured_spl,
                    steps_taken=step_num,
                    abort_reason=reason,
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
                    _ws_broadcast_gain_cal(step_num, measured_spl, "thermal_ceiling")
                    return CalibrationResult(
                        passed=False,
                        calibrated_level_dbfs=current_level_dbfs,
                        measured_spl_db=measured_spl,
                        steps_taken=step_num,
                        abort_reason=reason,
                    )

            # Broadcast current ramp progress via WS
            _ws_broadcast_gain_cal(step_num, measured_spl, _ws_state)

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
    finally:
        # GC-07/11: Ensure cleanup happens even on unexpected exceptions.
        # The caller (measure_nearfield.py) handles GraphManager mode
        # restoration. This finally block is for local resource cleanup.
        print("  Calibration ramp finished.")
