#!/home/ela/audio-workstation-venv/bin/python3
"""JACK callback-based 1000Hz sine tone generator for audio path testing.

Generates a continuous sine tone through PipeWire's JACK bridge, testing the
same code path as Reaper: JACK process callbacks -> loopback-8ch-sink ->
CamillaDSP -> USBStreamer.

Registers 8 output ports matching the loopback-8ch-sink channel layout.
Outputs tone on ports 1+2 (L/R mains), silence on ports 3-8.

Usage:
    python3 jack-tone-generator.py --duration 30 --frequency 1000
"""

import argparse
import sys
import threading
import time
import numpy as np

import jack


def main():
    parser = argparse.ArgumentParser(description="JACK sine tone generator")
    parser.add_argument("--duration", type=float, default=30,
                        help="Duration in seconds (default: 30)")
    parser.add_argument("--frequency", type=float, default=1000,
                        help="Tone frequency in Hz (default: 1000)")
    parser.add_argument("--amplitude", type=float, default=0.063,
                        help="Amplitude, 0.063 = -24dBFS (default: 0.063)")
    parser.add_argument("--connect-to", type=str, default="CamillaDSP 8ch Input",
                        help="JACK sink to auto-connect to (default: CamillaDSP 8ch Input)")
    args = parser.parse_args()

    # Shared state — phase is only accessed from the RT callback (single-threaded)
    phase = [np.float64(0.0)]
    xruns = []
    callback_gaps = []
    last_callback_time = [0.0]
    shutdown_reason = [None]
    finished = threading.Event()

    client = jack.Client("tone-generator")

    # Register 8 output ports
    outports = []
    for i in range(8):
        outports.append(client.outports.register(f"out_{i+1}"))

    @client.set_process_callback
    def process(frames):
        now = time.monotonic()
        sr = client.samplerate

        # Detect graph suspension gaps (callback interval > 2x expected)
        if last_callback_time[0] > 0:
            expected_interval = frames / sr
            actual_interval = now - last_callback_time[0]
            if actual_interval > 2.0 * expected_interval:
                ts = time.strftime("%H:%M:%S")
                callback_gaps.append((ts, actual_interval))
                print(f"[{ts}] CALLBACK GAP: {actual_interval*1000:.1f}ms "
                      f"(expected {expected_interval*1000:.1f}ms)", file=sys.stderr)
        last_callback_time[0] = now

        phase_inc = 2.0 * np.pi * args.frequency / sr
        t = np.arange(frames, dtype=np.float64) * phase_inc + phase[0]
        phase[0] = (phase[0] + frames * phase_inc) % (2.0 * np.pi)

        tone = (args.amplitude * np.sin(t)).astype(np.float32)
        silence = np.zeros(frames, dtype=np.float32)

        # Channels 1+2: tone (L/R mains), channels 3-8: silence
        outports[0].get_array()[:] = tone
        outports[1].get_array()[:] = tone
        for port in outports[2:]:
            port.get_array()[:] = silence

    @client.set_xrun_callback
    def xrun(delay):
        ts = time.strftime("%H:%M:%S")
        xruns.append(ts)
        print(f"[{ts}] XRUN (delay: {delay:.1f}us)", file=sys.stderr)

    @client.set_shutdown_callback
    def shutdown(status, reason):
        shutdown_reason[0] = reason
        print(f"JACK shutdown: {reason}", file=sys.stderr)
        finished.set()

    # Activate and connect
    client.activate()

    print(f"JACK tone generator active: {args.frequency}Hz @ {args.amplitude} "
          f"({20*np.log10(args.amplitude):.1f}dBFS)")
    print(f"Sample rate: {client.samplerate}, Buffer size: {client.blocksize}")
    print(f"Duration: {args.duration}s")

    # Discover and connect to sink ports
    target_ports = client.get_ports(args.connect_to, is_input=True)
    if not target_ports:
        print(f"WARNING: No ports matching '{args.connect_to}' found. "
              f"Running unconnected.", file=sys.stderr)
    else:
        for i, outport in enumerate(outports):
            if i < len(target_ports):
                client.connect(outport, target_ports[i])
                print(f"  {outport.name} -> {target_ports[i].name}")
            else:
                print(f"  {outport.name} -> (no target port)")

    start = time.monotonic()

    try:
        while not finished.is_set():
            elapsed = time.monotonic() - start
            if elapsed >= args.duration:
                break
            remaining = args.duration - elapsed
            finished.wait(timeout=min(1.0, remaining))
    except KeyboardInterrupt:
        pass

    elapsed = time.monotonic() - start
    client.deactivate()
    client.close()

    # Summary
    print()
    print("=== Tone Generator Summary ===")
    print(f"Duration: {elapsed:.1f}s")
    print(f"Xruns: {len(xruns)}")
    if xruns:
        print(f"Xrun timestamps: {', '.join(xruns)}")
    print(f"Callback gaps: {len(callback_gaps)}")
    if callback_gaps:
        for ts, dur in callback_gaps:
            print(f"  [{ts}] {dur*1000:.1f}ms")
    if shutdown_reason[0]:
        print(f"Shutdown reason: {shutdown_reason[0]}")
    print(f"Result: {'PASS' if len(xruns) == 0 and len(callback_gaps) == 0 else 'FAIL'}")


if __name__ == "__main__":
    main()
