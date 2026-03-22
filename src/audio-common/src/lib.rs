//! Shared lock-free audio primitives for Pi audio workstation RT services.
//!
//! This crate contains data structures and utilities shared between
//! `pcm-bridge` and `signal-gen`. It has ZERO PipeWire dependencies —
//! everything here is pure Rust, testable without audio hardware.

pub mod audio_format;
pub mod capture_ring_buffer;
pub mod level_tracker;
pub mod ring_buffer;
pub mod spsc_queue;

// Re-export key types at crate root for convenience.
pub use capture_ring_buffer::CaptureRingBuffer;
pub use level_tracker::LevelTracker;
pub use ring_buffer::RingBuffer;
pub use spsc_queue::SpscQueue;
