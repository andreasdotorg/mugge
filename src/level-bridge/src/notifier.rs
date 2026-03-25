//! RT-safe event notification for waking the levels server from the PW callback.
//!
//! The PipeWire process callback sets an atomic flag and calls
//! `condvar.notify_one()` — both are RT-safe (no allocation, no mutex
//! lock, single futex wake syscall on Linux). The server thread waits
//! on the condvar with a timeout.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Condvar, Mutex};
use std::time::Duration;

/// RT-safe one-shot notifier. The RT callback calls `notify()` (lock-free),
/// the server thread calls `wait()` (blocking with timeout).
pub struct Notifier {
    flag: AtomicBool,
    condvar: Condvar,
    mutex: Mutex<()>,
}

impl Notifier {
    pub fn new() -> Self {
        Self {
            flag: AtomicBool::new(false),
            condvar: Condvar::new(),
            mutex: Mutex::new(()),
        }
    }

    /// Signal that new data is available. RT-safe: no allocation, no mutex
    /// lock. Sets an atomic flag and does a futex wake via `notify_one()`.
    #[inline]
    pub fn notify(&self) {
        self.flag.store(true, Ordering::Release);
        self.condvar.notify_one();
    }

    /// Wait for a notification, with timeout. Returns `true` if notified,
    /// `false` on timeout. Clears the flag on return.
    pub fn wait(&self, timeout: Duration) -> bool {
        // Fast path: flag already set (notification arrived before we wait).
        if self.flag.swap(false, Ordering::Acquire) {
            return true;
        }

        let guard = self.mutex.lock().unwrap();
        let (_guard, _result) = self
            .condvar
            .wait_timeout_while(guard, timeout, |_| {
                !self.flag.load(Ordering::Acquire)
            })
            .unwrap();

        // Clear the flag whether we were notified or timed out.
        self.flag.swap(false, Ordering::Acquire)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::time::Instant;

    #[test]
    fn notify_before_wait_returns_immediately() {
        let n = Notifier::new();
        n.notify();
        assert!(n.wait(Duration::from_millis(100)));
    }

    #[test]
    fn wait_without_notify_times_out() {
        let n = Notifier::new();
        let start = Instant::now();
        let result = n.wait(Duration::from_millis(50));
        assert!(!result);
        assert!(start.elapsed() >= Duration::from_millis(40));
    }

    #[test]
    fn notify_wakes_waiting_thread() {
        let n = Arc::new(Notifier::new());
        let n2 = n.clone();
        let handle = std::thread::spawn(move || {
            n2.wait(Duration::from_secs(5))
        });
        std::thread::sleep(Duration::from_millis(20));
        n.notify();
        assert!(handle.join().unwrap());
    }

    #[test]
    fn flag_cleared_after_wait() {
        let n = Notifier::new();
        n.notify();
        assert!(n.wait(Duration::from_millis(100)));
        // Second wait should timeout since flag was cleared.
        assert!(!n.wait(Duration::from_millis(50)));
    }

    #[test]
    fn multiple_notifies_coalesce() {
        let n = Notifier::new();
        n.notify();
        n.notify();
        n.notify();
        assert!(n.wait(Duration::from_millis(100)));
        // Only one notification consumed.
        assert!(!n.wait(Duration::from_millis(50)));
    }
}
