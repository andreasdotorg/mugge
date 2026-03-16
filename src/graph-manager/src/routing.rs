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
//! - **Live:** Reaper linked to filter-chain + headphones + singer IEM.
//! - **Measurement:** Signal-gen → filter-chain, UMIK-1 capture active.
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
/// Not used in routing yet — will be needed when mic input routing is added.
#[allow(dead_code)]
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
/// TODO: Verify exact REAPER PW node name on Pi (`pw-jack reaper`).
const REAPER_PREFIX: &str = "REAPER";

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
    /// Mixxx provides 8 channels. Ch 0-3 go through the convolver for
    /// speaker processing. Ch 4-5 (engineer headphones) bypass convolver
    /// and go directly to USBStreamer ch 4-5.
    fn dj_links() -> Vec<DesiredLink> {
        let mut links = Vec::new();
        let aux = ["AUX0", "AUX1", "AUX2", "AUX3"];

        // Mixxx → convolver (ch 0-3: speaker channels through FIR).
        // TODO: Verify Mixxx port names on Pi — JACK clients may use
        // output_FL/output_FR for stereo or output_AUX0 for multi-channel.
        for ch_name in &aux {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(MIXXX_PREFIX.to_string()),
                output_port: format!("output_{}", ch_name),
                input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                input_port: format!("playback_{}", ch_name),
                optional: false,
            });
        }

        // Convolver → USBStreamer (ch 0-3: processed speakers).
        links.extend(Self::convolver_to_usbstreamer_links());

        // Mixxx → USBStreamer direct (ch 4-5: engineer headphones, bypass convolver).
        // TODO: Verify Mixxx output port names for ch 4-5 on Pi.
        for ch in 4..6 {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(MIXXX_PREFIX.to_string()),
                output_port: format!("output_AUX{}", ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: format!("playback_AUX{}", ch),
                optional: false,
            });
        }

        links
    }

    /// Live mode: Reaper → convolver → USBStreamer (speakers + HP + IEM).
    ///
    /// Reaper provides 8 channels. Ch 0-3 through convolver (speakers),
    /// ch 4-5 direct to USBStreamer (engineer HP), ch 6-7 direct to
    /// USBStreamer (singer IEM, passthrough per D-011).
    fn live_links() -> Vec<DesiredLink> {
        let mut links = Vec::new();
        let aux = ["AUX0", "AUX1", "AUX2", "AUX3"];

        // Reaper → convolver (ch 0-3: speaker channels through FIR).
        // TODO: Verify Reaper port names on Pi — multi-channel JACK output.
        for ch_name in &aux {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                output_port: format!("output_{}", ch_name),
                input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                input_port: format!("playback_{}", ch_name),
                optional: false,
            });
        }

        // Convolver → USBStreamer (ch 0-3: processed speakers).
        links.extend(Self::convolver_to_usbstreamer_links());

        // Reaper → USBStreamer direct (ch 4-5: engineer headphones).
        // TODO: Verify Reaper output port names for ch 4-5 on Pi.
        for ch in 4..6 {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                output_port: format!("output_AUX{}", ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: format!("playback_AUX{}", ch),
                optional: false,
            });
        }

        // Reaper → USBStreamer direct (ch 6-7: singer IEM, passthrough).
        // TODO: Verify Reaper output port names for ch 6-7 on Pi.
        for ch in 6..8 {
            links.push(DesiredLink {
                output_node: NodeMatch::Prefix(REAPER_PREFIX.to_string()),
                output_port: format!("output_AUX{}", ch),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: format!("playback_AUX{}", ch),
                optional: true, // IEM is optional equipment
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
        let aux = ["AUX0", "AUX1", "AUX2", "AUX3"];

        // Signal-gen → convolver (ch 0-3: measurement signals).
        // Signal-gen uses audio.position = AUX0..AUX7 → output_AUX0..output_AUX7.
        // Convolver capture is Audio/Sink with AUX positions → playback_AUX0..AUX3.
        for ch_name in &aux {
            links.push(DesiredLink {
                output_node: NodeMatch::Exact(SIGNAL_GEN.to_string()),
                output_port: format!("output_{}", ch_name),
                input_node: NodeMatch::Exact(CONVOLVER_IN.to_string()),
                input_port: format!("playback_{}", ch_name),
                optional: false,
            });
        }

        // Convolver → USBStreamer (ch 0-3: measurement signal to speakers).
        links.extend(Self::convolver_to_usbstreamer_links());

        // UMIK-1 → signal-gen capture (mono measurement mic).
        // UMIK-1 is a capture source with MONO position → capture_MONO.
        // Signal-gen capture uses MONO position → input_MONO.
        links.push(DesiredLink {
            output_node: NodeMatch::Prefix(UMIK1_PREFIX.to_string()),
            output_port: "capture_MONO".to_string(),
            input_node: NodeMatch::Exact(SIGNAL_GEN_CAPTURE.to_string()),
            input_port: "input_MONO".to_string(),
            optional: true, // UMIK-1 may not be plugged in
        });

        links
    }

    // -------------------------------------------------------------------
    // Shared link sets
    // -------------------------------------------------------------------

    /// Convolver output → USBStreamer playback (ch 0-3).
    /// Used by all modes (speakers always go through the convolver).
    ///
    /// Convolver playback source uses audio.position = [ AUX0..AUX3 ]
    /// → output_AUX0..output_AUX3.
    /// NOTE: Verify on Pi — filter-chain playback node may use playback_
    /// prefix instead of output_. If so, update this helper.
    fn convolver_to_usbstreamer_links() -> Vec<DesiredLink> {
        let aux = ["AUX0", "AUX1", "AUX2", "AUX3"];
        aux.iter()
            .map(|ch_name| DesiredLink {
                output_node: NodeMatch::Exact(CONVOLVER_OUT.to_string()),
                output_port: format!("output_{}", ch_name),
                input_node: NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string()),
                input_port: format!("playback_{}", ch_name),
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
    fn dj_has_10_links() {
        // Mixxx → convolver (4) + convolver → USBStreamer (4) + Mixxx → USBStreamer HP (2).
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Dj).len(), 10);
    }

    #[test]
    fn live_has_12_links() {
        // REAPER → convolver (4) + convolver → USBStreamer (4) + REAPER → USBStreamer HP (2) + REAPER → USBStreamer IEM (2).
        let table = RoutingTable::production();
        assert_eq!(table.links_for(Mode::Live).len(), 12);
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
        // ch 6-7 (IEM) should be optional.
        let iem_links: Vec<_> = live_links
            .iter()
            .filter(|l| l.output_port.contains('6') || l.output_port.contains('7'))
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
        // 4 to convolver + 2 to USBStreamer HP = 6
        assert_eq!(mixxx_links.len(), 6);
    }

    #[test]
    fn reaper_uses_prefix_matching() {
        let table = RoutingTable::production();
        let live_links = table.links_for(Mode::Live);
        let reaper_links: Vec<_> = live_links
            .iter()
            .filter(|l| matches!(&l.output_node, NodeMatch::Prefix(p) if p == "REAPER"))
            .collect();
        // 4 to convolver + 2 to USBStreamer HP + 2 to USBStreamer IEM = 8
        assert_eq!(reaper_links.len(), 8);
    }
}
