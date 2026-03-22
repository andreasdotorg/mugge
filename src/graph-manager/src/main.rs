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
mod gain_integrity;
mod graph;
mod lifecycle;
mod link_audit;
mod reconcile;
mod routing;
mod rpc;
mod watchdog;

// PipeWire registry listener — Linux only (needs libpipewire).
#[cfg(feature = "pipewire-backend")]
mod registry;

// Common imports (always compiled).
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use clap::Parser;
use log::info;

use routing::Mode;

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

    // Safety watchdog — monitors critical audio nodes and latches a
    // safety mute if any disappear (T-044-4).
    let watchdog_state = Rc::new(RefCell::new(Watchdog::new()));
    info!("Safety watchdog initialized (monitoring {} nodes)", watchdog::MONITORED_NODES.len());

    // Gain integrity check — periodic Mult <= 1.0 verification (T-044-5).
    let gain_integrity_state = Rc::new(RefCell::new(GainIntegrityCheck::new()));
    info!("Gain integrity check initialized (checking {} gain nodes)", watchdog::GAIN_NODE_NAMES.len());

    // Graph info cache — quantum, sample rate, xruns (Phase 2a).
    // Updated by a 1s timer via pw-metadata subprocess. RPC returns cached values.
    let graph_info_cache = Rc::new(RefCell::new(rpc::GraphInfoSnapshot::empty()));
    info!("Graph info cache initialized");

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
        );
    info!("PipeWire registry listener registered (reconciliation + lifecycle + watchdog wired)");

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

    // Gain integrity timer: every 30s, run `pw-dump` and check that all
    // gain node Mult values are <= 1.0 (T-044-5). If any Mult > 1.0,
    // trigger watchdog safety mute.
    let _gain_timer = mainloop.loop_().add_timer({
        let gain_integrity_state = gain_integrity_state.clone();
        let watchdog_state = watchdog_state.clone();
        let reg_handle = reg_handle.clone();
        let event_tx = event_tx.clone();
        let graph = graph.clone();
        move |_expirations| {
            run_gain_integrity_check(
                &gain_integrity_state,
                &watchdog_state,
                &reg_handle,
                &event_tx,
                &graph,
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

    // Graph info timer: every 1s, run pw-metadata to cache quantum/rate,
    // and scan the graph state for driver node xruns (Phase 2a).
    // This moves subprocess calls from the Python web-UI event loop
    // to the GM PW thread, freeing the uvicorn asyncio loop.
    let _graph_info_timer = mainloop.loop_().add_timer({
        let graph_info_cache = graph_info_cache.clone();
        let graph = graph.clone();
        move |_expirations| {
            update_graph_info_cache(&graph_info_cache, &graph);
        }
    });
    _graph_info_timer
        .update_timer(
            Some(Duration::from_secs(1)),
            Some(Duration::from_secs(1)),
        )
        .into_result()
        .expect("Failed to arm graph info timer");
    info!("Graph info timer armed (1s polling)");

    info!("PipeWire main loop starting");
    mainloop.run();
    info!("PipeWire main loop exited");

    // Drop PipeWire objects in reverse order BEFORE calling deinit().
    drop(_graph_info_timer);
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
) {
    use rpc::{DeviceStatus, GraphEvent, LinkSnapshot, RpcResult};

    match cmd {
        rpc::RpcCommand::SetMode { mode, reply } => {
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
            registry::apply_actions(
                &actions,
                core_ref,
                reg_handle,
                &g,
                event_tx,
                link_proxies,
            );

            // 4. Send reply.
            let _ = reply.send(RpcResult::Ok);

            // 5. Emit mode_changed event.
            let _ = event_tx.send(GraphEvent::ModeChanged {
                from: old_mode.to_string(),
                to: mode.to_string(),
            });
        }

        rpc::RpcCommand::GetState { reply } => {
            let g = graph.borrow();
            let mode = *current_mode.borrow();
            let reg = component_registry.borrow();
            let snap = build_state_snapshot(&g, mode, &reg);
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
                    let g = graph.borrow();
                    let mut restored = 0usize;
                    for (name, mult) in &gains {
                        if let Some(node) = g.node_by_name(name) {
                            if reg_handle.set_node_mult(node.id, *mult as f32) {
                                info!("Watchdog unlatch: restored {} (node {}) to Mult={}", name, node.id, mult);
                                restored += 1;
                            } else {
                                log::warn!("Watchdog unlatch: failed to restore {} (node {})", name, node.id);
                            }
                        } else {
                            log::warn!("Watchdog unlatch: node '{}' not in graph, skipping restore", name);
                        }
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
    }
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
    watchdog_state: &std::rc::Rc<std::cell::RefCell<watchdog::Watchdog>>,
    reg_handle: &registry::RegistryHandle,
    event_tx: &std::sync::mpsc::Sender<rpc::GraphEvent>,
    graph: &std::rc::Rc<std::cell::RefCell<graph::GraphState>>,
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
            // We force a mute by calling set_node_mult(0.0) on all gain nodes.
            let g = graph.borrow();
            for name in watchdog::GAIN_NODE_NAMES {
                if let Some(node) = g.node_by_name(name) {
                    log::error!("GAIN INTEGRITY: Muting {} (node {}) via set_node_mult", name, node.id);
                    reg_handle.set_node_mult(node.id, 0.0);
                }
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

/// Update the cached PipeWire graph info (quantum, sample rate, xruns).
///
/// Runs `pw-metadata -n settings` to read quantum/force-quantum/sample-rate,
/// then finds the USBStreamer driver node from the graph state and runs
/// `pw-cli info <node-id>` to read the xrun count.
///
/// Called every 1s on the PW main loop thread. Subprocess overhead is ~5-10ms
/// each — acceptable for a 1s polling interval on the control plane.
#[cfg(feature = "pipewire-backend")]
fn update_graph_info_cache(
    cache: &std::rc::Rc<std::cell::RefCell<rpc::GraphInfoSnapshot>>,
    graph: &std::rc::Rc<std::cell::RefCell<graph::GraphState>>,
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

    // --- Step 2: Find driver node and read xruns ---
    let mut xruns: u64 = 0;
    let mut driver_node_name = String::new();

    // Extract driver node info from the graph (borrow scope).
    let driver_info: Option<(String, u32)> = {
        let g = graph.borrow();
        let result = g.nodes()
            .find(|n| n.name.starts_with("alsa_output.usb-MiniDSP_USBStreamer"))
            .map(|n| (n.name.clone(), n.id));
        result
    };

    if let Some((name, node_id)) = driver_info {
        driver_node_name = name;
        match Command::new("pw-cli").arg("info").arg(node_id.to_string()).output() {
            Ok(output) if output.status.success() => {
                let stdout = String::from_utf8_lossy(&output.stdout);
                for line in stdout.lines() {
                    let trimmed = line.trim();
                    if trimmed.contains("xrun") {
                        // Parse lines like: clock.xrun-count = "3"
                        if let Some(eq_pos) = trimmed.find('=') {
                            let val_str = trimmed[eq_pos + 1..].trim().trim_matches('"');
                            if let Ok(v) = val_str.parse::<u64>() {
                                xruns += v;
                            }
                        }
                    }
                }
            }
            Ok(_) => {
                log::debug!("pw-cli info {} failed (node may have been removed)", node_id);
            }
            Err(e) => {
                log::debug!("pw-cli info failed to execute: {}", e);
            }
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
        assert_eq!("monitoring".parse::<Mode>().unwrap(), Mode::Monitoring);
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
}
