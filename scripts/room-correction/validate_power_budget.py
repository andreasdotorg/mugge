#!/usr/bin/env python3
"""
Power budget validator for CamillaDSP production configurations.

For each output channel, traces the gain chain from 0 dBFS input through
the mixer, all pipeline filters, and the amplifier to compute worst-case
power at the speaker terminals. Compares to each driver's pe_max (thermal
power rating) and reports PASS/FAIL per channel.

Hardware constants (McGrey PA4504 + Behringer ADA8200):
  - ADA8200 output at 0 dBFS: +16 dBu = 4.9 Vrms
  - McGrey PA4504 voltage gain: 42.4x at full gain

Exit code 0 = all channels pass, 1 = at least one channel fails.
"""

import argparse
import math
import sys
from pathlib import Path

import yaml


# ----- Hardware constants --------------------------------------------------

# Behringer ADA8200: 0 dBFS = +16 dBu = 4.9 Vrms
DAC_VRMS_AT_0DBFS = 4.9

# McGrey PA4504: voltage gain at full setting
AMP_VOLTAGE_GAIN = 42.4


# ----- Project paths -------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent.parent

IDENTITIES_DIR = PROJECT_ROOT / "configs" / "speakers" / "identities"
PROFILES_DIR = PROJECT_ROOT / "configs" / "speakers" / "profiles"
PRODUCTION_DIR = PROJECT_ROOT / "configs" / "camilladsp" / "production"


# ----- YAML loading -------------------------------------------------------

def load_yaml(path):
    """Load a YAML file and return the parsed dict."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_identity(name, identities_dir=None):
    """Load a speaker identity by name (without .yml extension)."""
    directory = Path(identities_dir) if identities_dir else IDENTITIES_DIR
    path = directory / f"{name}.yml"
    if not path.exists():
        raise FileNotFoundError(f"Speaker identity not found: {path}")
    return load_yaml(path)


def load_profile(name, profiles_dir=None):
    """Load a speaker profile by name (without .yml extension)."""
    directory = Path(profiles_dir) if profiles_dir else PROFILES_DIR
    path = directory / f"{name}.yml"
    if not path.exists():
        raise FileNotFoundError(f"Speaker profile not found: {path}")
    return load_yaml(path)


# ----- Gain extraction from CamillaDSP config -----------------------------

def get_mixer_gain_db(config, channel):
    """
    Get the worst-case mixer gain for a destination channel.

    For a single source, returns that source's gain.
    For multiple sources (e.g. mono sum), assumes worst-case correlated
    signals: linear sum of source amplitudes, converted back to dB.

    Returns the gain in dB.
    """
    mixers = config.get("mixers", {})
    for mixer_name, mixer_def in mixers.items():
        for mapping in mixer_def.get("mapping", []):
            if mapping["dest"] == channel:
                sources = mapping.get("sources", [])
                if not sources:
                    return -math.inf  # No sources = silence
                # Sum source amplitudes (worst case: correlated signals)
                total_amplitude = 0.0
                for src in sources:
                    gain_db = src.get("gain", 0)
                    total_amplitude += 10 ** (gain_db / 20.0)
                return 20.0 * math.log10(total_amplitude) if total_amplitude > 0 else -math.inf
    # Channel not in any mixer mapping
    return -math.inf


def get_filter_gain_db(filter_def):
    """
    Get the worst-case gain contribution of a single filter definition.

    For Gain filters: returns the gain parameter directly.
    For Biquad shelf/peak filters: returns the gain parameter if positive,
        0 if negative (attenuation doesn't increase worst-case power).
    For BiquadCombo (HPF/LPF): 0 dB in passband (worst case).
    For Conv (FIR): returns 0 dB (FIR boost is accounted for separately
        via max_boost_db from the identity).

    Returns the gain in dB.
    """
    ftype = filter_def.get("type", "")
    params = filter_def.get("parameters", {})

    if ftype == "Gain":
        return params.get("gain", 0.0)

    if ftype == "Biquad":
        bq_type = params.get("type", "").lower()
        if bq_type in ("lowshelf", "highshelf", "peaking", "lowshelffo",
                        "highshelffo", "peakingfo"):
            gain = params.get("gain", 0.0)
            # Only count positive gain as worst-case boost
            return max(0.0, gain)
        # Other biquad types (notch, allpass, etc.): 0 dB passband
        return 0.0

    if ftype == "BiquadCombo":
        # HPF/LPF: 0 dB in passband (worst case)
        return 0.0

    if ftype == "Conv":
        # FIR boost handled separately via identity max_boost_db
        return 0.0

    if ftype == "Delay":
        return 0.0

    # Unknown filter type: conservative 0 dB assumption
    return 0.0


def trace_pipeline_gain_db(config, channel, fir_max_boost_db=0.0):
    """
    Trace the total gain for a channel through the CamillaDSP pipeline.

    Sums mixer gain + all filter gains applied to this channel in pipeline
    order, plus the FIR worst-case boost.

    Parameters
    ----------
    config : dict
        Parsed CamillaDSP configuration.
    channel : int
        Output channel index (0-based).
    fir_max_boost_db : float
        Worst-case boost from FIR convolution filters (from identity
        max_boost_db). Applied once for any Conv filter on this channel.

    Returns
    -------
    float
        Total worst-case gain in dB from 0 dBFS input to DAC output.
    """
    filters = config.get("filters", {})
    pipeline = config.get("pipeline", [])

    total_gain_db = 0.0
    fir_boost_applied = False

    for step in pipeline:
        step_type = step.get("type", "")

        if step_type == "Mixer":
            total_gain_db += get_mixer_gain_db(config, channel)

        elif step_type == "Filter":
            step_channels = step.get("channels", [])
            if channel in step_channels:
                for filter_name in step.get("names", []):
                    filter_def = filters.get(filter_name, {})
                    if filter_def.get("type") == "Conv" and not fir_boost_applied:
                        total_gain_db += fir_max_boost_db
                        fir_boost_applied = True
                    else:
                        total_gain_db += get_filter_gain_db(filter_def)

    return total_gain_db


# ----- Power computation --------------------------------------------------

def compute_power_watts(total_digital_gain_db, impedance_ohm,
                        dac_vrms=DAC_VRMS_AT_0DBFS,
                        amp_voltage_gain=AMP_VOLTAGE_GAIN):
    """
    Compute worst-case power at speaker terminals.

    Parameters
    ----------
    total_digital_gain_db : float
        Total digital gain from 0 dBFS to DAC output.
    impedance_ohm : float
        Speaker impedance in ohms.
    dac_vrms : float
        DAC output voltage at 0 dBFS in Vrms.
    amp_voltage_gain : float
        Amplifier voltage gain (linear).

    Returns
    -------
    float
        Power in watts at speaker terminals.
    """
    # Voltage at DAC output after digital gain
    v_dac = dac_vrms * (10 ** (total_digital_gain_db / 20.0))
    # Voltage at speaker terminals after amp
    v_speaker = v_dac * amp_voltage_gain
    # Power: P = V^2 / R
    return (v_speaker ** 2) / impedance_ohm


def power_margin_db(computed_watts, pe_max_watts):
    """
    Compute the safety margin between computed power and driver rating.

    Returns positive dB if safe (computed < limit), negative if over limit.
    """
    if computed_watts <= 0:
        return math.inf
    return 10.0 * math.log10(pe_max_watts / computed_watts)


# ----- Channel-to-speaker mapping -----------------------------------------

def map_channels_to_speakers(profile, identities_dir=None):
    """
    Build a mapping from channel index to speaker info (name, identity data).

    Returns
    -------
    dict
        {channel_index: {"name": str, "role": str, "identity": dict}}
    """
    directory = Path(identities_dir) if identities_dir else IDENTITIES_DIR
    channel_map = {}

    for spk_key, spk_cfg in profile.get("speakers", {}).items():
        ch = spk_cfg["channel"]
        id_name = spk_cfg["identity"]
        identity = load_identity(id_name, identities_dir=directory)
        channel_map[ch] = {
            "name": spk_key,
            "role": spk_cfg.get("role", "unknown"),
            "identity_name": id_name,
            "identity": identity,
        }

    return channel_map


# ----- Main validation ----------------------------------------------------

class ChannelResult:
    """Result of power budget validation for a single channel."""

    def __init__(self, channel, name, role, identity_name,
                 total_gain_db, computed_watts, pe_max_watts,
                 impedance_ohm, margin_db):
        self.channel = channel
        self.name = name
        self.role = role
        self.identity_name = identity_name
        self.total_gain_db = total_gain_db
        self.computed_watts = computed_watts
        self.pe_max_watts = pe_max_watts
        self.impedance_ohm = impedance_ohm
        self.margin_db = margin_db

    @property
    def passed(self):
        return self.margin_db >= 0

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return (
            f"  ch {self.channel} ({self.name}, {self.identity_name}): "
            f"{status}  "
            f"gain={self.total_gain_db:+.1f} dB  "
            f"power={self.computed_watts:.2f}W / {self.pe_max_watts:.0f}W  "
            f"margin={self.margin_db:+.1f} dB"
        )


def validate_power_budget(
    config_path,
    profile_name,
    profiles_dir=None,
    identities_dir=None,
    dac_vrms=DAC_VRMS_AT_0DBFS,
    amp_voltage_gain=AMP_VOLTAGE_GAIN,
):
    """
    Validate the power budget for all speaker channels in a CamillaDSP config.

    Parameters
    ----------
    config_path : str or Path
        Path to the CamillaDSP production YAML config.
    profile_name : str
        Speaker profile name (without .yml).
    profiles_dir : str or Path, optional
        Override profiles directory.
    identities_dir : str or Path, optional
        Override identities directory.
    dac_vrms : float
        DAC output voltage at 0 dBFS.
    amp_voltage_gain : float
        Amplifier voltage gain.

    Returns
    -------
    list of ChannelResult
        Validation results per speaker channel.
    """
    config = load_yaml(config_path)
    profile = load_profile(profile_name, profiles_dir=profiles_dir)
    channel_map = map_channels_to_speakers(
        profile, identities_dir=identities_dir
    )

    results = []
    for ch, spk_info in sorted(channel_map.items()):
        identity = spk_info["identity"]
        impedance = identity.get("impedance_ohm")
        pe_max = identity.get("max_power_watts")
        fir_max_boost = identity.get("max_boost_db", 0)

        if impedance is None or pe_max is None:
            # Cannot validate without impedance and power rating
            continue

        total_gain = trace_pipeline_gain_db(config, ch, fir_max_boost_db=fir_max_boost)
        power = compute_power_watts(
            total_gain, impedance,
            dac_vrms=dac_vrms,
            amp_voltage_gain=amp_voltage_gain,
        )
        margin = power_margin_db(power, pe_max)

        results.append(ChannelResult(
            channel=ch,
            name=spk_info["name"],
            role=spk_info["role"],
            identity_name=spk_info["identity_name"],
            total_gain_db=total_gain,
            computed_watts=power,
            pe_max_watts=pe_max,
            impedance_ohm=impedance,
            margin_db=margin,
        ))

    return results


def print_results(results, config_name=""):
    """Print validation results to stdout."""
    header = f"Power budget validation: {config_name}" if config_name else "Power budget validation"
    print(header)
    print(f"  DAC: {DAC_VRMS_AT_0DBFS} Vrms at 0 dBFS")
    print(f"  Amp: {AMP_VOLTAGE_GAIN}x voltage gain")
    print()

    all_pass = True
    for r in results:
        print(str(r))
        if not r.passed:
            all_pass = False

    print()
    if all_pass:
        print("RESULT: ALL CHANNELS PASS")
    else:
        print("RESULT: VALIDATION FAILED — one or more channels exceed pe_max")

    return all_pass


# ----- CLI -----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate CamillaDSP config power budget against speaker thermal limits."
    )
    parser.add_argument(
        "config",
        help="Path to CamillaDSP production config YAML.",
    )
    parser.add_argument(
        "profile",
        help="Speaker profile name (without .yml).",
    )
    parser.add_argument(
        "--profiles-dir",
        default=None,
        help="Override profiles directory.",
    )
    parser.add_argument(
        "--identities-dir",
        default=None,
        help="Override identities directory.",
    )
    parser.add_argument(
        "--dac-vrms",
        type=float,
        default=DAC_VRMS_AT_0DBFS,
        help=f"DAC Vrms at 0 dBFS (default: {DAC_VRMS_AT_0DBFS}).",
    )
    parser.add_argument(
        "--amp-gain",
        type=float,
        default=AMP_VOLTAGE_GAIN,
        help=f"Amplifier voltage gain (default: {AMP_VOLTAGE_GAIN}).",
    )

    args = parser.parse_args()

    results = validate_power_budget(
        config_path=args.config,
        profile_name=args.profile,
        profiles_dir=args.profiles_dir,
        identities_dir=args.identities_dir,
        dac_vrms=args.dac_vrms,
        amp_voltage_gain=args.amp_gain,
    )

    all_pass = print_results(results, config_name=args.config)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
