"""
Synthetic room impulse response generator using the image source method.

Generates realistic room impulse responses for testing the correction pipeline
without actual measurements. Models direct path, first and second order
reflections off six walls, room modes as resonant peaks, and a noise floor.

The image source method works by "mirroring" the sound source across each
wall to create virtual sources. Each virtual source represents one reflection
path. The delay is the virtual source distance / speed of sound, and the
attenuation is 1/distance times the wall absorption loss per reflection.
"""

import numpy as np
import scipy.signal
import yaml

from room_correction import dsp_utils


SAMPLE_RATE = dsp_utils.SAMPLE_RATE
SPEED_OF_SOUND = 343.0  # m/s at ~20C


def load_room_config(config_path):
    """Load room configuration from a YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def distance(p1, p2):
    """Euclidean distance between two 3D points."""
    p1 = np.asarray(p1, dtype=np.float64)
    p2 = np.asarray(p2, dtype=np.float64)
    return np.sqrt(np.sum((p1 - p2) ** 2))


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


def generate_room_ir(
    speaker_pos,
    mic_pos,
    room_dims,
    wall_absorption=0.3,
    temperature=22.0,
    room_modes=None,
    include_second_order=True,
    ir_length=None,
    sr=SAMPLE_RATE,
):
    """
    Generate a synthetic room impulse response using the image source method.

    Steps:
    1. Compute direct path (distance -> delay, 1/r attenuation)
    2. Compute first-order reflections (6 image sources)
    3. Optionally compute second-order reflections (30 image sources)
    4. Sum all paths into an impulse response
    5. Add room modes as biquad IIR resonances
    6. Add noise floor at -60dB

    Parameters
    ----------
    speaker_pos : array_like
        Speaker position [x, y, z] in meters.
    mic_pos : array_like
        Microphone position [x, y, z] in meters.
    room_dims : array_like
        Room dimensions [length, width, height] in meters.
    wall_absorption : float
        Wall absorption coefficient (0 = perfectly reflective, 1 = anechoic).
    temperature : float
        Temperature in Celsius (affects speed of sound).
    room_modes : list of dict, optional
        Room modes as [{frequency, q, gain}, ...].
    include_second_order : bool
        Whether to include second-order reflections.
    ir_length : int, optional
        Length of the output IR in samples. Default: 0.5s.
    sr : int
        Sample rate.

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

    # Reflection coefficient per wall hit
    reflection_coeff = 1.0 - wall_absorption

    # -- Direct path --
    d = distance(speaker_pos, mic_pos)
    delay_samples = int(d / speed * sr)
    attenuation = 1.0 / max(d, 0.01)  # 1/r law
    if delay_samples < ir_length:
        ir[delay_samples] += attenuation

    # -- First-order reflections --
    for img_pos, n_refl in image_sources_first_order(speaker_pos, room_dims):
        d = distance(img_pos, mic_pos)
        delay_samples = int(d / speed * sr)
        attenuation = (reflection_coeff ** n_refl) / max(d, 0.01)
        if 0 <= delay_samples < ir_length:
            ir[delay_samples] += attenuation

    # -- Second-order reflections --
    if include_second_order:
        for img_pos, n_refl in image_sources_second_order(speaker_pos, room_dims):
            d = distance(img_pos, mic_pos)
            delay_samples = int(d / speed * sr)
            attenuation = (reflection_coeff ** n_refl) / max(d, 0.01)
            if 0 <= delay_samples < ir_length:
                ir[delay_samples] += attenuation

    # -- Room modes (resonant peaks via biquad IIR) --
    if room_modes:
        for mode in room_modes:
            freq = mode['frequency']
            q = mode['q']
            gain_db = mode['gain']
            # Design a peaking EQ biquad
            b, a = scipy.signal.iirpeak(freq / (sr / 2), q)
            gain_linear = dsp_utils.db_to_linear(gain_db)
            # Apply the mode as a resonance on the IR
            mode_ir = scipy.signal.lfilter(b * gain_linear, a, ir)
            ir = ir + mode_ir

    # -- Noise floor at -60dB --
    noise_level = dsp_utils.db_to_linear(-60) * np.max(np.abs(ir))
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

    room_ir = generate_room_ir(
        speaker_pos=speaker_pos,
        mic_pos=mic_pos,
        room_dims=room_dims,
        wall_absorption=wall_abs,
        temperature=temp,
        room_modes=modes,
        sr=sr,
    )

    # Convolve sweep with room IR to simulate recording
    recording = dsp_utils.convolve_fir(sweep, room_ir)

    return recording, room_ir
