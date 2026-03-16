#!/home/ela/audio-workstation-venv/bin/python3
"""MIDI system controller daemon for the APCmini mk2 (US-036).

Turns the APCmini mk2 into a dual-purpose device:
  - Faders (CC 48-56): always forwarded to Reaper via virtual MIDI port
  - Grid buttons (notes 0-63): routed based on grid mode
  - Shift button (note 122): toggles grid mode

Architecture:
  APCmini mk2 (hardware) <--ALSA MIDI--> daemon <--virtual port--> Reaper

  The daemon opens the APCmini mk2 exclusively, creates a virtual MIDI port
  named "APCmini-Reaper", and acts as a bidirectional MIDI router. Reaper
  connects to the virtual port. The daemon forwards fader CCs and (in Reaper
  mode) grid note events to Reaper, and forwards Reaper's LED updates back
  to the APCmini hardware.

State machine (3 states):
  REAPER   - default; grid -> Reaper, LEDs from Reaper
  SYSTEM   - shift toggle; grid -> system actions, amber/red LEDs
  CONFIRMING - within system mode; destructive action awaiting 2nd press (3s)

System actions (grid buttons in system mode):
  Immediate:  stats_toggle, mixxx_toggle, reaper_toggle
  Confirmed:  dj_mode, live_mode (destructive - quantum change + app start/stop)

Usage:
  python3 midi-system-controller.py [--config /path/to/apcmini-mk2.yml] [--mock]

  --mock uses mock MIDI ports for development/testing on machines without
  hardware (e.g., macOS).

Dependencies:
  pip install mido python-rtmidi pyyaml
"""

import argparse
import logging
import subprocess
import sys
import time

import mido
import yaml

log = logging.getLogger("midi-system-controller")

# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------

STATE_REAPER = "reaper"
STATE_SYSTEM = "system"
STATE_CONFIRMING = "confirming"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(path):
    """Load and return the YAML configuration dict."""
    with open(path) as f:
        return yaml.safe_load(f)


DEFAULT_CONFIG = {
    "device_name": "APC mini mk2",
    "virtual_port_name": "APCmini-Reaper",
    "timeouts": {"system_mode": 7.0, "confirmation": 3.0},
    "fader_ccs": [48, 49, 50, 51, 52, 53, 54, 55, 56],
    "grid_buttons": {"system_mode_map": {}},
    "shift_note": 122,
    "led_colors": {
        "reaper_mode_shift": 0,
        "system_mode_shift": 5,
        "system_active": 9,
        "system_destructive": 5,
        "system_inactive": 1,
        "confirm_blink": [5, 0],
        "confirm_success": 21,
    },
}


# ---------------------------------------------------------------------------
# Mock MIDI ports (for --mock development mode)
# ---------------------------------------------------------------------------

class MockPort:
    """Minimal mock MIDI port for development without hardware."""

    def __init__(self, name="mock"):
        self.name = name
        self._closed = False

    def send(self, msg):
        log.debug("mock-send [%s]: %s", self.name, msg)

    def poll(self):
        return None

    def close(self):
        self._closed = True

    @property
    def closed(self):
        return self._closed


# ---------------------------------------------------------------------------
# System actions
# ---------------------------------------------------------------------------

def run_command(cmd, description):
    """Run a shell command, logging success or failure."""
    log.info("action: %s — running: %s", description, cmd)
    try:
        subprocess.run(cmd, shell=True, check=True, timeout=15,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log.info("action: %s — success", description)
        return True
    except subprocess.CalledProcessError as e:
        log.error("action: %s — failed (rc=%d): %s",
                  description, e.returncode, e.stderr.decode(errors="replace").strip())
        return False
    except subprocess.TimeoutExpired:
        log.error("action: %s — timed out after 15s", description)
        return False


def action_dj_mode():
    """Switch to DJ mode: set quantum 1024, launch Mixxx."""
    run_command("pw-metadata -n settings 0 clock.force-quantum 1024",
                "set quantum 1024")
    run_command("start-mixxx.sh", "launch Mixxx")


def action_live_mode():
    """Switch to Live mode: kill Mixxx, set quantum 256."""
    run_command("pkill -f mixxx || true", "stop Mixxx")
    run_command("pw-metadata -n settings 0 clock.force-quantum 256",
                "set quantum 256")


def action_stats_toggle():
    """Toggle the stats dashboard (D-020) browser window."""
    run_command(
        'wlrctl window focus app_id:chromium || wlrctl window minimize app_id:chromium',
        "toggle stats view")


def action_mixxx_toggle():
    """Toggle the Mixxx window focus."""
    run_command(
        'wlrctl window focus app_id:mixxx || wlrctl window minimize app_id:mixxx',
        "toggle Mixxx view")


def action_reaper_toggle():
    """Toggle the Reaper window focus."""
    run_command(
        'wlrctl window focus app_id:reaper || wlrctl window minimize app_id:reaper',
        "toggle Reaper view")


ACTION_DISPATCH = {
    "dj_mode": action_dj_mode,
    "live_mode": action_live_mode,
    "stats_toggle": action_stats_toggle,
    "mixxx_toggle": action_mixxx_toggle,
    "reaper_toggle": action_reaper_toggle,
}


# ---------------------------------------------------------------------------
# Controller daemon
# ---------------------------------------------------------------------------

class MidiSystemController:
    """APCmini mk2 system controller daemon.

    Opens the hardware MIDI device, creates a virtual MIDI port for Reaper,
    and runs the main event loop routing messages between them.
    """

    def __init__(self, config, hw_in, hw_out, virt_in, virt_out):
        self.cfg = config
        self.hw_in = hw_in
        self.hw_out = hw_out
        self.virt_in = virt_in
        self.virt_out = virt_out

        self.grid_mode = STATE_REAPER
        self.pending_action = None
        self.pending_note = None
        self.confirm_deadline = 0.0
        self.system_entered_at = 0.0
        self.blink_phase = 0
        self.last_blink_time = 0.0

        # LED cache: stores Reaper's LED state for flicker-free mode transitions
        self.reaper_led_cache = {}

        # Parse system mode map: convert string keys to int
        raw_map = self.cfg.get("grid_buttons", {}).get("system_mode_map", {})
        self.system_map = {}
        for key, val in raw_map.items():
            self.system_map[int(key)] = val

        self.fader_ccs = set(self.cfg.get("fader_ccs", []))
        self.shift_note = self.cfg.get("shift_note", 122)
        self.colors = self.cfg.get("led_colors", DEFAULT_CONFIG["led_colors"])
        self.timeouts = self.cfg.get("timeouts", DEFAULT_CONFIG["timeouts"])

        self.running = True

    # -- LED helpers --------------------------------------------------------

    def set_led(self, note, color):
        """Send a note-on to the hardware to set an LED color."""
        self.hw_out.send(mido.Message("note_on", note=note, velocity=color))

    def paint_reaper_mode(self):
        """Restore Reaper LED state from cache, set shift LED off."""
        for note, color in self.reaper_led_cache.items():
            self.set_led(note, color)
        # Clear any system-mode LEDs that are not in the Reaper cache
        for note in self.system_map:
            if note not in self.reaper_led_cache:
                self.set_led(note, 0)
        self.set_led(self.shift_note, self.colors["reaper_mode_shift"])

    def paint_system_mode(self):
        """Paint system mode LEDs: destructive buttons amber, others dim."""
        for note, entry in self.system_map.items():
            if entry.get("confirm"):
                self.set_led(note, self.colors["system_destructive"])
            else:
                self.set_led(note, self.colors["system_active"])
        self.set_led(self.shift_note, self.colors["system_mode_shift"])

    def flash_success(self, note):
        """Brief green flash on a button after a successful action."""
        self.set_led(note, self.colors["confirm_success"])

    # -- State transitions --------------------------------------------------

    def enter_reaper_mode(self):
        """Transition to Reaper mode."""
        log.info("mode -> REAPER")
        self.grid_mode = STATE_REAPER
        self.pending_action = None
        self.pending_note = None
        self.paint_reaper_mode()

    def enter_system_mode(self):
        """Transition to System mode."""
        log.info("mode -> SYSTEM")
        self.grid_mode = STATE_SYSTEM
        self.system_entered_at = time.monotonic()
        self.pending_action = None
        self.pending_note = None
        self.paint_system_mode()

    def enter_confirming(self, note, action_name):
        """Transition to Confirming state for a destructive action."""
        log.info("mode -> CONFIRMING (%s, note %d)", action_name, note)
        self.grid_mode = STATE_CONFIRMING
        self.pending_action = action_name
        self.pending_note = note
        self.confirm_deadline = time.monotonic() + self.timeouts["confirmation"]
        self.blink_phase = 0
        self.last_blink_time = time.monotonic()
        # Start blink on the pending button
        blink_colors = self.colors["confirm_blink"]
        self.set_led(note, blink_colors[0])

    # -- Message handling ---------------------------------------------------

    def handle_hw_message(self, msg):
        """Process a MIDI message from the APCmini mk2 hardware."""
        # Faders: always forward to Reaper, regardless of mode
        if msg.type == "control_change" and msg.control in self.fader_ccs:
            self.virt_out.send(msg)
            return

        # Shift button: toggle grid mode (on note_on only)
        if msg.type == "note_on" and msg.note == self.shift_note and msg.velocity > 0:
            if self.grid_mode == STATE_REAPER:
                self.enter_system_mode()
            else:
                self.enter_reaper_mode()
            return

        # Grid note events
        if msg.type in ("note_on", "note_off") and 0 <= msg.note <= 63:
            if self.grid_mode == STATE_REAPER:
                # Forward to Reaper
                self.virt_out.send(msg)

            elif self.grid_mode == STATE_SYSTEM:
                # Only act on note_on
                if msg.type == "note_on" and msg.velocity > 0:
                    self.handle_system_button(msg.note)

            elif self.grid_mode == STATE_CONFIRMING:
                if msg.type == "note_on" and msg.velocity > 0:
                    self.handle_confirm_button(msg.note)
            return

        # Other messages (aftertouch, etc.): forward to Reaper in Reaper mode
        if self.grid_mode == STATE_REAPER:
            self.virt_out.send(msg)

    def handle_system_button(self, note):
        """Handle a grid button press in System mode."""
        entry = self.system_map.get(note)
        if entry is None:
            log.debug("system mode: unmapped note %d, ignoring", note)
            return

        action_name = entry["action"]
        needs_confirm = entry.get("confirm", False)

        if needs_confirm:
            self.enter_confirming(note, action_name)
        else:
            self.execute_action(action_name, note)

    def handle_confirm_button(self, note):
        """Handle a grid button press in Confirming state."""
        if note == self.pending_note:
            # Second press on same button: confirmed
            log.info("confirmed: %s", self.pending_action)
            self.execute_action(self.pending_action, note)
        else:
            # Different button: cancel confirmation, treat as new system press
            log.info("confirmation cancelled (different button %d)", note)
            self.grid_mode = STATE_SYSTEM
            self.system_entered_at = time.monotonic()
            self.paint_system_mode()
            self.handle_system_button(note)

    def execute_action(self, action_name, note):
        """Execute a system action and return to system mode briefly."""
        func = ACTION_DISPATCH.get(action_name)
        if func is None:
            log.error("unknown action: %s", action_name)
            return

        func()
        self.flash_success(note)
        # Brief pause to show the green flash, then back to system mode
        # (The main loop will repaint on the next timer tick)
        self.grid_mode = STATE_SYSTEM
        self.system_entered_at = time.monotonic()
        self.pending_action = None
        self.pending_note = None

    def handle_virt_message(self, msg):
        """Process a MIDI message from Reaper (via the virtual port)."""
        # LED updates from Reaper: cache them
        if msg.type == "note_on" and 0 <= msg.note <= 63:
            self.reaper_led_cache[msg.note] = msg.velocity
            # Only forward to hardware if we are in Reaper mode
            if self.grid_mode == STATE_REAPER:
                self.hw_out.send(msg)
            return

        # Other messages from Reaper: forward to hardware
        self.hw_out.send(msg)

    # -- Timer checks -------------------------------------------------------

    def check_timeouts(self):
        """Check and handle system mode and confirmation timeouts."""
        now = time.monotonic()

        if self.grid_mode == STATE_SYSTEM:
            elapsed = now - self.system_entered_at
            if elapsed >= self.timeouts["system_mode"]:
                log.info("system mode timeout (%.1fs), reverting to Reaper", elapsed)
                self.enter_reaper_mode()

        elif self.grid_mode == STATE_CONFIRMING:
            if now >= self.confirm_deadline:
                log.info("confirmation timeout for %s, reverting to system mode",
                         self.pending_action)
                self.grid_mode = STATE_SYSTEM
                self.system_entered_at = time.monotonic()
                self.pending_action = None
                self.pending_note = None
                self.paint_system_mode()
            else:
                # Blink the pending button LED
                if now - self.last_blink_time >= 0.3:
                    blink_colors = self.colors["confirm_blink"]
                    self.blink_phase = 1 - self.blink_phase
                    self.set_led(self.pending_note, blink_colors[self.blink_phase])
                    self.last_blink_time = now

    # -- Main loop ----------------------------------------------------------

    def run(self):
        """Main event loop: poll MIDI input + 100ms timer for timeouts."""
        log.info("starting main loop, grid_mode=%s", self.grid_mode)
        self.paint_reaper_mode()

        while self.running:
            # Poll hardware input
            msg = self.hw_in.poll()
            if msg is not None:
                self.handle_hw_message(msg)
                continue  # process messages as fast as they arrive

            # Poll virtual port input (from Reaper)
            msg = self.virt_in.poll()
            if msg is not None:
                self.handle_virt_message(msg)
                continue

            # No messages: check timeouts and sleep briefly
            self.check_timeouts()
            time.sleep(0.01)  # 10ms poll interval, low CPU usage

    def stop(self):
        """Signal the main loop to stop."""
        self.running = False


# ---------------------------------------------------------------------------
# Port opening with reconnect
# ---------------------------------------------------------------------------

def find_hw_port(device_name, port_type):
    """Find a MIDI port matching device_name.

    port_type is 'input' or 'output'. Returns the port name string or None.
    """
    if port_type == "input":
        names = mido.get_input_names()
    else:
        names = mido.get_output_names()
    for name in names:
        if device_name.lower() in name.lower():
            return name
    return None


def open_ports(config, mock=False):
    """Open hardware and virtual MIDI ports.

    Returns (hw_in, hw_out, virt_in, virt_out).
    In mock mode, returns MockPort instances.
    """
    if mock:
        log.info("mock mode: using mock MIDI ports")
        return (MockPort("hw-in"), MockPort("hw-out"),
                MockPort("virt-in"), MockPort("virt-out"))

    device_name = config["device_name"]
    virt_name = config["virtual_port_name"]

    hw_in_name = find_hw_port(device_name, "input")
    if hw_in_name is None:
        raise IOError(f"hardware input port not found: {device_name}")
    hw_out_name = find_hw_port(device_name, "output")
    if hw_out_name is None:
        raise IOError(f"hardware output port not found: {device_name}")

    log.info("opening hardware input: %s", hw_in_name)
    hw_in = mido.open_input(hw_in_name)
    log.info("opening hardware output: %s", hw_out_name)
    hw_out = mido.open_output(hw_out_name)

    log.info("opening virtual port: %s", virt_name)
    virt_in = mido.open_input(virt_name, virtual=True)
    virt_out = mido.open_output(virt_name, virtual=True)

    return hw_in, hw_out, virt_in, virt_out


def close_ports(*ports):
    """Close MIDI ports, ignoring errors."""
    for port in ports:
        try:
            if port and not port.closed:
                port.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="APCmini mk2 MIDI system controller daemon (US-036)")
    parser.add_argument("--config", type=str,
                        default="/etc/pi4-audio/midi/apcmini-mk2.yml",
                        help="Path to YAML config file")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock MIDI ports (for development without hardware)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # Load config
    try:
        config = load_config(args.config)
        log.info("loaded config from %s", args.config)
    except FileNotFoundError:
        log.warning("config file not found: %s — using defaults", args.config)
        config = DEFAULT_CONFIG

    # Main loop with reconnect on hardware disconnect
    while True:
        hw_in = hw_out = virt_in = virt_out = None
        try:
            hw_in, hw_out, virt_in, virt_out = open_ports(config, mock=args.mock)
            controller = MidiSystemController(
                config, hw_in, hw_out, virt_in, virt_out)
            controller.run()
        except KeyboardInterrupt:
            log.info("interrupted, shutting down")
            break
        except IOError as e:
            log.error("MIDI I/O error: %s — retrying in 2s", e)
            close_ports(hw_in, hw_out, virt_in, virt_out)
            time.sleep(2)
            continue
        except Exception:
            log.exception("unexpected error — retrying in 2s")
            close_ports(hw_in, hw_out, virt_in, virt_out)
            time.sleep(2)
            continue
        finally:
            close_ports(hw_in, hw_out, virt_in, virt_out)


if __name__ == "__main__":
    main()
