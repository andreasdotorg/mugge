# Consultation Matrix — mugge

Universal consultation rules from the orchestration protocol always apply.
The rules below are project-specific additions.

## Domain-Specific Consultation Rules

| Before doing this... | ...consult this advisor |
|----------------------|------------------------|
| Any change to crossover design, filter parameters, or FIR tap count | Audio Engineer + Architect |
| Any change to CamillaDSP configuration (YAML files) | Audio Engineer |
| Any change to channel assignments or signal routing | Audio Engineer + Architect |
| Any change to latency budget (chunksize, buffer sizes) | Audio Engineer |
| Any change to PipeWire or ALSA configuration | Architect |
| Any measurement pipeline design decision | Audio Engineer |
| Any target curve or psychoacoustic smoothing parameter | Audio Engineer |
| Any time alignment or delay value change | Audio Engineer |
| Documentation describing signal processing concepts | Audio Engineer (accuracy review) |
| Documentation describing system architecture | Architect (accuracy review) |
| Any change to the documentation suite structure | Technical Writer |
| Any operational procedure (how-to, runbook) | Audio Engineer (correctness) + Technical Writer (clarity) |
| Any service listening on a network port | Security Specialist |
| Any remote access configuration (SSH, VNC, web UI) | Security Specialist |
| Any firewall or network rules | Security Specialist |
| Any script running as root or with elevated privileges | Security Specialist |
| Any WiFi or network configuration | Security Specialist |
| Any MIDI controller mapping or layout | UX Specialist |
| Any user interaction during a live show | UX Specialist |
| Any web UI or dashboard design | UX Specialist + Security Specialist |
| Any headless operation workflow | UX Specialist |
| Any display requirements or visual feedback design | UX Specialist |
| Any mode-switching procedure | UX Specialist + Audio Engineer |
| Any real-time performance constraint or CPU budget decision | Architect |
| Any memory allocation strategy or buffer sizing | Architect |
| Any systemd service configuration | Architect + Security Specialist |
