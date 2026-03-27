"""Unit tests for pw_helpers gain-parsing functions (F-057).

Tests the pure parsing functions that extract gain Mult values from
pw-dump JSON data. These functions implement the "gain params on convolver
node" model — linear builtin gain nodes appear as Props params on the
parent convolver capture node, not as separate PipeWire nodes.

Architecture reference: pw_helpers.py docstring, Pi OBSERVE session S-004.
"""

import pytest

from app.pw_helpers import (
    _extract_gain_params,
    _parse_mult_from_enum,
    find_convolver_node,
    find_gain_node,
    find_quantum,
    find_sample_rate,
    find_filter_info,
    CONVOLVER_NODE_NAME,
)


# ---------------------------------------------------------------------------
# Fixtures: realistic pw-dump JSON fragments
# ---------------------------------------------------------------------------

def _make_convolver_obj(
    node_id=43,
    gain_params=None,
    node_name=CONVOLVER_NODE_NAME,
):
    """Build a pw-dump JSON object for the convolver node.

    The gain params live in info.params.Props[1].params as a flat
    alternating key-value array.
    """
    if gain_params is None:
        gain_params = {
            "gain_left_hp": 0.001,
            "gain_right_hp": 0.001,
            "gain_sub1_lp": 0.000631,
            "gain_sub2_lp": 0.000631,
        }

    # Build the flat params array: each gain node has Control, Mult, Add
    flat_params = []
    for name, mult in gain_params.items():
        flat_params.extend([
            f"{name}:Control", 0.0,
            f"{name}:Mult", mult,
            f"{name}:Add", 0.0,
        ])

    return {
        "id": node_id,
        "type": "PipeWire:Interface:Node",
        "info": {
            "props": {
                "node.name": node_name,
                "node.description": "4-channel FIR convolver",
                "media.class": "Audio/Sink",
            },
            "params": {
                "Props": [
                    # Props[0]: other node props (volume, mute, etc.)
                    {"volume": 1.0, "mute": False},
                    # Props[1]: filter-chain builtin params
                    {"params": flat_params},
                ],
            },
        },
    }


def _make_pw_dump(convolver_obj=None, extras=None):
    """Build a minimal pw-dump list with optional convolver and extras."""
    data = []
    if extras:
        data.extend(extras)
    if convolver_obj is not None:
        data.append(convolver_obj)
    return data


# ---------------------------------------------------------------------------
# _extract_gain_params
# ---------------------------------------------------------------------------

class TestExtractGainParams:
    """Test _extract_gain_params() which parses Props[1].params."""

    def test_happy_path_four_channels(self):
        """Extracts all four gain Mult values from a realistic convolver."""
        obj = _make_convolver_obj()
        result = _extract_gain_params(obj["info"])

        assert result == {
            "gain_left_hp": 0.001,
            "gain_right_hp": 0.001,
            "gain_sub1_lp": 0.000631,
            "gain_sub2_lp": 0.000631,
        }

    def test_empty_params(self):
        """Returns empty dict when params dict is empty."""
        result = _extract_gain_params({"params": {}})
        assert result == {}

    def test_no_params_key(self):
        """Returns empty dict when info has no params key."""
        result = _extract_gain_params({})
        assert result == {}

    def test_params_not_dict(self):
        """Returns empty dict when params is not a dict."""
        result = _extract_gain_params({"params": "invalid"})
        assert result == {}

    def test_no_props_in_params(self):
        """Returns empty dict when Props key is missing from params."""
        result = _extract_gain_params({"params": {"Other": []}})
        assert result == {}

    def test_props_entry_not_dict(self):
        """Skips non-dict entries in Props array."""
        result = _extract_gain_params({
            "params": {"Props": ["not_a_dict", 42]}
        })
        assert result == {}

    def test_props_entry_without_params_array(self):
        """Skips Props entries that have no 'params' sub-array."""
        result = _extract_gain_params({
            "params": {"Props": [{"volume": 1.0}]}
        })
        assert result == {}

    def test_params_array_not_list(self):
        """Skips Props entries where 'params' is not a list."""
        result = _extract_gain_params({
            "params": {"Props": [{"params": "not_a_list"}]}
        })
        assert result == {}

    def test_partial_gains(self):
        """Extracts only the gains present in the params array."""
        obj = _make_convolver_obj(gain_params={"gain_left_hp": 0.05})
        result = _extract_gain_params(obj["info"])

        assert result == {"gain_left_hp": 0.05}

    def test_zero_mult_is_valid(self):
        """Mult value of 0.0 is extracted (muted channel)."""
        obj = _make_convolver_obj(gain_params={"gain_left_hp": 0.0})
        result = _extract_gain_params(obj["info"])

        assert result == {"gain_left_hp": 0.0}

    def test_non_numeric_mult_skipped(self):
        """Non-numeric Mult values are silently skipped."""
        info = {
            "params": {
                "Props": [
                    {},
                    {"params": [
                        "gain_left_hp:Mult", "not_a_number",
                        "gain_right_hp:Mult", 0.001,
                    ]},
                ],
            },
        }
        result = _extract_gain_params(info)
        assert result == {"gain_right_hp": 0.001}

    def test_odd_length_params_array(self):
        """Odd-length params array doesn't crash (last unpaired key skipped)."""
        info = {
            "params": {
                "Props": [
                    {},
                    {"params": [
                        "gain_left_hp:Mult", 0.001,
                        "orphan_key",
                    ]},
                ],
            },
        }
        result = _extract_gain_params(info)
        assert result == {"gain_left_hp": 0.001}

    def test_non_mult_keys_ignored(self):
        """Only :Mult keys are extracted; :Control and :Add are ignored."""
        info = {
            "params": {
                "Props": [
                    {},
                    {"params": [
                        "gain_left_hp:Control", 0.0,
                        "gain_left_hp:Mult", 0.001,
                        "gain_left_hp:Add", 0.0,
                    ]},
                ],
            },
        }
        result = _extract_gain_params(info)
        assert result == {"gain_left_hp": 0.001}


# ---------------------------------------------------------------------------
# find_convolver_node
# ---------------------------------------------------------------------------

class TestFindConvolverNode:
    """Test find_convolver_node() which locates the convolver in pw-dump."""

    def test_finds_convolver(self):
        """Returns convolver ID and gain params."""
        pw_data = _make_pw_dump(_make_convolver_obj(node_id=43))
        node_id, gains = find_convolver_node(pw_data)

        assert node_id == 43
        assert gains == {
            "gain_left_hp": 0.001,
            "gain_right_hp": 0.001,
            "gain_sub1_lp": 0.000631,
            "gain_sub2_lp": 0.000631,
        }

    def test_not_found_empty_dump(self):
        """Returns (None, {}) for empty pw-dump."""
        node_id, gains = find_convolver_node([])
        assert node_id is None
        assert gains == {}

    def test_not_found_wrong_name(self):
        """Returns (None, {}) when convolver name doesn't match."""
        obj = _make_convolver_obj(node_name="other-convolver")
        pw_data = _make_pw_dump(obj)
        node_id, gains = find_convolver_node(pw_data)

        assert node_id is None
        assert gains == {}

    def test_convolver_among_other_nodes(self):
        """Finds convolver even when mixed with other nodes."""
        other = {
            "id": 10,
            "info": {"props": {"node.name": "alsa_output.usb"}},
        }
        convolver = _make_convolver_obj(node_id=43)
        pw_data = _make_pw_dump(convolver, extras=[other])

        node_id, gains = find_convolver_node(pw_data)
        assert node_id == 43
        assert "gain_left_hp" in gains


# ---------------------------------------------------------------------------
# find_gain_node
# ---------------------------------------------------------------------------

class TestFindGainNode:
    """Test find_gain_node() which resolves a named gain's Mult value."""

    def test_finds_existing_gain(self):
        """Returns convolver ID and Mult for existing gain node."""
        pw_data = _make_pw_dump(_make_convolver_obj(node_id=43))
        node_id, mult = find_gain_node(pw_data, "gain_left_hp")

        assert node_id == 43
        assert mult == 0.001

    def test_missing_gain_returns_none(self):
        """Returns (convolver_id, None) for gain not in params."""
        obj = _make_convolver_obj(gain_params={"gain_left_hp": 0.001})
        pw_data = _make_pw_dump(obj)
        node_id, mult = find_gain_node(pw_data, "gain_sub1_lp")

        assert node_id == 43  # convolver found
        assert mult is None   # but this specific gain isn't in params

    def test_no_convolver_returns_none(self):
        """Returns (None, None) when convolver not found."""
        node_id, mult = find_gain_node([], "gain_left_hp")
        assert node_id is None
        assert mult is None

    def test_zero_mult_is_found(self):
        """Mult=0.0 (muted) is distinct from not-found (None)."""
        obj = _make_convolver_obj(gain_params={"gain_left_hp": 0.0})
        pw_data = _make_pw_dump(obj)
        node_id, mult = find_gain_node(pw_data, "gain_left_hp")

        assert node_id == 43
        assert mult == 0.0  # legitimately muted, not None


# ---------------------------------------------------------------------------
# _parse_mult_from_enum
# ---------------------------------------------------------------------------

class TestParseMultFromEnum:
    """Test _parse_mult_from_enum() which parses pw-cli enum-params output."""

    def test_parses_named_mult(self):
        """Parses Mult value for a specific gain node."""
        text = (
            '  Object: size 128, type Spa:Pod:Object:Param:Props (262146)\n'
            '    Prop: key Spa:Pod:Object:Param:Props:params\n'
            '      String "gain_left_hp:Mult"\n'
            '      Float 0.001000\n'
            '      String "gain_right_hp:Mult"\n'
            '      Float 0.001000\n'
        )
        result = _parse_mult_from_enum(text, "gain_left_hp")
        assert result == pytest.approx(0.001)

    def test_parses_second_gain(self):
        """Can target a specific gain by name."""
        text = (
            '      String "gain_left_hp:Mult"\n'
            '      Float 0.001000\n'
            '      String "gain_sub1_lp:Mult"\n'
            '      Float 0.000631\n'
        )
        result = _parse_mult_from_enum(text, "gain_sub1_lp")
        assert result == pytest.approx(0.000631)

    def test_returns_none_when_not_found(self):
        """Returns None when the named gain isn't in the output."""
        text = '      String "gain_left_hp:Mult"\n      Float 0.001000\n'
        result = _parse_mult_from_enum(text, "gain_sub2_lp")
        assert result is None

    def test_returns_none_for_empty(self):
        """Returns None for empty input."""
        assert _parse_mult_from_enum("", "gain_left_hp") is None

    def test_without_node_name_returns_first(self):
        """Without node_name, returns the first Mult found."""
        text = (
            '      String "gain_left_hp:Mult"\n'
            '      Float 0.005000\n'
        )
        result = _parse_mult_from_enum(text, None)
        assert result == pytest.approx(0.005)


# ---------------------------------------------------------------------------
# find_quantum / find_sample_rate / find_filter_info
# ---------------------------------------------------------------------------

class TestFindQuantum:
    """Test find_quantum() metadata extraction."""

    def _make_settings_metadata(self, entries):
        return [{
            "type": "PipeWire:Interface:Metadata",
            "info": {
                "props": {"metadata.name": "settings"},
                "metadata": entries,
            },
        }]

    def test_reads_force_quantum(self):
        """Extracts clock.force-quantum from settings metadata."""
        pw_data = self._make_settings_metadata([
            {"key": "clock.force-quantum", "value": {"value": 1024}},
        ])
        assert find_quantum(pw_data) == 1024

    def test_falls_back_to_clock_quantum(self):
        """Falls back to clock.quantum if force-quantum missing."""
        pw_data = self._make_settings_metadata([
            {"key": "clock.quantum", "value": {"value": 256}},
        ])
        assert find_quantum(pw_data) == 256

    def test_returns_none_when_missing(self):
        """Returns None when no quantum metadata exists."""
        assert find_quantum([]) is None

    def test_prefers_force_quantum(self):
        """force-quantum is checked before clock.quantum."""
        pw_data = self._make_settings_metadata([
            {"key": "clock.force-quantum", "value": {"value": 1024}},
            {"key": "clock.quantum", "value": {"value": 256}},
        ])
        assert find_quantum(pw_data) == 1024


class TestFindSampleRate:
    """Test find_sample_rate() metadata extraction."""

    def _make_settings_metadata(self, entries):
        return [{
            "type": "PipeWire:Interface:Metadata",
            "info": {
                "props": {"metadata.name": "settings"},
                "metadata": entries,
            },
        }]

    def test_reads_clock_rate(self):
        """Extracts clock.rate from settings metadata."""
        pw_data = self._make_settings_metadata([
            {"key": "clock.rate", "value": {"value": 48000}},
        ])
        assert find_sample_rate(pw_data) == 48000

    def test_returns_48000_fallback(self):
        """Returns 48000 when no rate metadata exists."""
        assert find_sample_rate([]) == 48000


class TestFindFilterInfo:
    """Test find_filter_info() node metadata extraction."""

    def test_extracts_convolver_info(self):
        """Returns node metadata for the convolver."""
        obj = _make_convolver_obj(node_id=43)
        pw_data = _make_pw_dump(obj)
        info = find_filter_info(pw_data)

        assert info["node_name"] == CONVOLVER_NODE_NAME
        assert info["node_id"] == 43
        assert info["description"] == "4-channel FIR convolver"

    def test_returns_empty_when_missing(self):
        """Returns empty dict when convolver not found."""
        assert find_filter_info([]) == {}
