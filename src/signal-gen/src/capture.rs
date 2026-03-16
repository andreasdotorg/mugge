//! Capture ring buffer and recording state machine.
//!
//! The PipeWire capture callback writes UMIK-1 input samples into a
//! lock-free ring buffer. The RPC thread reads recorded data on demand
//! (for `playrec` and `capture_level` commands).
//!
//! Section 5.3 of D-037 specifies the capture ring buffer design:
//! - 30-second circular buffer at 48kHz mono = 1,440,000 samples (~5.5 MB)
//! - Lock-free: RT callback writes, RPC thread reads
//! - Single-session buffer (AE-SF-NEW-2): each playrec overwrites previous
//! - Live metering (peak/RMS) computed from every quantum regardless of
//!   recording state

use std::sync::atomic::{AtomicBool, AtomicU32, AtomicUsize, Ordering};
use std::cell::UnsafeCell;

// ---------------------------------------------------------------------------
// Recording state machine
// ---------------------------------------------------------------------------

/// Recording state: Idle -> Recording -> Complete.
///
/// Transitions:
/// - Idle -> Recording: on StartCapture or Playrec command
/// - Recording -> Complete: on StopCapture command or playrec tail timeout
/// - Complete -> Idle: on next StartCapture/Playrec (resets buffer)
/// - Recording -> Idle: on Stop command (discard partial recording)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecordingState {
    /// Not recording. Capture stream still runs (for metering) but samples
    /// are discarded.
    Idle,
    /// Actively recording into the ring buffer.
    Recording,
    /// Recording complete. Buffer is frozen and available for get_recording.
    Complete,
}

// ---------------------------------------------------------------------------
// Capture ring buffer
// ---------------------------------------------------------------------------

/// Lock-free capture ring buffer for UMIK-1 audio samples.
///
/// Design (D-037 Section 5.3):
/// - Fixed-size f32 buffer for mono capture (UMIK-1 is single channel)
/// - RT callback writes via `write_samples()` (no allocation, no blocking)
/// - RPC thread reads frozen buffer via `read_recording()`
/// - Live peak/RMS metering from every quantum via `update_levels()`
///
/// Thread safety model:
/// - The RT callback is the sole writer of `buffer`, `write_pos`, `frames_written`,
///   `recording_state`, `peak`, `rms_sum`, and `rms_count`.
/// - The RPC thread is the sole reader of the frozen buffer (only when
///   state == Complete) and of `peak`/`rms_sum`/`rms_count`.
/// - AtomicBool/AtomicUsize/AtomicU32 ensure cross-thread visibility.
pub struct CaptureRingBuffer {
    /// Sample storage. Only written by the RT callback.
    buffer: UnsafeCell<Vec<f32>>,
    /// Total capacity in samples.
    capacity: usize,
    /// Current write position (wraps around). Written by RT only.
    write_pos: AtomicUsize,
    /// Number of frames written in the current recording session.
    /// Capped at `capacity` (the buffer is circular).
    frames_written: AtomicUsize,
    /// Current recording state. Written by RT only.
    recording: AtomicBool,
    /// True when a complete recording is available for reading.
    complete: AtomicBool,
    /// Live peak level (linear) from the most recent quantum.
    /// Stored as u32 bits for atomic access (f32::to_bits / from_bits).
    peak_bits: AtomicU32,
    /// Accumulator for RMS computation: sum of squares over the last quantum.
    /// Stored as u32 bits.
    rms_bits: AtomicU32,
    /// Sample rate (for metadata in get_recording response).
    sample_rate: u32,
}

// Safety: CaptureRingBuffer follows SPSC discipline.
// - RT callback is the sole producer (writes buffer, write_pos, frames_written,
//   recording, peak_bits, rms_bits)
// - RPC thread is the sole consumer (reads buffer only when complete==true,
//   reads peak_bits/rms_bits for metering)
// AtomicBool/AtomicUsize/AtomicU32 with Acquire/Release ordering ensures
// proper happens-before relationships.
unsafe impl Send for CaptureRingBuffer {}
unsafe impl Sync for CaptureRingBuffer {}

impl CaptureRingBuffer {
    /// Create a new capture ring buffer.
    ///
    /// `duration_secs` is the buffer length in seconds (default 30).
    /// `sample_rate` is the capture sample rate in Hz (default 48000).
    pub fn new(duration_secs: u32, sample_rate: u32) -> Self {
        let capacity = (duration_secs as usize) * (sample_rate as usize);
        Self {
            buffer: UnsafeCell::new(vec![0.0f32; capacity]),
            capacity,
            write_pos: AtomicUsize::new(0),
            frames_written: AtomicUsize::new(0),
            recording: AtomicBool::new(false),
            complete: AtomicBool::new(false),
            peak_bits: AtomicU32::new(0.0f32.to_bits()),
            rms_bits: AtomicU32::new(0.0f32.to_bits()),
            sample_rate,
        }
    }

    /// Start recording. Resets write position and frame count.
    ///
    /// Called from the RT callback when a StartCapture or Playrec command
    /// is processed. Any previous recording is overwritten.
    pub fn start_recording(&self) {
        self.write_pos.store(0, Ordering::Relaxed);
        self.frames_written.store(0, Ordering::Relaxed);
        self.complete.store(false, Ordering::Release);
        self.recording.store(true, Ordering::Release);
    }

    /// Stop recording. Freezes the buffer for reading.
    ///
    /// Called from the RT callback when a StopCapture command is processed
    /// or when playrec tail expires.
    pub fn stop_recording(&self) {
        self.recording.store(false, Ordering::Release);
        // Only mark complete if we actually recorded something.
        if self.frames_written.load(Ordering::Relaxed) > 0 {
            self.complete.store(true, Ordering::Release);
        }
    }

    /// Discard a partial recording (e.g., on Stop during recording).
    pub fn discard_recording(&self) {
        self.recording.store(false, Ordering::Release);
        // Do NOT set complete -- partial recording is not retrievable.
    }

    /// Returns true if currently recording.
    pub fn is_recording(&self) -> bool {
        self.recording.load(Ordering::Acquire)
    }

    /// Returns true if a complete recording is available.
    pub fn is_complete(&self) -> bool {
        self.complete.load(Ordering::Acquire)
    }

    /// Returns the current recording state.
    pub fn state(&self) -> RecordingState {
        if self.recording.load(Ordering::Acquire) {
            RecordingState::Recording
        } else if self.complete.load(Ordering::Acquire) {
            RecordingState::Complete
        } else {
            RecordingState::Idle
        }
    }

    /// Write samples from the capture PW callback into the ring buffer.
    ///
    /// Only writes if recording is active. Wraps around at capacity.
    /// Called from the RT thread only -- no allocation, no blocking.
    pub fn write_samples(&self, samples: &[f32]) {
        if !self.recording.load(Ordering::Relaxed) {
            return;
        }

        let pos = self.write_pos.load(Ordering::Relaxed);
        // Safety: only the RT thread writes to the buffer while recording.
        let buf = unsafe { &mut *self.buffer.get() };

        for (i, &sample) in samples.iter().enumerate() {
            let idx = (pos + i) % self.capacity;
            buf[idx] = sample;
        }

        let new_pos = (pos + samples.len()) % self.capacity;
        self.write_pos.store(new_pos, Ordering::Release);

        let written = self.frames_written.load(Ordering::Relaxed) + samples.len();
        // Cap at capacity to indicate the buffer is full but valid.
        self.frames_written.store(written.min(self.capacity), Ordering::Release);
    }

    /// Update live metering levels from incoming capture samples.
    ///
    /// Called every quantum regardless of recording state. Computes peak
    /// and RMS from the provided samples and stores them atomically for
    /// the RPC thread to read via `capture_level`.
    pub fn update_levels(&self, samples: &[f32]) {
        if samples.is_empty() {
            return;
        }

        let mut peak: f32 = 0.0;
        let mut sum_sq: f32 = 0.0;

        for &s in samples {
            let abs = s.abs();
            if abs > peak {
                peak = abs;
            }
            sum_sq += s * s;
        }

        let rms = (sum_sq / samples.len() as f32).sqrt();

        self.peak_bits.store(peak.to_bits(), Ordering::Release);
        self.rms_bits.store(rms.to_bits(), Ordering::Release);
    }

    /// Read the current peak level (linear). Thread-safe snapshot.
    pub fn peak(&self) -> f32 {
        f32::from_bits(self.peak_bits.load(Ordering::Acquire))
    }

    /// Read the current RMS level (linear). Thread-safe snapshot.
    pub fn rms(&self) -> f32 {
        f32::from_bits(self.rms_bits.load(Ordering::Acquire))
    }

    /// Read the frozen recording buffer.
    ///
    /// Returns `None` if no complete recording is available.
    /// Returns `Some((samples, sample_rate))` with the recorded audio.
    ///
    /// The returned samples are in chronological order (oldest first).
    /// If the buffer wrapped, the samples are reordered to be contiguous.
    ///
    /// Called from the RPC thread only -- must only be called when
    /// `is_complete()` returns true.
    pub fn read_recording(&self) -> Option<(Vec<f32>, u32)> {
        if !self.complete.load(Ordering::Acquire) {
            return None;
        }

        let frames_written = self.frames_written.load(Ordering::Acquire);
        if frames_written == 0 {
            return None;
        }

        let write_pos = self.write_pos.load(Ordering::Acquire);
        // Safety: we only read while complete==true, which means the RT
        // thread is not writing. The RPC thread is the sole reader.
        let buf = unsafe { &*self.buffer.get() };

        let n_samples = frames_written.min(self.capacity);
        let mut result = Vec::with_capacity(n_samples);

        if frames_written < self.capacity {
            // No wraparound: samples are at [0..frames_written).
            result.extend_from_slice(&buf[..n_samples]);
        } else {
            // Wrapped: oldest samples start at write_pos, newest end at write_pos-1.
            // Reorder to chronological: [write_pos..capacity] then [0..write_pos].
            result.extend_from_slice(&buf[write_pos..self.capacity]);
            result.extend_from_slice(&buf[..write_pos]);
        }

        Some((result, self.sample_rate))
    }

    /// Consume the recording (read it and reset to idle).
    ///
    /// After calling this, `is_complete()` returns false until the next
    /// recording session completes.
    pub fn take_recording(&self) -> Option<(Vec<f32>, u32)> {
        let result = self.read_recording();
        if result.is_some() {
            self.complete.store(false, Ordering::Release);
        }
        result
    }

    /// Number of frames written in the current/last recording session.
    pub fn frames_written(&self) -> usize {
        self.frames_written.load(Ordering::Acquire)
    }

    /// Buffer capacity in samples.
    pub fn capacity(&self) -> usize {
        self.capacity
    }

    /// Sample rate.
    pub fn sample_rate(&self) -> u32 {
        self.sample_rate
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    const RATE: u32 = 48000;

    fn make_buffer(secs: u32) -> CaptureRingBuffer {
        CaptureRingBuffer::new(secs, RATE)
    }

    // -----------------------------------------------------------------------
    // Recording state machine
    // -----------------------------------------------------------------------

    #[test]
    fn initial_state_is_idle() {
        let buf = make_buffer(1);
        assert_eq!(buf.state(), RecordingState::Idle);
        assert!(!buf.is_recording());
        assert!(!buf.is_complete());
    }

    #[test]
    fn start_recording_transitions_to_recording() {
        let buf = make_buffer(1);
        buf.start_recording();
        assert_eq!(buf.state(), RecordingState::Recording);
        assert!(buf.is_recording());
        assert!(!buf.is_complete());
    }

    #[test]
    fn stop_recording_transitions_to_complete() {
        let buf = make_buffer(1);
        buf.start_recording();
        // Write some samples so the recording is non-empty.
        buf.write_samples(&[0.1, 0.2, 0.3]);
        buf.stop_recording();
        assert_eq!(buf.state(), RecordingState::Complete);
        assert!(!buf.is_recording());
        assert!(buf.is_complete());
    }

    #[test]
    fn stop_empty_recording_stays_idle() {
        let buf = make_buffer(1);
        buf.start_recording();
        // Don't write any samples.
        buf.stop_recording();
        // No samples written -> should not be marked complete.
        assert_eq!(buf.state(), RecordingState::Idle);
    }

    #[test]
    fn discard_recording_returns_to_idle() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.write_samples(&[0.1, 0.2]);
        buf.discard_recording();
        assert_eq!(buf.state(), RecordingState::Idle);
        assert!(!buf.is_recording());
        assert!(!buf.is_complete());
    }

    #[test]
    fn start_after_complete_resets_to_recording() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.write_samples(&[0.5]);
        buf.stop_recording();
        assert_eq!(buf.state(), RecordingState::Complete);

        // Start a new recording.
        buf.start_recording();
        assert_eq!(buf.state(), RecordingState::Recording);
        assert_eq!(buf.frames_written(), 0);
    }

    // -----------------------------------------------------------------------
    // Write and read back
    // -----------------------------------------------------------------------

    #[test]
    fn write_and_read_back_correct_samples() {
        let buf = make_buffer(1);
        let samples = [0.1f32, 0.2, 0.3, 0.4, 0.5];

        buf.start_recording();
        buf.write_samples(&samples);
        buf.stop_recording();

        let (data, rate) = buf.read_recording().unwrap();
        assert_eq!(rate, RATE);
        assert_eq!(data.len(), 5);
        for (i, &expected) in samples.iter().enumerate() {
            assert!(
                (data[i] - expected).abs() < 1e-7,
                "sample {}: expected {}, got {}",
                i,
                expected,
                data[i]
            );
        }
    }

    #[test]
    fn write_multiple_chunks() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.write_samples(&[0.1, 0.2, 0.3]);
        buf.write_samples(&[0.4, 0.5]);
        buf.stop_recording();

        let (data, _) = buf.read_recording().unwrap();
        assert_eq!(data.len(), 5);
        let expected = [0.1f32, 0.2, 0.3, 0.4, 0.5];
        for (i, &e) in expected.iter().enumerate() {
            assert!((data[i] - e).abs() < 1e-7);
        }
    }

    #[test]
    fn read_returns_none_when_idle() {
        let buf = make_buffer(1);
        assert!(buf.read_recording().is_none());
    }

    #[test]
    fn read_returns_none_while_recording() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.write_samples(&[0.1]);
        // Still recording -- not complete.
        assert!(buf.read_recording().is_none());
    }

    // -----------------------------------------------------------------------
    // Ring buffer wraparound
    // -----------------------------------------------------------------------

    #[test]
    fn wraparound_produces_chronological_output() {
        // Tiny buffer: 10 samples capacity (at rate=10, 1 second).
        let buf = CaptureRingBuffer::new(1, 10);
        assert_eq!(buf.capacity(), 10);

        buf.start_recording();
        // Write 15 samples into a 10-sample buffer -> wraps around.
        let samples: Vec<f32> = (0..15).map(|i| i as f32 * 0.1).collect();
        buf.write_samples(&samples);
        buf.stop_recording();

        let (data, _) = buf.read_recording().unwrap();
        // Should contain the last 10 samples in chronological order.
        assert_eq!(data.len(), 10);
        let expected: Vec<f32> = (5..15).map(|i| i as f32 * 0.1).collect();
        for (i, &e) in expected.iter().enumerate() {
            assert!(
                (data[i] - e).abs() < 1e-6,
                "sample {}: expected {:.1}, got {:.1}",
                i,
                e,
                data[i]
            );
        }
    }

    #[test]
    fn frames_written_capped_at_capacity() {
        let buf = CaptureRingBuffer::new(1, 10);
        buf.start_recording();
        let samples: Vec<f32> = (0..15).map(|i| i as f32).collect();
        buf.write_samples(&samples);
        // frames_written should be capped at 10.
        assert_eq!(buf.frames_written(), 10);
    }

    // -----------------------------------------------------------------------
    // Samples not written when not recording
    // -----------------------------------------------------------------------

    #[test]
    fn write_discarded_when_not_recording() {
        let buf = make_buffer(1);
        // Don't start recording.
        buf.write_samples(&[0.1, 0.2, 0.3]);
        assert_eq!(buf.frames_written(), 0);
    }

    // -----------------------------------------------------------------------
    // take_recording consumes the recording
    // -----------------------------------------------------------------------

    #[test]
    fn take_recording_consumes() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.write_samples(&[0.5, 0.6]);
        buf.stop_recording();

        let result = buf.take_recording();
        assert!(result.is_some());
        let (data, _) = result.unwrap();
        assert_eq!(data.len(), 2);

        // Second take should return None.
        assert!(buf.take_recording().is_none());
        assert_eq!(buf.state(), RecordingState::Idle);
    }

    // -----------------------------------------------------------------------
    // Peak and RMS computation
    // -----------------------------------------------------------------------

    #[test]
    fn peak_and_rms_from_known_signal() {
        let buf = make_buffer(1);

        // Constant signal at 0.5 amplitude.
        let samples = vec![0.5f32; 100];
        buf.update_levels(&samples);

        assert!((buf.peak() - 0.5).abs() < 1e-6, "peak: {}", buf.peak());
        assert!((buf.rms() - 0.5).abs() < 1e-6, "rms: {}", buf.rms());
    }

    #[test]
    fn peak_and_rms_from_sine_wave() {
        let buf = make_buffer(1);

        // Generate one full cycle of a sine wave at amplitude 0.5.
        let n = 1000;
        let samples: Vec<f32> = (0..n)
            .map(|i| 0.5 * (2.0 * std::f32::consts::PI * i as f32 / n as f32).sin())
            .collect();
        buf.update_levels(&samples);

        // Peak should be ~0.5.
        assert!(
            (buf.peak() - 0.5).abs() < 0.01,
            "peak: {} (expected ~0.5)",
            buf.peak()
        );
        // RMS of a sine wave = amplitude / sqrt(2) = 0.5 / 1.4142 ~= 0.3536.
        let expected_rms = 0.5 / std::f32::consts::SQRT_2;
        assert!(
            (buf.rms() - expected_rms).abs() < 0.01,
            "rms: {} (expected ~{})",
            buf.rms(),
            expected_rms
        );
    }

    #[test]
    fn peak_and_rms_with_negative_samples() {
        let buf = make_buffer(1);
        let samples = [-0.8f32, 0.3, -0.5, 0.1];
        buf.update_levels(&samples);

        assert!(
            (buf.peak() - 0.8).abs() < 1e-6,
            "peak should track absolute value"
        );
    }

    #[test]
    fn peak_and_rms_empty_no_update() {
        let buf = make_buffer(1);
        buf.update_levels(&[]);
        // Initial values should be zero.
        assert_eq!(buf.peak(), 0.0);
        assert_eq!(buf.rms(), 0.0);
    }

    #[test]
    fn levels_update_independently_of_recording() {
        let buf = make_buffer(1);
        // Not recording, but levels should still update.
        assert!(!buf.is_recording());
        buf.update_levels(&[0.7, -0.3]);
        assert!((buf.peak() - 0.7).abs() < 1e-6);
    }

    // -----------------------------------------------------------------------
    // Capacity and metadata
    // -----------------------------------------------------------------------

    #[test]
    fn capacity_matches_duration_times_rate() {
        let buf = CaptureRingBuffer::new(30, 48000);
        assert_eq!(buf.capacity(), 1_440_000);
        assert_eq!(buf.sample_rate(), 48000);
    }

    #[test]
    fn capacity_small_buffer() {
        let buf = CaptureRingBuffer::new(1, 100);
        assert_eq!(buf.capacity(), 100);
    }
}
