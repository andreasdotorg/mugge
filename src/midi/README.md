# APCmini mk2 MIDI System Controller

A daemon that turns the Akai APCmini mk2 into a dual-purpose control surface
for the Pi 4B audio workstation. The controller acts as an exclusive MIDI proxy
between the hardware and Reaper, adding a system control layer to the grid
buttons while keeping faders permanently routed to Reaper.

## Architecture

```
APCmini mk2           daemon                Reaper
(hardware)     <-- ALSA MIDI -->     <-- virtual port -->
               bidirectional          "APCmini-Reaper"
               MIDI router
```

The daemon opens the APCmini mk2 exclusively, creates a virtual MIDI port
named `APCmini-Reaper`, and routes all traffic between the two. Reaper sees
only the virtual port. This gives the daemon full control over which messages
reach Reaper and which trigger system actions.

- **Faders** (CC 48-56): always forwarded to Reaper, regardless of grid mode.
- **Grid buttons** (notes 0-63): routed based on the current grid mode.
- **Shift button** (note 122): toggles the grid between Reaper mode and
  System mode.

## Dual-Mode Grid

The 8x8 grid has two modes, toggled by the Shift button:

**Reaper mode** (default) -- Grid buttons are forwarded to Reaper for mixer
control (mute, solo, arm, clip launch, etc.). LEDs are driven by Reaper.

**System mode** -- Grid buttons trigger system actions (mode switching,
window focus toggles). LEDs show the system layout. The daemon caches
Reaper's LED state and replays it on return to Reaper mode for
flicker-free transitions.

## State Machine

```
                        shift
    +--------+  ------>  +--------+
    | REAPER |           | SYSTEM |
    +--------+  <------  +--------+
        ^       shift        |
        |                    | destructive button press
        |       shift        v
        +-- <------  +------------+
                     | CONFIRMING |
                     +------------+
                         |     |
              2nd press  |     | timeout (3s) or different button
              (execute)  |     |
                         v     v
                       SYSTEM mode
```

- **REAPER**: Default state. Grid events go to Reaper.
- **SYSTEM**: Grid events trigger system actions. Auto-returns to REAPER
  after 7 seconds of inactivity (configurable).
- **CONFIRMING**: Destructive actions (dj_mode, live_mode) require a second
  press within 3 seconds. The pending button blinks amber/off. Pressing a
  different button cancels and processes the new button. Shift returns to
  REAPER.

## Usage

```bash
# Normal operation (requires APCmini mk2 connected)
python3 midi-system-controller.py --config /path/to/apcmini-mk2.yml

# Development/testing without hardware
python3 midi-system-controller.py --mock

# Verbose logging
python3 midi-system-controller.py --config /path/to/apcmini-mk2.yml -v
```

### Command-Line Options

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to YAML config file (default: `/etc/pi4-audio/midi/apcmini-mk2.yml`) |
| `--mock` | Use mock MIDI ports for development without hardware |
| `--verbose`, `-v` | Enable debug-level logging |

## Dependencies

```bash
pip install mido python-rtmidi pyyaml
```

- **mido** -- MIDI message handling and port I/O
- **python-rtmidi** -- MIDI backend for mido (ALSA on Linux)
- **pyyaml** -- YAML configuration parsing

## Configuration Reference

The config file is `configs/midi/apcmini-mk2.yml`. All keys:

### `device_name`

MIDI device name substring used to find the APCmini mk2 in the system's
MIDI port list. Case-insensitive match.

```yaml
device_name: "APC mini mk2"
```

### `virtual_port_name`

Name of the virtual MIDI port created for Reaper to connect to.

```yaml
virtual_port_name: "APCmini-Reaper"
```

### `timeouts`

| Key | Default | Description |
|-----|---------|-------------|
| `system_mode` | 7.0 | Seconds of inactivity before auto-return to Reaper mode |
| `confirmation` | 3.0 | Seconds to confirm a destructive action (second press) |

```yaml
timeouts:
  system_mode: 7.0
  confirmation: 3.0
```

### `fader_ccs`

List of MIDI CC numbers for the faders. These are always forwarded to
Reaper regardless of grid mode.

```yaml
fader_ccs: [48, 49, 50, 51, 52, 53, 54, 55, 56]
```

### `shift_note`

MIDI note number for the Shift button.

```yaml
shift_note: 122
```

### `grid_buttons.system_mode_map`

Maps grid button note numbers to system actions. Each entry has:

| Key | Required | Description |
|-----|----------|-------------|
| `action` | yes | Action name (must exist in `ACTION_DISPATCH`) |
| `confirm` | no | If `true`, requires two presses within confirmation timeout |

```yaml
grid_buttons:
  system_mode_map:
    0: { action: "dj_mode", confirm: true }
    1: { action: "live_mode", confirm: true }
    7: { action: "stats_toggle", confirm: false }
    8: { action: "mixxx_toggle", confirm: false }
    9: { action: "reaper_toggle", confirm: false }
```

Available actions:

| Action | Destructive | Description |
|--------|-------------|-------------|
| `dj_mode` | yes | Set PipeWire quantum 1024, launch Mixxx |
| `live_mode` | yes | Kill Mixxx, set PipeWire quantum 256 |
| `stats_toggle` | no | Toggle stats dashboard window focus |
| `mixxx_toggle` | no | Toggle Mixxx window focus |
| `reaper_toggle` | no | Toggle Reaper window focus |

### `led_colors`

LED color velocity values sent to the APCmini mk2 hardware.

| Key | Default | Description |
|-----|---------|-------------|
| `reaper_mode_shift` | 0 | Shift LED in Reaper mode (off) |
| `system_mode_shift` | 5 | Shift LED in System mode (amber) |
| `system_active` | 9 | Non-destructive system buttons (red) |
| `system_destructive` | 5 | Destructive system buttons (amber) |
| `system_inactive` | 1 | Inactive/unused system buttons (dim) |
| `confirm_blink` | [5, 0] | Alternating colors during confirmation (amber/off) |
| `confirm_success` | 21 | Flash after successful action (green) |

## Deployment

### systemd User Service

The daemon runs as a systemd user service on the Pi. The service file is at
`configs/systemd/user/midi-system-controller.service`.

Deploy:

```bash
# Copy the daemon script
cp src/midi/midi-system-controller.py /home/ela/bin/midi-system-controller.py
chmod +x /home/ela/bin/midi-system-controller.py

# Copy the config
sudo mkdir -p /etc/pi4-audio/midi
sudo cp configs/midi/apcmini-mk2.yml /etc/pi4-audio/midi/apcmini-mk2.yml

# Install the systemd service
mkdir -p ~/.config/systemd/user
cp configs/systemd/user/midi-system-controller.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable midi-system-controller
systemctl --user start midi-system-controller
```

The service starts after PipeWire and restarts on failure (3-second delay).
It uses the virtualenv at `/home/ela/audio-workstation-venv/`.

### USB Hot-Plug

If the APCmini mk2 is disconnected, the daemon catches the I/O error,
closes all ports, waits 2 seconds, and retries. Reconnecting the device
will restore normal operation without restarting the service.

## Running Tests

Tests mock the `mido` module and run without MIDI hardware or the mido
package installed.

```bash
# Run all tests
python3 src/midi/test_midi_daemon.py -v

# Or with pytest
pytest src/midi/test_midi_daemon.py -v
```

## Safety Features

- **Confirmation for destructive actions**: Mode switches (dj_mode,
  live_mode) require pressing the same button twice within 3 seconds.
  The button blinks during the confirmation window.
- **Auto-timeout**: System mode reverts to Reaper mode after 7 seconds
  of inactivity, preventing accidental system actions if the operator
  forgets to switch back.
- **Shift exits any state**: Pressing Shift always returns to Reaper mode,
  even from the Confirming state.
- **Faders always active**: Fader CCs are forwarded to Reaper in all modes,
  so the mixer never goes dead.
- **LED cache**: Reaper's LED state is cached during system mode and replayed
  on return, preventing flicker or lost LED states.
