//! Lock-free SPSC ring buffer for interleaved float32 PCM.
//!
//! Single producer (PipeWire process callback) writes interleaved frames.
//! Multiple consumers (socket clients) each maintain their own read position.
//!
//! If the writer laps a reader, the reader detects the gap and skips ahead
//! (drop-oldest semantics). The writer never blocks.
//!
//! ## Clock metadata
//!
//! Each write is accompanied by a `ChunkMeta` entry in a parallel metadata
//! ring. Consumers can read `(graph_position, graph_nsec, n_frames)` for
//! each chunk to correlate PCM data with PipeWire graph clock timestamps.

use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use crate::level_tracker::GraphClock;

/// Metadata for one write chunk in the ring buffer.
#[derive(Debug, Clone, Copy, Default)]
pub struct ChunkMeta {
    /// PipeWire graph clock frame position at this chunk.
    pub graph_position: u64,
    /// PipeWire graph clock nanoseconds at this chunk.
    pub graph_nsec: u64,
    /// Number of frames in this chunk.
    pub n_frames: u32,
}

/// Metadata slot stored atomically in the metadata ring.
/// Each slot holds position, nsec, and n_frames as separate atomics
/// so the RT writer can stamp them without locks.
struct MetaSlot {
    graph_position: AtomicU64,
    graph_nsec: AtomicU64,
    n_frames: AtomicU64, // stored as u64 for alignment; only lower 32 bits used
}

impl MetaSlot {
    fn new() -> Self {
        Self {
            graph_position: AtomicU64::new(0),
            graph_nsec: AtomicU64::new(0),
            n_frames: AtomicU64::new(0),
        }
    }

    fn store(&self, meta: &ChunkMeta) {
        self.graph_position.store(meta.graph_position, Ordering::Relaxed);
        self.graph_nsec.store(meta.graph_nsec, Ordering::Relaxed);
        self.n_frames.store(meta.n_frames as u64, Ordering::Relaxed);
    }

    fn load(&self) -> ChunkMeta {
        ChunkMeta {
            graph_position: self.graph_position.load(Ordering::Relaxed),
            graph_nsec: self.graph_nsec.load(Ordering::Relaxed),
            n_frames: self.n_frames.load(Ordering::Relaxed) as u32,
        }
    }
}

/// Lock-free ring buffer for interleaved float32 PCM audio.
///
/// The buffer stores `capacity * channels` floats. `write_pos` is a
/// monotonically increasing frame counter (not wrapped). Readers compute
/// their index into the buffer using `pos % capacity`.
pub struct RingBuffer {
    /// Flat storage: capacity * channels floats, interleaved.
    data: Box<[f32]>,
    /// Number of frames (not samples) the buffer can hold. Must be power of 2.
    capacity: usize,
    /// Number of interleaved channels.
    channels: usize,
    /// Monotonically increasing write position in frames.
    /// Readers see this via Acquire ordering.
    write_pos: AtomicUsize,
    /// Parallel metadata ring — one slot per frame-capacity entry.
    /// Indexed by `meta_write_count % meta_capacity`. Each write()
    /// call stamps one slot.
    meta: Box<[MetaSlot]>,
    /// Number of metadata slots (= capacity, power of 2).
    meta_capacity: usize,
    /// Monotonically increasing metadata write counter.
    meta_write_pos: AtomicUsize,
}

// Safety: the ring buffer is designed for SPSC use. The writer (PW callback)
// is the only thread that modifies `data`. Readers only read `data` at
// positions behind `write_pos`. The AtomicUsize provides the necessary
// synchronization between the writer and readers.
unsafe impl Sync for RingBuffer {}
unsafe impl Send for RingBuffer {}

impl RingBuffer {
    /// Create a new ring buffer. `capacity` is rounded up to the next power of 2.
    pub fn new(capacity: usize, channels: usize) -> Self {
        let capacity = capacity.next_power_of_two();
        let meta: Vec<MetaSlot> = (0..capacity).map(|_| MetaSlot::new()).collect();
        Self {
            data: vec![0.0f32; capacity * channels].into_boxed_slice(),
            capacity,
            channels,
            write_pos: AtomicUsize::new(0),
            meta: meta.into_boxed_slice(),
            meta_capacity: capacity,
            meta_write_pos: AtomicUsize::new(0),
        }
    }

    /// Write interleaved float32 frames into the ring buffer.
    ///
    /// Called from the PipeWire process callback (single writer).
    /// `samples` contains `n_frames * channels` interleaved floats.
    /// `clock` carries the PipeWire graph clock for this chunk.
    pub fn write_interleaved(&self, samples: &[f32], channels: usize, clock: GraphClock) {
        debug_assert_eq!(channels, self.channels);
        let n_frames = samples.len() / channels;
        if n_frames == 0 {
            return;
        }
        assert!(
            n_frames <= self.capacity,
            "write_interleaved: n_frames ({}) exceeds capacity ({})",
            n_frames, self.capacity,
        );

        let wp = self.write_pos.load(Ordering::Relaxed);
        let mask = self.capacity - 1; // capacity is power-of-2

        // Copy samples into the ring buffer, wrapping around if needed.
        let start_idx = (wp & mask) * channels;
        let total_samples = n_frames * channels;
        let ring_len = self.capacity * channels;

        // Safety: we are the single writer. No other thread writes to `data`.
        // Readers only access positions behind our write_pos (after the
        // Release store below), so there's no data race on the actual
        // float values.
        let data_ptr = self.data.as_ptr() as *mut f32;

        if start_idx + total_samples <= ring_len {
            // No wraparound needed.
            unsafe {
                std::ptr::copy_nonoverlapping(
                    samples.as_ptr(),
                    data_ptr.add(start_idx),
                    total_samples,
                );
            }
        } else {
            // Wraparound: copy in two parts.
            let first_samples = ring_len - start_idx;
            unsafe {
                std::ptr::copy_nonoverlapping(
                    samples.as_ptr(),
                    data_ptr.add(start_idx),
                    first_samples,
                );
                std::ptr::copy_nonoverlapping(
                    samples.as_ptr().add(first_samples),
                    data_ptr,
                    total_samples - first_samples,
                );
            }
        }

        // Stamp metadata for this chunk.
        let mwp = self.meta_write_pos.load(Ordering::Relaxed);
        let meta_idx = mwp & (self.meta_capacity - 1);
        self.meta[meta_idx].store(&ChunkMeta {
            graph_position: clock.position,
            graph_nsec: clock.nsec,
            n_frames: n_frames as u32,
        });
        self.meta_write_pos.store(mwp + 1, Ordering::Release);

        // Publish the new write position. Release ordering ensures the
        // data writes above are visible to readers before they see the
        // updated write_pos.
        self.write_pos.store(wp + n_frames, Ordering::Release);
    }

    /// Get the current write position (frame count since start).
    pub fn write_pos(&self) -> usize {
        self.write_pos.load(Ordering::Acquire)
    }

    /// Read `n_frames` of interleaved data starting from `read_pos`.
    ///
    /// Returns `Some(data)` if the requested frames are still in the buffer,
    /// or `None` if the writer has lapped us (caller should skip ahead).
    ///
    /// `read_pos` is the caller's frame counter (not wrapped).
    pub fn read_interleaved(&self, read_pos: usize, n_frames: usize) -> Option<Vec<f32>> {
        let wp = self.write_pos.load(Ordering::Acquire);

        // Check if the data we want is still in the buffer.
        if wp < read_pos + n_frames {
            // Not enough data written yet.
            return None;
        }
        if wp > read_pos + self.capacity {
            // Writer lapped us — data at read_pos has been overwritten.
            return None;
        }

        let mask = self.capacity - 1;
        let channels = self.channels;
        let total_samples = n_frames * channels;
        let ring_len = self.capacity * channels;
        let start_idx = (read_pos & mask) * channels;

        let mut out = vec![0.0f32; total_samples];

        if start_idx + total_samples <= ring_len {
            out.copy_from_slice(&self.data[start_idx..start_idx + total_samples]);
        } else {
            let first_samples = ring_len - start_idx;
            out[..first_samples].copy_from_slice(&self.data[start_idx..ring_len]);
            out[first_samples..].copy_from_slice(&self.data[..total_samples - first_samples]);
        }

        Some(out)
    }

    /// Read the most recent metadata entry. Returns `None` if no writes
    /// have occurred yet.
    pub fn latest_meta(&self) -> Option<ChunkMeta> {
        let mwp = self.meta_write_pos.load(Ordering::Acquire);
        if mwp == 0 {
            return None;
        }
        let idx = (mwp - 1) & (self.meta_capacity - 1);
        Some(self.meta[idx].load())
    }

    /// Ring buffer capacity in frames.
    pub fn capacity(&self) -> usize {
        self.capacity
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn no_clock() -> GraphClock {
        GraphClock::default()
    }

    #[test]
    fn write_and_read_basic() {
        let ring = RingBuffer::new(16, 2);
        assert_eq!(ring.capacity(), 16);

        // Write 4 frames of stereo data.
        let data: Vec<f32> = (0..8).map(|i| i as f32).collect();
        ring.write_interleaved(&data, 2, no_clock());
        assert_eq!(ring.write_pos(), 4);

        // Read back.
        let out = ring.read_interleaved(0, 4).unwrap();
        assert_eq!(out, data);
    }

    #[test]
    fn write_wraparound() {
        let ring = RingBuffer::new(8, 1); // 8 frames, mono

        // Write 6 frames.
        let data1: Vec<f32> = (0..6).map(|i| i as f32).collect();
        ring.write_interleaved(&data1, 1, no_clock());

        // Write 4 more frames (wraps around: 6+4=10, capacity=8).
        let data2: Vec<f32> = (10..14).map(|i| i as f32).collect();
        ring.write_interleaved(&data2, 1, no_clock());

        // Read the last 4 frames (positions 6..10).
        let out = ring.read_interleaved(6, 4).unwrap();
        assert_eq!(out, vec![10.0, 11.0, 12.0, 13.0]);
    }

    #[test]
    fn reader_lapped() {
        let ring = RingBuffer::new(4, 1);

        // Write 4 frames.
        ring.write_interleaved(&[1.0, 2.0, 3.0, 4.0], 1, no_clock());
        // Write 4 more (overwrites the first 4).
        ring.write_interleaved(&[5.0, 6.0, 7.0, 8.0], 1, no_clock());

        // Try to read from position 0 — lapped, should return None.
        assert!(ring.read_interleaved(0, 4).is_none());

        // Read from position 4 should work.
        let out = ring.read_interleaved(4, 4).unwrap();
        assert_eq!(out, vec![5.0, 6.0, 7.0, 8.0]);
    }

    #[test]
    fn not_enough_data() {
        let ring = RingBuffer::new(8, 2);
        ring.write_interleaved(&[1.0, 2.0, 3.0, 4.0], 2, no_clock()); // 2 frames

        // Try to read 4 frames — not enough data yet.
        assert!(ring.read_interleaved(0, 4).is_none());

        // Read 2 frames should work.
        let out = ring.read_interleaved(0, 2).unwrap();
        assert_eq!(out, vec![1.0, 2.0, 3.0, 4.0]);
    }

    // -- Metadata tests --

    #[test]
    fn meta_none_before_write() {
        let ring = RingBuffer::new(8, 1);
        assert!(ring.latest_meta().is_none());
    }

    #[test]
    fn meta_captured_on_write() {
        // Capacity must be >= n_frames written in a single call.
        // Previous capacity of 8 with 256 samples caused a heap overflow (F-116).
        let ring = RingBuffer::new(256, 1);
        let clk = GraphClock { position: 1024, nsec: 21_333_333 };
        ring.write_interleaved(&[0.5; 256], 1, clk);

        let meta = ring.latest_meta().unwrap();
        assert_eq!(meta.graph_position, 1024);
        assert_eq!(meta.graph_nsec, 21_333_333);
        assert_eq!(meta.n_frames, 256);
    }

    #[test]
    fn meta_latest_wins() {
        let ring = RingBuffer::new(8, 1);
        ring.write_interleaved(&[0.5; 4], 1, GraphClock { position: 100, nsec: 1000 });
        ring.write_interleaved(&[0.5; 4], 1, GraphClock { position: 200, nsec: 2000 });

        let meta = ring.latest_meta().unwrap();
        assert_eq!(meta.graph_position, 200);
        assert_eq!(meta.graph_nsec, 2000);
    }

    #[test]
    fn meta_n_frames_correct() {
        let ring = RingBuffer::new(1024, 2);
        ring.write_interleaved(&[0.0; 512], 2, no_clock()); // 256 frames

        let meta = ring.latest_meta().unwrap();
        assert_eq!(meta.n_frames, 256);
    }
}
