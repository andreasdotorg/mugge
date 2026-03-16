//! pcm-bridge — PipeWire audio bridge for the web UI.
//!
//! Two operating modes:
//!
//! **Monitor mode** (default, `--mode monitor`): Passive tap on a sink's
//! monitor ports. Reads from CamillaDSP's loopback-8ch-sink monitor ports
//! without participating in the RT audio graph. Cannot cause xruns.
//!
//! **Capture mode** (`--mode capture`): Reads from a PipeWire capture/source
//! node directly (e.g., the USBStreamer ALSA input carrying ADA8200 ADAT
//! channels). Uses `--node-name` to select the source.
//!
//! Multiple instances can run simultaneously (one per source, each on its
//! own TCP port).
//!
//! Wire format (matches existing web UI protocol):
//!   4-byte LE uint32 header (frame count) + interleaved float32 PCM
//!   Sent in chunks of `quantum` frames (default 256).

mod ring_buffer;
mod server;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use clap::{Parser, ValueEnum};
use log::{info, warn};

/// Operating mode for the PipeWire stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
enum Mode {
    /// Passive monitor-port tap on a sink node (default).
    Monitor,
    /// Direct capture from a PipeWire source/capture node.
    Capture,
}

/// PipeWire audio bridge for the web UI.
#[derive(Parser, Debug)]
#[command(name = "pcm-bridge", version)]
struct Args {
    /// Operating mode: "monitor" taps a sink's monitor ports (passive,
    /// no xruns). "capture" reads from a source node directly.
    #[arg(long, value_enum, default_value_t = Mode::Monitor)]
    mode: Mode,

    /// PipeWire target node name for monitor mode.
    /// Matched against node.name. Used with --mode monitor.
    #[arg(long, default_value = "loopback-8ch-sink")]
    target: String,

    /// PipeWire source node name for capture mode.
    /// Matched against node.name. Used with --mode capture.
    /// Example: alsa_input.usb-MiniDSP_USBStreamer-00.pro-input-0
    #[arg(long)]
    node_name: Option<String>,

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
        "pcm-bridge starting: mode={:?}, target={}, listen={:?}:{}, channels={}, rate={}, quantum={}",
        args.mode, args.target, listen_kind, listen_addr, args.channels, args.rate, args.quantum,
    );

    if args.mode == Mode::Capture {
        let node = args.node_name.as_deref().unwrap_or("(none)");
        info!("Capture mode: node-name={}", node);
    }

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
    // (verified against Pi PipeWire 1.4.10 headers in Nix store):
    const SPA_TYPE_Id: u32 = 3;       // enum spa_type: None=1, Bool=2, Id=3
    const SPA_TYPE_Int: u32 = 4;      // Int=4, Long=5, Float=6, Double=7
    const SPA_TYPE_Object: u32 = 15;  // Struct=14, Object=15
    const SPA_TYPE_OBJECT_Format: u32 = 0x40003; // START=0x40000, PropInfo, Props, Format
    const SPA_PARAM_EnumFormat: u32 = 3;
    const SPA_FORMAT_mediaType: u32 = 1;
    const SPA_FORMAT_mediaSubtype: u32 = 2;
    const SPA_FORMAT_AUDIO_format: u32 = 0x10001;    // START_Audio + 1
    const SPA_FORMAT_AUDIO_rate: u32 = 0x10003;      // +3 (flags at +2)
    const SPA_FORMAT_AUDIO_channels: u32 = 0x10004;  // +4
    const SPA_MEDIA_TYPE_audio: u32 = 1; // unknown=0, audio=1
    const SPA_MEDIA_SUBTYPE_raw: u32 = 1;
    const SPA_AUDIO_FORMAT_F32LE: u32 = 0x11A; // F32_LE in interleaved block

    let mut buf = Vec::with_capacity(136);

    // Helper: write a property with an Id value
    fn write_prop_id(buf: &mut Vec<u8>, key: u32, val: u32) {
        buf.extend_from_slice(&key.to_le_bytes());    // property key
        buf.extend_from_slice(&0u32.to_le_bytes());    // property flags
        buf.extend_from_slice(&4u32.to_le_bytes());    // pod size
        buf.extend_from_slice(&SPA_TYPE_Id.to_le_bytes()); // pod type = SPA_TYPE_Id
        buf.extend_from_slice(&val.to_le_bytes());     // value
        buf.extend_from_slice(&[0u8; 4]);              // pad to 8-byte align
    }

    // Helper: write a property with an Int value
    fn write_prop_int(buf: &mut Vec<u8>, key: u32, val: i32) {
        buf.extend_from_slice(&key.to_le_bytes());
        buf.extend_from_slice(&0u32.to_le_bytes());
        buf.extend_from_slice(&4u32.to_le_bytes());    // pod size
        buf.extend_from_slice(&SPA_TYPE_Int.to_le_bytes()); // pod type = SPA_TYPE_Int
        buf.extend_from_slice(&val.to_le_bytes());
        buf.extend_from_slice(&[0u8; 4]);              // pad to 8-byte align
    }

    // Object pod header (size filled in at end)
    let header_pos = buf.len();
    buf.extend_from_slice(&0u32.to_le_bytes());                        // size placeholder
    buf.extend_from_slice(&SPA_TYPE_Object.to_le_bytes());             // type = Object (15)
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

/// Build PipeWire stream properties based on the operating mode.
///
/// Returns owned Properties. The `channels` value is passed as an owned
/// string so it outlives the properties! macro scope.
fn build_stream_props(args: &Args) -> pipewire::properties::Properties {
    let channels_str = args.channels.to_string();

    match args.mode {
        Mode::Monitor => {
            // Monitor mode: passive tap on a sink's monitor ports.
            // stream.capture.sink tells PipeWire we want monitor ports.
            // target.object names the sink to capture from.
            pipewire::properties::properties! {
                "media.type" => "Audio",
                "media.category" => "Capture",
                "media.role" => "Monitor",
                "media.class" => "Stream/Input/Audio",
                "node.name" => "pcm-bridge",
                "node.description" => "PCM Bridge for Web UI",
                "node.always-process" => "true",
                "audio.channels" => &*channels_str,
                "stream.capture.sink" => "true",
                "target.object" => &*args.target,
            }
        }
        Mode::Capture => {
            // Capture mode: read from a PipeWire source/capture node.
            // No stream.capture.sink — we're reading from a source, not
            // tapping a sink's monitor. target.object points to the source.
            let target = args.node_name.as_deref().unwrap_or(&args.target);
            pipewire::properties::properties! {
                "media.type" => "Audio",
                "media.category" => "Capture",
                "media.role" => "Production",
                "media.class" => "Stream/Input/Audio",
                "node.name" => "pcm-bridge-capture",
                "node.description" => "PCM Bridge Capture",
                "node.always-process" => "true",
                "audio.channels" => &*channels_str,
                "target.object" => target,
            }
        }
    }
}

/// Run the PipeWire main loop, capturing audio from monitor or source ports.
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
    let props = build_stream_props(args);

    let stream = pipewire::stream::Stream::new(&core, "pcm-bridge", props)
        .expect("Failed to create PipeWire stream");

    // SPA format params specifying F32LE at the configured rate and channel
    // count. This drives PipeWire port creation — without it, PipeWire
    // defaults to 1 channel regardless of the audio.channels property.
    // The WirePlumber routing properties handle stream linking.
    let format_pod_bytes = build_audio_format(channels, args.rate);
    let format_pod = unsafe {
        &*(format_pod_bytes.as_ptr() as *const libspa::pod::Pod)
    };
    let mut params: [&libspa::pod::Pod; 1] = [format_pod];

    // Process callback: invoked by PipeWire each quantum. Copies interleaved
    // float32 data from the PW buffer into our ring buffer. This runs on the
    // PW data thread (RT_PROCESS flag). In monitor mode, the graph does NOT
    // wait for us (best-effort). In capture mode, we're a regular graph
    // participant but still run at SCHED_OTHER.
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

    info!("PipeWire stream connected ({:?} mode), entering main loop", args.mode);

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

#[cfg(test)]
mod tests {
    use super::*;

    // --- parse_listen tests ---

    #[test]
    fn parse_listen_tcp_prefix() {
        let (kind, addr) = parse_listen("tcp:127.0.0.1:9090");
        assert!(matches!(kind, ListenKind::Tcp));
        assert_eq!(addr, "127.0.0.1:9090");
    }

    #[test]
    fn parse_listen_unix_prefix() {
        let (kind, addr) = parse_listen("unix:/run/pcm-bridge.sock");
        assert!(matches!(kind, ListenKind::Unix));
        assert_eq!(addr, "/run/pcm-bridge.sock");
    }

    #[test]
    fn parse_listen_bare_defaults_to_tcp() {
        let (kind, addr) = parse_listen("0.0.0.0:8080");
        assert!(matches!(kind, ListenKind::Tcp));
        assert_eq!(addr, "0.0.0.0:8080");
    }

    // --- build_audio_format (SPA pod) tests ---

    #[test]
    fn build_audio_format_size_and_alignment() {
        let pod = build_audio_format(8, 48000);
        assert_eq!(pod.len() % 8, 0, "SPA pod must be 8-byte aligned");
        // 5 properties * 24 bytes each = 120, plus 16 bytes header = 136.
        assert_eq!(pod.len(), 136);
    }

    #[test]
    fn build_audio_format_header_type() {
        let pod = build_audio_format(2, 44100);
        // Bytes 4..8 are the pod type (SPA_TYPE_Object = 15).
        let pod_type = u32::from_le_bytes(pod[4..8].try_into().unwrap());
        assert_eq!(pod_type, 15, "pod header type must be SPA_TYPE_Object");
    }

    #[test]
    fn build_audio_format_body_size() {
        let pod = build_audio_format(3, 48000);
        // Bytes 0..4 are the body size (total - 8 byte pod header).
        let body_size = u32::from_le_bytes(pod[0..4].try_into().unwrap());
        assert_eq!(body_size as usize, pod.len() - 8);
    }

    #[test]
    fn build_audio_format_channels_embedded() {
        let pod = build_audio_format(8, 48000);
        // channels property value at: 16 + 4*24 + 16 = 128.
        let ch_val = u32::from_le_bytes(pod[128..132].try_into().unwrap());
        assert_eq!(ch_val, 8);
    }

    #[test]
    fn build_audio_format_rate_embedded() {
        let pod = build_audio_format(2, 96000);
        // rate property value at: 16 + 3*24 + 16 = 104.
        let rate_val = i32::from_le_bytes(pod[104..108].try_into().unwrap());
        assert_eq!(rate_val, 96000);
    }

    // --- CLI argument parsing tests ---

    fn parse_args(args: &[&str]) -> Result<Args, clap::Error> {
        Args::try_parse_from(args)
    }

    #[test]
    fn cli_default_mode_is_monitor() {
        let args = parse_args(&["pcm-bridge"]).unwrap();
        assert_eq!(args.mode, Mode::Monitor);
    }

    #[test]
    fn cli_mode_monitor_explicit() {
        let args = parse_args(&["pcm-bridge", "--mode", "monitor"]).unwrap();
        assert_eq!(args.mode, Mode::Monitor);
    }

    #[test]
    fn cli_mode_capture() {
        let args = parse_args(&["pcm-bridge", "--mode", "capture"]).unwrap();
        assert_eq!(args.mode, Mode::Capture);
    }

    #[test]
    fn cli_invalid_mode_rejected() {
        let result = parse_args(&["pcm-bridge", "--mode", "invalid"]);
        assert!(result.is_err());
    }

    #[test]
    fn cli_node_name_accepted() {
        let args = parse_args(&[
            "pcm-bridge",
            "--mode", "capture",
            "--node-name", "alsa_input.usb-MiniDSP_USBStreamer-00.pro-input-0",
        ]).unwrap();
        assert_eq!(
            args.node_name.as_deref(),
            Some("alsa_input.usb-MiniDSP_USBStreamer-00.pro-input-0"),
        );
    }

    #[test]
    fn cli_node_name_default_is_none() {
        let args = parse_args(&["pcm-bridge"]).unwrap();
        assert!(args.node_name.is_none());
    }

    #[test]
    fn cli_default_target() {
        let args = parse_args(&["pcm-bridge"]).unwrap();
        assert_eq!(args.target, "loopback-8ch-sink");
    }

    #[test]
    fn cli_default_channels() {
        let args = parse_args(&["pcm-bridge"]).unwrap();
        assert_eq!(args.channels, 3);
    }

    #[test]
    fn cli_custom_channels() {
        let args = parse_args(&["pcm-bridge", "--channels", "8"]).unwrap();
        assert_eq!(args.channels, 8);
    }

    #[test]
    fn cli_default_listen() {
        let args = parse_args(&["pcm-bridge"]).unwrap();
        assert_eq!(args.listen, "tcp:127.0.0.1:9090");
    }

    // --- PipeWire property generation tests ---
    //
    // pipewire::init() is safe to call without a running daemon — it only
    // initializes the library. Properties are pure key-value dicts that
    // don't need a daemon either. We use Once to ensure init is called
    // exactly once across parallel test threads.

    fn ensure_pw_init() {
        use std::sync::Once;
        static PW_INIT: Once = Once::new();
        PW_INIT.call_once(|| {
            pipewire::init();
        });
    }

    fn make_args(mode: Mode, target: &str, node_name: Option<&str>, channels: u32) -> Args {
        Args {
            mode,
            target: target.to_string(),
            node_name: node_name.map(String::from),
            listen: "tcp:127.0.0.1:9090".to_string(),
            channels,
            rate: 48000,
            quantum: 256,
        }
    }

    #[test]
    fn props_monitor_has_capture_sink() {
        ensure_pw_init();
        let args = make_args(Mode::Monitor, "loopback-8ch-sink", None, 3);
        let props = build_stream_props(&args);
        assert_eq!(props.get("stream.capture.sink"), Some("true"));
    }

    #[test]
    fn props_monitor_role_is_monitor() {
        ensure_pw_init();
        let args = make_args(Mode::Monitor, "loopback-8ch-sink", None, 3);
        let props = build_stream_props(&args);
        assert_eq!(props.get("media.role"), Some("Monitor"));
    }

    #[test]
    fn props_monitor_target_object() {
        ensure_pw_init();
        let args = make_args(Mode::Monitor, "my-custom-sink", None, 8);
        let props = build_stream_props(&args);
        assert_eq!(props.get("target.object"), Some("my-custom-sink"));
    }

    #[test]
    fn props_monitor_channels() {
        ensure_pw_init();
        let args = make_args(Mode::Monitor, "loopback-8ch-sink", None, 8);
        let props = build_stream_props(&args);
        assert_eq!(props.get("audio.channels"), Some("8"));
    }

    #[test]
    fn props_monitor_node_name() {
        ensure_pw_init();
        let args = make_args(Mode::Monitor, "loopback-8ch-sink", None, 3);
        let props = build_stream_props(&args);
        assert_eq!(props.get("node.name"), Some("pcm-bridge"));
    }

    #[test]
    fn props_capture_no_capture_sink() {
        ensure_pw_init();
        let args = make_args(Mode::Capture, "loopback-8ch-sink", Some("usb-input"), 8);
        let props = build_stream_props(&args);
        assert_eq!(
            props.get("stream.capture.sink"), None,
            "capture mode must NOT set stream.capture.sink",
        );
    }

    #[test]
    fn props_capture_role_is_production() {
        ensure_pw_init();
        let args = make_args(Mode::Capture, "loopback-8ch-sink", Some("usb-input"), 8);
        let props = build_stream_props(&args);
        assert_eq!(props.get("media.role"), Some("Production"));
    }

    #[test]
    fn props_capture_target_uses_node_name() {
        ensure_pw_init();
        let args = make_args(
            Mode::Capture,
            "loopback-8ch-sink",
            Some("alsa_input.usb-MiniDSP_USBStreamer-00.pro-input-0"),
            8,
        );
        let props = build_stream_props(&args);
        assert_eq!(
            props.get("target.object"),
            Some("alsa_input.usb-MiniDSP_USBStreamer-00.pro-input-0"),
        );
    }

    #[test]
    fn props_capture_target_falls_back_to_target() {
        ensure_pw_init();
        let args = make_args(Mode::Capture, "fallback-sink", None, 2);
        let props = build_stream_props(&args);
        assert_eq!(props.get("target.object"), Some("fallback-sink"));
    }

    #[test]
    fn props_capture_node_name_is_capture_variant() {
        ensure_pw_init();
        let args = make_args(Mode::Capture, "loopback-8ch-sink", Some("usb-input"), 8);
        let props = build_stream_props(&args);
        assert_eq!(props.get("node.name"), Some("pcm-bridge-capture"));
    }

    #[test]
    fn props_both_modes_have_media_class() {
        ensure_pw_init();
        let monitor_args = make_args(Mode::Monitor, "sink", None, 3);
        let capture_args = make_args(Mode::Capture, "sink", Some("src"), 8);
        let monitor_props = build_stream_props(&monitor_args);
        let capture_props = build_stream_props(&capture_args);
        assert_eq!(monitor_props.get("media.class"), Some("Stream/Input/Audio"));
        assert_eq!(capture_props.get("media.class"), Some("Stream/Input/Audio"));
    }

    #[test]
    fn props_both_modes_always_process() {
        ensure_pw_init();
        let monitor_args = make_args(Mode::Monitor, "sink", None, 3);
        let capture_args = make_args(Mode::Capture, "sink", Some("src"), 8);
        let monitor_props = build_stream_props(&monitor_args);
        let capture_props = build_stream_props(&capture_args);
        assert_eq!(monitor_props.get("node.always-process"), Some("true"));
        assert_eq!(capture_props.get("node.always-process"), Some("true"));
    }
}
