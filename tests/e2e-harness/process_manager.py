"""E2E harness process manager — subprocess lifecycle for integration tests.

Manages PipeWire, CamillaDSP, pw-filter-chain (room simulator), and the RT
signal generator as subprocesses.  Starts in dependency order, tears down in
reverse.  Uses SIGTERM with a timeout, falling back to SIGKILL.

Designed for the US-050 E2E test harness.  All processes run in a private
PipeWire instance (not the user session) so tests are isolated.

Usage::

    pm = ProcessManager(
        pipewire_bin="pipewire",
        camilladsp_bin="camilladsp",
        camilladsp_config="tests/e2e-harness/camilladsp-e2e.yml",
        room_sim_script="tests/e2e-harness/start-room-sim.sh",
        siggen_bin="pi4-audio-siggen",
    )
    pm.start_all()
    try:
        ...  # run tests
    finally:
        pm.stop_all()
"""

import logging
import os
import shutil
import signal
import subprocess
import time

log = logging.getLogger(__name__)

# Startup timeouts (seconds)
PIPEWIRE_STARTUP_TIMEOUT = 5.0
CAMILLADSP_STARTUP_TIMEOUT = 5.0
ROOM_SIM_STARTUP_TIMEOUT = 3.0
SIGGEN_STARTUP_TIMEOUT = 5.0

# Shutdown
SIGTERM_TIMEOUT = 3.0
SIGKILL_TIMEOUT = 2.0

# CamillaDSP default WebSocket port for E2E harness
CAMILLADSP_E2E_PORT = 11235
CAMILLADSP_E2E_HOST = "127.0.0.1"


class ProcessError(Exception):
    """Raised when a managed process fails to start or dies unexpectedly."""


class ManagedProcess:
    """Wrapper around a subprocess with health-check and graceful shutdown."""

    def __init__(self, name, args, env=None, health_check=None,
                 startup_timeout=5.0):
        self.name = name
        self.args = args
        self.env = env
        self.health_check = health_check
        self.startup_timeout = startup_timeout
        self._proc = None

    @property
    def pid(self):
        return self._proc.pid if self._proc else None

    @property
    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        """Start the subprocess and wait for it to become healthy."""
        log.info("Starting %s: %s", self.name, " ".join(self.args))
        self._proc = subprocess.Popen(
            self.args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
        )

        # Check it didn't exit immediately
        time.sleep(0.1)
        if self._proc.poll() is not None:
            _, stderr = self._proc.communicate(timeout=2)
            stderr_text = stderr.decode("utf-8", errors="replace")[:500]
            raise ProcessError(
                f"{self.name} exited immediately (code {self._proc.returncode}). "
                f"stderr: {stderr_text}"
            )

        # Run health check if provided
        if self.health_check is not None:
            deadline = time.monotonic() + self.startup_timeout
            last_err = None
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    _, stderr = self._proc.communicate(timeout=2)
                    stderr_text = stderr.decode("utf-8", errors="replace")[:500]
                    raise ProcessError(
                        f"{self.name} died during startup "
                        f"(code {self._proc.returncode}). stderr: {stderr_text}"
                    )
                try:
                    if self.health_check():
                        log.info("%s healthy (pid %d)", self.name, self._proc.pid)
                        return
                except Exception as e:
                    last_err = e
                time.sleep(0.1)
            raise ProcessError(
                f"{self.name} failed health check within "
                f"{self.startup_timeout}s: {last_err}"
            )

        log.info("%s started (pid %d)", self.name, self._proc.pid)

    def stop(self):
        """Stop the subprocess: SIGTERM, then SIGKILL if needed."""
        if self._proc is None or self._proc.poll() is not None:
            return

        log.info("Stopping %s (pid %d) with SIGTERM", self.name, self._proc.pid)
        self._proc.send_signal(signal.SIGTERM)
        try:
            self._proc.wait(timeout=SIGTERM_TIMEOUT)
            log.info("%s terminated (code %d)", self.name, self._proc.returncode)
            return
        except subprocess.TimeoutExpired:
            pass

        log.warning(
            "%s did not exit after SIGTERM (%.1fs), sending SIGKILL",
            self.name, SIGTERM_TIMEOUT,
        )
        self._proc.kill()
        try:
            self._proc.wait(timeout=SIGKILL_TIMEOUT)
        except subprocess.TimeoutExpired:
            log.error("%s did not exit after SIGKILL", self.name)

    def collect_output(self):
        """Collect stdout/stderr from the process (non-blocking)."""
        if self._proc is None:
            return "", ""
        try:
            stdout, stderr = self._proc.communicate(timeout=1)
            return (
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except (subprocess.TimeoutExpired, ValueError):
            return "", ""


def _check_camilladsp_ws(host, port):
    """Health check: CamillaDSP WebSocket is accepting connections."""
    def check():
        from camilladsp import CamillaClient
        client = CamillaClient(host, port)
        client.connect()
        client.general.state()
        client.disconnect()
        return True
    return check


def _check_process_alive(proc_ref):
    """Health check: process is still running (no immediate crash)."""
    def check():
        return proc_ref.running
    return check


class ProcessManager:
    """Manages E2E harness subprocesses in dependency order.

    Start order: PipeWire -> CamillaDSP -> room simulator -> signal gen.
    Stop order:  signal gen -> room simulator -> CamillaDSP -> PipeWire.

    Parameters
    ----------
    pipewire_bin : str
        Path to ``pipewire`` binary.  If None, PipeWire management is
        skipped (assumes an external PipeWire instance is running).
    camilladsp_bin : str
        Path to ``camilladsp`` binary.
    camilladsp_config : str
        Path to the CamillaDSP YAML config file.
    camilladsp_port : int
        WebSocket port for CamillaDSP.
    room_sim_script : str or None
        Path to the room simulator start script (EH-2).  If None,
        room simulator management is skipped.
    room_sim_ir_dir : str or None
        Directory containing exported room IR WAV files (EH-1).
        Passed to the room simulator script.
    siggen_bin : str or None
        Path to the signal generator binary.  If None, signal gen
        management is skipped.
    siggen_port : int
        RPC port for the signal generator.
    env_overrides : dict or None
        Extra environment variables merged into each subprocess env.
        Use for ``PIPEWIRE_RUNTIME_DIR``, ``XDG_RUNTIME_DIR``, etc.
    """

    def __init__(
        self,
        pipewire_bin=None,
        camilladsp_bin="camilladsp",
        camilladsp_config="tests/e2e-harness/camilladsp-e2e.yml",
        camilladsp_port=CAMILLADSP_E2E_PORT,
        room_sim_script=None,
        room_sim_ir_dir=None,
        siggen_bin=None,
        siggen_port=9877,
        env_overrides=None,
    ):
        self._env = {**os.environ, **(env_overrides or {})}
        self._processes = []  # ordered list for teardown
        self._camilladsp_port = camilladsp_port

        # 1. PipeWire (optional — skip if using external instance)
        if pipewire_bin:
            pw = ManagedProcess(
                name="pipewire",
                args=[pipewire_bin],
                env=self._env,
                startup_timeout=PIPEWIRE_STARTUP_TIMEOUT,
            )
            self._processes.append(pw)

        # 2. CamillaDSP
        if not os.path.isfile(camilladsp_config):
            raise FileNotFoundError(
                f"CamillaDSP config not found: {camilladsp_config}"
            )
        cdsp = ManagedProcess(
            name="camilladsp",
            args=[
                camilladsp_bin,
                "-p", str(camilladsp_port),
                camilladsp_config,
            ],
            env=self._env,
            health_check=_check_camilladsp_ws(
                CAMILLADSP_E2E_HOST, camilladsp_port,
            ),
            startup_timeout=CAMILLADSP_STARTUP_TIMEOUT,
        )
        self._processes.append(cdsp)

        # 3. Room simulator (optional — EH-2)
        if room_sim_script:
            room_args = [room_sim_script]
            if room_sim_ir_dir:
                room_args.append(room_sim_ir_dir)
            room = ManagedProcess(
                name="room-simulator",
                args=room_args,
                env=self._env,
                startup_timeout=ROOM_SIM_STARTUP_TIMEOUT,
            )
            self._processes.append(room)

        # 4. Signal generator (optional)
        if siggen_bin:
            sg = ManagedProcess(
                name="signal-gen",
                args=[
                    siggen_bin,
                    "--port", str(siggen_port),
                ],
                env=self._env,
                startup_timeout=SIGGEN_STARTUP_TIMEOUT,
            )
            self._processes.append(sg)

    @property
    def camilladsp_port(self):
        return self._camilladsp_port

    def start_all(self):
        """Start all managed processes in dependency order.

        If any process fails to start, all previously started processes
        are torn down before re-raising the error.
        """
        started = []
        try:
            for proc in self._processes:
                proc.start()
                started.append(proc)
        except Exception:
            log.error("Startup failed at %s, tearing down", proc.name)
            for p in reversed(started):
                try:
                    p.stop()
                except Exception as e:
                    log.warning("Error stopping %s during rollback: %s",
                                p.name, e)
            raise

    def stop_all(self):
        """Stop all managed processes in reverse dependency order."""
        for proc in reversed(self._processes):
            try:
                proc.stop()
            except Exception as e:
                log.warning("Error stopping %s: %s", proc.name, e)

    def check_health(self):
        """Check that all managed processes are still running.

        Returns a dict mapping process name to running status.
        """
        return {proc.name: proc.running for proc in self._processes}

    def get_process(self, name):
        """Get a ManagedProcess by name, or None."""
        for proc in self._processes:
            if proc.name == name:
                return proc
        return None

    def collect_all_output(self):
        """Collect stdout/stderr from all stopped processes.

        Returns a dict mapping process name to (stdout, stderr) tuples.
        Useful for diagnostics after test failure.
        """
        return {
            proc.name: proc.collect_output()
            for proc in self._processes
            if not proc.running
        }
