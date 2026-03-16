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

mod graph;
mod registry;
mod routing;

use std::cell::RefCell;
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use clap::Parser;
use log::info;

use graph::GraphState;
use routing::{Mode, RoutingTable};

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

/// Run the PipeWire main loop with registry listener and graph tracking.
///
/// This function blocks until the shutdown flag is set.
fn run_pipewire(
    initial_mode: Mode,
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

    // Register registry listener (push-based graph awareness).
    let (_registry, _registry_listener) =
        registry::register_graph_listener(&core, graph.clone());
    info!("PipeWire registry listener registered");

    // Build the routing table.
    let _routing_table = RoutingTable::production();
    info!("Routing table loaded ({} modes)", Mode::ALL.len());
    info!("Initial mode: {}", initial_mode);

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

    info!("PipeWire main loop starting");
    mainloop.run();
    info!("PipeWire main loop exited");

    // Drop PipeWire objects in reverse order BEFORE calling deinit().
    drop(_shutdown_timer);
    drop(_registry_listener);
    drop(_registry);
    drop(graph);
    drop(core);
    drop(context);
    drop(mainloop);

    unsafe {
        pipewire::deinit();
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

    // Run PipeWire main loop (blocks until shutdown).
    // TODO (GM-3): Start RPC server thread before PW loop.
    run_pipewire(initial_mode, shutdown);

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
