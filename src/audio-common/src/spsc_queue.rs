//! Lock-free single-producer single-consumer ring buffer.
//!
//! - Fixed capacity (power of two for efficient modular indexing).
//! - No allocation in `push()` or `pop()`.
//! - No mutex, no blocking.
//! - Safe for RT: one thread pushes, the other pops.

use std::cell::UnsafeCell;
use std::sync::atomic::{AtomicUsize, Ordering};

/// Lock-free single-producer single-consumer ring buffer.
///
/// Uses `AtomicUsize` for read/write positions with `Acquire`/`Release`
/// ordering to ensure visibility of written data across threads.
pub struct SpscQueue<T: Copy, const N: usize> {
    buffer: [UnsafeCell<T>; N],
    head: AtomicUsize, // next write position (producer)
    tail: AtomicUsize, // next read position (consumer)
}

// Safety: SpscQueue is designed for single-producer single-consumer use.
unsafe impl<T: Copy + Send, const N: usize> Send for SpscQueue<T, N> {}
unsafe impl<T: Copy + Send, const N: usize> Sync for SpscQueue<T, N> {}

impl<T: Copy + Default, const N: usize> SpscQueue<T, N> {
    /// Create a new empty SPSC queue.
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
    pub fn push(&self, item: T) -> Result<(), T> {
        let head = self.head.load(Ordering::Relaxed);
        let tail = self.tail.load(Ordering::Acquire);
        let next_head = (head + 1) % N;

        if next_head == tail {
            return Err(item); // full
        }

        unsafe {
            *self.buffer[head].get() = item;
        }

        self.head.store(next_head, Ordering::Release);
        Ok(())
    }

    /// Try to pop an item. Returns `None` if the queue is empty.
    pub fn pop(&self) -> Option<T> {
        let tail = self.tail.load(Ordering::Relaxed);
        let head = self.head.load(Ordering::Acquire);

        if tail == head {
            return None; // empty
        }

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

#[cfg(test)]
mod tests {
    use super::*;

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
    }

    #[test]
    fn queue_full_push_returns_err() {
        let q = SpscQueue::<u32, 4>::new();
        assert!(q.push(1).is_ok());
        assert!(q.push(2).is_ok());
        assert!(q.push(3).is_ok());
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
}
