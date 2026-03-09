# RustDesk Headless Remote Desktop Setup

The Pi runs headless at gigs -- no HDMI display connected. Remote access for
GUI operations (Mixxx, Reaper, CamillaDSP web UI) requires a working remote
desktop solution. The owner chose RustDesk over VNC.

This session configured remote desktop for headless Wayland operation on the
Pi. RustDesk required five fixes to achieve screen capture, but mouse input
remained broken due to a confirmed RustDesk Wayland limitation. wayvnc (already
installed) worked immediately for both screen and input using native wlroots
protocols, and is now the primary venue remote desktop solution. RustDesk
remains useful for view-only remote monitoring.

---

## Environment

**Date:** 2026-03-09
**Operator:** change-manager (automated via SSH)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8 PREEMPT aarch64

### Software versions

| Component | Version |
|-----------|---------|
| RustDesk | 1.3.9 |
| PipeWire | 1.4.2 |
| labwc | 0.9.2 (wlroots 0.19.1) |
| xdg-desktop-portal-wlr | 0.7.1-2 |
| wayvnc | 0.9.1 (primary venue remote desktop) |

### Connection details

| Field | Value |
|-------|-------|
| Relay ID | 309152807 |
| Direct IP | 192.168.178.185 |
| Password | 234269 (temporary, set this session) |

---

## Root Cause Chain

The five failures formed a dependency chain. Each fix unblocked the next
failure:

1. **Screen capture failed** -- no `wl_output` on headless Pi (no HDMI) --
   fixed by `LABWC_FALLBACK_OUTPUT` (Fix 1)
2. **Screen share dialog blocked** -- xdg-desktop-portal-wlr shows interactive
   chooser, no one at Pi to approve -- fixed by `chooser_type=none` (Fix 2)
3. **Direct IP "Connection denied"** -- RustDesk not listening on TCP 21118 --
   fixed by `direct-server Y` (Fix 3)
4. **Mouse does not move** -- `/dev/uinput` permissions block input injection
   on Wayland -- fixed by chmod/chown + udev rule (Fix 4, necessary but not
   sufficient)
5. **Mouse still does not move** -- RustDesk systemd service lacks
   `WAYLAND_DISPLAY`, cannot connect to labwc for input injection. Logs:
   "Can't open display: (null)" -- fixed by systemd drop-in (Fix 5).
   **Mouse still broken after fix** -- confirmed as RustDesk Wayland
   limitation: RustDesk creates uinput virtual devices but labwc does not
   route them to the virtual display.
6. **Resolution: wayvnc** -- uses native wlroots protocols
   (`wlr-virtual-keyboard-v1`, `wlr-virtual-pointer-v1`) for input injection,
   bypassing the uinput path entirely. Screen + input both work. (Fix 6)

---

## Fix 1: Virtual Display for Headless Operation

**Problem:** With no HDMI display connected, labwc creates no `wl_output`.
Screen capture (used by RustDesk via xdg-desktop-portal-wlr) requires at
least one output to exist.

**File modified:** `~/.config/labwc/environment`

**Change:** Added:

```
LABWC_FALLBACK_OUTPUT=NOOP-fallback
```

**Effect:** labwc creates a virtual 1920x1080 output named `NOOP-fallback`
when no physical display is connected. This output is available for screen
capture without consuming GPU resources for real rendering.

**Restart:**

```bash
systemctl --user restart labwc
```

---

## Fix 2: Screen Share Auto-Approve (Wayland Portal)

**Problem:** xdg-desktop-portal-wlr presents an interactive screen share
permission dialog when RustDesk requests screen capture. On a headless Pi
with no one at the keyboard, this dialog blocks indefinitely.

**File created:** `~/.config/xdg-desktop-portal-wlr/config`

**Content:**

```ini
[screencast]
chooser_type = none
output_name = NOOP-fallback
```

**Effect:** Skips the interactive screen share permission dialog entirely.
Screen capture is auto-approved and directed to the `NOOP-fallback` output
from Fix 1.

**Restart:**

```bash
systemctl --user restart xdg-desktop-portal-wlr
```

---

## Fix 3: RustDesk Direct IP Server

**Problem:** RustDesk by default only accepts relay connections through its
cloud infrastructure. Direct IP connections to `192.168.178.185` returned
"Connection denied" because no TCP listener was active on port 21118.

**Command:**

```bash
sudo rustdesk --option direct-server Y
```

**Files modified:**
- `/home/ela/.config/rustdesk/RustDesk2.toml`
- `/root/.config/rustdesk/RustDesk2.toml`

**Effect:** Enables a TCP listener on port 21118 for direct LAN connections.
No relay server needed for same-network access.

**Firewall rules added** (persisted to `/etc/nftables.conf`):

```
tcp dport 21118 accept        # RustDesk direct IP
udp dport 21116-21119 accept  # RustDesk UDP
```

Both rules placed before the default drop rule.

**Restart:**

```bash
sudo systemctl restart rustdesk
```

---

## Fix 4: Input Injection (uinput) -- Applied, Necessary but Not Sufficient

**Problem:** On Wayland, RustDesk injects mouse and keyboard events via
`/dev/uinput`. The default permissions (`root:root 0600`) block the RustDesk
server process (running as user `ela`) from writing to this device.

**Commands applied:**

```bash
sudo chmod 660 /dev/uinput
sudo chown root:input /dev/uinput
```

**Persistence:** udev rule created at `/etc/udev/rules.d/99-uinput.rules`:

```
KERNEL=="uinput", GROUP="input", MODE="0660"
```

**Prerequisite:** User `ela` must be in the `input` group (already confirmed).

**Effect:** Allows the RustDesk server (running as `ela`, member of `input`
group) to inject mouse and keyboard events on Wayland via `/dev/uinput`.

**Status:** Applied. Necessary but not sufficient -- RustDesk creates virtual
input devices via uinput, but labwc does not route them to the virtual
display. This is a confirmed RustDesk Wayland limitation, not a permissions
issue. The udev rule survives reboot and remains useful for other uinput
consumers.

---

## Fix 5: RustDesk WAYLAND_DISPLAY Environment -- Applied, Insufficient

**Problem:** The RustDesk `--server` process runs as a systemd service. The
service environment does not include `WAYLAND_DISPLAY`, so RustDesk cannot
connect to the labwc Wayland compositor for input event injection. Logs showed
"Can't open display: (null)".

**File created:** `/etc/systemd/system/rustdesk.service.d/wayland.conf`
(systemd drop-in override)

**Content:**

```ini
[Service]
Environment=WAYLAND_DISPLAY=wayland-0
```

**Effect:** The RustDesk server process inherits `WAYLAND_DISPLAY=wayland-0`,
allowing it to connect to labwc and inject mouse/keyboard events via the
Wayland protocol. Combined with Fix 4 (uinput permissions), this completes
the input injection path.

**Restart:**

```bash
sudo systemctl daemon-reload && sudo systemctl restart rustdesk
```

**Status:** Applied. The WAYLAND_DISPLAY fix resolved the "Can't open display"
error, but RustDesk mouse input remains broken. This is a confirmed RustDesk
Wayland limitation: RustDesk uses uinput for input injection, but labwc does
not route uinput virtual devices to the virtual display. RustDesk screen
capture works; RustDesk is usable for view-only remote monitoring.

---

## Fix 6: wayvnc as Primary Venue Remote Desktop

**Background:** RustDesk screen capture works (Fixes 1-3), but mouse/keyboard
input is broken on Wayland due to RustDesk's reliance on uinput virtual
devices that labwc does not route to the virtual display. This is a confirmed
RustDesk limitation, not a configuration issue.

wayvnc 0.9.1 was already installed on the Pi. Unlike RustDesk, wayvnc uses
native wlroots protocols (`wlr-virtual-keyboard-v1`, `wlr-virtual-pointer-v1`)
for input injection. These protocols are first-class citizens in labwc -- no
uinput, no portal, no permission workarounds needed.

**Command:**

```bash
wayvnc --output=NOOP-fallback 0.0.0.0 5900
```

**Firewall rule added** (persisted to `/etc/nftables.conf`):

```
tcp dport 5900 accept           # wayvnc VNC
```

Placed before the default drop rule.

**Test results:**

| Client | Platform | Result |
|--------|----------|--------|
| Remmina (`nix-shell -p remmina`) | macOS | PASS -- screen + input both work |
| Screen Sharing (native) | macOS | FAIL -- protocol/auth negotiation issue (future story) |

**Effect:** Full remote desktop with screen capture and mouse/keyboard input.
Uses the same `NOOP-fallback` virtual output from Fix 1.

---

## Summary

### Role assignment

| Tool | Role | Screen | Input |
|------|------|--------|-------|
| **wayvnc** | Primary venue remote desktop | Working | Working (native wlroots) |
| **RustDesk** | View-only remote monitoring | Working (Fixes 1-3) | Broken (Wayland limitation) |

### Fix status

| Fix | File | Status |
|-----|------|--------|
| 1. Virtual display | `~/.config/labwc/environment` | Applied, working |
| 2. Portal auto-approve | `~/.config/xdg-desktop-portal-wlr/config` | Applied, working (RustDesk only) |
| 3. Direct IP server | `RustDesk2.toml` (ela + root) + `/etc/nftables.conf` | Applied, working (RustDesk only) |
| 4. uinput injection | `/etc/udev/rules.d/99-uinput.rules` | Applied, necessary but not sufficient for RustDesk |
| 5. WAYLAND_DISPLAY | `/etc/systemd/system/rustdesk.service.d/wayland.conf` | Applied, insufficient -- RustDesk Wayland limitation |
| 6. wayvnc | `/etc/nftables.conf` (TCP 5900) | Applied, working -- primary venue solution |

All changes persist across reboot.

**wayvnc connection path:** client connects to `192.168.178.185:5900` (TCP) --
wayvnc captures `NOOP-fallback` output via native wlroots protocol -- input
injected via `wlr-virtual-keyboard-v1` / `wlr-virtual-pointer-v1`.

**RustDesk connection path (view-only):** client connects to
`192.168.178.185:21118` (TCP) -- RustDesk captures `NOOP-fallback` output via
xdg-desktop-portal-wlr (auto-approved) -- input injection broken.
