# HOWTO: Venue Setup

This is the operational checklist for setting up the mugge audio workstation at a
venue. It covers everything from power-on through verified room correction and
readiness to perform. The audience is the operator standing at the rig -- it is
meant to be read sequentially, top to bottom, one step at a time.

The web UI runs at `https://mugge.local:8080` (or the Pi's IP on port 8080).
All steps that say "open" or "go to" refer to tabs in this interface.

---

## Phase 1: Physical Setup

These steps happen before the Pi is powered on.

1. Position the flight case. Run power to the case. Do NOT turn on the
   amplifier yet.

2. Connect the speaker cables to the ADA8200 outputs:
   - Channel 1: Left wideband speaker
   - Channel 2: Right wideband speaker
   - Channel 3: Subwoofer 1
   - Channel 4: Subwoofer 2
   - Channels 5-6: Engineer headphones
   - Channels 7-8: Singer in-ear monitors (live mode only)

3. Verify the ADAT optical cable between USBStreamer and ADA8200.

4. Connect the UMIK-1 measurement microphone to a USB port on the Pi. Do not
   place it at the measurement position yet -- it will be needed during the
   pre-flight checks but should stay out of the way until Phase 3.

5. Connect any MIDI controllers (Hercules DJControl, APCmini mk2, Nektar SE25).

---

## Phase 2: Power-On and System Check

6. Power on the Pi. Wait for the boot sequence to complete (approximately 30
   seconds). The web UI auto-starts as a systemd service.

7. Open a browser and go to `https://mugge.local:8080`. You should see the
   Dashboard tab with level meters and the spectrum analyzer. Confirm the
   status bar at the top shows PipeWire running and the DSP load indicator
   is present.

8. Go to the **Config** tab. Confirm the current quantum value is displayed.
   For DJ mode set it to 1024 (press the 1024 button and Apply). For live
   vocal mode set it to 256.

9. Check the gain values. The Config tab shows per-channel gain sliders for
   the four speaker channels (left, right, sub 1, sub 2). Production defaults
   are deep attenuation (around -60 dB for mains, -64 dB for subs). Do not
   change these until measurement is complete.

10. Turn on the amplifier. Because the gain nodes are at deep attenuation and
    no audio application is running, the speakers are silent. This is the safe
    moment to power the amp.

---

## Phase 3: Speaker Profile Selection

The system needs to know which speakers are connected so it can generate
appropriate crossover and protection filters.

11. Go to the **Config** tab, Speaker Configuration section. You will see a
    list of available speaker profiles. Each profile defines a topology (2-way,
    3-way), crossover frequency, and references to speaker identity files that
    contain the driver specifications.

12. Select the profile that matches your current speaker setup. For the
    standard PA rig this is typically `2way-80hz-sealed` (self-built wideband
    mains with sealed 15" subs at 80 Hz crossover). Review the profile
    summary: topology, crossover frequency, number of channels, and the
    speaker identities it references.

13. Press **Activate**. The system performs the D-053 safety flow:
    - Mute all gain nodes (Mult = 0.0)
    - Switch the PipeWire filter-chain configuration to match the profile
    - Ramp gain back up to the configured production values

    The status bar will briefly show MUTED during the transition. If anything
    goes wrong during activation, the system stays muted and reports the error.

14. After activation, confirm in the Config tab that the active profile name
    matches what you selected and the channel assignments look correct.

If no existing profile matches your speakers, you can create a new one from
the Config tab's speaker configuration section. This requires defining speaker
identities first (driver specifications) and then building a profile that
references them. For a first-time venue with unfamiliar speakers, do this
before the day of the event.

---

## Phase 4: Pre-Flight and Measurement

This is the room correction workflow. It measures each speaker channel in the
room, computes correction filters, and deploys them -- all from the web UI.

### 4a. Position the Microphone

15. Place the UMIK-1 at the primary measurement position. This is typically
    center of the dance floor (DJ mode) or center of the audience seating
    area (live mode), at ear height. Use a microphone stand. The mic should
    point straight up (omnidirectional pickup, but the calibration file
    assumes 0-degree incidence).

### 4b. Pre-Flight Checks

16. Go to the **Measure** tab. The room correction wizard occupies this tab.
    The first screen is the pre-flight checklist. The system runs four
    automated checks:

    - **UMIK-1 detected:** Confirms the measurement microphone is connected and
      its calibration file is loaded. The calibration serial number is displayed
      for verification.
    - **GraphManager mode:** Confirms the GraphManager is running and in a mode
      compatible with measurement. If it is in the wrong mode, the wizard will
      indicate what needs to change.
    - **Profile validated:** Confirms the active speaker profile passes schema
      and constraint validation (all referenced identities exist, channel
      assignments are within the 8-channel budget, mandatory HPF values are
      declared).
    - **Amplifier status:** This is always a manual check. The wizard shows a
      checkbox for you to confirm that amplifiers are on and at a safe level.
      The system cannot verify this automatically.

    All four checks must pass (green) before the wizard allows you to proceed.
    If any automated check fails, the wizard shows what is wrong and how to
    fix it.

17. Confirm the amplifier checkbox. Press **Start Measurement**.

### 4c. Gain Calibration

18. The wizard enters gain calibration. It plays pink noise through each
    speaker channel individually at -20 dBFS (the signal generator's immutable
    safety cap) and reads the UMIK-1 level. This step ensures the measurement
    level is appropriate -- loud enough for good signal-to-noise ratio but
    safe for the drivers.

    The calibration display shows the measured SPL for each channel. If the
    level is too low (microphone too far from the speaker, or amplifier gain
    too low), the wizard warns you. Adjust the amplifier gain or microphone
    position as needed.

    This step takes a few seconds per channel.

### 4d. Sweep Measurements

19. The wizard now measures each speaker channel. For each channel, it plays a
    logarithmic sweep (20 Hz to 20 kHz) and records the response through the
    UMIK-1. The sweep uses 1/f energy distribution so that low frequencies get
    proportionally more measurement time, improving the signal-to-noise ratio
    where room modes are most problematic.

    A progress bar tracks the measurement. Each sweep takes several seconds.
    The wizard measures one channel at a time (the signal generator enforces
    single-channel isolation -- all other channels are silent).

20. For spatial averaging, the wizard prompts you to move the UMIK-1 to a
    slightly different position (within about half a meter of the original)
    and repeats the sweep set. Three to five positions are typical. Spatial
    averaging makes the correction effective over a wider listening area
    rather than optimizing for a single point.

    The wizard tracks which positions have been measured and shows a count.
    After the minimum number of positions, a "Finish Positions" button
    appears.

### 4e. Filter Generation

21. After all sweeps are complete, the wizard enters the filter generation
    phase. The pipeline runs automatically:

    - **Deconvolution:** Each recorded sweep is deconvolved against the
      reference sweep to extract the room's impulse response per channel per
      position.
    - **Spatial averaging:** The impulse responses from different microphone
      positions are averaged in the frequency domain. This smooths out
      position-dependent artifacts.
    - **Target curve application:** The configured target curve (flat, Harman,
      or PA-optimized) is applied. The target is always implemented as
      relative attenuation, never as boost.
    - **Inversion and D-009 enforcement:** The averaged response is inverted to
      compute the correction filter. The D-009 safety rule is enforced: every
      frequency bin is clamped to -0.5 dB maximum. No boost, ever.
    - **Crossover integration:** The correction filter is convolved with the
      crossover shape (highpass for mains, lowpass for subs) from the active
      speaker profile. This produces a single combined filter per channel.
    - **Minimum-phase synthesis:** The combined filter is converted to minimum
      phase using the cepstral method (log magnitude, inverse FFT, causal
      window, exponential). This ensures the smallest possible group delay.
    - **Export:** The final filter is truncated to the configured tap count
      (16,384 by default) and exported as a WAV file.

    The wizard shows a pipeline step visualization with progress indicators
    for each stage. Per-channel result cards display key metrics: D-009 peak
    gain in dB, minimum-phase verification pass/fail, and format validation.

    This phase takes a few seconds on the Pi.

### 4f. Deploy

22. When filter generation completes, the wizard enters the deploy phase.
    It copies the generated WAV files to `/etc/pi4audio/coeffs/`, updates
    the PipeWire filter-chain configuration to reference the new files, and
    triggers a configuration reload.

    The deploy does NOT restart PipeWire. It updates the convolver
    coefficients in place. There is no USBStreamer transient risk during
    this step.

### 4g. Verification

23. The wizard runs an automatic verification sweep. It plays a new sweep
    through each channel with the correction filters now active and checks
    the result against the expected target curve. The verification confirms:

    - **D-009 compliance:** No frequency bin exceeds -0.5 dB (no boost in the
      deployed filter).
    - **Minimum-phase property:** The deployed filter is minimum-phase.
    - **Format correctness:** Sample rate, bit depth, and tap count match the
      configuration.
    - **Crossover sum:** The combined highpass and lowpass filters sum to unity
      through the crossover region (no energy gap or overlap).
    - **Filter loaded:** PipeWire has actually loaded the new coefficients
      (verified via the filter-chain node status).

    Per-channel verification cards show pass/fail for each check. If any
    check fails, the wizard reports the failure and offers to roll back to
    the previous filter set.

24. When all channels pass verification, the wizard shows **COMPLETE**. The
    room correction filters are active and deployed.

25. Remove the UMIK-1 from the measurement position. Stow it safely.

---

## Phase 5: Sound Check

26. Go to the **Dashboard** tab. The level meters and spectrum analyzer are
    now live. Start your audio application:
    - DJ mode: Launch Mixxx via `pw-jack mixxx` (or the launch script)
    - Live mode: Launch Reaper

27. Play a familiar test track at low volume. Watch the Dashboard:
    - The level meters should show signal on all four speaker channels
    - The spectrum analyzer should show the expected frequency distribution
    - Check that the crossover region (around 80 Hz) looks clean -- energy
      should transition smoothly from mains to subs

28. Walk the room. Listen at several positions. The correction should have
    tamed the worst room modes (bass peaks) without making the sound thin
    or unnatural. If a particular frequency range sounds wrong, you can
    re-run the measurement (go back to the Measure tab). Each measurement
    replaces the previous correction filters.

29. If you are in live mode, check the singer's in-ear monitors. The IEM
    channels bypass the convolver entirely (direct PipeWire link to
    USBStreamer channels 7-8). The singer should hear the backing track
    without room correction artifacts. Confirm the PA path delay is
    acceptable -- at quantum 256, the PA path is approximately 5.3 ms.

---

## Phase 6: Ready to Perform

30. Confirm the amplifier is at performance level.

31. Confirm the quantum is correct for your mode:
    - DJ mode: 1024 (~21 ms PA path, efficient CPU)
    - Live mode: 256 (~5.3 ms PA path, low latency)

32. The system is ready. The Dashboard tab provides real-time monitoring
    throughout the performance -- level meters with peak hold, spectrum
    analysis, system health (CPU, temperature, xrun count).

33. The **MUTE** button in the status bar is always available for emergencies.
    It sets all four gain nodes to zero without dropping the PipeWire stream
    (no USBStreamer transient). Press UNMUTE to restore the previous gain
    values.

---

## Quick Reference: Timing

| Phase | Duration | Notes |
|-------|----------|-------|
| Physical setup | 15-30 min | Depends on venue, cable runs |
| Power-on and system check | 2 min | Pi boot + web UI check |
| Speaker profile selection | 1 min | Select and activate |
| Pre-flight checks | 1 min | Automated + amp confirmation |
| Gain calibration | 1 min | A few seconds per channel |
| Sweep measurements (3 positions) | 5-10 min | Includes repositioning the mic |
| Filter generation | 30 sec | Pipeline runs on Pi |
| Deploy + verification | 1 min | Automated |
| Sound check | 5-10 min | Walk the room, listen |
| **Total** | **~30-60 min** | From power-on to ready |

---

## Troubleshooting

**UMIK-1 not detected:** Unplug and replug the USB cable. Check that the Pi
recognizes it (`lsusb` should show miniDSP). The calibration file lives at
`/home/ela/7161942.txt` on the Pi -- if it is missing, the pre-flight check
will fail with a calibration error.

**GraphManager mode wrong:** The wizard checks the current GM mode via
`/api/v1/test-tool/current-mode`. If GM is not in the expected mode, the
wizard indicates what mode is needed. Mode transitions can be triggered from
the Config tab or via GM RPC.

**Sweep measurement noisy:** If the room has high ambient noise (generators,
HVAC, crowd), the measurement signal-to-noise ratio suffers. Options: increase
the amplifier gain (makes the sweep louder relative to ambient noise), move the
microphone closer to the speakers for near-field measurement, or wait for a
quieter moment. The -20 dBFS safety cap on the signal generator cannot be
changed.

**D-009 verification fails:** This means the filter generation produced a
filter with gain above -0.5 dB at some frequency. This should not happen
with the standard pipeline (the D-009 clamp is applied during generation and
re-enforced during combination). If it does, the wizard offers rollback.
Check whether the speaker profile's target curve or gain staging values are
unusual.

**PipeWire not running:** The status bar will show no PipeWire connection.
Restarting PipeWire requires the amplifier to be OFF first (USBStreamer
transient risk -- see `docs/operations/safety.md` Section 1). After
confirming the amp is off: `systemctl --user restart pipewire.service`, then
turn the amp back on.

**High CPU or xruns during measurement:** The filter-chain convolver runs
alongside the measurement sweep. At quantum 256 (live mode), the combined CPU
load is higher. If xruns occur during measurement, switch to quantum 1024
temporarily (Config tab), run the measurement, then switch back to 256 for
the performance.

---

## Cross-References

- [Safety Operations Manual](../../operations/safety.md) -- USBStreamer
  transient risk, gain staging rules, measurement safety
- [RT Audio Stack](../../architecture/rt-audio-stack.md) -- PipeWire
  configuration, filter-chain convolver, quantum settings
- [Room Compensation](../../architecture/room-compensation.md) -- detailed
  explanation of the measurement and filter generation pipeline
- [Design Rationale](../../theory/design-rationale.md) -- why combined FIR,
  why minimum-phase, why cut-only correction
