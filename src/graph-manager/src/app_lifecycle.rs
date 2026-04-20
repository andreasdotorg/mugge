//! US-085: Application lifecycle management for mode transitions.
//!
//! Maps modes to systemd user services and orchestrates stop/start
//! transitions. Runs on a background thread — MUST NOT block the
//! PipeWire main loop (safety watchdog would stall).

use crate::routing::Mode;

/// NixOS-stable path to systemctl. The GM service runs with a minimal PATH
/// (only PipeWire/bin), so bare "systemctl" is not found. This symlink is
/// managed by NixOS and always resolves to the active systemd package.
const SYSTEMCTL: &str = "/run/current-system/sw/bin/systemctl";

/// Returns the systemd user services that should be running in a given mode.
pub fn services_for_mode(mode: Mode) -> &'static [&'static str] {
    match mode {
        Mode::Dj => &["pi4audio-mixxx.service"],
        Mode::Live => &["pi4audio-reaper.service"],
        Mode::Standby | Mode::Measurement => &[],
    }
}

/// Returns all services managed by app lifecycle (union of all modes).
pub fn all_managed_services() -> &'static [&'static str] {
    &["pi4audio-mixxx.service", "pi4audio-reaper.service"]
}

/// Stop services not needed for `new_mode`, then start the ones that are.
///
/// Called from a background thread after graph reconciliation completes.
/// Errors are logged but not fatal — the PW graph is correct regardless.
pub fn transition_apps(new_mode: Mode) -> Result<(), String> {
    let wanted = services_for_mode(new_mode);

    // Stop services that are not needed in the new mode.
    for &svc in all_managed_services() {
        if !wanted.contains(&svc) {
            let status = std::process::Command::new(SYSTEMCTL)
                .args(["--user", "stop", svc])
                .status();
            match status {
                Ok(s) if s.success() => log::info!("Stopped {}", svc),
                Ok(s) => log::warn!("systemctl stop {} exited {}", svc, s),
                Err(e) => log::warn!("Failed to run systemctl stop {}: {}", svc, e),
            }
        }
    }

    // Start services needed for the new mode.
    for &svc in wanted {
        let status = std::process::Command::new(SYSTEMCTL)
            .args(["--user", "start", svc])
            .status();
        match status {
            Ok(s) if s.success() => log::info!("Started {}", svc),
            Ok(s) => return Err(format!("systemctl start {} exited {}", svc, s)),
            Err(e) => return Err(format!("Failed to run systemctl start {}: {}", svc, e)),
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dj_mode_runs_mixxx() {
        let svcs = services_for_mode(Mode::Dj);
        assert_eq!(svcs, &["pi4audio-mixxx.service"]);
    }

    #[test]
    fn live_mode_runs_reaper() {
        let svcs = services_for_mode(Mode::Live);
        assert_eq!(svcs, &["pi4audio-reaper.service"]);
    }

    #[test]
    fn standby_runs_nothing() {
        assert!(services_for_mode(Mode::Standby).is_empty());
    }

    #[test]
    fn measurement_runs_nothing() {
        assert!(services_for_mode(Mode::Measurement).is_empty());
    }

    #[test]
    fn all_managed_covers_both() {
        let all = all_managed_services();
        assert!(all.contains(&"pi4audio-mixxx.service"));
        assert!(all.contains(&"pi4audio-reaper.service"));
    }
}
