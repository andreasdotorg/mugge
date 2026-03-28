//! Declarative routing table — defines the complete link topology for each
//! operating mode.
//!
//! The routing table is compiled in (not loaded from a config file) because
//! it is tightly coupled to our specific PW node names and port names.
//! Adding a mode always requires new routing logic, so there is no benefit
//! to runtime configurability (architect guidance, GM-2).
//!
//! ## Modes
//!
//! - **Monitoring:** Default mode. Filter-chain active for speakers,
//!   no application linked, no measurement.
//! - **Dj:** Mixxx linked to filter-chain + headphones via USBStreamer.
//! - **Live:** Reaper linked to filter-chain + headphones + singer IEM
//!   + ADA8200 capture inputs.
//! - **Measurement:** Signal-gen → filter-chain, UMIK-1 capture active.
//!
//! ## Port naming (D-041)
//!
//! All channel references in the routing table use one-based indexing per
//! D-041. Application-specific port name mapping is handled by
//! [`AppPortNaming`] — each application's naming convention (Mixxx: `out_0`,
//! Reaper: `out1`, filter-chain: `playback_AUX0`) is translated from
//! canonical one-based channel numbers at link definition time.
//!
//! ## Design (D-039, D-040)
//!
//! GraphManager is the sole PipeWire session manager. No WirePlumber.
//! All application links are created and destroyed by GraphManager based
//! on the active mode's DesiredLink set.

use std::collections::HashMap;
use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};

/// Operating modes — exactly 4, known at compile time (architect: use enum).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    /// Default: filter-chain active for speakers, no app, no measurement.
    Monitoring,
    /// Mixxx linked to filter-chain + headphones.
    Dj,
    /// Reaper linked to filter-chain + headphones + singer IEM.
    Live,
    /// Signal-gen → filter-chain, UMIK-1 capture active.
    Measurement,
}

impl fmt::Display for Mode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Mode::Monitoring => write!(f, "monitoring"),
            Mode::Dj => write!(f, "dj"),
            Mode::Live => write!(f, "live"),
            Mode::Measurement => write!(f, "measurement"),
        }
    }
}

impl FromStr for Mode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "monitoring" => Ok(Mode::Monitoring),
            "dj" => Ok(Mode::Dj),
            "live" => Ok(Mode::Live),
            "measurement" => Ok(Mode::Measurement),
            _ => Err(format!(
                "unknown mode '{}', expected: monitoring, dj, live, measurement",
                s
            )),
        }
    }
}

impl Mode {
    /// All known modes, for iteration.
    pub const ALL: [Mode; 4] = [
        Mode::Monitoring,
        Mode::Dj,
        Mode::Live,
        Mode::Measurement,
    ];
}

/// How to match a PW node by its `node.name` property.
///
/// Exact match for nodes we control (signal-gen, pcm-bridge, filter-chain).
/// Prefix match for USB devices with ALSA-generated variable suffixes
/// (USBStreamer, UMIK-1) and JACK clients with potential instance suffixes
/// (Mixxx, REAPER).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", content = "value")]
pub enum NodeMatch {
    /// node.name must equal this value exactly.
    Exact(String),
    /// node.name must start with this prefix (USB devices, JACK clients).
    Prefix(String),
}

impl NodeMatch {
    /// Test whether a PW node name matches this pattern.
    pub fn matches(&self, node_name: &str) -> bool {
        match self {
            NodeMatch::Exact(expected) => node_name == expected,
            NodeMatch::Prefix(prefix) => node_name.starts_with(prefix),
        }
    }
}

impl fmt::Display for NodeMatch {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            NodeMatch::Exact(name) => write!(f, "{}", name),
            NodeMatch::Prefix(prefix) => write!(f, "{}*", prefix),
        }
    }
}

/// A desired PW link between two ports.
///
/// GraphManager reconciles the set of DesiredLinks for the active mode
/// against the actual PW graph state: creating missing links and
/// destroying links that are no longer desired.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DesiredLink {
    /// Output (source) node matcher.
    pub output_node: NodeMatch,
    /// Output port name (exact).
    pub output_port: String,
    /// Input (sink) node matcher.
    pub input_node: NodeMatch,
    /// Input port name (exact).
    pub input_port: String,
    /// If true, a missing endpoint does not block the mode transition
    /// or count as an error. Used for optional devices (UMIK-1, IEM).
    pub optional: bool,
}

impl fmt::Display for DesiredLink {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}:{} -> {}:{}{}",
            self.output_node,
            self.output_port,
            self.input_node,
            self.input_port,
            if self.optional { " (optional)" } else { "" },
        )
    }
}

/// Speaker topology for routing parameterization.
///
/// Captures the number of speaker channels processed by the convolver
/// (and routed to USBStreamer) plus the subset of those channels that
/// receive L+R mono sum fan-out (subwoofers).
///
/// ## Examples
///
/// 2-way (4ch): mains L/R on ch 1-2, subs on ch 3-4.
/// ```
/// SpeakerLayout { num_speaker_channels: 4, sub_channels: vec![3, 4], stereo_main_channels: vec![1, 2] }
/// ```
///
/// 3-way (6ch): subs L/R on ch 1-2, mids L/R on ch 3-4, HF L/R on ch 5-6.
/// ```
/// SpeakerLayout { num_speaker_channels: 6, sub_channels: vec![1, 2], stereo_main_channels: vec![3, 4, 5, 6] }
/// ```
#[derive(Debug, Clone)]
pub struct SpeakerLayout {
    /// Total speaker channels handled by the convolver (e.g., 4 for 2-way, 6 for 3-way).
    pub num_speaker_channels: u32,
    /// One-based channel numbers that receive L+R mono sum fan-out (subwoofer channels).
    /// These channels get 2 links each (Master L + Master R → convolver input).
    pub sub_channels: Vec<u32>,
    /// One-based channel numbers that receive 1:1 mapping from stereo master.
    /// For 2-way: [1, 2] (mains). For 3-way: all non-sub channels [3, 4, 5, 6].
    /// Each channel is mapped from Master L (ch 1) or Master R (ch 2) based on
    /// odd=L, even=R pairing.
    pub stereo_main_channels: Vec<u32>,
}

impl SpeakerLayout {
    /// Default 2-way layout: 4 speaker channels, subs on ch 3-4, mains on ch 1-2.
    pub fn two_way() -> Self {
        Self {
            num_speaker_channels: 4,
            sub_channels: vec![3, 4],
            stereo_main_channels: vec![1, 2],
        }
    }

    /// 3-way layout from workshop-c3d-elf-3way profile:
    /// Subs L/R on ch 1-2, Mids L/R on ch 3-4, HF L/R on ch 5-6.
    pub fn three_way_stereo() -> Self {
        Self {
            num_speaker_channels: 6,
            sub_channels: vec![1, 2],
            stereo_main_channels: vec![3, 4, 5, 6],
        }
    }

    /// Build layout from speaker profile channel assignments.
    ///
    /// `sub_channels`: 1-based channel numbers assigned to subwoofer role.
    /// `all_channels`: total speaker channel count (excludes monitoring/HP/IEM).
    /// Non-sub channels are treated as stereo main channels with 1:1 mapping.
    pub fn from_profile(num_speaker_channels: u32, sub_channels: Vec<u32>) -> Self {
        let stereo_main_channels: Vec<u32> = (1..=num_speaker_channels)
            .filter(|ch| !sub_channels.contains(ch))
            .collect();
        Self {
            num_speaker_channels,
            sub_channels,
            stereo_main_channels,
        }
    }
}

/// The complete routing table: all modes and their desired link sets.
pub struct RoutingTable {
    table: HashMap<Mode, Vec<DesiredLink>>,
}

// ---------------------------------------------------------------------------
// Well-known node names (from component configs)
// ---------------------------------------------------------------------------

/// Filter-chain capture sink (receives app audio).
/// From: configs/pipewire/30-filter-chain-convolver.conf capture.props.node.name
const CONVOLVER_IN: &str = "pi4audio-convolver";

/// Filter-chain playback source (feeds USBStreamer ch 0-3).
/// From: configs/pipewire/30-filter-chain-convolver.conf playback.props.node.name
const CONVOLVER_OUT: &str = "pi4audio-convolver-out";

/// USBStreamer playback node name prefix (ALSA-generated, variable suffix).
const USBSTREAMER_OUT_PREFIX: &str = "alsa_output.usb-MiniDSP_USBStreamer";

/// USBStreamer capture node name prefix.
const USBSTREAMER_IN_PREFIX: &str = "alsa_input.usb-MiniDSP_USBStreamer";

/// Signal generator playback node.
const SIGNAL_GEN: &str = "pi4audio-signal-gen";

/// Signal generator capture node (UMIK-1 target).
const SIGNAL_GEN_CAPTURE: &str = "pi4audio-signal-gen-capture";

/// UMIK-1 capture node name prefix.
const UMIK1_PREFIX: &str = "alsa_input.usb-miniDSP_Umik-1";

/// pcm-bridge node name (level metering tap).
/// D-043: GraphManager creates the links from the convolver's output
/// ports to pcm-bridge's input ports.
const PCM_BRIDGE: &str = "pi4audio-pcm-bridge";

/// Level-bridge instance monitoring software/app outputs.
/// D-043/US-084/F-124: Always-on level metering. 8 channels max (Reaper).
/// Links are mode-specific: taps the active app's output ports.
const LEVEL_BRIDGE_SW: &str = "pi4audio-level-bridge-sw";

/// Level-bridge instance monitoring hardware output (USBStreamer monitor ports).
/// D-043/US-084: Always-on level metering. 8 channels (USBStreamer has 8 outputs).
const LEVEL_BRIDGE_HW_OUT: &str = "pi4audio-level-bridge-hw-out";

/// Level-bridge instance monitoring hardware input (ADA8200 capture ports).
/// D-043/US-084: Always-on level metering. 8 channels (ADA8200 has 8 inputs).
const LEVEL_BRIDGE_HW_IN: &str = "pi4audio-level-bridge-hw-in";

/// Mixxx JACK client node name prefix (under pw-jack).
/// Prefix match because JACK clients may register with variable suffixes.
/// TODO: Verify exact Mixxx PW node name on Pi (`pw-jack mixxx`).
const MIXXX_PREFIX: &str = "Mixxx";

/// REAPER JACK client node name prefix (under pw-jack).
/// Prefix match because JACK clients may register with variable suffixes.
/// Verified on Pi: `pw-jack reaper` registers as "REAPER" (C-005).
const REAPER_PREFIX: &str = "REAPER";

/// ADA8200 capture node (8ch input via USBStreamer ADAT).
/// From: configs/pipewire/20-usbstreamer.conf node.name
/// Verified on Pi: exact name "ada8200-in" (C-005).
const ADA8200_IN: &str = "ada8200-in";

/// UMIK-1 loopback sink node (local-demo only, F-159).
/// In local-demo, a PW loopback module echoes audio from its sink input to
/// the UMIK-1 source so the measurement pipeline receives real audio instead
/// of silence. On production Pi (real UMIK-1 mic), this node does not exist
/// and the optional link is silently skipped.
const UMIK1_LOOPBACK_SINK: &str = "umik1-loopback-sink";

/// Room simulator convolver input (local-demo only, F-159).
/// Mono filter-chain convolver that applies a synthetic room IR between the
/// speaker convolver output and the UMIK-1 loopback sink.
const ROOM_SIM_IN: &str = "pi4audio-room-sim";

/// Room simulator convolver output (local-demo only, F-159).
const ROOM_SIM_OUT: &str = "pi4audio-room-sim-out";

// ---------------------------------------------------------------------------
// Port naming — D-041 one-based channel mapping
// ---------------------------------------------------------------------------

/// Application-specific port naming conventions.
///
/// Each audio application uses different port name formats. This enum
/// maps a canonical one-based channel number to the application's actual
/// PW port name string. Per D-041, the routing table thinks in one-based
/// channels; this layer handles the translation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppPortNaming {
    /// Mixxx via pw-jack: `out_0`, `out_1`, ... (zero-based, underscore).
    /// Channel 1 -> "out_0", channel 2 -> "out_1", etc.
    MixxxOutput,
    /// Reaper via pw-jack: `out1`, `out2`, ... (one-based, no underscore).
    /// Channel 1 -> "out1", channel 2 -> "out2", etc.
    ReaperOutput,
    /// Reaper via pw-jack (inputs): `in1`, `in2`, ... (one-based, no underscore).
    /// Channel 1 -> "in1", channel 2 -> "in2", etc.
    ReaperInput,
    /// PW filter-chain capture (Audio/Sink): `playback_AUX0`, `playback_AUX1`, ...
    /// Channel 1 -> "playback_AUX0", channel 2 -> "playback_AUX1", etc.
    ConvolverInput,
    /// PW filter-chain playback (source): `output_AUX0`, `output_AUX1`, ...
    /// Channel 1 -> "output_AUX0", channel 2 -> "output_AUX1", etc.
    ConvolverOutput,
    /// USBStreamer playback adapter: `playback_AUX0`, `playback_AUX1`, ...
    /// Channel 1 -> "playback_AUX0", channel 2 -> "playback_AUX1", etc.
    UsbStreamerPlayback,
    /// ADA8200 capture adapter: `capture_AUX0`, `capture_AUX1`, ...
    /// Channel 1 -> "capture_AUX0", channel 2 -> "capture_AUX1", etc.
    Ada8200Capture,
    /// Signal generator output: `output_AUX0`, `output_AUX1`, ...
    /// Channel 1 -> "output_AUX0", channel 2 -> "output_AUX1", etc.
    SignalGenOutput,
    /// Signal generator capture input: `input_MONO`.
    /// Only channel 1 is valid.
    SignalGenCaptureInput,
    /// UMIK-1 capture: `capture_FL`.
    /// The UMIK-1 is mono but ALSA/PipeWire presents it as stereo (FL/FR).
    /// We use only the left channel.
    Umik1Capture,
    /// pcm-bridge input: `input_1`, `input_2`, ...
    /// PipeWire creates one-based input ports for streams without position info.
    /// Channel 1 -> "input_1", channel 2 -> "input_2", etc.
    PcmBridgeInput,
    /// Convolver monitor ports: `monitor_AUX0`, `monitor_AUX1`, ...
    /// PW Audio/Sink nodes expose monitor_ ports that mirror their input.
    /// Channel 1 -> "monitor_AUX0", channel 2 -> "monitor_AUX1", etc.
    ConvolverMonitor,
    /// USBStreamer monitor ports: `monitor_AUX0`, `monitor_AUX1`, ...
    /// PW playback sink nodes expose monitor_ ports for the played signal.
    /// Channel 1 -> "monitor_AUX0", channel 2 -> "monitor_AUX1", etc.
    UsbStreamerMonitor,
    /// Level-bridge input: `input_1`, `input_2`, ...
    /// Same format as PcmBridgeInput (PW convention for no SPA positions).
    /// Channel 1 -> "input_1", channel 2 -> "input_2", etc.
    LevelBridgeInput,
    /// UMIK-1 loopback sink playback port: `playback_FL` (F-159).
    /// Local-demo only — loopback module's Audio/Sink capture side.
    /// Only channel 1 is valid.
    Umik1LoopbackPlayback,
}

impl AppPortNaming {
    /// Map a one-based channel number to the application's port name.
    ///
    /// # Panics
    /// Panics if `channel` is 0 (violates D-041 one-based convention).
    pub fn port_name(self, channel: u32) -> String {
        assert!(channel >= 1, "D-041: channel numbers are one-based, got 0");
        let zero_based = channel - 1;
        match self {
            AppPortNaming::MixxxOutput => format!("out_{}", zero_based),
            AppPortNaming::ReaperOutput => format!("out{}", channel),
            AppPortNaming::ReaperInput => format!("in{}", channel),
            AppPortNaming::ConvolverInput => format!("playback_AUX{}", zero_based),
            AppPortNaming::ConvolverOutput => format!("output_AUX{}", zero_based),
            AppPortNaming::UsbStreamerPlayback => format!("playback_AUX{}", zero_based),
            AppPortNaming::Ada8200Capture => format!("capture_AUX{}", zero_based),
            AppPortNaming::SignalGenOutput => format!("output_AUX{}", zero_based),
            AppPortNaming::SignalGenCaptureInput => {
                assert_eq!(channel, 1, "signal-gen capture is mono, only channel 1");
                "input_MONO".to_string()
            }
            AppPortNaming::Umik1Capture => {
                assert_eq!(channel, 1, "UMIK-1 is mono, only channel 1");
                "capture_FL".to_string()
            }
            AppPortNaming::PcmBridgeInput => format!("input_{}", channel),
            AppPortNaming::ConvolverMonitor => format!("monitor_AUX{}", zero_based),
            AppPortNaming::UsbStreamerMonitor => format!("monitor_AUX{}", zero_based),
            AppPortNaming::LevelBridgeInput => format!("input_{}", channel),
            AppPortNaming::Umik1LoopbackPlayback => {
                assert_eq!(channel, 1, "UMIK-1 loopback sink is mono, only channel 1");
                "playback_FL".to_string()
            }
        }
    }
}

impl RoutingTable {
    /// Build the production routing table for the default 2-way (4ch) layout.
    ///
    /// This is the single source of truth for all application routing.
    /// Node names and port names are compiled in because they are fixed
    /// by our component configurations.
    pub fn production() -> Self {
        Self::production_for(SpeakerLayout::two_way())
    }

    /// Build the production routing table for a given speaker layout.
    ///
    /// The layout determines:
    /// - How many convolver→USBStreamer links are created (num_speaker_channels)
    /// - Which convolver inputs get L+R mono sum fan-out (sub_channels)
    /// - Which convolver inputs get 1:1 stereo mapping (stereo_main_channels)
    /// - How many measurement fan-out links are created
    pub fn production_for(layout: SpeakerLayout) -> Self {
        let mut table = HashMap::new();

        table.insert(Mode::Monitoring, Self::monitoring_links(&layout));
        table.insert(Mode::Dj, Self::dj_links(&layout));
        table.insert(Mode::Live, Self::live_links(&layout));
        table.insert(Mode::Measurement, Self::measurement_links(&layout));

        Self { table }
    }

    /// Build a routing table from explicit entries (for testing).
    pub fn from_entries(entries: Vec<(Mode, Vec<DesiredLink>)>) -> Self {
        let table = entries.into_iter().collect();
        Self { table }
    }

    /// Get the desired links for a mode. Returns empty slice for unknown modes.
    pub fn links_for(&self, mode: Mode) -> &[DesiredLink] {
        self.table.get(&mode).map(|v| v.as_slice()).unwrap_or(&[])
    }

    /// Get all modes in the table.
    pub fn modes(&self) -> Vec<Mode> {
        self.table.keys().copied().collect()
    }

    // -------------------------------------------------------------------
    // Mode link definitions (private)
    // -------------------------------------------------------------------

    /// Monitoring mode: convolver output → USBStreamer (speaker channels).
    ///
    /// No application is linked. The convolver processes whatever is in
    /// its input buffers (silence if nothing is linked to it).
    ///
    /// Links: convolver-out ch 0..N → USBStreamer playback ch 0..N.
    /// F-131: No pcm-bridge links — no app to tap (spectrum would show
    /// post-gain signal at -100 dBFS, which is below display floor).
    fn monitoring_links(layout: &SpeakerLayout) -> Vec<DesiredLink> {
        // TODO: AE-F6 USBStreamer volume lock — when USBStreamer is first
        // detected, set volume to unity to prevent post-DSP clipping.
        let mut links = Self::convolver_to_usbstreamer_links(layout);
        // F-124: No level-bridge-sw in monitoring — no app to tap.
        // F-131: No pcm-bridge app tap in monitoring — no app to tap.
        // Always-on UMIK-1 capture for SPL metering (ch3, optional).
        links.push(Self::pcm_bridge_umik_link());
        links.extend(Self::level_bridge_hw_links());
        links
    }

    /// DJ mode: Mixxx → convolver → USBStreamer (speakers + headphones).
    ///
    /// Mixxx outputs 6 channels via pw-jack (verified on Pi, soundconfig.xml):
    ///   ch 1 = Master L, ch 2 = Master R,
    ///   ch 3-4 = unused (channel offset gap),
    ///   ch 5 = Headphone L, ch 6 = Headphone R.
    ///
    /// Stereo main channels (mains, mids, HF) get 1:1 mapping from Master L/R
    /// based on odd=L, even=R pairing. Sub channels get L+R mono sum fan-out
    /// (TK-239). PipeWire mixes multiple links to the same input port
    /// additively. The -6 dB mono sum compensation is baked into the sub FIR
    /// WAV coefficients (architect guidance).
    ///
    /// Headphone channels follow the speaker channels on the USBStreamer.
    /// For 2-way (4 speaker ch): HP on USBStreamer ch 5-6.
    /// For 3-way (6 speaker ch): HP on USBStreamer ch 7-8.
    fn dj_links(layout: &SpeakerLayout) -> Vec<DesiredLink> {
        let mut links = Vec::new();
        let mx = AppPortNaming::MixxxOutput;
        let cv_in = AppPortNaming::ConvolverInput;
        let usb = AppPortNaming::UsbStreamerPlayback;

        // Mixxx master → convolver stereo main channels (1:1 mapping).
        // Odd channel numbers map to Master L (ch 1), even to Master R (ch 2).
        for &ch in &layout.stereo_main_channels {
            let master_ch = if ch % 2 == 1 { 1 } else { 2 };
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(MIXXX_PREFIX.to_string()),
                output_port: mx.port_name(master_ch),
                input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                input_port: cv_in.port_name(ch),
                optional: false,
            });
        }

        // Mixxx master → convolver subs (explicit L+R mono sum, TK-239).
        // Both Master L (ch 1) and Master R (ch 2) feed each sub input.
        // PipeWire sums the two links at the input port.
        for &sub_ch in &layout.sub_channels {
            for master_ch in [1, 2] {
                links.push(DesiredLink {
                    output_node: NodeMatch::Prefix(MIXXX_PREFIX.to_string()),
                    output_port: mx.port_name(master_ch),
                    input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                    input_port: cv_in.port_name(sub_ch),
                    optional: false,
                });
            }
        }

        // Convolver → USBStreamer (all speaker channels: processed audio).
        links.extend(Self::convolver_to_usbstreamer_links(layout));

        // F-131: pcm-bridge taps Mixxx master L/R for spectrum display.
        links.extend(Self::pcm_bridge_app_tap_links(
            NodeMatch::Prefix(MIXXX_PREFIX.to_string()),
            AppPortNaming::MixxxOutput,
            2,
        ));

        // Mixxx headphones → USBStreamer direct (bypass convolver).
        // HP channels start at num_speaker_channels + 1.
        let hp_l = layout.num_speaker_channels + 1;
        let hp_r = layout.num_speaker_channels + 2;
        // Mixxx soundconfig.xml: channel offset places HP after speaker channels.
        // For 2-way: Mixxx ch 5-6 (out_4/out_5) → USBStreamer ch 5-6.
        // For 3-way: Mixxx ch 7-8 (out_6/out_7) → USBStreamer ch 7-8.
        for (mx_ch, usb_ch) in [(hp_l, hp_l), (hp_r, hp_r)] {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(MIXXX_PREFIX.to_string()),
                output_port: mx.port_name(mx_ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: usb.port_name(usb_ch),
                optional: false,
            });
        }

        // Always-on UMIK-1 capture for SPL metering (ch3, optional).
        links.push(Self::pcm_bridge_umik_link());

        // D-043/US-084: level-bridge always active.
        links.extend(Self::level_bridge_hw_links());
        // F-124: level-bridge-sw taps Mixxx outputs (8ch: consistent with 8-ch metering layout).
        // Mixxx populates 6 (Master L/R + gap 3-4 + HP L/R); ch 7-8 show silence.
        links.extend(Self::level_bridge_sw_links(
            NodeMatch::Prefix(MIXXX_PREFIX.to_string()),
            AppPortNaming::MixxxOutput,
            8,
        ));

        links
    }

    /// Live mode: Reaper → convolver → USBStreamer (speakers + HP + IEM)
    /// + ADA8200 capture → Reaper inputs (TK-239).
    ///
    /// Stereo main channels get 1:1 mapping from Master L/R (odd=L, even=R).
    /// Sub channels get L+R mono sum fan-out (TK-239). The -6 dB mono sum
    /// compensation is baked into the sub FIR WAV coefficients.
    ///
    /// HP and IEM bypass the convolver and go directly to USBStreamer.
    /// HP channels follow the speaker channels. IEM follows HP.
    ///
    /// ADA8200 8-channel capture feeds Reaper inputs for vocal mic,
    /// spare mic/line, and additional inputs (C-005 verified).
    fn live_links(layout: &SpeakerLayout) -> Vec<DesiredLink> {
        let mut links = Vec::new();
        let rp_out = AppPortNaming::ReaperOutput;
        let rp_in = AppPortNaming::ReaperInput;
        let cv_in = AppPortNaming::ConvolverInput;
        let usb = AppPortNaming::UsbStreamerPlayback;
        let ada = AppPortNaming::Ada8200Capture;

        // Reaper master → convolver stereo main channels (1:1 mapping).
        // Odd channel numbers map to Master L (ch 1), even to Master R (ch 2).
        for &ch in &layout.stereo_main_channels {
            let master_ch = if ch % 2 == 1 { 1 } else { 2 };
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                output_port: rp_out.port_name(master_ch),
                input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                input_port: cv_in.port_name(ch),
                optional: false,
            });
        }

        // Reaper master → convolver subs (explicit L+R mono sum, TK-239).
        // Both Master L (ch 1) and Master R (ch 2) feed each sub input.
        // PipeWire sums the two links at the input port.
        for &sub_ch in &layout.sub_channels {
            for master_ch in [1, 2] {
                links.push(DesiredLink {
                    output_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                    output_port: rp_out.port_name(master_ch),
                    input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                    input_port: cv_in.port_name(sub_ch),
                    optional: false,
                });
            }
        }

        // Convolver → USBStreamer (all speaker channels: processed audio).
        links.extend(Self::convolver_to_usbstreamer_links(layout));

        // F-131: pcm-bridge taps Reaper master L/R for spectrum display.
        links.extend(Self::pcm_bridge_app_tap_links(
            NodeMatch::Prefix(REAPER_PREFIX.to_string()),
            AppPortNaming::ReaperOutput,
            2,
        ));

        // Reaper headphones → USBStreamer direct (bypass convolver).
        // HP channels start at num_speaker_channels + 1.
        let hp_l = layout.num_speaker_channels + 1;
        let hp_r = layout.num_speaker_channels + 2;
        for ch in hp_l..=hp_r {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                output_port: rp_out.port_name(ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: usb.port_name(ch),
                optional: false,
            });
        }

        // Reaper singer IEM → USBStreamer direct (passthrough per D-011).
        // IEM channels start at num_speaker_channels + 3.
        let iem_l = layout.num_speaker_channels + 3;
        let iem_r = layout.num_speaker_channels + 4;
        for ch in iem_l..=iem_r {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                output_port: rp_out.port_name(ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: usb.port_name(ch),
                optional: true, // IEM is optional equipment
            });
        }

        // ADA8200 capture → Reaper inputs (TK-239, C-005 verified).
        // All 8 ADA8200 channels feed Reaper's 8 input ports.
        // Ch 1 = vocal mic, ch 2 = spare mic/line, ch 3-8 = available.
        for ch in 1..=8 {
            links.push(DesiredLink {
                output_node: NodeMatch::Exact(ADA8200_IN.to_string()),
                output_port: ada.port_name(ch),
                input_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                input_port: rp_in.port_name(ch),
                optional: false,
            });
        }

        // Always-on UMIK-1 capture for SPL metering (ch3, optional).
        links.push(Self::pcm_bridge_umik_link());

        // D-043/US-084: level-bridge always active.
        links.extend(Self::level_bridge_hw_links());
        // F-124: level-bridge-sw taps Reaper outputs (8ch: Master L/R + unused 3-4 + HP L/R + IEM L/R).
        links.extend(Self::level_bridge_sw_links(
            NodeMatch::Prefix(REAPER_PREFIX.to_string()),
            AppPortNaming::ReaperOutput,
            8,
        ));

        links
    }

    /// Measurement mode: signal-gen → convolver, UMIK-1 → signal-gen capture.
    ///
    /// F-097: Signal-gen is mono (1 output channel, output_AUX0). Its single
    /// output fans out to all N convolver inputs — PW duplicates the signal.
    /// The RPC `channels` bitmask selects which convolver inputs are active
    /// (e.g., play through left main only for per-speaker measurement).
    ///
    /// UMIK-1 captures the room response back to signal-gen for analysis.
    /// pcm-bridge taps the UMIK-1 capture for room-response metering (US-088).
    fn measurement_links(layout: &SpeakerLayout) -> Vec<DesiredLink> {
        let mut links = Vec::new();
        let sg = AppPortNaming::SignalGenOutput;
        let cv_in = AppPortNaming::ConvolverInput;
        let umik = AppPortNaming::Umik1Capture;
        let sg_cap = AppPortNaming::SignalGenCaptureInput;

        // F-097: Mono signal-gen output_AUX0 → all N convolver inputs.
        // PW fans out: each convolver input gets a copy of the same signal.
        for ch in 1..=layout.num_speaker_channels {
            links.push(DesiredLink {
                output_node: NodeMatch::Exact(SIGNAL_GEN.to_string()),
                output_port: sg.port_name(1), // always ch 1 (mono)
                input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                input_port: cv_in.port_name(ch),
                optional: false,
            });
        }

        // Convolver → USBStreamer (all speaker channels: measurement signal to speakers).
        links.extend(Self::convolver_to_usbstreamer_links(layout));

        // Always-on UMIK-1 capture for SPL metering (ch3, optional).
        links.push(Self::pcm_bridge_umik_link());

        // UMIK-1 → signal-gen capture (mono measurement mic).
        links.push(DesiredLink {
            output_node: NodeMatch::Prefix(UMIK1_PREFIX.to_string()),
            output_port: umik.port_name(1),
            input_node: NodeMatch::Exact(SIGNAL_GEN_CAPTURE.to_string()),
            input_port: sg_cap.port_name(1),
            optional: true, // UMIK-1 may not be plugged in
        });

        // F-159: Convolver → room-sim → UMIK-1 loopback (local-demo only).
        // In local-demo, a room-sim convolver applies a synthetic room IR
        // between the speaker convolver output and the UMIK-1 loopback sink.
        // This gives the measurement pipeline a realistic room response
        // without any special code paths. On production Pi (real mic, real
        // room), these nodes don't exist and the optional links are silently
        // skipped by the reconciler.
        let cv_out = AppPortNaming::ConvolverOutput;   // output_AUX0
        let rs_in = AppPortNaming::ConvolverInput;   // playback_AUX0
        let rs_out = AppPortNaming::ConvolverOutput;  // output_AUX0
        let lb = AppPortNaming::Umik1LoopbackPlayback;

        // Hop 1: convolver-out ch1 → room-sim input
        links.push(DesiredLink {
            output_node: NodeMatch::Exact(CONVOLVER_OUT.to_string()),
            output_port: cv_out.port_name(1), // output_AUX0 (left main)
            input_node: NodeMatch::Exact(ROOM_SIM_IN.to_string()),
            input_port: rs_in.port_name(1), // playback_AUX0
            optional: true, // only present in local-demo
        });

        // Hop 2: room-sim output → UMIK-1 loopback sink
        links.push(DesiredLink {
            output_node: NodeMatch::Exact(ROOM_SIM_OUT.to_string()),
            output_port: rs_out.port_name(1), // output_AUX0
            input_node: NodeMatch::Exact(UMIK1_LOOPBACK_SINK.to_string()),
            input_port: lb.port_name(1), // playback_FL
            optional: true, // only present in local-demo
        });

        // D-043/US-084: level-bridge always active.
        links.extend(Self::level_bridge_hw_links());
        // F-124: level-bridge-sw taps signal-gen output (1ch mono).
        links.extend(Self::level_bridge_sw_links(
            NodeMatch::Exact(SIGNAL_GEN.to_string()),
            AppPortNaming::SignalGenOutput,
            1,
        ));

        links
    }

    // -------------------------------------------------------------------
    // Shared link sets
    // -------------------------------------------------------------------

    /// UMIK-1 capture → pcm-bridge channel 3 (always-on SPL/spectrum source).
    ///
    /// UMIK-1 is routed to pcm-bridge input channel 3 in ALL modes. Channels
    /// 1-2 are reserved for the app stereo tap (DJ/Live) or measurement
    /// stimulus. Channel 3 is always the mic capture, avoiding signal mixing.
    /// The link is optional because UMIK-1 may not be plugged in.
    fn pcm_bridge_umik_link() -> DesiredLink {
        let umik = AppPortNaming::Umik1Capture;
        let pcm = AppPortNaming::PcmBridgeInput;
        DesiredLink {
            output_node: NodeMatch::Prefix(UMIK1_PREFIX.to_string()),
            output_port: umik.port_name(1),
            input_node: NodeMatch::Exact(PCM_BRIDGE.to_string()),
            input_port: pcm.port_name(3), // ch3: dedicated UMIK-1 channel
            optional: true,
        }
    }

    /// App output → pcm-bridge input (F-131).
    ///
    /// Taps the app's output ports at full level (pre-convolver, pre-gain)
    /// for spectrum display. The web UI deinterleaves L+R and averages to
    /// mono for FFT, so only the stereo master is needed (2 channels for
    /// DJ/Live, 1 for measurement).
    ///
    /// All links are optional because pcm-bridge may not be running.
    fn pcm_bridge_app_tap_links(
        source_node: NodeMatch,
        source_naming: AppPortNaming,
        num_channels: u32,
    ) -> Vec<DesiredLink> {
        let pcm = AppPortNaming::PcmBridgeInput;
        (1..=num_channels)
            .map(|ch| DesiredLink {
                output_node: source_node.clone(),
                output_port: source_naming.port_name(ch),
                input_node: NodeMatch::Exact(PCM_BRIDGE.to_string()),
                input_port: pcm.port_name(ch),
                optional: true,
            })
            .collect()
    }

    /// Convolver output → USBStreamer playback (ch 1..N speaker channels).
    /// Used by all modes (speakers always go through the convolver).
    ///
    /// Verified on Pi (C-005): filter-chain playback node uses
    /// `output_AUX0..output_AUXN` port names.
    fn convolver_to_usbstreamer_links(layout: &SpeakerLayout) -> Vec<DesiredLink> {
        let cv_out = AppPortNaming::ConvolverOutput;
        let usb = AppPortNaming::UsbStreamerPlayback;
        (1..=layout.num_speaker_channels)
            .map(|ch| DesiredLink {
                output_node: NodeMatch::Exact(CONVOLVER_OUT.to_string()),
                output_port: cv_out.port_name(ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: usb.port_name(ch),
                optional: false,
            })
            .collect()
    }

    /// Hardware level-bridge links — always present in every mode (D-043, US-084).
    ///
    /// Two hardware level-bridge instances tap the physical I/O:
    ///
    /// 1. **level-bridge-hw-out** (8ch): USBStreamer monitor_AUX0..7 → input_1..8.
    ///    Taps the exact signal reaching the DAC (post-crossover, post-gain).
    /// 2. **level-bridge-hw-in** (8ch): ADA8200 capture_AUX0..7 → input_1..8.
    ///    Taps hardware inputs (mics, line-in).
    ///
    /// level-bridge-sw is NOT included here — its links are mode-specific
    /// (F-124/F-125: must tap the active app's output ports, not the convolver
    /// monitor which only shows 4 speaker channels).
    ///
    /// All links are optional because level-bridge instances may not be running.
    /// Total: 8 + 8 = 16 links.
    fn level_bridge_hw_links() -> Vec<DesiredLink> {
        let usb_mon = AppPortNaming::UsbStreamerMonitor;
        let ada = AppPortNaming::Ada8200Capture;
        let lb_in = AppPortNaming::LevelBridgeInput;
        let mut links = Vec::with_capacity(16);

        // level-bridge-hw-out: USBStreamer monitor → level-bridge-hw-out input (8ch).
        for ch in 1..=8 {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                output_port: usb_mon.port_name(ch),
                input_node: NodeMatch::Exact(LEVEL_BRIDGE_HW_OUT.to_string()),
                input_port: lb_in.port_name(ch),
                optional: true,
            });
        }

        // level-bridge-hw-in: ADA8200 capture → level-bridge-hw-in input (8ch).
        for ch in 1..=8 {
            links.push(DesiredLink {
                output_node: NodeMatch::Exact(ADA8200_IN.to_string()),
                output_port: ada.port_name(ch),
                input_node: NodeMatch::Exact(LEVEL_BRIDGE_HW_IN.to_string()),
                input_port: lb_in.port_name(ch),
                optional: true,
            });
        }

        links
    }

    /// level-bridge-sw links for a specific app (F-124/F-125).
    ///
    /// Taps the app's output ports so the SW meters show all channels
    /// the app produces (including HP, IEM), not just the 4 convolver
    /// speaker channels.
    ///
    /// All links are optional because level-bridge-sw may not be running.
    fn level_bridge_sw_links(
        source_node: NodeMatch,
        source_naming: AppPortNaming,
        num_channels: u32,
    ) -> Vec<DesiredLink> {
        let lb_in = AppPortNaming::LevelBridgeInput;
        (1..=num_channels)
            .map(|ch| DesiredLink {
                output_node: source_node.clone(),
                output_port: source_naming.port_name(ch),
                input_node: NodeMatch::Exact(LEVEL_BRIDGE_SW.to_string()),
                input_port: lb_in.port_name(ch),
                optional: true,
            })
            .collect()
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------------
    // Mode
    // -----------------------------------------------------------------------

    #[test]
    fn mode_display() {
        assert_eq!(Mode::Monitoring.to_string(), "monitoring");
        assert_eq!(Mode::Dj.to_string(), "dj");
        assert_eq!(Mode::Live.to_string(), "live");
        assert_eq!(Mode::Measurement.to_string(), "measurement");
    }

    #[test]
    fn mode_all_has_four_variants() {
        assert_eq!(Mode::ALL.len(), 4);
    }

    #[test]
    fn mode_serde_roundtrip() {
        for mode in Mode::ALL {
            let json = serde_json::to_string(&mode).unwrap();
            let parsed: Mode = serde_json::from_str(&json).unwrap();
            assert_eq!(parsed, mode);
        }
    }

    #[test]
    fn mode_serde_lowercase() {
        let json = serde_json::to_string(&Mode::Monitoring).unwrap();
        assert_eq!(json, "\"monitoring\"");
    }

    // -----------------------------------------------------------------------
    // NodeMatch
    // -----------------------------------------------------------------------

    #[test]
    fn node_match_exact_matches() {
        let m = NodeMatch::Exact("pi4audio-signal-gen".to_string());
        assert!(m.matches("pi4audio-signal-gen"));
        assert!(!m.matches("pi4audio-signal-gen-capture"));
        assert!(!m.matches("other-node"));
    }

    #[test]
    fn node_match_prefix_matches() {
        let m = NodeMatch::Prefix("alsa_output.usb-MiniDSP_USBStreamer".to_string());
        assert!(m.matches("alsa_output.usb-MiniDSP_USBStreamer-00.analog-stereo"));
        assert!(m.matches("alsa_output.usb-MiniDSP_USBStreamer-01.pro-output-0"));
        assert!(!m.matches("alsa_input.usb-miniDSP_Umik-1"));
    }

    #[test]
    fn node_match_exact_display() {
        let m = NodeMatch::Exact("pi4audio-convolver".to_string());
        assert_eq!(m.to_string(), "pi4audio-convolver");
    }

    #[test]
    fn node_match_prefix_display() {
        let m = NodeMatch::Prefix("alsa_output.usb-MiniDSP".to_string());
        assert_eq!(m.to_string(), "alsa_output.usb-MiniDSP*");
    }

    // -----------------------------------------------------------------------
    // DesiredLink
    // -----------------------------------------------------------------------

    #[test]
    fn desired_link_display_required() {
        let link = DesiredLink {
            output_node: NodeMatch::Exact("signal-gen".to_string()),
            output_port: "output_AUX0".to_string(),
            input_node: NodeMatch::Exact("convolver".to_string()),
            input_port: "input_0".to_string(),
            optional: false,
        };
        assert_eq!(
            link.to_string(),
            "signal-gen:output_AUX0 -> convolver:input_0"
        );
    }

    #[test]
    fn desired_link_display_optional() {
        let link = DesiredLink {
            output_node: NodeMatch::Exact("umik-1".to_string()),
            output_port: "capture_FL".to_string(),
            input_node: NodeMatch::Exact("signal-gen-capture".to_string()),
            input_port: "input_MONO".to_string(),
            optional: true,
        };
        assert!(link.to_string().contains("(optional)"));
    }

    // -----------------------------------------------------------------------
    // RoutingTable
    // -----------------------------------------------------------------------

    #[test]
    fn production_table_has_all_modes() {
        let table = RoutingTable::production();
        for mode in Mode::ALL {
            // All modes exist in the table (even if links are empty placeholders).
            let _ = table.links_for(mode);
        }
    }

    #[test]
    fn production_table_modes_count() {
        let table = RoutingTable::production();
        assert_eq!(table.modes().len(), 4);
    }

    // -----------------------------------------------------------------------
    // Production routing entries
    // -----------------------------------------------------------------------

    #[test]
    fn monitoring_has_21_links() {
        // convolver-out → USBStreamer ch 0-3 (4)
        // + UMIK-1 → pcm-bridge ch3 (1, always-on)
        // + level-bridge-hw-out (8) + level-bridge-hw-in (8) = 21.
        // F-124: No level-bridge-sw in monitoring (no app to tap).
        // F-131: No pcm-bridge app tap in monitoring (no app to tap).
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Monitoring).len(), 21);
    }

    #[test]
    fn dj_has_39_links() {
        // Mixxx → convolver mains (2) + Mixxx → convolver subs fan-out (4)
        // + convolver → USBStreamer (4) + F-131: Mixxx → pcm-bridge stereo (2)
        // + Mixxx → USBStreamer HP (2)
        // + UMIK-1 → pcm-bridge ch3 (1, always-on)
        // + level-bridge-hw-out (8) + level-bridge-hw-in (8)
        // + F-124: Mixxx → level-bridge-sw (8: consistent 8-ch metering) = 39.
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Dj).len(), 39);
    }

    #[test]
    fn live_has_49_links() {
        // REAPER → convolver mains (2) + REAPER → convolver subs fan-out (4)
        // + convolver → USBStreamer (4) + F-131: REAPER → pcm-bridge stereo (2)
        // + REAPER → USBStreamer HP (2) + REAPER → USBStreamer IEM (2)
        // + ADA8200 → REAPER capture (8)
        // + UMIK-1 → pcm-bridge ch3 (1, always-on)
        // + level-bridge-hw-out (8) + level-bridge-hw-in (8)
        // + F-124: REAPER → level-bridge-sw (8) = 49.
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Live).len(), 49);
    }

    #[test]
    fn measurement_has_29_links() {
        // F-097: signal-gen mono fan-out → convolver (4) + convolver → USBStreamer (4)
        // + US-088: UMIK-1 → pcm-bridge (1) + UMIK-1 → signal-gen-capture (1)
        // + level-bridge-hw-out (8) + level-bridge-hw-in (8)
        // + F-124: signal-gen → level-bridge-sw (1)
        // + F-159: convolver→room-sim (1) + room-sim→UMIK-1 loopback (1) = 29.
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Measurement).len(), 29);
    }

    #[test]
    fn live_iem_links_are_optional() {
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        // IEM links (out7, out8 → USBStreamer AUX6, AUX7) should be optional.
        // Filter to USBStreamer target only (F-124: out7/out8 also go to level-bridge-sw).
        let iem_links: Vec<_> = live_links
            .iter()
            .filter(|l| {
                (l.output_port == "out7" || l.output_port == "out8")
                    && matches!(&l.input_node, NodeMatch::Prefix(p) if p.starts_with("alsa_output"))
            })
            .collect();
        assert_eq!(iem_links.len(), 2);
        assert!(iem_links.iter().all(|l| l.optional));
    }

    #[test]
    fn measurement_umik1_links_are_optional() {
        // US-088: UMIK-1 has 2 links: → signal-gen-capture + → pcm-bridge.
        let table = RoutingTable::production();
        let meas_links = table.links_for(Mode::Measurement);
        let umik_links: Vec<_> = meas_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p.contains("Umik")))
            .collect();
        assert_eq!(umik_links.len(), 2);
        assert!(umik_links.iter().all(|l| l.optional));
    }

    #[test]
    fn pcm_bridge_links_per_mode() {
        // F-131: pcm-bridge taps app output (stereo master) for spectrum on ch1-2.
        // UMIK-1 always-on tap on ch3 in all modes.
        // Monitoring: 1 (UMIK-1 only). DJ/Live: 3 (stereo L/R + UMIK-1).
        // Measurement: 1 (UMIK-1 ch3; no app tap).
        let table = RoutingTable::production();
        for mode in Mode::ALL {
            let links = table.links_for(mode);
            let pcm_links: Vec<_> = links
                .iter()
                .filter(|l| {
                    matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-pcm-bridge")
                })
                .collect();
            let expected = match mode {
                Mode::Monitoring => 1,   // UMIK-1 ch3 only (no app to tap)
                Mode::Measurement => 1,  // UMIK-1 ch3 only (no app tap in measurement)
                _ => 3,                  // F-131: stereo master L/R + UMIK-1 ch3
            };
            assert_eq!(
                pcm_links.len(),
                expected,
                "Mode {} should have {} pcm-bridge links",
                mode,
                expected,
            );
            // All pcm-bridge links are optional (pcm-bridge may not be running).
            assert!(
                pcm_links.iter().all(|l| l.optional),
                "pcm-bridge links should be optional in mode {}",
                mode,
            );
        }
    }

    #[test]
    fn pcm_bridge_monitoring_has_umik_link() {
        // Monitoring mode has 1 pcm-bridge link: UMIK-1 ch3 (always-on).
        // No app tap (F-131: no app to tap).
        let table = RoutingTable::production();
        let links = table.links_for(Mode::Monitoring);
        let pcm_links: Vec<_> = links
            .iter()
            .filter(|l| {
                matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-pcm-bridge")
            })
            .collect();
        assert_eq!(pcm_links.len(), 1);
        assert!(matches!(&pcm_links[0].output_node, NodeMatch::Prefix(p) if p.contains("Umik")));
        assert_eq!(pcm_links[0].input_port, "input_3");
        assert!(pcm_links[0].optional);
    }

    #[test]
    fn pcm_bridge_dj_taps_mixxx_stereo() {
        // F-131: DJ mode taps Mixxx master L/R for spectrum display (ch1-2).
        // Plus always-on UMIK-1 on ch3.
        let table = RoutingTable::production();
        let links = table.links_for(Mode::Dj);
        let pcm_links: Vec<_> = links
            .iter()
            .filter(|l| {
                matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-pcm-bridge")
            })
            .collect();
        assert_eq!(pcm_links.len(), 3); // Mixxx L + Mixxx R + UMIK-1
        // First two links: Mixxx master L/R.
        assert!(matches!(&pcm_links[0].output_node, NodeMatch::Prefix(p) if p == "Mixxx"));
        assert_eq!(pcm_links[0].output_port, "out_0");
        assert_eq!(pcm_links[0].input_port, "input_1");
        assert!(matches!(&pcm_links[1].output_node, NodeMatch::Prefix(p) if p == "Mixxx"));
        assert_eq!(pcm_links[1].output_port, "out_1");
        assert_eq!(pcm_links[1].input_port, "input_2");
        // Third link: UMIK-1 on ch3.
        assert!(matches!(&pcm_links[2].output_node, NodeMatch::Prefix(p) if p.contains("Umik")));
        assert_eq!(pcm_links[2].input_port, "input_3");
    }

    #[test]
    fn pcm_bridge_measurement_taps_umik1() {
        // UMIK-1 always-on tap on pcm-bridge ch3 (consistent across all modes).
        let table = RoutingTable::production();
        let links = table.links_for(Mode::Measurement);
        let pcm_links: Vec<_> = links
            .iter()
            .filter(|l| {
                matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-pcm-bridge")
            })
            .collect();
        assert_eq!(pcm_links.len(), 1, "UMIK-1 mono → 1 pcm-bridge link");
        assert!(
            matches!(&pcm_links[0].output_node, NodeMatch::Prefix(p) if p.contains("Umik")),
            "Measurement pcm-bridge link should come from UMIK-1, got: {}",
            pcm_links[0].output_node,
        );
        assert_eq!(pcm_links[0].output_port, "capture_FL", "UMIK-1 capture port (FL channel)");
        assert_eq!(pcm_links[0].input_port, "input_3", "pcm-bridge ch3 (dedicated UMIK-1)");
    }

    #[test]
    fn all_modes_have_level_bridge_links() {
        // D-043/US-084/F-124: level-bridge links in all modes.
        // hw-out (8) + hw-in (8) = 16 in every mode.
        // sw links are mode-specific: Monitoring=0, DJ=4, Live=8, Measurement=1.
        let table = RoutingTable::production();
        for mode in Mode::ALL {
            let links = table.links_for(mode);
            let lb_links: Vec<_> = links
                .iter()
                .filter(|l| {
                    matches!(&l.input_node, NodeMatch::Exact(n) if n.starts_with("pi4audio-level-bridge"))
                })
                .collect();
            let expected_sw = match mode {
                Mode::Monitoring => 0,   // no app to tap
                Mode::Dj => 8,           // Mixxx 8ch (consistent with 8-ch metering layout)
                Mode::Live => 8,         // Reaper 8ch
                Mode::Measurement => 1,  // signal-gen mono
            };
            assert_eq!(
                lb_links.len(),
                16 + expected_sw,
                "Mode {} should have {} level-bridge links (16 hw + {} sw)",
                mode, 16 + expected_sw, expected_sw,
            );
            // All level-bridge links are optional (instances may not be running).
            assert!(
                lb_links.iter().all(|l| l.optional),
                "level-bridge links should be optional in mode {}",
                mode,
            );
        }
    }

    #[test]
    fn level_bridge_sw_taps_app_outputs() {
        // F-124: level-bridge-sw taps the active app's output ports per mode.
        let table = RoutingTable::production();

        // Monitoring: no level-bridge-sw links (no app).
        let mon_sw: Vec<_> = table.links_for(Mode::Monitoring).iter()
            .filter(|l| matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-level-bridge-sw"))
            .collect();
        assert_eq!(mon_sw.len(), 0, "Monitoring should have 0 level-bridge-sw links");

        // DJ: Mixxx 8ch (out_0..out_7 → input_1..8, consistent 8-ch metering).
        // Mixxx populates 6 (Master L/R + gap 3-4 + HP L/R); ch 7-8 show silence.
        let dj_sw: Vec<_> = table.links_for(Mode::Dj).iter()
            .filter(|l| matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-level-bridge-sw"))
            .collect();
        assert_eq!(dj_sw.len(), 8);
        for (i, link) in dj_sw.iter().enumerate() {
            assert_eq!(link.output_port, format!("out_{}", i));
            assert_eq!(link.input_port, format!("input_{}", i + 1));
            assert!(matches!(&link.output_node, NodeMatch::Prefix(p) if p == "Mixxx"));
        }

        // Live: Reaper 8ch (out1..out8 → input_1..8).
        let live_sw: Vec<_> = table.links_for(Mode::Live).iter()
            .filter(|l| matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-level-bridge-sw"))
            .collect();
        assert_eq!(live_sw.len(), 8);
        for (i, link) in live_sw.iter().enumerate() {
            assert_eq!(link.output_port, format!("out{}", i + 1));
            assert_eq!(link.input_port, format!("input_{}", i + 1));
            assert!(matches!(&link.output_node, NodeMatch::Prefix(p) if p == "REAPER"));
        }

        // Measurement: signal-gen 1ch (output_AUX0 → input_1).
        let meas_sw: Vec<_> = table.links_for(Mode::Measurement).iter()
            .filter(|l| matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-level-bridge-sw"))
            .collect();
        assert_eq!(meas_sw.len(), 1);
        assert_eq!(meas_sw[0].output_port, "output_AUX0");
        assert_eq!(meas_sw[0].input_port, "input_1");
        assert!(matches!(&meas_sw[0].output_node, NodeMatch::Exact(n) if n == "pi4audio-signal-gen"));
    }

    #[test]
    fn level_bridge_hw_out_taps_usbstreamer_monitor() {
        // level-bridge-hw-out taps USBStreamer's monitor ports (8ch).
        let table = RoutingTable::production();
        let links = table.links_for(Mode::Monitoring);
        let hw_out_links: Vec<_> = links
            .iter()
            .filter(|l| {
                matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-level-bridge-hw-out")
            })
            .collect();
        assert_eq!(hw_out_links.len(), 8);
        for (i, link) in hw_out_links.iter().enumerate() {
            assert_eq!(link.output_port, format!("monitor_AUX{}", i));
            assert_eq!(link.input_port, format!("input_{}", i + 1));
            assert!(matches!(&link.output_node, NodeMatch::Prefix(p) if p.starts_with("alsa_output.usb-MiniDSP_USBStreamer")));
        }
    }

    #[test]
    fn level_bridge_hw_in_taps_ada8200_capture() {
        // level-bridge-hw-in taps ADA8200 capture ports (8ch).
        let table = RoutingTable::production();
        let links = table.links_for(Mode::Monitoring);
        let hw_in_links: Vec<_> = links
            .iter()
            .filter(|l| {
                matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-level-bridge-hw-in")
            })
            .collect();
        assert_eq!(hw_in_links.len(), 8);
        for (i, link) in hw_in_links.iter().enumerate() {
            assert_eq!(link.output_port, format!("capture_AUX{}", i));
            assert_eq!(link.input_port, format!("input_{}", i + 1));
            assert!(matches!(&link.output_node, NodeMatch::Exact(n) if n == "ada8200-in"));
        }
    }

    #[test]
    fn all_modes_share_convolver_to_usbstreamer() {
        // Every mode should have the 4 convolver → USBStreamer links.
        let table = RoutingTable::production();
        for mode in Mode::ALL {
            let links = table.links_for(mode);
            let conv_to_usb: Vec<_> = links
                .iter()
                .filter(|l| {
                    matches!(&l.output_node, NodeMatch::Exact(n) if n == "pi4audio-convolver-out")
                        && matches!(&l.input_node, NodeMatch::Prefix(p) if p.starts_with("alsa_output.usb-MiniDSP_USBStreamer"))
                })
                .collect();
            assert_eq!(
                conv_to_usb.len(),
                4,
                "Mode {} should have 4 convolver→USBStreamer links",
                mode
            );
        }
    }

    #[test]
    fn from_entries_roundtrip() {
        let table = RoutingTable::from_entries(vec![
            (Mode::Monitoring, vec![]),
            (Mode::Dj, vec![DesiredLink {
                output_node: NodeMatch::Exact("test".to_string()),
                output_port: "out_0".to_string(),
                input_node: NodeMatch::Exact("sink".to_string()),
                input_port: "in_0".to_string(),
                optional: false,
            }]),
        ]);
        assert_eq!(table.links_for(Mode::Monitoring).len(), 0);
        assert_eq!(table.links_for(Mode::Dj).len(), 1);
        assert_eq!(table.links_for(Mode::Live).len(), 0); // not in table
    }

    // -----------------------------------------------------------------------
    // Port name verification (GM-4)
    // -----------------------------------------------------------------------

    #[test]
    fn convolver_capture_uses_playback_aux_ports() {
        // Audio/Sink nodes get playback_ prefixed ports per PW convention.
        let table = RoutingTable::production();
        let meas_links = table.links_for(Mode::Measurement);
        let conv_input_links: Vec<_> = meas_links
            .iter()
            .filter(|l| matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-convolver"))
            .collect();
        assert_eq!(conv_input_links.len(), 4);
        for link in &conv_input_links {
            assert!(
                link.input_port.starts_with("playback_AUX"),
                "Convolver capture port should use playback_AUX prefix, got: {}",
                link.input_port
            );
        }
    }

    #[test]
    fn convolver_output_uses_output_aux_ports() {
        // Convolver playback source uses output_AUX prefix.
        let table = RoutingTable::production();
        let mon_links = table.links_for(Mode::Monitoring);
        for link in mon_links {
            if matches!(&link.output_node, NodeMatch::Exact(n) if n == "pi4audio-convolver-out") {
                assert!(
                    link.output_port.starts_with("output_AUX"),
                    "Convolver output port should use output_AUX prefix, got: {}",
                    link.output_port
                );
            }
        }
    }

    #[test]
    fn usbstreamer_uses_playback_aux_ports() {
        // USBStreamer playback adapter gets playback_AUX ports.
        let table = RoutingTable::production();
        let mon_links = table.links_for(Mode::Monitoring);
        for link in mon_links {
            if matches!(&link.input_node, NodeMatch::Prefix(p) if p.starts_with("alsa_output.usb-MiniDSP")) {
                assert!(
                    link.input_port.starts_with("playback_AUX"),
                    "USBStreamer port should use playback_AUX prefix, got: {}",
                    link.input_port
                );
            }
        }
    }

    #[test]
    fn signal_gen_uses_output_aux_ports() {
        // F-097: Signal-gen is mono — all links use output_AUX0.
        // 4 fan-out links to convolver
        // + F-124: 1 link to level-bridge-sw = 5.
        // (US-088: pcm-bridge now taps UMIK-1, not signal-gen.)
        let table = RoutingTable::production();
        let meas_links = table.links_for(Mode::Measurement);
        let siggen_links: Vec<_> = meas_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Exact(n) if n == "pi4audio-signal-gen"))
            .collect();
        assert_eq!(siggen_links.len(), 5);
        for link in &siggen_links {
            assert_eq!(
                link.output_port, "output_AUX0",
                "F-097: mono signal-gen should only use output_AUX0, got: {}",
                link.output_port
            );
        }
    }

    #[test]
    fn signal_gen_capture_uses_input_mono_port() {
        // Signal-gen capture uses MONO position → input_MONO.
        let table = RoutingTable::production();
        let meas_links = table.links_for(Mode::Measurement);
        let capture_links: Vec<_> = meas_links
            .iter()
            .filter(|l| matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-signal-gen-capture"))
            .collect();
        assert_eq!(capture_links.len(), 1);
        assert_eq!(capture_links[0].input_port, "input_MONO");
    }

    #[test]
    fn umik1_uses_capture_mono_port() {
        // US-088: 2 UMIK-1 links (→ signal-gen-capture + → pcm-bridge), both use capture_FL.
        let table = RoutingTable::production();
        let meas_links = table.links_for(Mode::Measurement);
        let umik_links: Vec<_> = meas_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p.contains("Umik")))
            .collect();
        assert_eq!(umik_links.len(), 2);
        assert!(umik_links.iter().all(|l| l.output_port == "capture_FL"));
    }

    #[test]
    fn mixxx_uses_prefix_matching() {
        let table = RoutingTable::production();
        let dj_links = table.links_for(Mode::Dj);
        let mixxx_links: Vec<_> = dj_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p == "Mixxx"))
            .collect();
        // 2 mains + 4 sub fan-out + 2 HP + F-131: 2 pcm-bridge stereo
        // + F-124: 8 level-bridge-sw = 18
        assert_eq!(mixxx_links.len(), 18);
    }

    #[test]
    fn dj_sub_mono_sum_fan_out() {
        // Each sub convolver input (AUX2, AUX3) receives links from BOTH
        // Mixxx Master L (out_0) and Master R (out_1) for mono sum.
        let table = RoutingTable::production();
        let dj_links = table.links_for(Mode::Dj);

        for sub_aux in ["AUX2", "AUX3"] {
            let sub_links: Vec<_> = dj_links
                .iter()
                .filter(|l| {
                    matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-convolver")
                        && l.input_port == format!("playback_{}", sub_aux)
                })
                .collect();
            assert_eq!(
                sub_links.len(),
                2,
                "Sub input {} should have 2 fan-out links (L+R mono sum)",
                sub_aux,
            );
            // One from out_0 (Master L), one from out_1 (Master R).
            let ports: Vec<&str> = sub_links.iter().map(|l| l.output_port.as_str()).collect();
            assert!(ports.contains(&"out_0"), "Missing Master L for {}", sub_aux);
            assert!(ports.contains(&"out_1"), "Missing Master R for {}", sub_aux);
        }
    }

    #[test]
    fn dj_mixxx_port_names_use_out_prefix() {
        // Mixxx JACK ports are out_0..out_3 (verified on Pi, GM-12).
        let table = RoutingTable::production();
        let dj_links = table.links_for(Mode::Dj);
        let mixxx_links: Vec<_> = dj_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p == "Mixxx"))
            .collect();
        for link in &mixxx_links {
            assert!(
                link.output_port.starts_with("out_"),
                "Mixxx port should use out_ prefix, got: {}",
                link.output_port
            );
        }
    }

    #[test]
    fn reaper_uses_prefix_matching() {
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let reaper_links: Vec<_> = live_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p == "REAPER"))
            .collect();
        // 2 mains + 4 sub fan-out + 2 HP + 2 IEM + F-131: 2 pcm-bridge stereo
        // + F-124: 8 level-bridge-sw = 20
        assert_eq!(reaper_links.len(), 20);
    }

    #[test]
    fn live_sub_mono_sum_fan_out() {
        // Each sub convolver input (AUX2, AUX3) receives links from BOTH
        // Reaper Master L (out1) and Master R (out2) for mono sum.
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);

        for sub_aux in ["AUX2", "AUX3"] {
            let sub_links: Vec<_> = live_links
                .iter()
                .filter(|l| {
                    matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-convolver")
                        && l.input_port == format!("playback_{}", sub_aux)
                })
                .collect();
            assert_eq!(
                sub_links.len(),
                2,
                "Sub input {} should have 2 fan-out links (L+R mono sum)",
                sub_aux,
            );
            let ports: Vec<&str> = sub_links.iter().map(|l| l.output_port.as_str()).collect();
            assert!(ports.contains(&"out1"), "Missing Master L for {}", sub_aux);
            assert!(ports.contains(&"out2"), "Missing Master R for {}", sub_aux);
        }
    }

    #[test]
    fn live_reaper_port_names_use_out_prefix() {
        // Reaper JACK ports are out1..out8 (1-based, no underscore, verified on Pi).
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let reaper_links: Vec<_> = live_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p == "REAPER"))
            .collect();
        for link in &reaper_links {
            assert!(
                link.output_port.starts_with("out"),
                "Reaper port should use out prefix, got: {}",
                link.output_port
            );
            // Should NOT contain underscore (Reaper uses out1 not out_1).
            assert!(
                !link.output_port.contains('_'),
                "Reaper port should not contain underscore, got: {}",
                link.output_port
            );
        }
    }

    // -----------------------------------------------------------------------
    // AppPortNaming — D-041 one-based channel mapping
    // -----------------------------------------------------------------------

    #[test]
    fn port_naming_mixxx_output() {
        // Mixxx: zero-based with underscore (out_0, out_1, ...).
        assert_eq!(AppPortNaming::MixxxOutput.port_name(1), "out_0");
        assert_eq!(AppPortNaming::MixxxOutput.port_name(2), "out_1");
        assert_eq!(AppPortNaming::MixxxOutput.port_name(4), "out_3");
    }

    #[test]
    fn port_naming_reaper_output() {
        // Reaper: one-based, no underscore (out1, out2, ...).
        assert_eq!(AppPortNaming::ReaperOutput.port_name(1), "out1");
        assert_eq!(AppPortNaming::ReaperOutput.port_name(2), "out2");
        assert_eq!(AppPortNaming::ReaperOutput.port_name(8), "out8");
    }

    #[test]
    fn port_naming_reaper_input() {
        // Reaper input: one-based, no underscore (in1, in2, ...).
        assert_eq!(AppPortNaming::ReaperInput.port_name(1), "in1");
        assert_eq!(AppPortNaming::ReaperInput.port_name(8), "in8");
    }

    #[test]
    fn port_naming_convolver_input() {
        // Convolver capture (Audio/Sink): playback_AUX prefix, zero-based.
        assert_eq!(AppPortNaming::ConvolverInput.port_name(1), "playback_AUX0");
        assert_eq!(AppPortNaming::ConvolverInput.port_name(4), "playback_AUX3");
    }

    #[test]
    fn port_naming_convolver_output() {
        // Convolver playback (source): output_AUX prefix, zero-based.
        assert_eq!(AppPortNaming::ConvolverOutput.port_name(1), "output_AUX0");
        assert_eq!(AppPortNaming::ConvolverOutput.port_name(4), "output_AUX3");
    }

    #[test]
    fn port_naming_usbstreamer_playback() {
        assert_eq!(AppPortNaming::UsbStreamerPlayback.port_name(1), "playback_AUX0");
        assert_eq!(AppPortNaming::UsbStreamerPlayback.port_name(8), "playback_AUX7");
    }

    #[test]
    fn port_naming_ada8200_capture() {
        assert_eq!(AppPortNaming::Ada8200Capture.port_name(1), "capture_AUX0");
        assert_eq!(AppPortNaming::Ada8200Capture.port_name(8), "capture_AUX7");
    }

    #[test]
    fn port_naming_signal_gen_output() {
        assert_eq!(AppPortNaming::SignalGenOutput.port_name(1), "output_AUX0");
        assert_eq!(AppPortNaming::SignalGenOutput.port_name(4), "output_AUX3");
    }

    #[test]
    fn port_naming_signal_gen_capture_input() {
        assert_eq!(AppPortNaming::SignalGenCaptureInput.port_name(1), "input_MONO");
    }

    #[test]
    fn port_naming_umik1_capture() {
        assert_eq!(AppPortNaming::Umik1Capture.port_name(1), "capture_FL");
    }

    #[test]
    fn port_naming_pcm_bridge_input() {
        // pcm-bridge input: input_ prefix, one-based (PW convention for no SPA positions).
        assert_eq!(AppPortNaming::PcmBridgeInput.port_name(1), "input_1");
        assert_eq!(AppPortNaming::PcmBridgeInput.port_name(4), "input_4");
    }

    #[test]
    fn port_naming_convolver_monitor() {
        // Convolver monitor: monitor_AUX prefix, zero-based.
        assert_eq!(AppPortNaming::ConvolverMonitor.port_name(1), "monitor_AUX0");
        assert_eq!(AppPortNaming::ConvolverMonitor.port_name(4), "monitor_AUX3");
    }

    #[test]
    fn port_naming_usbstreamer_monitor() {
        // USBStreamer monitor: monitor_AUX prefix, zero-based.
        assert_eq!(AppPortNaming::UsbStreamerMonitor.port_name(1), "monitor_AUX0");
        assert_eq!(AppPortNaming::UsbStreamerMonitor.port_name(8), "monitor_AUX7");
    }

    #[test]
    fn port_naming_level_bridge_input() {
        // Level-bridge input: input_ prefix, one-based.
        assert_eq!(AppPortNaming::LevelBridgeInput.port_name(1), "input_1");
        assert_eq!(AppPortNaming::LevelBridgeInput.port_name(8), "input_8");
    }

    #[test]
    #[should_panic(expected = "D-041: channel numbers are one-based")]
    fn port_naming_rejects_channel_zero() {
        // D-041: channel 0 is never valid.
        AppPortNaming::MixxxOutput.port_name(0);
    }

    #[test]
    #[should_panic(expected = "signal-gen capture is mono")]
    fn port_naming_signal_gen_capture_rejects_multichannel() {
        AppPortNaming::SignalGenCaptureInput.port_name(2);
    }

    #[test]
    #[should_panic(expected = "UMIK-1 is mono")]
    fn port_naming_umik1_rejects_multichannel() {
        AppPortNaming::Umik1Capture.port_name(2);
    }

    // -----------------------------------------------------------------------
    // Live mode — ADA8200 capture links (TK-239)
    // -----------------------------------------------------------------------

    #[test]
    fn live_has_8_ada8200_to_reaper_links() {
        // ADA8200 8-channel capture → Reaper inputs (TK-239).
        // Excludes ADA8200 → level-bridge-hw-in links.
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let capture_links: Vec<_> = live_links
            .iter()
            .filter(|l| {
                matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in")
                    && matches!(&l.input_node, NodeMatch::Prefix(p) if p == "REAPER")
            })
            .collect();
        assert_eq!(capture_links.len(), 8);
    }

    #[test]
    fn live_capture_links_use_correct_port_names() {
        // ADA8200: capture_AUX0..7 → Reaper: in1..in8.
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let capture_links: Vec<_> = live_links
            .iter()
            .filter(|l| {
                matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in")
                    && matches!(&l.input_node, NodeMatch::Prefix(p) if p == "REAPER")
            })
            .collect();
        for (i, link) in capture_links.iter().enumerate() {
            let expected_out = format!("capture_AUX{}", i);
            let expected_in = format!("in{}", i + 1);
            assert_eq!(link.output_port, expected_out, "ADA8200 port mismatch at ch {}", i + 1);
            assert_eq!(link.input_port, expected_in, "Reaper input port mismatch at ch {}", i + 1);
        }
    }

    #[test]
    fn live_capture_links_are_required() {
        // ADA8200 → Reaper capture links are NOT optional — ADA8200 is always present in live mode.
        // (ADA8200 → level-bridge links are optional.)
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let capture_links: Vec<_> = live_links
            .iter()
            .filter(|l| {
                matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in")
                    && matches!(&l.input_node, NodeMatch::Prefix(p) if p == "REAPER")
            })
            .collect();
        assert!(capture_links.iter().all(|l| !l.optional));
    }

    #[test]
    fn live_capture_uses_exact_match_for_ada8200() {
        // ADA8200 uses Exact match (fixed node.name in our config), not Prefix.
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let capture_links: Vec<_> = live_links
            .iter()
            .filter(|l| {
                matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in")
                    && matches!(&l.input_node, NodeMatch::Prefix(p) if p == "REAPER")
            })
            .collect();
        assert!(!capture_links.is_empty());
        for link in &capture_links {
            assert!(
                matches!(&link.output_node, NodeMatch::Exact(_)),
                "ADA8200 should use Exact match, not Prefix"
            );
        }
    }

    #[test]
    fn live_capture_targets_reaper_prefix() {
        // ADA8200 → Reaper capture links target Reaper (Prefix match for JACK client).
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let capture_links: Vec<_> = live_links
            .iter()
            .filter(|l| {
                matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in")
                    && !matches!(&l.input_node, NodeMatch::Exact(n) if n.starts_with("pi4audio-level-bridge"))
            })
            .collect();
        for link in &capture_links {
            assert!(
                matches!(&link.input_node, NodeMatch::Prefix(p) if p == "REAPER"),
                "Capture links should target REAPER prefix"
            );
        }
    }

    // -----------------------------------------------------------------------
    // DJ mode — sub mono sum (TK-239)
    // -----------------------------------------------------------------------

    #[test]
    fn dj_has_no_app_capture_links() {
        // DJ mode has no app-bound capture links — Mixxx doesn't use mic input.
        // Level-bridge-hw-in has capture links (ADA8200 → level-bridge), which is fine.
        // UMIK-1 → pcm-bridge (always-on SPL tap) is infrastructure, not app capture.
        let table = RoutingTable::production();
        let dj_links = table.links_for(Mode::Dj);
        let app_capture_links: Vec<_> = dj_links
            .iter()
            .filter(|l| {
                l.output_port.starts_with("capture_")
                    && !matches!(&l.input_node, NodeMatch::Exact(n) if n.starts_with("pi4audio-level-bridge"))
                    && !matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-pcm-bridge")
            })
            .collect();
        assert_eq!(app_capture_links.len(), 0);
    }

    #[test]
    fn monitoring_has_no_app_links() {
        // Monitoring mode: no application (Mixxx/Reaper/signal-gen) links.
        // Only infrastructure links: convolver-out → USBStreamer, convolver-out → pcm-bridge,
        // and level-bridge metering links.
        let table = RoutingTable::production();
        let mon_links = table.links_for(Mode::Monitoring);
        for link in mon_links {
            let is_app = matches!(&link.output_node, NodeMatch::Prefix(p) if p == "Mixxx" || p == "REAPER")
                || matches!(&link.output_node, NodeMatch::Exact(n) if n == "pi4audio-signal-gen");
            assert!(
                !is_app,
                "Monitoring should not have application output links, got: {}",
                link,
            );
        }
    }

    // -----------------------------------------------------------------------
    // SpeakerLayout constructors
    // -----------------------------------------------------------------------

    #[test]
    fn two_way_layout() {
        let layout = SpeakerLayout::two_way();
        assert_eq!(layout.num_speaker_channels, 4);
        assert_eq!(layout.sub_channels, vec![3, 4]);
        assert_eq!(layout.stereo_main_channels, vec![1, 2]);
    }

    #[test]
    fn three_way_stereo_layout() {
        let layout = SpeakerLayout::three_way_stereo();
        assert_eq!(layout.num_speaker_channels, 6);
        assert_eq!(layout.sub_channels, vec![1, 2]);
        assert_eq!(layout.stereo_main_channels, vec![3, 4, 5, 6]);
    }

    #[test]
    fn from_profile_layout() {
        // workshop-c3d-elf-3way: subs on ch 1-2, everything else is stereo main.
        let layout = SpeakerLayout::from_profile(6, vec![1, 2]);
        assert_eq!(layout.num_speaker_channels, 6);
        assert_eq!(layout.sub_channels, vec![1, 2]);
        assert_eq!(layout.stereo_main_channels, vec![3, 4, 5, 6]);
    }

    #[test]
    fn from_profile_2way_matches_two_way() {
        let layout = SpeakerLayout::from_profile(4, vec![3, 4]);
        assert_eq!(layout.num_speaker_channels, 4);
        assert_eq!(layout.sub_channels, vec![3, 4]);
        assert_eq!(layout.stereo_main_channels, vec![1, 2]);
    }

    // -----------------------------------------------------------------------
    // 3-way stereo routing (6 speaker channels)
    // -----------------------------------------------------------------------

    #[test]
    fn three_way_monitoring_has_23_links() {
        // convolver-out → USBStreamer ch 0-5 (6)
        // + UMIK-1 → pcm-bridge ch3 (1, always-on)
        // + level-bridge-hw-out (8) + level-bridge-hw-in (8) = 23.
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        assert_eq!(table.links_for(Mode::Monitoring).len(), 23);
    }

    #[test]
    fn three_way_dj_has_43_links() {
        // Stereo main channels (3,4,5,6): 4 links (1:1 from Master L/R)
        // + Sub mono sum fan-out (ch 1,2): 2 subs * 2 master channels = 4
        // + convolver → USBStreamer (6)
        // + pcm-bridge stereo (2)
        // + HP (2, ch 7-8 on USBStreamer)
        // + UMIK-1 → pcm-bridge ch3 (1)
        // + level-bridge-hw-out (8) + level-bridge-hw-in (8)
        // + level-bridge-sw (8) = 43.
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        assert_eq!(table.links_for(Mode::Dj).len(), 43);
    }

    #[test]
    fn three_way_live_has_53_links() {
        // Stereo main channels (3,4,5,6): 4 links (1:1 from Master L/R)
        // + Sub mono sum fan-out (ch 1,2): 2 subs * 2 master channels = 4
        // + convolver → USBStreamer (6)
        // + pcm-bridge stereo (2)
        // + HP (2, ch 7-8 on USBStreamer)
        // + IEM (2, ch 9-10 on USBStreamer, optional)
        // + ADA8200 capture (8)
        // + UMIK-1 → pcm-bridge ch3 (1)
        // + level-bridge-hw-out (8) + level-bridge-hw-in (8)
        // + level-bridge-sw (8) = 53.
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        assert_eq!(table.links_for(Mode::Live).len(), 53);
    }

    #[test]
    fn three_way_measurement_has_33_links() {
        // signal-gen mono fan-out → convolver (6) + convolver → USBStreamer (6)
        // + UMIK-1 → pcm-bridge (1) + UMIK-1 → signal-gen-capture (1)
        // + level-bridge-hw-out (8) + level-bridge-hw-in (8)
        // + level-bridge-sw (1)
        // + room-sim hops (2) = 33.
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        assert_eq!(table.links_for(Mode::Measurement).len(), 33);
    }

    #[test]
    fn three_way_has_6_convolver_to_usbstreamer() {
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        for mode in Mode::ALL {
            let links = table.links_for(mode);
            let conv_to_usb: Vec<_> = links
                .iter()
                .filter(|l| {
                    matches!(&l.output_node, NodeMatch::Exact(n) if n == "pi4audio-convolver-out")
                        && matches!(&l.input_node, NodeMatch::Prefix(p) if p.starts_with("alsa_output.usb-MiniDSP_USBStreamer"))
                })
                .collect();
            assert_eq!(
                conv_to_usb.len(),
                6,
                "Mode {} should have 6 convolver→USBStreamer links for 3-way",
                mode
            );
        }
    }

    #[test]
    fn three_way_dj_sub_mono_sum_fan_out() {
        // 3-way: subs on ch 1-2 (AUX0, AUX1). Each gets L+R mono sum.
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        let dj_links = table.links_for(Mode::Dj);

        for sub_aux in ["AUX0", "AUX1"] {
            let sub_links: Vec<_> = dj_links
                .iter()
                .filter(|l| {
                    matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-convolver")
                        && l.input_port == format!("playback_{}", sub_aux)
                })
                .collect();
            assert_eq!(
                sub_links.len(),
                2,
                "Sub input {} should have 2 fan-out links (L+R mono sum)",
                sub_aux,
            );
            let ports: Vec<&str> = sub_links.iter().map(|l| l.output_port.as_str()).collect();
            assert!(ports.contains(&"out_0"), "Missing Master L for {}", sub_aux);
            assert!(ports.contains(&"out_1"), "Missing Master R for {}", sub_aux);
        }
    }

    #[test]
    fn three_way_dj_stereo_main_mapping() {
        // 3-way: mids on ch 3-4, HF on ch 5-6.
        // ch 3 (odd) → Master L (out_0), ch 4 (even) → Master R (out_1),
        // ch 5 (odd) → Master L (out_0), ch 6 (even) → Master R (out_1).
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        let dj_links = table.links_for(Mode::Dj);

        for (ch, expected_master_port) in [(3, "out_0"), (4, "out_1"), (5, "out_0"), (6, "out_1")] {
            let target_port = format!("playback_AUX{}", ch - 1);
            let main_links: Vec<_> = dj_links
                .iter()
                .filter(|l| {
                    matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-convolver")
                        && l.input_port == target_port
                })
                .collect();
            assert_eq!(
                main_links.len(),
                1,
                "Convolver ch {} should have exactly 1 link (1:1 from master)",
                ch,
            );
            assert_eq!(
                main_links[0].output_port, expected_master_port,
                "Convolver ch {} should be fed by {}, got {}",
                ch, expected_master_port, main_links[0].output_port,
            );
        }
    }

    #[test]
    fn three_way_dj_hp_on_ch7_8() {
        // 3-way: HP channels at num_speaker_channels+1 and +2 = USBStreamer ch 7-8.
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        let dj_links = table.links_for(Mode::Dj);

        let hp_links: Vec<_> = dj_links
            .iter()
            .filter(|l| {
                matches!(&l.output_node, NodeMatch::Prefix(p) if p == "Mixxx")
                    && matches!(&l.input_node, NodeMatch::Prefix(p) if p.starts_with("alsa_output"))
                    && (l.input_port == "playback_AUX6" || l.input_port == "playback_AUX7")
            })
            .collect();
        assert_eq!(hp_links.len(), 2, "3-way DJ should have 2 HP links on ch 7-8");
        assert!(!hp_links[0].optional);
        assert!(!hp_links[1].optional);
    }

    #[test]
    fn three_way_live_hp_on_ch7_8_iem_on_ch9_10() {
        // 3-way live: HP on ch 7-8, IEM on ch 9-10.
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        let live_links = table.links_for(Mode::Live);

        // HP links (ch 7-8).
        let hp_links: Vec<_> = live_links
            .iter()
            .filter(|l| {
                matches!(&l.output_node, NodeMatch::Prefix(p) if p == "REAPER")
                    && matches!(&l.input_node, NodeMatch::Prefix(p) if p.starts_with("alsa_output"))
                    && (l.input_port == "playback_AUX6" || l.input_port == "playback_AUX7")
            })
            .collect();
        assert_eq!(hp_links.len(), 2, "3-way Live HP should be on ch 7-8");
        assert!(hp_links.iter().all(|l| !l.optional));

        // IEM links (ch 9-10).
        let iem_links: Vec<_> = live_links
            .iter()
            .filter(|l| {
                matches!(&l.output_node, NodeMatch::Prefix(p) if p == "REAPER")
                    && matches!(&l.input_node, NodeMatch::Prefix(p) if p.starts_with("alsa_output"))
                    && (l.input_port == "playback_AUX8" || l.input_port == "playback_AUX9")
            })
            .collect();
        assert_eq!(iem_links.len(), 2, "3-way Live IEM should be on ch 9-10");
        assert!(iem_links.iter().all(|l| l.optional));
    }

    #[test]
    fn three_way_measurement_fans_out_to_6_channels() {
        // Signal-gen mono → 6 convolver inputs.
        let table = RoutingTable::production_for(SpeakerLayout::three_way_stereo());
        let meas_links = table.links_for(Mode::Measurement);
        let fanout: Vec<_> = meas_links
            .iter()
            .filter(|l| {
                matches!(&l.output_node, NodeMatch::Exact(n) if n == "pi4audio-signal-gen")
                    && matches!(&l.input_node, NodeMatch::Exact(n) if n == "pi4audio-convolver")
            })
            .collect();
        assert_eq!(fanout.len(), 6);
        // All should use output_AUX0 (mono).
        assert!(fanout.iter().all(|l| l.output_port == "output_AUX0"));
        // Should cover AUX0..AUX5.
        let target_ports: Vec<&str> = fanout.iter().map(|l| l.input_port.as_str()).collect();
        for ch in 0..6 {
            let port = format!("playback_AUX{}", ch);
            assert!(target_ports.contains(&port.as_str()), "Missing {}", port);
        }
    }
}
