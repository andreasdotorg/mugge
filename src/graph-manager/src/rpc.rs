//! TCP RPC server for JSON command interface.
//!
//! Listens on a localhost TCP port (default 127.0.0.1:4002) and accepts
//! newline-delimited JSON commands. Push events are broadcast to all
//! connected clients.
//!
//! Line length is capped at 4096 bytes per SEC-D037-03.
//!
//! ## Protocol
//!
//! - Request: `{"cmd": "<name>", ...fields}\n`
//! - Ack: `{"type": "ack", "cmd": "<name>", "ok": true/false, ...}\n`
//! - Response: `{"type": "response", "cmd": "<name>", "ok": true, ...data}\n`
//! - Event: `{"type": "event", "event": "<name>", ...data}\n`
//!
//! ## Thread model
//!
//! The RPC server runs on its own thread. All PW API calls happen on the
//! PW main loop thread. Communication between threads uses `std::sync::mpsc`
//! channels: commands flow RPC → PW, events flow PW → RPC.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;

use log::{debug, error, info, warn};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::routing::Mode;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// Maximum line length in bytes (SEC-D037-03).
pub const MAX_LINE_LENGTH: usize = 4096;

/// Default RPC listen address.
pub const DEFAULT_ADDR: &str = "127.0.0.1:4002";

// ---------------------------------------------------------------------------
// Incoming JSON request
// ---------------------------------------------------------------------------

/// Raw JSON request from a client (before validation).
#[derive(Debug, Deserialize)]
pub struct RpcRequest {
    pub cmd: String,
    #[serde(default)]
    pub mode: Option<String>,
}

// ---------------------------------------------------------------------------
// Outgoing JSON responses
// ---------------------------------------------------------------------------

/// Acknowledgment response (command accepted/rejected).
#[derive(Debug, Serialize)]
pub struct AckResponse {
    pub r#type: &'static str,
    pub cmd: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// State query response.
#[derive(Debug, Serialize)]
pub struct StateResponse {
    pub r#type: &'static str,
    pub cmd: &'static str,
    pub ok: bool,
    pub mode: String,
    pub nodes: Vec<NodeInfo>,
    pub links: Vec<LinkInfo>,
    pub devices: HashMap<String, String>,
}

/// Device query response.
#[derive(Debug, Serialize)]
pub struct DevicesResponse {
    pub r#type: &'static str,
    pub cmd: &'static str,
    pub ok: bool,
    pub devices: Vec<DeviceStatus>,
}

/// Link topology query response.
#[derive(Debug, Serialize)]
pub struct LinksResponse {
    pub r#type: &'static str,
    pub cmd: &'static str,
    pub ok: bool,
    pub mode: String,
    pub desired: usize,
    pub actual: usize,
    pub missing: usize,
    pub links: Vec<LinkDetail>,
}

// ---------------------------------------------------------------------------
// Snapshot types (sent from PW thread to RPC thread)
// ---------------------------------------------------------------------------

/// Snapshot of the full graph state for `get_state` responses.
#[derive(Debug, Clone, Serialize)]
pub struct StateSnapshot {
    pub mode: String,
    pub nodes: Vec<NodeInfo>,
    pub links: Vec<LinkInfo>,
    pub devices: HashMap<String, String>,
}

impl StateSnapshot {
    /// Default empty snapshot (monitoring mode, no data).
    pub fn empty() -> Self {
        let mut devices = HashMap::new();
        devices.insert("usbstreamer".to_string(), "unknown".to_string());
        devices.insert("umik1".to_string(), "unknown".to_string());
        devices.insert("convolver".to_string(), "unknown".to_string());
        devices.insert("convolver-out".to_string(), "unknown".to_string());
        Self {
            mode: "monitoring".to_string(),
            nodes: Vec::new(),
            links: Vec::new(),
            devices,
        }
    }
}

/// Node info for RPC responses.
#[derive(Debug, Clone, Serialize)]
pub struct NodeInfo {
    pub id: u32,
    pub name: String,
    pub media_class: String,
}

/// Link info for RPC responses (raw PW IDs).
#[derive(Debug, Clone, Serialize)]
pub struct LinkInfo {
    pub id: u32,
    pub output_node: u32,
    pub output_port: u32,
    pub input_node: u32,
    pub input_port: u32,
}

/// Device status for `get_devices` responses.
#[derive(Debug, Clone, Serialize)]
pub struct DeviceStatus {
    pub name: String,
    pub node_name: String,
    pub status: String,
}

impl DeviceStatus {
    /// Default device list with "unknown" status.
    pub fn defaults() -> Vec<Self> {
        vec![
            Self {
                name: "usbstreamer".to_string(),
                node_name: "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0".to_string(),
                status: "unknown".to_string(),
            },
            Self {
                name: "umik1".to_string(),
                node_name: "alsa_input.usb-miniDSP_UMIK-1-00.mono-fallback".to_string(),
                status: "unknown".to_string(),
            },
            Self {
                name: "convolver".to_string(),
                node_name: "pi4audio-convolver".to_string(),
                status: "unknown".to_string(),
            },
            Self {
                name: "convolver-out".to_string(),
                node_name: "pi4audio-convolver-out".to_string(),
                status: "unknown".to_string(),
            },
        ]
    }
}

/// Snapshot of link topology for `get_links` responses.
#[derive(Debug, Clone, Serialize)]
pub struct LinkSnapshot {
    pub mode: String,
    pub desired: usize,
    pub actual: usize,
    pub missing: usize,
    pub links: Vec<LinkDetail>,
}

impl LinkSnapshot {
    /// Default empty snapshot.
    pub fn empty(mode: &str) -> Self {
        Self {
            mode: mode.to_string(),
            desired: 0,
            actual: 0,
            missing: 0,
            links: Vec::new(),
        }
    }
}

/// Individual link detail for `get_links` responses.
#[derive(Debug, Clone, Serialize)]
pub struct LinkDetail {
    pub output_node: String,
    pub output_port: String,
    pub input_node: String,
    pub input_port: String,
    pub status: String,
}

// ---------------------------------------------------------------------------
// Cross-thread command enum (RPC thread → PW main loop thread)
// ---------------------------------------------------------------------------

/// Result of a mode transition.
#[derive(Debug)]
pub enum RpcResult {
    Ok,
    Error(String),
}

/// Commands sent from the RPC thread to the PW main loop thread.
pub enum RpcCommand {
    /// Request a mode transition.
    SetMode {
        mode: Mode,
        reply: mpsc::Sender<RpcResult>,
    },

    /// Request a snapshot of the current graph state.
    GetState {
        reply: mpsc::Sender<StateSnapshot>,
    },

    /// Request the current device list.
    GetDevices {
        reply: mpsc::Sender<Vec<DeviceStatus>>,
    },

    /// Request the current link topology.
    GetLinks {
        reply: mpsc::Sender<LinkSnapshot>,
    },
}

// ---------------------------------------------------------------------------
// Push events (PW main loop thread → RPC thread → all clients)
// ---------------------------------------------------------------------------

/// Events pushed from the PW thread to all connected RPC clients.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "event")]
pub enum GraphEvent {
    #[serde(rename = "node_added")]
    NodeAdded {
        id: u32,
        name: String,
        media_class: String,
    },
    #[serde(rename = "node_removed")]
    NodeRemoved { id: u32, name: String },
    #[serde(rename = "mode_changed")]
    ModeChanged { from: String, to: String },
    #[serde(rename = "link_created")]
    LinkCreated {
        output_node: String,
        output_port: String,
        input_node: String,
        input_port: String,
    },
    #[serde(rename = "link_failed")]
    LinkFailed {
        output_node: String,
        output_port: String,
        input_node: String,
        input_port: String,
        reason: String,
    },
    #[serde(rename = "link_destroyed")]
    LinkDestroyed {
        output_node: String,
        output_port: String,
        input_node: String,
        input_port: String,
    },
    #[serde(rename = "device_connected")]
    DeviceConnected { name: String },
    #[serde(rename = "device_disconnected")]
    DeviceDisconnected { name: String },
}


// ---------------------------------------------------------------------------
// Command handler
// ---------------------------------------------------------------------------

/// Result of handling a parsed RPC request.
pub enum HandleResult {
    /// Ack response JSON.
    Ack(String),
    /// Error response JSON.
    Error(String, String),
    /// Response JSON (data query).
    ResponseJson(String),
}

/// Handle a parsed RPC request.
///
/// For `ping`, responds immediately. For commands that need PW thread data,
/// sends an `RpcCommand` through the channel and blocks on the reply.
pub fn handle_request(
    req: &RpcRequest,
    cmd_tx: &mpsc::Sender<RpcCommand>,
    stored_mode: &Mutex<String>,
) -> HandleResult {
    match req.cmd.as_str() {
        "ping" => HandleResult::Ack("ping".to_string()),
        "set_mode" => handle_set_mode(req, cmd_tx, stored_mode),
        "get_state" => handle_get_state(cmd_tx, stored_mode),
        "get_devices" => handle_get_devices(cmd_tx),
        "get_links" => handle_get_links(cmd_tx, stored_mode),
        other => HandleResult::Error(
            other.to_string(),
            format!("unknown command: \"{}\"", other),
        ),
    }
}

fn handle_set_mode(
    req: &RpcRequest,
    cmd_tx: &mpsc::Sender<RpcCommand>,
    stored_mode: &Mutex<String>,
) -> HandleResult {
    let mode_str = match &req.mode {
        Some(s) => s.as_str(),
        None => {
            return HandleResult::Error(
                "set_mode".to_string(),
                "missing \"mode\" field".to_string(),
            )
        }
    };

    let mode: Mode = match mode_str.parse() {
        Ok(m) => m,
        Err(e) => return HandleResult::Error("set_mode".to_string(), e),
    };

    // Send to PW thread and wait for result.
    let (reply_tx, reply_rx) = mpsc::channel();
    if cmd_tx
        .send(RpcCommand::SetMode {
            mode,
            reply: reply_tx,
        })
        .is_err()
    {
        return HandleResult::Error(
            "set_mode".to_string(),
            "internal: PW thread not responding".to_string(),
        );
    }

    match reply_rx.recv() {
        Ok(RpcResult::Ok) => {
            // Update stored mode.
            if let Ok(mut m) = stored_mode.lock() {
                *m = mode.to_string();
            }
            HandleResult::Ack("set_mode".to_string())
        }
        Ok(RpcResult::Error(e)) => HandleResult::Error("set_mode".to_string(), e),
        Err(_) => HandleResult::Error(
            "set_mode".to_string(),
            "internal: PW thread dropped reply channel".to_string(),
        ),
    }
}

fn handle_get_state(
    cmd_tx: &mpsc::Sender<RpcCommand>,
    stored_mode: &Mutex<String>,
) -> HandleResult {
    let (reply_tx, reply_rx) = mpsc::channel();
    if cmd_tx.send(RpcCommand::GetState { reply: reply_tx }).is_err() {
        // PW thread not available — return stub.
        let mode = stored_mode
            .lock()
            .map(|m| m.clone())
            .unwrap_or_else(|_| "monitoring".to_string());
        let snap = StateSnapshot::empty();
        let resp = StateResponse {
            r#type: "response",
            cmd: "get_state",
            ok: true,
            mode,
            nodes: snap.nodes,
            links: snap.links,
            devices: snap.devices,
        };
        return HandleResult::ResponseJson(
            serde_json::to_string(&resp).unwrap_or_default(),
        );
    }

    match reply_rx.recv() {
        Ok(snap) => {
            let resp = StateResponse {
                r#type: "response",
                cmd: "get_state",
                ok: true,
                mode: snap.mode,
                nodes: snap.nodes,
                links: snap.links,
                devices: snap.devices,
            };
            HandleResult::ResponseJson(
                serde_json::to_string(&resp).unwrap_or_default(),
            )
        }
        Err(_) => {
            let mode = stored_mode
                .lock()
                .map(|m| m.clone())
                .unwrap_or_else(|_| "monitoring".to_string());
            let snap = StateSnapshot::empty();
            let resp = StateResponse {
                r#type: "response",
                cmd: "get_state",
                ok: true,
                mode,
                nodes: snap.nodes,
                links: snap.links,
                devices: snap.devices,
            };
            HandleResult::ResponseJson(
                serde_json::to_string(&resp).unwrap_or_default(),
            )
        }
    }
}

fn handle_get_devices(cmd_tx: &mpsc::Sender<RpcCommand>) -> HandleResult {
    let (reply_tx, reply_rx) = mpsc::channel();
    if cmd_tx
        .send(RpcCommand::GetDevices { reply: reply_tx })
        .is_err()
    {
        let resp = DevicesResponse {
            r#type: "response",
            cmd: "get_devices",
            ok: true,
            devices: DeviceStatus::defaults(),
        };
        return HandleResult::ResponseJson(
            serde_json::to_string(&resp).unwrap_or_default(),
        );
    }

    match reply_rx.recv() {
        Ok(devices) => {
            let resp = DevicesResponse {
                r#type: "response",
                cmd: "get_devices",
                ok: true,
                devices,
            };
            HandleResult::ResponseJson(
                serde_json::to_string(&resp).unwrap_or_default(),
            )
        }
        Err(_) => {
            let resp = DevicesResponse {
                r#type: "response",
                cmd: "get_devices",
                ok: true,
                devices: DeviceStatus::defaults(),
            };
            HandleResult::ResponseJson(
                serde_json::to_string(&resp).unwrap_or_default(),
            )
        }
    }
}

fn handle_get_links(
    cmd_tx: &mpsc::Sender<RpcCommand>,
    stored_mode: &Mutex<String>,
) -> HandleResult {
    let (reply_tx, reply_rx) = mpsc::channel();
    if cmd_tx
        .send(RpcCommand::GetLinks { reply: reply_tx })
        .is_err()
    {
        let mode = stored_mode
            .lock()
            .map(|m| m.clone())
            .unwrap_or_else(|_| "monitoring".to_string());
        let snap = LinkSnapshot::empty(&mode);
        let resp = LinksResponse {
            r#type: "response",
            cmd: "get_links",
            ok: true,
            mode: snap.mode,
            desired: snap.desired,
            actual: snap.actual,
            missing: snap.missing,
            links: snap.links,
        };
        return HandleResult::ResponseJson(
            serde_json::to_string(&resp).unwrap_or_default(),
        );
    }

    match reply_rx.recv() {
        Ok(snap) => {
            let resp = LinksResponse {
                r#type: "response",
                cmd: "get_links",
                ok: true,
                mode: snap.mode,
                desired: snap.desired,
                actual: snap.actual,
                missing: snap.missing,
                links: snap.links,
            };
            HandleResult::ResponseJson(
                serde_json::to_string(&resp).unwrap_or_default(),
            )
        }
        Err(_) => {
            let mode = stored_mode
                .lock()
                .map(|m| m.clone())
                .unwrap_or_else(|_| "monitoring".to_string());
            let snap = LinkSnapshot::empty(&mode);
            let resp = LinksResponse {
                r#type: "response",
                cmd: "get_links",
                ok: true,
                mode: snap.mode,
                desired: snap.desired,
                actual: snap.actual,
                missing: snap.missing,
                links: snap.links,
            };
            HandleResult::ResponseJson(
                serde_json::to_string(&resp).unwrap_or_default(),
            )
        }
    }
}

// ---------------------------------------------------------------------------
// Response formatting
// ---------------------------------------------------------------------------

/// Format an ack response as a JSON line.
pub fn format_ack(cmd: &str) -> String {
    serde_json::to_string(&AckResponse {
        r#type: "ack",
        cmd: cmd.to_string(),
        ok: true,
        error: None,
    })
    .unwrap()
}

/// Format an error response as a JSON line.
pub fn format_error(cmd: &str, error: &str) -> String {
    serde_json::to_string(&AckResponse {
        r#type: "ack",
        cmd: cmd.to_string(),
        ok: false,
        error: Some(error.to_string()),
    })
    .unwrap()
}

/// Format a line-too-long error (SEC-D037-03).
pub fn format_line_too_long() -> String {
    format_error("", "line too long (max 4096 bytes)")
}

/// Format a GraphEvent as a JSON line for broadcast.
pub fn format_event(event: &GraphEvent) -> String {
    // Wrap the serde(tag) output with the "type": "event" envelope.
    let mut map = match serde_json::to_value(event) {
        Ok(Value::Object(m)) => m,
        _ => return String::new(),
    };
    map.insert("type".to_string(), Value::String("event".to_string()));
    serde_json::to_string(&map).unwrap_or_default()
}

// ---------------------------------------------------------------------------
// Line parsing
// ---------------------------------------------------------------------------

/// Parse a JSON line into an RpcRequest.
///
/// Returns `Err` with a formatted error response if:
/// - The line exceeds MAX_LINE_LENGTH (SEC-D037-03)
/// - The JSON is malformed
/// - The `cmd` field is missing
pub fn parse_line(line: &str) -> Result<RpcRequest, String> {
    if line.len() > MAX_LINE_LENGTH {
        return Err(format_line_too_long());
    }

    let req: RpcRequest = serde_json::from_str(line).map_err(|e| {
        format_error("", &format!("invalid JSON: {}", e))
    })?;

    if req.cmd.is_empty() {
        return Err(format_error("", "missing \"cmd\" field"));
    }

    Ok(req)
}

// ---------------------------------------------------------------------------
// Stub PW-thread command handler
// ---------------------------------------------------------------------------

/// Placeholder handler for the PW main loop thread (test-only).
///
/// Processes `RpcCommand` messages from the RPC thread, returning default
/// stub responses. Production code uses `dispatch_rpc_command` in main.rs.
#[cfg(test)]
pub fn handle_pw_command(cmd: RpcCommand, current_mode: &Mutex<String>) {
    match cmd {
        RpcCommand::SetMode { mode, reply } => {
            if let Ok(mut m) = current_mode.lock() {
                *m = mode.to_string();
            }
            let _ = reply.send(RpcResult::Ok);
        }
        RpcCommand::GetState { reply } => {
            let mode = current_mode
                .lock()
                .map(|m| m.clone())
                .unwrap_or_else(|_| "monitoring".to_string());
            let mut snap = StateSnapshot::empty();
            snap.mode = mode;
            let _ = reply.send(snap);
        }
        RpcCommand::GetDevices { reply } => {
            let _ = reply.send(DeviceStatus::defaults());
        }
        RpcCommand::GetLinks { reply } => {
            let mode = current_mode
                .lock()
                .map(|m| m.clone())
                .unwrap_or_else(|_| "monitoring".to_string());
            let _ = reply.send(LinkSnapshot::empty(&mode));
        }
    }
}

// ---------------------------------------------------------------------------
// TCP server
// ---------------------------------------------------------------------------

/// Shared list of connected client streams for event broadcasting.
type ClientList = Arc<Mutex<Vec<TcpStream>>>;

/// Run the RPC server on its own thread.
///
/// Accepts TCP connections on `addr`, reads newline-delimited JSON,
/// dispatches commands, and writes responses. Push events from
/// `event_rx` are broadcast to all connected clients.
///
/// Channels are created externally (in `main()`) so that:
/// - `cmd_tx` stays with the RPC thread (to send commands to PW)
/// - `cmd_rx` goes to the PW main loop thread (to receive commands)
/// - `event_tx` goes to the PW main loop thread (to push events)
/// - `event_rx` stays with the RPC thread (to broadcast events)
///
/// Returns the thread handle.
pub fn start_rpc_thread(
    addr: &str,
    initial_mode: &str,
    cmd_tx: mpsc::Sender<RpcCommand>,
    event_rx: mpsc::Receiver<GraphEvent>,
    shutdown: Arc<AtomicBool>,
) -> thread::JoinHandle<()> {
    let addr = addr.to_string();
    let initial_mode = initial_mode.to_string();

    thread::spawn(move || {
        run_rpc_server(&addr, &initial_mode, cmd_tx, event_rx, shutdown);
    })
}

fn run_rpc_server(
    addr: &str,
    initial_mode: &str,
    cmd_tx: mpsc::Sender<RpcCommand>,
    event_rx: mpsc::Receiver<GraphEvent>,
    shutdown: Arc<AtomicBool>,
) {
    let listener = match TcpListener::bind(addr) {
        Ok(l) => {
            info!("RPC server listening on {}", addr);
            l
        }
        Err(e) => {
            error!("RPC server failed to bind {}: {}", addr, e);
            return;
        }
    };

    // Non-blocking accept so we can check shutdown.
    listener
        .set_nonblocking(true)
        .expect("Failed to set non-blocking on TCP listener");

    let clients: ClientList = Arc::new(Mutex::new(Vec::new()));
    let stored_mode = Arc::new(Mutex::new(initial_mode.to_string()));

    // Event broadcast thread.
    let clients_for_events = clients.clone();
    thread::spawn(move || {
        while let Ok(event) = event_rx.recv() {
            let json = format_event(&event);
            if json.is_empty() {
                continue;
            }
            let line = format!("{}\n", json);
            let mut clients = clients_for_events.lock().unwrap();
            clients.retain(|stream| {
                let mut s = match stream.try_clone() {
                    Ok(s) => s,
                    Err(_) => return false,
                };
                s.write_all(line.as_bytes()).is_ok()
            });
        }
    });

    while !shutdown.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, peer)) => {
                info!("RPC client connected: {}", peer);
                // Store clone for event broadcasting.
                if let Ok(clone) = stream.try_clone() {
                    clients.lock().unwrap().push(clone);
                }
                let cmd_tx = cmd_tx.clone();
                let stored_mode = stored_mode.clone();
                let shutdown = shutdown.clone();
                thread::spawn(move || {
                    handle_client(stream, cmd_tx, stored_mode, shutdown);
                });
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                // No connection pending, sleep briefly and retry.
                thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(e) => {
                warn!("RPC accept error: {}", e);
            }
        }
    }

    info!("RPC server shutting down");
}

fn handle_client(
    stream: TcpStream,
    cmd_tx: mpsc::Sender<RpcCommand>,
    stored_mode: Arc<Mutex<String>>,
    shutdown: Arc<AtomicBool>,
) {
    let peer = stream
        .peer_addr()
        .map(|a| a.to_string())
        .unwrap_or_else(|_| "unknown".to_string());

    let mut writer = match stream.try_clone() {
        Ok(s) => s,
        Err(e) => {
            error!("Failed to clone stream for {}: {}", peer, e);
            return;
        }
    };

    let mut reader = BufReader::new(stream);

    // SEC-GM-03: Cap line reads at the I/O layer to prevent unbounded memory
    // allocation. The previous code used `.lines()` which reads the entire
    // line into memory before parse_line's length check runs. Now we read
    // into a fixed-capacity buffer and reject oversized lines before parsing.
    //
    // Buffer capacity: MAX_LINE_LENGTH + 1 for the newline + 1 to detect
    // overflow (if we read MAX_LINE_LENGTH+2 bytes without a newline, the
    // line is too long).
    let cap = MAX_LINE_LENGTH + 2;
    let mut buf = Vec::with_capacity(cap);
    loop {
        if shutdown.load(Ordering::Relaxed) {
            break;
        }

        buf.clear();
        // Read until newline or cap, whichever comes first.
        match reader.by_ref().take(cap as u64).read_until(b'\n', &mut buf) {
            Ok(0) => break, // EOF
            Ok(_) => {}
            Err(e) => {
                debug!("RPC read error from {}: {}", peer, e);
                break;
            }
        }

        // Strip trailing newline/CR.
        if buf.last() == Some(&b'\n') {
            buf.pop();
        }
        if buf.last() == Some(&b'\r') {
            buf.pop();
        }

        if buf.is_empty() {
            continue;
        }

        // Reject oversized lines at the I/O layer (SEC-GM-03).
        let response = if buf.len() > MAX_LINE_LENGTH {
            // Drain any remaining bytes on this line (past our cap) so the
            // next read starts at a fresh line boundary.
            let mut drain = Vec::new();
            let _ = reader.read_until(b'\n', &mut drain);
            warn!("SEC-GM-03: rejected oversized line ({} bytes) from {}", buf.len(), peer);
            format_line_too_long()
        } else {
            let line = match std::str::from_utf8(&buf) {
                Ok(s) => s,
                Err(_) => {
                    debug!("RPC invalid UTF-8 from {}", peer);
                    continue;
                }
            };
            match parse_line(line) {
                Ok(req) => match handle_request(&req, &cmd_tx, &stored_mode) {
                    HandleResult::Ack(cmd) => format_ack(&cmd),
                    HandleResult::Error(cmd, msg) => format_error(&cmd, &msg),
                    HandleResult::ResponseJson(json) => json,
                },
                Err(err_json) => err_json,
            }
        };

        let line_out = format!("{}\n", response);
        if writer.write_all(line_out.as_bytes()).is_err() {
            debug!("RPC write error to {}, disconnecting", peer);
            break;
        }
    }

    info!("RPC client disconnected: {}", peer);
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------------
    // JSON parsing: valid commands
    // -----------------------------------------------------------------------

    #[test]
    fn parse_ping_command() {
        let json = r#"{"cmd":"ping"}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "ping");
    }

    #[test]
    fn parse_get_state_command() {
        let json = r#"{"cmd":"get_state"}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "get_state");
    }

    #[test]
    fn parse_set_mode_command() {
        let json = r#"{"cmd":"set_mode","mode":"dj"}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "set_mode");
        assert_eq!(req.mode.as_deref(), Some("dj"));
    }

    #[test]
    fn parse_get_devices_command() {
        let json = r#"{"cmd":"get_devices"}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "get_devices");
    }

    #[test]
    fn parse_get_links_command() {
        let json = r#"{"cmd":"get_links"}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "get_links");
    }

    // -----------------------------------------------------------------------
    // JSON parsing: invalid/malformed
    // -----------------------------------------------------------------------

    #[test]
    fn parse_invalid_json() {
        let result = parse_line("not json at all");
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains("invalid JSON"), "Error: {}", err);
    }

    #[test]
    fn parse_missing_cmd_field() {
        let result = parse_line(r#"{"mode":"dj"}"#);
        assert!(result.is_err());
    }

    #[test]
    fn parse_empty_object() {
        let result = parse_line(r#"{}"#);
        assert!(result.is_err());
    }

    // -----------------------------------------------------------------------
    // Line length (SEC-D037-03)
    // -----------------------------------------------------------------------

    #[test]
    fn line_within_limit_accepted() {
        let json = r#"{"cmd":"ping"}"#;
        assert!(json.len() <= MAX_LINE_LENGTH);
        assert!(parse_line(json).is_ok());
    }

    #[test]
    fn line_exceeding_limit_rejected() {
        let padding = "x".repeat(MAX_LINE_LENGTH + 1);
        let result = parse_line(&padding);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains("line too long"), "Error: {}", err);
    }

    #[test]
    fn line_at_exact_limit_accepted() {
        // A valid JSON padded to exactly MAX_LINE_LENGTH bytes.
        let base = r#"{"cmd":"ping","_":""#;
        let suffix = r#""}"#;
        let pad_len = MAX_LINE_LENGTH - base.len() - suffix.len();
        let json = format!("{}{}{}", base, "a".repeat(pad_len), suffix);
        assert_eq!(json.len(), MAX_LINE_LENGTH);
        // Should pass length check (valid JSON too).
        assert!(parse_line(&json).is_ok());
    }

    // -----------------------------------------------------------------------
    // set_mode validation
    // -----------------------------------------------------------------------

    #[test]
    fn set_mode_valid_modes() {
        for mode_str in &["monitoring", "dj", "live", "measurement"] {
            assert!(
                mode_str.parse::<Mode>().is_ok(),
                "Expected valid mode: {}",
                mode_str
            );
        }
    }

    #[test]
    fn set_mode_invalid_mode() {
        let err = "foo".parse::<Mode>().unwrap_err();
        assert!(err.contains("unknown mode"), "Error: {}", err);
        assert!(err.contains("foo"), "Error: {}", err);
    }

    #[test]
    fn set_mode_missing_mode_field() {
        let (cmd_tx, cmd_rx) = mpsc::channel();
        let stored_mode = Mutex::new("monitoring".to_string());

        // Spawn stub handler so the channel doesn't hang.
        thread::spawn(move || {
            while let Ok(cmd) = cmd_rx.recv() {
                handle_pw_command(cmd, &Mutex::new("monitoring".to_string()));
            }
        });

        let req = parse_line(r#"{"cmd":"set_mode"}"#).unwrap();
        let result = handle_request(&req, &cmd_tx, &stored_mode);
        match result {
            HandleResult::Error(cmd, msg) => {
                assert_eq!(cmd, "set_mode");
                assert!(msg.contains("missing"), "Error: {}", msg);
            }
            _ => panic!("Expected error for missing mode field"),
        }
    }

    #[test]
    fn set_mode_invalid_mode_value() {
        let (cmd_tx, cmd_rx) = mpsc::channel();
        let stored_mode = Mutex::new("monitoring".to_string());

        thread::spawn(move || {
            while let Ok(cmd) = cmd_rx.recv() {
                handle_pw_command(cmd, &Mutex::new("monitoring".to_string()));
            }
        });

        let req = parse_line(r#"{"cmd":"set_mode","mode":"foo"}"#).unwrap();
        let result = handle_request(&req, &cmd_tx, &stored_mode);
        match result {
            HandleResult::Error(cmd, msg) => {
                assert_eq!(cmd, "set_mode");
                assert!(msg.contains("unknown mode"), "Error: {}", msg);
            }
            _ => panic!("Expected error for invalid mode"),
        }
    }

    #[test]
    fn set_mode_valid_updates_stored() {
        let (cmd_tx, cmd_rx) = mpsc::channel();
        let stored_mode = Arc::new(Mutex::new("monitoring".to_string()));

        let mode_for_handler = Arc::new(Mutex::new("monitoring".to_string()));
        thread::spawn({
            let mode = mode_for_handler.clone();
            move || {
                while let Ok(cmd) = cmd_rx.recv() {
                    handle_pw_command(cmd, &mode);
                }
            }
        });

        let req = parse_line(r#"{"cmd":"set_mode","mode":"dj"}"#).unwrap();
        let result = handle_request(&req, &cmd_tx, &stored_mode);
        assert!(matches!(result, HandleResult::Ack(ref c) if c == "set_mode"));
        assert_eq!(*stored_mode.lock().unwrap(), "dj");
    }

    // -----------------------------------------------------------------------
    // ping
    // -----------------------------------------------------------------------

    #[test]
    fn ping_always_returns_ok() {
        let (cmd_tx, _cmd_rx) = mpsc::channel();
        let stored_mode = Mutex::new("monitoring".to_string());

        let req = parse_line(r#"{"cmd":"ping"}"#).unwrap();
        let result = handle_request(&req, &cmd_tx, &stored_mode);
        match result {
            HandleResult::Ack(cmd) => assert_eq!(cmd, "ping"),
            _ => panic!("Expected ack for ping"),
        }
    }

    // -----------------------------------------------------------------------
    // Unknown command
    // -----------------------------------------------------------------------

    #[test]
    fn unknown_command_rejected() {
        let (cmd_tx, _cmd_rx) = mpsc::channel();
        let stored_mode = Mutex::new("monitoring".to_string());

        let req = parse_line(r#"{"cmd":"reboot"}"#).unwrap();
        let result = handle_request(&req, &cmd_tx, &stored_mode);
        match result {
            HandleResult::Error(_, msg) => {
                assert!(msg.contains("unknown command"), "Error: {}", msg);
                assert!(msg.contains("reboot"), "Error: {}", msg);
            }
            _ => panic!("Expected error for unknown command"),
        }
    }

    // -----------------------------------------------------------------------
    // Ack/error response format
    // -----------------------------------------------------------------------

    #[test]
    fn ack_response_format() {
        let json = format_ack("set_mode");
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "ack");
        assert_eq!(v["cmd"], "set_mode");
        assert_eq!(v["ok"], true);
        assert!(v.get("error").is_none() || v["error"].is_null());
    }

    #[test]
    fn error_response_format() {
        let json = format_error("set_mode", "unknown mode: \"foo\"");
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "ack");
        assert_eq!(v["cmd"], "set_mode");
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"], "unknown mode: \"foo\"");
    }

    // -----------------------------------------------------------------------
    // RpcCommand enum (snapshot types)
    // -----------------------------------------------------------------------

    #[test]
    fn state_snapshot_serializes() {
        let snap = StateSnapshot::empty();
        let json = serde_json::to_string(&snap).unwrap();
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["mode"], "monitoring");
        assert!(v["nodes"].is_array());
        assert!(v["links"].is_array());
        assert!(v["devices"].is_object());
    }

    #[test]
    fn device_status_defaults_has_four_entries() {
        let defaults = DeviceStatus::defaults();
        assert_eq!(defaults.len(), 4);
        let names: Vec<_> = defaults.iter().map(|d| d.name.as_str()).collect();
        assert!(names.contains(&"usbstreamer"));
        assert!(names.contains(&"umik1"));
        assert!(names.contains(&"convolver"));
        assert!(names.contains(&"convolver-out"));
    }

    #[test]
    fn link_snapshot_empty_serializes() {
        let snap = LinkSnapshot::empty("dj");
        let json = serde_json::to_string(&snap).unwrap();
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["mode"], "dj");
        assert_eq!(v["desired"], 0);
        assert_eq!(v["actual"], 0);
        assert_eq!(v["missing"], 0);
        assert!(v["links"].is_array());
    }

    // -----------------------------------------------------------------------
    // Event serialization
    // -----------------------------------------------------------------------

    #[test]
    fn event_node_added_serializes() {
        let event = GraphEvent::NodeAdded {
            id: 42,
            name: "pi4audio-convolver".to_string(),
            media_class: "Audio/Sink".to_string(),
        };
        let json = format_event(&event);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "node_added");
        assert_eq!(v["id"], 42);
        assert_eq!(v["name"], "pi4audio-convolver");
        assert_eq!(v["media_class"], "Audio/Sink");
    }

    #[test]
    fn event_node_removed_serializes() {
        let event = GraphEvent::NodeRemoved {
            id: 42,
            name: "pi4audio-convolver".to_string(),
        };
        let json = format_event(&event);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "node_removed");
        assert_eq!(v["id"], 42);
        assert_eq!(v["name"], "pi4audio-convolver");
    }

    #[test]
    fn event_mode_changed_serializes() {
        let event = GraphEvent::ModeChanged {
            from: "monitoring".to_string(),
            to: "dj".to_string(),
        };
        let json = format_event(&event);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "mode_changed");
        assert_eq!(v["from"], "monitoring");
        assert_eq!(v["to"], "dj");
    }

    #[test]
    fn event_link_created_serializes() {
        let event = GraphEvent::LinkCreated {
            output_node: "pi4audio-convolver-out".to_string(),
            output_port: "output_AUX0".to_string(),
            input_node: "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0".to_string(),
            input_port: "playback_AUX0".to_string(),
        };
        let json = format_event(&event);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "link_created");
        assert_eq!(v["output_node"], "pi4audio-convolver-out");
        assert_eq!(v["input_port"], "playback_AUX0");
    }

    #[test]
    fn event_link_failed_serializes() {
        let event = GraphEvent::LinkFailed {
            output_node: "signal-gen".to_string(),
            output_port: "output_AUX0".to_string(),
            input_node: "pi4audio-convolver".to_string(),
            input_port: "input_0".to_string(),
            reason: "port not found".to_string(),
        };
        let json = format_event(&event);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "link_failed");
        assert_eq!(v["reason"], "port not found");
    }

    #[test]
    fn event_link_destroyed_serializes() {
        let event = GraphEvent::LinkDestroyed {
            output_node: "Mixxx".to_string(),
            output_port: "out_0".to_string(),
            input_node: "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0".to_string(),
            input_port: "playback_AUX0".to_string(),
        };
        let json = format_event(&event);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "link_destroyed");
        assert_eq!(v["output_node"], "Mixxx");
        assert_eq!(v["input_port"], "playback_AUX0");
    }

    #[test]
    fn event_device_connected_serializes() {
        let event = GraphEvent::DeviceConnected {
            name: "usbstreamer".to_string(),
        };
        let json = format_event(&event);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "device_connected");
        assert_eq!(v["name"], "usbstreamer");
    }

    #[test]
    fn event_device_disconnected_serializes() {
        let event = GraphEvent::DeviceDisconnected {
            name: "umik1".to_string(),
        };
        let json = format_event(&event);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "event");
        assert_eq!(v["event"], "device_disconnected");
        assert_eq!(v["name"], "umik1");
    }

    // -----------------------------------------------------------------------
    // get_state response format
    // -----------------------------------------------------------------------

    #[test]
    fn get_state_stub_response_format() {
        let (cmd_tx, cmd_rx) = mpsc::channel();
        let stored_mode = Mutex::new("monitoring".to_string());

        let mode = Arc::new(Mutex::new("monitoring".to_string()));
        thread::spawn(move || {
            while let Ok(cmd) = cmd_rx.recv() {
                handle_pw_command(cmd, &mode);
            }
        });

        let req = parse_line(r#"{"cmd":"get_state"}"#).unwrap();
        let result = handle_request(&req, &cmd_tx, &stored_mode);
        match result {
            HandleResult::ResponseJson(json) => {
                let v: Value = serde_json::from_str(&json).unwrap();
                assert_eq!(v["type"], "response");
                assert_eq!(v["cmd"], "get_state");
                assert_eq!(v["ok"], true);
                assert_eq!(v["mode"], "monitoring");
                assert!(v["nodes"].is_array());
                assert!(v["links"].is_array());
                assert!(v["devices"].is_object());
            }
            _ => panic!("Expected ResponseJson for get_state"),
        }
    }

    // -----------------------------------------------------------------------
    // get_devices response format
    // -----------------------------------------------------------------------

    #[test]
    fn get_devices_stub_response_format() {
        let (cmd_tx, cmd_rx) = mpsc::channel();
        let stored_mode = Mutex::new("monitoring".to_string());

        let mode = Arc::new(Mutex::new("monitoring".to_string()));
        thread::spawn(move || {
            while let Ok(cmd) = cmd_rx.recv() {
                handle_pw_command(cmd, &mode);
            }
        });

        let req = parse_line(r#"{"cmd":"get_devices"}"#).unwrap();
        let result = handle_request(&req, &cmd_tx, &stored_mode);
        match result {
            HandleResult::ResponseJson(json) => {
                let v: Value = serde_json::from_str(&json).unwrap();
                assert_eq!(v["type"], "response");
                assert_eq!(v["cmd"], "get_devices");
                assert_eq!(v["ok"], true);
                assert!(v["devices"].is_array());
                assert_eq!(v["devices"].as_array().unwrap().len(), 4);
            }
            _ => panic!("Expected ResponseJson for get_devices"),
        }
    }

    // -----------------------------------------------------------------------
    // get_links response format
    // -----------------------------------------------------------------------

    #[test]
    fn get_links_stub_response_format() {
        let (cmd_tx, cmd_rx) = mpsc::channel();
        let stored_mode = Mutex::new("dj".to_string());

        let mode = Arc::new(Mutex::new("dj".to_string()));
        thread::spawn(move || {
            while let Ok(cmd) = cmd_rx.recv() {
                handle_pw_command(cmd, &mode);
            }
        });

        let req = parse_line(r#"{"cmd":"get_links"}"#).unwrap();
        let result = handle_request(&req, &cmd_tx, &stored_mode);
        match result {
            HandleResult::ResponseJson(json) => {
                let v: Value = serde_json::from_str(&json).unwrap();
                assert_eq!(v["type"], "response");
                assert_eq!(v["cmd"], "get_links");
                assert_eq!(v["ok"], true);
                assert_eq!(v["mode"], "dj");
                assert_eq!(v["desired"], 0);
                assert_eq!(v["actual"], 0);
                assert_eq!(v["missing"], 0);
                assert!(v["links"].is_array());
            }
            _ => panic!("Expected ResponseJson for get_links"),
        }
    }

    // -----------------------------------------------------------------------
    // TCP connection handling (integration-style)
    // -----------------------------------------------------------------------

    /// Start an RPC server with a stub PW handler thread for testing.
    /// Creates channels, spawns the stub handler, and returns everything
    /// needed to interact with the server.
    fn start_test_rpc_server(
        addr: &str,
        initial_mode: &str,
        shutdown: Arc<AtomicBool>,
    ) -> thread::JoinHandle<()> {
        let (cmd_tx, cmd_rx) = mpsc::channel::<RpcCommand>();
        let (_event_tx, event_rx) = mpsc::channel::<GraphEvent>();

        // Stub PW handler thread (same as GM-9 scaffolding).
        thread::spawn({
            let mode = Arc::new(Mutex::new(initial_mode.to_string()));
            move || {
                while let Ok(cmd) = cmd_rx.recv() {
                    handle_pw_command(cmd, &mode);
                }
            }
        });

        start_rpc_thread(addr, initial_mode, cmd_tx, event_rx, shutdown)
    }

    #[test]
    fn tcp_server_accepts_and_responds() {
        let shutdown = Arc::new(AtomicBool::new(false));
        let _handle =
            start_test_rpc_server("127.0.0.1:0", "monitoring", shutdown.clone());

        // Give the server a moment to bind.
        // We can't know the port from start_rpc_thread with port 0,
        // so we test with a known port.
        shutdown.store(true, Ordering::Relaxed);
        // Let server loop exit.
        thread::sleep(std::time::Duration::from_millis(100));
    }

    #[test]
    fn tcp_ping_roundtrip() {
        use std::io::{BufRead, BufReader, Write};

        // Use a random port to avoid conflicts.
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        drop(listener);

        let shutdown = Arc::new(AtomicBool::new(false));
        let addr_str = addr.to_string();
        let _handle =
            start_test_rpc_server(&addr_str, "monitoring", shutdown.clone());

        // Give the server a moment to bind.
        thread::sleep(std::time::Duration::from_millis(100));

        // Connect and send ping.
        let mut stream = TcpStream::connect(&addr_str).unwrap();
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(2)))
            .unwrap();
        stream.write_all(b"{\"cmd\":\"ping\"}\n").unwrap();

        let mut reader = BufReader::new(&stream);
        let mut response = String::new();
        reader.read_line(&mut response).unwrap();

        let v: Value = serde_json::from_str(response.trim()).unwrap();
        assert_eq!(v["type"], "ack");
        assert_eq!(v["cmd"], "ping");
        assert_eq!(v["ok"], true);

        shutdown.store(true, Ordering::Relaxed);
        thread::sleep(std::time::Duration::from_millis(100));
    }

    #[test]
    fn tcp_line_too_long_rejected() {
        use std::io::{BufRead, BufReader, Write};

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        drop(listener);

        let shutdown = Arc::new(AtomicBool::new(false));
        let addr_str = addr.to_string();
        let _handle =
            start_test_rpc_server(&addr_str, "monitoring", shutdown.clone());

        thread::sleep(std::time::Duration::from_millis(100));

        let mut stream = TcpStream::connect(&addr_str).unwrap();
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(2)))
            .unwrap();

        // Send a line that exceeds 4096 bytes.
        let long_line = format!("{{\"cmd\":\"ping\",\"_\":\"{}\"}}\n", "x".repeat(MAX_LINE_LENGTH));
        stream.write_all(long_line.as_bytes()).unwrap();

        let mut reader = BufReader::new(&stream);
        let mut response = String::new();
        reader.read_line(&mut response).unwrap();

        let v: Value = serde_json::from_str(response.trim()).unwrap();
        assert_eq!(v["ok"], false);
        assert!(v["error"].as_str().unwrap().contains("line too long"));

        shutdown.store(true, Ordering::Relaxed);
        thread::sleep(std::time::Duration::from_millis(100));
    }
}
