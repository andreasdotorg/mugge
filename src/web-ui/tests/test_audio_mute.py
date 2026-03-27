"""Tests for AudioMuteManager with dynamic gain node discovery (US-091).

Verifies mute/unmute works with any number of gain nodes:
2-way (4 nodes), 3-way (6 nodes), 4-way (8 nodes).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.audio_mute import AudioMuteManager, discover_gain_nodes, DEFAULT_GAIN_NODE_NAMES


# -- Mock pw-dump data builders -----------------------------------------------

def _make_convolver_pw_data(gain_nodes: dict) -> list:
    """Build a minimal pw-dump list with a convolver node containing gain params.

    gain_nodes: dict mapping gain node names to Mult values, e.g.
        {"gain_left_hp": 0.001, "gain_right_hp": 0.001, ...}
    """
    params_array = []
    for name, mult in gain_nodes.items():
        params_array.extend([f"{name}:Mult", mult])

    return [
        {
            "id": 42,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "node.name": "pi4audio-convolver",
                    "node.description": "Test convolver",
                },
                "params": {
                    "Props": [
                        {"volume": 1.0, "mute": False},
                        {"params": params_array},
                    ],
                },
            },
        },
    ]


def _run(coro):
    """Run async coroutine in sync test context (works with pytest-playwright's loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


# Standard topologies
GAINS_2WAY = {
    "gain_left_hp": 0.001,
    "gain_right_hp": 0.001,
    "gain_sub1_lp": 0.000631,
    "gain_sub2_lp": 0.000631,
}

GAINS_3WAY = {
    "gain_mid_l": 0.002,
    "gain_mid_r": 0.002,
    "gain_sub_l": 0.001,
    "gain_sub_r": 0.001,
    "gain_tw_l": 0.003,
    "gain_tw_r": 0.003,
}

GAINS_4WAY = {
    "gain_mid_l": 0.002,
    "gain_mid_r": 0.002,
    "gain_sub_l": 0.001,
    "gain_sub_r": 0.001,
    "gain_tw_l": 0.004,
    "gain_tw_r": 0.004,
    "gain_upper_mid_l": 0.003,
    "gain_upper_mid_r": 0.003,
}


# -- discover_gain_nodes tests ------------------------------------------------

class TestDiscoverGainNodes:
    """Tests for the discover_gain_nodes function."""

    def test_discovers_2way_nodes(self):
        pw_data = _make_convolver_pw_data(GAINS_2WAY)
        names = discover_gain_nodes(pw_data)
        assert set(names) == set(GAINS_2WAY.keys())

    def test_discovers_3way_nodes(self):
        pw_data = _make_convolver_pw_data(GAINS_3WAY)
        names = discover_gain_nodes(pw_data)
        assert set(names) == set(GAINS_3WAY.keys())

    def test_discovers_4way_nodes(self):
        pw_data = _make_convolver_pw_data(GAINS_4WAY)
        names = discover_gain_nodes(pw_data)
        assert set(names) == set(GAINS_4WAY.keys())

    def test_returns_sorted(self):
        pw_data = _make_convolver_pw_data(GAINS_3WAY)
        names = discover_gain_nodes(pw_data)
        assert names == sorted(names)

    def test_falls_back_to_defaults_when_no_convolver(self):
        pw_data = [{"id": 1, "type": "PipeWire:Interface:Node",
                     "info": {"props": {"node.name": "other-node"}}}]
        names = discover_gain_nodes(pw_data)
        assert names == DEFAULT_GAIN_NODE_NAMES

    def test_falls_back_when_no_gain_prefix(self):
        pw_data = _make_convolver_pw_data({"volume_master": 1.0})
        names = discover_gain_nodes(pw_data)
        assert names == DEFAULT_GAIN_NODE_NAMES

    def test_ignores_non_gain_params(self):
        mixed = {**GAINS_2WAY, "conv_left_hp": 0.5, "hpf_sub1_lp_s1": 0.7}
        pw_data = _make_convolver_pw_data(mixed)
        names = discover_gain_nodes(pw_data)
        assert set(names) == set(GAINS_2WAY.keys())


# -- Mute tests parameterized by topology ------------------------------------

@pytest.fixture(params=[
    ("2way", GAINS_2WAY, 4),
    ("3way", GAINS_3WAY, 6),
    ("4way", GAINS_4WAY, 8),
], ids=["2way", "3way", "4way"])
def topology(request):
    """Parameterized fixture: (name, gain_dict, expected_count)."""
    return request.param


class TestMuteNWay:
    """Mute/unmute across all topologies."""

    def test_mute_sets_all_to_zero(self, topology):
        name, gains, n = topology
        pw_data = _make_convolver_pw_data(gains)
        set_calls = []

        async def mock_set_mult(node_id, node_name, mult):
            set_calls.append((node_id, node_name, mult))
            return True

        mgr = AudioMuteManager()
        with patch("app.audio_mute.pw_dump", AsyncMock(return_value=pw_data)), \
             patch("app.audio_mute.set_mult", side_effect=mock_set_mult):
            result = _run(mgr.mute())

        assert result["ok"] is True
        assert mgr.is_muted is True
        assert len(set_calls) == n
        for _, _, mult in set_calls:
            assert mult == 0.0

    def test_mute_stores_pre_mute_gains(self, topology):
        name, gains, n = topology
        pw_data = _make_convolver_pw_data(gains)

        async def mock_set_mult(node_id, node_name, mult):
            return True

        mgr = AudioMuteManager()
        with patch("app.audio_mute.pw_dump", AsyncMock(return_value=pw_data)), \
             patch("app.audio_mute.set_mult", side_effect=mock_set_mult):
            _run(mgr.mute())

        assert len(mgr._pre_mute_gains) == n
        for gname, expected in gains.items():
            assert mgr._pre_mute_gains[gname] == expected

    def test_unmute_restores_all(self, topology):
        name, gains, n = topology
        pw_data = _make_convolver_pw_data(gains)
        unmute_calls = {}

        async def mock_set_mult(node_id, node_name, mult):
            return True

        async def mock_set_mult_capture(node_id, node_name, mult):
            unmute_calls[node_name] = mult
            return True

        mgr = AudioMuteManager()
        # Mute first
        with patch("app.audio_mute.pw_dump", AsyncMock(return_value=pw_data)), \
             patch("app.audio_mute.set_mult", side_effect=mock_set_mult):
            _run(mgr.mute())

        # Unmute
        with patch("app.audio_mute.pw_dump", AsyncMock(return_value=pw_data)), \
             patch("app.audio_mute.set_mult", side_effect=mock_set_mult_capture):
            result = _run(mgr.unmute())

        assert result["ok"] is True
        assert mgr.is_muted is False
        assert len(unmute_calls) == n
        for gname, expected in gains.items():
            assert unmute_calls[gname] == expected


# -- Edge cases ---------------------------------------------------------------

class TestMuteEdgeCases:

    def test_already_muted(self):
        mgr = AudioMuteManager()
        mgr.is_muted = True
        result = _run(mgr.mute())
        assert result["ok"] is True
        assert result["detail"] == "already muted"

    def test_not_muted(self):
        mgr = AudioMuteManager()
        result = _run(mgr.unmute())
        assert result["ok"] is True
        assert result["detail"] == "not muted"

    def test_pw_dump_failure(self):
        mgr = AudioMuteManager()
        with patch("app.audio_mute.pw_dump", AsyncMock(return_value=None)):
            result = _run(mgr.mute())
        assert result["ok"] is False
        assert "pw-dump failed" in result["error"]
        assert mgr.is_muted is False

    def test_convolver_not_found(self):
        mgr = AudioMuteManager()
        pw_data = [{"id": 1, "type": "PipeWire:Interface:Node",
                     "info": {"props": {"node.name": "other"}}}]
        with patch("app.audio_mute.pw_dump", AsyncMock(return_value=pw_data)):
            result = _run(mgr.mute())
        assert result["ok"] is False
        assert "convolver node not found" in result["error"]

    def test_unmute_no_pre_mute_values(self):
        mgr = AudioMuteManager()
        mgr.is_muted = True
        mgr._pre_mute_gains = {}
        result = _run(mgr.unmute())
        assert result["ok"] is False
        assert "no pre-mute values" in result["error"]

    def test_unmute_pw_dump_failure(self):
        mgr = AudioMuteManager()
        mgr.is_muted = True
        mgr._pre_mute_gains = {"gain_left_hp": 0.001}
        with patch("app.audio_mute.pw_dump", AsyncMock(return_value=None)):
            result = _run(mgr.unmute())
        assert result["ok"] is False

    def test_partial_set_mult_failure(self):
        pw_data = _make_convolver_pw_data(GAINS_2WAY)
        call_count = [0]

        async def mock_set_mult(node_id, node_name, mult):
            call_count[0] += 1
            return call_count[0] != 2

        mgr = AudioMuteManager()
        with patch("app.audio_mute.pw_dump", AsyncMock(return_value=pw_data)), \
             patch("app.audio_mute.set_mult", side_effect=mock_set_mult):
            result = _run(mgr.mute())

        assert result["ok"] is True  # Partial success
        assert mgr.is_muted is True

    def test_mult_none_falls_back_to_read_mult(self):
        """F-057: When pw-dump doesn't expose Mult, falls back to read_mult."""
        pw_data = [
            {
                "id": 42,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {"node.name": "pi4audio-convolver"},
                    "params": {"Props": [{"volume": 1.0}]},
                },
            },
        ]

        async def mock_read_mult(node_id, name):
            return 0.005

        async def mock_set_mult(node_id, name, mult):
            return True

        mgr = AudioMuteManager()
        with patch("app.audio_mute.pw_dump", AsyncMock(return_value=pw_data)), \
             patch("app.audio_mute.read_mult", side_effect=mock_read_mult), \
             patch("app.audio_mute.set_mult", side_effect=mock_set_mult):
            result = _run(mgr.mute())

        assert result["ok"] is True
        for name in DEFAULT_GAIN_NODE_NAMES:
            assert mgr._pre_mute_gains[name] == 0.005
