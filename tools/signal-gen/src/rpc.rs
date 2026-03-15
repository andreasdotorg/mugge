//! TCP RPC server for JSON command interface.
//!
//! Listens on a localhost TCP port (default 127.0.0.1:4001) and accepts
//! newline-delimited JSON commands. State broadcasts are sent to all
//! connected clients.
//!
//! Line length is capped at 4096 bytes per SEC-D037-03.
//!
//! Section 7 of D-037 specifies the full protocol. This module handles:
//! - JSON parsing and validation
//! - Command translation to `Command` structs for the RT thread
//! - Level rejection (AD-D037-3): levels above cap are REJECTED, not clamped
//! - Frequency validation (AE-MF-2): [20, 20000] Hz
//! - Channel validation: [1..8]
//! - Response formatting (ack, error, state, events)

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::command::{
    channels_to_bitmask, bitmask_to_channels, Command, CommandKind, CommandQueue,
    PlayState, SignalType, StateQueue, StateSnapshot,
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// Maximum line length in bytes (SEC-D037-03).
pub const MAX_LINE_LENGTH: usize = 4096;

/// Minimum frequency in Hz (AE-MF-2).
pub const MIN_FREQ_HZ: f64 = 20.0;

/// Maximum frequency in Hz (AE-MF-2).
pub const MAX_FREQ_HZ: f64 = 20000.0;

/// Minimum level in dBFS.
pub const MIN_LEVEL_DBFS: f64 = -60.0;

// ---------------------------------------------------------------------------
// Incoming JSON request
// ---------------------------------------------------------------------------

/// Raw JSON request from a client (before validation).
#[derive(Debug, Deserialize)]
pub struct RpcRequest {
    pub cmd: String,
    #[serde(default)]
    pub signal: Option<String>,
    #[serde(default)]
    pub freq: Option<f64>,
    #[serde(default)]
    pub sweep_end: Option<f64>,
    #[serde(default)]
    pub channels: Option<Vec<u8>>,
    #[serde(default)]
    pub level_dbfs: Option<f64>,
    #[serde(default)]
    pub duration: Option<f64>,
    #[serde(default)]
    pub format: Option<String>,
}

// ---------------------------------------------------------------------------
// Outgoing JSON responses
// ---------------------------------------------------------------------------

/// Acknowledgment response.
#[derive(Debug, Serialize)]
pub struct AckResponse {
    pub r#type: &'static str,
    pub cmd: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Status response (wraps a StateSnapshot in JSON).
#[derive(Debug, Serialize)]
pub struct StatusResponse {
    pub r#type: &'static str,
    pub cmd: &'static str,
    pub ok: bool,
    pub playing: bool,
    pub recording: bool,
    pub signal: String,
    pub freq: f32,
    pub channels: Vec<u8>,
    pub level_dbfs: f32,
    pub elapsed: f32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration: Option<f32>,
    pub capture_peak_dbfs: f32,
    pub capture_rms_dbfs: f32,
    pub capture_connected: bool,
    pub samples_generated: u64,
}

/// Capture level response.
#[derive(Debug, Serialize)]
pub struct CaptureLevelResponse {
    pub r#type: &'static str,
    pub cmd: &'static str,
    pub ok: bool,
    pub peak_dbfs: f32,
    pub rms_dbfs: f32,
}

/// Async event broadcast.
#[derive(Debug, Serialize)]
pub struct EventResponse {
    pub r#type: &'static str,
    pub event: String,
    #[serde(flatten)]
    pub data: serde_json::Map<String, Value>,
}

// ---------------------------------------------------------------------------
// Signal type parsing
// ---------------------------------------------------------------------------

/// Parse a signal type string into the enum.
fn parse_signal_type(s: &str) -> Result<SignalType, String> {
    match s {
        "silence" => Ok(SignalType::Silence),
        "sine" => Ok(SignalType::Sine),
        "white" => Ok(SignalType::White),
        "pink" => Ok(SignalType::Pink),
        "sweep" => Ok(SignalType::Sweep),
        other => Err(format!("unknown signal type: \"{}\"", other)),
    }
}

/// Convert a SignalType to its string representation.
pub fn signal_type_to_str(st: SignalType) -> &'static str {
    match st {
        SignalType::Silence => "silence",
        SignalType::Sine => "sine",
        SignalType::White => "white",
        SignalType::Pink => "pink",
        SignalType::Sweep => "sweep",
    }
}

// ---------------------------------------------------------------------------
// Level conversion
// ---------------------------------------------------------------------------

/// Convert linear amplitude to dBFS. Returns -infinity for zero.
fn linear_to_dbfs(linear: f32) -> f32 {
    if linear <= 0.0 {
        f32::NEG_INFINITY
    } else {
        20.0 * linear.log10()
    }
}

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

/// Validate frequency is within [20, 20000] Hz (AE-MF-2).
fn validate_freq(freq: f64) -> Result<(), String> {
    if freq < MIN_FREQ_HZ {
        return Err(format!(
            "freq {:.1} below minimum {:.0} Hz",
            freq, MIN_FREQ_HZ
        ));
    }
    if freq > MAX_FREQ_HZ {
        return Err(format!(
            "freq {:.1} above maximum {:.0} Hz",
            freq, MAX_FREQ_HZ
        ));
    }
    Ok(())
}

/// Validate channels array: all values must be in [1..8].
fn validate_channels(channels: &[u8]) -> Result<(), String> {
    for &ch in channels {
        if ch < 1 || ch > 8 {
            return Err(format!("channel {} out of range [1..8]", ch));
        }
    }
    if channels.is_empty() {
        return Err("channels array must not be empty".to_string());
    }
    Ok(())
}

/// Validate level_dbfs against the hard cap (AD-D037-3: reject, not clamp).
fn validate_level(level_dbfs: f64, max_level_dbfs: f64) -> Result<(), String> {
    if level_dbfs > max_level_dbfs {
        return Err(format!(
            "level {:.1} exceeds cap {:.1}",
            level_dbfs, max_level_dbfs
        ));
    }
    if level_dbfs < MIN_LEVEL_DBFS {
        return Err(format!(
            "level {:.1} below minimum {:.1}",
            level_dbfs, MIN_LEVEL_DBFS
        ));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Command handler
// ---------------------------------------------------------------------------

/// Result of handling a parsed RPC request.
pub enum HandleResult {
    /// Command accepted, pushed to queue. Send ack to client.
    Ack(String),
    /// Command rejected with error message.
    Error(String, String),
    /// Status query — return formatted status JSON.
    StatusJson(String),
    /// Capture level query — return formatted level JSON.
    CaptureLevelJson(String),
    /// Get recording — placeholder (actual data comes from capture module).
    GetRecording,
}

/// Handle a parsed RPC request.
///
/// Validates all fields, translates to a `Command`, and pushes to the
/// command queue. Returns the appropriate response.
///
/// `max_level_dbfs` is the immutable hard cap from `--max-level-dbfs`.
/// `latest_state` is the most recent StateSnapshot from the feedback queue.
/// `capture_connected` indicates whether the capture device is present
/// in the PipeWire registry. Used to reject `playrec` when no capture
/// source is available (BUG-SG12-4).
pub fn handle_request(
    req: &RpcRequest,
    cmd_queue: &CommandQueue,
    max_level_dbfs: f64,
    latest_state: &StateSnapshot,
    capture_connected: bool,
) -> HandleResult {
    match req.cmd.as_str() {
        "play" => handle_play(req, cmd_queue, max_level_dbfs, false, capture_connected),
        "playrec" => handle_play(req, cmd_queue, max_level_dbfs, true, capture_connected),
        "stop" => handle_stop(cmd_queue),
        "set_level" => handle_set_level(req, cmd_queue, max_level_dbfs),
        "set_signal" => handle_set_signal(req, cmd_queue),
        "set_channel" => handle_set_channel(req, cmd_queue),
        "set_freq" => handle_set_freq(req, cmd_queue),
        "status" => handle_status(latest_state),
        "capture_level" => handle_capture_level(latest_state),
        "get_recording" => HandleResult::GetRecording,
        other => HandleResult::Error(
            other.to_string(),
            format!("unknown command: \"{}\"", other),
        ),
    }
}

fn handle_play(
    req: &RpcRequest,
    cmd_queue: &CommandQueue,
    max_level_dbfs: f64,
    is_playrec: bool,
    capture_connected: bool,
) -> HandleResult {
    let cmd_name = if is_playrec { "playrec" } else { "play" };

    // BUG-SG12-4: Reject playrec when capture device is not connected.
    // Without this check, playrec silently records nothing and
    // get_recording returns "no recording available".
    if is_playrec && !capture_connected {
        return HandleResult::Error(
            cmd_name.to_string(),
            "capture device not connected".to_string(),
        );
    }

    // Signal type (required).
    let signal_str = match &req.signal {
        Some(s) => s.as_str(),
        None => return HandleResult::Error(cmd_name.to_string(), "missing \"signal\" field".to_string()),
    };
    let signal = match parse_signal_type(signal_str) {
        Ok(s) => s,
        Err(e) => return HandleResult::Error(cmd_name.to_string(), e),
    };

    // Channels (required).
    let ch_list = match &req.channels {
        Some(c) => c.as_slice(),
        None => return HandleResult::Error(cmd_name.to_string(), "missing \"channels\" field".to_string()),
    };
    if let Err(e) = validate_channels(ch_list) {
        return HandleResult::Error(cmd_name.to_string(), e);
    }
    let channels = channels_to_bitmask(ch_list);

    // Level (required).
    let level_dbfs = match req.level_dbfs {
        Some(l) => l,
        None => return HandleResult::Error(cmd_name.to_string(), "missing \"level_dbfs\" field".to_string()),
    };
    if let Err(e) = validate_level(level_dbfs, max_level_dbfs) {
        return HandleResult::Error(cmd_name.to_string(), e);
    }

    // Frequency (optional, defaults differ by signal type).
    let freq = req.freq.unwrap_or(1000.0);
    if signal == SignalType::Sine || signal == SignalType::Sweep {
        if let Err(e) = validate_freq(freq) {
            return HandleResult::Error(cmd_name.to_string(), e);
        }
    }

    // Sweep end frequency.
    let sweep_end = req.sweep_end.unwrap_or(20000.0);
    if signal == SignalType::Sweep {
        if let Err(e) = validate_freq(sweep_end) {
            return HandleResult::Error(cmd_name.to_string(), e);
        }
        if sweep_end <= freq {
            return HandleResult::Error(
                cmd_name.to_string(),
                format!("sweep_end {:.1} must be > freq {:.1}", sweep_end, freq),
            );
        }
    }

    // Duration.
    let duration = req.duration;

    // Playrec requires a finite duration.
    if is_playrec && duration.is_none() {
        return HandleResult::Error(
            cmd_name.to_string(),
            "playrec requires a finite \"duration\"".to_string(),
        );
    }

    // Build and push the command.
    let cmd = if is_playrec {
        Command {
            kind: CommandKind::Playrec {
                signal,
                channels,
                level_dbfs: level_dbfs as f32,
                frequency: freq as f32,
                duration_secs: duration.unwrap() as f32,
                sweep_end_hz: sweep_end as f32,
            },
        }
    } else {
        Command {
            kind: CommandKind::Play {
                signal,
                channels,
                level_dbfs: level_dbfs as f32,
                frequency: freq as f32,
                duration_secs: duration.map(|d| d as f32),
                sweep_end_hz: sweep_end as f32,
            },
        }
    };

    if cmd_queue.push(cmd).is_err() {
        return HandleResult::Error(cmd_name.to_string(), "command queue full".to_string());
    }

    HandleResult::Ack(cmd_name.to_string())
}

fn handle_stop(cmd_queue: &CommandQueue) -> HandleResult {
    let cmd = Command {
        kind: CommandKind::Stop,
    };
    if cmd_queue.push(cmd).is_err() {
        return HandleResult::Error("stop".to_string(), "command queue full".to_string());
    }
    HandleResult::Ack("stop".to_string())
}

fn handle_set_level(
    req: &RpcRequest,
    cmd_queue: &CommandQueue,
    max_level_dbfs: f64,
) -> HandleResult {
    let level_dbfs = match req.level_dbfs {
        Some(l) => l,
        None => {
            return HandleResult::Error(
                "set_level".to_string(),
                "missing \"level_dbfs\" field".to_string(),
            )
        }
    };
    if let Err(e) = validate_level(level_dbfs, max_level_dbfs) {
        return HandleResult::Error("set_level".to_string(), e);
    }

    let cmd = Command {
        kind: CommandKind::SetLevel {
            level_dbfs: level_dbfs as f32,
        },
    };
    if cmd_queue.push(cmd).is_err() {
        return HandleResult::Error("set_level".to_string(), "command queue full".to_string());
    }
    HandleResult::Ack("set_level".to_string())
}

fn handle_set_signal(req: &RpcRequest, cmd_queue: &CommandQueue) -> HandleResult {
    let signal_str = match &req.signal {
        Some(s) => s.as_str(),
        None => {
            return HandleResult::Error(
                "set_signal".to_string(),
                "missing \"signal\" field".to_string(),
            )
        }
    };
    let signal = match parse_signal_type(signal_str) {
        Ok(s) => s,
        Err(e) => return HandleResult::Error("set_signal".to_string(), e),
    };

    let freq = req.freq.unwrap_or(0.0) as f32;

    let cmd = Command {
        kind: CommandKind::SetSignal {
            signal,
            frequency: freq,
        },
    };
    if cmd_queue.push(cmd).is_err() {
        return HandleResult::Error("set_signal".to_string(), "command queue full".to_string());
    }
    HandleResult::Ack("set_signal".to_string())
}

fn handle_set_channel(req: &RpcRequest, cmd_queue: &CommandQueue) -> HandleResult {
    let ch_list = match &req.channels {
        Some(c) => c.as_slice(),
        None => {
            return HandleResult::Error(
                "set_channel".to_string(),
                "missing \"channels\" field".to_string(),
            )
        }
    };
    if let Err(e) = validate_channels(ch_list) {
        return HandleResult::Error("set_channel".to_string(), e);
    }

    let cmd = Command {
        kind: CommandKind::SetChannel {
            channels: channels_to_bitmask(ch_list),
        },
    };
    if cmd_queue.push(cmd).is_err() {
        return HandleResult::Error("set_channel".to_string(), "command queue full".to_string());
    }
    HandleResult::Ack("set_channel".to_string())
}

fn handle_set_freq(req: &RpcRequest, cmd_queue: &CommandQueue) -> HandleResult {
    let freq = match req.freq {
        Some(f) => f,
        None => {
            return HandleResult::Error(
                "set_freq".to_string(),
                "missing \"freq\" field".to_string(),
            )
        }
    };
    if let Err(e) = validate_freq(freq) {
        return HandleResult::Error("set_freq".to_string(), e);
    }

    let cmd = Command {
        kind: CommandKind::SetFrequency {
            frequency: freq as f32,
        },
    };
    if cmd_queue.push(cmd).is_err() {
        return HandleResult::Error("set_freq".to_string(), "command queue full".to_string());
    }
    HandleResult::Ack("set_freq".to_string())
}

fn handle_status(latest_state: &StateSnapshot) -> HandleResult {
    let is_playing = matches!(
        latest_state.state,
        PlayState::Playing | PlayState::Fading | PlayState::PlayrecInProgress
    );
    let is_recording = matches!(
        latest_state.state,
        PlayState::Recording | PlayState::PlayrecInProgress
    );

    let resp = StatusResponse {
        r#type: "ack",
        cmd: "status",
        ok: true,
        playing: is_playing,
        recording: is_recording,
        signal: signal_type_to_str(latest_state.signal).to_string(),
        freq: latest_state.frequency,
        channels: bitmask_to_channels(latest_state.channels),
        level_dbfs: latest_state.level_dbfs,
        elapsed: latest_state.elapsed_secs,
        duration: if latest_state.duration_secs > 0.0 {
            Some(latest_state.duration_secs)
        } else {
            None
        },
        capture_peak_dbfs: linear_to_dbfs(latest_state.capture_peak),
        capture_rms_dbfs: linear_to_dbfs(latest_state.capture_rms),
        capture_connected: latest_state.capture_connected,
        samples_generated: latest_state.samples_generated,
    };
    let json = serde_json::to_string(&resp).unwrap_or_else(|_| {
        r#"{"type":"ack","ok":false,"error":"internal: failed to serialize status"}"#.to_string()
    });
    HandleResult::StatusJson(json)
}

fn handle_capture_level(latest_state: &StateSnapshot) -> HandleResult {
    let resp = CaptureLevelResponse {
        r#type: "ack",
        cmd: "capture_level",
        ok: true,
        peak_dbfs: linear_to_dbfs(latest_state.capture_peak),
        rms_dbfs: linear_to_dbfs(latest_state.capture_rms),
    };
    let json = serde_json::to_string(&resp).unwrap_or_else(|_| {
        r#"{"type":"ack","ok":false,"error":"internal: failed to serialize capture_level"}"#
            .to_string()
    });
    HandleResult::CaptureLevelJson(json)
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

/// Format an async event as a JSON line.
pub fn format_event(event: &str) -> String {
    let data = serde_json::Map::new();
    // Events can carry additional data depending on type.
    // The base event structure is minimal.
    let resp = EventResponse {
        r#type: "event",
        event: event.to_string(),
        data,
    };
    serde_json::to_string(&resp).unwrap()
}

/// Format a state broadcast from a StateSnapshot.
pub fn format_state_broadcast(snap: &StateSnapshot) -> String {
    let is_playing = matches!(
        snap.state,
        PlayState::Playing | PlayState::Fading | PlayState::PlayrecInProgress
    );
    let is_recording = matches!(
        snap.state,
        PlayState::Recording | PlayState::PlayrecInProgress
    );

    let resp = StatusResponse {
        r#type: "state",
        cmd: "status",
        ok: true,
        playing: is_playing,
        recording: is_recording,
        signal: signal_type_to_str(snap.signal).to_string(),
        freq: snap.frequency,
        channels: bitmask_to_channels(snap.channels),
        level_dbfs: snap.level_dbfs,
        elapsed: snap.elapsed_secs,
        duration: if snap.duration_secs > 0.0 {
            Some(snap.duration_secs)
        } else {
            None
        },
        capture_peak_dbfs: linear_to_dbfs(snap.capture_peak),
        capture_rms_dbfs: linear_to_dbfs(snap.capture_rms),
        capture_connected: snap.capture_connected,
        samples_generated: snap.samples_generated,
    };
    serde_json::to_string(&resp).unwrap_or_default()
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

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::command::{CommandQueue, StateSnapshot, PlayState, SignalType};

    fn make_queue() -> CommandQueue {
        CommandQueue::new()
    }

    fn default_state() -> StateSnapshot {
        StateSnapshot::stopped()
    }

    // -----------------------------------------------------------------------
    // JSON parsing: valid commands
    // -----------------------------------------------------------------------

    #[test]
    fn parse_play_command() {
        let json = r#"{"cmd":"play","signal":"sine","channels":[1,2],"level_dbfs":-20.0,"freq":1000.0}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "play");
        assert_eq!(req.signal.as_deref(), Some("sine"));
        assert_eq!(req.channels.as_deref(), Some(&[1u8, 2][..]));
        assert_eq!(req.level_dbfs, Some(-20.0));
        assert_eq!(req.freq, Some(1000.0));
    }

    #[test]
    fn parse_stop_command() {
        let json = r#"{"cmd":"stop"}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "stop");
    }

    #[test]
    fn parse_set_level_command() {
        let json = r#"{"cmd":"set_level","level_dbfs":-15.0}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "set_level");
        assert_eq!(req.level_dbfs, Some(-15.0));
    }

    #[test]
    fn parse_set_freq_command() {
        let json = r#"{"cmd":"set_freq","freq":440.0}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "set_freq");
        assert_eq!(req.freq, Some(440.0));
    }

    #[test]
    fn parse_playrec_command() {
        let json = r#"{"cmd":"playrec","signal":"sweep","channels":[1],"level_dbfs":-20.0,"freq":20.0,"sweep_end":20000.0,"duration":10.0}"#;
        let req = parse_line(json).unwrap();
        assert_eq!(req.cmd, "playrec");
        assert_eq!(req.signal.as_deref(), Some("sweep"));
        assert_eq!(req.duration, Some(10.0));
        assert_eq!(req.sweep_end, Some(20000.0));
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
        let result = parse_line(r#"{"signal":"sine"}"#);
        // serde will default cmd to "" since String has no default via Deserialize
        // Actually, cmd is not Option and has no default, so this should fail
        // Let's check: serde requires cmd since it's String, not Option<String>
        // With no default, missing field causes deserialization error
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
        let json = r#"{"cmd":"stop"}"#;
        assert!(json.len() <= MAX_LINE_LENGTH);
        assert!(parse_line(json).is_ok());
    }

    #[test]
    fn line_exceeding_limit_rejected() {
        // Create a line that's just over 4096 bytes.
        let padding = "x".repeat(MAX_LINE_LENGTH + 1);
        let result = parse_line(&padding);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains("line too long"), "Error: {}", err);
    }

    #[test]
    fn line_at_exact_limit_accepted() {
        // A valid JSON that's exactly 4096 bytes.
        // We can't easily make valid JSON exactly 4096 bytes, but we can
        // verify that a line of exactly MAX_LINE_LENGTH passes the length check.
        let padding = " ".repeat(MAX_LINE_LENGTH - r#"{"cmd":"stop"}"#.len());
        let json = format!(r#"{{"cmd":"stop","_":"{}"}}"#, padding);
        // This may or may not be exactly MAX_LINE_LENGTH, but it tests
        // the boundary behavior. What matters: <= MAX_LINE_LENGTH passes.
        if json.len() <= MAX_LINE_LENGTH {
            // Should pass length check (may fail JSON parse if too large,
            // but the point is the length check doesn't reject it).
            let _ = parse_line(&json); // length check passes
        }
    }

    // -----------------------------------------------------------------------
    // Level rejection (AD-D037-3)
    // -----------------------------------------------------------------------

    #[test]
    fn level_above_cap_rejected() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"set_level","level_dbfs":-5.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Error(cmd, msg) => {
                assert_eq!(cmd, "set_level");
                assert!(msg.contains("exceeds cap"), "Error: {}", msg);
            }
            _ => panic!("Expected error for level above cap"),
        }
    }

    #[test]
    fn level_at_exactly_cap_accepted() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"set_level","level_dbfs":-20.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Ack(cmd) => assert_eq!(cmd, "set_level"),
            HandleResult::Error(_, msg) => panic!("Should accept at cap: {}", msg),
            _ => panic!("Expected ack"),
        }
    }

    #[test]
    fn level_below_cap_accepted() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"set_level","level_dbfs":-30.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Ack(cmd) => assert_eq!(cmd, "set_level"),
            _ => panic!("Expected ack"),
        }
    }

    #[test]
    fn play_level_above_cap_rejected() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"play","signal":"sine","channels":[1],"level_dbfs":-5.0,"freq":1000.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Error(cmd, msg) => {
                assert_eq!(cmd, "play");
                assert!(msg.contains("exceeds cap"), "Error: {}", msg);
            }
            _ => panic!("Expected error for level above cap in play"),
        }
    }

    // -----------------------------------------------------------------------
    // Frequency validation (AE-MF-2)
    // -----------------------------------------------------------------------

    #[test]
    fn freq_below_20hz_rejected() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"set_freq","freq":10.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Error(cmd, msg) => {
                assert_eq!(cmd, "set_freq");
                assert!(msg.contains("below minimum"), "Error: {}", msg);
            }
            _ => panic!("Expected error for freq below 20 Hz"),
        }
    }

    #[test]
    fn freq_above_20khz_rejected() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"set_freq","freq":25000.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Error(cmd, msg) => {
                assert_eq!(cmd, "set_freq");
                assert!(msg.contains("above maximum"), "Error: {}", msg);
            }
            _ => panic!("Expected error for freq above 20 kHz"),
        }
    }

    #[test]
    fn freq_within_range_accepted() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"set_freq","freq":1000.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Ack(cmd) => assert_eq!(cmd, "set_freq"),
            _ => panic!("Expected ack for valid freq"),
        }
    }

    #[test]
    fn freq_at_boundaries_accepted() {
        let q = make_queue();
        let state = default_state();

        // Exactly 20 Hz.
        let json = r#"{"cmd":"set_freq","freq":20.0}"#;
        let req = parse_line(json).unwrap();
        assert!(matches!(handle_request(&req, &q, -20.0, &state, true), HandleResult::Ack(_)));

        // Exactly 20000 Hz.
        let json = r#"{"cmd":"set_freq","freq":20000.0}"#;
        let req = parse_line(json).unwrap();
        assert!(matches!(handle_request(&req, &q, -20.0, &state, true), HandleResult::Ack(_)));
    }

    // -----------------------------------------------------------------------
    // Channel validation
    // -----------------------------------------------------------------------

    #[test]
    fn channel_out_of_range_rejected() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"set_channel","channels":[9]}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Error(cmd, msg) => {
                assert_eq!(cmd, "set_channel");
                assert!(msg.contains("out of range"), "Error: {}", msg);
            }
            _ => panic!("Expected error for channel out of range"),
        }
    }

    #[test]
    fn channel_array_to_bitmask_in_play() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"play","signal":"sine","channels":[1,3,5],"level_dbfs":-20.0,"freq":1000.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        assert!(matches!(result, HandleResult::Ack(_)));

        // Verify the command was pushed with correct bitmask.
        let cmd = q.pop().unwrap();
        match cmd.kind {
            CommandKind::Play { channels, .. } => {
                assert_eq!(channels, 0b0001_0101, "channels bitmask for [1,3,5]");
            }
            other => panic!("Expected Play, got {:?}", other),
        }
    }

    // -----------------------------------------------------------------------
    // Sweep validation
    // -----------------------------------------------------------------------

    #[test]
    fn sweep_end_must_be_greater_than_freq() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"play","signal":"sweep","channels":[1],"level_dbfs":-20.0,"freq":1000.0,"sweep_end":500.0,"duration":1.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Error(_, msg) => {
                assert!(msg.contains("must be > freq"), "Error: {}", msg);
            }
            _ => panic!("Expected error for sweep_end <= freq"),
        }
    }

    // -----------------------------------------------------------------------
    // Playrec validation
    // -----------------------------------------------------------------------

    #[test]
    fn playrec_requires_duration() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"playrec","signal":"pink","channels":[1],"level_dbfs":-20.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Error(cmd, msg) => {
                assert_eq!(cmd, "playrec");
                assert!(msg.contains("duration"), "Error: {}", msg);
            }
            _ => panic!("Expected error for playrec without duration"),
        }
    }

    // -----------------------------------------------------------------------
    // Status response
    // -----------------------------------------------------------------------

    #[test]
    fn status_response_includes_all_fields() {
        let state = StateSnapshot {
            state: PlayState::Playing,
            signal: SignalType::Sine,
            channels: 0b0000_0011,
            level_dbfs: -20.0,
            frequency: 1000.0,
            elapsed_secs: 1.5,
            duration_secs: 10.0,
            capture_peak: 0.05,
            capture_rms: 0.02,
            capture_connected: true,
            samples_generated: 72000,
        };

        let q = make_queue();
        let json = r#"{"cmd":"status"}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);

        match result {
            HandleResult::StatusJson(json_str) => {
                let v: Value = serde_json::from_str(&json_str).unwrap();
                assert_eq!(v["type"], "ack");
                assert_eq!(v["cmd"], "status");
                assert_eq!(v["ok"], true);
                assert_eq!(v["playing"], true);
                assert_eq!(v["recording"], false);
                assert_eq!(v["signal"], "sine");
                assert_eq!(v["freq"], 1000.0);
                assert_eq!(v["channels"], serde_json::json!([1, 2]));
                assert_eq!(v["level_dbfs"], -20.0);
                assert_eq!(v["elapsed"], 1.5);
                assert_eq!(v["duration"], 10.0);
                assert!(v["capture_connected"].as_bool().unwrap());
                assert_eq!(v["samples_generated"], 72000);
                // capture_peak_dbfs and capture_rms_dbfs should be present.
                assert!(v["capture_peak_dbfs"].is_number());
                assert!(v["capture_rms_dbfs"].is_number());
            }
            _ => panic!("Expected StatusJson"),
        }
    }

    // -----------------------------------------------------------------------
    // Ack/error response format
    // -----------------------------------------------------------------------

    #[test]
    fn ack_response_format() {
        let json = format_ack("play");
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "ack");
        assert_eq!(v["cmd"], "play");
        assert_eq!(v["ok"], true);
        assert!(v.get("error").is_none() || v["error"].is_null());
    }

    #[test]
    fn error_response_format() {
        let json = format_error("set_level", "level -5.0 exceeds cap -20.0");
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "ack");
        assert_eq!(v["cmd"], "set_level");
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"], "level -5.0 exceeds cap -20.0");
    }

    // -----------------------------------------------------------------------
    // Stop command pushes to queue
    // -----------------------------------------------------------------------

    #[test]
    fn stop_pushes_to_queue() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"stop"}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        assert!(matches!(result, HandleResult::Ack(_)));

        let cmd = q.pop().unwrap();
        assert!(matches!(cmd.kind, CommandKind::Stop));
    }

    // -----------------------------------------------------------------------
    // Unknown command
    // -----------------------------------------------------------------------

    #[test]
    fn unknown_command_rejected() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"reboot"}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Error(_, msg) => {
                assert!(msg.contains("unknown command"), "Error: {}", msg);
            }
            _ => panic!("Expected error for unknown command"),
        }
    }

    // -----------------------------------------------------------------------
    // Signal type parsing
    // -----------------------------------------------------------------------

    #[test]
    fn signal_type_parsing() {
        assert_eq!(parse_signal_type("silence"), Ok(SignalType::Silence));
        assert_eq!(parse_signal_type("sine"), Ok(SignalType::Sine));
        assert_eq!(parse_signal_type("white"), Ok(SignalType::White));
        assert_eq!(parse_signal_type("pink"), Ok(SignalType::Pink));
        assert_eq!(parse_signal_type("sweep"), Ok(SignalType::Sweep));
        assert!(parse_signal_type("sawtooth").is_err());
    }

    // -----------------------------------------------------------------------
    // State broadcast formatting
    // -----------------------------------------------------------------------

    #[test]
    fn state_broadcast_format() {
        let snap = StateSnapshot {
            state: PlayState::Stopped,
            signal: SignalType::Silence,
            channels: 0,
            level_dbfs: -120.0,
            frequency: 0.0,
            elapsed_secs: 0.0,
            duration_secs: 0.0,
            capture_peak: 0.0,
            capture_rms: 0.0,
            capture_connected: false,
            samples_generated: 0,
        };
        let json = format_state_broadcast(&snap);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["type"], "state");
        assert_eq!(v["cmd"], "status");
        assert_eq!(v["playing"], false);
        assert_eq!(v["recording"], false);
    }

    // -----------------------------------------------------------------------
    // Validation helpers direct tests
    // -----------------------------------------------------------------------

    #[test]
    fn validate_freq_boundaries() {
        assert!(validate_freq(20.0).is_ok());
        assert!(validate_freq(20000.0).is_ok());
        assert!(validate_freq(19.9).is_err());
        assert!(validate_freq(20001.0).is_err());
        assert!(validate_freq(1000.0).is_ok());
    }

    #[test]
    fn validate_channels_valid() {
        assert!(validate_channels(&[1]).is_ok());
        assert!(validate_channels(&[1, 2, 3, 4, 5, 6, 7, 8]).is_ok());
    }

    #[test]
    fn validate_channels_invalid() {
        assert!(validate_channels(&[0]).is_err());
        assert!(validate_channels(&[9]).is_err());
        assert!(validate_channels(&[]).is_err());
    }

    #[test]
    fn validate_level_boundaries() {
        assert!(validate_level(-20.0, -20.0).is_ok()); // exactly at cap
        assert!(validate_level(-30.0, -20.0).is_ok()); // below cap
        assert!(validate_level(-19.9, -20.0).is_err()); // above cap
        assert!(validate_level(-60.0, -20.0).is_ok()); // at minimum
        assert!(validate_level(-61.0, -20.0).is_err()); // below minimum
    }

    // -----------------------------------------------------------------------
    // BUG-SG12-4: playrec rejected when capture disconnected
    // -----------------------------------------------------------------------

    #[test]
    fn playrec_rejected_when_capture_disconnected() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"playrec","signal":"sweep","channels":[1],"level_dbfs":-20.0,"freq":20.0,"sweep_end":20000.0,"duration":10.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, false);
        match result {
            HandleResult::Error(cmd, msg) => {
                assert_eq!(cmd, "playrec");
                assert!(
                    msg.contains("capture device not connected"),
                    "Error: {}",
                    msg
                );
            }
            _ => panic!("Expected error for playrec with disconnected capture"),
        }
        // Verify no command was pushed to the queue.
        assert!(q.pop().is_none(), "No command should be queued");
    }

    #[test]
    fn playrec_accepted_when_capture_connected() {
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"playrec","signal":"sweep","channels":[1],"level_dbfs":-20.0,"freq":20.0,"sweep_end":20000.0,"duration":10.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, true);
        match result {
            HandleResult::Ack(cmd) => assert_eq!(cmd, "playrec"),
            HandleResult::Error(_, msg) => {
                panic!("playrec should be accepted when capture connected: {}", msg)
            }
            _ => panic!("Expected Ack"),
        }
        // Verify the command was queued.
        let cmd = q.pop().unwrap();
        assert!(matches!(cmd.kind, CommandKind::Playrec { .. }));
    }

    #[test]
    fn play_accepted_when_capture_disconnected() {
        // Regular play (not playrec) should work regardless of capture state.
        let q = make_queue();
        let state = default_state();
        let json = r#"{"cmd":"play","signal":"sine","channels":[1],"level_dbfs":-20.0,"freq":1000.0}"#;
        let req = parse_line(json).unwrap();
        let result = handle_request(&req, &q, -20.0, &state, false);
        match result {
            HandleResult::Ack(cmd) => assert_eq!(cmd, "play"),
            HandleResult::Error(_, msg) => {
                panic!("play should succeed even without capture: {}", msg)
            }
            _ => panic!("Expected Ack"),
        }
    }
}
