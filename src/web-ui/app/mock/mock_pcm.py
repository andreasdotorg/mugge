"""Mock PCM stream generator for spectrum display in development mode.

Generates synthetic 3-channel interleaved float32 audio data that produces
a visible spectrum when processed by spectrum.js. Uses only stdlib modules
(no numpy dependency).

Wire format (matches real PcmStreamCollector):
    - Binary WebSocket messages (arraybuffer)
    - First 4 bytes: LE uint32 frame count header
    - Remainder: interleaved float32 for 3 channels (L, R, Sub)

The synthetic signal mixes several sine tones at different frequencies
with low-level pink-ish noise for a realistic broadband floor. Active
channels and amplitude are derived from the mock scenario.
"""

import asyncio
import logging
import math
import random
import struct

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

SAMPLE_RATE = 48000
NUM_CHANNELS = 3
FRAMES_PER_CHUNK = 256  # ~5.3ms at 48kHz
SEND_INTERVAL = 0.016   # ~16ms between sends (~62 chunks/sec)

# Tone frequencies (Hz) and relative amplitudes (linear)
_TONES = [
    (100.0, 0.30),
    (440.0, 0.25),
    (1000.0, 0.15),
    (5000.0, 0.08),
    (2500.0, 0.10),
]

# Header: 4 bytes LE uint32 frame count
_HEADER_FMT = "<I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


def _db_to_linear(db: float) -> float:
    """Convert dBFS to linear amplitude."""
    if db <= -120.0:
        return 0.0
    return 10.0 ** (db / 20.0)


def _pink_noise_sample(rng: random.Random, state: list) -> float:
    """Simple pink-ish noise via Voss-McCartney algorithm (8 octaves).

    Uses a running-sum approach: on each call, one random octave
    is replaced with a new random value. The sum of all octaves
    approximates a -3dB/octave slope.
    """
    # Pick a random octave to update based on trailing zeros of a counter
    # For simplicity, just update one random octave each sample
    idx = rng.randint(0, len(state) - 1)
    state[idx] = rng.uniform(-1.0, 1.0)
    return sum(state) / len(state)


async def mock_pcm_stream(ws: WebSocket, scenario_key: str) -> None:
    """Stream synthetic PCM data over WebSocket for mock mode.

    Args:
        ws: Accepted WebSocket connection.
        scenario_key: Scenario letter (A-E) from SCENARIOS dict.
    """
    from .mock_data import SCENARIOS

    scenario = SCENARIOS.get(scenario_key, SCENARIOS["A"])
    active_channels = set(scenario.get("active_channels", []))
    peak_db = scenario.get("level_base_peak", -12.0)

    # Scale amplitude based on scenario peak level
    amplitude = _db_to_linear(peak_db)

    # Determine which of the 3 PCM channels (L=0, R=1, Sub=2) are active
    ch_active = [False] * NUM_CHANNELS
    if 0 in active_channels:
        ch_active[0] = True  # L
    if 1 in active_channels:
        ch_active[1] = True  # R
    if 2 in active_channels or 3 in active_channels:
        ch_active[2] = True  # Sub (any sub active)

    log.info(
        "Mock PCM stream started (scenario=%s, amplitude=%.3f, channels=%s)",
        scenario_key, amplitude, ch_active,
    )

    rng = random.Random()
    # Pink noise state: 8 octaves per channel
    pink_states = [[0.0] * 8 for _ in range(NUM_CHANNELS)]

    # Phase accumulators for each tone (continuous across chunks)
    tone_phases = [0.0] * len(_TONES)
    phase_increments = [
        2.0 * math.pi * freq / SAMPLE_RATE for freq, _ in _TONES
    ]

    # Slow amplitude modulation phase (simulates music dynamics)
    mod_phase = 0.0
    mod_increment = 2.0 * math.pi * 0.15 / SAMPLE_RATE  # 0.15 Hz envelope

    # Pre-compute buffer size
    floats_per_chunk = FRAMES_PER_CHUNK * NUM_CHANNELS
    chunk_fmt = f"<{floats_per_chunk}f"

    try:
        while True:
            samples = []

            for frame_idx in range(FRAMES_PER_CHUNK):
                # Slow amplitude modulation (0.5 to 1.0)
                mod = 0.75 + 0.25 * math.sin(mod_phase)
                mod_phase += mod_increment

                # Sum tones
                tone_sum = 0.0
                for t_idx, (_, rel_amp) in enumerate(_TONES):
                    tone_sum += rel_amp * math.sin(tone_phases[t_idx])
                    tone_phases[t_idx] += phase_increments[t_idx]

                # Keep phases bounded to avoid float precision loss
                for t_idx in range(len(tone_phases)):
                    if tone_phases[t_idx] > 2.0 * math.pi:
                        tone_phases[t_idx] -= 2.0 * math.pi

                # Apply modulation and overall amplitude
                signal = tone_sum * mod * amplitude

                for ch in range(NUM_CHANNELS):
                    if ch_active[ch]:
                        # Add pink noise floor
                        noise = _pink_noise_sample(rng, pink_states[ch])
                        noise_level = 0.02 * amplitude  # -34dB below signal
                        # Slight per-channel variation
                        ch_offset = 1.0 if ch < 2 else 0.7  # sub slightly lower
                        samples.append(signal * ch_offset + noise * noise_level)
                    else:
                        samples.append(0.0)

            # Keep mod_phase bounded
            if mod_phase > 2.0 * math.pi:
                mod_phase -= 2.0 * math.pi

            # Pack header + interleaved float32 data
            header = struct.pack(_HEADER_FMT, FRAMES_PER_CHUNK)
            payload = struct.pack(chunk_fmt, *samples)

            await ws.send_bytes(header + payload)
            await asyncio.sleep(SEND_INTERVAL)

    except WebSocketDisconnect:
        log.info("Mock PCM client disconnected")
    except Exception:
        log.exception("Mock PCM stream error")
