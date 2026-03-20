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

_MEASUREMENT_ATTENUATION_DB = -20.0


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

    def __post_init__(self):
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

        self._broadcast_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._watchdog = MeasurementWatchdog(
            timeout_s=10.0, on_timeout=self._on_watchdog_timeout)
        self._gm_client: Any = None
        self._pump_task: Optional[asyncio.Task] = None
        self._is_mock: bool = False
        self._quantum_overridden: bool = False

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
            # device indices.
            if not _MOCK_MODE:
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

        In mock mode, uses MockGraphManagerClient (no-op).
        """
        if self._gm_client is None:
            log.warning("No GraphManager client — skipping mode switch")
            return

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
            # On failure, try to restore production mode.
            try:
                await asyncio.to_thread(
                    self._gm_client.restore_production_mode)
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
        if self._sd_override is not None:
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
            result = await asyncio.to_thread(
                calibrate_channel,
                channel_index=ch.index,
                target_spl_db=ch.target_spl_db,
                hard_limit_spl_db=self._config.hard_limit_spl_db,
                sample_rate=self._config.sample_rate,
                output_device=self._config.output_device,
                input_device=self._config.input_device,
                umik_sensitivity_dbfs_to_spl=self._config.umik_sensitivity_dbfs_to_spl,
                thermal_ceiling_dbfs=ch.thermal_ceiling_dbfs,
                gm_client=self._gm_client,
                ws_server=adapter, channel_name=ch.name,
                measurement_attenuation_db=(
                    0.0 if self._is_mock else _MEASUREMENT_ATTENUATION_DB),
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

        if self._sd_override is not None:
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
                                   channel_name: str) -> None:
        """Validate recording integrity after a sweep.

        Checks peak level, clipping, DC offset, and SNR.  Raises
        ``RuntimeError`` on any failure.
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

        issues: list[str] = []

        if peak_dbfs < -40.0:
            issues.append(
                f"Peak too low: {peak_dbfs:.1f} dBFS < -40 dBFS "
                f"(mic not receiving signal?)")

        if peak_dbfs > -1.0:
            issues.append(
                f"Peak too high: {peak_dbfs:.1f} dBFS > -1 dBFS "
                f"(likely clipping)")

        if dc_offset > 0.01:
            issues.append(
                f"DC offset: {dc_offset:.4f} (>0.01, possible ADC issue)")

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

        if self._sd_override is not None:
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
                    sr=self._config.sample_rate)
                # M-1: Recording integrity checks (skip in mock mode).
                if not self._is_mock:
                    self._check_recording_integrity(recording, ch.name)
                key = f"ch{ch.index}_pos{pos}"
                peak_dbfs = float(
                    20 * np.log10(max(np.max(np.abs(recording)), 1e-10)))
                self._sweep_results[key] = {
                    "channel": ch.index, "position": pos,
                    "recording_samples": len(recording),
                    "peak_dbfs": peak_dbfs,
                }
                await self._broadcast({
                    "type": "sweep_done", "channel": ch.index,
                    "channel_name": ch.name, "position": pos + 1,
                    "sweep_num": count, "sweep_total": total,
                    "progress_pct": self._progress_pct,
                    "peak_dbfs": peak_dbfs,
                })

        if self._sd_override is not None:
            mn._sd_override = None
        log.info("Sweep phase complete: %d sweeps", count)

    # -- FILTER_GEN (stubbed) ------------------------------------------------

    async def _run_filter_gen(self) -> None:
        """TODO: Integrate room_correction pipeline (deconvolution, smoothing,
        inversion, crossover, export).  Currently passes through."""
        self._check_abort("CP-5")
        self._transition(MeasurementState.FILTER_GEN)
        await self._broadcast_state()
        await self._broadcast({
            "type": "filter_gen_progress", "phase": "pending",
            "message": "Filter generation pipeline not yet integrated",
        })

    # -- DEPLOY (stubbed) ----------------------------------------------------

    async def _run_deploy(self) -> None:
        """TODO: Deploy new FIR filter WAV files to the PW filter-chain.
        Reload via pw-cli module reload (D-040)."""
        self._check_abort("CP-6")
        self._transition(MeasurementState.DEPLOY)
        await self._broadcast_state()
        await self._broadcast({
            "type": "deploy_progress", "phase": "pending",
            "message": "Filter deployment not yet integrated",
        })

    # -- VERIFY (stubbed) ----------------------------------------------------

    async def _run_verify(self) -> None:
        """TODO: Post-deploy verification sweep comparing pre/post response."""
        self._check_abort("CP-7")
        self._transition(MeasurementState.VERIFY)
        await self._broadcast_state()
        await self._broadcast({
            "type": "verify_progress", "phase": "pending",
            "message": "Verification sweep not yet integrated",
        })

    # -- CP-0: playrec with abort racing -------------------------------------

    async def _playrec_with_abort(
        self, play_fn: Callable, signal: np.ndarray,
        channel: int, output_device: Any, input_device: Any,
        sr: int = 48000,
    ) -> np.ndarray:
        """Race ``play_fn`` against ``abort_event`` (CP-0).

        If abort wins, calls ``sd.abort()`` to interrupt audio I/O.
        """
        playrec_task = asyncio.ensure_future(asyncio.to_thread(
            play_fn, signal, channel, output_device, input_device, sr=sr))
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
        """Restore GraphManager to production (monitoring) mode."""
        if self._gm_client is None:
            return
        try:
            await asyncio.to_thread(self._gm_client.restore_production_mode)
            log.info("Restored GraphManager to production (monitoring) mode")
        except Exception as exc:
            log.error("Failed to restore production mode: %s", exc)

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
        }
