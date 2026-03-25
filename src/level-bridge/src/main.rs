//! level-bridge — Always-on PipeWire level metering for the web UI (D-049).
//!
//! Lightweight service that taps PipeWire nodes and publishes per-channel
//! peak/RMS levels as JSON over TCP at ~30 Hz. Extracted from pcm-bridge
//! to separate always-on level metering from on-demand PCM streaming.
//!
//! Two operating modes:
//!
//! **Monitor mode** (default, `--mode monitor`): Taps a sink node's monitor
//! ports (e.g., the convolver output).
//!
//! **Capture mode** (`--mode capture`): Reads from a source/capture node
//! directly (e.g., the USBStreamer ALSA input).
//!
//! **Self-linking** (`--self-link`): Uses PipeWire stream properties
//! (`stream.capture.sink`, `target.object`) for automatic linking by
//! WirePlumber, removing the need for GraphManager management.
//!
//! **Level metering protocol:** JSON snapshots at ~30 Hz, newline-delimited.
//!   `{"channels":N,"peak":[-3.1,-4.2,...],"rms":[-12.5,-14.0,...],"pos":N,"nsec":N}\n`
//! Values are in dBFS, rounded to 1 decimal place. -120.0 means silence.
//!
//! **Audio backend:** Native PipeWire `pw_stream`. `node.passive = true`
//! ensures level-bridge never drives the graph scheduler.

pub(crate) mod levels {
    pub use audio_common::level_tracker::*;
}

use levels::GraphClock;
mod notifier;
mod server;

use notifier::Notifier;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use clap::{Parser, ValueEnum};
use log::{info, warn};

/// Operating mode for the audio stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
enum Mode {
    /// Passive monitor-port tap on a sink node (default).
    Monitor,
    /// Direct capture from a source/capture node.
    Capture,
}

/// PipeWire level metering bridge for the web UI (D-049).
#[derive(Parser, Debug)]
#[command(name = "level-bridge", version)]
struct Args {
    /// Operating mode: "monitor" taps a sink's monitor ports (passive,
    /// no xruns). "capture" reads from a source node directly.
    #[arg(long, value_enum, default_value_t = Mode::Monitor)]
    mode: Mode,

    /// Run under GraphManager supervision. Uses pi4audio- node naming
    /// convention so GM's ownership filter recognizes level-bridge links.
    /// When false (default), uses --self-link properties for WirePlumber
    /// auto-linking.
    #[arg(long, env = "PI4AUDIO_MANAGED")]
    managed: bool,

    /// Enable self-linking via PipeWire stream properties. Sets
    /// `stream.capture.sink = true` + `target.object` for monitor mode,
    /// or `target.object` for capture mode. WirePlumber creates the links
    /// automatically — no GraphManager management needed.
    #[arg(long)]
    self_link: bool,

    /// Target node name. In monitor mode, the sink node to tap. In capture
    /// mode, the source node to read from.
    #[arg(long, default_value = "pi4audio-convolver")]
    target: String,

    /// Listen address for level metering (JSON at ~30 Hz).
    /// Use "tcp:HOST:PORT" for TCP or "unix:PATH" for Unix socket.
    #[arg(long, default_value = "tcp:127.0.0.1:9100")]
    levels_listen: String,

    /// Number of audio channels to capture.
    #[arg(long, default_value_t = 4)]
    channels: u32,

    /// Sample rate in Hz.
    #[arg(long, default_value_t = 48000)]
    rate: u32,
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
    let (levels_kind, levels_addr) = parse_listen(&args.levels_listen);

    info!(
        "level-bridge starting: mode={:?}, managed={}, self_link={}, target={}, listen={:?}:{}, channels={}, rate={}",
        args.mode, args.managed, args.self_link, args.target, levels_kind, levels_addr, args.channels, args.rate,
    );

    if args.managed {
        info!("Managed mode: running under GraphManager supervision");
    }
    if args.self_link {
        info!("Self-link mode: PipeWire/WirePlumber auto-linking enabled");
    }

    // Shared shutdown flag — set by signal handlers, polled by server and audio backend.
    let shutdown = Arc::new(AtomicBool::new(false));

    // Register signal handlers for graceful shutdown.
    for sig in [signal_hook::consts::SIGTERM, signal_hook::consts::SIGINT] {
        if let Err(e) = signal_hook::flag::register(sig, shutdown.clone()) {
            warn!("Failed to register signal handler for {}: {}", sig, e);
        }
    }

    // Level tracker shared between audio process callback and the levels server.
    let level_tracker = Arc::new(levels::LevelTracker::new(args.channels as usize));

    // US-077 Phase 4: event notifier replaces independent poll timer.
    // The PW process callback signals this after processing; the levels
    // server thread waits on it instead of sleeping.
    let levels_notifier = Arc::new(Notifier::new());

    // Spawn the levels server thread.
    let tracker_for_server = level_tracker.clone();
    let shutdown_for_server = shutdown.clone();
    let notifier_for_server = levels_notifier.clone();
    let levels_thread = std::thread::Builder::new()
        .name("levels-server".into())
        .spawn(move || {
            server::run_levels_server(
                levels_kind,
                &levels_addr,
                tracker_for_server,
                shutdown_for_server,
                notifier_for_server,
            );
        })
        .expect("Failed to spawn levels server thread");

    // Run PipeWire audio backend on the main thread.
    info!("Using PipeWire native audio backend");
    run_pipewire(&args, level_tracker.clone(), shutdown.clone(), levels_notifier);

    info!("Audio loop exited, waiting for levels server thread...");
    let _ = levels_thread.join();
    info!("level-bridge shutdown complete");
}

// ---------------------------------------------------------------------------
// PipeWire native audio backend
// ---------------------------------------------------------------------------

use audio_common::audio_format::build_audio_format;

fn build_stream_props(args: &Args) -> pipewire::properties::Properties {
    let channels_str = args.channels.to_string();

    match args.mode {
        Mode::Monitor if args.managed => {
            pipewire::properties::properties! {
                "media.type" => "Audio",
                "media.category" => "Capture",
                "media.role" => "Monitor",
                "media.class" => "Stream/Input/Audio",
                "node.name" => "pi4audio-level-bridge",
                "node.description" => "Level Bridge for Web UI",
                "node.always-process" => "true",
                "node.passive" => "true",
                "audio.channels" => &*channels_str,
            }
        }
        Mode::Monitor if args.self_link => {
            pipewire::properties::properties! {
                "media.type" => "Audio",
                "media.category" => "Capture",
                "media.role" => "Monitor",
                "media.class" => "Stream/Input/Audio",
                "node.name" => "pi4audio-level-bridge",
                "node.description" => "Level Bridge for Web UI",
                "node.passive" => "true",
                "audio.channels" => &*channels_str,
                "stream.capture.sink" => "true",
                "target.object" => &*args.target,
            }
        }
        Mode::Monitor => {
            // Standalone without self-link: no auto-connect properties.
            // Requires external link management (GM or manual pw-link).
            pipewire::properties::properties! {
                "media.type" => "Audio",
                "media.category" => "Capture",
                "media.role" => "Monitor",
                "media.class" => "Stream/Input/Audio",
                "node.name" => "pi4audio-level-bridge",
                "node.description" => "Level Bridge for Web UI",
                "node.passive" => "true",
                "audio.channels" => &*channels_str,
            }
        }
        Mode::Capture => {
            pipewire::properties::properties! {
                "media.type" => "Audio",
                "media.category" => "Capture",
                "media.role" => "Production",
                "media.class" => "Stream/Input/Audio",
                "node.name" => "pi4audio-level-bridge-capture",
                "node.description" => "Level Bridge Capture",
                "node.passive" => "true",
                "audio.channels" => &*channels_str,
                "target.object" => &*args.target,
            }
        }
    }
}

fn run_pipewire(
    args: &Args,
    level_tracker: Arc<levels::LevelTracker>,
    shutdown: Arc<AtomicBool>,
    levels_notifier: Arc<Notifier>,
) {
    use std::time::Duration;

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

    let stream = pipewire::stream::Stream::new(&core, "level-bridge", props)
        .expect("Failed to create PipeWire stream");

    let format_pod_bytes = build_audio_format(channels, args.rate, &[]);
    let format_pod = unsafe {
        &*(format_pod_bytes.as_ptr() as *const libspa::pod::Pod)
    };
    let mut params: [&libspa::pod::Pod; 1] = [format_pod];

    let levels_for_cb = level_tracker;
    let levels_notify_cb = levels_notifier;
    let channels_usize = channels as usize;
    let process_count = Arc::new(std::sync::atomic::AtomicU64::new(0));
    let process_count_cb = process_count.clone();
    let clock_logged = Arc::new(AtomicBool::new(false));
    let clock_logged_cb = clock_logged.clone();

    let _listener = stream
        .add_local_listener()
        .process(move |stream: &pipewire::stream::StreamRef, _: &mut ()| {
            process_count_cb.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
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

                // Read PipeWire graph clock via pw_stream_get_time_n.
                let clock = {
                    let mut pw_time: std::mem::MaybeUninit<pipewire_sys::pw_time> =
                        std::mem::MaybeUninit::zeroed();
                    let ret = pipewire_sys::pw_stream_get_time_n(
                        stream.as_raw_ptr() as *mut _,
                        pw_time.as_mut_ptr(),
                        std::mem::size_of::<pipewire_sys::pw_time>(),
                    );
                    if ret == 0 {
                        let t = pw_time.assume_init();
                        GraphClock {
                            position: t.ticks,
                            nsec: if t.now >= 0 { t.now as u64 } else { 0 },
                        }
                    } else {
                        GraphClock::default()
                    }
                };

                // Log the first graph clock values at startup.
                if clock.position != 0
                    && !clock_logged_cb.load(Ordering::Relaxed)
                    && clock_logged_cb
                        .compare_exchange(false, true, Ordering::Relaxed, Ordering::Relaxed)
                        .is_ok()
                {
                    info!(
                        "First graph clock: position={}, nsec={}",
                        clock.position, clock.nsec
                    );
                }

                let byte_count = (*chunk).size as usize;
                let bytes_per_frame = channels_usize * std::mem::size_of::<f32>();
                let n_frames = byte_count / bytes_per_frame;

                if n_frames > 0 {
                    let float_slice = std::slice::from_raw_parts(
                        data_ptr as *const f32,
                        n_frames * channels_usize,
                    );
                    // Level-bridge only: no ring buffer write, just level tracking.
                    levels_for_cb.process(float_slice, channels_usize, clock);

                    // Wake levels server thread (RT-safe: atomic store + futex wake).
                    levels_notify_cb.notify();
                }

                pipewire_sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
            }
        })
        .state_changed(|_stream, _data, old, new| {
            info!("PipeWire stream state: {:?} -> {:?}", old, new);
        })
        .register()
        .expect("Failed to register stream listener");

    // Stream flags: same logic as pcm-bridge (F-083).
    let mut flags = pipewire::stream::StreamFlags::MAP_BUFFERS;
    if args.managed {
        flags |= pipewire::stream::StreamFlags::RT_PROCESS;
    }
    if !args.managed {
        flags |= pipewire::stream::StreamFlags::AUTOCONNECT;
    }
    stream
        .connect(
            libspa::utils::Direction::Input,
            None,
            flags,
            &mut params,
        )
        .expect("Failed to connect PipeWire stream");

    info!("PipeWire stream connected ({:?} mode), entering main loop", args.mode);

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
    info!(
        "PipeWire main loop exited (process callback invoked {} times)",
        process_count.load(std::sync::atomic::Ordering::Relaxed)
    );

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
        let (kind, addr) = parse_listen("tcp:127.0.0.1:9100");
        assert!(matches!(kind, ListenKind::Tcp));
        assert_eq!(addr, "127.0.0.1:9100");
    }

    #[test]
    fn parse_listen_unix_prefix() {
        let (kind, addr) = parse_listen("unix:/run/level-bridge.sock");
        assert!(matches!(kind, ListenKind::Unix));
        assert_eq!(addr, "/run/level-bridge.sock");
    }

    #[test]
    fn parse_listen_bare_defaults_to_tcp() {
        let (kind, addr) = parse_listen("0.0.0.0:9100");
        assert!(matches!(kind, ListenKind::Tcp));
        assert_eq!(addr, "0.0.0.0:9100");
    }

    // --- CLI argument parsing tests ---

    fn parse_args(args: &[&str]) -> Result<Args, clap::Error> {
        Args::try_parse_from(args)
    }

    #[test]
    fn cli_default_mode_is_monitor() {
        let args = parse_args(&["level-bridge"]).unwrap();
        assert_eq!(args.mode, Mode::Monitor);
    }

    #[test]
    fn cli_mode_monitor_explicit() {
        let args = parse_args(&["level-bridge", "--mode", "monitor"]).unwrap();
        assert_eq!(args.mode, Mode::Monitor);
    }

    #[test]
    fn cli_mode_capture() {
        let args = parse_args(&["level-bridge", "--mode", "capture"]).unwrap();
        assert_eq!(args.mode, Mode::Capture);
    }

    #[test]
    fn cli_invalid_mode_rejected() {
        let result = parse_args(&["level-bridge", "--mode", "invalid"]);
        assert!(result.is_err());
    }

    #[test]
    fn cli_default_target() {
        let args = parse_args(&["level-bridge"]).unwrap();
        assert_eq!(args.target, "pi4audio-convolver");
    }

    #[test]
    fn cli_default_channels() {
        let args = parse_args(&["level-bridge"]).unwrap();
        assert_eq!(args.channels, 4);
    }

    #[test]
    fn cli_custom_channels() {
        let args = parse_args(&["level-bridge", "--channels", "8"]).unwrap();
        assert_eq!(args.channels, 8);
    }

    #[test]
    fn cli_default_levels_listen() {
        let args = parse_args(&["level-bridge"]).unwrap();
        assert_eq!(args.levels_listen, "tcp:127.0.0.1:9100");
    }

    #[test]
    fn cli_managed_default_is_false() {
        let args = parse_args(&["level-bridge"]).unwrap();
        assert!(!args.managed);
    }

    #[test]
    fn cli_managed_flag() {
        let args = parse_args(&["level-bridge", "--managed"]).unwrap();
        assert!(args.managed);
    }

    #[test]
    fn cli_self_link_default_is_false() {
        let args = parse_args(&["level-bridge"]).unwrap();
        assert!(!args.self_link);
    }

    #[test]
    fn cli_self_link_flag() {
        let args = parse_args(&["level-bridge", "--self-link"]).unwrap();
        assert!(args.self_link);
    }

    // --- PipeWire property tests ---

    mod pw_tests {
        use super::*;

        fn ensure_pw_init() {
            use std::sync::Once;
            static PW_INIT: Once = Once::new();
            PW_INIT.call_once(|| {
                pipewire::init();
            });
        }

        fn make_args(mode: Mode, target: &str, channels: u32, self_link: bool) -> Args {
            Args {
                mode,
                managed: false,
                self_link,
                target: target.to_string(),
                levels_listen: "tcp:127.0.0.1:9100".to_string(),
                channels,
                rate: 48000,
            }
        }

        fn make_managed_args(mode: Mode, target: &str, channels: u32) -> Args {
            Args {
                mode,
                managed: true,
                self_link: false,
                target: target.to_string(),
                levels_listen: "tcp:127.0.0.1:9100".to_string(),
                channels,
                rate: 48000,
            }
        }

        #[test]
        fn props_self_link_monitor_has_capture_sink() {
            ensure_pw_init();
            let args = make_args(Mode::Monitor, "pi4audio-convolver", 4, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("stream.capture.sink"), Some("true"));
        }

        #[test]
        fn props_self_link_monitor_has_target_object() {
            ensure_pw_init();
            let args = make_args(Mode::Monitor, "my-custom-sink", 4, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("target.object"), Some("my-custom-sink"));
        }

        #[test]
        fn props_no_self_link_monitor_no_capture_sink() {
            ensure_pw_init();
            let args = make_args(Mode::Monitor, "pi4audio-convolver", 4, false);
            let props = build_stream_props(&args);
            assert_eq!(props.get("stream.capture.sink"), None);
        }

        #[test]
        fn props_no_self_link_monitor_no_target_object() {
            ensure_pw_init();
            let args = make_args(Mode::Monitor, "pi4audio-convolver", 4, false);
            let props = build_stream_props(&args);
            assert_eq!(props.get("target.object"), None);
        }

        #[test]
        fn props_monitor_role_is_monitor() {
            ensure_pw_init();
            let args = make_args(Mode::Monitor, "pi4audio-convolver", 4, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("media.role"), Some("Monitor"));
        }

        #[test]
        fn props_monitor_node_name() {
            ensure_pw_init();
            let args = make_args(Mode::Monitor, "pi4audio-convolver", 4, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("node.name"), Some("pi4audio-level-bridge"));
        }

        #[test]
        fn props_monitor_channels() {
            ensure_pw_init();
            let args = make_args(Mode::Monitor, "pi4audio-convolver", 8, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("audio.channels"), Some("8"));
        }

        #[test]
        fn props_monitor_passive() {
            ensure_pw_init();
            let args = make_args(Mode::Monitor, "pi4audio-convolver", 4, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("node.passive"), Some("true"));
        }

        #[test]
        fn props_capture_no_capture_sink() {
            ensure_pw_init();
            let args = make_args(Mode::Capture, "alsa_input.usb", 8, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("stream.capture.sink"), None);
        }

        #[test]
        fn props_capture_role_is_production() {
            ensure_pw_init();
            let args = make_args(Mode::Capture, "alsa_input.usb", 8, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("media.role"), Some("Production"));
        }

        #[test]
        fn props_capture_target_object() {
            ensure_pw_init();
            let args = make_args(Mode::Capture, "alsa_input.usb-MiniDSP", 8, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("target.object"), Some("alsa_input.usb-MiniDSP"));
        }

        #[test]
        fn props_capture_node_name_is_capture_variant() {
            ensure_pw_init();
            let args = make_args(Mode::Capture, "alsa_input.usb", 8, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("node.name"), Some("pi4audio-level-bridge-capture"));
        }

        #[test]
        fn props_both_modes_have_media_class() {
            ensure_pw_init();
            let monitor_args = make_args(Mode::Monitor, "sink", 4, true);
            let capture_args = make_args(Mode::Capture, "src", 8, true);
            let monitor_props = build_stream_props(&monitor_args);
            let capture_props = build_stream_props(&capture_args);
            assert_eq!(monitor_props.get("media.class"), Some("Stream/Input/Audio"));
            assert_eq!(capture_props.get("media.class"), Some("Stream/Input/Audio"));
        }

        #[test]
        fn props_managed_monitor_no_capture_sink() {
            ensure_pw_init();
            let args = make_managed_args(Mode::Monitor, "pi4audio-convolver", 4);
            let props = build_stream_props(&args);
            assert_eq!(props.get("stream.capture.sink"), None);
        }

        #[test]
        fn props_managed_monitor_no_target_object() {
            ensure_pw_init();
            let args = make_managed_args(Mode::Monitor, "pi4audio-convolver", 4);
            let props = build_stream_props(&args);
            assert_eq!(props.get("target.object"), None);
        }

        #[test]
        fn props_managed_monitor_has_always_process() {
            ensure_pw_init();
            let args = make_managed_args(Mode::Monitor, "pi4audio-convolver", 4);
            let props = build_stream_props(&args);
            assert_eq!(props.get("node.always-process"), Some("true"));
        }

        #[test]
        fn props_managed_monitor_has_node_name() {
            ensure_pw_init();
            let args = make_managed_args(Mode::Monitor, "pi4audio-convolver", 4);
            let props = build_stream_props(&args);
            assert_eq!(props.get("node.name"), Some("pi4audio-level-bridge"));
        }

        #[test]
        fn props_non_managed_no_always_process() {
            ensure_pw_init();
            let args = make_args(Mode::Monitor, "sink", 4, true);
            let props = build_stream_props(&args);
            assert_eq!(props.get("node.always-process"), None);
        }
    }
}
