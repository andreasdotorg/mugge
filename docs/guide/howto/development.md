# HOWTO: Common Development Tasks

This guide covers the most common tasks that workers and developers perform on
the mugge project. It assumes you have already cloned the
repository and have Nix installed.

## 1. Nix Environment

The project uses Nix flakes (`flake.nix`) to provide a fully reproducible
Python 3.13 environment with all dependencies. There is no `requirements.txt`
or `pyproject.toml` for dependency management. The single source of truth for
all Python dependencies is `flake.nix`.

### 1.1 Running Tests and Commands

**`nix run .#<target>`** is the QA gate. It runs tests impurely against the
working tree (picks up uncommitted changes):

```sh
nix run .#test-unit             # Web UI unit tests (excludes e2e)
nix run .#test-room-correction  # Room correction DSP tests
nix run .#test-graph-manager    # GraphManager Rust tests (pure logic)
nix run .#test-e2e              # Playwright e2e tests
nix run .#test-all              # All suites sequentially
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

- `nix run .#test-all` (runs all suites sequentially)

### 2.5 GraphManager Rust Tests

Rust-based logic tests for the GraphManager (reconciler, watchdog, routing
tables). Runs via `cargo test` inside the Nix environment.

```sh
nix run .#test-graph-manager
```

### 2.6 Running Everything

```sh
nix run .#test-all # All suites sequentially against working tree
```

### 2.7 Three-Gate Testing Process

The project uses a three-gate testing process (owner-approved, 2026-03-22):

| Gate | When | What | Who |
|------|------|------|-----|
| **Gate 1** | Every task | `nix run .#test-<suite>` (targeted suite for changed code) | Worker |
| **Gate 2** | Pre-merge / story-closing commits | `nix run .#test-all` (full suite including E2E) | Worker or CI |
| **Gate 3** | REVIEW phase | Pi acceptance testing | Owner |

**`nix run .#test-*` is the sole QA gate.** `nix flake check` is build
validation only. `nix develop` is for interactive exploration, not QA.


## 3. Running the Web UI Locally

The web UI is a FastAPI application. In mock mode (`PI_AUDIO_MOCK=1`, the
default), it uses mock collectors and mock backends so you can develop and
test without audio hardware or PipeWire.

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
3. The owner must be notified before any action that restarts PipeWire or
   reboots the Pi, because the USBStreamer produces transients through the
   amplifier chain that can damage speakers. See `docs/operations/safety.md`.

### 4.2 The Deploy Script

`scripts/deploy/deploy.sh` deploys version-controlled configs and scripts to
the Pi via SSH/SCP/rsync.

```sh
scripts/deploy/deploy.sh --dry-run              # preview what would be deployed
scripts/deploy/deploy.sh                         # deploy configs and code
scripts/deploy/deploy.sh --mode dj               # deploy and set DJ/PA mode
scripts/deploy/deploy.sh --mode live             # deploy and set Live mode
scripts/deploy/deploy.sh --pi ela@10.0.0.5       # deploy to a different host
scripts/deploy/deploy.sh --reboot                # deploy and reboot
```

The script runs 10 sections:

1. Validate prerequisites (clean git, Pi reachable, source files exist)
2. Deploy user-level configs (PipeWire, WirePlumber, labwc, systemd user units)
3. Deploy system-level configs via sudo (udev rules, systemd overrides)
4. Deploy FIR coefficient files to `/etc/pi4audio/coeffs/`
5. Reload systemd (system + user)
6. Deploy scripts to `~/bin/` (test, stability, launch scripts)
6b. Deploy Rust binaries to `~/bin/` (with `.bak` rollback + version check)
7. Deploy web UI, measurement, and room correction code via rsync
8. Verify (PipeWire config syntax, script syntax, libjack resolution)
9. Optionally reboot

### 4.3 Manual Deploy (git pull on Pi)

For quick code-only updates during development sessions, the CM may run
`git pull` on the Pi instead of the full deploy script. This is only
appropriate for changes to scripts and application code (not system configs).

### 4.4 Rust Binary Deployment

The project has 4 Rust crates that produce binaries deployed to `~/bin/`
on the Pi:

| Crate | Binary name | Build directory | Systemd service |
|-------|------------|-----------------|-----------------|
| `src/graph-manager/` | `pi4audio-graph-manager` | `src/graph-manager/target/release/` | `pi4audio-graph-manager.service` |
| `src/pcm-bridge/` | `pcm-bridge` | `src/target/release/` | `pcm-bridge@monitor.service` |
| `src/signal-gen/` | `pi4audio-signal-gen` | `src/target/release/` | `pi4audio-signal-gen.service` |
| `src/level-bridge/` | `level-bridge` | `src/target/release/` | `level-bridge@monitor.service` |

Note: `graph-manager` has its own `Cargo.toml` and builds independently.
The other three are in a Cargo workspace (`src/Cargo.toml`), which is why
their build output lands in `src/target/release/`.

#### Building on the Pi (native ARM)

The Pi has Rust installed via rustup (`~/.cargo/env`). Non-login SSH
sessions do not source this automatically, so prefix build commands:

```sh
# Build graph-manager (separate crate, own Cargo.lock)
ssh ela@192.168.178.185 "source ~/.cargo/env && cd ~/pi4-audio-workstation/src/graph-manager && cargo build --release"

# Build workspace binaries (pcm-bridge, signal-gen, level-bridge)
ssh ela@192.168.178.185 "source ~/.cargo/env && cd ~/pi4-audio-workstation/src && cargo build --release"
```

#### Deploying binaries

**Option A: deploy.sh** — Section 6b of `deploy.sh` handles Rust binary
deployment automatically. It looks for local release binaries, backs up
existing binaries as `.bak`, copies the new ones, and runs `--version`
verification. If no local release binaries exist, section 6b is skipped.

**Option B: Manual deployment** — After building on the Pi:

```sh
# Stop services first (binaries may be read-only while running)
ssh ela@192.168.178.185 "systemctl --user stop pi4audio-graph-manager.service pcm-bridge@monitor.service pi4audio-signal-gen.service level-bridge@monitor.service"

# Back up + copy binaries
ssh ela@192.168.178.185 "cd ~/pi4-audio-workstation && \
  for bin in pi4audio-graph-manager; do \
    test -f ~/bin/\$bin && cp ~/bin/\$bin ~/bin/\$bin.bak; \
    chmod u+w ~/bin/\$bin 2>/dev/null; \
    cp src/graph-manager/target/release/\$bin ~/bin/\$bin && chmod +x ~/bin/\$bin; \
  done && \
  for bin in pcm-bridge pi4audio-signal-gen level-bridge; do \
    test -f ~/bin/\$bin && cp ~/bin/\$bin ~/bin/\$bin.bak; \
    chmod u+w ~/bin/\$bin 2>/dev/null; \
    cp src/target/release/\$bin ~/bin/\$bin && chmod +x ~/bin/\$bin; \
  done"

# Restart services
ssh ela@192.168.178.185 "systemctl --user start pi4audio-graph-manager.service pcm-bridge@monitor.service pi4audio-signal-gen.service level-bridge@monitor.service"
```

**SAFETY:** Stopping PipeWire-connected services does NOT restart PipeWire
itself (no USBStreamer transient risk). However, if restarting the graph
manager, audio routing will be interrupted until it comes back up.

#### Rollback

If a newly deployed binary causes issues, restore from the `.bak` file:

```sh
ssh ela@192.168.178.185 "systemctl --user stop pi4audio-graph-manager.service && \
  cp ~/bin/pi4audio-graph-manager.bak ~/bin/pi4audio-graph-manager && \
  systemctl --user start pi4audio-graph-manager.service"
```

#### Version verification

Three of the four binaries support `--version` (pcm-bridge, signal-gen,
level-bridge). Graph-manager does not have a version flag yet.

```sh
ssh ela@192.168.178.185 "~/bin/pcm-bridge --version && ~/bin/pi4audio-signal-gen --version && ~/bin/level-bridge --version"
```


## 5. Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PI_AUDIO_MOCK` | `1` | Enable mock mode (mock collectors, mock GraphManager/signal-gen). Set to `0` for real hardware. |
| `PI_AUDIO_URL` | (unset) | Pi web UI URL for e2e tests against real hardware. Tests skip if unset. |
| `PI4AUDIO_LEVELS_HOST` | `127.0.0.1` | pcm-bridge levels server host for LevelsCollector (peak/RMS metering). |
| `PI4AUDIO_LEVELS_PORT` | `9100` | pcm-bridge levels server TCP port for LevelsCollector. |
| `PI4AUDIO_PCM_JACK` | (unset) | Enable legacy JACK PCM collector (`1` = enable). Default off — pcm-bridge (Rust) is the replacement. The JACK client joins the RT graph and can cause xruns. |
| ~~`PI4AUDIO_PW_TOP`~~ | **removed** | Removed (US-063). PipeWireCollector now uses GraphManager RPC — no pw-top subprocess, no env gate needed. PipeWire data is always available. |
| `PI4AUDIO_MEAS_DIR` | (unset) | Override measurement directory path. Set in webui systemd service file on Pi. |
| `PLAYWRIGHT_BROWSERS_PATH` | (set by flake) | Path to Playwright's Chromium. Set automatically in `nix develop` and `nix run`. |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | `1` (set by flake) | Prevents Playwright from downloading browsers (Nix provides them). |


## 6. Project Layout

```
mugge/
  flake.nix                       Nix flake — all deps, packages, test targets
  flake.lock                      Pinned Nix inputs
  configs/                        Version-controlled Pi configs
    pipewire/                     PipeWire config fragments (quantum, filter-chain convolver)
    wireplumber/                  WirePlumber config fragments (D-043: linking disabled)
    labwc/                        Wayland compositor config
    systemd/                      Systemd unit files and overrides
    udev/                         udev rules (USBStreamer ALSA lockout, US-044)
    room-correction/              Room correction pipeline configs
    speakers/                     Speaker identity profiles
    camilladsp/                   Historical CamillaDSP configs (service stopped, D-040)
  src/
    graph-manager/                Rust GraphManager — sole PipeWire link manager (D-039)
    signal-gen/                   Rust RT signal generator — measurement audio source
    pcm-bridge/                   Rust PipeWire monitor tap (lock-free level metering)
    web-ui/                       FastAPI web UI + monitoring dashboard
      app/                        FastAPI application
        collectors/               Backend data collectors (FilterChain, Levels, System, PW)
        measurement/              Measurement daemon (session, routes)
        mock/                     Mock backends for development
      static/                     Frontend assets (HTML, JS, CSS)
      tests/                      Unit + integration tests
        e2e/                      Playwright e2e tests
          screenshots/            Visual regression reference images
    room-correction/              DSP pipeline (sweep, deconvolution, filters)
      tests/                      Unit tests (15+ test files)
    measurement/                  Measurement client libraries (GraphManager, signal-gen)
    midi/                         MIDI daemon
      tests/                      MIDI daemon tests
  scripts/
    deploy/deploy.sh              Deployment script (9 sections)
    test/                         Hardware test scripts
    stability/                    Stability test scripts
    launch/                       Application launch scripts
    drivers/                      Driver validation
      tests/                      Driver validation tests
  docs/
    architecture/                 Architecture documents (rt-audio-stack, web-ui, etc.)
    operations/safety.md          Safety manual — read before audio-producing operations
    lab-notes/                    Session lab notes (CHANGE, DEPLOY, OBSERVE)
    project/                      Status, decisions, assumptions, user stories
    guide/howto/                  This file and future HOWTOs
    theory/                       Design rationale, signal processing theory
```


## 7. Continuous Integration (US-070)

The project uses GitHub Actions for CI. The workflow is defined in
`.github/workflows/ci.yml`.

### 7.1 What Triggers CI

| Event | Scope | Behavior |
|-------|-------|----------|
| `push` | Any branch (`**`) | Runs on every push to any branch |
| `pull_request` | `main` branch | Runs on PR creation and each subsequent push |

A concurrency group (`ci-<ref>`) cancels in-progress runs when a newer commit
is pushed to the same branch, so you do not waste CI minutes on superseded
commits.

### 7.2 CI Jobs

CI runs two parallel jobs on `ubuntu-latest` (GitHub-hosted) runners:

| Job | What it runs | Typical duration |
|-----|-------------|-----------------|
| **`test-all`** | `nix run .#test-all` (web-ui unit, room-correction, midi, drivers, graph-manager via cargo), then individual Rust targets: `test-graph-manager`, `test-pcm-bridge`, `test-signal-gen` | 5-15 min |
| **`test-e2e`** | `nix run .#test-e2e` (Playwright browser tests against mock server) | 7-20 min |

Both jobs install Nix via `cachix/install-nix-action` and cache the Nix store
via `nix-community/cache-nix-action` (keyed on `flake.lock` hash). The first
run after a cache miss is slow (full Nix build); subsequent runs use cached
store paths.

### 7.3 Reading CI Results

- **GitHub PR page:** Check the "Checks" tab for per-job status.
- **GitHub Actions tab:** See full logs for each step.
- **Failed step:** Expand the failed step to see pytest or cargo test output.
  The test name and assertion message are usually sufficient to identify the
  failure.

### 7.4 Branch Protection

Branch protection on `main` requires both `test-all` and `test-e2e` to pass
before a PR can be merged. Force-push to `main` is disabled. Squash merge is
the default merge strategy (clean main history).

Workers create feature branches for their work (naming convention:
`<story-id>/<short-description>`, e.g., `us-064/graph-rework`), open PRs
against `main`, and merge only after CI passes.

### 7.5 Flaky Test Policy

A flaky test is a bug, not an inconvenience:

- **Do not** add retry logic or "re-run until green" workflows.
- **Do** file a defect and quarantine the test (`@pytest.mark.skip` with the
  defect ID) until fixed.
- CI failure on a flaky test blocks the PR until the test is fixed or properly
  quarantined.
