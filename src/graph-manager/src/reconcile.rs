//! Reconciliation engine — diffs desired links vs actual graph state and
//! produces link actions (create/destroy).
//!
//! This is the core of GraphManager's session management. On every registry
//! event (node/port/link appear/disappear), the reconciler runs:
//!
//! 1. For each DesiredLink in the active mode: find matching nodes and
//!    ports in GraphState. If link is missing → Create.
//! 2. For each existing link owned by GraphManager: if NOT in the desired
//!    set → Destroy.
//!
//! ## Ownership
//!
//! GraphManager only creates/destroys links where at least one endpoint
//! node matches a NodeMatch in the routing table (any mode). PipeWire-
//! internal links (device ↔ driver, clock, etc.) are invisible to
//! reconciliation.
//!
//! ## Idempotency
//!
//! Reconciliation is idempotent: calling it multiple times with the same
//! graph state and mode produces the same actions. Missing ports are
//! treated as "skip" (not error), so rapid events during node startup
//! converge naturally as ports appear.
//!
//! ## Thread model
//!
//! Runs synchronously on the PW main loop thread. The reconcile function
//! is pure (no PW API calls) — it returns a Vec<LinkAction> that the
//! caller applies. This makes the logic fully testable without PipeWire.

use crate::graph::GraphState;
use crate::routing::{DesiredLink, Mode, NodeMatch, RoutingTable};

/// An action to apply to the PW graph.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LinkAction {
    /// Create a link between two ports.
    Create {
        output_node_id: u32,
        output_port_id: u32,
        input_node_id: u32,
        input_port_id: u32,
        description: String,
    },
    /// Destroy an existing link by its PW global ID.
    Destroy {
        link_id: u32,
        description: String,
    },
}

/// Find a node+port combination: searches all nodes matching the
/// NodeMatch and returns the first (node_id, port_id) where the node
/// actually has the requested port.
///
/// This is the GM-13 fix. The previous implementation used `find_node`
/// (first matching node) + `find_port` (port on that node) — which
/// fails when multiple nodes match a Prefix pattern (e.g., a JACK
/// client registering separate input and output nodes under the same
/// name prefix). The first node might not have the requested port,
/// causing the desired link to fail resolution even though the correct
/// node+port exists in the graph.
fn find_node_port(
    graph: &GraphState,
    matcher: &NodeMatch,
    port_name: &str,
) -> Option<(u32, u32)> {
    let nodes = graph.nodes_matching(|name| matcher.matches(name));
    for node in &nodes {
        let ports = graph.ports_for_node(node.id, port_name);
        if let Some(port) = ports.first() {
            return Some((node.id, port.id));
        }
    }
    None
}

/// Check if a node matches any NodeMatch in the routing table (any mode).
///
/// Used to determine link ownership: GraphManager only manages links
/// where at least one endpoint is a "known" node.
fn is_known_node(graph: &GraphState, node_id: u32, table: &RoutingTable) -> bool {
    let node = match graph.node(node_id) {
        Some(n) => n,
        None => return false,
    };
    for mode in Mode::ALL {
        for link in table.links_for(mode) {
            if link.output_node.matches(&node.name) || link.input_node.matches(&node.name) {
                return true;
            }
        }
    }
    false
}

/// Compute the set of link actions needed to reconcile the graph.
///
/// This is a pure function: it reads GraphState and RoutingTable, and
/// returns actions. No PW API calls. Fully testable.
///
/// # Arguments
/// * `graph` — Current PW graph state (nodes, ports, links).
/// * `table` — Routing table (all modes and their desired links).
/// * `mode` — Currently active operating mode.
///
/// # Returns
/// A list of actions to apply. Create actions come first (bring up
/// desired links), then Destroy actions (tear down unwanted links).
pub fn reconcile(graph: &GraphState, table: &RoutingTable, mode: Mode) -> Vec<LinkAction> {
    let mut actions = Vec::new();
    let desired = table.links_for(mode);

    // Phase 1: Identify links to CREATE.
    // For each desired link, check if it exists. If not, create it.
    let mut desired_port_pairs: Vec<(u32, u32)> = Vec::new();

    for dl in desired {
        match resolve_desired_link(graph, dl) {
            Some((out_node, out_port, in_node, in_port)) => {
                desired_port_pairs.push((out_port, in_port));
                if !graph.link_exists(out_port, in_port) {
                    actions.push(LinkAction::Create {
                        output_node_id: out_node,
                        output_port_id: out_port,
                        input_node_id: in_node,
                        input_port_id: in_port,
                        description: dl.to_string(),
                    });
                }
            }
            None => {
                if dl.optional {
                    log::debug!("Skipping optional link (endpoint missing): {}", dl);
                } else {
                    log::warn!("Required link endpoint missing (will retry): {}", dl);
                }
            }
        }
    }

    // Phase 2: Identify links to DESTROY.
    // For each existing link that GraphManager owns (at least one endpoint
    // is a known node), check if it's in the desired set. If not, destroy it.
    for link in graph.links() {
        let pair = (link.output_port, link.input_port);
        if desired_port_pairs.contains(&pair) {
            continue; // This link is desired, keep it.
        }
        // Check ownership: at least one endpoint must be a known node.
        if is_known_node(graph, link.output_node, table)
            || is_known_node(graph, link.input_node, table)
        {
            let desc = format!(
                "stale link id={} ({}:{} -> {}:{})",
                link.id, link.output_node, link.output_port,
                link.input_node, link.input_port,
            );
            actions.push(LinkAction::Destroy {
                link_id: link.id,
                description: desc,
            });
        }
    }

    actions
}

/// Resolve a DesiredLink to concrete PW port IDs.
///
/// Returns `Some((output_node_id, output_port_id, input_node_id, input_port_id))`
/// if both endpoints are found, or `None` if any endpoint is missing.
///
/// Uses `find_node_port` to search ALL matching nodes for the requested
/// port (GM-13 fix). This correctly handles JACK clients that register
/// multiple nodes under the same name prefix (e.g., separate input and
/// output nodes).
fn resolve_desired_link(
    graph: &GraphState,
    dl: &DesiredLink,
) -> Option<(u32, u32, u32, u32)> {
    let (out_node_id, out_port_id) = find_node_port(graph, &dl.output_node, &dl.output_port)?;
    let (in_node_id, in_port_id) = find_node_port(graph, &dl.input_node, &dl.input_port)?;
    Some((out_node_id, out_port_id, in_node_id, in_port_id))
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::{TrackedLink, TrackedNode, TrackedPort};
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

    fn make_link(id: u32, out_node: u32, out_port: u32, in_node: u32, in_port: u32) -> TrackedLink {
        TrackedLink {
            id,
            output_node: out_node,
            output_port: out_port,
            input_node: in_node,
            input_port: in_port,
        }
    }

    /// Build a minimal routing table with one mode and one link.
    fn one_link_table(
        out_node: &str,
        out_port: &str,
        in_node: &str,
        in_port: &str,
        optional: bool,
    ) -> RoutingTable {
        RoutingTable::from_entries(vec![(
            Mode::Monitoring,
            vec![DesiredLink {
                output_node: NodeMatch::Exact(out_node.to_string()),
                output_port: out_port.to_string(),
                input_node: NodeMatch::Exact(in_node.to_string()),
                input_port: in_port.to_string(),
                optional,
            }],
        )])
    }

    // -----------------------------------------------------------------------
    // Create actions
    // -----------------------------------------------------------------------

    #[test]
    fn creates_missing_link() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "src-node", "Stream/Output/Audio"));
        g.add_node(make_node(20, "sink-node", "Audio/Sink"));
        g.add_port(make_port(100, 10, "output_0", "out"));
        g.add_port(make_port(200, 20, "input_0", "in"));

        let table = one_link_table("src-node", "output_0", "sink-node", "input_0", false);
        let actions = reconcile(&g, &table, Mode::Monitoring);

        assert_eq!(actions.len(), 1);
        match &actions[0] {
            LinkAction::Create {
                output_port_id,
                input_port_id,
                ..
            } => {
                assert_eq!(*output_port_id, 100);
                assert_eq!(*input_port_id, 200);
            }
            _ => panic!("expected Create"),
        }
    }

    #[test]
    fn skips_existing_link() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "src-node", "Stream/Output/Audio"));
        g.add_node(make_node(20, "sink-node", "Audio/Sink"));
        g.add_port(make_port(100, 10, "output_0", "out"));
        g.add_port(make_port(200, 20, "input_0", "in"));
        g.add_link(make_link(500, 10, 100, 20, 200));

        let table = one_link_table("src-node", "output_0", "sink-node", "input_0", false);
        let actions = reconcile(&g, &table, Mode::Monitoring);

        // Link exists, no actions needed.
        assert!(actions.is_empty());
    }

    #[test]
    fn skips_optional_link_with_missing_node() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "src-node", "Stream/Output/Audio"));
        // sink-node is missing (e.g., UMIK-1 not plugged in).
        g.add_port(make_port(100, 10, "output_0", "out"));

        let table = one_link_table("src-node", "output_0", "sink-node", "input_0", true);
        let actions = reconcile(&g, &table, Mode::Monitoring);

        // Optional link, endpoint missing — skip, no error.
        assert!(actions.is_empty());
    }

    #[test]
    fn skips_required_link_with_missing_port() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "src-node", "Stream/Output/Audio"));
        g.add_node(make_node(20, "sink-node", "Audio/Sink"));
        g.add_port(make_port(100, 10, "output_0", "out"));
        // input_0 port not yet created (ports arriving in separate events).

        let table = one_link_table("src-node", "output_0", "sink-node", "input_0", false);
        let actions = reconcile(&g, &table, Mode::Monitoring);

        // Port missing — skip (will retry on next event).
        assert!(actions.is_empty());
    }

    // -----------------------------------------------------------------------
    // Destroy actions
    // -----------------------------------------------------------------------

    #[test]
    fn destroys_stale_link_with_known_endpoint() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "src-node", "Stream/Output/Audio"));
        g.add_node(make_node(20, "sink-node", "Audio/Sink"));
        g.add_port(make_port(100, 10, "output_0", "out"));
        g.add_port(make_port(200, 20, "input_0", "in"));
        // This link exists in the graph but is NOT in the desired set.
        g.add_link(make_link(500, 10, 100, 20, 200));

        // Empty desired set for this mode — the link should be destroyed.
        let table = RoutingTable::from_entries(vec![(
            Mode::Monitoring,
            vec![],
        )]);
        // But we need the nodes to be "known" — add a link to some mode.
        let table = RoutingTable::from_entries(vec![
            (Mode::Monitoring, vec![]),
            (
                Mode::Dj,
                vec![DesiredLink {
                    output_node: NodeMatch::Exact("src-node".to_string()),
                    output_port: "output_0".to_string(),
                    input_node: NodeMatch::Exact("other-sink".to_string()),
                    input_port: "input_0".to_string(),
                    optional: false,
                }],
            ),
        ]);

        let actions = reconcile(&g, &table, Mode::Monitoring);

        assert_eq!(actions.len(), 1);
        match &actions[0] {
            LinkAction::Destroy { link_id, .. } => assert_eq!(*link_id, 500),
            _ => panic!("expected Destroy"),
        }
    }

    #[test]
    fn ignores_link_between_unknown_nodes() {
        let mut g = GraphState::new();
        // Two nodes NOT in any routing table entry.
        g.add_node(make_node(10, "pw-driver-internal", "Audio/Source"));
        g.add_node(make_node(20, "alsa-adapter-internal", "Audio/Sink"));
        g.add_port(make_port(100, 10, "output_0", "out"));
        g.add_port(make_port(200, 20, "input_0", "in"));
        g.add_link(make_link(500, 10, 100, 20, 200));

        // Empty routing table — no known nodes at all.
        let table = RoutingTable::from_entries(vec![(Mode::Monitoring, vec![])]);
        let actions = reconcile(&g, &table, Mode::Monitoring);

        // Link between unknown nodes — leave it alone.
        assert!(actions.is_empty());
    }

    // -----------------------------------------------------------------------
    // Prefix matching
    // -----------------------------------------------------------------------

    #[test]
    fn prefix_match_finds_node() {
        let mut g = GraphState::new();
        g.add_node(make_node(
            10,
            "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0",
            "Audio/Sink",
        ));
        g.add_node(make_node(20, "pi4audio-convolver-out", "Stream/Output/Audio"));
        g.add_port(make_port(100, 20, "output_0", "out"));
        g.add_port(make_port(
            200,
            10,
            "playback_AUX0",
            "in",
        ));

        let table = RoutingTable::from_entries(vec![(
            Mode::Monitoring,
            vec![DesiredLink {
                output_node: NodeMatch::Exact("pi4audio-convolver-out".to_string()),
                output_port: "output_0".to_string(),
                input_node: NodeMatch::Prefix(
                    "alsa_output.usb-MiniDSP_USBStreamer".to_string(),
                ),
                input_port: "playback_AUX0".to_string(),
                optional: false,
            }],
        )]);

        let actions = reconcile(&g, &table, Mode::Monitoring);

        assert_eq!(actions.len(), 1);
        match &actions[0] {
            LinkAction::Create {
                output_port_id,
                input_port_id,
                ..
            } => {
                assert_eq!(*output_port_id, 100);
                assert_eq!(*input_port_id, 200);
            }
            _ => panic!("expected Create"),
        }
    }

    // -----------------------------------------------------------------------
    // Idempotency
    // -----------------------------------------------------------------------

    #[test]
    fn reconcile_is_idempotent() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "src-node", "Stream/Output/Audio"));
        g.add_node(make_node(20, "sink-node", "Audio/Sink"));
        g.add_port(make_port(100, 10, "output_0", "out"));
        g.add_port(make_port(200, 20, "input_0", "in"));

        let table = one_link_table("src-node", "output_0", "sink-node", "input_0", false);

        // First reconcile: should create.
        let actions1 = reconcile(&g, &table, Mode::Monitoring);
        assert_eq!(actions1.len(), 1);

        // Simulate the link being created.
        g.add_link(make_link(500, 10, 100, 20, 200));

        // Second reconcile: no actions (link exists).
        let actions2 = reconcile(&g, &table, Mode::Monitoring);
        assert!(actions2.is_empty());

        // Third reconcile: still no actions.
        let actions3 = reconcile(&g, &table, Mode::Monitoring);
        assert!(actions3.is_empty());
    }

    // -----------------------------------------------------------------------
    // Feedback loop regression (duplicate creation window)
    // -----------------------------------------------------------------------

    #[test]
    fn reconcile_before_link_in_graph_produces_create() {
        // Simulates the window between core.create_object() and the
        // registry global event: link NOT yet in GraphState, so reconcile
        // will produce another Create for the same port pair. The
        // apply_actions guard (link_proxies check) prevents the actual
        // duplicate PW call. This test documents the expected behavior
        // of the pure reconcile function.
        let mut g = GraphState::new();
        g.add_node(make_node(10, "src-node", "Stream/Output/Audio"));
        g.add_node(make_node(20, "sink-node", "Audio/Sink"));
        g.add_port(make_port(100, 10, "output_0", "out"));
        g.add_port(make_port(200, 20, "input_0", "in"));

        let table = one_link_table("src-node", "output_0", "sink-node", "input_0", false);

        // First reconcile: creates the link.
        let actions1 = reconcile(&g, &table, Mode::Monitoring);
        assert_eq!(actions1.len(), 1);

        // Link NOT added to graph yet (simulates the window before
        // the registry global event arrives).

        // Second reconcile: still wants to create (link not in graph).
        // The apply_actions guard prevents the actual duplicate.
        let actions2 = reconcile(&g, &table, Mode::Monitoring);
        assert_eq!(actions2.len(), 1);

        // Now the registry event arrives: link added to graph.
        g.add_link(make_link(500, 10, 100, 20, 200));

        // Third reconcile: no actions (link exists).
        let actions3 = reconcile(&g, &table, Mode::Monitoring);
        assert!(actions3.is_empty());
    }

    #[test]
    fn reconcile_after_new_port_during_link_window() {
        // Scenario: reconcile creates link A. Before the global event
        // for link A arrives, a new port appears for the same node,
        // triggering another reconcile. Without guards, this would
        // create a duplicate link A.
        let mut g = GraphState::new();
        g.add_node(make_node(10, "src-node", "Stream/Output/Audio"));
        g.add_node(make_node(20, "sink-node", "Audio/Sink"));
        g.add_port(make_port(100, 10, "output_0", "out"));
        g.add_port(make_port(200, 20, "input_0", "in"));

        let table = one_link_table("src-node", "output_0", "sink-node", "input_0", false);

        // First reconcile: produce Create.
        let actions1 = reconcile(&g, &table, Mode::Monitoring);
        assert_eq!(actions1.len(), 1);

        // New port appears (e.g., output_1 on same node), but link
        // NOT yet in graph. Reconcile fires again.
        g.add_port(make_port(101, 10, "output_1", "out"));
        let actions2 = reconcile(&g, &table, Mode::Monitoring);

        // Pure reconcile still says Create (it doesn't know about
        // pending creates). The apply_actions guard catches this.
        assert_eq!(actions2.len(), 1);
        assert!(matches!(&actions2[0], LinkAction::Create {
            output_port_id: 100,
            input_port_id: 200,
            ..
        }));
    }

    // -----------------------------------------------------------------------
    // Mode transition
    // -----------------------------------------------------------------------

    // -----------------------------------------------------------------------
    // GM-13: prefix match with multiple nodes (JACK client in/out nodes)
    // -----------------------------------------------------------------------

    #[test]
    fn gm13_prefix_match_picks_node_with_matching_port() {
        // Reproduces the GM-13 bug: a JACK client (e.g., Mixxx via pw-jack)
        // registers TWO nodes with the same prefix — one for outputs and
        // one for inputs. The old find_node() picked the first match
        // (HashMap iteration order), which might be the input node that
        // has no output ports. The link then failed to resolve even though
        // the correct node+port exists.
        let mut g = GraphState::new();

        // Mixxx input node (JACK capture) — has input ports only.
        g.add_node(make_node(10, "Mixxx", "Stream/Input/Audio"));
        g.add_port(make_port(100, 10, "in_0", "in"));
        g.add_port(make_port(101, 10, "in_1", "in"));

        // Mixxx output node (JACK playback) — has output ports.
        g.add_node(make_node(11, "Mixxx", "Stream/Output/Audio"));
        g.add_port(make_port(110, 11, "out_0", "out"));
        g.add_port(make_port(111, 11, "out_1", "out"));

        // Convolver input (sink).
        g.add_node(make_node(20, "pi4audio-convolver", "Audio/Sink"));
        g.add_port(make_port(200, 20, "playback_AUX0", "in"));

        let table = RoutingTable::from_entries(vec![(
            Mode::Dj,
            vec![DesiredLink {
                output_node: NodeMatch::Prefix("Mixxx".to_string()),
                output_port: "out_0".to_string(),
                input_node: NodeMatch::Exact("pi4audio-convolver".to_string()),
                input_port: "playback_AUX0".to_string(),
                optional: false,
            }],
        )]);

        let actions = reconcile(&g, &table, Mode::Dj);

        // Must create the link using the OUTPUT node (id=11), not the
        // input node (id=10) which has no "out_0" port.
        assert_eq!(actions.len(), 1, "expected 1 Create action, got {:?}", actions);
        match &actions[0] {
            LinkAction::Create {
                output_node_id,
                output_port_id,
                input_port_id,
                ..
            } => {
                assert_eq!(*output_node_id, 11, "should pick the output node");
                assert_eq!(*output_port_id, 110);
                assert_eq!(*input_port_id, 200);
            }
            _ => panic!("expected Create, got {:?}", actions[0]),
        }
    }

    #[test]
    fn gm13_prefix_match_input_side_picks_correct_node() {
        // Same as above but for the INPUT side: multiple nodes match the
        // input_node prefix, and only one has the requested input port.
        let mut g = GraphState::new();

        // Source node.
        g.add_node(make_node(10, "pi4audio-convolver-out", "Stream/Output/Audio"));
        g.add_port(make_port(100, 10, "output_AUX0", "out"));

        // USBStreamer output node (playback) — has playback ports.
        g.add_node(make_node(20, "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0", "Audio/Sink"));
        g.add_port(make_port(200, 20, "playback_AUX0", "in"));

        // USBStreamer node with a different suffix but same prefix — no playback ports.
        g.add_node(make_node(21, "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-1", "Audio/Sink"));
        // This node has different port names.
        g.add_port(make_port(210, 21, "monitor_AUX0", "out"));

        let table = RoutingTable::from_entries(vec![(
            Mode::Monitoring,
            vec![DesiredLink {
                output_node: NodeMatch::Exact("pi4audio-convolver-out".to_string()),
                output_port: "output_AUX0".to_string(),
                input_node: NodeMatch::Prefix("alsa_output.usb-MiniDSP_USBStreamer".to_string()),
                input_port: "playback_AUX0".to_string(),
                optional: false,
            }],
        )]);

        let actions = reconcile(&g, &table, Mode::Monitoring);

        assert_eq!(actions.len(), 1, "expected 1 Create action, got {:?}", actions);
        match &actions[0] {
            LinkAction::Create {
                input_node_id,
                input_port_id,
                ..
            } => {
                assert_eq!(*input_node_id, 20, "should pick node with playback_AUX0");
                assert_eq!(*input_port_id, 200);
            }
            _ => panic!("expected Create"),
        }
    }

    // -----------------------------------------------------------------------
    // GM-14: manually created links not destroyed when desired set resolves
    // -----------------------------------------------------------------------

    #[test]
    fn gm14_does_not_destroy_manually_created_desired_link() {
        // Reproduces the GM-14 consequence: during GM-12, links were created
        // manually with pw-link. If the reconciler failed to resolve the
        // desired link (GM-13 bug), it wouldn't include those port pairs
        // in desired_port_pairs, causing Phase 2 to mark the manually-created
        // link as "stale" and destroy it.
        //
        // With the GM-13 fix, the link resolves correctly, so the manually-
        // created link is recognized as desired and kept.
        let mut g = GraphState::new();

        // Two Mixxx nodes (JACK in/out) with same prefix.
        g.add_node(make_node(10, "Mixxx", "Stream/Input/Audio"));
        g.add_port(make_port(100, 10, "in_0", "in"));

        g.add_node(make_node(11, "Mixxx", "Stream/Output/Audio"));
        g.add_port(make_port(110, 11, "out_0", "out"));

        // Convolver.
        g.add_node(make_node(20, "pi4audio-convolver", "Audio/Sink"));
        g.add_port(make_port(200, 20, "playback_AUX0", "in"));

        // The correct link already exists (created manually with pw-link).
        g.add_link(make_link(500, 11, 110, 20, 200));

        let table = RoutingTable::from_entries(vec![(
            Mode::Dj,
            vec![DesiredLink {
                output_node: NodeMatch::Prefix("Mixxx".to_string()),
                output_port: "out_0".to_string(),
                input_node: NodeMatch::Exact("pi4audio-convolver".to_string()),
                input_port: "playback_AUX0".to_string(),
                optional: false,
            }],
        )]);

        let actions = reconcile(&g, &table, Mode::Dj);

        // The link exists and is desired — no actions needed.
        assert!(
            actions.is_empty(),
            "expected no actions (link is desired and exists), got {:?}",
            actions,
        );
    }

    #[test]
    fn gm13_all_desired_links_created_despite_duplicate_nodes() {
        // Full DJ scenario: Mixxx has two nodes matching the prefix.
        // All desired links for Master L/R to convolver should resolve.
        let mut g = GraphState::new();

        // Mixxx input node.
        g.add_node(make_node(10, "Mixxx", "Stream/Input/Audio"));
        g.add_port(make_port(100, 10, "in_0", "in"));
        g.add_port(make_port(101, 10, "in_1", "in"));

        // Mixxx output node.
        g.add_node(make_node(11, "Mixxx", "Stream/Output/Audio"));
        g.add_port(make_port(110, 11, "out_0", "out"));
        g.add_port(make_port(111, 11, "out_1", "out"));

        // Convolver.
        g.add_node(make_node(20, "pi4audio-convolver", "Audio/Sink"));
        g.add_port(make_port(200, 20, "playback_AUX0", "in"));
        g.add_port(make_port(201, 20, "playback_AUX1", "in"));

        let table = RoutingTable::from_entries(vec![(
            Mode::Dj,
            vec![
                DesiredLink {
                    output_node: NodeMatch::Prefix("Mixxx".to_string()),
                    output_port: "out_0".to_string(),
                    input_node: NodeMatch::Exact("pi4audio-convolver".to_string()),
                    input_port: "playback_AUX0".to_string(),
                    optional: false,
                },
                DesiredLink {
                    output_node: NodeMatch::Prefix("Mixxx".to_string()),
                    output_port: "out_1".to_string(),
                    input_node: NodeMatch::Exact("pi4audio-convolver".to_string()),
                    input_port: "playback_AUX1".to_string(),
                    optional: false,
                },
            ],
        )]);

        let actions = reconcile(&g, &table, Mode::Dj);

        // Both links should be created (2 Create actions).
        let creates: Vec<_> = actions
            .iter()
            .filter(|a| matches!(a, LinkAction::Create { .. }))
            .collect();
        assert_eq!(creates.len(), 2, "expected 2 Create actions, got {:?}", actions);
    }

    // -----------------------------------------------------------------------
    // Mode transition
    // -----------------------------------------------------------------------

    #[test]
    fn mode_switch_creates_and_destroys() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "src-a", "Stream/Output/Audio"));
        g.add_node(make_node(20, "sink-a", "Audio/Sink"));
        g.add_node(make_node(30, "src-b", "Stream/Output/Audio"));
        g.add_node(make_node(40, "sink-b", "Audio/Sink"));
        g.add_port(make_port(100, 10, "output_0", "out"));
        g.add_port(make_port(200, 20, "input_0", "in"));
        g.add_port(make_port(300, 30, "output_0", "out"));
        g.add_port(make_port(400, 40, "input_0", "in"));

        // Mode A uses src-a → sink-a, Mode B uses src-b → sink-b.
        let table = RoutingTable::from_entries(vec![
            (
                Mode::Monitoring,
                vec![DesiredLink {
                    output_node: NodeMatch::Exact("src-a".to_string()),
                    output_port: "output_0".to_string(),
                    input_node: NodeMatch::Exact("sink-a".to_string()),
                    input_port: "input_0".to_string(),
                    optional: false,
                }],
            ),
            (
                Mode::Dj,
                vec![DesiredLink {
                    output_node: NodeMatch::Exact("src-b".to_string()),
                    output_port: "output_0".to_string(),
                    input_node: NodeMatch::Exact("sink-b".to_string()),
                    input_port: "input_0".to_string(),
                    optional: false,
                }],
            ),
        ]);

        // Start in Monitoring: create link A.
        let actions = reconcile(&g, &table, Mode::Monitoring);
        assert_eq!(actions.len(), 1);
        assert!(matches!(&actions[0], LinkAction::Create { output_port_id: 100, .. }));

        // Simulate link A created.
        g.add_link(make_link(500, 10, 100, 20, 200));

        // Switch to DJ: should destroy link A and create link B.
        let actions = reconcile(&g, &table, Mode::Dj);
        assert_eq!(actions.len(), 2);

        let creates: Vec<_> = actions.iter().filter(|a| matches!(a, LinkAction::Create { .. })).collect();
        let destroys: Vec<_> = actions.iter().filter(|a| matches!(a, LinkAction::Destroy { .. })).collect();
        assert_eq!(creates.len(), 1);
        assert_eq!(destroys.len(), 1);
    }
}
