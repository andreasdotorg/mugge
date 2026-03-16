//! pi4audio-signal-gen -- RT signal generator for measurement and test tooling.
//!
//! Maintains an always-on PipeWire playback stream (targeting the loopback sink
//! that feeds CamillaDSP) and a capture stream (targeting the UMIK-1). Signal
//! content is controlled via a JSON-over-TCP RPC interface without ever closing
//! or reopening the audio streams.
//!
//! This eliminates TK-224's root cause: WirePlumber routing races caused by
//! per-burst stream opening in the Python measurement pipeline.
//!
//! ## Thread model
//!
//! 1. **Main thread** — PipeWire main loop (event dispatch, shutdown timer)
//! 2. **RPC thread** — TCP listener, JSON parsing, command queue push, state polling
//! 3. **PW data thread** (PW-managed, SCHED_FIFO) — process callback invoked each quantum

mod capture;
mod command;
mod generator;
mod ramp;
mod registry;
mod rpc;
mod safety;

use std::io::{BufRead, BufReader, Write as IoWrite};
use std::net::{TcpListener, TcpStream};
use std::process;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use base64::Engine as _;
use clap::Parser;
use log::{error, info, warn};

use capture::CaptureRingBuffer;
use command::{
    Command, CommandKind, CommandQueue, PlayState, SignalType, StateQueue, StateSnapshot,
};
use generator::{
    PinkNoiseGenerator, SignalGenerator, SilenceGenerator, SineGenerator, SweepGenerator,
    WhiteNoiseGenerator,
};
use ramp::FadeRamp;
use registry::{CaptureConnectionState, DeviceEventQueue};
use rpc::MAX_LINE_LENGTH;
use safety::SafetyLimits;

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

/// RT signal generator for Pi audio workstation measurement and test tooling.
#[derive(Parser, Debug)]
#[command(name = "pi4audio-signal-gen", version)]
struct Args {
    /// PipeWire playback target node name.
    #[arg(long, default_value = "loopback-8ch-sink")]
    target: String,

    /// PipeWire capture target node name (UMIK-1).
    #[arg(long, default_value = "UMIK-1")]
    capture_target: String,

    /// Number of output channels.
    #[arg(long, default_value_t = 8)]
    channels: u32,

    /// Sample rate in Hz.
    #[arg(long, default_value_t = 48000)]
    rate: u32,

    /// RPC listen address (tcp:HOST:PORT).
    #[arg(long, default_value = "tcp:127.0.0.1:4001")]
    listen: String,

    /// Hard output level cap in dBFS (immutable after startup).
    #[arg(long, default_value_t = -20.0)]
    max_level_dbfs: f64,

    /// Fade ramp duration in milliseconds.
    #[arg(long, default_value_t = 20)]
    ramp_ms: u32,

    /// Capture ring buffer duration in seconds.
    #[arg(long, default_value_t = 30)]
    capture_buffer_secs: u32,

    /// Device name pattern to watch for hot-plug events.
    #[arg(long, default_value = "UMIK-1")]
    device_watch: String,
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

    // Capture state
    /// Whether playrec is in progress (coordinating play + capture).
    playrec_active: bool,
    /// Tail samples remaining after playback finishes during playrec.
    /// Capture continues for this many samples to catch reverb tail.
    playrec_tail_remaining: Option<u64>,
    /// Tail duration in samples (configurable, default 500ms worth).
    playrec_tail_samples: u64,

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
    ) -> Self {
        let ramp_samples = FadeRamp::ms_to_samples(ramp_ms, rate);
        let safety = SafetyLimits::from_dbfs(max_level_dbfs);
        // Default tail: 500ms for reverb tail capture.
        let playrec_tail_samples = (rate as u64) / 2;

        Self {
            channels,
            rate: rate as f64,
            generator: Box::new(SilenceGenerator),
            gen_silence: SilenceGenerator,
            gen_sine: SineGenerator::new(1000.0, rate as f64),
            gen_white: WhiteNoiseGenerator::new(42),
            gen_pink: PinkNoiseGenerator::new(42),
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
            playrec_active: false,
            playrec_tail_remaining: None,
            playrec_tail_samples,
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
            CommandKind::Playrec {
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
                self.switch_generator(
                    signal,
                    frequency,
                    Some(duration_secs),
                    sweep_end_hz,
                );
                self.fade = FadeRamp::new(0.0, 1.0, self.ramp_samples);
                self.play_state = PlayState::PlayrecInProgress;
                self.elapsed_samples = 0;
                self.duration_samples = (duration_secs as f64 * self.rate) as u64;
                self.burst_remaining = Some(self.duration_samples);
                self.pending_stop = false;
                // Record-before-play (AE-MF-1): start capture first.
                self.playrec_active = true;
                self.playrec_tail_remaining = None;
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
                    self.current_level_linear / self.current_level_linear.max(1e-10),
                    new_linear / self.current_level_linear.max(1e-10),
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
            CommandKind::StartCapture => {
                // Standalone capture: record without playing.
                self.playrec_active = false;
                self.playrec_tail_remaining = None;
            }
            CommandKind::StopCapture => {
                self.playrec_active = false;
                self.playrec_tail_remaining = None;
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
                // We can't move gen_sine out, so we create a new one with current params.
                self.generator =
                    Box::new(SineGenerator::new(frequency as f64, self.rate));
            }
            SignalType::White => {
                self.generator = Box::new(WhiteNoiseGenerator::new(
                    // Use samples_generated as seed for variety.
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
        }
    }

    /// Create a state snapshot for the feedback queue.
    fn snapshot(
        &self,
        capture: Option<&CaptureRingBuffer>,
        conn_state: Option<&CaptureConnectionState>,
    ) -> StateSnapshot {
        let (cap_peak, cap_rms) = match capture {
            Some(cap) => (cap.peak(), cap.rms()),
            None => (0.0, 0.0),
        };
        let cap_connected = conn_state.map_or(false, |cs| cs.is_connected());
        StateSnapshot {
            state: self.play_state,
            signal: self.active_signal,
            channels: self.active_channels,
            level_dbfs: self.current_level_dbfs,
            frequency: self.current_freq,
            elapsed_secs: self.elapsed_samples as f32 / self.rate as f32,
            duration_secs: self.duration_samples as f32 / self.rate as f32,
            capture_peak: cap_peak,
            capture_rms: cap_rms,
            capture_connected: cap_connected,
            samples_generated: self.samples_generated,
        }
    }

    /// Run the playback process callback logic on a buffer.
    ///
    /// This is the core audio processing function, called from the PW
    /// playback process callback. Factored out so the non-PW parts are testable.
    ///
    /// `capture` is the shared capture ring buffer. When a Playrec or
    /// StartCapture command is processed, this method controls the recording
    /// state machine. Pass `None` in unit tests that don't need capture.
    fn process(
        &mut self,
        output: &mut [f32],
        n_frames: usize,
        cmd_queue: &CommandQueue,
        state_queue: &StateQueue,
        capture: Option<&CaptureRingBuffer>,
        conn_state: Option<&CaptureConnectionState>,
    ) {
        // 1. Drain all pending commands (AD-D037-6: multi-command-per-quantum).
        while let Some(cmd) = cmd_queue.pop() {
            // Handle capture-related commands BEFORE applying to playback state.
            match cmd.kind {
                CommandKind::Playrec { .. } => {
                    // Record-before-play (AE-MF-1): start capture first.
                    if let Some(cap) = capture {
                        cap.start_recording();
                    }
                }
                CommandKind::StartCapture => {
                    if let Some(cap) = capture {
                        cap.start_recording();
                    }
                }
                CommandKind::StopCapture => {
                    if let Some(cap) = capture {
                        cap.stop_recording();
                    }
                }
                CommandKind::Stop => {
                    // If we were recording during playrec, discard partial.
                    if self.playrec_active {
                        if let Some(cap) = capture {
                            cap.discard_recording();
                        }
                        self.playrec_active = false;
                        self.playrec_tail_remaining = None;
                    }
                }
                _ => {}
            }
            self.apply_command(cmd);
        }

        // Handle pending stop from a PREVIOUS quantum (fade already finished).
        if self.pending_stop && self.fade.is_finished() {
            self.play_state = PlayState::Stopped;
            self.active_signal = SignalType::Silence;
            self.generator = Box::new(SilenceGenerator);
            self.burst_remaining = None;
            self.pending_stop = false;

            // If playrec was active and playback just stopped, start tail countdown.
            if self.playrec_active && self.playrec_tail_remaining.is_none() {
                self.playrec_tail_remaining = Some(self.playrec_tail_samples);
            }
        }

        // 2. Generate samples into the buffer.
        self.generator.generate(
            output,
            n_frames,
            self.channels,
            self.active_channels,
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
            // Clear burst to prevent re-triggering next quantum.
            self.burst_remaining = None;
        }

        // 6. Check if sweep finished (generator-level auto-stop).
        if self.generator.is_finished() && self.play_state == PlayState::Playing {
            self.fade = FadeRamp::new(1.0, 0.0, self.ramp_samples);
            self.pending_stop = true;
        }

        // 6b. Check if pending_stop fade completed THIS quantum.
        // This catches the case where burst triggers stop and the fade-out
        // completes within the same quantum (e.g. ramp_samples=1).
        if self.pending_stop && self.fade.is_finished() {
            self.play_state = PlayState::Stopped;
            self.active_signal = SignalType::Silence;
            self.generator = Box::new(SilenceGenerator);
            self.burst_remaining = None;
            self.pending_stop = false;

            if self.playrec_active && self.playrec_tail_remaining.is_none() {
                self.playrec_tail_remaining = Some(self.playrec_tail_samples);
            }
        }

        // 7. Handle playrec tail countdown.
        if let Some(ref mut tail) = self.playrec_tail_remaining {
            *tail = tail.saturating_sub(n_frames as u64);
            if *tail == 0 {
                // Tail expired: stop capture and emit playrec_complete.
                if let Some(cap) = capture {
                    cap.stop_recording();
                }
                self.playrec_active = false;
                self.playrec_tail_remaining = None;
                self.play_state = PlayState::Stopped;
            }
        }

        // Update counters.
        self.samples_generated += n_frames as u64;
        self.elapsed_samples += n_frames as u64;

        // 8. Push state snapshot (at most once per callback).
        let _ = state_queue.push(self.snapshot(capture, conn_state));
    }
}

/// Convert dBFS to linear amplitude.
fn dbfs_to_linear(dbfs: f32) -> f32 {
    10.0f32.powf(dbfs / 20.0)
}

// ---------------------------------------------------------------------------
// PipeWire playback stream
// ---------------------------------------------------------------------------

/// Build an SPA audio format pod for stream negotiation as raw bytes.
///
/// Port count in PipeWire is driven by the format params passed to
/// `stream.connect()`, not by the `audio.channels` node property.
/// Without format params, PipeWire never creates ports and WirePlumber
/// cannot auto-link the stream (BUG-SG12-5 / TK-236).
///
/// `positions` specifies channel position IDs (e.g. AUX0-AUX7 for playback,
/// MONO for capture). When provided, PipeWire creates per-channel ports that
/// match the target sink/source topology, enabling WirePlumber auto-linking.
/// Without positions, PipeWire creates a single interleaved port that cannot
/// be linked to multi-port targets (TK-236 topology mismatch).
///
/// The pod is constructed directly in the SPA wire format because the
/// `spa_pod_builder_*` C functions are inline and not exposed by bindgen.
#[allow(non_upper_case_globals)]
fn build_audio_format(channels: u32, rate: u32, positions: &[u32]) -> Vec<u8> {
    // SPA pod wire format (all little-endian, 8-byte aligned):
    //
    // Pod header:     size:u32, type:u32
    // Object body:    body_type:u32, body_id:u32
    // Property:       key:u32, flags:u32, value_pod(size:u32, type:u32, data...)
    // Array pod:      size:u32, type:u32(=Array), child_size:u32, child_type:u32, elements...
    //
    // Constants from spa/utils/type.h and spa/param/format.h
    // (verified against Pi PipeWire 1.4.10 headers in Nix store):
    const SPA_TYPE_Id: u32 = 3;       // enum spa_type: None=1, Bool=2, Id=3
    const SPA_TYPE_Int: u32 = 4;      // Int=4, Long=5, Float=6, Double=7
    const SPA_TYPE_Array: u32 = 13;   // String=8..Bitmap=12, Array=13
    const SPA_TYPE_Object: u32 = 15;  // Struct=14, Object=15
    const SPA_TYPE_OBJECT_Format: u32 = 0x40003; // START=0x40000, PropInfo, Props, Format
    const SPA_PARAM_EnumFormat: u32 = 3;
    const SPA_FORMAT_mediaType: u32 = 1;
    const SPA_FORMAT_mediaSubtype: u32 = 2;
    const SPA_FORMAT_AUDIO_format: u32 = 0x10001;    // START_Audio + 1
    const SPA_FORMAT_AUDIO_rate: u32 = 0x10003;      // +3 (flags at +2)
    const SPA_FORMAT_AUDIO_channels: u32 = 0x10004;  // +4
    const SPA_FORMAT_AUDIO_position: u32 = 0x10005;  // +5
    const SPA_MEDIA_TYPE_audio: u32 = 1; // unknown=0, audio=1
    const SPA_MEDIA_SUBTYPE_raw: u32 = 1;
    const SPA_AUDIO_FORMAT_F32LE: u32 = 0x11A; // F32_LE in interleaved block

    // 5 scalar properties * 24 bytes + position array property + 16 bytes header.
    // Position array: 8 (key+flags) + 8 (array pod header) + 8 (child descriptor)
    //   + 4*N positions, padded to 8-byte alignment.
    let mut buf = Vec::with_capacity(200);

    // Helper: write a property with an Id value
    fn write_prop_id(buf: &mut Vec<u8>, key: u32, val: u32) {
        buf.extend_from_slice(&key.to_le_bytes());    // property key
        buf.extend_from_slice(&0u32.to_le_bytes());    // property flags
        buf.extend_from_slice(&4u32.to_le_bytes());    // pod size
        buf.extend_from_slice(&SPA_TYPE_Id.to_le_bytes()); // pod type
        buf.extend_from_slice(&val.to_le_bytes());     // value
        buf.extend_from_slice(&[0u8; 4]);              // pad to 8-byte align
    }

    // Helper: write a property with an Int value
    fn write_prop_int(buf: &mut Vec<u8>, key: u32, val: i32) {
        buf.extend_from_slice(&key.to_le_bytes());
        buf.extend_from_slice(&0u32.to_le_bytes());
        buf.extend_from_slice(&4u32.to_le_bytes());    // pod size
        buf.extend_from_slice(&SPA_TYPE_Int.to_le_bytes()); // pod type
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

    // Position array property (TK-236): tells PipeWire which channel each
    // port represents, enabling per-channel port creation and WirePlumber
    // auto-linking to matching target ports.
    if !positions.is_empty() {
        let n = positions.len() as u32;
        // Array element size is 4 bytes (Id), child descriptor is 8 bytes.
        let array_data_size = 8 + n * 4; // child_desc(8) + elements(4*N)

        buf.extend_from_slice(&SPA_FORMAT_AUDIO_position.to_le_bytes()); // property key
        buf.extend_from_slice(&0u32.to_le_bytes());                       // property flags
        // Array pod: size includes child descriptor + all elements.
        buf.extend_from_slice(&array_data_size.to_le_bytes());            // pod size
        buf.extend_from_slice(&SPA_TYPE_Array.to_le_bytes());             // pod type = Array
        // Child descriptor: size and type of each element.
        buf.extend_from_slice(&4u32.to_le_bytes());                       // child size = 4
        buf.extend_from_slice(&SPA_TYPE_Id.to_le_bytes());                // child type = Id
        // Elements: one Id per channel position.
        for &pos in positions {
            buf.extend_from_slice(&pos.to_le_bytes());
        }
        // Pad to 8-byte alignment if needed.
        let remainder = (n * 4) % 8;
        if remainder != 0 {
            let pad = 8 - remainder;
            for _ in 0..pad {
                buf.push(0u8);
            }
        }
    }

    // Fill in object body size
    let body_size = (buf.len() - header_pos - 8) as u32;
    buf[header_pos..header_pos + 4].copy_from_slice(&body_size.to_le_bytes());

    buf
}

/// Channel position constants from spa/param/audio/raw.h.
/// Used for `audio.position` in stream properties and SPA format pods.
#[allow(dead_code)]
mod spa_channel {
    pub const MONO: u32 = 0x02;  // UNKNOWN=0, NA=1, MONO=2
    pub const AUX0: u32 = 0x1000;
    pub const AUX1: u32 = 0x1001;
    pub const AUX2: u32 = 0x1002;
    pub const AUX3: u32 = 0x1003;
    pub const AUX4: u32 = 0x1004;
    pub const AUX5: u32 = 0x1005;
    pub const AUX6: u32 = 0x1006;
    pub const AUX7: u32 = 0x1007;

    /// Playback channel positions: 8 aux channels matching loopback sink.
    pub const PLAYBACK_8CH: [u32; 8] = [AUX0, AUX1, AUX2, AUX3, AUX4, AUX5, AUX6, AUX7];
    /// Capture channel position: mono (UMIK-1 measurement mic).
    pub const CAPTURE_MONO: [u32; 1] = [MONO];
}

/// Run the PipeWire main loop with playback and capture streams.
///
/// This function blocks until the shutdown flag is set.
fn run_pipewire(
    args: &Args,
    cmd_queue: Arc<CommandQueue>,
    state_queue: Arc<StateQueue>,
    capture_buf: Arc<CaptureRingBuffer>,
    event_queue: Arc<DeviceEventQueue>,
    conn_state: Arc<CaptureConnectionState>,
    shutdown: Arc<AtomicBool>,
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

    let playback_props = pipewire::properties::properties! {
        "media.type" => "Audio",
        "media.category" => "Playback",
        "media.role" => "Production",
        "media.class" => "Stream/Output/Audio",
        "node.name" => "pi4audio-signal-gen",
        "node.description" => "RT Signal Generator",
        "target.object" => &*args.target,
        "audio.channels" => &*channels_str,
        "audio.position" => "AUX0,AUX1,AUX2,AUX3,AUX4,AUX5,AUX6,AUX7",
        "node.always-process" => "true",
    };

    let playback_stream =
        pipewire::stream::Stream::new(&core, "pi4audio-signal-gen", playback_props)
            .expect("Failed to create PipeWire playback stream");

    // SPA format params: F32LE at configured rate, channel count, and
    // positions (AUX0-AUX7). Drives PipeWire per-channel port creation
    // matching the loopback sink topology (BUG-SG12-5 / TK-236).
    let playback_fmt_bytes = build_audio_format(
        args.channels, args.rate, &spa_channel::PLAYBACK_8CH,
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
    );

    let cmd_q = cmd_queue;
    let state_q = state_queue;
    let playback_capture_buf = capture_buf.clone();
    let playback_conn_state = conn_state.clone();
    let channels = args.channels as usize;

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
                        Some(&playback_capture_buf),
                        Some(&playback_conn_state),
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

    playback_stream
        .connect(
            libspa::utils::Direction::Output,
            None,
            pipewire::stream::StreamFlags::AUTOCONNECT
                | pipewire::stream::StreamFlags::MAP_BUFFERS
                | pipewire::stream::StreamFlags::RT_PROCESS
                // DRIVER makes this stream self-clocking so PipeWire always
                // invokes the process callback. Without it, native PW streams
                // stay suspended because no driver pulls them into a graph
                // cycle (BUG-SG12-6). JACK clients get activation via
                // jack_activate(); native streams need DRIVER instead.
                | pipewire::stream::StreamFlags::DRIVER,
            &mut playback_params,
        )
        .expect("Failed to connect PipeWire playback stream");

    info!("PipeWire playback stream connected");

    // -----------------------------------------------------------------------
    // Capture stream (Section 3.2) — targets UMIK-1
    // -----------------------------------------------------------------------

    let capture_props = pipewire::properties::properties! {
        "media.type" => "Audio",
        "media.category" => "Capture",
        "media.role" => "Production",
        "media.class" => "Stream/Input/Audio",
        "node.name" => "pi4audio-signal-gen-capture",
        "node.description" => "RT Signal Generator (UMIK-1 capture)",
        "target.object" => &*args.capture_target,
        "audio.channels" => "1",
        "audio.position" => "MONO",
        "node.always-process" => "true",
    };

    let capture_stream =
        pipewire::stream::Stream::new(&core, "pi4audio-signal-gen-capture", capture_props)
            .expect("Failed to create PipeWire capture stream");

    // SPA format params: mono F32LE at configured rate with MONO
    // position (BUG-SG12-5 / TK-236).
    let capture_fmt_bytes = build_audio_format(1, args.rate, &spa_channel::CAPTURE_MONO);
    let capture_fmt_pod = unsafe {
        &*(capture_fmt_bytes.as_ptr() as *const libspa::pod::Pod)
    };
    let mut capture_params: [&libspa::pod::Pod; 1] = [capture_fmt_pod];

    let cap_buf_for_cb = capture_buf.clone();

    // Register the capture process callback.
    let _capture_listener = capture_stream
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

                // Read captured samples (mono F32).
                let size = (*chunk).size as usize;
                let n_frames = size / std::mem::size_of::<f32>();

                if n_frames > 0 {
                    let input = std::slice::from_raw_parts(
                        data_ptr as *const f32,
                        n_frames,
                    );

                    // Always update live metering (even when not recording).
                    cap_buf_for_cb.update_levels(input);

                    // Write to ring buffer if recording is active.
                    cap_buf_for_cb.write_samples(input);
                }

                pipewire_sys::pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf);
            }
        })
        .state_changed(|_stream, _data, old, new| {
            info!("PipeWire capture stream state: {:?} -> {:?}", old, new);
        })
        .register()
        .expect("Failed to register capture stream listener");

    capture_stream
        .connect(
            libspa::utils::Direction::Input,
            None,
            pipewire::stream::StreamFlags::AUTOCONNECT
                | pipewire::stream::StreamFlags::MAP_BUFFERS
                | pipewire::stream::StreamFlags::RT_PROCESS,
            &mut capture_params,
        )
        .expect("Failed to connect PipeWire capture stream");

    info!("PipeWire capture stream connected (target: {})", args.capture_target);

    // -----------------------------------------------------------------------
    // PipeWire registry listener for device hot-plug (Section 8.1)
    // -----------------------------------------------------------------------

    let (_registry, _registry_listener) = registry::register_registry_listener(
        &core,
        event_queue,
        conn_state,
        args.device_watch.clone(),
    );
    info!("PipeWire registry listener registered (watching: {})", args.device_watch);

    // Shutdown timer: poll the AtomicBool every 100ms and quit the PW loop.
    // We capture the raw pointer because MainLoop is not Clone.
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
    drop(_registry_listener);
    drop(_registry);
    drop(_capture_listener);
    drop(capture_stream);
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
    capture_buf: Arc<CaptureRingBuffer>,
    event_queue: Arc<DeviceEventQueue>,
    conn_state: Arc<CaptureConnectionState>,
    shutdown: Arc<AtomicBool>,
    max_level_dbfs: f64,
) {
    let listener = match TcpListener::bind(listen_addr) {
        Ok(l) => l,
        Err(e) => {
            error!("Failed to bind RPC server to {}: {}", listen_addr, e);
            return;
        }
    };

    // Set SO_REUSEADDR for quick restart.
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
                    &capture_buf,
                    &event_queue,
                    &conn_state,
                    &shutdown,
                    max_level_dbfs,
                    &mut latest_state,
                );
                info!("RPC client disconnected: {}", addr);
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                // No pending connection — sleep briefly to avoid busy-wait.
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
    capture_buf: &CaptureRingBuffer,
    event_queue: &DeviceEventQueue,
    conn_state: &CaptureConnectionState,
    shutdown: &AtomicBool,
    max_level_dbfs: f64,
    latest_state: &mut StateSnapshot,
) {
    if let Err(e) = stream.set_read_timeout(Some(Duration::from_millis(100))) {
        warn!("Failed to set read timeout: {}", e);
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

        // Poll state queue for updates.
        while let Some(snap) = state_queue.pop() {
            *latest_state = snap;
            // Send state broadcast to client.
            let broadcast = rpc::format_state_broadcast(latest_state);
            if write_line(&mut writer, &broadcast).is_err() {
                return; // Client disconnected.
            }
        }

        // Poll device event queue for hot-plug / xrun events.
        while let Some(event) = event_queue.pop() {
            let event_json = registry::format_device_event(&event);
            if write_line(&mut writer, &event_json).is_err() {
                return; // Client disconnected.
            }
        }

        // Read a line from the client.
        line_buf.clear();
        match reader.read_line(&mut line_buf) {
            Ok(0) => return, // EOF — client disconnected.
            Ok(_) => {
                let line = line_buf.trim();
                if line.is_empty() {
                    continue;
                }

                // Check line length (SEC-D037-03).
                if line.len() > MAX_LINE_LENGTH {
                    let resp = rpc::format_line_too_long();
                    if write_line(&mut writer, &resp).is_err() {
                        return;
                    }
                    continue;
                }

                // Parse and handle the command.
                let response = match rpc::parse_line(line) {
                    Ok(req) => {
                        let result =
                            rpc::handle_request(&req, cmd_queue, max_level_dbfs, latest_state, conn_state.is_connected());
                        match result {
                            rpc::HandleResult::Ack(cmd) => rpc::format_ack(&cmd),
                            rpc::HandleResult::Error(cmd, msg) => {
                                rpc::format_error(&cmd, &msg)
                            }
                            rpc::HandleResult::StatusJson(json) => json,
                            rpc::HandleResult::CaptureLevelJson(json) => json,
                            rpc::HandleResult::GetRecording => {
                                format_get_recording_response(capture_buf)
                            }
                        }
                    }
                    Err(err_response) => err_response,
                };

                if write_line(&mut writer, &response).is_err() {
                    return;
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock
                || e.kind() == std::io::ErrorKind::TimedOut =>
            {
                // Read timeout — go back to polling state queue.
                continue;
            }
            Err(e) => {
                warn!("RPC read error: {}", e);
                return;
            }
        }
    }
}

/// Write a JSON line to the TCP stream, appending newline.
fn write_line(writer: &mut TcpStream, line: &str) -> std::io::Result<()> {
    writer.write_all(line.as_bytes())?;
    writer.write_all(b"\n")?;
    writer.flush()
}

/// Format the get_recording response from the capture ring buffer.
///
/// Returns the captured audio as base64-encoded float32 little-endian PCM
/// per D-037 Section 7.3.
fn format_get_recording_response(capture_buf: &CaptureRingBuffer) -> String {
    match capture_buf.take_recording() {
        Some((samples, sample_rate)) => {
            let n_frames = samples.len();
            // Encode f32 samples as little-endian bytes, then base64.
            let mut bytes = Vec::with_capacity(n_frames * 4);
            for &s in &samples {
                bytes.extend_from_slice(&s.to_le_bytes());
            }
            let encoded = base64::engine::general_purpose::STANDARD.encode(&bytes);

            // Build JSON response per D-037 Section 7.3.
            let resp = serde_json::json!({
                "type": "ack",
                "cmd": "get_recording",
                "ok": true,
                "sample_rate": sample_rate,
                "channels": 1,
                "n_frames": n_frames,
                "data": encoded,
            });
            serde_json::to_string(&resp).unwrap_or_else(|_| {
                rpc::format_error("get_recording", "internal: failed to serialize recording")
            })
        }
        None => rpc::format_error("get_recording", "no recording available"),
    }
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
        "pi4audio-signal-gen starting: target={}, capture_target={}, \
         channels={}, rate={}, listen={}, max_level_dbfs={}, ramp_ms={}",
        args.target,
        args.capture_target,
        args.channels,
        args.rate,
        args.listen,
        args.max_level_dbfs,
        args.ramp_ms,
    );

    // Shared shutdown flag — set by signal handlers, polled by PW timer and RPC server.
    let shutdown = Arc::new(AtomicBool::new(false));

    // Register signal handlers for graceful shutdown.
    for sig in [signal_hook::consts::SIGTERM, signal_hook::consts::SIGINT] {
        if let Err(e) = signal_hook::flag::register(sig, shutdown.clone()) {
            warn!("Failed to register signal handler for {}: {}", sig, e);
        }
    }

    // Shared command queue (RPC -> RT) and state feedback queue (RT -> RPC).
    let cmd_queue = Arc::new(CommandQueue::new());
    let state_queue = Arc::new(StateQueue::new());

    // Shared capture ring buffer (D-037 Section 5.3).
    let capture_buf = Arc::new(CaptureRingBuffer::new(
        args.capture_buffer_secs,
        args.rate,
    ));
    info!(
        "Capture ring buffer: {}s at {}Hz = {} samples ({:.1} MB)",
        args.capture_buffer_secs,
        args.rate,
        capture_buf.capacity(),
        (capture_buf.capacity() * std::mem::size_of::<f32>()) as f64 / (1024.0 * 1024.0),
    );

    // Device event queue (PW registry -> RPC thread) and capture connection state.
    let event_queue = Arc::new(DeviceEventQueue::new());
    let conn_state = Arc::new(CaptureConnectionState::new());

    // Parse listen address.
    let (host, port) = parse_listen_addr(&args.listen);
    let rpc_addr = format!("{}:{}", host, port);

    // Spawn the RPC server thread.
    let rpc_cmd_queue = cmd_queue.clone();
    let rpc_state_queue = state_queue.clone();
    let rpc_capture_buf = capture_buf.clone();
    let rpc_event_queue = event_queue.clone();
    let rpc_conn_state = conn_state.clone();
    let rpc_shutdown = shutdown.clone();
    let max_level_dbfs = args.max_level_dbfs;
    let rpc_thread = std::thread::Builder::new()
        .name("rpc-server".into())
        .spawn(move || {
            run_rpc_server(
                &rpc_addr,
                rpc_cmd_queue,
                rpc_state_queue,
                rpc_capture_buf,
                rpc_event_queue,
                rpc_conn_state,
                rpc_shutdown,
                max_level_dbfs,
            );
        })
        .expect("Failed to spawn RPC server thread");

    // Run PipeWire main loop on the main thread (blocks until shutdown).
    run_pipewire(
        &args,
        cmd_queue.clone(),
        state_queue.clone(),
        capture_buf.clone(),
        event_queue.clone(),
        conn_state.clone(),
        shutdown.clone(),
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

    fn make_args(listen: &str, max_level_dbfs: f64) -> Args {
        Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: listen.into(),
            max_level_dbfs,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        }
    }

    // -----------------------------------------------------------------------
    // validate_args (preserved from SG-1)
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
    // ProcessState: command processing logic
    // -----------------------------------------------------------------------

    #[test]
    fn process_state_initial_is_stopped() {
        let state = ProcessState::new(8, 48000, -20.0, 20);
        assert_eq!(state.play_state, PlayState::Stopped);
        assert_eq!(state.active_signal, SignalType::Silence);
        assert_eq!(state.active_channels, 0);
    }

    #[test]
    fn play_command_activates_generator() {
        let mut state = ProcessState::new(2, 48000, -20.0, 20);
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
        let mut state = ProcessState::new(2, 48000, -20.0, 20);
        // First start playback.
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

        // Then stop.
        state.apply_command(Command {
            kind: CommandKind::Stop,
        });
        assert!(state.pending_stop, "Stop should set pending_stop");
        assert!(state.fade.is_active(), "Stop should initiate fade-out ramp");
    }

    #[test]
    fn set_frequency_updates_state() {
        let mut state = ProcessState::new(2, 48000, -20.0, 20);
        state.apply_command(Command {
            kind: CommandKind::SetFrequency { frequency: 440.0 },
        });
        assert_eq!(state.current_freq, 440.0);
    }

    #[test]
    fn set_channel_updates_state() {
        let mut state = ProcessState::new(8, 48000, -20.0, 20);
        state.apply_command(Command {
            kind: CommandKind::SetChannel { channels: 0b1111_0000 },
        });
        assert_eq!(state.active_channels, 0b1111_0000);
    }

    #[test]
    fn multi_command_drain_in_process() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let mut state = ProcessState::new(2, 48000, -20.0, 20);

        // Push multiple commands to simulate rapid-fire from RPC.
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

        // Process one quantum.
        let mut buf = vec![0.0f32; 512]; // 256 frames * 2 channels
        state.process(&mut buf, 256, &cmd_queue, &state_queue, None, None);

        // Both commands should have been applied.
        assert_eq!(state.active_signal, SignalType::Pink);
        assert_eq!(state.active_channels, 0b11);
        assert_eq!(state.play_state, PlayState::Playing);
    }

    #[test]
    fn process_generates_silence_when_stopped() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let mut state = ProcessState::new(2, 48000, -20.0, 20);

        let mut buf = vec![1.0f32; 512]; // pre-fill with non-zero
        state.process(&mut buf, 256, &cmd_queue, &state_queue, None, None);

        // All samples should be zero (silence).
        assert!(
            buf.iter().all(|&s| s == 0.0),
            "Stopped state should produce silence"
        );
    }

    #[test]
    fn process_pushes_state_snapshot() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let mut state = ProcessState::new(2, 48000, -20.0, 20);

        let mut buf = vec![0.0f32; 512];
        state.process(&mut buf, 256, &cmd_queue, &state_queue, None, None);

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
        let mut state = ProcessState::new(1, 48000, -20.0, 20);

        // Play a 0.01s burst (480 samples at 48kHz).
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

        // Process enough frames to exhaust the burst.
        let mut buf = vec![0.0f32; 480];
        state.process(&mut buf, 480, &cmd_queue, &state_queue, None, None);

        // Burst should have triggered pending_stop.
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
    // Capture integration: playrec starts capture recording
    // -----------------------------------------------------------------------

    #[test]
    fn playrec_starts_capture_recording() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let capture = CaptureRingBuffer::new(1, 48000);
        let mut state = ProcessState::new(1, 48000, -20.0, 20);

        cmd_queue
            .push(Command {
                kind: CommandKind::Playrec {
                    signal: SignalType::Sine,
                    channels: 0b01,
                    level_dbfs: -20.0,
                    frequency: 1000.0,
                    duration_secs: 0.1,
                    sweep_end_hz: 20000.0,
                },
            })
            .unwrap();

        let mut buf = vec![0.0f32; 256];
        state.process(&mut buf, 256, &cmd_queue, &state_queue, Some(&capture), None);

        assert!(capture.is_recording(), "Playrec should start capture recording");
        assert_eq!(state.play_state, PlayState::PlayrecInProgress);
        assert!(state.playrec_active, "playrec_active should be true");
    }

    #[test]
    fn start_capture_starts_recording() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let capture = CaptureRingBuffer::new(1, 48000);
        let mut state = ProcessState::new(1, 48000, -20.0, 20);

        cmd_queue
            .push(Command {
                kind: CommandKind::StartCapture,
            })
            .unwrap();

        let mut buf = vec![0.0f32; 256];
        state.process(&mut buf, 256, &cmd_queue, &state_queue, Some(&capture), None);

        assert!(capture.is_recording(), "StartCapture should start recording");
    }

    #[test]
    fn stop_capture_stops_recording() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let capture = CaptureRingBuffer::new(1, 48000);
        let mut state = ProcessState::new(1, 48000, -20.0, 20);

        // Start capture.
        cmd_queue
            .push(Command {
                kind: CommandKind::StartCapture,
            })
            .unwrap();
        let mut buf = vec![0.0f32; 256];
        state.process(&mut buf, 256, &cmd_queue, &state_queue, Some(&capture), None);
        assert!(capture.is_recording());

        // Write some samples to capture (simulating PW capture callback).
        capture.write_samples(&[0.1, 0.2, 0.3]);

        // Stop capture.
        cmd_queue
            .push(Command {
                kind: CommandKind::StopCapture,
            })
            .unwrap();
        state.process(&mut buf, 256, &cmd_queue, &state_queue, Some(&capture), None);
        assert!(!capture.is_recording());
        assert!(capture.is_complete(), "Capture should be complete after stop");
    }

    #[test]
    fn stop_during_playrec_discards_recording() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let capture = CaptureRingBuffer::new(1, 48000);
        let mut state = ProcessState::new(1, 48000, -20.0, 20);

        // Start playrec.
        cmd_queue
            .push(Command {
                kind: CommandKind::Playrec {
                    signal: SignalType::Sine,
                    channels: 0b01,
                    level_dbfs: -20.0,
                    frequency: 1000.0,
                    duration_secs: 1.0,
                    sweep_end_hz: 20000.0,
                },
            })
            .unwrap();
        let mut buf = vec![0.0f32; 256];
        state.process(&mut buf, 256, &cmd_queue, &state_queue, Some(&capture), None);
        assert!(capture.is_recording());

        // Write some samples.
        capture.write_samples(&[0.5; 100]);

        // User sends Stop during playrec -> discard partial recording.
        cmd_queue
            .push(Command {
                kind: CommandKind::Stop,
            })
            .unwrap();
        state.process(&mut buf, 256, &cmd_queue, &state_queue, Some(&capture), None);

        assert!(!capture.is_recording());
        assert!(
            !capture.is_complete(),
            "Partial recording should be discarded on Stop"
        );
        assert!(!state.playrec_active, "playrec_active should be cleared on Stop");
    }

    #[test]
    fn playrec_tail_stops_capture_after_playback() {
        let cmd_queue = CommandQueue::new();
        let state_queue = StateQueue::new();
        let capture = CaptureRingBuffer::new(1, 48000);
        let mut state = ProcessState::new(1, 48000, -20.0, 20);

        // Very short burst: 0.005s (240 samples at 48kHz).
        // Zero-length ramp so fade completes instantly within the same quantum.
        state.ramp_samples = 0;
        // Tail of 1024 samples -- larger than one 512-frame quantum so we can
        // observe it counting before it expires.
        state.playrec_tail_samples = 1024;

        cmd_queue
            .push(Command {
                kind: CommandKind::Playrec {
                    signal: SignalType::Sine,
                    channels: 0b01,
                    level_dbfs: -20.0,
                    frequency: 1000.0,
                    duration_secs: 0.005,
                    sweep_end_hz: 20000.0,
                },
            })
            .unwrap();

        // Process to exhaust burst. With ramp_samples=0, the fade-out completes
        // instantly and the tail countdown starts within the same quantum.
        let mut buf = vec![0.0f32; 512];
        state.process(&mut buf, 512, &cmd_queue, &state_queue, Some(&capture), None);
        // Write capture samples to simulate PW capture callback.
        capture.write_samples(&[0.1; 512]);

        // Playback should have stopped, tail countdown started.
        // After 512 frames, the 1024-sample tail has 512 remaining.
        assert!(state.playrec_tail_remaining.is_some(), "Tail should be counting");
        assert!(capture.is_recording(), "Capture should still be recording during tail");

        // Process enough frames to exhaust the remaining tail.
        let mut buf2 = vec![0.0f32; 512];
        state.process(&mut buf2, 512, &cmd_queue, &state_queue, Some(&capture), None);
        capture.write_samples(&[0.2; 512]);

        // Tail expired: capture should be stopped and complete.
        assert!(!state.playrec_active, "playrec_active should be false after tail");
        assert!(!capture.is_recording(), "Capture should stop after tail");
        assert!(capture.is_complete(), "Recording should be complete after tail");
    }

    #[test]
    fn snapshot_includes_capture_levels() {
        let capture = CaptureRingBuffer::new(1, 48000);
        let state = ProcessState::new(1, 48000, -20.0, 20);

        capture.update_levels(&[0.5; 100]);
        let snap = state.snapshot(Some(&capture), None);

        assert!((snap.capture_peak - 0.5).abs() < 1e-6, "peak: {}", snap.capture_peak);
        assert!((snap.capture_rms - 0.5).abs() < 1e-6, "rms: {}", snap.capture_rms);
    }

    #[test]
    fn snapshot_without_capture_has_zero_levels() {
        let state = ProcessState::new(1, 48000, -20.0, 20);
        let snap = state.snapshot(None, None);

        assert_eq!(snap.capture_peak, 0.0);
        assert_eq!(snap.capture_rms, 0.0);
    }

    #[test]
    fn snapshot_with_connected_capture() {
        let capture = CaptureRingBuffer::new(1, 48000);
        let conn = CaptureConnectionState::new();
        let state = ProcessState::new(1, 48000, -20.0, 20);

        conn.set_connected(47);
        let snap = state.snapshot(Some(&capture), Some(&conn));
        assert!(snap.capture_connected, "Should be connected");

        conn.set_disconnected();
        let snap = state.snapshot(Some(&capture), Some(&conn));
        assert!(!snap.capture_connected, "Should be disconnected");
    }

    // -----------------------------------------------------------------------
    // get_recording response format
    // -----------------------------------------------------------------------

    #[test]
    fn get_recording_returns_error_when_no_recording() {
        let capture = CaptureRingBuffer::new(1, 48000);
        let response = format_get_recording_response(&capture);
        assert!(response.contains("no recording available"));
        assert!(response.contains("\"ok\":false"));
    }

    #[test]
    fn get_recording_returns_base64_data() {
        let capture = CaptureRingBuffer::new(1, 48000);
        capture.start_recording();
        capture.write_samples(&[0.25, 0.5, 0.75]);
        capture.stop_recording();

        let response = format_get_recording_response(&capture);
        let v: serde_json::Value = serde_json::from_str(&response).unwrap();

        assert_eq!(v["type"], "ack");
        assert_eq!(v["cmd"], "get_recording");
        assert_eq!(v["ok"], true);
        assert_eq!(v["sample_rate"], 48000);
        assert_eq!(v["channels"], 1);
        assert_eq!(v["n_frames"], 3);

        // Decode base64 and verify samples.
        let encoded = v["data"].as_str().unwrap();
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .unwrap();
        assert_eq!(bytes.len(), 12); // 3 samples * 4 bytes

        let s0 = f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
        let s1 = f32::from_le_bytes([bytes[4], bytes[5], bytes[6], bytes[7]]);
        let s2 = f32::from_le_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]);

        assert!((s0 - 0.25).abs() < 1e-7);
        assert!((s1 - 0.5).abs() < 1e-7);
        assert!((s2 - 0.75).abs() < 1e-7);
    }

    #[test]
    fn get_recording_consumes_recording() {
        let capture = CaptureRingBuffer::new(1, 48000);
        capture.start_recording();
        capture.write_samples(&[0.1]);
        capture.stop_recording();

        // First call succeeds.
        let response = format_get_recording_response(&capture);
        assert!(response.contains("\"ok\":true"));

        // Second call fails -- recording consumed.
        let response2 = format_get_recording_response(&capture);
        assert!(response2.contains("no recording available"));
    }

    // --- BUG-SG12-5 + TK-236: build_audio_format regression tests ---

    #[test]
    fn build_audio_format_no_positions_size_and_alignment() {
        let pod = build_audio_format(8, 48000, &[]);
        assert_eq!(pod.len() % 8, 0, "SPA pod must be 8-byte aligned");
        // 5 properties * 24 bytes each = 120, plus 16 bytes header = 136.
        assert_eq!(pod.len(), 136);
    }

    #[test]
    fn build_audio_format_header_type() {
        let pod = build_audio_format(2, 44100, &[]);
        // Bytes 4..8 are the pod type (SPA_TYPE_Object = 15).
        let pod_type = u32::from_le_bytes(pod[4..8].try_into().unwrap());
        assert_eq!(pod_type, 15, "pod header type must be SPA_TYPE_Object");
    }

    #[test]
    fn build_audio_format_body_size() {
        let pod = build_audio_format(3, 48000, &[]);
        // Bytes 0..4 are the body size (total - 8 byte pod header).
        let body_size = u32::from_le_bytes(pod[0..4].try_into().unwrap());
        assert_eq!(body_size as usize, pod.len() - 8);
    }

    #[test]
    fn build_audio_format_channels_embedded_no_positions() {
        let pod = build_audio_format(8, 48000, &[]);
        // channels property value at: 16 + 4*24 + 16 = 128.
        let ch_val = u32::from_le_bytes(pod[128..132].try_into().unwrap());
        assert_eq!(ch_val, 8);
    }

    #[test]
    fn build_audio_format_rate_embedded() {
        let pod = build_audio_format(2, 96000, &[]);
        // rate property value at: 16 + 3*24 + 16 = 104.
        let rate_val = i32::from_le_bytes(pod[104..108].try_into().unwrap());
        assert_eq!(rate_val, 96000);
    }

    #[test]
    fn build_audio_format_mono_capture_with_position() {
        // Capture stream: 1 channel with MONO position.
        let pod = build_audio_format(1, 48000, &spa_channel::CAPTURE_MONO);
        assert_eq!(pod.len() % 8, 0, "SPA pod must be 8-byte aligned");
        // Should be larger than 136 (base) due to position property.
        assert!(pod.len() > 136);
        let body_size = u32::from_le_bytes(pod[0..4].try_into().unwrap());
        assert_eq!(body_size as usize, pod.len() - 8);
    }

    #[test]
    fn build_audio_format_8ch_with_positions() {
        // Playback stream: 8 channels with AUX0-AUX7 positions.
        let pod = build_audio_format(8, 48000, &spa_channel::PLAYBACK_8CH);
        assert_eq!(pod.len() % 8, 0, "SPA pod must be 8-byte aligned");
        // Base (136) + position property: 8 (key+flags) + 8 (array header)
        //   + 8 (child desc) + 32 (8*4 elements) = 56. But alignment...
        // Position property: key(4) + flags(4) + size(4) + type(4)
        //   + child_size(4) + child_type(4) + 8*4=32 elements = 56 bytes.
        // 56 % 8 == 0, no extra padding needed.
        assert!(pod.len() > 136);
        let body_size = u32::from_le_bytes(pod[0..4].try_into().unwrap());
        assert_eq!(body_size as usize, pod.len() - 8);
    }

    #[test]
    fn build_audio_format_positions_contain_aux_values() {
        // Verify AUX0-AUX7 position IDs are embedded in the pod.
        let pod = build_audio_format(8, 48000, &spa_channel::PLAYBACK_8CH);
        // Position array elements start after:
        //   16 (object header) + 5*24 (scalar properties) = 136
        //   + 8 (position key+flags) + 8 (array pod header+child desc) = 152
        // Actually: position property = key(4)+flags(4)+array_size(4)+array_type(4)
        //   +child_size(4)+child_type(4) = 24 bytes of overhead, then elements.
        // Offset of first element: 136 + 24 = 160.
        let first_pos = u32::from_le_bytes(pod[160..164].try_into().unwrap());
        assert_eq!(first_pos, spa_channel::AUX0, "First position should be AUX0");
        let last_pos = u32::from_le_bytes(pod[188..192].try_into().unwrap());
        assert_eq!(last_pos, spa_channel::AUX7, "Last position should be AUX7");
    }

    #[test]
    fn build_audio_format_mono_position_value() {
        let pod = build_audio_format(1, 48000, &spa_channel::CAPTURE_MONO);
        // Mono position element at offset 160.
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
