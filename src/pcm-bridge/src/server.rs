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

    // F-081: Heartbeat frame for idle-path client pruning.
    // A valid v2 frame with frame_count=0 and no PCM payload (24 bytes).
    // Clients handle this gracefully (zero frames = no FFT processing).
    let heartbeat: [u8; 24] = {
        let mut hb = [0u8; 24];
        hb[0] = 2; // version
        // bytes 1..24 are zero: pad=0, frame_count=0, graph_pos=0, graph_nsec=0
        hb
    };

    // F-081: Counter for idle ticks (no data flowing). At 200ms per tick,
    // 25 ticks = ~5 seconds between heartbeat prunes.
    let mut idle_ticks: u32 = 0;
    const IDLE_PRUNE_INTERVAL: u32 = 25;

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
            idle_ticks += 1;

            // F-081: Prune dead clients on idle path by sending a heartbeat
            // frame. Dead sockets return BrokenPipe/ConnectionReset on write.
            if idle_ticks >= IDLE_PRUNE_INTERVAL && !clients.is_empty() {
                let before = clients.len();
                clients.retain_mut(|client| {
                    match client.stream.write_all(&heartbeat) {
                        Ok(()) => true,
                        Err(_) => {
                            info!("Client disconnected (idle heartbeat prune)");
                            false
                        }
                    }
                });
                let pruned = before - clients.len();
                if pruned > 0 {
                    info!("F-081: pruned {} dead client(s) during idle", pruned);
                }
                idle_ticks = 0;
            }

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
        // F-081: Data is flowing — reset idle counter.
        idle_ticks = 0;

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
                // F-081: Also prune dead clients via heartbeat (same leak vector).
                let ring_wp = ring.write_pos();
                clients.retain_mut(|client| {
                    client.read_pos = ring_wp;
                    match client.stream.write_all(&heartbeat) {
                        Ok(()) => true,
                        Err(_) => {
                            info!("Client disconnected (ring-None prune)");
                            false
                        }
                    }
                });
                notifier.wait(wait_timeout);
            }
        }
    }
}

