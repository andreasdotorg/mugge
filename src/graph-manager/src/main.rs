//! pi4audio-graph-manager — sole PipeWire session manager for the audio
//! workstation.
//!
//! Manages the complete PW audio graph: registry listening, node/port/link
//! tracking, declarative routing table, and link creation/destruction.
//! Replaces WirePlumber for all application routing (D-039).
//!
//! ## Architecture (D-039, D-040)
//!
//! - GraphManager is a daemon subsystem, not a web UI component.
//! - It is the sole PW session manager — no WirePlumber.
//! - PipeWire handles device nodes, audio processing, and clocking.
//! - GraphManager handles everything above: link topology, mode
//!   transitions, component lifecycle, device monitoring.
//!
//! ## Thread model
//!
//! 1. **Main thread** — PipeWire main loop (registry events, link
//!    management, shutdown timer)
//! 2. **RPC thread** — TCP listener (port 4002), JSON protocol,
//!    state queries, mode transition requests
//!
//! ## Modules
//!
//! - `graph` — Node/port/link tracking data structures
//! - `routing` — Declarative routing table (mode → desired links)
//! - `registry` — PW registry listener (push-based graph awareness)
//! - `reconcile` — Reconciliation engine (diff desired vs actual → actions)
//! - `lifecycle` — Component health observer (derive health from graph state)
//! - `rpc` — TCP JSON-RPC server (port 4002), cross-thread commands

mod graph;
mod lifecycle;
mod reconcile;
mod registry;
mod routing;
mod rpc;

use std::cell::RefCell;
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::Arc;
use std::time::Duration;

use clap::Parser;
use log::info;

use graph::GraphState;
use lifecycle::ComponentRegistry;
use routing::{Mode, RoutingTable};
use rpc::{
    DeviceStatus, GraphEvent, LinkSnapshot, RpcCommand, RpcResult, StateSnapshot,
};

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

/// PipeWire graph manager for the Pi audio workstation.
///
/// Manages all application routing as the sole PW session manager.
/// Connects to PipeWire, tracks the audio graph, and creates/destroys
/// links according to the active operating mode.
#[derive(Parser, Debug)]
#[command(name = "pi4audio-graph-manager")]
#[command(about = "PipeWire graph manager — sole session manager for Pi audio workstation")]
struct Args {
    /// RPC listen address (JSON-RPC over TCP).
    #[arg(long, default_value = "tcp:127.0.0.1:4002")]
    listen: String,

    /// Initial operating mode.
    #[arg(long, default_value = "monitoring")]
    mode: String,

    /// Log level (RUST_LOG format).
    #[arg(long, default_value = "info")]
    log_level: String,
}

/// Parse the initial mode from the CLI string.
fn parse_mode(s: &str) -> Result<Mode, String> {
    match s {
        "monitoring" => Ok(Mode::Monitoring),
        "dj" => Ok(Mode::Dj),
        "live" => Ok(Mode::Live),
        "measurement" => Ok(Mode::Measurement),
        _ => Err(format!(
            "unknown mode '{}', expected: monitoring, dj, live, measurement",
            s
        )),
    }
}

/// Parse the listen address, stripping optional "tcp:" prefix.
fn parse_listen_addr(addr: &str) -> String {
    addr.strip_prefix("tcp:").unwrap_or(addr).to_string()
}

// ---------------------------------------------------------------------------
// PipeWire main loop
// ---------------------------------------------------------------------------

/// Run the PipeWire main loop with registry listener, graph tracking,
/// and RPC command processing.
///
/// This function blocks until the shutdown flag is set.
///
/// # Arguments
/// * `initial_mode` — Starting operating mode.
/// * `cmd_rx` — Receives `RpcCommand` from the RPC thread.
/// * `event_tx` — Sends `GraphEvent` push events to the RPC thread.
/// * `shutdown` — Shared flag set by signal handlers.
fn run_pipewire(
    initial_mode: Mode,
    cmd_rx: mpsc::Receiver<RpcCommand>,
    event_tx: mpsc::Sender<GraphEvent>,
    shutdown: Arc<AtomicBool>,
) {
    pipewire::init();

    let mainloop = pipewire::main_loop::MainLoop::new(None)
        .expect("Failed to create PipeWire main loop");
    let context = pipewire::context::Context::new(&mainloop)
        .expect("Failed to create PipeWire context");
    let core = context
        .connect(None)
        .expect("Failed to connect to PipeWire daemon");

    // Graph state — shared between registry listener callbacks.
    // Both closures run on the PW main loop thread, so Rc<RefCell<>> is safe.
    let graph = Rc::new(RefCell::new(GraphState::new()));

    // Build the routing table.
    let routing_table = Rc::new(RoutingTable::production());
    info!("Routing table loaded ({} modes)", Mode::ALL.len());

    // Current mode — shared so RPC can update it for mode transitions.
    let current_mode = Rc::new(RefCell::new(initial_mode));
    info!("Initial mode: {}", initial_mode);

    // Component health registry — tracks health of managed components
    // by observing node presence/absence in the PW registry.
    let component_registry = Rc::new(RefCell::new(ComponentRegistry::production()));
    info!(
        "Component registry loaded ({} components)",
        component_registry.borrow().len(),
    );

    // Created link proxies — must be kept alive for links to persist.
    // Keyed by (output_port_id, input_port_id).
    let link_proxies: Rc<RefCell<std::collections::HashMap<(u32, u32), pipewire::link::Link>>> =
        Rc::new(RefCell::new(std::collections::HashMap::new()));

    // Register registry listener (push-based graph awareness).
    // After every graph state change, reconciliation runs automatically
    // and component health is re-evaluated.
    // Pass core, event_tx, link_proxies, and component_registry.
    let (_registry, _registry_listener) =
        registry::register_graph_listener(
            &core,
            graph.clone(),
            routing_table.clone(),
            current_mode.clone(),
            event_tx.clone(),
            link_proxies.clone(),
            component_registry.clone(),
        );
    info!("PipeWire registry listener registered (reconciliation + lifecycle wired)");

    // Shutdown timer: poll the AtomicBool every 100ms and quit the PW loop.
    let mainloop_ptr = mainloop.as_raw_ptr();
    let _shutdown_timer = mainloop.loop_().add_timer({
        let shutdown = shutdown.clone();
        let graph = graph.clone();
        move |_expirations| {
            if shutdown.load(Ordering::Relaxed) {
                let g = graph.borrow();
                info!(
                    "Shutdown: tracked {} nodes, {} ports, {} links",
                    g.node_count(),
                    g.port_count(),
                    g.link_count(),
                );
                info!("Shutdown signal received, quitting PipeWire main loop");
                unsafe {
                    pipewire_sys::pw_main_loop_quit(mainloop_ptr);
                }
            }
        }
    });
    _shutdown_timer
        .update_timer(
            Some(Duration::from_millis(100)),
            Some(Duration::from_millis(100)),
        )
        .into_result()
        .expect("Failed to arm shutdown timer");

    // RPC command timer: poll the mpsc channel every 50ms and process
    // commands from the RPC thread. 50ms worst-case latency is well
    // under human perception threshold for mode transitions.
    let _rpc_timer = mainloop.loop_().add_timer({
        let graph = graph.clone();
        let routing_table = routing_table.clone();
        let current_mode = current_mode.clone();
        let event_tx = event_tx.clone();
        let link_proxies = link_proxies.clone();
        let core_weak = core.downgrade();
        let component_registry = component_registry.clone();
        move |_expirations| {
            // Drain all pending commands.
            while let Ok(cmd) = cmd_rx.try_recv() {
                dispatch_rpc_command(
                    cmd,
                    &graph,
                    &routing_table,
                    &current_mode,
                    &event_tx,
                    &link_proxies,
                    &core_weak,
                    &component_registry,
                );
            }
        }
    });
    _rpc_timer
        .update_timer(
            Some(Duration::from_millis(50)),
            Some(Duration::from_millis(50)),
        )
        .into_result()
        .expect("Failed to arm RPC command timer");
    info!("RPC command timer armed (50ms polling)");

    info!("PipeWire main loop starting");
    mainloop.run();
    info!("PipeWire main loop exited");

    // Drop PipeWire objects in reverse order BEFORE calling deinit().
    drop(_rpc_timer);
    drop(_shutdown_timer);
    drop(_registry_listener);
    drop(_registry);
    drop(link_proxies);
    drop(graph);
    drop(core);
    drop(context);
    drop(mainloop);

    unsafe {
        pipewire::deinit();
    }
}

/// Dispatch a single RPC command on the PW main loop thread.
///
/// This runs inside the 50ms timer callback. It has full access to
/// the PW graph state (Rc<RefCell<>>) because it is on the PW thread.
fn dispatch_rpc_command(
    cmd: RpcCommand,
    graph: &Rc<RefCell<GraphState>>,
    routing_table: &Rc<RoutingTable>,
    current_mode: &Rc<RefCell<Mode>>,
    event_tx: &mpsc::Sender<GraphEvent>,
    link_proxies: &Rc<RefCell<std::collections::HashMap<(u32, u32), pipewire::link::Link>>>,
    core_weak: &pipewire::core::WeakCore,
    component_registry: &Rc<RefCell<ComponentRegistry>>,
) {
    match cmd {
        RpcCommand::SetMode { mode, reply } => {
            let old_mode = *current_mode.borrow();
            if mode == old_mode {
                // No-op: already in the requested mode.
                let _ = reply.send(RpcResult::Ok);
                return;
            }

            // 1. Update mode.
            *current_mode.borrow_mut() = mode;
            info!("Mode transition: {} -> {}", old_mode, mode);

            // 2. Run reconciliation.
            let g = graph.borrow();
            let actions = reconcile::reconcile(&g, routing_table, mode);

            // 3. Apply link actions.
            if let Some(core) = core_weak.upgrade() {
                registry::apply_actions(
                    &actions,
                    &core,
                    &g,
                    event_tx,
                    link_proxies,
                );
            } else {
                log::warn!("PW core unavailable during mode transition");
            }

            // 4. Send reply.
            let _ = reply.send(RpcResult::Ok);

            // 5. Emit mode_changed event.
            let _ = event_tx.send(GraphEvent::ModeChanged {
                from: old_mode.to_string(),
                to: mode.to_string(),
            });
        }

        RpcCommand::GetState { reply } => {
            let g = graph.borrow();
            let mode = *current_mode.borrow();
            let reg = component_registry.borrow();
            let snap = build_state_snapshot(&g, mode, &reg);
            let _ = reply.send(snap);
        }

        RpcCommand::GetDevices { reply } => {
            let reg = component_registry.borrow();
            let devices = reg
                .all_health()
                .into_iter()
                .map(|(name, health)| DeviceStatus {
                    name: name.to_string(),
                    node_name: name.to_string(),
                    status: health.as_str().to_string(),
                })
                .collect();
            let _ = reply.send(devices);
        }

        RpcCommand::GetLinks { reply } => {
            let g = graph.borrow();
            let mode = *current_mode.borrow();
            let desired = routing_table.links_for(mode);
            let actual_count = g.link_count();
            let snap = LinkSnapshot {
                mode: mode.to_string(),
                desired: desired.len(),
                actual: actual_count,
                missing: if desired.len() > actual_count {
                    desired.len() - actual_count
                } else {
                    0
                },
                links: Vec::new(), // Detailed link info comes with GM-3 integration.
            };
            let _ = reply.send(snap);
        }
    }
}

/// Build a StateSnapshot from the current GraphState, mode, and component health.
fn build_state_snapshot(
    graph: &GraphState,
    mode: Mode,
    component_registry: &ComponentRegistry,
) -> StateSnapshot {
    use rpc::NodeInfo as RpcNodeInfo;
    use rpc::LinkInfo as RpcLinkInfo;

    let nodes: Vec<RpcNodeInfo> = graph
        .nodes()
        .map(|n| RpcNodeInfo {
            id: n.id,
            name: n.name.clone(),
            media_class: n.media_class.clone(),
        })
        .collect();

    let links: Vec<RpcLinkInfo> = graph
        .links()
        .map(|l| RpcLinkInfo {
            id: l.id,
            output_node: l.output_node,
            output_port: l.output_port,
            input_node: l.input_node,
            input_port: l.input_port,
        })
        .collect();

    let devices: std::collections::HashMap<String, String> = component_registry
        .all_health()
        .into_iter()
        .map(|(name, health)| (name.to_string(), health.as_str().to_string()))
        .collect();

    StateSnapshot {
        mode: mode.to_string(),
        nodes,
        links,
        devices,
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn main() {
    let args = Args::parse();

    // Initialize logging.
    std::env::set_var("RUST_LOG", &args.log_level);
    env_logger::init();

    let listen_addr = parse_listen_addr(&args.listen);
    let initial_mode = parse_mode(&args.mode).unwrap_or_else(|e| {
        eprintln!("Error: {}", e);
        std::process::exit(1);
    });

    info!("pi4audio-graph-manager starting");
    info!("RPC listen address: {}", listen_addr);
    info!("Initial mode: {}", initial_mode);

    // Shutdown flag — set by SIGINT/SIGTERM handler.
    let shutdown = Arc::new(AtomicBool::new(false));

    // Register signal handlers.
    {
        let shutdown = shutdown.clone();
        signal_hook::flag::register(signal_hook::consts::SIGINT, shutdown.clone())
            .expect("Failed to register SIGINT handler");
        signal_hook::flag::register(signal_hook::consts::SIGTERM, shutdown)
            .expect("Failed to register SIGTERM handler");
    }

    // Create cross-thread channels.
    // cmd: RPC thread → PW thread (commands with one-shot reply channels).
    // event: PW thread → RPC thread (push events broadcast to all clients).
    let (cmd_tx, cmd_rx) = mpsc::channel::<RpcCommand>();
    let (event_tx, event_rx) = mpsc::channel::<GraphEvent>();

    // Start RPC server thread BEFORE PW loop. The RPC thread owns
    // cmd_tx (sends commands) and event_rx (broadcasts events).
    let _rpc_handle = rpc::start_rpc_thread(
        &listen_addr,
        &initial_mode.to_string(),
        cmd_tx,
        event_rx,
        shutdown.clone(),
    );

    // Run PipeWire main loop (blocks until shutdown). The PW thread
    // owns cmd_rx (receives commands) and event_tx (emits events).
    run_pipewire(initial_mode, cmd_rx, event_tx, shutdown);

    info!("pi4audio-graph-manager exited");
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_mode_valid() {
        assert_eq!(parse_mode("monitoring").unwrap(), Mode::Monitoring);
        assert_eq!(parse_mode("dj").unwrap(), Mode::Dj);
        assert_eq!(parse_mode("live").unwrap(), Mode::Live);
        assert_eq!(parse_mode("measurement").unwrap(), Mode::Measurement);
    }

    #[test]
    fn parse_mode_invalid() {
        assert!(parse_mode("unknown").is_err());
        assert!(parse_mode("").is_err());
    }

    #[test]
    fn parse_listen_addr_with_prefix() {
        assert_eq!(parse_listen_addr("tcp:127.0.0.1:4002"), "127.0.0.1:4002");
    }

    #[test]
    fn parse_listen_addr_without_prefix() {
        assert_eq!(parse_listen_addr("127.0.0.1:4002"), "127.0.0.1:4002");
    }

    #[test]
    fn shutdown_flag_default_false() {
        let flag = Arc::new(AtomicBool::new(false));
        assert!(!flag.load(Ordering::Relaxed));
    }

    #[test]
    fn shutdown_flag_can_be_set() {
        let flag = Arc::new(AtomicBool::new(false));
        flag.store(true, Ordering::Relaxed);
        assert!(flag.load(Ordering::Relaxed));
    }
}
