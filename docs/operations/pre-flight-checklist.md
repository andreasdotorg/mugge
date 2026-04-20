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

| Step | Action | Verify |
|------|--------|--------|
| 1.1 | Connect all audio cables (USBStreamer ADAT to ADA8200, speaker cables) | Physical inspection |
| 1.2 | Connect USB devices (USBStreamer, Hercules, APCmini, Nektar) | Physical inspection |
| 1.3 | Power on the Pi | Wait for SSH or VNC access |
| 1.4 | Verify audio stack (Section 2 below) | All Section 2 checks PASS |
| 1.5 | Verify gain attenuation (Section 5 below) | All gains at safe defaults |
| 1.6 | **Power on amplifiers** | Only after 1.4 and 1.5 pass |

**If the Pi needs a reboot after amps are on:** Power off amplifiers FIRST
(Section 7).

---

## 2. Audio Stack Verification

These checks confirm the core audio infrastructure is running correctly
after boot.

| # | Check | Command | Expected | Notes |
|---|-------|---------|----------|-------|
| 2.1 | PipeWire running | `systemctl --user is-active pipewire.service` | `active` | |
| 2.2 | WirePlumber running | `systemctl --user is-active wireplumber.service` | `active` | |
| 2.3 | PipeWire at FIFO/88 | `chrt -p $(pgrep -x pipewire)` | `SCHED_FIFO, priority 88` | F-020/F-291 fix |
| 2.4 | Filter-chain convolver loaded | `pw-cli ls Node \| grep convolver` | `pi4audio-convolver` present | |
| 2.5 | USBStreamer enumerated | `pw-cli ls Node \| grep -i usbstreamer` | USBStreamer playback node present | |
| 2.6 | GraphManager active | `systemctl --user is-active pi4audio-graph-manager.service` | `active` | Port 4002 |
| 2.7 | Gain nodes present | `pw-cli ls Node \| grep gain_` | 4 gain nodes: gain_left_hp, gain_right_hp, gain_sub1_lp, gain_sub2_lp | |
| 2.8 | Sample rate correct | `pw-metadata -n settings \| grep clock.rate` | `48000` | |

---

## 3. DJ Mode Checks

Run these after Section 2 passes, when operating in DJ/PA mode.

| # | Check | Command | Expected | Notes |
|---|-------|---------|----------|-------|
| 3.1 | Mixxx running | `systemctl --user is-active pi4audio-mixxx.service` | `active` | Auto-launched by labwc |
| 3.2 | Mixxx at FIFO/70 | `chrt -p $(pgrep -f '.mixxx-wrapped')` | `SCHED_FIFO, priority 70` | F-296 fix |
| 3.3 | pw-Mixxx threads at FIFO | `ps -eLo pid,tid,cls,rtprio,comm \| grep pw-Mixxx` | `FF` (FIFO), priority 70 | |
| 3.4 | GM DJ links established | `pw-link -l \| grep Mixxx` | Mixxx output linked to convolver inputs | |
| 3.5 | Quantum set to 1024 | `pw-metadata -n settings \| grep quantum` | `1024` | DJ mode quantum |
| 3.6 | Hercules controller detected | `aconnect -l \| grep -i hercules` or `lsusb \| grep -i hercules` | Hercules DJControl Mix Ultra listed | USB-MIDI (G-02) |
| 3.7 | Hercules MIDI mapping loaded | Check Mixxx preferences > Controllers | Hercules mapping active | |
| 3.8 | pw-top ERR baseline | `pw-top -b -n 2` (use second sample) | ERR rate < 2/min | First sample always zero |

---

## 4. Live Mode Checks

Run these after Section 2 passes, when operating in live vocal mode.

| # | Check | Command | Expected | Notes |
|---|-------|---------|----------|-------|
| 4.1 | Reaper started | `systemctl --user is-active pi4audio-reaper.service` | `active` | Manual start: `systemctl --user start pi4audio-reaper.service` |
| 4.2 | Reaper at FIFO/70 | `chrt -p $(pgrep -f reaper)` | `SCHED_FIFO, priority 70` | US-162 |
| 4.3 | GM live links established | `pw-link -l \| grep -E 'Reaper\|ada8200-in'` | Reaper and capture adapter linked | |
| 4.4 | Quantum set to 256 | `pw-metadata -n settings \| grep quantum` | `256` | Live mode — <25ms PA latency |
| 4.5 | ada8200-in capture present | `pw-cli ls Node \| grep ada8200-in` | ada8200-in node active | Vocal mic input |
| 4.6 | IEM routing confirmed | `pw-link -l \| grep -E 'ch[67]\|IEM'` | Reaper linked to USBStreamer ch 6-7 | Direct bypass, no convolver |
| 4.7 | Vocal mic gain check | Test vocal mic through Reaper | Signal visible in Reaper meters | No open mics until amps are on |
| 4.8 | pw-top ERR baseline | `pw-top -b -n 2` (use second sample) | ERR rate < 2/min | |

---

## 5. Safety Checks

**These checks are mandatory before powering on amplifiers.**

| # | Check | Command | Expected | Notes |
|---|-------|---------|----------|-------|
| 5.1 | Mains gain at -60 dB | `pw-cli enum-params <convolver-id> Props \| grep -A1 gain_left_hp` | Mult = 0.001 | D-063 gate closed default |
| 5.2 | Subs gain at -64 dB | `pw-cli enum-params <convolver-id> Props \| grep -A1 gain_sub1_lp` | Mult = 0.000631 | D-063 gate closed default |
| 5.3 | All 4 gains at defaults | Web UI Config tab | All sliders at production defaults | |
| 5.4 | No open mics before amps | Physical check | All mic cables disconnected or muted | Prevents feedback on amp power-on |
| 5.5 | Watchdog active | `echo '{"cmd":"status"}' \| nc -q1 127.0.0.1 4002` | Watchdog status: active | GraphManager watchdog (US-044) |
| 5.6 | D-031 protection filters | Verify convolver loaded FIR coefficients | Non-dirac FIR files in `/etc/pi4audio/coeffs/` | Driver protection via crossover FIR |

**After all safety checks pass:** Power on amplifiers. Open the audio gate
via web UI or `pw-cli` to set gains to production levels.

---

## 6. Monitoring

Ongoing checks during operation.

| # | Check | How | What to watch for |
|---|-------|-----|-------------------|
| 6.1 | pw-top ERR rate | `pw-top` (interactive) or `pw-top -b -n 2` | ERR rate > 2/min = investigate. Use second sample (first is always zero). |
| 6.2 | Web UI system tab | Browse to `https://mugge.local:8080` | Connection status, mode indicator, gain levels |
| 6.3 | CPU temperature | `cat /sys/class/thermal/thermal_zone0/temp` | Below 80000 (80C). Normal DJ: ~71C. |
| 6.4 | B/Q ratio | `pw-top` | Under 50% comfortable. Over 80% = danger (CPU pressure). |
| 6.5 | Quantum correct | `pw-top` Rate/Quantum column | 1024 for DJ, 256 for live |

**If ERR rate spikes during a gig:** Do NOT restart PipeWire (transient risk).
Check pw-top for which node is producing ERR. If Mixxx, check thread
scheduling. If USBStreamer, residual USB jitter (~1/min is acceptable).

---

## 7. Teardown Sequence

**Rule: Amplifiers power off FIRST, before Pi shutdown.**

| Step | Action | Why |
|------|--------|-----|
| 7.1 | Close audio gate (mute all gains) | Web UI MUTE button or `pw-cli` set Mult=0.0 |
| 7.2 | **Power off amplifiers** | Prevents transients from reaching speakers |
| 7.3 | Stop Mixxx/Reaper if running | `systemctl --user stop pi4audio-mixxx` / `pi4audio-reaper` |
| 7.4 | Shut down Pi | `sudo shutdown -h now` |
| 7.5 | Disconnect cables | Physical teardown |

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

- `docs/operations/safety.md` — Full safety operations manual
- D-009 — Cut-only correction, -0.5 dB safety margin
- D-013 — PREEMPT_RT mandatory for production
- D-031 — Driver protection filters
- D-063 — Audio gate (gain defaults at startup)
- F-020/F-291 — PipeWire FIFO/88 fix
- F-296 — Mixxx FIFO/70 fix
- US-044 — ALSA device lockout + watchdog
- US-167 — Story tracking this checklist
