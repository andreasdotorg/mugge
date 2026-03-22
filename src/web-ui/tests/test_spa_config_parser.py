"""Tests for SPA config parser and filter-chain topology extraction."""

import pathlib

import pytest

from app.spa_config_parser import (
    extract_filter_chain_topology,
    parse_spa_config,
)

# Path to the real config file used as fixture
CONFIG_PATH = pathlib.Path(__file__).resolve().parents[3] / "configs/pipewire/30-filter-chain-convolver.conf"


@pytest.fixture
def config_text():
    return CONFIG_PATH.read_text()


@pytest.fixture
def parsed(config_text):
    return parse_spa_config(config_text)


@pytest.fixture
def topology(parsed):
    return extract_filter_chain_topology(parsed)


# ── Parsing basics ──────────────────────────────────────────────


class TestParseSpaConfig:
    def test_returns_dict(self, parsed):
        assert isinstance(parsed, dict)

    def test_context_modules_is_list(self, parsed):
        assert "context.modules" in parsed
        assert isinstance(parsed["context.modules"], list)
        assert len(parsed["context.modules"]) == 1

    def test_module_name(self, parsed):
        module = parsed["context.modules"][0]
        assert module["name"] == "libpipewire-module-filter-chain"

    def test_node_description(self, parsed):
        args = parsed["context.modules"][0]["args"]
        assert args["node.description"] == "FIR Convolver (4ch x 16k taps)"

    def test_filter_graph_exists(self, parsed):
        args = parsed["context.modules"][0]["args"]
        assert "filter.graph" in args
        graph = args["filter.graph"]
        assert "nodes" in graph
        assert "links" in graph
        assert "inputs" in graph
        assert "outputs" in graph

    def test_capture_props(self, parsed):
        args = parsed["context.modules"][0]["args"]
        cap = args["capture.props"]
        assert cap["node.name"] == "pi4audio-convolver"
        assert cap["media.class"] == "Audio/Sink"
        assert cap["audio.channels"] == 4
        assert cap["node.autoconnect"] is False

    def test_audio_position_array(self, parsed):
        args = parsed["context.modules"][0]["args"]
        pos = args["capture.props"]["audio.position"]
        assert pos == ["AUX0", "AUX1", "AUX2", "AUX3"]

    def test_playback_props(self, parsed):
        args = parsed["context.modules"][0]["args"]
        play = args["playback.props"]
        assert play["node.name"] == "pi4audio-convolver-out"
        assert play["node.passive"] is True


# ── Topology extraction ────────────────────────────────────────


class TestExtractTopology:
    def test_node_count(self, topology):
        assert len(topology["nodes"]) == 8

    def test_convolver_nodes(self, topology):
        convolvers = [n for n in topology["nodes"] if n["label"] == "convolver"]
        assert len(convolvers) == 4
        names = {n["name"] for n in convolvers}
        assert names == {"conv_left_hp", "conv_right_hp", "conv_sub1_lp", "conv_sub2_lp"}

    def test_gain_nodes(self, topology):
        gains = [n for n in topology["nodes"] if n["label"] == "linear"]
        assert len(gains) == 4
        names = {n["name"] for n in gains}
        assert names == {"gain_left_hp", "gain_right_hp", "gain_sub1_lp", "gain_sub2_lp"}

    def test_all_nodes_are_builtin(self, topology):
        for node in topology["nodes"]:
            assert node["type"] == "builtin"

    def test_convolver_has_config(self, topology):
        conv = next(n for n in topology["nodes"] if n["name"] == "conv_left_hp")
        assert "config" in conv
        assert conv["config"]["filename"] == "/etc/pi4audio/coeffs/combined_left_hp.wav"

    def test_gain_has_control(self, topology):
        gain = next(n for n in topology["nodes"] if n["name"] == "gain_left_hp")
        assert "control" in gain
        assert gain["control"]["Mult"] == 0.001
        assert gain["control"]["Add"] == 0.0

    def test_sub_gain_values(self, topology):
        gain = next(n for n in topology["nodes"] if n["name"] == "gain_sub1_lp")
        assert gain["control"]["Mult"] == 0.000631

    def test_link_count(self, topology):
        assert len(topology["links"]) == 4

    def test_links_connect_convolver_to_gain(self, topology):
        for link in topology["links"]:
            assert link["output_node"].startswith("conv_")
            assert link["output_port"] == "Out"
            assert link["input_node"].startswith("gain_")
            assert link["input_port"] == "In"

    def test_link_pairing(self, topology):
        pairs = {(l["output_node"], l["input_node"]) for l in topology["links"]}
        assert ("conv_left_hp", "gain_left_hp") in pairs
        assert ("conv_right_hp", "gain_right_hp") in pairs
        assert ("conv_sub1_lp", "gain_sub1_lp") in pairs
        assert ("conv_sub2_lp", "gain_sub2_lp") in pairs

    def test_input_count(self, topology):
        assert len(topology["inputs"]) == 4

    def test_inputs_are_convolver_inputs(self, topology):
        for inp in topology["inputs"]:
            assert inp["node"].startswith("conv_")
            assert inp["port"] == "In"

    def test_output_count(self, topology):
        assert len(topology["outputs"]) == 4

    def test_outputs_are_gain_outputs(self, topology):
        for out in topology["outputs"]:
            assert out["node"].startswith("gain_")
            assert out["port"] == "Out"


# ── Edge cases ─────────────────────────────────────────────────


class TestEdgeCases:
    def test_comments_ignored(self):
        text = """
        # This is a comment
        key1 = "value1"
        # Another comment
        key2 = 42
        """
        result = parse_spa_config(text)
        assert result == {"key1": "value1", "key2": 42}

    def test_nested_objects(self):
        text = """
        outer = {
            inner = {
                deep = "value"
            }
        }
        """
        result = parse_spa_config(text)
        assert result["outer"]["inner"]["deep"] == "value"

    def test_quoted_strings_with_spaces(self):
        text = 'label = "FIR Convolver (4ch x 16k taps)"'
        result = parse_spa_config(text)
        assert result["label"] == "FIR Convolver (4ch x 16k taps)"

    def test_quoted_string_with_path(self):
        text = 'filename = "/etc/pi4audio/coeffs/combined_left_hp.wav"'
        result = parse_spa_config(text)
        assert result["filename"] == "/etc/pi4audio/coeffs/combined_left_hp.wav"

    def test_array_of_strings(self):
        text = 'items = [ "foo" "bar" "baz" ]'
        result = parse_spa_config(text)
        assert result["items"] == ["foo", "bar", "baz"]

    def test_array_of_objects(self):
        text = """
        items = [
            { name = "a" value = 1 }
            { name = "b" value = 2 }
        ]
        """
        result = parse_spa_config(text)
        assert len(result["items"]) == 2
        assert result["items"][0]["name"] == "a"
        assert result["items"][1]["value"] == 2

    def test_unquoted_values(self):
        text = "type = builtin"
        result = parse_spa_config(text)
        assert result["type"] == "builtin"

    def test_numeric_values(self):
        text = """
        int_val = 4
        float_val = 0.001
        """
        result = parse_spa_config(text)
        assert result["int_val"] == 4
        assert isinstance(result["int_val"], int)
        assert result["float_val"] == 0.001
        assert isinstance(result["float_val"], float)

    def test_boolean_values(self):
        text = """
        yes = true
        no = false
        """
        result = parse_spa_config(text)
        assert result["yes"] is True
        assert result["no"] is False

    def test_dotted_keys(self):
        text = """
        node.name = "foo"
        session.suspend-timeout-seconds = 0
        """
        result = parse_spa_config(text)
        assert result["node.name"] == "foo"
        assert result["session.suspend-timeout-seconds"] == 0

    def test_key_value_without_equals(self):
        text = """
        type   builtin
        name   conv_left_hp
        """
        result = parse_spa_config(text)
        assert result["type"] == "builtin"
        assert result["name"] == "conv_left_hp"

    def test_empty_object(self):
        text = "obj = {}"
        result = parse_spa_config(text)
        assert result["obj"] == {}

    def test_empty_array(self):
        text = "arr = []"
        result = parse_spa_config(text)
        assert result["arr"] == []

    def test_no_context_modules_raises(self):
        config = {"other": "data"}
        with pytest.raises(ValueError, match="No context.modules"):
            extract_filter_chain_topology(config)

    def test_escaped_quote_in_string(self):
        text = r'msg = "say \"hello\""'
        result = parse_spa_config(text)
        assert result["msg"] == 'say "hello"'

    def test_inline_object_in_array(self):
        text = """
        links = [
            { output = "conv:Out" input = "gain:In" }
        ]
        """
        result = parse_spa_config(text)
        assert result["links"][0]["output"] == "conv:Out"
        assert result["links"][0]["input"] == "gain:In"
