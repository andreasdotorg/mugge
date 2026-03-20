//! Per-channel peak and RMS level tracking for the web UI.
//!
//! The PipeWire process callback calls [`LevelTracker::process`] each quantum
//! with interleaved float32 samples. The tracker accumulates peak (max |sample|)
//! and sum-of-squares per channel. A server thread calls [`LevelTracker::take_snapshot`]
//! at 10 Hz to harvest the accumulated values as dBFS, resetting the accumulators.
//!
//! All state is stored in atomic integers (bit-punned f32→u32) so the RT callback
//! never blocks. The design is single-writer (PW callback) / single-reader (levels
//! server thread), but uses atomics for correctness without locks.

use std::sync::atomic::{AtomicU32, Ordering};

/// Maximum number of channels supported.
const MAX_CHANNELS: usize = 32;

/// Convert a linear amplitude to dBFS. Returns -120.0 for zero or negative.
fn linear_to_dbfs(linear: f32) -> f32 {
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

/// Per-channel level snapshot in dBFS.
#[derive(Debug, Clone)]
pub struct LevelSnapshot {
    /// Number of active channels in the arrays below.
    pub channels: usize,
    /// Peak level per channel in dBFS (max |sample| since last snapshot).
    pub peak_dbfs: [f32; MAX_CHANNELS],
    /// RMS level per channel in dBFS (root-mean-square since last snapshot).
    pub rms_dbfs: [f32; MAX_CHANNELS],
}

impl Default for LevelSnapshot {
    fn default() -> Self {
        Self {
            channels: 0,
            peak_dbfs: [-120.0; MAX_CHANNELS],
            rms_dbfs: [-120.0; MAX_CHANNELS],
        }
    }
}

/// Lock-free per-channel level tracker.
///
/// Single writer (PW process callback) accumulates peak and sum-of-squares.
/// Single reader (levels server) harvests via [`take_snapshot`].
pub struct LevelTracker {
    channels: usize,
    /// Per-channel peak (max |sample|), stored as f32 bits in AtomicU32.
    peak: [AtomicU32; MAX_CHANNELS],
    /// Per-channel sum of squares, stored as f32 bits in AtomicU32.
    sum_sq: [AtomicU32; MAX_CHANNELS],
    /// Total sample count accumulated since last snapshot (shared across channels).
    sample_count: AtomicU32,
}

// Safety: LevelTracker uses only atomics for shared state. No raw pointers,
// no interior mutability beyond atomics. Safe to share across threads.
unsafe impl Sync for LevelTracker {}
unsafe impl Send for LevelTracker {}

impl LevelTracker {
    /// Create a new level tracker for the given number of channels.
    pub fn new(channels: usize) -> Self {
        assert!(channels <= MAX_CHANNELS, "channels {} exceeds MAX_CHANNELS {}", channels, MAX_CHANNELS);
        // Initialize peak to 0.0 and sum_sq to 0.0
        const ZERO_BITS: u32 = 0; // 0.0f32.to_bits() == 0
        let peak = std::array::from_fn(|_| AtomicU32::new(ZERO_BITS));
        let sum_sq = std::array::from_fn(|_| AtomicU32::new(ZERO_BITS));
        Self {
            channels,
            peak,
            sum_sq,
            sample_count: AtomicU32::new(0),
        }
    }

    /// Process interleaved float32 samples from the PW callback.
    ///
    /// This is called from the RT audio thread. It uses only atomic operations
    /// (no allocations, no locks, no syscalls).
    pub fn process(&self, samples: &[f32], channels: usize) {
        debug_assert_eq!(channels, self.channels);
        let n_frames = samples.len() / channels;
        if n_frames == 0 {
            return;
        }

        for frame in 0..n_frames {
            let base = frame * channels;
            for ch in 0..channels {
                let sample = samples[base + ch];
                let abs_sample = sample.abs();

                // Update peak (max |sample|)
                atomic_max_f32(&self.peak[ch], abs_sample);

                // Accumulate sum of squares for RMS
                atomic_add_f32(&self.sum_sq[ch], sample * sample);
            }
        }

        // Accumulate frame count (not sample count — one frame = one sample per channel)
        // Using Relaxed ordering: the snapshot reader uses a Release/Acquire fence
        // implicitly via the swap operations.
        let prev = self.sample_count.load(Ordering::Relaxed);
        let new_count = prev.saturating_add(n_frames as u32);
        self.sample_count.store(new_count, Ordering::Relaxed);
    }

    /// Harvest the accumulated levels as a dBFS snapshot and reset accumulators.
    ///
    /// Called from the levels server thread at ~10 Hz. Returns peak and RMS
    /// in dBFS for each channel.
    pub fn take_snapshot(&self) -> LevelSnapshot {
        let n = self.sample_count.swap(0, Ordering::AcqRel);

        let mut snap = LevelSnapshot {
            channels: self.channels,
            ..Default::default()
        };

        for ch in 0..self.channels {
            // Swap peak to 0.0, get the accumulated peak
            let peak_bits = self.peak[ch].swap(0u32, Ordering::AcqRel);
            let peak_linear = f32::from_bits(peak_bits);
            snap.peak_dbfs[ch] = linear_to_dbfs(peak_linear);

            // Swap sum_sq to 0.0, get the accumulated sum of squares
            let sum_sq_bits = self.sum_sq[ch].swap(0u32, Ordering::AcqRel);
            let sum_sq = f32::from_bits(sum_sq_bits);

            if n > 0 {
                let rms_linear = (sum_sq / n as f32).sqrt();
                snap.rms_dbfs[ch] = linear_to_dbfs(rms_linear);
            }
            // else: rms stays at -120.0 (default)
        }

        snap
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // --- linear_to_dbfs tests ---

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

    // --- LevelTracker tests ---

    #[test]
    fn tracker_new_defaults() {
        let tracker = LevelTracker::new(2);
        let snap = tracker.take_snapshot();
        assert_eq!(snap.channels, 2);
        assert_eq!(snap.peak_dbfs[0], -120.0);
        assert_eq!(snap.peak_dbfs[1], -120.0);
        assert_eq!(snap.rms_dbfs[0], -120.0);
        assert_eq!(snap.rms_dbfs[1], -120.0);
    }

    #[test]
    fn tracker_silent_input() {
        let tracker = LevelTracker::new(2);
        let silence = vec![0.0f32; 256 * 2];
        tracker.process(&silence, 2);
        let snap = tracker.take_snapshot();
        assert_eq!(snap.peak_dbfs[0], -120.0);
        assert_eq!(snap.rms_dbfs[0], -120.0);
    }

    #[test]
    fn tracker_unity_sine_peak() {
        let tracker = LevelTracker::new(1);
        // Single frame with sample = 1.0
        tracker.process(&[1.0], 1);
        let snap = tracker.take_snapshot();
        assert!((snap.peak_dbfs[0] - 0.0).abs() < 0.01, "expected ~0 dBFS peak, got {}", snap.peak_dbfs[0]);
    }

    #[test]
    fn tracker_unity_dc_rms() {
        let tracker = LevelTracker::new(1);
        // 100 frames of DC at 1.0 => RMS = 1.0 => 0 dBFS
        let dc: Vec<f32> = vec![1.0; 100];
        tracker.process(&dc, 1);
        let snap = tracker.take_snapshot();
        assert!((snap.rms_dbfs[0] - 0.0).abs() < 0.01, "expected ~0 dBFS RMS, got {}", snap.rms_dbfs[0]);
    }

    #[test]
    fn tracker_half_amplitude_rms() {
        let tracker = LevelTracker::new(1);
        let half: Vec<f32> = vec![0.5; 1000];
        tracker.process(&half, 1);
        let snap = tracker.take_snapshot();
        // DC at 0.5 => RMS = 0.5 => -6.02 dBFS
        assert!((snap.rms_dbfs[0] - (-6.02)).abs() < 0.1, "expected ~-6.02 dBFS, got {}", snap.rms_dbfs[0]);
    }

    #[test]
    fn tracker_multichannel_independent() {
        let tracker = LevelTracker::new(2);
        // 4 frames, stereo: ch0 = 1.0, ch1 = 0.1
        let samples = [1.0, 0.1, 1.0, 0.1, 1.0, 0.1, 1.0, 0.1];
        tracker.process(&samples, 2);
        let snap = tracker.take_snapshot();

        // Ch0: peak = 1.0 => 0 dBFS
        assert!((snap.peak_dbfs[0] - 0.0).abs() < 0.01);
        // Ch1: peak = 0.1 => -20 dBFS
        assert!((snap.peak_dbfs[1] - (-20.0)).abs() < 0.1);
    }

    #[test]
    fn tracker_reset_after_snapshot() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[1.0], 1);

        let snap1 = tracker.take_snapshot();
        assert!((snap1.peak_dbfs[0] - 0.0).abs() < 0.01);

        // After snapshot, accumulators are reset
        let snap2 = tracker.take_snapshot();
        assert_eq!(snap2.peak_dbfs[0], -120.0);
        assert_eq!(snap2.rms_dbfs[0], -120.0);
    }

    #[test]
    fn tracker_multiple_process_calls_accumulate() {
        let tracker = LevelTracker::new(1);
        // First call: peak 0.5
        tracker.process(&[0.5, 0.3, 0.4], 1);
        // Second call: peak 0.8
        tracker.process(&[0.2, 0.8, 0.1], 1);

        let snap = tracker.take_snapshot();
        // Peak should be 0.8 from the second call
        let expected_peak = linear_to_dbfs(0.8);
        assert!((snap.peak_dbfs[0] - expected_peak).abs() < 0.1);

        // RMS over all 6 samples: sqrt((0.25 + 0.09 + 0.16 + 0.04 + 0.64 + 0.01) / 6)
        // = sqrt(1.19 / 6) = sqrt(0.19833) = 0.4454 => -7.03 dBFS
        let expected_rms = linear_to_dbfs((1.19f32 / 6.0).sqrt());
        assert!((snap.rms_dbfs[0] - expected_rms).abs() < 0.5);
    }

    #[test]
    fn tracker_negative_samples_use_abs_for_peak() {
        let tracker = LevelTracker::new(1);
        tracker.process(&[-0.9, 0.3, -0.7], 1);
        let snap = tracker.take_snapshot();
        // Peak should be |-0.9| = 0.9
        let expected = linear_to_dbfs(0.9);
        assert!((snap.peak_dbfs[0] - expected).abs() < 0.1);
    }

    #[test]
    #[should_panic(expected = "exceeds MAX_CHANNELS")]
    fn tracker_too_many_channels_panics() {
        let _ = LevelTracker::new(33);
    }

    // --- atomic helper tests ---

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
}
