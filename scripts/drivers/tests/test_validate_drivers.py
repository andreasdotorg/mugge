"""
Tests for the driver database validator.

Covers:
- Valid driver passes validation
- Missing required fields (fs_hz, re_ohm, z_nom_ohm, qts) are rejected
- Invalid enum values are rejected
- T/S cross-check (Qts) detects inconsistency
- T/S cross-check (Vd) detects inconsistency
- Missing data file references are flagged
"""

import copy
import os
import textwrap
from pathlib import Path

import pytest
import yaml

# Import the module under test
import sys

_THIS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _THIS_DIR.parent.parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from drivers.validate_drivers import validate_driver


# ----- Fixtures ------------------------------------------------------------

def _minimal_valid_driver():
    """Return a minimal valid driver dict that passes all validation."""
    return {
        "schema_version": 1,
        "metadata": {
            "id": "test-driver-1",
            "manufacturer": "TestCo",
            "model": "TD-1",
            "driver_type": "woofer",
            "nominal_diameter_in": 8.0,
            "actual_diameter_mm": None,
            "magnet_type": "ferrite",
            "cone_material": "paper",
            "surround_material": "rubber",
            "voice_coil_diameter_mm": None,
            "weight_kg": None,
            "mounting": {
                "cutout_diameter_mm": None,
                "bolt_circle_diameter_mm": None,
                "bolt_count": None,
                "overall_depth_mm": None,
                "flange_diameter_mm": None,
            },
            "datasheet_url": None,
            "datasheet_file": None,
            "ts_parameter_source": "manufacturer",
            "ts_measurement_date": None,
            "ts_measurement_notes": "",
            "notes": "",
            "quantity_owned": None,
            "serial_numbers": [],
            "purchase_date": None,
            "condition": "new",
        },
        "thiele_small": {
            "fs_hz": 35.0,
            "re_ohm": 6.2,
            "z_nom_ohm": 8,
            "qts": 0.38,
            "qes": None,
            "qms": None,
            "vas_liters": None,
            "cms_m_per_n": None,
            "xmax_mm": None,
            "xmech_mm": None,
            "le_mh": None,
            "bl_tm": None,
            "mms_g": None,
            "mmd_g": None,
            "sd_cm2": None,
            "sensitivity_db_1w1m": None,
            "sensitivity_db_2v83_1m": None,
            "pe_max_watts": None,
            "pe_peak_watts": None,
            "power_handling_note": "",
            "eta0_percent": None,
            "vd_cm3": None,
        },
        "measurements": {
            "impedance_curve": {
                "source": None,
                "date": None,
                "conditions": "",
                "data_file": None,
            },
            "frequency_response": {
                "source": None,
                "date": None,
                "conditions": "",
                "reference_distance_m": None,
                "data_file": None,
            },
            "nearfield_response": {
                "source": None,
                "date": None,
                "data_file": None,
            },
            "distortion": {
                "data_file": None,
                "test_level_db_spl": None,
            },
        },
        "application_notes": [],
    }


@pytest.fixture
def valid_driver():
    return _minimal_valid_driver()


@pytest.fixture
def tmp_driver_dir(tmp_path):
    """Create a temporary driver directory with a data/ subdirectory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return tmp_path


# ----- Tests: Valid driver -------------------------------------------------

class TestValidDriver:
    def test_valid_driver_passes(self, valid_driver, tmp_driver_dir):
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_valid_driver_with_all_optional_ts(self, valid_driver, tmp_driver_dir):
        """A driver with all optional T/S fields populated also passes."""
        valid_driver["thiele_small"].update({
            "qes": 0.45,
            "qms": 3.5,
            "vas_liters": 50.0,
            "xmax_mm": 8.0,
            "le_mh": 1.2,
            "bl_tm": 10.5,
            "mms_g": 45.0,
            "sd_cm2": 220.0,
            "sensitivity_db_1w1m": 87.5,
            "pe_max_watts": 200,
        })
        # Compute correct Qts from Qes and Qms
        qes = valid_driver["thiele_small"]["qes"]
        qms = valid_driver["thiele_small"]["qms"]
        valid_driver["thiele_small"]["qts"] = (qes * qms) / (qes + qms)
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert errors == [], f"Expected no errors, got: {errors}"


# ----- Tests: Missing required fields -------------------------------------

class TestRequiredFields:
    @pytest.mark.parametrize("field", ["fs_hz", "re_ohm", "z_nom_ohm", "qts"])
    def test_missing_required_ts_field(self, valid_driver, tmp_driver_dir, field):
        """Each of the 4 required T/S fields must be non-null."""
        valid_driver["thiele_small"][field] = None
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any(field in e for e in errors), (
            f"Expected error for missing {field}, got: {errors}"
        )

    def test_missing_metadata_id(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["id"] = ""
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("metadata.id" in e for e in errors)

    def test_missing_metadata_id_null(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["id"] = None
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("metadata.id" in e for e in errors)

    def test_wrong_schema_version(self, valid_driver, tmp_driver_dir):
        valid_driver["schema_version"] = 2
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("schema_version" in e for e in errors)


# ----- Tests: Invalid enum values ------------------------------------------

class TestEnumValidation:
    def test_invalid_driver_type(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["driver_type"] = "speaker"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("driver_type" in e and "speaker" in e for e in errors)

    def test_invalid_magnet_type(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["magnet_type"] = "ceramic"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("magnet_type" in e for e in errors)

    def test_invalid_cone_material(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["cone_material"] = "titanium"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("cone_material" in e for e in errors)

    def test_invalid_surround_material(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["surround_material"] = "plastic"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("surround_material" in e for e in errors)

    def test_invalid_condition(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["condition"] = "broken"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("condition" in e for e in errors)

    def test_invalid_ts_parameter_source(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["ts_parameter_source"] = "guessed"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("ts_parameter_source" in e for e in errors)

    def test_invalid_measurement_source(self, valid_driver, tmp_driver_dir):
        valid_driver["measurements"]["impedance_curve"]["source"] = "unknown"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("source" in e for e in errors)

    def test_invalid_confidence(self, valid_driver, tmp_driver_dir):
        valid_driver["application_notes"] = [
            {"note": "test", "source": "me", "confidence": "maybe"}
        ]
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("confidence" in e for e in errors)


# ----- Tests: Type validation ---------------------------------------------

class TestTypeValidation:
    def test_ts_field_string_instead_of_number(self, valid_driver, tmp_driver_dir):
        valid_driver["thiele_small"]["fs_hz"] = "thirty-five"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("fs_hz" in e and "number" in e for e in errors)

    def test_ts_field_bool_rejected(self, valid_driver, tmp_driver_dir):
        valid_driver["thiele_small"]["re_ohm"] = True
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("re_ohm" in e and "number" in e for e in errors)

    def test_metadata_numeric_field_string(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["nominal_diameter_in"] = "eight"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("nominal_diameter_in" in e for e in errors)

    def test_invalid_date_format(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["ts_measurement_date"] = "March 11, 2026"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("ts_measurement_date" in e and "ISO 8601" in e for e in errors)

    def test_valid_date_passes(self, valid_driver, tmp_driver_dir):
        valid_driver["metadata"]["ts_measurement_date"] = "2026-03-11"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        # Should not contain date errors
        date_errors = [e for e in errors if "ts_measurement_date" in e]
        assert date_errors == []


# ----- Tests: T/S cross-checks --------------------------------------------

class TestCrossChecks:
    def test_qts_cross_check_consistent(self, valid_driver, tmp_driver_dir):
        """Consistent Qts/Qes/Qms should not produce errors."""
        valid_driver["thiele_small"]["qes"] = 0.5
        valid_driver["thiele_small"]["qms"] = 3.0
        # Correct Qts = (0.5 * 3.0) / (0.5 + 3.0) = 0.4286
        valid_driver["thiele_small"]["qts"] = 0.4286
        errors = validate_driver(valid_driver, tmp_driver_dir)
        qts_errors = [e for e in errors if "Qts cross-check" in e]
        assert qts_errors == []

    def test_qts_cross_check_detects_inconsistency(self, valid_driver, tmp_driver_dir):
        """Inconsistent Qts should trigger cross-check error."""
        valid_driver["thiele_small"]["qes"] = 0.5
        valid_driver["thiele_small"]["qms"] = 3.0
        # Correct Qts would be ~0.4286, we set it to 0.7 (far off)
        valid_driver["thiele_small"]["qts"] = 0.7
        errors = validate_driver(valid_driver, tmp_driver_dir)
        qts_errors = [e for e in errors if "Qts cross-check" in e]
        assert len(qts_errors) == 1

    def test_qts_cross_check_within_tolerance(self, valid_driver, tmp_driver_dir):
        """Qts within 5% tolerance should pass."""
        valid_driver["thiele_small"]["qes"] = 0.5
        valid_driver["thiele_small"]["qms"] = 3.0
        expected = (0.5 * 3.0) / (0.5 + 3.0)  # 0.4286
        # Set Qts to 4% off (within 5% tolerance)
        valid_driver["thiele_small"]["qts"] = expected * 1.04
        errors = validate_driver(valid_driver, tmp_driver_dir)
        qts_errors = [e for e in errors if "Qts cross-check" in e]
        assert qts_errors == []

    def test_qts_cross_check_skipped_if_partial(self, valid_driver, tmp_driver_dir):
        """Cross-check should be skipped if Qes or Qms is null."""
        valid_driver["thiele_small"]["qes"] = 0.5
        valid_driver["thiele_small"]["qms"] = None
        valid_driver["thiele_small"]["qts"] = 0.7  # Would be wrong if Qms were set
        errors = validate_driver(valid_driver, tmp_driver_dir)
        qts_errors = [e for e in errors if "Qts cross-check" in e]
        assert qts_errors == []

    def test_vd_cross_check_detects_inconsistency(self, valid_driver, tmp_driver_dir):
        """Inconsistent Vd should trigger cross-check error."""
        valid_driver["thiele_small"]["sd_cm2"] = 200.0
        valid_driver["thiele_small"]["xmax_mm"] = 10.0
        # Correct Vd = 200 * (10/10) = 200 cm^3
        valid_driver["thiele_small"]["vd_cm3"] = 300.0  # 50% off
        errors = validate_driver(valid_driver, tmp_driver_dir)
        vd_errors = [e for e in errors if "Vd cross-check" in e]
        assert len(vd_errors) == 1

    def test_vd_cross_check_consistent(self, valid_driver, tmp_driver_dir):
        """Consistent Vd should pass."""
        valid_driver["thiele_small"]["sd_cm2"] = 200.0
        valid_driver["thiele_small"]["xmax_mm"] = 10.0
        valid_driver["thiele_small"]["vd_cm3"] = 200.0
        errors = validate_driver(valid_driver, tmp_driver_dir)
        vd_errors = [e for e in errors if "Vd cross-check" in e]
        assert vd_errors == []


# ----- Tests: Data file references -----------------------------------------

class TestDataFileReferences:
    def test_missing_data_file_flagged(self, valid_driver, tmp_driver_dir):
        """A data_file reference to a non-existent file should be flagged."""
        valid_driver["measurements"]["impedance_curve"]["data_file"] = \
            "impedance.zma"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("impedance.zma" in e and "not found" in e for e in errors)

    def test_existing_data_file_passes(self, valid_driver, tmp_driver_dir):
        """A data_file reference to an existing file should pass."""
        data_dir = tmp_driver_dir / "data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "impedance.zma").write_text("# test data\n")
        valid_driver["measurements"]["impedance_curve"]["data_file"] = \
            "impedance.zma"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        file_errors = [e for e in errors if "impedance.zma" in e]
        assert file_errors == []

    def test_null_data_file_ok(self, valid_driver, tmp_driver_dir):
        """Null data_file should not trigger any file-not-found error."""
        valid_driver["measurements"]["impedance_curve"]["data_file"] = None
        errors = validate_driver(valid_driver, tmp_driver_dir)
        file_errors = [e for e in errors if "not found" in e]
        assert file_errors == []

    def test_nearfield_missing_data_file(self, valid_driver, tmp_driver_dir):
        """Nearfield response missing data file should be flagged."""
        valid_driver["measurements"]["nearfield_response"]["data_file"] = \
            "nearfield.frd"
        errors = validate_driver(valid_driver, tmp_driver_dir)
        assert any("nearfield.frd" in e and "not found" in e for e in errors)
