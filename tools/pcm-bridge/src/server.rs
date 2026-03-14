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
