//! PipeWire registry listener for device hot-plug detection.
//!
//! Monitors the PipeWire registry for node add/remove events matching
//! the `--device-watch` pattern (default: "UMIK-1"). When the capture
//! device disappears or reappears, the signal generator broadcasts
//! `capture_device_connected` / `capture_device_disconnected` events
//! to all connected RPC clients.
//!
//! D-037 Section 8.1: PW registry listener.
//! D-037 Section 8.2: Capture stream state machine (Connected/Disconnected).
//!
//! ## Thread model
//!
//! The PW registry callbacks run on the PW main loop thread (same thread
//! that drives the main loop). Events are pushed into a lock-free SPSC
//! queue and consumed by the RPC server thread for client broadcast.
//!
//! ## Design
//!
//! - `DeviceEvent` enum: Added / Removed / Xrun
//! - `DeviceEventQueue`: SPSC ring buffer for event delivery
//! - `TrackedDevices`: tracks which PW node IDs match the watch pattern
//! - `register_registry_listener()`: PW-specific setup (only compiles with PW)
//! - `format_device_event()`: JSON formatting for RPC broadcast

use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};

use command::SpscQueue;

use crate::command;

// ---------------------------------------------------------------------------
// Device event types
// ---------------------------------------------------------------------------

/// Maximum length of a device name stored in DeviceEvent.
/// UMIK-1 names are short, but we allow some headroom.
const MAX_DEVICE_NAME_LEN: usize = 64;

/// A device name stored inline (no heap allocation) for Copy compatibility
/// with SpscQueue.
#[derive(Debug, Clone, Copy)]
pub struct DeviceName {
    buf: [u8; MAX_DEVICE_NAME_LEN],
    len: u8,
}

impl DeviceName {
    /// Create a DeviceName from a string, truncating if necessary.
    pub fn from_str(s: &str) -> Self {
        let bytes = s.as_bytes();
        let len = bytes.len().min(MAX_DEVICE_NAME_LEN);
        let mut buf = [0u8; MAX_DEVICE_NAME_LEN];
        buf[..len].copy_from_slice(&bytes[..len]);
        Self {
            buf,
            len: len as u8,
        }
    }

    /// Return the name as a string slice.
    pub fn as_str(&self) -> &str {
        std::str::from_utf8(&self.buf[..self.len as usize]).unwrap_or("")
    }
}

impl PartialEq for DeviceName {
    fn eq(&self, other: &Self) -> bool {
        self.as_str() == other.as_str()
    }
}

impl Eq for DeviceName {}

/// Device events pushed from the PW registry listener to the RPC thread.
///
/// All variants are Copy (no heap allocation) for use in SpscQueue.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceEvent {
    /// A device matching the watch pattern appeared in the PW registry.
    Added {
        name: DeviceName,
        node_id: u32,
    },
    /// A previously tracked device was removed from the PW registry.
    Removed {
        name: DeviceName,
        node_id: u32,
    },
    /// PipeWire reported a buffer xrun on a stream.
    Xrun {
        /// "playback" or "capture"
        stream: DeviceName,
        count: u32,
    },
}

/// Default impl required by SpscQueue::new() for buffer initialization.
/// The default value is never read as meaningful data.
impl Default for DeviceEvent {
    fn default() -> Self {
        Self::Xrun {
            stream: DeviceName::from_str(""),
            count: 0,
        }
    }
}

/// Capacity of the device event queue. Hot-plug events are infrequent;
/// 16 slots is generous.
const DEVICE_EVENT_QUEUE_CAPACITY: usize = 16;

/// SPSC queue for device events (PW main loop -> RPC thread).
pub type DeviceEventQueue = SpscQueue<DeviceEvent, DEVICE_EVENT_QUEUE_CAPACITY>;

// ---------------------------------------------------------------------------
// Tracked device set
// ---------------------------------------------------------------------------

/// Maximum number of simultaneously tracked PW node IDs.
/// In practice there is one UMIK-1 at most, but we allow a few
/// for edge cases (brief overlap during re-enumeration).
const MAX_TRACKED_DEVICES: usize = 4;

/// A fixed-capacity set of PW node IDs being tracked.
///
/// When a registry `global` event matches the watch pattern, the node ID
/// is added here. When `global_remove` fires, we check this set to
/// determine whether the removed node was one of ours.
///
/// No heap allocation, no locks. Only used from the PW main loop thread.
pub struct TrackedDevices {
    ids: [u32; MAX_TRACKED_DEVICES],
    names: [DeviceName; MAX_TRACKED_DEVICES],
    count: usize,
}

impl TrackedDevices {
    pub fn new() -> Self {
        Self {
            ids: [0; MAX_TRACKED_DEVICES],
            names: [DeviceName::from_str(""); MAX_TRACKED_DEVICES],
            count: 0,
        }
    }

    /// Add a tracked device. Returns false if the set is full.
    pub fn add(&mut self, node_id: u32, name: DeviceName) -> bool {
        // Don't add duplicates.
        if self.contains(node_id) {
            return true;
        }
        if self.count >= MAX_TRACKED_DEVICES {
            return false;
        }
        self.ids[self.count] = node_id;
        self.names[self.count] = name;
        self.count += 1;
        true
    }

    /// Remove a tracked device by node ID. Returns the name if found.
    pub fn remove(&mut self, node_id: u32) -> Option<DeviceName> {
        for i in 0..self.count {
            if self.ids[i] == node_id {
                let name = self.names[i];
                // Swap with last element to maintain density.
                self.count -= 1;
                if i < self.count {
                    self.ids[i] = self.ids[self.count];
                    self.names[i] = self.names[self.count];
                }
                return Some(name);
            }
        }
        None
    }

    /// Check if a node ID is tracked.
    pub fn contains(&self, node_id: u32) -> bool {
        self.ids[..self.count].contains(&node_id)
    }

    /// Number of currently tracked devices.
    pub fn len(&self) -> usize {
        self.count
    }

    /// Whether the set is empty.
    pub fn is_empty(&self) -> bool {
        self.count == 0
    }
}

// ---------------------------------------------------------------------------
// Capture connection state (shared between PW main loop and RPC thread)
// ---------------------------------------------------------------------------

/// Atomic flag indicating whether the capture device is connected.
///
/// Set by the registry listener (PW main loop thread).
/// Read by the RPC thread for state broadcasts and playrec rejection.
pub struct CaptureConnectionState {
    connected: AtomicBool,
    node_id: AtomicU32,
}

impl CaptureConnectionState {
    pub fn new() -> Self {
        Self {
            connected: AtomicBool::new(false),
            node_id: AtomicU32::new(0),
        }
    }

    pub fn set_connected(&self, node_id: u32) {
        self.node_id.store(node_id, Ordering::Relaxed);
        self.connected.store(true, Ordering::Release);
    }

    pub fn set_disconnected(&self) {
        self.connected.store(false, Ordering::Release);
    }

    pub fn is_connected(&self) -> bool {
        self.connected.load(Ordering::Acquire)
    }

    pub fn node_id(&self) -> u32 {
        self.node_id.load(Ordering::Relaxed)
    }
}

// ---------------------------------------------------------------------------
// Event formatting for RPC broadcast
// ---------------------------------------------------------------------------

/// Format a device event as a JSON line for RPC broadcast.
///
/// Event format per D-037 Section 7.3:
/// - `{"type":"event","event":"capture_device_connected","name":"UMIK-1","node_id":47}`
/// - `{"type":"event","event":"capture_device_disconnected","name":"UMIK-1","node_id":47}`
/// - `{"type":"event","event":"xrun","stream":"playback","count":1}`
pub fn format_device_event(event: &DeviceEvent) -> String {
    match event {
        DeviceEvent::Added { name, node_id } => {
            let mut data = serde_json::Map::new();
            data.insert(
                "name".to_string(),
                serde_json::Value::String(name.as_str().to_string()),
            );
            data.insert(
                "node_id".to_string(),
                serde_json::Value::Number((*node_id).into()),
            );
            let resp = crate::rpc::EventResponse {
                r#type: "event",
                event: "capture_device_connected".to_string(),
                data,
            };
            serde_json::to_string(&resp).unwrap()
        }
        DeviceEvent::Removed { name, node_id } => {
            let mut data = serde_json::Map::new();
            data.insert(
                "name".to_string(),
                serde_json::Value::String(name.as_str().to_string()),
            );
            data.insert(
                "node_id".to_string(),
                serde_json::Value::Number((*node_id).into()),
            );
            let resp = crate::rpc::EventResponse {
                r#type: "event",
                event: "capture_device_disconnected".to_string(),
                data,
            };
            serde_json::to_string(&resp).unwrap()
        }
        DeviceEvent::Xrun { stream, count } => {
            let mut data = serde_json::Map::new();
            data.insert(
                "stream".to_string(),
                serde_json::Value::String(stream.as_str().to_string()),
            );
            data.insert(
                "count".to_string(),
                serde_json::Value::Number((*count).into()),
            );
            let resp = crate::rpc::EventResponse {
                r#type: "event",
                event: "xrun".to_string(),
                data,
            };
            serde_json::to_string(&resp).unwrap()
        }
    }
}

/// Check if a node name matches the device watch pattern.
///
/// Uses substring matching (case-sensitive) as per D-037 Section 8.1:
/// the default watch pattern "UMIK-1" matches any node whose name
/// contains "UMIK-1".
pub fn matches_watch_pattern(node_name: &str, pattern: &str) -> bool {
    node_name.contains(pattern)
}

// ---------------------------------------------------------------------------
// PipeWire registry listener setup
// ---------------------------------------------------------------------------

/// Register a PipeWire registry listener that monitors for device add/remove.
///
/// The listener watches for PW nodes whose `node.name` property matches
/// the `watch_pattern` (substring match). When a matching node appears,
/// a `DeviceEvent::Added` is pushed to the event queue and the
/// `CaptureConnectionState` is set to connected. When a tracked node
/// disappears, a `DeviceEvent::Removed` is pushed and the state is
/// set to disconnected.
///
/// Returns the registry and its listener. Both must be kept alive for
/// the duration of the PW main loop.
///
/// # Arguments
/// * `core` - The PW core connection.
/// * `event_queue` - SPSC queue for delivering events to the RPC thread.
/// * `conn_state` - Shared connection state flag.
/// * `watch_pattern` - Device name pattern to match (e.g., "UMIK-1").
pub fn register_registry_listener(
    core: &pipewire::core::Core,
    event_queue: std::sync::Arc<DeviceEventQueue>,
    conn_state: std::sync::Arc<CaptureConnectionState>,
    watch_pattern: String,
) -> (pipewire::registry::Registry, Box<dyn std::any::Any>) {
    use std::cell::RefCell;
    use std::rc::Rc;

    let registry = core.get_registry().expect("Failed to get PipeWire registry");

    // TrackedDevices is shared between the two closures. Both run on the
    // PW main loop thread (single-threaded), so Rc<RefCell<>> is safe.
    let tracked = Rc::new(RefCell::new(TrackedDevices::new()));
    let tracked_add = tracked.clone();
    let tracked_remove = tracked;

    let eq_add = event_queue.clone();
    let eq_remove = event_queue;
    let cs_add = conn_state.clone();
    let cs_remove = conn_state;
    let pattern_add = watch_pattern.clone();

    let listener = registry
        .add_listener_local()
        .global(move |global| {
            // Only interested in Node objects.
            if global.type_ == pipewire::types::ObjectType::Node {
                if let Some(props) = global.props {
                    let node_name = props.get("node.name").unwrap_or("");
                    if matches_watch_pattern(node_name, &pattern_add) {
                        let name = DeviceName::from_str(node_name);
                        tracked_add.borrow_mut().add(global.id, name);
                        cs_add.set_connected(global.id);
                        let _ = eq_add.push(DeviceEvent::Added {
                            name,
                            node_id: global.id,
                        });
                        log::info!(
                            "Capture device detected: {} (node_id={})",
                            node_name,
                            global.id
                        );
                    }
                }
            }
        })
        .global_remove(move |id| {
            let mut tracked = tracked_remove.borrow_mut();
            if let Some(name) = tracked.remove(id) {
                // If no tracked devices remain, mark as disconnected.
                if tracked.is_empty() {
                    cs_remove.set_disconnected();
                }
                let _ = eq_remove.push(DeviceEvent::Removed {
                    name,
                    node_id: id,
                });
                log::info!(
                    "Capture device removed: {} (node_id={})",
                    name.as_str(),
                    id
                );
            }
        })
        .register();

    (registry, Box::new(listener))
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------------
    // DeviceName
    // -----------------------------------------------------------------------

    #[test]
    fn device_name_from_str_and_back() {
        let name = DeviceName::from_str("UMIK-1");
        assert_eq!(name.as_str(), "UMIK-1");
    }

    #[test]
    fn device_name_empty() {
        let name = DeviceName::from_str("");
        assert_eq!(name.as_str(), "");
    }

    #[test]
    fn device_name_truncates_long_string() {
        let long = "a".repeat(100);
        let name = DeviceName::from_str(&long);
        assert_eq!(name.as_str().len(), MAX_DEVICE_NAME_LEN);
    }

    #[test]
    fn device_name_equality() {
        let a = DeviceName::from_str("UMIK-1");
        let b = DeviceName::from_str("UMIK-1");
        assert_eq!(a, b);
    }

    #[test]
    fn device_name_inequality() {
        let a = DeviceName::from_str("UMIK-1");
        let b = DeviceName::from_str("UMIK-2");
        assert_ne!(a, b);
    }

    // -----------------------------------------------------------------------
    // TrackedDevices
    // -----------------------------------------------------------------------

    #[test]
    fn tracked_devices_initially_empty() {
        let tracked = TrackedDevices::new();
        assert!(tracked.is_empty());
        assert_eq!(tracked.len(), 0);
    }

    #[test]
    fn tracked_devices_add_and_contains() {
        let mut tracked = TrackedDevices::new();
        let name = DeviceName::from_str("UMIK-1");
        assert!(tracked.add(42, name));
        assert!(tracked.contains(42));
        assert!(!tracked.contains(43));
        assert_eq!(tracked.len(), 1);
    }

    #[test]
    fn tracked_devices_add_duplicate_is_noop() {
        let mut tracked = TrackedDevices::new();
        let name = DeviceName::from_str("UMIK-1");
        assert!(tracked.add(42, name));
        assert!(tracked.add(42, name)); // duplicate
        assert_eq!(tracked.len(), 1);
    }

    #[test]
    fn tracked_devices_remove_returns_name() {
        let mut tracked = TrackedDevices::new();
        let name = DeviceName::from_str("UMIK-1");
        tracked.add(42, name);

        let removed = tracked.remove(42);
        assert!(removed.is_some());
        assert_eq!(removed.unwrap().as_str(), "UMIK-1");
        assert!(tracked.is_empty());
    }

    #[test]
    fn tracked_devices_remove_unknown_returns_none() {
        let mut tracked = TrackedDevices::new();
        assert!(tracked.remove(99).is_none());
    }

    #[test]
    fn tracked_devices_remove_middle_element() {
        let mut tracked = TrackedDevices::new();
        tracked.add(10, DeviceName::from_str("dev-a"));
        tracked.add(20, DeviceName::from_str("dev-b"));
        tracked.add(30, DeviceName::from_str("dev-c"));
        assert_eq!(tracked.len(), 3);

        // Remove the middle one.
        let removed = tracked.remove(20);
        assert_eq!(removed.unwrap().as_str(), "dev-b");
        assert_eq!(tracked.len(), 2);
        assert!(tracked.contains(10));
        assert!(!tracked.contains(20));
        assert!(tracked.contains(30));
    }

    #[test]
    fn tracked_devices_full_rejects_add() {
        let mut tracked = TrackedDevices::new();
        for i in 0..MAX_TRACKED_DEVICES as u32 {
            assert!(tracked.add(i, DeviceName::from_str("dev")));
        }
        assert_eq!(tracked.len(), MAX_TRACKED_DEVICES);

        // One more should fail.
        assert!(!tracked.add(99, DeviceName::from_str("overflow")));
    }

    // -----------------------------------------------------------------------
    // CaptureConnectionState
    // -----------------------------------------------------------------------

    #[test]
    fn capture_connection_state_initially_disconnected() {
        let state = CaptureConnectionState::new();
        assert!(!state.is_connected());
        assert_eq!(state.node_id(), 0);
    }

    #[test]
    fn capture_connection_state_connect_disconnect() {
        let state = CaptureConnectionState::new();

        state.set_connected(47);
        assert!(state.is_connected());
        assert_eq!(state.node_id(), 47);

        state.set_disconnected();
        assert!(!state.is_connected());
    }

    // -----------------------------------------------------------------------
    // matches_watch_pattern
    // -----------------------------------------------------------------------

    #[test]
    fn matches_exact_name() {
        assert!(matches_watch_pattern("UMIK-1", "UMIK-1"));
    }

    #[test]
    fn matches_substring() {
        assert!(matches_watch_pattern("alsa_input.usb-miniDSP_UMIK-1_12345-00.mono-fallback", "UMIK-1"));
    }

    #[test]
    fn no_match_different_device() {
        assert!(!matches_watch_pattern("USBStreamer", "UMIK-1"));
    }

    #[test]
    fn no_match_case_sensitive() {
        assert!(!matches_watch_pattern("umik-1", "UMIK-1"));
    }

    #[test]
    fn empty_pattern_matches_everything() {
        assert!(matches_watch_pattern("anything", ""));
    }

    // -----------------------------------------------------------------------
    // DeviceEvent queue
    // -----------------------------------------------------------------------

    #[test]
    fn device_event_queue_push_pop() {
        let queue = DeviceEventQueue::new();
        let event = DeviceEvent::Added {
            name: DeviceName::from_str("UMIK-1"),
            node_id: 42,
        };

        assert!(queue.push(event).is_ok());
        let popped = queue.pop();
        assert!(popped.is_some());
        assert_eq!(popped.unwrap(), event);
    }

    #[test]
    fn device_event_queue_empty_returns_none() {
        let queue = DeviceEventQueue::new();
        assert!(queue.pop().is_none());
    }

    #[test]
    fn device_event_queue_multiple_events() {
        let queue = DeviceEventQueue::new();
        let add = DeviceEvent::Added {
            name: DeviceName::from_str("UMIK-1"),
            node_id: 42,
        };
        let remove = DeviceEvent::Removed {
            name: DeviceName::from_str("UMIK-1"),
            node_id: 42,
        };
        let xrun = DeviceEvent::Xrun {
            stream: DeviceName::from_str("playback"),
            count: 1,
        };

        queue.push(add).unwrap();
        queue.push(remove).unwrap();
        queue.push(xrun).unwrap();

        assert_eq!(queue.pop().unwrap(), add);
        assert_eq!(queue.pop().unwrap(), remove);
        assert_eq!(queue.pop().unwrap(), xrun);
        assert!(queue.pop().is_none());
    }

    // -----------------------------------------------------------------------
    // format_device_event
    // -----------------------------------------------------------------------

    #[test]
    fn format_added_event() {
        let event = DeviceEvent::Added {
            name: DeviceName::from_str("UMIK-1"),
            node_id: 47,
        };
        let json = format_device_event(&event);
        let v: serde_json::Value = serde_json::from_str(&json).unwrap();

        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "capture_device_connected");
        assert_eq!(v["name"], "UMIK-1");
        assert_eq!(v["node_id"], 47);
    }

    #[test]
    fn format_removed_event() {
        let event = DeviceEvent::Removed {
            name: DeviceName::from_str("UMIK-1"),
            node_id: 47,
        };
        let json = format_device_event(&event);
        let v: serde_json::Value = serde_json::from_str(&json).unwrap();

        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "capture_device_disconnected");
        assert_eq!(v["name"], "UMIK-1");
        assert_eq!(v["node_id"], 47);
    }

    #[test]
    fn format_xrun_event() {
        let event = DeviceEvent::Xrun {
            stream: DeviceName::from_str("playback"),
            count: 3,
        };
        let json = format_device_event(&event);
        let v: serde_json::Value = serde_json::from_str(&json).unwrap();

        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "xrun");
        assert_eq!(v["stream"], "playback");
        assert_eq!(v["count"], 3);
    }
}
