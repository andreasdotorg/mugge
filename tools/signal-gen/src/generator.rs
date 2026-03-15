//! Signal generator trait and waveform implementations.
//!
//! Each generator produces interleaved float32 samples into a provided buffer.
//! The `SignalGenerator` trait is object-safe so generators can be swapped at
//! runtime via RPC commands without restarting the PipeWire stream.
//!
//! All generators are RT-safe: no allocation, no syscalls, no blocking after
//! construction. The `generate` method is called from the PipeWire process
//! callback on the SCHED_FIFO data thread.

use rand_core::{RngCore, SeedableRng};
use rand_xoshiro::Xoshiro256PlusPlus;

// ---------------------------------------------------------------------------
// Trait
// ---------------------------------------------------------------------------

/// Trait for all signal generators (Section 4.1).
///
/// Implementations must be RT-safe: no allocation, no syscalls, no blocking.
/// The `generate` method is called from the PipeWire process callback.
pub trait SignalGenerator: Send {
    /// Fill `buffer` with interleaved float32 samples.
    ///
    /// - `buffer.len()` == `n_frames * channels`
    /// - Only channels whose bit is set in `active_channels` receive signal;
    ///   others receive silence (0.0).
    /// - `level_linear` is the linear amplitude scale (e.g., 0.1 for -20 dBFS).
    ///   The caller (safety limiter) may apply additional hard clipping after
    ///   this returns.
    fn generate(
        &mut self,
        buffer: &mut [f32],
        n_frames: usize,
        channels: usize,
        active_channels: u8,
        level_linear: f32,
    );

    /// Human-readable name for status reporting.
    fn name(&self) -> &'static str;

    /// Returns true if this generator has finished (burst mode).
    /// Continuous generators always return false.
    fn is_finished(&self) -> bool {
        false
    }
}

// ---------------------------------------------------------------------------
// Silence
// ---------------------------------------------------------------------------

/// Silence generator -- writes zeroes. This is the default at startup.
pub struct SilenceGenerator;

impl SignalGenerator for SilenceGenerator {
    fn generate(
        &mut self,
        buffer: &mut [f32],
        _n_frames: usize,
        _channels: usize,
        _active_channels: u8,
        _level_linear: f32,
    ) {
        buffer.fill(0.0);
    }

    fn name(&self) -> &'static str {
        "silence"
    }
}

// ---------------------------------------------------------------------------
// Sine (Section 4.3)
// ---------------------------------------------------------------------------

/// Phase-continuous sine generator with f64 accumulator.
///
/// Frequency changes update `phase_increment` without resetting `phase`,
/// producing a smooth transition with no click or discontinuity.
pub struct SineGenerator {
    phase: f64,
    phase_increment: f64,
}

impl SineGenerator {
    /// Create a new sine generator.
    ///
    /// `freq` is the initial frequency in Hz, `sample_rate` in Hz.
    pub fn new(freq: f64, sample_rate: f64) -> Self {
        Self {
            phase: 0.0,
            phase_increment: 2.0 * std::f64::consts::PI * freq / sample_rate,
        }
    }

    /// Update frequency without resetting phase (phase-continuous).
    pub fn set_frequency(&mut self, freq: f64, sample_rate: f64) {
        self.phase_increment = 2.0 * std::f64::consts::PI * freq / sample_rate;
    }
}

impl SignalGenerator for SineGenerator {
    fn generate(
        &mut self,
        buffer: &mut [f32],
        n_frames: usize,
        channels: usize,
        active_channels: u8,
        level_linear: f32,
    ) {
        for frame in 0..n_frames {
            let sample = (self.phase.sin() * level_linear as f64) as f32;
            self.phase += self.phase_increment;

            // Wrap phase to [0, 2*pi) to prevent f64 precision loss over time.
            if self.phase >= 2.0 * std::f64::consts::PI {
                self.phase -= 2.0 * std::f64::consts::PI;
            }

            let base = frame * channels;
            for ch in 0..channels {
                buffer[base + ch] = if active_channels & (1 << ch) != 0 {
                    sample
                } else {
                    0.0
                };
            }
        }
    }

    fn name(&self) -> &'static str {
        "sine"
    }
}

// ---------------------------------------------------------------------------
// White Noise (Section 4.4)
// ---------------------------------------------------------------------------

/// White noise generator using xoshiro256++ PRNG.
///
/// Produces uniform samples in [-1.0, 1.0]. No heap allocation, no syscalls.
pub struct WhiteNoiseGenerator {
    rng: Xoshiro256PlusPlus,
}

impl WhiteNoiseGenerator {
    /// Create a new white noise generator with the given seed.
    pub fn new(seed: u64) -> Self {
        Self {
            rng: Xoshiro256PlusPlus::seed_from_u64(seed),
        }
    }

    /// Generate a single uniform random sample in [-1.0, 1.0].
    #[inline]
    fn next_sample(&mut self) -> f32 {
        // Convert u64 to float in [-1.0, 1.0]:
        // Take the upper 53 bits for a double in [0, 1), then scale to [-1, 1].
        let bits = self.rng.next_u64();
        let f = (bits >> 11) as f64 * (1.0 / (1u64 << 53) as f64); // [0, 1)
        (f * 2.0 - 1.0) as f32
    }
}

impl SignalGenerator for WhiteNoiseGenerator {
    fn generate(
        &mut self,
        buffer: &mut [f32],
        n_frames: usize,
        channels: usize,
        active_channels: u8,
        level_linear: f32,
    ) {
        for frame in 0..n_frames {
            let sample = self.next_sample() * level_linear;
            let base = frame * channels;
            for ch in 0..channels {
                buffer[base + ch] = if active_channels & (1 << ch) != 0 {
                    sample
                } else {
                    0.0
                };
            }
        }
    }

    fn name(&self) -> &'static str {
        "white"
    }
}

// ---------------------------------------------------------------------------
// Pink Noise — Voss-McCartney (Section 4.5)
// ---------------------------------------------------------------------------

const PINK_NUM_ROWS: usize = 16;

/// Pink noise generator using the Voss-McCartney algorithm with 16 rows.
///
/// Produces 1/f noise by summing random number generators that update at
/// octave-spaced intervals. O(1) per sample with one RNG call per sample.
/// Spectral accuracy: +/- 0.5 dB around ideal -3 dB/octave slope.
pub struct PinkNoiseGenerator {
    rows: [f64; PINK_NUM_ROWS],
    running_sum: f64,
    counter: u32,
    rng: Xoshiro256PlusPlus,
    norm: f64,
}

impl PinkNoiseGenerator {
    /// Create a new pink noise generator with the given seed.
    pub fn new(seed: u64) -> Self {
        let mut rng = Xoshiro256PlusPlus::seed_from_u64(seed);
        let mut rows = [0.0f64; PINK_NUM_ROWS];
        let mut running_sum = 0.0f64;

        // Initialize all rows with random values in [-1, 1].
        for row in &mut rows {
            let bits = rng.next_u64();
            let f = (bits >> 11) as f64 * (1.0 / (1u64 << 53) as f64);
            *row = f * 2.0 - 1.0;
            running_sum += *row;
        }

        Self {
            rows,
            running_sum,
            counter: 0,
            rng,
            norm: 1.0 / PINK_NUM_ROWS as f64,
        }
    }

    /// Generate a single pink noise sample.
    #[inline]
    fn next_sample(&mut self) -> f64 {
        // Increment counter (wraps naturally at u32::MAX).
        self.counter = self.counter.wrapping_add(1);

        // Find the index of the lowest set bit.
        let row_idx = self.counter.trailing_zeros() as usize;

        if row_idx < PINK_NUM_ROWS {
            // Subtract old value, generate new, add new value.
            self.running_sum -= self.rows[row_idx];
            let bits = self.rng.next_u64();
            let f = (bits >> 11) as f64 * (1.0 / (1u64 << 53) as f64);
            self.rows[row_idx] = f * 2.0 - 1.0;
            self.running_sum += self.rows[row_idx];
        }

        self.running_sum * self.norm
    }
}

impl SignalGenerator for PinkNoiseGenerator {
    fn generate(
        &mut self,
        buffer: &mut [f32],
        n_frames: usize,
        channels: usize,
        active_channels: u8,
        level_linear: f32,
    ) {
        for frame in 0..n_frames {
            let sample = (self.next_sample() * level_linear as f64) as f32;
            let base = frame * channels;
            for ch in 0..channels {
                buffer[base + ch] = if active_channels & (1 << ch) != 0 {
                    sample
                } else {
                    0.0
                };
            }
        }
    }

    fn name(&self) -> &'static str {
        "pink"
    }
}

// ---------------------------------------------------------------------------
// Log Sweep (Section 4.6)
// ---------------------------------------------------------------------------

/// Logarithmic frequency sweep generator.
///
/// Sweeps from `f_start` to `f_end` over `total_samples`. The instantaneous
/// frequency increases exponentially, spending equal time per octave.
/// Burst mode only -- transitions to finished after `total_samples`.
pub struct SweepGenerator {
    phase: f64,
    sample_count: u64,
    total_samples: u64,
    f_start: f64,
    rate: f64,
    log_sweep_rate: f64,
    finished: bool,
}

impl SweepGenerator {
    /// Create a new sweep generator.
    ///
    /// - `f_start`, `f_end`: sweep frequency range in Hz [20, 20000] per AE-MF-2
    /// - `duration_secs`: sweep duration in seconds
    /// - `sample_rate`: sample rate in Hz
    pub fn new(f_start: f64, f_end: f64, duration_secs: f64, sample_rate: f64) -> Self {
        let total_samples = (duration_secs * sample_rate) as u64;
        let log_sweep_rate = (f_end / f_start).ln() / total_samples as f64;
        Self {
            phase: 0.0,
            sample_count: 0,
            total_samples,
            f_start,
            rate: sample_rate,
            log_sweep_rate,
            finished: false,
        }
    }

    /// Return the instantaneous frequency at the current sample position.
    pub fn instantaneous_freq(&self) -> f64 {
        self.f_start * (self.log_sweep_rate * self.sample_count as f64).exp()
    }
}

impl SignalGenerator for SweepGenerator {
    fn generate(
        &mut self,
        buffer: &mut [f32],
        n_frames: usize,
        channels: usize,
        active_channels: u8,
        level_linear: f32,
    ) {
        for frame in 0..n_frames {
            let sample = if self.finished {
                0.0
            } else {
                // Instantaneous frequency at current sample.
                let f_inst = self.f_start
                    * (self.log_sweep_rate * self.sample_count as f64).exp();

                // Advance phase by instantaneous frequency.
                self.phase += 2.0 * std::f64::consts::PI * f_inst / self.rate;

                // Wrap phase to avoid precision loss.
                if self.phase >= 2.0 * std::f64::consts::PI {
                    self.phase -= 2.0 * std::f64::consts::PI;
                }

                self.sample_count += 1;
                if self.sample_count >= self.total_samples {
                    self.finished = true;
                }

                (self.phase.sin() * level_linear as f64) as f32
            };

            let base = frame * channels;
            for ch in 0..channels {
                buffer[base + ch] = if active_channels & (1 << ch) != 0 {
                    sample
                } else {
                    0.0
                };
            }
        }
    }

    fn name(&self) -> &'static str {
        "sweep"
    }

    fn is_finished(&self) -> bool {
        self.finished
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE_RATE: f64 = 48000.0;

    // Helper: create a mono buffer and generate into it.
    fn generate_mono(gen: &mut dyn SignalGenerator, n_frames: usize, level: f32) -> Vec<f32> {
        let mut buf = vec![0.0f32; n_frames];
        gen.generate(&mut buf, n_frames, 1, 0x01, level);
        buf
    }

    // -----------------------------------------------------------------------
    // Silence
    // -----------------------------------------------------------------------

    #[test]
    fn silence_output_is_all_zeroes() {
        let mut gen = SilenceGenerator;
        let buf = generate_mono(&mut gen, 1024, 1.0);
        assert!(buf.iter().all(|&s| s == 0.0));
    }

    #[test]
    fn silence_name() {
        assert_eq!(SilenceGenerator.name(), "silence");
    }

    // -----------------------------------------------------------------------
    // Sine: phase continuity
    // -----------------------------------------------------------------------

    #[test]
    fn sine_phase_continuity_across_calls() {
        // Generate 256 samples in one call, then 256 in another.
        // The boundary should have no discontinuity.
        let mut gen = SineGenerator::new(1000.0, SAMPLE_RATE);
        let buf1 = generate_mono(&mut gen, 256, 1.0);
        let buf2 = generate_mono(&mut gen, 256, 1.0);

        // Check continuity at the boundary: the difference between the
        // last sample of buf1 and the first sample of buf2 should be
        // close to one phase_increment step.
        let diff = (buf2[0] - buf1[255]).abs();
        // At 1kHz / 48kHz, phase_increment produces ~0.13 difference per
        // sample. Allow generous tolerance for the boundary.
        assert!(
            diff < 0.2,
            "Discontinuity at boundary: last={}, first={}, diff={}",
            buf1[255],
            buf2[0],
            diff
        );
    }

    #[test]
    fn sine_frequency_change_is_phase_continuous() {
        let mut gen = SineGenerator::new(440.0, SAMPLE_RATE);
        let buf1 = generate_mono(&mut gen, 128, 1.0);

        // Change frequency mid-stream.
        gen.set_frequency(880.0, SAMPLE_RATE);
        let buf2 = generate_mono(&mut gen, 128, 1.0);

        // The boundary should still be smooth -- no large jump.
        let diff = (buf2[0] - buf1[127]).abs();
        assert!(
            diff < 0.2,
            "Discontinuity on freq change: last={}, first={}, diff={}",
            buf1[127],
            buf2[0],
            diff
        );
    }

    #[test]
    fn sine_frequency_accuracy() {
        // Generate exactly one second of 1000 Hz sine.
        // Count zero crossings: should be ~2000 (2 per cycle).
        let mut gen = SineGenerator::new(1000.0, SAMPLE_RATE);
        let n = SAMPLE_RATE as usize;
        let buf = generate_mono(&mut gen, n, 1.0);

        let mut zero_crossings = 0u32;
        for i in 1..n {
            if (buf[i - 1] >= 0.0) != (buf[i] >= 0.0) {
                zero_crossings += 1;
            }
        }

        // 1000 Hz -> 2000 zero crossings per second. Allow +/- 2.
        let expected = 2000u32;
        assert!(
            zero_crossings.abs_diff(expected) <= 2,
            "Expected ~{} zero crossings, got {}",
            expected,
            zero_crossings
        );
    }

    #[test]
    fn sine_output_range() {
        let mut gen = SineGenerator::new(440.0, SAMPLE_RATE);
        let buf = generate_mono(&mut gen, 48000, 0.5);
        for &s in &buf {
            assert!(
                s.abs() <= 0.5 + 1e-6,
                "Sample {} exceeds level 0.5",
                s
            );
        }
    }

    #[test]
    fn sine_name() {
        let gen = SineGenerator::new(1000.0, SAMPLE_RATE);
        assert_eq!(gen.name(), "sine");
    }

    // -----------------------------------------------------------------------
    // Sine: channel routing
    // -----------------------------------------------------------------------

    #[test]
    fn sine_active_channels_routing() {
        // 4 channels, only channel 0 and 2 active (bitmask 0b0101 = 5).
        let mut gen = SineGenerator::new(1000.0, SAMPLE_RATE);
        let channels = 4;
        let n_frames = 64;
        let mut buf = vec![0.0f32; n_frames * channels];
        gen.generate(&mut buf, n_frames, channels, 0b0101, 1.0);

        // Start from frame 1: frame 0 has sin(0)=0 which is legitimately zero.
        for frame in 1..n_frames {
            let base = frame * channels;
            // Channels 0 and 2 should have signal.
            assert_ne!(buf[base], 0.0, "ch0 frame {} should have signal", frame);
            assert_ne!(buf[base + 2], 0.0, "ch2 frame {} should have signal", frame);
            // Channels 1 and 3 should be silent.
            assert_eq!(buf[base + 1], 0.0, "ch1 frame {} should be silent", frame);
            assert_eq!(buf[base + 3], 0.0, "ch3 frame {} should be silent", frame);
        }
    }

    // -----------------------------------------------------------------------
    // White noise: distribution
    // -----------------------------------------------------------------------

    #[test]
    fn white_noise_mean_near_zero() {
        let mut gen = WhiteNoiseGenerator::new(42);
        let n = 100_000;
        let buf = generate_mono(&mut gen, n, 1.0);
        let mean: f64 = buf.iter().map(|&s| s as f64).sum::<f64>() / n as f64;
        assert!(
            mean.abs() < 0.01,
            "White noise mean should be ~0, got {}",
            mean
        );
    }

    #[test]
    fn white_noise_std_uniform() {
        // For uniform [-1, 1], std = 1/sqrt(3) ~ 0.577.
        let mut gen = WhiteNoiseGenerator::new(42);
        let n = 100_000;
        let buf = generate_mono(&mut gen, n, 1.0);
        let mean: f64 = buf.iter().map(|&s| s as f64).sum::<f64>() / n as f64;
        let variance: f64 =
            buf.iter().map(|&s| (s as f64 - mean).powi(2)).sum::<f64>() / n as f64;
        let std_dev = variance.sqrt();
        let expected = 1.0 / 3.0f64.sqrt(); // ~0.577
        assert!(
            (std_dev - expected).abs() < 0.02,
            "White noise std should be ~{:.3}, got {:.3}",
            expected,
            std_dev
        );
    }

    #[test]
    fn white_noise_range() {
        let mut gen = WhiteNoiseGenerator::new(42);
        let buf = generate_mono(&mut gen, 100_000, 1.0);
        for &s in &buf {
            assert!(
                s >= -1.0 && s <= 1.0,
                "White noise sample {} outside [-1, 1]",
                s
            );
        }
    }

    #[test]
    fn white_noise_level_scaling() {
        let mut gen = WhiteNoiseGenerator::new(42);
        let level = 0.1f32;
        let buf = generate_mono(&mut gen, 10_000, level);
        for &s in &buf {
            assert!(
                s.abs() <= level + 1e-6,
                "Sample {} exceeds level {}",
                s,
                level
            );
        }
    }

    #[test]
    fn white_noise_name() {
        let gen = WhiteNoiseGenerator::new(0);
        assert_eq!(gen.name(), "white");
    }

    // -----------------------------------------------------------------------
    // Pink noise: spectral slope
    // -----------------------------------------------------------------------

    #[test]
    fn pink_noise_spectral_slope() {
        // Generate a long pink noise signal and verify the spectral slope
        // is approximately -10 dB/decade (-3 dB/octave).
        //
        // Method: compute average power in two frequency bands separated
        // by a decade, check the ratio is close to 10 dB.
        let mut gen = PinkNoiseGenerator::new(42);
        let n = 262_144; // 2^18, ~5.5 seconds at 48kHz
        let buf = generate_mono(&mut gen, n, 1.0);

        // Simple power spectral density via averaged periodograms.
        // Split into segments, compute |FFT|^2 for each, average.
        let seg_len = 4096;
        let n_segs = n / seg_len;
        let mut psd = vec![0.0f64; seg_len / 2 + 1];

        for seg in 0..n_segs {
            let offset = seg * seg_len;
            // Apply Hann window and compute DFT magnitude squared.
            // (We use a basic DFT on binned averages for simplicity --
            // this test validates slope, not absolute magnitude.)
            let mut windowed = vec![0.0f64; seg_len];
            for i in 0..seg_len {
                let w = 0.5 * (1.0 - (2.0 * std::f64::consts::PI * i as f64 / seg_len as f64).cos());
                windowed[i] = buf[offset + i] as f64 * w;
            }

            // Compute power at each frequency bin via DFT.
            // For test purposes, only compute bins we need (low and high band).
            // Full DFT would be expensive but we can afford it for 4096 points.
            for k in 0..=(seg_len / 2) {
                let mut re = 0.0f64;
                let mut im = 0.0f64;
                for i in 0..seg_len {
                    let angle = 2.0 * std::f64::consts::PI * k as f64 * i as f64 / seg_len as f64;
                    re += windowed[i] * angle.cos();
                    im -= windowed[i] * angle.sin();
                }
                psd[k] += re * re + im * im;
            }
        }

        // Average and convert to dB.
        let freq_resolution = SAMPLE_RATE / seg_len as f64; // ~11.72 Hz per bin
        for p in psd.iter_mut() {
            *p /= n_segs as f64;
        }

        // Compare power at ~100 Hz vs ~1000 Hz (one decade apart).
        let bin_100 = (100.0 / freq_resolution).round() as usize;
        let bin_1000 = (1000.0 / freq_resolution).round() as usize;

        // Average a few bins around each target to reduce variance.
        let avg_bins = 3;
        let power_100: f64 = psd[bin_100 - avg_bins..=bin_100 + avg_bins]
            .iter()
            .sum::<f64>()
            / (2 * avg_bins + 1) as f64;
        let power_1000: f64 = psd[bin_1000 - avg_bins..=bin_1000 + avg_bins]
            .iter()
            .sum::<f64>()
            / (2 * avg_bins + 1) as f64;

        let db_diff = 10.0 * (power_100 / power_1000).log10();

        // Pink noise: +10 dB/decade (lower freqs have more power).
        // Voss-McCartney has +/- 0.5 dB ripple per the design doc.
        // Allow +/- 2 dB tolerance for statistical variation in the test.
        assert!(
            (db_diff - 10.0).abs() < 2.0,
            "Pink noise slope should be ~10 dB/decade, got {:.1} dB \
             (power@100Hz={:.1} dB, power@1kHz={:.1} dB)",
            db_diff,
            10.0 * power_100.log10(),
            10.0 * power_1000.log10()
        );
    }

    #[test]
    fn pink_noise_mean_near_zero() {
        let mut gen = PinkNoiseGenerator::new(42);
        let n = 100_000;
        let buf = generate_mono(&mut gen, n, 1.0);
        let mean: f64 = buf.iter().map(|&s| s as f64).sum::<f64>() / n as f64;
        assert!(
            mean.abs() < 0.05,
            "Pink noise mean should be ~0, got {}",
            mean
        );
    }

    #[test]
    fn pink_noise_name() {
        let gen = PinkNoiseGenerator::new(0);
        assert_eq!(gen.name(), "pink");
    }

    // -----------------------------------------------------------------------
    // Sweep: frequency range coverage
    // -----------------------------------------------------------------------

    #[test]
    fn sweep_covers_frequency_range() {
        // 1-second sweep from 20 Hz to 20000 Hz.
        let mut gen = SweepGenerator::new(20.0, 20000.0, 1.0, SAMPLE_RATE);

        // Check instantaneous frequency at start, middle, and end.
        let f_start = gen.instantaneous_freq();
        assert!(
            (f_start - 20.0).abs() < 0.1,
            "Start freq should be ~20 Hz, got {}",
            f_start
        );

        // Advance to halfway.
        let half = (SAMPLE_RATE as usize) / 2;
        let mut buf = vec![0.0f32; half];
        gen.generate(&mut buf, half, 1, 0x01, 1.0);

        let f_mid = gen.instantaneous_freq();
        // Log sweep midpoint: sqrt(20 * 20000) = ~632 Hz.
        let expected_mid = (20.0f64 * 20000.0).sqrt();
        let ratio = f_mid / expected_mid;
        assert!(
            (ratio - 1.0).abs() < 0.05,
            "Mid freq should be ~{:.0} Hz, got {:.0} Hz",
            expected_mid,
            f_mid
        );

        // Advance to end.
        let remaining = (SAMPLE_RATE as usize) - half;
        let mut buf2 = vec![0.0f32; remaining];
        gen.generate(&mut buf2, remaining, 1, 0x01, 1.0);

        // After total_samples, the generator should be finished.
        assert!(gen.is_finished(), "Sweep should be finished after total_samples");
    }

    #[test]
    fn sweep_burst_auto_stop() {
        // Short sweep: 0.01 seconds (480 samples at 48kHz).
        let mut gen = SweepGenerator::new(100.0, 10000.0, 0.01, SAMPLE_RATE);
        assert!(!gen.is_finished());

        // Generate the full sweep.
        let n = 480;
        let mut buf = vec![0.0f32; n];
        gen.generate(&mut buf, n, 1, 0x01, 1.0);
        assert!(gen.is_finished(), "Sweep should be finished after duration");

        // Further generation should produce silence.
        let mut buf2 = vec![1.0f32; 256]; // fill with non-zero
        gen.generate(&mut buf2, 256, 1, 0x01, 1.0);
        assert!(
            buf2.iter().all(|&s| s == 0.0),
            "Post-sweep output should be silence"
        );
    }

    #[test]
    fn sweep_output_is_nonzero_during_sweep() {
        let mut gen = SweepGenerator::new(20.0, 20000.0, 0.1, SAMPLE_RATE);
        let n = 4800; // 0.1 seconds
        let mut buf = vec![0.0f32; n];
        gen.generate(&mut buf, n, 1, 0x01, 1.0);

        // Most samples should be non-zero (except possibly near zero crossings).
        let nonzero_count = buf.iter().filter(|&&s| s.abs() > 1e-6).count();
        assert!(
            nonzero_count > n / 2,
            "Sweep should produce mostly non-zero samples, got {}/{}",
            nonzero_count,
            n
        );
    }

    #[test]
    fn sweep_name() {
        let gen = SweepGenerator::new(20.0, 20000.0, 1.0, SAMPLE_RATE);
        assert_eq!(gen.name(), "sweep");
    }

    #[test]
    fn sweep_not_finished_initially() {
        let gen = SweepGenerator::new(20.0, 20000.0, 1.0, SAMPLE_RATE);
        assert!(!gen.is_finished());
    }

    // -----------------------------------------------------------------------
    // General: is_finished defaults to false for continuous generators
    // -----------------------------------------------------------------------

    #[test]
    fn continuous_generators_never_finish() {
        assert!(!SilenceGenerator.is_finished());
        assert!(!SineGenerator::new(1000.0, SAMPLE_RATE).is_finished());
        assert!(!WhiteNoiseGenerator::new(0).is_finished());
        assert!(!PinkNoiseGenerator::new(0).is_finished());
    }
}
