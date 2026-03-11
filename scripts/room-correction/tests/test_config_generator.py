"""Tests for config_generator module (US-011b)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

# Ensure the parent directory is on the path so we can import config_generator
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config_generator
from config_generator import (
    D029_MARGIN_DB,
    IDENTITIES_DIR,
    MAX_CHANNELS,
    PROFILES_DIR,
    ValidationError,
    generate_config,
    load_identity,
    load_profile,
    load_profile_with_identities,
    validate_hpf_in_config,
    validate_profile,
)


class TestLoadIdentity(unittest.TestCase):
    """Test loading speaker identity YAML files."""

    def test_load_bose_jewel(self):
        identity = load_identity("bose-jewel-double-cube")
        self.assertEqual(identity["name"], "Bose Jewel Double Cube")
        self.assertEqual(identity["impedance_ohm"], 8)
        self.assertEqual(identity["max_boost_db"], 4)
        self.assertEqual(identity["mandatory_hpf_hz"], 155)
        self.assertEqual(identity["max_power_watts"], 20)

    def test_load_bose_ps28(self):
        identity = load_identity("bose-ps28-iii-sub")
        self.assertEqual(identity["name"], "Bose PS28 III Subwoofer")
        self.assertAlmostEqual(identity["impedance_ohm"], 2.33)
        self.assertEqual(identity["max_boost_db"], 10)
        self.assertEqual(identity["mandatory_hpf_hz"], 42)
        self.assertEqual(identity["max_power_watts"], 62)
        # Check compensation EQ
        self.assertEqual(len(identity["compensation_eq"]), 1)
        eq = identity["compensation_eq"][0]
        self.assertEqual(eq["type"], "peak")
        self.assertEqual(eq["frequency_hz"], 65)
        self.assertAlmostEqual(eq["gain_db"], 10.0)
        self.assertAlmostEqual(eq["q"], 1.0)

    def test_load_wideband(self):
        identity = load_identity("wideband-selfbuilt-v1")
        self.assertEqual(identity["name"], "Wideband Self-Built v1")
        self.assertEqual(identity["impedance_ohm"], 8)
        self.assertEqual(identity["max_boost_db"], 0)
        self.assertIsNone(identity["mandatory_hpf_hz"])
        self.assertEqual(identity["compensation_eq"], [])

    def test_load_custom_sub(self):
        identity = load_identity("sub-custom-15")
        self.assertEqual(identity["name"], "Custom 15-inch Subwoofer")
        self.assertEqual(identity["impedance_ohm"], 8)
        self.assertEqual(identity["type"], "sealed")

    def test_load_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_identity("nonexistent-speaker")


class TestLoadProfile(unittest.TestCase):
    """Test loading speaker profile YAML files."""

    def test_load_bose_home(self):
        profile = load_profile("bose-home")
        self.assertEqual(profile["name"], "Bose Home System")
        self.assertEqual(profile["topology"], "2way")
        self.assertEqual(profile["crossover"]["frequency_hz"], 155)
        self.assertEqual(profile["crossover"]["slope_db_per_oct"], 48)

        # Check speaker configuration
        self.assertIn("sat_left", profile["speakers"])
        self.assertIn("sub2", profile["speakers"])
        self.assertEqual(
            profile["speakers"]["sub2"]["polarity"], "inverted"
        )

    def test_load_2way_sealed(self):
        profile = load_profile("2way-80hz-sealed")
        self.assertEqual(profile["crossover"]["frequency_hz"], 80)
        self.assertEqual(
            profile["speakers"]["sat_left"]["identity"],
            "wideband-selfbuilt-v1",
        )

    def test_load_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_profile("nonexistent-profile")

    def test_load_profile_with_identities(self):
        profile, identities = load_profile_with_identities("bose-home")
        self.assertIn("bose-jewel-double-cube", identities)
        self.assertIn("bose-ps28-iii-sub", identities)
        self.assertEqual(
            identities["bose-jewel-double-cube"]["max_boost_db"], 4
        )

    def test_monitoring_channels(self):
        profile = load_profile("bose-home")
        mon = profile["monitoring"]
        self.assertEqual(mon["hp_left"], 4)
        self.assertEqual(mon["hp_right"], 5)
        self.assertEqual(mon["hp2_left"], 6)
        self.assertEqual(mon["hp2_right"], 7)

    def test_gain_staging(self):
        profile = load_profile("bose-home")
        gs = profile["gain_staging"]
        self.assertAlmostEqual(gs["satellite"]["headroom_db"], -7.0)
        self.assertAlmostEqual(gs["satellite"]["power_limit_db"], -13.5)
        self.assertAlmostEqual(gs["subwoofer"]["headroom_db"], -13.0)
        self.assertAlmostEqual(gs["subwoofer"]["power_limit_db"], -8.6)


class TestValidation(unittest.TestCase):
    """Test profile validation logic."""

    def test_bose_home_validates(self):
        """The bose-home profile should pass all validations."""
        profile, identities = load_profile_with_identities("bose-home")
        errors = validate_profile(profile, identities)
        self.assertEqual(errors, [], f"Unexpected errors: {errors}")

    def test_2way_sealed_validates(self):
        """The 2way-80hz-sealed profile should pass all validations."""
        profile, identities = load_profile_with_identities("2way-80hz-sealed")
        errors = validate_profile(profile, identities)
        self.assertEqual(errors, [], f"Unexpected errors: {errors}")

    def test_missing_identity_detected(self):
        """Validation should catch a reference to a nonexistent identity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a profile that references a nonexistent identity
            profiles_dir = Path(tmpdir) / "profiles"
            identities_dir = Path(tmpdir) / "identities"
            profiles_dir.mkdir()
            identities_dir.mkdir()

            bad_profile = {
                "name": "Bad Profile",
                "topology": "2way",
                "crossover": {"frequency_hz": 80, "slope_db_per_oct": 48},
                "speakers": {
                    "sat_left": {
                        "identity": "nonexistent-speaker",
                        "role": "satellite",
                        "channel": 0,
                        "filter_type": "highpass",
                        "polarity": "normal",
                    },
                },
                "monitoring": {"hp_left": 4, "hp_right": 5, "hp2_left": 6, "hp2_right": 7},
                "gain_staging": {"satellite": {"headroom_db": -7.0, "power_limit_db": -13.5}},
            }

            errors = validate_profile(
                bad_profile, {}, identities_dir=identities_dir
            )
            self.assertTrue(
                any("missing" in e.lower() or "not found" in e.lower() for e in errors),
                f"Expected missing identity error, got: {errors}",
            )

    def test_channel_overflow_detected(self):
        """Validation should catch channels exceeding the budget."""
        profile = {
            "name": "Overflow",
            "topology": "2way",
            "crossover": {"frequency_hz": 80},
            "speakers": {
                "sat_left": {
                    "identity": "wideband-selfbuilt-v1",
                    "role": "satellite",
                    "channel": 0,
                },
                "overflow": {
                    "identity": "wideband-selfbuilt-v1",
                    "role": "satellite",
                    "channel": 9,  # exceeds 8-channel budget
                },
            },
            "monitoring": {},
            "gain_staging": {
                "satellite": {"headroom_db": -7.0, "power_limit_db": -24.0},
            },
        }
        identities = {
            "wideband-selfbuilt-v1": load_identity("wideband-selfbuilt-v1"),
        }
        errors = validate_profile(profile, identities)
        self.assertTrue(
            any("channel" in e.lower() and ("exceed" in e.lower() or "maximum" in e.lower()) for e in errors),
            f"Expected channel overflow error, got: {errors}",
        )

    def test_insufficient_headroom_detected(self):
        """Validation should catch D-029 headroom violations."""
        profile = {
            "name": "Bad Headroom",
            "topology": "2way",
            "crossover": {"frequency_hz": 155},
            "speakers": {
                "sat_left": {
                    "identity": "bose-jewel-double-cube",
                    "role": "satellite",
                    "channel": 0,
                    "filter_type": "highpass",
                    "polarity": "normal",
                },
            },
            "monitoring": {"hp_left": 4, "hp_right": 5, "hp2_left": 6, "hp2_right": 7},
            "gain_staging": {
                "satellite": {
                    "headroom_db": -3.0,  # Only 3dB, but need 4 + 0.5 = 4.5dB
                    "power_limit_db": -13.5,
                },
            },
        }
        identities = {
            "bose-jewel-double-cube": load_identity("bose-jewel-double-cube"),
        }
        errors = validate_profile(profile, identities)
        self.assertTrue(
            any("d-029" in e.lower() for e in errors),
            f"Expected D-029 headroom error, got: {errors}",
        )

    def test_sufficient_headroom_passes(self):
        """Headroom exactly at the margin should pass."""
        profile = {
            "name": "Exact Headroom",
            "topology": "2way",
            "crossover": {"frequency_hz": 155},
            "speakers": {
                "sat_left": {
                    "identity": "bose-jewel-double-cube",
                    "role": "satellite",
                    "channel": 0,
                    "filter_type": "highpass",
                    "polarity": "normal",
                },
            },
            "monitoring": {"hp_left": 4, "hp_right": 5, "hp2_left": 6, "hp2_right": 7},
            "gain_staging": {
                "satellite": {
                    "headroom_db": -4.5,  # Exactly 4 + 0.5 = 4.5dB
                    "power_limit_db": -13.5,
                },
            },
        }
        identities = {
            "bose-jewel-double-cube": load_identity("bose-jewel-double-cube"),
        }
        errors = validate_profile(profile, identities)
        d029_errors = [e for e in errors if "d-029" in e.lower()]
        self.assertEqual(d029_errors, [], f"Unexpected D-029 errors: {d029_errors}")


class TestGenerateConfig(unittest.TestCase):
    """Test CamillaDSP config generation."""

    def test_generate_bose_home_config(self):
        """Generated config for bose-home should have the right structure."""
        config = generate_config("bose-home")

        # Devices section
        self.assertIn("devices", config)
        self.assertEqual(config["devices"]["samplerate"], 48000)
        self.assertEqual(config["devices"]["capture"]["channels"], 8)
        self.assertEqual(config["devices"]["playback"]["channels"], 8)

        # Mixers section
        self.assertIn("mixers", config)
        mixer_names = list(config["mixers"].keys())
        self.assertEqual(len(mixer_names), 1)
        mixer = config["mixers"][mixer_names[0]]
        self.assertEqual(mixer["channels"]["in"], 8)
        self.assertEqual(mixer["channels"]["out"], 8)

        # Filters section
        self.assertIn("filters", config)
        filters = config["filters"]
        self.assertIn("sat_headroom", filters)
        self.assertIn("sub_headroom", filters)
        self.assertIn("sat_power_limit", filters)
        self.assertIn("sub_power_limit", filters)
        # FIR filters for each speaker
        self.assertIn("sat_left_fir", filters)
        self.assertIn("sat_right_fir", filters)
        self.assertIn("sub1_fir", filters)
        self.assertIn("sub2_fir", filters)

        # Pipeline section
        self.assertIn("pipeline", config)
        pipeline = config["pipeline"]
        self.assertGreater(len(pipeline), 0)
        # First step is always the mixer
        self.assertEqual(pipeline[0]["type"], "Mixer")

    def test_bose_home_gain_values(self):
        """Generated config should have correct gain staging values."""
        config = generate_config("bose-home")
        filters = config["filters"]

        self.assertAlmostEqual(
            filters["sat_headroom"]["parameters"]["gain"], -7.0
        )
        self.assertAlmostEqual(
            filters["sub_headroom"]["parameters"]["gain"], -13.0
        )
        self.assertAlmostEqual(
            filters["sat_power_limit"]["parameters"]["gain"], -13.5
        )
        self.assertAlmostEqual(
            filters["sub_power_limit"]["parameters"]["gain"], -8.6
        )

    def test_bose_home_sub_inversion(self):
        """Sub2 should be inverted in the mixer mapping for isobaric clamshell."""
        config = generate_config("bose-home")
        mixer_name = list(config["mixers"].keys())[0]
        mapping = config["mixers"][mixer_name]["mapping"]

        # Find the sub2 mapping (dest channel 3)
        sub2_mapping = None
        for m in mapping:
            if m["dest"] == 3:
                sub2_mapping = m
                break
        self.assertIsNotNone(sub2_mapping, "Sub2 mapping (dest 3) not found")

        # All sources should be inverted
        for src in sub2_mapping["sources"]:
            self.assertTrue(
                src.get("inverted", False),
                f"Sub2 source ch {src['channel']} should be inverted",
            )

    def test_bose_home_sub1_not_inverted(self):
        """Sub1 should NOT be inverted."""
        config = generate_config("bose-home")
        mixer_name = list(config["mixers"].keys())[0]
        mapping = config["mixers"][mixer_name]["mapping"]

        sub1_mapping = None
        for m in mapping:
            if m["dest"] == 2:
                sub1_mapping = m
                break
        self.assertIsNotNone(sub1_mapping, "Sub1 mapping (dest 2) not found")

        # Sources should NOT be inverted (or explicitly False)
        for src in sub1_mapping["sources"]:
            self.assertFalse(
                src.get("inverted", False),
                f"Sub1 source ch {src['channel']} should NOT be inverted",
            )

    def test_bose_home_monitoring_passthrough(self):
        """Monitoring channels (4-7) should pass through."""
        config = generate_config("bose-home")
        mixer_name = list(config["mixers"].keys())[0]
        mapping = config["mixers"][mixer_name]["mapping"]

        for ch in [4, 5, 6, 7]:
            found = False
            for m in mapping:
                if m["dest"] == ch:
                    found = True
                    self.assertEqual(len(m["sources"]), 1)
                    self.assertEqual(m["sources"][0]["channel"], ch)
                    self.assertEqual(m["sources"][0]["gain"], 0)
                    break
            self.assertTrue(found, f"Monitoring channel {ch} not found")

    def test_bose_home_fir_uses_dirac_by_default(self):
        """Without filter_paths, FIR filters should use dirac placeholder."""
        config = generate_config("bose-home")
        for fir_name in ["sat_left_fir", "sat_right_fir", "sub1_fir", "sub2_fir"]:
            fir = config["filters"][fir_name]
            self.assertEqual(fir["type"], "Conv")
            self.assertIn("dirac", fir["parameters"]["filename"])

    def test_custom_filter_paths(self):
        """Custom filter paths should override dirac placeholders."""
        paths = {
            "sat_left": "/custom/sat_left.wav",
            "sub1": "/custom/sub1.wav",
        }
        config = generate_config("bose-home", filter_paths=paths)
        self.assertEqual(
            config["filters"]["sat_left_fir"]["parameters"]["filename"],
            "/custom/sat_left.wav",
        )
        self.assertEqual(
            config["filters"]["sub1_fir"]["parameters"]["filename"],
            "/custom/sub1.wav",
        )
        # Unspecified filters still use dirac
        self.assertIn(
            "dirac",
            config["filters"]["sat_right_fir"]["parameters"]["filename"],
        )

    def test_mode_affects_chunksize(self):
        """DJ mode should use chunksize 2048, live mode 256."""
        dj_config = generate_config("bose-home", mode="dj")
        live_config = generate_config("bose-home", mode="live")
        self.assertEqual(dj_config["devices"]["chunksize"], 2048)
        self.assertEqual(live_config["devices"]["chunksize"], 256)

    def test_pipeline_order(self):
        """Pipeline should follow: mixer -> headroom -> HPF -> FIR -> power_limit."""
        config = generate_config("bose-home")
        pipeline = config["pipeline"]

        # Extract pipeline step types/names
        steps = []
        for step in pipeline:
            if step["type"] == "Mixer":
                steps.append("mixer")
            elif step["type"] == "Filter":
                names = step["names"]
                if any("headroom" in n for n in names):
                    steps.append("headroom")
                elif any("_hpf" in n for n in names):
                    steps.append("hpf")
                elif any("fir" in n for n in names):
                    steps.append("fir")
                elif any("power_limit" in n for n in names):
                    steps.append("power_limit")
                elif any("delay" in n for n in names):
                    steps.append("delay")

        # Verify order
        self.assertEqual(steps[0], "mixer")
        # After mixer, headroom should come before HPF and FIR
        headroom_indices = [i for i, s in enumerate(steps) if s == "headroom"]
        hpf_indices = [i for i, s in enumerate(steps) if s == "hpf"]
        fir_indices = [i for i, s in enumerate(steps) if s == "fir"]
        power_indices = [i for i, s in enumerate(steps) if s == "power_limit"]

        self.assertTrue(
            all(h < min(fir_indices) for h in headroom_indices),
            "All headroom steps should come before FIR steps",
        )
        if hpf_indices:
            self.assertTrue(
                all(h < min(hpf_indices) for h in headroom_indices),
                "All headroom steps should come before HPF steps",
            )
            self.assertTrue(
                all(hp < min(fir_indices) for hp in hpf_indices),
                "All HPF steps should come before FIR steps",
            )
        self.assertTrue(
            all(f < min(power_indices) for f in fir_indices),
            "All FIR steps should come before power limit steps",
        )

    def test_delays_add_pipeline_steps(self):
        """Providing delays should add delay filter steps to the pipeline."""
        delays = {"sat_left": 1.5, "sub1": 0.8}
        config = generate_config("bose-home", delays=delays)

        # Check delay filters exist
        self.assertIn("sat_left_delay", config["filters"])
        self.assertIn("sub1_delay", config["filters"])
        self.assertEqual(
            config["filters"]["sat_left_delay"]["parameters"]["delay"], 1.5
        )
        self.assertEqual(
            config["filters"]["sat_left_delay"]["parameters"]["unit"], "ms"
        )

        # Check pipeline has delay steps
        pipeline = config["pipeline"]
        delay_steps = [
            s for s in pipeline
            if s["type"] == "Filter" and any("delay" in n for n in s["names"])
        ]
        self.assertGreater(len(delay_steps), 0)

    def test_yaml_output_is_valid(self):
        """Generated YAML should be valid and re-parseable."""
        yaml_str = config_generator.generate_config_yaml("bose-home")
        parsed = yaml.safe_load(yaml_str)
        self.assertIn("devices", parsed)
        self.assertIn("mixers", parsed)
        self.assertIn("filters", parsed)
        self.assertIn("pipeline", parsed)


class TestBoseHomeMatchesReference(unittest.TestCase):
    """
    Test that the generated config for bose-home matches the reference
    CamillaDSP production config in structure and key values.
    """

    @classmethod
    def setUpClass(cls):
        """Load both the generated config and the reference config."""
        cls.generated = generate_config("bose-home", mode="live")

        ref_path = (
            config_generator.PROJECT_ROOT
            / "configs"
            / "camilladsp"
            / "production"
            / "bose-home.yml"
        )
        with open(ref_path, "r") as f:
            cls.reference = yaml.safe_load(f)

    def test_devices_match(self):
        """Device configuration should match."""
        gen_dev = self.generated["devices"]
        ref_dev = self.reference["devices"]

        self.assertEqual(gen_dev["samplerate"], ref_dev["samplerate"])
        self.assertEqual(gen_dev["chunksize"], ref_dev["chunksize"])
        self.assertEqual(gen_dev["queuelimit"], ref_dev["queuelimit"])
        self.assertEqual(
            gen_dev["capture"]["channels"], ref_dev["capture"]["channels"]
        )
        self.assertEqual(
            gen_dev["playback"]["channels"], ref_dev["playback"]["channels"]
        )

    def test_mixer_channel_count(self):
        """Mixer should have 8in/8out."""
        gen_mixer = list(self.generated["mixers"].values())[0]
        ref_mixer = list(self.reference["mixers"].values())[0]

        self.assertEqual(
            gen_mixer["channels"]["in"], ref_mixer["channels"]["in"]
        )
        self.assertEqual(
            gen_mixer["channels"]["out"], ref_mixer["channels"]["out"]
        )

    def test_mixer_mapping_count(self):
        """Should have 8 mixer mappings (one per output channel)."""
        gen_mixer = list(self.generated["mixers"].values())[0]
        ref_mixer = list(self.reference["mixers"].values())[0]

        self.assertEqual(
            len(gen_mixer["mapping"]), len(ref_mixer["mapping"])
        )

    def test_sub_mono_sum(self):
        """Sub channels should have mono sum of L+R at -6dB."""
        gen_mixer = list(self.generated["mixers"].values())[0]

        for dest_ch in [2, 3]:
            mapping = None
            for m in gen_mixer["mapping"]:
                if m["dest"] == dest_ch:
                    mapping = m
                    break
            self.assertIsNotNone(mapping, f"Dest {dest_ch} not found")
            self.assertEqual(len(mapping["sources"]), 2)
            for src in mapping["sources"]:
                self.assertEqual(src["gain"], -6)
                self.assertIn(src["channel"], [0, 1])

    def test_headroom_filters_match(self):
        """Headroom gain values should match reference."""
        gen_f = self.generated["filters"]
        ref_f = self.reference["filters"]

        self.assertAlmostEqual(
            gen_f["sat_headroom"]["parameters"]["gain"],
            ref_f["sat_headroom"]["parameters"]["gain"],
        )
        self.assertAlmostEqual(
            gen_f["sub_headroom"]["parameters"]["gain"],
            ref_f["sub_headroom"]["parameters"]["gain"],
        )

    def test_power_limit_filters_match(self):
        """Power limit gain values should match reference."""
        gen_f = self.generated["filters"]
        ref_f = self.reference["filters"]

        self.assertAlmostEqual(
            gen_f["sat_power_limit"]["parameters"]["gain"],
            ref_f["sat_power_limit"]["parameters"]["gain"],
        )
        self.assertAlmostEqual(
            gen_f["sub_power_limit"]["parameters"]["gain"],
            ref_f["sub_power_limit"]["parameters"]["gain"],
        )

    def test_fir_filter_structure(self):
        """FIR filters should have Conv type with Wav parameters."""
        gen_f = self.generated["filters"]

        for fir_key in ["sat_left_fir", "sat_right_fir", "sub1_fir", "sub2_fir"]:
            self.assertEqual(gen_f[fir_key]["type"], "Conv")
            self.assertEqual(gen_f[fir_key]["parameters"]["type"], "Wav")
            self.assertIn("filename", gen_f[fir_key]["parameters"])

    def test_pipeline_structure_matches(self):
        """
        Pipeline structure should match reference:
        mixer -> headroom -> HPF -> FIR -> power_limit

        The generated config includes mandatory HPF steps that the
        hand-written reference lacks. We verify the non-HPF steps match.
        """
        gen_p = self.generated["pipeline"]
        ref_p = self.reference["pipeline"]

        # Both should start with a Mixer step
        self.assertEqual(gen_p[0]["type"], "Mixer")
        self.assertEqual(ref_p[0]["type"], "Mixer")

        # Count non-HPF Filter steps in generated config (HPF is new)
        gen_non_hpf_count = sum(
            1 for s in gen_p
            if s["type"] == "Filter"
            and not any("_hpf" in n for n in s.get("names", []))
        )
        ref_filter_count = sum(1 for s in ref_p if s["type"] == "Filter")
        self.assertEqual(gen_non_hpf_count, ref_filter_count)

    def test_sub2_inversion_matches_reference(self):
        """
        Sub driver 2 should be inverted in our generated config, matching
        the reference bose-home.yml.
        """
        gen_mixer = list(self.generated["mixers"].values())[0]
        ref_mixer = list(self.reference["mixers"].values())[0]

        # Find dest 3 in both
        gen_sub2 = None
        ref_sub2 = None
        for m in gen_mixer["mapping"]:
            if m["dest"] == 3:
                gen_sub2 = m
        for m in ref_mixer["mapping"]:
            if m["dest"] == 3:
                ref_sub2 = m

        self.assertIsNotNone(gen_sub2)
        self.assertIsNotNone(ref_sub2)

        # Both should have inverted sources
        for src in gen_sub2["sources"]:
            self.assertTrue(src.get("inverted", False))
        for src in ref_sub2["sources"]:
            self.assertTrue(src.get("inverted", False))


class TestWriteConfig(unittest.TestCase):
    """Test writing config to file."""

    def test_write_and_read_back(self):
        """Write config to a temp file and verify it's valid YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test_config.yml"
            config_generator.write_config(output, "bose-home")
            self.assertTrue(output.exists())

            with open(output, "r") as f:
                parsed = yaml.safe_load(f)
            self.assertIn("devices", parsed)
            self.assertIn("pipeline", parsed)


class TestMandatoryHPF(unittest.TestCase):
    """Test TK-107/TK-108: mandatory HPF filter generation and validation."""

    def test_hpf_filter_generated_for_mandatory_hpf_speaker(self):
        """Speaker with mandatory_hpf_hz produces a BiquadCombo HPF filter."""
        config = generate_config("bose-home")
        filters = config["filters"]

        # bose-ps28-iii-sub has mandatory_hpf_hz: 42 — used by sub1 and sub2
        self.assertIn("sub1_hpf", filters)
        sub1_hpf = filters["sub1_hpf"]
        self.assertEqual(sub1_hpf["type"], "BiquadCombo")
        self.assertEqual(sub1_hpf["parameters"]["type"], "ButterworthHighpass")
        self.assertEqual(sub1_hpf["parameters"]["order"], 4)
        self.assertEqual(sub1_hpf["parameters"]["freq"], 42)

        self.assertIn("sub2_hpf", filters)
        sub2_hpf = filters["sub2_hpf"]
        self.assertEqual(sub2_hpf["type"], "BiquadCombo")
        self.assertEqual(sub2_hpf["parameters"]["type"], "ButterworthHighpass")
        self.assertEqual(sub2_hpf["parameters"]["order"], 4)
        self.assertEqual(sub2_hpf["parameters"]["freq"], 42)

    def test_hpf_filter_generated_for_satellite_with_hpf(self):
        """Bose Jewel satellites also have mandatory_hpf_hz: 155."""
        config = generate_config("bose-home")
        filters = config["filters"]

        self.assertIn("sat_left_hpf", filters)
        self.assertEqual(filters["sat_left_hpf"]["parameters"]["freq"], 155)
        self.assertIn("sat_right_hpf", filters)
        self.assertEqual(filters["sat_right_hpf"]["parameters"]["freq"], 155)

    def test_no_hpf_for_null_mandatory_hpf(self):
        """Speaker with mandatory_hpf_hz: null does NOT produce an HPF filter."""
        config = generate_config("2way-80hz-sealed")
        filters = config["filters"]

        # wideband-selfbuilt-v1 has mandatory_hpf_hz: null
        self.assertNotIn("sat_left_hpf", filters)
        self.assertNotIn("sat_right_hpf", filters)
        # sub-custom-15 has mandatory_hpf_hz: null
        self.assertNotIn("sub1_hpf", filters)
        self.assertNotIn("sub2_hpf", filters)

    def test_bose_home_hpf_in_pipeline(self):
        """HPF filter steps appear in the pipeline for bose-home speakers."""
        config = generate_config("bose-home")
        pipeline = config["pipeline"]

        # Collect all filter names in the pipeline
        pipeline_filter_names = set()
        for step in pipeline:
            if step.get("type") == "Filter":
                for name in step.get("names", []):
                    pipeline_filter_names.add(name)

        # Sub HPFs must be in pipeline
        self.assertIn("sub1_hpf", pipeline_filter_names)
        self.assertIn("sub2_hpf", pipeline_filter_names)
        # Satellite HPFs must be in pipeline
        self.assertIn("sat_left_hpf", pipeline_filter_names)
        self.assertIn("sat_right_hpf", pipeline_filter_names)

    def test_no_hpf_in_pipeline_for_null(self):
        """Speakers with null mandatory_hpf_hz have no HPF pipeline steps."""
        config = generate_config("2way-80hz-sealed")
        pipeline = config["pipeline"]

        pipeline_filter_names = set()
        for step in pipeline:
            if step.get("type") == "Filter":
                for name in step.get("names", []):
                    pipeline_filter_names.add(name)

        hpf_names = [n for n in pipeline_filter_names if "_hpf" in n]
        self.assertEqual(hpf_names, [], f"Unexpected HPF filters: {hpf_names}")

    def test_bose_home_subs_have_hpf_sats_have_hpf(self):
        """
        For bose-home: both subs and satellites have mandatory HPFs.
        Subs at 42Hz, satellites at 155Hz.
        """
        config = generate_config("bose-home")
        filters = config["filters"]

        # Subs: 42Hz
        self.assertEqual(filters["sub1_hpf"]["parameters"]["freq"], 42)
        self.assertEqual(filters["sub2_hpf"]["parameters"]["freq"], 42)
        # Satellites: 155Hz
        self.assertEqual(filters["sat_left_hpf"]["parameters"]["freq"], 155)
        self.assertEqual(filters["sat_right_hpf"]["parameters"]["freq"], 155)

    def test_hpf_pipeline_order_before_fir(self):
        """HPF steps must come after headroom and before FIR in the pipeline."""
        config = generate_config("bose-home")
        pipeline = config["pipeline"]

        # Find indices of HPF and FIR steps
        hpf_indices = []
        fir_indices = []
        headroom_indices = []
        for i, step in enumerate(pipeline):
            if step.get("type") == "Filter":
                names = step.get("names", [])
                if any("_hpf" in n for n in names):
                    hpf_indices.append(i)
                elif any("_fir" in n or "fir" in n for n in names):
                    fir_indices.append(i)
                elif any("headroom" in n for n in names):
                    headroom_indices.append(i)

        self.assertGreater(len(hpf_indices), 0, "No HPF steps found")
        self.assertGreater(len(fir_indices), 0, "No FIR steps found")

        # All headroom before all HPF
        self.assertTrue(
            all(h < min(hpf_indices) for h in headroom_indices),
            "All headroom steps should come before HPF steps",
        )
        # All HPF before all FIR
        self.assertTrue(
            all(hp < min(fir_indices) for hp in hpf_indices),
            "All HPF steps should come before FIR steps",
        )

    def test_validation_raises_when_hpf_missing_from_filters(self):
        """validate_hpf_in_config raises error when mandatory HPF missing from filters."""
        profile, identities = load_profile_with_identities("bose-home")

        # Build a config that deliberately omits HPF filters
        config = {
            "filters": {
                "sat_headroom": {"type": "Gain", "parameters": {"gain": -7.0}},
                "sub_headroom": {"type": "Gain", "parameters": {"gain": -13.0}},
                "sat_left_fir": {"type": "Conv", "parameters": {"type": "Wav", "filename": "x.wav"}},
            },
            "pipeline": [
                {"type": "Mixer", "name": "route_bose_home"},
                {"type": "Filter", "channels": [0], "names": ["sat_left_fir"]},
            ],
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_hpf_in_config(profile, identities, config)
        self.assertIn("mandatory hpf", str(ctx.exception).lower())

    def test_validation_raises_when_hpf_missing_from_pipeline(self):
        """validate_hpf_in_config raises error when HPF filter exists but not in pipeline."""
        profile, identities = load_profile_with_identities("bose-home")

        # Build a config with HPF in filters but NOT in pipeline
        config = {
            "filters": {
                "sub1_hpf": {
                    "type": "BiquadCombo",
                    "parameters": {"type": "ButterworthHighpass", "order": 4, "freq": 42},
                },
                "sub2_hpf": {
                    "type": "BiquadCombo",
                    "parameters": {"type": "ButterworthHighpass", "order": 4, "freq": 42},
                },
                "sat_left_hpf": {
                    "type": "BiquadCombo",
                    "parameters": {"type": "ButterworthHighpass", "order": 4, "freq": 155},
                },
                "sat_right_hpf": {
                    "type": "BiquadCombo",
                    "parameters": {"type": "ButterworthHighpass", "order": 4, "freq": 155},
                },
            },
            "pipeline": [
                {"type": "Mixer", "name": "route_bose_home"},
                # HPF filters NOT referenced in pipeline
            ],
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_hpf_in_config(profile, identities, config)
        self.assertIn("pipeline", str(ctx.exception).lower())

    def test_validation_succeeds_for_complete_config(self):
        """validate_hpf_in_config passes when HPF is in both filters and pipeline."""
        config = generate_config("bose-home")
        profile, identities = load_profile_with_identities("bose-home")

        # Should not raise — config from generate_config is complete
        validate_hpf_in_config(profile, identities, config)

    def test_validation_succeeds_for_null_hpf_profile(self):
        """validate_hpf_in_config passes for profiles with no mandatory HPF."""
        config = generate_config("2way-80hz-sealed")
        profile, identities = load_profile_with_identities("2way-80hz-sealed")

        # Should not raise — no mandatory HPFs
        validate_hpf_in_config(profile, identities, config)


if __name__ == "__main__":
    unittest.main()
