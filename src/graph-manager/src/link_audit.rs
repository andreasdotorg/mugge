//! Link audit — verify no links bypass the convolver/gain chain to reach
//! USBStreamer speaker output ports directly (T-044-3).
//!
//! This is a safety layer that complements the reconciliation engine.
//! The reconciler manages desired links and destroys stale ones on known
//! nodes. The link audit enforces a stricter invariant: **only the
//! convolver output node may link to USBStreamer speaker channels
//! (playback_AUX0..AUX{N-1}, where N = num_speaker_channels).** Any
//! other source linking to those ports is an unauthorized bypass of
//! the convolver/gain chain.
//!
//! ## Safety rule
//!
//! USBStreamer playback ports AUX0..AUX{N-1} drive the amplifier chain
//! (speaker channels as defined by the active speaker layout). All audio
//! reaching these ports
//! MUST pass through the convolver (which includes the gain nodes with
//! safety attenuation). A bypass link could send unattenuated audio
//! directly to the amplifiers.
//!
//! Headphone/IEM ports (AUX4..AUX7) are NOT subject to this rule —
//! they legitimately receive direct links from Mixxx/Reaper in DJ/Live
//! modes.
//!
//! ## Design
//!
//! - `audit_links()` is a pure function — it reads GraphState and returns
//!   a list of violating link IDs. No PW API calls.
//! - Called from `run_reconcile()` in registry.rs after every graph
//!   mutation, alongside the watchdog check.
//! - Violating links are destroyed via `registry.destroy_global()`.
//! - A `GraphEvent::LinkAuditViolation` push event is emitted.
//!
//! ## Thread model
//!
//! Same as watchdog: runs on the PW main loop thread, single-threaded.

use crate::graph::GraphState;
use crate::routing::NodeMatch;

/// USBStreamer playback node name prefix.
const USBSTREAMER_OUT_PREFIX: &str = "alsa_output.usb-MiniDSP_USBStreamer";

/// Convolver output node name (the only authorized source for speaker ports).
const CONVOLVER_OUT: &str = "pi4audio-convolver-out";

/// Default number of speaker channels (2-way layout).
const DEFAULT_SPEAKER_CHANNELS: u32 = 4;

/// Generate the list of protected speaker port names for N speaker channels.
fn speaker_ports(num_speaker_channels: u32) -> Vec<String> {
    (0..num_speaker_channels)
        .map(|ch| format!("playback_AUX{}", ch))
        .collect()
}

/// Result of a link audit: a violating link that bypasses the convolver.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditViolation {
    /// PW link ID to destroy.
    pub link_id: u32,
    /// Name of the unauthorized source node.
    pub source_node: String,
    /// Source port name.
    pub source_port: String,
    /// USBStreamer port being bypassed to.
    pub target_port: String,
}

/// Audit all links in the graph for convolver bypass violations,
/// using the default 4-channel speaker layout.
///
/// Convenience wrapper around `audit_links_for()`.
pub fn audit_links(graph: &GraphState) -> Vec<AuditViolation> {
    audit_links_for(graph, DEFAULT_SPEAKER_CHANNELS)
}

/// Audit all links in the graph for convolver bypass violations.
///
/// Returns a list of violating links: any link where the input (sink)
/// port is a USBStreamer speaker port (AUX0..AUX{N-1}) and the output
/// (source) node is NOT `pi4audio-convolver-out`.
///
/// `num_speaker_channels` determines which USBStreamer ports are protected.
/// For 2-way: 4 (AUX0..AUX3). For 3-way: 6 (AUX0..AUX5).
///
/// This is a pure function — no PW API calls.
pub fn audit_links_for(graph: &GraphState, num_speaker_channels: u32) -> Vec<AuditViolation> {
    let usb_matcher = NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string());
    let protected_ports = speaker_ports(num_speaker_channels);

    let mut violations = Vec::new();

    for link in graph.links() {
        // Check if the link's input (sink) node is the USBStreamer.
        let input_node = match graph.node(link.input_node) {
            Some(n) => n,
            None => continue,
        };

        if !usb_matcher.matches(&input_node.name) {
            continue;
        }

        // Check if the input port is a speaker port (AUX0..AUX{N-1}).
        let input_port = match graph.port(link.input_port) {
            Some(p) => p,
            None => continue,
        };

        if !protected_ports.iter().any(|p| p == &input_port.name) {
            continue; // Headphone/IEM port — not protected.
        }

        // Check if the output (source) node is the convolver.
        let output_node = match graph.node(link.output_node) {
            Some(n) => n,
            None => continue,
        };

        if output_node.name == CONVOLVER_OUT {
            continue; // Authorized link.
        }

        // Violation: non-convolver source linking to speaker port.
        let source_port_name = graph
            .port(link.output_port)
            .map(|p| p.name.clone())
            .unwrap_or_else(|| link.output_port.to_string());

        violations.push(AuditViolation {
            link_id: link.id,
            source_node: output_node.name.clone(),
            source_port: source_port_name,
            target_port: input_port.name.clone(),
        });
    }

    violations
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::{GraphState, TrackedLink, TrackedNode, TrackedPort};
    use std::collections::HashMap;

    fn make_node(id: u32, name: &str, class: &str) -> TrackedNode {
        TrackedNode {
            id,
            name: name.to_string(),
            media_class: class.to_string(),
            properties: HashMap::new(),
        }
    }

    fn make_port(id: u32, node_id: u32, name: &str, direction: &str) -> TrackedPort {
        TrackedPort {
            id,
            node_id,
            name: name.to_string(),
            direction: direction.to_string(),
            properties: HashMap::new(),
        }
    }

    fn make_link(
        id: u32,
        out_node: u32,
        out_port: u32,
        in_node: u32,
        in_port: u32,
    ) -> TrackedLink {
        TrackedLink {
            id,
            output_node: out_node,
            output_port: out_port,
            input_node: in_node,
            input_port: in_port,
        }
    }

    /// Build a graph with convolver-out and USBStreamer, with legitimate
    /// convolver→USBStreamer speaker links.
    fn graph_with_legitimate_links() -> GraphState {
        let mut g = GraphState::new();

        // Convolver output node.
        g.add_node(make_node(
            200,
            "pi4audio-convolver-out",
            "Stream/Output/Audio",
        ));
        for ch in 0..4u32 {
            g.add_port(make_port(
                20000 + ch,
                200,
                &format!("output_AUX{}", ch),
                "out",
            ));
        }

        // USBStreamer playback node.
        g.add_node(make_node(
            300,
            "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0",
            "Audio/Sink",
        ));
        for ch in 0..8u32 {
            g.add_port(make_port(
                30000 + ch,
                300,
                &format!("playback_AUX{}", ch),
                "in",
            ));
        }

        // Legitimate links: convolver-out → USBStreamer ch 0-3.
        for ch in 0..4u32 {
            g.add_link(make_link(
                1000 + ch,
                200,
                20000 + ch,
                300,
                30000 + ch,
            ));
        }

        g
    }

    // -----------------------------------------------------------------------
    // No violations
    // -----------------------------------------------------------------------

    #[test]
    fn legitimate_links_produce_no_violations() {
        let g = graph_with_legitimate_links();
        let violations = audit_links(&g);
        assert!(violations.is_empty());
    }

    #[test]
    fn empty_graph_produces_no_violations() {
        let g = GraphState::new();
        let violations = audit_links(&g);
        assert!(violations.is_empty());
    }

    #[test]
    fn headphone_bypass_not_flagged() {
        // Mixxx → USBStreamer AUX4 (headphone L) is legitimate.
        let mut g = graph_with_legitimate_links();

        g.add_node(make_node(400, "Mixxx", "Stream/Output/Audio"));
        g.add_port(make_port(40002, 400, "out_2", "out"));

        // Mixxx → USBStreamer AUX4 (headphone, not speaker).
        g.add_link(make_link(2000, 400, 40002, 300, 30004));

        let violations = audit_links(&g);
        assert!(violations.is_empty());
    }

    #[test]
    fn iem_bypass_not_flagged() {
        // Reaper → USBStreamer AUX6 (IEM L) is legitimate.
        let mut g = graph_with_legitimate_links();

        g.add_node(make_node(500, "REAPER", "Stream/Output/Audio"));
        g.add_port(make_port(50006, 500, "out7", "out"));

        // Reaper → USBStreamer AUX6 (IEM, not speaker).
        g.add_link(make_link(2000, 500, 50006, 300, 30006));

        let violations = audit_links(&g);
        assert!(violations.is_empty());
    }

    // -----------------------------------------------------------------------
    // Bypass violations
    // -----------------------------------------------------------------------

    #[test]
    fn direct_app_to_speaker_port_is_violation() {
        // Mixxx → USBStreamer AUX0 (speaker) bypasses convolver.
        let mut g = graph_with_legitimate_links();

        g.add_node(make_node(400, "Mixxx", "Stream/Output/Audio"));
        g.add_port(make_port(40000, 400, "out_0", "out"));

        // Bypass link: Mixxx → USBStreamer AUX0 (speaker).
        g.add_link(make_link(2000, 400, 40000, 300, 30000));

        let violations = audit_links(&g);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].link_id, 2000);
        assert_eq!(violations[0].source_node, "Mixxx");
        assert_eq!(violations[0].source_port, "out_0");
        assert_eq!(violations[0].target_port, "playback_AUX0");
    }

    #[test]
    fn reaper_to_speaker_port_is_violation() {
        // Reaper → USBStreamer AUX1 bypasses convolver.
        let mut g = graph_with_legitimate_links();

        g.add_node(make_node(500, "REAPER", "Stream/Output/Audio"));
        g.add_port(make_port(50001, 500, "out1", "out"));

        g.add_link(make_link(2000, 500, 50001, 300, 30001));

        let violations = audit_links(&g);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].source_node, "REAPER");
        assert_eq!(violations[0].target_port, "playback_AUX1");
    }

    #[test]
    fn unknown_app_to_speaker_port_is_violation() {
        // Some rogue application → USBStreamer AUX2.
        let mut g = graph_with_legitimate_links();

        g.add_node(make_node(999, "rogue-app", "Stream/Output/Audio"));
        g.add_port(make_port(99900, 999, "output_0", "out"));

        g.add_link(make_link(2000, 999, 99900, 300, 30002));

        let violations = audit_links(&g);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].source_node, "rogue-app");
        assert_eq!(violations[0].target_port, "playback_AUX2");
    }

    #[test]
    fn multiple_violations_detected() {
        // Two different apps bypassing to different speaker ports.
        let mut g = graph_with_legitimate_links();

        g.add_node(make_node(400, "Mixxx", "Stream/Output/Audio"));
        g.add_port(make_port(40000, 400, "out_0", "out"));
        g.add_port(make_port(40001, 400, "out_1", "out"));

        // Bypass to AUX0 and AUX3.
        g.add_link(make_link(2000, 400, 40000, 300, 30000));
        g.add_link(make_link(2001, 400, 40001, 300, 30003));

        let violations = audit_links(&g);
        assert_eq!(violations.len(), 2);
        let ids: Vec<u32> = violations.iter().map(|v| v.link_id).collect();
        assert!(ids.contains(&2000));
        assert!(ids.contains(&2001));
    }

    #[test]
    fn all_four_speaker_ports_protected() {
        // Verify each speaker port (AUX0..3) triggers a violation.
        for ch in 0..4u32 {
            let mut g = graph_with_legitimate_links();

            g.add_node(make_node(999, "rogue", "Stream/Output/Audio"));
            g.add_port(make_port(99900, 999, "output_0", "out"));

            g.add_link(make_link(2000, 999, 99900, 300, 30000 + ch));

            let violations = audit_links(&g);
            assert_eq!(
                violations.len(),
                1,
                "Expected violation for speaker port AUX{}, got {:?}",
                ch,
                violations,
            );
            assert_eq!(
                violations[0].target_port,
                format!("playback_AUX{}", ch),
            );
        }
    }

    #[test]
    fn aux4_through_aux7_not_protected() {
        // Verify headphone/IEM ports (AUX4..7) do NOT trigger violations
        // under the default 4-channel audit.
        for ch in 4..8u32 {
            let mut g = graph_with_legitimate_links();

            g.add_node(make_node(999, "rogue", "Stream/Output/Audio"));
            g.add_port(make_port(99900, 999, "output_0", "out"));

            g.add_link(make_link(2000, 999, 99900, 300, 30000 + ch));

            let violations = audit_links(&g);
            assert!(
                violations.is_empty(),
                "AUX{} should not be protected, got {:?}",
                ch,
                violations,
            );
        }
    }

    // -----------------------------------------------------------------------
    // 6-channel (3-way) audit
    // -----------------------------------------------------------------------

    #[test]
    fn six_channel_audit_protects_aux0_through_aux5() {
        // With 6 speaker channels, AUX0..AUX5 should be protected.
        for ch in 0..6u32 {
            let mut g = graph_with_legitimate_links();

            g.add_node(make_node(999, "rogue", "Stream/Output/Audio"));
            g.add_port(make_port(99900, 999, "output_0", "out"));

            g.add_link(make_link(2000, 999, 99900, 300, 30000 + ch));

            let violations = audit_links_for(&g, 6);
            assert_eq!(
                violations.len(),
                1,
                "AUX{} should be protected with 6-channel audit, got {:?}",
                ch,
                violations,
            );
        }
    }

    #[test]
    fn six_channel_audit_does_not_protect_aux6_through_aux7() {
        // With 6 speaker channels, AUX6..AUX7 (headphones) should NOT be protected.
        for ch in 6..8u32 {
            let mut g = graph_with_legitimate_links();

            g.add_node(make_node(999, "rogue", "Stream/Output/Audio"));
            g.add_port(make_port(99900, 999, "output_0", "out"));

            g.add_link(make_link(2000, 999, 99900, 300, 30000 + ch));

            let violations = audit_links_for(&g, 6);
            assert!(
                violations.is_empty(),
                "AUX{} should not be protected with 6-channel audit, got {:?}",
                ch,
                violations,
            );
        }
    }

    // -----------------------------------------------------------------------
    // Edge cases
    // -----------------------------------------------------------------------

    #[test]
    fn violation_with_missing_output_port() {
        // Link references a port that's not in the graph (orphaned link).
        // Should still detect the violation based on node and input port.
        let mut g = graph_with_legitimate_links();

        g.add_node(make_node(999, "rogue", "Stream/Output/Audio"));
        // Deliberately NOT adding port 99900 to the graph.

        g.add_link(make_link(2000, 999, 99900, 300, 30000));

        let violations = audit_links(&g);
        assert_eq!(violations.len(), 1);
        // Source port name falls back to the port ID string.
        assert_eq!(violations[0].source_port, "99900");
    }

    #[test]
    fn link_to_missing_node_ignored() {
        // Link references a node that's not in the graph.
        let mut g = graph_with_legitimate_links();

        // Link from unknown node 999 (not in graph) to USBStreamer.
        g.add_link(make_link(2000, 999, 99900, 300, 30000));

        // Node 999 is not in the graph, so audit can't determine the
        // source node name — the link is skipped (we can't meaningfully
        // report on it without knowing the source).
        let violations = audit_links(&g);
        assert!(violations.is_empty());
    }

    #[test]
    fn link_to_non_usbstreamer_node_ignored() {
        // Link to a different Audio/Sink that is NOT the USBStreamer.
        let mut g = graph_with_legitimate_links();

        g.add_node(make_node(888, "some-other-sink", "Audio/Sink"));
        g.add_port(make_port(88800, 888, "playback_AUX0", "in"));

        g.add_node(make_node(999, "some-source", "Stream/Output/Audio"));
        g.add_port(make_port(99900, 999, "output_0", "out"));

        // Link to a non-USBStreamer sink — not our concern.
        g.add_link(make_link(2000, 999, 99900, 888, 88800));

        let violations = audit_links(&g);
        assert!(violations.is_empty());
    }

    #[test]
    fn convolver_links_coexist_with_violation() {
        // Legitimate convolver links exist alongside a bypass violation.
        // The legitimate links should not be flagged.
        let mut g = graph_with_legitimate_links();

        g.add_node(make_node(999, "rogue", "Stream/Output/Audio"));
        g.add_port(make_port(99900, 999, "output_0", "out"));

        // One bypass link alongside 4 legitimate convolver links.
        g.add_link(make_link(2000, 999, 99900, 300, 30000));

        let violations = audit_links(&g);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].link_id, 2000);
        // Verify the legitimate links are NOT in the violations.
        for v in &violations {
            assert!(v.link_id >= 2000);
        }
    }
}
