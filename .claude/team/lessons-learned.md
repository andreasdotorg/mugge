# Lessons Learned — Pi4 Audio Workstation

Project-specific process lessons. For global lessons, see
`~/mobile/gabriela-bogk/team-protocol/lessons-learned.md`.

---

## L-001: sshd drop-in files use first-match-wins, not last-match-wins

**Date:** 2026-03-08
**Context:** US-000a security hardening — SSH password auth disable

sshd config processing differs from systemd unit drop-ins:

- **systemd unit drop-ins:** processed in lexical order, **last value wins**
  (higher-numbered files override lower-numbered ones)
- **sshd drop-ins (`/etc/ssh/sshd_config.d/`):** processed in lexical order,
  **first value wins** (lower-numbered files take priority, later duplicates
  are silently ignored)

A `99-hardening.conf` setting `PasswordAuthentication no` was silently ignored
because `50-cloud-init.conf` already set `PasswordAuthentication yes` and was
read first. The fix: use a prefix lower than the file you need to override
(e.g., `40-`), or remove the conflicting file.

**Always verify sshd changes with `sudo sshd -T | grep <directive>` after
reload.** The `-T` flag shows the effective configuration after all drop-ins
are merged.

---

## L-002: Decisions that require Pi changes need implementation tasks

**Date:** 2026-03-09
**Context:** D-018 (wayvnc replaces RustDesk) — declared but never executed

D-018 was recorded in decisions.md and referenced in status.md, but nobody
actually removed RustDesk from the Pi. It was still running with a weak
password, 3 firewall ports still open. The security specialist discovered
this during a cross-team review -- weeks could have passed with the old
software exposed.

**Root cause:** Decisions (D-NNN) are recorded as policy statements. There
is no automatic mechanism to translate a decision into an implementation
task on the Pi.

**Fix:** Any decision that requires Pi changes must have a corresponding
task (TK-NNN) assigned to the change-manager at the time the decision is
recorded. The PM is responsible for filing this task. The decision is not
"implemented" until the task is done and verified.

**Verification:** After a decision's task is complete, the CM or QE should
confirm the Pi state matches the decision (e.g., `dpkg -l rustdesk` returns
"not installed", firewall rules removed, ports closed).

---

## L-003: Worker verification is not owner verification

**Date:** 2026-03-09
**Context:** TK-040 (USBStreamer 8ch in Reaper) — closed prematurely

A worker verified a fix at the system level (`pw-jack jack_lsp` showed
ports), then killed Reaper before the owner could confirm via VNC that the
8 channels were actually visible in the application GUI. TK-040 was marked
done based on worker testing alone.

**Fix:** Any task requiring owner-visible verification (GUI rendering, audio
output, MIDI response) must NOT be closed until the owner confirms via VNC
or direct observation. Worker testing is necessary but not sufficient.
Workers must leave applications running for owner inspection after applying
fixes. This is now a permanent process rule in tasks.md.

---

## L-004: Change Manager is not a worker — do not direct CM to execute Pi commands

**Date:** 2026-03-09
**Context:** Entire session — PM repeatedly directed CM to run SSH commands on Pi

The CM's role is coordination: git operations, access lock tracking, conflict
prevention between workers. All SSH commands on the Pi must be executed by
workers. The PM repeatedly directed the CM to run Pi commands (`fuser`,
`systemctl`, `dpkg --get-selections`, `sudo reboot`, etc.), conflating
"coordinates SSH access" with "executes SSH commands."

**Root cause:** The deploy-verify protocol in config.md says "change-manager
copies files to the Pi" and "worker runs these checks," but the PM treated
the CM as both coordinator and executor.

**Fix:** The CM should:
1. Handle git operations (commit, push, branch management)
2. Track the Pi access lock (who currently has SSH access)
3. Prevent conflicts between workers accessing the Pi simultaneously
4. **Refuse** Pi command execution requests and redirect to a worker

All SSH commands on the Pi — including reboot, service management, package
operations, verification checks — must be executed by workers. The CM grants
the access lock to the worker and tracks it, but does not execute.

---

## L-005: Orchestrator destroyed live team after compaction (sixth global occurrence)

**Date:** 2026-03-10
**Context:** Context compaction in pi4-audio session — team had 14 live agents

After context compaction, the orchestrator assumed all 14 team agents were dead.
Sent shutdown requests, force-cleaned the config file, deleted the team, and
created a new empty one. All agents were in fact alive with full session context
(review findings, architectural decisions, approval history).

This is global L-031 and the sixth time this pattern has occurred across projects.
See global lessons-learned.md for the full analysis and prevention protocol.

**Key takeaway for this project:** The pi4-audio team has expensive-to-rebuild
context: hardware state knowledge, approval chains, F-020/TK-039 analysis.
Destroying the team is far more costly here than in a pure code project.

**Prevention:** See CLAUDE.md STOP block. Do not shut down or recreate the team
after compaction. Ping one agent, wait for response, resume.
