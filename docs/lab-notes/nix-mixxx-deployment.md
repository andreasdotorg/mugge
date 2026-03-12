# Nix Mixxx 2.5.4 Deployment to Pi

Lab note for deploying Mixxx 2.5.4 from nixpkgs to the Pi via Nix,
bypassing Trixie's Qt 6.8.2 limitation (D-033 Stage 1).

---

## Prerequisites

- Nix installed on Mac (multi-user, flakes enabled)
- `linux-builder` VM running (`nix build` can cross-build for aarch64-linux)
- Pi reachable at `ela@192.168.178.185` with SSH key auth
- Pi on PREEMPT_RT kernel with hardware V3D GL (D-022)

## Procedure

### Step 1: Download cached Mixxx to Mac's Nix store

```bash
# Fetches pre-built aarch64-linux binary from cache.nixos.org (~132 MiB)
# No local compilation needed if the binary cache has it
$ nix build --system aarch64-linux 'nixpkgs#mixxx' --no-link
```

Expected: 2-5 minutes depending on network speed.

### Step 2: Install Nix on Pi (one-time)

```bash
$ ssh ela@192.168.178.185 'sh <(curl -L https://nixos.org/nix/install) --daemon'
```

Follow the prompts. This installs the Nix daemon and creates `/nix/store/`
on the Pi. Only needed once.

### Step 3: Copy Mixxx closure to Pi

```bash
$ nix copy --to ssh://ela@192.168.178.185 'nixpkgs#legacyPackages.aarch64-linux.mixxx'
```

This copies Mixxx and all its runtime dependencies (the "closure") to the
Pi's Nix store. Subsequent copies of the same version are instant (already
present).

### Step 4: Run Mixxx

```bash
# On the Pi:
$ /nix/store/<hash>-mixxx-2.5.4/bin/mixxx
```

To find the exact store path:

```bash
$ nix path-info 'nixpkgs#legacyPackages.aarch64-linux.mixxx'
```

Or create a convenience symlink:

```bash
$ nix build 'nixpkgs#legacyPackages.aarch64-linux.mixxx' -o ~/mixxx-nix
$ ~/mixxx-nix/bin/mixxx
```

## Validation

| Check | Method | Expected |
|-------|--------|----------|
| Version | `mixxx --version` | 2.5.4 |
| Qt version | Check Mixxx about dialog or `ldd` | Qt 6.10.2 |
| VSync | Run with `MESA_VK_WSI_PRESENT_MODE=fifo` or check `--logLevel debug` | VSync=1, no tearing |
| Minimize behavior | Minimize window, restore | No crash, window restores correctly |
| CPU usage (idle) | `top` / `htop` while Mixxx is open, no track loaded | Compare with Mixxx 2.5.0 baseline |
| CPU usage (playing) | Load and play a track, monitor for 60 seconds | Compare with Mixxx 2.5.0 baseline (~85% with hardware GL) |
| Xruns | `pw-top` during playback | 0 xruns |

## Notes

- **linux-builder resources:** Currently 2 cores / 2 GB. Bump to 4 cores /
  4 GB for future patched builds (custom Mixxx with Pi-specific patches).
  Edit `~/.config/nix/nix.conf` or the builder's NixOS config.
- **Mixxx 2.5.0 stays installed via apt** as fallback until 2.5.4 is validated.
  The two installations are independent (apt in `/usr/`, Nix in `/nix/store/`).
- **pw-jack:** The Nix Mixxx may need `pw-jack` from the system PATH.
  If JACK bridge fails, try: `pw-jack /nix/store/<hash>-mixxx-2.5.4/bin/mixxx`.
- **Related:** D-033 (incremental Nix adoption), TK-138 (flake.nix Mixxx
  package), TK-139 (Pi validation).
