# Manual Mode Switching: DJ ↔ Live

Manual procedure for switching between DJ/PA mode and live vocal mode.

Per owner decision (US-085 deferred), mode switching is a manual operator
workflow. The operator stops/starts applications and triggers GraphManager
mode transitions. Automated switching is a future nice-to-have.

**Pre-requisite:** Audio stack must be verified before any mode switch.
See `docs/operations/pre-flight-checklist.md` Section 2.

**Safety:** Mode switching does NOT restart PipeWire and does NOT cause
USBStreamer transients. The audio path remains connected throughout -- only
link topology and quantum change. Amplifiers can stay on, but should be at
a safe level during the switch. Gain defaults (0.001 mains, 0.000631 subs)
prevent transient damage, but operator awareness is important -- there will
be a brief period with no application producing audio between stop and start.

---

## DJ → Live

### Step 1: Stop Mixxx

```bash
systemctl --user stop pi4audio-mixxx
```

Verify:

```bash
systemctl --user is-active pi4audio-mixxx.service
# Expected: inactive
```

### Step 2: Trigger GM Live Mode

Via web UI mode dropdown, or via HTTP RPC:

```bash
curl -X POST http://localhost:4002/mode/live
```

GraphManager will:
- Tear down DJ links (Mixxx → convolver)
- Create live links (Reaper → convolver, ada8200-in → Reaper)
- Set quantum to 256 (`pw-metadata -n settings 0 clock.force-quantum 256`)
- Create ada8200-in capture adapter node (US-158)

### Step 3: Start Reaper

```bash
systemctl --user start pi4audio-reaper
```

Verify:

```bash
systemctl --user is-active pi4audio-reaper.service
# Expected: active

chrt -p $(pgrep -f reaper)
# Expected: SCHED_FIFO, priority 70
```

### Step 4: Verify Live Mode

- [ ] Quantum is 256 — `pw-metadata -n settings | grep quantum`
- [ ] ada8200-in node present — `pw-cli ls Node | grep ada8200-in`
- [ ] GM live links established — `pw-link -l | grep -E 'Reaper|ada8200-in'`
- [ ] IEM routing to ch 6-7 — `pw-link -l | grep -E 'ch[67]|IEM'` (direct bypass, no convolver)
- [ ] pw-top ERR baseline — `pw-top -b -n 2` (use second sample) — ERR < 2/min

For the full live mode verification suite, see `pre-flight-checklist.md` Section 4.

---

## Live → DJ

### Step 1: Stop Reaper

```bash
systemctl --user stop pi4audio-reaper
```

Verify:

```bash
systemctl --user is-active pi4audio-reaper.service
# Expected: inactive
```

### Step 2: Trigger GM DJ Mode

Via web UI mode dropdown, or via HTTP RPC:

```bash
curl -X POST http://localhost:4002/mode/dj
```

GraphManager will:
- Tear down live links (Reaper → convolver, ada8200-in → Reaper)
- Create DJ links (Mixxx → convolver)
- Set quantum to 1024 (`pw-metadata -n settings 0 clock.force-quantum 1024`)
- Destroy ada8200-in capture adapter node

### Step 3: Start Mixxx

```bash
systemctl --user start pi4audio-mixxx
```

Verify:

```bash
systemctl --user is-active pi4audio-mixxx.service
# Expected: active

chrt -p $(pgrep -f '.mixxx-wrapped')
# Expected: SCHED_FIFO, priority 70
```

### Step 4: Verify DJ Mode

- [ ] Quantum is 1024 — `pw-metadata -n settings | grep quantum`
- [ ] GM DJ links established — `pw-link -l | grep Mixxx` (Mixxx output linked to convolver inputs)
- [ ] Hercules controller detected — `aconnect -l | grep -i hercules` or `lsusb | grep -i hercules`
- [ ] pw-Mixxx threads at FIFO — `ps -eLo pid,tid,cls,rtprio,comm | grep pw-Mixxx` shows priority 70
- [ ] pw-top ERR baseline — `pw-top -b -n 2` (use second sample) — ERR < 2/min

For the full DJ mode verification suite, see `pre-flight-checklist.md` Section 3.

---

## Troubleshooting

### Links not created after GM mode switch

GraphManager may need the target application running before it can create
links. If links are missing after step 2, wait for the application to start
(step 3), then check again. GM reconciles links on node appearance events.

If links are still missing:

```bash
# Check GM status
echo '{"cmd":"status"}' | nc -q1 127.0.0.1 4002

# Manual link creation (fallback)
pw-link <source-port> <sink-port>
```

### Quantum did not change

Verify GM set the quantum:

```bash
pw-metadata -n settings | grep quantum
```

If incorrect, set manually:

```bash
# DJ mode
pw-metadata -n settings 0 clock.force-quantum 1024

# Live mode
pw-metadata -n settings 0 clock.force-quantum 256
```

### Application fails to start

Check journal for errors:

```bash
journalctl --user -u pi4audio-mixxx -n 20 --no-pager
journalctl --user -u pi4audio-reaper -n 20 --no-pager
```

Common causes:
- PipeWire not ready — ExecStartPre probe should handle this, but check
  `pw-cli info 0` manually
- Display not available — Mixxx and Reaper need the labwc Wayland session

---

## Cross-References

- `docs/operations/pre-flight-checklist.md` -- Full verification checklists per mode
- `docs/operations/safety.md` -- Safety constraints
- US-085 -- Automated mode switching (deferred)
- US-165 -- Story tracking this procedure
- US-158 -- GM manages ada8200-in lifecycle per mode
- US-162 -- Reaper systemd service
- US-157 -- Mixxx systemd service
