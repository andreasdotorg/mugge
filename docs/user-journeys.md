# User Journeys — mugge

Operational workflows for mugge. Each journey documents a
complete procedure from start to verification, written for audio professionals operating
under venue time pressure.

**Audience:** Sound engineers and DJs operating the Pi4 audio workstation at live events.
Setup/calibration procedures assume access to a phone/tablet (web UI) or laptop (SSH/VNC).
During-show procedures are designed for MIDI-controller-only operation where possible.

**Flow ordering:** These journeys follow a strict dependency chain. Do not skip ahead.

```
1. Adding New Speakers
   |
   v
2. Gain Staging Setup & Validation
   |
   v
3. Crossover Configuration
   |
   v
4. Bass Protection Setup
   |
   v
5. SPL Calibration
   |
   v
6. Room Correction -- Per-Speaker
   |
   v
7. Room Correction -- Sub Timing
   |
   v
8. Room Correction -- Integration Testing
   |
   v
9. Running a Show
   |
   v
10. Debugging Issues (as needed)
```

---

## 1. Adding New Speakers

### Overview

Register a new speaker in the system by creating its identity file, assigning it to a
channel, and creating or updating the speaker profile. This is a preparatory step done
before any acoustic work begins -- typically at home or in the workshop, not at the venue.

### Prerequisites

- Physical speaker available for inspection (impedance, driver size, enclosure type)
- Access to the Pi via SSH or VNC
- Manufacturer specifications or prior near-field measurements (if available)
- Knowledge of the intended channel assignment (see Channel Assignment table in CLAUDE.md)

### Step-by-Step Procedure

1. **Identify the speaker characteristics.**
   Gather: manufacturer, model, impedance (ohms), enclosure type (sealed/ported), port
   tuning frequency (if ported), power handling (watts), and any known acoustic bandwidth.

2. **Create a speaker identity YAML file.**
   Identity files live at `configs/speakers/identities/`. Create a new file named after
   the speaker model (e.g., `my-speaker-model.yml`).

   Required fields:
   ```yaml
   name: "Human-readable speaker name"
   manufacturer: "Manufacturer"
   model: "Model designation"
   type: sealed | ported

   impedance_ohm: 8        # Nominal impedance
   sensitivity_db_spl: null # Fill in if known (1W/1m)

   # D-029 gain staging limits
   max_boost_db: 4          # Maximum boost the correction pipeline may apply
   mandatory_hpf_hz: null   # Subsonic HPF frequency (CRITICAL for ported enclosures)

   # Power handling
   max_power_watts: null
   power_limit_note: ""

   # Compensation EQ -- typically empty until listening-position measurement
   compensation_eq: []
   ```

   For ported enclosures, `mandatory_hpf_hz` is **not optional**. Set it to approximately
   0.72x the lowest port tuning frequency. Cone excursion rises sharply below port tuning
   and will exceed Xmax without protection.

3. **Verify amplifier compatibility.**
   Check that the amplifier channel can handle the speaker's impedance. The 4-channel
   Class D amp delivers up to 450W into 4 ohm. Low-impedance loads (e.g., the PS28 III
   at 2.33 ohm) require dedicated amp channels.

4. **Assign the speaker to a channel.**
   Update or create a speaker profile at `configs/speakers/profiles/`. The profile maps
   speakers to CamillaDSP output channels and declares the crossover topology.

   ```yaml
   name: "Profile Name"
   topology: 2way
   crossover:
     frequency_hz: 80
     slope_db_per_oct: 48
   speakers:
     main_left:
       identity: my-speaker-model
       role: satellite
       channel: 0
       filter_type: highpass
       polarity: normal
     # ... additional speakers
   ```

5. **Deploy the identity and profile files to the Pi.**
   Copy files to the Pi's `configs/speakers/` directory via the change manager or SCP.

### Verification / Success Criteria

- [ ] Identity YAML passes schema validation (all required fields present)
- [ ] `mandatory_hpf_hz` is set for all ported enclosures
- [ ] Amplifier impedance compatibility confirmed
- [ ] Speaker profile maps all intended channels
- [ ] Files deployed to Pi and readable

### Common Pitfalls

- **Omitting `mandatory_hpf_hz` for ported speakers.** This is a safety-critical field.
  Without it, the bass protection pipeline cannot generate subsonic filters, risking
  driver damage from cone excursion below port tuning.
- **Wrong impedance value.** Isobaric configurations (like the PS28 III) have different
  effective impedance than single-driver nominal. Verify with a multimeter if in doubt.
- **Channel conflicts.** Two speakers assigned to the same output channel will produce
  undefined behavior in CamillaDSP. Cross-check against the Channel Assignment table.

### Web UI Touchpoints

None. This is a file-management workflow performed via SSH/editor. The web UI becomes
relevant only after the speaker is integrated into a running CamillaDSP configuration.

---

## 2. Gain Staging Setup & Validation

### Overview

Establish the correct gain structure from source through the entire signal chain:
source material (-14 LUFS nominal) through PipeWire (unity) through CamillaDSP
(per-channel trim) through FIR filters (which must not exceed -0.5dB per D-009)
through the ADA8200 DAC (0dBFS = +18dBu) to the amplifier (26dB gain) to the speakers.

Gain staging MUST be completed before room correction. The correction pipeline assumes
a properly calibrated gain structure. Incorrect staging produces either clipping
(destroying transients) or insufficient headroom (wasting dynamic range).

### Prerequisites

- Speakers registered and assigned (Journey 1 complete)
- All hardware connected: Pi -> USBStreamer -> ADA8200 -> Amplifier -> Speakers
- CamillaDSP running with the appropriate production config (`dj-pa.yml` or `live.yml`)
- Web UI accessible (for level monitoring)
- Pink noise test signal or known-level reference track available

### Step-by-Step Procedure

1. **Verify PipeWire is at unity gain.**
   PipeWire should pass audio without modification. Confirm via SSH:
   ```bash
   wpctl get-volume @DEFAULT_AUDIO_SINK@
   ```
   Expected: `Volume: 1.000000`. If not, reset: `wpctl set-volume @DEFAULT_AUDIO_SINK@ 1.0`

2. **Set CamillaDSP mixer trims to 0dB.**
   In the production config, all mixer source gains for PA channels (0-3) should start
   at 0dB (mains) or -6dB (sub mono sum -- this is the L+R summing gain, not a trim).
   The `speaker_trim` filter provides a global safety attenuation (currently -24dB in
   the production configs -- this is a placeholder for initial testing and must be
   adjusted to match the amplifier/speaker combination).

3. **Set amplifier gain controls.**
   Start with amplifier volume at minimum. This is the coarse gain control for the
   entire system.

4. **Play a reference signal.**
   Use pink noise at -20dBFS or a known reference track at -14 LUFS. Route through
   the DJ application (Mixxx) or DAW (Reaper) as appropriate for the mode being
   calibrated.

5. **Observe pre-DSP levels on the web UI.**
   The MAIN meters (ML/MR) on the engineer dashboard show the signal entering
   the convolver. Target: -20dBFS to -14dBFS for reference material.

6. **Observe post-DSP levels on the web UI.**
   The PA SENDS meters (SatL/SatR/S1/S2) show the signal after FIR processing and
   speaker trim. With dirac (passthrough) filters and -24dB speaker trim, post-DSP
   levels should be approximately 24dB below pre-DSP levels.

7. **Adjust speaker trim for target SPL.**
   Increase the `speaker_trim` gain in CamillaDSP (reduce the attenuation) while
   simultaneously increasing amplifier gain until the desired listening level is
   reached. The goal: post-DSP peaks should not exceed -3dBFS on any channel.

   The split between CamillaDSP trim and amplifier gain is a tradeoff:
   - More CamillaDSP gain = more digital headroom consumed = less room for FIR correction
   - More amplifier gain = higher noise floor from analog amplification

   Rule of thumb: keep CamillaDSP per-channel trims within +/-3dB of nominal.

8. **Verify headroom with hot material.**
   Play the loudest expected source material (psytrance at -0.5 LUFS for DJ mode).
   Confirm no clipping indicators appear on the web UI. Post-DSP peaks must stay
   below -0.5dBFS (the D-009 safety margin).

9. **Document the gain structure.**
   Record the final values: PipeWire volume, CamillaDSP mixer gains, speaker trim,
   amplifier gain setting. These become the baseline for room correction.

### Verification / Success Criteria

- [ ] PipeWire at unity gain (1.0)
- [ ] Pre-DSP levels between -20dBFS and -6dBFS with reference material
- [ ] Post-DSP peaks below -3dBFS with reference material
- [ ] No clipping with hottest expected source material (-0.5 LUFS psytrance)
- [ ] Web UI CLIP indicators never trigger during validation
- [ ] Gain values documented

### Common Pitfalls

- **Adjusting gain after room correction.** Changing the gain structure invalidates all
  correction filters. The filters were designed for a specific operating point. If you
  change trim values, re-run the correction pipeline.
- **Forgetting the sub mono sum gain.** The L+R summing for subwoofers applies -6dB per
  channel to maintain unity gain through the sum. This is not a trim -- do not adjust it.
- **Clipping at the ADA8200 DAC.** The ADA8200's 0dBFS corresponds to +18dBu analog
  output. If CamillaDSP sends 0dBFS, the DAC is at its maximum. Digital clipping in
  CamillaDSP is worse than analog clipping in the amp -- always clip-check digitally.

### Web UI Touchpoints

- **Engineer Dashboard** -- MAIN meters (ML/MR) for pre-DSP monitoring
- **Engineer Dashboard** -- PA SENDS meters (SatL/SatR/S1/S2) for post-DSP monitoring
- **Engineer Dashboard** -- CLIP indicators on all meters
- **Engineer Dashboard** -- DSP health bar (processing load, buffer level)

---

## 3. Crossover Configuration

### Overview

Configure the combined minimum-phase FIR crossover that separates frequency bands
between mains and subwoofers. This system does NOT use traditional IIR (Linkwitz-Riley)
crossovers. Instead, the crossover slope is combined with room correction into a single
minimum-phase FIR filter per output channel. This design choice preserves psytrance
kick transient fidelity (~1-2ms group delay vs ~4-5ms for LR4 IIR).

Crossover parameters are declared in the speaker profile YAML file and executed by the
room correction pipeline. You cannot adjust crossover frequency in the CamillaDSP YAML
directly -- you regenerate the FIR coefficients.

### Prerequisites

- Gain staging complete (Journey 2)
- Speaker profile created with crossover section (Journey 1)
- Understanding of the speaker system's capabilities (acoustic bandwidth from identity files)

### Step-by-Step Procedure

1. **Determine the crossover frequency.**
   The crossover point depends on the satellite speakers' low-frequency capability and
   the subwoofers' upper range. For the Bose system (Jewel Double Cube + PS28 III), the
   crossover is at 200Hz due to the satellites' limited low-frequency extension. For
   full-range mains with dedicated subs, 80Hz is the standard default.

   The crossover frequency is set in the speaker profile:
   ```yaml
   crossover:
     frequency_hz: 80    # or 200 for bandwidth-limited satellites
     slope_db_per_oct: 48
   ```

2. **Select the crossover slope.**
   FIR crossovers can achieve much steeper slopes than IIR. Available range: 48-96 dB/oct.
   Steeper slopes provide better band separation but require more FIR taps for accurate
   low-frequency reproduction.
   - 48 dB/oct: good default, efficient in taps
   - 96 dB/oct: maximum separation, use when satellites have very limited LF capability

3. **Verify the crossover design against speaker identity constraints.**
   Check that the crossover frequency falls within the acoustic bandwidth of both the
   satellite and subwoofer. The satellite's `mandatory_hpf_hz` (from its identity file)
   must be at or below the crossover frequency -- otherwise the satellite receives content
   it cannot reproduce.

4. **Run the correction pipeline to generate crossover filters.**
   The crossover is generated as part of the room correction pipeline (Journey 6). For
   crossover-only testing without room correction, you can run the pipeline with dirac
   (flat) impulse responses:
   ```bash
   python runner.py --mock --room-config mock/room_config.yml \
       --profile configs/speakers/profiles/your-profile.yml \
       --output-dir /tmp/crossover-test/
   ```

5. **Verify the generated filters.**
   The pipeline's mandatory verification suite checks crossover behavior:
   - High-pass filters must attenuate below crossover frequency
   - Low-pass filters must attenuate above crossover frequency
   - All filters must comply with D-009 (gain <= -0.5dB at every frequency)

### Verification / Success Criteria

- [ ] Crossover frequency appropriate for speaker system capabilities
- [ ] Slope steep enough to protect bandwidth-limited drivers
- [ ] Generated filters pass all verification checks
- [ ] Mains do not receive significant content below crossover frequency
- [ ] Subs do not receive significant content above crossover frequency

### Common Pitfalls

- **Setting crossover too low for small satellites.** If the crossover frequency is below
  the satellite's usable bandwidth, the satellite receives content it cannot reproduce,
  wasting amplifier power and potentially causing driver damage. The Bose Jewel Double
  Cube is usable only down to ~200Hz -- a crossover at 80Hz would be destructive.
- **Confusing IIR and FIR crossover configuration.** The CamillaDSP YAML files do NOT
  contain crossover filters. The Conv filters in the pipeline load combined FIR WAV files
  that include both crossover and room correction. Editing the YAML crossover section
  (if it existed) would have no effect.
- **Changing crossover without re-running the pipeline.** The crossover is baked into the
  combined FIR filter. Changing the profile YAML alone does nothing -- you must regenerate
  the filters.

### Web UI Touchpoints

- **Engineer Dashboard** -- PA SENDS meters confirm signal is correctly band-split
  (subs should show no high-frequency content; mains should show no sub-bass)
- **Engineer Dashboard** -- DSP health (processing load) to verify FIR convolution
  is within CPU budget after filter deployment

---

## 4. Bass Protection Setup

### Overview

Configure three layers of bass protection to prevent driver damage from excessive
low-frequency excursion:

1. **Subsonic HPF** -- Minimum-phase high-pass filter baked into the combined FIR,
   typically at 25-42Hz depending on the driver/enclosure. For ported enclosures, this
   is MANDATORY: cone excursion rises sharply below port tuning frequency.
2. **D-009 cut-only guarantee + speaker_trim attenuation** -- All FIR correction filters
   are mathematically guaranteed to have gain <= -0.5dB at every frequency (D-009).
   Combined with the `speaker_trim` filter (which always attenuates), the output level
   is always lower than the input level. This eliminates the possibility of digital
   clipping from the DSP chain itself.
3. **Amplifier thermal protection** -- External to the software stack, built into the
   amplifier hardware. Not software-controlled but must be verified as functional.

### Prerequisites

- Speaker identities created with `mandatory_hpf_hz` values (Journey 1)
- Gain staging complete (Journey 2)
- Crossover frequency determined (Journey 3)

### Step-by-Step Procedure

1. **Verify `mandatory_hpf_hz` in speaker identity files.**
   Every ported enclosure MUST have this field set. For sealed enclosures, it is optional
   but recommended.

   Reference values from current inventory:
   - Bose PS28 III (ported, dual-port 58/88Hz): `mandatory_hpf_hz: 42`
   - Bose Jewel Double Cube (sealed): `mandatory_hpf_hz: 200`

2. **Confirm subsonic filter generation in the pipeline.**
   The room correction pipeline (`runner.py`) automatically generates subsonic protection
   filters for any channel whose speaker identity declares `mandatory_hpf_hz`. This
   appears as Stage 5b in the pipeline output:
   ```
   [5b] Generating subsonic protection filters (mandatory HPF protection)...
     sub1: subsonic HPF at 42Hz (mandatory HPF protection)
   ```
   The subsonic filter is convolved into the combined FIR -- it is not a separate
   CamillaDSP filter stage.

3. **Understand the D-009 cut-only guarantee.**
   CamillaDSP does not have a built-in limiter. Instead, the system relies on a
   mathematical guarantee: all FIR correction filters are verified to have gain <= -0.5dB
   at every frequency bin (D-009), and the `speaker_trim` filter always applies negative
   gain (attenuation). Together, these ensure that the DSP chain's output level is always
   lower than its input level -- digital clipping from the DSP pipeline is impossible.

   If a digital limiter is ever needed (e.g., for additional transient protection beyond
   D-009), the implementation path would be a PipeWire filter-chain with a LADSPA limiter
   plugin inserted upstream of CamillaDSP. This is a future option, not current
   architecture.

4. **Verify amplifier thermal protection.**
   Confirm the amplifier's built-in thermal protection is enabled. This is a hardware
   feature and cannot be configured in software. Consult the amplifier documentation.
   For the PS28 III at 2.33 ohm with a 450W amp channel, thermal protection is
   especially critical -- the amp can deliver far more power than the driver can handle.

5. **Test bass protection with subsonic test signals.**
   Play a 20Hz sine wave at moderate level. Confirm:
   - The web UI shows significant attenuation on sub channels (subsonic HPF working)
   - No audible cone excursion distortion from the subwoofers
   - Post-DSP levels remain below input levels (D-009 guarantee in effect)

### Verification / Success Criteria

- [ ] All ported speakers have `mandatory_hpf_hz` set in identity files
- [ ] Pipeline output confirms subsonic filter generation (Stage 5b)
- [ ] Combined filters pass the mandatory HPF verification check
- [ ] D-009 compliance verified (all filter gains <= -0.5dB)
- [ ] Amplifier thermal protection confirmed functional
- [ ] Subsonic test signal shows proper attenuation on sub channels

### Common Pitfalls

- **Relying on the crossover as bass protection.** The crossover slope attenuates content
  below the crossover frequency, but it is not steep enough at very low frequencies to
  prevent damage. A dedicated subsonic HPF (48dB/oct minimum-phase) provides the
  additional protection needed below port tuning.
- **Forgetting to re-verify after filter regeneration.** Every time the room correction
  pipeline runs, the subsonic filter is regenerated as part of the combined FIR. The
  pipeline's mandatory verification suite includes a HPF check, but confirm the output
  explicitly.
- **Assuming D-009 cut-only protects against subsonic content.** D-009 guarantees the
  filter gain is <= -0.5dB, meaning the DSP chain never amplifies. However, this does
  not prevent subsonic content from passing through at near-unity gain. A sustained 15Hz
  signal at -6dBFS would pass through a flat (dirac) filter at -6.5dBFS -- still enough
  to cause dangerous cone excursion. The subsonic HPF is the primary defense against
  low-frequency driver damage.

### Web UI Touchpoints

- **Engineer Dashboard** -- S1/S2 meters for monitoring sub output levels
- **Engineer Dashboard** -- CLIP indicators on sub channels
- **Engineer Dashboard** -- DSP health (clipped samples counter should remain 0)

---

## 5. SPL Calibration

### Overview

Establish an absolute SPL reference using the UMIK-1 measurement microphone. This
calibration links the digital meter readings on the web UI to real-world sound pressure
levels, enabling target curve application during room correction and SPL compliance
monitoring during shows.

### Prerequisites

- Gain staging complete (Journey 2)
- UMIK-1 measurement microphone available
- UMIK-1 calibration file present on Pi (`/home/ela/7161942.txt`, serial 7161942,
  -1.378dB sensitivity)
- Web UI accessible

### Step-by-Step Procedure

1. **Connect the UMIK-1.**
   Plug the UMIK-1 into a USB port on the Pi. Verify detection:
   ```bash
   arecord -l | grep UMIK
   ```
   The UMIK-1 should appear as a USB audio capture device.

2. **Verify the calibration file.**
   The UMIK-1 calibration file contains frequency-dependent sensitivity corrections
   from miniDSP's factory calibration. The file at `/home/ela/7161942.txt` is a
   magnitude-only correction (minimum-phase assumption). Confirm it matches the UMIK-1's
   serial number (printed on the microphone body).

3. **Generate a reference SPL tone.**
   Play a 1kHz sine wave at a known digital level (e.g., -20dBFS) through the PA system.
   Alternatively, use pink noise for a broadband reference.

4. **Measure with an external SPL meter (if available).**
   Place a calibrated SPL meter at the listening position. Record the dBA and dBC
   readings. This provides the absolute reference for mapping digital levels to SPL.

5. **Calibrate the web UI SPL display.**
   The UMIK-1's sensitivity at 1kHz is -1.378dB (from the calibration file). Two
   calibration methods are available:

   **Method A: External SPL meter comparison (recommended, +/-1dB accuracy).**
   Play pink noise at a stable level. Read the SPL value from a calibrated external
   SPL meter at the listening position. Read the uncalibrated SPL value from the web
   UI. Set the calibration offset to: `external reading - web UI reading`.

   **Method B: Manufacturer sensitivity (no external meter, +/-2dB accuracy).**
   Use the UMIK-1 manufacturer sensitivity (-1.378dB for serial 7161942) directly.
   This provides approximately +/-2dB accuracy without a pistonphone or reference
   SPL meter.

   Configure the offset in the web UI settings:
   ```
   spl_meter.calibration_offset_db: <computed offset>
   ```

6. **Select a target curve.**
   Target curves define the desired frequency response shape after room correction:
   - `flat`: Equal energy per frequency band. Used for reference/measurement.
   - `harman`: Harman-like preference curve with mild bass shelf. Good for music listening.
   - SPL-dependent targets: More bass boost at lower SPL, flatter at high SPL (PA use).

   The target curve is configured in the speaker profile:
   ```yaml
   target_curve: flat   # or harman, or a custom curve name
   ```

### Verification / Success Criteria

- [ ] UMIK-1 detected by ALSA on the Pi
- [ ] Calibration file serial matches microphone serial
- [ ] Reference tone produces expected SPL at listening position (+/- 3dB)
- [ ] SPL offset documented for web UI calibration
- [ ] Target curve selected and configured in speaker profile

### Common Pitfalls

- **Using the wrong calibration file.** Each UMIK-1 has a unique calibration file keyed
  to its serial number. Using the wrong file introduces systematic measurement error
  that propagates through all room correction filters.
- **Measuring SPL in a noisy environment.** Background noise raises the apparent SPL
  reading. Calibrate in a quiet environment or use a gated measurement technique.
- **Confusing dBA and dBC weighting.** dBA de-emphasizes low frequencies (matching human
  hearing sensitivity). dBC is approximately flat. For bass-heavy music (psytrance),
  dBC is more representative of actual acoustic energy. The web UI should display both.

### Web UI Touchpoints

- **Engineer Dashboard** -- SPL hero display (right panel, 42px readout)
- **Engineer Dashboard** -- LUFS readouts (short-term, integrated, momentary)
- **Engineer Dashboard** -- MAIN meters for digital reference level

---

## 6. Room Correction -- Per-Speaker

### Overview

Measure each speaker individually at the listening position and generate correction
filters that compensate for room acoustics. This is the core of the room correction
pipeline. Each speaker gets its own measurement because different physical placement
produces different room interaction (reflections, standing waves, boundary effects).

The pipeline measures, computes, and verifies correction filters automatically. The
operator's role is microphone placement and pipeline invocation.

### Prerequisites

- All previous journeys complete (1-5)
- UMIK-1 connected and calibrated
- Room quiet (no music, no crowd, minimal HVAC noise)
- Amplifier at the gain-staged operating level (Journey 2 settings)
- 3-5 measurement positions planned in a cluster around the primary listening area
  (e.g., center of dancefloor, +/-0.5m in each direction)

### Step-by-Step Procedure

1. **Place the UMIK-1 at the first measurement position.**
   Position the microphone at ear height (~1.2m for standing, ~1.0m for seated) at the
   center of the intended listening area. Point the UMIK-1 capsule toward the ceiling
   (0-degree incidence for omnidirectional measurement).

2. **Run the room correction pipeline.**
   ```bash
   cd ~/pi4-audio-workstation/src/room-correction/
   python runner.py --stage full \
       --room-config /path/to/venue-room-config.yml \
       --profile /path/to/speaker-profile.yml \
       --calibration /home/ela/7161942.txt \
       --output-dir /tmp/correction-$(date +%Y%m%d-%H%M)/
   ```

   The pipeline executes seven stages automatically:
   - **[1/7] Sweep generation:** Creates a log sweep (20Hz-20kHz, default 5 seconds)
   - **[2/7] Measurement:** Plays the sweep through each speaker individually and records
     the response via UMIK-1. Deconvolves to extract impulse responses.
   - **[2b] UMIK-1 calibration:** Applies the frequency-dependent sensitivity correction
   - **[3/7] Time alignment:** Detects arrival times, computes relative delays (see Journey 7)
   - **[4/7] Correction filters:** Generates per-channel correction with frequency-dependent
     windowing, psychoacoustic smoothing, and D-009 cut-only constraint
   - **[5/7] Crossover filters:** Generates minimum-phase FIR crossover shapes
   - **[5b] Subsonic protection:** Generates mandatory HPF filters for ported enclosures
   - **[6/7] Combination:** Convolves correction + crossover + subsonic into single FIR per channel
   - **[7/7] Export:** Writes combined WAV files

3. **Monitor pipeline progress.**
   The pipeline prints detailed progress for each stage. Key things to watch:
   - Impulse response quality: look for reasonable IR lengths and clean deconvolution
   - Correction filter gains: all must be <= -0.5dB (D-009)
   - Processing times: the full pipeline should complete in under 60 seconds on the Pi

4. **Review the mandatory verification results.**
   The pipeline runs verification automatically after filter generation:
   - **D-009 compliance:** Every frequency bin <= -0.5dB (HARD FAIL if violated)
   - **Format check:** Correct sample rate, bit depth, channel count
   - **Minimum-phase check:** Verifies consistent phase behavior
   - **Target deviation:** Confirms correction tracks the target curve within tolerance
   - **Mandatory HPF:** Verifies subsonic protection for ported enclosures

   ALL checks must pass. If any check fails, the pipeline prints `PIPELINE FAILED` and
   does not deploy filters.

5. **Repeat for multiple positions (spatial averaging).**
   Take 3-5 measurements clustered within +/-0.5m of the primary listening position,
   all at ear height (~1.2m). Minimum 3 positions; the sweet spot is 5.

   For each position, run the measurement stage individually:
   ```bash
   python runner.py --stage measure --position-id pos1 \
       --room-config /path/to/venue-room-config.yml \
       --profile /path/to/speaker-profile.yml \
       --calibration /home/ela/7161942.txt \
       --output-dir /tmp/correction-$(date +%Y%m%d-%H%M)/
   # Move mic to next position
   python runner.py --stage measure --position-id pos2 ...
   python runner.py --stage measure --position-id pos3 ...
   ```

   Then run the full pipeline with spatial averaging enabled:
   ```bash
   python runner.py --stage full --spatial-average \
       --room-config /path/to/venue-room-config.yml \
       --profile /path/to/speaker-profile.yml \
       --calibration /home/ela/7161942.txt \
       --output-dir /tmp/correction-$(date +%Y%m%d-%H%M)/
   ```

   The spatial averaging module energy-averages the magnitude spectra across all
   measured positions. Energy-averaging (not complex-averaging) is used because phase
   varies chaotically at high frequencies across positions -- complex averaging would
   cause destructive cancellation artifacts. Time alignment uses only the PRIMARY
   position (pos1), not the averaged response.

6. **Deploy the generated filters.**
   On successful verification, copy the combined filter WAV files to the CamillaDSP
   coefficients directory:
   ```
   combined_left_hp.wav  -> /etc/camilladsp/coeffs/combined_left_hp.wav
   combined_right_hp.wav -> /etc/camilladsp/coeffs/combined_right_hp.wav
   combined_sub1_lp.wav  -> /etc/camilladsp/coeffs/combined_sub1_lp.wav
   combined_sub2_lp.wav  -> /etc/camilladsp/coeffs/combined_sub2_lp.wav
   ```

   **WARNING:** Deploying new filters requires restarting CamillaDSP. Restarting
   CamillaDSP causes the USBStreamer to lose its audio stream, which produces transients
   through the amplifier chain. **Turn off amplifiers before restarting CamillaDSP.**

7. **Restart CamillaDSP with new filters.**
   ```bash
   sudo systemctl restart camilladsp
   ```
   Verify CamillaDSP starts successfully and loads the new filters (check the web UI
   DSP health status: should show "Running" with the correct config path).

### Verification / Success Criteria

- [ ] Pipeline completes with `PIPELINE COMPLETE: All filters generated and verified`
- [ ] All D-009 checks pass (no filter gain exceeds -0.5dB)
- [ ] Mandatory HPF checks pass for all ported enclosures
- [ ] Combined filter files present in output directory
- [ ] Filters deployed to `/etc/camilladsp/coeffs/`
- [ ] CamillaDSP restarts successfully with new filters
- [ ] Web UI shows "Running" state with correct config

### Common Pitfalls

- **Measuring with music playing.** The sweep measurement requires silence. Any background
  audio contaminates the impulse response and produces incorrect correction.
- **Moving the microphone during a sweep.** Each sweep takes ~5 seconds. Hold the mic
  steady (use a mic stand). Movement during measurement invalidates the impulse response.
- **Deploying filters that failed verification.** The pipeline explicitly blocks this,
  but if you manually copy filter files, ALWAYS verify first. A filter with gain > -0.5dB
  will clip with hot psytrance material.
- **Forgetting to restart CamillaDSP.** CamillaDSP loads filter WAV files at startup.
  Overwriting the files on disk does not change the running filters -- you must restart.
- **Not turning off amps before restart.** The USBStreamer produces transients when it
  loses its audio stream. These transients pass through the amplifier to the speakers.
  Always mute or power off amps before restarting CamillaDSP.

### Web UI Touchpoints

- **Engineer Dashboard** -- DSP health (verify CamillaDSP state after filter deployment)
- **Engineer Dashboard** -- Processing load (verify CPU is within budget with new filters)
- **Engineer Dashboard** -- All meters (verify signal flow is correct after deployment)

---

## 7. Room Correction -- Sub Timing

### Overview

Align the arrival times of all speakers so that their acoustic output reaches the
listening position simultaneously. Sound travels at approximately 343 m/s (at 20 deg C).
Speakers at different distances arrive at different times. The furthest speaker is used
as the reference (delay = 0); all closer speakers receive positive delay to compensate.

Time alignment is computed automatically by the room correction pipeline (Stage 3/7)
from the impulse response onset detection. This journey covers validation and manual
adjustment if needed.

### Prerequisites

- Per-speaker room correction complete (Journey 6) -- impulse responses available
- Delay values computed by the pipeline (saved to `delays.yml` in the output directory)

### Step-by-Step Procedure

1. **Review the computed delay values.**
   The pipeline saves delay values to `delays.yml`:
   ```yaml
   delays_ms:
     main_left: 0.0      # Reference speaker (furthest)
     main_right: 0.23
     sub1: 1.45
     sub2: 2.10
   delays_samples:
     main_left: 0
     main_right: 11
     sub1: 70
     sub2: 101
   ```

   The furthest speaker has delay 0. All others have positive delays. Verify that the
   relative delays make physical sense: a 1-meter distance difference equals ~2.9ms.

2. **Apply delays in CamillaDSP.**
   Delays are configured as CamillaDSP `Delay` filters in the pipeline YAML. Each
   channel that needs delay gets its own filter definition:

   ```yaml
   filters:
     delay_main_right:
       type: Delay
       parameters:
         delay: 0.23
         unit: ms
         subsample: false
     delay_sub1:
       type: Delay
       parameters:
         delay: 1.45
         unit: ms
         subsample: false
   ```

   Delay filters go AFTER FIR convolution and BEFORE `speaker_trim` in the pipeline:
   ```yaml
   pipeline:
     - type: Mixer
       name: route_dj
     - type: Filter        # FIR convolution first
       channels: [0]
       names: [left_hp]
     # ... other FIR filters ...
     - type: Filter        # Then delay
       channels: [1]
       names: [delay_main_right]
     - type: Filter
       channels: [2]
       names: [delay_sub1]
     - type: Filter        # Speaker trim last
       channels: [0, 1, 2, 3]
       names: [speaker_trim]
   ```

   Integer sample precision is sufficient (0.02ms at 48kHz). The `subsample: false`
   setting avoids unnecessary interpolation overhead.

   The deployment module (`deploy.py`) can inject these delay filters into the
   production config automatically. Delay values can also be hot-reloaded via the
   pycamilladsp websocket API without restarting CamillaDSP (though hot-reload has
   not yet been verified on this system).

3. **Verify alignment with a polarity/impulse test.**
   Play a short impulse or click through all channels simultaneously. At the listening
   position, all speakers should produce a single coherent transient. If the subs arrive
   noticeably late or early relative to the mains, the alignment needs adjustment.

4. **Fine-tune if necessary.**
   Temperature affects the speed of sound (~1.7% difference between 20 deg C and 30 deg C).
   At typical venue distances (5-10m), this produces ~0.05ms per meter of error --
   negligible for most setups. However, if the venue temperature is significantly
   different from the measurement conditions, re-running the pipeline is the cleanest
   solution.

### Verification / Success Criteria

- [ ] Delay values physically plausible (match relative speaker distances)
- [ ] Furthest speaker has delay 0
- [ ] Impulse test produces coherent single transient at listening position
- [ ] No audible time smearing on kick drums or other transient-heavy material
- [ ] CamillaDSP config updated with delay values

### Common Pitfalls

- **Applying delay to the wrong direction.** Closer speakers get MORE delay (they
  arrive too early and must wait). Applying delay to the furthest speaker doubles the
  misalignment.
- **Confusing acoustic delay with processing delay.** CamillaDSP's FIR convolution
  adds processing latency (~chunksize/samplerate). This is constant across all channels
  and does not need compensation. Only acoustic propagation delay (distance/speed_of_sound)
  varies between channels.
- **Sub-to-main phase cancellation at crossover.** Even with correct time alignment,
  the sub and main can be out of phase at the crossover frequency due to the crossover
  filters' phase response. The minimum-phase FIR design minimizes this, but if you
  hear a dip at the crossover frequency, check polarity (inversion may be needed on
  one sub, as done for the PS28 III isobaric configuration).

### Web UI Touchpoints

- **Engineer Dashboard** -- S1/S2 meters for sub output verification
- **Engineer Dashboard** -- MAIN meters for overall system coherence check

---

## 8. Room Correction -- Integration Testing

### Overview

Full-system verification after all correction filters, crossovers, delays, and protection
mechanisms are deployed. This is the final quality gate before the system is declared
ready for a show. The goal: confirm that the complete signal chain (source -> PipeWire ->
CamillaDSP -> ADA8200 -> Amplifier -> Speakers -> Room -> Microphone) produces the
intended frequency response at the listening position.

### Prerequisites

- All room correction filters deployed (Journey 6)
- Time alignment applied (Journey 7)
- Bass protection verified (Journey 4)
- UMIK-1 available for verification measurement
- Amplifiers at show-level gain

### Step-by-Step Procedure

1. **Run a verification measurement.**
   Play the sweep through the complete system (all speakers simultaneously, at show-level
   gain) and record via UMIK-1 at the primary listening position. This measures the
   corrected in-room response -- what the audience actually hears.

   The pipeline's `--stage verify` mode can check individual filter files:
   ```bash
   python runner.py --stage verify --filter /etc/camilladsp/coeffs/combined_left_hp.wav
   ```

2. **Compare corrected vs uncorrected response.**
   The verification measurement should show:
   - Smoother frequency response than uncorrected (fewer peaks and dips)
   - Response tracking the target curve within +/-3dB from 30Hz to 10kHz
   - Room modes (narrow peaks below ~300Hz) significantly reduced
   - High-frequency response preserved (no over-correction above 1kHz)

3. **Check sub-main integration at crossover.**
   The most critical frequency region is around the crossover point (80Hz or 200Hz
   depending on speaker profile). At this frequency:
   - Sub and main contributions should sum constructively (no cancellation dip)
   - Level should be within +/-3dB of adjacent frequency bands
   - If a dip exists, check time alignment and polarity settings

4. **Play reference tracks.**
   Use familiar, well-recorded material across multiple genres:
   - Psytrance with heavy kicks: check transient clarity and sub-bass impact
   - Vocal tracks: check midrange clarity and absence of coloration
   - Broadband pink noise: listen for obvious resonances or holes

5. **Stress test at show-level volume.**
   Play the hottest expected material at full show volume for 10-15 minutes. Monitor:
   - Web UI: no CLIP indicators, processing load stable, temperature reasonable
   - Audio: no distortion, no audible compression (limiter engaging), no thermal shutdown
   - DSP health: zero clipped samples, zero xruns

6. **Document the final system state.**
   Record:
   - Date, venue, speaker positions
   - Active CamillaDSP config path
   - Filter file checksums (or git commit hash)
   - Verification measurement results
   - Any deviation from target curve and reason

### Verification / Success Criteria

- [ ] Corrected response within +/-3dB of target curve (30Hz-10kHz)
- [ ] No cancellation dip at crossover frequency
- [ ] Zero xruns during 10-15 minute stress test
- [ ] Zero clipped samples during stress test
- [ ] CPU temperature below 75 deg C under sustained load
- [ ] DSP processing load within budget (< 45% for DJ mode, < 30% for live mode)
- [ ] Transient clarity preserved on kick-heavy material
- [ ] No audible artifacts (ringing, distortion, coloration)

### Common Pitfalls

- **Skipping the verification measurement.** Design principle 7 requires a mandatory
  verification measurement after every filter deployment. Never go to show without
  confirming the correction is working as intended.
- **Correcting at a single position and expecting uniform coverage.** Room correction
  is optimized for the measurement position(s). Sound quality will vary at other positions.
  Spatial averaging (3-5 positions) extends the effective correction zone.
- **Over-trusting the visual response curve.** A frequency response that looks flat on
  a plot may still sound wrong. Always supplement measurement with critical listening.
  Room correction handles steady-state response but not temporal artifacts (echoes,
  flutter, early reflections).

### Web UI Touchpoints

- **Engineer Dashboard** -- All meters active during stress test
- **Engineer Dashboard** -- DSP health (processing load, buffer level, clipped samples)
- **Engineer Dashboard** -- System health (CPU temperature, memory)
- **Engineer Dashboard** -- PipeWire status (xrun count, quantum)

---

## 9. Running a Show

### Overview

Operational flows for the two performance modes: DJ/PA (psytrance events) and Live
(vocal performance with backing tracks). Both modes follow the same startup sequence
but differ in application, CamillaDSP configuration, and interaction model.

### Prerequisites

- Integration testing complete (Journey 8) -- system verified for this venue
- All hardware connected and powered (in correct order)
- MIDI controllers connected (Hercules DJControl Mix Ultra for DJ, APCmini mk2 for both)
- Web UI accessible on phone/tablet for monitoring
- Firewall port 8080 open in nftables (required for phone/tablet web UI access; see
  Journey 10 "Web UI Not Accessible" for setup instructions)

### Startup Sequence (Both Modes)

1. **Power on the Pi.**
   The audio stack auto-starts via systemd:
   - PipeWire starts at boot (SCHED_FIFO 88)
   - CamillaDSP starts at boot (SCHED_FIFO 80)
   - Web UI starts at boot (SCHED_OTHER, Nice=10)

2. **Wait for full initialization (~30 seconds).**
   The Pi needs time for all services to stabilize. Do not interact until the green
   power LED stops flickering.

3. **Verify system health via web UI.**
   Open the engineer dashboard on your phone/tablet (`https://mugge:8080`). Check:
   - DSP health: "Running" (green)
   - PipeWire: quantum correct (1024 for DJ, 256 for live)
   - All meters visible and responding
   - No error indicators

4. **Verify MIDI controllers.**
   Confirm USB-MIDI devices are detected. The APCmini mk2 should show its LED startup
   sequence. The Hercules controller (if using USB rather than Bluetooth) should be
   enumerated.

5. **Select operating mode.**
   Switch to the appropriate CamillaDSP configuration:
   - **DJ/PA mode:** `dj-pa.yml` (chunksize 2048, quantum 1024)
   - **Live mode:** `live.yml` (chunksize 256, quantum 256)

   Mode switching requires loading a different CamillaDSP config and adjusting PipeWire
   quantum. The recommended approach is via the web UI or a dedicated script.

   For DJ mode, set PipeWire quantum:
   ```bash
   pw-metadata -n settings 0 clock.force-quantum 1024
   ```

### DJ/PA Mode Flow

1. **Launch Mixxx.**
   ```bash
   pw-jack mixxx
   ```
   Mixxx runs with hardware V3D GL on PREEMPT_RT (D-022). CPU usage ~85%.

2. **Load tracks and verify audio routing.**
   Play a preview track through the headphone cue (channels 5/6). Confirm:
   - Headphone output on the engineer's headphones
   - No bleed to PA channels

3. **Begin performance.**
   Use the Hercules DJControl Mix Ultra for deck control (play, cue, pitch, EQ).
   Use the APCmini mk2 for:
   - Effect triggers (pad grid)
   - Channel levels (faders)
   - Visual feedback (LED colors indicate active state)

4. **Monitor during performance.**
   Keep the web UI visible on a phone/tablet. Watch for:
   - CLIP indicators (red = signal too hot)
   - DSP processing load (should stay below 45%)
   - CPU temperature (should stay below 75 deg C)
   - Xrun count (should remain 0)

### Live Mode Flow

1. **Launch Reaper.**
   Reaper handles backing track playback, vocal mixing, and IEM routing.
   The singer's IEM signal path: Reaper -> CamillaDSP (passthrough on ch 7/8, no FIR
   processing) -> USBStreamer -> IEM transmitter.

2. **Verify singer IEM.**
   Have the singer confirm IEM audio is present and at a comfortable level. The singer
   can adjust levels via the Singer IEM web UI on her phone (`https://mugge:8080`,
   singer role login).

3. **Load the set list in Reaper.**
   Cue the first backing track. Verify vocal mic is routed and levels are correct.

4. **Begin performance.**
   Use the APCmini mk2 for:
   - Transport control (play, stop, next track)
   - Channel levels (vocal, backing, IEM mix)
   - Visual cues (LED colors for song sections or cue points)

5. **Engineer monitors during performance.**
   Same as DJ mode, plus:
   - IEM meters (IL/IR) -- confirm singer is receiving audio
   - Vocal mic input (MAIN meters if routed through the convolver)

### Emergency Procedures

**Audio cuts out completely:**
1. Check web UI -- is PipeWire still running? Is the convolver loaded?
2. If PipeWire crashed: **warn operator to turn off amps**, then restart:
   `systemctl --user restart pipewire`
3. If USB device disconnected: check physical cables, reconnect

**Uncontrolled feedback or oscillation:**
1. **MIDI panic button** (APCmini mk2 -- designated button, requires definition)
2. **Web UI kill switch** -- mute all PA outputs
3. **Physical amp power off** as last resort

**System freeze / kernel lockup:**
1. Wait 10 seconds (BCM2835 watchdog should trigger reboot)
2. If no recovery: power cycle the Pi
3. Audio stack auto-restarts on boot -- verify via web UI after reboot

**Singer loses IEM:**
1. Check web UI IEM meters -- is signal present?
2. Check the singer's web UI -- is it connected?
3. If disconnected: the IEM mix continues at its last settings (IEM is not affected
   by web UI disconnection)
4. If IEM hardware issue: switch to wedge monitor (backup plan)

### Verification / Success Criteria

- [ ] All services start automatically on power-on
- [ ] Web UI shows healthy system state within 30 seconds of boot
- [ ] MIDI controllers detected and responsive
- [ ] Correct operating mode active (DJ/PA or Live)
- [ ] Audio passes through all channels correctly
- [ ] Emergency procedures understood and accessible

### Common Pitfalls

- **Forgetting to set PipeWire quantum for DJ mode.** The production PipeWire config
  defaults to quantum 256 (live mode). DJ mode needs quantum 1024. If you launch Mixxx
  at quantum 256, CamillaDSP CPU usage will be unnecessarily high (chunksize 2048 with
  quantum 256 means more frequent processing cycles).
- **Turning on amplifiers before CamillaDSP is stable.** The USBStreamer produces
  transients during initialization. Wait for the web UI to confirm "Running" state
  before powering amps.
- **Not testing the emergency kill switch before the show.** Verify the MIDI panic button
  and web UI mute function actually work before the audience arrives.

### Web UI Touchpoints

- **Engineer Dashboard** -- Primary monitoring interface during show
- **Singer IEM UI** -- Singer's self-service level control (phone, portrait orientation)
- **System health tab** -- Detailed diagnostics if issues arise
- **MIDI configuration** -- Controller mapping verification (pre-show only)

---

## 10. Debugging Issues

### Overview

Diagnostic procedures for common failure modes, organized by symptom. This is a
reference for troubleshooting during setup and shows. Emergency recovery procedures
are in Journey 9.

### Common Failure Modes

#### No Audio Output

**Symptoms:** All meters at -infinity, no sound from speakers.

**Diagnostic procedure:**
1. **Check CamillaDSP state** via web UI DSP health. If "Stopped" or "Error":
   ```bash
   journalctl --user -u camilladsp -n 50
   ```
   Common causes: config file error, filter WAV file missing, ALSA device not available.

2. **Check PipeWire** via web UI system health. If PipeWire is not running:
   ```bash
   systemctl --user status pipewire
   journalctl --user -u pipewire -n 50
   ```

3. **Check ALSA devices:**
   ```bash
   aplay -l    # List playback devices
   arecord -l  # List capture devices
   ```
   The USBStreamer must appear. If missing: check USB cable, try a different USB port.

4. **Check the filter-chain convolver:**
   ```bash
   pw-cli ls Node | grep pi4audio-convolver
   ```
   Two nodes should appear: `pi4audio-convolver` (capture) and
   `pi4audio-convolver-out` (playback). If missing: check PipeWire config at
   `~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf`.

#### Xruns / Audio Glitches

**Symptoms:** Clicks, pops, or dropouts in audio. Web UI xrun counter increasing.

**Diagnostic procedure:**
1. **Check DSP processing load** on web UI. If > 90%: the Pi is CPU-starved.
   - For DJ mode: verify quantum is 1024 (not 256)
   - Check for runaway processes: `top` or web UI per-process CPU

2. **Check scheduling priorities:**
   ```bash
   chrt -p $(pgrep pipewire)     # Should be SCHED_FIFO 88
   chrt -p $(pgrep camilladsp)   # Should be SCHED_FIFO 80
   ```
   If priorities are wrong (SCHED_OTHER instead of SCHED_FIFO), the systemd overrides
   may not have been applied. Check the service drop-in files.

3. **Check CPU temperature** on web UI. Thermal throttling begins at 80 deg C.
   If temperature is high:
   - Check ventilation in the flight case
   - Reduce DSP load (switch to shorter filters if needed)

4. **Check USB errors:**
   USB isochronous transfer errors cause audio corruption. Inspect:
   ```bash
   dmesg | grep -i "usb\|xhci\|error"
   ```
   USB hub issues or cable problems are common culprits.

#### CamillaDSP Crashes

**Symptoms:** Web UI shows CamillaDSP disconnected. Audio stops.

**Diagnostic procedure:**
1. **Check crash logs:**
   ```bash
   journalctl --user -u camilladsp -n 100
   ```

2. **Common crash causes:**
   - Invalid filter WAV file (wrong sample rate, wrong number of channels, corrupt file)
   - ALSA device disappeared (USB disconnect)
   - Out of memory (unlikely with 4GB, but check if other processes are leaking)

3. **Recovery:**
   **Turn off amplifiers first** (USBStreamer transient risk), then:
   ```bash
   sudo systemctl restart camilladsp
   ```

#### High CPU / Thermal Throttling

**Symptoms:** DSP processing load climbing, temperature above 75 deg C, potential xruns.

**Diagnostic procedure:**
1. **Identify CPU consumers** via web UI per-process CPU display or:
   ```bash
   top -b -n 1 | head -20
   ```

2. **Reduce load options:**
   - Switch to 8,192-tap filters (half the FIR computation)
   - Increase chunksize (trades latency for efficiency)
   - Kill unnecessary processes (browser windows, file manager, etc.)
   - Improve ventilation (open flight case, add fan)

3. **Thermal reference points:**
   - < 65 deg C: Normal (green on web UI)
   - 65-75 deg C: Elevated but safe (yellow on web UI)
   - > 75 deg C: Concern -- take action (red on web UI)
   - > 80 deg C: Thermal throttling begins (CPU frequency reduced automatically)

#### Web UI Not Accessible

**Symptoms:** Browser cannot connect to `https://mugge:8080`.

**Diagnostic procedure:**
1. **Check web UI service:**
   ```bash
   systemctl --user status pi4-audio-webui
   journalctl --user -u pi4-audio-webui -n 50
   ```

2. **Check network connectivity:**
   ```bash
   ip addr show   # Verify Pi has an IP address
   ping mugge     # From the client device
   ```

3. **Check firewall:**
   Port 8080 MUST be allowed in nftables for phone/tablet access during shows (singer
   IEM control, engineer monitoring). This is the same risk profile as the existing
   VNC 5900 allowance.

   **Prerequisite (one-time setup):** Add `tcp dport 8080 accept` to the nftables
   ruleset. Without this rule, the web UI is only accessible from localhost (SSH
   tunnel would be required, which is impractical during a show).

   Verify the rule is present:
   ```bash
   sudo nft list ruleset | grep 8080
   ```
   If missing, add it to the nftables configuration and reload:
   ```bash
   # Add to the input chain in /etc/nftables.conf:
   #   tcp dport 8080 accept
   sudo nft add rule inet filter input tcp dport 8080 accept
   ```

4. **Self-signed certificate issues:**
   The first connection to the HTTPS endpoint requires accepting the self-signed
   certificate. If the browser refuses: try clearing certificate cache or navigating
   directly to `https://<pi-ip>:8080` by IP address.

#### MIDI Controller Not Responding

**Symptoms:** MIDI controller LEDs on but no response in Mixxx/Reaper.

**Diagnostic procedure:**
1. **Check USB enumeration:**
   ```bash
   lsusb | grep -i "akai\|hercules\|nektar"
   ```

2. **Check MIDI device visibility:**
   ```bash
   aconnect -l   # List MIDI connections
   ```

3. **Check MIDI mapping in the application:**
   - Mixxx: Preferences -> Controllers -> verify mapping is loaded
   - Reaper: Preferences -> MIDI Devices -> verify device is enabled

4. **Hercules DJControl Mix Ultra caveat:** This controller is Bluetooth-primary.
   USB-MIDI functionality on Linux is unverified (assumption A6). If USB-MIDI does not
   work, Bluetooth pairing may be required.

### General Diagnostic Checklist

For any undiagnosed issue, work through this checklist:

1. [ ] Web UI accessible and showing current data?
2. [ ] CamillaDSP state = "Running"?
3. [ ] PipeWire running at correct priority (SCHED_FIFO 88)?
4. [ ] CamillaDSP at correct priority (SCHED_FIFO 80)?
5. [ ] USB devices (USBStreamer, UMIK-1, MIDI controllers) enumerated?
6. [ ] ALSA devices listed (`aplay -l`, `arecord -l`)?
7. [ ] CPU temperature below 75 deg C?
8. [ ] DSP processing load below budget threshold?
9. [ ] Xrun count = 0?
10. [ ] No USB errors in `dmesg`?

### Web UI Touchpoints

- **Engineer Dashboard** -- Primary diagnostic interface
- **System health tab** -- Detailed CPU, temperature, memory, PipeWire status
- **DSP health section** -- CamillaDSP state, processing load, buffer level, clipped samples
- All diagnostic data refreshes automatically (system health at 1Hz, levels at 10Hz)

---

## Appendix A: Quick Reference -- Signal Chain

```
Source Material (-14 LUFS nominal, -0.5 LUFS worst case for psytrance)
    |
    v
Mixxx / Reaper (application, via pw-jack JACK bridge)
    |
    v
PipeWire — single audio graph (SCHED_FIFO 88)
    |
    +-- filter-chain convolver (FFTW3 + ARM NEON, within same graph cycle)
    |   |-- FIR convolution: combined crossover + room correction (<= -0.5dB, D-009)
    |   |-- Per-channel gain: linear builtin Mult params (C-009)
    |   |-- Per-channel delay: time alignment
    |   |-- 4 speaker channels (mains HP + subs LP, 16,384 taps each)
    |
    +-- Direct PipeWire links (bypass convolver)
    |   |-- Engineer headphones (ch 5-6)
    |   |-- Singer IEM (ch 7-8, live mode only)
    |
    v
USBStreamer (hw:USBStreamer,0) -- 8ch ADAT output
    |
    v
ADA8200 (ADAT-to-analog, 0dBFS = +18dBu)
    |
    v
Amplifier (26dB gain, 4x450W Class D)
    |
    v
Speakers (mains ch 1-2, subs ch 3-4, HP ch 5-6, IEM ch 7-8)
```

## Appendix B: Key File Locations

| File | Location | Purpose |
|------|----------|---------|
| DJ/PA CamillaDSP config | `configs/camilladsp/production/dj-pa.yml` | DJ mode DSP pipeline |
| Live CamillaDSP config | `configs/camilladsp/production/live.yml` | Live mode DSP pipeline |
| Combined FIR filters | `/etc/camilladsp/coeffs/combined_*.wav` | Deployed correction filters |
| Speaker identities | `configs/speakers/identities/*.yml` | Speaker hardware specs |
| Speaker profiles | `configs/speakers/profiles/*.yml` | System topology + crossover |
| Room correction pipeline | `src/room-correction/runner.py` | Filter generation CLI |
| UMIK-1 calibration | `/home/ela/7161942.txt` | Microphone frequency correction |
| PipeWire config | `~/.config/pipewire/pipewire.conf.d/10-audio-settings.conf` | Audio server settings |
| Web UI | `src/web-ui/` | Monitoring dashboard source |

## Appendix C: Decisions Referenced

| ID | Summary | Impact on User Journeys |
|----|---------|------------------------|
| D-002/D-011 | Dual chunksize (2048 DJ / 256 live) | Mode-dependent latency and CPU tradeoff |
| D-009 | Cut-only correction with -0.5dB margin | All filters must attenuate, never boost |
| D-013/D-022 | PREEMPT_RT with hardware V3D GL | Single kernel for both modes |
| D-018 | wayvnc for remote access | VNC on tablet for remote maintenance |
| D-020 | Web UI architecture | Monitoring and control during shows |
| D-029 | Per-speaker gain staging limits | max_boost_db and mandatory_hpf_hz |
| D-032 | HTTPS for web UI | Self-signed cert, accept on first connection |
