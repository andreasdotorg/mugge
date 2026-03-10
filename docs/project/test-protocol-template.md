# Test Protocol Template

Every significant test in this project requires two documents: a **test protocol**
(written and approved before execution) and a **test execution record** (written
during and after execution). This template defines the required structure for both.

A test protocol is not a script. The script implements the protocol. The protocol
justifies why the script is correct.

---

## Part 1: Test Protocol (Before Execution)

### 1.1 Identification

| Field | Value |
|-------|-------|
| Protocol ID | TP-XXX |
| Title | [Descriptive title] |
| Parent story/task | [US-XXX / TK-XXX] |
| Author | [Role] |
| Reviewer | [Role -- must include QE] |
| Status | Draft / Approved / Superseded |

### 1.2 Test Objective

**What are we testing?** State whether this is:
- A **hypothesis** (e.g., "PipeWire FIFO workaround survives reboot") -- the test
  may produce evidence for or against.
- A **feature validation** (e.g., "DJ mode produces correctly routed 8-channel
  audio") -- the test confirms a specific capability works.
- A **regression check** (e.g., "Reaper stable on new kernel") -- the test confirms
  a fix did not break something else.

**What question does this test answer?** State in one sentence.

### 1.3 System Under Test

Describe the complete, reproducible system state required before the test begins.

| Component | Required state | How achieved |
|-----------|---------------|--------------|
| Git commit | `abc1234` | `scripts/deploy.sh` |
| Kernel | e.g., `6.12.62+rpt-rpi-v8-rt` | `/boot/firmware/config.txt` |
| CamillaDSP config | e.g., `dj-pa.yml`, chunksize 2048 | Deploy script sets `active.yml` symlink |
| PipeWire quantum | e.g., 1024 | Runtime `pw-metadata` or static config |
| PipeWire scheduling | e.g., SCHED_FIFO/88 | F-020 systemd override |
| CamillaDSP scheduling | e.g., SCHED_FIFO/80 | systemd override |
| Application | e.g., Mixxx via `pw-jack` | Launch script |
| Hardware connections | e.g., USBStreamer, ADA8200, UMIK-1 | Physical |
| [Other] | | |

**Deploy procedure:** Reference the exact deploy command. Example:
```
scripts/deploy.sh --mode dj --reboot
```

### 1.4 Controlled Variables

What variables are held constant, and how do we ensure they stay constant?

| Variable | Controlled value | Control mechanism | What happens if it drifts |
|----------|-----------------|-------------------|--------------------------|
| Example: Kernel | `6.12.62+rpt-rpi-v8-rt` | `config.txt` + reboot | Test invalid; abort |
| Example: PipeWire priority | FIFO/88 | F-020 systemd override | STOP gate in Phase 0 |
| Example: CamillaDSP config | `dj-pa.yml` | Websocket API switch | Verify after switch |

### 1.5 Pass/Fail Criteria

For each criterion: what is measured, what threshold constitutes pass/fail, and
why is that threshold valid?

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 1 | [Name] | [How measured] | [Threshold] | [Threshold] | [Why this threshold is meaningful] |

**Justification guidance:**
- Thresholds must be traceable to a requirement (user story AC), a physical
  constraint (hearing threshold, hardware limit), or a prior validated measurement.
- "It should work" is not a justification. "The signal must exceed -40dBFS because
  the ADA8200 noise floor is approximately -90dBFS and a 50dB margin ensures the
  signal is clearly distinguishable from noise" is a justification.

### 1.6 Execution Procedure

Step-by-step procedure. Each step must specify:
- The exact command or action
- The expected output or observable result
- What to do if the expected result is not observed (abort, skip, note and continue)

Reference the test script if one exists:
```
Script: scripts/test/tk039-audio-validation.sh --phase both
```

The script implements the procedure. The procedure in this document explains
the reasoning behind each step that the script cannot capture.

### 1.7 Evidence Capture

What evidence is collected and where is it stored?

| Evidence | Format | Location | Retention |
|----------|--------|----------|-----------|
| Example: Signal levels | JSON (per-channel peak dBFS, 1Hz sample rate) | `/tmp/tk039/dj-levels.json` | Committed to `data/TK-039/` |
| Example: Xrun log | Text (timestamped journal grep) | `/tmp/tk039/dj-xruns.log` | Committed to `data/TK-039/` |

### 1.8 Risks and Mitigations

What could go wrong during test execution, and how do we handle it?

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Example: Kernel lockup | Low (D-022 fix) | Test aborted, Pi needs hard reboot | Watchdog enabled; retry from Phase 0 |

### 1.9 Approval

| Role | Name | Date | Verdict |
|------|------|------|---------|
| QE (author) | | | |
| Audio Engineer (domain) | | | Required for audio tests |
| Architect (if architectural) | | | |
| Owner (if UAT) | | | |

---

## Part 2: Test Execution Record (During/After Execution)

### 2.1 Execution Metadata

| Field | Value |
|-------|-------|
| Protocol ID | TP-XXX (reference to approved protocol) |
| Execution date | [ISO 8601] |
| Operator | [Who ran it] |
| Git commit (deployed) | `abc1234` |
| Git commit (verified on Pi) | [Output of `git rev-parse --short HEAD` on deployed repo, or deploy script output] |

### 2.2 Pre-flight Verification

Record the actual pre-test state. For each item in section 1.3 (System Under Test),
record what was actually observed:

| Component | Expected | Observed | Pass/Fail |
|-----------|----------|----------|-----------|
| Kernel | `6.12.62+rpt-rpi-v8-rt` | [actual output of `uname -r`] | |
| PipeWire scheduling | SCHED_FIFO/88 | [actual output of `chrt -p`] | |

### 2.3 Execution Log

Timestamped record of what happened. Include full command output, not summaries.
If a test script was used, attach or inline the complete stdout/stderr.

```
[2026-03-10T14:30:00+01:00] Started tk039-audio-validation.sh --phase both
[2026-03-10T14:30:02+01:00] Phase 0: Preflight...
[complete output follows]
```

### 2.4 Results

For each criterion in section 1.5:

| # | Criterion | Result | Evidence | Justification |
|---|-----------|--------|----------|---------------|
| 1 | [Name] | PASS/FAIL | [File reference] | [Why the evidence supports this judgement] |

**Judgement guidance:**
- A PASS requires positive evidence, not absence of failure.
  "No errors" is not evidence of correctness. "Channel 0 peak was -12.3dBFS,
  which exceeds the -40dBFS threshold, confirming signal is present and at a
  level consistent with music playback" is evidence.
- A FAIL must state what was expected, what was observed, and the gap.

### 2.5 Deviations

Any deviation from the approved protocol. Why it occurred, what was done instead,
and whether it affects the validity of results.

### 2.6 Findings

New defects, observations, or follow-up items discovered during test execution.

| ID | Severity | Description | Action |
|----|----------|-------------|--------|
| | | | |

### 2.7 Outcome

**Overall:** PASS / FAIL / PARTIAL

**QE sign-off:**

| Role | Name | Date | Verdict | Notes |
|------|------|------|---------|-------|
| QE | | | | |

---

## Notes

- A test protocol must be approved BEFORE execution begins. Retroactive protocols
  for tests already run are documentation, not validation.
- The test script is an implementation artifact. The protocol document is the
  authoritative definition of what constitutes a valid test. If the script and
  protocol disagree, the protocol is correct and the script must be fixed.
- Raw test output must be preserved. Summaries are useful for communication but
  are not evidence. Evidence is the actual numbers, logs, and timestamps.
- The QE must approve both the protocol (before) and the results (after). DoD
  for any story with test criteria is not reached until QE signs off.
