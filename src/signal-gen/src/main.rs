//! pi4audio-signal-gen -- RT signal generator for measurement and test tooling.
//!
//! Maintains an always-on PipeWire playback stream. In managed mode (D-040),
//! GraphManager controls all link topology. Signal content is controlled via
//! a JSON-over-TCP RPC interface without ever closing or reopening the audio
//! stream.
//!
//! Signal-gen is play-only (D-040 / US-067). Capture is handled by pw-record
//! in the Python measurement session (Track A).
//!
//! This eliminates TK-224's root cause: WirePlumber routing races caused by
//! per-burst stream opening in the Python measurement pipeline.
//!
//! ## Thread model
//!
//! 1. **Main thread** — PipeWire main loop (event dispatch, shutdown timer)
//! 2. **RPC thread** — TCP listener, JSON parsing, command queue push, state polling
//! 3. **PW data thread** (PW-managed, SCHED_FIFO) — process callback invoked each quantum

mod command;
mod file_playback;
mod generator;
mod ramp;
mod registry;
mod rpc;
mod safety;

use std::io::{BufRead, BufReader, Write as IoWrite};
use std::net::{TcpListener, TcpStream};
use std::process;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use audio_common::audio_format::build_audio_format;
use clap::Parser;
use log::{error, info, warn};

use command::{
    Command, CommandKind, CommandQueue, PlayState, SignalType, StateQueue, StateSnapshot,
};
use file_playback::FilePlaybackGenerator;
use generator::{
    PinkNoiseGenerator, SignalGenerator, SilenceGenerator, SineGenerator, SweepGenerator,
    WhiteNoiseGenerator,
};
use ramp::FadeRamp;
use registry::DeviceEventQueue;
use rpc::MAX_LINE_LENGTH;
use safety::SafetyLimits;

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

/// RT signal generator for Pi audio workstation measurement and test tooling.
#[derive(Parser, Debug)]
#[command(name = "pi4audio-signal-gen", version)]
struct Args {
    /// PipeWire playback target node name (unused in --managed mode).
    #[arg(long, default_value = "")]
    target: String,

    /// Number of output channels (F-097: default 1 for mono measurement).
    #[arg(long, default_value_t = 1)]
    channels: u32,

    /// Sample rate in Hz.
    #[arg(long, default_value_t = 48000)]
    rate: u32,

    /// RPC listen address (tcp:HOST:PORT).
    #[arg(long, default_value = "tcp:127.0.0.1:4001")]
    listen: String,

    /// Hard output level cap in dBFS (immutable after startup).
    #[arg(long, default_value_t = -20.0, allow_hyphen_values = true)]
    max_level_dbfs: f64,

    /// Fade ramp duration in milliseconds.
    #[arg(long, default_value_t = 20)]
    ramp_ms: u32,

    /// Device name pattern to watch for hot-plug events.
    #[arg(long, default_value = "UMIK-1")]
    device_watch: String,

    /// Run in managed mode (GraphManager creates links).
    /// When set, AUTOCONNECT and target.object are omitted so that
    /// pi4audio-graph-manager controls all link topology.
    #[arg(long, env = "PI4AUDIO_MANAGED")]
    managed: bool,
}

/// Validate safety-critical arguments before entering the main loop.
///
/// SEC-D037-01: Reject non-loopback listen addresses.
/// SEC-D037-04: Reject max_level_dbfs outside [-120.0, -0.5].
fn validate_args(args: &Args) -> Result<(), String> {
    // SEC-D037-01: Loopback-only binding
    let addr = args.listen.strip_prefix("tcp:").unwrap_or(&args.listen);
    let host = addr.rsplit_once(':').map(|(h, _)| h).unwrap_or(addr);
    match host {
        "127.0.0.1" | "::1" | "localhost" => {}
        _ => {
            return Err(format!(
                "Error: --listen address must be loopback \
                 (127.0.0.1, ::1, or localhost). \
                 Binding to non-loopback addresses is prohibited. Got: {host}"
            ))
        }
    }

    // SEC-D037-04: Level cap ceiling
    if args.max_level_dbfs > -0.5 {
        return Err(format!(
            "Error: --max-level-dbfs must be <= -0.5 \
             (D-009 absolute ceiling). Got: {}",
            args.max_level_dbfs
        ));
    }
    if args.max_level_dbfs < -120.0 {
        return Err(format!(
            "Error: --max-level-dbfs must be >= -120.0. Got: {}",
            args.max_level_dbfs
        ));
    }

    Ok(())
}

/// Parse the listen address into (host, port).
fn parse_listen_addr(listen: &str) -> (&str, &str) {
    let addr = listen.strip_prefix("tcp:").unwrap_or(listen);
    addr.rsplit_once(':').unwrap_or((addr, "4001"))
}

// ---------------------------------------------------------------------------
// Process state — shared between PW callback and command application
// ---------------------------------------------------------------------------

/// Shared slot for pre-decoded file playback samples.
///
/// The RPC thread writes decoded audio into this slot; the RT thread
/// reads it (briefly locking the Mutex) only when switching to file mode.
pub(crate) type SharedFileSamples = Arc<Mutex<Arc<Vec<f32>>>>;

/// All mutable state for the PW process callback.
///
/// Lives on the PW data thread. Commands arrive via the SPSC queue.
/// State snapshots are pushed back to the RPC thread via the feedback queue.
pub(crate) struct ProcessState {
    // Audio parameters
    channels: usize,
    rate: f64,

    // Current generator (trait object, swapped on Play/SetSignal)
    generator: Box<dyn SignalGenerator>,

    // Generator instances kept alive for reuse (avoids re-init on switch)
    gen_silence: SilenceGenerator,
    gen_sine: SineGenerator,
    gen_white: WhiteNoiseGenerator,
    gen_pink: PinkNoiseGenerator,
    // Sweep is always freshly created (different params each time)

    // Shared file samples slot (RPC thread writes, RT thread reads on switch)
    file_samples: SharedFileSamples,

    // Playback state
    play_state: PlayState,
    active_signal: SignalType,
    active_channels: u8,
    current_level_dbfs: f32,
    current_level_linear: f32,
    current_freq: f32,

    // Fade ramp
    fade: FadeRamp,
    ramp_samples: u32,

    // Safety
    safety: SafetyLimits,

    // Burst tracking
    burst_remaining: Option<u64>,
    pending_stop: bool,

    // Counters
    samples_generated: u64,
    elapsed_samples: u64,
    duration_samples: u64,
}

impl ProcessState {
    fn new(
        channels: usize,
        rate: u32,
        max_level_dbfs: f64,
        ramp_ms: u32,
        file_samples: SharedFileSamples,
    ) -> Self {
        let ramp_samples = FadeRamp::ms_to_samples(ramp_ms, rate);
        let safety = SafetyLimits::from_dbfs(max_level_dbfs);

        Self {
            channels,
            rate: rate as f64,
            generator: Box::new(SilenceGenerator),
            gen_silence: SilenceGenerator,
            gen_sine: SineGenerator::new(1000.0, rate as f64),
            gen_white: WhiteNoiseGenerator::new(42),
            gen_pink: PinkNoiseGenerator::new(42),
            file_samples,
            play_state: PlayState::Stopped,
            active_signal: SignalType::Silence,
            active_channels: 0,
            current_level_dbfs: -120.0,
            current_level_linear: 0.0,
            current_freq: 1000.0,
            fade: FadeRamp::new(0.0, 0.0, 0), // no-op initially
            ramp_samples,
            safety,
            burst_remaining: None,
            pending_stop: false,
            samples_generated: 0,
            elapsed_samples: 0,
            duration_samples: 0,
        }
    }

    /// Apply a single command to the process state.
    fn apply_command(&mut self, cmd: Command) {
        match cmd.kind {
            CommandKind::Play {
                signal,
                channels,
                level_dbfs,
                frequency,
                duration_secs,
                sweep_end_hz,
            } => {
                self.active_signal = signal;
                self.active_channels = channels;
                self.current_level_dbfs = level_dbfs;
                self.current_level_linear = dbfs_to_linear(level_dbfs);
                self.current_freq = frequency;
                self.switch_generator(signal, frequency, duration_secs, sweep_end_hz);
                self.fade = FadeRamp::new(0.0, 1.0, self.ramp_samples); // fade in
                self.play_state = PlayState::Playing;
                self.elapsed_samples = 0;
                self.duration_samples = duration_secs
                    .map(|d| (d as f64 * self.rate) as u64)
                    .unwrap_or(0);
                self.burst_remaining =
                    duration_secs.map(|d| (d as f64 * self.rate) as u64);
                self.pending_stop = false;
            }
            CommandKind::Stop => {
                if self.play_state != PlayState::Stopped {
                    self.fade = FadeRamp::new(1.0, 0.0, self.ramp_samples);
                    self.pending_stop = true;
                }
            }
            CommandKind::SetLevel { level_dbfs } => {
                let new_linear = dbfs_to_linear(level_dbfs);
                self.fade = FadeRamp::new(
                    self.current_level_linear / new_linear.max(1e-10),
                    1.0,
                    self.ramp_samples,
                );
                self.current_level_dbfs = level_dbfs;
                self.current_level_linear = new_linear;
            }
            CommandKind::SetChannel { channels } => {
                self.active_channels = channels;
            }
            CommandKind::SetSignal { signal, frequency } => {
                self.active_signal = signal;
                if frequency > 0.0 {
                    self.current_freq = frequency;
                }
                self.switch_generator(signal, self.current_freq, None, 20000.0);
            }
            CommandKind::SetFrequency { frequency } => {
                self.current_freq = frequency;
                self.gen_sine.set_frequency(frequency as f64, self.rate);
            }
        }
    }

    /// Switch the active generator to the requested signal type.
    fn switch_generator(
        &mut self,
        signal: SignalType,
        frequency: f32,
        duration_secs: Option<f32>,
        sweep_end_hz: f32,
    ) {
        match signal {
            SignalType::Silence => {
                self.generator = Box::new(SilenceGenerator);
            }
            SignalType::Sine => {
                self.gen_sine.set_frequency(frequency as f64, self.rate);
                self.generator =
                    Box::new(SineGenerator::new(frequency as f64, self.rate));
            }
            SignalType::White => {
                self.generator = Box::new(WhiteNoiseGenerator::new(
                    self.samples_generated,
                ));
            }
            SignalType::Pink => {
                self.generator = Box::new(PinkNoiseGenerator::new(
                    self.samples_generated,
                ));
            }
            SignalType::Sweep => {
                let dur = duration_secs.unwrap_or(1.0) as f64;
                self.generator = Box::new(SweepGenerator::new(
                    frequency as f64,
                    sweep_end_hz as f64,
                    dur,
                    self.rate,
                ));
            }
            SignalType::File => {
                let samples = match self.file_samples.lock() {
                    Ok(guard) => Arc::clone(&*guard),
                    Err(poisoned) => Arc::clone(&*poisoned.into_inner()),
                };
                self.generator = Box::new(FilePlaybackGenerator::new(samples));
            }
        }
    }

    /// Create a state snapshot for the feedback queue.
    fn snapshot(&self) -> StateSnapshot {
        StateSnapshot {
            state: self.play_state,
            signal: self.active_signal,
            channels: self.active_channels,
            level_dbfs: self.current_level_dbfs,
            frequency: self.current_freq,
            elapsed_secs: self.elapsed_samples as f32 / self.rate as f32,
            duration_secs: self.duration_samples as f32 / self.rate as f32,
            samples_generated: self.samples_generated,
        }
    }

    /// Run the playback process callback logic on a buffer.
    ///
    /// This is the core audio processing function, called from the PW
    /// playback process callback. Factored out so the non-PW parts are testable.
    fn process(
        &mut self,
        output: &mut [f32],
        n_frames: usize,
        cmd_queue: &CommandQueue,
        state_queue: &StateQueue,
    ) {
        // 1. Drain all pending commands (AD-D037-6: multi-command-per-quantum).
        while let Some(cmd) = cmd_queue.pop() {
            self.apply_command(cmd);
        }

        // Handle pending stop from a PREVIOUS quantum (fade already finished).
        if self.pending_stop && self.fade.is_finished() {
            self.play_state = PlayState::Stopped;
            self.active_signal = SignalType::Silence;
            self.generator = Box::new(SilenceGenerator);
            self.burst_remaining = None;
            self.pending_stop = false;
        }

        // 2. Generate samples into the buffer.
        // F-140: In mono mode (1 output channel), any non-zero bitmask means
        // "play on the single channel". The UI sends channel numbers 1-8 which
        // map to bitmask bits 0-7, but only bit 0 drives ch=0 in the generator.
        let effective_channels = if self.channels == 1 && self.active_channels != 0 {
            0x01
        } else {
            self.active_channels
        };
        self.generator.generate(
            output,
            n_frames,
            self.channels,
            effective_channels,
            self.current_level_linear,
        );

        // 3. Apply fade ramp (per-sample multiply).
        if self.fade.is_active() {
            for frame in 0..n_frames {
                let gain = self.fade.next();
                for ch in 0..self.channels {
                    output[frame * self.channels + ch] *= gain;
                }
            }
        }

        // 4. Apply hard safety clip (per-sample, Section 6).
        self.safety.hard_clip(output);

        // 5. Handle burst duration (auto-stop after N samples).
        let mut burst_expired = false;
        if let Some(ref mut burst) = self.burst_remaining {
            *burst = burst.saturating_sub(n_frames as u64);
            if *burst == 0 {
                burst_expired = true;
            }
        }
        if burst_expired {
            self.fade = FadeRamp::new(1.0, 0.0, self.ramp_samples);
            self.pending_stop = true;
            self.burst_remaining = None;
        }

        // 6. Check if sweep finished (generator-level auto-stop).
        if self.generator.is_finished() && self.play_state == PlayState::Playing {
            self.fade = FadeRamp::new(1.0, 0.0, self.ramp_samples);
            self.pending_stop = true;
        }

        // 6b. Check if pending_stop fade completed THIS quantum.
        if self.pending_stop && self.fade.is_finished() {
            self.play_state = PlayState::Stopped;
            self.active_signal = SignalType::Silence;
            self.generator = Box::new(SilenceGenerator);
            self.burst_remaining = None;
            self.pending_stop = false;
        }

        // Update counters.
        self.samples_generated += n_frames as u64;
        self.elapsed_samples += n_frames as u64;

        // 7. Push state snapshot (at most once per callback).
        let _ = state_queue.push(self.snapshot());
    }
}

/// Convert dBFS to linear amplitude.
fn dbfs_to_linear(dbfs: f32) -> f32 {
    10.0f32.powf(dbfs / 20.0)
}

// ---------------------------------------------------------------------------
// PipeWire playback stream
// ---------------------------------------------------------------------------

use audio_common::audio_format::spa_channel;

/// Run the PipeWire main loop with the playback stream.
///
/// This function blocks until the shutdown flag is set.
fn run_pipewire(
    args: &Args,
    cmd_queue: Arc<CommandQueue>,
    state_queue: Arc<StateQueue>,
    event_queue: Arc<DeviceEventQueue>,
    shutdown: Arc<AtomicBool>,
    file_samples: SharedFileSamples,
) {
    pipewire::init();

    let mainloop = pipewire::main_loop::MainLoop::new(None)
        .expect("Failed to create PipeWire main loop");
    let context = pipewire::context::Context::new(&mainloop)
        .expect("Failed to create PipeWire context");
    let core = context
        .connect(None)
        .expect("Failed to connect to PipeWire daemon");

    let channels_str = args.channels.to_string();

    // -----------------------------------------------------------------------
    // Playback stream (Section 3.1)
    // -----------------------------------------------------------------------

    let rate_str = args.rate.to_string();
    let latency_str = format!("{}/{}", args.rate / 10, args.rate); // 100ms default latency
    let position_str: String = (0..args.channels)
        .map(|i| format!("AUX{}", i))
        .collect::<Vec<_>>()
        .join(",");
    let mut playback_props = pipewire::properties::properties! {
        "media.type" => "Audio",
        "media.category" => "Playback",
        "media.role" => "Production",
        "media.class" => "Stream/Output/Audio",
        "node.name" => "pi4audio-signal-gen",
        "node.description" => "RT Signal Generator",
        "audio.channels" => &*channels_str,
        "audio.position" => &*position_str,
        "node.rate" => &*format!("1/{rate_str}"),
        "node.latency" => &*latency_str,
    };
    if args.managed {
        playback_props.insert("node.always-process", "true");
        playback_props.insert("node.group", "pi4audio.usbstreamer");
    }
    if !args.managed && !args.target.is_empty() {
        playback_props.insert("target.object", &*args.target);
    }

    let playback_stream =
        pipewire::stream::Stream::new(&core, "pi4audio-signal-gen", playback_props)
            .expect("Failed to create PipeWire playback stream");

    // SPA format params: F32LE at configured rate, channel count, and
    // positions (AUX0..AUX{N-1}).
    let playback_positions: Vec<u32> = (0..args.channels)
        .map(|i| spa_channel::AUX0 + i)
        .collect();
    let playback_fmt_bytes = build_audio_format(
        args.channels, args.rate, &playback_positions,
    );
    let playback_fmt_pod = unsafe {
        &*(playback_fmt_bytes.as_ptr() as *const libspa::pod::Pod)
    };
    let mut playback_params: [&libspa::pod::Pod; 1] = [playback_fmt_pod];

    // Process callback state.
    let mut proc_state = ProcessState::new(
        args.channels as usize,
        args.rate,
        args.max_level_dbfs,
        args.ramp_ms,
        file_samples,
    );

    let cmd_q = cmd_queue;
    let state_q = state_queue;
    let channels = args.channels as usize;

    let _playback_stream_ptr = playback_stream.as_raw_ptr();

    // Register the playback process callback.
    let _playback_listener = playback_stream
        .add_local_listener()
        .process(move |stream: &pipewire::stream::StreamRef, _: &mut ()| {
            unsafe {
                let raw_buf =
                    pipewire_sys::pw_stream_dequeue_buffer(stream.as_raw_ptr());
                if raw_buf.is_null() {
                    return;
                }

                let spa_buf = (*raw_buf).buffer;
                if spa_buf.is_null() || (*spa_buf).n_datas == 0 {
                    pipewire_sys::pw_stream_queue_buffer(
                        stream.as_raw_ptr(),
                        raw_buf,
                    );
                    return;
                }

                let data = &*(*spa_buf).datas;
                let data_ptr = data.data;
                if data_ptr.is_null() {
                    pipewire_sys::pw_stream_queue_buffer(
                        stream.as_raw_ptr(),
                        raw_buf,
                    );
                    return;
                }

                let chunk = data.chunk;
                if chunk.is_null() {
                    pipewire_sys::pw_stream_queue_buffer(
                        stream.as_raw_ptr(),
                        raw_buf,
                    );
                    return;
                }

                let max_size = data.maxsize as usize;
                let bytes_per_frame = channels * std::mem::size_of::<f32>();
                let n_frames = max_size / bytes_per_frame;

                if n_frames > 0 {
                    let output = std::slice::from_raw_parts_mut(
                        data_ptr as *mut f32,
                        n_frames * channels,
                    );

                    proc_state.process(
                        output,
                        n_frames,
                        &cmd_q,
                        &state_q,
                    );

                    // Tell PipeWire how many bytes we wrote.
                    (*chunk).offset = 0;
                    (*chunk).stride = (channels * std::mem::size_of::<f32>()) as i32;
                    (*chunk).size = (n_frames * bytes_per_frame) as u32;
                }

                pipewire_sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
            }
        })
        .state_changed(|_stream, _data, old, new| {
            info!("PipeWire playback stream state: {:?} -> {:?}", old, new);
        })
        .register()
        .expect("Failed to register playback stream listener");

    let playback_flags = if args.managed {
        pipewire::stream::StreamFlags::MAP_BUFFERS
            | pipewire::stream::StreamFlags::RT_PROCESS
    } else {
        pipewire::stream::StreamFlags::AUTOCONNECT
            | pipewire::stream::StreamFlags::MAP_BUFFERS
    };

    playback_stream
        .connect(
            libspa::utils::Direction::Output,
            None,
            playback_flags,
            &mut playback_params,
        )
        .expect("Failed to connect PipeWire playback stream");

    if args.managed {
        info!("PipeWire playback stream connected (managed mode, no AUTOCONNECT)");
    } else if args.target.is_empty() {
        info!("PipeWire playback stream connected (default routing)");
    } else {
        info!("PipeWire playback stream connected (target: {})", args.target);
    }

    // -----------------------------------------------------------------------
    // PipeWire registry listener for device hot-plug (Section 8.1)
    // -----------------------------------------------------------------------

    let (_registry, _registry_listener) = registry::register_registry_listener(
        &core,
        event_queue,
        args.device_watch.clone(),
    );
    info!("PipeWire registry listener registered (watching: {})", args.device_watch);

    // Shutdown timer: poll the AtomicBool every 100ms and quit the PW loop.
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
    drop(_shutdown_timer);
    drop(_registry_listener);
    drop(_registry);
    drop(_playback_listener);
    drop(playback_stream);
    drop(core);
    drop(context);
    drop(mainloop);

    unsafe { pipewire::deinit(); }
}

// ---------------------------------------------------------------------------
// RPC server thread
// ---------------------------------------------------------------------------

/// Run the RPC TCP server loop.
///
/// Accepts connections on the listen address, reads newline-delimited JSON,
/// dispatches commands via `handle_request`, and sends responses.
/// Polls the state feedback queue for broadcasts.
fn run_rpc_server(
    listen_addr: &str,
    cmd_queue: Arc<CommandQueue>,
    state_queue: Arc<StateQueue>,
    event_queue: Arc<DeviceEventQueue>,
    shutdown: Arc<AtomicBool>,
    max_level_dbfs: f64,
    file_samples: SharedFileSamples,
    sample_rate: u32,
) {
    let listener = match TcpListener::bind(listen_addr) {
        Ok(l) => l,
        Err(e) => {
            error!("Failed to bind RPC server to {}: {}", listen_addr, e);
            return;
        }
    };

    if let Err(e) = listener.set_nonblocking(true) {
        warn!("Failed to set non-blocking on RPC listener: {}", e);
    }

    info!("RPC server listening on {}", listen_addr);

    let mut latest_state = StateSnapshot::stopped();

    while !shutdown.load(Ordering::Relaxed) {
        // Poll state queue for updates.
        while let Some(snap) = state_queue.pop() {
            latest_state = snap;
        }

        // Accept a new connection (non-blocking).
        match listener.accept() {
            Ok((stream, addr)) => {
                info!("RPC client connected from {}", addr);
                handle_client(
                    stream,
                    &cmd_queue,
                    &state_queue,
                    &event_queue,
                    &shutdown,
                    max_level_dbfs,
                    &mut latest_state,
                    &file_samples,
                    sample_rate,
                );
                info!("RPC client disconnected: {}", addr);
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => {
                warn!("RPC accept error: {}", e);
                std::thread::sleep(Duration::from_millis(100));
            }
        }
    }

    info!("RPC server shutting down");
}

/// Handle a single RPC client connection.
fn handle_client(
    stream: TcpStream,
    cmd_queue: &CommandQueue,
    state_queue: &StateQueue,
    event_queue: &DeviceEventQueue,
    shutdown: &AtomicBool,
    max_level_dbfs: f64,
    latest_state: &mut StateSnapshot,
    file_samples: &SharedFileSamples,
    sample_rate: u32,
) {
    if let Err(e) = stream.set_nonblocking(true) {
        warn!("Failed to set non-blocking on client stream: {}", e);
    }

    let mut reader = BufReader::new(stream.try_clone().unwrap_or_else(|e| {
        error!("Failed to clone TCP stream: {}", e);
        panic!("Cannot clone TCP stream");
    }));
    let mut writer = stream;

    let mut line_buf = String::new();

    loop {
        if shutdown.load(Ordering::Relaxed) {
            break;
        }

        let mut did_work = false;

        // Poll state queue for updates.
        while let Some(snap) = state_queue.pop() {
            *latest_state = snap;
            let broadcast = rpc::format_state_broadcast(latest_state);
            if write_line(&mut writer, &broadcast).is_err() {
                return;
            }
            did_work = true;
        }

        // Poll device event queue for hot-plug / xrun events.
        while let Some(event) = event_queue.pop() {
            let event_json = registry::format_device_event(&event);
            if write_line(&mut writer, &event_json).is_err() {
                return;
            }
            did_work = true;
        }

        // Read a line from the client (non-blocking).
        line_buf.clear();
        match reader.read_line(&mut line_buf) {
            Ok(0) => return, // EOF
            Ok(_) => {
                did_work = true;
                let line = line_buf.trim();
                if line.is_empty() {
                    continue;
                }

                if line.len() > MAX_LINE_LENGTH {
                    let resp = rpc::format_line_too_long();
                    if write_line(&mut writer, &resp).is_err() {
                        return;
                    }
                    continue;
                }

                let response = match rpc::parse_line(line) {
                    Ok(req) => {
                        let result =
                            rpc::handle_request(&req, cmd_queue, max_level_dbfs, latest_state, file_samples, sample_rate);
                        match result {
                            rpc::HandleResult::Ack(cmd) => rpc::format_ack(&cmd),
                            rpc::HandleResult::Error(cmd, msg) => {
                                rpc::format_error(&cmd, &msg)
                            }
                            rpc::HandleResult::StatusJson(json) => json,
                        }
                    }
                    Err(err_response) => err_response,
                };

                if write_line(&mut writer, &response).is_err() {
                    return;
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                // No data available.
            }
            Err(e) => {
                warn!("RPC read error: {}", e);
                return;
            }
        }

        if !did_work {
            std::thread::sleep(Duration::from_millis(5));
        }
    }
}

/// Write a JSON line to the TCP stream, appending newline.
fn write_line(writer: &mut TcpStream, line: &str) -> std::io::Result<()> {
    writer.write_all(line.as_bytes())?;
    writer.write_all(b"\n")?;
    writer.flush()
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let args = Args::parse();

    if let Err(msg) = validate_args(&args) {
        error!("{}", msg);
        process::exit(1);
    }

    info!(
        "pi4audio-signal-gen starting: target={}, \
         channels={}, rate={}, listen={}, max_level_dbfs={}, ramp_ms={}",
        args.target,
        args.channels,
        args.rate,
        args.listen,
        args.max_level_dbfs,
        args.ramp_ms,
    );

    // Shared shutdown flag.
    let shutdown = Arc::new(AtomicBool::new(false));

    for sig in [signal_hook::consts::SIGTERM, signal_hook::consts::SIGINT] {
        if let Err(e) = signal_hook::flag::register(sig, shutdown.clone()) {
            warn!("Failed to register signal handler for {}: {}", sig, e);
        }
    }

    // Shared command queue (RPC -> RT) and state feedback queue (RT -> RPC).
    let cmd_queue = Arc::new(CommandQueue::new());
    let state_queue = Arc::new(StateQueue::new());

    // Shared file playback samples (RPC thread writes, RT thread reads).
    let file_samples: SharedFileSamples = Arc::new(Mutex::new(Arc::new(Vec::new())));

    // Device event queue (PW registry -> RPC thread).
    let event_queue = Arc::new(DeviceEventQueue::new());

    // Parse listen address.
    let (host, port) = parse_listen_addr(&args.listen);
    let rpc_addr = format!("{}:{}", host, port);

    // Spawn the RPC server thread.
    let rpc_cmd_queue = cmd_queue.clone();
    let rpc_state_queue = state_queue.clone();
    let rpc_event_queue = event_queue.clone();
    let rpc_shutdown = shutdown.clone();
    let max_level_dbfs = args.max_level_dbfs;
    let rpc_file_samples = file_samples.clone();
    let rpc_sample_rate = args.rate;
    let rpc_thread = std::thread::Builder::new()
        .name("rpc-server".into())
        .spawn(move || {
            run_rpc_server(
                &rpc_addr,
                rpc_cmd_queue,
                rpc_state_queue,
                rpc_event_queue,
                rpc_shutdown,
                max_level_dbfs,
                rpc_file_samples,
                rpc_sample_rate,
            );
        })
        .expect("Failed to spawn RPC server thread");

    // Run PipeWire main loop on the main thread (blocks until shutdown).
    run_pipewire(
        &args,
        cmd_queue.clone(),
        state_queue.clone(),
        event_queue.clone(),
        shutdown.clone(),
        file_samples.clone(),
    );

    info!("PipeWire loop exited, waiting for RPC server thread...");
    let _ = rpc_thread.join();
    info!("pi4audio-signal-gen shutdown complete");
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use command::{CommandKind, SignalType, PlayState};

    fn test_file_samples() -> SharedFileSamples {
        Arc::new(Mutex::new(Arc::new(Vec::new())))
    }

    fn make_args(listen: &str, max_level_dbfs: f64) -> Args {
        Args {
            target: "".into(),
            channels: 8,
            rate: 48000,
            listen: listen.into(),
            max_level_dbfs,
            ramp_ms: 20,
            device_watch: "UMIK-1".into(),
            managed: false,
        }
    }

    // -----------------------------------------------------------------------
    // validate_args
    // -----------------------------------------------------------------------

    #[test]
    fn validate_loopback_ipv4_accepted() {
        assert!(validate_args(&make_args("tcp:127.0.0.1:4001", -20.0)).is_ok());
    }

    #[test]
    fn validate_loopback_ipv6_accepted() {
        assert!(validate_args(&make_args("tcp:::1:4001", -20.0)).is_ok());
    }

    #[test]
    fn validate_loopback_localhost_accepted() {
        assert!(validate_args(&make_args("tcp:localhost:4001", -20.0)).is_ok());
    }

    #[test]
    fn validate_non_loopback_rejected() {
        let err = validate_args(&make_args("tcp:0.0.0.0:4001", -20.0)).unwrap_err();
        assert!(err.contains("loopback"));
    }

    #[test]
    fn validate_external_ip_rejected() {
        assert!(validate_args(&make_args("tcp:192.168.1.1:4001", -20.0)).is_err());
    }

    #[test]
    fn validate_max_level_at_ceiling_accepted() {
        assert!(validate_args(&make_args("tcp:127.0.0.1:4001", -0.5)).is_ok());
    }

    #[test]
    fn validate_max_level_above_ceiling_rejected() {
        let err = validate_args(&make_args("tcp:127.0.0.1:4001", 0.0)).unwrap_err();
        assert!(err.contains("-0.5"));
    }

    #[test]
    fn validate_max_level_below_floor_rejected() {
        let err = validate_args(&make_args("tcp:127.0.0.1:4001", -130.0)).unwrap_err();
        assert!(err.contains("-120.0"));
    }

    #[test]
    fn validate_default_level_accepted() {
        assert!(validate_args(&make_args("tcp:127.0.0.1:4001", -20.0)).is_ok());
    }

    #[test]
    fn validate_listen_without_tcp_prefix() {
        assert!(validate_args(&make_args("127.0.0.1:4001", -20.0)).is_ok());
    }

    // -----------------------------------------------------------------------
    // --managed flag (GM-10)
    // -----------------------------------------------------------------------

    #[test]
    fn managed_default_is_false() {
        let args = make_args("tcp:127.0.0.1:4001", -20.0);
        assert!(!args.managed);
    }

    #[test]
    fn managed_flag_can_be_set() {
        let mut args = make_args("tcp:127.0.0.1:4001", -20.0);
        args.managed = true;
        assert!(args.managed);
    }

    #[test]
    fn managed_flag_parsed_from_cli() {
        let args = Args::try_parse_from([
            "pi4audio-signal-gen",
            "--managed",
        ]).expect("--managed flag should be accepted");
        assert!(args.managed);
    }

    #[test]
    fn managed_flag_absent_defaults_false() {
        let args = Args::try_parse_from([
            "pi4audio-signal-gen",
        ]).expect("no flags should be accepted");
        assert!(!args.managed);
    }

    // -----------------------------------------------------------------------
    // ProcessState: command processing logic
    // -----------------------------------------------------------------------

    #[test]
    fn process_state_initial_is_stopped() {
        let state = ProcessState::new(8, 48000, -20.0, 20, test_file_samples());
        assert_eq!(state.play_state, PlayState::Stopped);
        assert_eq!(state.active_signal, SignalType::Silence);
        assert_eq!(state.active_channels, 0);
    }

    #[test]
    fn play_command_activates_generator() {
        let mut state = ProcessState::new(2, 48000, -20.0, 20, test_file_samples());
        state.apply_command(Command {
            kind: CommandKind::Play {
                signal: SignalType::Sine,
                channels: 0b0000_0011,
                level_dbfs: -20.0,
                frequency: 1000.0,
                duration_secs: None,
                sweep_end_hz: 0.0,
            },
        });

        assert_eq!(state.play_state, PlayState::Playing);
        assert_eq!(state.active_signal, SignalType::Sine);
        assert_eq!(state.active_channels, 0b0000_0011);
        assert_eq!(state.current_freq, 1000.0);
        assert!(state.fade.is_active(), "Should have fade-in ramp");
    }

    #[test]
    fn stop_command_initiates_fade_out() {
        let mut state = ProcessState::new(2, 48000, -20.0, 20, test_file_samples());
        state.apply_command(Command {
            kind: CommandKind::Play {
                signal: SignalType::Sine,
                channels: 0b01,
                level_dbfs: -20.0,
                frequency: 1000.0,
                duration_secs: None,
                sweep_end_hz: 0.0,
            },
        });
        assert_eq!(state.play_state, PlayState::Playing);

        state.apply_command(Command {
            kind: CommandKind::Stop,
        });
        assert!(state.pending_stop, "Stop should set pending_stop");
        assert!(state.fade.is_active(), "Stop should initiate fade-out ramp");
    }

    #[test]
    fn set_frequency_updates_state() {
        let mut state = ProcessState::new(2, 48000, -20.0, 20, test_file_samples());
        state.apply_command(Command {
            kind: CommandKind::SetFrequency { frequency: 440.0 },
        });
        assert_eq!(state.current_freq, 440.0);
    }

    #[test]
    fn set_channel_updates_state() {
        let mut state = ProcessState::new(8, 48000, -20.0, 20, test_file_samples());
        state.apply_command(Command {
            kind: CommandKind::SetChannel { channels: 0b1111_0000 },
        });
        assert_eq!(state.active_channels, 0b1111_0000);
    }

    #[test]
    fn multi_command_drain_in_process() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let mut state = ProcessState::new(2, 48000, -20.0, 20, test_file_samples());

        cmd_queue
            .push(Command {
                kind: CommandKind::Play {
                    signal: SignalType::Pink,
                    channels: 0b01,
                    level_dbfs: -20.0,
                    frequency: 0.0,
                    duration_secs: None,
                    sweep_end_hz: 0.0,
                },
            })
            .unwrap();
        cmd_queue
            .push(Command {
                kind: CommandKind::SetChannel { channels: 0b11 },
            })
            .unwrap();

        let mut buf = vec![0.0f32; 512]; // 256 frames * 2 channels
        state.process(&mut buf, 256, &cmd_queue, &state_queue);

        assert_eq!(state.active_signal, SignalType::Pink);
        assert_eq!(state.active_channels, 0b11);
        assert_eq!(state.play_state, PlayState::Playing);
    }

    #[test]
    fn process_generates_silence_when_stopped() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let mut state = ProcessState::new(2, 48000, -20.0, 20, test_file_samples());

        let mut buf = vec![1.0f32; 512]; // pre-fill with non-zero
        state.process(&mut buf, 256, &cmd_queue, &state_queue);

        assert!(
            buf.iter().all(|&s| s == 0.0),
            "Stopped state should produce silence"
        );
    }

    #[test]
    fn process_pushes_state_snapshot() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let mut state = ProcessState::new(2, 48000, -20.0, 20, test_file_samples());

        let mut buf = vec![0.0f32; 512];
        state.process(&mut buf, 256, &cmd_queue, &state_queue);

        let snap = state_queue.pop();
        assert!(snap.is_some(), "Process should push a state snapshot");
        let snap = snap.unwrap();
        assert_eq!(snap.state, PlayState::Stopped);
        assert_eq!(snap.samples_generated, 256);
    }

    #[test]
    fn burst_auto_stop_triggers_fade_out() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let mut state = ProcessState::new(1, 48000, -20.0, 20, test_file_samples());

        state.apply_command(Command {
            kind: CommandKind::Play {
                signal: SignalType::Sine,
                channels: 0b01,
                level_dbfs: -20.0,
                frequency: 1000.0,
                duration_secs: Some(0.01),
                sweep_end_hz: 0.0,
            },
        });

        let mut buf = vec![0.0f32; 480];
        state.process(&mut buf, 480, &cmd_queue, &state_queue);

        assert!(state.pending_stop, "Burst completion should trigger pending_stop");
    }

    // -----------------------------------------------------------------------
    // Signal handler flag
    // -----------------------------------------------------------------------

    #[test]
    fn shutdown_flag_default_false() {
        let flag = Arc::new(AtomicBool::new(false));
        assert!(!flag.load(Ordering::Relaxed));
    }

    #[test]
    fn shutdown_flag_can_be_set() {
        let flag = Arc::new(AtomicBool::new(false));
        flag.store(true, Ordering::Relaxed);
        assert!(flag.load(Ordering::Relaxed));
    }

    // -----------------------------------------------------------------------
    // dbfs_to_linear
    // -----------------------------------------------------------------------

    #[test]
    fn dbfs_to_linear_minus_20() {
        let linear = dbfs_to_linear(-20.0);
        assert!((linear - 0.1).abs() < 1e-5);
    }

    #[test]
    fn dbfs_to_linear_zero() {
        let linear = dbfs_to_linear(0.0);
        assert!((linear - 1.0).abs() < 1e-5);
    }

    // -----------------------------------------------------------------------
    // parse_listen_addr
    // -----------------------------------------------------------------------

    #[test]
    fn parse_listen_addr_with_prefix() {
        let (host, port) = parse_listen_addr("tcp:127.0.0.1:4001");
        assert_eq!(host, "127.0.0.1");
        assert_eq!(port, "4001");
    }

    #[test]
    fn parse_listen_addr_without_prefix() {
        let (host, port) = parse_listen_addr("127.0.0.1:4001");
        assert_eq!(host, "127.0.0.1");
        assert_eq!(port, "4001");
    }

    // -----------------------------------------------------------------------
    // build_audio_format regression tests (BUG-SG12-5 / TK-236)
    // -----------------------------------------------------------------------

    #[test]
    fn build_audio_format_no_positions_size_and_alignment() {
        let pod = build_audio_format(8, 48000, &[]);
        assert_eq!(pod.len() % 8, 0, "SPA pod must be 8-byte aligned");
        assert_eq!(pod.len(), 136);
    }

    #[test]
    fn build_audio_format_header_type() {
        let pod = build_audio_format(2, 44100, &[]);
        let pod_type = u32::from_le_bytes(pod[4..8].try_into().unwrap());
        assert_eq!(pod_type, 15, "pod header type must be SPA_TYPE_Object");
    }

    #[test]
    fn build_audio_format_body_size() {
        let pod = build_audio_format(3, 48000, &[]);
        let body_size = u32::from_le_bytes(pod[0..4].try_into().unwrap());
        assert_eq!(body_size as usize, pod.len() - 8);
    }

    #[test]
    fn build_audio_format_channels_embedded_no_positions() {
        let pod = build_audio_format(8, 48000, &[]);
        let ch_val = u32::from_le_bytes(pod[128..132].try_into().unwrap());
        assert_eq!(ch_val, 8);
    }

    #[test]
    fn build_audio_format_rate_embedded() {
        let pod = build_audio_format(2, 96000, &[]);
        let rate_val = i32::from_le_bytes(pod[104..108].try_into().unwrap());
        assert_eq!(rate_val, 96000);
    }

    #[test]
    fn build_audio_format_mono_capture_with_position() {
        let pod = build_audio_format(1, 48000, &spa_channel::CAPTURE_MONO);
        assert_eq!(pod.len() % 8, 0, "SPA pod must be 8-byte aligned");
        assert!(pod.len() > 136);
        let body_size = u32::from_le_bytes(pod[0..4].try_into().unwrap());
        assert_eq!(body_size as usize, pod.len() - 8);
    }

    #[test]
    fn build_audio_format_8ch_with_positions() {
        let pod = build_audio_format(8, 48000, &spa_channel::PLAYBACK_8CH);
        assert_eq!(pod.len() % 8, 0, "SPA pod must be 8-byte aligned");
        assert!(pod.len() > 136);
        let body_size = u32::from_le_bytes(pod[0..4].try_into().unwrap());
        assert_eq!(body_size as usize, pod.len() - 8);
    }

    #[test]
    fn build_audio_format_positions_contain_aux_values() {
        let pod = build_audio_format(8, 48000, &spa_channel::PLAYBACK_8CH);
        let first_pos = u32::from_le_bytes(pod[160..164].try_into().unwrap());
        assert_eq!(first_pos, spa_channel::AUX0, "First position should be AUX0");
        let last_pos = u32::from_le_bytes(pod[188..192].try_into().unwrap());
        assert_eq!(last_pos, spa_channel::AUX7, "Last position should be AUX7");
    }

    #[test]
    fn build_audio_format_mono_position_value() {
        let pod = build_audio_format(1, 48000, &spa_channel::CAPTURE_MONO);
        let pos_val = u32::from_le_bytes(pod[160..164].try_into().unwrap());
        assert_eq!(pos_val, spa_channel::MONO, "Capture position should be MONO");
    }

    #[test]
    fn spa_channel_constants() {
        assert_eq!(spa_channel::MONO, 0x02);
        assert_eq!(spa_channel::AUX0, 0x1000);
        assert_eq!(spa_channel::AUX7, 0x1007);
        assert_eq!(spa_channel::PLAYBACK_8CH.len(), 8);
        assert_eq!(spa_channel::CAPTURE_MONO.len(), 1);
    }
}
