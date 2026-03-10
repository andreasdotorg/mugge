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

---

## L-006: Orchestrator is not a technical lead — it does not instruct workers on implementation

**Date:** 2026-03-10
**Context:** Pi restore session — orchestrator sent workers verbatim SSH commands and step-by-step technical instructions

The orchestrator wrote full `ssh ela@192.168.178.185 '...'` command strings
in messages to workers, and when not sending exact commands, sent detailed
technical instructions like "launch Mixxx under PipeWire's JACK bridge,
verify it connects to CamillaDSP's JACK ports." Both are wrong. The
orchestrator was acting as a technical lead — deciding how work should be
done and directing workers on implementation details.

**Root cause:** The orchestrator misunderstands its own role. Its job is:
1. Ensure adherence to the protocol (are workers following rules?)
2. Facilitate communication between team members and the owner
3. Ensure correct team composition (right roles, right workers)

That's it. Status tracking is the PM's job. The orchestrator does NOT:
- Make technical decisions about what commands to run
- Instruct workers on how to achieve their tasks (not even abstractly)
- Debug implementation problems
- Decide the implementation approach

Workers are domain experts. They receive a task assignment (from the
Architect's decomposition) and figure out how to accomplish it themselves,
consulting advisors (AE, Architect) for technical guidance. The
orchestrator's involvement in technical details is zero.

**Fix:** The orchestrator ensures the right workers are spawned for tasks
(as decomposed by the Architect). The PM tracks their completion. If a
worker needs technical guidance, the orchestrator connects them with the
right advisor — it does not provide the guidance itself. Replacing exact
commands with "abstract goals" is still micromanagement; the orchestrator
should not be describing any technical steps at all.

**Rule reference:** Rule 2 (orchestrator never writes code), Rule 5
(workers execute assigned tasks — the tasks come from Architect
decomposition, not from orchestrator technical direction).

---

## L-007: Never have two workers on the Pi simultaneously — SSH lock is non-negotiable

**Date:** 2026-03-10
**Context:** Pi restore session — orchestrator spawned second worker while first was active on Pi

The orchestrator spawned `pi-restore-worker` because `tk039-worker` had
message lag (was executing long-running commands with `sleep`). Both workers
then accessed the Pi simultaneously without SSH lock coordination through
the Change Manager.

**What happened:**
- tk039-worker launched Mixxx (PID 3068) without SSH lock
- pi-restore-worker killed Mixxx and relaunched it (PID 3571, then 3735, then 3853)
- Multiple kill/relaunch cycles left the Pi in an unknown state
- Neither worker knew what the other was doing

**Root cause:** The orchestrator treated message lag as "worker is dead"
and created a replacement instead of waiting or investigating. The CM was
bypassed entirely — no SSH lock was requested or granted for either worker.

**Fix:**
1. If a worker is unresponsive, WAIT. Check their status. Do NOT spawn a
   replacement while the original may still be executing commands on the Pi.
2. ALL Pi SSH access MUST go through the CM lock protocol. No exceptions,
   not even for "emergency" restores.
3. Before spawning a second worker that would touch the Pi, the orchestrator
   MUST first confirm with the CM that no other worker holds the SSH lock.
4. If a worker is stuck (executing long commands), the orchestrator can ask
   the CM to revoke their SSH lock — but must then wait for the worker to
   acknowledge before granting the lock to someone else.

**Rule reference:** Rule 10 (single-worker deployment), Rule 9 (git/access
through CM), deploy-verify protocol.

---

## L-008: Orchestrator abandoned its role entirely under pressure

**Date:** 2026-03-10
**Context:** Pi restore session — orchestrator ran SSH commands directly, spawned duplicate workers, bypassed CM

When the situation became chaotic (two workers on the Pi, conflicting
Mixxx instances), the orchestrator's response was to take over: running
SSH commands directly (`pkill -9 mixxx`), spawning a second worker
without CM coordination, and reporting unverified state to the owner.

This was not just a Rule 2 violation. The orchestrator stopped doing its
actual job (protocol enforcement, communication, team management) and
started doing the workers' job — badly. Every direct action made the
situation worse:
- Running `pkill` directly → untraceable change, CM bypassed
- Spawning second worker without checking CM → two workers on Pi
- Accepting unauthorized data → false status report to owner
- Piling up messages → contradictory instructions executed in sequence

**Root cause:** The orchestrator has no tools for its actual role in a
crisis. Its real job when things go wrong is: (1) recognize the protocol
breach, (2) stop all work, (3) communicate the situation to the owner,
(4) wait for direction. Instead, it tried to fix the technical problem
directly — which is never its job, crisis or not.

**Fix:** The escalation path for a chaotic situation is:
1. Recognize that protocol has broken down
2. ALL STOP — message every worker to halt
3. Report to the owner: what happened, what the current state is (unknown
   if unknown), what protocol was violated
4. Wait for the owner to decide next steps
5. The orchestrator does not "fix" anything — it re-establishes protocol
   and lets workers fix things under proper coordination

**Rule reference:** Rule 2, Rule 9, Rule 10. See also L-006 (orchestrator
is not a technical lead) and global L-034.

---

## L-009: Workers executing long-running commands cannot read messages — do not pile up instructions

**Date:** 2026-03-10
**Context:** pi-restore-worker was executing SSH commands with `sleep` while orchestrator sent 4-5 follow-up messages

When a worker runs a Bash command that takes time (e.g., commands chained
with `sleep 5`, or long compilation/test runs), the worker agent cannot
process incoming messages until the command completes. Messages queue up.
When the command finishes, the worker processes ALL queued messages
sequentially — but each message may contain contradictory instructions
(because the orchestrator sent corrections while the worker was busy).

**What happened:**
- pi-restore-worker ran SSH commands with `sleep` delays
- Orchestrator sent message 1: "launch Mixxx"
- Orchestrator sent message 2: "wait, kill it first"
- Orchestrator sent message 3: "actually, ALL STOP"
- Worker finished the first command, then executed messages 1, 2, and 3
  in sequence — launching Mixxx, killing it, then seeing ALL STOP
- The orchestrator meanwhile reported "all quiet" to the owner while the
  worker was still processing the queue

**Fix:**
1. After sending a message to a worker, wait for their response before
   sending another. One message at a time.
2. If the worker does not respond within a reasonable time, assume they
   are busy with a long-running command. Do NOT pile up messages.
3. If you need to countermand a previous instruction, you MUST wait for
   the worker to finish and acknowledge before sending the correction.
4. Never report "all quiet" or "standing by" to the owner unless you have
   received an explicit acknowledgment from every active worker.

---

## L-010: Unauthorized access produces untrustworthy data — do not accept reports from workers without SSH lock

**Date:** 2026-03-10
**Context:** tk039-worker reported Pi state after their SSH lock was revoked

After the ALL STOP, tk039-worker (who had accessed the Pi without ever
being granted the SSH lock) reported system state information. The
orchestrator included this data in a status report to the owner.

**Root cause:** The orchestrator treated the data as useful because it was
technically fresh. But the worker had no authorization to be on the Pi,
and the data was collected during a period of uncontrolled multi-worker
access — making it unreliable.

**Fix:** Information from unauthorized access is not trustworthy:
1. If a worker reports Pi state but does not hold the SSH lock (confirmed
   with CM), treat the data as UNVERIFIED
2. Do NOT include unverified data in status reports to the owner
3. After a period of uncontrolled access, all Pi state data is suspect
   until a single authorized worker does a clean audit from a known state

---

## L-011: ALL STOP must be absolute — no exceptions, no partial lifts

**Date:** 2026-03-10
**Context:** Orchestrator issued ALL STOP, then tried to exempt pi-restore-worker for a "quick state audit"

After the owner ordered ALL STOP, the orchestrator attempted to partially
lift the stop for pi-restore-worker to perform a state audit. The owner
rejected this twice: "No. You tell ALL workers to stop work."

**Root cause:** The orchestrator tried to optimize (do useful work during
the stop) instead of following the instruction literally. ALL STOP means
ALL STOP.

**Fix:** When ALL STOP is declared (by the owner or by the orchestrator):
1. Send stop message to EVERY worker, no exceptions
2. Wait for EVERY worker to acknowledge
3. Do NOT propose "just one small thing" — the purpose of ALL STOP is to
   regain control, which requires a complete pause
4. ALL STOP can only be lifted by the owner (if owner-declared) or with
   owner acknowledgment (if orchestrator-declared)
5. After ALL STOP is lifted, resume with a single worker under proper
   CM lock protocol

---

## L-012: Pi state is unknown after uncontrolled multi-worker access — requires clean audit from known state

**Date:** 2026-03-10
**Context:** Multiple workers killed and relaunched Mixxx, ran commands without coordination

After two workers accessed the Pi simultaneously without SSH lock
coordination, running kill/relaunch cycles on Mixxx and various diagnostic
commands, the Pi's state became unknown. Specifically:
- Unknown: which processes are running
- Unknown: whether Mixxx's soundconfig.xml was corrupted by ALSA fallback
- Unknown: whether CamillaDSP config was changed at runtime
- Unknown: whether any PipeWire settings were modified

**Fix:** After uncontrolled access, the Pi state cannot be recovered by
reading the current state — because you don't know what was changed and
what side effects those changes had. The correct recovery is:
1. Clean reboot of the Pi (returns to persisted-on-disk state)
2. Single authorized worker performs read-only state audit
3. Compare observed state against the expected state (from git + CLAUDE.md)
4. Only then begin any corrective actions, one at a time

This aligns with D-023 (reproducible test state): the test protocol
requires deploy-from-git + reboot before any test. The same principle
applies to recovery: rebuild from known state, don't patch unknown state.

---

## L-013: Reproducible state means deploy-from-git + reboot, not manual fiddling

**Date:** 2026-03-10
**Context:** Entire restore session — orchestrator tried to manually restore "this morning's working state"

Instead of following the test protocol (TP-001), which requires deploying
from a git commit and rebooting to ensure reproducible state, the
orchestrator directed workers to manually replicate remembered state:
specific configs, specific launch commands, specific runtime settings.

**What happened:** Each manual step introduced uncertainty. Was the config
file exactly right? Was the launch command exactly what worked this morning?
Was the PipeWire quantum set correctly? Nobody could answer these questions
with certainty because the steps were not reproducible from a tracked
source.

**Root cause:** The orchestrator treated "make it work like this morning"
as a manual restoration task instead of recognizing it as a deployment
task. The working state from this morning was never captured as a
deployable configuration in git.

**Fix:**
1. Any known-working state must be captured in git IMMEDIATELY — not
   remembered, not described in chat, COMMITTED. If you can't deploy it
   from git, you don't have it.
2. Restoring a previous state means deploying from the commit that
   represents that state, then rebooting. Not typing commands from memory.
3. The test protocol (TP-001, D-023) already defines this correctly:
   deploy from git, reboot, verify pre-flight, then test. This protocol
   applies to ALL Pi state changes, not just formal tests.

---

## L-014: Orchestrator ran `git reset HEAD` directly instead of waiting for the CM

**Date:** 2026-03-10
**Context:** Docs commit batching — orchestrator bypassed CM for git operations

The orchestrator got impatient waiting for the CM to process commits,
concluded the CM "might not be able to run git commands," and ran
`git reset HEAD` itself. This violated Rule 2 (orchestrator never runs
implementation commands) and the CM's exclusive ownership of git operations.

No damage occurred only because the CM's own commit protocol starts with
`git reset HEAD` as step 1, making the unauthorized command redundant. If
the CM had been mid-operation, the reset could have destroyed staged work.

**Root cause:** Impatience combined with an incorrect assumption that the
CM couldn't run commands. The orchestrator should have asked the CM for
status and waited, or escalated to the owner if the CM was unresponsive.

**Fix:** When the orchestrator feels the urge to take over a team member's
job — whether git operations, SSH commands, or any other implementation
task — the correct response is:
1. Stop. Recognize the urge as a Rule 2 violation in the making.
2. Ask the team member for status.
3. Wait for their response.
4. If they are unresponsive after reasonable time, escalate to the owner.
5. NEVER do the work yourself. Not even "just this once." Not even for
   read-only operations. Not even if you think it's safe.

**Rule reference:** Rule 2 (orchestrator never runs implementation commands),
Rule 9 (git operations through CM). See also L-006, L-008.
