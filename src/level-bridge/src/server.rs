//! TCP/Unix socket server for streaming level metering data to the web UI.
//!
//! Sends JSON snapshots at ~30 Hz to all connected clients. Each snapshot
//! is a single JSON line (newline-delimited). Format:
//!   `{"channels":N,"peak":[...],"rms":[...],"pos":N,"nsec":N}\n`
//!
//! Values are in dBFS, rounded to 1 decimal place. -120.0 means silence.

use std::io::Write;
use std::net::{TcpListener, TcpStream};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use log::{error, info, warn};

use crate::levels::LevelTracker;
use crate::notifier::Notifier;
use crate::ListenKind;

/// Run the level metering server. Blocks until shutdown is signalled.
pub fn run_levels_server(
    kind: ListenKind,
    addr: &str,
    tracker: Arc<LevelTracker>,
    shutdown: Arc<AtomicBool>,
    notifier: Arc<Notifier>,
) {
    match kind {
        ListenKind::Tcp => run_levels_tcp(addr, tracker, shutdown, notifier),
        ListenKind::Unix => run_levels_unix(addr, tracker, shutdown, notifier),
    }
}

fn run_levels_tcp(
    addr: &str,
    tracker: Arc<LevelTracker>,
    shutdown: Arc<AtomicBool>,
    notifier: Arc<Notifier>,
) {
    let listener = TcpListener::bind(addr).unwrap_or_else(|e| {
        error!("Failed to bind levels TCP {}: {}", addr, e);
        std::process::exit(1);
    });
    listener
        .set_nonblocking(true)
        .expect("Failed to set non-blocking on levels listener");
    info!("Levels TCP server listening on {}", addr);

    let mut clients: Vec<TcpStream> = Vec::new();

    // US-081: ~30 Hz snapshot rate for smooth meter rendering.
    let snapshot_interval = Duration::from_millis(33);
    let mut last_snapshot = std::time::Instant::now();

    while !shutdown.load(Ordering::Relaxed) {
        // Accept new connections.
        match listener.accept() {
            Ok((stream, peer)) => {
                info!("Levels client connected: {}", peer);
                let _ = stream.set_nodelay(true);
                let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
                let _ = stream.set_nonblocking(false);
                clients.push(stream);
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
            Err(e) => {
                warn!("Levels TCP accept error: {}", e);
            }
        }

        // Wait for PW process callback notification or timeout.
        let elapsed = last_snapshot.elapsed();
        if elapsed < snapshot_interval {
            let remaining = snapshot_interval - elapsed;
            notifier.wait(remaining);
            if last_snapshot.elapsed() < snapshot_interval {
                continue;
            }
        }

        // Take a snapshot and broadcast to all clients.
        last_snapshot = std::time::Instant::now();
        let snap = tracker.take_snapshot();
        let json = format_level_json(&snap);

        clients.retain_mut(|stream| {
            match stream.write_all(json.as_bytes()) {
                Ok(()) => true,
                Err(_) => {
                    info!("Levels client disconnected");
                    false
                }
            }
        });
    }

    info!("Levels TCP server shutting down");
}

fn run_levels_unix(
    path: &str,
    tracker: Arc<LevelTracker>,
    shutdown: Arc<AtomicBool>,
    notifier: Arc<Notifier>,
) {
    let _ = std::fs::remove_file(path);
    let listener = UnixListener::bind(path).unwrap_or_else(|e| {
        error!("Failed to bind levels Unix socket {}: {}", path, e);
        std::process::exit(1);
    });
    listener
        .set_nonblocking(true)
        .expect("Failed to set non-blocking on levels listener");
    info!("Levels Unix socket server listening on {}", path);

    let mut clients: Vec<UnixStream> = Vec::new();

    let snapshot_interval = Duration::from_millis(33);
    let mut last_snapshot = std::time::Instant::now();

    while !shutdown.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, _)) => {
                info!("Levels Unix client connected");
                let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
                let _ = stream.set_nonblocking(false);
                clients.push(stream);
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
            Err(e) => {
                warn!("Levels Unix accept error: {}", e);
            }
        }

        let elapsed = last_snapshot.elapsed();
        if elapsed < snapshot_interval {
            let remaining = snapshot_interval - elapsed;
            notifier.wait(remaining);
            if last_snapshot.elapsed() < snapshot_interval {
                continue;
            }
        }

        last_snapshot = std::time::Instant::now();
        let snap = tracker.take_snapshot();
        let json = format_level_json(&snap);

        clients.retain_mut(|stream| {
            match stream.write_all(json.as_bytes()) {
                Ok(()) => true,
                Err(_) => {
                    info!("Levels Unix client disconnected");
                    false
                }
            }
        });
    }

    let _ = std::fs::remove_file(path);
    info!("Levels Unix socket server shutting down");
}

/// Format a level snapshot as a newline-delimited JSON string.
/// One line per snapshot: `{"channels":N,"peak":[...],"rms":[...],"pos":N,"nsec":N}\n`
fn format_level_json(snap: &crate::levels::LevelSnapshot) -> String {
    let ch = snap.channels;
    let mut s = String::with_capacity(32 + ch * 16);
    s.push_str("{\"channels\":");
    s.push_str(&ch.to_string());

    s.push_str(",\"peak\":[");
    for i in 0..ch {
        if i > 0 {
            s.push(',');
        }
        write_f32_1dp(&mut s, snap.peak_dbfs[i]);
    }

    s.push_str("],\"rms\":[");
    for i in 0..ch {
        if i > 0 {
            s.push(',');
        }
        write_f32_1dp(&mut s, snap.rms_dbfs[i]);
    }

    s.push_str("],\"pos\":");
    s.push_str(&snap.graph_clock.position.to_string());
    s.push_str(",\"nsec\":");
    s.push_str(&snap.graph_clock.nsec.to_string());
    s.push_str("}\n");
    s
}

/// Write an f32 rounded to 1 decimal place without pulling in a formatting library.
fn write_f32_1dp(s: &mut String, v: f32) {
    use std::fmt::Write;
    let _ = write!(s, "{:.1}", v);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::levels::LevelSnapshot;

    #[test]
    fn format_level_json_empty_channels() {
        let snap = LevelSnapshot::default();
        let json = format_level_json(&snap);
        assert_eq!(json, "{\"channels\":0,\"peak\":[],\"rms\":[],\"pos\":0,\"nsec\":0}\n");
    }

    #[test]
    fn format_level_json_single_channel() {
        let mut snap = LevelSnapshot::default();
        snap.channels = 1;
        snap.peak_dbfs[0] = -3.1;
        snap.rms_dbfs[0] = -12.5;
        let json = format_level_json(&snap);
        assert_eq!(json, "{\"channels\":1,\"peak\":[-3.1],\"rms\":[-12.5],\"pos\":0,\"nsec\":0}\n");
    }

    #[test]
    fn format_level_json_two_channels() {
        let mut snap = LevelSnapshot::default();
        snap.channels = 2;
        snap.peak_dbfs[0] = -0.5;
        snap.peak_dbfs[1] = -6.0;
        snap.rms_dbfs[0] = -10.0;
        snap.rms_dbfs[1] = -20.0;
        let json = format_level_json(&snap);
        assert_eq!(json, "{\"channels\":2,\"peak\":[-0.5,-6.0],\"rms\":[-10.0,-20.0],\"pos\":0,\"nsec\":0}\n");
    }

    #[test]
    fn format_level_json_silence() {
        let mut snap = LevelSnapshot::default();
        snap.channels = 2;
        let json = format_level_json(&snap);
        assert_eq!(json, "{\"channels\":2,\"peak\":[-120.0,-120.0],\"rms\":[-120.0,-120.0],\"pos\":0,\"nsec\":0}\n");
    }

    #[test]
    fn format_level_json_ends_with_newline() {
        let snap = LevelSnapshot::default();
        let json = format_level_json(&snap);
        assert!(json.ends_with('\n'));
    }

    #[test]
    fn format_level_json_is_valid_json() {
        let mut snap = LevelSnapshot::default();
        snap.channels = 3;
        snap.peak_dbfs[0] = -1.5;
        snap.peak_dbfs[1] = -3.2;
        snap.peak_dbfs[2] = -120.0;
        snap.rms_dbfs[0] = -10.3;
        snap.rms_dbfs[1] = -15.7;
        snap.rms_dbfs[2] = -120.0;
        let json = format_level_json(&snap);
        let trimmed = json.trim();
        assert!(trimmed.starts_with('{'));
        assert!(trimmed.ends_with('}'));
        assert!(trimmed.contains("\"channels\":3"));
        assert!(trimmed.contains("\"peak\":["));
        assert!(trimmed.contains("\"rms\":["));
        assert!(trimmed.contains("\"pos\":"));
        assert!(trimmed.contains("\"nsec\":"));
    }

    #[test]
    fn format_level_json_with_graph_clock() {
        use crate::levels::GraphClock;
        let mut snap = LevelSnapshot::default();
        snap.channels = 1;
        snap.peak_dbfs[0] = -6.0;
        snap.rms_dbfs[0] = -12.0;
        snap.graph_clock = GraphClock { position: 48000, nsec: 1_000_000_000 };
        let json = format_level_json(&snap);
        assert_eq!(json, "{\"channels\":1,\"peak\":[-6.0],\"rms\":[-12.0],\"pos\":48000,\"nsec\":1000000000}\n");
    }
}
