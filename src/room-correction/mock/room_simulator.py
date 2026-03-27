"""
Synthetic room impulse response generator using the image source method.

Generates realistic room impulse responses for testing the correction pipeline
without actual measurements. Models direct path, first through third order
reflections off six walls, room modes as resonant peaks, and optional noise.

The image source method works by "mirroring" the sound source across each
wall to create virtual sources. Each virtual source represents one reflection
path. The delay is the virtual source distance / speed of sound, and the
attenuation is 1/distance times the wall absorption loss per reflection.

Features (T-067-2):
    - Per-wall absorption coefficients (each wall can differ)
    - Frequency-dependent absorption (octave-band coefficients -> FIR per reflection)
    - 3rd-order reflections for rooms < 50 m^2
    - Accurate axial modes in 20-80 Hz range
    - Deterministic output: noise opt-in via noise_floor_dbfs parameter
"""

import numpy as np
import scipy.signal
import yaml

from room_correction import dsp_utils


SAMPLE_RATE = dsp_utils.SAMPLE_RATE
SPEED_OF_SOUND = 343.0  # m/s at ~20C

# Wall identifiers used for per-wall absorption.
WALL_NAMES = ("x0", "x1", "y0", "y1", "z0", "z1")

# Standard octave-band center frequencies (Hz) for frequency-dependent absorption.
OCTAVE_BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]


def load_room_config(config_path):
    """Load room configuration from a YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def distance(p1, p2):
    """Euclidean distance between two 3D points."""
    p1 = np.asarray(p1, dtype=np.float64)
    p2 = np.asarray(p2, dtype=np.float64)
    return np.sqrt(np.sum((p1 - p2) ** 2))


def _parse_wall_absorption(wall_absorption):
    """Normalize wall_absorption into a 6-element dict keyed by WALL_NAMES.

    Accepts:
        - float: uniform absorption for all walls
        - dict: per-wall values (missing walls use 0.3 default)

    Each value can be a float (broadband) or a list/dict of octave-band
    coefficients (frequency-dependent).

    Returns dict mapping wall name -> value (float or list).
    """
    if isinstance(wall_absorption, (int, float)):
        return {name: float(wall_absorption) for name in WALL_NAMES}
    if isinstance(wall_absorption, dict):
        result = {}
        for name in WALL_NAMES:
            result[name] = wall_absorption.get(name, 0.3)
        return result
    return {name: 0.3 for name in WALL_NAMES}


def _is_freq_dependent(abs_value):
    """Check if an absorption value is frequency-dependent (list or dict)."""
    return isinstance(abs_value, (list, dict))


def _abs_to_octave_array(abs_value):
    """Convert an absorption value to an array of octave-band coefficients.

    If scalar, returns uniform array. If list, uses directly. If dict,
    maps by OCTAVE_BANDS keys.
    """
    if isinstance(abs_value, (int, float)):
        return np.full(len(OCTAVE_BANDS), float(abs_value))
    if isinstance(abs_value, list):
        arr = np.array(abs_value, dtype=np.float64)
        if len(arr) < len(OCTAVE_BANDS):
            arr = np.pad(arr, (0, len(OCTAVE_BANDS) - len(arr)),
                         constant_values=arr[-1])
        return arr[:len(OCTAVE_BANDS)]
    if isinstance(abs_value, dict):
        return np.array([abs_value.get(f, 0.3) for f in OCTAVE_BANDS],
                        dtype=np.float64)
    return np.full(len(OCTAVE_BANDS), 0.3)


def _design_absorption_fir(abs_coeffs, n_taps=65, sr=SAMPLE_RATE):
    """Design an FIR filter that models frequency-dependent wall absorption.

    Takes octave-band absorption coefficients and creates an FIR filter whose
    magnitude at each octave band equals (1 - absorption) = reflection coefficient.

    Parameters
    ----------
    abs_coeffs : array_like
        Absorption coefficients at OCTAVE_BANDS frequencies (0 to 1).
    n_taps : int
        FIR filter length (odd for linear phase).
    sr : int
        Sample rate.

    Returns
    -------
    np.ndarray
        FIR filter coefficients.
    """
    abs_coeffs = np.asarray(abs_coeffs, dtype=np.float64)
    abs_coeffs = np.clip(abs_coeffs, 0.0, 0.999)

    reflection = 1.0 - abs_coeffs

    # Build frequency/gain pairs for firwin2, including DC and Nyquist.
    nyquist = sr / 2.0
    freqs = [0.0]
    gains = [float(reflection[0])]
    for i, f in enumerate(OCTAVE_BANDS):
        if f < nyquist:
            freqs.append(f / nyquist)
            gains.append(float(reflection[i]))
    freqs.append(1.0)
    gains.append(float(reflection[-1]))

    # Ensure monotonically increasing frequencies (dedup).
    clean_freqs = [freqs[0]]
    clean_gains = [gains[0]]
    for i in range(1, len(freqs)):
        if freqs[i] > clean_freqs[-1]:
            clean_freqs.append(freqs[i])
            clean_gains.append(gains[i])

    fir = scipy.signal.firwin2(n_taps, clean_freqs, clean_gains)
    return fir


# -- Image source enumeration --------------------------------------------------

# Each wall is defined by axis (0=x, 1=y, 2=z) and side (0=low, 1=high).
_WALL_DEFS = [
    (0, 0, "x0"),  # x=0 wall
    (0, 1, "x1"),  # x=Lx wall
    (1, 0, "y0"),  # y=0 wall
    (1, 1, "y1"),  # y=Ly wall
    (2, 0, "z0"),  # z=0 floor
    (2, 1, "z1"),  # z=Lz ceiling
]


def _reflect_point(pos, axis, side, room_dims):
    """Reflect a point across a wall. Returns the mirrored position."""
    pos = np.array(pos, dtype=np.float64)
    if side == 0:
        pos[axis] = -pos[axis]
    else:
        pos[axis] = 2 * room_dims[axis] - pos[axis]
    return pos


def image_sources_first_order(source, room_dims):
    """
    Compute first-order image source positions.

    For a rectangular room with dimensions (Lx, Ly, Lz), each wall produces
    one mirror image of the source. There are 6 walls -> 6 image sources.

    Returns list of (image_position, n_reflections) tuples.
    """
    sx, sy, sz = source
    lx, ly, lz = room_dims
    images = []
    # Reflect across each of the 6 walls
    images.append((np.array([-sx, sy, sz]), 1))         # x=0 wall
    images.append((np.array([2*lx - sx, sy, sz]), 1))   # x=Lx wall
    images.append((np.array([sx, -sy, sz]), 1))          # y=0 wall
    images.append((np.array([sx, 2*ly - sy, sz]), 1))    # y=Ly wall
    images.append((np.array([sx, sy, -sz]), 1))          # z=0 (floor)
    images.append((np.array([sx, sy, 2*lz - sz]), 1))   # z=Lz (ceiling)
    return images


def image_sources_second_order(source, room_dims):
    """
    Compute second-order image source positions.

    Second-order images are reflections of first-order images across walls
    they haven't already reflected off. This gives 30 additional image
    sources (6 first-order images x 5 remaining walls each).
    """
    first_order = image_sources_first_order(source, room_dims)
    second_order = []
    for img_pos, _ in first_order:
        for img2_pos, _ in image_sources_first_order(img_pos, room_dims):
            second_order.append((img2_pos, 2))
    return second_order


def _image_sources_with_walls(source, room_dims, max_order=2):
    """Compute image sources up to max_order, tracking which walls were hit.

    Returns list of (image_position, wall_sequence) where wall_sequence is
    a list of wall names hit in order (e.g. ["x0", "y1"]).
    """
    results = []
    # Start with the source at order 0 (no reflections).
    current = [(np.asarray(source, dtype=np.float64), [])]

    for _order in range(max_order):
        next_level = []
        for pos, walls_hit in current:
            for axis, side, wall_name in _WALL_DEFS:
                new_pos = _reflect_point(pos, axis, side, room_dims)
                new_walls = walls_hit + [wall_name]
                next_level.append((new_pos, new_walls))
        results.extend(next_level)
        current = next_level

    return results


def _compute_axial_modes(room_dims, speed, freq_min=20.0, freq_max=80.0):
    """Compute accurate axial room modes between freq_min and freq_max.

    Axial modes (n, 0, 0), (0, n, 0), (0, 0, n) occur at:
        f = (n * c) / (2 * L)

    Returns list of dicts: {frequency, q, gain} suitable for room_modes.
    """
    modes = []
    for dim_idx, L in enumerate(room_dims):
        if L <= 0:
            continue
        n = 1
        while True:
            freq = (n * speed) / (2.0 * L)
            if freq > freq_max:
                break
            if freq >= freq_min:
                # Q increases with frequency; lower modes are broader.
                q = 4.0 + freq / 10.0
                # Gain depends on room size: smaller rooms have stronger modes.
                # Base gain 10 dB, scaled by 1/sqrt(room_volume).
                vol = room_dims[0] * room_dims[1] * room_dims[2]
                gain = 10.0 * (50.0 / max(vol, 10.0)) ** 0.3
                gain = min(gain, 15.0)
                modes.append({
                    "frequency": round(freq, 2),
                    "q": round(q, 1),
                    "gain": round(gain, 1),
                })
            n += 1
    return modes


def generate_room_ir(
    speaker_pos,
    mic_pos,
    room_dims,
    wall_absorption=0.3,
    temperature=22.0,
    room_modes=None,
    include_second_order=True,
    include_third_order=None,
    ir_length=None,
    sr=SAMPLE_RATE,
    noise_floor_dbfs=None,
    auto_axial_modes=False,
):
    """
    Generate a synthetic room impulse response using the image source method.

    Steps:
    1. Compute direct path (distance -> delay, 1/r attenuation)
    2. Compute reflections (1st, 2nd, optionally 3rd order)
    3. Apply frequency-dependent absorption per reflection (if configured)
    4. Sum all paths into an impulse response
    5. Add room modes as biquad IIR resonances
    6. Optionally add noise floor

    Parameters
    ----------
    speaker_pos : array_like
        Speaker position [x, y, z] in meters.
    mic_pos : array_like
        Microphone position [x, y, z] in meters.
    room_dims : array_like
        Room dimensions [length, width, height] in meters.
    wall_absorption : float or dict
        Wall absorption coefficient(s). Float for uniform, dict for per-wall.
        Per-wall values can be float (broadband) or list (octave-band).
    temperature : float
        Temperature in Celsius (affects speed of sound).
    room_modes : list of dict, optional
        Room modes as [{frequency, q, gain}, ...].
    include_second_order : bool
        Whether to include second-order reflections.
    include_third_order : bool or None
        Whether to include third-order reflections. None = auto (True for
        rooms < 50 m^2 floor area).
    ir_length : int, optional
        Length of the output IR in samples. Default: 0.5s.
    sr : int
        Sample rate.
    noise_floor_dbfs : float or None
        Noise floor level in dBFS. None = no noise (deterministic output).
    auto_axial_modes : bool
        If True, automatically compute axial room modes in 20-80 Hz range
        and add them to any explicitly provided room_modes.

    Returns
    -------
    np.ndarray
        Synthetic room impulse response.
    """
    # Temperature-dependent speed of sound
    speed = 331.3 + 0.606 * temperature

    if ir_length is None:
        ir_length = int(0.5 * sr)

    ir = np.zeros(ir_length, dtype=np.float64)

    # Parse per-wall absorption.
    wall_abs = _parse_wall_absorption(wall_absorption)
    has_freq_dep = any(_is_freq_dependent(v) for v in wall_abs.values())

    # Pre-compute FIR filters for frequency-dependent walls.
    wall_firs = {}
    if has_freq_dep:
        for wname, absval in wall_abs.items():
            if _is_freq_dependent(absval):
                wall_firs[wname] = _design_absorption_fir(
                    _abs_to_octave_array(absval), sr=sr)

    # Broadband reflection coefficients per wall.
    wall_refl = {}
    for wname, absval in wall_abs.items():
        if isinstance(absval, (int, float)):
            wall_refl[wname] = 1.0 - float(absval)
        else:
            # For freq-dependent walls, use mean absorption as broadband fallback.
            arr = _abs_to_octave_array(absval)
            wall_refl[wname] = float(1.0 - np.mean(arr))

    # Determine reflection order.
    floor_area = room_dims[0] * room_dims[1]
    if include_third_order is None:
        include_third_order = floor_area < 50.0
    max_order = 1
    if include_second_order:
        max_order = 2
    if include_third_order:
        max_order = 3

    # -- Direct path --
    d = distance(speaker_pos, mic_pos)
    delay_samples = int(d / speed * sr)
    attenuation = 1.0 / max(d, 0.01)  # 1/r law
    if delay_samples < ir_length:
        ir[delay_samples] += attenuation

    # -- Reflections with per-wall tracking --
    all_images = _image_sources_with_walls(speaker_pos, room_dims, max_order)

    for img_pos, wall_seq in all_images:
        d = distance(img_pos, mic_pos)
        delay_samples = int(d / speed * sr)
        if delay_samples < 0 or delay_samples >= ir_length:
            continue

        # Compute broadband attenuation: product of per-wall reflection coeffs.
        refl_product = 1.0
        for wname in wall_seq:
            refl_product *= wall_refl[wname]
        attenuation = refl_product / max(d, 0.01)

        if has_freq_dep and any(w in wall_firs for w in wall_seq):
            # Frequency-dependent: place an impulse, then filter it through
            # the cascaded wall absorption FIRs.
            impulse = np.zeros(ir_length, dtype=np.float64)
            impulse[delay_samples] = 1.0 / max(d, 0.01)
            for wname in wall_seq:
                if wname in wall_firs:
                    impulse = scipy.signal.fftconvolve(
                        impulse, wall_firs[wname], mode='full')[:ir_length]
                else:
                    impulse *= wall_refl[wname]
            ir += impulse
        else:
            ir[delay_samples] += attenuation

    # -- Room modes (resonant peaks via biquad IIR) --
    # Auto-compute axial modes if requested.
    all_modes = list(room_modes) if room_modes else []
    if auto_axial_modes:
        axial = _compute_axial_modes(room_dims, speed)
        # Avoid duplicates: skip auto modes that are close to explicit ones.
        existing_freqs = {m['frequency'] for m in all_modes}
        for mode in axial:
            if not any(abs(mode['frequency'] - ef) < 2.0 for ef in existing_freqs):
                all_modes.append(mode)

    if all_modes:
        for mode in all_modes:
            freq = mode['frequency']
            q = mode['q']
            gain_db = mode['gain']
            if freq <= 0 or freq >= sr / 2:
                continue
            # Design a peaking EQ biquad
            b, a = scipy.signal.iirpeak(freq / (sr / 2), q)
            gain_linear = dsp_utils.db_to_linear(gain_db)
            # Apply the mode as a resonance on the IR
            mode_ir = scipy.signal.lfilter(b * gain_linear, a, ir)
            ir = ir + mode_ir

    # -- Optional noise floor --
    if noise_floor_dbfs is not None:
        noise_level = dsp_utils.db_to_linear(noise_floor_dbfs) * np.max(np.abs(ir))
        ir += noise_level * np.random.RandomState(42).randn(ir_length)

    # Normalize peak to 1.0
    peak = np.max(np.abs(ir))
    if peak > 0:
        ir /= peak

    return ir


def simulate_measurement(sweep, speaker_pos, mic_pos, room_config, sr=SAMPLE_RATE):
    """
    Simulate a full measurement: convolve sweep with synthetic room IR.

    This produces what the microphone would record if the sweep were played
    through a speaker in the simulated room.

    Parameters
    ----------
    sweep : np.ndarray
        The excitation sweep signal.
    speaker_pos : array_like
        Speaker position.
    mic_pos : array_like
        Microphone position.
    room_config : dict
        Room configuration dictionary (from room_config.yml).
    sr : int
        Sample rate.

    Returns
    -------
    tuple of (np.ndarray, np.ndarray)
        (simulated_recording, room_ir) — both as float64 arrays.
    """
    room = room_config.get('room', {})
    room_dims = room.get('dimensions', [8.0, 6.0, 3.0])
    wall_abs = room.get('wall_absorption', 0.3)
    temp = room.get('temperature', 22.0)
    modes = room_config.get('room_modes', None)
    noise = room.get('noise_floor_dbfs', None)

    room_ir = generate_room_ir(
        speaker_pos=speaker_pos,
        mic_pos=mic_pos,
        room_dims=room_dims,
        wall_absorption=wall_abs,
        temperature=temp,
        room_modes=modes,
        noise_floor_dbfs=noise,
        sr=sr,
    )

    # Convolve sweep with room IR to simulate recording
    recording = dsp_utils.convolve_fir(sweep, room_ir)

    return recording, room_ir
