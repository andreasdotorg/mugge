//! Command and StateSnapshot types, lock-free ring buffers.
//!
//! The RPC thread pushes `Command` values into a lock-free SPSC queue.
//! The PipeWire process callback pops commands each quantum and updates
//! the active generator / parameters. State snapshots flow back from
//! the process callback to the RPC thread for client status responses.
//!
//! All types in this module are `Copy` (no heap allocation) to ensure
//! they are safe for lock-free transfer between threads.
//!
//! The SPSC ring buffer is hand-rolled using `AtomicUsize` for the
//! read/write positions. No external crate dependency, no mutex, O(1)
//! push/pop, no allocation after construction.

use std::cell::UnsafeCell;
use std::sync::atomic::{AtomicUsize, Ordering};

// ---------------------------------------------------------------------------
// Signal types
// ---------------------------------------------------------------------------

/// Signal type selector (matches RPC `signal` field).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SignalType {
    Silence,
    Sine,
    White,
    Pink,
    Sweep,
}

// ---------------------------------------------------------------------------
// Play state
// ---------------------------------------------------------------------------

/// Current playback state of the signal generator.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlayState {
    Stopped,
    Playing,
    Fading,
    Recording,
    PlayrecInProgress,
}

// ---------------------------------------------------------------------------
// Command
// ---------------------------------------------------------------------------

/// A command sent from the RPC thread to the RT process callback.
///
/// Must be `Copy` -- no heap pointers, safe for lock-free SPSC transfer.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Command {
    pub kind: CommandKind,
}

/// Command variants (Section 5.2).
///
/// The process callback drains ALL pending commands per quantum
/// (multi-command-per-quantum semantics, AD-D037-6).
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum CommandKind {
    /// Start playback with the given parameters.
    Play {
        signal: SignalType,
        channels: u8,
        level_dbfs: f32,
        frequency: f32,
        duration_secs: Option<f32>,
        sweep_end_hz: f32,
    },
    /// Start play+record simultaneously.
    Playrec {
        signal: SignalType,
        channels: u8,
        level_dbfs: f32,
        frequency: f32,
        duration_secs: f32,
        sweep_end_hz: f32,
    },
    /// Stop playback (fade out to silence).
    Stop,
    /// Change output level (fade ramp to new level).
    SetLevel { level_dbfs: f32 },
    /// Change active output channels (sequential fade).
    SetChannel { channels: u8 },
    /// Change signal type (sequential fade).
    SetSignal { signal: SignalType, frequency: f32 },
    /// Change frequency (phase-continuous for sine).
    SetFrequency { frequency: f32 },
    /// Begin writing capture samples to the ring buffer.
    StartCapture,
    /// Stop writing capture samples.
    StopCapture,
}

// ---------------------------------------------------------------------------
// StateSnapshot
// ---------------------------------------------------------------------------

/// State snapshot pushed from the RT process callback to the RPC thread.
///
/// At most one snapshot per quantum (~5.3ms at 256 frames). The RPC thread
/// polls at ~50ms and forwards to connected TCP clients.
///
/// Must be `Copy` -- safe for lock-free SPSC transfer.
#[derive(Debug, Clone, Copy)]
pub struct StateSnapshot {
    pub state: PlayState,
    pub signal: SignalType,
    pub channels: u8,
    pub level_dbfs: f32,
    pub frequency: f32,
    pub elapsed_secs: f32,
    pub duration_secs: f32,
    pub capture_peak: f32,
    pub capture_rms: f32,
    pub capture_connected: bool,
    pub samples_generated: u64,
}

impl StateSnapshot {
    /// Create a default "stopped" snapshot.
    pub fn stopped() -> Self {
        Self {
            state: PlayState::Stopped,
            signal: SignalType::Silence,
            channels: 0,
            level_dbfs: -120.0,
            frequency: 0.0,
            elapsed_secs: 0.0,
            duration_secs: 0.0,
            capture_peak: 0.0,
            capture_rms: 0.0,
            capture_connected: false,
            samples_generated: 0,
        }
    }
}

// ---------------------------------------------------------------------------
// Channel bitmask helpers
// ---------------------------------------------------------------------------

/// Encode a list of 1-indexed channel numbers into a bitmask.
///
/// Channel 1 -> bit 0, channel 8 -> bit 7.
/// Out-of-range channels (0 or > 8) are ignored.
pub fn channels_to_bitmask(channels: &[u8]) -> u8 {
    let mut mask = 0u8;
    for &ch in channels {
        if ch >= 1 && ch <= 8 {
            mask |= 1 << (ch - 1);
        }
    }
    mask
}

/// Decode a bitmask into a list of 1-indexed channel numbers.
pub fn bitmask_to_channels(mask: u8) -> Vec<u8> {
    let mut channels = Vec::new();
    for i in 0..8 {
        if mask & (1 << i) != 0 {
            channels.push(i + 1);
        }
    }
    channels
}

// ---------------------------------------------------------------------------
// Lock-free SPSC ring buffer
// ---------------------------------------------------------------------------

/// Lock-free single-producer single-consumer ring buffer.
///
/// - Fixed capacity (power of two for efficient modular indexing).
/// - No allocation in `push()` or `pop()`.
/// - No mutex, no blocking.
/// - Safe for RT: one thread pushes, the other pops.
///
/// Uses `AtomicUsize` for read/write positions with `Acquire`/`Release`
/// ordering to ensure visibility of written data across threads.
pub struct SpscQueue<T: Copy, const N: usize> {
    buffer: [UnsafeCell<T>; N],
    head: AtomicUsize, // next write position (producer)
    tail: AtomicUsize, // next read position (consumer)
}

// Safety: SpscQueue is designed for single-producer single-consumer use.
// The producer only writes `head` and buffer slots; the consumer only
// writes `tail` and reads buffer slots. The AtomicUsize ordering ensures
// proper happens-before relationships.
unsafe impl<T: Copy + Send, const N: usize> Send for SpscQueue<T, N> {}
unsafe impl<T: Copy + Send, const N: usize> Sync for SpscQueue<T, N> {}

impl<T: Copy + Default, const N: usize> SpscQueue<T, N> {
    /// Create a new empty SPSC queue.
    ///
    /// `N` should be a power of two for optimal performance (modular
    /// arithmetic uses bitwise AND instead of division).
    pub fn new() -> Self {
        Self {
            buffer: std::array::from_fn(|_| UnsafeCell::new(T::default())),
            head: AtomicUsize::new(0),
            tail: AtomicUsize::new(0),
        }
    }
}

impl<T: Copy, const N: usize> SpscQueue<T, N> {
    /// Try to push an item. Returns `Err(item)` if the queue is full.
    ///
    /// Only the producer thread should call this.
    pub fn push(&self, item: T) -> Result<(), T> {
        let head = self.head.load(Ordering::Relaxed);
        let tail = self.tail.load(Ordering::Acquire);
        let next_head = (head + 1) % N;

        if next_head == tail {
            return Err(item); // full
        }

        // Safety: only the producer writes to buffer[head], and we have
        // verified that head != tail (so the slot is not being read).
        unsafe {
            *self.buffer[head].get() = item;
        }

        self.head.store(next_head, Ordering::Release);
        Ok(())
    }

    /// Try to pop an item. Returns `None` if the queue is empty.
    ///
    /// Only the consumer thread should call this.
    pub fn pop(&self) -> Option<T> {
        let tail = self.tail.load(Ordering::Relaxed);
        let head = self.head.load(Ordering::Acquire);

        if tail == head {
            return None; // empty
        }

        // Safety: only the consumer reads from buffer[tail], and we have
        // verified that tail != head (so the slot has been written).
        let item = unsafe { *self.buffer[tail].get() };

        self.tail.store((tail + 1) % N, Ordering::Release);
        Some(item)
    }

    /// Check if the queue is empty (snapshot -- may be stale).
    pub fn is_empty(&self) -> bool {
        self.head.load(Ordering::Acquire) == self.tail.load(Ordering::Acquire)
    }

    /// Usable capacity (N - 1, since one slot is reserved to distinguish
    /// full from empty).
    pub const fn capacity(&self) -> usize {
        N - 1
    }
}

/// Command queue capacity. 64 slots per design doc Section 5.2.
/// Using 64 (power of two) for efficient modular arithmetic.
pub const CMD_QUEUE_CAPACITY: usize = 64;

/// State feedback queue capacity. Smaller is fine -- the RPC thread
/// polls at 50ms and only needs the latest snapshot.
pub const STATE_QUEUE_CAPACITY: usize = 16;

/// Type alias for the command queue (RPC -> RT).
pub type CommandQueue = SpscQueue<Command, CMD_QUEUE_CAPACITY>;

/// Type alias for the state feedback queue (RT -> RPC).
pub type StateQueue = SpscQueue<StateSnapshot, STATE_QUEUE_CAPACITY>;

// ---------------------------------------------------------------------------
// Default impls for queue initialization
// ---------------------------------------------------------------------------

impl Default for Command {
    fn default() -> Self {
        Self {
            kind: CommandKind::Stop,
        }
    }
}

impl Default for StateSnapshot {
    fn default() -> Self {
        Self::stopped()
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------------
    // Channel bitmask
    // -----------------------------------------------------------------------

    #[test]
    fn channels_1_3_5_encode_to_bitmask() {
        let mask = channels_to_bitmask(&[1, 3, 5]);
        assert_eq!(mask, 0b0001_0101);
    }

    #[test]
    fn channels_all_eight_encode_to_0xff() {
        let mask = channels_to_bitmask(&[1, 2, 3, 4, 5, 6, 7, 8]);
        assert_eq!(mask, 0xFF);
    }

    #[test]
    fn channels_empty_encodes_to_zero() {
        let mask = channels_to_bitmask(&[]);
        assert_eq!(mask, 0x00);
    }

    #[test]
    fn channels_out_of_range_ignored() {
        let mask = channels_to_bitmask(&[0, 1, 9, 255]);
        // Only channel 1 is valid.
        assert_eq!(mask, 0b0000_0001);
    }

    #[test]
    fn channels_duplicate_idempotent() {
        let mask = channels_to_bitmask(&[1, 1, 1, 3, 3]);
        assert_eq!(mask, 0b0000_0101);
    }

    #[test]
    fn bitmask_roundtrip() {
        let original = [1u8, 3, 5, 7];
        let mask = channels_to_bitmask(&original);
        let decoded = bitmask_to_channels(mask);
        assert_eq!(decoded, vec![1, 3, 5, 7]);
    }

    #[test]
    fn bitmask_to_channels_all() {
        let channels = bitmask_to_channels(0xFF);
        assert_eq!(channels, vec![1, 2, 3, 4, 5, 6, 7, 8]);
    }

    #[test]
    fn bitmask_to_channels_empty() {
        let channels = bitmask_to_channels(0x00);
        assert!(channels.is_empty());
    }

    // -----------------------------------------------------------------------
    // SPSC queue: basic push/pop
    // -----------------------------------------------------------------------

    #[test]
    fn queue_push_and_pop() {
        let q = SpscQueue::<u32, 4>::new();
        assert!(q.is_empty());

        assert!(q.push(42).is_ok());
        assert!(!q.is_empty());

        assert_eq!(q.pop(), Some(42));
        assert!(q.is_empty());
    }

    #[test]
    fn queue_fifo_order() {
        let q = SpscQueue::<u32, 8>::new();
        q.push(1).unwrap();
        q.push(2).unwrap();
        q.push(3).unwrap();

        assert_eq!(q.pop(), Some(1));
        assert_eq!(q.pop(), Some(2));
        assert_eq!(q.pop(), Some(3));
        assert_eq!(q.pop(), None);
    }

    #[test]
    fn queue_empty_pop_returns_none() {
        let q = SpscQueue::<u32, 4>::new();
        assert_eq!(q.pop(), None);
        assert_eq!(q.pop(), None);
    }

    #[test]
    fn queue_full_push_returns_err() {
        // Capacity is N-1 = 3 for a 4-slot queue.
        let q = SpscQueue::<u32, 4>::new();
        assert!(q.push(1).is_ok());
        assert!(q.push(2).is_ok());
        assert!(q.push(3).is_ok());
        // Queue is full (3 items in a 4-slot buffer).
        assert_eq!(q.push(4), Err(4));
    }

    #[test]
    fn queue_capacity() {
        let q = SpscQueue::<u32, 64>::new();
        assert_eq!(q.capacity(), 63);
    }

    #[test]
    fn queue_wrap_around() {
        let q = SpscQueue::<u32, 4>::new();
        // Fill and drain several times to exercise wrap-around.
        for round in 0..5 {
            let base = round * 10;
            q.push(base + 1).unwrap();
            q.push(base + 2).unwrap();
            q.push(base + 3).unwrap();
            assert_eq!(q.pop(), Some(base + 1));
            assert_eq!(q.pop(), Some(base + 2));
            assert_eq!(q.pop(), Some(base + 3));
            assert!(q.is_empty());
        }
    }

    // -----------------------------------------------------------------------
    // Command round-trip through queue
    // -----------------------------------------------------------------------

    #[test]
    fn command_play_round_trip() {
        let q = CommandQueue::new();
        let cmd = Command {
            kind: CommandKind::Play {
                signal: SignalType::Sine,
                channels: channels_to_bitmask(&[1, 2]),
                level_dbfs: -20.0,
                frequency: 1000.0,
                duration_secs: None,
                sweep_end_hz: 0.0,
            },
        };
        q.push(cmd).unwrap();
        let popped = q.pop().unwrap();
        match popped.kind {
            CommandKind::Play {
                signal,
                channels,
                level_dbfs,
                frequency,
                duration_secs,
                ..
            } => {
                assert_eq!(signal, SignalType::Sine);
                assert_eq!(channels, 0b0000_0011);
                assert_eq!(level_dbfs, -20.0);
                assert_eq!(frequency, 1000.0);
                assert!(duration_secs.is_none());
            }
            other => panic!("Expected Play, got {:?}", other),
        }
    }

    #[test]
    fn command_playrec_round_trip() {
        let q = CommandQueue::new();
        let cmd = Command {
            kind: CommandKind::Playrec {
                signal: SignalType::Sweep,
                channels: channels_to_bitmask(&[1]),
                level_dbfs: -20.0,
                frequency: 20.0,
                duration_secs: 5.0,
                sweep_end_hz: 20000.0,
            },
        };
        q.push(cmd).unwrap();
        let popped = q.pop().unwrap();
        match popped.kind {
            CommandKind::Playrec {
                signal,
                duration_secs,
                sweep_end_hz,
                ..
            } => {
                assert_eq!(signal, SignalType::Sweep);
                assert_eq!(duration_secs, 5.0);
                assert_eq!(sweep_end_hz, 20000.0);
            }
            other => panic!("Expected Playrec, got {:?}", other),
        }
    }

    #[test]
    fn command_stop_round_trip() {
        let q = CommandQueue::new();
        q.push(Command { kind: CommandKind::Stop }).unwrap();
        match q.pop().unwrap().kind {
            CommandKind::Stop => {}
            other => panic!("Expected Stop, got {:?}", other),
        }
    }

    #[test]
    fn command_set_level_round_trip() {
        let q = CommandQueue::new();
        q.push(Command {
            kind: CommandKind::SetLevel { level_dbfs: -6.0 },
        })
        .unwrap();
        match q.pop().unwrap().kind {
            CommandKind::SetLevel { level_dbfs } => assert_eq!(level_dbfs, -6.0),
            other => panic!("Expected SetLevel, got {:?}", other),
        }
    }

    #[test]
    fn command_set_channel_round_trip() {
        let q = CommandQueue::new();
        q.push(Command {
            kind: CommandKind::SetChannel {
                channels: channels_to_bitmask(&[3, 4]),
            },
        })
        .unwrap();
        match q.pop().unwrap().kind {
            CommandKind::SetChannel { channels } => {
                assert_eq!(channels, 0b0000_1100);
            }
            other => panic!("Expected SetChannel, got {:?}", other),
        }
    }

    #[test]
    fn command_set_signal_round_trip() {
        let q = CommandQueue::new();
        q.push(Command {
            kind: CommandKind::SetSignal {
                signal: SignalType::Pink,
                frequency: 0.0,
            },
        })
        .unwrap();
        match q.pop().unwrap().kind {
            CommandKind::SetSignal { signal, .. } => {
                assert_eq!(signal, SignalType::Pink);
            }
            other => panic!("Expected SetSignal, got {:?}", other),
        }
    }

    #[test]
    fn command_set_frequency_round_trip() {
        let q = CommandQueue::new();
        q.push(Command {
            kind: CommandKind::SetFrequency { frequency: 440.0 },
        })
        .unwrap();
        match q.pop().unwrap().kind {
            CommandKind::SetFrequency { frequency } => assert_eq!(frequency, 440.0),
            other => panic!("Expected SetFrequency, got {:?}", other),
        }
    }

    #[test]
    fn command_start_stop_capture_round_trip() {
        let q = CommandQueue::new();
        q.push(Command {
            kind: CommandKind::StartCapture,
        })
        .unwrap();
        q.push(Command {
            kind: CommandKind::StopCapture,
        })
        .unwrap();

        match q.pop().unwrap().kind {
            CommandKind::StartCapture => {}
            other => panic!("Expected StartCapture, got {:?}", other),
        }
        match q.pop().unwrap().kind {
            CommandKind::StopCapture => {}
            other => panic!("Expected StopCapture, got {:?}", other),
        }
    }

    // -----------------------------------------------------------------------
    // StateSnapshot round-trip through queue
    // -----------------------------------------------------------------------

    #[test]
    fn state_snapshot_round_trip() {
        let q = StateQueue::new();
        let snap = StateSnapshot {
            state: PlayState::Playing,
            signal: SignalType::Sine,
            channels: 0b0000_0011,
            level_dbfs: -20.0,
            frequency: 1000.0,
            elapsed_secs: 1.5,
            duration_secs: 10.0,
            capture_peak: 0.05,
            capture_rms: 0.02,
            capture_connected: true,
            samples_generated: 72000,
        };

        q.push(snap).unwrap();
        let popped = q.pop().unwrap();

        assert_eq!(popped.state, PlayState::Playing);
        assert_eq!(popped.signal, SignalType::Sine);
        assert_eq!(popped.channels, 0b0000_0011);
        assert_eq!(popped.level_dbfs, -20.0);
        assert_eq!(popped.frequency, 1000.0);
        assert_eq!(popped.elapsed_secs, 1.5);
        assert_eq!(popped.duration_secs, 10.0);
        assert_eq!(popped.capture_peak, 0.05);
        assert_eq!(popped.capture_rms, 0.02);
        assert!(popped.capture_connected);
        assert_eq!(popped.samples_generated, 72000);
    }

    // -----------------------------------------------------------------------
    // Multi-command drain (AD-D037-6)
    // -----------------------------------------------------------------------

    #[test]
    fn multi_command_drain() {
        // Simulates the process callback draining all pending commands.
        let q = CommandQueue::new();

        q.push(Command {
            kind: CommandKind::SetLevel { level_dbfs: -10.0 },
        })
        .unwrap();
        q.push(Command {
            kind: CommandKind::SetSignal {
                signal: SignalType::Sine,
                frequency: 440.0,
            },
        })
        .unwrap();
        q.push(Command {
            kind: CommandKind::Play {
                signal: SignalType::Sine,
                channels: 0xFF,
                level_dbfs: -10.0,
                frequency: 440.0,
                duration_secs: None,
                sweep_end_hz: 0.0,
            },
        })
        .unwrap();

        // Drain all commands (process callback pattern from Section 5.4).
        let mut drained = Vec::new();
        while let Some(cmd) = q.pop() {
            drained.push(cmd);
        }

        assert_eq!(drained.len(), 3);
        assert!(matches!(drained[0].kind, CommandKind::SetLevel { .. }));
        assert!(matches!(drained[1].kind, CommandKind::SetSignal { .. }));
        assert!(matches!(drained[2].kind, CommandKind::Play { .. }));

        // Queue should now be empty.
        assert!(q.is_empty());
        assert_eq!(q.pop(), None);
    }

    // -----------------------------------------------------------------------
    // StateSnapshot default
    // -----------------------------------------------------------------------

    #[test]
    fn state_snapshot_default_is_stopped() {
        let snap = StateSnapshot::stopped();
        assert_eq!(snap.state, PlayState::Stopped);
        assert_eq!(snap.signal, SignalType::Silence);
        assert_eq!(snap.channels, 0);
        assert_eq!(snap.samples_generated, 0);
    }
}
