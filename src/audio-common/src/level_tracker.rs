//! Per-channel peak and RMS level tracking for the web UI.
//!
//! The PipeWire process callback calls [`LevelTracker::process`] each quantum
//! with interleaved float32 samples. The tracker accumulates peak (max |sample|)
//! and sum-of-squares per channel. A server thread calls [`LevelTracker::take_snapshot`]
//! at 10 Hz to harvest the accumulated values as dBFS, resetting the accumulators.
//!
//! ## Double-buffer design
//!
//! Two accumulator buffers (A and B) eliminate the race condition that existed
//! in the previous per-field atomic swap design. The PW callback always writes
//! to the "active" buffer (selected by an atomic index). `take_snapshot()`
//! atomically flips the index — redirecting the writer to the other buffer —
//! then reads the now-stale buffer at leisure. One atomic swap replaces N+1
//! individual swaps, guaranteeing a consistent snapshot.
//!
//! ## Graph clock
//!
//! Each process callback stamps the buffer with the PipeWire graph clock
//! (`graph_position` in frames, `graph_nsec` in nanoseconds). The snapshot
//! carries the most recent clock values for downstream consumers.

use std::sync::atomic::{fence, AtomicU32, AtomicU64, AtomicUsize, Ordering};

/// Maximum number of channels supported.
const MAX_CHANNELS: usize = 32;

/// PipeWire graph clock stamp captured in the process callback.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct GraphClock {
    /// Monotonic frame position from `pw_time.ticks`.
    pub position: u64,
    /// Monotonic nanoseconds from `pw_time.now`.
    pub nsec: u64,
}

/// Convert a linear amplitude to dBFS. Returns -120.0 for zero or negative.
pub fn linear_to_dbfs(linear: f32) -> f32 {
    if linear <= 0.0 {
        -120.0
    } else {
        20.0 * linear.log10()
    }
}

/// Atomically store `new` if it is greater than the current value (f32 as u32 bits).
/// Used for peak tracking from the RT callback.
fn atomic_max_f32(atom: &AtomicU32, new: f32) {
    let new_bits = new.to_bits();
    loop {
        let old_bits = atom.load(Ordering::Relaxed);
        let old = f32::from_bits(old_bits);
        if new <= old {
            break;
        }
        match atom.compare_exchange_weak(old_bits, new_bits, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => break,
            Err(_) => continue,
        }
    }
}

/// Atomically add `val` to the current value (f32 as u32 bits).
/// Used for sum-of-squares accumulation from the RT callback.
fn atomic_add_f32(atom: &AtomicU32, val: f32) {
    loop {
        let old_bits = atom.load(Ordering::Relaxed);
        let old = f32::from_bits(old_bits);
        let new = old + val;
        match atom.compare_exchange_weak(
            old_bits,
            new.to_bits(),
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => break,
            Err(_) => continue,
        }
    }
}

/// Per-channel level snapshot in dBFS, with graph clock.
#[derive(Debug, Clone)]
pub struct LevelSnapshot {
    /// Number of active channels in the arrays below.
    pub channels: usize,
    /// Peak level per channel in dBFS (max |sample| since last snapshot).
    pub peak_dbfs: [f32; MAX_CHANNELS],
    /// RMS level per channel in dBFS (root-mean-square since last snapshot).
    pub rms_dbfs: [f32; MAX_CHANNELS],
    /// Most recent PipeWire graph clock from this accumulation window.
    pub graph_clock: GraphClock,
}

impl Default for LevelSnapshot {
    fn default() -> Self {
        Self {
            channels: 0,
            peak_dbfs: [-120.0; MAX_CHANNELS],
            rms_dbfs: [-120.0; MAX_CHANNELS],
            graph_clock: GraphClock::default(),
        }
    }
}

/// One half of the double buffer. Holds per-channel accumulators, a
/// shared frame count, and the most recent graph clock stamp. All
/// fields are atomic for lock-free RT access.
struct AccumulatorBuffer {
    peak: [AtomicU32; MAX_CHANNELS],
    sum_sq: [AtomicU32; MAX_CHANNELS],
    sample_count: AtomicU32,
    graph_position: AtomicU64,
    graph_nsec: AtomicU64,
}

impl AccumulatorBuffer {
    fn new() -> Self {
        Self {
            peak: std::array::from_fn(|_| AtomicU32::new(0)),
            sum_sq: std::array::from_fn(|_| AtomicU32::new(0)),
            sample_count: AtomicU32::new(0),
            graph_position: AtomicU64::new(0),
            graph_nsec: AtomicU64::new(0),
        }
    }

    /// Reset all accumulators to zero. Called by the reader after swapping
    /// the active index, so no writer contention.
    fn reset(&self, channels: usize) {
        self.sample_count.store(0, Ordering::Relaxed);
        self.graph_position.store(0, Ordering::Relaxed);
        self.graph_nsec.store(0, Ordering::Relaxed);
        for ch in 0..channels {
            self.peak[ch].store(0, Ordering::Relaxed);
            self.sum_sq[ch].store(0, Ordering::Relaxed);
        }
    }
}

/// Lock-free per-channel level tracker using double buffering.
///
/// Single writer (PW process callback) accumulates peak and sum-of-squares
/// into the active buffer. Single reader (levels server) flips the active
/// index and reads the stale buffer without contention.
pub struct LevelTracker {
    channels: usize,
    buffers: [AccumulatorBuffer; 2],
    /// Index (0 or 1) of the buffer the writer is currently using.
    active: AtomicUsize,
}

// Safety: LevelTracker uses only atomics for shared state. No raw pointers,
// no interior mutability beyond atomics. Safe to share across threads.
unsafe impl Sync for LevelTracker {}
unsafe impl Send for LevelTracker {}

impl LevelTracker {
    /// Create a new level tracker for the given number of channels.
    pub fn new(channels: usize) -> Self {
        assert!(channels <= MAX_CHANNELS, "channels {} exceeds MAX_CHANNELS {}", channels, MAX_CHANNELS);
        Self {
            channels,
            buffers: [AccumulatorBuffer::new(), AccumulatorBuffer::new()],
            active: AtomicUsize::new(0),
        }
    }

    /// Process interleaved float32 samples from the PW callback.
    ///
    /// This is called from the RT audio thread. It uses only atomic operations
    /// (no allocations, no locks, no syscalls).
    ///
    /// `clock` carries the PipeWire graph clock for this quantum. Pass
    /// `GraphClock::default()` if clock data is unavailable (sentinel 0,0).
    pub fn process(&self, samples: &[f32], channels: usize, clock: GraphClock) {
        assert_eq!(channels, self.channels);
        let n_frames = samples.len() / channels;
        if n_frames == 0 {
            return;
        }

        // Read the active index once per call. If take_snapshot() flips
        // the index mid-quantum, this entire quantum's data lands in the
        // same buffer — no partial contamination.
        let idx = self.active.load(Ordering::Acquire);
        let buf = &self.buffers[idx];

        for frame in 0..n_frames {
            let base = frame * channels;
            for ch in 0..channels {
                let sample = samples[base + ch];
                let abs_sample = sample.abs();

                // Update peak (max |sample|)
                atomic_max_f32(&buf.peak[ch], abs_sample);

                // Accumulate sum of squares for RMS
                atomic_add_f32(&buf.sum_sq[ch], sample * sample);
            }
        }

        let prev = buf.sample_count.load(Ordering::Relaxed);
        let new_count = prev.saturating_add(n_frames as u32);
        buf.sample_count.store(new_count, Ordering::Relaxed);

        // Stamp the most recent clock values. Each quantum overwrites the
        // previous stamp — the snapshot returns the latest.
        buf.graph_position.store(clock.position, Ordering::Relaxed);
        buf.graph_nsec.store(clock.nsec, Ordering::Relaxed);
    }

    /// Harvest the accumulated levels as a dBFS snapshot and reset accumulators.
    ///
    /// Called from the levels server thread at ~10 Hz. Atomically flips the
    /// active buffer index so the writer starts using the other buffer, then
    /// reads the stale buffer without any race.
    pub fn take_snapshot(&self) -> LevelSnapshot {
        // Full fence ensures all prior writes by the RT thread are visible
        // before we flip the index. This prevents the reader from seeing a
        // partially-written buffer on weakly-ordered architectures (ARM).
        fence(Ordering::SeqCst);

        // Flip the active index: writer switches to the other buffer.
        // XOR with 1 toggles between 0 and 1.
        let old_idx = self.active.fetch_xor(1, Ordering::AcqRel);
        let stale = &self.buffers[old_idx];

        // Read the stale buffer. The writer is now using the other buffer,
        // so these reads are uncontested.
        let n = stale.sample_count.load(Ordering::Relaxed);

        let mut snap = LevelSnapshot {
            channels: self.channels,
            ..Default::default()
        };

        for ch in 0..self.channels {
            let peak_linear = f32::from_bits(stale.peak[ch].load(Ordering::Relaxed));
            snap.peak_dbfs[ch] = linear_to_dbfs(peak_linear);

            let sum_sq = f32::from_bits(stale.sum_sq[ch].load(Ordering::Relaxed));

            if n > 0 {
                let rms_linear = (sum_sq / n as f32).sqrt();
                snap.rms_dbfs[ch] = linear_to_dbfs(rms_linear);
            }
        }

        snap.graph_clock = GraphClock {
            position: stale.graph_position.load(Ordering::Relaxed),
            nsec: stale.graph_nsec.load(Ordering::Relaxed),
        };

        // Reset the stale buffer so it's clean for next time.
        stale.reset(self.channels);

        snap
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn clock(pos: u64, nsec: u64) -> GraphClock {
        GraphClock { position: pos, nsec }
    }

    #[test]
    fn dbfs_zero_is_minus_120() {
        assert_eq!(linear_to_dbfs(0.0), -120.0);
    }

    #[test]
    fn dbfs_negative_is_minus_120() {
        assert_eq!(linear_to_dbfs(-0.5), -120.0);
    }

    #[test]
    fn dbfs_unity_is_zero() {
        let db = linear_to_dbfs(1.0);
        assert!((db - 0.0).abs() < 0.001, "expected ~0.0 dBFS, got {}", db);
    }

    #[test]
    fn dbfs_half_is_minus_6() {
        let db = linear_to_dbfs(0.5);
        assert!((db - (-6.0206)).abs() < 0.01, "expected ~-6.02 dBFS, got {}", db);
    }

    #[test]
    fn dbfs_tenth_is_minus_20() {
        let db = linear_to_dbfs(0.1);
        assert!((db - (-20.0)).abs() < 0.01, "expected ~-20.0 dBFS, got {}", db);
    }

    #[test]
    fn tracker_new_defaults() {
        let tracker = LevelTracker::new(2);
        let snap = tracker.take_snapshot();
        assert_eq!(snap.channels, 2);
        assert_eq!(snap.peak_dbfs[0], -120.0);
        assert_eq!(snap.peak_dbfs[1], -120.0);
        assert_eq!(snap.rms_dbfs[0], -120.0);
        assert_eq!(snap.rms_dbfs[1], -120.0);
        assert_eq!(snap.graph_clock, GraphClock::default());
    }

    #[test]
    fn tracker_silent_input() {
        let tracker = LevelTracker::new(2);
        let silence = vec![0.0f32; 256 * 2];
        tracker.process(&silence, 2, GraphClock::default());
        let snap = tracker.take_snapshot();
        assert_eq!(snap.peak_dbfs[0], -120.0);
        assert_eq!(snap.rms_dbfs[0], -120.0);
    }

    #[test]
    fn tracker_unity_sine_peak() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[1.0], 1, GraphClock::default());
        let snap = tracker.take_snapshot();
        assert!((snap.peak_dbfs[0] - 0.0).abs() < 0.01);
    }

    #[test]
    fn tracker_unity_dc_rms() {
        let tracker = LevelTracker::new(1);
        let dc: Vec<f32> = vec![1.0; 100];
        tracker.process(&dc, 1, GraphClock::default());
        let snap = tracker.take_snapshot();
        assert!((snap.rms_dbfs[0] - 0.0).abs() < 0.01);
    }

    #[test]
    fn tracker_half_amplitude_rms() {
        let tracker = LevelTracker::new(1);
        let half: Vec<f32> = vec![0.5; 1000];
        tracker.process(&half, 1, GraphClock::default());
        let snap = tracker.take_snapshot();
        assert!((snap.rms_dbfs[0] - (-6.02)).abs() < 0.1);
    }

    #[test]
    fn tracker_multichannel_independent() {
        let tracker = LevelTracker::new(2);
        let samples = [1.0, 0.1, 1.0, 0.1, 1.0, 0.1, 1.0, 0.1];
        tracker.process(&samples, 2, GraphClock::default());
        let snap = tracker.take_snapshot();
        assert!((snap.peak_dbfs[0] - 0.0).abs() < 0.01);
        assert!((snap.peak_dbfs[1] - (-20.0)).abs() < 0.1);
    }

    #[test]
    fn tracker_reset_after_snapshot() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[1.0], 1, GraphClock::default());
        let snap1 = tracker.take_snapshot();
        assert!((snap1.peak_dbfs[0] - 0.0).abs() < 0.01);
        let snap2 = tracker.take_snapshot();
        assert_eq!(snap2.peak_dbfs[0], -120.0);
        assert_eq!(snap2.rms_dbfs[0], -120.0);
    }

    #[test]
    fn tracker_multiple_process_calls_accumulate() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[0.5, 0.3, 0.4], 1, GraphClock::default());
        tracker.process(&[0.2, 0.8, 0.1], 1, GraphClock::default());
        let snap = tracker.take_snapshot();
        let expected_peak = linear_to_dbfs(0.8);
        assert!((snap.peak_dbfs[0] - expected_peak).abs() < 0.1);
        let expected_rms = linear_to_dbfs((1.19f32 / 6.0).sqrt());
        assert!((snap.rms_dbfs[0] - expected_rms).abs() < 0.5);
    }

    #[test]
    fn tracker_negative_samples_use_abs_for_peak() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[-0.9, 0.3, -0.7], 1, GraphClock::default());
        let snap = tracker.take_snapshot();
        let expected = linear_to_dbfs(0.9);
        assert!((snap.peak_dbfs[0] - expected).abs() < 0.1);
    }

    #[test]
    #[should_panic(expected = "exceeds MAX_CHANNELS")]
    fn tracker_too_many_channels_panics() {
        let _ = LevelTracker::new(33);
    }

    #[test]
    fn atomic_max_f32_updates_when_greater() {
        let atom = AtomicU32::new(0.5f32.to_bits());
        atomic_max_f32(&atom, 0.8);
        let val = f32::from_bits(atom.load(Ordering::Relaxed));
        assert!((val - 0.8).abs() < 0.001);
    }

    #[test]
    fn atomic_max_f32_no_update_when_smaller() {
        let atom = AtomicU32::new(0.8f32.to_bits());
        atomic_max_f32(&atom, 0.5);
        let val = f32::from_bits(atom.load(Ordering::Relaxed));
        assert!((val - 0.8).abs() < 0.001);
    }

    #[test]
    fn atomic_add_f32_accumulates() {
        let atom = AtomicU32::new(0.0f32.to_bits());
        atomic_add_f32(&atom, 0.25);
        atomic_add_f32(&atom, 0.25);
        atomic_add_f32(&atom, 0.5);
        let val = f32::from_bits(atom.load(Ordering::Relaxed));
        assert!((val - 1.0).abs() < 0.001);
    }

    // -- Double-buffer specific tests --

    #[test]
    fn double_buffer_alternates() {
        let tracker = LevelTracker::new(1);
        assert_eq!(tracker.active.load(Ordering::Relaxed), 0);

        tracker.process(&[0.5], 1, GraphClock::default());
        let _snap = tracker.take_snapshot();
        assert_eq!(tracker.active.load(Ordering::Relaxed), 1);

        tracker.process(&[0.3], 1, GraphClock::default());
        let _snap = tracker.take_snapshot();
        assert_eq!(tracker.active.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn double_buffer_stale_is_clean_after_snapshot() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[1.0; 100], 1, GraphClock::default());

        let snap = tracker.take_snapshot();
        assert!((snap.peak_dbfs[0] - 0.0).abs() < 0.01);

        let snap2 = tracker.take_snapshot();
        assert_eq!(snap2.peak_dbfs[0], -120.0);

        tracker.process(&[0.25; 10], 1, GraphClock::default());
        let snap3 = tracker.take_snapshot();
        let expected = linear_to_dbfs(0.25);
        assert!((snap3.peak_dbfs[0] - expected).abs() < 0.1);
    }

    #[test]
    fn double_buffer_no_cross_contamination() {
        let tracker = LevelTracker::new(2);

        tracker.process(&[0.8, 0.2, 0.8, 0.2], 2, GraphClock::default());

        let snap1 = tracker.take_snapshot();
        assert!((snap1.peak_dbfs[0] - linear_to_dbfs(0.8)).abs() < 0.1);
        assert!((snap1.peak_dbfs[1] - linear_to_dbfs(0.2)).abs() < 0.1);

        tracker.process(&[0.1, 0.9, 0.1, 0.9], 2, GraphClock::default());

        let snap2 = tracker.take_snapshot();
        assert!((snap2.peak_dbfs[0] - linear_to_dbfs(0.1)).abs() < 0.1);
        assert!((snap2.peak_dbfs[1] - linear_to_dbfs(0.9)).abs() < 0.1);
    }

    #[test]
    fn double_buffer_process_after_snapshot_lands_in_new_buffer() {
        let tracker = LevelTracker::new(1);

        tracker.process(&[0.5; 48], 1, GraphClock::default());

        let snap = tracker.take_snapshot();
        assert!((snap.peak_dbfs[0] - linear_to_dbfs(0.5)).abs() < 0.1);

        tracker.process(&[0.3; 48], 1, GraphClock::default());

        let snap2 = tracker.take_snapshot();
        assert!((snap2.peak_dbfs[0] - linear_to_dbfs(0.3)).abs() < 0.1);
    }

    // -- Graph clock tests --

    #[test]
    fn graph_clock_captured_in_snapshot() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[0.5; 256], 1, clock(48000, 1_000_000_000));
        let snap = tracker.take_snapshot();
        assert_eq!(snap.graph_clock.position, 48000);
        assert_eq!(snap.graph_clock.nsec, 1_000_000_000);
    }

    #[test]
    fn graph_clock_latest_wins() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[0.5; 256], 1, clock(48000, 1_000_000_000));
        tracker.process(&[0.5; 256], 1, clock(96000, 2_000_000_000));
        let snap = tracker.take_snapshot();
        assert_eq!(snap.graph_clock.position, 96000);
        assert_eq!(snap.graph_clock.nsec, 2_000_000_000);
    }

    #[test]
    fn graph_clock_reset_after_snapshot() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[0.5; 256], 1, clock(48000, 1_000_000_000));
        let _snap = tracker.take_snapshot();

        let snap2 = tracker.take_snapshot();
        assert_eq!(snap2.graph_clock, GraphClock::default());
    }

    #[test]
    fn graph_clock_monotonic_across_snapshots() {
        let tracker = LevelTracker::new(1);

        // Simulate 3 quanta with monotonically increasing clocks.
        tracker.process(&[0.5; 256], 1, clock(256, 5_333_333));
        let snap1 = tracker.take_snapshot();

        tracker.process(&[0.5; 256], 1, clock(512, 10_666_666));
        let snap2 = tracker.take_snapshot();

        tracker.process(&[0.5; 256], 1, clock(768, 16_000_000));
        let snap3 = tracker.take_snapshot();

        assert!(snap2.graph_clock.position > snap1.graph_clock.position);
        assert!(snap3.graph_clock.position > snap2.graph_clock.position);
        assert!(snap2.graph_clock.nsec > snap1.graph_clock.nsec);
        assert!(snap3.graph_clock.nsec > snap2.graph_clock.nsec);
    }

    #[test]
    fn graph_clock_default_when_no_data() {
        let tracker = LevelTracker::new(1);
        let snap = tracker.take_snapshot();
        assert_eq!(snap.graph_clock, GraphClock::default());
    }
}
