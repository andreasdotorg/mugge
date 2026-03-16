"""
Time alignment: detect speaker arrival times and compute delay compensation.

For a multi-speaker system (mains + subs), each speaker is at a different
distance from the listener. Sound from the closer speaker arrives first.
Without compensation, the signals from different speakers arrive at different
times, causing comb filtering in the crossover region.

Solution: delay the closer speakers so all arrivals are synchronized. The
furthest speaker is the reference (zero delay); all others get positive delay.

Detection method: find the onset of energy in each speaker's impulse response
by looking for the first sample that exceeds a threshold above the noise floor.
"""

import logging
import warnings

import numpy as np

from . import dsp_utils


logger = logging.getLogger(__name__)


SAMPLE_RATE = dsp_utils.SAMPLE_RATE


def detect_arrival_time(ir, threshold_db=-20.0, sr=SAMPLE_RATE):
    """
    Detect the arrival time of sound in an impulse response.

    Finds the first sample where the energy exceeds threshold_db relative
    to the peak. This corresponds to the direct sound arrival.

    Parameters
    ----------
    ir : np.ndarray
        Impulse response.
    threshold_db : float
        Detection threshold relative to peak (negative dB).
    sr : int
        Sample rate.

    Returns
    -------
    float
        Arrival time in seconds.
    """
    ir = np.asarray(ir, dtype=np.float64)
    envelope = np.abs(ir)
    peak = np.max(envelope)

    if peak == 0:
        return 0.0

    threshold_linear = peak * dsp_utils.db_to_linear(threshold_db)

    # Find first sample exceeding threshold
    indices = np.where(envelope >= threshold_linear)[0]
    if len(indices) == 0:
        return 0.0

    arrival_sample = indices[0]
    return arrival_sample / sr


def compute_delays(impulse_responses, sr=SAMPLE_RATE):
    """
    Compute delay compensation values for multiple speakers.

    The furthest speaker (latest arrival) becomes the reference with zero
    delay. All other speakers get positive delay to align their arrivals.

    Parameters
    ----------
    impulse_responses : dict
        Mapping of speaker name to impulse response array.
    sr : int
        Sample rate.

    Returns
    -------
    dict
        Mapping of speaker name to delay in seconds.
    """
    arrivals = {}
    for name, ir in impulse_responses.items():
        arrivals[name] = detect_arrival_time(ir, sr=sr)

    # Reference is the latest arrival (furthest speaker)
    max_arrival = max(arrivals.values())

    delays = {}
    for name, arrival in arrivals.items():
        delays[name] = max_arrival - arrival

    return delays


def delays_to_samples(delays, sr=SAMPLE_RATE):
    """
    Convert delay values from seconds to samples.

    Parameters
    ----------
    delays : dict
        Mapping of speaker name to delay in seconds.
    sr : int
        Sample rate.

    Returns
    -------
    dict
        Mapping of speaker name to delay in samples (integer).
    """
    return {name: int(round(delay * sr)) for name, delay in delays.items()}


# Maximum delay difference before warning (50 ms)
_MAX_DELAY_DIFF_MS = 50.0


def compute_delays_for_camilladsp(arrival_times: dict[str, float]) -> dict[str, float]:
    """
    Compute delay values compatible with CamillaDSP YAML format.

    The furthest speaker (latest arrival) is the reference with delay 0.
    All other speakers receive positive delay in milliseconds to align
    their arrivals with the reference.

    Edge cases
    ----------
    - Single speaker: returns {name: 0.0}.
    - All identical arrival times: all delays are 0.0.
    - Negative or zero arrival times: raises ValueError.
    - Delay difference > 50 ms: warns but proceeds.

    Parameters
    ----------
    arrival_times : dict[str, float]
        Mapping of channel name to arrival time in seconds.
        All values must be strictly positive.

    Returns
    -------
    dict[str, float]
        Mapping of channel name to delay in milliseconds.

    Raises
    ------
    ValueError
        If any arrival time is negative or zero, or if the dict is empty.
    """
    if not arrival_times:
        raise ValueError("arrival_times must not be empty")

    for name, t in arrival_times.items():
        if t <= 0.0:
            raise ValueError(
                f"Arrival time for '{name}' must be strictly positive, got {t}"
            )

    # Single speaker: no alignment needed
    if len(arrival_times) == 1:
        name = next(iter(arrival_times))
        return {name: 0.0}

    max_arrival = max(arrival_times.values())

    delays_ms = {}
    for name, arrival in arrival_times.items():
        delays_ms[name] = (max_arrival - arrival) * 1000.0

    # Warn if any delay exceeds threshold
    max_delay_ms = max(delays_ms.values())
    if max_delay_ms > _MAX_DELAY_DIFF_MS:
        warnings.warn(
            f"Large delay difference detected: {max_delay_ms:.1f} ms "
            f"(threshold: {_MAX_DELAY_DIFF_MS:.0f} ms). "
            f"Check speaker placement.",
            stacklevel=2,
        )

    return delays_ms
