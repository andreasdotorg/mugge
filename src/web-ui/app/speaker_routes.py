"""Speaker configuration REST endpoints.

US-089: CRUD access to speaker identity and profile YAML files.

Read endpoints (Phase 1):
    GET /api/v1/speakers/identities         List all speaker identities
    GET /api/v1/speakers/identities/{name}   Read one identity by filename stem
    GET /api/v1/speakers/profiles            List all speaker profiles
    GET /api/v1/speakers/profiles/{name}     Read one profile by filename stem

Write endpoints (Phase 2):
    POST   /api/v1/speakers/identities         Create new identity
    PUT    /api/v1/speakers/identities/{name}  Update existing identity
    DELETE /api/v1/speakers/identities/{name}  Delete identity
    POST   /api/v1/speakers/profiles           Create new profile
    PUT    /api/v1/speakers/profiles/{name}    Update existing profile
    DELETE /api/v1/speakers/profiles/{name}    Delete profile

YAML files live under ``configs/speakers/identities/`` and
``configs/speakers/profiles/`` in the repo (development) or on the Pi.
"""

from __future__ import annotations

import logging
import os
import pathlib
import re
from typing import Any

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/speakers", tags=["speakers"])

# Resolve config directories: check Pi path first, then repo fallback.
_PI_SPEAKERS_DIR = pathlib.Path(
    os.environ.get("PI4AUDIO_SPEAKERS_DIR", "/etc/pi4audio/speakers")
)
_REPO_SPEAKERS_DIR = (
    pathlib.Path(__file__).resolve().parents[3] / "configs" / "speakers"
)
_PI_REPO_SPEAKERS_DIR = pathlib.Path.home() / "pi4-audio-workstation" / "configs" / "speakers"

# Allowed filename characters (prevent path traversal).
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _speakers_dir() -> pathlib.Path | None:
    """Return the speakers config directory, checking Pi path then repo."""
    if _PI_SPEAKERS_DIR.is_dir():
        return _PI_SPEAKERS_DIR
    if _REPO_SPEAKERS_DIR.is_dir():
        return _REPO_SPEAKERS_DIR
    if _PI_REPO_SPEAKERS_DIR.is_dir():
        return _PI_REPO_SPEAKERS_DIR
    return None


def _list_yamls(subdir: str) -> list[dict]:
    """List YAML files in a speakers subdirectory.

    Returns a list of {name, filename} dicts sorted by name.
    """
    base = _speakers_dir()
    if base is None:
        return []
    d = base / subdir
    if not d.is_dir():
        return []
    result = []
    for f in sorted(d.iterdir()):
        if f.suffix in (".yml", ".yaml") and f.is_file():
            try:
                data = yaml.safe_load(f.read_text())
            except Exception:
                data = {}
            display_name = data.get("name", f.stem) if isinstance(data, dict) else f.stem
            result.append({"name": f.stem, "display_name": display_name})
    return result


def _read_yaml(subdir: str, name: str) -> dict | None:
    """Read a single YAML file by stem name from a speakers subdirectory."""
    if not _SAFE_NAME.match(name):
        return None
    base = _speakers_dir()
    if base is None:
        return None
    d = base / subdir
    # Try .yml first (project convention), then .yaml.
    for ext in (".yml", ".yaml"):
        path = d / (name + ext)
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text())
                return data if isinstance(data, dict) else None
            except Exception as exc:
                log.warning("Failed to parse %s: %s", path, exc)
                return None
    return None


def _resolve_yaml_path(subdir: str, name: str) -> pathlib.Path | None:
    """Return the path for a YAML file (existing or new).

    For existing files: returns the found path (.yml or .yaml).
    For new files: returns the .yml path (project convention).
    Returns None if name is invalid or base dir not found.
    """
    if not _SAFE_NAME.match(name):
        return None
    base = _speakers_dir()
    if base is None:
        return None
    d = base / subdir
    # Return existing file path if found.
    for ext in (".yml", ".yaml"):
        path = d / (name + ext)
        if path.is_file():
            return path
    # New file: use .yml convention.
    return d / (name + ".yml")


def _write_yaml(subdir: str, name: str, data: dict) -> pathlib.Path | None:
    """Write a dict to a YAML file. Returns the path on success, None on failure."""
    path = _resolve_yaml_path(subdir, name)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        return path
    except Exception as exc:
        log.warning("Failed to write %s: %s", path, exc)
        return None


def _delete_yaml(subdir: str, name: str) -> bool:
    """Delete a YAML file by stem name. Returns True if deleted."""
    if not _SAFE_NAME.match(name):
        return False
    base = _speakers_dir()
    if base is None:
        return False
    d = base / subdir
    for ext in (".yml", ".yaml"):
        path = d / (name + ext)
        if path.is_file():
            path.unlink()
            return True
    return False


# -- Schema validation --------------------------------------------------------

# Required fields for speaker identities (from existing YAML convention).
_IDENTITY_REQUIRED = {"name", "type", "impedance_ohm", "sensitivity_db_spl", "max_boost_db", "mandatory_hpf_hz"}

# Required fields for speaker profiles.
_PROFILE_REQUIRED = {"name", "topology", "crossover", "speakers"}

# Required fields within a profile's crossover section.
_CROSSOVER_REQUIRED = {"frequency_hz", "slope_db_per_oct", "type"}

# Valid identity enclosure types.
_VALID_TYPES = {"sealed", "ported", "open-baffle", "horn", "bandpass", "transmission-line"}

# Valid profile topologies.
_VALID_TOPOLOGIES = {"2way", "3way", "4way", "meh"}

# Valid speaker roles.
_VALID_ROLES = {"satellite", "subwoofer", "fullrange", "midrange", "tweeter"}

# Valid filter types.
_VALID_FILTER_TYPES = {"highpass", "lowpass", "fullrange", "bandpass"}

# Valid polarities.
_VALID_POLARITIES = {"normal", "inverted"}

# Valid enclosure types per speaker in a profile.
_VALID_ENCLOSURE_TYPES = {"sealed", "ported", "horn", "bandpass", "onken", "open_baffle", "isobaric"}

# Valid GM modes for mode_constraints.
_VALID_GM_MODES = {"dj", "live", "monitoring", "measurement"}

# Maximum channel index (0-indexed, 8 channels total).
_MAX_CHANNEL = 7

# D-029 gain staging margin.
_D029_MARGIN_DB = 0.5

# Expected stereo speaker counts per topology (speaker channels, not monitoring).
_TOPOLOGY_SPEAKER_COUNTS = {"2way": 4, "3way": 6, "4way": 8, "meh": None}


def _validate_identity(data: Any) -> str | None:
    """Validate an identity dict. Returns error string, or None if valid."""
    if not isinstance(data, dict):
        return "Body must be a JSON object"
    missing = _IDENTITY_REQUIRED - data.keys()
    if missing:
        return f"Missing required fields: {', '.join(sorted(missing))}"
    if not isinstance(data["name"], str) or not data["name"].strip():
        return "'name' must be a non-empty string"
    if data["type"] not in _VALID_TYPES:
        return f"'type' must be one of: {', '.join(sorted(_VALID_TYPES))}"
    if not isinstance(data["impedance_ohm"], (int, float)):
        return "'impedance_ohm' must be a number"
    if not isinstance(data["sensitivity_db_spl"], (int, float)):
        return "'sensitivity_db_spl' must be a number"
    if not isinstance(data["max_boost_db"], (int, float)):
        return "'max_boost_db' must be a number"
    if not isinstance(data["mandatory_hpf_hz"], (int, float)):
        return "'mandatory_hpf_hz' must be a number"
    return None


def _validate_crossover(xover: Any, label: str = "crossover") -> str | None:
    """Validate a single crossover object. Returns error string, or None."""
    if not isinstance(xover, dict):
        return f"'{label}' must be an object"
    xover_missing = _CROSSOVER_REQUIRED - xover.keys()
    if xover_missing:
        return f"{label} missing fields: {', '.join(sorted(xover_missing))}"
    if not isinstance(xover["frequency_hz"], (int, float)):
        return f"'{label}.frequency_hz' must be a number"
    return None


def _validate_profile(data: Any) -> str | None:
    """Validate a profile dict. Returns error string, or None if valid."""
    if not isinstance(data, dict):
        return "Body must be a JSON object"
    missing = _PROFILE_REQUIRED - data.keys()
    if missing:
        return f"Missing required fields: {', '.join(sorted(missing))}"
    if not isinstance(data["name"], str) or not data["name"].strip():
        return "'name' must be a non-empty string"
    if not isinstance(data["topology"], str):
        return "'topology' must be a string"
    if data["topology"] not in _VALID_TOPOLOGIES:
        return (f"'topology' must be one of: "
                f"{', '.join(sorted(_VALID_TOPOLOGIES))}")
    # Validate crossover section — single object or list for multi-way.
    xover = data["crossover"]
    if isinstance(xover, list):
        if len(xover) == 0:
            return "'crossover' list must not be empty"
        for i, xo in enumerate(xover):
            err = _validate_crossover(xo, f"crossovers[{i}]")
            if err:
                return err
    else:
        err = _validate_crossover(xover, "crossover")
        if err:
            return err
    # Validate speakers section.
    speakers = data["speakers"]
    if not isinstance(speakers, dict) or len(speakers) == 0:
        return "'speakers' must be a non-empty object"
    for spk_name, spk in speakers.items():
        if not isinstance(spk, dict):
            return f"speakers.{spk_name} must be an object"
        if "identity" not in spk:
            return f"speakers.{spk_name} missing 'identity'"
        if "role" not in spk:
            return f"speakers.{spk_name} missing 'role'"
        if spk["role"] not in _VALID_ROLES:
            return (f"speakers.{spk_name}.role must be one of: "
                    f"{', '.join(sorted(_VALID_ROLES))}")
        if "channel" not in spk:
            return f"speakers.{spk_name} missing 'channel'"
        if not isinstance(spk["channel"], int) or spk["channel"] < 0 or spk["channel"] > _MAX_CHANNEL:
            return f"speakers.{spk_name}.channel must be an integer 0-{_MAX_CHANNEL}"
        # Optional: delay_ms
        if "delay_ms" in spk:
            if not isinstance(spk["delay_ms"], (int, float)):
                return f"speakers.{spk_name}.delay_ms must be a number"
            if spk["delay_ms"] < 0:
                return f"speakers.{spk_name}.delay_ms must be >= 0"
        # Optional: enclosure_type
        if "enclosure_type" in spk:
            if spk["enclosure_type"] not in _VALID_ENCLOSURE_TYPES:
                return (f"speakers.{spk_name}.enclosure_type must be one of: "
                        f"{', '.join(sorted(_VALID_ENCLOSURE_TYPES))}")
    # Optional: mode_constraints
    if "mode_constraints" in data:
        mc = data["mode_constraints"]
        if not isinstance(mc, list):
            return "'mode_constraints' must be a list"
        for mode in mc:
            if mode not in _VALID_GM_MODES:
                return (f"mode_constraints: '{mode}' is not a valid mode. "
                        f"Must be one of: {', '.join(sorted(_VALID_GM_MODES))}")
    return None


def _name_error(name: str) -> JSONResponse | None:
    """Return a 400 response if the name is invalid, or None if valid."""
    if not _SAFE_NAME.match(name):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_name",
                     "detail": "Name must match [a-zA-Z0-9][a-zA-Z0-9._-]*"},
        )
    return None


# -- Identity endpoints -------------------------------------------------------

@router.get("/identities")
async def list_identities():
    """List all speaker identity YAML files."""
    return {"identities": _list_yamls("identities")}


@router.get("/identities/{name}")
async def get_identity(name: str):
    """Read a single speaker identity by filename stem."""
    data = _read_yaml("identities", name)
    if data is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Speaker identity '{name}' not found"},
        )
    return data


@router.post("/identities")
async def create_identity(body: dict[str, Any]):
    """Create a new speaker identity YAML file.

    The filename stem is derived from the body by slugifying the 'name' field.
    If a 'slug' field is provided, it is used instead.
    """
    err = _validate_identity(body)
    if err:
        return JSONResponse(status_code=422, content={"error": "validation", "detail": err})
    slug = body.pop("slug", None) or _slugify(body["name"])
    name_err = _name_error(slug)
    if name_err:
        return name_err
    if _read_yaml("identities", slug) is not None:
        return JSONResponse(
            status_code=409,
            content={"error": "already_exists",
                     "detail": f"Identity '{slug}' already exists"},
        )
    path = _write_yaml("identities", slug, body)
    if path is None:
        return JSONResponse(status_code=500, content={"error": "write_failed"})
    return JSONResponse(status_code=201, content={"ok": True, "name": slug})


@router.put("/identities/{name}")
async def update_identity(name: str, body: dict[str, Any]):
    """Update an existing speaker identity YAML file."""
    name_err = _name_error(name)
    if name_err:
        return name_err
    if _read_yaml("identities", name) is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Speaker identity '{name}' not found"},
        )
    err = _validate_identity(body)
    if err:
        return JSONResponse(status_code=422, content={"error": "validation", "detail": err})
    path = _write_yaml("identities", name, body)
    if path is None:
        return JSONResponse(status_code=500, content={"error": "write_failed"})
    return {"ok": True, "name": name}


@router.delete("/identities/{name}")
async def delete_identity(name: str):
    """Delete a speaker identity YAML file."""
    name_err = _name_error(name)
    if name_err:
        return name_err
    if not _delete_yaml("identities", name):
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Speaker identity '{name}' not found"},
        )
    return {"ok": True, "name": name}


# -- Profile endpoints --------------------------------------------------------

@router.get("/profiles")
async def list_profiles():
    """List all speaker profile YAML files."""
    return {"profiles": _list_yamls("profiles")}


@router.get("/profiles/{name}")
async def get_profile(name: str):
    """Read a single speaker profile by filename stem."""
    data = _read_yaml("profiles", name)
    if data is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Speaker profile '{name}' not found"},
        )
    return data


@router.post("/profiles")
async def create_profile(body: dict[str, Any]):
    """Create a new speaker profile YAML file."""
    err = _validate_profile(body)
    if err:
        return JSONResponse(status_code=422, content={"error": "validation", "detail": err})
    slug = body.pop("slug", None) or _slugify(body["name"])
    name_err = _name_error(slug)
    if name_err:
        return name_err
    if _read_yaml("profiles", slug) is not None:
        return JSONResponse(
            status_code=409,
            content={"error": "already_exists",
                     "detail": f"Profile '{slug}' already exists"},
        )
    path = _write_yaml("profiles", slug, body)
    if path is None:
        return JSONResponse(status_code=500, content={"error": "write_failed"})
    return JSONResponse(status_code=201, content={"ok": True, "name": slug})


@router.put("/profiles/{name}")
async def update_profile(name: str, body: dict[str, Any]):
    """Update an existing speaker profile YAML file."""
    name_err = _name_error(name)
    if name_err:
        return name_err
    if _read_yaml("profiles", name) is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Speaker profile '{name}' not found"},
        )
    err = _validate_profile(body)
    if err:
        return JSONResponse(status_code=422, content={"error": "validation", "detail": err})
    path = _write_yaml("profiles", name, body)
    if path is None:
        return JSONResponse(status_code=500, content={"error": "write_failed"})
    return {"ok": True, "name": name}


@router.delete("/profiles/{name}")
async def delete_profile(name: str):
    """Delete a speaker profile YAML file."""
    name_err = _name_error(name)
    if name_err:
        return name_err
    if not _delete_yaml("profiles", name):
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Speaker profile '{name}' not found"},
        )
    return {"ok": True, "name": name}


# -- Deep validation ----------------------------------------------------------

def _get_crossover_frequencies(profile: dict) -> list[float]:
    """Extract sorted crossover frequencies from a profile."""
    xover = profile.get("crossover", {})
    if isinstance(xover, list):
        return [x["frequency_hz"] for x in xover]
    if isinstance(xover, dict) and "frequency_hz" in xover:
        freq = xover["frequency_hz"]
        if isinstance(freq, list):
            return sorted(freq)
        return [freq]
    return []


def _deep_validate_profile(profile: dict) -> dict:
    """Run deep validation checks on a profile with resolved identities.

    Returns {valid: bool, errors: [...], warnings: [...]}.
    Each error/warning is {check: str, message: str}.
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    speakers = profile.get("speakers", {})

    # 1. Duplicate channel detection
    channel_map: dict[int, list[str]] = {}
    for spk_name, spk in speakers.items():
        ch = spk.get("channel")
        if isinstance(ch, int):
            channel_map.setdefault(ch, []).append(spk_name)
    for ch, names in sorted(channel_map.items()):
        if len(names) > 1:
            errors.append({
                "check": "duplicate_channel",
                "message": f"Channel {ch} assigned to multiple speakers: {', '.join(names)}",
            })

    # 2. Channel budget
    all_channels = set(channel_map.keys())
    monitoring = profile.get("monitoring", {})
    if isinstance(monitoring, dict):
        for ch in monitoring.values():
            if isinstance(ch, int):
                all_channels.add(ch)
    if len(all_channels) > 8:
        errors.append({
            "check": "channel_budget",
            "message": f"Total channels ({len(all_channels)}) exceeds maximum of 8",
        })

    # 3. Identity resolution
    identities: dict[str, dict] = {}
    missing_ids: list[str] = []
    for spk_name, spk in speakers.items():
        id_name = spk.get("identity", "")
        if id_name and id_name not in identities:
            id_data = _read_yaml("identities", id_name)
            if id_data is not None:
                identities[id_name] = id_data
            else:
                missing_ids.append(id_name)
                errors.append({
                    "check": "identity_missing",
                    "message": f"Speaker '{spk_name}' references identity '{id_name}' which does not exist",
                })

    # 4. Crossover frequency ordering (multi-way)
    freqs = _get_crossover_frequencies(profile)
    if len(freqs) > 1:
        for i in range(1, len(freqs)):
            if freqs[i] <= freqs[i - 1]:
                errors.append({
                    "check": "crossover_order",
                    "message": (f"Crossover frequencies must be monotonically increasing: "
                                f"{freqs[i - 1]}Hz >= {freqs[i]}Hz at index {i}"),
                })

    # 5. D-031: mandatory HPF for every speaker
    for spk_name, spk in speakers.items():
        id_name = spk.get("identity", "")
        identity = identities.get(id_name, {})
        if identity and identity.get("mandatory_hpf_hz") is None:
            errors.append({
                "check": "d031_hpf_missing",
                "message": (f"Speaker '{spk_name}' ({id_name}): "
                            f"mandatory_hpf_hz not declared (D-031 violation)"),
            })

    # 6. Sub HPF vs crossover consistency
    lowest_xover = freqs[0] if freqs else None
    if lowest_xover is not None:
        for spk_name, spk in speakers.items():
            if spk.get("filter_type") == "lowpass" or spk.get("role") == "subwoofer":
                id_name = spk.get("identity", "")
                identity = identities.get(id_name, {})
                hpf = identity.get("mandatory_hpf_hz")
                if isinstance(hpf, (int, float)) and hpf >= lowest_xover:
                    errors.append({
                        "check": "sub_hpf_vs_crossover",
                        "message": (f"Speaker '{spk_name}': mandatory HPF ({hpf}Hz) "
                                    f">= crossover ({lowest_xover}Hz) — sub has no passband"),
                    })

    # 7. Sensitivity mismatch warning
    sensitivities: dict[str, float] = {}
    for spk_name, spk in speakers.items():
        id_name = spk.get("identity", "")
        identity = identities.get(id_name, {})
        sens = identity.get("sensitivity_db_spl")
        if isinstance(sens, (int, float)):
            sensitivities[spk_name] = sens
    if len(sensitivities) >= 2:
        max_sens = max(sensitivities.values())
        min_sens = min(sensitivities.values())
        diff = max_sens - min_sens
        if diff > 10:
            max_spk = [n for n, s in sensitivities.items() if s == max_sens][0]
            min_spk = [n for n, s in sensitivities.items() if s == min_sens][0]
            warnings.append({
                "check": "sensitivity_mismatch",
                "message": (f"Sensitivity difference {diff:.1f}dB between "
                            f"'{max_spk}' ({max_sens}dB) and '{min_spk}' ({min_sens}dB) "
                            f"exceeds 10dB — gain calibration recommended"),
            })

    # 8. Topology/speaker count consistency
    topology = profile.get("topology", "")
    expected = _TOPOLOGY_SPEAKER_COUNTS.get(topology)
    actual = len(speakers)
    if expected is not None and actual != expected:
        warnings.append({
            "check": "topology_count",
            "message": (f"Topology '{topology}' typically has {expected} speakers "
                        f"(stereo), but profile has {actual}"),
        })

    # 9. D-029 gain staging
    gain_staging = profile.get("gain_staging", {})
    if isinstance(gain_staging, dict):
        for spk_name, spk in speakers.items():
            id_name = spk.get("identity", "")
            identity = identities.get(id_name, {})
            max_boost = identity.get("max_boost_db", 0)
            if not isinstance(max_boost, (int, float)):
                continue
            role = spk.get("role", "")
            if role in ("satellite", "midrange", "tweeter", "fullrange"):
                gs_group = gain_staging.get("satellite", {})
            elif role == "subwoofer":
                gs_group = gain_staging.get("subwoofer", {})
            else:
                continue
            if not isinstance(gs_group, dict):
                continue
            headroom = gs_group.get("headroom_db", 0)
            if isinstance(headroom, (int, float)) and abs(headroom) < max_boost + _D029_MARGIN_DB:
                warnings.append({
                    "check": "d029_gain_staging",
                    "message": (f"Speaker '{spk_name}' ({id_name}): "
                                f"|headroom| ({abs(headroom):.1f}dB) < "
                                f"max_boost ({max_boost}dB) + margin ({_D029_MARGIN_DB}dB)"),
                })

    # 10. Horn crossover proximity warning
    import math
    for spk_name, spk in speakers.items():
        id_name = spk.get("identity", "")
        identity = identities.get(id_name, {})
        horn_cutoff = identity.get("horn_cutoff_freq_hz")
        if not isinstance(horn_cutoff, (int, float)):
            continue
        # Check if any crossover frequency is within 0.5 octaves of horn cutoff
        for freq in freqs:
            octave_distance = abs(math.log2(freq / horn_cutoff))
            if octave_distance < 0.5:
                warnings.append({
                    "check": "horn_crossover_proximity",
                    "message": (
                        f"Speaker '{spk_name}' ({id_name}): crossover {freq}Hz is "
                        f"{octave_distance:.2f} octaves from horn cutoff {horn_cutoff}Hz "
                        f"(< 0.5 oct). Horn unloads below cutoff — excursion risk."
                    ),
                    "horn_cutoff_freq_hz": horn_cutoff,
                    "horn_path_length_m": identity.get("horn_path_length_m"),
                })

    # 11. D-054 channel budget analysis — monitoring availability per topology
    speaker_channels = set(channel_map.keys())
    n_speaker_ch = len(speaker_channels)
    monitoring_channels: set[int] = set()
    if isinstance(monitoring, dict):
        for ch in monitoring.values():
            if isinstance(ch, int):
                monitoring_channels.add(ch)
    n_monitoring_ch = len(monitoring_channels - speaker_channels)
    available_for_monitoring = 8 - n_speaker_ch

    # Determine available modes based on monitoring capacity
    has_hp = n_monitoring_ch >= 2
    has_iem = n_monitoring_ch >= 4

    available_modes: list[str] = []
    if has_hp:
        available_modes.append("dj")
    if has_iem:
        available_modes.append("live")
    if not has_hp:
        available_modes.append("testing")

    if n_speaker_ch >= 8 and n_monitoring_ch == 0:
        warnings.append({
            "check": "channel_budget_no_monitoring",
            "message": (f"All 8 channels used for speakers — no monitoring "
                        f"(headphones/IEM). Testing and evaluation only (D-054)."),
            "speaker_channels": n_speaker_ch,
            "monitoring_channels": n_monitoring_ch,
            "available_for_monitoring": available_for_monitoring,
            "available_modes": available_modes,
        })
    elif n_speaker_ch >= 6 and not has_iem:
        warnings.append({
            "check": "channel_budget_no_iem",
            "message": (f"{n_speaker_ch} speaker channels, {n_monitoring_ch} monitoring — "
                        f"no IEM channels available. Live vocal mode blocked (D-054)."),
            "speaker_channels": n_speaker_ch,
            "monitoring_channels": n_monitoring_ch,
            "available_for_monitoring": available_for_monitoring,
            "available_modes": available_modes,
        })

    # 12. Mode constraint enforcement — cross-reference declared modes vs budget
    declared_modes = profile.get("mode_constraints")
    if isinstance(declared_modes, list) and declared_modes:
        for mode in declared_modes:
            if mode == "live" and "live" not in available_modes:
                errors.append({
                    "check": "mode_constraint_impossible",
                    "message": (f"Profile declares 'live' mode but channel budget has no "
                                f"IEM channels ({n_monitoring_ch} monitoring). "
                                f"Live vocal mode requires 4 monitoring channels (HP + IEM)."),
                })
            elif mode == "dj" and "dj" not in available_modes:
                errors.append({
                    "check": "mode_constraint_impossible",
                    "message": (f"Profile declares 'dj' mode but channel budget has no "
                                f"headphone channels ({n_monitoring_ch} monitoring). "
                                f"DJ mode requires 2 monitoring channels (HP)."),
                })
    elif not isinstance(declared_modes, list) or not declared_modes:
        # Auto-derive: warn about mode limitations when no explicit constraints
        if "live" not in available_modes and "dj" in available_modes:
            warnings.append({
                "check": "mode_auto_derived",
                "message": (f"No mode_constraints declared. Channel budget limits this "
                            f"profile to DJ/PA mode only (no IEM for live vocal)."),
                "available_modes": available_modes,
            })
        elif "dj" not in available_modes and "live" not in available_modes:
            warnings.append({
                "check": "mode_auto_derived",
                "message": (f"No mode_constraints declared. Channel budget limits this "
                            f"profile to testing/evaluation only (no monitoring)."),
                "available_modes": available_modes,
            })

    valid = len(errors) == 0
    result = {"valid": valid, "errors": errors, "warnings": warnings}
    result["channel_budget"] = {
        "speaker_channels": n_speaker_ch,
        "monitoring_channels": n_monitoring_ch,
        "available_for_monitoring": available_for_monitoring,
        "available_modes": available_modes,
    }
    return result


@router.post("/profiles/{name}/validate")
async def validate_profile_endpoint(name: str):
    """Deep-validate a speaker profile against its referenced identities."""
    data = _read_yaml("profiles", name)
    if data is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Speaker profile '{name}' not found"},
        )
    result = _deep_validate_profile(data)
    return result


@router.post("/profiles/{name}/check-mode/{mode}")
async def check_mode_compatibility(name: str, mode: str):
    """Pre-flight check: can this profile support the requested GM mode?

    Returns {compatible: bool, reason: str, available_modes: [...],
             channel_budget: {...}}.
    """
    if mode not in _VALID_GM_MODES:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_mode",
                     "detail": f"Mode must be one of: {', '.join(sorted(_VALID_GM_MODES))}"},
        )
    data = _read_yaml("profiles", name)
    if data is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Speaker profile '{name}' not found"},
        )
    result = _deep_validate_profile(data)
    budget = result.get("channel_budget", {})
    available = budget.get("available_modes", [])

    # Check explicit mode_constraints first
    declared = data.get("mode_constraints")
    if isinstance(declared, list) and declared:
        if mode not in declared:
            return {
                "compatible": False,
                "reason": (f"Profile explicitly excludes '{mode}' mode. "
                           f"Declared modes: {', '.join(declared)}."),
                "available_modes": available,
                "declared_modes": declared,
                "channel_budget": budget,
            }

    # Check channel budget supports the mode
    if mode == "live" and "live" not in available:
        return {
            "compatible": False,
            "reason": (f"Live vocal mode requires IEM channels (4 monitoring). "
                       f"This profile has {budget.get('monitoring_channels', 0)} "
                       f"monitoring channels."),
            "available_modes": available,
            "channel_budget": budget,
        }
    if mode == "dj" and "dj" not in available:
        return {
            "compatible": False,
            "reason": (f"DJ mode requires headphone channels (2 monitoring). "
                       f"This profile has {budget.get('monitoring_channels', 0)} "
                       f"monitoring channels."),
            "available_modes": available,
            "channel_budget": budget,
        }

    return {
        "compatible": True,
        "reason": f"Profile supports '{mode}' mode.",
        "available_modes": available,
        "channel_budget": budget,
    }


# -- Activate endpoint --------------------------------------------------------

# Active profile marker path (local state, not PW config).
_ACTIVE_PROFILE_DIR = pathlib.Path(
    os.environ.get("PI4AUDIO_STATE_DIR",
                   pathlib.Path.home() / ".config" / "pi4audio")
)

# PW filter-chain config deploy path.
_PW_CONF_DIR = pathlib.Path(
    os.environ.get("PI4AUDIO_PW_CONF_DIR",
                   pathlib.Path.home() / ".config" / "pipewire" / "pipewire.conf.d")
)
_PW_CONF_FILENAME = "30-filter-chain-convolver.conf"


def _compute_target_gains(profile: dict) -> dict[str, float]:
    """Compute target linear gain values from a profile's gain_staging.

    Returns a dict mapping gain node names (e.g. 'gain_left_hp') to
    linear Mult values. Used to communicate ramp-up targets to the frontend.
    """
    import math
    speakers = profile.get("speakers", {})
    gain_staging = profile.get("gain_staging", {})
    result = {}
    for spk_key, spk_cfg in speakers.items():
        role = spk_cfg.get("role", "")
        if role in ("satellite", "midrange", "tweeter", "fullrange"):
            gs_group = gain_staging.get("satellite", {})
        elif role == "subwoofer":
            gs_group = gain_staging.get("subwoofer", {})
        else:
            gs_group = {}
        db = gs_group.get("power_limit_db", -60.0)
        if not isinstance(db, (int, float)):
            db = -60.0
        linear = 10.0 ** (db / 20.0) if db > -120 else 0.0
        # Map spk_key to gain node name using canonical mapping
        from room_correction.pw_config_generator import channel_suffix
        suffix = channel_suffix(spk_key)
        result[f"gain_{suffix}"] = round(linear, 6)
    return result


def _configure_thermal_protection(
    profile_name: str,
    profile: dict,
    target_gains: dict,
    thermal_monitor,
    thermal_limiter,
) -> None:
    """Configure thermal monitor + limiter for the activated profile.

    Reads speaker identities to get pe_max_watts, impedance, and sensitivity,
    then passes per-channel thermal state to the monitor and limiter.

    This is best-effort: if thermal_ceiling is not importable or data is
    missing, protection runs in degraded mode (no ceilings).
    """
    if thermal_monitor is None:
        return

    try:
        import sys
        from pathlib import Path
        rc_root = Path(__file__).resolve().parents[2] / "room-correction"
        if str(rc_root) not in sys.path:
            sys.path.insert(0, str(rc_root))
        from thermal_ceiling import load_channel_ceilings
    except ImportError:
        log.warning("thermal_ceiling not importable — thermal protection "
                    "running without ceiling data")
        return

    # Build pw_gain_mults from target_gains: {spk_name: Mult}.
    # target_gains maps gain node names (gain_left_hp) -> Mult values.
    # load_channel_ceilings expects speaker names (sat_left) -> Mult values.
    # Use canonical reverse-lookup from pw_config_generator.
    from room_correction.pw_config_generator import spk_key_from_suffix
    pw_gain_mults = {}
    for gain_name, mult in target_gains.items():
        # gain_name is like "gain_left_hp" -> suffix is "left_hp"
        suffix = gain_name.removeprefix("gain_")
        spk_name = spk_key_from_suffix(suffix)
        if spk_name != suffix:
            pw_gain_mults[spk_name] = mult
        else:
            # For N-way topologies, try the speaker name from the profile
            # directly if the known mapping doesn't cover it.
            speakers = profile.get("speakers", {})
            for sname in speakers:
                if suffix.startswith(sname.replace("_", "_")):
                    pw_gain_mults[sname] = mult
                    break

    try:
        base = _speakers_dir()
        project_root = str(base.parents[1]) if base else None
        ceilings = load_channel_ceilings(
            profile_name,
            pw_gain_mults=pw_gain_mults if pw_gain_mults else None,
            project_root=project_root,
        )
    except Exception as exc:
        log.warning("Failed to compute thermal ceilings for '%s': %s",
                    profile_name, exc)
        return

    if not ceilings:
        log.info("No thermal ceilings computed for '%s'", profile_name)
        return

    # Configure thermal monitor from ceilings dict.
    thermal_monitor.configure_from_ceilings(ceilings)
    log.info("Thermal monitor configured: %d channels from profile '%s'",
             len(ceilings), profile_name)

    # Configure thermal limiter with channel mappings.
    if thermal_limiter is not None:
        limiter_configs = []
        speakers = profile.get("speakers", {})
        for spk_name, info in ceilings.items():
            spk_cfg = speakers.get(spk_name, {})
            # Determine gain node name for this speaker.
            # The gain node name follows the pattern gain_{suffix} where
            # suffix is derived from the speaker key via channel_suffix.
            from room_correction.pw_config_generator import channel_suffix
            suffix = channel_suffix(spk_name)
            gain_node_name = f"gain_{suffix}"

            limiter_configs.append({
                "name": spk_name,
                "channel_index": info["channel"],
                "gain_node_name": gain_node_name,
                "base_mult": info.get("pw_gain_mult", 1.0),
            })

        thermal_limiter.configure_channels(limiter_configs)
        log.info("Thermal limiter configured: %d channels from profile '%s'",
                 len(limiter_configs), profile_name)


async def _activate_profile_impl(
    name: str,
    profile: dict,
    mute_manager,
    is_mock: bool,
    thermal_monitor=None,
    thermal_limiter=None,
) -> dict:
    """Core activation logic. Returns a result dict.

    Steps:
    1. Validate profile — reject if errors
    2. Mute all channels (skip in mock mode)
    3. Generate PW filter-chain config
    4. Write config file
    5. Write active-profile marker
    6. Return target gains for frontend ramp-up (no auto-unmute)
    """
    # 1. Validate
    validation = _deep_validate_profile(profile)
    if not validation["valid"]:
        return {
            "activated": False,
            "error": "validation_failed",
            "validation": validation,
        }

    # 2. Mute (D-043 safety: mute before any config change)
    if not is_mock and mute_manager is not None:
        mute_result = await mute_manager.mute()
        if not mute_result.get("ok"):
            return {
                "activated": False,
                "error": "mute_failed",
                "detail": mute_result.get("error", "unknown mute error"),
            }

    # 3. Generate PW filter-chain config
    try:
        base = _speakers_dir()
        profiles_dir = str(base / "profiles") if base else None
        identities_dir = str(base / "identities") if base else None

        from room_correction.pw_config_generator import generate_filter_chain_conf

        # Extract per-channel delay_ms from profile speakers section.
        speakers = profile.get("speakers", {})
        delays_ms = {}
        for spk_name, spk_cfg in speakers.items():
            d = spk_cfg.get("delay_ms", 0.0)
            if isinstance(d, (int, float)) and d > 0:
                delays_ms[spk_name] = float(d)

        pw_conf = generate_filter_chain_conf(
            name,
            delays_ms=delays_ms if delays_ms else None,
            profiles_dir=profiles_dir,
            identities_dir=identities_dir,
            validate=False,  # Already validated above
        )
    except Exception as exc:
        log.error("PW config generation failed: %s", exc)
        return {
            "activated": False,
            "error": "config_generation_failed",
            "detail": str(exc),
        }

    # 4. Write PW config file
    try:
        conf_dir = _PW_CONF_DIR
        conf_dir.mkdir(parents=True, exist_ok=True)
        conf_path = conf_dir / _PW_CONF_FILENAME
        conf_path.write_text(pw_conf)
    except Exception as exc:
        log.error("Failed to write PW config: %s", exc)
        return {
            "activated": False,
            "error": "config_write_failed",
            "detail": str(exc),
        }

    # 5. Write active-profile marker
    try:
        state_dir = _ACTIVE_PROFILE_DIR
        state_dir.mkdir(parents=True, exist_ok=True)
        marker = state_dir / "active-profile.yml"
        marker.write_text(yaml.dump(
            {"profile": name, "display_name": profile.get("name", name)},
            default_flow_style=False,
        ))
    except Exception as exc:
        log.warning("Failed to write active-profile marker: %s", exc)
        # Non-fatal — config was already deployed

    # 6. Compute target gains for ramp-up
    target_gains = _compute_target_gains(profile)

    # 7. Configure thermal monitor + limiter (US-092 protection chain).
    _configure_thermal_protection(
        name, profile, target_gains, thermal_monitor, thermal_limiter)

    log.info("Profile '%s' activated (safety_flow=%s)",
             name, "muted" if not is_mock else "skipped")

    return {
        "activated": True,
        "profile": name,
        "display_name": profile.get("name", name),
        "config_path": str(conf_path),
        "safety_flow": "muted" if not is_mock else "skipped",
        "target_gains": target_gains,
        "warnings": validation.get("warnings", []),
        "instructions": (
            "All channels are muted. Use the ramp-up endpoint or "
            "manually set gain values to restore output."
            if not is_mock else
            "Mock mode — no PW reload needed. Config file written."
        ),
    }


@router.post("/profiles/{name}/activate")
async def activate_profile(name: str, request: Request):
    """Activate a speaker profile with D-043 safety flow.

    Sequence: validate -> mute -> generate config -> write -> return target gains.
    Does NOT auto-unmute — ramp-up is a separate explicit action.
    """
    data = _read_yaml("profiles", name)
    if data is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Speaker profile '{name}' not found"},
        )
    mute_manager = getattr(request.app.state, "audio_mute", None)
    thermal_monitor = getattr(request.app.state, "thermal_monitor", None)
    thermal_limiter = getattr(request.app.state, "thermal_limiter", None)
    is_mock = os.environ.get("PI_AUDIO_MOCK", "1") == "1"

    result = await _activate_profile_impl(
        name, data, mute_manager, is_mock,
        thermal_monitor=thermal_monitor,
        thermal_limiter=thermal_limiter,
    )

    if not result.get("activated"):
        status = 422 if result.get("error") == "validation_failed" else 500
        return JSONResponse(status_code=status, content=result)

    return result


# -- Helpers ------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert a display name to a filename-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed"
