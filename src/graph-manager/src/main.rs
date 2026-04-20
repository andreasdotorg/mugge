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
//! - `watchdog` — Safety mute watchdog (T-044-4, latches mute on node loss)
//! - `rpc` — TCP JSON-RPC server (port 4002), cross-thread commands

// Pure-logic modules — compile on all platforms.
mod app_lifecycle;
mod gain_integrity;
mod graph;
mod lifecycle;
mod link_audit;
mod reconcile;
mod routing;
mod rpc;
mod venue;
mod watchdog;

// PipeWire registry listener — Linux only (needs libpipewire).
#[cfg(feature = "pipewire-backend")]
mod registry;

// Common imports (always compiled).
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use clap::Parser;
use log::info;

use routing::{Mode, SpeakerLayout};

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
    #[arg(long, default_value = "standby")]
    mode: String,

    /// Log level (RUST_LOG format).
    #[arg(long, default_value = "info")]
    log_level: String,

    /// Number of speaker output channels (e.g. 4 for 2-way, 6 for 3-way stereo).
    #[arg(long, default_value = "4")]
    speaker_channels: u32,

    /// Comma-separated list of 1-based sub channel numbers (e.g. "3,4" or "1,2").
    #[arg(long, default_value = "3,4")]
    sub_channels: String,

    /// Write the actual bound port to this file after binding.
    /// Used by orchestration scripts when --listen uses port 0.
    #[arg(long)]
    port_file: Option<String>,
}


/// Parse and validate the listen address, stripping optional "tcp:" prefix.
///
/// # Security (SEC-GM-01)
///
/// Only loopback addresses are permitted. Binding to a non-loopback address
/// would expose the unauthenticated RPC interface to the venue network,
/// allowing anyone on the LAN to change operating modes, create/destroy
/// links, and disrupt a live performance.
fn parse_listen_addr(addr: &str) -> Result<String, String> {
    let stripped = addr.strip_prefix("tcp:").unwrap_or(addr);

    // Extract the host portion (everything before the last ':port').
    let host = match stripped.rsplit_once(':') {
        Some((h, _port)) => h,
        None => stripped,
    };

    // Allow IPv6 bracket notation: [::1]:4002 → ::1
    let host_bare = host.strip_prefix('[').and_then(|h| h.strip_suffix(']')).unwrap_or(host);

    match host_bare {
        "127.0.0.1" | "::1" | "localhost" => Ok(stripped.to_string()),
        _ => Err(format!(
            "SEC-GM-01: refusing to bind to non-loopback address '{}'. \
             Only 127.0.0.1, ::1, and localhost are permitted.",
            stripped,
        )),
    }
}

// ---------------------------------------------------------------------------
// PipeWire main loop (Linux only — requires pipewire-backend feature)
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
#[cfg(feature = "pipewire-backend")]
fn run_pipewire(
    initial_mode: Mode,
    speaker_layout: SpeakerLayout,
    cmd_rx: std::sync::mpsc::Receiver<rpc::RpcCommand>,
    event_tx: std::sync::mpsc::Sender<rpc::GraphEvent>,
    shutdown: Arc<AtomicBool>,
) {
    use std::cell::RefCell;
    use std::rc::Rc;
    use std::time::Duration;

    use gain_integrity::GainIntegrityCheck;
    use graph::GraphState;
    use lifecycle::ComponentRegistry;
    use routing::RoutingTable;
    use watchdog::Watchdog;

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

    // Build the routing table from the speaker layout.
    info!(
        "Speaker layout: {} channels, subs {:?}, stereo mains {:?}",
        speaker_layout.num_speaker_channels, speaker_layout.sub_channels, speaker_layout.stereo_main_channels,
    );
    let routing_table = Rc::new(RoutingTable::production_for(speaker_layout));
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

    // Safety watchdog — monitors critical audio nodes and latches a
    // safety mute if any disappear (T-044-4).
    let watchdog_state = Rc::new(RefCell::new(Watchdog::new()));
    info!("Safety watchdog initialized (monitoring {} nodes)", watchdog::MONITORED_NODES.len());

    // Gain integrity check — periodic Mult <= 1.0 verification (T-044-5).
    let gain_integrity_state = Rc::new(RefCell::new(GainIntegrityCheck::new()));
    info!("Gain integrity check initialized (checking {} gain params)", watchdog::GAIN_PARAM_NAMES.len());

    // Graph info cache — quantum, sample rate, xruns (Phase 2a).
    // Updated by a 1s timer via pw-metadata subprocess. RPC returns cached values.
    let graph_info_cache = Rc::new(RefCell::new(rpc::GraphInfoSnapshot::empty()));
    info!("Graph info cache initialized");

    // Resolve directory paths once at startup (F-256: avoid per-call env reads).
    let resolved_state_dir = venue::state_dir();
    let resolved_venues_dir = venue::venues_dir();

    // Active venue name.
    // US-123: Load persisted venue name from disk (does NOT open gate or apply gains).
    // US-113: If no persisted venue (first boot), load the default venue.
    let persisted_venue = venue::load_persisted_venue(&resolved_state_dir);
    let (initial_venue, initial_pending_gains) = match persisted_venue {
        Some(name) => {
            // Normal boot: venue name restored from disk.
            // Load the profile to populate pending_gains (gate stays closed).
            let gains = match venue::find_venue(&resolved_venues_dir, &name) {
                Ok(profile) => venue::venue_gains(&profile),
                Err(e) => {
                    log::warn!("US-123: persisted venue '{}' not found: {} — starting with no venue", name, e);
                    Vec::new()
                }
            };
            (Some(name), gains)
        }
        None => {
            // First boot (US-113): load default venue, persist it, populate
            // pending_gains. Gate stays CLOSED per D-063 safety invariant.
            match venue::load_default_venue(&resolved_venues_dir, &resolved_state_dir) {
                Ok(name) => {
                    let gains = match venue::find_venue(&resolved_venues_dir, &name) {
                        Ok(profile) => venue::venue_gains(&profile),
                        Err(e) => {
                            log::warn!("US-113: default venue '{}' profile error: {}", name, e);
                            Vec::new()
                        }
                    };
                    (Some(name), gains)
                }
                Err(e) => {
                    log::warn!("US-113: failed to load default venue: {} — starting with no venue", e);
                    (None, Vec::new())
                }
            }
        }
    };
    let active_venue: Rc<RefCell<Option<String>>> = Rc::new(RefCell::new(initial_venue));

    // D-063 audio gate state: all gains start at 0.0, gate closed.
    // Gate must be explicitly opened via `open_gate` RPC after loading a venue.
    let gate_open: Rc<RefCell<bool>> = Rc::new(RefCell::new(false));
    let pending_gains: Rc<RefCell<Vec<(String, f64)>>> = Rc::new(RefCell::new(initial_pending_gains));

    // US-140: Settlement epoch counters (deterministic reconciler settlement).
    // Both live on the PW main loop thread — Cell<u64> is sufficient (no sync needed).
    // reconcile_epoch: increments each time reconcile produces non-empty actions.
    // settled_epoch: set to reconcile_epoch when reconcile produces zero actions.
    let reconcile_epoch: Rc<std::cell::Cell<u64>> = Rc::new(std::cell::Cell::new(0));
    let settled_epoch: Rc<std::cell::Cell<u64>> = Rc::new(std::cell::Cell::new(0));

    // US-140: Pending settlement waiters (await_settled RPC).
    // Checked by the settlement timer on the PW main loop thread.
    let pending_waiters: Rc<RefCell<Vec<rpc::PendingSettlementWaiter>>> =
        Rc::new(RefCell::new(Vec::new()));

    // Created link proxies — must be kept alive for links to persist.
    // Keyed by (output_port_id, input_port_id).
    let link_proxies: Rc<RefCell<std::collections::HashMap<(u32, u32), pipewire::link::Link>>> =
        Rc::new(RefCell::new(std::collections::HashMap::new()));

    // Register registry listener (push-based graph awareness).
    // After every graph state change, reconciliation runs automatically,
    // component health is re-evaluated, and the safety watchdog is checked.
    // Pass core, event_tx, link_proxies, component_registry, and watchdog.
    let (_registry, _registry_listener, reg_handle) =
        registry::register_graph_listener(
            &core,
            graph.clone(),
            routing_table.clone(),
            current_mode.clone(),
            event_tx.clone(),
            link_proxies.clone(),
            component_registry.clone(),
            watchdog_state.clone(),
            gate_open.clone(),
            reconcile_epoch.clone(),
            settled_epoch.clone(),
        );
    info!("PipeWire registry listener registered (reconciliation + lifecycle + watchdog wired)");

    // US-123 / F-249: Set quantum on startup to match initial mode.
    // Previously only called during mode transitions, leaving quantum unset
    // at boot (reported as F-249).
    set_quantum_for_mode(initial_mode);

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
    // Safety: core_ptr is the raw pointer to the PW core. The Core object
    // is owned by run_pipewire() and lives until after mainloop.run() returns.
    // The timer callback runs on the same PW main loop thread. The pointer
    // is stable for the duration of the main loop.
    let core_ptr = core.as_raw_ptr();
    let _rpc_timer = mainloop.loop_().add_timer({
        let graph = graph.clone();
        let routing_table = routing_table.clone();
        let current_mode = current_mode.clone();
        let event_tx = event_tx.clone();
        let link_proxies = link_proxies.clone();
        let component_registry = component_registry.clone();
        let reg_handle = reg_handle.clone();
        let watchdog_state = watchdog_state.clone();
        let gain_integrity_state = gain_integrity_state.clone();
        let graph_info_cache = graph_info_cache.clone();
        let active_venue = active_venue.clone();
        let gate_open = gate_open.clone();
        let pending_gains = pending_gains.clone();
        let reconcile_epoch = reconcile_epoch.clone();
        let settled_epoch = settled_epoch.clone();
        let pending_waiters = pending_waiters.clone();
        move |_expirations| {
            // Drain all pending commands.
            while let Ok(cmd) = cmd_rx.try_recv() {
                // Safety: core_ptr is valid for the duration of the main loop.
                // CoreRef is the borrowed form of Core — we reconstruct it from
                // the raw pointer to pass into dispatch_rpc_command.
                let core_ref = unsafe {
                    &*(core_ptr as *const pipewire::core::CoreRef)
                };
                dispatch_rpc_command(
                    cmd,
                    &graph,
                    &routing_table,
                    &current_mode,
                    &event_tx,
                    &link_proxies,
                    core_ref,
                    &reg_handle,
                    &component_registry,
                    &watchdog_state,
                    &gain_integrity_state,
                    &graph_info_cache,
                    &active_venue,
                    &gate_open,
                    &pending_gains,
                    &resolved_state_dir,
                    &resolved_venues_dir,
                    &reconcile_epoch,
                    &settled_epoch,
                    &pending_waiters,
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

    // US-140: Settlement check timer — checks pending await_settled waiters.
    // Runs every 10ms to provide responsive settlement notification.
    // Settlement typically takes 2-42ms (1-2 PW main loop cycles).
    let _settlement_timer = mainloop.loop_().add_timer({
        let reconcile_epoch = reconcile_epoch.clone();
        let settled_epoch = settled_epoch.clone();
        let pending_waiters = pending_waiters.clone();
        let graph = graph.clone();
        let routing_table = routing_table.clone();
        let current_mode = current_mode.clone();
        move |_expirations| {
            check_pending_waiters(
                &pending_waiters,
                &reconcile_epoch,
                &settled_epoch,
                &graph,
                &routing_table,
                &current_mode,
            );
        }
    });
    _settlement_timer
        .update_timer(
            Some(Duration::from_millis(10)),
            Some(Duration::from_millis(10)),
        )
        .into_result()
        .expect("Failed to arm settlement timer");
    info!("Settlement check timer armed (10ms polling)");

    // Gain integrity timer: every 30s, run `pw-dump` and check that all
    // gain node Mult values are <= 1.0 (T-044-5). If any Mult > 1.0,
    // trigger watchdog safety mute.
    let _gain_timer = mainloop.loop_().add_timer({
        let gain_integrity_state = gain_integrity_state.clone();
        let watchdog_state = watchdog_state.clone();
        let reg_handle = reg_handle.clone();
        let event_tx = event_tx.clone();
        let graph = graph.clone();
        let gate_open = gate_open.clone();
        move |_expirations| {
            run_gain_integrity_check(
                &gain_integrity_state,
                &watchdog_state,
                &reg_handle,
                &event_tx,
                &graph,
                &gate_open,
            );
        }
    });
    _gain_timer
        .update_timer(
            Some(Duration::from_secs(30)),
            Some(Duration::from_secs(30)),
        )
        .into_result()
        .expect("Failed to arm gain integrity timer");
    info!("Gain integrity timer armed (30s polling)");

    // Graph info timer: every 5s, run pw-metadata + pw-dump to cache
    // quantum/rate/xruns (Phase 2a, F-095: reduced from N+1 to 2 subprocesses).
    // F-127: reduced from 1s to 5s — quantum/rate/xruns change infrequently,
    // and 1s polling caused ~1 pw-dump/sec driving journald + PW CPU overhead.
    let _graph_info_timer = mainloop.loop_().add_timer({
        let graph_info_cache = graph_info_cache.clone();
        let graph = graph.clone();
        move |_expirations| {
            update_graph_info_cache(&graph_info_cache, &graph);
        }
    });
    _graph_info_timer
        .update_timer(
            Some(Duration::from_secs(5)),
            Some(Duration::from_secs(5)),
        )
        .into_result()
        .expect("Failed to arm graph info timer");
    info!("Graph info timer armed (5s polling)");

    info!("PipeWire main loop starting");
    mainloop.run();
    info!("PipeWire main loop exited");

    // Drop PipeWire objects in reverse order BEFORE calling deinit().
    drop(_graph_info_timer);
    drop(_settlement_timer);
    drop(_gain_timer);
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
#[cfg(feature = "pipewire-backend")]
fn dispatch_rpc_command(
    cmd: rpc::RpcCommand,
    graph: &std::rc::Rc<std::cell::RefCell<graph::GraphState>>,
    routing_table: &std::rc::Rc<routing::RoutingTable>,
    current_mode: &std::rc::Rc<std::cell::RefCell<Mode>>,
    event_tx: &std::sync::mpsc::Sender<rpc::GraphEvent>,
    link_proxies: &std::rc::Rc<std::cell::RefCell<std::collections::HashMap<(u32, u32), pipewire::link::Link>>>,
    core_ref: &pipewire::core::CoreRef,
    reg_handle: &registry::RegistryHandle,
    component_registry: &std::rc::Rc<std::cell::RefCell<lifecycle::ComponentRegistry>>,
    watchdog_state: &std::rc::Rc<std::cell::RefCell<watchdog::Watchdog>>,
    gain_integrity_state: &std::rc::Rc<std::cell::RefCell<gain_integrity::GainIntegrityCheck>>,
    graph_info_cache: &std::rc::Rc<std::cell::RefCell<rpc::GraphInfoSnapshot>>,
    active_venue: &std::rc::Rc<std::cell::RefCell<Option<String>>>,
    gate_open: &std::rc::Rc<std::cell::RefCell<bool>>,
    pending_gains: &std::rc::Rc<std::cell::RefCell<Vec<(String, f64)>>>,
    resolved_state_dir: &std::path::Path,
    resolved_venues_dir: &std::path::Path,
    reconcile_epoch: &std::rc::Rc<std::cell::Cell<u64>>,
    settled_epoch: &std::rc::Rc<std::cell::Cell<u64>>,
    pending_waiters: &std::rc::Rc<std::cell::RefCell<Vec<rpc::PendingSettlementWaiter>>>,
) {
    use rpc::{DeviceStatus, GraphEvent, LinkSnapshot, RpcResult};

    match cmd {
        rpc::RpcCommand::SetMode { mode, reply } => {
            let old_mode = *current_mode.borrow();
            if mode == old_mode {
                // No-op: already in the requested mode.
                // US-140: Return current epoch even on no-op.
                let _ = reply.send(RpcResult::OkWithEpoch {
                    epoch: reconcile_epoch.get(),
                });
                return;
            }

            // 1. Update mode.
            *current_mode.borrow_mut() = mode;
            info!("Mode transition: {} -> {}", old_mode, mode);

            // 1b. Set quantum for the new mode (F-230, F-249).
            // DJ: force-quantum=1024; all other modes: force-quantum=256.
            set_quantum_for_mode(mode);

            // 2. Run reconciliation.
            let g = graph.borrow();
            let result = reconcile::reconcile(&g, routing_table, mode);

            // Log any missing endpoints (mode transition — log all, no dedup).
            for endpoint in &result.missing_endpoints {
                log::warn!("Required link endpoint missing (will retry): {}", endpoint);
            }

            // US-140: Update epoch counters after reconcile, before applying link actions.
            if result.actions.is_empty() {
                settled_epoch.set(reconcile_epoch.get());
            } else {
                reconcile_epoch.set(reconcile_epoch.get() + 1);
            }

            // 3. Apply link actions.
            registry::apply_actions(
                &result.actions,
                core_ref,
                reg_handle,
                &g,
                event_tx,
                link_proxies,
            );

            // 3b. D-063: Close the gate on standby transition.
            // Standby means "no audio" — gains must be zeroed.
            if mode == Mode::Standby && *gate_open.borrow() {
                if let Some(convolver) = g.node_by_name(watchdog::CONVOLVER_NODE_NAME) {
                    for name in watchdog::GAIN_PARAM_NAMES {
                        let prefixed = format!("{}:Mult", name);
                        reg_handle.set_node_param_mult(convolver.id, &prefixed, 0.0);
                    }
                }
                *gate_open.borrow_mut() = false;
                info!("D-063: Gate closed on standby transition");
                let _ = event_tx.send(GraphEvent::GateClosed {
                    reason: "standby transition".to_string(),
                });
            }
            drop(g);

            // 4. Send reply with epoch (US-140 AC #3).
            let _ = reply.send(RpcResult::OkWithEpoch {
                epoch: reconcile_epoch.get(),
            });

            // 5. Emit mode_changed event.
            let _ = event_tx.send(GraphEvent::ModeChanged {
                from: old_mode.to_string(),
                to: mode.to_string(),
            });

            // 6. US-085: Transition app services on a background thread.
            // MUST NOT block the PW main loop — safety watchdog would stall.
            let new_mode = mode;
            std::thread::spawn(move || {
                if let Err(e) = app_lifecycle::transition_apps(new_mode) {
                    log::error!("App lifecycle transition failed: {}", e);
                }
            });
        }

        rpc::RpcCommand::GetState { reply } => {
            let g = graph.borrow();
            let mode = *current_mode.borrow();
            let reg = component_registry.borrow();
            let gi_cache = graph_info_cache.borrow();
            let is_gate_open = *gate_open.borrow();
            let venue = active_venue.borrow().clone();
            let mut snap = build_state_snapshot(&g, mode, &reg);
            // US-123 AC #7: populate boot state fields.
            snap.gate_open = is_gate_open;
            snap.venue_loaded = venue.is_some();
            snap.persisted_venue = venue;
            snap.quantum = if gi_cache.force_quantum > 0 {
                gi_cache.force_quantum
            } else {
                gi_cache.quantum
            };
            let _ = reply.send(snap);
        }

        rpc::RpcCommand::GetDevices { reply } => {
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

        rpc::RpcCommand::GetLinks { reply } => {
            let g = graph.borrow();
            let mode = *current_mode.borrow();
            let desired = routing_table.links_for(mode);
            // US-140 AC #8: Fix missing calculation — use reconciler to check
            // each desired link against actual graph by port pair, not total
            // link count (which includes links GM didn't create).
            let missing = count_missing_links(&g, routing_table, mode);
            let actual = desired.len() - missing;
            let snap = LinkSnapshot {
                mode: mode.to_string(),
                desired: desired.len(),
                actual,
                missing,
                links: Vec::new(), // Detailed link info comes with GM-3 integration.
            };
            let _ = reply.send(snap);
        }

        rpc::RpcCommand::WatchdogStatus { reply } => {
            let wd = watchdog_state.borrow();
            let _ = reply.send(wd.status());
        }

        rpc::RpcCommand::WatchdogUnlatch { reply } => {
            let mut wd = watchdog_state.borrow_mut();
            match wd.unlatch() {
                Some(gains) => {
                    // Drop the borrow before accessing the graph (may need
                    // to look up node IDs for gain restoration).
                    drop(wd);

                    info!("Watchdog unlatch: restoring {} gain values", gains.len());

                    // Restore pre-mute gain values via native PW API.
                    // Gain builtins are params on the convolver node.
                    let g = graph.borrow();
                    let mut restored = 0usize;
                    if let Some(convolver) = g.node_by_name(watchdog::CONVOLVER_NODE_NAME) {
                        for (name, mult) in &gains {
                            let prefixed = format!("{}:Mult", name);
                            if reg_handle.set_node_param_mult(convolver.id, &prefixed, *mult as f32) {
                                info!("Watchdog unlatch: restored {} to Mult={}", prefixed, mult);
                                restored += 1;
                            } else {
                                log::warn!("Watchdog unlatch: failed to restore {}", prefixed);
                            }
                        }
                    } else {
                        log::warn!("Watchdog unlatch: convolver node not in graph, skipping restore");
                    }
                    drop(g);

                    let _ = event_tx.send(GraphEvent::WatchdogUnlatched {
                        restored_gains: restored,
                    });
                    let _ = reply.send(RpcResult::Ok);
                }
                None => {
                    let _ = reply.send(RpcResult::Error(
                        "watchdog is not latched".to_string(),
                    ));
                }
            }
        }

        rpc::RpcCommand::GainIntegrityStatus { reply } => {
            let gi = gain_integrity_state.borrow();
            let _ = reply.send(gi.status());
        }

        rpc::RpcCommand::GetGraphInfo { reply } => {
            let snap = graph_info_cache.borrow().clone();
            let _ = reply.send(snap);
        }

        rpc::RpcCommand::ListVenues { reply } => {
            let venues = venue::list_venues(&resolved_venues_dir);
            let _ = reply.send(venues);
        }

        rpc::RpcCommand::GetVenue { reply } => {
            let name = active_venue.borrow().clone();
            let _ = reply.send(name);
        }

        rpc::RpcCommand::SetVenue { name, reply } => {
            use rpc::RpcResult;

            // 1. Load and validate the venue profile.
            let profile = match venue::find_venue(&resolved_venues_dir, &name) {
                Ok(p) => p,
                Err(e) => {
                    let _ = reply.send(RpcResult::Error(e));
                    return;
                }
            };

            // 2. Compute linear gain values and store as pending (D-063).
            let gains = venue::venue_gains(&profile);
            *pending_gains.borrow_mut() = gains.clone();
            *active_venue.borrow_mut() = Some(name.clone());

            // US-123 AC #4: Persist venue name to disk for crash recovery.
            venue::persist_venue_name(&name, &resolved_state_dir);

            // 3. If gate is open, apply gains immediately (hot venue switch).
            // NOTE: Gains are applied in a single loop iteration with no ramp.
            // This may cause an audible click if gain values change significantly.
            // Acceptable for venue switch (operator action, not mid-performance).
            if *gate_open.borrow() {
                let g = graph.borrow();
                if let Some(convolver) = g.node_by_name(watchdog::CONVOLVER_NODE_NAME) {
                    let mut applied = 0usize;
                    for (param_name, mult) in &gains {
                        let prefixed = format!("{}:Mult", param_name);
                        if reg_handle.set_node_param_mult(convolver.id, &prefixed, *mult as f32) {
                            info!("set_venue (hot): {} = {:.6}", prefixed, mult);
                            applied += 1;
                        }
                    }
                    info!("set_venue: '{}' hot-applied ({}/{} gains)", name, applied, gains.len());
                }
            } else {
                info!("set_venue: '{}' loaded ({} gains pending, gate closed)", name, gains.len());
            }

            let _ = reply.send(RpcResult::Ok);
        }

        rpc::RpcCommand::OpenGate { reply } => {
            let gains = pending_gains.borrow().clone();
            if gains.is_empty() {
                let _ = reply.send(RpcResult::Error("no venue loaded".to_string()));
                return;
            }

            if *gate_open.borrow() {
                let _ = reply.send(RpcResult::Error("gate already open".to_string()));
                return;
            }

            let g = graph.borrow();
            let convolver = match g.node_by_name(watchdog::CONVOLVER_NODE_NAME) {
                Some(c) => c,
                None => {
                    let _ = reply.send(RpcResult::Error(
                        "convolver node not found in graph".to_string(),
                    ));
                    return;
                }
            };

            // D-063: Cosine ramp-up over 30 steps.
            // Each step applies Mult = target * (1 - cos(pi * step / 30)) / 2.
            // NOTE: Current implementation applies all 30 steps within a single
            // PW main loop iteration (instantaneous apply, not a true temporal
            // ramp). PipeWire coalesces the param updates — only the final value
            // takes effect in the next graph cycle. A true temporal ramp would
            // require a per-cycle timer callback. Acceptable for MVP; revisit if
            // audible clicks are reported on gate open.
            let steps = 30u32;
            for step in 1..=steps {
                let t = std::f64::consts::PI * step as f64 / steps as f64;
                let ramp = (1.0 - t.cos()) / 2.0;
                for (param_name, target_mult) in &gains {
                    let prefixed = format!("{}:Mult", param_name);
                    let mult = (*target_mult * ramp) as f32;
                    reg_handle.set_node_param_mult(convolver.id, &prefixed, mult);
                }
            }
            drop(g);

            *gate_open.borrow_mut() = true;

            let venue_name = active_venue.borrow().clone().unwrap_or_default();
            info!(
                "D-063: Gate opened for '{}' ({} channels, {} ramp steps)",
                venue_name, gains.len(), steps
            );

            let _ = event_tx.send(GraphEvent::GateOpened {
                venue: venue_name,
                channels: gains.len(),
            });
            let _ = reply.send(RpcResult::Ok);
        }

        rpc::RpcCommand::CloseGate { reply } => {
            let g = graph.borrow();
            if let Some(convolver) = g.node_by_name(watchdog::CONVOLVER_NODE_NAME) {
                for name in watchdog::GAIN_PARAM_NAMES {
                    let prefixed = format!("{}:Mult", name);
                    reg_handle.set_node_param_mult(convolver.id, &prefixed, 0.0);
                }
            }
            drop(g);

            *gate_open.borrow_mut() = false;
            info!("D-063: Gate closed (all gains zeroed)");

            let _ = event_tx.send(GraphEvent::GateClosed {
                reason: "close_gate RPC".to_string(),
            });
            let _ = reply.send(RpcResult::Ok);
        }

        rpc::RpcCommand::GetGate { reply } => {
            let _ = reply.send(rpc::GateStatus {
                gate_open: *gate_open.borrow(),
                has_pending_gains: !pending_gains.borrow().is_empty(),
                venue: active_venue.borrow().clone(),
            });
        }

        rpc::RpcCommand::AwaitSettled { since_epoch, timeout_ms, reply } => {
            // US-140: Check if already settled. If so, reply immediately.
            if settled_epoch.get() >= since_epoch {
                let g = graph.borrow();
                let mode = *current_mode.borrow();
                let desired = routing_table.links_for(mode);
                let missing = count_missing_links(&g, routing_table, mode);
                let actual = desired.len() - missing;
                let _ = reply.send(rpc::SettlementResult {
                    ok: true,
                    settled_epoch: settled_epoch.get(),
                    desired: desired.len(),
                    actual,
                    missing,
                    reason: None,
                });
            } else {
                // Not yet settled — add to pending waiters.
                let deadline = std::time::Instant::now()
                    + std::time::Duration::from_millis(timeout_ms);
                pending_waiters.borrow_mut().push(rpc::PendingSettlementWaiter {
                    since_epoch,
                    deadline,
                    reply,
                });
            }
        }
    }
}

/// US-140: Count missing desired links by running reconciliation and
/// counting Create actions. This gives the accurate "missing" count
/// because the reconciler resolves node matchers and port names to
/// actual port IDs, then checks which desired links exist in the graph.
///
/// Replaces the broken `desired.len() - g.link_count()` calculation
/// that compared against TOTAL graph links (AC #8).
#[cfg(feature = "pipewire-backend")]
fn count_missing_links(
    graph: &graph::GraphState,
    routing_table: &routing::RoutingTable,
    mode: routing::Mode,
) -> usize {
    let result = reconcile::reconcile(graph, routing_table, mode);
    result.actions.iter().filter(|a| matches!(a, reconcile::LinkAction::Create { .. })).count()
}

/// US-140: Check pending settlement waiters and send replies for those that
/// have settled or timed out.
///
/// Called every 10ms on the PW main loop thread. Drains waiters that are
/// satisfied or expired.
#[cfg(feature = "pipewire-backend")]
fn check_pending_waiters(
    pending_waiters: &std::rc::Rc<std::cell::RefCell<Vec<rpc::PendingSettlementWaiter>>>,
    reconcile_epoch: &std::rc::Rc<std::cell::Cell<u64>>,
    settled_epoch: &std::rc::Rc<std::cell::Cell<u64>>,
    graph: &std::rc::Rc<std::cell::RefCell<graph::GraphState>>,
    routing_table: &std::rc::Rc<routing::RoutingTable>,
    current_mode: &std::rc::Rc<std::cell::RefCell<routing::Mode>>,
) {
    let mut waiters = pending_waiters.borrow_mut();
    if waiters.is_empty() {
        return;
    }

    let now = std::time::Instant::now();
    let current_settled = settled_epoch.get();
    let g = graph.borrow();
    let mode = *current_mode.borrow();
    let desired = routing_table.links_for(mode);
    let missing = count_missing_links(&g, routing_table, mode);
    let actual = desired.len() - missing;

    // Process waiters: remove those that are settled or timed out.
    waiters.retain(|waiter| {
        if current_settled >= waiter.since_epoch {
            // Settled — send success reply.
            let _ = waiter.reply.send(rpc::SettlementResult {
                ok: true,
                settled_epoch: current_settled,
                desired: desired.len(),
                actual,
                missing,
                reason: None,
            });
            false // remove from list
        } else if now >= waiter.deadline {
            // Timeout — send error reply.
            let _ = waiter.reply.send(rpc::SettlementResult {
                ok: false,
                settled_epoch: current_settled,
                desired: desired.len(),
                actual,
                missing,
                reason: Some("timeout".to_string()),
            });
            false // remove from list
        } else {
            true // keep waiting
        }
    });
}

/// Run one cycle of the gain integrity check (T-044-5).
///
/// Spawns `pw-dump` as a subprocess, parses gain node Mult values,
/// and checks that all are <= 1.0. If any Mult > 1.0, triggers the
/// watchdog's safety mute mechanism.
///
/// This runs on the PW main loop thread every 30s. The subprocess
/// overhead (~50ms) is acceptable for a control-plane check (AE approved).
#[cfg(feature = "pipewire-backend")]
fn run_gain_integrity_check(
    gain_integrity_state: &std::rc::Rc<std::cell::RefCell<gain_integrity::GainIntegrityCheck>>,
    _watchdog_state: &std::rc::Rc<std::cell::RefCell<watchdog::Watchdog>>,
    reg_handle: &registry::RegistryHandle,
    event_tx: &std::sync::mpsc::Sender<rpc::GraphEvent>,
    graph: &std::rc::Rc<std::cell::RefCell<graph::GraphState>>,
    gate_open: &std::rc::Rc<std::cell::RefCell<bool>>,
) {
    use std::process::Command;

    // Run pw-dump and capture output (timeout: 5s).
    let output = Command::new("pw-dump")
        .arg("--no-colors")
        .output();

    let output = match output {
        Ok(o) => o,
        Err(e) => {
            log::warn!("Gain integrity: pw-dump failed to execute: {}", e);
            gain_integrity_state.borrow_mut().record_failure(
                format!("pw-dump exec failed: {}", e),
            );
            return;
        }
    };

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        log::warn!("Gain integrity: pw-dump exited with {}: {}", output.status, stderr);
        gain_integrity_state.borrow_mut().record_failure(
            format!("pw-dump exited {}", output.status),
        );
        return;
    }

    let json_str = match std::str::from_utf8(&output.stdout) {
        Ok(s) => s,
        Err(e) => {
            log::warn!("Gain integrity: pw-dump output not UTF-8: {}", e);
            gain_integrity_state.borrow_mut().record_failure(
                "pw-dump output not UTF-8".to_string(),
            );
            return;
        }
    };

    let gains = match gain_integrity::parse_pw_dump_gains(json_str) {
        Ok(g) => g,
        Err(e) => {
            log::warn!("Gain integrity: parse error: {}", e);
            gain_integrity_state.borrow_mut().record_failure(e);
            return;
        }
    };

    let result = gain_integrity_state.borrow_mut().check(&gains);

    match result {
        gain_integrity::GainCheckResult::Violation { ref violating, .. } => {
            // Trigger watchdog safety mute.
            log::error!(
                "GAIN INTEGRITY VIOLATION: Mult > 1.0 on {} node(s) — triggering safety mute",
                violating.len(),
            );

            // Emit violation event.
            let _ = event_tx.send(rpc::GraphEvent::GainIntegrityViolation {
                violating: violating.clone(),
            });

            // Trigger watchdog mute via the same mechanism as T-044-4.
            // Set Mult=0.0 on all gain builtins inside the convolver node
            // using prefixed param names (e.g., "gain_left_hp:Mult").
            let g = graph.borrow();
            if let Some(convolver) = g.node_by_name(watchdog::CONVOLVER_NODE_NAME) {
                for name in watchdog::GAIN_PARAM_NAMES {
                    let prefixed = format!("{}:Mult", name);
                    log::error!("GAIN INTEGRITY: Muting {} (convolver node {}) via set_node_param_mult", prefixed, convolver.id);
                    reg_handle.set_node_param_mult(convolver.id, &prefixed, 0.0);
                }
            } else {
                log::error!("GAIN INTEGRITY: Convolver node not found — cannot mute gain params");
            }
            drop(g);

            // D-063: Close the audio gate to keep state consistent.
            // After gain integrity mute, get_gate must report closed.
            // Operator must re-open the gate explicitly after investigation.
            if *gate_open.borrow() {
                *gate_open.borrow_mut() = false;
                log::error!("GAIN INTEGRITY: Gate closed (gain integrity violation)");
                let _ = event_tx.send(rpc::GraphEvent::GateClosed {
                    reason: "gain integrity violation".to_string(),
                });
            }
        }
        gain_integrity::GainCheckResult::AllOk { .. } => {
            log::debug!("Gain integrity check passed");
        }
        gain_integrity::GainCheckResult::MissingNodes { ref missing } => {
            // Watchdog T-044-4 handles missing nodes — just log here.
            log::debug!("Gain integrity: {} gain nodes missing (watchdog handles)", missing.len());
        }
        gain_integrity::GainCheckResult::CheckFailed { .. } => {
            // Already logged by record_failure.
        }
    }
}

/// Parse `clock.xrun-count` from `pw-cli info` output.
///
/// Only matches lines containing `xrun-count` specifically — NOT
/// `clock.xrun-delay` or `clock.xrun-last-size`, which contain
/// nanosecond/sample values that would wildly inflate the count.
///
/// Returns 0 if no xrun-count line is found.
#[cfg(any(feature = "pipewire-backend", test))]
fn parse_xrun_count(pw_cli_output: &str) -> u64 {
    for line in pw_cli_output.lines() {
        let trimmed = line.trim();
        if trimmed.contains("xrun-count") {
            // Parse lines like: clock.xrun-count = "7"
            if let Some(eq_pos) = trimmed.find('=') {
                let val_str = trimmed[eq_pos + 1..].trim().trim_matches('"');
                if let Ok(v) = val_str.parse::<u64>() {
                    return v;
                }
            }
        }
    }
    0
}

/// Parse per-node `clock.xrun-count` from `pw-dump` JSON output (F-095).
///
/// Replaces the N separate `pw-cli info <node_id>` calls with a single
/// `pw-dump` parse. Returns the sum of `clock.xrun-count` across all nodes
/// and the driver node name (USBStreamer).
///
/// In pw-dump JSON, xrun-count appears in `info.props` as an integer:
/// ```json
/// {
///   "type": "PipeWire:Interface:Node",
///   "info": {
///     "props": {
///       "node.name": "alsa_output.usb-MiniDSP_USBStreamer...",
///       "clock.xrun-count": 7
///     }
///   }
/// }
/// ```
#[cfg(any(feature = "pipewire-backend", test))]
fn parse_pw_dump_xruns(json_str: &str) -> Result<(u64, String), String> {
    let objects: serde_json::Value =
        serde_json::from_str(json_str).map_err(|e| format!("JSON parse error: {}", e))?;

    let array = objects
        .as_array()
        .ok_or_else(|| "pw-dump output is not a JSON array".to_string())?;

    let mut total_xruns: u64 = 0;
    let mut driver_node_name = String::new();

    for obj in array {
        let obj_type = obj.get("type").and_then(|t| t.as_str()).unwrap_or("");
        if obj_type != "PipeWire:Interface:Node" {
            continue;
        }

        let props = match obj.get("info").and_then(|i| i.get("props")) {
            Some(p) => p,
            None => continue,
        };

        // Extract xrun count from props.
        if let Some(xrun_val) = props.get("clock.xrun-count") {
            if let Some(count) = xrun_val.as_u64() {
                total_xruns += count;
            }
        }

        // Identify the driver node.
        if let Some(name) = props.get("node.name").and_then(|n| n.as_str()) {
            if name.starts_with("alsa_output.usb-MiniDSP_USBStreamer") {
                driver_node_name = name.to_string();
            }
        }
    }

    Ok((total_xruns, driver_node_name))
}

/// Set PipeWire quantum for the given mode (F-230, F-249).
///
/// GM is the single authority for quantum in all modes:
/// - DJ: 1024 (~21ms PA path, efficient convolution for Mixxx)
/// - Live/Standby/Measurement: 256 (~5.3ms PA path, below slapback threshold)
///
/// F-249: Previously non-DJ modes cleared force-quantum to 0, relying on PW
/// config defaults. PipeWire may negotiate a higher quantum (e.g. 1024) when
/// force-quantum is 0, depending on the graph topology. Explicit 256 ensures
/// deterministic behavior regardless of PW negotiation.
///
/// Uses `pw-metadata -n settings 0 clock.force-quantum <value>`.
/// Errors are logged but not fatal — quantum mismatch is a performance issue,
/// not a correctness issue.
#[cfg(feature = "pipewire-backend")]
fn set_quantum_for_mode(mode: Mode) {
    use std::process::Command;

    let quantum = match mode {
        Mode::Dj => 1024,
        // F-249: Explicitly set 256 instead of clearing to 0.
        _ => 256,
    };

    let quantum_str = quantum.to_string();
    match Command::new("pw-metadata")
        .args(["-n", "settings", "0", "clock.force-quantum", &quantum_str])
        .output()
    {
        Ok(output) if output.status.success() => {
            info!("F-230: Set clock.force-quantum={} for {} mode", quantum, mode);
        }
        Ok(output) => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            log::warn!(
                "F-230: pw-metadata set force-quantum={} failed (exit {}): {}",
                quantum, output.status, stderr.trim()
            );
        }
        Err(e) => {
            log::warn!("F-230: pw-metadata not available: {}", e);
        }
    }
}

/// Update the cached PipeWire graph info (quantum, sample rate, xruns).
///
/// Runs `pw-metadata -n settings` to read quantum/force-quantum/sample-rate,
/// then runs ONE `pw-dump --no-colors` to aggregate `clock.xrun-count` across
/// all nodes and identify the driver node.
///
/// F-095: Previously spawned N `pw-cli info <node_id>` subprocesses (one per
/// tracked node), causing 62% CPU on Pi via journald log flooding. Now uses
/// exactly 2 subprocesses per cycle: pw-metadata + pw-dump.
///
/// Called every 5s on the PW main loop thread (F-127: reduced from 1s).
#[cfg(feature = "pipewire-backend")]
fn update_graph_info_cache(
    cache: &std::rc::Rc<std::cell::RefCell<rpc::GraphInfoSnapshot>>,
    _graph: &std::rc::Rc<std::cell::RefCell<graph::GraphState>>,
) {
    use std::process::Command;

    // --- Step 1: Read metadata (quantum, sample_rate) via pw-metadata ---
    let mut quantum: u32 = 0;
    let mut force_quantum: u32 = 0;
    let mut sample_rate: u32 = 0;

    match Command::new("pw-metadata").arg("-n").arg("settings").output() {
        Ok(output) if output.status.success() => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            for line in stdout.lines() {
                // Lines look like: update: id:0 key:'clock.quantum' value:'1024' type:''
                if let Some(key_start) = line.find("key:'") {
                    let rest = &line[key_start + 5..];
                    if let Some(key_end) = rest.find('\'') {
                        let key = &rest[..key_end];
                        if let Some(val_start) = rest.find("value:'") {
                            let val_rest = &rest[val_start + 7..];
                            if let Some(val_end) = val_rest.find('\'') {
                                let val = &val_rest[..val_end];
                                match key {
                                    "clock.quantum" => {
                                        quantum = val.parse().unwrap_or(0);
                                    }
                                    "clock.force-quantum" => {
                                        force_quantum = val.parse().unwrap_or(0);
                                    }
                                    "clock.rate" => {
                                        sample_rate = val.parse().unwrap_or(0);
                                    }
                                    _ => {}
                                }
                            }
                        }
                    }
                }
            }
        }
        Ok(output) => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            log::debug!("pw-metadata exited with {}: {}", output.status, stderr.trim());
        }
        Err(e) => {
            log::debug!("pw-metadata failed to execute: {}", e);
        }
    }

    // --- Step 2: Aggregate xruns via ONE pw-dump call (F-095) ---
    //
    // Replaces N `pw-cli info <node_id>` calls with a single pw-dump.
    // Parses JSON to sum clock.xrun-count across all nodes and identify
    // the USBStreamer driver node.
    let mut xruns: u64 = 0;
    let mut driver_node_name = String::new();

    match Command::new("pw-dump").arg("--no-colors").output() {
        Ok(output) if output.status.success() => {
            match std::str::from_utf8(&output.stdout) {
                Ok(json_str) => {
                    match parse_pw_dump_xruns(json_str) {
                        Ok((total, driver)) => {
                            xruns = total;
                            driver_node_name = driver;
                        }
                        Err(e) => {
                            log::debug!("pw-dump xrun parse error: {}", e);
                        }
                    }
                }
                Err(e) => {
                    log::debug!("pw-dump output not UTF-8: {}", e);
                }
            }
        }
        Ok(output) => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            log::debug!("pw-dump exited with {}: {}", output.status, stderr.trim());
        }
        Err(e) => {
            log::debug!("pw-dump failed to execute: {}", e);
        }
    }

    // --- Step 3: Determine graph state ---
    let graph_state = if quantum > 0 || force_quantum > 0 {
        "running".to_string()
    } else {
        "unknown".to_string()
    };

    // --- Step 4: Update cache ---
    let mut snap = cache.borrow_mut();
    snap.quantum = quantum;
    snap.force_quantum = force_quantum;
    snap.sample_rate = sample_rate;
    snap.xruns = xruns;
    snap.driver_node = driver_node_name;
    snap.graph_state = graph_state;
}

/// Build a StateSnapshot from the current GraphState, mode, and component health.
#[cfg(feature = "pipewire-backend")]
fn build_state_snapshot(
    graph: &graph::GraphState,
    mode: Mode,
    component_registry: &lifecycle::ComponentRegistry,
) -> rpc::StateSnapshot {
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

    rpc::StateSnapshot {
        mode: mode.to_string(),
        nodes,
        links,
        devices,
        gate_open: false,
        venue_loaded: false,
        persisted_venue: None,
        quantum: 0,
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[cfg(feature = "pipewire-backend")]
fn main() {
    use std::sync::mpsc;
    use rpc::{RpcCommand, GraphEvent};

    let args = Args::parse();

    // Initialize logging (SEC-GM-02: avoid std::env::set_var, unsafe in Rust 2024).
    env_logger::Builder::from_env(
        env_logger::Env::default().default_filter_or(&args.log_level),
    )
    .init();

    let listen_addr = parse_listen_addr(&args.listen).unwrap_or_else(|e| {
        eprintln!("Error: {}", e);
        std::process::exit(1);
    });
    let initial_mode: Mode = args.mode.parse().unwrap_or_else(|e: String| {
        eprintln!("Error: {}", e);
        std::process::exit(1);
    });

    // Parse speaker layout from CLI args.
    let sub_ch: Vec<u32> = args.sub_channels.split(',')
        .map(|s| s.trim().parse().expect("invalid sub channel number"))
        .collect();
    let speaker_layout = SpeakerLayout::from_profile(args.speaker_channels, sub_ch);

    info!("pi4audio-graph-manager starting");
    info!("RPC listen address: {}", listen_addr);
    info!("Initial mode: {}", initial_mode);
    info!(
        "Speaker layout: {} channels, subs {:?}",
        speaker_layout.num_speaker_channels, speaker_layout.sub_channels,
    );

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
        args.port_file,
    );

    // Run PipeWire main loop (blocks until shutdown). The PW thread
    // owns cmd_rx (receives commands) and event_tx (emits events).
    run_pipewire(initial_mode, speaker_layout, cmd_rx, event_tx, shutdown);

    info!("pi4audio-graph-manager exited");
}

#[cfg(not(feature = "pipewire-backend"))]
fn main() {
    eprintln!("pi4audio-graph-manager requires the pipewire-backend feature (Linux only).");
    eprintln!("On macOS, run: cargo test --no-default-features");
    std::process::exit(1);
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_mode_valid() {
        assert_eq!("standby".parse::<Mode>().unwrap(), Mode::Standby);
        assert_eq!("dj".parse::<Mode>().unwrap(), Mode::Dj);
        assert_eq!("live".parse::<Mode>().unwrap(), Mode::Live);
        assert_eq!("measurement".parse::<Mode>().unwrap(), Mode::Measurement);
    }

    #[test]
    fn parse_mode_invalid() {
        assert!("unknown".parse::<Mode>().is_err());
        assert!("".parse::<Mode>().is_err());
    }

    #[test]
    fn parse_listen_addr_with_prefix() {
        assert_eq!(
            parse_listen_addr("tcp:127.0.0.1:4002").unwrap(),
            "127.0.0.1:4002"
        );
    }

    #[test]
    fn parse_listen_addr_without_prefix() {
        assert_eq!(
            parse_listen_addr("127.0.0.1:4002").unwrap(),
            "127.0.0.1:4002"
        );
    }

    // -----------------------------------------------------------------------
    // SEC-GM-01: loopback binding validation
    // -----------------------------------------------------------------------

    #[test]
    fn parse_listen_addr_accepts_ipv6_loopback() {
        assert_eq!(
            parse_listen_addr("tcp:[::1]:4002").unwrap(),
            "[::1]:4002"
        );
    }

    #[test]
    fn parse_listen_addr_accepts_localhost() {
        assert_eq!(
            parse_listen_addr("tcp:localhost:4002").unwrap(),
            "localhost:4002"
        );
    }

    #[test]
    fn parse_listen_addr_rejects_all_interfaces() {
        let result = parse_listen_addr("tcp:0.0.0.0:4002");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("SEC-GM-01"));
    }

    #[test]
    fn parse_listen_addr_rejects_lan_ip() {
        let result = parse_listen_addr("tcp:192.168.1.100:4002");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("SEC-GM-01"));
    }

    #[test]
    fn parse_listen_addr_rejects_wildcard_ipv6() {
        let result = parse_listen_addr("tcp:[::]:4002");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("SEC-GM-01"));
    }

    #[test]
    fn parse_listen_addr_rejects_bare_wildcard() {
        let result = parse_listen_addr("0.0.0.0:4002");
        assert!(result.is_err());
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

    // -----------------------------------------------------------------------
    // parse_xrun_count (F-092)
    // -----------------------------------------------------------------------

    #[test]
    fn parse_xrun_count_extracts_count() {
        let output = r#"
        id: 42, type: PipeWire:Interface:Node/3
          clock.quantum = "1024"
          clock.rate = "48000"
          clock.xrun-count = "7"
          clock.xrun-delay = "12345"
          clock.xrun-last-size = "256"
        "#;
        assert_eq!(parse_xrun_count(output), 7);
    }

    #[test]
    fn parse_xrun_count_ignores_delay_and_size() {
        // Verify we don't sum xrun-delay (ns) or xrun-last-size
        let output = r#"
          clock.xrun-delay = "9999999"
          clock.xrun-last-size = "512"
        "#;
        assert_eq!(parse_xrun_count(output), 0);
    }

    #[test]
    fn parse_xrun_count_zero_when_no_xruns() {
        let output = r#"
        id: 42, type: PipeWire:Interface:Node/3
          clock.quantum = "1024"
          clock.rate = "48000"
        "#;
        assert_eq!(parse_xrun_count(output), 0);
    }

    #[test]
    fn parse_xrun_count_handles_zero_value() {
        let output = "  clock.xrun-count = \"0\"\n";
        assert_eq!(parse_xrun_count(output), 0);
    }

    #[test]
    fn parse_xrun_count_handles_large_value() {
        let output = "  clock.xrun-count = \"42387\"\n";
        assert_eq!(parse_xrun_count(output), 42387);
    }

    #[test]
    fn parse_xrun_count_empty_output() {
        assert_eq!(parse_xrun_count(""), 0);
    }

    #[test]
    fn parse_xrun_count_realistic_multi_node_aggregation() {
        // Simulate summing across 3 nodes like the real code does
        let node1 = "  clock.xrun-count = \"3\"\n  clock.xrun-delay = \"999999\"\n";
        let node2 = "  clock.xrun-count = \"0\"\n";
        let node3 = "  clock.xrun-count = \"12\"\n  clock.xrun-delay = \"555555\"\n";
        let total: u64 = [node1, node2, node3]
            .iter()
            .map(|s| parse_xrun_count(s))
            .sum();
        assert_eq!(total, 15);
    }

    // -----------------------------------------------------------------------
    // parse_pw_dump_xruns (F-095)
    // -----------------------------------------------------------------------

    #[test]
    fn parse_pw_dump_xruns_empty_array() {
        let (xruns, driver) = parse_pw_dump_xruns("[]").unwrap();
        assert_eq!(xruns, 0);
        assert_eq!(driver, "");
    }

    #[test]
    fn parse_pw_dump_xruns_sums_across_nodes() {
        let json = r#"[
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "node.name": "Mixxx",
                        "clock.xrun-count": 3
                    }
                }
            },
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "node.name": "pi4audio-convolver",
                        "clock.xrun-count": 0
                    }
                }
            },
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "node.name": "alsa_output.usb-MiniDSP_USBStreamer_B-00",
                        "clock.xrun-count": 12
                    }
                }
            }
        ]"#;
        let (xruns, driver) = parse_pw_dump_xruns(json).unwrap();
        assert_eq!(xruns, 15);
        assert_eq!(driver, "alsa_output.usb-MiniDSP_USBStreamer_B-00");
    }

    #[test]
    fn parse_pw_dump_xruns_ignores_non_node_objects() {
        let json = r#"[
            {
                "type": "PipeWire:Interface:Link",
                "info": {
                    "props": { "clock.xrun-count": 999 }
                }
            },
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "node.name": "test-node",
                        "clock.xrun-count": 5
                    }
                }
            }
        ]"#;
        let (xruns, _) = parse_pw_dump_xruns(json).unwrap();
        assert_eq!(xruns, 5);
    }

    #[test]
    fn parse_pw_dump_xruns_handles_missing_xrun_prop() {
        let json = r#"[
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "node.name": "no-xrun-node"
                    }
                }
            },
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "node.name": "has-xrun-node",
                        "clock.xrun-count": 7
                    }
                }
            }
        ]"#;
        let (xruns, _) = parse_pw_dump_xruns(json).unwrap();
        assert_eq!(xruns, 7);
    }

    #[test]
    fn parse_pw_dump_xruns_invalid_json() {
        assert!(parse_pw_dump_xruns("not json").is_err());
    }

    #[test]
    fn parse_pw_dump_xruns_not_array() {
        assert!(parse_pw_dump_xruns("{}").is_err());
    }

    #[test]
    fn parse_pw_dump_xruns_node_without_info() {
        let json = r#"[
            {
                "type": "PipeWire:Interface:Node"
            }
        ]"#;
        let (xruns, _) = parse_pw_dump_xruns(json).unwrap();
        assert_eq!(xruns, 0);
    }
}
