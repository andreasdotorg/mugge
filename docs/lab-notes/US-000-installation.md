# Lab Notes: US-000 — Base Installation

Story: US-000 (Base system installation and configuration)
Template: [docs/lab-notes/template.md](template.md)

---

## Task T0: ALSA Loopback Module Configuration

**Date:** 2026-03-08 13:42 (CET)
**Operator:** Claude worker via SSH
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8 SMP PREEMPT aarch64

### Pre-conditions

- Disk space: 117G total, 6.7G used, 106G avail (6%)
- No Loopback card present (cards 0-7: vc4hdmi0, vc4hdmi1, Headphones, USBStreamer, U18dB, Ultra, SE25, mk2)

### Procedure

```bash
# Step 1: Check module availability
$ /sbin/modinfo snd-aloop
filename:       /lib/modules/6.12.47+rpt-rpi-v8/kernel/sound/drivers/snd-aloop.ko.xz
license:        GPL
description:    A loopback soundcard
author:         Jaroslav Kysela <perex@perex.cz>
srcversion:     42674B373DD0E18BA8900B9
depends:        snd-timer,snd,snd-pcm
intree:         Y
name:           snd_aloop
vermagic:       6.12.47+rpt-rpi-v8 SMP preempt mod_unload modversions aarch64
parm:           index:Index value for loopback soundcard. (array of int)
parm:           id:ID string for loopback soundcard. (array of charp)
parm:           enable:Enable this loopback soundcard. (array of bool)
parm:           pcm_substreams:PCM substreams # (1-8) for loopback driver. (array of int)
parm:           pcm_notify:Break capture when PCM format/rate/channels changes. (array of int)
parm:           timer_source:Sound card name or number [...]. (array of charp)
```

```bash
# Step 2: Load snd-aloop module
$ sudo modprobe snd-aloop index=10 pcm_substreams=2
# (no output, success)
```

```bash
# Step 3: Create persistent module loading config
$ echo "snd-aloop" | sudo tee /etc/modules-load.d/audio.conf
snd-aloop
```

```bash
# Step 4: Create modprobe options
$ echo "options snd-aloop index=10 pcm_substreams=2 channels=4" | sudo tee /etc/modprobe.d/snd-aloop.conf
options snd-aloop index=10 pcm_substreams=2 channels=4
```

```bash
# Step 5: Verify Loopback card is present
$ cat /proc/asound/cards
 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0
                      vc4-hdmi-0
 1 [vc4hdmi1       ]: vc4-hdmi - vc4-hdmi-1
                      vc4-hdmi-1
 2 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones
                      bcm2835 Headphones
 3 [USBStreamer    ]: USB-Audio - USBStreamer
                      miniDSP USBStreamer at usb-0000:01:00.0-1.4, high speed
 4 [U18dB          ]: USB-Audio - Umik-1  Gain: 18dB
                      miniDSP Umik-1  Gain: 18dB at usb-0000:01:00.0-1.2.1, full speed
 5 [Ultra          ]: USB-Audio - DJControl Mix Ultra
                      Guillemot Corporation DJControl Mix Ultra at usb-0000:01:00.0-1.2.4.1, full spe
 6 [SE25           ]: USB-Audio - SE25
                      Nektar SE25 at usb-0000:01:00.0-1.2.4.2, full speed
 7 [mk2            ]: USB-Audio - APC mini mk2
                      AKAI professional APC mini mk2 at usb-0000:01:00.0-1.2.4.3, full speed
10 [Loopback       ]: Loopback - Loopback
                      Loopback 1
```

```bash
# Step 6: Full aplay -l output
$ aplay -l
**** List of PLAYBACK Hardware Devices ****
card 0: vc4hdmi0 [vc4-hdmi-0], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 1: vc4hdmi1 [vc4-hdmi-1], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 2: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]
  Subdevices: 8/8
  Subdevice #0: subdevice #0
  (subdevices #1-#7 omitted)
card 3: USBStreamer [USBStreamer], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 10: Loopback [Loopback], device 0: Loopback PCM [Loopback PCM]
  Subdevices: 2/2
  Subdevice #0: subdevice #0
  Subdevice #1: subdevice #1
card 10: Loopback [Loopback], device 1: Loopback PCM [Loopback PCM]
  Subdevices: 2/2
  Subdevice #0: subdevice #0
  Subdevice #1: subdevice #1
```

### Versions Installed

| Package / Binary | Version | How verified |
|------------------|---------|--------------|
| snd-aloop (kernel module) | built-in to kernel 6.12.47+rpt-rpi-v8 | `modinfo snd-aloop` |

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| snd-aloop module loads | Module loads without error | Loaded successfully | PASS |
| Loopback in /proc/asound/cards | Card 10 "Loopback" | Card 10 [Loopback] present | PASS |
| Loopback in aplay -l | Listed with 2 substreams | Listed at card 10, device 0 and 1, 2 substreams each | PASS |
| Persistent config files created | /etc/modules-load.d/audio.conf and /etc/modprobe.d/snd-aloop.conf | Both exist, correct contents | PASS |

### Post-conditions

- Disk space: unchanged (module config files only)

### Deviations from Plan

- The `channels=4` parameter in the modprobe options is not a recognized parameter for
  snd-aloop (valid params: index, id, enable, pcm_substreams, pcm_notify, timer_source).
  It was included as specified in the task instructions. modprobe does not error on
  unknown module parameters when the module is already loaded. This should be verified
  on next reboot to confirm it does not prevent module loading.

### Notes

- Kernel version: 6.12.47+rpt-rpi-v8 (PREEMPT, not PREEMPT_RT)
- Module options applied: index=10, pcm_substreams=2
- Card index 10 avoids conflicts with USB devices (0-7 currently used)

---

## Task T1: CamillaDSP v3.0.1 Installation

**Date:** 2026-03-08 13:43 (CET)
**Operator:** Claude worker via SSH
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8

### Pre-conditions

- CamillaDSP not previously installed
- Disk space: 117G total, 6.7G used

### Procedure

```bash
# Step 1: Download aarch64 binary
$ cd /tmp && wget -q https://github.com/HEnquist/camilladsp/releases/download/v3.0.1/camilladsp-linux-aarch64.tar.gz
$ ls -la camilladsp-linux-aarch64.tar.gz
-rw-rw-r-- 1 ela ela 2495232 Mar 20  2025 camilladsp-linux-aarch64.tar.gz
```

```bash
# Step 2: Record sha256sum
$ sha256sum /tmp/camilladsp-linux-aarch64.tar.gz
bba066f690fdfb3e97e749bf137b7563f09590ae583ae359c5be29d95eff7d50  /tmp/camilladsp-linux-aarch64.tar.gz
```

```bash
# Step 3: Extract and install
$ cd /tmp && tar xf camilladsp-linux-aarch64.tar.gz
$ ls -la /tmp/camilladsp
-rwxr-xr-x 1 ela ela 6890912 Mar 20  2025 /tmp/camilladsp
$ sudo cp /tmp/camilladsp /usr/local/bin/camilladsp
$ sudo chmod 755 /usr/local/bin/camilladsp
```

```bash
# Step 4: Verify version
$ camilladsp --version
CamillaDSP 3.0.1
```

```bash
# Step 5: Create directories and set ownership
$ sudo mkdir -p /etc/camilladsp/configs /etc/camilladsp/coeffs /etc/camilladsp/filters
$ sudo chown -R ela:ela /etc/camilladsp
$ ls -la /etc/camilladsp/
total 28
drwxr-xr-x   5 ela  ela   4096 Mar  8 13:43 .
drwxr-xr-x 135 root root 12288 Mar  8 13:43 ..
drwxr-xr-x   2 ela  ela   4096 Mar  8 13:43 coeffs
drwxr-xr-x   2 ela  ela   4096 Mar  8 13:43 configs
drwxr-xr-x   2 ela  ela   4096 Mar  8 13:43 filters
```

```bash
# Step 6: Check if binary is static (ldd output)
$ ldd /usr/local/bin/camilladsp
	linux-vdso.so.1 (0x0000007fbe95c000)
	libasound.so.2 => /lib/aarch64-linux-gnu/libasound.so.2 (0x0000007fbe280000)
	libgcc_s.so.1 => /lib/aarch64-linux-gnu/libgcc_s.so.1 (0x0000007fbe240000)
	libpthread.so.0 => /lib/aarch64-linux-gnu/libpthread.so.0 (0x0000007fbe210000)
	libm.so.6 => /lib/aarch64-linux-gnu/libm.so.6 (0x0000007fbe160000)
	libdl.so.2 => /lib/aarch64-linux-gnu/libdl.so.2 (0x0000007fbe130000)
	libc.so.6 => /lib/aarch64-linux-gnu/libc.so.6 (0x0000007fbdf70000)
	/lib/ld-linux-aarch64.so.1 (0x0000007fbe920000)
# RESULT: Dynamically linked (not static). Depends on libasound, libgcc_s, libc, etc.
```

```bash
# Step 7: Full help output
$ camilladsp --help
CamillaDSP v3.0.1
Henrik Enquist <henrik.enquist@gmail.com>
A flexible tool for processing audio

Built with features: websocket

Supported device types:
Capture: RawFile, WavFile, Stdin, SignalGenerator, Alsa
Playback: File, Stdout, Alsa

Usage: camilladsp [OPTIONS] [CONFIGFILE]

Arguments:
  [CONFIGFILE]  The configuration file to use

Options:
  -c, --check                          Check config file and exit
  -s, --statefile <STATEFILE>          Use the given file to persist the state
  -v...                                Increase message verbosity
  -l, --loglevel <LOGLEVEL>            Set log level [possible values: trace, debug, info, warn, error, off]
  -o, --logfile <LOGFILE>              Write logs to the given file path
      --log_rotate_size <ROTATE_SIZE>  Rotate log file when the size in bytes exceeds this value
      --log_keep_nbr <KEEP_NBR>       Number of previous log files to keep
  -a, --address <ADDRESS>              IP address to bind websocket server to
  -p, --port <PORT>                    Port for websocket server
  -w, --wait                           Wait for config from websocket
  -g, --gain <GAIN>                    Initial gain in dB for main volume control
      --gain1 <GAIN1>                  Initial gain in dB for Aux1 fader
      --gain2 <GAIN2>                  Initial gain in dB for Aux2 fader
      --gain3 <GAIN3>                  Initial gain in dB for Aux3 fader
      --gain4 <GAIN4>                  Initial gain in dB for Aux4 fader
  -m, --mute                           Start with main volume control muted
      --mute1                          Start with Aux1 fader muted
      --mute2                          Start with Aux2 fader muted
      --mute3                          Start with Aux3 fader muted
      --mute4                          Start with Aux4 fader muted
  -e, --extra_samples <EXTRA_SAMPLES>  Override number of extra samples in config
  -n, --channels <CHANNELS>            Override number of channels of capture device in config
  -r, --samplerate <SAMPLERATE>        Override samplerate in config
  -f, --format <FORMAT>                Override sample format of capture device in config
                                       [possible values: S16LE, S24LE, S24LE3, S32LE, FLOAT32LE, FLOAT64LE]
  -h, --help                           Print help
  -V, --version                        Print version
```

### Versions Installed

| Package / Binary | Version | How verified |
|------------------|---------|--------------|
| CamillaDSP | 3.0.1 | `camilladsp --version` |

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Binary at /usr/local/bin/camilladsp | Exists, executable | -rwxr-xr-x, 6,890,912 bytes | PASS |
| Version output | CamillaDSP 3.0.1 | CamillaDSP 3.0.1 | PASS |
| Websocket address flag exists | `-a` / `--address` flag | Present: `-a, --address <ADDRESS>` | PASS |
| Directories created | /etc/camilladsp/{configs,coeffs,filters} | All present, owned by ela:ela | PASS |
| sha256sum recorded | Checksum available | bba066f690fdfb3e97e749bf137b7563f09590ae583ae359c5be29d95eff7d50 | PASS |
| Systemd service NOT created | No service file | Confirmed: no service created | PASS |

### Post-conditions

- Binary installed at /usr/local/bin/camilladsp (6.6MB)
- Config directories at /etc/camilladsp/ owned by ela:ela

### Deviations from Plan

None.

### Notes

- Binary is dynamically linked, depends on libasound.so.2 (ALSA). This is expected
  for a build with ALSA backend support.
- Built with features: websocket (no PulseAudio, no JACK -- uses ALSA directly)
- Supported capture types: RawFile, WavFile, Stdin, SignalGenerator, Alsa
- Supported playback types: File, Stdout, Alsa
- The `-a` / `--address` flag confirms we can bind websocket to 127.0.0.1 only (firewall requirement)
- Aux faders (gain1-4, mute1-4) available -- useful for per-channel gain control

---

## Task T2: Python DSP Libraries

**Date:** 2026-03-08 13:43 (CET)
**Operator:** Claude worker via SSH
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8

### Pre-conditions

- Python 3.13.5 installed (system)
- No venv previously created
- Disk space: 117G total, 7.3G used (after T1)

### Procedure

```bash
# Step 1: Install system dependencies
$ sudo apt install -y libportaudio2 libsndfile1 libopenblas-dev liblapack-dev gfortran
# libsndfile1 already installed (1.2.2-2+b1)
# Installed: gfortran (4:14.2.0-1), liblapack-dev (3.12.1-6), libopenblas-dev (0.3.29+ds-3),
#   libportaudio2 (19.6.0-1.2+b3), gfortran-14 (14.2.0-19), libgfortran-14-dev,
#   libopenblas0-pthread (0.3.29+ds-3), libopenblas-pthread-dev (0.3.29+ds-3)
# Download: 21.4 MB, Space: 122 MB
```

```bash
# Step 2: Check Python version
$ python3 --version
Python 3.13.5
```

```bash
# Step 3: Create venv
$ python3 -m venv /home/ela/audio-workstation-venv
```

```bash
# Step 4: Upgrade pip
$ source /home/ela/audio-workstation-venv/bin/activate
$ pip install --upgrade pip
Successfully installed pip-26.0.1
```

```bash
# Step 5: Install pycamilladsp (from GitHub, PyPI version incompatible with Python 3.13)
$ pip install git+https://github.com/HEnquist/pycamilladsp.git
# Cloned commit bf378f58cf9ab031f222ddc3249f042b09623019
# Installed: camilladsp-3.0.0, PyYAML-6.0.3, websocket-client-1.9.0
```

```bash
# Step 6: Install remaining packages
$ pip install numpy scipy soundfile sounddevice matplotlib
# ALL installed from prebuilt wheels (no source compilation needed)
# numpy-2.4.2, scipy-1.17.1, soundfile-0.13.1, sounddevice-0.5.5, matplotlib-3.10.8
# Plus dependencies: cffi, contourpy, cycler, fonttools, kiwisolver, packaging,
#   pillow, pycparser, pyparsing, python-dateutil, six
```

```bash
# Step 7: Verify all imports
$ python3 -c "import numpy; import scipy; import soundfile; import camilladsp; import sounddevice; print('All imports OK')"
All imports OK
```

```bash
# Step 8: Full pip freeze
$ pip freeze
camilladsp @ git+https://github.com/HEnquist/pycamilladsp.git@bf378f58cf9ab031f222ddc3249f042b09623019
cffi==2.0.0
contourpy==1.3.3
cycler==0.12.1
fonttools==4.61.1
kiwisolver==1.4.9
matplotlib==3.10.8
numpy==2.4.2
packaging==26.0
pillow==12.1.1
pycparser==3.0
pyparsing==3.3.2
python-dateutil==2.9.0.post0
PyYAML==6.0.3
scipy==1.17.1
six==1.17.0
sounddevice==0.5.5
soundfile==0.13.1
websocket-client==1.9.0
```

### Versions Installed

| Package / Binary | Version | How verified |
|------------------|---------|--------------|
| Python | 3.13.5 | `python3 --version` |
| numpy | 2.4.2 | `pip freeze` |
| scipy | 1.17.1 | `pip freeze` |
| soundfile | 0.13.1 | `pip freeze` |
| camilladsp (pycamilladsp) | 3.0.0 (git bf378f5) | `pip freeze` |
| sounddevice | 0.5.5 | `pip freeze` |
| matplotlib | 3.10.8 | `pip freeze` |
| pip | 26.0.1 | `pip --version` |

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Venv created | /home/ela/audio-workstation-venv exists | Created successfully | PASS |
| All imports succeed | "All imports OK" | "All imports OK" | PASS |
| scipy from wheel (no compilation) | Prebuilt wheel | manylinux_2_27_aarch64 wheel used | PASS |

### Post-conditions

- Venv at /home/ela/audio-workstation-venv
- 18 packages installed

### Deviations from Plan

- `pycamilladsp` is not available on PyPI for Python 3.13. The PyPI package has upper
  version bounds that exclude 3.13. Installed from GitHub main branch instead
  (commit bf378f5). The import name is `camilladsp` (not `pycamilladsp`).
- scipy installed from a prebuilt wheel (no 20-30 min compilation needed). The Debian
  Trixie version of Python 3.13 has prebuilt aarch64 wheels on PyPI.

### Notes

- System deps installed: libportaudio2, libsndfile1, libopenblas-dev, liblapack-dev, gfortran
- All Python packages had prebuilt aarch64 wheels available -- fast installation

---

## Task T7: RustDesk Installation

**Date:** 2026-03-08 13:45 (CET)
**Operator:** Claude worker via SSH
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8

### Pre-conditions

- RustDesk not previously installed
- Disk space: 117G total, 7.3G used

### Procedure

```bash
# Step 1: Download RustDesk aarch64 .deb
$ cd /tmp && wget -q 'https://github.com/rustdesk/rustdesk/releases/download/1.3.9/rustdesk-1.3.9-aarch64.deb' -O rustdesk-aarch64.deb
$ ls -la rustdesk-aarch64.deb
-rw-rw-r-- 1 ela ela 18601052 Mar 31  2025 rustdesk-aarch64.deb
```

```bash
# Step 2: Install .deb and fix dependencies
$ sudo dpkg -i /tmp/rustdesk-aarch64.deb
# Initial dependency errors: libxdo3, gstreamer1.0-pipewire missing
$ sudo apt install -f -y
# Installed: libxdo3 (1:3.20160805.1-5.1), gstreamer1.0-pipewire (1.4.2-1+rpt3)
# Also upgraded: pipewire stack (1.4.2-1+rpt2 -> 1.4.2-1+rpt3), libcamera (0.6 -> 0.7)
# Created symlink: /etc/systemd/system/multi-user.target.wants/rustdesk.service
```

```bash
# Step 3: Verify version
$ rustdesk --version
1.3.9
```

```bash
# Step 4: Get RustDesk ID
$ rustdesk --get-id
309152807
```

### Versions Installed

| Package / Binary | Version | How verified |
|------------------|---------|--------------|
| RustDesk | 1.3.9 | `rustdesk --version` |

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| RustDesk installed | Version output | 1.3.9 | PASS |
| RustDesk ID available | Numeric ID | 309152807 | PASS |
| RustDesk service running | systemctl active | active (confirmed in T6 services list) | PASS |

### Post-conditions

- .deb name: rustdesk-1.3.9-aarch64.deb (18.6 MB)
- RustDesk ID: 309152807
- Service auto-enabled at install

### Deviations from Plan

- dpkg install initially failed due to missing libxdo3 and gstreamer1.0-pipewire.
  `apt install -f -y` resolved these automatically.
- The `apt install -f` also triggered a PipeWire upgrade (1.4.2-1+rpt2 -> 1.4.2-1+rpt3)
  and a libcamera upgrade (0.6 -> 0.7). This is harmless but notable.

### Notes

- RustDesk uses public relay by default (client-only mode). No additional firewall
  ports needed.
- The rustdesk.service was automatically created and enabled by the .deb postinst script.
- No `User=pi` reference was created (verified in T6).

---

## Task T3: Mixxx Installation

**Date:** 2026-03-08 13:46 (CET)
**Operator:** Claude worker via SSH
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8

### Pre-conditions

- Mixxx not previously installed
- Disk space: 117G total, 7.3G used

### Procedure

```bash
# Step 1: Check repo availability
$ apt-cache search mixxx
mixxx - Digital Disc Jockey Interface
mixxx-data - Digital Disc Jockey Interface -- data files

$ apt-cache policy mixxx
mixxx:
  Installed: (none)
  Candidate: 2.5.0+dfsg-3+b1
  Version table:
     2.5.0+dfsg-3+b1 500
        500 http://deb.debian.org/debian trixie/main arm64 Packages
```

```bash
# Step 2: Install Mixxx
$ sudo DEBIAN_FRONTEND=noninteractive apt install -y mixxx
# Download: 20.9 MB
# Space: 77.3 MB
# Installed 16 packages:
#   mixxx (2.5.0+dfsg-3+b1), mixxx-data (2.5.0+dfsg-3)
#   libdjinterop0, libqt6core5compat6, libqt6keychain1, libqt6network6,
#   libqt6qml6, libqt6qmlmodels6, libqt6qmlworkerscript6, libqt6qmlmeta6,
#   libqt6quick6, libqt6sql6, libqt6sql6-sqlite, libqt6svgwidgets6,
#   libqt6xml6, libshout-idjc3
```

```bash
# Step 3: Verify version (needs offscreen Qt platform for headless SSH)
$ QT_QPA_PLATFORM=offscreen mixxx --version
ConfigObject: Could not read "/home/ela/.mixxx/mixxx.cfg"

Mixxx 2.5.0
```

```bash
# Step 4: Check gpu_mem
$ grep gpu_mem /boot/firmware/config.txt
# (no output -- gpu_mem is NOT set in config.txt)
```

```bash
# Step 5: Check disk space impact
$ df -h /
/dev/mmcblk0p2  117G  7.4G  105G   7% /
# Delta: +100 MB (7.3G -> 7.4G)
```

### Versions Installed

| Package / Binary | Version | How verified |
|------------------|---------|--------------|
| Mixxx | 2.5.0+dfsg-3+b1 | `QT_QPA_PLATFORM=offscreen mixxx --version` |

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Mixxx installed | Version output | Mixxx 2.5.0 | PASS |
| Source repo | Debian Trixie main | deb.debian.org/debian trixie/main arm64 | PASS |
| gpu_mem | Check current value | Not set in config.txt (default) | NOTE |

### Post-conditions

- Disk delta: ~+100 MB
- Disk space: 7.4G used of 117G

### Deviations from Plan

None.

### Notes

- gpu_mem is not set in /boot/firmware/config.txt. The default for Pi 4 without this
  setting is 76MB. May need gpu_mem=128 for Mixxx OpenGL -- deferred to integration test.
- Mixxx requires a display to run (fails with SIGABRT without QT_QPA_PLATFORM=offscreen).
  For actual use, it needs the desktop session (labwc/Wayland or X11).
- Mixxx 2.5.0 is the current Debian Trixie version (relatively recent).

---

## Task T5: Reaper Installation

**Date:** 2026-03-08 13:48 (CET)
**Operator:** Claude worker via SSH
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8

### Pre-conditions

- Reaper not previously installed
- Disk space: 117G total, 7.4G used

### Procedure

```bash
# Step 1: Download Reaper
$ cd /tmp && wget -q 'https://www.reaper.fm/files/7.x/reaper731_linux_aarch64.tar.xz' -O reaper_linux_aarch64.tar.xz
$ ls -la reaper_linux_aarch64.tar.xz
-rw-rw-r-- 1 ela ela 11416324 Jan 31  2025 reaper_linux_aarch64.tar.xz
```

```bash
# Step 2: Extract
$ cd /tmp && tar xf reaper_linux_aarch64.tar.xz
$ ls /tmp/reaper_linux_aarch64/
install-reaper.sh  readme-linux.txt  REAPER
```

```bash
# Step 3: Install with flags
$ cd /tmp/reaper_linux_aarch64 && ./install-reaper.sh --install /home/ela/opt/REAPER --integrate-desktop
REAPER installation script
-------------------------------------------------------------------------------
REAPER installer -- install to /home/ela/opt/REAPER

Cleaning up destination... done
Copying files... done
Writing uninstall script to /home/ela/opt/REAPER/REAPER/uninstall-reaper.sh
Installing desktop integration... done

 *** Installation complete
```

```bash
# Step 4: Verify binary
$ ls -la /home/ela/opt/REAPER/REAPER/reaper
-rwxr-xr-x 1 ela ela 10830928 Mar  8 13:48 /home/ela/opt/REAPER/REAPER/reaper
$ file /home/ela/opt/REAPER/REAPER/reaper
/home/ela/opt/REAPER/REAPER/reaper: ELF 64-bit LSB executable, ARM aarch64, version 1 (GNU/Linux),
  dynamically linked, interpreter /lib/ld-linux-aarch64.so.1, for GNU/Linux 3.7.0,
  BuildID[sha1]=d9ad35d6e31ec9bea631aa8469ad8852e3053326, stripped
```

### Versions Installed

| Package / Binary | Version | How verified |
|------------------|---------|--------------|
| Reaper | 7.31 | Tarball name: reaper731_linux_aarch64.tar.xz |

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Binary exists at /home/ela/opt/REAPER/REAPER/reaper | Exists and executable | -rwxr-xr-x, 10.3 MB | PASS |
| Binary is aarch64 | ELF 64-bit ARM | Confirmed via `file` | PASS |
| Install was non-interactive | No prompts needed | --install and --integrate-desktop flags worked | PASS |

### Post-conditions

- Installed to /home/ela/opt/REAPER/REAPER/
- Desktop integration installed (menu entries)
- Uninstaller at /home/ela/opt/REAPER/REAPER/uninstall-reaper.sh

### Deviations from Plan

None. The installer accepted the `--install` and `--integrate-desktop` flags and
ran non-interactively.

### Notes

- Download URL: https://www.reaper.fm/files/7.x/reaper731_linux_aarch64.tar.xz
- Reaper runs with --help output via SSH, but GUI requires a display session.
- Reaper supports extensive batch processing and scripting (Lua) -- useful for automation.

---

## Task T4: PipeWire JACK Bridge Verification

**Date:** 2026-03-08 13:49 (CET)
**Operator:** Claude worker via SSH
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8

### Pre-conditions

- PipeWire already running (pipewire, pipewire-pulse, wireplumber)
- pipewire-jack NOT yet installed

### Procedure

```bash
# Step 1: pw-jack not found initially
$ pw-jack jack_lsp
bash: line 1: pw-jack: command not found
```

```bash
# Step 2: Install pipewire-jack
$ sudo DEBIAN_FRONTEND=noninteractive apt install -y pipewire-jack
# Installed: pipewire-jack (1.4.2-1+rpt3)
# Also upgraded: pipewire-libcamera (1.4.2-1+rpt3)
```

```bash
# Step 3: jack_lsp still needed JACK tools
$ pw-jack jack_lsp
/usr/bin/pw-jack: 60: exec: jack_lsp: not found
```

```bash
# Step 4: Install jackd2 (includes JACK client tools)
$ sudo DEBIAN_FRONTEND=noninteractive apt install -y jackd2
# Installed: jackd2 (1.9.22~dfsg-4), jackd (5+nmu1), jack-example-tools (4-4),
#   libzita-alsa-pcmi0t64, libzita-resampler1, qjackctl (1.0.4-1)
# qjackctl installed as dependency -- bonus!
```

```bash
# Step 5: JACK port listing (via PipeWire bridge)
$ pw-jack jack_lsp
Umik-1  Gain  18dB Analog Stereo:capture_FL
Umik-1  Gain  18dB Analog Stereo:capture_FR
USBStreamer  Analog Surround 4.0:capture_FL
USBStreamer  Analog Surround 4.0:capture_FR
USBStreamer  Analog Surround 4.0:capture_RL
USBStreamer  Analog Surround 4.0:capture_RR
Loopback Analog Stereo:capture_FL
Loopback Analog Stereo:capture_FR
USBStreamer  Analog Surround 7.1:playback_FL
USBStreamer  Analog Surround 7.1:playback_FR
USBStreamer  Analog Surround 7.1:playback_RL
USBStreamer  Analog Surround 7.1:playback_RR
USBStreamer  Analog Surround 7.1:playback_FC
USBStreamer  Analog Surround 7.1:playback_LFE
USBStreamer  Analog Surround 7.1:playback_SL
USBStreamer  Analog Surround 7.1:playback_SR
USBStreamer  Analog Surround 7.1:monitor_FL
USBStreamer  Analog Surround 7.1:monitor_FR
USBStreamer  Analog Surround 7.1:monitor_RL
USBStreamer  Analog Surround 7.1:monitor_RR
USBStreamer  Analog Surround 7.1:monitor_FC
USBStreamer  Analog Surround 7.1:monitor_LFE
USBStreamer  Analog Surround 7.1:monitor_SL
USBStreamer  Analog Surround 7.1:monitor_SR
Loopback Analog Stereo:playback_FL
Loopback Analog Stereo:playback_FR
Loopback Analog Stereo:monitor_FL
Loopback Analog Stereo:monitor_FR
Built-in Audio Stereo:playback_FL
Built-in Audio Stereo:playback_FR
Built-in Audio Stereo:monitor_FL
Built-in Audio Stereo:monitor_FR
Midi-Bridge:Midi Through Port-0 (capture)
Midi-Bridge:DJControl Mix Ultra MIDI 1 (capture)
Midi-Bridge:SE25 MIDI1 (capture)
Midi-Bridge:SE25 MIDI2 (capture)
Midi-Bridge:APC mini mk2 Control (capture)
Midi-Bridge:APC mini mk2 Notes (capture)
BLE MIDI 1:out
Midi-Bridge:Midi Through Port-0 (playback)
Midi-Bridge:DJControl Mix Ultra MIDI 1 (playback)
Midi-Bridge:SE25 MIDI1 (playback)
Midi-Bridge:APC mini mk2 Control (playback)
Midi-Bridge:APC mini mk2 Notes (playback)
BLE MIDI 1:in
```

```bash
# Step 6: PipeWire settings metadata
$ pw-metadata -n settings
Found "settings" metadata 32
update: id:0 key:'log.level' value:'2' type:''
update: id:0 key:'clock.rate' value:'48000' type:''
update: id:0 key:'clock.allowed-rates' value:'[ 48000 ]' type:''
update: id:0 key:'clock.quantum' value:'1024' type:''
update: id:0 key:'clock.min-quantum' value:'32' type:''
update: id:0 key:'clock.max-quantum' value:'2048' type:''
update: id:0 key:'clock.force-quantum' value:'0' type:''
update: id:0 key:'clock.force-rate' value:'0' type:''
```

```bash
# Step 7: Check ALSA loopback in PipeWire
$ pw-cli list-objects | grep -i loopback
# Loopback device and nodes visible:
#   device.description = "Loopback"
#   node.description = "Loopback Analog Stereo" (playback and capture)
#   Ports: playback_FL, playback_FR, capture_FL, capture_FR, monitor_FL, monitor_FR
```

```bash
# Step 8: Check USBStreamer in PipeWire
$ pw-cli list-objects | grep -i usb
# USBStreamer fully visible:
#   device: alsa_card.usb-miniDSP_USBStreamer_00001-00
#   Capture node: USBStreamer Analog Surround 4.0 (FL, FR, RL, RR)
#   Playback node: USBStreamer Analog Surround 7.1 (FL, FR, RL, RR, FC, LFE, SL, SR)
# UMIK-1 also visible:
#   device: alsa_card.usb-miniDSP_Umik-1_Gain__18dB_000-0000-00
```

```bash
# Step 9: PipeWire version
$ pipewire --version
pipewire
Compiled with libpipewire 1.4.2
Linked with libpipewire 1.4.2
```

### Versions Installed

| Package / Binary | Version | How verified |
|------------------|---------|--------------|
| PipeWire | 1.4.2 | `pipewire --version` |
| pipewire-jack | 1.4.2-1+rpt3 | `dpkg -l pipewire-jack` |
| jackd2 | 1.9.22~dfsg-4 | `dpkg -l jackd2` |
| qjackctl | 1.0.4-1 | `dpkg -l qjackctl` |

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| pw-jack jack_lsp lists JACK ports | Ports visible | 44 ports listed (audio + MIDI) | PASS |
| clock.rate | 48000 | 48000 | PASS |
| clock.quantum | Recorded | 1024 | PASS |
| clock.force-quantum | Recorded (not changed) | 0 (not forced) | PASS |
| Loopback in PipeWire | Visible | Loopback Analog Stereo (playback + capture) | PASS |
| USBStreamer in PipeWire | Visible | 7.1 playback + 4.0 capture nodes | PASS |
| PipeWire version | Recorded | 1.4.2 (compiled + linked) | PASS |
| qjackctl installed | Installed | 1.0.4-1 (installed as jackd2 dependency) | PASS |

### Post-conditions

- JACK bridge fully operational
- All USB audio devices visible via JACK

### Deviations from Plan

- pw-jack was not present initially (pipewire-jack not installed). Installed it.
- jack_lsp was not available even after pipewire-jack (it provides the LD_PRELOAD
  wrapper but not the JACK client tools). Had to install jackd2 separately.
- qjackctl was pulled in as a dependency of jackd2, so the optional step was fulfilled
  automatically.

### Notes

- PipeWire settings: clock.rate=48000, clock.quantum=1024, clock.force-quantum=0
- All MIDI devices visible via JACK bridge: DJControl Mix Ultra, SE25, APC mini mk2,
  BLE MIDI 1, Midi Through
- USBStreamer appears as 7.1 surround output (8 channels) and 4.0 surround capture
  (4 channels) -- matches the hardware spec (8 out, 8 in via ADAT)
- Note: PipeWire sees the USBStreamer capture as only 4 channels. The full 8-channel
  capture may require ALSA profile configuration.

---

## Task T6: Integration Smoke Test

**Date:** 2026-03-08 13:50 (CET)
**Operator:** Claude worker via SSH
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8

### Pre-conditions

- All software installed from T0-T5 and T7

### Procedure

```bash
# Step 1: Verify all binaries
$ camilladsp --version
CamillaDSP 3.0.1

$ QT_QPA_PLATFORM=offscreen mixxx --version
Mixxx 2.5.0

$ source /home/ela/audio-workstation-venv/bin/activate
$ python3 -c "import numpy, scipy, soundfile, camilladsp, sounddevice; print('OK')"
OK

$ ls -la /home/ela/opt/REAPER/REAPER/reaper
-rwxr-xr-x 1 ela ela 10830928 Mar  8 13:48 /home/ela/opt/REAPER/REAPER/reaper

$ rustdesk --version
1.3.9
```

```bash
# Step 2: Disk space
$ df -h /
Filesystem      Size  Used Avail Use% Mounted on
/dev/mmcblk0p2  117G  7.5G  105G   7% /
```

```bash
# Step 3: RAM
$ free -h
               total        used        free      shared  buff/cache   available
Mem:           3.7Gi       598Mi       1.5Gi       192Mi       1.9Gi       3.1Gi
Swap:          2.0Gi          0B       2.0Gi
```

```bash
# Step 4: Check listening ports
$ ss -tlnp
State  Recv-Q Send-Q Local Address:Port Peer Address:PortProcess
LISTEN 0      128          0.0.0.0:22        0.0.0.0:*
LISTEN 0      128             [::]:22           [::]:*
# Only SSH listening -- clean. No unexpected ports.
# Note: CUPS (631) and rpcbind (111) from pre-conditions are gone.
```

```bash
# Step 5: USB devices
$ lsusb
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 001 Device 002: ID 2109:3431 VIA Labs, Inc. Hub
Bus 001 Device 005: ID 05e3:0610 Genesys Logic, Inc. Hub
Bus 001 Device 006: ID 2752:0007 miniDSP Umik-1  Gain: 18dB
Bus 001 Device 007: ID 05e3:0610 Genesys Logic, Inc. Hub
Bus 001 Device 008: ID 06f8:b131 Guillemot Corp. DJControl Mix Ultra
Bus 001 Device 009: ID 2467:2006 Nektar SE25
Bus 001 Device 010: ID 09e8:004f AKAI  Professional M.I. Corp. APC mini mk2
Bus 001 Device 011: ID 2752:0016 miniDSP  USBStreamer
Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 002 Device 002: ID 05e3:0626 Genesys Logic, Inc. Hub
Bus 002 Device 003: ID 05e3:0626 Genesys Logic, Inc. Hub

$ aplay -l
**** List of PLAYBACK Hardware Devices ****
card 0: vc4hdmi0, card 1: vc4hdmi1, card 2: Headphones, card 3: USBStreamer
card 10: Loopback (device 0 + device 1, 2 substreams each)

$ arecord -l
**** List of CAPTURE Hardware Devices ****
card 3: USBStreamer, card 4: U18dB (Umik-1), card 10: Loopback (device 0 + device 1)
```

```bash
# Step 6: CRITICAL CHECK -- no User=pi in systemd
$ grep -r "User=pi" /etc/systemd/system/
# (no output -- PASS)
```

```bash
# Step 7: Bluetooth check
$ systemctl is-active bluetooth.service
active
```

```bash
# Step 8: Full system snapshot
$ uname -a
Linux mugge 6.12.47+rpt-rpi-v8 #1 SMP PREEMPT Debian 1:6.12.47-1+rpt1 (2025-09-16) aarch64 GNU/Linux

# Running services (22 total):
# accounts-daemon, avahi-daemon, bluetooth, colord, cron, dbus, getty@tty1,
# lightdm, NetworkManager, nfs-blkmap, packagekit, polkit, rustdesk,
# serial-getty@ttyS0, ssh, systemd-journald, systemd-logind, systemd-timesyncd,
# systemd-udevd, udisks2, user@1000, wpa_supplicant
```

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| camilladsp --version | 3.0.1 | CamillaDSP 3.0.1 | PASS |
| mixxx --version | 2.5.0 | Mixxx 2.5.0 | PASS |
| Python imports | OK | OK | PASS |
| Reaper binary exists | Executable at /home/ela/opt/REAPER/REAPER/reaper | Present, 10.3 MB, executable | PASS |
| rustdesk --version | 1.3.9 | 1.3.9 | PASS |
| Disk space | Reasonable usage | 7.5G / 117G (7%) | PASS |
| RAM | Adequate free | 3.1Gi available of 3.7Gi | PASS |
| No unexpected ports | Only SSH | Only port 22 (SSH) | PASS |
| All USB devices present | 5 audio/MIDI devices | All present (USBStreamer, UMIK-1, DJControl, SE25, APCmini) | PASS |
| No User=pi in systemd | Empty grep output | Empty (no matches) | PASS |
| Bluetooth active | active | active | PASS |
| Loopback card present | Card 10 | Card 10 Loopback | PASS |

### Post-conditions

- Total disk usage: 7.5G of 117G (7%)
- Disk delta from start of session: +0.8G (6.7G -> 7.5G)
- RAM: 598Mi used, 3.1Gi available, 2.0Gi swap unused

### Deviations from Plan

- No reboot was performed. The snd-aloop module was loaded at runtime and the
  persistence config files are in place. Persistence should be verified on next reboot.

### Notes

- The listening ports are cleaner than the pre-conditions indicated. The CLAUDE.md
  mentioned CUPS on 631/localhost and rpcbind on 111, but only SSH (22) is listening
  now. This may be due to services having been stopped or not running in the current
  session. Worth monitoring.
- PipeWire was upgraded from 1.4.2-1+rpt2 to 1.4.2-1+rpt3 during the RustDesk
  installation (gstreamer1.0-pipewire dependency pull). All PipeWire services appear
  to be functioning normally after the upgrade.
- All 5 USB audio/MIDI devices are recognized and visible in both ALSA and PipeWire/JACK.
- The Hercules DJControl Mix Ultra is presenting as USB-MIDI (Midi-Bridge:DJControl Mix Ultra MIDI 1)
  -- this partially answers the open question about USB-MIDI support on Linux.

---

## Summary

### All Versions Installed

| Software | Version | Location |
|----------|---------|----------|
| CamillaDSP | 3.0.1 | /usr/local/bin/camilladsp |
| Mixxx | 2.5.0+dfsg-3+b1 | /usr/bin/mixxx (apt) |
| Reaper | 7.31 | /home/ela/opt/REAPER/REAPER/reaper |
| RustDesk | 1.3.9 | /usr/bin/rustdesk (deb) |
| PipeWire | 1.4.2-1+rpt3 | system |
| pipewire-jack | 1.4.2-1+rpt3 | system |
| jackd2 | 1.9.22~dfsg-4 | system |
| qjackctl | 1.0.4-1 | system |
| Python | 3.13.5 | /usr/bin/python3 |
| numpy | 2.4.2 | venv |
| scipy | 1.17.1 | venv |
| soundfile | 0.13.1 | venv |
| pycamilladsp | 3.0.0 (git bf378f5) | venv |
| sounddevice | 0.5.5 | venv |
| matplotlib | 3.10.8 | venv |
| snd-aloop | kernel 6.12.47 | kernel module |

### System State

| Metric | Value |
|--------|-------|
| OS | Debian 13 Trixie |
| Kernel | 6.12.47+rpt-rpi-v8 SMP PREEMPT aarch64 |
| Hostname | mugge |
| Disk used | 7.5G / 117G (7%) |
| RAM available | 3.1Gi / 3.7Gi |
| Swap | 2.0Gi (unused) |
| Listening ports | SSH (22) only |
| Bluetooth | active |
| RustDesk ID | 309152807 |
| PipeWire clock.rate | 48000 |
| PipeWire clock.quantum | 1024 |
| PipeWire clock.force-quantum | 0 (not forced) |
| gpu_mem | Not set (default ~76MB) |

### Overall Pass/Fail

| Task | Status |
|------|--------|
| T0: ALSA Loopback Module | PASS |
| T1: CamillaDSP v3.0.1 | PASS |
| T2: Python DSP Libraries | PASS |
| T7: RustDesk | PASS |
| T3: Mixxx | PASS |
| T5: Reaper | PASS |
| T4: PipeWire JACK Bridge | PASS |
| T6: Integration Smoke Test | PASS |
| CRITICAL: No User=pi in systemd | PASS |
| CRITICAL: Bluetooth still active | PASS |

### Items Needing Follow-up

1. **Reboot test needed**: Verify snd-aloop persists across reboot with index=10.
   The `channels=4` modprobe option is not a valid snd-aloop parameter and may
   cause a warning or be silently ignored.
2. **gpu_mem for Mixxx**: Currently unset (default ~76MB). May need gpu_mem=128 for
   OpenGL rendering. Deferred to integration test per task instructions.
3. **USBStreamer 4-channel capture**: PipeWire sees only 4 capture channels (surround 4.0).
   The USBStreamer has 8 inputs via ADAT. May need ALSA profile configuration to expose
   all 8 channels.
4. **pycamilladsp from GitHub**: Installed from git (not PyPI) because the PyPI package
   doesn't support Python 3.13. Monitor for a PyPI release compatible with 3.13.
5. **CUPS/rpcbind ports**: The pre-conditions listed CUPS (631) and rpcbind (111) as
   listening, but they are not listening now. Monitor whether they return after reboot.
