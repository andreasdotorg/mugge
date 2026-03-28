"""In-process measurement session state machine (WP-D, TK-168, US-061).

Drives IDLE -> SETUP -> GAIN_CAL -> MEASURING -> FILTER_GEN -> DEPLOY -> VERIFY -> COMPLETE.
Lives on the daemon process; survives browser disconnects.  All blocking audio
I/O dispatched via ``asyncio.to_thread()``.

Cancellation contract: 8 named points CP-0..CP-7 (see ``_check_abort`` calls).

Design (D-040): GraphManager controls measurement routing via JSON-over-TCP RPC
(port 4002). Session connects to GM for mode switching and verification.
Per-channel attenuation is handled by the signal generator (only the test
channel emits signal). Per-thread RNG; ``asyncio.wait(FIRST_COMPLETED)``
for CP-0.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

import numpy as np

log = logging.getLogger(__name__)

# True when running without real audio hardware (macOS dev, CI, e2e subprocess).
_MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"

# Path to room-correction scripts (resolved once at import time)
_RC_DIR = os.environ.get("PI4AUDIO_RC_DIR", os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "room-correction")))

# Path to measurement client modules (graph_manager_client, signal_gen_client).
_MEAS_DIR = os.environ.get("PI4AUDIO_MEAS_DIR", os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "measurement")))


def _ensure_rc_path() -> None:
    """Add room-correction dir to sys.path if needed."""
    if _RC_DIR not in sys.path:
        sys.path.insert(0, _RC_DIR)


# ---------------------------------------------------------------------------
# Measurement config constants
# ---------------------------------------------------------------------------

_MEASUREMENT_ATTENUATION_DB = float(
    os.environ.get("PI4AUDIO_MEASUREMENT_ATTENUATION_DB", "-20.0"))

# Mic clipping detection threshold.  Default -3 dBFS catches ADC
# saturation in production.  Local-demo raises to 0 because the
# room-sim convolver produces supra-unity peaks in the digital domain.
_MIC_CLIP_THRESHOLD_DBFS = float(
    os.environ.get("PI4AUDIO_MIC_CLIP_THRESHOLD_DBFS", "-3.0"))

# Gain calibration target SPL and hard limit.  Defaults match production
# (75 dB target, 84 dB hard limit).  Local-demo overrides because the
# room-sim convolver adds ~+16 dB gain — starting at -60 dBFS already
# produces ~77 dB "SPL", above the 75 dB target.
_TARGET_SPL_DB: Optional[float] = (
    float(os.environ["PI4AUDIO_TARGET_SPL_DB"])
    if "PI4AUDIO_TARGET_SPL_DB" in os.environ else None)
_HARD_LIMIT_SPL_DB: Optional[float] = (
    float(os.environ["PI4AUDIO_HARD_LIMIT_SPL_DB"])
    if "PI4AUDIO_HARD_LIMIT_SPL_DB" in os.environ else None)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class MeasurementState(enum.Enum):
    IDLE = "idle"
    SETUP = "setup"
    GAIN_CAL = "gain_cal"
    MEASURING = "measuring"
    FILTER_GEN = "filter_gen"
    DEPLOY = "deploy"
    VERIFY = "verify"
    COMPLETE = "complete"
    ABORTED = "aborted"
    ERROR = "error"


_TRANSITIONS: Dict[MeasurementState, tuple] = {
    MeasurementState.IDLE:       (MeasurementState.SETUP,),
    MeasurementState.SETUP:      (MeasurementState.GAIN_CAL, MeasurementState.ABORTED, MeasurementState.ERROR),
    MeasurementState.GAIN_CAL:   (MeasurementState.MEASURING, MeasurementState.ABORTED, MeasurementState.ERROR),
    MeasurementState.MEASURING:  (MeasurementState.FILTER_GEN, MeasurementState.ABORTED, MeasurementState.ERROR),
    MeasurementState.FILTER_GEN: (MeasurementState.DEPLOY, MeasurementState.ABORTED, MeasurementState.ERROR),
    MeasurementState.DEPLOY:     (MeasurementState.VERIFY, MeasurementState.ABORTED, MeasurementState.ERROR),
    MeasurementState.VERIFY:     (MeasurementState.COMPLETE, MeasurementState.ABORTED, MeasurementState.ERROR),
    MeasurementState.COMPLETE:   (),
    MeasurementState.ABORTED:    (),
    MeasurementState.ERROR:      (),
}


class _AbortError(Exception):
    """Internal — raised at cancellation points, caught by ``run()``."""


# ---------------------------------------------------------------------------
# Abort adapter
# ---------------------------------------------------------------------------

class _AbortAdapter:
    """Bridges ``session.abort_event`` to the ``ws_server.abort_requested``
    interface expected by ``gain_calibration.calibrate_channel()``.
    """

    def __init__(self, abort_event: asyncio.Event,
                 broadcast_queue: asyncio.Queue,
                 loop: asyncio.AbstractEventLoop) -> None:
        self._event = abort_event
        self._queue = broadcast_queue
        self._loop = loop

    @property
    def abort_requested(self) -> bool:
        return self._event.is_set()

    def broadcast(self, message: dict) -> None:
        try:
            self._queue.put_nowait(message)
            self._loop.call_soon_threadsafe(lambda: None)
        except asyncio.QueueFull:
            log.warning("Broadcast queue full, dropping: %s",
                        message.get("type", "?"))


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------

class MeasurementWatchdog:
    """10-second software watchdog.  ``kick()`` is thread-safe."""

    def __init__(self, timeout_s: float = 10.0,
                 on_timeout: Optional[Callable[[], None]] = None) -> None:
        self._timeout_s = timeout_s
        self._on_timeout = on_timeout
        self._last_kick = time.monotonic()
        self._task: Optional[asyncio.Task] = None
        self._stopped = False

    def kick(self) -> None:
        self._last_kick = time.monotonic()

    async def start(self) -> None:
        self._stopped = False
        self._last_kick = time.monotonic()
        self._task = asyncio.create_task(self._run(), name="measurement-watchdog")

    async def stop(self) -> None:
        self._stopped = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stopped:
            await asyncio.sleep(1.0)
            if time.monotonic() - self._last_kick >= self._timeout_s:
                log.error("Watchdog timeout after %.1fs",
                          time.monotonic() - self._last_kick)
                if self._on_timeout:
                    self._on_timeout()
                return


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChannelConfig:
    index: int
    name: str
    target_spl_db: float = 75.0
    thermal_ceiling_dbfs: float = -20.0
    mandatory_hpf_hz: Optional[float] = None
    speaker_key: Optional[str] = None  # Maps to speaker profile key (e.g. "sat_left")


@dataclass
class SessionConfig:
    channels: List[ChannelConfig]
    positions: int = 1
    sweep_duration_s: float = 5.0
    sweep_level_dbfs: float = -20.0
    hard_limit_spl_db: float = 84.0
    umik_sensitivity_dbfs_to_spl: float = 121.4
    calibration_file: Optional[str] = None
    output_dir: str = "/tmp/pi4audio-measurement"
    gm_host: str = "127.0.0.1"
    gm_port: int = 4002
    output_device: Optional[Any] = None
    input_device: Optional[Any] = None
    sample_rate: int = 48000
    input_device_name: str = "UMIK"        # Substring match for UMIK-1
    output_device_name: str = "pipewire"   # Must match PipeWire sink, not ALSA sysdefault
    profile_name: Optional[str] = None     # Speaker profile for filter generation

    def __post_init__(self):
        # In mock mode, default to synthetic device indices.
        # These are also correct for SignalGenClient (sd_override) which
        # uses index 0 = output sink, 1 = UMIK-1 capture.
        if _MOCK_MODE:
            if self.output_device is None:
                self.output_device = 0
            if self.input_device is None:
                self.input_device = 1


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class MeasurementSession:
    """In-process measurement session driving the full lifecycle.

    Parameters
    ----------
    config : SessionConfig
    ws_broadcast : async callback ``(msg: dict) -> None``, injected by WP-E
    sd_override : MockSoundDevice or None (for testing)
    """

    def __init__(self, config: SessionConfig,
                 ws_broadcast: Callable[[dict], Awaitable[None]],
                 sd_override: Any = None) -> None:
        self._config = config
        self._ws_broadcast = ws_broadcast
        self._sd_override = sd_override

        self._state = MeasurementState.IDLE
        self._started_at: Optional[datetime] = None
        self._finished_at: Optional[datetime] = None
        self._error_message: Optional[str] = None

        self.abort_event = asyncio.Event()
        self._abort_reason: Optional[str] = None

        self._current_channel_idx: int = 0
        self._current_position: int = 0
        self._progress_pct: float = 0.0
        self._gain_cal_results: Dict[int, Any] = {}
        self._sweep_results: Dict[str, Any] = {}

        self._filter_gen_result: Optional[Dict[str, Any]] = None
        self._deploy_result: Optional[Dict[str, Any]] = None
        self._recordings: Dict[str, np.ndarray] = {}  # US-096: raw recordings for cal
        # Deconvolved impulse responses per channel/position (populated after
        # each sweep by deconvolution; used by _build_correction_filters for
        # spatial averaging).
        self._impulse_responses: Dict[str, np.ndarray] = {}
        # Time alignment delays computed from impulse responses (seconds).
        self._time_alignment_delays: Dict[str, float] = {}

        self._broadcast_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._watchdog = MeasurementWatchdog(
            timeout_s=10.0, on_timeout=self._on_watchdog_timeout)
        self._gm_client: Any = None
        self._pump_task: Optional[asyncio.Task] = None
        self._is_mock: bool = False
        self._quantum_overridden: bool = False
        # F-160: GM mode saved before entering measurement, restored on cleanup.
        self._pre_measurement_gm_mode: Optional[str] = None

    # -- Properties ----------------------------------------------------------

    @property
    def state(self) -> MeasurementState:
        return self._state

    @property
    def config(self) -> SessionConfig:
        return self._config

    @property
    def abort_requested(self) -> bool:
        return self.abort_event.is_set()

    # -- State transitions ---------------------------------------------------

    def _transition(self, new_state: MeasurementState) -> None:
        allowed = _TRANSITIONS.get(self._state, ())
        if new_state not in allowed:
            raise RuntimeError(
                f"Invalid transition: {self._state.value} -> {new_state.value}")
        old = self._state
        self._state = new_state
        log.info("State: %s -> %s", old.value, new_state.value)

    # -- Broadcasting --------------------------------------------------------

    async def _broadcast(self, msg: dict) -> None:
        self._watchdog.kick()
        await self._ws_broadcast(msg)

    async def _broadcast_state(self, extra: Optional[dict] = None) -> None:
        msg: dict = {"type": "session_state", "state": self._state.value}
        if extra:
            msg.update(extra)
        await self._broadcast(msg)

    async def _pump_broadcast_queue(self) -> None:
        """Drain worker-thread messages to the WS broadcast (background task)."""
        try:
            while True:
                await self._broadcast(await self._broadcast_queue.get())
        except asyncio.CancelledError:
            while not self._broadcast_queue.empty():
                try:
                    await self._broadcast(self._broadcast_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

    def _enqueue_progress(self, msg: dict) -> None:
        """Thread-safe: enqueue a progress message for the broadcast pump."""
        try:
            self._broadcast_queue.put_nowait(msg)
        except asyncio.QueueFull:
            log.warning("Broadcast queue full, dropping: %s",
                        msg.get("type", "?"))

    # -- Cancellation --------------------------------------------------------

    def request_abort(self, reason: str = "operator abort") -> None:
        if not self.abort_event.is_set():
            self._abort_reason = reason
            self.abort_event.set()
            log.info("Abort requested: %s", reason)

    def _check_abort(self, checkpoint: str) -> None:
        if self.abort_event.is_set():
            log.info("Abort at %s", checkpoint)
            raise _AbortError(self._abort_reason or "abort requested")

    # -- Main entry ----------------------------------------------------------

    async def run(self) -> None:
        """Execute the full measurement lifecycle."""
        self._started_at = datetime.now()
        self._pump_task = asyncio.create_task(
            self._pump_broadcast_queue(), name="broadcast-pump")
        await self._watchdog.start()

        try:
            # TK-199: Resolve device names to indices before any state
            # transition (fail-fast if UMIK-1 or output device not found).
            # Skipped in mock mode where __post_init__ already sets integer
            # device indices.  Also skipped when sd_override is set — the
            # SignalGenClient handles audio I/O directly and does not use
            # sounddevice device indices.
            if not _MOCK_MODE and self._sd_override is None:
                _ensure_rc_path()
                from measure_nearfield import find_device
                import sounddevice as _sd

                input_idx = find_device(
                    self._config.input_device_name, kind='input')
                if input_idx is None:
                    raise RuntimeError(
                        f"Input device '{self._config.input_device_name}' "
                        f"not found")

                # Safety: reject loopback/monitor sources -- these are
                # digital loopbacks, not a real microphone like the UMIK-1.
                input_info = _sd.query_devices(input_idx)
                input_name = input_info.get('name', '')
                _LOOPBACK_KEYWORDS = ("monitor", "pipewire", "default")
                for keyword in _LOOPBACK_KEYWORDS:
                    if keyword in input_name.lower():
                        raise RuntimeError(
                            f"Resolved input device '{input_name}' "
                            f"(index {input_idx}) appears to be a loopback "
                            f"source (matched '{keyword}'), not a real "
                            f"microphone. Check that UMIK-1 is connected.")

                output_idx = find_device(
                    self._config.output_device_name, kind='output')
                if output_idx is None:
                    raise RuntimeError(
                        f"Output device '{self._config.output_device_name}' "
                        f"not found")

                self._config.input_device = input_idx
                self._config.output_device = output_idx

                output_info = _sd.query_devices(output_idx)
                output_name = output_info.get('name', '')
                log.info("Resolved devices: input=%d ('%s'), output=%d ('%s')",
                         input_idx, input_name,
                         output_idx, output_name)
            elif self._sd_override is not None and not _MOCK_MODE:
                # sd_override (e.g. SignalGenClient) handles all audio I/O.
                # Set synthetic device indices matching the override's
                # query_devices() output (0=output, 1=input).
                if self._config.output_device is None:
                    self._config.output_device = 0
                if self._config.input_device is None:
                    self._config.input_device = 1
                log.info("Skipping sounddevice resolution — using sd_override "
                         "(signal generator mode)")

            await self._run_setup()
            await self._run_gain_cal()
            await self._run_measuring()
            await self._run_filter_gen()
            await self._run_deploy()
            await self._run_verify()
            self._transition(MeasurementState.COMPLETE)
            self._finished_at = datetime.now()
            await self._broadcast_state()
        except _AbortError as exc:
            await self._handle_abort(str(exc))
        except asyncio.CancelledError:
            # Task cancelled by /reset endpoint (F-049).  Treat as abort.
            # Uncancel so that subsequent awaits in _handle_abort and
            # _cleanup don't raise CancelledError again.
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            await self._handle_abort("task cancelled (reset)")
        except Exception as exc:
            log.exception("Session error")
            self._error_message = str(exc)
            try:
                self._transition(MeasurementState.ERROR)
            except RuntimeError:
                self._state = MeasurementState.ERROR
            self._finished_at = datetime.now()
            await self._broadcast_state({"error": str(exc)})
        finally:
            await self._cleanup()

    # -- Measurement mode management (D-040: GraphManager) --------------------

    async def _enter_measurement_mode(self) -> None:
        """Switch GraphManager to measurement routing mode.

        In measurement mode, GM establishes: signal-gen -> filter-chain,
        UMIK-1 capture active. All non-measurement links are torn down.
        Saves the current mode for restoration on cleanup (F-160).

        In mock mode, uses MockGraphManagerClient (no-op).
        """
        if self._gm_client is None:
            log.warning("No GraphManager client — skipping mode switch")
            return

        # F-160: Save the current GM mode before switching.
        try:
            self._pre_measurement_gm_mode = await asyncio.to_thread(
                self._gm_client.get_mode)
            log.info("F-160: Saved pre-measurement GM mode: %s",
                     self._pre_measurement_gm_mode)
        except Exception as exc:
            log.warning("F-160: Failed to query GM mode: %s — "
                        "will restore to monitoring", exc)
            self._pre_measurement_gm_mode = "monitoring"

        try:
            await asyncio.to_thread(self._gm_client.enter_measurement_mode)
            # Verify the mode was actually set.
            mode = await asyncio.to_thread(self._gm_client.get_mode)
            if mode != "measurement":
                raise RuntimeError(
                    f"GraphManager did not enter measurement mode "
                    f"(current mode: {mode}). Aborting for safety.")
            log.info("GraphManager switched to measurement mode")
        except Exception:
            # On failure, try to restore the previous mode.
            try:
                target = self._pre_measurement_gm_mode or "monitoring"
                await asyncio.to_thread(
                    self._gm_client.set_mode, target)
            except Exception:
                pass
            raise

    # -- SETUP ---------------------------------------------------------------

    async def _run_setup(self) -> None:
        self._transition(MeasurementState.SETUP)
        await self._broadcast_state()
        await self._connect_gm()
        if self._gm_client is not None:
            try:
                state = await asyncio.to_thread(self._gm_client.get_state)
                log.info("GraphManager state: mode=%s", state.get("mode"))
            except Exception as exc:
                log.warning("GraphManager state check failed: %s", exc)

        await self._broadcast({"type": "setup_complete"})

    # -- GAIN_CAL ------------------------------------------------------------

    async def _run_gain_cal(self) -> None:
        self._transition(MeasurementState.GAIN_CAL)
        await self._broadcast_state()

        # D-040: Switch GM to measurement mode once (covers all channels).
        # The signal generator handles per-channel selection.
        await self._enter_measurement_mode()

        _ensure_rc_path()
        from gain_calibration import calibrate_channel, set_mock_sd

        # US-067 Track A: When using signal-gen mode, pass the
        # SignalGenClient directly as signal_gen for the new separated
        # play + pw-record capture pattern.  In mock mode, keep the old
        # set_mock_sd path (MockSoundDevice provides playrec()).
        _siggen_client = None
        _cap_target = None
        if self._sd_override is not None and not self._is_mock:
            _siggen_client = self._sd_override
            if _MEAS_DIR not in sys.path:
                sys.path.insert(0, _MEAS_DIR)
            import pw_capture as _pwc
            _cap_target = _pwc.DEFAULT_TARGET
        elif self._sd_override is not None:
            set_mock_sd(self._sd_override)

        adapter = _AbortAdapter(self.abort_event, self._broadcast_queue, asyncio.get_running_loop())
        for i, ch in enumerate(self._config.channels):
            self._check_abort("CP-2")  # between channels
            self._current_channel_idx = i
            await self._broadcast({
                "type": "gain_cal_start", "channel": ch.index,
                "channel_name": ch.name,
                "channel_num": i + 1,
                "channel_total": len(self._config.channels),
            })
            # CP-1 checked inside calibrate_channel via adapter.abort_requested
            _eff_attenuation = (
                0.0 if self._is_mock
                else _MEASUREMENT_ATTENUATION_DB)
            _eff_target = _TARGET_SPL_DB if _TARGET_SPL_DB is not None else ch.target_spl_db
            _eff_limit = _HARD_LIMIT_SPL_DB if _HARD_LIMIT_SPL_DB is not None else self._config.hard_limit_spl_db
            result = await asyncio.to_thread(
                calibrate_channel,
                channel_index=ch.index,
                target_spl_db=_eff_target,
                hard_limit_spl_db=_eff_limit,
                sample_rate=self._config.sample_rate,
                output_device=self._config.output_device,
                input_device=self._config.input_device,
                umik_sensitivity_dbfs_to_spl=self._config.umik_sensitivity_dbfs_to_spl,
                thermal_ceiling_dbfs=ch.thermal_ceiling_dbfs,
                gm_client=self._gm_client,
                ws_server=adapter, channel_name=ch.name,
                measurement_attenuation_db=_eff_attenuation,
                signal_gen=_siggen_client,
                capture_target=_cap_target,
                mic_clip_threshold_dbfs=_MIC_CLIP_THRESHOLD_DBFS,
            )
            self._gain_cal_results[ch.index] = result
            if not result.passed:
                if self.abort_requested:
                    raise _AbortError(self._abort_reason or "gain cal abort")
                raise RuntimeError(
                    f"Gain cal failed for {ch.name}: {result.abort_reason}")
            await self._broadcast({
                "type": "gain_cal_done", "channel": ch.index,
                "channel_name": ch.name,
                "calibrated_level_dbfs": result.calibrated_level_dbfs,
                "measured_spl_db": result.measured_spl_db,
                "steps_taken": result.steps_taken,
            })

        if self._is_mock and self._sd_override is not None:
            set_mock_sd(None)
        log.info("Gain cal complete for %d channels",
                 len(self._config.channels))

    # -- MEASURING -----------------------------------------------------------

    async def _verify_measurement_mode_active(self) -> None:
        """Check that GraphManager is still in measurement mode.

        In mock mode, skips the check.
        """
        if self._is_mock or self._gm_client is None:
            return
        try:
            await asyncio.to_thread(self._gm_client.verify_measurement_mode)
            log.info("GraphManager measurement mode verified")
        except RuntimeError:
            raise
        except Exception as exc:
            log.warning("GraphManager mode verification failed: %s", exc)

    @staticmethod
    def _check_recording_integrity(recording: np.ndarray,
                                   channel_name: str,
                                   ) -> None:
        """Validate recording integrity after a sweep.

        Checks peak level, clipping, DC offset, and SNR.  Raises
        ``RuntimeError`` on any failure.

        The peak ceiling is adjusted by ``_MEASUREMENT_ATTENUATION_DB``.
        In production (-20 dB attenuation), the ADC-clipping ceiling is
        -1 dBFS.  In local-demo (0 dB attenuation, digital loopback),
        convolution can produce supra-unity peaks, so the ceiling rises
        proportionally.
        """
        peak = float(np.max(np.abs(recording)))
        peak_dbfs = 20.0 * np.log10(max(peak, 1e-10))

        rms = float(np.sqrt(np.mean(recording ** 2)))
        rms_dbfs = 20.0 * np.log10(max(rms, 1e-10))

        dc_offset = float(abs(np.mean(recording)))

        # Estimate noise floor from last 10% of recording (post-sweep decay).
        tail_len = max(int(len(recording) * 0.1), 1)
        tail = recording[-tail_len:]
        noise_rms = float(np.sqrt(np.mean(tail ** 2)))
        noise_dbfs = 20.0 * np.log10(max(noise_rms, 1e-10))
        snr_db = rms_dbfs - noise_dbfs if noise_rms > 0 else float("inf")

        # Peak ceiling detects ADC clipping or misconfigured gain.
        # Default -1 dBFS catches near-clipping in production.
        # Local-demo sets PI4AUDIO_RECORDING_PEAK_CEILING_DBFS=20
        # because its room-sim convolver produces supra-unity peaks.
        _peak_ceiling = float(os.environ.get(
            "PI4AUDIO_RECORDING_PEAK_CEILING_DBFS", "-1.0"))

        issues: list[str] = []

        if peak_dbfs < -40.0:
            issues.append(
                f"Peak too low: {peak_dbfs:.1f} dBFS < -40 dBFS "
                f"(mic not receiving signal?)")

        if peak_dbfs > _peak_ceiling:
            issues.append(
                f"Peak too high: {peak_dbfs:.1f} dBFS > {_peak_ceiling:.1f} dBFS "
                f"(likely clipping)")

        _dc_ceiling = float(os.environ.get(
            "PI4AUDIO_RECORDING_DC_CEILING", "0.01"))
        if dc_offset > _dc_ceiling:
            issues.append(
                f"DC offset: {dc_offset:.4f} (>{_dc_ceiling}, possible ADC issue)")

        if snr_db < 20.0:
            issues.append(
                f"SNR too low: {snr_db:.1f} dB < 20 dB "
                f"(noisy environment or mic too far)")

        if issues:
            raise RuntimeError(
                f"Recording integrity check failed for {channel_name}: "
                + "; ".join(issues))

        log.info("Recording integrity OK for %s (peak=%.1f dBFS, "
                 "SNR=%.1f dB, DC=%.4f)",
                 channel_name, peak_dbfs, snr_db, dc_offset)

    async def _run_measuring(self) -> None:
        # Validate sweep level does not exceed any channel's thermal ceiling.
        max_thermal = max(ch.thermal_ceiling_dbfs for ch in self._config.channels)
        if self._config.sweep_level_dbfs > max_thermal:
            raise RuntimeError(
                f"sweep_level_dbfs ({self._config.sweep_level_dbfs}) exceeds "
                f"thermal ceiling ({max_thermal})")

        self._transition(MeasurementState.MEASURING)
        await self._broadcast_state()

        # M-2: Re-verify GraphManager is still in measurement mode.
        await self._verify_measurement_mode_active()

        _ensure_rc_path()
        import measure_nearfield as mn
        from room_correction.sweep import generate_log_sweep
        from room_correction import dsp_utils

        # US-067 Track A: In signal-gen mode, pass SignalGenClient
        # directly to play_and_record for separated play + pw-record
        # capture.  In mock mode, keep the legacy _sd_override path.
        _siggen_client = None
        _cap_target = None
        if self._sd_override is not None and not self._is_mock:
            _siggen_client = self._sd_override
            if _MEAS_DIR not in sys.path:
                sys.path.insert(0, _MEAS_DIR)
            import pw_capture as _pwc
            _cap_target = _pwc.DEFAULT_TARGET
        elif self._sd_override is not None:
            mn._sd_override = self._sd_override

        total = len(self._config.channels) * self._config.positions
        count = 0
        for pos in range(self._config.positions):
            for ch in self._config.channels:
                self._check_abort("CP-3")  # before each sweep
                if pos > 0:
                    self._check_abort("CP-4")  # between positions
                # D-040: GM measurement mode already set in _run_gain_cal.
                # Per-channel selection is handled by the signal generator.
                self._current_channel_idx = ch.index
                self._current_position = pos
                count += 1
                self._progress_pct = count / total * 100.0
                await self._broadcast({
                    "type": "sweep_start", "channel": ch.index,
                    "channel_name": ch.name, "position": pos + 1,
                    "positions_total": self._config.positions,
                    "sweep_num": count, "sweep_total": total,
                    "progress_pct": self._progress_pct,
                })
                sweep = generate_log_sweep(
                    duration=self._config.sweep_duration_s,
                    f_start=20.0, f_end=20000.0, sr=self._config.sample_rate)
                target_peak = dsp_utils.db_to_linear(
                    self._config.sweep_level_dbfs)
                peak = np.max(np.abs(sweep))
                if peak > 0:
                    sweep *= target_peak / peak
                # CP-0: race abort against playrec
                recording = await self._playrec_with_abort(
                    mn.play_and_record, sweep, ch.index,
                    self._config.output_device, self._config.input_device,
                    sr=self._config.sample_rate,
                    signal_gen=_siggen_client,
                    capture_target=_cap_target)
                # M-1: Recording integrity checks (skip in mock mode).
                if not self._is_mock:
                    self._check_recording_integrity(
                        recording, ch.name)

                # US-096: Apply UMIK-1 calibration to recording if cal file set.
                cal_applied = False
                if self._config.calibration_file and not self._is_mock:
                    try:
                        _ensure_rc_path()
                        from room_correction.recording import (
                            apply_umik1_calibration,
                        )
                        recording = await asyncio.to_thread(
                            apply_umik1_calibration,
                            recording,
                            self._config.calibration_file,
                            sr=self._config.sample_rate,
                        )
                        cal_applied = True
                    except Exception as exc:
                        log.warning(
                            "UMIK-1 cal application failed for %s: %s",
                            ch.name, exc)

                key = f"ch{ch.index}_pos{pos}"
                self._recordings[key] = recording

                # GAP-1 fix: deconvolve recording to extract impulse response.
                # Uses the same Wiener deconvolution as runner.py stage 2.
                await self._broadcast({
                    "type": "deconvolution_start",
                    "channel": ch.index, "channel_name": ch.name,
                    "position": pos + 1,
                })
                _ensure_rc_path()
                from room_correction.deconvolution import deconvolve
                ir = await asyncio.to_thread(
                    deconvolve, recording, sweep,
                    sr=self._config.sample_rate)
                self._impulse_responses[key] = ir
                await self._broadcast({
                    "type": "deconvolution_done",
                    "channel": ch.index, "channel_name": ch.name,
                    "position": pos + 1,
                    "ir_samples": len(ir),
                })

                # Save IR as WAV for inspection / offline analysis.
                ir_dir = os.path.join(self._config.output_dir, "impulse_responses")
                os.makedirs(ir_dir, exist_ok=True)
                ir_path = os.path.join(ir_dir, f"ir_{key}.wav")
                from room_correction.export import export_filter
                await asyncio.to_thread(
                    export_filter, ir, ir_path,
                    n_taps=len(ir), sr=self._config.sample_rate)
                log.info("Deconvolved IR for %s: %d samples, saved %s",
                         key, len(ir), ir_path)

                peak_dbfs = float(
                    20 * np.log10(max(np.max(np.abs(recording)), 1e-10)))
                self._sweep_results[key] = {
                    "channel": ch.index, "position": pos,
                    "recording_samples": len(recording),
                    "peak_dbfs": peak_dbfs,
                    "calibration_applied": cal_applied,
                }
                await self._broadcast({
                    "type": "sweep_done", "channel": ch.index,
                    "channel_name": ch.name, "position": pos + 1,
                    "sweep_num": count, "sweep_total": total,
                    "progress_pct": self._progress_pct,
                    "peak_dbfs": peak_dbfs,
                })

            # All channels done for this position — notify frontend.
            # For multi-position sessions the wizard prompts mic repositioning
            # before the next position starts.
            is_last = (pos == self._config.positions - 1)
            await self._broadcast({
                "type": "position_complete",
                "position": pos + 1,
                "positions_total": self._config.positions,
                "is_last": is_last,
            })

        if self._is_mock and self._sd_override is not None:
            mn._sd_override = None
        log.info("Sweep phase complete: %d sweeps", count)

        # GAP-1 fix: compute time alignment delays from deconvolved IRs.
        # Uses one representative IR per channel (position 0) — same approach
        # as runner.py stage 3.
        if self._impulse_responses:
            _ensure_rc_path()
            from room_correction import time_align
            repr_irs: Dict[str, np.ndarray] = {}
            for ch in self._config.channels:
                ir_key = f"ch{ch.index}_pos0"
                if ir_key in self._impulse_responses:
                    repr_irs[ch.name] = self._impulse_responses[ir_key]
            if repr_irs:
                self._time_alignment_delays = time_align.compute_delays(
                    repr_irs, sr=self._config.sample_rate)
                delay_samples = time_align.delays_to_samples(
                    self._time_alignment_delays, sr=self._config.sample_rate)
                for name, delay_s in self._time_alignment_delays.items():
                    log.info("Time align %s: %.2fms (%d samples)",
                             name, delay_s * 1000, delay_samples[name])
                # Save delays to output dir for deployment.
                import yaml as _yaml
                delays_path = os.path.join(
                    self._config.output_dir, "delays.yml")
                os.makedirs(self._config.output_dir, exist_ok=True)
                with open(delays_path, "w") as f:
                    _yaml.dump({
                        "delays_ms": {
                            k: float(round(v * 1000, 3))
                            for k, v in self._time_alignment_delays.items()
                        },
                        "delays_samples": {
                            k: int(v) for k, v in delay_samples.items()
                        },
                    }, f, default_flow_style=False)
                log.info("Saved time alignment to %s", delays_path)

    # -- Spatial averaging ---------------------------------------------------

    def _build_correction_filters(
        self, profile: dict,
    ) -> Optional[Dict[str, np.ndarray]]:
        """Build per-speaker-key correction filters from impulse responses.

        Reads from ``_impulse_responses`` (deconvolved IRs), NOT raw
        ``_recordings`` (unprocessed sweeps).  For positions=1, returns
        the single IR per channel directly.  For positions>1, spatially
        averages across positions per channel.

        Returns None if no impulse responses are available (e.g. when
        deconvolution has not run yet — crossover-only mode).
        """
        positions = self._config.positions
        if not self._impulse_responses:
            return None

        # Map channel index -> speaker_key
        ch_to_spk: Dict[int, str] = {}
        speakers = profile.get("speakers", {})
        for ch in self._config.channels:
            if ch.speaker_key:
                ch_to_spk[ch.index] = ch.speaker_key
            else:
                # Fallback: match by channel index in the profile
                for spk_key, spk_cfg in speakers.items():
                    if spk_cfg.get("channel") == ch.index:
                        ch_to_spk[ch.index] = spk_key
                        break

        if not ch_to_spk:
            log.warning("No channel-to-speaker mapping — skipping correction")
            return None

        correction_filters: Dict[str, np.ndarray] = {}

        for ch in self._config.channels:
            spk_key = ch_to_spk.get(ch.index)
            if spk_key is None:
                continue

            # Collect recordings for this channel across all positions
            per_position = []
            for pos in range(positions):
                key = f"ch{ch.index}_pos{pos}"
                rec = self._impulse_responses.get(key)
                if rec is not None:
                    per_position.append(rec)

            if not per_position:
                continue

            if len(per_position) == 1:
                # Single position — use directly (no averaging needed)
                correction_filters[spk_key] = per_position[0]
            else:
                # Multi-position — spatial average
                _ensure_rc_path()
                from room_correction.spatial_average import spatial_average
                correction_filters[spk_key] = spatial_average(per_position)
                log.info("Spatial average for %s: %d positions -> %d samples",
                         spk_key, len(per_position),
                         len(correction_filters[spk_key]))

        return correction_filters if correction_filters else None

    # -- FILTER_GEN ----------------------------------------------------------

    async def _run_filter_gen(self) -> None:
        """Run the FIR filter generation pipeline (crossover + room correction).

        Uses the same pipeline as filter_routes._run_pipeline() but driven
        by session config rather than a REST request.  Correction filters
        are built from deconvolved impulse responses (populated by
        _run_measuring); falls back to crossover-only when no IRs exist.
        """
        self._check_abort("CP-5")
        self._transition(MeasurementState.FILTER_GEN)
        await self._broadcast_state()

        await self._broadcast({
            "type": "filter_gen_progress", "phase": "starting",
            "message": "Generating crossover and correction filters",
        })

        try:
            result = await asyncio.to_thread(self._filter_gen_sync)
            self._filter_gen_result = result
            await self._broadcast({
                "type": "filter_gen_progress", "phase": "complete",
                "all_pass": result["all_pass"],
                "channels": result["channels"],
                "output_dir": result["output_dir"],
            })
            if not result["all_pass"]:
                raise RuntimeError(
                    "Filter verification failed — see verification results")
            log.info("Filter generation complete: %d channels, all_pass=%s",
                     len(result["channels"]), result["all_pass"])
        except _AbortError:
            raise
        except Exception as exc:
            await self._broadcast({
                "type": "filter_gen_progress", "phase": "error",
                "message": str(exc),
            })
            raise

    def _filter_gen_sync(self) -> dict:
        """Run FIR generation synchronously (called in thread pool).

        Delegates to generate_profile_filters() — the same topology-agnostic
        pipeline used by filter_routes._run_pipeline().  Handles 2-way, 3-way,
        4-way, and MEH profiles including bandpass drivers, per-driver slope
        overrides, and subsonic HPFs on any driver (not just subwoofers).
        """
        _ensure_rc_path()
        from config_generator import (
            load_profile_with_identities,
            validate_and_raise,
        )
        from room_correction.generate_profile_filters import generate_profile_filters
        from room_correction.export import export_filter
        from room_correction.verify import (
            verify_d009, verify_minimum_phase, verify_format,
        )
        from room_correction.pw_config_generator import generate_filter_chain_conf

        self._check_abort("CP-5a")

        # Resolve profile name from session config or default.
        profile_name = self._config.profile_name
        if not profile_name:
            profile_name = "2way-80hz-sealed"

        _project_root = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "..", ".."))
        profiles_dir = os.path.join(
            _project_root, "configs", "speakers", "profiles")
        identities_dir = os.path.join(
            _project_root, "configs", "speakers", "identities")

        profile, identities = load_profile_with_identities(
            profile_name,
            profiles_dir=profiles_dir,
            identities_dir=identities_dir,
        )
        validate_and_raise(
            profile, identities, identities_dir=identities_dir)

        n_taps = 16384
        sr = self._config.sample_rate

        self._check_abort("CP-5b")

        self._enqueue_progress({
            "type": "filter_gen_progress", "phase": "in_progress",
            "step": "averaging", "message": "Building correction filters",
        })

        # Build correction filters from sweep recordings.
        # For positions=1 uses the single recording; for positions>1
        # spatially averages across mic positions per channel.
        # Returns None when no recordings exist (crossover-only mode).
        correction_filters = self._build_correction_filters(profile)
        if correction_filters:
            log.info("Using %d correction filters from sweep recordings",
                     len(correction_filters))
            # GAP-6: Save IRs with speaker-key naming so filter_routes
            # _load_correction_filters() can find them for later re-generation.
            from room_correction.export import export_filter as _export_ir
            ir_out = os.path.join(self._config.output_dir, "impulse_responses")
            os.makedirs(ir_out, exist_ok=True)
            for spk_key, ir_data in correction_filters.items():
                spk_path = os.path.join(ir_out, f"ir_{spk_key}.wav")
                _export_ir(ir_data, spk_path,
                           n_taps=len(ir_data), sr=sr)
                log.info("Saved speaker-key IR: %s", spk_path)
        else:
            log.info("No correction filters — crossover-only generation")

        self._enqueue_progress({
            "type": "filter_gen_progress", "phase": "in_progress",
            "step": "crossover",
            "message": "Generating combined crossover + correction filters",
        })

        # Delegate to the topology-agnostic pipeline (handles highpass,
        # lowpass, bandpass, per-driver slopes, subsonic HPFs on any driver).
        combined_filters = generate_profile_filters(
            profile=profile,
            identities=identities,
            correction_filters=correction_filters,
            n_taps=n_taps,
            sr=sr,
        )

        self._check_abort("CP-5c")

        self._enqueue_progress({
            "type": "filter_gen_progress", "phase": "in_progress",
            "step": "export",
            "message": f"Exporting {len(combined_filters)} WAV files",
        })

        # Export WAV files
        output_dir = self._config.output_dir
        from datetime import datetime as _dt
        timestamp = _dt.now()

        os.makedirs(output_dir, exist_ok=True)
        output_paths = {}
        for spk_key, fir in combined_filters.items():
            ts = timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"combined_{spk_key}_{ts}.wav"
            path = os.path.join(output_dir, filename)
            export_filter(fir, path, n_taps=n_taps, sr=sr)
            output_paths[spk_key] = path

        self._enqueue_progress({
            "type": "filter_gen_progress", "phase": "in_progress",
            "step": "minimum_phase",
            "message": "Verifying filters (D-009, min-phase, format)",
        })

        # Verify (same D-009 interlock as filter_routes)
        verifications = []
        all_pass = True
        for name, path in sorted(output_paths.items()):
            d009 = verify_d009(path)
            min_phase = verify_minimum_phase(path)
            fmt = verify_format(path, expected_taps=n_taps, expected_sr=sr)
            ch_pass = bool(d009.passed and min_phase.passed and fmt.passed)
            ch_result = {
                "channel": name,
                "d009_pass": bool(d009.passed),
                "d009_peak_db": float(round(
                    d009.details.get("max_gain_db", 0.0), 2)),
                "min_phase_pass": bool(min_phase.passed),
                "format_pass": bool(fmt.passed),
                "all_pass": ch_pass,
            }
            verifications.append(ch_result)
            self._enqueue_progress({
                "type": "filter_gen_progress", "phase": "in_progress",
                "step": "minimum_phase",
                "message": f"Verified {name}: {'PASS' if ch_pass else 'FAIL'}",
                "channel": name,
                "channel_result": ch_result,
            })
            if not ch_pass:
                all_pass = False

        # Generate PW filter-chain .conf (uses speaker keys directly)
        pw_conf = generate_filter_chain_conf(
            profile_name,
            filter_paths={
                spk_key: str(output_paths.get(spk_key, ""))
                for spk_key in profile["speakers"]
            },
            profiles_dir=profiles_dir,
            identities_dir=identities_dir,
            validate=False,
        )
        pw_conf_path = os.path.join(output_dir, "30-filter-chain-convolver.conf")
        with open(pw_conf_path, "w") as f:
            f.write(pw_conf)

        crossover_raw = profile.get("crossover", {}).get("frequency_hz")

        return {
            "profile": profile_name,
            "output_dir": output_dir,
            "channels": {
                name: str(path) for name, path in sorted(output_paths.items())
            },
            "verification": verifications,
            "all_pass": all_pass,
            "pw_conf_path": pw_conf_path,
            "pw_conf_content": pw_conf,
            "n_taps": n_taps,
            "crossover_freq_hz": crossover_raw,
            "timestamp": timestamp.isoformat(),
        }

    # -- DEPLOY --------------------------------------------------------------

    async def _run_deploy(self) -> None:
        """Deploy generated FIR WAV files and PW config to target paths.

        Uses the deploy module (updated for D-040) to copy WAV files to
        /etc/pi4audio/coeffs/ and the .conf drop-in to
        ~/.config/pipewire/pipewire.conf.d/.

        In mock mode, uses dry_run=True so no files are actually written
        to system paths.
        """
        self._check_abort("CP-6")
        self._transition(MeasurementState.DEPLOY)
        await self._broadcast_state()

        fg = getattr(self, "_filter_gen_result", None)
        if fg is None:
            await self._broadcast({
                "type": "deploy_progress", "phase": "skipped",
                "message": "No filter generation results to deploy",
            })
            log.warning("Deploy skipped: no filter generation results")
            return

        if not fg.get("all_pass", False):
            await self._broadcast({
                "type": "deploy_progress", "phase": "skipped",
                "message": "Filters did not pass verification — refusing deploy",
            })
            raise RuntimeError(
                "Deploy refused: filters did not pass verification")

        await self._broadcast({
            "type": "deploy_progress", "phase": "starting",
            "message": "Deploying filters and PW config",
        })

        try:
            result = await asyncio.to_thread(
                self._deploy_sync, fg)
            self._deploy_result = result
            await self._broadcast({
                "type": "deploy_progress", "phase": "complete",
                "deployed_wavs": result.get("deployed_wavs", []),
                "pw_conf_deployed": result.get("pw_conf_path", ""),
            })
            log.info("Deploy complete: %d WAVs, PW config at %s",
                     len(result.get("deployed_wavs", [])),
                     result.get("pw_conf_path", "n/a"))
        except _AbortError:
            raise
        except Exception as exc:
            await self._broadcast({
                "type": "deploy_progress", "phase": "error",
                "message": str(exc),
            })
            raise

    def _deploy_sync(self, fg_result: dict) -> dict:
        """Run deployment synchronously (called in thread pool)."""
        _ensure_rc_path()
        from room_correction.deploy import deploy_filters, deploy_pw_config

        self._check_abort("CP-6a")

        dry_run = self._is_mock
        output_dir = fg_result["output_dir"]

        self._enqueue_progress({
            "type": "deploy_progress", "phase": "in_progress",
            "step": "copy", "message": "Copying WAV coefficient files",
        })

        # Deploy WAV coefficient files
        deployed_wavs = deploy_filters(
            output_dir=output_dir,
            verified=True,
            dry_run=dry_run,
        )

        self._check_abort("CP-6b")

        self._enqueue_progress({
            "type": "deploy_progress", "phase": "in_progress",
            "step": "config",
            "message": f"Deployed {len(deployed_wavs)} WAV files, installing PW config",
        })

        # Deploy PW filter-chain .conf
        pw_conf_content = fg_result.get("pw_conf_content", "")
        pw_conf_path = ""
        if pw_conf_content:
            pw_conf_path = deploy_pw_config(
                conf_content=pw_conf_content,
                dry_run=dry_run,
            )

        # Reload PipeWire convolver so it picks up the new coefficients.
        # Destroy the convolver node; PipeWire re-reads .conf.d/ and recreates
        # it with the newly deployed WAV files.
        if not dry_run:
            self._enqueue_progress({
                "type": "deploy_progress", "phase": "in_progress",
                "step": "reload",
                "message": "Reloading filter-chain convolver",
            })
            self._reload_convolver()
            self._enqueue_progress({
                "type": "deploy_progress", "phase": "in_progress",
                "step": "reload",
                "message": "Filter-chain convolver reloaded",
            })

        return {
            "deployed_wavs": deployed_wavs,
            "pw_conf_path": pw_conf_path,
            "dry_run": dry_run,
        }

    @staticmethod
    def _reload_convolver(node_name: str = "pi4audio-convolver",
                          timeout_s: float = 5.0) -> None:
        """Destroy and wait for PipeWire to recreate the convolver node.

        PipeWire's filter-chain module re-reads its .conf.d/ drop-ins when
        the node is destroyed, recreating it with updated coefficients.
        """
        import subprocess

        log.info("Reloading convolver: destroying node '%s'", node_name)
        try:
            subprocess.run(
                ["pw-cli", "destroy", node_name],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            log.warning("pw-cli destroy failed (non-fatal): %s", exc)
            return

        # Wait for PipeWire to recreate the node from .conf.d/.
        import time
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            time.sleep(0.5)
            result = subprocess.run(
                ["pw-cli", "list-objects", "Node"],
                capture_output=True, text=True, timeout=5,
            )
            if node_name in result.stdout:
                log.info("Convolver node '%s' recreated", node_name)
                return
        log.warning("Convolver node '%s' did not reappear within %.0fs",
                    node_name, timeout_s)

    # -- VERIFY --------------------------------------------------------------

    async def _run_verify(self) -> None:
        """Post-deploy verification sweep: confirm correction effectiveness.

        Plays a single sweep per channel through the corrected signal path,
        records via UMIK-1, deconvolves, and compares the post-correction
        frequency response to the expected flat-ish target.  Reports max
        deviation in the correction band (30 Hz -- 16 kHz).

        In mock mode, skips the live sweep and reports only the static
        filter-gen verification results.  Design principle #7: mandatory
        verification measurement to confirm correction effectiveness.
        """
        self._check_abort("CP-7")
        self._transition(MeasurementState.VERIFY)
        await self._broadcast_state()

        fg = getattr(self, "_filter_gen_result", None)
        static_verification = fg.get("verification", []) if fg else []

        # In mock mode we cannot run a real verification sweep —
        # no PipeWire is running.  Report static verification only.
        if self._is_mock:
            await self._broadcast({
                "type": "verify_progress", "phase": "complete",
                "message": "Static verification passed (live verification "
                           "sweep requires Pi + UMIK-1 hardware)",
                "verification": static_verification,
                "live_verification": None,
            })
            return

        # Live verification sweep — one sweep per channel, single position.
        await self._broadcast({
            "type": "verify_progress", "phase": "sweeping",
            "message": "Running verification sweeps",
        })

        _ensure_rc_path()
        import measure_nearfield as mn
        from room_correction.sweep import generate_log_sweep
        from room_correction.deconvolution import deconvolve
        from room_correction import dsp_utils

        # US-067 Track A: signal-gen mode uses separated play + capture.
        _siggen_client = None
        _cap_target = None
        if self._sd_override is not None and not self._is_mock:
            _siggen_client = self._sd_override
            if _MEAS_DIR not in sys.path:
                sys.path.insert(0, _MEAS_DIR)
            import pw_capture as _pwc
            _cap_target = _pwc.DEFAULT_TARGET
        elif self._sd_override is not None:
            mn._sd_override = self._sd_override

        sr = self._config.sample_rate
        sweep = generate_log_sweep(
            duration=self._config.sweep_duration_s,
            f_start=20.0, f_end=20000.0, sr=sr)
        target_peak = dsp_utils.db_to_linear(self._config.sweep_level_dbfs)
        peak = np.max(np.abs(sweep))
        if peak > 0:
            sweep *= target_peak / peak

        verify_results = []
        for ch in self._config.channels:
            self._check_abort("CP-7a")
            await self._broadcast({
                "type": "verify_progress", "phase": "sweep_channel",
                "channel": ch.index, "channel_name": ch.name,
            })

            try:
                recording = await self._playrec_with_abort(
                    mn.play_and_record, sweep, ch.index,
                    self._config.output_device, self._config.input_device,
                    sr=sr, signal_gen=_siggen_client,
                    capture_target=_cap_target)
            except Exception as exc:
                log.warning("Verify sweep failed for %s: %s", ch.name, exc)
                verify_results.append({
                    "channel": ch.name, "pass": False,
                    "error": str(exc),
                })
                continue

            # Deconvolve to get post-correction IR
            ir = await asyncio.to_thread(deconvolve, recording, sweep, sr=sr)

            # Compute magnitude response in dB
            n_fft = dsp_utils.next_power_of_2(len(ir))
            freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
            mag = np.abs(np.fft.rfft(ir, n=n_fft))
            mag_db = 20.0 * np.log10(np.maximum(mag, 1e-20))

            # Evaluate deviation from flat in the correction band (30-16000 Hz)
            band_mask = (freqs >= 30.0) & (freqs <= 16000.0)
            if np.any(band_mask):
                band_db = mag_db[band_mask]
                # Normalize to mean level in the band
                mean_db = float(np.mean(band_db))
                deviation = band_db - mean_db
                max_pos = float(np.max(deviation))
                max_neg = float(np.min(deviation))
                max_dev = max(abs(max_pos), abs(max_neg))

                # Pass if max deviation <= 6 dB (generous for real rooms)
                passed = max_dev <= 6.0
            else:
                max_pos = 0.0
                max_neg = 0.0
                max_dev = 0.0
                passed = True

            verify_results.append({
                "channel": ch.name,
                "pass": passed,
                "max_deviation_db": round(max_dev, 1),
                "max_peak_db": round(max_pos, 1),
                "max_dip_db": round(max_neg, 1),
                "band": "30-16000 Hz",
            })
            log.info("Verify %s: max_dev=%.1f dB, pass=%s",
                     ch.name, max_dev, passed)

        if self._is_mock and self._sd_override is not None:
            mn._sd_override = None

        all_pass = all(r.get("pass", False) for r in verify_results)

        await self._broadcast({
            "type": "verify_progress", "phase": "complete",
            "message": "Live verification complete" if all_pass
                       else "Live verification: some channels exceed tolerance",
            "verification": static_verification,
            "live_verification": verify_results,
            "all_pass": all_pass,
        })

    # -- CP-0: playrec with abort racing -------------------------------------

    async def _playrec_with_abort(
        self, play_fn: Callable, signal: np.ndarray,
        channel: int, output_device: Any, input_device: Any,
        sr: int = 48000, **kwargs,
    ) -> np.ndarray:
        """Race ``play_fn`` against ``abort_event`` (CP-0).

        If abort wins, calls ``sd.abort()`` to interrupt audio I/O.
        Extra kwargs (e.g. signal_gen, capture_target) are forwarded
        to play_fn.
        """
        playrec_task = asyncio.ensure_future(asyncio.to_thread(
            play_fn, signal, channel, output_device, input_device,
            sr=sr, **kwargs))
        abort_task = asyncio.ensure_future(self.abort_event.wait())

        done, pending = await asyncio.wait(
            {playrec_task, abort_task},
            return_when=asyncio.FIRST_COMPLETED)

        if abort_task in done:
            log.info("CP-0: abort during playrec")
            await asyncio.to_thread(self._sd_abort)
            try:
                await asyncio.wait_for(playrec_task, timeout=2.0)
            except asyncio.TimeoutError:
                log.error("CP-0: playrec thread did not exit within 2s after sd.abort()")
                playrec_task.cancel()
            except Exception:
                pass  # playrec may raise after abort — that's expected
            raise _AbortError(self._abort_reason or "abort during playrec")

        if abort_task in pending:
            abort_task.cancel()
            try:
                await abort_task
            except asyncio.CancelledError:
                pass

        result = playrec_task.result()
        # play_and_record() returns (trimmed_recording, pre_roll) tuple;
        # MockSoundDevice.playrec() returns ndarray directly.
        return result[0] if isinstance(result, tuple) else result

    # -- Helpers -------------------------------------------------------------

    def _sd_abort(self) -> None:
        """Call sd.abort() on whatever sounddevice is active."""
        sd = self._sd_override
        if sd is None:
            try:
                import sounddevice as sd  # type: ignore[no-redef]
            except ImportError:
                return
        if hasattr(sd, "abort"):
            try:
                sd.abort()
            except Exception as exc:
                log.warning("sd.abort() failed: %s", exc)

    async def _handle_abort(self, reason: str) -> None:
        self._abort_reason = reason
        try:
            self._transition(MeasurementState.ABORTED)
        except RuntimeError:
            self._state = MeasurementState.ABORTED
        self._finished_at = datetime.now()
        await self._broadcast_state({"abort_reason": reason})
        log.info("Session aborted: %s", reason)

    async def _restore_production_mode(self) -> None:
        """Restore GraphManager to the mode active before measurement (F-160)."""
        if self._gm_client is None:
            return
        target = self._pre_measurement_gm_mode or "monitoring"
        try:
            await asyncio.to_thread(self._gm_client.set_mode, target)
            log.info("F-160: Restored GraphManager to %s mode", target)
        except Exception as exc:
            log.error("Failed to restore GM to %s mode: %s", target, exc)

    async def _connect_gm(self) -> None:
        """Connect to the GraphManager RPC server (D-040)."""
        self._is_mock = False

        if _MOCK_MODE:
            # Use mock client for testing without a running GraphManager.
            if _MEAS_DIR not in sys.path:
                sys.path.insert(0, _MEAS_DIR)
            try:
                from graph_manager_client import MockGraphManagerClient
                client = MockGraphManagerClient(
                    host=self._config.gm_host,
                    port=self._config.gm_port)
                client.connect()
                self._gm_client = client
                self._is_mock = True
                log.info("Using MockGraphManagerClient")
            except ImportError:
                log.warning("No GraphManagerClient available")
                self._gm_client = None
            return

        if _MEAS_DIR not in sys.path:
            sys.path.insert(0, _MEAS_DIR)
        try:
            from graph_manager_client import GraphManagerClient
            client = GraphManagerClient(
                host=self._config.gm_host,
                port=self._config.gm_port)
            await asyncio.to_thread(client.connect)
            self._gm_client = client
            log.info("GraphManager connected (%s:%d)",
                     self._config.gm_host, self._config.gm_port)
        except Exception as exc:
            log.warning("GraphManager connection failed: %s", exc)
            self._gm_client = None

    async def _disconnect_gm(self) -> None:
        if self._gm_client is not None:
            try:
                await asyncio.to_thread(self._gm_client.close)
            except Exception:
                pass
            self._gm_client = None

    async def _cleanup(self) -> None:
        await self._watchdog.stop()
        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
        # D-040: Restore production mode before disconnecting.
        await self._restore_production_mode()
        await self._disconnect_gm()
        log.info("Session cleanup complete")

    def _on_watchdog_timeout(self) -> None:
        self.request_abort("watchdog timeout")
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, self._sd_abort)

    # -- Status snapshot -----------------------------------------------------

    def to_status_dict(self) -> dict:
        """JSON-serializable snapshot for reconnecting browsers."""
        return {
            "state": self._state.value,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "finished_at": self._finished_at.isoformat() if self._finished_at else None,
            "error_message": self._error_message,
            "abort_reason": self._abort_reason,
            "abort_requested": self.abort_requested,
            "current_channel_idx": self._current_channel_idx,
            "current_position": self._current_position,
            "progress_pct": self._progress_pct,
            "channels": [
                {"index": c.index, "name": c.name,
                 "target_spl_db": c.target_spl_db,
                 "thermal_ceiling_dbfs": c.thermal_ceiling_dbfs}
                for c in self._config.channels
            ],
            "gain_cal_results": {
                str(k): {
                    "passed": v.passed,
                    "calibrated_level_dbfs": v.calibrated_level_dbfs,
                    "measured_spl_db": v.measured_spl_db,
                    "steps_taken": v.steps_taken,
                    "abort_reason": v.abort_reason,
                } for k, v in self._gain_cal_results.items()
            },
            "sweep_results": self._sweep_results,
            "positions": self._config.positions,
            "sweep_duration_s": self._config.sweep_duration_s,
            "filter_gen_result": self._filter_gen_result,
            "deploy_result": self._deploy_result,
            "calibration": {
                "file": self._config.calibration_file,
                "sensitivity": self._config.umik_sensitivity_dbfs_to_spl,
            },
        }
