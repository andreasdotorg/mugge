# Zynq Platform Exploration

The Pi 4B audio workstation works. The CPU benchmarks confirmed that 16,384-tap
FIR convolution on four channels at chunksize 256 uses approximately 34% of a
single Cortex-A72 core in the production configuration. The PREEMPT_RT kernel
provides bounded scheduling latency. The system is stable under sustained load.

But the Pi 4B was never designed for real-time audio. Its USB bus is shared
between the audio interface, three MIDI controllers, and a measurement
microphone. Its ARM cores run CamillaDSP's FFT convolution through LLVM
auto-vectorized NEON instructions rather than hand-tuned DSP code. The ADAT
audio stream passes through a USB-to-ADAT bridge (the miniDSP USBStreamer)
because the Pi has no native ADAT interface. Each of these is a layer of
indirection that adds latency, complexity, or both.

Given the current platform's success, the natural question is: what would a
purpose-built platform look like? Specifically, what would a Xilinx Zynq-based
system offer -- an FPGA for deterministic DSP processing alongside ARM cores
for the software stack, with a direct ADAT interface eliminating the USB audio
bridge entirely?

This document explores that question. It is not a proposal or a commitment. It
is a feasibility sketch: what is possible, what it would cost, and what the
rough implementation would look like.

---

## Platform Selection

The Zynq family spans two generations. The Zynq-7000 series pairs dual-core
Cortex-A9 processors (up to 866MHz) with 28nm FPGA fabric. The Zynq UltraScale+
(ZU+) series pairs quad-core Cortex-A53 processors (up to 1.5GHz) with 16nm
fabric and significantly more DSP resources.

For this project, the ZU+ is the stronger candidate. The Zynq-7000's Cortex-A9
cores are roughly one-third the single-thread performance of the Pi 4B's
Cortex-A72. Even with FIR convolution offloaded to FPGA, the ARM side still
needs to run PipeWire, Mixxx, Reaper, the measurement pipeline, and a web UI.
The A9 cannot realistically handle this workload. The ZU+'s quad-core
Cortex-A53 at 1.2-1.5GHz is closer to viable -- not as fast as the A72
per-core, but with four cores and modern NEON, it can likely handle the
remaining software stack.

The recommended device is the ZU5EV, as found on the AMD Kria KV260
development board. It provides:

- Quad-core Cortex-A53 at 1.333GHz (application processing)
- Dual-core Cortex-R5F (available for real-time tasks)
- 1,248 DSP48E2 slices (FPGA DSP resources)
- 117,120 LUTs (FPGA logic)
- 2.25MB block RAM
- Mali-400 GPU (OpenGL ES 2.0, needed for Mixxx waveform display)
- 4GB DDR4 shared between ARM and FPGA via AXI interconnect

Several ZU+ boards are available at different price points. The KV260 is the
conservative choice (best documentation, AMD-provided Ubuntu image, active
community). Budget alternatives exist for the 4-channel scope where the full
ZU5EV capacity is not needed:

| Board | Zynq Part | DSP Slices | BRAM | RAM | Price (approx.) |
|-------|-----------|-----------|------|-----|-----------------|
| AMD Kria KV260 (recommended) | ZU5EV | 1,248 | 2.25MB | 4GB DDR4 | ~$350 |
| Used Kria KR260 | ZU5EV | 1,248 | 2.25MB | 4GB DDR4 | ~$180-250 used |
| ALINX AXU3EG (budget alternative) | ZU3EG | 360 | 0.95MB | 2-4GB DDR4 | ~$200-250 |
| MYiR MYC-CZU3EG | ZU3EG | 360 | 0.95MB | 2-4GB DDR4 | ~$150-200 (SOM + carrier) |
| Trenz TE0820 | ZU3EG | 360 | 0.95MB | 2-4GB DDR4 | ~250 EUR (SOM + carrier) |
| Ultra96-V2 (Avnet) | ZU3EG | 360 | 0.95MB | 2GB DDR4 | ~$250 |

All ZU3EG boards provide 360 DSP slices -- adequate for the 4-channel FIR
workload (11-16 slices needed) with room for dual ADAT and future expansion.
The ZU5EV's 1,248 slices and 2.25MB BRAM provide more headroom for scaling
beyond 4 channels. The ZU2CG was evaluated but eliminated: its dual-core A53
cannot run Mixxx alongside PipeWire, and the 2GB DDR4 on available boards is
insufficient for the full software stack.

The KV260 is the architect's recommended board. While the ALINX AXU3EG saves
~$100-150, the savings are a false economy: the KV260 provides AMD's official
Ubuntu BSP, active community support, and accessible documentation that
significantly reduce bringup time. The ALINX boards require more BSP
integration effort with less community backing. For a project where FPGA
bringup is already the primary risk, choosing the best-supported platform is
worth the premium.

*Prices are from early 2025 and should be verified before purchase.*

Neither platform is commodity-priced like the Pi 4B (~$75), but even the
cheapest viable board replaces both the Pi and the USBStreamer (~$200),
narrowing the net cost gap significantly.

---

## FPGA FIR Capacity

The core question: can the FPGA fabric handle 16,384-tap FIR convolution for
four channels with deterministic timing?

Each DSP48E2 slice performs a 27x18-bit multiply-accumulate per clock cycle with
a 48-bit accumulator. At a 300MHz fabric clock (conservative for 16nm ZU+), one
slice produces 300 million multiply-accumulate operations per second. A single
48kHz audio channel with 16,384 taps requires 16,384 x 48,000 = 786 million
MACs per second. At 300MHz, the ratio of clock cycles to sample period is
roughly 6,250:1, meaning each DSP slice can process multiple taps per sample
period. A four-channel 16,384-tap engine requires only 11-16 DSP48E2 slices
depending on the pipeline architecture.

The ZU5EV provides 1,248 slices; the ZU3EG provides 360. Even on the smaller
device, our workload uses under 5% of available DSP capacity. This leaves
substantial headroom: the same fabric could support 65,536-tap filters (four
times our current length) or expand to eight corrected channels without
approaching resource limits. The FPGA is not the bottleneck.

Block RAM for coefficient storage is similarly comfortable. Four channels of
16,384 taps at 24-bit coefficients requires approximately 192KB -- well within
the ZU5EV's 2.25MB of block RAM (or even the ZU3EG's 0.95MB).

FPGA power consumption under sustained DSP load is estimated at 3-5W for the
convolution engine -- comparable to the Pi 4B's CPU consumption under
CamillaDSP load, but with deterministic timing guarantees that the Pi cannot
match.

---

## Audio Quality

### Accumulator Precision

CamillaDSP processes audio in 64-bit floating-point. Moving convolution to FPGA
means moving to fixed-point arithmetic. The question is whether fixed-point
precision is adequate.

The DSP48E2 slice provides 27x18-bit multiply-accumulate with a 48-bit
accumulator. A naive 24-bit-throughout implementation would not suffice. With
16,384 taps, the accumulated rounding error from 24-bit multiplication degrades
the noise floor below the level that 24-bit audio demands. However, the 48-bit
accumulator provides sufficient headroom for the full multiply-accumulate chain:
24-bit samples multiplied by 18-bit coefficients produce 42-bit products, and
accumulating 16,384 such products requires 14 additional bits of headroom
(log2 of 16,384), totaling 56 bits worst-case. With proper scaling, this fits
within the 48-bit accumulator. The final result is truncated to 24-bit output
only after accumulation is complete, preserving precision where it matters.

The 48-bit accumulator width is standard in Xilinx DSP48 slices precisely
because FIR filter accumulation is one of the primary use cases for FPGA-based
DSP. The precision is adequate for professional-quality audio processing.

### Coefficient Quantization

The filter coefficients generated by the measurement pipeline are 64-bit
floating-point values. Quantizing them to 18-bit or 24-bit fixed-point
introduces quantization noise. For minimum-phase FIR room correction filters,
this quantization noise is well below the noise floor of the ADA8200's analog
output stage. The practical impact on audio quality is negligible.

Verification is straightforward: convolve a test signal with the 64-bit
floating-point filter and with the quantized fixed-point filter, then compare
the outputs. If the difference is below -120dBFS (well beyond audibility), the
quantization is acceptable.

---

## Latency Analysis

The Pi 4B's audio latency is dominated by buffer periods. At the current live
mode parameters (chunksize 256, PipeWire quantum 256, per D-011), the
bone-to-electronic delay for the singer's IEM path is approximately 21
milliseconds. The PA path adds acoustic propagation on top of that. This is
within the comfortable range but leaves little margin, and the gap between IEM
and PA paths is the slapback window that D-011 was carefully designed to
minimize.

An FPGA processing path changes the latency model fundamentally. The DSP chain
from audio input to ADAT frame output is deterministic and measured in clock
cycles rather than buffer periods:

| Stage | Pi 4B (D-011) | Zynq FPGA |
|-------|---------------|-----------|
| PipeWire routing | ~5.3ms (quantum 256) | ~1.3-5.3ms (quantum 64-256) |
| ALSA loopback | ~5.3ms (one buffer) | eliminated (direct fabric path) |
| DSP processing | ~5.3ms (CamillaDSP chunksize 256) | <0.5ms (pipeline delay) |
| USB transfer | ~1ms (to USBStreamer) | eliminated (direct ADAT) |
| ADAT framing | ~0.02ms | ~0.02ms |
| **Total DSP path** | **~17ms** | **~1.8-5.8ms** |

The pure FPGA DSP path (input to ADAT output, no PipeWire) is under 1
millisecond. If the audio source still routes through PipeWire on the ARM side
(which it would for Mixxx and Reaper), PipeWire's quantum adds 1.3-5.3ms
depending on configuration. Even in the worst case, the total is roughly 6ms --
a three-fold improvement over the Pi.

For the singer's IEM path specifically, the bone-to-IEM latency drops from
approximately 21ms to approximately 1.8-5.8ms depending on PipeWire quantum. At
the low end, this approaches the point where the electronic signal arrives
before the singer's own bone-conducted sound has finished propagating. Slapback
is not merely minimized -- it is eliminated as a perceptual concern.

If the IEM path bypasses PipeWire entirely (FPGA receives audio directly from
an I2S input), the latency drops to approximately 0.7ms. This would require a
dedicated audio input on the carrier board but is architecturally feasible.

---

## ADAT Interface

The Pi 4B reaches the ADA8200 through a USB-to-ADAT bridge (the miniDSP
USBStreamer). This works, but it adds a USB hop, a dependency on a third-party
device, and a constraint to 8 channels on a single ADAT link.

An FPGA can implement the ADAT Lightpipe protocol directly in fabric. The ADAT
transmitter is a well-understood serial protocol: 8 channels of 24-bit audio
multiplexed into a single optical bitstream at 12.288MHz (for 48kHz sample
rate). Open-source HDL implementations exist (notably the adat_transmitter core
on GitHub, targeting Xilinx and Lattice FPGAs). Each transmitter core requires
fewer than 500 LUTs and no DSP slices -- negligible relative to the ZU5EV's
117,120 LUTs.

The physical interface requires one LVDS or single-ended output per ADAT link,
driving a Toslink optical transmitter module. These are commodity components
(Toshiba TOTX173, Everlight PLT133/T10, typically $2-5) that accept 3.3V TTL
input directly from FPGA I/O pins with no level shifting needed. Two Toslink
transmitters for dual ADAT is the baseline; the ZU5EV has enough I/O pins and
fabric for eight or more transmitters if the channel count grows.

Clock generation is handled by the FPGA's PLL, synthesizing the 12.288MHz ADAT
bit clock from a crystal reference with sub-nanosecond jitter -- well within
ADAT specifications and the ADA8200's receiver tolerance. For bidirectional
audio (input from ADAT), clock recovery from the incoming bitstream is needed;
for output-only operation (our primary use case), the FPGA generates its own
clock.

Eliminating the USBStreamer removes a device from the signal chain, removes a
USB dependency, and removes a potential failure point. The FPGA generates ADAT
frames directly from processed audio samples with deterministic, cycle-accurate
timing.

---

## Channel Expansion

The current system uses a single ADAT Lightpipe connection (8 channels at
48kHz) and the channel budget is fully allocated:

| Ch | Current Assignment |
|----|-------------------|
| 0-1 | Main L/R speakers (FIR crossover + correction) |
| 2-3 | Sub 1 / Sub 2 (FIR crossover + correction) |
| 4-5 | Engineer headphones (passthrough) |
| 6-7 | Singer IEM (passthrough) |

There is no room for a recording feed, a second monitor mix, a measurement
output, or expanding to a 3-way speaker configuration.

Dual ADAT provides 16 output channels at 48kHz. The second link could carry:

- A dedicated multitrack recording feed (8 channels, pre- or post-processing)
- A third monitor mix (e.g., a front-of-house reference)
- Measurement signals for real-time system monitoring
- 3-way speaker outputs: left/right wideband becomes left/right mid + left/right
  high, with dedicated crossover filters for each driver

The 3-way expansion is particularly interesting. The current 2-way crossover
(wideband + sub) is a compromise driven partly by the channel budget. With 16
channels, a 3-way configuration (high, mid, sub per side, plus IEM and
headphones) would use 10 of 16 channels, leaving 6 for recording and monitoring.

The architecture scales further still. Each ADAT transmitter core uses fewer
than 500 LUTs and one I/O pin. Eight ADAT transmitters would require fewer than
4,000 LUTs (under 4% of fabric) and eight Toslink optical modules -- providing
64 output channels at 48kHz. The DSP engine would need proportionally more DSP
slices (roughly 32-64 for 64-channel FIR at 16,384 taps), still well within the
ZU5EV's 1,248 available slices. Each additional ADAT output needs only a $2-5
Toslink transmitter module and one FPGA pin.

For context: 64 channels at 48kHz is enough for an 8-way speaker array with
independent correction per driver, multiple independent monitor mixes, a full
multitrack recording feed, and dedicated measurement outputs -- simultaneously.
The FPGA resource cost is modest; the real constraint becomes the analog side.
At approximately 160 EUR per ADA8200 (roughly 10 EUR per channel for 8in/8out
ADAT-to-analog with mic preamps), eight units for 64 channels would cost
approximately 1,280 EUR -- roughly 20 EUR per channel for the complete
digital-to-analog path including optical interface.

---

## Filter Updates

On the Pi 4B, changing FIR coefficients requires restarting CamillaDSP or using
its websocket API to reload filter files. Either approach risks a brief audio
interruption -- a gap or click during the transition.

FPGA-based convolution enables a cleaner approach: double-buffered DMA for
coefficient updates. The mechanism:

1. The ARM cores compute new filter coefficients (via the measurement pipeline).
2. The ARM writes the new coefficients into an inactive DMA buffer in shared
   DDR4 memory.
3. The FPGA's convolution engine continues processing with the active buffer.
4. On the next audio frame boundary, the DMA controller atomically swaps the
   active and inactive buffer pointers via the AXI HP port.
5. The convolution engine begins using the new coefficients on the next frame.

The transition is glitch-free by construction. There is no moment where the
convolution engine operates on partially-updated coefficients. The swap happens
between frames, synchronized to the audio clock.

This matters for the per-venue measurement workflow. The correction pipeline
could iteratively refine filters -- measure, compute, deploy, verify, adjust --
without audible interruptions between iterations. On the Pi, each iteration
requires a CamillaDSP restart; on the Zynq, the refinement loop is seamless.

---

## Software Reuse

A significant portion of the current software stack transfers directly to a
Zynq platform. The changes are concentrated in the real-time audio path; the
application layer and measurement pipeline remain largely unchanged.

### What carries over

- **Measurement pipeline** (Python with scipy/numpy): Runs on the ARM cores.
  The filter generation math does not need real-time performance -- it runs once
  at setup time. The code is identical regardless of whether convolution runs on
  ARM or FPGA. This is a key reason for building the pipeline on the Pi first:
  the measurement and filter generation code transfers directly.
- **Filter design approach**: Combined minimum-phase FIR filters, cut-only
  correction with -0.5dB safety margin, per-venue fresh measurement, four (or
  more) independent correction filters, speaker profiles and configurable
  crossover. All platform-independent decisions.
- **PipeWire audio routing**: Continues to manage application-level audio
  routing on the ARM side. The FPGA replaces the ALSA loopback + CamillaDSP
  portion of the chain.
- **Reaper**: Runs on ARM for live vocal performance. CPU requirements are
  modest once DSP is offloaded.
- **Web UI / remote access**: RustDesk or equivalent, running on ARM.

### What changes

- **CamillaDSP**: Replaced by the FPGA convolution engine. The pipeline
  configuration (filter assignments, delay values, gain trims) moves from YAML
  files to FPGA register writes via a control interface on the ARM side.
- **ALSA loopback**: Eliminated. PipeWire routes audio to the FPGA fabric
  through a DMA interface rather than through an ALSA loopback device.
- **USBStreamer**: Eliminated. The FPGA generates ADAT directly.
- **PREEMPT_RT kernel**: Still beneficial for PipeWire scheduling on the ARM
  side, but the hard real-time DSP guarantee comes from the FPGA fabric rather
  than the kernel scheduler. The safety classification (D-013) shifts from
  software-enforced to hardware-enforced.

### Risk: Mixxx on Cortex-A53

Mixxx is the most demanding application remaining on the ARM side after DSP
offload. It requires OpenGL ES rendering (for waveform displays via the ZU5EV's
Mali-400 GPU), audio decoding, and beat detection. The Cortex-A53 is comparable
to the Pi 3B+'s CPU (also quad A53 at 1.4GHz), which can run PipeWire and
lightweight desktop workloads -- but Mixxx's waveform rendering and library
management alongside PipeWire on A53 is unverified.

Whether Mixxx runs acceptably is an open question that cannot be answered by
analysis alone. It needs a benchmark on actual hardware. This is the GO/NO-GO
gate for the platform (see Recommendation).

---

## Gains and Losses

An honest comparison of what the Zynq platform would provide versus what it
costs relative to the proven Pi 4B:

| Dimension | Pi 4B (current) | Zynq UltraScale+ |
|-----------|----------------|-------------------|
| DSP latency | ~5.3ms (chunksize 256) | <0.5ms (FPGA pipeline) |
| Bone-to-IEM | ~21ms | ~1.8-5.8ms (with PipeWire) |
| Slapback risk | Managed (D-011 parameters) | Eliminated |
| Output channels | 8 (single ADAT) | 16 (dual ADAT), scalable to 64 |
| FIR headroom | ~34% CPU, 16k taps max practical | <5% DSP slices, 65k+ taps feasible |
| Real-time guarantee | Software (PREEMPT_RT) | Hardware (FPGA fabric) |
| Safety isolation | Kernel scheduler (D-013) | Silicon-level independence |
| Filter hot-swap | CamillaDSP restart/API | Glitch-free DMA swap |
| ARM performance | Cortex-A72 quad @ 1.8GHz | Cortex-A53 quad @ 1.2-1.5GHz (weaker) |
| Mixxx viability | Proven | Unknown (GO/NO-GO gate) |
| Platform cost | ~$75 (Pi 4B 8GB) | ~$200-400 total (board + peripherals) |
| USB audio bridge | Required (USBStreamer) | Eliminated |
| Community/support | Massive (Raspberry Pi) | Niche (FPGA development) |
| Setup complexity | apt-get install | FPGA bitstream + PetaLinux |
| Development skills | Linux sysadmin | FPGA/HDL + embedded Linux |
| Time to production | Operational now | 15-24 weeks estimated |

The gains are real: lower latency, more channels, hardware-level safety,
deterministic DSP. The costs are also real: higher price, niche toolchain,
smaller community, uncertain Mixxx performance, and a significant development
investment. The Pi is proven and running; the Zynq is a bet on headroom and
architectural cleanliness.

---

## Hardware: Off-the-Shelf BOM

The Zynq platform does not require a custom PCB. Everything except a trivial
breakout board is off-the-shelf.

### New Purchases

| Component | Price (approx.) | Notes |
|-----------|----------------|-------|
| Zynq UltraScale+ board | ~$150-350 | KV260 (~$350, recommended) or ALINX AXU3EG (~$200-250, budget). See Platform Selection for full comparison. |
| MicroSD 64GB A2-rated | ~$12 | Boot media for PetaLinux or Ubuntu |
| USB-C 5V/3A PD power supply | ~$15 | KV260 uses USB-C Power Delivery |
| TOSLINK TX module | ~$2.50 | Toshiba TOTX173 (through-hole, 3.3V TTL, 15 Mbps). Alternatives: Everlight PLT133/T10 (~$1-2 at LCSC) |
| TOSLINK RX module | ~$2.50 | Toshiba TORX173 (through-hole, 3.3V TTL output). Alternatives: Everlight PLR135/T10 |
| TOSLINK optical cables (2x 1m) | ~$10 | Standard Toslink patch cables |
| Pin headers + wiring | ~$5 | For PMOD breakout assembly |
| **Total new purchases** | **~$200-400** | Depending on board choice |

### Already Owned (from Pi system)

The ADA8200, amplifier, all three MIDI controllers (Hercules, APCmini, SE25),
UMIK-1 measurement microphone, speakers, and subwoofers carry over unchanged.
The ADA8200 receives ADAT Lightpipe exactly as it does from the USBStreamer
today.

### No Longer Needed

| Component | Saved | Notes |
|-----------|-------|-------|
| Raspberry Pi 4B 8GB | ~$75 | Replaced by KV260 |
| miniDSP USBStreamer | ~$200 | Replaced by direct FPGA ADAT |
| Pi heatsink + fan | ~$15 | KV260 has its own thermal solution |

Net cost delta: approximately -$90 to +$110 depending on board choice ($200-400
new purchases minus $290 no longer needed). With the budget ALINX AXU3EG, the
Zynq platform could cost less than the Pi 4B + USBStreamer it replaces. The
USBStreamer elimination (~$200) is the largest single saving.

### The Only Custom Piece: PMOD-to-TOSLINK Breakout

A trivial adapter board connects the KV260's PMOD header to two TOSLINK
optical modules (one TX for ADAT output, one RX for future ADAT input).

**Recommended transmitter: Toshiba TOTX173** (or pin-compatible TOTX147).
Through-hole package with standard Toslink connector integrated. VCC range
2.7-5.5V (works directly at 3.3V FPGA I/O). TTL input, active-low (light ON
when data LOW). Maximum data rate approximately 15 Mbps -- ADAT at 48kHz runs
at 12.288 Mbps, well within margin. The only external component required is a
0.1uF decoupling capacitor on VCC. Price: approximately 2.50 EUR at
Mouser/DigiKey/Farnell, approximately 1 EUR at LCSC. Alternatives: Everlight
PLT133/T10 (1-2 EUR at LCSC), Toshiba TOTX1350 (newer, wider voltage range).

**Wiring per TOTX173 module:**
- Pin 1 (VCC) -> 3.3V from PMOD pin 6
- Pin 2 (GND) -> GND from PMOD pin 5
- Pin 3 (Data) -> FPGA PL pin directly (set Zynq I/O standard to LVCMOS33)
- 0.1uF ceramic capacitor across VCC-GND, placed close to the module

No series resistor is needed -- the TOTX173's internal LED driver handles
current limiting.

**Breakout design:**
- **Form factor:** 20x30mm perfboard (or $5 PCB from JLCPCB)
- **Connections:** 2x6 pin header plugging into KV260 PMOD connector
- **Components:** 2x TOSLINK modules (TOTX173 TX + TORX173 RX), 2x 0.1uF
  decoupling caps, pin headers
- **Pin mapping:** PMOD pin 1 -> ADAT TX data, pin 2 -> ADAT RX data,
  pin 5 -> GND, pin 6 -> 3.3V VCC
- **Build time:** Under 30 minutes on perfboard
- **Total component cost:** Under 6 EUR for dual ADAT (TX + RX)

**Ready-made alternative (no soldering):** MikroElektronika OPTO Encoder Click
boards (approximately 20 EUR each, plug-and-play with Click-to-PMOD adapters).
More expensive but zero assembly required. Generic "SPDIF optical output
modules" from AliExpress (2-5 EUR) may also work but require verification that
they contain a bare transmitter module rather than a converter IC that would
interfere with the FPGA's raw bitstream.

**For ADAT input (if needed later):** Add Toshiba TORX173 receiver modules --
same trivial wiring, TTL-level output from the module to an FPGA PL input pin.

**Note on 96kHz operation:** ADAT S/MUX at 96kHz halves the channel count per
link (4 channels at 96kHz instead of 8 at 48kHz) but does not double the
optical bitrate. The TOTX173's 15 Mbps rating is not a constraint for any
standard ADAT mode.

**Caveat:** The KV260 PMOD-to-PL pin mapping needs verification against the
carrier board schematic to confirm that the PMOD pins connect to programmable
logic (PL) I/O rather than processing system (PS) GPIO. The KR260 carrier
(same K26 SOM, different carrier board) is the fallback if the KV260 does not
expose PL pins on a user-accessible PMOD header.

### Scaling to 64 Channels

Scaling to 8 ADAT links (64 channels) requires 16 TOSLINK modules (8 TX + 8
RX) and 16 FPGA I/O pins. The KV260's single PMOD header (8 data pins) is
insufficient. The practical approach: build a "TOSLINK hat" that plugs into
the KV260's Raspberry Pi 40-pin header, which exposes additional PL pins. This
is a simple 2-layer PCB (all signals are 12.288MHz LVCMOS, no impedance control
needed) -- a weekend KiCad project, approximately $20-30 in parts. A full
custom carrier board is not justified: it would require dealing with 0.5mm-pitch
Samtec SOM connectors, USB 3.0 impedance-controlled routing, and Ethernet
magnetics -- a 4-7 week PCB design effort that provides no benefit over the
KV260 carrier for this use case.

The FPGA fabric handles 64 channels comfortably in terms of DSP slices: 168
slices for 64-channel FIR (47% of ZU3EG's 360, 13% of ZU5EV's 1,248), plus
under 4,000 LUTs for 8 ADAT transmitters. However, DSP slices alone do not
tell the full story. Coefficient memory becomes the binding constraint at scale:
64 x 16,384 taps x 4 bytes = 4MB.

The BRAM capacity determines the channel ceiling for each device:

| Device | BRAM | Max Channels (in BRAM) | Notes |
|--------|------|----------------------|-------|
| ZU3EG | 0.95MB | ~15 | Budget boards (ALINX, MYiR) |
| ZU5EV | 2.25MB | ~35 | KV260 / KR260 |
| ZU7EV | 4.5MB | 64+ | First device to hold all 64ch in BRAM |

For the current 4-channel scope, block RAM is not a concern (192KB needed vs
0.95-2.25MB available on any viable board). For 64 channels, two paths exist:

1. **DDR4 coefficient streaming** via AXI: feasible on any board with DDR4, but
   adds design complexity -- the FIR engine must pipeline coefficient fetches
   through the AXI interconnect alongside ARM memory traffic, requiring careful
   bandwidth management and adding latency to coefficient hot-swap.
2. **Larger FPGA**: The ZU7EV (4.5MB BRAM, available on boards at $1,200+) is
   the natural upgrade path if 64 channels becomes a real requirement. It holds
   all coefficients in block RAM without DDR4 streaming, keeping the FIR engine
   design simple and deterministic.

At ~$4 per TOSLINK module, the additional optical hardware for 64-channel
I/O is under $60.

---

## Work Packages

The development breaks into seven work packages spanning an estimated 15-24
weeks. This assumes one developer with FPGA experience working part-time, or a
shorter timeline with dedicated effort. The critical path runs through WP1
(the Mixxx GO/NO-GO gate) before significant FPGA investment begins.

### WP1: Platform Bringup (2-3 weeks)

Boot PetaLinux or Ubuntu on the selected SOM. Verify basic functionality: USB
devices enumerate, network works, PipeWire runs, audio applications launch.
**Benchmark Mixxx on Cortex-A53 -- this is the GO/NO-GO gate.** If Mixxx cannot
run DJ sets acceptably, evaluate whether live-only operation (Reaper only)
justifies the platform investment.

### WP2: FIR Convolution Engine (3-4 weeks)

Implement the 4-channel 16,384-tap FIR engine in HDL (Verilog or VHDL).
Synthesize for the target ZU+ device. Verify resource utilization (target:
11-16 DSP48E2 slices), timing closure at 300MHz, and numerical accuracy against
CamillaDSP's 64-bit floating-point output using test vectors. Verify that
48-bit accumulator precision matches expectations from the audio quality
analysis.

### WP3: ADAT Transmitter (2-3 weeks)

Integrate or adapt an open-source ADAT transmitter core. Implement dual
transmitters for 16 channels. Verify timing compliance with the ADA8200's
receiver using the FPGA's PLL-generated 12.288MHz clock. Build the Toslink
adapter board (PMOD-to-optical with commodity transceiver modules).

### WP4: DMA and Coefficient Loading (2-3 weeks)

Implement the double-buffered DMA interface between ARM and FPGA via the AXI
HP port. Build the control software on the ARM side: register interface for
filter assignment, delay values, gain trims. Verify glitch-free coefficient
swap under sustained audio load.

### WP5: Audio Pipeline Integration (2-3 weeks)

Connect PipeWire on the ARM side to the FPGA fabric through the DMA interface.
Replace the ALSA loopback + CamillaDSP chain with the FPGA path. Verify
end-to-end audio routing for both DJ and live modes.

### WP6: Measurement Pipeline Port (1-2 weeks)

Connect the existing Python measurement pipeline to the FPGA coefficient
loading interface. The pipeline code itself is unchanged; only the deployment
step changes (write to DMA buffer instead of writing WAV files and restarting
CamillaDSP).

### WP7: Validation (3-6 weeks)

Re-run the full test suite on the new platform:
- Latency measurement (equivalent of T2a/T2b)
- Stability test (equivalent of T3a/T3b -- 30-minute sustained load)
- Thermal test in flight case (equivalent of T4)
- Audio quality comparison: FPGA 48-bit fixed-point vs CamillaDSP 64-bit
  floating-point, measured at the ADA8200 analog output
- Coefficient quantization verification (18-bit and 24-bit vs 64-bit reference)
- Filter hot-swap verification under live audio
- Dual ADAT channel routing verification
- Safety isolation test: verify FPGA audio continues during ARM software crash

---

## Recommendation

Build the automated measurement and correction pipeline on the Pi 4B first.
Port the real-time DSP to Zynq as a second-generation platform.

The reasoning is pragmatic. The measurement pipeline -- sweep generation,
impulse response capture, correction filter computation, deployment,
verification -- is the same regardless of whether convolution runs on ARM or
FPGA. Building it on the Pi means it can be developed, tested, and used in
production immediately. The Pi platform is already proven and operational. The
filter design math, the measurement workflow, the verification procedures, and
the operational experience all transfer directly to a Zynq platform later.

Porting the DSP to FPGA is then a well-scoped hardware project: implement
the convolution engine, the ADAT transmitter, and the coefficient loading
interface. The pipeline that feeds it already exists and is validated.

**GO/NO-GO gate:** Before committing to the Zynq platform, benchmark Mixxx on
a Cortex-A53 (WP1). If Mixxx cannot run DJ sets acceptably on A53, the platform
is not viable for the full dual-mode use case. It might still work for
live-only operation (Reaper is lighter than Mixxx), but that would halve the
platform's value proposition.

---

*This document is an exploration, not a commitment. The Pi 4B platform is
proven and operational. A Zynq platform would be a significant engineering
investment justified only if the Pi's limitations become constraining -- for
example, if the system needs more channels, longer filters, or lower latency
than USB audio can provide.*
