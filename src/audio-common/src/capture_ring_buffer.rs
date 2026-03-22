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

/// Lock-free capture ring buffer for UMIK-1 audio samples.
///
/// Design (D-037 Section 5.3):
/// - Fixed-size f32 buffer for mono capture (UMIK-1 is single channel)
/// - RT callback writes via `write_samples()` (no allocation, no blocking)
/// - RPC thread reads frozen buffer via `read_recording()`
/// - Live peak/RMS metering from every quantum via `update_levels()`
pub struct CaptureRingBuffer {
    buffer: UnsafeCell<Vec<f32>>,
    capacity: usize,
    write_pos: AtomicUsize,
    frames_written: AtomicUsize,
    recording: AtomicBool,
    complete: AtomicBool,
    peak_bits: AtomicU32,
    rms_bits: AtomicU32,
    sample_rate: u32,
}

// Safety: CaptureRingBuffer follows SPSC discipline.
unsafe impl Send for CaptureRingBuffer {}
unsafe impl Sync for CaptureRingBuffer {}

impl CaptureRingBuffer {
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

    pub fn start_recording(&self) {
        self.write_pos.store(0, Ordering::Relaxed);
        self.frames_written.store(0, Ordering::Relaxed);
        self.complete.store(false, Ordering::Release);
        self.recording.store(true, Ordering::Release);
    }

    pub fn stop_recording(&self) {
        self.recording.store(false, Ordering::Release);
        if self.frames_written.load(Ordering::Relaxed) > 0 {
            self.complete.store(true, Ordering::Release);
        }
    }

    pub fn discard_recording(&self) {
        self.recording.store(false, Ordering::Release);
    }

    pub fn is_recording(&self) -> bool {
        self.recording.load(Ordering::Acquire)
    }

    pub fn is_complete(&self) -> bool {
        self.complete.load(Ordering::Acquire)
    }

    pub fn state(&self) -> RecordingState {
        if self.recording.load(Ordering::Acquire) {
            RecordingState::Recording
        } else if self.complete.load(Ordering::Acquire) {
            RecordingState::Complete
        } else {
            RecordingState::Idle
        }
    }

    pub fn write_samples(&self, samples: &[f32]) {
        if !self.recording.load(Ordering::Relaxed) {
            return;
        }

        let pos = self.write_pos.load(Ordering::Relaxed);
        let buf = unsafe { &mut *self.buffer.get() };

        for (i, &sample) in samples.iter().enumerate() {
            let idx = (pos + i) % self.capacity;
            buf[idx] = sample;
        }

        let new_pos = (pos + samples.len()) % self.capacity;
        self.write_pos.store(new_pos, Ordering::Release);

        let written = self.frames_written.load(Ordering::Relaxed) + samples.len();
        self.frames_written.store(written.min(self.capacity), Ordering::Release);
    }

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

    pub fn peak(&self) -> f32 {
        f32::from_bits(self.peak_bits.load(Ordering::Acquire))
    }

    pub fn rms(&self) -> f32 {
        f32::from_bits(self.rms_bits.load(Ordering::Acquire))
    }

    pub fn read_recording(&self) -> Option<(Vec<f32>, u32)> {
        if !self.complete.load(Ordering::Acquire) {
            return None;
        }

        let frames_written = self.frames_written.load(Ordering::Acquire);
        if frames_written == 0 {
            return None;
        }

        let write_pos = self.write_pos.load(Ordering::Acquire);
        let buf = unsafe { &*self.buffer.get() };

        let n_samples = frames_written.min(self.capacity);
        let mut result = Vec::with_capacity(n_samples);

        if frames_written < self.capacity {
            result.extend_from_slice(&buf[..n_samples]);
        } else {
            result.extend_from_slice(&buf[write_pos..self.capacity]);
            result.extend_from_slice(&buf[..write_pos]);
        }

        Some((result, self.sample_rate))
    }

    pub fn take_recording(&self) -> Option<(Vec<f32>, u32)> {
        let result = self.read_recording();
        if result.is_some() {
            self.complete.store(false, Ordering::Release);
        }
        result
    }

    pub fn frames_written(&self) -> usize {
        self.frames_written.load(Ordering::Acquire)
    }

    pub fn capacity(&self) -> usize {
        self.capacity
    }

    pub fn sample_rate(&self) -> u32 {
        self.sample_rate
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const RATE: u32 = 48000;

    fn make_buffer(secs: u32) -> CaptureRingBuffer {
        CaptureRingBuffer::new(secs, RATE)
    }

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
    }

    #[test]
    fn stop_recording_transitions_to_complete() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.write_samples(&[0.1, 0.2, 0.3]);
        buf.stop_recording();
        assert_eq!(buf.state(), RecordingState::Complete);
    }

    #[test]
    fn stop_empty_recording_stays_idle() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.stop_recording();
        assert_eq!(buf.state(), RecordingState::Idle);
    }

    #[test]
    fn discard_recording_returns_to_idle() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.write_samples(&[0.1, 0.2]);
        buf.discard_recording();
        assert_eq!(buf.state(), RecordingState::Idle);
    }

    #[test]
    fn start_after_complete_resets_to_recording() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.write_samples(&[0.5]);
        buf.stop_recording();
        assert_eq!(buf.state(), RecordingState::Complete);
        buf.start_recording();
        assert_eq!(buf.state(), RecordingState::Recording);
        assert_eq!(buf.frames_written(), 0);
    }

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
            assert!((data[i] - expected).abs() < 1e-7);
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
        assert!(buf.read_recording().is_none());
    }

    #[test]
    fn wraparound_produces_chronological_output() {
        let buf = CaptureRingBuffer::new(1, 10);
        assert_eq!(buf.capacity(), 10);
        buf.start_recording();
        let samples: Vec<f32> = (0..15).map(|i| i as f32 * 0.1).collect();
        buf.write_samples(&samples);
        buf.stop_recording();
        let (data, _) = buf.read_recording().unwrap();
        assert_eq!(data.len(), 10);
        let expected: Vec<f32> = (5..15).map(|i| i as f32 * 0.1).collect();
        for (i, &e) in expected.iter().enumerate() {
            assert!((data[i] - e).abs() < 1e-6);
        }
    }

    #[test]
    fn frames_written_capped_at_capacity() {
        let buf = CaptureRingBuffer::new(1, 10);
        buf.start_recording();
        let samples: Vec<f32> = (0..15).map(|i| i as f32).collect();
        buf.write_samples(&samples);
        assert_eq!(buf.frames_written(), 10);
    }

    #[test]
    fn write_discarded_when_not_recording() {
        let buf = make_buffer(1);
        buf.write_samples(&[0.1, 0.2, 0.3]);
        assert_eq!(buf.frames_written(), 0);
    }

    #[test]
    fn take_recording_consumes() {
        let buf = make_buffer(1);
        buf.start_recording();
        buf.write_samples(&[0.5, 0.6]);
        buf.stop_recording();
        let result = buf.take_recording();
        assert!(result.is_some());
        assert!(buf.take_recording().is_none());
        assert_eq!(buf.state(), RecordingState::Idle);
    }

    #[test]
    fn peak_and_rms_from_known_signal() {
        let buf = make_buffer(1);
        let samples = vec![0.5f32; 100];
        buf.update_levels(&samples);
        assert!((buf.peak() - 0.5).abs() < 1e-6);
        assert!((buf.rms() - 0.5).abs() < 1e-6);
    }

    #[test]
    fn peak_and_rms_from_sine_wave() {
        let buf = make_buffer(1);
        let n = 1000;
        let samples: Vec<f32> = (0..n)
            .map(|i| 0.5 * (2.0 * std::f32::consts::PI * i as f32 / n as f32).sin())
            .collect();
        buf.update_levels(&samples);
        assert!((buf.peak() - 0.5).abs() < 0.01);
        let expected_rms = 0.5 / std::f32::consts::SQRT_2;
        assert!((buf.rms() - expected_rms).abs() < 0.01);
    }

    #[test]
    fn peak_and_rms_with_negative_samples() {
        let buf = make_buffer(1);
        buf.update_levels(&[-0.8f32, 0.3, -0.5, 0.1]);
        assert!((buf.peak() - 0.8).abs() < 1e-6);
    }

    #[test]
    fn peak_and_rms_empty_no_update() {
        let buf = make_buffer(1);
        buf.update_levels(&[]);
        assert_eq!(buf.peak(), 0.0);
        assert_eq!(buf.rms(), 0.0);
    }

    #[test]
    fn levels_update_independently_of_recording() {
        let buf = make_buffer(1);
        assert!(!buf.is_recording());
        buf.update_levels(&[0.7, -0.3]);
        assert!((buf.peak() - 0.7).abs() < 1e-6);
    }

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
