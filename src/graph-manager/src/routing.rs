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
const UMIK1_PREFIX: &str = "alsa_input.usb-miniDSP_UMIK-1";

/// pcm-bridge node name (monitor port tap).
/// Not linked by GraphManager — pcm-bridge creates its own monitor port
/// connections for level metering. Recognized here so GraphManager's
/// ownership filter doesn't destroy pcm-bridge's self-created links.
#[allow(dead_code)]
const PCM_BRIDGE: &str = "pi4audio-pcm-bridge";

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
    /// UMIK-1 capture: `capture_MONO`.
    /// Only channel 1 is valid.
    Umik1Capture,
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
                "capture_MONO".to_string()
            }
        }
    }
}

impl RoutingTable {
    /// Build the production routing table.
    ///
    /// This is the single source of truth for all application routing.
    /// Node names and port names are compiled in because they are fixed
    /// by our component configurations.
    pub fn production() -> Self {
        let mut table = HashMap::new();

        table.insert(Mode::Monitoring, Self::monitoring_links());
        table.insert(Mode::Dj, Self::dj_links());
        table.insert(Mode::Live, Self::live_links());
        table.insert(Mode::Measurement, Self::measurement_links());

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
    /// Links: convolver-out ch 0-3 → USBStreamer playback ch 0-3.
    fn monitoring_links() -> Vec<DesiredLink> {
        // TODO: AE-F6 USBStreamer volume lock — when USBStreamer is first
        // detected, set volume to unity to prevent post-DSP clipping.
        Self::convolver_to_usbstreamer_links()
    }

    /// DJ mode: Mixxx → convolver → USBStreamer (speakers + headphones).
    ///
    /// Mixxx outputs 4 channels via pw-jack (verified on Pi, GM-12):
    ///   ch 1 = Master L, ch 2 = Master R,
    ///   ch 3 = Headphone L, ch 4 = Headphone R.
    ///
    /// Master L/R go 1:1 to convolver mains (ch 1-2) AND fan-out to
    /// both sub convolver inputs (ch 3-4) for mono-sum (TK-239). PipeWire
    /// mixes multiple links to the same input port additively. The -6 dB
    /// mono sum compensation is baked into the sub FIR WAV coefficients
    /// (architect guidance).
    ///
    /// Headphone L/R bypass the convolver and go directly to USBStreamer
    /// ch 5-6.
    fn dj_links() -> Vec<DesiredLink> {
        let mut links = Vec::new();
        let mx = AppPortNaming::MixxxOutput;
        let cv_in = AppPortNaming::ConvolverInput;
        let usb = AppPortNaming::UsbStreamerPlayback;

        // Mixxx master → convolver mains (1:1).
        // Ch 1 (Master L) → convolver ch 1 (left wideband)
        // Ch 2 (Master R) → convolver ch 2 (right wideband)
        for ch in 1..=2 {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(MIXXX_PREFIX.to_string()),
                output_port: mx.port_name(ch),
                input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                input_port: cv_in.port_name(ch),
                optional: false,
            });
        }

        // Mixxx master → convolver subs (explicit L+R mono sum, TK-239).
        // Both Master L (ch 1) and Master R (ch 2) feed each sub input.
        // PipeWire sums the two links at the input port.
        for sub_ch in [3, 4] {
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

        // Convolver → USBStreamer (ch 1-4: processed speakers).
        links.extend(Self::convolver_to_usbstreamer_links());

        // Mixxx headphones → USBStreamer direct (bypass convolver).
        // Ch 3 (Headphone L) → USBStreamer ch 5
        // Ch 4 (Headphone R) → USBStreamer ch 6
        for (mx_ch, usb_ch) in [(3, 5), (4, 6)] {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(MIXXX_PREFIX.to_string()),
                output_port: mx.port_name(mx_ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: usb.port_name(usb_ch),
                optional: false,
            });
        }

        links
    }

    /// Live mode: Reaper → convolver → USBStreamer (speakers + HP + IEM)
    /// + ADA8200 capture → Reaper inputs (TK-239).
    ///
    /// Reaper outputs 8 channels via pw-jack (verified on Pi, C-005):
    ///   ch 1 = Master L, ch 2 = Master R,
    ///   ch 3-4 = unused (available but not routed),
    ///   ch 5 = HP L, ch 6 = HP R,
    ///   ch 7 = IEM L, ch 8 = IEM R.
    ///
    /// Master L/R go 1:1 to convolver mains (ch 1-2) AND fan-out to
    /// both sub convolver inputs (ch 3-4) for mono-sum (TK-239), same
    /// pattern as DJ mode. The -6 dB mono sum compensation is baked
    /// into the sub FIR WAV coefficients (architect guidance).
    ///
    /// HP and IEM bypass the convolver and go directly to USBStreamer.
    ///
    /// ADA8200 8-channel capture feeds Reaper inputs for vocal mic,
    /// spare mic/line, and additional inputs (C-005 verified).
    fn live_links() -> Vec<DesiredLink> {
        let mut links = Vec::new();
        let rp_out = AppPortNaming::ReaperOutput;
        let rp_in = AppPortNaming::ReaperInput;
        let cv_in = AppPortNaming::ConvolverInput;
        let usb = AppPortNaming::UsbStreamerPlayback;
        let ada = AppPortNaming::Ada8200Capture;

        // Reaper master → convolver mains (1:1).
        // Ch 1 (Master L) → convolver ch 1 (left wideband)
        // Ch 2 (Master R) → convolver ch 2 (right wideband)
        for ch in 1..=2 {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                output_port: rp_out.port_name(ch),
                input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                input_port: cv_in.port_name(ch),
                optional: false,
            });
        }

        // Reaper master → convolver subs (explicit L+R mono sum, TK-239).
        // Both Master L (ch 1) and Master R (ch 2) feed each sub input.
        // PipeWire sums the two links at the input port.
        for sub_ch in [3, 4] {
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

        // Convolver → USBStreamer (ch 1-4: processed speakers).
        links.extend(Self::convolver_to_usbstreamer_links());

        // Reaper headphones → USBStreamer direct (bypass convolver).
        // Ch 5 (HP L) → USBStreamer ch 5
        // Ch 6 (HP R) → USBStreamer ch 6
        for ch in 5..=6 {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                output_port: rp_out.port_name(ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: usb.port_name(ch),
                optional: false,
            });
        }

        // Reaper singer IEM → USBStreamer direct (passthrough per D-011).
        // Ch 7 (IEM L) → USBStreamer ch 7
        // Ch 8 (IEM R) → USBStreamer ch 8
        for ch in 7..=8 {
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

        links
    }

    /// Measurement mode: signal-gen → convolver, UMIK-1 → signal-gen capture.
    ///
    /// Signal-gen sends test signals through the convolver to the speakers.
    /// UMIK-1 captures the room response back to signal-gen for analysis.
    fn measurement_links() -> Vec<DesiredLink> {
        let mut links = Vec::new();
        let sg = AppPortNaming::SignalGenOutput;
        let cv_in = AppPortNaming::ConvolverInput;
        let umik = AppPortNaming::Umik1Capture;
        let sg_cap = AppPortNaming::SignalGenCaptureInput;

        // Signal-gen → convolver (ch 1-4: measurement signals).
        for ch in 1..=4 {
            links.push(DesiredLink {
                output_node: NodeMatch::Exact(SIGNAL_GEN.to_string()),
                output_port: sg.port_name(ch),
                input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                input_port: cv_in.port_name(ch),
                optional: false,
            });
        }

        // Convolver → USBStreamer (ch 1-4: measurement signal to speakers).
        links.extend(Self::convolver_to_usbstreamer_links());

        // UMIK-1 → signal-gen capture (mono measurement mic).
        links.push(DesiredLink {
            output_node: NodeMatch::Prefix(UMIK1_PREFIX.to_string()),
            output_port: umik.port_name(1),
            input_node: NodeMatch::Exact(SIGNAL_GEN_CAPTURE.to_string()),
            input_port: sg_cap.port_name(1),
            optional: true, // UMIK-1 may not be plugged in
        });

        links
    }

    // -------------------------------------------------------------------
    // Shared link sets
    // -------------------------------------------------------------------

    /// Convolver output → USBStreamer playback (ch 1-4).
    /// Used by all modes (speakers always go through the convolver).
    ///
    /// Verified on Pi (C-005): filter-chain playback node uses
    /// `output_AUX0..output_AUX3` port names.
    fn convolver_to_usbstreamer_links() -> Vec<DesiredLink> {
        let cv_out = AppPortNaming::ConvolverOutput;
        let usb = AppPortNaming::UsbStreamerPlayback;
        (1..=4)
            .map(|ch| DesiredLink {
                output_node: NodeMatch::Exact(CONVOLVER_OUT.to_string()),
                output_port: cv_out.port_name(ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: usb.port_name(ch),
                optional: false,
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
        assert!(!m.matches("alsa_input.usb-miniDSP_UMIK-1"));
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
            output_port: "capture_MONO".to_string(),
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
    fn monitoring_has_4_links() {
        // convolver-out → USBStreamer ch 0-3 (4 links).
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Monitoring).len(), 4);
    }

    #[test]
    fn dj_has_12_links() {
        // Mixxx → convolver mains (2) + Mixxx → convolver subs fan-out (4)
        // + convolver → USBStreamer (4) + Mixxx → USBStreamer HP (2) = 12.
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Dj).len(), 12);
    }

    #[test]
    fn live_has_22_links() {
        // REAPER → convolver mains (2) + REAPER → convolver subs fan-out (4)
        // + convolver → USBStreamer (4) + REAPER → USBStreamer HP (2)
        // + REAPER → USBStreamer IEM (2) + ADA8200 → REAPER capture (8) = 22.
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Live).len(), 22);
    }

    #[test]
    fn measurement_has_9_links() {
        // signal-gen → convolver (4) + convolver → USBStreamer (4) + UMIK-1 → signal-gen-capture (1).
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Measurement).len(), 9);
    }

    #[test]
    fn live_iem_links_are_optional() {
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        // IEM links (out7, out8 → USBStreamer AUX6, AUX7) should be optional.
        let iem_links: Vec<_> = live_links
            .iter()
            .filter(|l| l.output_port == "out7" || l.output_port == "out8")
            .collect();
        assert_eq!(iem_links.len(), 2);
        assert!(iem_links.iter().all(|l| l.optional));
    }

    #[test]
    fn measurement_umik1_link_is_optional() {
        let table = RoutingTable::production();
        let meas_links = table.links_for(Mode::Measurement);
        let umik_links: Vec<_> = meas_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p.contains("UMIK")))
            .collect();
        assert_eq!(umik_links.len(), 1);
        assert!(umik_links[0].optional);
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
        // Signal-gen is Stream/Output/Audio with AUX positions → output_AUX.
        let table = RoutingTable::production();
        let meas_links = table.links_for(Mode::Measurement);
        let siggen_links: Vec<_> = meas_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Exact(n) if n == "pi4audio-signal-gen"))
            .collect();
        assert_eq!(siggen_links.len(), 4);
        for link in &siggen_links {
            assert!(
                link.output_port.starts_with("output_AUX"),
                "Signal-gen port should use output_AUX prefix, got: {}",
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
        let table = RoutingTable::production();
        let meas_links = table.links_for(Mode::Measurement);
        let umik_links: Vec<_> = meas_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p.contains("UMIK")))
            .collect();
        assert_eq!(umik_links.len(), 1);
        assert_eq!(umik_links[0].output_port, "capture_MONO");
    }

    #[test]
    fn mixxx_uses_prefix_matching() {
        let table = RoutingTable::production();
        let dj_links = table.links_for(Mode::Dj);
        let mixxx_links: Vec<_> = dj_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p == "Mixxx"))
            .collect();
        // 2 mains + 4 sub fan-out + 2 HP = 8
        assert_eq!(mixxx_links.len(), 8);
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
        // 2 mains + 4 sub fan-out + 2 HP + 2 IEM = 10
        assert_eq!(reaper_links.len(), 10);
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
        assert_eq!(AppPortNaming::Umik1Capture.port_name(1), "capture_MONO");
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
    fn live_has_8_ada8200_capture_links() {
        // ADA8200 8-channel capture → Reaper inputs (TK-239).
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let capture_links: Vec<_> = live_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in"))
            .collect();
        assert_eq!(capture_links.len(), 8);
    }

    #[test]
    fn live_capture_links_use_correct_port_names() {
        // ADA8200: capture_AUX0..7, Reaper: in1..in8.
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let capture_links: Vec<_> = live_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in"))
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
        // Capture links are NOT optional — ADA8200 is always present in live mode.
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let capture_links: Vec<_> = live_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in"))
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
            .filter(|l| matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in"))
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
        // Capture links target Reaper (Prefix match for JACK client).
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let capture_links: Vec<_> = live_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Exact(n) if n == "ada8200-in"))
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
    fn dj_has_no_capture_links() {
        // DJ mode has no capture input links — Mixxx doesn't use mic input.
        let table = RoutingTable::production();
        let dj_links = table.links_for(Mode::Dj);
        let capture_links: Vec<_> = dj_links
            .iter()
            .filter(|l| l.output_port.starts_with("capture_"))
            .collect();
        assert_eq!(capture_links.len(), 0);
    }

    #[test]
    fn monitoring_has_no_app_links() {
        // Monitoring mode: only convolver → USBStreamer, no app links.
        let table = RoutingTable::production();
        let mon_links = table.links_for(Mode::Monitoring);
        assert_eq!(mon_links.len(), 4);
        for link in mon_links {
            assert!(
                matches!(&link.output_node, NodeMatch::Exact(n) if n == "pi4audio-convolver-out"),
                "Monitoring should only have convolver output links"
            );
        }
    }
}
