# Coding Principles — mugge

## Topic: Temporal and spatial memory safety — core architectural principle (2026-03-26)

**Context:** F-116 follow-up escalated by owner to a broader architectural
principle covering all safety-relevant invariant checks, not just bounds checks.
**Learning:** The "bounds checks are expensive" argument is doubly wrong:
1. **Hardware:** On modern superscalar CPUs (including Pi 4 Cortex-A72),
   branch prediction handles the happy path with zero effective penalty.
   Runtime performance is dominated by RAM latency, not branch instructions.
2. **Compiler:** Modern compilers (LLVM/rustc) routinely optimize bounds
   checks via loop-invariant code motion (LICM) and strength reduction. A
   bounds check inside a loop is often hoisted to a single check before loop
   entry, or eliminated entirely when the compiler proves the invariant via
   induction variable analysis. The per-iteration cost drops to zero.

There is no performance justification for `debug_assert` over `assert!` in
this project. Optimizing out safety checks without rigorous formal proof is
always the wrong decision.
**Rule — applies to ALL Rust code, especially audio-common and RT services:**
- All bounds checks: `assert!`, never `debug_assert`
- Channel count validation: `assert_eq!`, never `debug_assert_eq!`
- Any safety-relevant invariant check must be runtime, not debug-only
- No exceptions without rigorous formal proof (which we don't do)
**Applied examples:**
- F-116: RingBuffer capacity bounds check upgraded (`50db4df`)
- Architect finding: 2 additional `debug_assert_eq!` in `level_tracker.rs:177`
  and `ring_buffer.rs:117` being upgraded to runtime asserts
**Source:** Owner directive (2026-03-26), broadened from initial F-116 fix.
**Tags:** rust, memory-safety, bounds-check, channel-count, debug-assert, assert,
assert-eq, rt-safety, performance, cortex-a72, architectural-principle
