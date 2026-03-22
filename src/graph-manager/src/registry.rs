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
use crate::link_audit;
use crate::reconcile::{self, LinkAction};
use crate::routing::{Mode, RoutingTable};
use crate::rpc::GraphEvent;
use crate::watchdog::{Watchdog, WatchdogAction};

/// Lightweight handle to call `destroy_global()` on the PW registry.
///
/// The PipeWire `Registry` type is not `Clone`, so we cannot share it
/// between closures directly. This wrapper stores the raw pointer and
/// provides a safe-ish `destroy_global()` method. It is only used on the
/// PW main loop thread (single-threaded), and the pointer is valid for
/// the lifetime of the registry (which outlives all closures).
#[derive(Clone)]
pub struct RegistryHandle {
    ptr: std::ptr::NonNull<pipewire_sys::pw_registry>,
}

impl RegistryHandle {
    /// Create a handle from a `Registry` reference.
    ///
    /// # Safety
    /// The caller must ensure the `Registry` outlives all uses of this handle.
    fn from_registry(registry: &pipewire::registry::Registry) -> Self {
        // Registry stores a NonNull<pipewire_sys::pw_registry>. We access the
        // raw pointer via the same pattern used for Core in main.rs.
        // Registry::as_ptr() is private, so we cast through the struct layout.
        // Safety: Registry is #[repr(Rust)] but its only field is
        // NonNull<pipewire_sys::pw_registry>, so transmuting &Registry to get
        // the pointer is sound on the same thread.
        let ptr = unsafe {
            let reg_ptr: *const pipewire::registry::Registry = registry;
            let nn: std::ptr::NonNull<pipewire_sys::pw_registry> =
                std::ptr::read(reg_ptr as *const std::ptr::NonNull<pipewire_sys::pw_registry>);
            nn
        };
        Self { ptr }
    }

    /// Destroy a global object by ID via the PipeWire registry.
    pub fn destroy_global(&self, global_id: u32) {
        unsafe {
            libspa::spa_interface_call_method!(
                self.ptr.as_ptr(),
                pipewire_sys::pw_registry_methods,
                destroy,
                global_id
            );
        }
    }

    /// Set the Mult parameter to the given value on a PipeWire node, using
    /// the native PipeWire API (no subprocess).
    ///
    /// This is the safety-critical mute path (T-044-4). It binds a temporary
    /// node proxy via the registry, builds the SPA Props pod containing the
    /// Mult parameter, calls `pw_node_set_param`, and destroys the proxy.
    ///
    /// ## Timing
    ///
    /// Each call takes <1ms (in-process function call, no fork/exec). This
    /// meets the <21ms budget for the complete 4-node mute operation.
    ///
    /// ## Safety
    ///
    /// Must be called on the PW main loop thread. The registry pointer must
    /// be valid. Best-effort: returns false on failure but never panics.
    pub fn set_node_mult(&self, node_id: u32, mult_value: f32) -> bool {
        unsafe {
            // 1. Bind a temporary node proxy via the registry.
            //    pw_registry_bind(registry, id, type, version, user_data_size)
            //    Returns *mut c_void (the proxy), or null on failure.
            let type_cstr = std::ffi::CStr::from_bytes_with_nul_unchecked(
                pipewire_sys::PW_TYPE_INTERFACE_Node,
            );
            let proxy_ptr: *mut std::os::raw::c_void =
                libspa::spa_interface_call_method!(
                    self.ptr.as_ptr(),
                    pipewire_sys::pw_registry_methods,
                    bind,
                    node_id,
                    type_cstr.as_ptr(),
                    pipewire_sys::PW_VERSION_NODE,  // version 3
                    0usize  // no user data
                );

            if proxy_ptr.is_null() {
                log::error!(
                    "WATCHDOG: pw_registry_bind failed for node {} — null proxy",
                    node_id,
                );
                return false;
            }

            // 2. Build the SPA Props pod: Object(Props) { params => Struct { String("Mult"), Float(value) } }
            //    This matches what pw-cli sends for: pw-cli s <id> Props '{ params = [ "Mult" <value> ] }'
            let mut pod_data: Vec<u8> = Vec::with_capacity(128);
            let mut builder = libspa::pod::builder::Builder::new(&mut pod_data);

            let build_result = libspa::__builder_add__!(
                &mut builder,
                Object(
                    spa_sys::SPA_TYPE_OBJECT_Props,
                    spa_sys::SPA_PARAM_Props,
                ) {
                    spa_sys::SPA_PROP_params => Struct {
                        String("Mult"),
                        Float(mult_value),
                    },
                }
            );

            if build_result.is_err() {
                log::error!(
                    "WATCHDOG: SPA pod build failed for node {} — {:?}",
                    node_id, build_result,
                );
                // Destroy the proxy before returning.
                pipewire_sys::pw_proxy_destroy(proxy_ptr.cast());
                return false;
            }

            // Drop the builder to release the borrow on pod_data.
            drop(builder);

            // 3. Get the pod pointer from the built data.
            let pod_ptr = pod_data.as_ptr() as *const spa_sys::spa_pod;

            // 4. Call pw_node_set_param(proxy, SPA_PARAM_Props, 0, pod).
            //    The proxy pointer is a pw_node proxy obtained via pw_registry_bind.
            libspa::spa_interface_call_method!(
                proxy_ptr,
                pipewire_sys::pw_node_methods,
                set_param,
                spa_sys::SPA_PARAM_Props,
                0u32,  // flags
                pod_ptr
            );

            // 5. Destroy the temporary proxy. The set_param message has been
            //    queued in PipeWire's protocol buffer and will be sent on the
            //    next main loop iteration. Destroying the proxy after queuing
            //    is safe — PW flushes pending messages before cleanup.
            pipewire_sys::pw_proxy_destroy(proxy_ptr.cast());

            true
        }
    }
}

/// Apply reconciliation link actions to the PW graph.
///
/// For `Create`: creates a PW link via `core.create_object()` and stores
/// the proxy in `link_proxies` (keyed by port pair) to keep it alive.
/// For `Destroy`: removes our proxy (if we created the link) and calls
/// `registry.destroy_global()` to destroy the link in PipeWire (GM-7).
///
/// Emits `GraphEvent::LinkCreated` / `GraphEvent::LinkDestroyed` /
/// `GraphEvent::LinkFailed` for each action.
pub fn apply_actions(
    actions: &[LinkAction],
    core: &pipewire::core::CoreRef,
    registry: &RegistryHandle,
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

                // Resolve names for the event BEFORE removing anything.
                let (out_name, out_port_name, in_name, in_port_name) =
                    if let Some(link) = graph.link(*link_id) {
                        let on = graph
                            .node(link.output_node)
                            .map(|n| n.name.clone())
                            .unwrap_or_else(|| link.output_node.to_string());
                        let op = graph
                            .port(link.output_port)
                            .map(|p| p.name.clone())
                            .unwrap_or_else(|| link.output_port.to_string());
                        let in_ = graph
                            .node(link.input_node)
                            .map(|n| n.name.clone())
                            .unwrap_or_else(|| link.input_node.to_string());
                        let ip = graph
                            .port(link.input_port)
                            .map(|p| p.name.clone())
                            .unwrap_or_else(|| link.input_port.to_string());
                        (on, op, in_, ip)
                    } else {
                        (
                            link_id.to_string(),
                            "?".to_string(),
                            "?".to_string(),
                            "?".to_string(),
                        )
                    };

                // Remove our proxy if we created this link. Look up the
                // link in GraphState to find its port pair (our proxy key).
                if let Some(link) = graph.link(*link_id) {
                    let key = (link.output_port, link.input_port);
                    let removed = link_proxies.borrow_mut().remove(&key);
                    if removed.is_some() {
                        log::info!(
                            "  Proxy dropped for link id={} ({}:{} -> {}:{})",
                            link_id,
                            link.output_node, link.output_port,
                            link.input_node, link.input_port,
                        );
                    }
                }

                // Destroy the link in PipeWire via the registry. This
                // works for any link (ours or pre-existing/foreign).
                // PipeWire will emit a global_remove event when the link
                // is actually destroyed, which updates our GraphState.
                registry.destroy_global(*link_id);
                log::info!("  Link destroyed via registry: id={}", link_id);

                let _ = event_tx.send(GraphEvent::LinkDestroyed {
                    output_node: out_name,
                    output_port: out_port_name,
                    input_node: in_name,
                    input_port: in_port_name,
                });
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
    registry: &RegistryHandle,
    event_tx: &mpsc::Sender<GraphEvent>,
    link_proxies: &Rc<RefCell<HashMap<(u32, u32), pipewire::link::Link>>>,
    component_registry: &Rc<RefCell<ComponentRegistry>>,
    watchdog: &Rc<RefCell<Watchdog>>,
) {
    let actions = reconcile::reconcile(graph, table, mode);
    apply_actions(&actions, core, registry, graph, event_tx, link_proxies);

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

    // Run safety watchdog check (T-044-4).
    // This fires on every graph mutation — if a critical node disappears,
    // the watchdog latches a safety mute within the same PW loop iteration.
    run_watchdog_check(graph, watchdog, registry, event_tx);

    // Run link audit (T-044-3).
    // Verify no links bypass the convolver/gain chain to reach USBStreamer
    // speaker ports directly. Destroy any violating links immediately.
    run_link_audit(graph, registry, event_tx);
}

/// Execute the safety watchdog check and apply mute actions.
///
/// Called after every graph mutation. The watchdog's check() is pure —
/// it returns an action. This function applies the action via PW API.
///
/// ## Mute mechanism
///
/// **Primary (SetGainMute):** Uses `pw_node_set_param()` via the native
/// PipeWire API (`RegistryHandle::set_node_mult`). Binds a temporary node
/// proxy, builds a SPA Props pod with Mult=0.0, calls set_param, and
/// destroys the proxy. No subprocess — <1ms per node, <5ms for all 4.
///
/// **Fallback (DestroyUsbLinks):** Uses `registry.destroy_global()` to
/// destroy all links to USBStreamer input ports. This is the existing
/// link destruction mechanism already used by reconciliation.
fn run_watchdog_check(
    graph: &GraphState,
    watchdog: &Rc<RefCell<Watchdog>>,
    registry: &RegistryHandle,
    event_tx: &mpsc::Sender<GraphEvent>,
) {
    let action = watchdog.borrow_mut().check(graph);

    match action {
        WatchdogAction::AllPresent | WatchdogAction::AlreadyLatched => {
            // No action needed.
        }

        WatchdogAction::SetGainMute { gain_nodes } => {
            // Primary mute path: set Mult=0.0 on all available gain nodes
            // via native PW API (pw_registry_bind + pw_node_set_param).
            // No subprocess — <1ms per node, well within the <21ms budget.
            let missing = watchdog.borrow().missing_at_latch().to_vec();
            log::error!(
                "WATCHDOG MUTE: Setting Mult=0.0 on {} gain nodes via native PW API (missing: {:?})",
                gain_nodes.len(),
                missing,
            );

            // Store pre-mute gains (default production values from
            // 30-filter-chain-convolver.conf, since reading the actual
            // Mult value would require an async enum_params round-trip).
            let pre_mute: Vec<(String, f64)> = gain_nodes
                .iter()
                .map(|(_, name)| {
                    let default_mult = match name.as_str() {
                        "gain_left_hp" | "gain_right_hp" => 0.001,
                        "gain_sub1_lp" | "gain_sub2_lp" => 0.000631,
                        _ => 0.001,
                    };
                    (name.clone(), default_mult)
                })
                .collect();
            watchdog.borrow_mut().store_pre_mute_gains(pre_mute);

            // Execute mute via native PW API — no pw-cli subprocess.
            // Safety-critical: best-effort per node. If one fails, we
            // continue to mute the remaining nodes.
            for (node_id, name) in &gain_nodes {
                log::error!("WATCHDOG: Muting {} (node {}) via set_node_mult", name, node_id);
                if registry.set_node_mult(*node_id, 0.0) {
                    log::error!("WATCHDOG: Muted {} (node {})", name, node_id);
                } else {
                    log::error!(
                        "WATCHDOG: Native set_param failed for {} (node {})",
                        name, node_id,
                    );
                }
            }

            // Emit watchdog mute event.
            let _ = event_tx.send(GraphEvent::WatchdogMute {
                missing_nodes: missing,
                mechanism: "gain_mute_native".to_string(),
            });
        }

        WatchdogAction::DestroyUsbLinks { link_ids } => {
            // Fallback: destroy all links to USBStreamer.
            let missing = watchdog.borrow().missing_at_latch().to_vec();
            log::error!(
                "WATCHDOG FALLBACK: Destroying {} USBStreamer links (missing: {:?})",
                link_ids.len(),
                missing,
            );

            for link_id in &link_ids {
                registry.destroy_global(*link_id);
                log::error!("WATCHDOG: Destroyed link id={}", link_id);
            }

            // Emit watchdog mute event.
            let _ = event_tx.send(GraphEvent::WatchdogMute {
                missing_nodes: missing,
                mechanism: "link_destroy".to_string(),
            });
        }

    }
}

/// Run the link audit and destroy any bypass links (T-044-3).
///
/// Checks all links in the graph for convolver bypass violations:
/// any link to USBStreamer speaker ports (AUX0..AUX3) that does NOT
/// originate from `pi4audio-convolver-out`. Violating links are
/// destroyed immediately via `registry.destroy_global()`.
///
/// Called after every graph mutation alongside the watchdog check.
fn run_link_audit(
    graph: &GraphState,
    registry: &RegistryHandle,
    event_tx: &mpsc::Sender<GraphEvent>,
) {
    let violations = link_audit::audit_links(graph);

    if violations.is_empty() {
        return;
    }

    log::error!(
        "LINK AUDIT: {} bypass violation(s) detected — destroying",
        violations.len(),
    );

    let mut destroyed = 0usize;
    let mut violation_info = Vec::new();

    for v in &violations {
        log::error!(
            "LINK AUDIT: Destroying bypass link id={}: {} ({}) -> USBStreamer {}",
            v.link_id, v.source_node, v.source_port, v.target_port,
        );
        registry.destroy_global(v.link_id);
        destroyed += 1;
        violation_info.push((
            v.source_node.clone(),
            v.source_port.clone(),
            v.target_port.clone(),
        ));
    }

    let _ = event_tx.send(GraphEvent::LinkAuditViolation {
        violations: violation_info,
        destroyed,
    });
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
    watchdog: Rc<RefCell<Watchdog>>,
) -> (pipewire::registry::Registry, Box<dyn std::any::Any>, RegistryHandle) {
    let registry = core
        .get_registry()
        .expect("Failed to get PipeWire registry");

    // Create a lightweight handle for destroy_global() calls inside closures.
    // Safety: the Registry object is returned from this function and kept
    // alive for the duration of the PW main loop. The handle is only used
    // on the PW main loop thread (single-threaded).
    let reg_handle = RegistryHandle::from_registry(&registry);

    // Re-entrancy guard: prevents reconciliation from firing when the
    // registry delivers events for links that we just created/destroyed.
    // Without this, create_object() -> global event -> reconcile() -> create_object()
    // forms a feedback loop. Single-threaded, so Cell<bool> is sufficient.
    //
    // F-079: dirty flag tracks whether a graph mutation occurred while
    // reconciliation was running. If so, we re-run reconciliation after
    // the current one completes to pick up ports that arrived during the
    // window (e.g., Mixxx out_1 arriving while out_0's links are being
    // created). Without this, those ports are added to GraphState but
    // never trigger reconciliation, leaving links permanently missing.
    let reconciling = Rc::new(std::cell::Cell::new(false));
    let dirty = Rc::new(std::cell::Cell::new(false));
    let reconciling_add = reconciling.clone();
    let dirty_add = dirty.clone();
    let reconciling_remove = reconciling;
    let dirty_remove = dirty;

    // Core is Clone (Rc-based) — safe to clone into closures on the
    // same PW main loop thread. No WeakCore needed.
    let core_add = core.clone();
    let core_remove = core.clone();
    let reg_handle_add = reg_handle.clone();
    let reg_handle_remove = reg_handle.clone();
    let graph_add = graph.clone();
    let table_add = table.clone();
    let mode_add = mode.clone();
    let event_tx_add = event_tx.clone();
    let link_proxies_add = link_proxies.clone();
    let comp_reg_add = component_registry.clone();
    let watchdog_add = watchdog.clone();
    let graph_remove = graph;
    let table_remove = table;
    let mode_remove = mode;
    let event_tx_remove = event_tx;
    let link_proxies_remove = link_proxies;
    let comp_reg_remove = component_registry;
    let watchdog_remove = watchdog;

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
            //
            // F-079: If a mutation occurs while reconciling, set the dirty
            // flag so we re-run after the current reconciliation completes.
            // This handles the case where ports arrive during link creation
            // (e.g., Mixxx out_1 arrives while out_0's links are being
            // created). Without this, those ports never trigger reconciliation.
            if mutated && !reconciling_add.get() {
                reconciling_add.set(true);
                dirty_add.set(false);
                let current_mode = *mode_add.borrow();
                run_reconcile(
                    &g,
                    &table_add,
                    current_mode,
                    &core_add,
                    &reg_handle_add,
                    &event_tx_add,
                    &link_proxies_add,
                    &comp_reg_add,
                    &watchdog_add,
                );
                // F-079: If new mutations arrived during reconciliation,
                // re-run to pick up newly arrived ports/nodes. Loop until
                // clean to handle cascading arrivals.
                while dirty_add.get() {
                    dirty_add.set(false);
                    let current_mode = *mode_add.borrow();
                    run_reconcile(
                        &g,
                        &table_add,
                        current_mode,
                        &core_add,
                        &reg_handle_add,
                        &event_tx_add,
                        &link_proxies_add,
                        &comp_reg_add,
                        &watchdog_add,
                    );
                }
                reconciling_add.set(false);
            } else if mutated && reconciling_add.get() {
                // F-079: Mark dirty so the outer reconciliation loop
                // re-runs after the current one completes.
                dirty_add.set(true);
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
            // F-079: dirty flag for cascading mutations (same pattern as global).
            if removed && !reconciling_remove.get() {
                reconciling_remove.set(true);
                dirty_remove.set(false);
                let current_mode = *mode_remove.borrow();
                run_reconcile(
                    &g,
                    &table_remove,
                    current_mode,
                    &core_remove,
                    &reg_handle_remove,
                    &event_tx_remove,
                    &link_proxies_remove,
                    &comp_reg_remove,
                    &watchdog_remove,
                );
                while dirty_remove.get() {
                    dirty_remove.set(false);
                    let current_mode = *mode_remove.borrow();
                    run_reconcile(
                        &g,
                        &table_remove,
                        current_mode,
                        &core_remove,
                        &reg_handle_remove,
                        &event_tx_remove,
                        &link_proxies_remove,
                        &comp_reg_remove,
                        &watchdog_remove,
                    );
                }
                reconciling_remove.set(false);
            } else if removed && reconciling_remove.get() {
                dirty_remove.set(true);
            }
        })
        .register();

    (registry, Box::new(listener), reg_handle)
}
