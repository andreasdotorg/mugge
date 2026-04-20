# Mode Switching: DJ ↔ Live

Mode switching is fully automatic. Sending a `set_mode` command to GraphManager
(JSON-RPC on port 4002) triggers the complete transition: graph reconciliation,
quantum change, and application lifecycle (stop old app, start new app).

**Pre-requisite:** Audio stack must be verified before any mode switch.
See `docs/operations/pre-flight-checklist.md` Section 2.

**Safety:** Mode switching does NOT restart PipeWire and does NOT cause
USBStreamer transients. The audio path remains connected throughout — only
link topology and quantum change. D-063: gain gate stays closed during
transition. The operator opens the gate separately after verifying the
mode switch completed correctly.

**Important:** Do not trigger rapid consecutive mode switches. The app
lifecycle runs on a background thread with no concurrency protection —
wait for one transition to complete before starting another.

---

## Quick Reference

From the web UI: use the mode dropdown (triggers `set_mode` via the web-ui backend).

From the command line:

```bash
# Switch to DJ mode (stops Reaper, starts Mixxx, quantum 1024)
echo '{"cmd":"set_mode","mode":"dj"}' | nc -w5 127.0.0.1 4002

# Switch to live mode (stops Mixxx, starts Reaper, quantum 256)
echo '{"cmd":"set_mode","mode":"live"}' | nc -w5 127.0.0.1 4002

# Switch to standby (stops any running app, no audio)
echo '{"cmd":"set_mode","mode":"standby"}' | nc -w5 127.0.0.1 4002
```

---

## What Happens Automatically (US-085)

When GM receives `set_mode`, it executes in order:

1. **Update mode** and set quantum (DJ=1024, Live/Standby=256)
2. **Reconcile links** — destroy old links, create new ones
3. **Send RPC reply** with epoch (caller can use `await_settled` to block)
4. **Emit ModeChanged event** to all connected TCP clients
5. **Transition apps** (background thread, does not block PW main loop):
   - Stop services not needed in the new mode
   - Start services needed for the new mode

### DJ → Live

- GM tears down DJ links (Mixxx→convolver), creates live links
  (Reaper→convolver, ada8200-in→Reaper, IEM), sets quantum to 256
- Background thread: stops `pi4audio-mixxx.service`, starts `pi4audio-reaper.service`
- GM reconciler creates remaining links once Reaper registers its JACK ports

### Live → DJ

- GM tears down live links, creates DJ links (Mixxx→convolver), sets quantum to 1024
- Background thread: stops `pi4audio-reaper.service`, starts `pi4audio-mixxx.service`
- GM reconciler creates remaining links once Mixxx registers its JACK ports

### → Standby

- GM tears down app links, closes gain gate (D-063), keeps convolver→USBStreamer
  links, sets quantum to 256
- Background thread: stops all managed services

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

GM reconciles links immediately on `set_mode`. If some links are missing,
the application (Mixxx/Reaper) may not have registered its JACK ports yet.
GM's reconciler timer retries periodically and will create app-specific
links when the ports appear.

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
- App lifecycle errors are logged by GM: `journalctl -u pi4audio-graph-manager -n 20 --no-pager`

---

## Cross-References

- `docs/operations/pre-flight-checklist.md` — Full verification checklists per mode
- `docs/operations/safety.md` — Safety constraints
- US-085 — GM-native app lifecycle management (this implementation)
- US-165 — Story tracking mode switching procedure
- US-157 — Mixxx systemd service
- US-162 — Reaper systemd service
