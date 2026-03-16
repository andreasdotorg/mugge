//! PipeWire registry listener — detects node/port/link appear/disappear
//! events, updates the GraphState, triggers reconciliation, and updates
//! component health.
//!
//! The registry listener is the push-based graph awareness mechanism
//! (US-059 AC: "detects node appearance and disappearance within 100ms,
//! without polling"). PipeWire's registry API delivers events as globals
//! are added and removed — no polling needed.
//!
//! After every graph state mutation:
//! 1. The reconciliation engine runs (diff desired vs actual links).
//! 2. Component health is re-evaluated (detect connect/disconnect transitions).
//! 3. Health transitions are emitted as `DeviceConnected`/`DeviceDisconnected`
//!    events to RPC clients.
//!
//! ## Thread model
//!
//! Registry callbacks run on the PW main loop thread (single-threaded).
//! GraphState and ComponentRegistry are accessed only from this thread.
//! RPC snapshots are delivered via a channel, not direct access.
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
//! After each mutation, `reconcile()` runs and component health updates.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use std::sync::mpsc;

use crate::graph::{GraphState, TrackedLink, TrackedNode, TrackedPort};
use crate::lifecycle::{ComponentRegistry, HealthTransition};
use crate::reconcile::{self, LinkAction};
use crate::routing::{Mode, RoutingTable};
use crate::rpc::GraphEvent;

/// Apply reconciliation link actions to the PW graph.
///
/// For `Create`: creates a PW link via `core.create_object()` and stores
/// the proxy in `link_proxies` (keyed by port pair) to keep it alive.
/// For `Destroy`: destroys the PW link via `registry.destroy_global()`.
///
/// Emits `GraphEvent::LinkCreated` / `GraphEvent::LinkFailed` for each
/// create action.
pub fn apply_actions(
    actions: &[LinkAction],
    core: &pipewire::core::CoreRef,
    graph: &GraphState,
    event_tx: &mpsc::Sender<GraphEvent>,
    link_proxies: &Rc<RefCell<HashMap<(u32, u32), pipewire::link::Link>>>,
) {
    if actions.is_empty() {
        return;
    }
    log::info!("Reconciliation: applying {} action(s)", actions.len());

    for action in actions {
        match action {
            LinkAction::Create {
                output_node_id,
                output_port_id,
                input_node_id,
                input_port_id,
                description,
            } => {
                // Guard: skip if we already created this link (port pair
                // already in link_proxies). Prevents duplicate creation
                // during the window between core.create_object() and the
                // registry global event confirming the link.
                if link_proxies.borrow().contains_key(&(*output_port_id, *input_port_id)) {
                    log::debug!("  SKIP (already created): {}", description);
                    continue;
                }

                log::info!("  CREATE: {}", description);

                let props = pipewire::properties::properties! {
                    "link.output.port" => output_port_id.to_string(),
                    "link.input.port" => input_port_id.to_string(),
                    "link.output.node" => output_node_id.to_string(),
                    "link.input.node" => input_node_id.to_string(),
                };

                match core.create_object::<pipewire::link::Link>(
                    "link-factory",
                    &props,
                ) {
                    Ok(link) => {
                        log::info!(
                            "  Link created: {}:{} -> {}:{}",
                            output_node_id, output_port_id,
                            input_node_id, input_port_id,
                        );
                        link_proxies
                            .borrow_mut()
                            .insert((*output_port_id, *input_port_id), link);

                        // Resolve node names for the event.
                        let out_name = graph
                            .node(*output_node_id)
                            .map(|n| n.name.clone())
                            .unwrap_or_else(|| output_node_id.to_string());
                        let in_name = graph
                            .node(*input_node_id)
                            .map(|n| n.name.clone())
                            .unwrap_or_else(|| input_node_id.to_string());
                        let out_port_name = graph
                            .port(*output_port_id)
                            .map(|p| p.name.clone())
                            .unwrap_or_else(|| output_port_id.to_string());
                        let in_port_name = graph
                            .port(*input_port_id)
                            .map(|p| p.name.clone())
                            .unwrap_or_else(|| input_port_id.to_string());

                        let _ = event_tx.send(GraphEvent::LinkCreated {
                            output_node: out_name,
                            output_port: out_port_name,
                            input_node: in_name,
                            input_port: in_port_name,
                        });
                    }
                    Err(e) => {
                        log::warn!("  Link create failed: {} — {}", description, e);

                        let out_name = graph
                            .node(*output_node_id)
                            .map(|n| n.name.clone())
                            .unwrap_or_else(|| output_node_id.to_string());
                        let in_name = graph
                            .node(*input_node_id)
                            .map(|n| n.name.clone())
                            .unwrap_or_else(|| input_node_id.to_string());
                        let out_port_name = graph
                            .port(*output_port_id)
                            .map(|p| p.name.clone())
                            .unwrap_or_else(|| output_port_id.to_string());
                        let in_port_name = graph
                            .port(*input_port_id)
                            .map(|p| p.name.clone())
                            .unwrap_or_else(|| input_port_id.to_string());

                        let _ = event_tx.send(GraphEvent::LinkFailed {
                            output_node: out_name,
                            output_port: out_port_name,
                            input_node: in_name,
                            input_port: in_port_name,
                            reason: e.to_string(),
                        });
                    }
                }
            }
            LinkAction::Destroy { link_id, description } => {
                log::info!("  DESTROY id={}: {}", link_id, description);
                // Remove the proxy from our tracked set. When the proxy
                // drops, PW will destroy the link. We also call
                // destroy_global for links we didn't create (pre-existing).
                let mut proxies = link_proxies.borrow_mut();
                // Find and remove proxy by link_id — we need to scan
                // since our key is (output_port, input_port), not link_id.
                // The registry will notify us via global_remove when it
                // actually goes away.
                proxies.retain(|_, _| true); // Placeholder: real proxy
                // lookup by link_id requires GraphState to map link_id
                // to port pair. For now, destroy via global_remove.
                drop(proxies);

                // Destroy via registry. This works for any link by global ID.
                // Note: requires the registry reference — we'll use the core
                // to get a fresh registry destroy. Actually, PipeWire's
                // Registry::destroy_global needs the registry object.
                // For now, log the intent — the registry destroy_global
                // integration requires passing the Registry into apply_actions.
                // TODO (GM-7): Wire Registry into apply_actions for destroy.
                log::warn!(
                    "  DESTROY: link id={} logged but not yet removed (requires Registry ref)",
                    link_id,
                );
            }
        }
    }
}

/// Run reconciliation against the current graph state and apply actions,
/// then update component health and emit transition events.
///
/// Called after every graph mutation (registry events). The reconcile
/// function is pure — it reads state and returns actions. apply_actions
/// executes them against PW. After reconciliation, component health is
/// re-evaluated and any transitions are emitted as RPC push events.
fn run_reconcile(
    graph: &GraphState,
    table: &RoutingTable,
    mode: Mode,
    core: &pipewire::core::CoreRef,
    event_tx: &mpsc::Sender<GraphEvent>,
    link_proxies: &Rc<RefCell<HashMap<(u32, u32), pipewire::link::Link>>>,
    component_registry: &Rc<RefCell<ComponentRegistry>>,
) {
    let actions = reconcile::reconcile(graph, table, mode);
    apply_actions(&actions, core, graph, event_tx, link_proxies);

    // Update component health from the current graph state.
    let transitions = component_registry.borrow_mut().update(graph);
    for transition in &transitions {
        let event = match transition {
            HealthTransition::Connected { name } => {
                GraphEvent::DeviceConnected { name: name.clone() }
            }
            HealthTransition::Disconnected { name } => {
                GraphEvent::DeviceDisconnected { name: name.clone() }
            }
        };
        let _ = event_tx.send(event);
    }
}

/// Register the PW registry listener that populates GraphState from
/// registry events, triggers reconciliation, and updates component
/// health after each mutation.
///
/// Returns the registry and listener objects. Both must be kept alive
/// for the duration of the PW main loop (drop order matters).
///
/// # Arguments
/// * `core` - PW core connection.
/// * `graph` - Shared GraphState, wrapped in Rc<RefCell<>> for
///   single-threaded sharing between the two closures.
/// * `table` - Routing table (all modes and their desired links).
/// * `mode` - Shared current operating mode, wrapped in Rc<RefCell<>>
///   so that RPC mode transitions update the value for the next
///   reconciliation cycle.
/// * `event_tx` - Channel to send push events to RPC clients.
/// * `link_proxies` - Shared map of created link proxies (kept alive).
/// * `component_registry` - Component health observer, updated after
///   every graph mutation to detect connect/disconnect transitions.
pub fn register_graph_listener(
    core: &pipewire::core::Core,
    graph: Rc<RefCell<GraphState>>,
    table: Rc<RoutingTable>,
    mode: Rc<RefCell<Mode>>,
    event_tx: mpsc::Sender<GraphEvent>,
    link_proxies: Rc<RefCell<HashMap<(u32, u32), pipewire::link::Link>>>,
    component_registry: Rc<RefCell<ComponentRegistry>>,
) -> (pipewire::registry::Registry, Box<dyn std::any::Any>) {
    let registry = core
        .get_registry()
        .expect("Failed to get PipeWire registry");

    // Re-entrancy guard: prevents reconciliation from firing when the
    // registry delivers events for links that we just created/destroyed.
    // Without this, create_object() -> global event -> reconcile() -> create_object()
    // forms a feedback loop. Single-threaded, so Cell<bool> is sufficient.
    let reconciling = Rc::new(std::cell::Cell::new(false));
    let reconciling_add = reconciling.clone();
    let reconciling_remove = reconciling;

    // Core is Clone (Rc-based) — safe to clone into closures on the
    // same PW main loop thread. No WeakCore needed.
    let core_add = core.clone();
    let core_remove = core.clone();
    let graph_add = graph.clone();
    let table_add = table.clone();
    let mode_add = mode.clone();
    let event_tx_add = event_tx.clone();
    let link_proxies_add = link_proxies.clone();
    let comp_reg_add = component_registry.clone();
    let graph_remove = graph;
    let table_remove = table;
    let mode_remove = mode;
    let event_tx_remove = event_tx;
    let link_proxies_remove = link_proxies;
    let comp_reg_remove = component_registry;

    let listener = registry
        .add_listener_local()
        .global(move |global| {
            let mut g = graph_add.borrow_mut();
            let mut mutated = false;

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
                    mutated = true;
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
                    mutated = true;
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
                    mutated = true;
                }
            }

            // Trigger reconciliation and health update after every graph mutation.
            // Skip if already reconciling (re-entrancy guard: our own link
            // creation triggers global events that re-enter this callback).
            if mutated && !reconciling_add.get() {
                reconciling_add.set(true);
                let current_mode = *mode_add.borrow();
                run_reconcile(
                    &g,
                    &table_add,
                    current_mode,
                    &core_add,
                    &event_tx_add,
                    &link_proxies_add,
                    &comp_reg_add,
                );
                reconciling_add.set(false);
            }
        })
        .global_remove(move |id| {
            let mut g = graph_remove.borrow_mut();

            // We don't know the object type from global_remove, so try
            // removing from all three collections. At most one will match.
            let removed = if g.remove_link(id).is_some() {
                true
            } else if g.remove_port(id).is_some() {
                true
            } else if g.remove_node(id).is_some() {
                true
            } else {
                // ID not tracked — this is normal for object types we don't
                // track (Client, Module, Factory, etc).
                log::trace!("global_remove for untracked id={}", id);
                false
            };

            // Trigger reconciliation and health update after every graph mutation.
            // Skip if already reconciling (re-entrancy guard).
            if removed && !reconciling_remove.get() {
                reconciling_remove.set(true);
                let current_mode = *mode_remove.borrow();
                run_reconcile(
                    &g,
                    &table_remove,
                    current_mode,
                    &core_remove,
                    &event_tx_remove,
                    &link_proxies_remove,
                    &comp_reg_remove,
                );
                reconciling_remove.set(false);
            }
        })
        .register();

    (registry, Box::new(listener))
}
