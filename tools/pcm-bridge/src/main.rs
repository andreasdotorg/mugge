//! pcm-bridge — Passive PipeWire monitor-port PCM bridge.
//!
//! Replaces the broken JACK-based PcmStreamCollector in the web UI.
//! Reads from CamillaDSP monitor ports (passive taps that do NOT participate
//! in the RT audio graph) and serves interleaved float32 PCM over a TCP
//! socket or Unix socket.
//!
//! Key property: this binary runs at SCHED_OTHER and can NEVER cause xruns
//! in the PipeWire RT graph, because monitor ports are best-effort passive
//! taps — the graph does not wait for us.
//!
//! Wire format (matches existing web UI protocol):
//!   4-byte LE uint32 header (frame count) + interleaved float32 PCM
//!   Sent in chunks of `quantum` frames (default 256).

mod ring_buffer;
mod server;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use clap::Parser;
use log::{info, warn};

/// Passive PipeWire monitor-port PCM bridge for the web UI.
#[derive(Parser, Debug)]
#[command(name = "pcm-bridge", version)]
struct Args {
    /// PipeWire target node name to capture from.
    /// This is matched against the node.name property in PipeWire.
    #[arg(long, default_value = "CamillaDSP")]
    target: String,

    /// Listen address. Use "tcp:HOST:PORT" for TCP or "unix:PATH" for Unix socket.
    #[arg(long, default_value = "tcp:127.0.0.1:9090")]
    listen: String,

    /// Number of audio channels to capture.
    #[arg(long, default_value_t = 3)]
    channels: u32,

    /// Sample rate in Hz.
    #[arg(long, default_value_t = 48000)]
    rate: u32,

    /// Frames per quantum (chunk size sent to clients).
    #[arg(long, default_value_t = 256)]
    quantum: u32,
}

/// Parse listen address into (kind, address) tuple.
fn parse_listen(s: &str) -> (ListenKind, String) {
    if let Some(addr) = s.strip_prefix("tcp:") {
        (ListenKind::Tcp, addr.to_string())
    } else if let Some(path) = s.strip_prefix("unix:") {
        (ListenKind::Unix, path.to_string())
    } else {
        // Default to TCP if no prefix
        (ListenKind::Tcp, s.to_string())
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) enum ListenKind {
    Tcp,
    Unix,
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let args = Args::parse();
    let (listen_kind, listen_addr) = parse_listen(&args.listen);

    info!(
        "pcm-bridge starting: target={}, listen={:?}:{}, channels={}, rate={}, quantum={}",
        args.target, listen_kind, listen_addr, args.channels, args.rate, args.quantum,
    );

    // Shared shutdown flag — set by signal handlers, polled by PW timer and server.
    let shutdown = Arc::new(AtomicBool::new(false));

    // Register signal handlers for graceful shutdown.
    for sig in [signal_hook::consts::SIGTERM, signal_hook::consts::SIGINT] {
        if let Err(e) = signal_hook::flag::register(sig, shutdown.clone()) {
            warn!("Failed to register signal handler for {}: {}", sig, e);
        }
    }

    // Ring buffer shared between PipeWire process callback and the TCP server.
    // 8192 frames is ~170ms at 48kHz — enough to absorb scheduling jitter
    // without excessive memory use.
    let ring = Arc::new(ring_buffer::RingBuffer::new(8192, args.channels as usize));

    // Spawn the socket server thread.
    let server_ring = ring.clone();
    let server_shutdown = shutdown.clone();
    let quantum = args.quantum as usize;
    let channels = args.channels as usize;
    let server_thread = std::thread::Builder::new()
        .name("pcm-server".into())
        .spawn(move || {
            server::run_server(
                listen_kind,
                &listen_addr,
                server_ring,
                server_shutdown,
                quantum,
                channels,
            );
        })
        .expect("Failed to spawn server thread");

    // Run PipeWire main loop on the main thread.
    run_pipewire(&args, ring.clone(), shutdown.clone());

    info!("PipeWire loop exited, waiting for server thread...");
    let _ = server_thread.join();
    info!("pcm-bridge shutdown complete");
}

/// Run the PipeWire main loop, capturing audio from monitor ports.
fn run_pipewire(args: &Args, ring: Arc<ring_buffer::RingBuffer>, shutdown: Arc<AtomicBool>) {
    pipewire::init();

    let mainloop = pipewire::main_loop::MainLoopBox::new(None)
        .expect("Failed to create PipeWire main loop");
    let context = pipewire::context::ContextBox::new(mainloop.loop_(), None)
        .expect("Failed to create PipeWire context");
    let core = context
        .connect(None)
        .expect("Failed to connect to PipeWire daemon");

    let channels = args.channels;

    // Stream properties: capture from CamillaDSP's monitor ports.
    //
    // STREAM_CAPTURE_SINK = "true" tells PipeWire we want to capture
    // the output of a sink (i.e., monitor ports). TARGET_OBJECT names
    // the node to capture from.
    let props = pipewire::properties::properties! {
        *pipewire::keys::MEDIA_TYPE => "Audio",
        *pipewire::keys::MEDIA_CATEGORY => "Capture",
        *pipewire::keys::MEDIA_ROLE => "Monitor",
        *pipewire::keys::NODE_NAME => "pcm-bridge",
        *pipewire::keys::NODE_DESCRIPTION => "PCM Bridge for Web UI",
        *pipewire::keys::STREAM_CAPTURE_SINK => "true",
        *pipewire::keys::TARGET_OBJECT => &*args.target,
    };

    let stream = pipewire::stream::StreamBox::new(&core, "pcm-bridge", props)
        .expect("Failed to create PipeWire stream");

    // Build audio format pod: interleaved F32LE at the configured rate/channels.
    let mut audio_info_raw = libspa::param::audio::AudioInfoRaw::new();
    audio_info_raw.set_format(libspa::param::audio::AudioFormat::F32LE);
    audio_info_raw.set_rate(args.rate);
    audio_info_raw.set_channels(channels);

    let values: Vec<u8> = libspa::pod::serialize::PodSerializer::serialize(
        std::io::Cursor::new(Vec::new()),
        &libspa::pod::Value::Object(libspa::pod::Object {
            type_: libspa::utils::SpaTypes::ObjectParamFormat.as_raw(),
            id: libspa::param::ParamType::EnumFormat.as_raw(),
            properties: audio_info_raw.into(),
        }),
    )
    .expect("Failed to serialize audio format pod")
    .0
    .into_inner();

    let mut params = [libspa::pod::Pod::from_bytes(&values).expect("Bad pod bytes")];

    // Process callback: invoked by PipeWire each quantum. Copies interleaved
    // float32 data from the PW buffer into our ring buffer. This runs on the
    // PW data thread (RT_PROCESS flag), but since we're reading monitor ports
    // the graph does NOT wait for us — if we're slow, frames are simply dropped.
    //
    // Note: the callback receives &Stream (base type), which only provides raw
    // pointer access. We use the FFI pw_stream_dequeue_buffer directly because
    // the safe dequeue_buffer() wrapper is on StreamBox/StreamRc, not Stream.
    let ring_for_cb = ring;
    let channels_usize = channels as usize;

    let _listener = stream
        .add_local_listener()
        .process(move |stream: &pipewire::stream::Stream, _: &mut ()| {
            unsafe {
                let raw_buf = pipewire::sys::pw_stream_dequeue_buffer(stream.as_raw_ptr());
                if raw_buf.is_null() {
                    return;
                }

                let spa_buf = (*raw_buf).buffer;
                if spa_buf.is_null() || (*spa_buf).n_datas == 0 {
                    pipewire::sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
                    return;
                }

                let data = &*(*spa_buf).datas;
                let data_ptr = data.data;
                if data_ptr.is_null() {
                    pipewire::sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
                    return;
                }

                let chunk = data.chunk;
                if chunk.is_null() || (*chunk).size == 0 {
                    pipewire::sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
                    return;
                }

                let byte_count = (*chunk).size as usize;
                let bytes_per_frame = channels_usize * std::mem::size_of::<f32>();
                let n_frames = byte_count / bytes_per_frame;

                if n_frames > 0 {
                    let float_slice = std::slice::from_raw_parts(
                        data_ptr as *const f32,
                        n_frames * channels_usize,
                    );
                    ring_for_cb.write_interleaved(float_slice, channels_usize);
                }

                pipewire::sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
            }
        })
        .state_changed(|_stream, _data, old, new| {
            info!("PipeWire stream state: {:?} -> {:?}", old, new);
        })
        .register()
        .expect("Failed to register stream listener");

    // Connect for capture with AUTOCONNECT + MAP_BUFFERS + RT_PROCESS.
    stream
        .connect(
            libspa::utils::Direction::Input,
            None,
            pipewire::stream::StreamFlags::AUTOCONNECT
                | pipewire::stream::StreamFlags::MAP_BUFFERS
                | pipewire::stream::StreamFlags::RT_PROCESS,
            &mut params,
        )
        .expect("Failed to connect PipeWire stream");

    info!("PipeWire stream connected, entering main loop");

    // Periodic timer polls the shutdown AtomicBool (set by signal_hook
    // in main()) and quits the PipeWire main loop when triggered.
    //
    // We use a raw pointer to call pw_main_loop_quit because the Rust
    // MainLoop type cannot be cloned or captured by reference in a
    // 'static closure. The pointer remains valid because the timer
    // source is dropped before mainloop goes out of scope.
    let mainloop_ptr = mainloop.as_raw_ptr();
    let _shutdown_timer = mainloop.loop_().add_timer({
        let shutdown = shutdown.clone();
        move |_expirations| {
            if shutdown.load(Ordering::Relaxed) {
                info!("Shutdown signal received, quitting PipeWire main loop");
                // Safety: mainloop_ptr is valid — timer is dropped before mainloop.
                unsafe {
                    pipewire::sys::pw_main_loop_quit(mainloop_ptr);
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

    mainloop.run();
    info!("PipeWire main loop exited");

    pipewire::deinit();
}
