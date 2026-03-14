"""In-process measurement session state machine (WP-D, TK-168).

Drives IDLE -> SETUP -> GAIN_CAL -> MEASURING -> FILTER_GEN -> DEPLOY -> VERIFY -> COMPLETE.
Lives on the daemon process; survives browser disconnects.  All blocking audio
I/O dispatched via ``asyncio.to_thread()``.

Cancellation contract: 8 named points CP-0..CP-7 (see ``_check_abort`` calls).

Design: two CamillaDSP connections (session owns #2); MEASUREMENT_CONFIG_MARKER
for orphan detection; per-thread RNG; ``asyncio.wait(FIRST_COMPLETED)`` for CP-0.
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

from ..mode_manager import MEASUREMENT_CONFIG_MARKER

# Path to room-correction scripts (resolved once at import time)
_RC_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "room-correction"))


def _ensure_rc_path() -> None:
    """Add room-correction dir to sys.path if needed."""
    if _RC_DIR not in sys.path:
        sys.path.insert(0, _RC_DIR)


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
                 broadcast_queue: asyncio.Queue) -> None:
        self._event = abort_event
        self._queue = broadcast_queue

    @property
    def abort_requested(self) -> bool:
        return self._event.is_set()

    def broadcast(self, message: dict) -> None:
        try:
            self._queue.put_nowait(message)
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
    production_config_path: str = "/etc/camilladsp/active.yml"
    output_device: Optional[Any] = None
    input_device: Optional[Any] = None
    sample_rate: int = 48000


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
    cdsp_host / cdsp_port : CamillaDSP websocket endpoint
    """

    def __init__(self, config: SessionConfig,
                 ws_broadcast: Callable[[dict], Awaitable[None]],
                 sd_override: Any = None,
                 cdsp_host: str = "127.0.0.1",
                 cdsp_port: int = 1234) -> None:
        self._config = config
        self._ws_broadcast = ws_broadcast
        self._sd_override = sd_override
        self._cdsp_host = cdsp_host
        self._cdsp_port = cdsp_port

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
        self._cdsp_client: Any = None
        self._pump_task: Optional[asyncio.Task] = None

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

    # -- SETUP ---------------------------------------------------------------

    async def _run_setup(self) -> None:
        self._transition(MeasurementState.SETUP)
        await self._broadcast_state()
        await self._connect_cdsp()
        # TODO: Swap CamillaDSP to measurement config.
        if self._cdsp_client is not None:
            try:
                st = await asyncio.to_thread(self._cdsp_client.general.state)
                log.info("CamillaDSP state: %s", st)
            except Exception as exc:
                log.warning("CamillaDSP state check failed: %s", exc)
        await self._broadcast({"type": "setup_complete"})

    # -- GAIN_CAL ------------------------------------------------------------

    async def _run_gain_cal(self) -> None:
        self._transition(MeasurementState.GAIN_CAL)
        await self._broadcast_state()

        _ensure_rc_path()
        from gain_calibration import calibrate_channel, set_mock_sd
        if self._sd_override is not None:
            set_mock_sd(self._sd_override)

        adapter = _AbortAdapter(self.abort_event, self._broadcast_queue)
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
                camilladsp_client=self._cdsp_client,
                ws_server=adapter, channel_name=ch.name,
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

    async def _run_measuring(self) -> None:
        # Validate sweep level does not exceed any channel's thermal ceiling.
        max_thermal = max(ch.thermal_ceiling_dbfs for ch in self._config.channels)
        if self._config.sweep_level_dbfs > max_thermal:
            raise RuntimeError(
                f"sweep_level_dbfs ({self._config.sweep_level_dbfs}) exceeds "
                f"thermal ceiling ({max_thermal})")

        self._transition(MeasurementState.MEASURING)
        await self._broadcast_state()

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
        """TODO: Integrate room_correction.export + deploy + reload via
        session's CamillaDSP connection #2."""
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

    async def _restore_production_config(self) -> None:
        if self._cdsp_client is None:
            return
        try:
            await asyncio.to_thread(
                self._cdsp_client.config.set_config_file_path,
                self._config.production_config_path)
            await asyncio.to_thread(self._cdsp_client.general.reload)
            log.info("Restored production config: %s",
                     self._config.production_config_path)
        except Exception as exc:
            log.error("Failed to restore production config: %s", exc)

    async def _connect_cdsp(self) -> None:
        """Create the session's own CamillaDSP connection (#2)."""
        try:
            from camilladsp import CamillaClient
        except ImportError:
            try:
                mock_dir = os.path.join(_RC_DIR, "mock")
                if mock_dir not in sys.path:
                    sys.path.insert(0, mock_dir)
                from mock_camilladsp import MockCamillaClient as CamillaClient  # type: ignore[no-redef]
                log.info("Using MockCamillaClient")
            except ImportError:
                log.warning("No CamillaClient available")
                self._cdsp_client = None
                return
        client = CamillaClient(self._cdsp_host, self._cdsp_port)
        try:
            await asyncio.to_thread(client.connect)
            self._cdsp_client = client
            log.info("CamillaDSP connected (%s:%d)",
                     self._cdsp_host, self._cdsp_port)
        except Exception as exc:
            log.warning("CamillaDSP connection failed: %s", exc)
            self._cdsp_client = None

    async def _disconnect_cdsp(self) -> None:
        if self._cdsp_client is not None:
            try:
                await asyncio.to_thread(self._cdsp_client.disconnect)
            except Exception:
                pass
            self._cdsp_client = None

    async def _cleanup(self) -> None:
        await self._watchdog.stop()
        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
        await self._disconnect_cdsp()
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
