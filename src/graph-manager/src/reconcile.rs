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

    // ===================================================================
    // S-1 through S-4: DoD #7 regression tests (QE-specified scenarios)
    // ===================================================================

    // -------------------------------------------------------------------
    // Helper: build a production-like graph with all nodes and ports
    // -------------------------------------------------------------------

    /// Build a GraphState with all production nodes and ports needed
    /// to fully resolve links for the specified modes. Uses realistic
    /// PW node names matching the production routing table constants.
    ///
    /// Node ID allocation scheme (deterministic, avoids collisions):
    ///   Convolver-in:  100     Convolver-out: 200
    ///   USBStreamer:    300     Mixxx-out:     400
    ///   Mixxx-in:      401     Reaper-out:    500
    ///   Reaper-in:     501     ADA8200-in:    600
    ///   Signal-gen:    700     Signal-gen-cap: 800
    ///   UMIK-1:        900
    ///
    /// Port IDs: node_id * 100 + zero-based-port-index.
    fn build_production_graph() -> GraphState {
        let mut g = GraphState::new();

        // -- Convolver input (Audio/Sink): 4 playback ports --
        g.add_node(make_node(100, "pi4audio-convolver", "Audio/Sink"));
        for ch in 0..4u32 {
            g.add_port(make_port(
                10000 + ch, 100,
                &format!("playback_AUX{}", ch), "in",
            ));
        }

        // -- Convolver output (Stream/Output/Audio): 4 output ports --
        g.add_node(make_node(200, "pi4audio-convolver-out", "Stream/Output/Audio"));
        for ch in 0..4u32 {
            g.add_port(make_port(
                20000 + ch, 200,
                &format!("output_AUX{}", ch), "out",
            ));
        }

        // -- USBStreamer playback (Audio/Sink): 8 playback ports --
        g.add_node(make_node(
            300,
            "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0",
            "Audio/Sink",
        ));
        for ch in 0..8u32 {
            g.add_port(make_port(
                30000 + ch, 300,
                &format!("playback_AUX{}", ch), "in",
            ));
        }

        // -- Mixxx output (Stream/Output/Audio): 4 ports (master L/R, HP L/R) --
        g.add_node(make_node(400, "Mixxx", "Stream/Output/Audio"));
        for ch in 0..4u32 {
            g.add_port(make_port(
                40000 + ch, 400,
                &format!("out_{}", ch), "out",
            ));
        }

        // -- Mixxx input (Stream/Input/Audio): 2 ports --
        g.add_node(make_node(401, "Mixxx", "Stream/Input/Audio"));
        g.add_port(make_port(40100, 401, "in_0", "in"));
        g.add_port(make_port(40101, 401, "in_1", "in"));

        // -- Reaper output (Stream/Output/Audio): 8 ports --
        g.add_node(make_node(500, "REAPER", "Stream/Output/Audio"));
        for ch in 1..=8u32 {
            g.add_port(make_port(
                50000 + ch, 500,
                &format!("out{}", ch), "out",
            ));
        }

        // -- Reaper input (Stream/Input/Audio): 8 ports --
        g.add_node(make_node(501, "REAPER", "Stream/Input/Audio"));
        for ch in 1..=8u32 {
            g.add_port(make_port(
                50100 + ch, 501,
                &format!("in{}", ch), "in",
            ));
        }

        // -- ADA8200 capture (Audio/Source): 8 capture ports --
        g.add_node(make_node(600, "ada8200-in", "Audio/Source"));
        for ch in 0..8u32 {
            g.add_port(make_port(
                60000 + ch, 600,
                &format!("capture_AUX{}", ch), "out",
            ));
        }

        // -- Signal-gen playback: 4 output ports --
        g.add_node(make_node(700, "pi4audio-signal-gen", "Stream/Output/Audio"));
        for ch in 0..4u32 {
            g.add_port(make_port(
                70000 + ch, 700,
                &format!("output_AUX{}", ch), "out",
            ));
        }

        // -- Signal-gen capture: 1 input port (mono) --
        g.add_node(make_node(800, "pi4audio-signal-gen-capture", "Stream/Input/Audio"));
        g.add_port(make_port(80000, 800, "input_MONO", "in"));

        // -- UMIK-1 capture: 1 port (mono) --
        g.add_node(make_node(
            900,
            "alsa_input.usb-miniDSP_UMIK-1-00.mono-fallback",
            "Audio/Source",
        ));
        g.add_port(make_port(90000, 900, "capture_MONO", "out"));

        g
    }

    /// Count Create actions in a list.
    fn count_creates(actions: &[LinkAction]) -> usize {
        actions.iter().filter(|a| matches!(a, LinkAction::Create { .. })).count()
    }

    /// Count Destroy actions in a list.
    fn count_destroys(actions: &[LinkAction]) -> usize {
        actions.iter().filter(|a| matches!(a, LinkAction::Destroy { .. })).count()
    }

    /// Simulate applying Create actions by adding corresponding links
    /// to the graph. Uses link_id starting from `next_link_id`.
    /// Returns the next available link ID.
    fn apply_creates(g: &mut GraphState, actions: &[LinkAction], mut next_link_id: u32) -> u32 {
        for action in actions {
            if let LinkAction::Create {
                output_node_id,
                output_port_id,
                input_node_id,
                input_port_id,
                ..
            } = action
            {
                g.add_link(make_link(
                    next_link_id,
                    *output_node_id, *output_port_id,
                    *input_node_id, *input_port_id,
                ));
                next_link_id += 1;
            }
        }
        next_link_id
    }

    /// Simulate applying Destroy actions by removing links from the graph.
    fn apply_destroys(g: &mut GraphState, actions: &[LinkAction]) {
        for action in actions {
            if let LinkAction::Destroy { link_id, .. } = action {
                g.remove_link(*link_id);
            }
        }
    }

    // -------------------------------------------------------------------
    // S-1: USB hotplug cycle
    // -------------------------------------------------------------------

    #[test]
    fn s1_usb_hotplug_cycle() {
        // Build full DJ topology, remove USBStreamer (simulating unplug),
        // reconcile, re-add USBStreamer with new PW IDs, reconcile.
        let table = RoutingTable::production();
        let mut g = build_production_graph();

        // Step 1: Reconcile in DJ mode — should create all 12 DJ links.
        let actions = reconcile(&g, &table, Mode::Dj);
        assert_eq!(count_creates(&actions), 12, "DJ mode: expected 12 creates");
        assert_eq!(count_destroys(&actions), 0, "DJ mode: no destroys initially");

        // Simulate: apply all creates.
        let next_id = apply_creates(&mut g, &actions, 1000);

        // Verify idempotent: reconcile again, no actions.
        let actions = reconcile(&g, &table, Mode::Dj);
        assert!(actions.is_empty(), "idempotent check failed: {:?}", actions);

        // Step 2: Unplug USBStreamer — remove node and its ports.
        // This cascades: the node, 8 ports, and links involving those ports
        // all disappear from the PW registry.
        g.remove_node(300);
        // Remove USBStreamer ports (IDs 30000-30007).
        for ch in 0..8u32 {
            g.remove_port(30000 + ch);
        }
        // Remove links that had USBStreamer ports. In DJ mode, links to
        // USBStreamer are: convolver-out→USB (4) + Mixxx HP→USB (2) = 6.
        // We need to find and remove those links.
        let usb_port_ids: Vec<u32> = (30000..30008).collect();
        let links_to_remove: Vec<u32> = g.links()
            .filter(|l| usb_port_ids.contains(&l.output_port) || usb_port_ids.contains(&l.input_port))
            .map(|l| l.id)
            .collect();
        assert_eq!(links_to_remove.len(), 6, "6 links involve USBStreamer ports");
        for link_id in &links_to_remove {
            g.remove_link(*link_id);
        }

        // Reconcile after unplug: USBStreamer gone, so 6 links can't resolve.
        // The 6 Mixxx→convolver links are still satisfied (both endpoints
        // still present). No creates (USBStreamer node missing), no destroys
        // (those links are already gone from the graph).
        let actions = reconcile(&g, &table, Mode::Dj);
        assert_eq!(
            count_creates(&actions), 0,
            "after unplug: no creates (USBStreamer missing), got {:?}", actions,
        );
        assert_eq!(
            count_destroys(&actions), 0,
            "after unplug: no destroys (links already gone), got {:?}", actions,
        );

        // Step 3: Re-plug USBStreamer with new PW IDs (new hardware session).
        g.add_node(make_node(
            310,
            "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0",
            "Audio/Sink",
        ));
        for ch in 0..8u32 {
            g.add_port(make_port(
                31000 + ch, 310,
                &format!("playback_AUX{}", ch), "in",
            ));
        }

        // Reconcile after re-plug: should recreate the 6 USBStreamer links.
        let actions = reconcile(&g, &table, Mode::Dj);
        assert_eq!(
            count_creates(&actions), 6,
            "after re-plug: expected 6 creates for USBStreamer links, got {:?}", actions,
        );
        assert_eq!(count_destroys(&actions), 0, "after re-plug: no destroys");

        // Apply creates and verify idempotent.
        apply_creates(&mut g, &actions, next_id);
        let actions = reconcile(&g, &table, Mode::Dj);
        assert!(actions.is_empty(), "final idempotent check: {:?}", actions);
    }

    // -------------------------------------------------------------------
    // S-2: Component crash/restart (Mixxx)
    // -------------------------------------------------------------------

    #[test]
    fn s2_component_crash_restart() {
        // Build DJ topology, simulate Mixxx crash (nodes disappear),
        // reconcile (Destroys for orphaned links), Mixxx restarts with
        // new IDs, reconcile (Creates for new links).
        let table = RoutingTable::production();
        let mut g = build_production_graph();

        // Step 1: Establish full DJ topology.
        let actions = reconcile(&g, &table, Mode::Dj);
        assert_eq!(count_creates(&actions), 12);
        let next_id = apply_creates(&mut g, &actions, 1000);

        // Step 2: Mixxx crashes — both nodes disappear.
        // Mixxx output node (400) and input node (401).
        g.remove_node(400);
        for ch in 0..4u32 {
            g.remove_port(40000 + ch);
        }
        g.remove_node(401);
        g.remove_port(40100);
        g.remove_port(40101);

        // Links involving Mixxx ports disappear from PW graph.
        // DJ Mixxx links: master→convolver (2) + master→sub (4) + HP→USB (2) = 8.
        let mixxx_port_ids: Vec<u32> = (40000..40004).collect();
        let links_to_remove: Vec<u32> = g.links()
            .filter(|l| mixxx_port_ids.contains(&l.output_port) || mixxx_port_ids.contains(&l.input_port))
            .map(|l| l.id)
            .collect();
        assert_eq!(links_to_remove.len(), 8, "8 links involve Mixxx output ports");
        for link_id in &links_to_remove {
            g.remove_link(*link_id);
        }

        // Reconcile: Mixxx gone, 8 links can't resolve. The 4
        // convolver→USBStreamer links are still present and desired.
        let actions = reconcile(&g, &table, Mode::Dj);
        assert_eq!(
            count_creates(&actions), 0,
            "after crash: no creates (Mixxx gone), got {:?}", actions,
        );
        assert_eq!(
            count_destroys(&actions), 0,
            "after crash: no destroys (Mixxx links already gone), got {:?}", actions,
        );

        // Step 3: Mixxx restarts with new PW IDs.
        g.add_node(make_node(410, "Mixxx", "Stream/Output/Audio"));
        for ch in 0..4u32 {
            g.add_port(make_port(
                41000 + ch, 410,
                &format!("out_{}", ch), "out",
            ));
        }
        g.add_node(make_node(411, "Mixxx", "Stream/Input/Audio"));
        g.add_port(make_port(41100, 411, "in_0", "in"));
        g.add_port(make_port(41101, 411, "in_1", "in"));

        // Reconcile: should recreate the 8 Mixxx links.
        let actions = reconcile(&g, &table, Mode::Dj);
        assert_eq!(
            count_creates(&actions), 8,
            "after restart: expected 8 creates for Mixxx links, got {:?}", actions,
        );
        assert_eq!(count_destroys(&actions), 0);

        // Verify the creates use the NEW node ID (410, not 400).
        for action in &actions {
            if let LinkAction::Create { output_node_id, .. } = action {
                assert_ne!(*output_node_id, 400, "should use new Mixxx node ID");
            }
        }

        // Apply and verify idempotent.
        apply_creates(&mut g, &actions, next_id);
        let actions = reconcile(&g, &table, Mode::Dj);
        assert!(actions.is_empty(), "final idempotent: {:?}", actions);
    }

    // -------------------------------------------------------------------
    // S-3a/b/c: Production mode transitions
    // -------------------------------------------------------------------

    #[test]
    fn s3a_monitoring_to_dj_transition() {
        let table = RoutingTable::production();
        let mut g = build_production_graph();

        // Establish Monitoring topology: 4 links (convolver→USB).
        let actions = reconcile(&g, &table, Mode::Monitoring);
        assert_eq!(count_creates(&actions), 4);
        let next_id = apply_creates(&mut g, &actions, 1000);
        assert!(reconcile(&g, &table, Mode::Monitoring).is_empty());

        // Switch to DJ: creates Mixxx links, keeps convolver→USB links.
        let actions = reconcile(&g, &table, Mode::Dj);

        // DJ has 12 total links. 4 convolver→USB links are shared with
        // Monitoring and already exist. So: 8 new creates, 0 destroys.
        assert_eq!(
            count_creates(&actions), 8,
            "Mon→DJ: expected 8 new creates (Mixxx links), got {:?}", actions,
        );
        assert_eq!(
            count_destroys(&actions), 0,
            "Mon→DJ: convolver→USB links shared, no destroys",
        );

        apply_creates(&mut g, &actions, next_id);
        assert!(reconcile(&g, &table, Mode::Dj).is_empty());
    }

    #[test]
    fn s3b_dj_to_live_transition() {
        let table = RoutingTable::production();
        let mut g = build_production_graph();

        // Establish DJ topology: 12 links.
        let actions = reconcile(&g, &table, Mode::Dj);
        assert_eq!(count_creates(&actions), 12);
        let next_id = apply_creates(&mut g, &actions, 1000);
        assert!(reconcile(&g, &table, Mode::Dj).is_empty());

        // Switch to Live.
        // Live has 22 links. Shared with DJ: convolver→USB (4 links).
        // DJ-only links to destroy: Mixxx→convolver (6) + Mixxx HP→USB (2) = 8.
        // Live-only links to create: Reaper→convolver (6) + Reaper HP→USB (2)
        //   + Reaper IEM→USB (2) + ADA8200→Reaper (8) = 18.
        let actions = reconcile(&g, &table, Mode::Live);

        assert_eq!(
            count_creates(&actions), 18,
            "DJ→Live: expected 18 new creates, got {:?}", actions,
        );
        assert_eq!(
            count_destroys(&actions), 8,
            "DJ→Live: expected 8 destroys (Mixxx links), got {:?}", actions,
        );

        apply_creates(&mut g, &actions, next_id);
        apply_destroys(&mut g, &actions);
        assert!(reconcile(&g, &table, Mode::Live).is_empty());
    }

    #[test]
    fn s3c_live_to_monitoring_transition() {
        let table = RoutingTable::production();
        let mut g = build_production_graph();

        // Establish Live topology: 22 links.
        let actions = reconcile(&g, &table, Mode::Live);
        assert_eq!(count_creates(&actions), 22);
        let next_id = apply_creates(&mut g, &actions, 1000);
        assert!(reconcile(&g, &table, Mode::Live).is_empty());

        // Switch to Monitoring.
        // Monitoring has 4 links (convolver→USB), all shared with Live.
        // Live-only links to destroy: Reaper→convolver (6) + Reaper HP→USB (2)
        //   + Reaper IEM→USB (2) + ADA8200→Reaper (8) = 18.
        let actions = reconcile(&g, &table, Mode::Monitoring);

        assert_eq!(
            count_creates(&actions), 0,
            "Live→Mon: no new creates (convolver→USB already exists), got {:?}", actions,
        );
        assert_eq!(
            count_destroys(&actions), 18,
            "Live→Mon: expected 18 destroys (Reaper + ADA8200 links), got {:?}", actions,
        );

        apply_destroys(&mut g, &actions);
        assert!(reconcile(&g, &table, Mode::Monitoring).is_empty());
    }

    // -------------------------------------------------------------------
    // S-4: Stale link cleanup (foreign link on known node)
    // -------------------------------------------------------------------

    #[test]
    fn s4_stale_foreign_link_destroyed() {
        // A link exists on a known node (convolver) that is NOT in the
        // desired set for the current mode. This simulates a leftover
        // from a manual pw-link or a previous mode's stale link.
        let table = RoutingTable::production();
        let mut g = build_production_graph();

        // Establish Monitoring topology.
        let actions = reconcile(&g, &table, Mode::Monitoring);
        let next_id = apply_creates(&mut g, &actions, 1000);

        // Add a foreign node and a stale link: some-app → convolver.
        g.add_node(make_node(999, "some-rogue-app", "Stream/Output/Audio"));
        g.add_port(make_port(99900, 999, "output_0", "out"));
        // Link from rogue app to convolver input port (playback_AUX0).
        g.add_link(make_link(
            next_id, 999, 99900, 100, 10000,
        ));

        // Reconcile: the foreign link has one known endpoint (convolver
        // is in the routing table). It is NOT in the desired set for
        // Monitoring. So it should be destroyed.
        let actions = reconcile(&g, &table, Mode::Monitoring);

        assert_eq!(
            count_destroys(&actions), 1,
            "expected 1 destroy for stale foreign link, got {:?}", actions,
        );
        match &actions.iter().find(|a| matches!(a, LinkAction::Destroy { .. })).unwrap() {
            LinkAction::Destroy { link_id, .. } => {
                assert_eq!(*link_id, next_id, "should destroy the foreign link");
            }
            _ => unreachable!(),
        }

        // No creates — the desired links are all still present.
        assert_eq!(count_creates(&actions), 0);
    }

    #[test]
    fn s4_foreign_link_between_unknown_nodes_ignored() {
        // A link between two nodes that are NOT in any routing table
        // entry. GraphManager should leave it alone.
        let table = RoutingTable::production();
        let mut g = build_production_graph();

        // Establish Monitoring topology.
        let actions = reconcile(&g, &table, Mode::Monitoring);
        apply_creates(&mut g, &actions, 1000);

        // Add two unknown nodes and a link between them.
        g.add_node(make_node(990, "pw-internal-driver", "Audio/Source"));
        g.add_port(make_port(99000, 990, "output_FL", "out"));
        g.add_node(make_node(991, "pw-internal-sink", "Audio/Sink"));
        g.add_port(make_port(99100, 991, "input_FL", "in"));
        g.add_link(make_link(2000, 990, 99000, 991, 99100));

        // Reconcile: link is between unknown nodes — should be ignored.
        let actions = reconcile(&g, &table, Mode::Monitoring);
        assert!(
            actions.is_empty(),
            "link between unknown nodes should be ignored, got {:?}", actions,
        );
    }
}
