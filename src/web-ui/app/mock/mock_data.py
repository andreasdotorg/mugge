"""Mock data generators for development without a Pi connection.

Generates realistic-looking audio workstation telemetry. Uses time-based
oscillations (sine waves with random phase offsets) to create natural
meter movement and CPU fluctuations.

Scenarios:
    A - Normal DJ:  Mixxx playing, moderate CPU, stable
    B - Normal Live: Reaper active, low-latency settings
    C - Stressed:    Both apps, high CPU/temp, heavy load
    D - Failure:     CamillaDSP paused, xruns climbing, degraded scheduling
    E - Idle:        No music, all levels at -120 dBFS
"""

import math
import random
import time

# 31 ISO 1/3-octave center frequencies (IEC 61260)
SPECTRUM_BANDS = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
    2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000,
    20000,
]

CHANNEL_LABELS = [
    "Main L", "Main R", "Sub 1", "Sub 2",
    "HP L", "HP R", "IEM L", "IEM R",
]

SCENARIOS = {
    "A": {
        "name": "Normal DJ",
        "mode": "dj",
        "cpu_total": 155.0,
        "cpu_cores": [82.0, 48.0, 31.5, 38.8],
        "temperature": 62.5,
        "quantum": 1024,
        "sample_rate": 48000,
        "graph_state": "running",
        "pw_policy": "SCHED_FIFO",
        "pw_priority": 88,
        "cdsp_policy": "SCHED_FIFO",
        "cdsp_priority": 80,
        "cdsp_state": "Running",
        "processing_load": 5.0,
        "capture_rate": 48000,
        "playback_rate": 48000,
        "rate_adjust": 1.0001,
        "buffer_level": 2048,
        "clipped_samples": 0,
        "xruns": 0,
        "chunksize": 2048,
        "memory_used_mb": 1024,
        "memory_total_mb": 3840,
        "mixxx_cpu": 95.0,
        "reaper_cpu": 0.0,
        "camilladsp_cpu": 5.2,
        "pipewire_cpu": 7.1,
        "labwc_cpu": 4.3,
        "active_channels": [0, 1, 2, 3],
        "level_base_rms": -18.0,
        "level_base_peak": -12.0,
    },
    "B": {
        "name": "Normal Live",
        "mode": "live",
        "cpu_total": 120.0,
        "cpu_cores": [55.0, 40.0, 25.0, 30.0],
        "temperature": 58.0,
        "quantum": 256,
        "sample_rate": 48000,
        "graph_state": "running",
        "pw_policy": "SCHED_FIFO",
        "pw_priority": 88,
        "cdsp_policy": "SCHED_FIFO",
        "cdsp_priority": 80,
        "cdsp_state": "Running",
        "processing_load": 19.0,
        "capture_rate": 48000,
        "playback_rate": 48000,
        "rate_adjust": 1.0000,
        "buffer_level": 512,
        "clipped_samples": 0,
        "xruns": 0,
        "chunksize": 256,
        "memory_used_mb": 980,
        "memory_total_mb": 3840,
        "mixxx_cpu": 0.0,
        "reaper_cpu": 65.0,
        "camilladsp_cpu": 18.0,
        "pipewire_cpu": 9.5,
        "labwc_cpu": 3.8,
        "active_channels": [0, 1, 2, 3, 6, 7],
        "level_base_rms": -20.0,
        "level_base_peak": -14.0,
    },
    "C": {
        "name": "Stressed",
        "mode": "dj",
        "cpu_total": 310.0,
        "cpu_cores": [92.0, 85.0, 78.0, 82.0],
        "temperature": 73.0,
        "quantum": 1024,
        "sample_rate": 48000,
        "graph_state": "running",
        "pw_policy": "SCHED_FIFO",
        "pw_priority": 88,
        "cdsp_policy": "SCHED_FIFO",
        "cdsp_priority": 80,
        "cdsp_state": "Running",
        "processing_load": 35.0,
        "capture_rate": 48000,
        "playback_rate": 48000,
        "rate_adjust": 1.0003,
        "buffer_level": 1800,
        "clipped_samples": 0,
        "xruns": 0,
        "chunksize": 2048,
        "memory_used_mb": 2800,
        "memory_total_mb": 3840,
        "mixxx_cpu": 145.0,
        "reaper_cpu": 55.0,
        "camilladsp_cpu": 28.0,
        "pipewire_cpu": 14.0,
        "labwc_cpu": 8.5,
        "active_channels": [0, 1, 2, 3, 4, 5, 6, 7],
        "level_base_rms": -14.0,
        "level_base_peak": -6.0,
    },
    "D": {
        "name": "Failure",
        "mode": "dj",
        "cpu_total": 280.0,
        "cpu_cores": [88.0, 80.0, 70.0, 75.0],
        "temperature": 78.0,
        "quantum": 1024,
        "sample_rate": 48000,
        "graph_state": "running",
        "pw_policy": "SCHED_OTHER",
        "pw_priority": 0,
        "cdsp_policy": "SCHED_OTHER",
        "cdsp_priority": 0,
        "cdsp_state": "Paused",
        "processing_load": 42.0,
        "capture_rate": 48000,
        "playback_rate": 48000,
        "rate_adjust": 0.9998,
        "buffer_level": 300,
        "clipped_samples": 12,
        "xruns": 0,
        "chunksize": 2048,
        "memory_used_mb": 3200,
        "memory_total_mb": 3840,
        "mixxx_cpu": 160.0,
        "reaper_cpu": 0.0,
        "camilladsp_cpu": 35.0,
        "pipewire_cpu": 18.0,
        "labwc_cpu": 12.0,
        "active_channels": [0, 1],
        "level_base_rms": -25.0,
        "level_base_peak": -18.0,
    },
    "E": {
        "name": "Idle",
        "mode": "dj",
        "cpu_total": 12.0,
        "cpu_cores": [5.0, 3.0, 2.0, 2.5],
        "temperature": 48.0,
        "quantum": 1024,
        "sample_rate": 48000,
        "graph_state": "running",
        "pw_policy": "SCHED_FIFO",
        "pw_priority": 88,
        "cdsp_policy": "SCHED_FIFO",
        "cdsp_priority": 80,
        "cdsp_state": "Running",
        "processing_load": 1.0,
        "capture_rate": 48000,
        "playback_rate": 48000,
        "rate_adjust": 1.0000,
        "buffer_level": 2048,
        "clipped_samples": 0,
        "xruns": 0,
        "chunksize": 2048,
        "memory_used_mb": 620,
        "memory_total_mb": 3840,
        "mixxx_cpu": 2.0,
        "reaper_cpu": 0.0,
        "camilladsp_cpu": 0.8,
        "pipewire_cpu": 1.2,
        "labwc_cpu": 2.5,
        "active_channels": [],
        "level_base_rms": -120.0,
        "level_base_peak": -120.0,
    },
}


class MockDataGenerator:
    """Generate mock telemetry for a given scenario.

    Produces two data shapes:
        monitoring() — level meters + CamillaDSP status (for /ws/monitoring)
        system()     — full system health (for /ws/system)
    """

    def __init__(self, scenario: str = "A", freeze_time: bool = False):
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario}'. "
                             f"Valid: {', '.join(sorted(SCENARIOS))}")
        self.scenario = scenario
        self.s = SCENARIOS[scenario]
        self.freeze_time = freeze_time

        if freeze_time:
            # Deterministic: fixed start, seeded RNG for identical output across runs
            self.start_time = 0.0
            self._frozen_timestamp = 1700000000.0  # fixed epoch for JSON output
            rng = random.Random(42)
            self._phase_offsets = [rng.uniform(0, 2 * math.pi) for _ in range(8)]
            self._freq_offsets = [rng.uniform(0.3, 1.7) for _ in range(8)]
        else:
            self.start_time = time.monotonic()
            self._phase_offsets = [random.uniform(0, 2 * math.pi) for _ in range(8)]
            self._freq_offsets = [random.uniform(0.3, 1.7) for _ in range(8)]

    def _elapsed(self) -> float:
        if self.freeze_time:
            return 1.0  # fixed point in time for deterministic output
        return time.monotonic() - self.start_time

    def _jitter(self, base: float, amplitude: float) -> float:
        if self.freeze_time:
            return base
        return base + random.uniform(-amplitude, amplitude)

    def _proc_jitter(self, base: float, t: float) -> float:
        if base == 0.0:
            return 0.0
        return max(0, round(self._jitter(
            base + 3.0 * math.sin(t * 0.25), 2.0
        ), 1))

    def monitoring(self) -> dict:
        """Level meters + CamillaDSP status (designed for ~10 Hz push).

        Combines level data and CamillaDSP state into one message so the
        monitor view can render meters and show DSP health without needing
        a second WebSocket.
        """
        if self.freeze_time:
            random.seed(42)
        t = self._elapsed()
        s = self.s

        # -- Level meters --
        active = set(s["active_channels"])
        capture_rms = []
        capture_peak = []
        playback_rms = []
        playback_peak = []

        for ch in range(8):
            if ch not in active:
                capture_rms.append(-120.0)
                capture_peak.append(-120.0)
                playback_rms.append(-120.0)
                playback_peak.append(-120.0)
                continue

            phase = self._phase_offsets[ch]
            freq = self._freq_offsets[ch]

            # Layered oscillation for music-like meter movement
            beat = math.sin(2 * math.pi * 2.2 * t + phase)  # ~132 BPM
            sub = 0.4 * math.sin(2 * math.pi * freq * t + phase * 1.5)
            envelope = 0.3 * math.sin(2 * math.pi * 0.08 * t + phase * 0.7)
            noise = random.uniform(-1.5, 1.5)
            combined = beat * 3.0 + sub * 2.0 + envelope * 4.0 + noise

            base_rms = s["level_base_rms"]
            base_peak = s["level_base_peak"]

            rms_val = max(-120.0, min(0.0, base_rms + combined))
            peak_val = max(-120.0, min(0.0, base_peak + combined
                                       + random.uniform(0, 2.0)))
            if peak_val < rms_val:
                peak_val = min(0.0, rms_val + random.uniform(1.0, 4.0))

            capture_rms.append(round(rms_val, 1))
            capture_peak.append(round(peak_val, 1))

            pb_offset = -2.0 + 0.5 * math.sin(t * 0.5 + ch)
            pb_rms = max(-120.0, min(0.0, rms_val + pb_offset))
            pb_peak = max(-120.0, min(0.0, peak_val + pb_offset))
            if pb_peak < pb_rms:
                pb_peak = min(0.0, pb_rms + random.uniform(1.0, 3.0))

            playback_rms.append(round(pb_rms, 1))
            playback_peak.append(round(pb_peak, 1))

        # -- CamillaDSP status (included at every tick for low-latency display) --
        processing_load = max(0, self._jitter(
            s["processing_load"] + 1.0 * math.sin(t * 0.3), 0.5
        ))
        xruns = s["xruns"]
        if self.scenario == "D":
            xruns = int(t / 3)
        buffer_level = max(0, int(self._jitter(
            s["buffer_level"] + 20 * math.sin(t * 0.4), 10
        )))
        rate_adjust = s["rate_adjust"] + 0.00002 * math.sin(t * 0.1)

        return {
            "timestamp": self._frozen_timestamp if self.freeze_time else time.time(),
            "capture_rms": capture_rms,
            "capture_peak": capture_peak,
            "playback_rms": playback_rms,
            "playback_peak": playback_peak,
            "spectrum": {
                "bands": self._spectrum(t, active),
            },
            "camilladsp": {
                "state": s["cdsp_state"],
                "processing_load": round(processing_load, 2),
                "buffer_level": buffer_level,
                "clipped_samples": s["clipped_samples"],
                "xruns": xruns,
                "rate_adjust": round(rate_adjust, 6),
                "capture_rate": s["capture_rate"],
                "playback_rate": s["playback_rate"],
                "chunksize": s["chunksize"],
            },
        }

    def _spectrum(self, t: float, active: set) -> list:
        """Generate plausible 1/3-octave spectrum mock data (31 bands).

        Pink noise slope: ~-3 dB/octave (each band ~1 dB lower).
        Random variation: +/- 4 dB per band per update.
        Occasional bass peak in 50-80 Hz range.
        Returns list of 31 floats in dB, clamped to [-60, 0].
        """
        if not active:
            return [-60.0] * 31

        base_level = self.s["level_base_rms"]
        bands = []
        for i, freq in enumerate(SPECTRUM_BANDS):
            # Pink noise slope: -3 dB per octave relative to 20 Hz
            octaves_from_base = math.log2(freq / 20.0) if freq > 0 else 0
            slope = -1.0 * octaves_from_base  # approx -1 dB per band

            # Slow envelope per band for natural movement
            env = 2.0 * math.sin(2 * math.pi * 0.15 * t + i * 0.4)

            # Random variation
            noise = random.uniform(-4.0, 4.0)

            # Bass peak simulation (50-80 Hz range, bands 4-6)
            bass_boost = 0.0
            if 4 <= i <= 6:
                bass_boost = 3.0 + 2.0 * math.sin(2 * math.pi * 0.3 * t)

            val = base_level + 10.0 + slope + env + noise + bass_boost
            bands.append(round(max(-60.0, min(0.0, val)), 1))

        return bands

    def system(self) -> dict:
        """Full system health snapshot (designed for ~1 Hz push)."""
        if self.freeze_time:
            random.seed(43)
        t = self._elapsed()
        s = self.s

        cpu_total = self._jitter(
            s["cpu_total"] + 5.0 * math.sin(t * 0.2), 3.0
        )
        cpu_cores = [
            max(0, min(100, self._jitter(
                c + 4.0 * math.sin(t * 0.15 + i * 1.2), 2.5
            )))
            for i, c in enumerate(s["cpu_cores"])
        ]
        temperature = self._jitter(
            s["temperature"] + 1.5 * math.sin(t * 0.05), 0.5
        )
        processing_load = max(0, self._jitter(
            s["processing_load"] + 1.0 * math.sin(t * 0.3), 0.5
        ))
        xruns = s["xruns"]
        if self.scenario == "D":
            xruns = int(t / 3)
        buffer_level = max(0, int(self._jitter(
            s["buffer_level"] + 20 * math.sin(t * 0.4), 10
        )))
        rate_adjust = s["rate_adjust"] + 0.00002 * math.sin(t * 0.1)
        memory_used = max(0, int(self._jitter(
            s["memory_used_mb"] + 10 * math.sin(t * 0.02), 5
        )))

        return {
            "timestamp": self._frozen_timestamp if self.freeze_time else time.time(),
            "cpu": {
                "total_percent": round(cpu_total, 1),
                "per_core": [round(c, 1) for c in cpu_cores],
                "temperature": round(temperature, 1),
            },
            "pipewire": {
                "quantum": s["quantum"],
                "sample_rate": s["sample_rate"],
                "graph_state": s["graph_state"],
                "scheduling": {
                    "pipewire_policy": s["pw_policy"],
                    "pipewire_priority": s["pw_priority"],
                    "camilladsp_policy": s["cdsp_policy"],
                    "camilladsp_priority": s["cdsp_priority"],
                },
            },
            "camilladsp": {
                "state": s["cdsp_state"],
                "processing_load": round(processing_load, 2),
                "capture_rate": s["capture_rate"],
                "playback_rate": s["playback_rate"],
                "rate_adjust": round(rate_adjust, 6),
                "buffer_level": buffer_level,
                "clipped_samples": s["clipped_samples"],
                "xruns": xruns,
                "chunksize": s["chunksize"],
            },
            "memory": {
                "used_mb": memory_used,
                "total_mb": s["memory_total_mb"],
                "available_mb": s["memory_total_mb"] - memory_used,
            },
            "mode": s["mode"],
            "processes": {
                "mixxx_cpu": self._proc_jitter(s["mixxx_cpu"], t),
                "reaper_cpu": self._proc_jitter(s["reaper_cpu"], t),
                "camilladsp_cpu": self._proc_jitter(s["camilladsp_cpu"], t),
                "pipewire_cpu": self._proc_jitter(s["pipewire_cpu"], t),
                "labwc_cpu": self._proc_jitter(s["labwc_cpu"], t),
            },
        }
