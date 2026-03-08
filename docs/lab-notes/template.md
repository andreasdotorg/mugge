# Lab Note Template

Use this template for each task entry in a lab notes file. Copy the section
below and fill it in as you work. Record commands and output contemporaneously
-- do not reconstruct from memory after the fact.

---

## Task [TASK-ID]: [Short description]

**Date:** YYYY-MM-DD HH:MM (timezone)
**Operator:** [who ran this]
**Host:** [hostname, OS version, kernel]

### Pre-conditions

- Disk space: `df -h /` output
- Relevant package versions already installed (if any)

### Procedure

Record each command exactly as run. Include the full command and relevant
output (or excerpts for verbose output -- note what was trimmed).

```bash
# Step 1: [what this does]
$ command-here
<output>
```

```bash
# Step 2: ...
$ command-here
<output>
```

### Versions Installed

| Package / Binary | Version | How verified |
|------------------|---------|--------------|
| example | 1.2.3 | `example --version` |

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| [describe check] | [expected result] | [actual result] | PASS / FAIL |

### Post-conditions

- Disk space: `df -h /` output
- Disk delta: [+/- amount]

### Deviations from Plan

None / [describe what differed from the planned procedure and why]

### Notes

[Observations, warnings, anything worth recording for future reference]
