"""
Speaker driver database validator.

Loads all driver YAML files from configs/drivers/*/driver.yml, validates
required fields, types, enum values, T/S parameter cross-checks, and
measurement data file references.

Uses only stdlib + PyYAML (already in project dependencies).

Exit code 0 if all valid, 1 if any errors.
"""

import re
import sys
from pathlib import Path

import yaml


# ----- Constants -----------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent.parent
DRIVERS_DIR = PROJECT_ROOT / "configs" / "drivers"

REQUIRED_TS_FIELDS = ("fs_hz", "re_ohm", "z_nom_ohm", "qts")

VALID_DRIVER_TYPES = {
    "woofer", "midrange", "tweeter", "full-range",
    "subwoofer", "coaxial",
}

VALID_MAGNET_TYPES = {"ferrite", "neodymium", "alnico"}

VALID_CONE_MATERIALS = {
    "paper", "polypropylene", "aluminum", "kevlar", "carbon-fiber",
}

VALID_SURROUND_MATERIALS = {"rubber", "foam", "cloth"}

VALID_CONDITIONS = {"new", "good", "fair", "needs-repair", "retired"}

VALID_TS_SOURCES = {
    "manufacturer", "measured-added-mass", "measured-impedance-jig",
}

VALID_MEASUREMENT_SOURCES = {"measured", "datasheet", "manufacturer-file"}

VALID_CONFIDENCES = {"high", "medium", "low", "estimated"}

# Numeric fields in thiele_small that must be numbers if present
TS_NUMERIC_FIELDS = (
    "fs_hz", "re_ohm", "z_nom_ohm", "qts", "qes", "qms",
    "vas_liters", "cms_m_per_n", "xmax_mm", "xmech_mm", "le_mh",
    "bl_tm", "mms_g", "mmd_g", "sd_cm2", "sensitivity_db_1w1m",
    "sensitivity_db_2v83_1m", "pe_max_watts", "pe_peak_watts",
    "eta0_percent", "vd_cm3",
)

# Numeric fields in metadata
METADATA_NUMERIC_FIELDS = (
    "nominal_diameter_in", "actual_diameter_mm", "voice_coil_diameter_mm",
    "weight_kg",
)

MOUNTING_NUMERIC_FIELDS = (
    "cutout_diameter_mm", "bolt_circle_diameter_mm", "bolt_count",
    "overall_depth_mm", "flange_diameter_mm",
)

# ISO 8601 date pattern (YYYY-MM-DD)
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# T/S cross-check tolerances
QTS_TOLERANCE = 0.05   # 5%
VD_TOLERANCE = 0.10    # 10%


# ----- Validation ----------------------------------------------------------

def _is_numeric(value):
    """Check if a value is a number (int or float), excluding bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_numeric_field(data, field, section_label, errors):
    """Validate a field is numeric if non-null."""
    value = data.get(field)
    if value is not None and not _is_numeric(value):
        errors.append(
            f"{section_label}.{field}: expected number, got "
            f"{type(value).__name__} ({value!r})"
        )


def _check_enum_field(data, field, valid_values, section_label, errors):
    """Validate a field matches an allowed enum value if non-null."""
    value = data.get(field)
    if value is not None and value not in valid_values:
        errors.append(
            f"{section_label}.{field}: invalid value {value!r}, "
            f"must be one of: {sorted(valid_values)}"
        )


def _check_date_field(data, field, section_label, errors):
    """Validate a field is ISO 8601 date (YYYY-MM-DD) if non-null."""
    value = data.get(field)
    if value is not None:
        date_str = str(value)
        if not ISO_DATE_PATTERN.match(date_str):
            errors.append(
                f"{section_label}.{field}: invalid ISO 8601 date {value!r}, "
                f"expected YYYY-MM-DD"
            )


def validate_driver(driver_data, driver_dir):
    """
    Validate a single driver YAML file.

    Parameters
    ----------
    driver_data : dict
        Parsed YAML data from driver.yml.
    driver_dir : Path
        Directory containing the driver.yml file (for resolving data file paths).

    Returns
    -------
    list of str
        Validation errors (empty if valid).
    """
    errors = []

    if not isinstance(driver_data, dict):
        errors.append("Driver file must be a YAML mapping (dict)")
        return errors

    # Schema version
    sv = driver_data.get("schema_version")
    if sv != 1:
        errors.append(
            f"schema_version: expected 1, got {sv!r}"
        )

    # --- metadata section ---
    metadata = driver_data.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata: section missing or not a mapping")
        metadata = {}

    if not metadata.get("id"):
        errors.append("metadata.id: REQUIRED field is empty or missing")

    _check_enum_field(
        metadata, "driver_type", VALID_DRIVER_TYPES, "metadata", errors
    )
    _check_enum_field(
        metadata, "magnet_type", VALID_MAGNET_TYPES, "metadata", errors
    )
    _check_enum_field(
        metadata, "cone_material", VALID_CONE_MATERIALS, "metadata", errors
    )
    _check_enum_field(
        metadata, "surround_material", VALID_SURROUND_MATERIALS, "metadata",
        errors
    )
    _check_enum_field(
        metadata, "condition", VALID_CONDITIONS, "metadata", errors
    )
    _check_enum_field(
        metadata, "ts_parameter_source", VALID_TS_SOURCES, "metadata", errors
    )

    for field in METADATA_NUMERIC_FIELDS:
        _check_numeric_field(metadata, field, "metadata", errors)

    # Mounting sub-section
    mounting = metadata.get("mounting")
    if isinstance(mounting, dict):
        for field in MOUNTING_NUMERIC_FIELDS:
            _check_numeric_field(mounting, field, "metadata.mounting", errors)

    # Date fields
    _check_date_field(metadata, "ts_measurement_date", "metadata", errors)
    _check_date_field(metadata, "purchase_date", "metadata", errors)

    # --- thiele_small section ---
    ts = driver_data.get("thiele_small")
    if not isinstance(ts, dict):
        errors.append("thiele_small: section missing or not a mapping")
        ts = {}

    # Required T/S fields must be non-null
    for field in REQUIRED_TS_FIELDS:
        value = ts.get(field)
        if value is None:
            errors.append(
                f"thiele_small.{field}: REQUIRED field is null or missing"
            )

    # Numeric type checks for all T/S fields
    for field in TS_NUMERIC_FIELDS:
        _check_numeric_field(ts, field, "thiele_small", errors)

    # T/S cross-checks
    _cross_check_qts(ts, errors)
    _cross_check_vd(ts, errors)

    # --- measurements section ---
    measurements = driver_data.get("measurements")
    if isinstance(measurements, dict):
        _validate_measurements(measurements, driver_dir, errors)

    # --- application_notes section ---
    app_notes = driver_data.get("application_notes")
    if app_notes is not None:
        if not isinstance(app_notes, list):
            errors.append("application_notes: expected list, got "
                          f"{type(app_notes).__name__}")
        else:
            for i, note in enumerate(app_notes):
                if isinstance(note, dict):
                    _check_enum_field(
                        note, "confidence", VALID_CONFIDENCES,
                        f"application_notes[{i}]", errors
                    )

    return errors


def _cross_check_qts(ts, errors):
    """
    Cross-check: Qts = (Qes * Qms) / (Qes + Qms), within 5% tolerance.

    Only checked if all three values are provided and numeric.
    """
    qts = ts.get("qts")
    qes = ts.get("qes")
    qms = ts.get("qms")

    if qts is None or qes is None or qms is None:
        return
    if not (_is_numeric(qts) and _is_numeric(qes) and _is_numeric(qms)):
        return
    if qes + qms == 0:
        return

    expected_qts = (qes * qms) / (qes + qms)
    if expected_qts == 0:
        return

    deviation = abs(qts - expected_qts) / expected_qts
    if deviation > QTS_TOLERANCE:
        errors.append(
            f"thiele_small: Qts cross-check FAILED. "
            f"Qts={qts}, but (Qes*Qms)/(Qes+Qms) = "
            f"({qes}*{qms})/({qes}+{qms}) = {expected_qts:.4f}. "
            f"Deviation: {deviation:.1%} (tolerance: {QTS_TOLERANCE:.0%})"
        )


def _cross_check_vd(ts, errors):
    """
    Cross-check: Vd = Sd * Xmax (converted to same units), within 10% tolerance.

    Vd in cm^3, Sd in cm^2, Xmax in mm.
    Vd = Sd * (Xmax / 10)  [mm -> cm]
    """
    vd = ts.get("vd_cm3")
    sd = ts.get("sd_cm2")
    xmax = ts.get("xmax_mm")

    if vd is None or sd is None or xmax is None:
        return
    if not (_is_numeric(vd) and _is_numeric(sd) and _is_numeric(xmax)):
        return

    expected_vd = sd * (xmax / 10.0)
    if expected_vd == 0:
        return

    deviation = abs(vd - expected_vd) / expected_vd
    if deviation > VD_TOLERANCE:
        errors.append(
            f"thiele_small: Vd cross-check FAILED. "
            f"Vd={vd} cm^3, but Sd*Xmax = "
            f"{sd}*{xmax}/10 = {expected_vd:.2f} cm^3. "
            f"Deviation: {deviation:.1%} (tolerance: {VD_TOLERANCE:.0%})"
        )


def _validate_measurements(measurements, driver_dir, errors):
    """Validate measurement entries and data file references."""
    data_dir = driver_dir / "data"

    for section_name in ("impedance_curve", "frequency_response",
                         "nearfield_response", "distortion"):
        section = measurements.get(section_name)
        if not isinstance(section, dict):
            continue

        # Validate measurement source enum
        if section_name in ("impedance_curve", "frequency_response"):
            _check_enum_field(
                section, "source", VALID_MEASUREMENT_SOURCES,
                f"measurements.{section_name}", errors
            )

        # Validate date fields
        _check_date_field(
            section, "date", f"measurements.{section_name}", errors
        )

        # Validate data file reference exists
        data_file = section.get("data_file")
        if data_file is not None:
            file_path = data_dir / data_file
            if not file_path.exists():
                errors.append(
                    f"measurements.{section_name}.data_file: "
                    f"referenced file {data_file!r} not found at {file_path}"
                )


# ----- Discovery and main -------------------------------------------------

def find_drivers(drivers_dir=None):
    """
    Find all driver.yml files under the drivers directory.

    Returns
    -------
    list of Path
        Sorted list of driver.yml file paths.
    """
    base = Path(drivers_dir) if drivers_dir else DRIVERS_DIR
    driver_files = sorted(base.glob("*/driver.yml"))
    return driver_files


def validate_all(drivers_dir=None):
    """
    Validate all drivers found under the drivers directory.

    Returns
    -------
    dict
        Mapping of driver ID (directory name) to list of error strings.
        Only drivers with errors are included.
    """
    driver_files = find_drivers(drivers_dir)
    all_errors = {}

    if not driver_files:
        print(f"WARNING: No driver files found in {drivers_dir or DRIVERS_DIR}")
        return all_errors

    for driver_path in driver_files:
        driver_dir = driver_path.parent
        driver_id = driver_dir.name

        try:
            with open(driver_path, "r") as f:
                driver_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            all_errors[driver_id] = [f"YAML parse error: {e}"]
            continue

        errors = validate_driver(driver_data, driver_dir)
        if errors:
            all_errors[driver_id] = errors

    return all_errors


def main(drivers_dir=None):
    """Run validation and print results. Returns exit code."""
    driver_files = find_drivers(drivers_dir)

    if not driver_files:
        print(f"No driver files found in {drivers_dir or DRIVERS_DIR}")
        return 1

    print(f"Validating {len(driver_files)} driver(s)...")

    all_errors = validate_all(drivers_dir)

    valid_count = len(driver_files) - len(all_errors)
    for driver_path in driver_files:
        driver_id = driver_path.parent.name
        if driver_id in all_errors:
            print(f"\n  FAIL: {driver_id}")
            for err in all_errors[driver_id]:
                print(f"    - {err}")
        else:
            print(f"  OK: {driver_id}")

    print(f"\n{valid_count}/{len(driver_files)} drivers valid.")

    if all_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
