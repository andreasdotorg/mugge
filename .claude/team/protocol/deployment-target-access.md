# Deployment Target Access

Projects that operate on external systems (servers, clusters, devices, cloud
accounts) declare **deployment targets** in the project's `config.md`. Access
to these targets is managed by the Change Manager through a tiered access
model based on a readers-writer lock.

## Terminology

- **Deployment target:** Any external system the team deploys to or operates
  on. Declared in project config with a name, access mechanism, and access
  controller.
- **Target session:** A time-bounded period during which an agent has
  authorized access to a deployment target at a specific tier.
- **Session holder:** The agent currently holding a target session.

## Access Tiers

### Tier 1: OBSERVE (shared read)

Non-destructive inspection of the deployment target. Reading state, checking
logs, listing processes, querying configuration. No state changes.

| Property | Value |
|----------|-------|
| Concurrency | **Shared.** Multiple OBSERVE sessions may be active simultaneously. |
| Who may request | Any worker or advisor with a task that requires target state information. |
| Grant authority | Change Manager grants without approval chain. Lightweight: request → grant. |
| Allowed operations | Read-only. Process listing, log reading, config inspection, service status, device queries, monitoring. Any command that leaves zero trace on the target. |
| Prohibited operations | Anything that modifies state: killing processes, editing files, restarting services, changing runtime config, installing packages, launching applications, rebooting. |
| Duration | Time-bounded. Default: 10 minutes (configurable per target in project config). Auto-expires. Agent must re-request for extension. |
| Notification | Change Manager logs the session. No other notification required. |
| Blocked by | An active CHANGE or DEPLOY session blocks new OBSERVE requests. OBSERVE sessions must drain before CHANGE or DEPLOY can be granted. |

**Request flow:**

```
Worker → CM: "Request OBSERVE session on <target> for <purpose>"
CM → Worker: "OBSERVE session granted. Expires in <N> minutes. Read-only only."
Worker: [executes read-only commands, reports findings]
Worker → CM: "Releasing OBSERVE session" (or session auto-expires)
```

### Tier 2: CHANGE (exclusive write)

State-modifying operations on the deployment target. Restarting services,
editing configs, killing processes, launching applications, setting runtime
parameters, loading configurations via APIs.

| Property | Value |
|----------|-------|
| Concurrency | **Exclusive.** ONE CHANGE session at a time. No concurrent OBSERVE, CHANGE, or DEPLOY sessions while active. |
| Who may request | A worker assigned to a task that requires target modification, by orchestrator direction. |
| Grant authority | Change Manager grants AFTER verifying: (a) no other session of any tier is active, (b) the worker has a plan approved by the Architect (and domain specialist if applicable). |
| Allowed operations | All operations — reads and writes. The worker follows the approved plan. Ad-hoc deviations require re-consultation with the Architect before execution. |
| Prohibited operations | None inherently, but the worker must not exceed the scope of the approved plan. |
| Duration | Task-bounded. The session lasts until the worker completes the task and releases the session, or the CM revokes it. No auto-expiry, but the CM revokes after a configurable unresponsive timeout (default: 5 minutes of no communication from the session holder). |
| Notification | CM notifies: **Advocatus Diaboli, Quality Engineer, Technical Writer** when the session is granted and when it is released. AD may challenge. QE tracks for test evidence. TW logs for documentation. |
| Rollback | The approved plan MUST include a rollback procedure before the CM grants the session. |
| Pre-conditions | (a) All code changes committed to git (clean working tree). (b) Plan reviewed and approved by the Architect. (c) No other session of any tier is active on this target. |
| Blocked by | Any active session of any tier on the same target. |

**Request flow:**

```
Worker → CM: "Request CHANGE session on <target>. Plan: <reference to approved plan>."
CM: [Verifies: no active sessions, plan exists and is architect-approved,
     git working tree is clean]
CM → AD, QE, TW: "CHANGE session requested by <worker> on <target>. Plan: <ref>."
CM → Worker: "CHANGE session granted. Follow the approved plan.
             Rollback procedure: <ref>. Notify me when complete."
Worker: [executes plan, step by step]
Worker → CM: "CHANGE session complete. Results: <summary>."
CM → AD, QE, TW: "CHANGE session released by <worker>. Results: <summary>."
CM: [logs session, clears lock]
```

### Tier 3: DEPLOY (exclusive, ceremony-heavy)

Formal deployment of version-controlled configuration or software to the
target. This tier adds mandatory pre-challenge, full evidence capture, and
structured verification on top of CHANGE. Used for deployments that must be
reproducible and auditable.

| Property | Value |
|----------|-------|
| Concurrency | **Exclusive.** Same as CHANGE — one session, no concurrent sessions of any tier. |
| Who may request | A worker in the Deploy phase (Phase 5) of a story, assigned by the orchestrator. |
| Grant authority | Change Manager grants AFTER verifying all CHANGE pre-conditions PLUS: (a) AD has completed pre-deployment challenge and the worker has addressed all findings, (b) deploy script or procedure is version-controlled and committed. |
| Allowed operations | Execution of the approved deploy procedure only. No ad-hoc commands. If the deploy script encounters an unexpected state, the worker halts and reports — does not improvise. |
| Duration | Task-bounded with mandatory checkpoints. The worker reports progress at each step of the deploy procedure. |
| Notification | Same as CHANGE, plus: CM notifies the **Project Manager** (for status tracking). |
| Rollback | Mandatory. The rollback plan is a pre-condition — if the deploy fails at any step, the worker executes the rollback before releasing the session. The rollback itself is part of the DEPLOY session (no new session needed). |
| Pre-conditions | All CHANGE pre-conditions, plus: (a) AD pre-deployment challenge completed and findings addressed. (b) Deploy procedure is an executable script or documented step-by-step in version control (not ad-hoc commands). (c) QE has approved the post-deploy verification criteria. |
| Evidence capture | The worker records: deployed git commit hash, command output for each step, pre-deploy and post-deploy target state snapshots, and any deviations from the plan. This evidence is a deliverable of the Deploy phase. |
| Post-deploy | After the deploy procedure completes, the session transitions to Verify (Phase 6). The same worker retains the session for verification. The session is released only after verification completes (pass or fail). On verification failure, the worker executes rollback before releasing. |

**Request flow:**

```
Worker → AD: "Pre-deployment challenge request. Plan: <ref>. Deploy procedure: <ref>."
AD: [challenges assumptions, identifies risks, raises findings]
Worker: [addresses AD findings, updates plan if needed]
AD → Worker: "Pre-deployment challenge complete. Findings addressed."

Worker → CM: "Request DEPLOY session on <target>.
             Plan: <ref>. Deploy procedure: <ref>.
             AD challenge: complete. QE verification criteria: <ref>."
CM: [Verifies: all CHANGE pre-conditions + AD challenge complete +
     deploy procedure in version control + QE criteria exist]
CM → AD, QE, TW, PM: "DEPLOY session granted to <worker> on <target>.
                       Commit: <hash>. Plan: <ref>."
CM → Worker: "DEPLOY session granted. Execute the deploy procedure.
             Report progress at each step. Rollback: <ref>."

Worker: [executes deploy procedure step by step, reports each step to CM]
Worker: [executes post-deploy verification per QE criteria]
Worker → CM: "DEPLOY session complete. Evidence: <ref>. Verification: PASS/FAIL."

[If FAIL: Worker executes rollback, reports to CM]

CM → AD, QE, TW, PM: "DEPLOY session released. Outcome: <PASS/FAIL>.
                       Evidence: <ref>."
CM: [logs session with full evidence, clears lock]
```

## Tier Escalation Rules

Escalation between tiers is **mechanical, not discretionary**. The boundary
is whether the operation modifies target state.

| Rule | Description |
|------|-------------|
| **Read → OBSERVE** | Any command that reads state without modifying it requires OBSERVE at minimum. |
| **Write → CHANGE** | Any command that modifies target state requires CHANGE at minimum. This includes: killing processes, editing files, restarting services, changing runtime configuration, launching applications, installing packages, rebooting, loading configs via API, setting audio parameters, modifying symlinks. |
| **Deploy → DEPLOY** | Any operation that deploys version-controlled configuration or software to the target as a formal, reproducible action requires DEPLOY. |
| **No self-escalation** | An agent holding an OBSERVE session who discovers something that needs fixing MUST release the OBSERVE session, REPORT the finding, and REQUEST a CHANGE session through the standard flow. They MUST NOT execute the fix under the OBSERVE session. |
| **No judgment calls** | The boundary between OBSERVE and CHANGE is not "is this risky?" or "is this safe?" — it is "does this command modify state?" If yes, CHANGE. No exceptions for "trivial" or "low-risk" changes. |

## Timeout and Revocation

| Situation | Action |
|-----------|--------|
| OBSERVE session reaches time limit | CM auto-expires the session. Agent is notified. Agent may re-request. |
| CHANGE/DEPLOY session holder is unresponsive | CM waits for the configurable timeout (default: 5 minutes of no communication). Then CM sends a final warning. If no response within 60 seconds of the warning, CM revokes the session and notifies the orchestrator + AD. |
| Revocation during active operation | The CM revokes the session authorization. If the agent has a command in flight on the target, the command may complete — the CM cannot interrupt remote execution. The CM MUST audit the target state after revocation (via a brief OBSERVE session) and report findings before granting any new session. |
| Emergency revocation (ALL STOP) | The orchestrator (or owner) declares ALL STOP. The CM immediately revokes ALL active sessions. The CM audits the target for any in-flight operations and reports to the owner. No new sessions are granted until the owner lifts ALL STOP. |
| Worker requests upgrade (OBSERVE → CHANGE) | Worker releases OBSERVE. CM verifies all OBSERVE sessions have drained. Worker submits CHANGE request with approved plan. CM grants per CHANGE flow. |

## The Orchestrator and Target Access

**The orchestrator MUST NOT hold or request target sessions at any tier.**

The orchestrator coordinates who gets access and when. The Change Manager
grants access and enforces the lock. The orchestrator never directly
interacts with the deployment target.

Specifically, the orchestrator MUST NOT:
- Execute commands on the deployment target
- Compose target-specific commands (SSH commands, kubectl commands, API
  calls, etc.) in messages to workers
- Request OBSERVE, CHANGE, or DEPLOY sessions from the CM

If the orchestrator needs target state information, it asks a worker to
request an OBSERVE session and report findings. If the orchestrator needs
a change made, it assigns a task to a worker and routes them through the
CHANGE flow.

**If the orchestrator finds itself writing a target-specific command in a
message, it is violating this rule.** The correct action is to describe
the desired outcome and delegate execution to the CM or a worker.

## Change Manager Session State

The CM tracks the following for each deployment target at all times:

```
target: <name>
active_sessions:
  - holder: <agent name>
    tier: OBSERVE | CHANGE | DEPLOY
    granted_at: <timestamp>
    expires_at: <timestamp or null>
    plan_ref: <reference or null>
    last_communication: <timestamp>
```

This state is queryable. Any agent may ask the CM: "What sessions are active
on <target>?" The CM responds with the current state. This enables the
orchestrator to make informed scheduling decisions without accessing the
target directly.

## Migration from SSH Lock

This section replaces the previous "SSH lock" protocol. The mapping is:

| Old concept | New concept |
|-------------|-------------|
| SSH lock | CHANGE or DEPLOY session (depending on context) |
| "Request SSH lock from CM" | "Request CHANGE session with approved plan" |
| "CM grants SSH lock" | "CM grants CHANGE session after verification" |
| "Release SSH lock" | "Release CHANGE session with results summary" |
| Read-only Pi access (no lock) | OBSERVE session (now formalized — was previously informal/ungated) |
| Rule 10 (single-worker deployment) | Subsumed by CHANGE/DEPLOY exclusivity. Rule 10 references this section. |
