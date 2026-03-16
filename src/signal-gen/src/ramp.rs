//! Cosine fade ramp for smooth signal transitions.
//!
//! Applied during play/stop and parameter change transitions to prevent
//! audible clicks. The ramp duration is configurable via `--ramp-ms`
//! (default 20ms = 960 samples at 48kHz).
//!
//! The cosine shape `0.5 * (1 - cos(pi * t))` has zero derivative at both
//! endpoints, producing a perceptually smooth transition with no discontinuity
//! in the signal or its first derivative.
//!
//! Section 4.7 of D-037 specifies the ramp applies to:
//! - Play (silence -> signal): ramp from 0.0 to target level
//! - Stop (signal -> silence): ramp from current level to 0.0
//! - Level change: ramp from old level to new level
//! - Channel change (AE-SF-3): sequential fade (out 20ms, in 20ms)
//! - Signal type change: sequential fade (out 20ms, in 20ms)

/// Cosine fade ramp between two levels.
///
/// Each call to `next()` returns the current gain value and advances
/// the ramp by one sample. When the ramp is complete, `next()` returns
/// `end_level` indefinitely.
///
/// RT-safe: no allocation, no syscalls, no blocking. Only f32 arithmetic.
pub struct FadeRamp {
    samples_remaining: u32,
    total_samples: u32,
    start_level: f32,
    end_level: f32,
}

impl FadeRamp {
    /// Create a new fade ramp.
    ///
    /// - `start_level`: gain at the beginning of the ramp
    /// - `end_level`: gain at the end of the ramp
    /// - `total_samples`: ramp duration in samples (e.g., 960 for 20ms at 48kHz)
    ///
    /// If `total_samples` is 0, the ramp immediately returns `end_level`.
    pub fn new(start_level: f32, end_level: f32, total_samples: u32) -> Self {
        Self {
            samples_remaining: total_samples,
            total_samples,
            start_level,
            end_level,
        }
    }

    /// Create a fade-in ramp (0.0 -> 1.0).
    pub fn fade_in(total_samples: u32) -> Self {
        Self::new(0.0, 1.0, total_samples)
    }

    /// Create a fade-out ramp (1.0 -> 0.0).
    pub fn fade_out(total_samples: u32) -> Self {
        Self::new(1.0, 0.0, total_samples)
    }

    /// Compute the default ramp duration in samples from milliseconds and sample rate.
    pub fn ms_to_samples(ramp_ms: u32, sample_rate: u32) -> u32 {
        (ramp_ms as u64 * sample_rate as u64 / 1000) as u32
    }

    /// Return the next gain value and advance the ramp by one sample.
    ///
    /// When the ramp is complete, returns `end_level` indefinitely.
    /// Matches the design doc Section 4.7 formula exactly.
    #[inline]
    pub fn next(&mut self) -> f32 {
        if self.samples_remaining == 0 {
            return self.end_level;
        }
        self.samples_remaining -= 1;
        let t = 1.0 - (self.samples_remaining as f32 / self.total_samples as f32);
        // Cosine interpolation: smooth at both endpoints (derivative = 0).
        let cos_t = 0.5 * (1.0 - (t * std::f32::consts::PI).cos());
        self.start_level + (self.end_level - self.start_level) * cos_t
    }

    /// Returns true if the ramp has completed (all samples consumed).
    pub fn is_finished(&self) -> bool {
        self.samples_remaining == 0
    }

    /// Returns true if the ramp is still producing interpolated values.
    pub fn is_active(&self) -> bool {
        self.samples_remaining > 0
    }

    /// Return the number of samples remaining in the ramp.
    pub fn samples_remaining(&self) -> u32 {
        self.samples_remaining
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE_RATE: u32 = 48000;
    const RAMP_MS: u32 = 20;

    fn ramp_samples() -> u32 {
        FadeRamp::ms_to_samples(RAMP_MS, SAMPLE_RATE)
    }

    // -----------------------------------------------------------------------
    // Construction helpers
    // -----------------------------------------------------------------------

    #[test]
    fn ms_to_samples_20ms_48khz() {
        assert_eq!(FadeRamp::ms_to_samples(20, 48000), 960);
    }

    #[test]
    fn ms_to_samples_10ms_48khz() {
        assert_eq!(FadeRamp::ms_to_samples(10, 48000), 480);
    }

    #[test]
    fn ms_to_samples_0ms() {
        assert_eq!(FadeRamp::ms_to_samples(0, 48000), 0);
    }

    // -----------------------------------------------------------------------
    // Fade-in: 0.0 -> 1.0
    // -----------------------------------------------------------------------

    #[test]
    fn fade_in_starts_at_zero() {
        let mut ramp = FadeRamp::fade_in(ramp_samples());
        let first = ramp.next();
        // First sample should be very close to 0.0 (cosine starts with
        // derivative = 0, so the first step is tiny).
        assert!(
            first.abs() < 0.01,
            "Fade-in first sample should be ~0.0, got {}",
            first
        );
    }

    #[test]
    fn fade_in_ends_at_one() {
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_in(n);
        let mut last = 0.0f32;
        for _ in 0..n {
            last = ramp.next();
        }
        assert!(
            (last - 1.0).abs() < 1e-5,
            "Fade-in last sample should be ~1.0, got {}",
            last
        );
    }

    #[test]
    fn fade_in_after_completion_returns_end_level() {
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_in(n);
        for _ in 0..n {
            ramp.next();
        }
        // Should return 1.0 indefinitely.
        for _ in 0..100 {
            assert_eq!(ramp.next(), 1.0);
        }
    }

    #[test]
    fn fade_in_monotonically_increasing() {
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_in(n);
        let mut prev = -1.0f32;
        for _ in 0..n {
            let v = ramp.next();
            assert!(
                v >= prev - 1e-7,
                "Fade-in should be monotonically increasing: prev={}, cur={}",
                prev,
                v
            );
            prev = v;
        }
    }

    #[test]
    fn fade_in_smooth_at_start() {
        // The cosine shape has derivative = 0 at t=0.
        // Check: first few samples should change slowly (small differences).
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_in(n);
        let s0 = ramp.next();
        let s1 = ramp.next();
        let s2 = ramp.next();

        let d01 = (s1 - s0).abs();
        let d12 = (s2 - s1).abs();

        // Both differences should be very small (cosine ramp starts gently).
        assert!(
            d01 < 0.001,
            "Start should be smooth: d01={}",
            d01
        );
        assert!(
            d12 < 0.001,
            "Start should be smooth: d12={}",
            d12
        );
    }

    #[test]
    fn fade_in_smooth_at_end() {
        // The cosine shape has derivative = 0 at t=1.
        // Last few samples should change slowly.
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_in(n);
        let mut values = Vec::with_capacity(n as usize);
        for _ in 0..n {
            values.push(ramp.next());
        }
        let len = values.len();
        let d_last = (values[len - 1] - values[len - 2]).abs();
        let d_prev = (values[len - 2] - values[len - 3]).abs();

        assert!(
            d_last < 0.001,
            "End should be smooth: d_last={}",
            d_last
        );
        assert!(
            d_prev < 0.001,
            "End should be smooth: d_prev={}",
            d_prev
        );
    }

    #[test]
    fn fade_in_correct_duration() {
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_in(n);
        assert!(ramp.is_active());
        assert!(!ramp.is_finished());
        assert_eq!(ramp.samples_remaining(), n);

        for i in 0..n {
            ramp.next();
            assert_eq!(ramp.samples_remaining(), n - i - 1);
        }

        assert!(ramp.is_finished());
        assert!(!ramp.is_active());
    }

    // -----------------------------------------------------------------------
    // Fade-out: 1.0 -> 0.0
    // -----------------------------------------------------------------------

    #[test]
    fn fade_out_starts_at_one() {
        let mut ramp = FadeRamp::fade_out(ramp_samples());
        let first = ramp.next();
        assert!(
            (first - 1.0).abs() < 0.01,
            "Fade-out first sample should be ~1.0, got {}",
            first
        );
    }

    #[test]
    fn fade_out_ends_at_zero() {
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_out(n);
        let mut last = 1.0f32;
        for _ in 0..n {
            last = ramp.next();
        }
        assert!(
            last.abs() < 1e-5,
            "Fade-out last sample should be ~0.0, got {}",
            last
        );
    }

    #[test]
    fn fade_out_monotonically_decreasing() {
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_out(n);
        let mut prev = 2.0f32;
        for _ in 0..n {
            let v = ramp.next();
            assert!(
                v <= prev + 1e-7,
                "Fade-out should be monotonically decreasing: prev={}, cur={}",
                prev,
                v
            );
            prev = v;
        }
    }

    #[test]
    fn fade_out_after_completion_returns_zero() {
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_out(n);
        for _ in 0..n {
            ramp.next();
        }
        for _ in 0..100 {
            assert_eq!(ramp.next(), 0.0);
        }
    }

    // -----------------------------------------------------------------------
    // Custom ramp: arbitrary start/end levels
    // -----------------------------------------------------------------------

    #[test]
    fn ramp_custom_levels() {
        // Ramp from 0.3 to 0.7 over 100 samples.
        let mut ramp = FadeRamp::new(0.3, 0.7, 100);
        let first = ramp.next();
        assert!(
            (first - 0.3).abs() < 0.01,
            "Custom ramp should start near 0.3, got {}",
            first
        );

        // Exhaust the ramp.
        let mut last = first;
        for _ in 1..100 {
            last = ramp.next();
        }
        assert!(
            (last - 0.7).abs() < 1e-4,
            "Custom ramp should end near 0.7, got {}",
            last
        );
    }

    #[test]
    fn ramp_midpoint_is_half() {
        // At t=0.5, cosine interpolation gives exactly 0.5 for a [0, 1] ramp.
        // cos(0.5 * pi) = 0, so 0.5 * (1 - 0) = 0.5
        let n = 1000u32; // even number for exact midpoint
        let mut ramp = FadeRamp::fade_in(n);
        let mut mid_value = 0.0f32;
        for i in 0..n {
            let v = ramp.next();
            if i == n / 2 - 1 {
                mid_value = v;
            }
        }
        // At sample n/2, t = 0.5, cos(pi*0.5) = 0, result = 0.5
        assert!(
            (mid_value - 0.5).abs() < 0.01,
            "Midpoint should be ~0.5, got {}",
            mid_value
        );
    }

    // -----------------------------------------------------------------------
    // Edge cases
    // -----------------------------------------------------------------------

    #[test]
    fn zero_length_ramp_returns_end_level() {
        let mut ramp = FadeRamp::new(0.0, 1.0, 0);
        assert!(ramp.is_finished());
        assert_eq!(ramp.next(), 1.0);
        assert_eq!(ramp.next(), 1.0);
    }

    #[test]
    fn single_sample_ramp() {
        let mut ramp = FadeRamp::new(0.0, 1.0, 1);
        assert!(ramp.is_active());
        let v = ramp.next();
        // t = 1.0 for a single sample, so cos(pi) = -1, result = 0.5*(1-(-1)) = 1.0
        assert!(
            (v - 1.0).abs() < 1e-5,
            "Single-sample ramp should jump to end: got {}",
            v
        );
        assert!(ramp.is_finished());
    }

    #[test]
    fn ramp_values_bounded_between_start_and_end() {
        // For fade-in [0, 1], all values should be in [0, 1].
        let n = ramp_samples();
        let mut ramp = FadeRamp::fade_in(n);
        for _ in 0..n {
            let v = ramp.next();
            assert!(
                v >= -1e-7 && v <= 1.0 + 1e-7,
                "Fade-in value {} outside [0, 1]",
                v
            );
        }
    }
}
