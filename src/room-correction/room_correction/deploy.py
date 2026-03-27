"""
Deploy generated filters to PipeWire filter-chain.

Handles copying filter WAV files to the PipeWire filter-chain coefficients
directory and deploying the generated PW filter-chain .conf drop-in.

SAFETY: This module refuses to deploy filters that have not passed
verification (run_all_checks). The deploy function requires explicit
confirmation that verification passed.

NOTE: On the Pi, restarting PipeWire will cause the USBStreamer to lose
its audio stream, producing transients through the amp chain. The deploy
function prints a warning. The caller (runner.py) should confirm with the
user before proceeding.

TK-166: Supports versioned (timestamped) filenames for deployment
traceability. Each deployment uses unique paths so that deployed versions
can be identified and rolled back if needed.

D-040: All CamillaDSP references replaced with PipeWire filter-chain
equivalents. The .conf drop-in deploys to
~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf
and WAV coefficients to /etc/pi4audio/coeffs/.
"""

import glob
import os
import re
import shutil

from .export import CHANNEL_FILENAMES, TIMESTAMP_FORMAT, versioned_filename


# Default PipeWire filter-chain coefficients directory on the Pi (D-040)
DEFAULT_COEFFS_DIR = "/etc/pi4audio/coeffs"

# Default PipeWire config drop-in directory
DEFAULT_PW_CONF_DIR = os.path.expanduser(
    "~/.config/pipewire/pipewire.conf.d"
)

# Default name for the filter-chain convolver config drop-in
DEFAULT_PW_CONF_NAME = "30-filter-chain-convolver.conf"

# Regex to match versioned coefficient files: combined_{channel}_{YYYYMMDD_HHMMSS}.wav
_VERSIONED_RE = re.compile(
    r"^combined_(.+)_(\d{8}_\d{6})\.wav$"
)

# Regex to extract filename values from PW filter-chain .conf files
_PW_FILENAME_RE = re.compile(r'filename\s*=\s*"([^"]+)"')


def deploy_filters(
    output_dir,
    coeffs_dir=DEFAULT_COEFFS_DIR,
    verified=False,
    dry_run=False,
    timestamp=None,
):
    """
    Deploy filter WAV files from output_dir to the PipeWire coefficients dir.

    Parameters
    ----------
    output_dir : str
        Directory containing the generated filter WAV files.
    coeffs_dir : str
        PipeWire filter-chain coefficients directory on the target system.
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


def deploy_pw_config(
    conf_content,
    pw_conf_dir=DEFAULT_PW_CONF_DIR,
    conf_name=DEFAULT_PW_CONF_NAME,
    dry_run=False,
):
    """
    Deploy a PipeWire filter-chain .conf drop-in file.

    Parameters
    ----------
    conf_content : str
        The complete .conf file content (from pw_config_generator).
    pw_conf_dir : str
        PipeWire config drop-in directory.
    conf_name : str
        Filename for the drop-in config.
    dry_run : bool
        If True, print what would be done without writing.

    Returns
    -------
    str
        Path to the deployed config file.
    """
    dst = os.path.join(pw_conf_dir, conf_name)

    if dry_run:
        print(f"  [DRY RUN] Would write PW config to {dst}")
        return dst

    os.makedirs(pw_conf_dir, exist_ok=True)
    with open(dst, "w") as f:
        f.write(conf_content)
    print(f"  Deployed PW config: {dst}")
    return dst


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


def _get_active_filenames(pw_conf_dir=DEFAULT_PW_CONF_DIR):
    """
    Parse PipeWire filter-chain .conf files for active FIR coefficient filenames.

    Scans all .conf files in the PW config drop-in directory for
    ``filename = "/path/to/file.wav"`` entries in convolver node configs.

    Returns an empty set if the directory doesn't exist or no filenames found.
    """
    active = set()
    if not os.path.isdir(pw_conf_dir):
        return active

    for conf_file in glob.glob(os.path.join(pw_conf_dir, "*.conf")):
        try:
            with open(conf_file, "r") as f:
                content = f.read()
        except OSError:
            continue

        for match in _PW_FILENAME_RE.finditer(content):
            fname = match.group(1)
            if fname:
                active.add(os.path.basename(fname))

    return active


def cleanup_old_coefficients(
    coeffs_dir=DEFAULT_COEFFS_DIR,
    keep=2,
    dry_run=False,
    pw_conf_dir=DEFAULT_PW_CONF_DIR,
):
    """
    Remove old versioned coefficient files, keeping the last N versions.

    Never deletes the currently-active version (checked by parsing PipeWire
    filter-chain config files for referenced filenames).

    Parameters
    ----------
    coeffs_dir : str
        PipeWire filter-chain coefficients directory.
    keep : int
        Number of most recent versions to keep per channel.
    dry_run : bool
        If True, print what would be deleted without actually deleting.
    pw_conf_dir : str
        PipeWire config drop-in directory (for active file detection).

    Returns
    -------
    list of str
        Paths of deleted (or would-be-deleted) files.
    """
    active_basenames = _get_active_filenames(pw_conf_dir)
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


def reload_pipewire():
    """
    Reload the PipeWire filter-chain by restarting the PipeWire user service.

    WARNING: Restarting PipeWire resets the USBStreamer, producing transients
    through the amplifier chain that can damage speakers. The caller MUST
    ensure amplifiers are off or muted before calling this function.

    On macOS (development), systemctl is not available. In that case, prints
    instructions for manual reload and returns False.

    Returns
    -------
    bool
        True if reload succeeded, False if skipped or failed.
    """
    import subprocess

    # Check if systemctl is available (Linux with systemd)
    if shutil.which("systemctl") is None:
        print(
            "\n  systemctl not available (expected on macOS dev)."
            "\n  To reload PipeWire on the Pi:"
            "\n    systemctl --user restart pipewire.service"
            "\n"
            "\n  WARNING: Restarting PipeWire resets the USBStreamer!"
            "\n  Ensure amplifiers are OFF or MUTED before restarting."
            "\n"
        )
        return False

    try:
        print(
            "\n  WARNING: Restarting PipeWire will reset the USBStreamer."
            "\n  Ensure amplifiers are OFF or MUTED."
        )
        result = subprocess.run(
            ["systemctl", "--user", "restart", "pipewire.service"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print("  PipeWire restarted successfully.")
            return True
        else:
            print(f"  WARNING: PipeWire restart failed: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        print("  WARNING: PipeWire restart timed out after 15s.")
        return False
    except Exception as e:
        print(f"  WARNING: PipeWire restart failed: {e}")
        return False
