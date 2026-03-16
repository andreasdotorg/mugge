"""
CamillaDSP configuration generator from speaker profiles.

Takes a speaker profile (Layer 2) referencing speaker identities (Layer 1),
plus runtime parameters (filter paths, delays, mode), and produces a
CamillaDSP-compatible YAML configuration.

The output is built as a Python dict and serialised via yaml.dump() —
NO string templating.

Pipeline pattern: mixer -> headroom -> HPF -> FIR -> power_limit -> delay

Design decision D-029: headroom reservation creates digital space for FIR
boost. The headroom value must be >= max_boost_db + 0.5dB margin.
"""

import os
from datetime import datetime
from pathlib import Path

import yaml


# ----- Constants -------------------------------------------------------

# Project root: three levels up from this file
# src/room-correction/config_generator.py -> project root
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent.parent

IDENTITIES_DIR = PROJECT_ROOT / "configs" / "speakers" / "identities"
PROFILES_DIR = PROJECT_ROOT / "configs" / "speakers" / "profiles"

DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHUNKSIZE_DJ = 2048
DEFAULT_CHUNKSIZE_LIVE = 256
DEFAULT_QUEUELIMIT = 4
DEFAULT_DIRAC_PATH = "/etc/camilladsp/coeffs/dirac_16384.wav"

MAX_CHANNELS = 8
D029_MARGIN_DB = 0.5


# ----- YAML loading ----------------------------------------------------

def load_identity(name, identities_dir=None):
    """
    Load a speaker identity YAML file by name (without .yml extension).

    Parameters
    ----------
    name : str
        Identity file name (e.g., 'bose-jewel-double-cube').
    identities_dir : str or Path, optional
        Override directory for identity files.

    Returns
    -------
    dict
        Parsed identity data.

    Raises
    ------
    FileNotFoundError
        If the identity file does not exist.
    """
    directory = Path(identities_dir) if identities_dir else IDENTITIES_DIR
    path = directory / f"{name}.yml"
    if not path.exists():
        raise FileNotFoundError(
            f"Speaker identity file not found: {path}"
        )
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_profile(name, profiles_dir=None):
    """
    Load a speaker profile YAML file by name (without .yml extension).

    Parameters
    ----------
    name : str
        Profile file name (e.g., 'bose-home').
    profiles_dir : str or Path, optional
        Override directory for profile files.

    Returns
    -------
    dict
        Parsed profile data.

    Raises
    ------
    FileNotFoundError
        If the profile file does not exist.
    """
    directory = Path(profiles_dir) if profiles_dir else PROFILES_DIR
    path = directory / f"{name}.yml"
    if not path.exists():
        raise FileNotFoundError(
            f"Speaker profile file not found: {path}"
        )
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_profile_with_identities(profile_name, profiles_dir=None, identities_dir=None):
    """
    Load a profile and resolve all referenced speaker identities.

    Returns
    -------
    tuple of (dict, dict)
        (profile, identities) where identities maps speaker role keys
        to their loaded identity dicts.
    """
    profile = load_profile(profile_name, profiles_dir=profiles_dir)
    identities = {}
    for spk_key, spk_cfg in profile["speakers"].items():
        id_name = spk_cfg["identity"]
        if id_name not in identities:
            identities[id_name] = load_identity(
                id_name, identities_dir=identities_dir
            )
    return profile, identities


# ----- Validation -------------------------------------------------------

class ValidationError(Exception):
    """Raised when profile validation fails."""
    pass


def validate_profile(profile, identities, identities_dir=None):
    """
    Validate a speaker profile against its referenced identities.

    Checks:
    1. Channel budget <= MAX_CHANNELS (8)
    2. All referenced identity files exist
    3. Crossover frequency consistency (satellites HPF >= crossover,
       subs mandatory HPF < crossover)
    4. D-029 gain staging: |headroom| >= max_boost + D029_MARGIN_DB

    Parameters
    ----------
    profile : dict
        Loaded profile data.
    identities : dict
        Mapping of identity names to loaded identity dicts.
    identities_dir : str or Path, optional
        Override directory for identity files (used for existence check).

    Returns
    -------
    list of str
        List of validation errors (empty if valid).
    """
    errors = []
    directory = Path(identities_dir) if identities_dir else IDENTITIES_DIR

    # 1. Channel budget
    used_channels = set()
    for spk_key, spk_cfg in profile["speakers"].items():
        used_channels.add(spk_cfg["channel"])
    monitoring = profile.get("monitoring", {})
    for mon_key, ch in monitoring.items():
        used_channels.add(ch)
    if max(used_channels) >= MAX_CHANNELS:
        if len(used_channels) > MAX_CHANNELS:
            errors.append(
                f"Channel budget exceeded: {len(used_channels)} channels "
                f"used, maximum is {MAX_CHANNELS}."
            )
    # Also check no channel index >= MAX_CHANNELS
    for ch in used_channels:
        if ch >= MAX_CHANNELS:
            errors.append(
                f"Channel index {ch} exceeds maximum index "
                f"{MAX_CHANNELS - 1} (0-indexed, {MAX_CHANNELS} channels)."
            )

    # 2. Identity files exist
    for spk_key, spk_cfg in profile["speakers"].items():
        id_name = spk_cfg["identity"]
        id_path = directory / f"{id_name}.yml"
        if not id_path.exists():
            errors.append(
                f"Identity file missing for speaker '{spk_key}': "
                f"{id_path}"
            )

    # 3. Crossover frequency consistency
    crossover_freq = profile.get("crossover", {}).get("frequency_hz")
    if crossover_freq:
        for spk_key, spk_cfg in profile["speakers"].items():
            id_name = spk_cfg["identity"]
            identity = identities.get(id_name, {})
            mandatory_hpf = identity.get("mandatory_hpf_hz")
            filter_type = spk_cfg.get("filter_type")

            # For subs with a mandatory HPF, it should be below the crossover
            if filter_type == "lowpass" and mandatory_hpf:
                if mandatory_hpf >= crossover_freq:
                    errors.append(
                        f"Speaker '{spk_key}': mandatory HPF ({mandatory_hpf}Hz) "
                        f">= crossover ({crossover_freq}Hz). Sub would have "
                        f"no passband."
                    )

    # 4. D-031: All speakers MUST declare subsonic protection
    for spk_key, spk_cfg in profile["speakers"].items():
        id_name = spk_cfg["identity"]
        identity = identities.get(id_name, {})
        if identity.get("mandatory_hpf_hz") is None:
            errors.append(
                f"D-031 violation: Speaker '{spk_key}' ({id_name}) has no "
                f"mandatory_hpf_hz. All speakers MUST declare subsonic protection."
            )

    # 5. D-029 gain staging math
    gain_staging = profile.get("gain_staging", {})
    for spk_key, spk_cfg in profile["speakers"].items():
        id_name = spk_cfg["identity"]
        identity = identities.get(id_name, {})
        max_boost = identity.get("max_boost_db", 0)
        role = spk_cfg.get("role", "")

        # Map role to gain staging group
        if role == "satellite":
            gs_group = gain_staging.get("satellite", {})
        elif role == "subwoofer":
            gs_group = gain_staging.get("subwoofer", {})
        else:
            continue

        headroom = gs_group.get("headroom_db", 0)
        # headroom is negative; |headroom| must be >= max_boost + margin
        if abs(headroom) < max_boost + D029_MARGIN_DB:
            errors.append(
                f"D-029 violation for speaker '{spk_key}' ({id_name}): "
                f"|headroom| ({abs(headroom):.1f}dB) < "
                f"max_boost ({max_boost}dB) + margin ({D029_MARGIN_DB}dB) = "
                f"{max_boost + D029_MARGIN_DB:.1f}dB."
            )

    return errors


def validate_and_raise(profile, identities, identities_dir=None):
    """Validate and raise ValidationError if any errors found."""
    errors = validate_profile(profile, identities, identities_dir=identities_dir)
    if errors:
        raise ValidationError(
            "Profile validation failed:\n  - " + "\n  - ".join(errors)
        )


def validate_hpf_in_config(profile, identities, config):
    """
    Post-generation validation: verify that every speaker with a mandatory
    HPF in its identity has a corresponding HPF filter definition AND
    pipeline step in the generated config.

    Parameters
    ----------
    profile : dict
        Loaded profile data.
    identities : dict
        Mapping of identity names to loaded identity dicts.
    config : dict
        Generated CamillaDSP configuration dict.

    Raises
    ------
    ValidationError
        If any mandatory HPF is missing from the generated config.
    """
    errors = []
    filters = config.get("filters", {})
    pipeline = config.get("pipeline", [])

    # Collect all filter names referenced in pipeline steps
    pipeline_filter_names = set()
    for step in pipeline:
        if step.get("type") == "Filter":
            for name in step.get("names", []):
                pipeline_filter_names.add(name)

    for spk_key, spk_cfg in profile["speakers"].items():
        id_name = spk_cfg["identity"]
        identity = identities.get(id_name, {})
        mandatory_hpf = identity.get("mandatory_hpf_hz")

        if mandatory_hpf is None:
            errors.append(
                f"Speaker '{spk_key}' ({id_name}) has mandatory_hpf_hz=None "
                f"in identity. Subsonic protection is missing — cannot validate "
                f"HPF in generated config."
            )
            continue

        hpf_name = f"{spk_key}_hpf"

        if hpf_name not in filters:
            errors.append(
                f"Speaker '{spk_key}' ({id_name}) requires mandatory HPF "
                f"at {mandatory_hpf}Hz but filter '{hpf_name}' is missing "
                f"from generated config."
            )
        if hpf_name not in pipeline_filter_names:
            errors.append(
                f"Speaker '{spk_key}' ({id_name}) requires mandatory HPF "
                f"at {mandatory_hpf}Hz but '{hpf_name}' is not in the "
                f"pipeline."
            )

    if errors:
        raise ValidationError(
            "Mandatory HPF validation failed:\n  - " + "\n  - ".join(errors)
        )


# ----- CamillaDSP config generation ------------------------------------

def _classify_speakers(profile):
    """
    Classify speakers into satellite and subwoofer groups.

    Returns
    -------
    tuple of (list, list)
        (satellites, subwoofers) where each entry is (key, config).
    """
    satellites = []
    subwoofers = []
    for spk_key, spk_cfg in profile["speakers"].items():
        if spk_cfg["role"] == "satellite":
            satellites.append((spk_key, spk_cfg))
        elif spk_cfg["role"] == "subwoofer":
            subwoofers.append((spk_key, spk_cfg))
    return satellites, subwoofers


def _build_devices(mode="dj", sample_rate=DEFAULT_SAMPLE_RATE):
    """Build the CamillaDSP devices section."""
    chunksize = DEFAULT_CHUNKSIZE_DJ if mode == "dj" else DEFAULT_CHUNKSIZE_LIVE
    return {
        "samplerate": sample_rate,
        "chunksize": chunksize,
        "queuelimit": DEFAULT_QUEUELIMIT,
        "capture": {
            "type": "Alsa",
            "channels": MAX_CHANNELS,
            "device": "hw:Loopback,1,0",
            "format": "S32LE",
        },
        "playback": {
            "type": "Alsa",
            "channels": MAX_CHANNELS,
            "device": "hw:USBStreamer,0",
            "format": "S32LE",
        },
    }


def _build_mixer(profile):
    """
    Build the CamillaDSP mixer section from profile.

    Satellites get a direct 1:1 mapping from their input channel.
    Subwoofers get a mono sum of L+R (channels 0+1) with -6dB per source.
    Sub polarity inversion is applied here via the 'inverted' flag.
    Monitoring channels pass through directly.
    """
    satellites, subwoofers = _classify_speakers(profile)
    monitoring = profile.get("monitoring", {})

    mixer_name = f"route_{profile['name'].lower().replace(' ', '_').replace('-', '_')}"
    mapping = []

    # Satellite mappings: direct 1:1 from input channel
    for spk_key, spk_cfg in satellites:
        ch = spk_cfg["channel"]
        mapping.append({
            "dest": ch,
            "sources": [{
                "channel": ch,
                "gain": 0,
                "inverted": False,
            }],
        })

    # Subwoofer mappings: mono sum of L+R
    for spk_key, spk_cfg in subwoofers:
        ch = spk_cfg["channel"]
        is_inverted = spk_cfg.get("polarity", "normal") == "inverted"
        mapping.append({
            "dest": ch,
            "sources": [
                {"channel": 0, "gain": -6, "inverted": is_inverted},
                {"channel": 1, "gain": -6, "inverted": is_inverted},
            ],
        })

    # Monitoring passthrough
    mon_channels = [
        ("hp_left", monitoring.get("hp_left")),
        ("hp_right", monitoring.get("hp_right")),
        ("hp2_left", monitoring.get("hp2_left")),
        ("hp2_right", monitoring.get("hp2_right")),
    ]
    for mon_name, ch in mon_channels:
        if ch is not None:
            mapping.append({
                "dest": ch,
                "sources": [{
                    "channel": ch,
                    "gain": 0,
                    "inverted": False,
                }],
            })

    return mixer_name, {
        "channels": {
            "in": MAX_CHANNELS,
            "out": MAX_CHANNELS,
        },
        "mapping": mapping,
    }


def _resolve_speaker_identities(profile, identities):
    """
    Build a mapping from speaker key to its resolved identity dict.

    Parameters
    ----------
    profile : dict
        Loaded profile data.
    identities : dict
        Mapping of identity names to loaded identity dicts.

    Returns
    -------
    dict
        Mapping of speaker key to identity dict.
    """
    spk_identities = {}
    for spk_key, spk_cfg in profile["speakers"].items():
        id_name = spk_cfg["identity"]
        if id_name in identities:
            spk_identities[spk_key] = identities[id_name]
    return spk_identities


def _build_filters(profile, identities=None, filter_paths=None):
    """
    Build the CamillaDSP filters section.

    Creates headroom, HPF (mandatory subsonic protection), FIR convolution,
    and power limit filters.

    Parameters
    ----------
    profile : dict
        Loaded profile data.
    identities : dict, optional
        Mapping of identity names to loaded identity dicts.
        Used to generate mandatory HPF filters.
    filter_paths : dict, optional
        Mapping of speaker keys to FIR WAV file paths.
        If not provided, uses DEFAULT_DIRAC_PATH for all.

    Returns
    -------
    dict
        Filters section for CamillaDSP config.
    """
    if filter_paths is None:
        filter_paths = {}
    if identities is None:
        identities = {}

    gain_staging = profile.get("gain_staging", {})
    satellites, subwoofers = _classify_speakers(profile)
    spk_identities = _resolve_speaker_identities(profile, identities)

    filters = {}

    # Headroom filters
    sat_gs = gain_staging.get("satellite", {})
    sub_gs = gain_staging.get("subwoofer", {})

    filters["sat_headroom"] = {
        "type": "Gain",
        "parameters": {
            "gain": float(sat_gs.get("headroom_db", -7.0)),
        },
    }
    filters["sub_headroom"] = {
        "type": "Gain",
        "parameters": {
            "gain": float(sub_gs.get("headroom_db", -13.0)),
        },
    }

    # Mandatory HPF filters (subsonic protection per speaker identity)
    for spk_key, spk_cfg in satellites + subwoofers:
        identity = spk_identities.get(spk_key, {})
        mandatory_hpf = identity.get("mandatory_hpf_hz")
        if mandatory_hpf is not None:
            filters[f"{spk_key}_hpf"] = {
                "type": "BiquadCombo",
                "parameters": {
                    "type": "ButterworthHighpass",
                    "order": 4,
                    "freq": mandatory_hpf,
                },
            }

    # FIR convolution filters (one per speaker)
    for spk_key, spk_cfg in satellites + subwoofers:
        fir_path = filter_paths.get(spk_key, DEFAULT_DIRAC_PATH)
        filter_name = f"{spk_key}_fir"
        filters[filter_name] = {
            "type": "Conv",
            "parameters": {
                "type": "Wav",
                "filename": fir_path,
            },
        }

    # Power limit filters
    filters["sat_power_limit"] = {
        "type": "Gain",
        "parameters": {
            "gain": float(sat_gs.get("power_limit_db", -13.5)),
        },
    }
    filters["sub_power_limit"] = {
        "type": "Gain",
        "parameters": {
            "gain": float(sub_gs.get("power_limit_db", -8.6)),
        },
    }

    return filters


def _build_pipeline(profile, mixer_name, identities=None, delays=None):
    """
    Build the CamillaDSP pipeline section.

    Pipeline pattern: mixer -> headroom -> HPF -> FIR -> power_limit -> delay

    Parameters
    ----------
    profile : dict
        Loaded profile data.
    mixer_name : str
        Name of the mixer (from _build_mixer).
    identities : dict, optional
        Mapping of identity names to loaded identity dicts.
        Used to determine which speakers need HPF pipeline steps.
    delays : dict, optional
        Mapping of speaker keys to delay in ms. If provided, delay
        filters are appended to the pipeline.

    Returns
    -------
    list
        Pipeline steps for CamillaDSP config.
    """
    if identities is None:
        identities = {}

    satellites, subwoofers = _classify_speakers(profile)
    spk_identities = _resolve_speaker_identities(profile, identities)
    pipeline = []

    # 1. Mixer
    pipeline.append({
        "type": "Mixer",
        "name": mixer_name,
    })

    # 2. Headroom reservation (before FIR)
    sat_channels = [spk_cfg["channel"] for _, spk_cfg in satellites]
    sub_channels = [spk_cfg["channel"] for _, spk_cfg in subwoofers]

    if sat_channels:
        pipeline.append({
            "type": "Filter",
            "channels": sat_channels,
            "names": ["sat_headroom"],
        })
    if sub_channels:
        pipeline.append({
            "type": "Filter",
            "channels": sub_channels,
            "names": ["sub_headroom"],
        })

    # 3. Mandatory HPF (subsonic protection, before FIR)
    for spk_key, spk_cfg in satellites + subwoofers:
        identity = spk_identities.get(spk_key, {})
        mandatory_hpf = identity.get("mandatory_hpf_hz")
        if mandatory_hpf is not None:
            ch = spk_cfg["channel"]
            pipeline.append({
                "type": "Filter",
                "channels": [ch],
                "names": [f"{spk_key}_hpf"],
            })

    # 4. FIR convolution (one per speaker channel)
    for spk_key, spk_cfg in satellites + subwoofers:
        ch = spk_cfg["channel"]
        filter_name = f"{spk_key}_fir"
        pipeline.append({
            "type": "Filter",
            "channels": [ch],
            "names": [filter_name],
        })

    # 5. Power limiting (after FIR)
    if sat_channels:
        pipeline.append({
            "type": "Filter",
            "channels": sat_channels,
            "names": ["sat_power_limit"],
        })
    if sub_channels:
        pipeline.append({
            "type": "Filter",
            "channels": sub_channels,
            "names": ["sub_power_limit"],
        })

    # 6. Delay (optional, only if delay values provided)
    if delays:
        for spk_key, spk_cfg in satellites + subwoofers:
            delay_ms = delays.get(spk_key)
            if delay_ms and delay_ms > 0:
                ch = spk_cfg["channel"]
                delay_filter_name = f"{spk_key}_delay"
                pipeline.append({
                    "type": "Filter",
                    "channels": [ch],
                    "names": [delay_filter_name],
                })

    return pipeline


def _build_delay_filters(profile, delays):
    """
    Build delay filters for speakers that need time alignment.

    Parameters
    ----------
    profile : dict
        Loaded profile data.
    delays : dict
        Mapping of speaker keys to delay in ms.

    Returns
    -------
    dict
        Delay filter definitions to merge into the filters section.
    """
    delay_filters = {}
    for spk_key, spk_cfg in profile["speakers"].items():
        delay_ms = delays.get(spk_key)
        if delay_ms and delay_ms > 0:
            delay_filters[f"{spk_key}_delay"] = {
                "type": "Delay",
                "parameters": {
                    "delay": float(delay_ms),
                    "unit": "ms",
                },
            }
    return delay_filters


def generate_config(
    profile_name,
    filter_paths=None,
    delays=None,
    mode="dj",
    sample_rate=DEFAULT_SAMPLE_RATE,
    profiles_dir=None,
    identities_dir=None,
    validate=True,
):
    """
    Generate a complete CamillaDSP configuration from a speaker profile.

    Parameters
    ----------
    profile_name : str
        Name of the speaker profile (without .yml).
    filter_paths : dict, optional
        Mapping of speaker keys to FIR WAV file paths.
        Keys should match speaker keys in the profile (e.g., 'sat_left').
        If not provided, uses dirac placeholder for all.
    delays : dict, optional
        Mapping of speaker keys to delay values in ms.
    mode : str
        'dj' or 'live' — controls chunksize.
    sample_rate : int
        Audio sample rate.
    profiles_dir : str or Path, optional
        Override profiles directory.
    identities_dir : str or Path, optional
        Override identities directory.
    validate : bool
        If True, validate the profile before generating.

    Returns
    -------
    dict
        Complete CamillaDSP configuration as a Python dict.

    Raises
    ------
    ValidationError
        If validation is enabled and the profile fails validation.
    FileNotFoundError
        If the profile or any referenced identity file is not found.
    """
    profile, identities = load_profile_with_identities(
        profile_name,
        profiles_dir=profiles_dir,
        identities_dir=identities_dir,
    )

    if validate:
        validate_and_raise(profile, identities, identities_dir=identities_dir)

    # Build each config section
    devices = _build_devices(mode=mode, sample_rate=sample_rate)
    mixer_name, mixer_def = _build_mixer(profile)
    filters = _build_filters(
        profile, identities=identities, filter_paths=filter_paths,
    )
    pipeline = _build_pipeline(
        profile, mixer_name, identities=identities, delays=delays,
    )

    # Add delay filters if specified
    if delays:
        delay_filters = _build_delay_filters(profile, delays)
        filters.update(delay_filters)

    config = {
        "devices": devices,
        "mixers": {mixer_name: mixer_def},
        "filters": filters,
        "pipeline": pipeline,
    }

    # TK-108: Post-generation validation — verify mandatory HPF presence
    validate_hpf_in_config(profile, identities, config)

    return config


def generate_config_yaml(
    profile_name,
    filter_paths=None,
    delays=None,
    mode="dj",
    sample_rate=DEFAULT_SAMPLE_RATE,
    profiles_dir=None,
    identities_dir=None,
    validate=True,
):
    """
    Generate CamillaDSP configuration and return as YAML string.

    Parameters are identical to generate_config().

    Returns
    -------
    str
        YAML-formatted CamillaDSP configuration.
    """
    config = generate_config(
        profile_name,
        filter_paths=filter_paths,
        delays=delays,
        mode=mode,
        sample_rate=sample_rate,
        profiles_dir=profiles_dir,
        identities_dir=identities_dir,
        validate=validate,
    )
    return yaml.dump(config, default_flow_style=False, sort_keys=False)


def write_config(
    output_path,
    profile_name,
    filter_paths=None,
    delays=None,
    mode="dj",
    sample_rate=DEFAULT_SAMPLE_RATE,
    profiles_dir=None,
    identities_dir=None,
    validate=True,
):
    """
    Generate and write CamillaDSP configuration to a file.

    Parameters are identical to generate_config() plus output_path.

    Parameters
    ----------
    output_path : str or Path
        Path to write the YAML configuration file.
    """
    config = generate_config(
        profile_name,
        filter_paths=filter_paths,
        delays=delays,
        mode=mode,
        sample_rate=sample_rate,
        profiles_dir=profiles_dir,
        identities_dir=identities_dir,
        validate=validate,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    return output_path


# ----- TK-166: Versioned filter path helpers --------------------------------

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


def versioned_filter_paths(
    speaker_keys,
    coeffs_dir="/etc/camilladsp/coeffs",
    timestamp=None,
):
    """
    Build a filter_paths dict with versioned (timestamped) filenames.

    CamillaDSP caches FIR coefficient files by filename. Using timestamped
    filenames ensures config.reload() picks up new coefficients.

    Parameters
    ----------
    speaker_keys : list of str
        Speaker keys from the profile, e.g. ['sat_left', 'sat_right',
        'sub1', 'sub2'].
    coeffs_dir : str
        Directory where coefficient files will be deployed.
    timestamp : datetime, optional
        Timestamp to embed. Defaults to datetime.now().

    Returns
    -------
    dict
        Mapping of speaker keys to versioned file paths,
        e.g. {'sat_left': '/etc/camilladsp/coeffs/combined_left_hp_20260314_143022.wav'}.
    """
    if timestamp is None:
        timestamp = datetime.now()
    ts_str = timestamp.strftime(TIMESTAMP_FORMAT)

    # Map speaker keys to their channel names for filename generation.
    # The convention: speaker key 'sat_left' -> channel 'left_hp',
    # 'sat_right' -> 'right_hp', 'sub1' -> 'sub1_lp', 'sub2' -> 'sub2_lp'.
    # For keys that don't match this pattern, use the key directly.
    _KEY_TO_CHANNEL = {
        "sat_left": "left_hp",
        "sat_right": "right_hp",
        "sub1": "sub1_lp",
        "sub2": "sub2_lp",
    }

    paths = {}
    for key in speaker_keys:
        channel = _KEY_TO_CHANNEL.get(key, key)
        filename = f"combined_{channel}_{ts_str}.wav"
        paths[key] = os.path.join(coeffs_dir, filename)

    return paths
