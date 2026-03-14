"""
Export combined filters as WAV files for CamillaDSP.

Handles final truncation, windowing, format conversion, and file output.
CamillaDSP reads filter coefficients from WAV files — it supports both
float32 and S32LE (32-bit signed integer). We use float32 for maximum
compatibility and dynamic range.

TK-166: Supports versioned (timestamped) filenames to bust CamillaDSP's
FIR coefficient cache on config.reload(). Without unique filenames,
CamillaDSP silently keeps old data even after the WAV file is overwritten.
"""

import os
from datetime import datetime

import numpy as np
import soundfile as sf

from . import dsp_utils


SAMPLE_RATE = dsp_utils.SAMPLE_RATE
DEFAULT_TAPS = 16384

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

# Channel names mapped to their unversioned filenames (fallback compatibility)
CHANNEL_FILENAMES = {
    'left_hp': 'combined_left_hp.wav',
    'right_hp': 'combined_right_hp.wav',
    'sub1_lp': 'combined_sub1_lp.wav',
    'sub2_lp': 'combined_sub2_lp.wav',
}


def versioned_filename(channel, timestamp=None):
    """
    Generate a versioned coefficient filename for a channel.

    Parameters
    ----------
    channel : str
        Channel name, e.g. 'left_hp', 'sub1_lp'.
    timestamp : datetime, optional
        Timestamp to embed. Defaults to datetime.now().

    Returns
    -------
    str
        Filename like 'combined_left_hp_20260314_143022.wav'.
    """
    if timestamp is None:
        timestamp = datetime.now()
    ts_str = timestamp.strftime(TIMESTAMP_FORMAT)
    return f"combined_{channel}_{ts_str}.wav"


def export_filter(fir_filter, output_path, n_taps=DEFAULT_TAPS, sr=SAMPLE_RATE):
    """
    Export a single FIR filter as a WAV file.

    Applies final truncation to n_taps with a fade-out window to avoid
    truncation artifacts (spectral splatter from a hard cutoff).

    Parameters
    ----------
    fir_filter : np.ndarray
        The FIR filter to export.
    output_path : str
        Output WAV file path.
    n_taps : int
        Target filter length. Truncates or zero-pads as needed.
    sr : int
        Sample rate.
    """
    fir_filter = np.asarray(fir_filter, dtype=np.float64)

    # Truncate or zero-pad to exact length
    if len(fir_filter) > n_taps:
        fir_filter = fir_filter[:n_taps]
        # Apply fade-out to avoid truncation artifacts
        fade_len = n_taps // 50  # 2% fade-out
        fade = dsp_utils.fade_window(n_taps, 0, fade_len)
        fir_filter *= fade
    elif len(fir_filter) < n_taps:
        fir_filter = np.pad(fir_filter, (0, n_taps - len(fir_filter)))

    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Write as float32 WAV (CamillaDSP compatible)
    sf.write(output_path, fir_filter.astype(np.float32), sr, subtype='FLOAT')


def export_all_filters(
    filters, output_dir, n_taps=DEFAULT_TAPS, sr=SAMPLE_RATE, timestamp=None,
):
    """
    Export a complete set of combined filters for all output channels.

    Parameters
    ----------
    filters : dict
        Mapping of channel names to FIR filter arrays. Expected keys:
        'left_hp', 'right_hp', 'sub1_lp', 'sub2_lp'.
    output_dir : str
        Output directory path.
    n_taps : int
        Target filter length for all filters.
    sr : int
        Sample rate.
    timestamp : datetime, optional
        If provided, filenames include this timestamp for cache-busting
        (TK-166). If None, uses the legacy unversioned filenames.

    Returns
    -------
    dict
        Mapping of channel names to output file paths.
    """
    os.makedirs(output_dir, exist_ok=True)

    output_paths = {}
    for channel in CHANNEL_FILENAMES:
        if channel in filters:
            if timestamp is not None:
                filename = versioned_filename(channel, timestamp)
            else:
                filename = CHANNEL_FILENAMES[channel]
            path = os.path.join(output_dir, filename)
            export_filter(filters[channel], path, n_taps=n_taps, sr=sr)
            output_paths[channel] = path

    return output_paths
