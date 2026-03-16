"""
Deploy generated filters to CamillaDSP.

Handles copying filter WAV files to the CamillaDSP coefficients directory
and optionally reloading the configuration via the pycamilladsp API.

SAFETY: This module refuses to deploy filters that have not passed
verification (run_all_checks). The deploy function requires explicit
confirmation that verification passed.

NOTE: On the Pi, restarting CamillaDSP will cause the USBStreamer to lose
its audio stream, producing transients through the amp chain. The deploy
function prints a warning. The caller (runner.py) should confirm with the
user before proceeding.

TK-166: Supports versioned (timestamped) filenames. CamillaDSP caches FIR
coefficient files by filename, so config.reload() with the same filename
silently keeps old data. Versioned filenames ensure each deployment uses
unique paths, making config.reload() pick up the new coefficients.
"""

import glob
import os
import re
import shutil

from .export import CHANNEL_FILENAMES, TIMESTAMP_FORMAT, versioned_filename


# Default CamillaDSP coefficients directory on the Pi
DEFAULT_COEFFS_DIR = "/etc/camilladsp/coeffs"

# Regex to match versioned coefficient files: combined_{channel}_{YYYYMMDD_HHMMSS}.wav
_VERSIONED_RE = re.compile(
    r"^combined_(.+)_(\d{8}_\d{6})\.wav$"
)


def deploy_filters(
    output_dir,
    coeffs_dir=DEFAULT_COEFFS_DIR,
    verified=False,
    dry_run=False,
    timestamp=None,
):
    """
    Deploy filter WAV files from output_dir to the CamillaDSP coefficients dir.

    Parameters
    ----------
    output_dir : str
        Directory containing the generated filter WAV files.
    coeffs_dir : str
        CamillaDSP coefficients directory on the target system.
    verified : bool
        MUST be True. Deployment is refused if verification has not passed.
    dry_run : bool
        If True, print what would be done without actually copying.
    timestamp : datetime, optional
        If provided, looks for and deploys versioned filenames (TK-166).
        If None, deploys legacy unversioned filenames for backwards
        compatibility.

    Returns
    -------
    list of str
        Paths of deployed files.

    Raises
    ------
    RuntimeError
        If verified is False (safety interlock).
    """
    if not verified:
        raise RuntimeError(
            "DEPLOYMENT REFUSED: Filters have not passed verification. "
            "Run verify.run_all_checks() first and ensure all checks pass."
        )

    if timestamp is not None:
        filter_files = {
            channel: versioned_filename(channel, timestamp)
            for channel in CHANNEL_FILENAMES
        }
    else:
        filter_files = dict(CHANNEL_FILENAMES)

    deployed = []
    for channel, filename in filter_files.items():
        src = os.path.join(output_dir, filename)
        dst = os.path.join(coeffs_dir, filename)

        if not os.path.exists(src):
            print(f"  WARNING: {src} not found, skipping")
            continue

        if dry_run:
            print(f"  [DRY RUN] Would copy {src} -> {dst}")
        else:
            os.makedirs(coeffs_dir, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  Deployed: {dst}")
        deployed.append(dst)

    return deployed


def list_versioned_files(channel, coeffs_dir=DEFAULT_COEFFS_DIR):
    """
    List all versioned coefficient files for a channel, sorted oldest first.

    Parameters
    ----------
    channel : str
        Channel name, e.g. 'left_hp', 'sub1_lp'.
    coeffs_dir : str
        Directory to search.

    Returns
    -------
    list of str
        Absolute paths sorted by timestamp (oldest first).
    """
    pattern = os.path.join(coeffs_dir, f"combined_{channel}_*.wav")
    matches = []
    for path in glob.glob(pattern):
        basename = os.path.basename(path)
        m = _VERSIONED_RE.match(basename)
        if m and m.group(1) == channel:
            matches.append((m.group(2), path))
    matches.sort(key=lambda x: x[0])
    return [path for _, path in matches]


def _get_active_filenames(host="localhost", port=1234):
    """
    Query CamillaDSP for currently active FIR coefficient filenames.

    Returns an empty set if pycamilladsp is not available or connection fails.
    """
    try:
        from camilladsp import CamillaClient
        client = CamillaClient(host, port)
        client.connect()
        config = client.config.active()
        client.disconnect()
    except Exception:
        return set()

    active = set()
    filters = config.get("filters", {})
    for filt in filters.values():
        params = filt.get("parameters", {})
        if filt.get("type") == "Conv" and params.get("type") == "Wav":
            fname = params.get("filename", "")
            if fname:
                active.add(os.path.basename(fname))
    return active


def cleanup_old_coefficients(
    coeffs_dir=DEFAULT_COEFFS_DIR,
    keep=2,
    dry_run=False,
    host="localhost",
    port=1234,
):
    """
    Remove old versioned coefficient files, keeping the last N versions.

    Never deletes the currently-active version (checked against CamillaDSP
    active config if reachable).

    Parameters
    ----------
    coeffs_dir : str
        CamillaDSP coefficients directory.
    keep : int
        Number of most recent versions to keep per channel.
    dry_run : bool
        If True, print what would be deleted without actually deleting.
    host : str
        CamillaDSP websocket host (for active config check).
    port : int
        CamillaDSP websocket port.

    Returns
    -------
    list of str
        Paths of deleted (or would-be-deleted) files.
    """
    active_basenames = _get_active_filenames(host, port)
    deleted = []

    for channel in CHANNEL_FILENAMES:
        versions = list_versioned_files(channel, coeffs_dir)
        if len(versions) <= keep:
            continue

        to_remove = versions[:-keep]
        for path in to_remove:
            basename = os.path.basename(path)
            if basename in active_basenames:
                print(f"  SKIP (active): {basename}")
                continue
            if dry_run:
                print(f"  [DRY RUN] Would delete {path}")
            else:
                os.remove(path)
                print(f"  Deleted: {path}")
            deleted.append(path)

    return deleted


def reload_camilladsp(host="localhost", port=1234):
    """
    Reload CamillaDSP configuration via the websocket API.

    Uses pycamilladsp config.reload() which is glitch-free (no audio
    interruption, no USBStreamer transients). This is safe to call
    without muting amplifiers.

    On macOS (development), pycamilladsp may not be available. In that
    case, prints instructions for manual reload and returns False.

    Parameters
    ----------
    host : str
        CamillaDSP websocket host.
    port : int
        CamillaDSP websocket port.

    Returns
    -------
    bool
        True if reload succeeded, False if skipped or failed.
    """
    try:
        from camilladsp import CamillaClient
    except ImportError:
        print(
            "\n  pycamilladsp not available (expected on macOS dev)."
            "\n  To reload manually on the Pi:"
            f"\n    from camilladsp import CamillaClient"
            f"\n    client = CamillaClient('{host}', {port})"
            "\n    client.connect()"
            "\n    client.config.reload()"
            "\n"
        )
        return False

    try:
        client = CamillaClient(host, port)
        client.connect()
        client.config.reload()
        client.disconnect()
        print("  CamillaDSP config reloaded successfully.")
        return True
    except Exception as e:
        print(f"  WARNING: CamillaDSP reload failed: {e}")
        return False
