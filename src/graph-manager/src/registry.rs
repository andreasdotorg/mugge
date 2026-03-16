//! PipeWire registry listener — detects node/port/link appear/disappear
//! events and updates the GraphState.
//!
//! The registry listener is the push-based graph awareness mechanism
//! (US-059 AC: "detects node appearance and disappearance within 100ms,
//! without polling"). PipeWire's registry API delivers events as globals
//! are added and removed — no polling needed.
//!
//! ## Thread model
//!
//! Registry callbacks run on the PW main loop thread (single-threaded).
//! GraphState is accessed only from this thread. RPC snapshots are
//! delivered via a channel, not direct access.
//!
//! ## Design
//!
//! We track three PW object types:
//! - **Node** (ObjectType::Node): application and device nodes
//! - **Port** (ObjectType::Port): per-channel ports on nodes
//! - **Link** (ObjectType::Link): connections between ports
//!
//! On `global` events, we extract properties and insert into GraphState.
//! On `global_remove`, we remove by ID and log the event.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use crate::graph::{GraphState, TrackedLink, TrackedNode, TrackedPort};

/// Register the PW registry listener that populates GraphState from
/// registry events.
///
/// Returns the registry and listener objects. Both must be kept alive
/// for the duration of the PW main loop (drop order matters).
///
/// # Arguments
/// * `core` - PW core connection.
/// * `graph` - Shared GraphState, wrapped in Rc<RefCell<>> for
///   single-threaded sharing between the two closures.
pub fn register_graph_listener(
    core: &pipewire::core::Core,
    graph: Rc<RefCell<GraphState>>,
) -> (pipewire::registry::Registry, Box<dyn std::any::Any>) {
    let registry = core
        .get_registry()
        .expect("Failed to get PipeWire registry");

    let graph_add = graph.clone();
    let graph_remove = graph;

    let listener = registry
        .add_listener_local()
        .global(move |global| {
            let mut g = graph_add.borrow_mut();

            if global.type_ == pipewire::types::ObjectType::Node {
                if let Some(props) = global.props {
                    let node_name = props.get("node.name").unwrap_or("").to_string();
                    let media_class = props.get("media.class").unwrap_or("").to_string();

                    let mut properties = HashMap::new();
                    for key in &[
                        "node.name",
                        "node.description",
                        "media.class",
                        "media.type",
                        "media.category",
                        "media.role",
                        "node.group",
                        "application.name",
                        "client.api",
                    ] {
                        if let Some(val) = props.get(key) {
                            properties.insert(key.to_string(), val.to_string());
                        }
                    }

                    g.add_node(TrackedNode {
                        id: global.id,
                        name: node_name,
                        media_class,
                        properties,
                    });
                }
            } else if global.type_ == pipewire::types::ObjectType::Port {
                if let Some(props) = global.props {
                    let node_id = props
                        .get("node.id")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);
                    let port_name = props.get("port.name").unwrap_or("").to_string();
                    let direction = props.get("port.direction").unwrap_or("").to_string();

                    let mut properties = HashMap::new();
                    for key in &[
                        "port.name",
                        "port.alias",
                        "port.direction",
                        "port.id",
                        "node.id",
                        "format.dsp",
                        "audio.channel",
                    ] {
                        if let Some(val) = props.get(key) {
                            properties.insert(key.to_string(), val.to_string());
                        }
                    }

                    g.add_port(TrackedPort {
                        id: global.id,
                        node_id,
                        name: port_name,
                        direction,
                        properties,
                    });
                }
            } else if global.type_ == pipewire::types::ObjectType::Link {
                if let Some(props) = global.props {
                    let output_port = props
                        .get("link.output.port")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);
                    let input_port = props
                        .get("link.input.port")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);
                    let output_node = props
                        .get("link.output.node")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);
                    let input_node = props
                        .get("link.input.node")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);

                    g.add_link(TrackedLink {
                        id: global.id,
                        output_port,
                        input_port,
                        output_node,
                        input_node,
                    });
                }
            }
        })
        .global_remove(move |id| {
            let mut g = graph_remove.borrow_mut();

            // We don't know the object type from global_remove, so try
            // removing from all three collections. At most one will match.
            if g.remove_link(id).is_some() {
                return;
            }
            if g.remove_port(id).is_some() {
                return;
            }
            if g.remove_node(id).is_some() {
                return;
            }
            // ID not tracked — this is normal for object types we don't
            // track (Client, Module, Factory, etc).
            log::trace!("global_remove for untracked id={}", id);
        })
        .register();

    (registry, Box::new(listener))
}
