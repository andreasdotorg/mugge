"""
Multi-position spatial averaging for room correction measurements.

When measuring room acoustics, multiple measurements at slightly different
positions around the listening area are averaged to produce a correction
filter that works over a wider area rather than at one exact mic position.

Algorithm: magnitude averaging in dB domain with phase from the reference
(primary/center) measurement position, converted to minimum phase.
"""

import numpy as np
import soundfile as sf

from . import dsp_utils


def spatial_average(
    impulse_responses: list[np.ndarray],
    reference_index: int = 0,
) -> np.ndarray:
    """
    Average multiple measurement positions using magnitude averaging in dB.

    Takes the FFT of each impulse response, averages the magnitudes in the
    dB domain (which naturally reduces the impact of narrow position-dependent
    notches), uses phase from the reference position, and converts the result
    to minimum phase via the real cepstrum method.

    Parameters
    ----------
    impulse_responses : list of np.ndarray
        List of impulse response arrays. All must have the same length.
        Minimum 2 required.
    reference_index : int
        Index of the reference position for phase (default: 0).
        Typically the primary/center measurement position.

    Returns
    -------
    np.ndarray
        Averaged impulse response as a minimum-phase signal, same length
        as the input IRs.

    Raises
    ------
    ValueError
        If fewer than 2 IRs provided, lengths are mismatched, the list
        is empty, or reference_index is out of range.
    """
    if not impulse_responses:
        raise ValueError("No impulse responses provided (empty list).")
    if len(impulse_responses) < 2:
        raise ValueError(
            f"Need at least 2 impulse responses for spatial averaging, "
            f"got {len(impulse_responses)}."
        )

    ir_length = len(impulse_responses[0])
    for i, ir in enumerate(impulse_responses):
        if len(ir) != ir_length:
            raise ValueError(
                f"Impulse response length mismatch: IR[0] has {ir_length} "
                f"samples, IR[{i}] has {len(ir)} samples."
            )

    if not (0 <= reference_index < len(impulse_responses)):
        raise ValueError(
            f"reference_index {reference_index} out of range for "
            f"{len(impulse_responses)} impulse responses."
        )

    # FFT all impulse responses
    fft_results = [np.fft.rfft(np.asarray(ir, dtype=np.float64))
                   for ir in impulse_responses]

    # Extract magnitudes in dB
    epsilon = 1e-10
    magnitudes_db = np.array([
        20.0 * np.log10(np.abs(fft_result) + epsilon)
        for fft_result in fft_results
    ])

    # Average magnitudes in dB domain
    mean_db = np.mean(magnitudes_db, axis=0)

    # Convert back to linear magnitude
    mean_mag = 10.0 ** (mean_db / 20.0)

    # Use phase from reference position only
    phase = np.angle(fft_results[reference_index])

    # Reconstruct complex spectrum
    averaged_fft = mean_mag * np.exp(1j * phase)

    # Convert to minimum phase using the real cepstrum method (dsp_utils)
    # First get the time-domain signal, then apply minimum-phase conversion
    averaged_ir = np.fft.irfft(averaged_fft, n=ir_length)

    # Convert to minimum phase
    result = dsp_utils.to_minimum_phase(averaged_ir)

    return result


def spatial_average_from_files(
    file_paths: list[str],
    reference_index: int = 0,
) -> np.ndarray:
    """
    Load WAV files and compute spatial average.

    All files must have the same sample rate and number of samples.

    Parameters
    ----------
    file_paths : list of str
        Paths to WAV files containing impulse responses.
    reference_index : int
        Index of the reference position for phase (default: 0).

    Returns
    -------
    np.ndarray
        Averaged impulse response as a minimum-phase signal.

    Raises
    ------
    ValueError
        If fewer than 2 files, sample rates don't match, or lengths differ.
    FileNotFoundError
        If any file does not exist.
    """
    if len(file_paths) < 2:
        raise ValueError(
            f"Need at least 2 files for spatial averaging, "
            f"got {len(file_paths)}."
        )

    impulse_responses = []
    expected_sr = None

    for i, path in enumerate(file_paths):
        data, sr = sf.read(path, dtype='float64', always_2d=False)
        if data.ndim > 1:
            data = data[:, 0]
        if expected_sr is None:
            expected_sr = sr
        elif sr != expected_sr:
            raise ValueError(
                f"Sample rate mismatch: file[0] has {expected_sr}Hz, "
                f"file[{i}] has {sr}Hz."
            )
        impulse_responses.append(data)

    return spatial_average(impulse_responses, reference_index=reference_index)
