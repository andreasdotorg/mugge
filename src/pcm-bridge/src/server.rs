//! Socket server for streaming PCM data to the web UI.
//!
//! Accepts TCP or Unix socket connections. Each client gets its own reader
//! position in the ring buffer. If a client falls behind, it skips ahead
//! (drop-oldest). If no client is connected, frames are silently dropped
//! by the ring buffer (no backpressure to PipeWire).
//!
//! Wire format v2 (US-077):
//!   - 1-byte version (0x02)
//!   - 3-byte padding (0x00) — aligns subsequent fields and ensures
//!     PCM data starts at byte 24 (4-byte aligned for Float32Array)
//!   - 4-byte LE uint32: frame count in this chunk
//!   - 8-byte LE uint64: graph clock position (frames)
//!   - 8-byte LE uint64: graph clock nsec (monotonic nanoseconds)
//!   - N * channels * 4 bytes: interleaved float32 PCM samples

use std::io::Write;
use std::net::{TcpListener, TcpStream};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use log::{error, info, warn};

use crate::levels::LevelTracker;
use crate::notifier::Notifier;
use crate::ring_buffer::RingBuffer;
use crate::ListenKind;

/// Run the socket server. Blocks until shutdown is signalled.
pub fn run_server(
    kind: ListenKind,
    addr: &str,
    ring: Arc<RingBuffer>,
    shutdown: Arc<AtomicBool>,
    notifier: Arc<Notifier>,
    quantum: usize,
    channels: usize,
) {
    match kind {
        ListenKind::Tcp => run_tcp(addr, ring, shutdown, notifier, quantum, channels),
        ListenKind::Unix => run_unix(addr, ring, shutdown, notifier, quantum, channels),
    }
}

/// A connected PCM stream client with its own read position.
struct PcmClient<S: Write> {
    stream: S,
    read_pos: usize,
}

fn run_tcp(
    addr: &str,
    ring: Arc<RingBuffer>,
    shutdown: Arc<AtomicBool>,
    notifier: Arc<Notifier>,
    quantum: usize,
    channels: usize,
) {
    let listener = TcpListener::bind(addr).unwrap_or_else(|e| {
        error!("Failed to bind TCP {}: {}", addr, e);
        std::process::exit(1);
    });
    listener
        .set_nonblocking(true)
        .expect("Failed to set non-blocking");
    info!("TCP server listening on {}", addr);

    let mut clients: Vec<PcmClient<TcpStream>> = Vec::new();
    broadcast_loop(&listener, &mut clients, &ring, &shutdown, &notifier, quantum, channels,
        |stream, peer| {
            info!("TCP client connected: {}", peer);
            let _ = stream.set_nodelay(true);
            let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
        },
        |listener| {
            match listener.accept() {
                Ok((stream, peer)) => Some((stream, format!("{}", peer))),
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => None,
                Err(e) => {
                    warn!("TCP accept error: {}", e);
                    None
                }
            }
        },
    );

    info!("TCP server shutting down");
}

fn run_unix(
    path: &str,
    ring: Arc<RingBuffer>,
    shutdown: Arc<AtomicBool>,
    notifier: Arc<Notifier>,
    quantum: usize,
    channels: usize,
) {
    let _ = std::fs::remove_file(path);

    let listener = UnixListener::bind(path).unwrap_or_else(|e| {
        error!("Failed to bind Unix socket {}: {}", path, e);
        std::process::exit(1);
    });
    listener
        .set_nonblocking(true)
        .expect("Failed to set non-blocking");
    info!("Unix socket server listening on {}", path);

    let mut clients: Vec<PcmClient<UnixStream>> = Vec::new();
    broadcast_loop(&listener, &mut clients, &ring, &shutdown, &notifier, quantum, channels,
        |stream, _peer| {
            info!("Unix socket client connected");
            let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
        },
        |listener| {
            match listener.accept() {
                Ok((stream, _)) => Some((stream, "unix".to_string())),
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => None,
                Err(e) => {
                    warn!("Unix accept error: {}", e);
                    None
                }
            }
        },
    );

    let _ = std::fs::remove_file(path);
    info!("Unix socket server shutting down");
}

/// Single-thread broadcast loop (F-077: replaces thread-per-client).
///
/// Accepts new connections, maintains a list of clients with independent read
/// positions, and broadcasts each quantum of PCM data to all connected clients.
/// Disconnected or slow clients are dropped via `retain_mut`.
///
/// US-077 Phase 4: the loop waits on a `Notifier` signaled by the PW process
/// callback instead of polling with `thread::sleep`. Data emission is driven
/// by the PW graph clock.
fn broadcast_loop<L, S, Setup, Accept>(
    listener: &L,
    clients: &mut Vec<PcmClient<S>>,
    ring: &Arc<RingBuffer>,
    shutdown: &Arc<AtomicBool>,
    notifier: &Notifier,
    quantum: usize,
    channels: usize,
    setup: Setup,
    accept: Accept,
)
where
    S: Write,
    Setup: Fn(&S, &str),
    Accept: Fn(&L) -> Option<(S, String)>,
{
    let payload_bytes = quantum * channels * std::mem::size_of::<f32>();
    // Wire format v2: [version:1][pad:3][frame_count:4][graph_pos:8][graph_nsec:8][PCM data]
    // 24-byte header ensures PCM data is 4-byte aligned (Float32Array compatible).
    let header_bytes: usize = 24; // 1 + 3 + 4 + 8 + 8
    let mut out_buf = vec![0u8; header_bytes + payload_bytes];
    out_buf[0] = 2; // version; bytes 1..4 are zero padding
    let frame_count = quantum as u32;
    out_buf[4..8].copy_from_slice(&frame_count.to_le_bytes());
    // graph_pos and graph_nsec are written per-quantum below

    // Timeout for notifier wait — used for shutdown polling and new-connection
    // acceptance when no audio data is flowing.
    let wait_timeout = Duration::from_millis(200);

    while !shutdown.load(Ordering::Relaxed) {
        // Accept all pending new connections.
        while let Some((stream, peer)) = accept(listener) {
            setup(&stream, &peer);
            clients.push(PcmClient {
                stream,
                read_pos: ring.write_pos(),
            });
        }

        let wp = ring.write_pos();

        // Not enough data for a full quantum — wait for notification from
        // the PW process callback (US-077 Phase 4: replaces thread::sleep).
        let min_read = clients.iter().map(|c| c.read_pos).min().unwrap_or(wp);
        if wp < min_read + quantum {
            notifier.wait(wait_timeout);
            continue;
        }

        // If no clients, wait for notification or new connection.
        if clients.is_empty() {
            notifier.wait(wait_timeout);
            continue;
        }

        // Read one quantum from the ring buffer (shared across all clients).
        // We read at the minimum read_pos — clients ahead of this will skip.
        // Actually, each client has its own read_pos, but the ring buffer data
        // is the same for all. We read once per quantum and broadcast.
        match ring.read_interleaved(min_read, quantum) {
            Some(samples) => {
                // Stamp metadata from ring buffer's latest chunk.
                // NOTE: latest_meta() may return metadata from a quantum newer
                // than the PCM data being sent (skew <= 1 quantum). Acceptable
                // for Phase 2 display use — the clock is informational, not
                // sample-accurate for this consumer.
                let meta = ring.latest_meta();
                let (graph_pos, graph_nsec) = match meta {
                    Some(m) => (m.graph_position, m.graph_nsec),
                    None => (0u64, 0u64),
                };
                out_buf[8..16].copy_from_slice(&graph_pos.to_le_bytes());
                out_buf[16..24].copy_from_slice(&graph_nsec.to_le_bytes());

                let sample_bytes = unsafe {
                    std::slice::from_raw_parts(
                        samples.as_ptr() as *const u8,
                        samples.len() * std::mem::size_of::<f32>(),
                    )
                };
                out_buf[header_bytes..].copy_from_slice(sample_bytes);

                // Broadcast to all clients; drop any that fail.
                clients.retain_mut(|client| {
                    // Skip clients that have lapped.
                    if wp > client.read_pos + ring.capacity() {
                        let skipped = wp - client.read_pos - ring.capacity();
                        warn!("Client too slow, skipping {} frames", skipped);
                        client.read_pos = wp;
                    }

                    // Client not yet ready for this quantum — it will catch up.
                    if client.read_pos > min_read {
                        return true;
                    }

                    match client.stream.write_all(&out_buf) {
                        Ok(()) => {
                            client.read_pos += quantum;
                            true
                        }
                        Err(_) => {
                            info!("Client disconnected");
                            false
                        }
                    }
                });
            }
            None => {
                // Ring returned None — reset all clients to current write pos.
                for client in clients.iter_mut() {
                    client.read_pos = ring.write_pos();
                }
                notifier.wait(wait_timeout);
            }
        }
    }
}

// ---- Level metering server (US060-3) ----

/// Run the level metering server. Sends JSON snapshots at ~10 Hz to all
/// connected clients. Each snapshot is a single JSON line (newline-delimited).
///
/// US-077 Phase 4: the server waits on a `Notifier` signaled by the PW
/// process callback instead of sleeping for a fixed 100ms. This makes
/// snapshot emission driven by the PW graph clock.
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

    // Track connected clients. Each gets its own writer.
    let clients: Arc<std::sync::Mutex<Vec<TcpStream>>> =
        Arc::new(std::sync::Mutex::new(Vec::new()));

    // US-077 Phase 4: ~10 Hz rate maintained by accumulating quanta
    // notifications. Wait up to 100ms for the next notification; take
    // a snapshot when woken or on timeout.
    let snapshot_interval = Duration::from_millis(100);
    let mut last_snapshot = std::time::Instant::now();

    while !shutdown.load(Ordering::Relaxed) {
        // Accept new connections.
        match listener.accept() {
            Ok((stream, peer)) => {
                info!("Levels client connected: {}", peer);
                let _ = stream.set_nodelay(true);
                let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
                let _ = stream.set_nonblocking(false);
                clients.lock().unwrap().push(stream);
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
            // After waking, check if enough time has passed for a snapshot.
            if last_snapshot.elapsed() < snapshot_interval {
                continue; // Not time yet — loop back to accept + wait.
            }
        }

        // Take a snapshot and broadcast to all clients.
        last_snapshot = std::time::Instant::now();
        let snap = tracker.take_snapshot();
        let json = format_level_json(&snap);

        let mut locked = clients.lock().unwrap();
        locked.retain_mut(|stream| {
            match stream.write_all(json.as_bytes()) {
                Ok(()) => true,
                Err(_) => {
                    info!("Levels client disconnected");
                    false
                }
            }
        });
        drop(locked);
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

    let clients: Arc<std::sync::Mutex<Vec<UnixStream>>> =
        Arc::new(std::sync::Mutex::new(Vec::new()));

    let snapshot_interval = Duration::from_millis(100);
    let mut last_snapshot = std::time::Instant::now();

    while !shutdown.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, _)) => {
                info!("Levels Unix client connected");
                let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
                let _ = stream.set_nonblocking(false);
                clients.lock().unwrap().push(stream);
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
            Err(e) => {
                warn!("Levels Unix accept error: {}", e);
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

        last_snapshot = std::time::Instant::now();
        let snap = tracker.take_snapshot();
        let json = format_level_json(&snap);

        let mut locked = clients.lock().unwrap();
        locked.retain_mut(|stream| {
            match stream.write_all(json.as_bytes()) {
                Ok(()) => true,
                Err(_) => {
                    info!("Levels Unix client disconnected");
                    false
                }
            }
        });
        drop(locked);
    }

    let _ = std::fs::remove_file(path);
    info!("Levels Unix socket server shutting down");
}

/// Format a level snapshot as a newline-delimited JSON string.
/// One line per snapshot: `{"channels":N,"peak":[...],"rms":[...]}\n`
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
        // Default values are -120.0
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
        // Verify it starts with { and ends with }
        assert!(trimmed.starts_with('{'));
        assert!(trimmed.ends_with('}'));
        // Verify it contains the expected keys
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
