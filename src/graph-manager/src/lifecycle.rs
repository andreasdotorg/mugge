//! Component lifecycle observer — tracks health of managed components
//! by observing PW registry events.
//!
//! GraphManager is an OBSERVER, not a supervisor. systemd manages process
//! restarts (signal-gen.service, pcm-bridge@.service both have
//! `Restart=on-failure`). GraphManager's role is:
//!
//! 1. Detect node appearance/disappearance from the PW registry.
//! 2. Derive component health (Connected/Disconnected) from GraphState.
//! 3. Emit `DeviceConnected`/`DeviceDisconnected` events on transitions.
//! 4. Provide health status for RPC `get_devices` responses.
//!
//! Reconciliation (GM-3) handles re-linking automatically when components
//! reappear — no lifecycle-specific link management needed here.
//!
//! ## Components
//!
//! | Component     | Type     | Health-tracking node                           |
//! |---------------|----------|------------------------------------------------|
//! | signal-gen    | Managed  | `pi4audio-signal-gen` (Exact)                  |
//! | pcm-bridge    | Managed  | `pi4audio-pcm-bridge` (Exact)                  |
//! | convolver     | PW module| `pi4audio-convolver` (Exact)                   |
//! | usbstreamer   | Hardware | `alsa_output.usb-MiniDSP_USBStreamer*` (Prefix) |
//! | umik1         | Hardware | `alsa_input.usb-miniDSP_UMIK-1*` (Prefix)      |
//!
//! Mixxx and REAPER are user-launched — they are not tracked as components.
//! Their nodes appear/disappear based on user action, not system health.

use crate::graph::GraphState;
use crate::routing::NodeMatch;

/// Component health as observed from the PW registry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ComponentHealth {
    /// Primary node is present in the PW registry.
    Connected,
    /// Primary node is absent from the PW registry.
    Disconnected,
}

impl ComponentHealth {
    /// String representation for RPC responses.
    pub fn as_str(&self) -> &'static str {
        match self {
            ComponentHealth::Connected => "connected",
            ComponentHealth::Disconnected => "disconnected",
        }
    }
}

/// A tracked component with its health-detecting node matcher.
#[derive(Debug, Clone)]
pub struct TrackedComponent {
    /// Logical name (e.g., "signal-gen", "usbstreamer").
    pub name: String,
    /// Node matcher for the primary health-tracking node.
    pub matcher: NodeMatch,
    /// Current observed health.
    pub health: ComponentHealth,
}

/// Health transition event emitted when a component's status changes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HealthTransition {
    /// Component appeared in the PW registry.
    Connected { name: String },
    /// Component disappeared from the PW registry.
    Disconnected { name: String },
}

/// Registry of tracked components and their health state.
///
/// Updated after every graph mutation. Returns health transitions
/// that the caller converts to RPC push events.
pub struct ComponentRegistry {
    components: Vec<TrackedComponent>,
}

impl ComponentRegistry {
    /// Build the production component registry.
    ///
    /// Lists all components whose health GraphManager tracks.
    /// Mixxx and REAPER are excluded — they are user-launched.
    pub fn production() -> Self {
        Self {
            components: vec![
                TrackedComponent {
                    name: "signal-gen".to_string(),
                    matcher: NodeMatch::Exact("pi4audio-signal-gen".to_string()),
                    health: ComponentHealth::Disconnected,
                },
                TrackedComponent {
                    name: "pcm-bridge".to_string(),
                    matcher: NodeMatch::Exact("pi4audio-pcm-bridge".to_string()),
                    health: ComponentHealth::Disconnected,
                },
                TrackedComponent {
                    name: "convolver".to_string(),
                    matcher: NodeMatch::Exact("pi4audio-convolver".to_string()),
                    health: ComponentHealth::Disconnected,
                },
                TrackedComponent {
                    name: "usbstreamer".to_string(),
                    matcher: NodeMatch::Prefix(
                        "alsa_output.usb-MiniDSP_USBStreamer".to_string(),
                    ),
                    health: ComponentHealth::Disconnected,
                },
                TrackedComponent {
                    name: "umik1".to_string(),
                    matcher: NodeMatch::Prefix(
                        "alsa_input.usb-miniDSP_UMIK-1".to_string(),
                    ),
                    health: ComponentHealth::Disconnected,
                },
            ],
        }
    }

    /// Build a registry from explicit entries (for testing).
    pub fn from_entries(entries: Vec<(String, NodeMatch)>) -> Self {
        Self {
            components: entries
                .into_iter()
                .map(|(name, matcher)| TrackedComponent {
                    name,
                    matcher,
                    health: ComponentHealth::Disconnected,
                })
                .collect(),
        }
    }

    /// Update all component health from the current graph state.
    ///
    /// Returns a list of health transitions (connected/disconnected)
    /// that occurred since the last update. The caller should convert
    /// these to RPC push events.
    pub fn update(&mut self, graph: &GraphState) -> Vec<HealthTransition> {
        let mut transitions = Vec::new();

        for component in &mut self.components {
            let node_present = !graph
                .nodes_matching(|name| component.matcher.matches(name))
                .is_empty();

            let new_health = if node_present {
                ComponentHealth::Connected
            } else {
                ComponentHealth::Disconnected
            };

            if new_health != component.health {
                let old = component.health;
                component.health = new_health;

                match (old, new_health) {
                    (ComponentHealth::Disconnected, ComponentHealth::Connected) => {
                        log::info!(
                            "Component '{}' connected (node matched: {})",
                            component.name,
                            component.matcher,
                        );
                        transitions.push(HealthTransition::Connected {
                            name: component.name.clone(),
                        });
                    }
                    (ComponentHealth::Connected, ComponentHealth::Disconnected) => {
                        log::warn!(
                            "Component '{}' disconnected (node gone: {})",
                            component.name,
                            component.matcher,
                        );
                        transitions.push(HealthTransition::Disconnected {
                            name: component.name.clone(),
                        });
                    }
                    _ => {} // same state, no transition
                }
            }
        }

        transitions
    }

    /// Get the health of a specific component by name.
    pub fn health(&self, name: &str) -> Option<ComponentHealth> {
        self.components
            .iter()
            .find(|c| c.name == name)
            .map(|c| c.health)
    }

    /// Get all component health statuses.
    pub fn all_health(&self) -> Vec<(&str, ComponentHealth)> {
        self.components
            .iter()
            .map(|c| (c.name.as_str(), c.health))
            .collect()
    }

    /// Number of tracked components.
    pub fn len(&self) -> usize {
        self.components.len()
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::{GraphState, TrackedNode};
    use std::collections::HashMap;

    fn make_node(id: u32, name: &str, class: &str) -> TrackedNode {
        TrackedNode {
            id,
            name: name.to_string(),
            media_class: class.to_string(),
            properties: HashMap::new(),
        }
    }

    // -----------------------------------------------------------------------
    // ComponentHealth
    // -----------------------------------------------------------------------

    #[test]
    fn health_as_str() {
        assert_eq!(ComponentHealth::Connected.as_str(), "connected");
        assert_eq!(ComponentHealth::Disconnected.as_str(), "disconnected");
    }

    // -----------------------------------------------------------------------
    // ComponentRegistry — production
    // -----------------------------------------------------------------------

    #[test]
    fn production_registry_has_5_components() {
        let reg = ComponentRegistry::production();
        assert_eq!(reg.len(), 5);
    }

    #[test]
    fn production_starts_all_disconnected() {
        let reg = ComponentRegistry::production();
        for (name, health) in reg.all_health() {
            assert_eq!(
                health,
                ComponentHealth::Disconnected,
                "Component '{}' should start disconnected",
                name,
            );
        }
    }

    // -----------------------------------------------------------------------
    // Health transitions
    // -----------------------------------------------------------------------

    #[test]
    fn node_appear_triggers_connected_transition() {
        let mut reg = ComponentRegistry::from_entries(vec![(
            "signal-gen".to_string(),
            NodeMatch::Exact("pi4audio-signal-gen".to_string()),
        )]);

        let mut g = GraphState::new();
        g.add_node(make_node(10, "pi4audio-signal-gen", "Stream/Output/Audio"));

        let transitions = reg.update(&g);

        assert_eq!(transitions.len(), 1);
        assert_eq!(
            transitions[0],
            HealthTransition::Connected {
                name: "signal-gen".to_string()
            }
        );
        assert_eq!(reg.health("signal-gen"), Some(ComponentHealth::Connected));
    }

    #[test]
    fn node_disappear_triggers_disconnected_transition() {
        let mut reg = ComponentRegistry::from_entries(vec![(
            "signal-gen".to_string(),
            NodeMatch::Exact("pi4audio-signal-gen".to_string()),
        )]);

        let mut g = GraphState::new();
        g.add_node(make_node(10, "pi4audio-signal-gen", "Stream/Output/Audio"));

        // First update: connected.
        let _ = reg.update(&g);
        assert_eq!(reg.health("signal-gen"), Some(ComponentHealth::Connected));

        // Remove the node.
        g.remove_node(10);

        // Second update: disconnected.
        let transitions = reg.update(&g);
        assert_eq!(transitions.len(), 1);
        assert_eq!(
            transitions[0],
            HealthTransition::Disconnected {
                name: "signal-gen".to_string()
            }
        );
        assert_eq!(
            reg.health("signal-gen"),
            Some(ComponentHealth::Disconnected)
        );
    }

    #[test]
    fn no_transition_when_state_unchanged() {
        let mut reg = ComponentRegistry::from_entries(vec![(
            "signal-gen".to_string(),
            NodeMatch::Exact("pi4audio-signal-gen".to_string()),
        )]);

        let mut g = GraphState::new();
        g.add_node(make_node(10, "pi4audio-signal-gen", "Stream/Output/Audio"));

        // First update: connected transition.
        let t1 = reg.update(&g);
        assert_eq!(t1.len(), 1);

        // Second update with same state: no transition.
        let t2 = reg.update(&g);
        assert!(t2.is_empty());

        // Third update: still no transition.
        let t3 = reg.update(&g);
        assert!(t3.is_empty());
    }

    #[test]
    fn prefix_match_detects_usbstreamer() {
        let mut reg = ComponentRegistry::from_entries(vec![(
            "usbstreamer".to_string(),
            NodeMatch::Prefix("alsa_output.usb-MiniDSP_USBStreamer".to_string()),
        )]);

        let mut g = GraphState::new();
        g.add_node(make_node(
            10,
            "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0",
            "Audio/Sink",
        ));

        let transitions = reg.update(&g);
        assert_eq!(transitions.len(), 1);
        assert_eq!(
            transitions[0],
            HealthTransition::Connected {
                name: "usbstreamer".to_string()
            }
        );
    }

    #[test]
    fn multiple_components_tracked_independently() {
        let mut reg = ComponentRegistry::from_entries(vec![
            (
                "signal-gen".to_string(),
                NodeMatch::Exact("pi4audio-signal-gen".to_string()),
            ),
            (
                "convolver".to_string(),
                NodeMatch::Exact("pi4audio-convolver".to_string()),
            ),
        ]);

        let mut g = GraphState::new();

        // Only signal-gen appears.
        g.add_node(make_node(10, "pi4audio-signal-gen", "Stream/Output/Audio"));
        let t1 = reg.update(&g);
        assert_eq!(t1.len(), 1);
        assert_eq!(reg.health("signal-gen"), Some(ComponentHealth::Connected));
        assert_eq!(
            reg.health("convolver"),
            Some(ComponentHealth::Disconnected)
        );

        // Now convolver appears too.
        g.add_node(make_node(20, "pi4audio-convolver", "Audio/Sink"));
        let t2 = reg.update(&g);
        assert_eq!(t2.len(), 1);
        assert_eq!(reg.health("convolver"), Some(ComponentHealth::Connected));

        // Signal-gen disappears.
        g.remove_node(10);
        let t3 = reg.update(&g);
        assert_eq!(t3.len(), 1);
        assert_eq!(
            t3[0],
            HealthTransition::Disconnected {
                name: "signal-gen".to_string()
            }
        );
        // Convolver still connected.
        assert_eq!(reg.health("convolver"), Some(ComponentHealth::Connected));
    }

    #[test]
    fn reconnect_after_disconnect() {
        let mut reg = ComponentRegistry::from_entries(vec![(
            "signal-gen".to_string(),
            NodeMatch::Exact("pi4audio-signal-gen".to_string()),
        )]);

        let mut g = GraphState::new();

        // Connect.
        g.add_node(make_node(10, "pi4audio-signal-gen", "Stream/Output/Audio"));
        let t1 = reg.update(&g);
        assert_eq!(t1.len(), 1);
        assert!(matches!(&t1[0], HealthTransition::Connected { .. }));

        // Disconnect (crash).
        g.remove_node(10);
        let t2 = reg.update(&g);
        assert_eq!(t2.len(), 1);
        assert!(matches!(&t2[0], HealthTransition::Disconnected { .. }));

        // Reconnect (systemd restart — new PW ID).
        g.add_node(make_node(50, "pi4audio-signal-gen", "Stream/Output/Audio"));
        let t3 = reg.update(&g);
        assert_eq!(t3.len(), 1);
        assert!(matches!(&t3[0], HealthTransition::Connected { .. }));
        assert_eq!(reg.health("signal-gen"), Some(ComponentHealth::Connected));
    }

    #[test]
    fn unknown_component_returns_none() {
        let reg = ComponentRegistry::production();
        assert_eq!(reg.health("nonexistent"), None);
    }

    #[test]
    fn all_health_returns_all_components() {
        let reg = ComponentRegistry::production();
        let health = reg.all_health();
        assert_eq!(health.len(), 5);
        let names: Vec<&str> = health.iter().map(|(n, _)| *n).collect();
        assert!(names.contains(&"signal-gen"));
        assert!(names.contains(&"pcm-bridge"));
        assert!(names.contains(&"convolver"));
        assert!(names.contains(&"usbstreamer"));
        assert!(names.contains(&"umik1"));
    }

    #[test]
    fn unrelated_nodes_dont_affect_health() {
        let mut reg = ComponentRegistry::from_entries(vec![(
            "signal-gen".to_string(),
            NodeMatch::Exact("pi4audio-signal-gen".to_string()),
        )]);

        let mut g = GraphState::new();
        // Add an unrelated node.
        g.add_node(make_node(10, "some-other-node", "Audio/Source"));

        let transitions = reg.update(&g);
        assert!(transitions.is_empty());
        assert_eq!(
            reg.health("signal-gen"),
            Some(ComponentHealth::Disconnected)
        );
    }
}
