//! PipeWire graph state tracker — tracks all nodes and links by ID.
//!
//! Maintains a local mirror of the PW graph state, updated by registry
//! events (global add/remove). This is the data layer that the
//! reconciliation engine (GM-3) queries to determine which links exist
//! and which nodes are present.
//!
//! ## Thread model
//!
//! GraphState is accessed only from the PW main loop thread. No
//! synchronization needed. The RPC thread reads snapshots via a
//! message-passing channel (not direct access).

use std::collections::HashMap;

use serde::Serialize;

/// A tracked PipeWire node.
#[derive(Debug, Clone, Serialize)]
pub struct TrackedNode {
    /// PipeWire global object ID.
    pub id: u32,
    /// `node.name` property (our primary identifier).
    pub name: String,
    /// `media.class` property (e.g., "Stream/Output/Audio", "Audio/Sink").
    pub media_class: String,
    /// All properties from the registry event.
    pub properties: HashMap<String, String>,
}

/// A tracked PipeWire link.
#[derive(Debug, Clone, Serialize)]
pub struct TrackedLink {
    /// PipeWire global object ID for the link.
    pub id: u32,
    /// Output (source) port ID.
    pub output_port: u32,
    /// Input (sink) port ID.
    pub input_port: u32,
    /// Output node ID.
    pub output_node: u32,
    /// Input node ID.
    pub input_node: u32,
}

/// A tracked PipeWire port.
#[derive(Debug, Clone, Serialize)]
pub struct TrackedPort {
    /// PipeWire global object ID for the port.
    pub id: u32,
    /// Parent node ID.
    pub node_id: u32,
    /// Port name (e.g., "output_AUX0", "input_MONO").
    pub name: String,
    /// Port direction: "in" or "out".
    pub direction: String,
    /// All properties from the registry event.
    pub properties: HashMap<String, String>,
}

/// Complete local mirror of the PW graph relevant to routing.
///
/// Tracks nodes, ports, and links. Updated by registry event callbacks.
/// Queried by the reconciliation engine and RPC state snapshots.
pub struct GraphState {
    nodes: HashMap<u32, TrackedNode>,
    ports: HashMap<u32, TrackedPort>,
    links: HashMap<u32, TrackedLink>,
}

impl GraphState {
    /// Create an empty graph state.
    pub fn new() -> Self {
        Self {
            nodes: HashMap::new(),
            ports: HashMap::new(),
            links: HashMap::new(),
        }
    }

    // -------------------------------------------------------------------
    // Node operations
    // -------------------------------------------------------------------

    /// Add or update a node from a registry global event.
    pub fn add_node(&mut self, node: TrackedNode) {
        log::info!(
            "Node added: id={}, name={}, class={}",
            node.id,
            node.name,
            node.media_class,
        );
        self.nodes.insert(node.id, node);
    }

    /// Remove a node by its PW global ID. Also removes all associated ports.
    pub fn remove_node(&mut self, id: u32) -> Option<TrackedNode> {
        // Remove all ports belonging to this node.
        let port_ids: Vec<u32> = self
            .ports
            .iter()
            .filter(|(_, p)| p.node_id == id)
            .map(|(&pid, _)| pid)
            .collect();
        for pid in &port_ids {
            self.ports.remove(pid);
        }
        if !port_ids.is_empty() {
            log::debug!("Removed {} ports for node id={}", port_ids.len(), id);
        }

        let node = self.nodes.remove(&id);
        if let Some(ref n) = node {
            log::info!("Node removed: id={}, name={}", n.id, n.name);
        }
        node
    }

    /// Get a node by ID.
    pub fn node(&self, id: u32) -> Option<&TrackedNode> {
        self.nodes.get(&id)
    }

    /// Find a node by its `node.name` property.
    pub fn node_by_name(&self, name: &str) -> Option<&TrackedNode> {
        self.nodes.values().find(|n| n.name == name)
    }

    /// Find all nodes whose name matches a predicate.
    pub fn nodes_matching(&self, predicate: impl Fn(&str) -> bool) -> Vec<&TrackedNode> {
        self.nodes.values().filter(|n| predicate(&n.name)).collect()
    }

    /// All tracked nodes.
    pub fn nodes(&self) -> impl Iterator<Item = &TrackedNode> {
        self.nodes.values()
    }

    /// Number of tracked nodes.
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }

    // -------------------------------------------------------------------
    // Port operations
    // -------------------------------------------------------------------

    /// Add or update a port from a registry global event.
    pub fn add_port(&mut self, port: TrackedPort) {
        log::debug!(
            "Port added: id={}, node={}, name={}, dir={}",
            port.id,
            port.node_id,
            port.name,
            port.direction,
        );
        self.ports.insert(port.id, port);
    }

    /// Remove a port by its PW global ID.
    pub fn remove_port(&mut self, id: u32) -> Option<TrackedPort> {
        let port = self.ports.remove(&id);
        if let Some(ref p) = port {
            log::debug!("Port removed: id={}, name={}", p.id, p.name);
        }
        port
    }

    /// Get a port by ID.
    pub fn port(&self, id: u32) -> Option<&TrackedPort> {
        self.ports.get(&id)
    }

    /// Find ports belonging to a node with a specific name.
    pub fn ports_for_node(&self, node_id: u32, port_name: &str) -> Vec<&TrackedPort> {
        self.ports
            .values()
            .filter(|p| p.node_id == node_id && p.name == port_name)
            .collect()
    }

    /// All ports belonging to a node.
    pub fn ports_of_node(&self, node_id: u32) -> Vec<&TrackedPort> {
        self.ports
            .values()
            .filter(|p| p.node_id == node_id)
            .collect()
    }

    /// Number of tracked ports.
    pub fn port_count(&self) -> usize {
        self.ports.len()
    }

    // -------------------------------------------------------------------
    // Link operations
    // -------------------------------------------------------------------

    /// Add or update a link from a registry global event.
    pub fn add_link(&mut self, link: TrackedLink) {
        log::info!(
            "Link added: id={}, {}:{} -> {}:{}",
            link.id,
            link.output_node,
            link.output_port,
            link.input_node,
            link.input_port,
        );
        self.links.insert(link.id, link);
    }

    /// Remove a link by its PW global ID.
    pub fn remove_link(&mut self, id: u32) -> Option<TrackedLink> {
        let link = self.links.remove(&id);
        if let Some(ref l) = link {
            log::info!("Link removed: id={}", l.id);
        }
        link
    }

    /// Get a link by ID.
    pub fn link(&self, id: u32) -> Option<&TrackedLink> {
        self.links.get(&id)
    }

    /// Check if a link exists between specific ports.
    pub fn link_exists(&self, output_port_id: u32, input_port_id: u32) -> bool {
        self.links
            .values()
            .any(|l| l.output_port == output_port_id && l.input_port == input_port_id)
    }

    /// All tracked links.
    pub fn links(&self) -> impl Iterator<Item = &TrackedLink> {
        self.links.values()
    }

    /// Number of tracked links.
    pub fn link_count(&self) -> usize {
        self.links.len()
    }

    // -------------------------------------------------------------------
    // Snapshot (for RPC)
    // -------------------------------------------------------------------

    /// Create a serializable snapshot of the full graph state.
    pub fn snapshot(&self) -> GraphSnapshot {
        GraphSnapshot {
            nodes: self.nodes.values().cloned().collect(),
            ports: self.ports.values().cloned().collect(),
            links: self.links.values().cloned().collect(),
        }
    }
}

/// Serializable snapshot of the graph state for RPC responses.
#[derive(Debug, Clone, Serialize)]
pub struct GraphSnapshot {
    pub nodes: Vec<TrackedNode>,
    pub ports: Vec<TrackedPort>,
    pub links: Vec<TrackedLink>,
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

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

    // -----------------------------------------------------------------------
    // Node tracking
    // -----------------------------------------------------------------------

    #[test]
    fn empty_graph() {
        let g = GraphState::new();
        assert_eq!(g.node_count(), 0);
        assert_eq!(g.port_count(), 0);
        assert_eq!(g.link_count(), 0);
    }

    #[test]
    fn add_and_get_node() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "pi4audio-signal-gen", "Stream/Output/Audio"));
        assert_eq!(g.node_count(), 1);
        assert!(g.node(10).is_some());
        assert_eq!(g.node(10).unwrap().name, "pi4audio-signal-gen");
    }

    #[test]
    fn remove_node() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "signal-gen", "Stream/Output/Audio"));
        let removed = g.remove_node(10);
        assert!(removed.is_some());
        assert_eq!(g.node_count(), 0);
    }

    #[test]
    fn remove_node_cascades_ports() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "signal-gen", "Stream/Output/Audio"));
        g.add_port(make_port(100, 10, "output_AUX0", "out"));
        g.add_port(make_port(101, 10, "output_AUX1", "out"));
        g.add_port(make_port(200, 20, "input_0", "in")); // different node
        assert_eq!(g.port_count(), 3);

        g.remove_node(10);
        // Ports for node 10 are removed, port for node 20 remains.
        assert_eq!(g.port_count(), 1);
        assert!(g.port(200).is_some());
    }

    #[test]
    fn remove_unknown_node_returns_none() {
        let mut g = GraphState::new();
        assert!(g.remove_node(999).is_none());
    }

    #[test]
    fn node_by_name() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "pi4audio-signal-gen", "Stream/Output/Audio"));
        g.add_node(make_node(20, "pi4audio-convolver", "Audio/Sink"));

        let found = g.node_by_name("pi4audio-convolver");
        assert!(found.is_some());
        assert_eq!(found.unwrap().id, 20);

        assert!(g.node_by_name("nonexistent").is_none());
    }

    #[test]
    fn nodes_matching() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "pi4audio-signal-gen", "Stream/Output/Audio"));
        g.add_node(make_node(20, "pi4audio-pcm-main", "Stream/Input/Audio"));
        g.add_node(make_node(30, "mixxx", "Stream/Output/Audio"));

        let pi4_nodes = g.nodes_matching(|n| n.starts_with("pi4audio-"));
        assert_eq!(pi4_nodes.len(), 2);
    }

    // -----------------------------------------------------------------------
    // Port tracking
    // -----------------------------------------------------------------------

    #[test]
    fn add_and_get_port() {
        let mut g = GraphState::new();
        g.add_port(make_port(100, 10, "output_AUX0", "out"));
        assert_eq!(g.port_count(), 1);
        assert!(g.port(100).is_some());
    }

    #[test]
    fn ports_for_node_by_name() {
        let mut g = GraphState::new();
        g.add_port(make_port(100, 10, "output_AUX0", "out"));
        g.add_port(make_port(101, 10, "output_AUX1", "out"));
        g.add_port(make_port(102, 10, "output_AUX0", "out")); // duplicate name

        let matches = g.ports_for_node(10, "output_AUX0");
        assert_eq!(matches.len(), 2);
    }

    #[test]
    fn ports_of_node() {
        let mut g = GraphState::new();
        g.add_port(make_port(100, 10, "output_AUX0", "out"));
        g.add_port(make_port(101, 10, "output_AUX1", "out"));
        g.add_port(make_port(200, 20, "input_0", "in"));

        let node_ports = g.ports_of_node(10);
        assert_eq!(node_ports.len(), 2);
    }

    // -----------------------------------------------------------------------
    // Link tracking
    // -----------------------------------------------------------------------

    #[test]
    fn add_and_get_link() {
        let mut g = GraphState::new();
        g.add_link(make_link(500, 10, 100, 20, 200));
        assert_eq!(g.link_count(), 1);
        assert!(g.link(500).is_some());
    }

    #[test]
    fn link_exists_check() {
        let mut g = GraphState::new();
        g.add_link(make_link(500, 10, 100, 20, 200));
        assert!(g.link_exists(100, 200));
        assert!(!g.link_exists(100, 201));
        assert!(!g.link_exists(101, 200));
    }

    #[test]
    fn remove_link() {
        let mut g = GraphState::new();
        g.add_link(make_link(500, 10, 100, 20, 200));
        let removed = g.remove_link(500);
        assert!(removed.is_some());
        assert_eq!(g.link_count(), 0);
    }

    // -----------------------------------------------------------------------
    // Snapshot
    // -----------------------------------------------------------------------

    #[test]
    fn snapshot_captures_all() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "signal-gen", "Stream/Output/Audio"));
        g.add_port(make_port(100, 10, "output_AUX0", "out"));
        g.add_link(make_link(500, 10, 100, 20, 200));

        let snap = g.snapshot();
        assert_eq!(snap.nodes.len(), 1);
        assert_eq!(snap.ports.len(), 1);
        assert_eq!(snap.links.len(), 1);
    }

    #[test]
    fn snapshot_serializable() {
        let mut g = GraphState::new();
        g.add_node(make_node(10, "signal-gen", "Stream/Output/Audio"));
        let snap = g.snapshot();
        let json = serde_json::to_string(&snap).unwrap();
        assert!(json.contains("signal-gen"));
    }
}
