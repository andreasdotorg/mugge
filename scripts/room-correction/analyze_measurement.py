#!/usr/bin/env python3
"""
Analyze a measurement recording from pw-record.

Reads a WAV file (including pw-record's unfinalised headers), extracts an
analysis window, computes the frequency response via averaged FFT, and prints
a frequency vs dB level table.

Usage:
    python analyze_measurement.py recording.wav
    python analyze_measurement.py recording.wav --start 2.0 --end 22.0
    python analyze_measurement.py recording.wav --crossover-detail 200
    python analyze_measurement.py recording.wav --fft-size 16384 --smoothing 3
"""

import argparse
import os
import struct
import sys

import numpy as np
import soundfile as sf

# Add the scripts/room-correction directory to path so room_correction package is importable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from room_correction.dsp_utils import linear_to_db, fractional_octave_smooth


def read_wav(path):
    """
    Read a WAV file, handling pw-record's unfinalised headers.

    pw-record may not update the RIFF/data chunk size fields when recording
    is stopped with Ctrl-C. The data chunk starts at byte offset 80 and
    contains float32 samples. If soundfile can read the file normally, we
    use that. Otherwise, fall back to raw parsing.

    Returns
    -------
    data : np.ndarray
        Audio samples, shape (n_samples,) for mono or (n_samples, n_channels).
    sr : int
        Sample rate in Hz.
    """
    # Try soundfile first — handles well-formed WAVs and many edge cases
    try:
        data, sr = sf.read(path, dtype="float64")
        return data, sr
    except Exception:
        pass

    # Fallback: parse pw-record's unfinalised WAV manually
    # pw-record writes a standard RIFF header but may leave size fields as 0
    # or 0xFFFFFFFF. Data starts at byte 80, format is float32.
    with open(path, "rb") as f:
        header = f.read(80)

        # Validate RIFF header
        if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ValueError(f"Not a WAV file: {path}")

        # Extract sample rate from fmt chunk (bytes 24-27 in standard WAV)
        # pw-record places fmt at offset 12, so sample rate is at offset 24
        sr = struct.unpack_from("<I", header, 24)[0]

        # Extract number of channels (bytes 22-23)
        n_channels = struct.unpack_from("<H", header, 22)[0]

        # Read all remaining data as float32
        f.seek(80)
        raw = f.read()

    n_samples_total = len(raw) // 4  # 4 bytes per float32
    data = np.frombuffer(raw[: n_samples_total * 4], dtype=np.float32).astype(
        np.float64
    )

    if n_channels > 1:
        # Trim to exact multiple of n_channels
        n_frames = n_samples_total // n_channels
        data = data[: n_frames * n_channels].reshape(n_frames, n_channels)

    return data, sr


def extract_window(data, sr, start_s, end_s):
    """
    Extract a time window from audio data.

    Parameters
    ----------
    data : np.ndarray
        Audio data, mono (n_samples,) or multi-channel (n_samples, n_channels).
    sr : int
        Sample rate.
    start_s : float
        Window start in seconds.
    end_s : float
        Window end in seconds.

    Returns
    -------
    np.ndarray
        Windowed audio segment.
    """
    if data.ndim == 2:
        n_frames = data.shape[0]
    else:
        n_frames = len(data)

    duration = n_frames / sr
    start_sample = int(start_s * sr)
    end_sample = int(end_s * sr)

    start_sample = max(0, start_sample)
    end_sample = min(n_frames, end_sample)

    if start_sample >= end_sample:
        raise ValueError(
            f"Invalid window: start={start_s:.1f}s end={end_s:.1f}s "
            f"(recording is {duration:.1f}s)"
        )

    if data.ndim == 2:
        return data[start_sample:end_sample, :]
    return data[start_sample:end_sample]


def compute_frequency_response(data, sr, fft_size, window_func="hann"):
    """
    Compute averaged frequency response using Welch's method.

    Splits the signal into overlapping segments, applies a window function,
    computes the FFT of each segment, and averages the magnitude spectra.
    This reduces noise variance compared to a single FFT.

    Parameters
    ----------
    data : np.ndarray
        Mono audio data (1D).
    sr : int
        Sample rate.
    fft_size : int
        FFT size (number of points per segment).
    window_func : str
        Window function name (hann, hamming, blackman, etc.).

    Returns
    -------
    freqs : np.ndarray
        Frequency array in Hz.
    magnitude_db : np.ndarray
        Magnitude in dB (averaged across segments).
    """
    data = np.asarray(data, dtype=np.float64)

    # Use scipy.signal.get_window to support multiple window types
    from scipy.signal import get_window

    window = get_window(window_func, fft_size)

    # 50% overlap for Welch averaging
    hop = fft_size // 2
    n_segments = max(1, (len(data) - fft_size) // hop + 1)

    # Accumulate magnitude squared (power spectrum)
    power_sum = np.zeros(fft_size // 2 + 1)

    for i in range(n_segments):
        start = i * hop
        segment = data[start : start + fft_size]
        if len(segment) < fft_size:
            break
        windowed = segment * window
        spectrum = np.fft.rfft(windowed)
        power_sum += np.abs(spectrum) ** 2

    # Average and convert to magnitude
    power_avg = power_sum / n_segments
    magnitude = np.sqrt(power_avg)

    freqs = np.fft.rfftfreq(fft_size, d=1.0 / sr)
    magnitude_db = linear_to_db(magnitude)

    return freqs, magnitude_db


def to_mono(data):
    """Convert multi-channel audio to mono by averaging channels."""
    if data.ndim == 1:
        return data
    return np.mean(data, axis=1)


# Standard 1/3-octave center frequencies for the summary table
THIRD_OCTAVE_FREQS = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
    2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000,
]


def interpolate_at_freqs(freqs, magnitude_db, target_freqs):
    """
    Interpolate magnitude at specific target frequencies.

    Parameters
    ----------
    freqs : np.ndarray
        Frequency array from FFT.
    magnitude_db : np.ndarray
        Magnitude in dB.
    target_freqs : list
        Frequencies at which to interpolate.

    Returns
    -------
    list of (freq, db) tuples
    """
    results = []
    for f in target_freqs:
        if f < freqs[1] or f > freqs[-1]:
            continue
        idx = np.argmin(np.abs(freqs - f))
        results.append((f, float(magnitude_db[idx])))
    return results


def crossover_detail(freqs, magnitude_db, crossover_hz, sr):
    """
    Generate fine-resolution frequency response around a crossover frequency.

    Reports at 1Hz steps within +/- 1 octave of the crossover frequency.

    Parameters
    ----------
    freqs : np.ndarray
        Frequency array from FFT.
    magnitude_db : np.ndarray
        Magnitude in dB.
    crossover_hz : float
        Crossover frequency.
    sr : int
        Sample rate.

    Returns
    -------
    list of (freq, db) tuples
    """
    f_low = max(crossover_hz / 2, freqs[1])
    f_high = min(crossover_hz * 2, sr / 2)

    mask = (freqs >= f_low) & (freqs <= f_high)
    detail_freqs = freqs[mask]
    detail_db = magnitude_db[mask]

    # Subsample to ~1Hz steps if resolution is finer
    step = max(1, int(1.0 / (freqs[1] - freqs[0]))) if freqs[1] > 0 else 1
    if step > 1:
        detail_freqs = detail_freqs[::step]
        detail_db = detail_db[::step]

    return list(zip(detail_freqs.tolist(), detail_db.tolist()))


def format_table(rows, title=None):
    """Format a list of (freq, db) tuples as a text table."""
    lines = []
    if title:
        lines.append(title)
        lines.append("-" * len(title))
    lines.append(f"  {'Freq (Hz)':>10}  {'Level (dB)':>10}")
    lines.append(f"  {'----------':>10}  {'----------':>10}")
    for freq, db in rows:
        if freq >= 1000:
            freq_str = f"{freq:.0f}"
        elif freq >= 100:
            freq_str = f"{freq:.0f}"
        else:
            freq_str = f"{freq:.1f}"
        lines.append(f"  {freq_str:>10}  {db:>10.1f}")
    return "\n".join(lines)


def analyze(path, start_s=2.0, end_s=22.0, fft_size=8192, window_func="hann",
            smoothing=None, crossover_hz=None, channel=None):
    """
    Main analysis function.

    Parameters
    ----------
    path : str
        Path to WAV file.
    start_s : float
        Analysis window start in seconds.
    end_s : float
        Analysis window end in seconds.
    fft_size : int
        FFT size.
    window_func : str
        Window function name.
    smoothing : int or None
        Fractional-octave smoothing (e.g. 3 for 1/3 octave). None = no smoothing.
    crossover_hz : float or None
        If set, print fine-resolution crossover detail.
    channel : int or None
        Channel to analyze (0-indexed). None = mono mix of all channels.

    Returns
    -------
    dict with keys: freqs, magnitude_db, table_rows, info
    """
    # Read WAV
    data, sr = read_wav(path)

    # File info
    if data.ndim == 2:
        n_frames, n_channels = data.shape
    else:
        n_frames = len(data)
        n_channels = 1

    duration = n_frames / sr

    info = {
        "path": os.path.basename(path),
        "sample_rate": sr,
        "channels": n_channels,
        "duration_s": duration,
        "window": f"{start_s:.1f}s - {end_s:.1f}s",
        "fft_size": fft_size,
        "window_func": window_func,
    }

    # Select channel
    if channel is not None and data.ndim == 2:
        if channel >= n_channels:
            raise ValueError(
                f"Channel {channel} requested but file has {n_channels} channels"
            )
        data = data[:, channel]
    else:
        data = to_mono(data)

    # Clamp end to recording duration
    if end_s > duration:
        end_s = duration
        info["window"] = f"{start_s:.1f}s - {end_s:.1f}s (clamped)"

    # Extract analysis window
    segment = extract_window(data, sr, start_s, end_s)

    # Compute frequency response
    freqs, magnitude_db = compute_frequency_response(segment, sr, fft_size, window_func)

    # Optional smoothing
    if smoothing is not None and smoothing > 0:
        # Convert back to linear, smooth, convert back to dB
        from room_correction.dsp_utils import db_to_linear

        magnitude_linear = db_to_linear(magnitude_db)
        smoothed = fractional_octave_smooth(magnitude_linear, freqs, smoothing)
        magnitude_db = linear_to_db(smoothed)
        info["smoothing"] = f"1/{smoothing} octave"

    # Build 1/3-octave summary table
    table_rows = interpolate_at_freqs(freqs, magnitude_db, THIRD_OCTAVE_FREQS)

    result = {
        "freqs": freqs,
        "magnitude_db": magnitude_db,
        "table_rows": table_rows,
        "info": info,
    }

    # Crossover detail
    if crossover_hz is not None:
        result["crossover_detail"] = crossover_detail(
            freqs, magnitude_db, crossover_hz, sr
        )

    return result


def print_results(result):
    """Print analysis results to stdout."""
    info = result["info"]

    print("=" * 60)
    print("MEASUREMENT ANALYSIS")
    print("=" * 60)
    print(f"  File:        {info['path']}")
    print(f"  Sample rate: {info['sample_rate']} Hz")
    print(f"  Channels:    {info['channels']}")
    print(f"  Duration:    {info['duration_s']:.1f}s")
    print(f"  Window:      {info['window']}")
    print(f"  FFT size:    {info['fft_size']}")
    print(f"  Window func: {info['window_func']}")
    if "smoothing" in info:
        print(f"  Smoothing:   {info['smoothing']}")
    print()

    # Summary statistics
    rows = result["table_rows"]
    if rows:
        db_values = [db for _, db in rows]
        print(f"  Peak level:  {max(db_values):.1f} dB at {rows[db_values.index(max(db_values))][0]:.0f} Hz")
        print(f"  Min level:   {min(db_values):.1f} dB at {rows[db_values.index(min(db_values))][0]:.0f} Hz")
        print(f"  Range:       {max(db_values) - min(db_values):.1f} dB")
        print()

    print(format_table(rows, "1/3-Octave Frequency Response"))
    print()

    if "crossover_detail" in result:
        detail = result["crossover_detail"]
        if detail:
            print(format_table(detail, "Crossover Region Detail"))
            print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a measurement recording from pw-record.",
        epilog="Handles pw-record's unfinalised WAV headers automatically.",
    )
    parser.add_argument("wav_file", help="Path to the WAV recording")
    parser.add_argument(
        "--start", type=float, default=2.0,
        help="Analysis window start in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--end", type=float, default=22.0,
        help="Analysis window end in seconds (default: 22.0)",
    )
    parser.add_argument(
        "--fft-size", type=int, default=8192,
        help="FFT size (default: 8192)",
    )
    parser.add_argument(
        "--window", type=str, default="hann",
        help="Window function: hann, hamming, blackman, etc. (default: hann)",
    )
    parser.add_argument(
        "--smoothing", type=int, default=None,
        help="Fractional-octave smoothing, e.g. 3 for 1/3 octave (default: none)",
    )
    parser.add_argument(
        "--crossover-detail", type=float, default=None, metavar="FREQ",
        help="Show fine resolution around crossover frequency in Hz",
    )
    parser.add_argument(
        "--channel", type=int, default=None,
        help="Analyze specific channel (0-indexed). Default: mono mix",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.wav_file):
        print(f"Error: file not found: {args.wav_file}", file=sys.stderr)
        sys.exit(1)

    result = analyze(
        path=args.wav_file,
        start_s=args.start,
        end_s=args.end,
        fft_size=args.fft_size,
        window_func=args.window,
        smoothing=args.smoothing,
        crossover_hz=args.crossover_detail,
        channel=args.channel,
    )

    print_results(result)


if __name__ == "__main__":
    main()
