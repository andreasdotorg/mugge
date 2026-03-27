# US-070 Completeness Assessment

**Assessed by:** worker-measure
**Date:** 2026-03-22
**Story:** US-070 — GitHub Actions CI with Self-Hosted Runner

## Summary

US-070 is partially implemented. The workflow file and test-everything flake target
exist, but several acceptance criteria are not met, the workflow has deviations from
the story spec, and the DoD has unfinished items.

## Implementation Artifacts

| Artifact | Path | Status |
|----------|------|--------|
| CI workflow | `.github/workflows/test.yml` | Exists (31 lines) |
| test-everything target | `flake.nix` lines 414-447 | Exists |
| Runner setup script | `scripts/ci/setup-runner.sh` | Exists (100 lines) |
| Runner documentation | `docs/guide/howto/development.md` | NOT WRITTEN |

## AC-by-AC Assessment

### AC1: Self-hosted runner setup
- **Runner installed:** UNKNOWN (requires dev machine access to verify)
- **Unprivileged user:** Setup script creates `github-runner` user -- DESIGNED but unverified
- **Nix store access:** Setup script adds `github-runner` to `nix-users` group -- DESIGNED
- **Systemd service:** Setup script installs `github-runner.service` -- DESIGNED
- **Runner labels:** Setup script registers with `--labels Linux,ARM64`
  - **GAP:** Story AC says `self-hosted, linux, aarch64`. Script uses `Linux,ARM64`.
    The `self-hosted` label is auto-added by GitHub, so that's fine. But `ARM64` vs
    `aarch64` is a mismatch, and `Linux` vs `linux` differs in case.
- **Status:** DESIGNED, NOT VERIFIED (owner needs to run `scripts/ci/setup-runner.sh`)

### AC2: Workflow definition
- **Filename:** `test.yml`, NOT `ci.yml` as specified in AC. Minor naming deviation.
- **Triggers:**
  - Push: `branches: [main]` only. **GAP:** AC says "push to any branch."
  - PR: `branches: [main]` -- MATCHES AC.
- **Jobs:** Two parallel jobs (`test-all`, `test-e2e`) -- MATCHES.
- **runs-on:** `[self-hosted, Linux, ARM64]`
  - **GAP:** AC says `[self-hosted, linux, aarch64]`. Case and label mismatch with AC.
- **Committed code:** `actions/checkout@v4` used -- MATCHES (runs against committed code).
- **test-all scope:** Runs `nix run .#test-all`, which includes web-ui unit, room-correction,
  midi, drivers, and graph-manager. **GAP:** `test-all` does NOT include pcm-bridge or
  signal-gen (they're Linux-only targets, separate in flake.nix). AC2 says test-all should
  include pcm-bridge and signal-gen.
- **Nix installer:** Uses `DeterminateSystems/nix-installer-action@main` in both jobs.
  This is unnecessary if the self-hosted runner already has Nix installed (the setup script
  installs Nix). It won't break anything but adds ~30s per job.
- **Workflow committed:** YES.

### AC3: Branch protection rules
- **NOT CONFIGURED.** This is a manual GitHub settings action by the owner.
  The story notes this is a manual step. No evidence of configuration.

### AC4: PR-based workflow enablement
- **NOT CONFIGURED.** Depends on AC3 (branch protection). The workflow supports PR
  triggers on `main`, but the branch protection enforcement is missing.
- **Squash merge default:** NOT CONFIGURED (GitHub repo settings).

### AC5: Nix caching
- **Self-hosted runner inherently has persistent Nix store** -- MATCHES design intent.
- **No GitHub cache actions used** -- MATCHES.
- **Status:** Will be met once runner is installed.

### AC6: Flaky test handling
- **Policy-level AC.** No enforcement mechanism in the workflow. The policy exists in
  testing-process.md. No `pytest.mark.skip` quarantine examples found.
- **Status:** POLICY EXISTS, no automated enforcement.

### AC7: Security considerations
- **Single-owner repo:** TRUE.
- **Runner SSH to Pi:** Setup script doesn't grant Pi access -- MATCHES.
- **Secrets in workflow:** No secrets used in `test.yml` -- MATCHES.

## DoD Assessment

| # | DoD Item | Status |
|---|----------|--------|
| 1 | Runner registered and running as systemd service | NOT DONE (script exists, not executed) |
| 2 | `.github/workflows/ci.yml` committed and functional | PARTIAL -- file is `test.yml`, not `ci.yml` |
| 3 | Both jobs pass on current `main` | NOT VERIFIED (runner not set up) |
| 4 | Branch protection configured on `main` | NOT DONE |
| 5 | Test PR verified (merge blocked on failure, allowed on success) | NOT DONE |
| 6 | Documentation in `docs/guide/howto/development.md` | NOT DONE |
| 7 | QE sign-off | NOT DONE |

## test-everything Flake Target

The `test-everything` target (flake.nix lines 414-447) runs:
1. Web-UI unit/integration tests (pytest, 308 tests)
2. Room-correction tests (pytest, 339 tests)
3. MIDI tests (pytest, 60 tests)
4. Drivers tests (pytest, 32 tests)
5. Graph-manager tests (cargo test -- **fails in Nix sandbox** with `Permission denied` writing to store path)
6. E2E browser tests (Playwright pytest)

**Test run results (2026-03-22):**
- Python suites: 308 + 339 + 60 + 32 = 739 passed
- Graph-manager (Rust): FAILS in Nix sandbox (cargo can't write `target/` inside `/nix/store`)
- E2E: Not reached due to graph-manager failure

**Root cause of graph-manager failure:** `test-everything` uses `cd ${toString ./.}/src/graph-manager`
which resolves to the Nix store copy. Cargo needs a writable `target/` directory. The standalone
`test-graph-manager` target has the same issue. This needs `CARGO_TARGET_DIR` set to a writable
location (e.g., `$TMPDIR`).

**Note:** pcm-bridge and signal-gen are NOT included in `test-everything`. They are Linux-only
targets (`test-pcm-bridge`, `test-signal-gen`) gated behind `pkgs.stdenv.hostPlatform.isLinux`.
The CI workflow doesn't reference them either. AC2 says they should be part of `test-all`.

## Gaps Summary (Actionable)

1. **Workflow filename:** `test.yml` vs AC-specified `ci.yml`
2. **Push trigger:** Only `main`, AC says "any branch"
3. **Runner labels:** `Linux,ARM64` vs AC `linux,aarch64` (case + naming)
4. **runs-on labels:** Same mismatch in workflow file
5. **test-all scope:** Missing pcm-bridge and signal-gen
6. **test-everything broken:** Graph-manager cargo test fails in Nix sandbox
7. **No concurrency groups:** Risk #1 in story mentions this, not implemented
8. **Runner not installed:** Manual owner action, setup script ready
9. **Branch protection not configured:** Manual owner action
10. **No documentation:** Runner setup/maintenance docs missing from development.md
11. **Nix installer action redundant:** Self-hosted runner will already have Nix

## Recommendation

US-070 should remain in IMPLEMENT phase. The workflow and flake target need fixes
(items 1-7) before the manual steps (items 8-9) and documentation (item 10) can
proceed. Specifically:

- Fix `test-everything` to set `CARGO_TARGET_DIR` for Rust tests
- Decide whether to rename `test.yml` to `ci.yml` or update the AC
- Add push trigger for all branches (or update AC)
- Add pcm-bridge + signal-gen to test-all (or document why they're separate)
- Add concurrency groups per Risk #1
- Write runner documentation in development.md
