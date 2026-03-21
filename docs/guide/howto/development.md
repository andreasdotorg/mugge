# HOWTO: Common Development Tasks

This guide covers the most common tasks that workers and developers perform on
the pi4-audio-workstation project. It assumes you have already cloned the
repository and have Nix installed.

## 1. Nix Environment

The project uses Nix flakes (`flake.nix`) to provide a fully reproducible
Python 3.13 environment with all dependencies. There is no `requirements.txt`
or `pyproject.toml` for dependency management. The single source of truth for
all Python dependencies is `flake.nix`.

### 1.1 Running Tests and Commands

**`nix flake check`** is the gold standard: pure, sandboxed derivations with
no access to the host environment. It runs four checks:

```sh
nix flake check    # Runs all four checks in the Nix sandbox:
                   #   test-web-ui           (web UI unit/integration tests)
                   #   test-room-correction  (DSP pipeline tests)
                   #   test-midi             (MIDI daemon tests)
                   #   test-drivers          (driver validation tests)
```

If `nix flake check` passes, the code is reproducible. This is what CI runs.

**`nix run .#<target>`** runs tests impurely against the working tree (picks
up uncommitted changes). Use these during development:

```sh
nix run .#test-unit             # Web UI unit tests (excludes e2e)
nix run .#test-room-correction  # Room correction DSP tests
nix run .#test-e2e              # Playwright e2e tests
nix run .#test-all              # All four suites sequentially
nix run .#serve                 # Dev server (mock mode, 0.0.0.0:8080)
```

### 1.2 Interactive Development

For editing, debugging, and REPL work, enter the development shell:

```sh
nix develop
```

This drops you into a shell with Python 3.13 and all flake dependencies
available. From here you can run pytest directly, start a REPL, use an editor,
or do any interactive work:

```sh
# Inside nix develop
python -m pytest src/room-correction/tests/ -v
python -m pytest src/web-ui/tests/ -v -k "not e2e"
python -c "import camilladsp; print(camilladsp.versions.VERSION)"
```

### 1.3 What NOT to Do

Do not bypass Nix for test runs or dependency management:

- **Do not** use `.venv/bin/python -m pytest ...` -- impure, not reproducible
- **Do not** use `source .venv/bin/activate && pytest ...` -- same problem
- **Do not** run `pip install ...` into any venv -- breaks Nix reproducibility

The `.venv` directories exist as an implementation detail of the Nix
environment setup. They are not the intended interface for running code.


## 2. Test Suites

The project has four test suites, each in its own subdirectory (under `src/`
for product code, `scripts/` for utilities) with a `pytest.ini`.

### 2.1 Room Correction Unit Tests

Tests for the DSP pipeline: sweep generation, deconvolution, spatial averaging,
gain calibration, time alignment, filter generation, thermal ceiling, power
validation. 15 test files in `src/room-correction/tests/`.

```sh
nix run .#test-room-correction
```

### 2.2 Web UI Unit / Integration Tests

Tests for the FastAPI backend: server startup, collectors, measurement session
state machine, Phase 1 validation. Run in mock mode (`PI_AUDIO_MOCK=1`).
Located in `src/web-ui/tests/` (excluding the `e2e/` subdirectory).

```sh
nix run .#test-unit
```

### 2.3 Web UI End-to-End Tests (Playwright)

E2E tests use Playwright (Chromium) to drive the web UI against a
session-scoped mock FastAPI server that starts automatically on a free port.
Located in `src/web-ui/tests/e2e/`.

```sh
nix run .#test-e2e
```

**Visual regression tests** compare screenshots against reference images in
`src/web-ui/tests/e2e/screenshots/`. After intentional UI changes,
regenerate reference screenshots and review the diffs before committing.

**Destructive tests** are marked `@pytest.mark.destructive` (they modify Pi
state) and are skipped by default. They require the `--destructive` flag.

**Tests against a real Pi** use the `pi_url` fixture and require the
`PI_AUDIO_URL` environment variable. Tests skip if it is unset.

### 2.4 MIDI Daemon and Driver Tests

Located in `src/midi/tests/` and `scripts/drivers/tests/` respectively.
These do not have individual `nix run` targets. They are included in:

- `nix flake check` (as `test-midi` and `test-drivers` checks)
- `nix run .#test-all` (runs all four suites sequentially)

### 2.5 Running Everything

```sh
nix flake check    # CI-grade, pure sandbox — 4 checks
nix run .#test-all # All 4 suites sequentially against working tree
```


## 3. Running the Web UI Locally

The web UI is a FastAPI application. In mock mode (`PI_AUDIO_MOCK=1`, the
default), it uses mock collectors and a mock sounddevice backend so you can
develop and test without audio hardware.

```sh
nix run .#serve
```

This starts uvicorn with `--reload` on `0.0.0.0:8080` in mock mode. The UI
will be available at `http://localhost:8080`. The `--reload` flag watches for
file changes and restarts the server automatically.

For interactive development (e.g., custom host/port, debugging), use the
development shell:

```sh
nix develop
cd src/web-ui
python -m uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload
```


## 4. Deploying to the Pi

Deployment to the Pi goes through the Change Manager (CM) using the deployment
target access protocol (see `.claude/team/protocol/deployment-target-access.md`).
Workers do not deploy directly; they commit code and the CM deploys.

### 4.1 Protocol Summary

1. The CM must hold a DEPLOY session (exclusive lock) before deploying.
2. Only committed code is deployed (D-023). The git working tree must be clean.
3. The owner must be notified before any action that restarts CamillaDSP or
   reboots the Pi, because the USBStreamer produces transients through the
   amplifier chain that can damage speakers. See `docs/operations/safety.md`.

### 4.2 The Deploy Script

`scripts/deploy/deploy.sh` deploys version-controlled configs and scripts to
the Pi via SSH/SCP/rsync.

```sh
scripts/deploy/deploy.sh --dry-run              # preview what would be deployed
scripts/deploy/deploy.sh                         # deploy, keep current CamillaDSP mode
scripts/deploy/deploy.sh --mode dj               # deploy and set DJ/PA mode
scripts/deploy/deploy.sh --mode live             # deploy and set Live mode
scripts/deploy/deploy.sh --pi ela@10.0.0.5       # deploy to a different host
scripts/deploy/deploy.sh --reboot                # deploy and reboot
```

The script runs 9 sections:

1. Validate prerequisites (clean git, Pi reachable, source files exist)
2. Deploy user-level configs (PipeWire, WirePlumber, labwc, systemd user units)
3. Deploy system-level configs via sudo (CamillaDSP, systemd overrides)
4. Set active CamillaDSP config symlink (`/etc/camilladsp/active.yml`)
5. Reload systemd (system + user)
6. Deploy scripts to `~/bin/` (test, stability, launch scripts)
7. Deploy web UI and room correction code via rsync
8. Verify (CamillaDSP config syntax, script syntax, libjack resolution)
9. Optionally reboot

### 4.3 Manual Deploy (git pull on Pi)

For quick code-only updates during development sessions, the CM may run
`git pull` on the Pi instead of the full deploy script. This is only
appropriate for changes to scripts and application code (not system configs).


## 5. Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PI_AUDIO_MOCK` | `1` | Enable mock mode (mock sounddevice, mock CamillaDSP, mock collectors). Set to `0` for real hardware. |
| `PI_AUDIO_URL` | (unset) | Pi web UI URL for e2e tests against real hardware. Tests skip if unset. |
| `PI4AUDIO_PCM_JACK` | (unset) | Enable legacy JACK PCM collector (`1` = enable). Default off — pcm-bridge (Rust) is the replacement. The JACK client joins the RT graph and can cause xruns. |
| `PI4AUDIO_PRODUCTION_CONFIG` | `/etc/camilladsp/active.yml` | Production CamillaDSP config path, restored after measurement. |
| `PLAYWRIGHT_BROWSERS_PATH` | (set by flake) | Path to Playwright's Chromium. Set automatically in `nix develop` and `nix run`. |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | `1` (set by flake) | Prevents Playwright from downloading browsers (Nix provides them). |


## 6. Project Layout

```
pi4-audio-workstation/
  flake.nix                       Nix flake — all deps, packages, test targets
  flake.lock                      Pinned Nix inputs
  configs/                        Version-controlled Pi configs
    camilladsp/                   CamillaDSP production configs (dj-pa.yml, live.yml)
    pipewire/                     PipeWire config fragments
    wireplumber/                  WirePlumber config fragments
    labwc/                        Wayland compositor config
    systemd/                      Systemd unit files and overrides
  scripts/
    deploy/deploy.sh              Deployment script (9 sections)
    room-correction/              DSP pipeline (sweep, deconvolution, filters)
      tests/                      Unit tests (15 test files)
      mock/                       Mock CamillaDSP client
    web-ui/                       FastAPI web UI + monitoring dashboard
      app/                        FastAPI application
        measurement/              Measurement daemon (session, routes)
        mock/                     Mock sounddevice
      static/                     Frontend assets (HTML, JS, CSS)
      tests/                      Unit + integration tests
        e2e/                      Playwright e2e tests
          screenshots/            Visual regression reference images
    midi/                         MIDI daemon
      tests/                      MIDI daemon tests
    drivers/                      Driver validation
      tests/                      Driver validation tests
    test/                         Hardware test scripts (T1-T5)
    stability/                    Stability test scripts
    launch/                       Application launch scripts
  tools/
    pcm-bridge/                   Rust PipeWire monitor tap (passive, no xruns)
  docs/
    architecture/                 Architecture documents (rt-audio-stack, measurement-daemon)
    operations/safety.md          Safety manual — read before audio-producing operations
    lab-notes/                    Session lab notes (CHANGE, DEPLOY, OBSERVE)
    project/                      Status, decisions, assumptions
    guide/howto/                  This file and future HOWTOs
```
