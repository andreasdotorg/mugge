"""PipeWire capture utility — record from a PW source node via pw-record.

Wraps the ``pw-record`` subprocess to capture audio from any PipeWire
source node (e.g. the UMIK-1).  Used by the measurement session to
replace the old ``playrec`` pattern with separated play + capture.

Signal flow (production):
    real UMIK-1 hardware -> pw-record -> WAV file -> numpy array

Signal flow (local-demo):
    speaker convolver -> room-sim convolver -> UMIK-1 loopback
    -> pw-record -> WAV file -> numpy array

The measurement code is identical in both cases — the only difference
is what PipeWire node backs the target name.

Usage::

    capture = start_capture("alsa_input.usb-miniDSP_UMIK-1", "/tmp/cap.wav")
    # ... play sweep via signal-gen ...
    stop_capture(capture)
    recording = load_wav("/tmp/cap.wav")
"""

import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Default PipeWire source node for the UMIK-1 microphone.
DEFAULT_TARGET = "alsa_input.usb-miniDSP_Umik-1"
SAMPLE_RATE = 48000


def _set_default_source(target: str) -> None:
    """Set the PipeWire default audio source via pw-metadata.

    WirePlumber's linking policy auto-links capture streams to the default
    source. Setting this before starting pw-record ensures the stream
    connects to the correct node without needing ``--target`` (which
    doesn't work when WP's linking is configured for headless use).
    """
    cmd = [
        "pw-metadata", "-n", "default", "0",
        "default.audio.source",
        f'{{"name":"{target}"}}',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        logger.warning("pw-metadata set default source failed: %s", result.stderr)
    else:
        logger.info("Set default audio source to %s", target)


def start_capture(
    output_path: str,
    target: str = DEFAULT_TARGET,
    sample_rate: int = SAMPLE_RATE,
    channels: int = 1,
    pw_record_bin: Optional[str] = None,
) -> subprocess.Popen:
    """Start a pw-record subprocess capturing from *target*.

    Parameters
    ----------
    output_path : str
        Path for the output WAV file.
    target : str
        PipeWire node name to capture from.
    sample_rate : int
        Sample rate (default 48000).
    channels : int
        Number of channels (default 1 for UMIK-1 mono).
    pw_record_bin : str or None
        Path to pw-record binary.  If None, uses PATH lookup.

    Returns
    -------
    subprocess.Popen
        The running pw-record process.  Call ``stop_capture()`` to
        terminate it cleanly.
    """
    # F-164: Set the default audio source so WP auto-links the stream.
    # pw-record's --target flag doesn't work in headless WP environments
    # because WP's linking policy needs a default source to match against.
    _set_default_source(target)

    bin_path = pw_record_bin or "pw-record"
    cmd = [
        bin_path,
        "--rate", str(sample_rate),
        "--channels", str(channels),
        "--format", "f32",
        output_path,
    ]
    logger.info("Starting capture: %s", " ".join(cmd))

    # Ensure output directory exists.
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    # Settle time for pw-record to connect and WP to create the link.
    time.sleep(1.0)

    if proc.poll() is not None:
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        raise RuntimeError(
            f"pw-record exited immediately (rc={proc.returncode}): {stderr}"
        )

    logger.info("Capture started (pid=%d, target=%s, path=%s)",
                proc.pid, target, output_path)
    return proc


def stop_capture(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    """Stop a pw-record subprocess with SIGINT (clean WAV finalization).

    Parameters
    ----------
    proc : subprocess.Popen
        The pw-record process returned by ``start_capture()``.
    timeout : float
        Seconds to wait for graceful exit before SIGKILL.
    """
    if proc.poll() is not None:
        logger.info("Capture already exited (rc=%d)", proc.returncode)
        return

    # SIGINT triggers pw-record's clean shutdown — it finalizes the
    # WAV header with the correct sample count.
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=timeout)
        logger.info("Capture stopped cleanly (rc=%d)", proc.returncode)
    except subprocess.TimeoutExpired:
        logger.warning("Capture did not exit after SIGINT, sending SIGKILL")
        proc.kill()
        proc.wait(timeout=2.0)


def load_wav(path: str, dtype: str = "float64") -> np.ndarray:
    """Load a WAV file recorded by pw-record.

    Parameters
    ----------
    path : str
        Path to the WAV file.
    dtype : str
        Output numpy dtype (default float64 to match gain_calibration).

    Returns
    -------
    np.ndarray
        Audio data, shape (n_frames, n_channels).
    """
    data, sr = sf.read(path, dtype=dtype)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    logger.info("Loaded capture: %d frames, %d ch, %d Hz from %s",
                data.shape[0], data.shape[1], sr, path)
    return data
