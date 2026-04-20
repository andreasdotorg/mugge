# Mode Switching: DJ ↔ Live

Automated mode switching via the `pi4audio-mode-switch` command. One command
triggers the full transition: stop old app → GM mode change → start new app.

**Pre-requisite:** Audio stack must be verified before any mode switch.
See `docs/operations/pre-flight-checklist.md` Section 2.

**Safety:** Mode switching does NOT restart PipeWire and does NOT cause
USBStreamer transients. The audio path remains connected throughout — only
link topology and quantum change. D-063: gain gate stays closed during
transition. The operator opens the gate separately after verifying the
mode switch completed correctly.

---

## Quick Reference

```bash
# Switch to DJ mode (stops Reaper, starts Mixxx, quantum 1024)
pi4audio-mode-switch dj

# Switch to live mode (stops Mixxx, starts Reaper, quantum 256)
pi4audio-mode-switch live

# Switch to standby (stops any running app, no audio)
pi4audio-mode-switch standby
```

The web UI mode dropdown triggers the same sequence via the web-ui backend.

---

## What Happens Automatically

### DJ → Live

1. **Stop Mixxx** — `systemctl --user stop pi4audio-mixxx`
2. **GM set_mode live** — tears down DJ links (Mixxx→convolver), creates live
   links (Reaper→convolver, ada8200-in→Reaper, IEM), sets quantum to 256
3. **Start Reaper** — `systemctl --user start pi4audio-reaper` (FIFO/70)
4. GM reconciler creates remaining links once Reaper registers its JACK ports

### Live → DJ

1. **Stop Reaper** — `systemctl --user stop pi4audio-reaper`
2. **GM set_mode dj** — tears down live links, creates DJ links
   (Mixxx→convolver), sets quantum to 1024
3. **Start Mixxx** — `systemctl --user start pi4audio-mixxx` (FIFO/70)
4. GM reconciler creates remaining links once Mixxx registers its JACK ports

### → Standby

1. **Stop current app** (Mixxx or Reaper)
2. **GM set_mode standby** — tears down app links, closes gain gate (D-063),
   keeps convolver→USBStreamer links, sets quantum to 256

---

## Post-Switch Verification

After the mode switch completes, verify with the pre-flight checklist:

- DJ mode: `pre-flight-checklist.md` Section 3
- Live mode: `pre-flight-checklist.md` Section 4

Key checks:

```bash
# Verify mode and quantum
echo '{"cmd":"get_state"}' | nc -w2 127.0.0.1 4002 | head -c 200

# Verify links created
echo '{"cmd":"get_links"}' | nc -w2 127.0.0.1 4002 | head -c 200

# Check ERR baseline (use second sample)
pw-top -b -n 2
```

---

## Troubleshooting

### Links not created after mode switch

GraphManager creates links when both endpoints exist. After the mode switch,
the new application (Mixxx/Reaper) takes a few seconds to start and register
its JACK ports. The GM reconciler runs on a timer and will create links
automatically when the ports appear. Wait 5-10 seconds, then verify.

If links are still missing:

```bash
# Check GM state
echo '{"cmd":"get_state"}' | nc -w2 127.0.0.1 4002

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

- `docs/operations/pre-flight-checklist.md` — Full verification checklists per mode
- `docs/operations/safety.md` — Safety constraints
- US-085 — Clean GM-native app lifecycle (deferred, future)
- US-165 — Story tracking mode switching procedure
- US-157 — Mixxx systemd service
- US-162 — Reaper systemd service
