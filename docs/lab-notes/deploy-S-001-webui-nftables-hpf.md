# DEPLOY Session S-001: Web UI Fixes, nftables Port 8080, HPF Production Configs

**Evidence basis: RECONSTRUCTED**

Sources: CM session open/close notifications (received in real time) plus
post-hoc command-level detail from worker-deploy (received after session
closure, before worker shutdown). The TW was not in the live event stream
during command execution. Timestamps are approximate (~21:55-22:05 CET),
provided by the worker after the fact.

**Protocol gap:** The deployment target access protocol requires the CM to CC
the TW with each command and its output during DEPLOY-level sessions. This
did not occur during S-001. The CM acknowledged the gap and committed to
explicit CC instructions for deploying workers in future sessions.

---

**Date:** 2026-03-12, approximately 21:55-22:05 CET
**Operator:** worker-deploy (via CM DEPLOY session S-001)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Source commit:** `eec9f2b`
**Safety precondition:** Owner confirmed PA is OFF prior to session grant.

---

## Scope

| Item | Description | Ticket |
|------|-------------|--------|
| Web UI fixes | TK-124 (`system.js` double `* 100`), TK-125 (dead overlay removal) | TK-124, TK-125 |
| nftables port 8080 | Persist firewall rule for web UI access | TK-140 |
| HPF production configs | D-031 mandatory subsonic driver protection in production CamillaDSP configs | D-031 |

---

## Item 1: TK-124/TK-125 -- Web UI Static Files

### 1.1 File Transfer

Six files deployed via scp from local repo to Pi:

```bash
$ scp scripts/web-ui/static/js/dashboard.js ela@192.168.178.185:/home/ela/web-ui/static/js/dashboard.js
$ scp scripts/web-ui/static/index.html ela@192.168.178.185:/home/ela/web-ui/static/index.html
$ scp scripts/web-ui/static/js/system.js ela@192.168.178.185:/home/ela/web-ui/static/js/system.js
$ scp scripts/web-ui/static/js/spectrum.js ela@192.168.178.185:/home/ela/web-ui/static/js/spectrum.js
$ scp scripts/web-ui/static/style.css ela@192.168.178.185:/home/ela/web-ui/static/style.css
$ scp scripts/web-ui/static/js/pcm-worklet.js ela@192.168.178.185:/home/ela/web-ui/static/js/pcm-worklet.js
```

All completed without error.

### 1.2 Checksum Verification

```bash
$ ssh ela@192.168.178.185 "md5sum /home/ela/web-ui/static/js/dashboard.js \
    /home/ela/web-ui/static/index.html \
    /home/ela/web-ui/static/js/system.js \
    /home/ela/web-ui/static/js/spectrum.js \
    /home/ela/web-ui/static/style.css \
    /home/ela/web-ui/static/js/pcm-worklet.js"
4a9b4d1422e06f8cfa653a1fafaea188  /home/ela/web-ui/static/js/dashboard.js
184f3c9d75834d1623edd7e5597927ca  /home/ela/web-ui/static/index.html
1fcf53e745cf6113cd5206ef295e1fa1  /home/ela/web-ui/static/js/system.js
51cf80d1f4e73eb036037d68d628ea3e  /home/ela/web-ui/static/js/spectrum.js
7c4548340dfa9eb7180d6a6f26bd25a7  /home/ela/web-ui/static/style.css
b6b154a535cea43ddd8c289a08f8d6f8  /home/ela/web-ui/static/js/pcm-worklet.js
```

All 6 checksums matched local repo files.

### 1.3 Service Restart

```bash
$ ssh ela@192.168.178.185 "systemctl --user restart pi4-audio-webui"
```

Initial restart hung in `deactivating (stop-sigterm)` for ~50 seconds. Uvicorn
was waiting for JACK background tasks to complete. Force-stopped and restarted:

```bash
$ ssh ela@192.168.178.185 "systemctl --user kill pi4-audio-webui"
$ ssh ela@192.168.178.185 "systemctl --user start pi4-audio-webui"
$ ssh ela@192.168.178.185 "systemctl --user status pi4-audio-webui"
● pi4-audio-webui.service - Pi4 Audio Workstation monitoring web UI (D-020)
     Active: active (running) since Thu 2026-03-12 21:59:08 CET; 3s ago
   Main PID: 103887 (uvicorn)
```

**Observation:** The ~50s hang on restart is worth investigating. If the web UI
service needs to be restarted during a gig (e.g., after a crash), a 50-second
outage of the monitoring dashboard is undesirable. The uvicorn shutdown timeout
or JACK client cleanup may need tuning.

### 1.4 Content Verification

Homepage loads:

```bash
$ ssh ela@192.168.178.185 "curl -sk https://localhost:8080/ | head -5"
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
```

TK-125 check (dead overlay removed):

```bash
$ ssh ela@192.168.178.185 "curl -sk https://localhost:8080/ | grep -i 'click\|overlay\|audio-start\|start.audio'"
<!-- Reconnect overlay -->
<div class="reconnect-overlay" id="reconnect-overlay">
```

Result: Only the reconnect overlay remains. No "click to start audio" overlay. **PASS.**

TK-124 check (double multiplication removed):

```bash
$ ssh ela@192.168.178.185 "curl -sk https://localhost:8080/static/js/system.js | grep 'processing_load'"
            cdsp.processing_load.toFixed(1) + "%");
```

Result: No `* 100` multiplication on `processing_load`. **PASS.**

---

## Item 2: TK-140 -- nftables Port 8080

### 2.1 Runtime Ruleset Check

```bash
$ ssh ela@192.168.178.185 "sudo nft list ruleset"
table inet filter {
    chain input {
        type filter hook input priority filter; policy drop;
        ip saddr 192.168.0.0/16 tcp dport 8080 accept
        tcp dport 5900 accept
        iif "lo" accept
        ct state established,related accept
        ip protocol icmp accept
        ip6 nexthdr ipv6-icmp accept
        tcp dport 22 accept
        udp dport 5353 accept
        log prefix "nftables-drop: " limit rate 5/minute burst 5 packets counter packets 17130 bytes 1471039 drop
    }
    ...
}
```

Port 8080 rule present in runtime ruleset, restricted to `192.168.0.0/16`.

### 2.2 Persistent Config Check

```bash
$ ssh ela@192.168.178.185 "cat /etc/nftables.conf"
```

Output contains `ip saddr 192.168.0.0/16 tcp dport 8080 accept` -- rule
already persistent in `/etc/nftables.conf`.

### 2.3 Service Status

```bash
$ ssh ela@192.168.178.185 "systemctl is-enabled nftables"
enabled

$ ssh ela@192.168.178.185 "systemctl status nftables"
● nftables.service - nftables
     Active: active (exited) since Tue 2026-03-10 22:52:11 CET; 1 day 23h ago
```

Result: Rule already persistent. **No changes made.** TK-140 was already done.

**Note:** `docs/project/status.md` listed TK-140 as "runtime-only, lost on
reboot." This finding contradicts that -- the rule was already persisted in
`/etc/nftables.conf` and the service is enabled. The status entry should be
corrected.

---

## Item 3: D-031 -- HPF in Production Configs

### 3.1 Deploy Base Configs from Repo

```bash
$ scp configs/camilladsp/production/dj-pa.yml ela@192.168.178.185:/etc/camilladsp/configs/dj-pa.yml
$ scp configs/camilladsp/production/live.yml ela@192.168.178.185:/etc/camilladsp/configs/live.yml
```

### 3.2 Add HPF Filters via Python Script

A Python script was written to `/tmp/add_hpf_prod.py` on the Pi and executed
with `sudo python3`. The script adds two Butterworth high-pass filters to each
production config:

- `wideband_hpf`: 4th-order Butterworth HPF at 25 Hz (channels 0-1, mains)
- `sub_hpf`: 4th-order Butterworth HPF at 20 Hz (channels 2-3, subs)

Both filters are inserted into the pipeline immediately after the mixer stage,
before existing filter stages.

```python
# /tmp/add_hpf_prod.py (executed on Pi)
import yaml
for config_file in ["/etc/camilladsp/production/dj-pa.yml",
                    "/etc/camilladsp/production/live.yml"]:
    with open(config_file) as f:
        config = yaml.safe_load(f)
    config["filters"]["wideband_hpf"] = {
        "type": "BiquadCombo",
        "parameters": {"type": "ButterworthHighpass", "freq": 25, "order": 4}
    }
    config["filters"]["sub_hpf"] = {
        "type": "BiquadCombo",
        "parameters": {"type": "ButterworthHighpass", "freq": 20, "order": 4}
    }
    old_pipeline = config["pipeline"]
    new_pipeline = [old_pipeline[0]]  # Mixer
    new_pipeline.append({"type": "Filter", "channels": [0, 1],
                         "names": ["wideband_hpf"]})
    new_pipeline.append({"type": "Filter", "channels": [2, 3],
                         "names": ["sub_hpf"]})
    for step in old_pipeline[1:]:
        new_pipeline.append(step)
    config["pipeline"] = new_pipeline
    with open(config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
```

Output:

```
Updated /etc/camilladsp/production/dj-pa.yml: 8 pipeline steps
Updated /etc/camilladsp/production/live.yml: 8 pipeline steps
```

The same script was also applied to the user-owned copies at
`/etc/camilladsp/configs/dj-pa.yml` and `/etc/camilladsp/configs/live.yml`.

### 3.3 Config Syntax Validation

```bash
$ ssh ela@192.168.178.185 "camilladsp -c /etc/camilladsp/production/dj-pa.yml"
2026-03-12 22:04:45.375039 INFO CamillaDSP version 3.0.1
Config is valid

$ ssh ela@192.168.178.185 "camilladsp -c /etc/camilladsp/production/live.yml"
2026-03-12 22:04:45.401591 INFO CamillaDSP version 3.0.1
Config is valid
```

Both configs pass CamillaDSP syntax validation.

### 3.4 Live Testing via Websocket API

Each config was loaded into the running CamillaDSP instance via the
pycamilladsp websocket API and verified for correct operation.

**dj-pa.yml:**

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| ProcessingState | RUNNING | RUNNING | PASS |
| Processing load | <15% | 5.2% | PASS |
| Clipped samples | 0 | 0 | PASS |

**live.yml:**

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| ProcessingState | RUNNING | RUNNING | PASS |
| Processing load | <45% | 21.0% | PASS |
| Clipped samples | 0 | 0 | PASS |

### 3.5 Config Restoration

Original active config (`bose-home.yml`) restored via websocket API:

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| ProcessingState | RUNNING | RUNNING | PASS |
| Processing load | reasonable | 17.1% | PASS |
| Clipped samples | 0 | 0 | PASS |

### 3.6 Cleanup

```bash
$ ssh ela@192.168.178.185 "rm -f /tmp/add_hpf.py /tmp/add_hpf_prod.py"
```

Temporary scripts removed.

---

## Validation Summary

| Item | Expected | Actual | Result |
|------|----------|--------|--------|
| TK-124 system.js fix | No `* 100` on processing_load | Confirmed | PASS |
| TK-125 dead overlay | No "click to start audio" | Only reconnect overlay | PASS |
| File checksums (6 files) | Match local repo | All 6 match | PASS |
| Web UI service | active (running) | active (running), PID 103887 | PASS |
| TK-140 nftables 8080 | Persistent rule | Already persistent | PASS (no-op) |
| D-031 dj-pa.yml syntax | Config is valid | Config is valid | PASS |
| D-031 live.yml syntax | Config is valid | Config is valid | PASS |
| D-031 dj-pa.yml live test | RUNNING, <15%, 0 clipped | RUNNING, 5.2%, 0 clipped | PASS |
| D-031 live.yml live test | RUNNING, <45%, 0 clipped | RUNNING, 21.0%, 0 clipped | PASS |
| Config restoration | bose-home.yml RUNNING | RUNNING, 17.1%, 0 clipped | PASS |

## Deviations from Plan

1. **TK-140 required no action.** The nftables port 8080 rule was already
   persistent. `docs/project/status.md` incorrectly listed it as runtime-only.
2. **Web UI service restart hung ~50s.** The `systemctl --user restart` command
   hung during deactivation. Required `kill` + manual `start`. This is a
   potential operational concern for gig-time service recovery.

## Post-Deployment State

- Web UI service: active (running), PID 103887
- CamillaDSP: RUNNING with bose-home.yml (original config restored)
- nftables: unchanged (already correct)
- Production configs on Pi: dj-pa.yml and live.yml now include D-031 HPF filters
- DEPLOY exclusive lock: released
- PA: remained OFF throughout session

## Notes

- This lab note is RECONSTRUCTED. The TW was not CC'd during command execution
  (protocol gap acknowledged by CM). Command-level detail was provided by
  worker-deploy after session closure. Timestamps are approximate.
- The CM committed to explicit CC instructions for future DEPLOY sessions.
- The ~50s web UI restart hang should be tracked. If uvicorn's shutdown timeout
  or JACK client cleanup is the cause, a shorter `TimeoutStopSec` in the
  systemd unit or graceful JACK disconnect on SIGTERM may help.
- HPF filter frequencies (25 Hz wideband, 20 Hz sub) are conservative subsonic
  protection values per D-031. These are IIR biquads in the CamillaDSP pipeline,
  separate from the FIR convolution filters. They protect against subsonic
  content regardless of the loaded FIR filters.
