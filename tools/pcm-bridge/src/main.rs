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
    #[arg(long, default_value = "loopback-8ch-sink")]
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

/// Build an SPA audio format pod for stream negotiation as raw bytes.
///
/// Port count in PipeWire is driven by the format params passed to
/// `stream.connect()`, not by the `audio.channels` node property.
/// Without format params, PipeWire defaults to 1 channel regardless
/// of the property value.
///
/// The pod is constructed directly in the SPA wire format because the
/// `spa_pod_builder_*` C functions are inline and not exposed by bindgen.
#[allow(non_upper_case_globals)]
fn build_audio_format(channels: u32, rate: u32) -> Vec<u8> {
    // SPA pod wire format (all little-endian, 8-byte aligned):
    //
    // Pod header:     size:u32, type:u32
    // Object body:    body_type:u32, body_id:u32
    // Property:       key:u32, flags:u32, value_pod(size:u32, type:u32, data...)
    //
    // Constants from spa/utils/type.h and spa/param/format.h
    // (names match C headers for easy cross-reference):
    const SPA_TYPE_Id: u32 = 4;
    const SPA_TYPE_Int: u32 = 6;
    const SPA_TYPE_OBJECT_Format: u32 = 0x40002;
    const SPA_PARAM_EnumFormat: u32 = 3;
    const SPA_FORMAT_mediaType: u32 = 1;
    const SPA_FORMAT_mediaSubtype: u32 = 2;
    const SPA_FORMAT_AUDIO_format: u32 = 0x10001;
    const SPA_FORMAT_AUDIO_rate: u32 = 0x10004;
    const SPA_FORMAT_AUDIO_channels: u32 = 0x10005;
    const SPA_MEDIA_TYPE_audio: u32 = 0;
    const SPA_MEDIA_SUBTYPE_raw: u32 = 1;
    const SPA_AUDIO_FORMAT_F32LE: u32 = 3;

    let mut buf = Vec::with_capacity(136);

    // Helper: write a property with an Id value
    fn write_prop_id(buf: &mut Vec<u8>, key: u32, val: u32) {
        buf.extend_from_slice(&key.to_le_bytes());    // property key
        buf.extend_from_slice(&0u32.to_le_bytes());    // property flags
        buf.extend_from_slice(&4u32.to_le_bytes());    // pod size
        buf.extend_from_slice(&4u32.to_le_bytes());    // pod type = SPA_TYPE_Id
        buf.extend_from_slice(&val.to_le_bytes());     // value
        buf.extend_from_slice(&[0u8; 4]);              // pad to 8-byte align
    }

    // Helper: write a property with an Int value
    fn write_prop_int(buf: &mut Vec<u8>, key: u32, val: i32) {
        buf.extend_from_slice(&key.to_le_bytes());
        buf.extend_from_slice(&0u32.to_le_bytes());
        buf.extend_from_slice(&4u32.to_le_bytes());    // pod size
        buf.extend_from_slice(&6u32.to_le_bytes());    // pod type = SPA_TYPE_Int
        buf.extend_from_slice(&val.to_le_bytes());
        buf.extend_from_slice(&[0u8; 4]);              // pad to 8-byte align
    }

    // Object pod header (size filled in at end)
    let header_pos = buf.len();
    buf.extend_from_slice(&0u32.to_le_bytes());                        // size placeholder
    buf.extend_from_slice(&SPA_TYPE_OBJECT_Format.to_le_bytes());      // type
    buf.extend_from_slice(&SPA_TYPE_OBJECT_Format.to_le_bytes());      // body type
    buf.extend_from_slice(&SPA_PARAM_EnumFormat.to_le_bytes());        // body id

    // Properties
    write_prop_id(&mut buf, SPA_FORMAT_mediaType, SPA_MEDIA_TYPE_audio);
    write_prop_id(&mut buf, SPA_FORMAT_mediaSubtype, SPA_MEDIA_SUBTYPE_raw);
    write_prop_id(&mut buf, SPA_FORMAT_AUDIO_format, SPA_AUDIO_FORMAT_F32LE);
    write_prop_int(&mut buf, SPA_FORMAT_AUDIO_rate, rate as i32);
    write_prop_int(&mut buf, SPA_FORMAT_AUDIO_channels, channels as i32);

    // Fill in object body size
    let body_size = (buf.len() - header_pos - 8) as u32;
    buf[header_pos..header_pos + 4].copy_from_slice(&body_size.to_le_bytes());

    buf
}

/// Run the PipeWire main loop, capturing audio from monitor ports.
fn run_pipewire(args: &Args, ring: Arc<ring_buffer::RingBuffer>, shutdown: Arc<AtomicBool>) {
    pipewire::init();

    let mainloop = pipewire::main_loop::MainLoop::new(None)
        .expect("Failed to create PipeWire main loop");
    let context = pipewire::context::Context::new(&mainloop)
        .expect("Failed to create PipeWire context");
    let core = context
        .connect(None)
        .expect("Failed to connect to PipeWire daemon");

    let channels = args.channels;
    let channels_str = channels.to_string();

    // Stream properties: capture from CamillaDSP's monitor ports.
    //
    // STREAM_CAPTURE_SINK = "true" tells PipeWire we want to capture
    // the output of a sink (i.e., monitor ports). TARGET_OBJECT names
    // the node to capture from.
    //
    // audio.channels is required for PipeWire to create the correct
    // number of input ports. Without it, PipeWire defaults to 1 channel
    // and WirePlumber cannot match against the 8-channel target sink.
    let props = pipewire::properties::properties! {
        "media.type" => "Audio",
        "media.category" => "Capture",
        "media.role" => "Monitor",
        "media.class" => "Stream/Input/Audio",
        "node.name" => "pcm-bridge",
        "node.description" => "PCM Bridge for Web UI",
        "node.always-process" => "true",
        "audio.channels" => &*channels_str,
        // Capture from a sink's monitor ports (passive tap).
        "stream.capture.sink" => "true",
        "target.object" => &*args.target,
    };

    let stream = pipewire::stream::Stream::new(&core, "pcm-bridge", props)
        .expect("Failed to create PipeWire stream");

    // SPA format params specifying F32LE at the configured rate and channel
    // count. This drives PipeWire port creation — without it, PipeWire
    // defaults to 1 channel regardless of the audio.channels property.
    // The WirePlumber routing properties above (media.class, node.always-process,
    // stream.capture.sink, target.object) handle stream linking.
    let format_pod_bytes = build_audio_format(channels, args.rate);
    let format_pod = unsafe {
        &*(format_pod_bytes.as_ptr() as *const libspa::pod::Pod)
    };
    let mut params: [&libspa::pod::Pod; 1] = [format_pod];

    // Process callback: invoked by PipeWire each quantum. Copies interleaved
    // float32 data from the PW buffer into our ring buffer. This runs on the
    // PW data thread (RT_PROCESS flag), but since we're reading monitor ports
    // the graph does NOT wait for us — if we're slow, frames are simply dropped.
    //
    // Note: the callback receives &StreamRef, which only provides raw
    // pointer access. We use the FFI pw_stream_dequeue_buffer directly because
    // the safe dequeue_buffer() wrapper is on StreamBox/StreamRc, not StreamRef.
    let ring_for_cb = ring;
    let channels_usize = channels as usize;

    let _listener = stream
        .add_local_listener()
        .process(move |stream: &pipewire::stream::StreamRef, _: &mut ()| {
            unsafe {
                let raw_buf = pipewire_sys::pw_stream_dequeue_buffer(stream.as_raw_ptr());
                if raw_buf.is_null() {
                    return;
                }

                let spa_buf = (*raw_buf).buffer;
                if spa_buf.is_null() || (*spa_buf).n_datas == 0 {
                    pipewire_sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
                    return;
                }

                let data = &*(*spa_buf).datas;
                let data_ptr = data.data;
                if data_ptr.is_null() {
                    pipewire_sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
                    return;
                }

                let chunk = data.chunk;
                if chunk.is_null() || (*chunk).size == 0 {
                    pipewire_sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
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

                pipewire_sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
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
    // We capture the raw pointer to call pw_main_loop_quit from the
    // timer callback, since MainLoop is not Clone.
    let mainloop_ptr = mainloop.as_raw_ptr();
    let _shutdown_timer = mainloop.loop_().add_timer({
        let shutdown = shutdown.clone();
        move |_expirations| {
            if shutdown.load(Ordering::Relaxed) {
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

    mainloop.run();
    info!("PipeWire main loop exited");

    // Drop PipeWire objects in reverse order BEFORE calling deinit().
    // Calling deinit() while stream/context/core are alive causes SIGSEGV
    // because their Drop impls reference already-freed PipeWire internals.
    drop(_shutdown_timer);
    drop(_listener);
    drop(stream);
    drop(core);
    drop(context);
    drop(mainloop);

    unsafe { pipewire::deinit(); }
}
