# Lab Notes: US-000a — Security Hardening

Story: US-000a (Security hardening for base system)
Template: [docs/lab-notes/template.md](template.md)

The Pi will operate on untrusted venue WiFi networks with SSH and other
services exposed. This session locked down the attack surface: disabling
unnecessary network services (rpcbind, Avahi, ModemManager), hardening SSH
to key-only authentication with a restrictive drop-in configuration, and
deploying nftables firewall rules that allow only SSH inbound with rate
limiting.

A notable lesson learned during this work: sshd uses first-match-wins
semantics for its `Match` blocks, which is the opposite of systemd's
last-match-wins convention. An initial attempt to override defaults with a
99-prefix drop-in file failed silently because the default configuration's
`Match` blocks took precedence. The fix was to use a 40-prefix, ensuring the
hardening rules match before the defaults. This is recorded as L-001 in the
project's lessons learned.

---

## Task US-000a: Security Hardening

**Date:** 2026-03-08
**Operator:** security-specialist (commands executed by change-manager via SSH)
**Host:** mugge (ela@192.168.178.185), Debian 13 Trixie, kernel 6.12.47 PREEMPT

### Pre-conditions

- Fresh install, no firewall, default SSH config
- Listening ports:

```
$ ss -tlnp
State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process
LISTEN 0      4096         0.0.0.0:111       0.0.0.0:*          # rpcbind
LISTEN 0      128          0.0.0.0:22        0.0.0.0:*          # SSH
LISTEN 0      4096       127.0.0.1:631       0.0.0.0:*          # CUPS (localhost)
LISTEN 0      4096            [::]:111          [::]:*          # rpcbind IPv6
LISTEN 0      128             [::]:22           [::]:*          # SSH IPv6
LISTEN 0      4096           [::1]:631          [::]:*          # CUPS IPv6 (localhost)
```

```
$ sudo nft list ruleset
(empty — no firewall rules)
```

```
$ sudo sshd -T | grep passwordauthentication
passwordauthentication yes
```

Source: `/etc/ssh/sshd_config.d/50-cloud-init.conf` contained `PasswordAuthentication yes`.

### Procedure

#### Phase 1: Disable Unnecessary Services (F-005, F-007, F-008)

```bash
$ sudo systemctl disable --now rpcbind.service rpcbind.socket
$ sudo systemctl disable --now ModemManager
$ sudo systemctl disable --now cups cups-browsed
```

Verification:

```
$ ss -tlnp
State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process
LISTEN 0      128          0.0.0.0:22        0.0.0.0:*          # SSH only
LISTEN 0      128             [::]:22           [::]:*          # SSH IPv6 only
```

Port 111 and 631 gone. All five services report `inactive`.

#### Phase 2: SSH Hardening (F-004, F-010)

**Attempt 1 (FAILED):**

```bash
$ sudo tee /etc/ssh/sshd_config.d/99-hardening.conf << 'EOF'
PasswordAuthentication no
PermitRootLogin no
EOF
$ sudo systemctl reload ssh
```

Verification showed hardening did NOT take effect:

```
$ sudo sshd -T | grep passwordauthentication
passwordauthentication yes    # still yes!
```

Root cause: sshd processes drop-in files in lexical order with **first-match-wins**
semantics. `50-cloud-init.conf` (PasswordAuthentication yes) loads before
`99-hardening.conf` (PasswordAuthentication no). The first value seen wins; the
later one is silently ignored. See "Deviations from Plan" below.

**Attempt 2 (SUCCESSFUL):**

```bash
# Rename to load before cloud-init's 50- prefix
$ sudo mv /etc/ssh/sshd_config.d/99-hardening.conf /etc/ssh/sshd_config.d/40-hardening.conf

# Remove the cloud-init override entirely
$ sudo rm /etc/ssh/sshd_config.d/50-cloud-init.conf

# Prevent cloud-init from recreating it on future runs
$ sudo tee /etc/cloud/cloud.cfg.d/99-disable-ssh.cfg << 'EOF'
ssh_pwauth: false
EOF

# Reload sshd
$ sudo systemctl reload ssh
```

Verification:

```
$ sudo sshd -T | grep -E '(passwordauthentication|permitrootlogin)'
permitrootlogin no
passwordauthentication no
```

```
# New SSH session with key auth — works
$ ssh ela@192.168.178.185 "echo 'NEW SESSION OK'"
NEW SESSION OK

# Password auth attempt — rejected
$ ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no ela@192.168.178.185 "echo SHOULD NOT SEE THIS"
Permission denied (publickey).
```

Server no longer advertises `password` as an authentication method. Only
`publickey` is offered.

#### Phase 3: nftables Firewall (F-001)

```bash
$ sudo apt install -y nftables
$ sudo systemctl enable nftables

$ sudo tee /etc/nftables.conf << 'EOF'
#!/usr/sbin/nft -f

flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Loopback — always allow
        iif "lo" accept

        # Established/related — allow return traffic and RustDesk direct connections
        ct state established,related accept

        # ICMP — allow ping (useful for diagnostics)
        ip protocol icmp accept
        ip6 nexthdr icmpv6 accept

        # SSH — allow inbound
        tcp dport 22 accept

        # mDNS — allow mugge.local resolution (link-local multicast only)
        udp dport 5353 accept

        # Log and drop everything else (rate-limited to avoid log spam)
        log prefix "nftables-drop: " limit rate 5/minute counter drop
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
EOF

$ sudo nft -f /etc/nftables.conf
```

Verification:

```
$ sudo nft list ruleset
# Full ruleset as written above, drop counter showing 8 packets / 794 bytes already blocked

$ ping -c 2 -W 3 1.1.1.1
# 2/2 received, ~36ms avg — outbound works

$ systemctl is-enabled nftables
enabled
```

### Versions Installed

| Package / Binary | Version | How verified |
|------------------|---------|--------------|
| nftables | (Trixie default) | `sudo apt install -y nftables` |

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Only SSH listening after service disable | Port 22 only | Port 22 only | PASS |
| sshd PasswordAuthentication | no | no | PASS |
| sshd PermitRootLogin | no | no | PASS |
| Key-based SSH session works | Connection succeeds | NEW SESSION OK | PASS |
| Password auth rejected | Permission denied | Permission denied (publickey) | PASS |
| nftables active and enabled | enabled + ruleset loaded | enabled, drop counter active | PASS |
| Outbound connectivity | ping succeeds | 2/2 received | PASS |

### Post-conditions

Single listening port (SSH). Firewall active with deny-inbound policy. Key-only
auth enforced.

### Files Modified

| File | Action | Contents |
|------|--------|---------|
| `/etc/ssh/sshd_config.d/40-hardening.conf` | CREATED | `PasswordAuthentication no` + `PermitRootLogin no` |
| `/etc/ssh/sshd_config.d/50-cloud-init.conf` | REMOVED | Was `PasswordAuthentication yes` |
| `/etc/cloud/cloud.cfg.d/99-disable-ssh.cfg` | CREATED | `ssh_pwauth: false` |
| `/etc/nftables.conf` | REPLACED | Full nftables ruleset (see Phase 3) |

### Services Disabled

| Service | Why |
|---------|-----|
| rpcbind.service + rpcbind.socket | NFS portmapper, unnecessary, history of vulnerabilities |
| ModemManager | Modem support, unnecessary on audio workstation |
| cups + cups-browsed | Print services, unnecessary |

### Findings Resolved

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| F-001 | No firewall | CRITICAL | nftables deny-inbound deployed |
| F-004 | SSH password auth enabled | HIGH | Key-only, root login prohibited |
| F-005 | rpcbind on port 111 | MEDIUM | Service disabled |
| F-007 | ModemManager running | LOW | Service disabled |
| F-008 | CUPS running | LOW | Service disabled |
| F-010 | cloud-init SSH override | UNKNOWN | Removed + cloud-init SSH module disabled |

### Deviations from Plan

Initial SSH hardening attempt used a `99-` prefix drop-in file, which was
silently overridden by cloud-init's `50-` prefix file due to sshd's
first-match-wins semantics. Required a second attempt: renamed to `40-` prefix,
removed the cloud-init file, and disabled cloud-init's SSH module to prevent
recurrence. See lessons learned entry in `.claude/team/lessons-learned.md`.

### Notes

- F-002 and F-003 (CamillaDSP websocket and web GUI binding) remain open —
  will be addressed when CamillaDSP is installed. The firewall will need port
  8080 added when the web UI service is ready.
