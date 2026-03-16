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
/// Prefix match only for the USBStreamer, whose ALSA-generated name includes
/// a variable serial suffix.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", content = "value")]
pub enum NodeMatch {
    /// node.name must equal this value exactly.
    Exact(String),
    /// node.name must start with this prefix (USBStreamer only).
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

impl RoutingTable {
    /// Build the production routing table.
    ///
    /// This is the single source of truth for all application routing.
    /// Node names and port names are compiled in because they are fixed
    /// by our component configurations.
    pub fn production() -> Self {
        let mut table = HashMap::new();

        // Monitoring mode: filter-chain receives from USBStreamer capture,
        // filter-chain output goes to USBStreamer playback.
        // No application (Mixxx/Reaper) is linked.
        table.insert(Mode::Monitoring, Self::monitoring_links());
        table.insert(Mode::Dj, Self::dj_links());
        table.insert(Mode::Live, Self::live_links());
        table.insert(Mode::Measurement, Self::measurement_links());

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

    /// Monitoring mode: filter-chain active, no application.
    ///
    /// TODO: Populate with actual filter-chain port names once the
    /// production PW filter-chain config is defined (US-059 Phase A).
    /// For now, this is a placeholder structure.
    fn monitoring_links() -> Vec<DesiredLink> {
        // Placeholder — actual links depend on filter-chain node/port names
        // which will be defined when the production filter-chain config is
        // created as part of US-059.
        Vec::new()
    }

    /// DJ mode: Mixxx → filter-chain → USBStreamer + headphones.
    fn dj_links() -> Vec<DesiredLink> {
        // Placeholder — requires Mixxx PW node name and filter-chain config.
        Vec::new()
    }

    /// Live mode: Reaper → filter-chain → USBStreamer + headphones + IEM.
    fn live_links() -> Vec<DesiredLink> {
        // Placeholder — requires Reaper PW node name and IEM routing.
        Vec::new()
    }

    /// Measurement mode: signal-gen → filter-chain, UMIK-1 → capture.
    fn measurement_links() -> Vec<DesiredLink> {
        // Placeholder — requires signal-gen and UMIK-1 node/port names.
        Vec::new()
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
}
