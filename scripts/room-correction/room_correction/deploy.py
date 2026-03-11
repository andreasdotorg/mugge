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
"""

import os
import shutil


# Default CamillaDSP coefficients directory on the Pi
DEFAULT_COEFFS_DIR = "/etc/camilladsp/coeffs"


def deploy_filters(
    output_dir,
    coeffs_dir=DEFAULT_COEFFS_DIR,
    verified=False,
    dry_run=False,
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

    filter_files = [
        "combined_left_hp.wav",
        "combined_right_hp.wav",
        "combined_sub1_lp.wav",
        "combined_sub2_lp.wav",
    ]

    deployed = []
    for filename in filter_files:
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


def reload_camilladsp(host="localhost", port=1234):
    """
    Reload CamillaDSP configuration via the websocket API.

    This is a stub for future integration with pycamilladsp. Currently
    prints instructions for manual reload.

    WARNING: Reloading CamillaDSP will briefly interrupt audio output.
    The USBStreamer may produce transients. Ensure amplifiers are muted
    or powered off before reloading.

    Parameters
    ----------
    host : str
        CamillaDSP websocket host.
    port : int
        CamillaDSP websocket port.
    """
    print(
        "\n"
        "  *** WARNING: CamillaDSP reload will interrupt audio output. ***\n"
        "  *** Ensure amplifiers are OFF or muted before proceeding.   ***\n"
        "\n"
        "  To reload CamillaDSP with new filters:\n"
        f"    1. SSH to the Pi\n"
        f"    2. sudo systemctl restart camilladsp\n"
        "\n"
        "  Or use pycamilladsp (when integrated):\n"
        f"    from camilladsp import CamillaClient\n"
        f"    client = CamillaClient('{host}', {port})\n"
        f"    client.connect()\n"
        f"    client.reload()\n"
    )
