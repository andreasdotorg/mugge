//! Safety limits and hard clip logic.
//!
//! `SafetyLimits` holds the immutable `--max-level-dbfs` cap and provides
//! the per-sample hard clip applied after every generator `generate()` call.
//! This is the last line of defense before samples reach PipeWire -- no
//! code path can bypass it.
//!
//! Defense-in-depth layer 2 (Section 6.2): even if a generator has a bug
//! that produces samples above the requested level, the hard clip prevents
//! them from reaching the output.

/// Immutable safety limits, set once at startup from `--max-level-dbfs`.
///
/// The `max_level_linear` field cannot be changed at runtime -- not via RPC,
/// not via any mechanism. Changing it requires restarting the process with a
/// different CLI flag value.
pub struct SafetyLimits {
    max_level_linear: f32,
}

impl SafetyLimits {
    /// Create safety limits from a dBFS value.
    ///
    /// `max_level_dbfs` must be in [-120.0, -0.5] (validated by `validate_args`
    /// in main.rs before this is called).
    pub fn from_dbfs(max_level_dbfs: f64) -> Self {
        let max_level_linear = 10.0f64.powf(max_level_dbfs / 20.0) as f32;
        Self { max_level_linear }
    }

    /// Create safety limits from a pre-computed linear amplitude value.
    pub fn from_linear(max_level_linear: f32) -> Self {
        Self { max_level_linear }
    }

    /// Return the maximum linear amplitude.
    pub fn max_level_linear(&self) -> f32 {
        self.max_level_linear
    }

    /// Apply hard clip to every sample in the buffer.
    ///
    /// This is called after the generator's `generate()` and after the fade
    /// ramp -- it is the absolute last step before samples enter PipeWire.
    /// Matches the process callback structure in Section 5.4, step 5:
    ///
    /// ```text
    /// for sample in output.iter_mut() {
    ///     *sample = sample.clamp(-max_linear, max_linear);
    /// }
    /// ```
    #[inline]
    pub fn hard_clip(&self, buffer: &mut [f32]) {
        let limit = self.max_level_linear;
        for sample in buffer.iter_mut() {
            *sample = sample.clamp(-limit, limit);
        }
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn from_dbfs_minus_20() {
        let limits = SafetyLimits::from_dbfs(-20.0);
        // -20 dBFS = 10^(-20/20) = 0.1
        let expected = 0.1f32;
        assert!(
            (limits.max_level_linear() - expected).abs() < 1e-6,
            "Expected {}, got {}",
            expected,
            limits.max_level_linear()
        );
    }

    #[test]
    fn from_dbfs_minus_0_5() {
        let limits = SafetyLimits::from_dbfs(-0.5);
        // -0.5 dBFS = 10^(-0.5/20) ~ 0.9441
        let expected = 10.0f64.powf(-0.5 / 20.0) as f32;
        assert!(
            (limits.max_level_linear() - expected).abs() < 1e-5,
            "Expected {}, got {}",
            expected,
            limits.max_level_linear()
        );
    }

    #[test]
    fn from_dbfs_minus_120() {
        let limits = SafetyLimits::from_dbfs(-120.0);
        // -120 dBFS = 10^(-120/20) = 1e-6
        let expected = 1e-6f32;
        assert!(
            (limits.max_level_linear() - expected).abs() < 1e-10,
            "Expected {}, got {}",
            expected,
            limits.max_level_linear()
        );
    }

    #[test]
    fn from_linear() {
        let limits = SafetyLimits::from_linear(0.5);
        assert!((limits.max_level_linear() - 0.5).abs() < 1e-7);
    }

    #[test]
    fn hard_clip_clamps_above_limit() {
        let limits = SafetyLimits::from_linear(0.5);
        let mut buffer = [0.0, 0.3, 0.5, 0.6, 0.9, 1.0];
        limits.hard_clip(&mut buffer);
        assert_eq!(buffer, [0.0, 0.3, 0.5, 0.5, 0.5, 0.5]);
    }

    #[test]
    fn hard_clip_clamps_below_negative_limit() {
        let limits = SafetyLimits::from_linear(0.5);
        let mut buffer = [0.0, -0.3, -0.5, -0.6, -0.9, -1.0];
        limits.hard_clip(&mut buffer);
        assert_eq!(buffer, [0.0, -0.3, -0.5, -0.5, -0.5, -0.5]);
    }

    #[test]
    fn hard_clip_passes_through_within_limit() {
        let limits = SafetyLimits::from_linear(0.5);
        let mut buffer = [0.0, 0.1, -0.1, 0.49, -0.49, 0.5, -0.5];
        let expected = [0.0, 0.1, -0.1, 0.49, -0.49, 0.5, -0.5];
        limits.hard_clip(&mut buffer);
        assert_eq!(buffer, expected);
    }

    #[test]
    fn hard_clip_at_exact_boundary() {
        // Samples exactly at the limit should pass through unchanged.
        let limits = SafetyLimits::from_linear(0.1);
        let mut buffer = [0.1, -0.1];
        limits.hard_clip(&mut buffer);
        assert_eq!(buffer, [0.1, -0.1]);
    }

    #[test]
    fn hard_clip_one_sample_above_boundary() {
        // One ULP above the limit in f32.
        let limit = 0.1f32;
        let limits = SafetyLimits::from_linear(limit);
        let above = f32::from_bits(limit.to_bits() + 1); // next representable f32
        let mut buffer = [above, -above];
        limits.hard_clip(&mut buffer);
        assert_eq!(buffer[0], limit, "Positive sample should be clamped to limit");
        assert_eq!(buffer[1], -limit, "Negative sample should be clamped to -limit");
    }

    #[test]
    fn hard_clip_empty_buffer() {
        let limits = SafetyLimits::from_linear(0.5);
        let mut buffer: [f32; 0] = [];
        limits.hard_clip(&mut buffer); // should not panic
    }

    #[test]
    fn hard_clip_preserves_zero() {
        let limits = SafetyLimits::from_linear(0.001);
        let mut buffer = [0.0f32; 10];
        limits.hard_clip(&mut buffer);
        assert!(buffer.iter().all(|&s| s == 0.0));
    }
}
