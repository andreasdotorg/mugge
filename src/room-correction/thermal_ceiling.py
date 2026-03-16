"""Thermal ceiling computation for speaker protection.

Computes the maximum safe digital level (dBFS) at the sounddevice output
for each speaker channel, based on the driver's thermal power rating
(pe_max_watts), impedance, amplifier voltage gain, and DAC output level.

The signal chain modelled:

  sounddevice (dBFS) -> CamillaDSP (attenuation) -> ADA8200 (Vrms) -> amp (V*gain) -> speaker

The thermal ceiling is the maximum dBFS at the sounddevice output such
that the power delivered to the driver does not exceed pe_max_watts.

A hardcoded safety cap (DEFAULT_HARD_CAP_DBFS = -20.0) is always enforced.
If T/S data is incomplete (pe_max_watts is null/None), the hard cap is
returned as a safe fallback.

Usage:
    from thermal_ceiling import compute_thermal_ceiling_dbfs, load_channel_ceilings
"""

import math
import os
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# Defense-in-depth: never exceed this level regardless of computed ceiling.
# At -20 dBFS without CamillaDSP: ~4.5W into 4 ohm (survivable for 7W CHN-50P).
# Matches SWEEP_LEVEL_HARD_CAP_DBFS in measure_nearfield.py.
DEFAULT_HARD_CAP_DBFS = -20.0

# Default hardware parameters (McGrey PA4504 + Behringer ADA8200)
DEFAULT_AMP_VOLTAGE_GAIN = 42.4  # V/V at full gain
DEFAULT_ADA8200_0DBFS_VRMS = 4.9  # Vrms at 0 dBFS (+16 dBu)

# Config paths relative to project root
HARDWARE_CONFIG_DIR = "configs/hardware"
SPEAKER_IDENTITY_DIR = "configs/speakers/identities"
SPEAKER_PROFILE_DIR = "configs/speakers/profiles"


def _find_project_root():
    """Walk up from this file to find the project root (contains configs/)."""
    d = Path(__file__).resolve().parent
    for _ in range(10):
        if (d / "configs").is_dir():
            return d
        d = d.parent
    return None


def _load_yaml(path):
    """Load a YAML file. Raises if pyyaml is not available."""
    if yaml is None:
        raise ImportError("pyyaml is required: pip install pyyaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def compute_thermal_ceiling_dbfs(pe_max_watts, impedance_ohm,
                                  camilladsp_attenuation_db,
                                  amp_voltage_gain=DEFAULT_AMP_VOLTAGE_GAIN,
                                  ada8200_0dbfs_vrms=DEFAULT_ADA8200_0DBFS_VRMS):
    """Compute the maximum safe digital level at sounddevice output.

    Returns the raw thermal ceiling without applying any hard cap. Use
    safe_ceiling_dbfs() to apply the defense-in-depth cap.

    Parameters
    ----------
    pe_max_watts : float or None
        Thermal power rating of the driver (watts). If None, returns None
        (caller should apply fallback).
    impedance_ohm : float
        Nominal impedance of the driver (ohms).
    camilladsp_attenuation_db : float
        Total attenuation applied by CamillaDSP in the measurement config
        (negative value, e.g. -20.0 for 20 dB of attenuation).
    amp_voltage_gain : float
        Amplifier voltage gain (V/V). Default: 42.4 (McGrey PA4504).
    ada8200_0dbfs_vrms : float
        DAC output voltage at 0 dBFS (Vrms). Default: 4.9 (ADA8200).

    Returns
    -------
    float or None
        Maximum safe digital level in dBFS, or None if pe_max_watts is
        missing/invalid.
    """
    if pe_max_watts is None or pe_max_watts <= 0:
        return None

    if impedance_ohm <= 0:
        raise ValueError(f"impedance_ohm must be positive, got {impedance_ohm}")
    if amp_voltage_gain <= 0:
        raise ValueError(f"amp_voltage_gain must be positive, got {amp_voltage_gain}")
    if ada8200_0dbfs_vrms <= 0:
        raise ValueError(f"ada8200_0dbfs_vrms must be positive, got {ada8200_0dbfs_vrms}")

    # Maximum voltage the driver can handle (V = sqrt(P * Z))
    v_max = math.sqrt(pe_max_watts * impedance_ohm)

    # Voltage at DAC output that would produce v_max at the speaker
    v_at_dac = v_max / amp_voltage_gain

    # That voltage expressed in dBFS (relative to DAC's 0 dBFS output)
    dbfs_at_dac = 20.0 * math.log10(v_at_dac / ada8200_0dbfs_vrms)

    # The sounddevice output goes through CamillaDSP attenuation before
    # reaching the DAC. So the maximum sounddevice level is higher by
    # the attenuation amount (subtracting a negative number = adding).
    return dbfs_at_dac - camilladsp_attenuation_db


def safe_ceiling_dbfs(pe_max_watts, impedance_ohm,
                       camilladsp_attenuation_db,
                       amp_voltage_gain=DEFAULT_AMP_VOLTAGE_GAIN,
                       ada8200_0dbfs_vrms=DEFAULT_ADA8200_0DBFS_VRMS,
                       hard_cap_dbfs=DEFAULT_HARD_CAP_DBFS):
    """Compute thermal ceiling with defense-in-depth hard cap.

    Wraps compute_thermal_ceiling_dbfs and enforces:
    - Falls back to hard_cap_dbfs when pe_max_watts is None/invalid.
    - Never returns a value higher (louder) than hard_cap_dbfs.

    Returns
    -------
    float
        Maximum safe digital level in dBFS. Always <= hard_cap_dbfs.
    """
    raw = compute_thermal_ceiling_dbfs(
        pe_max_watts, impedance_ohm, camilladsp_attenuation_db,
        amp_voltage_gain, ada8200_0dbfs_vrms)

    if raw is None:
        return hard_cap_dbfs
    return min(raw, hard_cap_dbfs)


def load_hardware_config(project_root=None):
    """Load hardware config files and return amp gain and DAC output level.

    Parameters
    ----------
    project_root : str or Path, optional
        Project root directory. Auto-detected if not provided.

    Returns
    -------
    dict
        Keys: amp_voltage_gain, ada8200_0dbfs_vrms
    """
    if project_root is None:
        project_root = _find_project_root()
    if project_root is None:
        return {
            "amp_voltage_gain": DEFAULT_AMP_VOLTAGE_GAIN,
            "ada8200_0dbfs_vrms": DEFAULT_ADA8200_0DBFS_VRMS,
        }

    project_root = Path(project_root)
    hw_dir = project_root / HARDWARE_CONFIG_DIR

    result = {
        "amp_voltage_gain": DEFAULT_AMP_VOLTAGE_GAIN,
        "ada8200_0dbfs_vrms": DEFAULT_ADA8200_0DBFS_VRMS,
    }

    amp_path = hw_dir / "amp-mcgrey-pa4504.yml"
    if amp_path.exists():
        amp = _load_yaml(amp_path)
        if amp and "specs" in amp:
            result["amp_voltage_gain"] = amp["specs"].get(
                "voltage_gain", DEFAULT_AMP_VOLTAGE_GAIN)

    dac_path = hw_dir / "dac-behringer-ada8200.yml"
    if dac_path.exists():
        dac = _load_yaml(dac_path)
        if dac and "specs" in dac:
            result["ada8200_0dbfs_vrms"] = dac["specs"].get(
                "output_level_0dbfs_vrms", DEFAULT_ADA8200_0DBFS_VRMS)

    return result


def load_speaker_identity(identity_name, project_root=None):
    """Load a speaker identity YAML and return pe_max_watts and impedance.

    Parameters
    ----------
    identity_name : str
        Identity file name without .yml extension (e.g. "markaudio-chn-50p-sealed-1l16").
    project_root : str or Path, optional
        Project root directory. Auto-detected if not provided.

    Returns
    -------
    dict
        Keys: pe_max_watts (float or None), impedance_ohm (float)
    """
    if project_root is None:
        project_root = _find_project_root()
    if project_root is None:
        raise FileNotFoundError("Cannot find project root (no configs/ directory)")

    project_root = Path(project_root)
    identity_path = project_root / SPEAKER_IDENTITY_DIR / f"{identity_name}.yml"

    if not identity_path.exists():
        raise FileNotFoundError(f"Speaker identity not found: {identity_path}")

    data = _load_yaml(identity_path)

    return {
        "pe_max_watts": data.get("max_power_watts"),
        "impedance_ohm": data.get("impedance_ohm"),
    }


def load_channel_ceilings(profile_name, camilladsp_attenuation_db,
                           project_root=None,
                           hard_cap_dbfs=DEFAULT_HARD_CAP_DBFS):
    """Compute thermal ceilings for all speaker channels in a profile.

    Parameters
    ----------
    profile_name : str
        Speaker profile name without .yml (e.g. "bose-home-chn50p").
    camilladsp_attenuation_db : float
        CamillaDSP measurement attenuation (e.g. -20.0).
    project_root : str or Path, optional
        Project root directory. Auto-detected if not provided.
    hard_cap_dbfs : float
        Absolute maximum digital level. Default: -20.0.

    Returns
    -------
    dict
        Mapping of speaker name -> dict with keys:
            channel (int), ceiling_dbfs (float), identity (str),
            pe_max_watts (float or None), impedance_ohm (float)
    """
    if project_root is None:
        project_root = _find_project_root()
    if project_root is None:
        raise FileNotFoundError("Cannot find project root (no configs/ directory)")

    project_root = Path(project_root)
    hw = load_hardware_config(project_root)

    profile_path = project_root / SPEAKER_PROFILE_DIR / f"{profile_name}.yml"
    if not profile_path.exists():
        raise FileNotFoundError(f"Speaker profile not found: {profile_path}")

    profile = _load_yaml(profile_path)
    speakers = profile.get("speakers", {})
    results = {}

    for spk_name, spk_data in speakers.items():
        identity_name = spk_data.get("identity")
        channel = spk_data.get("channel")

        if identity_name is None or channel is None:
            continue

        identity = load_speaker_identity(identity_name, project_root)
        pe = identity["pe_max_watts"]
        z = identity["impedance_ohm"]

        ceiling = safe_ceiling_dbfs(
            pe_max_watts=pe,
            impedance_ohm=z,
            camilladsp_attenuation_db=camilladsp_attenuation_db,
            amp_voltage_gain=hw["amp_voltage_gain"],
            ada8200_0dbfs_vrms=hw["ada8200_0dbfs_vrms"],
            hard_cap_dbfs=hard_cap_dbfs,
        )

        results[spk_name] = {
            "channel": channel,
            "ceiling_dbfs": ceiling,
            "identity": identity_name,
            "pe_max_watts": pe,
            "impedance_ohm": z,
        }

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Compute thermal ceiling for speaker channels.")
    parser.add_argument("--profile", default="bose-home-chn50p",
                        help="Speaker profile name (default: bose-home-chn50p)")
    parser.add_argument("--attenuation", type=float, default=-20.0,
                        help="CamillaDSP measurement attenuation in dB (default: -20.0)")
    parser.add_argument("--project-root", default=None,
                        help="Project root directory (auto-detected if omitted)")
    args = parser.parse_args()

    ceilings = load_channel_ceilings(
        args.profile, args.attenuation, project_root=args.project_root)

    print(f"Thermal ceilings for profile '{args.profile}' "
          f"(CamillaDSP attenuation: {args.attenuation} dB):")
    print(f"Hard cap: {DEFAULT_HARD_CAP_DBFS} dBFS")
    print()

    for name, info in sorted(ceilings.items(), key=lambda x: x[1]["channel"]):
        pe_str = f"{info['pe_max_watts']}W" if info['pe_max_watts'] else "N/A"
        print(f"  ch {info['channel']} ({name}): {info['ceiling_dbfs']:.2f} dBFS "
              f"[{info['identity']}, {pe_str} @ {info['impedance_ohm']} ohm]")
