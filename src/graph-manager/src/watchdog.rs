//! Filter-chain watchdog — safety mute via native PipeWire API (T-044-4).
//!
//! Monitors critical audio nodes in the PipeWire graph and latches a safety
//! MUTE when any disappear. The mute sets Mult=0.0 on all 4 gain nodes
//! (linear builtins in the filter-chain). If gain nodes themselves are gone,
//! the fallback destroys ALL links to the USBStreamer input ports.
//!
//! ## Safety model
//!
//! This is SAFETY-CRITICAL code. The design is fail-safe:
//! - Any error in the mute path → attempt mute anyway (best-effort)
//! - Mute is LATCHED: once triggered, stays muted until explicit unlatch
//! - Unlatch requires an RPC command (`watchdog_unlatch`)
//! - The watchdog never increases gain — it only sets Mult to 0.0
//!
//! ## Monitored nodes (6 total)
//!
//! | Node name                | Role                        |
//! |--------------------------|-----------------------------|
//! | `pi4audio-convolver`     | Filter-chain capture side   |
//! | `pi4audio-convolver-out` | Filter-chain playback side  |
//! | `gain_left_hp`           | Left main gain node         |
//! | `gain_right_hp`          | Right main gain node        |
//! | `gain_sub1_lp`           | Sub 1 gain node             |
//! | `gain_sub2_lp`           | Sub 2 gain node             |
//!
//! ## Mute mechanism
//!
//! **Primary:** Set Mult parameter to 0.0 on all 4 gain nodes using
//! `pw_node_set_param()` via `pipewire-rs` (target: <1ms per node, <5ms total).
//!
//! **Fallback:** If gain nodes themselves disappear (can't set Mult on a
//! nonexistent node), destroy ALL links to USBStreamer input ports using
//! `pw_registry::destroy_global()`.
//!
//! ## Thread model
//!
//! All watchdog state lives on the PW main loop thread (single-threaded,
//! `Rc<RefCell<>>`). The `check()` method is called from the registry
//! listener after every graph mutation. The unlatch command arrives via
//! the RPC command channel (processed by the 50ms timer callback).
//!
//! ## Response time
//!
//! Target: <21ms (1 PipeWire graph cycle at quantum 1024). Since registry
//! events are push-based (no polling), the watchdog fires within the same
//! PW main loop iteration that processes the node removal event. The native
//! PW API (`pw_registry_bind` + `pw_node_set_param` via `pipewire-sys` FFI)
//! adds <1ms per node — well within budget. No subprocess is used.

use crate::graph::GraphState;
use crate::routing::NodeMatch;

/// Names of the 6 monitored nodes.
///
/// If ANY of these disappear from the PW graph, the watchdog triggers.
pub const MONITORED_NODES: &[&str] = &[
    "pi4audio-convolver",
    "pi4audio-convolver-out",
    "gain_left_hp",
    "gain_right_hp",
    "gain_sub1_lp",
    "gain_sub2_lp",
];

/// Names of the 4 gain nodes whose Mult parameter is set to 0.0 on mute.
pub const GAIN_NODE_NAMES: &[&str] = &[
    "gain_left_hp",
    "gain_right_hp",
    "gain_sub1_lp",
    "gain_sub2_lp",
];

/// USBStreamer node name prefix — used for fallback link destruction.
const USBSTREAMER_OUT_PREFIX: &str = "alsa_output.usb-MiniDSP_USBStreamer";

/// Result of a watchdog check cycle.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WatchdogAction {
    /// All monitored nodes present, no action needed.
    AllPresent,
    /// Already latched — no new action (already muted).
    AlreadyLatched,
    /// Gain nodes available — set Mult=0.0 on each via native PW API.
    SetGainMute {
        /// (node_id, node_name) pairs for gain nodes to mute.
        gain_nodes: Vec<(u32, String)>,
    },
    /// Gain nodes NOT available — destroy USBStreamer links as fallback.
    DestroyUsbLinks {
        /// PW link IDs to destroy.
        link_ids: Vec<u32>,
    },
}

/// Watchdog state machine.
///
/// Tracks whether the safety mute is latched and which nodes were missing
/// when the latch was triggered. Pure state — no PW API calls. The caller
/// (registry listener) applies the returned actions.
pub struct Watchdog {
    /// Whether the safety mute is currently latched.
    latched: bool,
    /// Node names that were missing when the latch was triggered.
    missing_at_latch: Vec<String>,
    /// Pre-mute Mult values stored for unlatch restoration.
    /// Key: gain node name, Value: Mult value before mute.
    pre_mute_gains: Vec<(String, f64)>,
}

impl Watchdog {
    /// Create a new watchdog in the unlatched state.
    pub fn new() -> Self {
        Self {
            latched: false,
            missing_at_latch: Vec::new(),
            pre_mute_gains: Vec::new(),
        }
    }

    /// Whether the safety mute is currently latched.
    pub fn is_latched(&self) -> bool {
        self.latched
    }

    /// Node names that were missing when the latch was triggered.
    pub fn missing_at_latch(&self) -> &[String] {
        &self.missing_at_latch
    }

    /// Pre-mute gain values (for unlatch restoration).
    pub fn pre_mute_gains(&self) -> &[(String, f64)] {
        &self.pre_mute_gains
    }

    /// Check the graph state and determine what action to take.
    ///
    /// Called after every graph mutation (registry event). This is a pure
    /// function — it reads GraphState and returns an action. The caller
    /// applies the action via PW API calls.
    ///
    /// ## Logic
    ///
    /// 1. If already latched → `AlreadyLatched` (no-op).
    /// 2. Check all 6 monitored nodes. If all present → `AllPresent`.
    /// 3. If any missing → latch the mute and determine mechanism:
    ///    a. If gain nodes are present → `SetGainMute` (primary path).
    ///    b. If gain nodes are gone → `DestroyUsbLinks` (fallback path).
    pub fn check(&mut self, graph: &GraphState) -> WatchdogAction {
        if self.latched {
            return WatchdogAction::AlreadyLatched;
        }

        // Check which monitored nodes are missing.
        let missing: Vec<String> = MONITORED_NODES
            .iter()
            .filter(|name| graph.node_by_name(name).is_none())
            .map(|name| name.to_string())
            .collect();

        if missing.is_empty() {
            return WatchdogAction::AllPresent;
        }

        // Latch the mute.
        self.latched = true;
        self.missing_at_latch = missing.clone();
        log::error!(
            "WATCHDOG: Safety mute LATCHED — missing nodes: {:?}",
            missing,
        );

        // Determine mute mechanism: primary (gain nodes) or fallback (link destroy).
        let gain_nodes: Vec<(u32, String)> = GAIN_NODE_NAMES
            .iter()
            .filter_map(|name| {
                graph
                    .node_by_name(name)
                    .map(|node| (node.id, name.to_string()))
            })
            .collect();

        if !gain_nodes.is_empty() {
            // Primary path: at least some gain nodes available.
            WatchdogAction::SetGainMute { gain_nodes }
        } else {
            // Fallback: no gain nodes — destroy all links to USBStreamer.
            let usb_matcher = NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string());
            let link_ids: Vec<u32> = graph
                .links()
                .filter(|link| {
                    // Find links whose input node is the USBStreamer.
                    if let Some(node) = graph.node(link.input_node) {
                        usb_matcher.matches(&node.name)
                    } else {
                        false
                    }
                })
                .map(|link| link.id)
                .collect();

            log::error!(
                "WATCHDOG: Gain nodes gone — fallback: destroying {} USBStreamer links",
                link_ids.len(),
            );
            WatchdogAction::DestroyUsbLinks { link_ids }
        }
    }

    /// Store pre-mute gain values (called by the mute executor before zeroing).
    pub fn store_pre_mute_gains(&mut self, gains: Vec<(String, f64)>) {
        self.pre_mute_gains = gains;
    }

    /// Unlatch the safety mute, returning the pre-mute gains for restoration.
    ///
    /// Returns `None` if not latched. Returns `Some(gains)` with the stored
    /// pre-mute values if latched. The caller is responsible for restoring
    /// the Mult values via PW API calls.
    pub fn unlatch(&mut self) -> Option<Vec<(String, f64)>> {
        if !self.latched {
            return None;
        }

        self.latched = false;
        let gains = std::mem::take(&mut self.pre_mute_gains);
        self.missing_at_latch.clear();

        log::warn!("WATCHDOG: Safety mute UNLATCHED — restoring {} gain values", gains.len());
        Some(gains)
    }

    /// Get the current watchdog status for RPC responses.
    pub fn status(&self) -> WatchdogStatus {
        WatchdogStatus {
            latched: self.latched,
            missing_nodes: self.missing_at_latch.clone(),
            pre_mute_gains: self.pre_mute_gains.clone(),
        }
    }
}

/// Serializable watchdog status for RPC responses.
#[derive(Debug, Clone, serde::Serialize)]
pub struct WatchdogStatus {
    pub latched: bool,
    pub missing_nodes: Vec<String>,
    pub pre_mute_gains: Vec<(String, f64)>,
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::{GraphState, TrackedNode};
    use std::collections::HashMap;

    fn make_node(id: u32, name: &str, class: &str) -> TrackedNode {
        TrackedNode {
            id,
            name: name.to_string(),
            media_class: class.to_string(),
            properties: HashMap::new(),
        }
    }

    /// Build a graph with all 6 monitored nodes present.
    fn graph_all_present() -> GraphState {
        let mut g = GraphState::new();
        g.add_node(make_node(100, "pi4audio-convolver", "Audio/Sink"));
        g.add_node(make_node(200, "pi4audio-convolver-out", "Stream/Output/Audio"));
        g.add_node(make_node(301, "gain_left_hp", "Audio/Sink"));
        g.add_node(make_node(302, "gain_right_hp", "Audio/Sink"));
        g.add_node(make_node(303, "gain_sub1_lp", "Audio/Sink"));
        g.add_node(make_node(304, "gain_sub2_lp", "Audio/Sink"));
        g
    }

    /// Build a graph with USBStreamer and some links to it.
    fn graph_with_usb_links() -> GraphState {
        use crate::graph::{TrackedLink, TrackedPort};

        let mut g = graph_all_present();

        // Add USBStreamer node.
        g.add_node(make_node(
            400,
            "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0",
            "Audio/Sink",
        ));
        // Add USBStreamer ports.
        for ch in 0..4u32 {
            g.add_port(TrackedPort {
                id: 40000 + ch,
                node_id: 400,
                name: format!("playback_AUX{}", ch),
                direction: "in".to_string(),
                properties: HashMap::new(),
            });
        }

        // Add convolver-out ports.
        for ch in 0..4u32 {
            g.add_port(TrackedPort {
                id: 20000 + ch,
                node_id: 200,
                name: format!("output_AUX{}", ch),
                direction: "out".to_string(),
                properties: HashMap::new(),
            });
        }

        // Add links: convolver-out → USBStreamer.
        for ch in 0..4u32 {
            g.add_link(TrackedLink {
                id: 1000 + ch,
                output_node: 200,
                output_port: 20000 + ch,
                input_node: 400,
                input_port: 40000 + ch,
            });
        }

        g
    }

    // -----------------------------------------------------------------------
    // Basic state
    // -----------------------------------------------------------------------

    #[test]
    fn new_watchdog_is_not_latched() {
        let wd = Watchdog::new();
        assert!(!wd.is_latched());
        assert!(wd.missing_at_latch().is_empty());
    }

    // -----------------------------------------------------------------------
    // All present — no action
    // -----------------------------------------------------------------------

    #[test]
    fn all_nodes_present_returns_all_present() {
        let mut wd = Watchdog::new();
        let g = graph_all_present();
        assert_eq!(wd.check(&g), WatchdogAction::AllPresent);
        assert!(!wd.is_latched());
    }

    // -----------------------------------------------------------------------
    // Convolver disappears — primary mute path
    // -----------------------------------------------------------------------

    #[test]
    fn convolver_disappears_triggers_gain_mute() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();
        g.remove_node(100); // Remove pi4audio-convolver

        let action = wd.check(&g);
        assert!(wd.is_latched());

        match action {
            WatchdogAction::SetGainMute { gain_nodes } => {
                assert_eq!(gain_nodes.len(), 4);
                let names: Vec<&str> = gain_nodes.iter().map(|(_, n)| n.as_str()).collect();
                assert!(names.contains(&"gain_left_hp"));
                assert!(names.contains(&"gain_right_hp"));
                assert!(names.contains(&"gain_sub1_lp"));
                assert!(names.contains(&"gain_sub2_lp"));
            }
            other => panic!("expected SetGainMute, got {:?}", other),
        }
    }

    #[test]
    fn convolver_out_disappears_triggers_gain_mute() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();
        g.remove_node(200); // Remove pi4audio-convolver-out

        let action = wd.check(&g);
        assert!(wd.is_latched());
        assert!(matches!(action, WatchdogAction::SetGainMute { .. }));
        assert!(wd.missing_at_latch().contains(&"pi4audio-convolver-out".to_string()));
    }

    // -----------------------------------------------------------------------
    // Gain node disappears — triggers mute (it's a monitored node)
    // -----------------------------------------------------------------------

    #[test]
    fn single_gain_node_disappears_triggers_mute() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();
        g.remove_node(301); // Remove gain_left_hp

        let action = wd.check(&g);
        assert!(wd.is_latched());

        match action {
            WatchdogAction::SetGainMute { gain_nodes } => {
                // 3 remaining gain nodes can still be muted.
                assert_eq!(gain_nodes.len(), 3);
                let names: Vec<&str> = gain_nodes.iter().map(|(_, n)| n.as_str()).collect();
                assert!(!names.contains(&"gain_left_hp")); // this one is gone
                assert!(names.contains(&"gain_right_hp"));
            }
            other => panic!("expected SetGainMute, got {:?}", other),
        }
    }

    // -----------------------------------------------------------------------
    // All gain nodes disappear — fallback to link destruction
    // -----------------------------------------------------------------------

    #[test]
    fn all_gain_nodes_gone_triggers_usb_link_destroy() {
        let mut wd = Watchdog::new();
        let mut g = graph_with_usb_links();

        // Remove all gain nodes AND the convolver (triggering the watchdog).
        g.remove_node(100); // convolver
        g.remove_node(200); // convolver-out
        g.remove_node(301); // gain_left_hp
        g.remove_node(302); // gain_right_hp
        g.remove_node(303); // gain_sub1_lp
        g.remove_node(304); // gain_sub2_lp

        let action = wd.check(&g);
        assert!(wd.is_latched());

        match action {
            WatchdogAction::DestroyUsbLinks { link_ids } => {
                assert_eq!(link_ids.len(), 4);
                for id in &link_ids {
                    assert!(*id >= 1000 && *id <= 1003);
                }
            }
            other => panic!("expected DestroyUsbLinks, got {:?}", other),
        }
    }

    #[test]
    fn fallback_with_no_usb_links_returns_empty() {
        let mut wd = Watchdog::new();
        let mut g = GraphState::new();
        // No nodes at all — all monitored nodes missing, no gain nodes,
        // no USBStreamer links.

        let action = wd.check(&g);
        assert!(wd.is_latched());

        match action {
            WatchdogAction::DestroyUsbLinks { link_ids } => {
                assert!(link_ids.is_empty());
            }
            other => panic!("expected DestroyUsbLinks, got {:?}", other),
        }
    }

    // -----------------------------------------------------------------------
    // Latch behavior
    // -----------------------------------------------------------------------

    #[test]
    fn latched_watchdog_returns_already_latched() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();
        g.remove_node(100); // Trigger latch.

        let _ = wd.check(&g);
        assert!(wd.is_latched());

        // Second check with same state → AlreadyLatched.
        assert_eq!(wd.check(&g), WatchdogAction::AlreadyLatched);

        // Even if nodes come back → still latched.
        let g2 = graph_all_present();
        assert_eq!(wd.check(&g2), WatchdogAction::AlreadyLatched);
    }

    #[test]
    fn latch_persists_after_nodes_return() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();
        g.remove_node(100); // Trigger latch.
        let _ = wd.check(&g);
        assert!(wd.is_latched());

        // Nodes come back — still latched (requires explicit unlatch).
        let g2 = graph_all_present();
        assert_eq!(wd.check(&g2), WatchdogAction::AlreadyLatched);
        assert!(wd.is_latched());
    }

    // -----------------------------------------------------------------------
    // Unlatch
    // -----------------------------------------------------------------------

    #[test]
    fn unlatch_clears_latch_and_returns_gains() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();
        g.remove_node(100);
        let _ = wd.check(&g);

        // Store pre-mute gains.
        wd.store_pre_mute_gains(vec![
            ("gain_left_hp".to_string(), 0.001),
            ("gain_right_hp".to_string(), 0.001),
            ("gain_sub1_lp".to_string(), 0.000631),
            ("gain_sub2_lp".to_string(), 0.000631),
        ]);

        let gains = wd.unlatch();
        assert!(!wd.is_latched());
        assert!(gains.is_some());
        let gains = gains.unwrap();
        assert_eq!(gains.len(), 4);
        assert_eq!(gains[0], ("gain_left_hp".to_string(), 0.001));
    }

    #[test]
    fn unlatch_when_not_latched_returns_none() {
        let mut wd = Watchdog::new();
        assert!(wd.unlatch().is_none());
    }

    #[test]
    fn after_unlatch_watchdog_can_trigger_again() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();

        // First trigger.
        g.remove_node(100);
        let _ = wd.check(&g);
        assert!(wd.is_latched());

        // Unlatch.
        wd.unlatch();
        assert!(!wd.is_latched());

        // Nodes still missing — triggers again.
        let action = wd.check(&g);
        assert!(wd.is_latched());
        assert!(matches!(action, WatchdogAction::SetGainMute { .. }));
    }

    // -----------------------------------------------------------------------
    // Status
    // -----------------------------------------------------------------------

    #[test]
    fn status_reflects_state() {
        let mut wd = Watchdog::new();
        let status = wd.status();
        assert!(!status.latched);
        assert!(status.missing_nodes.is_empty());

        let mut g = graph_all_present();
        g.remove_node(100);
        let _ = wd.check(&g);

        let status = wd.status();
        assert!(status.latched);
        assert!(status.missing_nodes.contains(&"pi4audio-convolver".to_string()));
    }

    #[test]
    fn status_serializable() {
        let wd = Watchdog::new();
        let status = wd.status();
        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("\"latched\":false"));
    }

    // -----------------------------------------------------------------------
    // Missing node tracking
    // -----------------------------------------------------------------------

    #[test]
    fn missing_at_latch_tracks_all_missing_nodes() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();
        g.remove_node(100); // convolver
        g.remove_node(200); // convolver-out

        let _ = wd.check(&g);
        let missing = wd.missing_at_latch();
        assert!(missing.contains(&"pi4audio-convolver".to_string()));
        assert!(missing.contains(&"pi4audio-convolver-out".to_string()));
        assert_eq!(missing.len(), 2);
    }

    // -----------------------------------------------------------------------
    // Pre-mute gain storage
    // -----------------------------------------------------------------------

    #[test]
    fn pre_mute_gains_stored_and_cleared_on_unlatch() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();
        g.remove_node(100);
        let _ = wd.check(&g);

        wd.store_pre_mute_gains(vec![
            ("gain_left_hp".to_string(), 0.001),
        ]);
        assert_eq!(wd.pre_mute_gains().len(), 1);

        wd.unlatch();
        assert!(wd.pre_mute_gains().is_empty());
    }

    // -----------------------------------------------------------------------
    // Multiple monitored nodes missing simultaneously
    // -----------------------------------------------------------------------

    #[test]
    fn multiple_nodes_missing_still_single_latch() {
        let mut wd = Watchdog::new();
        let mut g = graph_all_present();
        g.remove_node(100); // convolver
        g.remove_node(301); // gain_left_hp

        let action = wd.check(&g);
        assert!(wd.is_latched());

        // Should still produce a mute action (3 gain nodes remain).
        match action {
            WatchdogAction::SetGainMute { gain_nodes } => {
                assert_eq!(gain_nodes.len(), 3);
            }
            other => panic!("expected SetGainMute, got {:?}", other),
        }

        // Second check → already latched.
        assert_eq!(wd.check(&g), WatchdogAction::AlreadyLatched);
    }
}
