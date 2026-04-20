# Pre-Flight Checklist for Gig Deployment

Operational checklist for the Pi 4B audio workstation. Run through this
before every gig. Each section must pass before moving to the next.

**Safety document:** `docs/operations/safety.md` is the authoritative
reference for all safety constraints referenced here.

---

## 1. Power-On Sequence

**Rule: Amplifiers power on LAST, after audio stack is verified.**

The USBStreamer produces full-scale transients when its audio stream is
interrupted (safety.md Section 1). Powering amps before the audio stack is
stable risks speaker damage.

- [ ] Connect all audio cables (USBStreamer ADAT to ADA8200, speaker cables)
- [ ] Connect USB devices (USBStreamer, Hercules, APCmini, Nektar)
- [ ] Power on the Pi — wait for SSH or VNC access
- [ ] Complete Section 2 (Audio Stack Verification) — all checks pass
- [ ] Complete Section 5 (Safety Checks) — all gains at safe defaults
- [ ] **Power on amplifiers** — only after all above checks pass

**If the Pi needs a reboot after amps are on:** Power off amplifiers FIRST
(Section 7).

---

## 2. Audio Stack Verification

Core audio infrastructure checks after boot.

- [ ] PipeWire running — `systemctl --user is-active pipewire.service` = `active`
- [ ] WirePlumber running — `systemctl --user is-active wireplumber.service` = `active`
- [ ] PipeWire at FIFO/88 — `chrt -p $(pgrep -x pipewire)` = `SCHED_FIFO, priority 88` (F-020/F-291)
- [ ] Filter-chain convolver loaded — `pw-cli ls Node | grep convolver` shows `pi4audio-convolver`
- [ ] USBStreamer enumerated — `pw-cli ls Node | grep -i usbstreamer` shows playback node
- [ ] GraphManager active — `systemctl --user is-active pi4audio-graph-manager.service` = `active`
- [ ] All 4 gain nodes present — `pw-cli ls Node | grep gain_` shows gain_left_hp, gain_right_hp, gain_sub1_lp, gain_sub2_lp
- [ ] Sample rate 48kHz — `pw-metadata -n settings | grep clock.rate` = `48000`

---

## 3. DJ Mode Checks

Run after Section 2 passes, when operating in DJ/PA mode.

- [ ] Mixxx running — `systemctl --user is-active pi4audio-mixxx.service` = `active` (auto-launched by labwc)
- [ ] Mixxx at FIFO/70 — `chrt -p $(pgrep -f '.mixxx-wrapped')` = `SCHED_FIFO, priority 70` (F-296)
- [ ] pw-Mixxx threads at FIFO — `ps -eLo pid,tid,cls,rtprio,comm | grep pw-Mixxx` shows `FF` priority 70
- [ ] GM DJ links established — `pw-link -l | grep Mixxx` shows Mixxx output linked to convolver inputs
- [ ] Quantum set to 1024 — `pw-metadata -n settings | grep quantum` = `1024`
- [ ] Hercules controller detected — `aconnect -l | grep -i hercules` or `lsusb | grep -i hercules`
- [ ] Hercules MIDI mapping loaded — check Mixxx preferences > Controllers
- [ ] pw-top ERR baseline — `pw-top -b -n 2` (use second sample, first is always zero) — ERR rate < 2/min

---

## 4. Live Mode Checks

Run after Section 2 passes, when operating in live vocal mode.

- [ ] Reaper started — `systemctl --user start pi4audio-reaper.service` then verify `is-active` = `active`
- [ ] Reaper at FIFO/70 — `chrt -p $(pgrep -f reaper)` = `SCHED_FIFO, priority 70` (US-162)
- [ ] GM live links established — `pw-link -l | grep -E 'Reaper|ada8200-in'` shows links
- [ ] Quantum set to 256 — `pw-metadata -n settings | grep quantum` = `256` (live mode, <25ms PA latency)
- [ ] ada8200-in capture present — `pw-cli ls Node | grep ada8200-in` shows active node (vocal mic input)
- [ ] IEM routing confirmed — `pw-link -l | grep -E 'ch[67]|IEM'` shows Reaper linked to USBStreamer ch 6-7 (direct bypass, no convolver)
- [ ] Vocal mic gain check — test vocal mic through Reaper, signal visible in meters (no open mics until amps on)
- [ ] pw-top ERR baseline — `pw-top -b -n 2` (use second sample) — ERR rate < 2/min

---

## 5. Safety Checks

**Mandatory before powering on amplifiers.**

- [ ] Mains gain at -60 dB — `pw-cli enum-params <convolver-id> Props | grep -A1 gain_left_hp` = Mult 0.001 (D-063 gate closed default)
- [ ] Subs gain at -64 dB — `pw-cli enum-params <convolver-id> Props | grep -A1 gain_sub1_lp` = Mult 0.000631 (D-063 gate closed default)
- [ ] All 4 gains at defaults — verify via web UI Config tab
- [ ] No open mics before amps — physical check, all mic cables disconnected or muted (prevents feedback on amp power-on)
- [ ] Watchdog active — `echo '{"cmd":"status"}' | nc -q1 127.0.0.1 4002` shows watchdog active (US-044)
- [ ] D-031 protection filters — verify non-dirac FIR files in `/etc/pi4audio/coeffs/` (driver protection via crossover FIR)

**After all safety checks pass:** Power on amplifiers. Open the audio gate
via web UI or `pw-cli` to set gains to production levels.

---

## 6. Monitoring

Ongoing checks during operation.

- [ ] pw-top ERR rate — `pw-top` (interactive) or `pw-top -b -n 2`. ERR > 2/min = investigate. First sample always zero.
- [ ] Web UI accessible — `https://mugge.local:8080` — connection status, mode indicator, gain levels
- [ ] CPU temperature — `cat /sys/class/thermal/thermal_zone0/temp` — below 80000 (80C). Normal DJ: ~71C.
- [ ] B/Q ratio — `pw-top` — under 50% comfortable, over 80% = danger (CPU pressure)
- [ ] Quantum correct — `pw-top` Rate/Quantum column — 1024 for DJ, 256 for live

**If ERR rate spikes during a gig:** Do NOT restart PipeWire (transient risk).
Check pw-top for which node is producing ERR. If Mixxx, check thread
scheduling. If USBStreamer, residual USB jitter (~1/min is acceptable).

---

## 7. Teardown Sequence

**Rule: Amplifiers power off FIRST, before Pi shutdown.**

- [ ] Close audio gate — web UI MUTE button or `pw-cli` set Mult=0.0 on all gain nodes
- [ ] **Power off amplifiers** — prevents transients from reaching speakers
- [ ] Stop Mixxx/Reaper — `systemctl --user stop pi4audio-mixxx` / `pi4audio-reaper`
- [ ] Shut down Pi — `sudo shutdown -h now`
- [ ] Disconnect cables — physical teardown

**Emergency shutdown:** If something sounds wrong, power off amplifiers
immediately (physical switch). Then diagnose. The Pi can be shut down
afterwards.

---

## Quick Reference: Channel Assignments

| Ch | Output | Input |
|----|--------|-------|
| 1 | Left wideband speaker | Vocal mic |
| 2 | Right wideband speaker | Spare mic/line |
| 3 | Subwoofer 1 | -- |
| 4 | Subwoofer 2 | -- |
| 5 | Engineer headphone L | -- |
| 6 | Engineer headphone R | -- |
| 7 | Singer IEM L | -- |
| 8 | Singer IEM R | -- |

## Quick Reference: Gain Defaults

| Node | Mult | dB | Purpose |
|------|------|----|---------|
| gain_left_hp | 0.001 | -60 | Left main |
| gain_right_hp | 0.001 | -60 | Right main |
| gain_sub1_lp | 0.000631 | -64 | Sub 1 |
| gain_sub2_lp | 0.000631 | -64 | Sub 2 |

## Quick Reference: Priority Hierarchy

| Process | Policy | Priority |
|---------|--------|----------|
| PipeWire | SCHED_FIFO | 88 |
| GraphManager | SCHED_FIFO | 80 |
| Mixxx / Reaper | SCHED_FIFO | 70 |
| Normal processes | SCHED_OTHER | 0 |

---

## Cross-References

- `docs/operations/safety.md` -- Full safety operations manual
- D-009 -- Cut-only correction, -0.5 dB safety margin
- D-013 -- PREEMPT_RT mandatory for production
- D-031 -- Driver protection filters
- D-063 -- Audio gate (gain defaults at startup)
- F-020/F-291 -- PipeWire FIFO/88 fix
- F-296 -- Mixxx FIFO/70 fix
- US-044 -- ALSA device lockout + watchdog
- US-167 -- Story tracking this checklist
