"""Unit tests for pw_wiring module.

Mocks subprocess.run and shutil.which so no PipeWire is needed.
"""

import subprocess
from unittest import mock

import pytest

# Import via importlib since directory has a hyphen.
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "pw_wiring", os.path.join(_HERE, "pw_wiring.py")
)
pw_wiring = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw_wiring)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_which(name):
    """Pretend pw-link exists at /usr/bin/pw-link."""
    if name == "pw-link":
        return "/usr/bin/pw-link"
    return None


def _ok_result(**kwargs):
    """A successful subprocess.CompletedProcess."""
    return subprocess.CompletedProcess(
        args=kwargs.get("args", []),
        returncode=0,
        stdout=kwargs.get("stdout", ""),
        stderr="",
    )


def _fail_result(stderr="error"):
    return subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=stderr,
    )


# ---------------------------------------------------------------------------
# Tests: _expected_links
# ---------------------------------------------------------------------------

class TestExpectedLinks:
    def test_total_link_count(self):
        links = pw_wiring._expected_links()
        # 8 (siggen→cdsp) + 8 (cdsp→room) + 1 (room→siggen-capture) = 17
        assert len(links) == 17

    def test_siggen_to_cdsp_links(self):
        links = pw_wiring._expected_links()
        siggen_cdsp = links[:8]
        for ch, (src, dst) in enumerate(siggen_cdsp):
            assert src == f"pi4audio-signal-gen:output_{ch}"
            assert dst == f"pi4audio-e2e-cdsp-capture:input_{ch}"

    def test_cdsp_to_room_links(self):
        links = pw_wiring._expected_links()
        cdsp_room = links[8:16]
        for ch, (src, dst) in enumerate(cdsp_room):
            assert src == f"pi4audio-e2e-cdsp-playback:output_{ch}"
            assert dst == f"pi4audio-e2e-room-sim-capture:input_{ch}"

    def test_room_to_siggen_capture_link(self):
        links = pw_wiring._expected_links()
        src, dst = links[16]
        assert src == "pi4audio-e2e-room-sim-playback:output_0"
        assert dst == "pi4audio-signal-gen-capture:input_0"

    def test_all_links_are_tuples_of_strings(self):
        for src, dst in pw_wiring._expected_links():
            assert isinstance(src, str)
            assert isinstance(dst, str)
            assert ":" in src
            assert ":" in dst


# ---------------------------------------------------------------------------
# Tests: _port helper
# ---------------------------------------------------------------------------

class TestPort:
    def test_output_port(self):
        assert pw_wiring._port("node", "output", 3) == "node:output_3"

    def test_input_port(self):
        assert pw_wiring._port("node", "input", 0) == "node:input_0"


# ---------------------------------------------------------------------------
# Tests: wire_e2e_graph
# ---------------------------------------------------------------------------

class TestWireE2EGraph:
    @mock.patch("shutil.which", side_effect=_mock_which)
    @mock.patch("subprocess.run", return_value=_ok_result())
    def test_creates_all_17_links(self, mock_run, mock_which):
        pw_wiring.wire_e2e_graph()
        assert mock_run.call_count == 17

    @mock.patch("shutil.which", side_effect=_mock_which)
    @mock.patch("subprocess.run", return_value=_ok_result())
    def test_pw_link_called_with_correct_args(self, mock_run, mock_which):
        pw_wiring.wire_e2e_graph()

        # First call: siggen output_0 → cdsp input_0
        first_call = mock_run.call_args_list[0]
        cmd = first_call[0][0]  # positional arg
        assert cmd == [
            "/usr/bin/pw-link",
            "pi4audio-signal-gen:output_0",
            "pi4audio-e2e-cdsp-capture:input_0",
        ]

        # Last call: room-sim playback output_0 → siggen-capture input_0
        last_call = mock_run.call_args_list[16]
        cmd = last_call[0][0]
        assert cmd == [
            "/usr/bin/pw-link",
            "pi4audio-e2e-room-sim-playback:output_0",
            "pi4audio-signal-gen-capture:input_0",
        ]

    @mock.patch("shutil.which", side_effect=_mock_which)
    @mock.patch("subprocess.run", return_value=_ok_result())
    def test_link_order_siggen_then_cdsp_then_room(self, mock_run, mock_which):
        pw_wiring.wire_e2e_graph()
        calls = mock_run.call_args_list

        # Verify the three groups appear in order
        # Group 1: calls 0-7 contain "pi4audio-signal-gen:output"
        for i in range(8):
            cmd = calls[i][0][0]
            assert "pi4audio-signal-gen:output" in cmd[1]
            assert "pi4audio-e2e-cdsp-capture:input" in cmd[2]

        # Group 2: calls 8-15 contain "pi4audio-e2e-cdsp-playback:output"
        for i in range(8, 16):
            cmd = calls[i][0][0]
            assert "pi4audio-e2e-cdsp-playback:output" in cmd[1]
            assert "pi4audio-e2e-room-sim-capture:input" in cmd[2]

        # Group 3: call 16 contains "pi4audio-e2e-room-sim-playback:output"
        cmd = calls[16][0][0]
        assert "pi4audio-e2e-room-sim-playback:output" in cmd[1]
        assert "pi4audio-signal-gen-capture:input" in cmd[2]

    @mock.patch("shutil.which", side_effect=_mock_which)
    @mock.patch("subprocess.run", return_value=_fail_result("link failed"))
    def test_raises_on_pw_link_failure(self, mock_run, mock_which):
        with pytest.raises(pw_wiring.WiringError, match="link failed"):
            pw_wiring.wire_e2e_graph()


# ---------------------------------------------------------------------------
# Tests: verify_wiring
# ---------------------------------------------------------------------------

class TestVerifyWiring:
    @mock.patch("shutil.which", side_effect=_mock_which)
    @mock.patch("subprocess.run")
    def test_all_connected(self, mock_run, mock_which):
        # Simulate pw-link --links output containing all port names
        all_ports = []
        for src, dst in pw_wiring._expected_links():
            all_ports.extend([src, dst])
        fake_output = "\n".join(all_ports)
        mock_run.return_value = _ok_result(stdout=fake_output)

        result = pw_wiring.verify_wiring()
        assert len(result) == 17
        assert all(result.values())

    @mock.patch("shutil.which", side_effect=_mock_which)
    @mock.patch("subprocess.run")
    def test_missing_link_detected(self, mock_run, mock_which):
        # Output that contains most ports but not the room→siggen link
        links = pw_wiring._expected_links()
        all_ports = []
        for src, dst in links[:-1]:  # exclude last link
            all_ports.extend([src, dst])
        fake_output = "\n".join(all_ports)
        mock_run.return_value = _ok_result(stdout=fake_output)

        result = pw_wiring.verify_wiring()
        # Last link should be missing
        last_key = (
            "pi4audio-e2e-room-sim-playback:output_0 → "
            "pi4audio-signal-gen-capture:input_0"
        )
        assert result[last_key] is False
        # Other links should be present
        connected = [k for k, v in result.items() if v]
        assert len(connected) == 16


# ---------------------------------------------------------------------------
# Tests: teardown_wiring
# ---------------------------------------------------------------------------

class TestTeardownWiring:
    @mock.patch("shutil.which", side_effect=_mock_which)
    @mock.patch("subprocess.run", return_value=_ok_result())
    def test_disconnects_all_17_links(self, mock_run, mock_which):
        pw_wiring.teardown_wiring()
        assert mock_run.call_count == 17

    @mock.patch("shutil.which", side_effect=_mock_which)
    @mock.patch("subprocess.run", return_value=_ok_result())
    def test_uses_disconnect_flag(self, mock_run, mock_which):
        pw_wiring.teardown_wiring()
        for call in mock_run.call_args_list:
            cmd = call[0][0]
            assert cmd[1] == "--disconnect"

    @mock.patch("shutil.which", side_effect=_mock_which)
    @mock.patch("subprocess.run", return_value=_fail_result("not found"))
    def test_tolerates_errors(self, mock_run, mock_which):
        # Should not raise even when pw-link fails
        pw_wiring.teardown_wiring()
        assert mock_run.call_count == 17


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @mock.patch("shutil.which", return_value=None)
    def test_pw_link_not_found_raises(self, mock_which):
        with pytest.raises(pw_wiring.WiringError, match="pw-link not found"):
            pw_wiring.wire_e2e_graph()

    @mock.patch("shutil.which", return_value=None)
    def test_verify_not_found_raises(self, mock_which):
        with pytest.raises(pw_wiring.WiringError, match="pw-link not found"):
            pw_wiring.verify_wiring()

    @mock.patch("shutil.which", return_value=None)
    def test_teardown_not_found_raises(self, mock_which):
        with pytest.raises(pw_wiring.WiringError, match="pw-link not found"):
            pw_wiring.teardown_wiring()
