//! Socket server for streaming PCM data to the web UI.
//!
//! Accepts TCP or Unix socket connections. Each client gets its own reader
//! position in the ring buffer. If a client falls behind, it skips ahead
//! (drop-oldest). If no client is connected, frames are silently dropped
//! by the ring buffer (no backpressure to PipeWire).
//!
//! Wire format (matches existing web UI PcmStreamCollector):
//!   - 4-byte LE uint32: frame count in this chunk
//!   - N * channels * 4 bytes: interleaved float32 PCM samples

use std::io::Write;
use std::net::{TcpListener, TcpStream};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use log::{error, info, warn};

use crate::levels::LevelTracker;
use crate::ring_buffer::RingBuffer;
use crate::ListenKind;

/// Run the socket server. Blocks until shutdown is signalled.
pub fn run_server(
    kind: ListenKind,
    addr: &str,
    ring: Arc<RingBuffer>,
    shutdown: Arc<AtomicBool>,
    quantum: usize,
    channels: usize,
) {
    match kind {
        ListenKind::Tcp => run_tcp(addr, ring, shutdown, quantum, channels),
        ListenKind::Unix => run_unix(addr, ring, shutdown, quantum, channels),
    }
}

fn run_tcp(
    addr: &str,
    ring: Arc<RingBuffer>,
    shutdown: Arc<AtomicBool>,
    quantum: usize,
    channels: usize,
) {
    let listener = TcpListener::bind(addr).unwrap_or_else(|e| {
        error!("Failed to bind TCP {}: {}", addr, e);
        std::process::exit(1);
    });
    // Non-blocking accept so we can check the shutdown flag.
    listener
        .set_nonblocking(true)
        .expect("Failed to set non-blocking");
    info!("TCP server listening on {}", addr);

    while !shutdown.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, peer)) => {
                info!("TCP client connected: {}", peer);
                let ring = ring.clone();
                let shutdown = shutdown.clone();
                std::thread::Builder::new()
                    .name(format!("client-{}", peer))
                    .spawn(move || {
                        handle_tcp_client(stream, ring, shutdown, quantum, channels);
                    })
                    .expect("Failed to spawn client thread");
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                // No pending connection — sleep briefly and retry.
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => {
                warn!("TCP accept error: {}", e);
                std::thread::sleep(Duration::from_millis(100));
            }
        }
    }

    info!("TCP server shutting down");
}

fn run_unix(
    path: &str,
    ring: Arc<RingBuffer>,
    shutdown: Arc<AtomicBool>,
    quantum: usize,
    channels: usize,
) {
    // Remove stale socket file if it exists.
    let _ = std::fs::remove_file(path);

    let listener = UnixListener::bind(path).unwrap_or_else(|e| {
        error!("Failed to bind Unix socket {}: {}", path, e);
        std::process::exit(1);
    });
    listener
        .set_nonblocking(true)
        .expect("Failed to set non-blocking");
    info!("Unix socket server listening on {}", path);

    while !shutdown.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, _)) => {
                info!("Unix socket client connected");
                let ring = ring.clone();
                let shutdown = shutdown.clone();
                std::thread::Builder::new()
                    .name("client-unix".into())
                    .spawn(move || {
                        handle_unix_client(stream, ring, shutdown, quantum, channels);
                    })
                    .expect("Failed to spawn client thread");
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => {
                warn!("Unix accept error: {}", e);
                std::thread::sleep(Duration::from_millis(100));
            }
        }
    }

    // Clean up the socket file.
    let _ = std::fs::remove_file(path);
    info!("Unix socket server shutting down");
}

fn handle_tcp_client(
    mut stream: TcpStream,
    ring: Arc<RingBuffer>,
    shutdown: Arc<AtomicBool>,
    quantum: usize,
    channels: usize,
) {
    // Disable Nagle's algorithm — we want low-latency chunked writes.
    let _ = stream.set_nodelay(true);
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    stream_to_writer(&mut stream, ring, shutdown, quantum, channels);
}

fn handle_unix_client(
    mut stream: UnixStream,
    ring: Arc<RingBuffer>,
    shutdown: Arc<AtomicBool>,
    quantum: usize,
    channels: usize,
) {
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    stream_to_writer(&mut stream, ring, shutdown, quantum, channels);
}

/// Core client loop: read from ring buffer, write framed PCM to the socket.
fn stream_to_writer(
    writer: &mut dyn Write,
    ring: Arc<RingBuffer>,
    shutdown: Arc<AtomicBool>,
    quantum: usize,
    channels: usize,
) {
    // Start reading from the current write position (don't replay old data).
    let mut read_pos = ring.write_pos();

    // Pre-allocate the output buffer: 4-byte header + quantum * channels * 4 bytes.
    let payload_bytes = quantum * channels * std::mem::size_of::<f32>();
    let mut out_buf = vec![0u8; 4 + payload_bytes];

    // Write the frame count header (constant for every chunk).
    let frame_count = quantum as u32;
    out_buf[0..4].copy_from_slice(&frame_count.to_le_bytes());

    // Target send interval matches the quantum period.
    // At 48kHz, 256 frames = 5.33ms.
    let send_interval = Duration::from_micros((quantum as u64 * 1_000_000) / 48000);

    while !shutdown.load(Ordering::Relaxed) {
        let wp = ring.write_pos();

        // Check if writer lapped us.
        if wp > read_pos + ring.capacity() {
            let skipped = wp - read_pos - ring.capacity();
            warn!("Client too slow, skipping {} frames", skipped);
            read_pos = wp;
        }

        // Check if enough data is available.
        if wp < read_pos + quantum {
            std::thread::sleep(send_interval / 2);
            continue;
        }

        // Read one quantum of frames from the ring buffer.
        match ring.read_interleaved(read_pos, quantum) {
            Some(samples) => {
                // Convert float32 samples to LE bytes in the output buffer.
                // Safety: reinterpreting &[f32] as &[u8] is safe on all platforms
                // because f32 has no alignment requirement stricter than u8.
                let sample_bytes = unsafe {
                    std::slice::from_raw_parts(
                        samples.as_ptr() as *const u8,
                        samples.len() * std::mem::size_of::<f32>(),
                    )
                };
                out_buf[4..].copy_from_slice(sample_bytes);

                if let Err(e) = writer.write_all(&out_buf) {
                    info!("Client disconnected: {}", e);
                    return;
                }

                read_pos += quantum;
            }
            None => {
                // Ring buffer returned None — either not enough data or lapped.
                // Reset to current write position.
                read_pos = ring.write_pos();
                std::thread::sleep(send_interval / 2);
            }
        }
    }
}

// ---- Level metering server (US060-3) ----

/// Run the level metering server. Sends JSON snapshots at 10 Hz to all
/// connected clients. Each snapshot is a single JSON line (newline-delimited).
pub fn run_levels_server(
    kind: ListenKind,
    addr: &str,
    tracker: Arc<LevelTracker>,
    shutdown: Arc<AtomicBool>,
) {
    match kind {
        ListenKind::Tcp => run_levels_tcp(addr, tracker, shutdown),
        ListenKind::Unix => run_levels_unix(addr, tracker, shutdown),
    }
}

fn run_levels_tcp(
    addr: &str,
    tracker: Arc<LevelTracker>,
    shutdown: Arc<AtomicBool>,
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

        // Take a snapshot and broadcast to all clients.
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

        // 10 Hz = 100ms interval.
        std::thread::sleep(Duration::from_millis(100));
    }

    info!("Levels TCP server shutting down");
}

fn run_levels_unix(
    path: &str,
    tracker: Arc<LevelTracker>,
    shutdown: Arc<AtomicBool>,
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

        std::thread::sleep(Duration::from_millis(100));
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

    s.push_str("]}\n");
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
        assert_eq!(json, "{\"channels\":0,\"peak\":[],\"rms\":[]}\n");
    }

    #[test]
    fn format_level_json_single_channel() {
        let mut snap = LevelSnapshot::default();
        snap.channels = 1;
        snap.peak_dbfs[0] = -3.1;
        snap.rms_dbfs[0] = -12.5;
        let json = format_level_json(&snap);
        assert_eq!(json, "{\"channels\":1,\"peak\":[-3.1],\"rms\":[-12.5]}\n");
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
        assert_eq!(json, "{\"channels\":2,\"peak\":[-0.5,-6.0],\"rms\":[-10.0,-20.0]}\n");
    }

    #[test]
    fn format_level_json_silence() {
        let mut snap = LevelSnapshot::default();
        snap.channels = 2;
        // Default values are -120.0
        let json = format_level_json(&snap);
        assert_eq!(json, "{\"channels\":2,\"peak\":[-120.0,-120.0],\"rms\":[-120.0,-120.0]}\n");
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
    }
}
