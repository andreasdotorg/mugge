# Testing and Code Quality Process (L-042)

**Status:** Approved — Architect confirmed, AD challenge resolved (11 findings)
**Author:** Quality Engineer
**Trigger:** L-042 — workers dismissed test failures without proper review;
no gate requiring tests to pass before task completion. Extended with owner
code quality directives (2026-03-22).

This document defines the testing and code quality governance process. It
complements:
- `test-strategy.md` — what to test and how (tiers, scenarios, tooling)
- `test-protocol-template.md` — how to write and execute formal test protocols
- `docs/guide/howto/development.md` — how to run tests (commands, Nix)

This document answers: **who decides when tests pass, fail, or get dismissed,
what code quality standards apply, and what happens at each gate.**

**Owner directives (binding):**
1. Tests are mandatory in every story's Definition of Done
2. Test and code quality review is part of the Rule 13 stakeholder approval matrix
3. No mock theater — tests must validate real behavior, not verify that
   mocks return what they were told to return
4. Code quality standards are mandatory — not aspirational, not optional

---

## 1. Test Failure Classification

Every test failure falls into exactly one category. Classification determines
the required response.

| Category | Definition | Example | Required response |
|----------|-----------|---------|-------------------|
| **Code bug** | The production code is wrong | Gain slider sends wrong parameter format | Fix the code. Test stays as-is. |
| **Test bug** | The test assertion is wrong or fragile | Test checks pixel position that varies with font rendering | Fix the test. File defect against test infrastructure. |
| **Environment gap** | Test assumes something unavailable in this environment | Test needs PipeWire daemon but runs in Nix sandbox | Mark `xfail` with defect reference. Document environment requirement. |
| **Flaky** | Test passes sometimes, fails sometimes, with no code change | Canvas screenshot differs due to animation timing | Special handling (see Section 2). |

### 1.1 Classification Authority

**Who can classify what:**

| Category | Who decides | Rationale |
|----------|-----------|-----------|
| **Code bug** | Worker (self-classify freely) | Worker knows if their code is wrong. Fix it and move on. |
| **Test bug** | QE + Architect agreement | Modifying a test is a coverage decision — requires review. |
| **Environment gap** | Architect (sole authority) | Only the Architect has full knowledge of environment capabilities. |
| **Flaky** | QE + Architect agreement | Non-determinism classification requires technical + quality perspective. |

The worker who encountered the failure **proposes** a classification but
**cannot unilaterally decide** anything except "code bug." For test bugs,
environment gaps, and flaky tests, the worker reports to QE and waits for
classification. This is the core L-042 fix.

**No test may be skipped, xfailed, or have its assertion weakened without
QE + Architect sign-off.** This is the hard gate that prevents L-042
recurrence.

**Rationale (AD finding):** Requiring all four roles (QE + AD + Architect +
SME) for every triage creates bottlenecks. QE + Architect is sufficient for
accountability while remaining practical. The AD is available for escalation
(see Section 9.1) but is not required for routine triage. For domain-specific
tests, the relevant SME may substitute for the Architect (QE + Audio Engineer
for audio tests, QE + Security Specialist for security tests).

### 1.2 Classification Evidence

The worker must provide to the QE:
1. The exact test command that was run (copy-paste, not paraphrased)
2. **Raw test output** — the complete stdout/stderr from the test run.
   Summaries, paraphrases, or excerpts are NOT acceptable. The QE needs
   the full traceback, assertion message, and any preceding context to
   classify accurately. Workers who provide summaries will be asked for
   the raw output before classification proceeds.
3. The worker's proposed classification and reasoning
4. What the worker believes the fix should be

"It failed" or "tests are broken" without evidence is not acceptable.
**"3 tests failed, here's what I think happened" without raw output is
also not acceptable.** The evidence must be the actual test runner output,
not the worker's interpretation of it.

---

## 2. Flaky Test Handling

Flaky tests are corrosive — they train workers to ignore failures. F-049
is the cautionary example: 9 measurement wizard tests were xfail'd due to
mock state isolation issues, and they remained broken across multiple
sessions because there was no re-evaluation mechanism. Special rules apply:

1. **First occurrence:** Worker reports to QE with full raw output. QE opens
   a defect (F-XXX) with `flaky` label.
2. **Investigation:** Worker or QE must identify the non-determinism source
   (timing, animation, race condition, external state).
3. **Remediation options** (in order of preference):
   a. Fix the test to be deterministic (e.g., freeze animation, mock time)
   b. Add a retry with `flaky` marker and defect reference
   c. Mark `xfail(strict=False)` with defect reference — last resort
4. **No silent `@pytest.mark.skip`** — skip without a tracked defect is a
   protocol violation.
5. **Re-evaluation intervals:** Every xfail'd flaky test must be
   re-evaluated on a fixed schedule:
   - **2-session TTL (default):** If not fixed within 2 sessions, QE
     escalates to Architect for a structural fix.
   - **5-session hard limit:** If still not fixed after 5 sessions, the
     test must be either fixed or formally redesigned. An xfail that
     persists beyond 5 sessions requires owner approval to continue.
   - **Session start audit:** At the start of each session, the QE
     reviews all active xfail markers and reports their age and status.
6. **xfail accumulation limit:** If more than 5 tests across all suites
   are xfail'd simultaneously, this is a systemic problem. The QE must
   escalate to the Architect and team lead for a dedicated fix sprint.
   The F-049 pattern (9 xfails accumulating unchecked) must not recur.

---

## 3. No Mock Theater (Owner Directive)

**Tests must test real behavior.** A test that cannot catch a real regression
is not a test — it is theater. This section defines what constitutes a
meaningful test and what does not.

### 3.1 What Mocks Are For

Mocks replace **external system boundaries** — things that are unavailable or
unsafe in the test environment:

| Legitimate mock target | Why |
|----------------------|-----|
| PipeWire daemon (pw-cli, pw-dump) | Not available in Nix sandbox |
| Audio hardware (USBStreamer, UMIK-1) | Not available in test environment |
| Network services (GraphManager RPC) | May not be running |
| OS services (systemd, /proc, /sys) | Not available in sandbox |
| Filesystem paths on Pi (/etc/pi4audio/) | Not present on dev machine |

### 3.2 What Mocks Are NOT For

Mocks must **never** replace internal application logic. The following are
prohibited:

- **Mocking the function under test.** If you mock `calculate_gain()` and
  then assert it returned what the mock was told to return, you have tested
  nothing.
- **Mocking internal modules to avoid testing them.** If module A calls
  module B, the test for A should exercise the real module B (unless B
  crosses a system boundary).
- **Asserting only that a mock was called.** `mock.assert_called_once()`
  verifies wiring, not correctness. It must be combined with assertions on
  the actual output or side effects.
- **Pre-loading expected results into mocks.** If the mock returns the
  exact data the test expects, and no real code transforms that data, the
  test is a tautology.

### 3.3 The Regression Test

Every test must pass this question: **"If I introduce a bug in the
implementation, will this test catch it?"**

If the answer is no — if the test would still pass with broken production
code — the test is meaningless and must be rewritten or deleted.

**Assert on values, not just structure.** When the implementation produces
specific values, tests must assert on those values. A test that checks only
key presence (`"quantum" in response`) when the code computes a specific
value (`1024`) is an incomplete test — it would pass even if the value were
`null` or wrong. This gives the QE a concrete criterion beyond the
regression question.

Examples:

| Test | Catches regression? | Verdict |
|------|-------------------|---------|
| Mock returns `{"quantum": 1024}`, assert frontend displays "1024" | YES — if frontend parsing breaks, test fails | Valid |
| Mock returns `{"quantum": 1024}`, assert mock was called | NO — implementation could return garbage and test passes | Invalid: mock theater |
| Call real `find_gain_node()` with real pw-dump JSON fixture, assert correct node ID extracted | YES — if parser breaks, test fails | Valid |
| Mock `find_gain_node()` to return `(42, 0.001)`, assert `set_gain()` passes `42` to `pw-cli` | PARTIAL — tests wiring but not parsing. Acceptable if parser has its own test. | Valid (with caveat) |
| Mock `pw_dump()` to return fixture JSON, call real `get_config()` endpoint, assert response shape | YES — exercises real parsing, routing, serialization | Valid |

### 3.4 Integration Test Requirements

Integration tests must exercise **real code paths**:

- The actual FastAPI route handler runs (not a mock of it)
- The actual data transformation/parsing code runs
- The actual error handling code runs
- Only system boundaries are mocked (database, hardware, OS)

A test that mocks every dependency of the function under test is a unit test
of the mocking framework, not a test of the application.

### 3.5 QE Review for Test Quality

The QE must review tests for mock theater during the Rule 13 approval
process (see Section 6). Tests that fail the regression test (Section 3.3)
are rejected — they do not count toward test coverage and must be rewritten.

**Companion test verification (AD finding):** When a test mocks an internal
function (e.g., the "wiring-only" pattern in 3.3 row 4), the QE must
explicitly verify that the mocked function has its own direct test
elsewhere. Document the companion test reference in the review. A wiring
test without its companion parser/logic test is incomplete coverage.

**Passthrough test judgment:** A test that asserts data passes through a
route handler unchanged (mock returns X, assert endpoint returns X) has
limited value — it catches routing regressions but tests no transformation
logic. Such tests are valid but should NOT be counted as full coverage for
the code path. The DoD acceptance criteria should require tests that
exercise actual transformation or business logic, not just routing.

### 3.6 Enforcement

**Writing mock theater is a protocol violation** equivalent to dismissing
a test failure. It creates a false sense of safety that is worse than having
no test at all. When the QE identifies mock theater:

1. The test is flagged and the worker must rewrite it
2. The task stays `in_progress` until the test is meaningful
3. Repeated violations are escalated to the team lead

### 3.7 Mock-Production Divergence (AD Finding)

**The most dangerous form of mock theater is invisible:** mock data that
looks realistic but does not match actual production output format. This
project has concrete evidence:

- **F-056:** Mock used `clock.quantum` key; real PipeWire uses
  `clock.force-quantum` for forced quantum values
- **F-057:** Mock gain node JSON path differs from actual PW builtin node
  structure exposed by `pw-dump`

Tests passed against the mock. They failed on the Pi. The mock diverged
from production reality without anyone noticing.

**Process mitigation:**
- When a worker modifies a collector or any code that parses external tool
  output (pw-dump, pw-cli, pw-metadata, /proc, systemd), they must provide
  a **real Pi data sample** alongside any mock update. The QE verifies the
  mock matches the sample at Gate 3.
- The Gate 3 checklist (Section 8) includes: "Verify mock data format
  matches observed Pi output for changed code paths."

**Technical mitigation (future):** Generate mock fixtures FROM real Pi output
(snapshot testing). Capture real `pw-dump`, `pw-cli info`, etc. output as
test fixtures, eliminating manual mock drift. Tracked as a future
improvement, not a current requirement.

---

## 4. Code Quality Standards (Owner Directive)

**Code quality is mandatory, not aspirational.** These standards apply to all
code written by workers. They are enforced at Rule 13 review by the Architect.
Standards are derived from existing codebase conventions, not imposed
abstractly.

### 4.1 Structure and Modularity

**File size guidelines** (not hard limits — Architect applies judgment):
- Python: ~300 lines typical. Over 500 lines warrants a review conversation.
- Rust: ~600-800 lines typical. Over 1200 lines needs clear internal sections
  with doc comment headers.
- JavaScript: ~500 lines typical. Over 800 lines acceptable if one cohesive
  feature.

**Function size:** Functions over ~50 lines deserve a second look. The test:
"can a reader understand this in one pass?" Deeply nested code (>3 indent
levels in logic, not counting match arms) should be extracted.

**DRY threshold:** Three instances of the same pattern triggers extraction,
not two. Two may be coincidental; three confirms a pattern. Exception:
configuration files (systemd units, PW configs) favor explicitness over DRY.

**Aggressive refactoring.** Refactor proactively. Do not let tech debt
accumulate. Protect refactorings with test scaffolding — write tests first,
then refactor. A refactoring without tests is a regression waiting to happen.

**Module boundaries** — follow existing conventions:
- **Rust:** Pure-logic modules (no PipeWire imports, compile with
  `--no-default-features`) are separated from I/O modules. This is
  load-bearing — it enables testing without a PW daemon.
- **Python:** Collectors in `app/collectors/`. Routes separate from business
  logic. Mock implementations mirror real counterparts.
- **JavaScript:** One file per tab/view. Shared code in `app.js`.

**Antipatterns:** God objects, circular imports/dependencies, dump-everything
utility files, abstractions that add indirection without clarity.

### 4.2 Correctness and Robustness

**Edge cases to verify during review:**
- Boundary values: empty collections, zero-length inputs, single-element
- Error paths: subprocess failures, node disappearance mid-operation,
  WebSocket disconnect during measurement
- State machine transitions: invalid transitions tested, not just happy path
- Concurrency edges: what if two operations arrive in the same cycle?

**Review question:** "What's the worst thing that happens if this input is
unexpected?" For safety-critical code (watchdog, gain integrity), the answer
must be "it fails safe" (mutes, not amplifies).

**Timing and race conditions — known sensitive areas:**
- Watchdog mute: <21ms, must use native PW API, no blocking I/O
- RPC command processing: 50ms poll, multiple commands can queue
- WebSocket broadcast: client disconnect during send must not crash loop
- Measurement session: state transitions must be lock-protected
- PipeWire registry: nodes can appear before their ports

**Timing antipatterns:** `time.sleep()` in production code (never in server
code), bare `subprocess.run()` on safety path, missing `try/except` around
WebSocket sends, state transitions without lock protection, TOCTOU bugs.

### 4.3 Observability

**Python logging:**
- `log = logging.getLogger(__name__)` at module level
- Use `%s` formatting: `log.info("Starting %s on port %d", name, port)` —
  defers string formatting until message is emitted
- No bare `print()` in production code (acceptable in CLI scripts and tests)

**Rust logging:**
- Use `log` crate macros (`log::info!`, `log::warn!`, etc.)
- Safety events: `log::error!` with prefix (`"WATCHDOG: ..."`,
  `"GAIN INTEGRITY: ..."`) for grep-based monitoring

**Log levels (both languages):**

| Level | When to use | Example |
|-------|------------|---------|
| ERROR | Safety events, unrecoverable failures | `WATCHDOG: Safety mute LATCHED` |
| WARN | Recoverable degradation | `Link create failed (will retry)` |
| INFO | State transitions, lifecycle events | `Mode transition: dj -> live` |
| DEBUG | Per-cycle details, routine polling | `Gain integrity check passed` |

**Structured data:** Include machine-parseable identifiers. Good:
`"CREATE: link from Mixxx:out_0 -> pi4audio-convolver:in_AUX0"`. Bad:
`"Created a link"`. No sensitive data in logs.

### 4.4 File Layout

Follow established conventions:

| Path | Convention | Deployment target |
|------|-----------|-------------------|
| `src/<component>/` | Source code by component | Not deployed directly |
| `configs/pipewire/` | PipeWire config fragments | `~/.config/pipewire/pipewire.conf.d/` |
| `configs/wireplumber/` | WP configs and scripts | `~/.config/wireplumber/` |
| `configs/systemd/user/` | User-level systemd units | `~/.config/systemd/user/` |
| `configs/udev/` | udev rules | `/etc/udev/rules.d/` |
| `scripts/deploy/` | Deploy script | Not deployed (runs from dev) |

Config files carry comments documenting their deployment path (lines 1-3).
No hardcoded absolute paths in source code except config files. Test data
and fixtures live alongside tests. WAV coefficients are NOT in the repo.

### 4.5 Safety Antipatterns (CRITICAL — Auto-Reject)

Any of the following in a code change is an automatic rejection:

1. **Gain boost:** Any code path that could set Mult > 1.0 or generate a
   filter with gain > -0.5 dB (D-009 violation).
2. **Unattenuated audio path:** Any link topology bypassing gain nodes or
   convolver to reach USBStreamer output.
3. **Watchdog bypass:** Any change preventing the watchdog from firing
   (swallowing events, delaying mute, auto-unlatching).
4. **Subprocess on safety path:** Mute mechanism must use native PW API.
   Subprocess latency (~50ms) exceeds 21ms safety budget.

### 4.6 Security Antipatterns (Flag for Security Specialist)

5. **Non-loopback binding:** RPC servers (GM 4002, signal-gen 4001) must
   bind 127.0.0.1 only.
6. **Unsanitized subprocess input:** Never `shell=True` with user input.
   Use array-form arguments.
7. **Credentials in source:** No SSH keys, passwords, or tokens in repo.
8. **Unbounded reads:** RPC reads capped at 4096 bytes. WebSocket messages
   need size limits.

### 4.7 Architectural Antipatterns (Flag, Discuss)

9. **Mixing pure logic with I/O:** Preserve Rust pure/I/O module separation.
10. **Feature flag proliferation:** Prefer runtime detection over compile-time
    flags. One Rust feature flag (`pipewire-backend`) is correct.
11. **Config duplication:** Production and test configs should share structure.
12. **Scattered node names:** Use constants (`MONITORED_NODES`,
    `USBSTREAMER_OUT_PREFIX`), not string literals across modules.

### 4.8 Enforcement

The **Architect** reviews code quality during Rule 13 approval (see Section 6).

**Architect Rule 13 review checklist:**

- [ ] No Mult > 1.0 in any code path
- [ ] No D-009 violation (filter gain <= -0.5 dB)
- [ ] No subprocess on safety-critical path
- [ ] All RPC/network listeners loopback-only
- [ ] No `shell=True` with interpolated strings
- [ ] Logging uses correct level and includes context
- [ ] State machine transitions are lock-protected
- [ ] Pure-logic modules have no I/O imports
- [ ] Tests cover failure/empty/edge cases
- [ ] File sizes within convention (justify exceptions)
- [ ] No hardcoded node names outside constants module

Workers who receive code quality feedback must address it before the task
can be marked complete. Code quality review is not optional and cannot be
deferred to a follow-up story.

---

## 5. Definition of Done (Owner Directives)

Every story's Definition of Done must include:

> **Relevant tests exist, pass, and have been reviewed by QE.**
> **Code meets quality standards and has been reviewed by Architect.**

### 5.1 Test Requirements in DoD

1. **Tests exist.** New functionality requires new tests. Bug fixes require
   a regression test that would have caught the bug. "No tests needed" is
   only valid for pure documentation changes — and even then, if the
   documentation describes behavior, the behavior must have tests.

2. **Tests pass.** All relevant test suites pass at Gate 1 (worker) and
   Gate 2 (CM commit). No story can be marked complete with failing tests.

3. **Tests have been reviewed.** The QE has reviewed the tests themselves —
   not just the test results — and confirmed they are adequate. Adequate
   means: they test real behavior (not mock theater), they cover the
   acceptance criteria, and they can catch regressions.

A story without tests is not done. A story with inadequate tests is not done.
The QE decides what is adequate.

### 5.2 Code Quality Requirements in DoD

1. **Code meets quality standards.** All code changes must comply with the
   standards in Section 4: well-structured, DRY, edge cases handled,
   concurrency addressed, logging structured, no antipatterns.

2. **Code has been reviewed.** The Architect has reviewed the code for
   quality and confirmed it meets the standards. The Architect's review
   checklist is in Section 4.8.

3. **Quality feedback addressed.** If the Architect or QE provides feedback,
   the worker must address it before the task can be marked complete.
   Code quality and test quality feedback cannot be deferred to follow-up
   stories.

A story with substandard code is not done, even if the tests pass.

---

## 6. Test and Code Quality Review in Rule 13 Approval Matrix (Owner Directive)

The Rule 13 stakeholder approval matrix (orchestration protocol) must include
both test review and code quality review as required approvals.

**Addition to the approval matrix:**

| Change domain | Required approval from |
|---------------|-----------------------|
| **All code changes** | **Quality Engineer (test adequacy)** |
| **All code changes** | **Architect (code quality)** |
| Security-sensitive changes | Security Specialist |
| Operational changes | Domain Specialist (if present) |
| Documentation / tracking changes | Project Manager |
| Multi-domain changes | All relevant approvals above |

**QE approval criteria for Rule 13:**

The QE approves if and only if:
1. Tests were run and all pass (evidence provided)
2. New/modified code has corresponding tests
3. Tests are meaningful (not mock theater — see Section 3)
4. Tests cover the story's acceptance criteria
5. Any xfail/skip markers are properly triaged with tracked defects

**Architect approval criteria for Rule 13:**

The Architect uses the review checklist in Section 4.8 (11 items covering
safety, security, logging, structure, testing, and conventions). Key
auto-reject criteria:
- Any Mult > 1.0 or D-009 violation (safety)
- Subprocess on safety-critical path (safety)
- Non-loopback network binding or unsanitized subprocess input (security)
- Pure-logic modules with I/O imports (architectural)

The CM must not commit without BOTH QE approval on test adequacy AND Architect
approval on code quality. These are in addition to (not a replacement for)
existing domain approvals (Security, etc.).

---

## 7. Definition of "Green" Suite

A test suite is **green** if and only if:

1. **Exit code 0** — pytest returns success
2. **Zero failures** — no test has status FAILED or ERROR
3. **All xfails are tracked** — every `xfail` marker references a defect
   ID (e.g., `@pytest.mark.xfail(reason="F-049: mock state isolation")`)
   and has QE approval
4. **xfail count within limit** — no more than 5 xfail'd tests across
   all suites (see Section 2, item 6)
5. **No skips without defects** — every `skip` marker references a tracked
   defect and has QE approval

An xfail'd test that unexpectedly passes (xpass) is treated as a signal:
the underlying issue may be fixed. The QE should investigate and potentially
remove the xfail marker.

**What "green" does NOT mean:**
- It does NOT mean "no xfails." Properly tracked xfails are acceptable.
- It does NOT mean "all code is correct." Green means the known test
  surface passes. Untested code paths may still have bugs.

---

## 8. Deployment Gates

Four tiers. Each must pass before proceeding to the next.

### Gate 1: Worker Task Completion (`nix run .#test-*`)

**When:** Worker reports a task as done.
**Who runs:** The worker.
**What runs:** The **relevant `nix run .#test-*` suite(s)** based on what
files changed (impure, runs against working tree).

**Required suites by change category:**

| Change category | Required `nix run` suites |
|----------------|--------------------------|
| Web UI backend (`src/web-ui/app/`) | `test-unit` |
| Web UI frontend (`src/web-ui/static/`) | `test-unit` + `test-e2e` |
| Web UI backend + frontend | `test-unit` + `test-e2e` |
| Room correction (`src/room-correction/`) | `test-room-correction` |
| GraphManager Rust (`src/graph-manager/`) | `cargo test --no-default-features` in `nix develop` |
| MIDI daemon (`src/midi/`) | `test-all` (includes midi suite) |
| Driver YAMLs (`configs/drivers/`) | `test-drivers` |
| PipeWire/WP configs (`configs/pipewire/`, `configs/wireplumber/`) | No local test — mark "requires Pi validation" |
| systemd units (`configs/systemd/`) | No local test — mark "requires Pi validation" |
| udev rules (`configs/udev/`) | No local test — mark "requires Pi validation" |
| Deploy script (`scripts/deploy/`) | Dry-run locally (`--dry-run`), full validation on Pi |
| Multiple categories | All relevant suites from above |

**Key rule:** Changes that touch BOTH frontend and backend require BOTH
`test-unit` AND `test-e2e`. A common mistake is running only unit tests
when a JS change breaks an E2E assertion.

**Why E2E is a Gate 1 obligation:** E2E tests require Playwright/Chromium
and a running server, which the pure Nix sandbox (`nix flake check`) cannot
provide. **E2E tests are NOT in `nix flake check`.** This means Gate 2
cannot verify E2E — the worker is the trust boundary for E2E pass evidence.
Workers MUST include E2E test output in their task completion report when
frontend changes are involved.

**Rules:**
- Worker MUST run the relevant suite(s) before reporting done
- ALL tests in the relevant suites must pass (exit code 0)
- If any test fails, the task stays `in_progress` until resolved
- Worker reports the raw test output to QE
- Pre-existing failures (tests that were already failing before the worker's
  changes) must still be reported — the worker does not get to assume they
  are someone else's problem
- For changes requiring Pi validation, the worker must note this in the
  task completion report so it is tracked for Gate 3

### Gate 2: Change Manager Commit (`nix flake check`)

**When:** Worker requests commit via Change Manager.
**Who runs:** Change Manager (or worker at CM's request).
**What runs:** `nix flake check` (pure Nix sandbox — the reproducibility gate).

**What `nix flake check` runs** (all must pass):
- `test-web-ui` — Python unit/integration tests (excludes E2E)
- `test-room-correction` — Room correction module tests
- `test-midi` — MIDI daemon tests
- `test-drivers` — Driver YAML validation
- `test-graph-manager` — GM pure-logic Rust tests (`--no-default-features`)
- `test-graph-manager-full` — GM full build with PipeWire linkage (Linux)
- `test-pcm-bridge` — pcm-bridge Rust tests (Linux, via `buildRustPackage`)
- `test-signal-gen` — signal-gen Rust tests (Linux, via `buildRustPackage`)

**What `nix flake check` does NOT run:**
- E2E tests (require Playwright/Chromium + running server — not available
  in pure sandbox). E2E coverage is a Gate 1 worker obligation.

**Rules:**
- `nix flake check` must pass before the commit is created
- If it fails, CM returns the task to the worker with the failure output
- The worker fixes the issue and re-requests commit
- CM does NOT commit code with known test failures unless the QE has
  explicitly approved an `xfail` with a tracked defect

### Gate 3: Pi Deployment Validation

**When:** Code is deployed to the Pi via a DEPLOY session.
**Who runs:** Worker holding the DEPLOY session (executes tests on Pi).
**Who owns:** The **QE owns Gate 3** — the QE defines what must be validated,
reviews the evidence, and signs off. The worker executes; the QE decides.
**What runs:** Hardware-specific validation per the test plan for the story.

**Rules:**
- QE writes the hardware validation criteria for each story BEFORE
  deployment begins. The worker must know what to test before they SSH in.
- Worker executes the validation on the Pi and reports results with raw
  evidence (command output, log excerpts, measurements)
- QE reviews evidence and signs off
- Deployment is not complete until QE signs off
- If the QE has not written validation criteria for a story, the worker
  must request them before proceeding with deployment
- The Change Manager enforces Gate 3: no DEPLOY session is closed without
  QE sign-off on hardware validation results
- **Mock divergence check (AD finding):** For changes that modify collectors
  or code parsing external tool output (pw-dump, pw-cli, pw-metadata, /proc),
  the worker must capture real Pi output and the QE must verify mock data
  format matches. F-056 and F-057 are evidence that mock-production divergence
  causes real defects (see Section 3.7).

---

## 9. Test Failure Triage Process

```
Test fails
    |
    v
Worker captures full output + proposes classification
    |
    v
Worker reports to QE with evidence (Section 1.2)
    |
    v
QE reviews evidence
    |
    +---> Code bug ---------> Worker fixes code, re-runs tests
    |                          (task stays in_progress)
    |
    +---> Test bug ---------> Worker fixes test, files defect,
    |                          re-runs tests (task stays in_progress)
    |
    +---> Environment gap ---> QE + Architect agree on classification
    |                          Worker marks xfail with defect ref
    |                          QE approves the xfail
    |                          Worker re-runs tests (xfail'd test expected)
    |
    +---> Flaky ------------> Follow Section 2 (flaky handling)
    |
    +---> Disagreement -----> Escalate to AD for challenge
                               AD + QE + Architect resolve
                               Owner breaks ties if needed
```

### 9.1 Escalation Path

1. Worker -> QE (all test failures)
2. QE -> Architect (classification disagreement or technical uncertainty)
3. QE -> AD (process challenge — is the test valid? is the gate appropriate?)
4. QE -> Owner (unresolvable disagreement, safety-critical test failure)

### 9.2 What Constitutes "Dismissal"

Any of the following without a tracked defect AND QE approval is a **protocol
violation**:

- Adding `@pytest.mark.skip` or `@pytest.mark.xfail`
- **Deleting a test or test file** — this is the most dangerous form of
  dismissal because it makes the suite "green" by removing coverage. A
  deleted test is treated identically to a dismissed failure. The worker
  must justify why the test is no longer needed, and the QE must agree
  that the deleted test's coverage is either obsolete or replaced by
  another test.
- Commenting out a test or assertion
- Changing an assertion to match wrong behavior ("make the test pass")
- Reporting a task as done with known failing tests
- Reducing assertion strictness without justification
- Writing mock theater (tests that verify mocks, not behavior)

Protocol violations are reported to the team lead and logged in
lessons-learned.

---

## 10. Test Environment Expectations

Tests must be designed to work within their environment's capabilities.
Workers and test authors must understand what each environment provides.

### 10.1 Environment Capabilities Matrix

| Capability | `nix flake check` (pure) | `nix run .#test-*` (impure) | `nix develop` (interactive) | Pi hardware |
|-----------|-------------------------|---------------------------|---------------------------|-------------|
| Python 3.13 + all deps | YES | YES | YES | YES |
| Rust toolchain (cargo, rustc) | YES | YES | YES | YES |
| PipeWire dev headers (libpipewire) | YES (Linux) | YES (Linux) | YES (Linux) | YES |
| PipeWire daemon (runtime) | NO | NO | YES | YES |
| Playwright / Chromium | NO | YES | YES | NO |
| Chromium fonts | NO | NO | NO | N/A |
| Real ALSA devices | NO | NO | NO | YES |
| Network (Pi SSH) | NO | NO | YES | N/A |
| Systemd user services | NO | NO | NO | YES |

### 10.2 Nix Pure Sandbox (`nix flake check`)

**Available:** Python 3.13, all pip dependencies, Rust toolchain,
PipeWire dev headers (Linux), filesystem (read/write within sandbox).

**NOT available:** PipeWire daemon, pw-cli/pw-dump/pw-metadata, audio
hardware, Playwright/Chromium, network access, host fonts, GPU, display
server.

**Implications for test design:**
- All PipeWire interactions must be mocked (PI_AUDIO_MOCK=1)
- **E2E tests cannot run here** — no Playwright/Chromium in pure sandbox.
  E2E is a Gate 1 (worker) obligation only.
- No tests may depend on network connectivity
- GM pure-logic tests use `--no-default-features` (no PipeWire backend)

### 10.3 Nix Impure (`nix run .#test-*`)

**Available:** Everything in pure sandbox PLUS Playwright/Chromium,
host environment (fonts if installed, PipeWire if running, network).

**Implications:**
- E2E tests run here (with Playwright) — this is the ONLY non-Pi
  environment where E2E works
- Tests may pass here but fail in pure sandbox due to host-specific
  conditions. Gate 2 (`nix flake check`) catches these.
- Chromium in the sandbox renders text with zero-width fonts — E2E
  tests must use `to_be_attached()` not `to_be_visible()` for text
  elements (F-048 zero-font workaround)
- Screenshot tests compare layout/structure, not text rendering

### 10.4 Pi Hardware

**Available:** Full production stack — PipeWire daemon, USB audio devices,
PREEMPT_RT kernel, real-time scheduling, systemd user services.

**Implications:** Only environment where hardware validation tests (Gate 3)
can run. Requires CM DEPLOY session.

### 10.5 GraphManager (Rust)

**Automated gate exists.** Two GM test checks are already in `nix flake check`:

1. **`test-graph-manager`** — Runs `cargo test --no-default-features --release`
   in pure Nix sandbox. Tests all pure-logic modules (graph state, routing
   table, reconciler, lifecycle, watchdog, link audit, gain integrity). No
   PipeWire needed. Runs on all platforms.
2. **`test-graph-manager-full`** — Linux only. Full `buildRustPackage` with
   PipeWire linkage. Runs `cargo test` with default features (includes
   `pipewire-backend`).

**Worker Gate 1:** For Rust changes, workers run
`cargo test --no-default-features` inside `nix develop` and report output
to QE. Gate 2 (`nix flake check`) then runs both checks automatically.

### 10.6 Config-Only Changes

Changes to PipeWire configs (`configs/pipewire/`), WirePlumber configs
(`configs/wireplumber/`), systemd units (`configs/systemd/`), and udev
rules (`configs/udev/`) have **no local test possible**. These must be
marked "requires Pi validation" in the task completion report and validated
at Gate 3.

---

## 11. QE Responsibilities in Testing and Code Quality Process

The QE is a **quality gate**, not a rubber stamp.

### 11.1 Proactive Duties

- Review every worker's test results before signing off on task completion
- **Review the tests themselves** for mock theater (Section 3) and adequacy
- **Verify companion tests** for wiring-only tests that mock internal
  functions (Section 3.5) — the mocked function must have its own test
- Challenge "PASS" claims that lack evidence
- Verify that `xfail` markers reference valid defects
- Track flaky test defects and escalate if TTL expires
- Write test criteria for hardware validation (Gate 3)
- Participate in every test failure triage
- **Rule 13 approval:** Sign off on test adequacy before CM commits (Section 6)
- **Verify E2E evidence** for frontend changes — E2E tests are not in
  `nix flake check`, so the worker's reported E2E output is the only
  evidence. Demand it when frontend files are in the changeset.
- Coordinate with the Architect on code quality review (Architect owns code
  quality; QE owns test quality — both must approve at Rule 13)

### 11.2 Blocking Authority

The QE can **block** task completion if:
- Tests were not run
- Test evidence is insufficient
- A failure was dismissed without proper triage
- An `xfail` was added without QE approval
- Hardware validation was skipped for a story that requires it
- Tests are mock theater (Section 3) — they verify mocks, not behavior
- New code has no corresponding tests (Section 5.1 — tests in DoD)
- Tests do not cover the story's acceptance criteria
- Code quality feedback from the Architect has not been addressed

The QE **cannot** block if:
- All tests pass with evidence
- All `xfail` markers are properly triaged and approved
- The Architect has explicitly overridden on technical grounds (rare)

### 11.3 Reporting

After each story completes testing, the QE compiles a test summary:
- Pass/fail per criterion with evidence references
- List of `xfail` markers with defect references
- List of open defects from this testing cycle
- Recommendation: PASS / FAIL / CONDITIONAL PASS

---

## 12. Lessons Learned Integration

This process was created in response to L-042. Key failure modes it prevents:

| Failure mode | How this process prevents it |
|-------------|------------------------------|
| Worker deletes failing test | Deletion = dismissal, requires defect + QE approval (Sec 9.2) |
| Worker adds skip without tracking | Skip without defect = protocol violation (Sec 9.2) |
| Worker reports "done" with failures | Gate 1 requires relevant suites pass; Gate 2 requires `nix flake check` (Sec 8) |
| Worker changes assertion to match bug | Assertion weakening without justification = protocol violation (Sec 9.2) |
| Worker provides summary instead of raw output | Raw output required, summaries rejected (Sec 1.2) |
| Flaky tests erode trust in suite | Flaky handling with re-evaluation intervals + accumulation limit (Sec 2) |
| xfails accumulate unchecked (F-049 pattern) | 5-test limit + session-start audit + 5-session hard cap (Sec 2) |
| No one reviews test results | QE reviews all results before sign-off (Sec 11) |
| Classification is subjective | QE + 1 quorum required (Sec 1.1) |
| Tests verify mocks, not behavior | No mock theater rule with QE review (Sec 3) |
| Story marked done without tests | Tests mandatory in DoD (Sec 5.1) |
| Tests not reviewed before commit | QE in Rule 13 approval matrix (Sec 6) |
| Test passes impure but fails pure | Gate 2 = `nix flake check` (pure sandbox) catches impure-only passes (Sec 8) |
| E2E not verified at commit time | E2E is Gate 1 obligation; worker must provide evidence (Sec 8) |
| Nobody owns Pi deployment validation | QE owns Gate 3: defines criteria, reviews evidence, signs off (Sec 8) |
| Code quality not reviewed | Architect in Rule 13 approval matrix for all code changes (Sec 6) |
| Tech debt accumulates silently | Aggressive refactoring required, protected by tests (Sec 4.1) |
| Edge cases ignored or deferred | Explicit handling required, Architect reviews (Sec 4.2) |
| Code quality feedback deferred | Must be addressed before task completion (Sec 5.2) |
| Mock data diverges from production (F-056, F-057) | Real Pi data sample required for collector changes; Gate 3 mock divergence check (Sec 3.7, 8) |
| Test asserts structure not values | Value-assertion criterion: assert values when code computes them (Sec 3.3) |
| Wiring test without companion logic test | QE verifies companion test exists during review (Sec 3.5, 11.1) |
