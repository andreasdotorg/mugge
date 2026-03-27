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
from fastapi import APIRouter
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

# Allowed filename characters (prevent path traversal).
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _speakers_dir() -> pathlib.Path | None:
    """Return the speakers config directory, checking Pi path then repo."""
    if _PI_SPEAKERS_DIR.is_dir():
        return _PI_SPEAKERS_DIR
    if _REPO_SPEAKERS_DIR.is_dir():
        return _REPO_SPEAKERS_DIR
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
_IDENTITY_REQUIRED = {"name", "type", "impedance_ohm", "max_boost_db", "mandatory_hpf_hz"}

# Required fields for speaker profiles.
_PROFILE_REQUIRED = {"name", "topology", "crossover", "speakers"}

# Required fields within a profile's crossover section.
_CROSSOVER_REQUIRED = {"frequency_hz", "slope_db_per_oct", "type"}

# Valid identity enclosure types.
_VALID_TYPES = {"sealed", "ported", "open-baffle", "horn", "bandpass", "transmission-line"}

# Valid speaker roles.
_VALID_ROLES = {"satellite", "subwoofer", "fullrange"}

# Valid filter types.
_VALID_FILTER_TYPES = {"highpass", "lowpass", "fullrange"}

# Valid polarities.
_VALID_POLARITIES = {"normal", "inverted"}


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
    if not isinstance(data["max_boost_db"], (int, float)):
        return "'max_boost_db' must be a number"
    if not isinstance(data["mandatory_hpf_hz"], (int, float)):
        return "'mandatory_hpf_hz' must be a number"
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
    # Validate crossover section.
    xover = data["crossover"]
    if not isinstance(xover, dict):
        return "'crossover' must be an object"
    xover_missing = _CROSSOVER_REQUIRED - xover.keys()
    if xover_missing:
        return f"crossover missing fields: {', '.join(sorted(xover_missing))}"
    if not isinstance(xover["frequency_hz"], (int, float)):
        return "'crossover.frequency_hz' must be a number"
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


# -- Helpers ------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert a display name to a filename-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed"
