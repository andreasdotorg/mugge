#!/usr/bin/env python3
"""Tests for the MIDI system controller daemon.

Mocks the mido module so tests run on any machine without MIDI hardware
or the mido/python-rtmidi packages installed.

Run:  cd src/midi && python -m pytest tests/test_midi_daemon.py -v
"""

import importlib
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Bootstrap: create a fake mido module before importing the daemon
# ---------------------------------------------------------------------------

_fake_mido = types.ModuleType("mido")


class _FakeMessage:
    """Minimal stand-in for mido.Message used in tests."""

    def __init__(self, msg_type="note_on", **kwargs):
        self.type = msg_type
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        attrs = " ".join(f"{k}={v}" for k, v in self.__dict__.items() if k != "type")
        return f"<FakeMessage {self.type} {attrs}>"


_fake_mido.Message = _FakeMessage
_fake_mido.get_input_names = lambda: []
_fake_mido.get_output_names = lambda: []
_fake_mido.open_input = lambda *a, **kw: None
_fake_mido.open_output = lambda *a, **kw: None
sys.modules["mido"] = _fake_mido

# Now import the daemon module
_daemon_path = os.path.join(os.path.dirname(__file__), "..", "midi-system-controller.py")
_spec = importlib.util.spec_from_file_location("midi_daemon", _daemon_path)
daemon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(daemon)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "configs", "midi", "apcmini-mk2.yml"
)


class RecordingPort:
    """A mock MIDI port that records sent messages and allows injecting poll results."""

    def __init__(self, name="test"):
        self.name = name
        self.sent = []
        self._poll_queue = []
        self._closed = False

    def send(self, msg):
        self.sent.append(msg)

    def poll(self):
        if self._poll_queue:
            return self._poll_queue.pop(0)
        return None

    def inject(self, msg):
        """Queue a message to be returned by the next poll() call."""
        self._poll_queue.append(msg)

    def close(self):
        self._closed = True

    @property
    def closed(self):
        return self._closed


def make_controller(config=None):
    """Create a MidiSystemController with RecordingPorts and the real config."""
    if config is None:
        config = daemon.load_config(CONFIG_PATH)
    hw_in = RecordingPort("hw-in")
    hw_out = RecordingPort("hw-out")
    virt_in = RecordingPort("virt-in")
    virt_out = RecordingPort("virt-out")
    ctrl = daemon.MidiSystemController(config, hw_in, hw_out, virt_in, virt_out)
    return ctrl, hw_in, hw_out, virt_in, virt_out


def note_on(note, velocity=127):
    return _FakeMessage("note_on", note=note, velocity=velocity)


def note_off(note, velocity=0):
    return _FakeMessage("note_off", note=note, velocity=velocity)


def cc(control, value):
    return _FakeMessage("control_change", control=control, value=value)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfigLoading(unittest.TestCase):
    """Test YAML configuration loading."""

    def test_load_config_from_yaml(self):
        cfg = daemon.load_config(CONFIG_PATH)
        assert cfg["device_name"] == "APC mini mk2"
        assert cfg["virtual_port_name"] == "APCmini-Reaper"
        assert cfg["shift_note"] == 122
        assert cfg["timeouts"]["system_mode"] == 7.0
        assert cfg["timeouts"]["confirmation"] == 3.0
        assert cfg["fader_ccs"] == [48, 49, 50, 51, 52, 53, 54, 55, 56]

    def test_config_system_mode_map(self):
        cfg = daemon.load_config(CONFIG_PATH)
        smap = cfg["grid_buttons"]["system_mode_map"]
        assert 0 in smap
        assert smap[0]["action"] == "dj_mode"
        assert smap[0]["confirm"] is True
        assert 7 in smap
        assert smap[7]["action"] == "stats_toggle"
        assert smap[7]["confirm"] is False

    def test_config_led_colors(self):
        cfg = daemon.load_config(CONFIG_PATH)
        colors = cfg["led_colors"]
        assert colors["reaper_mode_shift"] == 0
        assert colors["system_mode_shift"] == 5
        assert colors["confirm_blink"] == [5, 0]
        assert colors["confirm_success"] == 21

    def test_default_config_used_when_file_missing(self):
        """DEFAULT_CONFIG has all the required keys."""
        dc = daemon.DEFAULT_CONFIG
        assert "device_name" in dc
        assert "virtual_port_name" in dc
        assert "timeouts" in dc
        assert "fader_ccs" in dc
        assert "shift_note" in dc
        assert "led_colors" in dc


class TestControllerInit(unittest.TestCase):
    """Test MidiSystemController initialization."""

    def test_initial_state_is_reaper(self):
        ctrl, *_ = make_controller()
        assert ctrl.grid_mode == daemon.STATE_REAPER

    def test_system_map_keys_are_ints(self):
        ctrl, *_ = make_controller()
        for key in ctrl.system_map:
            assert isinstance(key, int), f"system_map key {key!r} is not int"

    def test_system_map_has_expected_actions(self):
        ctrl, *_ = make_controller()
        actions = {v["action"] for v in ctrl.system_map.values()}
        assert "dj_mode" in actions
        assert "live_mode" in actions
        assert "stats_toggle" in actions

    def test_fader_ccs_is_a_set(self):
        ctrl, *_ = make_controller()
        assert isinstance(ctrl.fader_ccs, set)
        assert 48 in ctrl.fader_ccs
        assert 56 in ctrl.fader_ccs

    def test_led_cache_starts_empty(self):
        ctrl, *_ = make_controller()
        assert ctrl.reaper_led_cache == {}


class TestStateMachineTransitions(unittest.TestCase):
    """Test state machine: REAPER <-> SYSTEM -> CONFIRMING."""

    def test_shift_reaper_to_system(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.handle_hw_message(note_on(122))
        assert ctrl.grid_mode == daemon.STATE_SYSTEM

    def test_shift_system_to_reaper(self):
        ctrl, *_ = make_controller()
        ctrl.handle_hw_message(note_on(122))
        assert ctrl.grid_mode == daemon.STATE_SYSTEM
        ctrl.handle_hw_message(note_on(122))
        assert ctrl.grid_mode == daemon.STATE_REAPER

    def test_shift_confirming_to_reaper(self):
        """Shift while confirming should return to Reaper mode."""
        ctrl, *_ = make_controller()
        # Enter system mode
        ctrl.handle_hw_message(note_on(122))
        assert ctrl.grid_mode == daemon.STATE_SYSTEM
        # Press a destructive button (note 0 = dj_mode, confirm=true)
        ctrl.handle_hw_message(note_on(0))
        assert ctrl.grid_mode == daemon.STATE_CONFIRMING
        # Shift should go back to Reaper
        ctrl.handle_hw_message(note_on(122))
        assert ctrl.grid_mode == daemon.STATE_REAPER

    def test_shift_only_on_note_on_with_velocity(self):
        """Shift should only trigger on note_on with velocity > 0."""
        ctrl, *_ = make_controller()
        # note_off on shift: should NOT toggle
        ctrl.handle_hw_message(note_off(122))
        assert ctrl.grid_mode == daemon.STATE_REAPER
        # note_on with velocity 0: should NOT toggle
        ctrl.handle_hw_message(note_on(122, velocity=0))
        assert ctrl.grid_mode == daemon.STATE_REAPER

    def test_system_mode_paints_leds(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.handle_hw_message(note_on(122))
        # hw_out should have received LED updates for all mapped buttons + shift
        sent_notes = {m.note for m in hw_out.sent if m.type == "note_on"}
        # All system_map keys should be painted
        for note in ctrl.system_map:
            assert note in sent_notes, f"Note {note} not painted in system mode"
        # Shift LED should be painted
        assert 122 in sent_notes


class TestAutoTimeout(unittest.TestCase):
    """Test system mode auto-timeout (7s default)."""

    def test_system_mode_timeout(self):
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()
        assert ctrl.grid_mode == daemon.STATE_SYSTEM
        # Simulate time passing beyond the timeout
        ctrl.system_entered_at -= 8.0  # shift the entry time 8s into the past
        ctrl.check_timeouts()
        assert ctrl.grid_mode == daemon.STATE_REAPER

    def test_system_mode_no_timeout_before_deadline(self):
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()
        # Only 3s passed (< 7s timeout)
        ctrl.system_entered_at -= 3.0
        ctrl.check_timeouts()
        assert ctrl.grid_mode == daemon.STATE_SYSTEM

    def test_confirmation_timeout_returns_to_system(self):
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()
        # Press destructive button
        ctrl.handle_hw_message(note_on(0))
        assert ctrl.grid_mode == daemon.STATE_CONFIRMING
        # Simulate confirmation timeout
        ctrl.confirm_deadline = 0.0  # deadline in the far past
        ctrl.check_timeouts()
        assert ctrl.grid_mode == daemon.STATE_SYSTEM

    def test_confirmation_timeout_resets_system_timer(self):
        """After confirmation timeout, system mode timer should be fresh."""
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()
        ctrl.handle_hw_message(note_on(0))
        assert ctrl.grid_mode == daemon.STATE_CONFIRMING
        import time
        before = time.monotonic()
        ctrl.confirm_deadline = 0.0
        ctrl.check_timeouts()
        assert ctrl.grid_mode == daemon.STATE_SYSTEM
        # system_entered_at should be recent (within 1 second of now)
        assert ctrl.system_entered_at >= before

    def test_confirmation_timeout_clears_pending(self):
        """After confirmation timeout, pending_action and pending_note are cleared."""
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()
        ctrl.handle_hw_message(note_on(0))
        assert ctrl.pending_action == "dj_mode"
        assert ctrl.pending_note == 0
        ctrl.confirm_deadline = 0.0
        ctrl.check_timeouts()
        assert ctrl.pending_action is None
        assert ctrl.pending_note is None


class TestConfirmationFlow(unittest.TestCase):
    """Test the two-press confirmation for destructive actions."""

    def test_first_press_enters_confirming(self):
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()
        ctrl.handle_hw_message(note_on(0))  # dj_mode, confirm=true
        assert ctrl.grid_mode == daemon.STATE_CONFIRMING
        assert ctrl.pending_action == "dj_mode"
        assert ctrl.pending_note == 0

    def test_second_press_executes_action(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        ctrl.handle_hw_message(note_on(0))
        assert ctrl.grid_mode == daemon.STATE_CONFIRMING

        # Mock the action function to track execution
        executed = []
        with patch.dict(daemon.ACTION_DISPATCH, {"dj_mode": lambda: executed.append("dj_mode")}):
            ctrl.handle_hw_message(note_on(0))  # second press confirms

        assert "dj_mode" in executed
        # Should return to system mode after execution
        assert ctrl.grid_mode == daemon.STATE_SYSTEM

    def test_different_button_cancels_confirmation(self):
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()
        ctrl.handle_hw_message(note_on(0))  # dj_mode, confirm=true
        assert ctrl.grid_mode == daemon.STATE_CONFIRMING

        # Press a different mapped button (note 7 = stats_toggle, confirm=false)
        executed = []
        with patch.dict(daemon.ACTION_DISPATCH, {"stats_toggle": lambda: executed.append("stats")}):
            ctrl.handle_hw_message(note_on(7))

        # Confirmation should be cancelled, stats_toggle executed immediately
        assert ctrl.grid_mode == daemon.STATE_SYSTEM
        assert "stats" in executed
        assert ctrl.pending_action is None

    def test_blink_during_confirmation(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        hw_out.sent.clear()

        ctrl.handle_hw_message(note_on(0))
        assert ctrl.grid_mode == daemon.STATE_CONFIRMING

        # The first blink LED should have been set
        blink_msgs = [m for m in hw_out.sent if m.type == "note_on" and m.note == 0]
        assert len(blink_msgs) >= 1

        # Simulate blink tick
        hw_out.sent.clear()
        ctrl.last_blink_time -= 0.5  # force blink interval to elapse
        ctrl.check_timeouts()
        blink_msgs = [m for m in hw_out.sent if m.type == "note_on" and m.note == 0]
        assert len(blink_msgs) == 1  # one blink update

    def test_immediate_action_no_confirmation(self):
        """Non-destructive buttons execute immediately without confirmation."""
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()

        executed = []
        with patch.dict(daemon.ACTION_DISPATCH, {"stats_toggle": lambda: executed.append("stats")}):
            ctrl.handle_hw_message(note_on(7))  # stats_toggle, confirm=false

        assert "stats" in executed
        assert ctrl.grid_mode == daemon.STATE_SYSTEM
        # Should NOT have entered confirming
        assert ctrl.pending_action is None


class TestFaderRouting(unittest.TestCase):
    """Test that fader CCs are always forwarded to Reaper regardless of mode."""

    def test_fader_forwarded_in_reaper_mode(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        msg = cc(48, 100)
        ctrl.handle_hw_message(msg)
        assert msg in virt_out.sent

    def test_fader_forwarded_in_system_mode(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        msg = cc(48, 100)
        ctrl.handle_hw_message(msg)
        assert msg in virt_out.sent

    def test_fader_forwarded_in_confirming_mode(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        ctrl.handle_hw_message(note_on(0))  # enter confirming
        assert ctrl.grid_mode == daemon.STATE_CONFIRMING
        msg = cc(48, 100)
        ctrl.handle_hw_message(msg)
        assert msg in virt_out.sent

    def test_all_nine_faders_forwarded(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        for fader_cc in [48, 49, 50, 51, 52, 53, 54, 55, 56]:
            msg = cc(fader_cc, 64)
            ctrl.handle_hw_message(msg)
            assert msg in virt_out.sent, f"Fader CC {fader_cc} not forwarded"

    def test_non_fader_cc_not_forwarded_in_system_mode(self):
        """A CC that is not a fader should go to Reaper only in Reaper mode."""
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        msg = cc(10, 64)  # not a fader CC
        ctrl.handle_hw_message(msg)
        # In system mode, non-fader CCs should NOT be forwarded (line 313 only
        # forwards "other messages" if grid_mode == STATE_REAPER)
        assert msg not in virt_out.sent


class TestGridRouting(unittest.TestCase):
    """Test grid button routing based on mode."""

    def test_grid_to_reaper_in_reaper_mode(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        msg = note_on(32)
        ctrl.handle_hw_message(msg)
        assert msg in virt_out.sent

    def test_grid_note_off_to_reaper_in_reaper_mode(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        msg = note_off(32)
        ctrl.handle_hw_message(msg)
        assert msg in virt_out.sent

    def test_grid_not_forwarded_in_system_mode(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        virt_out.sent.clear()
        msg = note_on(32)  # unmapped grid button
        ctrl.handle_hw_message(msg)
        assert msg not in virt_out.sent

    def test_system_button_triggers_action(self):
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()
        executed = []
        with patch.dict(daemon.ACTION_DISPATCH, {"stats_toggle": lambda: executed.append(True)}):
            ctrl.handle_hw_message(note_on(7))
        assert executed

    def test_unmapped_button_ignored_in_system_mode(self):
        """Pressing an unmapped grid button in system mode does nothing."""
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        initial_mode = ctrl.grid_mode
        virt_out.sent.clear()
        # Note 32 is not in system_mode_map
        ctrl.handle_hw_message(note_on(32))
        assert ctrl.grid_mode == initial_mode
        assert len(virt_out.sent) == 0

    def test_note_off_ignored_in_system_mode(self):
        """note_off events are ignored in system mode."""
        ctrl, *_ = make_controller()
        ctrl.enter_system_mode()
        executed = []
        with patch.dict(daemon.ACTION_DISPATCH, {"stats_toggle": lambda: executed.append(True)}):
            ctrl.handle_hw_message(note_off(7))
        assert not executed


class TestLEDCache(unittest.TestCase):
    """Test the Reaper LED cache for flicker-free mode transitions."""

    def test_reaper_led_cached(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        # Simulate Reaper sending LED updates
        ctrl.handle_virt_message(note_on(10, velocity=9))
        ctrl.handle_virt_message(note_on(20, velocity=5))
        assert ctrl.reaper_led_cache[10] == 9
        assert ctrl.reaper_led_cache[20] == 5

    def test_reaper_led_forwarded_in_reaper_mode(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        msg = note_on(10, velocity=9)
        ctrl.handle_virt_message(msg)
        # Should be forwarded to hardware
        assert any(m.note == 10 and m.velocity == 9 for m in hw_out.sent)

    def test_reaper_led_not_forwarded_in_system_mode(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        hw_out.sent.clear()
        ctrl.handle_virt_message(note_on(10, velocity=9))
        # Should be cached but NOT forwarded
        assert ctrl.reaper_led_cache[10] == 9
        led_for_10 = [m for m in hw_out.sent if hasattr(m, "note") and m.note == 10]
        assert len(led_for_10) == 0

    def test_led_cache_replayed_on_reaper_mode_entry(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        # Set some LEDs while in Reaper mode
        ctrl.handle_virt_message(note_on(10, velocity=9))
        ctrl.handle_virt_message(note_on(20, velocity=5))

        # Switch to system mode
        ctrl.enter_system_mode()
        hw_out.sent.clear()

        # Switch back to Reaper mode
        ctrl.enter_reaper_mode()

        # Cached LEDs should have been replayed
        replayed = {m.note: m.velocity for m in hw_out.sent
                    if m.type == "note_on" and hasattr(m, "note") and m.note in (10, 20)}
        assert replayed.get(10) == 9
        assert replayed.get(20) == 5

    def test_system_map_buttons_cleared_on_reaper_entry(self):
        """System mode buttons not in Reaper cache should be cleared (LED off)."""
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        hw_out.sent.clear()
        ctrl.enter_reaper_mode()

        # For system_map buttons not in reaper_led_cache, LED should be set to 0
        cleared = {m.note: m.velocity for m in hw_out.sent
                   if m.type == "note_on" and m.note in ctrl.system_map}
        for note in ctrl.system_map:
            if note not in ctrl.reaper_led_cache:
                assert cleared.get(note) == 0, f"Note {note} not cleared on Reaper entry"


class TestSystemActions(unittest.TestCase):
    """Test system action dispatch."""

    def test_all_config_actions_have_handlers(self):
        """Every action in the config must have a handler in ACTION_DISPATCH."""
        cfg = daemon.load_config(CONFIG_PATH)
        smap = cfg["grid_buttons"]["system_mode_map"]
        for key, entry in smap.items():
            action = entry["action"]
            assert action in daemon.ACTION_DISPATCH, \
                f"Action {action!r} (note {key}) has no handler in ACTION_DISPATCH"

    def test_action_dispatch_contains_expected_actions(self):
        assert "dj_mode" in daemon.ACTION_DISPATCH
        assert "live_mode" in daemon.ACTION_DISPATCH
        assert "stats_toggle" in daemon.ACTION_DISPATCH
        assert "mixxx_toggle" in daemon.ACTION_DISPATCH
        assert "reaper_toggle" in daemon.ACTION_DISPATCH

    def test_execute_unknown_action_logs_error(self):
        """Executing an unknown action should not crash."""
        ctrl, *_ = make_controller()
        # Should just log an error, not raise
        ctrl.execute_action("nonexistent_action", 0)

    def test_flash_success_after_action(self):
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        hw_out.sent.clear()

        with patch.dict(daemon.ACTION_DISPATCH, {"stats_toggle": lambda: None}):
            ctrl.handle_hw_message(note_on(7))

        # Should include a green flash on note 7
        flash_msgs = [m for m in hw_out.sent
                      if m.type == "note_on" and m.note == 7
                      and m.velocity == ctrl.colors["confirm_success"]]
        assert len(flash_msgs) == 1


class TestMockPort(unittest.TestCase):
    """Test the MockPort class itself."""

    def test_mock_port_send(self):
        port = daemon.MockPort("test")
        port.send(_FakeMessage("note_on", note=0, velocity=127))
        # Should not raise

    def test_mock_port_poll_returns_none(self):
        port = daemon.MockPort("test")
        assert port.poll() is None

    def test_mock_port_close(self):
        port = daemon.MockPort("test")
        assert not port.closed
        port.close()
        assert port.closed


class TestOpenPorts(unittest.TestCase):
    """Test port opening logic."""

    def test_mock_mode_returns_mock_ports(self):
        cfg = daemon.load_config(CONFIG_PATH)
        ports = daemon.open_ports(cfg, mock=True)
        assert len(ports) == 4
        for port in ports:
            assert isinstance(port, daemon.MockPort)

    def test_close_ports_handles_none(self):
        """close_ports should handle None ports without error."""
        daemon.close_ports(None, None)

    def test_close_ports_handles_already_closed(self):
        port = daemon.MockPort("test")
        port.close()
        daemon.close_ports(port)  # should not raise


class TestRunCommand(unittest.TestCase):
    """Test the run_command helper."""

    def test_run_command_success(self):
        result = daemon.run_command("true", "test-true")
        assert result is True

    def test_run_command_failure(self):
        result = daemon.run_command("false", "test-false")
        assert result is False

    def test_run_command_timeout(self):
        # Use a command that would hang, but run_command has a 15s timeout
        # We patch timeout to 0.1s for a fast test
        with patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("cmd", 15)):
            result = daemon.run_command("sleep 100", "test-timeout")
        assert result is False


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_grid_note_boundary_0(self):
        """Note 0 is a valid grid button."""
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        msg = note_on(0)
        ctrl.handle_hw_message(msg)
        assert msg in virt_out.sent

    def test_grid_note_boundary_63(self):
        """Note 63 is the last valid grid button."""
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        msg = note_on(63)
        ctrl.handle_hw_message(msg)
        assert msg in virt_out.sent

    def test_note_64_not_grid(self):
        """Note 64 is outside the grid range."""
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        msg = note_on(64)
        ctrl.handle_hw_message(msg)
        # Note 64 is not 0-63, not shift (122), so it falls through to
        # "other messages" and gets forwarded in Reaper mode
        assert msg in virt_out.sent

    def test_note_64_not_forwarded_in_system_mode(self):
        """Note 64 outside grid, not forwarded in system mode (other msg path)."""
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        virt_out.sent.clear()
        msg = note_on(64)
        ctrl.handle_hw_message(msg)
        assert msg not in virt_out.sent

    def test_reaper_led_note_outside_grid_forwarded_always(self):
        """Reaper messages for notes outside 0-63 are forwarded immediately."""
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        ctrl.enter_system_mode()
        hw_out.sent.clear()
        msg = note_on(100, velocity=5)
        ctrl.handle_virt_message(msg)
        # Not in 0-63 range, so should go through "other messages" path
        assert msg in hw_out.sent

    def test_non_note_virt_message_forwarded(self):
        """Non-note messages from Reaper (e.g. CC) are forwarded to hardware."""
        ctrl, hw_in, hw_out, virt_in, virt_out = make_controller()
        msg = cc(10, 64)
        hw_out.sent.clear()
        ctrl.handle_virt_message(msg)
        assert msg in hw_out.sent

    def test_stop_sets_running_false(self):
        ctrl, *_ = make_controller()
        assert ctrl.running is True
        ctrl.stop()
        assert ctrl.running is False


if __name__ == "__main__":
    unittest.main()
