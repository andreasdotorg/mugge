# TK-039: Deploy Cycle 2 — libjack Alternatives Configuration

> **Evidence basis: CONTEMPORANEOUS**
>
> TW is receiving real-time CM notifications (DEPLOY sessions S-005, S-006,
> and S-007) and recording events as they occur. Commands and output below
> come from CM forwarded reports, not post-hoc briefings.

Configures `update-alternatives` for `libjack.so.0` on the Pi so that
PipeWire's JACK implementation is the system default. This eliminates the
need for the `pw-jack` wrapper when launching Mixxx (resolves F-021 root
cause) and prevents the silent ALSA fallback that triggered the original
TK-039 session failure.

This is Deploy Cycle 2, following the successful Cycle 1 config manifest
deployment (S-004, documented in `docs/lab-notes/TK-039-deploy-cycle1.md`).

### Ground Truth Hierarchy

1. `CLAUDE.md` "Pi Hardware State" section (verified 2026-03-10)
2. The Pi itself (live state via SSH)
3. `configs/` directory in this repository

**SETUP-MANUAL.md is OBSOLETE.** Do not use as source of truth.

### Session Metadata

| Field | Value |
|-------|-------|
| CM session | S-005 (DEPLOY) |
| Session holder | pi-recovery-worker |
| Deployment target | Pi audio workstation (`ela@192.168.178.185`) |
| Deploy commit | `ca006f8` |
| Deploy script | `configure-libjack-alternatives.sh` |
| Scope | Register libjack alternatives + ldconfig + reboot |
| Rollback | `update-alternatives --set` to JACK2 or `--remove-all` |

### Deploy Plan

1. `--discover` (read-only path verification)
2. `sudo configure-libjack-alternatives.sh` (register alternatives + ldconfig)
3. `sudo reboot`
4. Post-reboot verify (ldconfig + readlink)

### Related Defects

- **F-021:** Mixxx silently falls back from JACK to ALSA when launched without
  `pw-jack` (libjack.so.0 resolves to JACK2, no alternatives configured)
- **F-022:** Mixxx autostart launches bare without `pw-jack`, re-triggers F-021
- **TK-061:** Configure `update-alternatives` for libjack (this deploy)

---

## Step 1: Discover (Read-Only Path Verification)

**Status:** Executed (authorized, read-only) — **FAIL (path mismatch)**
**Operator:** pi-recovery-worker via CM session S-005

```
$ configure-libjack-alternatives.sh --discover
```

The script's `--discover` mode revealed that the hardcoded library paths do
not match the actual library versions installed on the Pi:

| Library | Script expects | Actual on Pi |
|---------|---------------|-------------|
| PipeWire libjack | `libjack.so.0.4096.0` | `libjack.so.0.3.1402` |
| JACK2 libjack | `libjack.so.0.2.0` | `libjack.so.0.1.0` |

The script's `check_library_exists()` fail-safe caught the mismatch and
exited cleanly. **Zero mutations on the Pi.** This is a successful fail-safe,
not a script bug -- the hardcoded paths were best-guesses for Debian Trixie
(documented in script comments at lines 31-33). The actual Pi has different
library versions than anticipated.

---

## Session Outcome

**S-005 CLOSED — CLEAN (zero mutations).** Steps 2-4 not executed. The
discover step's fail-safe prevented any changes. Pi unchanged.

Session released per orchestrator direction. The script needs to be updated
with the correct library paths from the Pi before Cycle 2 can be retried.

---

## Findings Register

| ID | Source | Severity | Description | Status |
|----|--------|----------|-------------|--------|
| C2-1 | S-005 Step 1 | Medium | Hardcoded libjack paths in `configure-libjack-alternatives.sh` don't match Pi library versions. Script fail-safe worked correctly. | Resolved -- paths corrected in `0669fc8` |
| C2-2 | S-006 Step 3 | High | Package-owned symlink (`/usr/lib/.../libjack.so.0`) bypasses alternatives chain. `update-alternatives` registration is ineffective -- system still resolves to JACK2. | Superseded by C2-3 (deeper root cause) |
| C2-3 | S-007 Step 3 | High | `ldconfig` soname management fundamentally incompatible with `update-alternatives` for shared libraries. `ldconfig` recreates soname symlink from JACK2 `.so.0.1.0` file regardless of alternatives/divert. Entire approach abandoned. | Resolved -- D-027: `pw-jack` is permanent solution, TK-061 won't-fix |

---

*Session S-005 closed. Zero mutations. Script fix required before Cycle 2
retry.*

---

# S-006: Cycle 2 Retry (Corrected Library Paths)

Script updated with correct library paths from the Pi (commit `0669fc8`).
S-006 is a retry of the same scope as S-005.

### Session Metadata (S-006)

| Field | Value |
|-------|-------|
| CM session | S-006 (DEPLOY) |
| Session holder | pi-recovery-worker |
| Deployment target | Pi audio workstation (`ela@192.168.178.185`) |
| Deploy commit | `0669fc8` |
| Deploy script | `configure-libjack-alternatives.sh` (corrected paths) |
| Scope | Register libjack alternatives + ldconfig + reboot |
| Rollback | `update-alternatives --set` to JACK2 or `--remove-all` |

### Deploy Plan (S-006)

1. SCP script to Pi `/tmp/`
2. `--discover` (verify corrected paths match)
3. Register alternatives + ldconfig
4. `sudo reboot`
5. Post-reboot verify (ldconfig + readlink)
6. Cleanup `/tmp/` script

---

## S-006 Steps 1-3: SCP, Discover, Register Alternatives

**Status:** Steps 1-2 executed (authorized). Step 3 partially executed.
**Operator:** pi-recovery-worker via CM session S-006

Steps 1 (SCP to Pi) and 2 (discover with corrected paths) succeeded.
Step 3 (`update-alternatives` registration + ldconfig) partially succeeded:

- `update-alternatives --install` registered both PipeWire and JACK2
  libjack implementations
- `/etc/alternatives/libjack.so.0` correctly points to PipeWire's
  `libjack.so.0.3.1402`

### Finding C2-2: Package-Owned Symlink Bypasses Alternatives Chain

**Severity:** High
**Impact:** `update-alternatives` is ineffective — system still resolves to JACK2

The actual library symlink at `/usr/lib/aarch64-linux-gnu/libjack.so.0` is
**package-owned** by `libjack-jackd2-0` and points directly to JACK2's
`libjack.so.0.1.0`. It does NOT go through the alternatives chain at
`/etc/alternatives/libjack.so.0`.

```
Alternatives chain (correct):
  /etc/alternatives/libjack.so.0 -> PipeWire libjack.so.0.3.1402

Actual system symlink (wrong — bypasses alternatives):
  /usr/lib/.../libjack.so.0 -> JACK2 libjack.so.0.1.0
```

The `update-alternatives` mechanism only works if the "master" symlink
(`/usr/lib/.../libjack.so.0`) points to `/etc/alternatives/libjack.so.0`,
which then resolves to the selected implementation. But the JACK2 Debian
package owns the master symlink directly, bypassing the alternatives
indirection entirely. This means registering alternatives has no effect on
runtime library resolution -- `ldconfig` and `ld.so` still resolve to JACK2.

---

## S-006 Session Outcome

**S-006 CLOSED — PARTIAL.** `update-alternatives` entries registered but
ineffective due to package-owned symlink bypass (C2-2). Pi is in a mixed
state: alternatives registered but not active. System still resolves
`libjack.so.0` to JACK2.

Session released per orchestrator direction. Fix approach: `dpkg-divert` will
be used to take ownership of the master symlink from the JACK2 package,
allowing the alternatives chain to function. This fix will be committed and
deployed in a new session (Cycle 2 final retry).

---

*S-006 closed. Cycle 2 final retry pending with dpkg-divert fix.*

---

# S-007: Cycle 2 Final Retry (dpkg-divert Fix)

Script updated with `dpkg-divert` to take ownership of the master symlink
from the JACK2 package before registering alternatives (commit `0b6d714`).
This addresses Finding C2-2 from S-006.

### Session Metadata (S-007)

| Field | Value |
|-------|-------|
| CM session | S-007 (DEPLOY) |
| Session holder | pi-recovery-worker |
| Deployment target | Pi audio workstation (`ela@192.168.178.185`) |
| Deploy commit | `0b6d714` |
| Deploy script | `configure-libjack-alternatives.sh` (dpkg-divert fix) |
| Scope | Divert package symlink + register alternatives + ldconfig + reboot |
| Rollback | `dpkg-divert --remove` + `update-alternatives --remove-all` |

### Deploy Plan (S-007)

1. SCP script to Pi `/tmp/`
2. `--discover` (verify paths + divert capability)
3. Divert + register alternatives + verify
4. `sudo reboot`
5. Post-reboot verify (ldconfig + readlink)
6. Cleanup `/tmp/` script

---

## S-007 Steps 1-3: SCP, Discover, Divert + Register

**Status:** Steps 1-2 executed. Step 3 executed but ineffective.
**Operator:** pi-recovery-worker via CM session S-007

Steps 1-2 (SCP, discover) succeeded. Step 3 (dpkg-divert + register
alternatives) executed, but a fundamental conflict was discovered:

### Finding C2-3: ldconfig Soname Management Overwrites Alternatives

**Severity:** High
**Impact:** The entire `update-alternatives` approach for libjack is
fundamentally incompatible with how `ldconfig` manages shared library
soname symlinks.

`ldconfig` automatically creates a soname symlink based on the ELF SONAME
embedded in shared library files. Because JACK2's actual library file
(`libjack.so.0.1.0`) is physically present in `/usr/lib/aarch64-linux-gnu/`,
`ldconfig` always recreates:

```
/usr/lib/aarch64-linux-gnu/libjack.so.0 -> libjack.so.0.1.0
```

This happens regardless of what `update-alternatives` or `dpkg-divert` sets
at that path. Confirmed by test: manually fixing the symlink to point to
PipeWire, then running `ldconfig`, immediately reverts it to JACK2.

The `dpkg-divert` fix from S-006 only diverted the package-owned symlink,
not the actual `.so.0.1.0` library file. `ldconfig` uses the library file
directly to recreate the soname link -- it does not respect the alternatives
chain or the diversion.

**Root cause:** `update-alternatives` is designed for binaries in `$PATH`
(e.g., `/usr/bin/editor`), not for shared libraries managed by `ldconfig`.
Shared library resolution is handled by `ldconfig`'s soname mechanism, which
operates at a lower level than the alternatives system.

**Implication:** The `configure-libjack-alternatives.sh` approach may need
to be abandoned entirely. Three potential alternatives:
1. **`ld.so.conf.d` approach:** Place PipeWire's libjack directory first in
   the library search path, so it shadows JACK2's version.
2. **Accept `pw-jack` as canonical:** Keep the `pw-jack` wrapper as the
   permanent solution and ensure all launch paths use it.
3. **Remove JACK2 package:** If JACK2 is not needed independently, removing
   `libjack-jackd2-0` would eliminate the conflicting library file.

Awaiting architect guidance on which approach to pursue.

---

## S-007 Session Outcome

**S-007 CLOSED — ROLLBACK.** `dpkg-divert` and `update-alternatives`
entries were applied but proved ineffective -- `ldconfig` overwrites the
symlink (C2-3). The entire `update-alternatives` approach for libjack is
fundamentally incompatible with `ldconfig` soname management. All Cycle 2
changes rolled back; Pi restored to Cycle 1 baseline.

### Architect Decision: D-027

TK-061 (libjack alternatives) is **won't-fix**. Three sessions (S-005,
S-006, S-007) progressively revealed that `update-alternatives` cannot
control shared library resolution for `libjack.so.0`:

1. S-005: Hardcoded paths wrong (script fail-safe worked, C2-1)
2. S-006: Package-owned symlink bypasses alternatives chain (C2-2)
3. S-007: `ldconfig` soname management overwrites any symlink fix (C2-3)

**Resolution:** `pw-jack` via `LD_PRELOAD` is the **permanent solution**,
not a workaround. `start-mixxx.sh` already uses `pw-jack`. All launch
paths (including autostart, F-022) must use it. The `pw-jack` mechanism
operates at a higher level than `ldconfig` — it interposes PipeWire's
libjack via `LD_PRELOAD` before the dynamic linker resolves the soname
symlink, bypassing the entire conflict.

### Cleanup (Rollback Verification)

Partial state from S-006/S-007 cleaned up. All steps PASS:

| Step | Command | Result |
|------|---------|--------|
| 1 | `update-alternatives --remove-all libjack.so.0` | Alternatives group removed |
| 2 | `dpkg-divert --rename --remove /usr/lib/.../libjack.so.0` | Package symlink restored |
| 3 | `ldconfig` | Cache refreshed |
| 4 | `readlink -f libjack.so.0` | Resolves to JACK2 (standard state) |
| 5 | `pw-jack jack_lsp` | PipeWire JACK bridge confirmed working |
| 6 | `rm /tmp/configure-libjack-alternatives.sh` | Temp script removed |

**Pi state:** Cycle 1 baseline. Zero net changes from Cycle 2.

`configure-libjack-alternatives.sh` remains in the repo as documentation
of the attempt but is not deployed.

---

*Cycle 2 closed. Three sessions, zero net mutations. D-027 filed.
`pw-jack` is the permanent libjack strategy.*
