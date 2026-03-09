#!/home/ela/audio-workstation-venv/bin/python3
"""Monitor CamillaDSP state via websocket API during audio testing.

Detects stalls (frozen buffer level), processing load spikes, clipping,
and unexpected state changes. Designed to run alongside jack-tone-generator.py
to validate the CamillaDSP portion of the audio path.

Usage:
    python3 monitor-camilladsp.py --duration 30 --host 127.0.0.1 --port 1234
"""

import argparse
import json
import sys
import time

from camilladsp import CamillaClient


def main():
    parser = argparse.ArgumentParser(description="CamillaDSP websocket monitor")
    parser.add_argument("--duration", type=float, default=30,
                        help="Monitoring duration in seconds (default: 30)")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="CamillaDSP host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=1234,
                        help="CamillaDSP websocket port (default: 1234)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Poll interval in seconds (default: 0.5)")
    parser.add_argument("--output-json", type=str, default=None,
                        help="Write JSON summary to this file")
    args = parser.parse_args()

    client = CamillaClient(args.host, args.port)
    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            client.connect()
            break
        except Exception as e:
            if attempt == max_retries:
                print(f"ERROR: Cannot connect to CamillaDSP at {args.host}:{args.port} "
                      f"after {max_retries} attempts: {e}", file=sys.stderr)
                sys.exit(1)
            print(f"Connection attempt {attempt}/{max_retries} failed, retrying in 1s...",
                  file=sys.stderr)
            time.sleep(1)

    print(f"Connected to CamillaDSP at {args.host}:{args.port}")
    print(f"Monitoring for {args.duration}s, interval {args.interval}s")
    print()

    # Collect samples
    samples = []
    anomalies = []
    buffer_history = []
    initial_clipped = None
    peak_load = 0.0
    start = time.monotonic()

    try:
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= args.duration:
                break

            ts = time.strftime("%H:%M:%S")
            try:
                state = str(client.general.state())
                load = client.status.processing_load()
                buf = client.status.buffer_level()
                rate_adj = client.status.rate_adjust()
                clipped = client.status.clipped_samples()
            except Exception as e:
                ts_now = time.strftime("%H:%M:%S")
                msg = f"[{ts_now}] ERROR: Query failed: {e}"
                print(msg)
                anomalies.append(msg)
                time.sleep(args.interval)
                continue

            if initial_clipped is None:
                initial_clipped = clipped
            if load > peak_load:
                peak_load = load

            sample = {
                "time": ts,
                "elapsed": round(elapsed, 1),
                "state": state,
                "load": load,
                "buffer": buf,
                "rate_adjust": rate_adj,
                "clipped": clipped,
            }
            samples.append(sample)
            buffer_history.append(buf)

            print(f"[{ts}] state={state} load={load:.1f}% buf={buf} "
                  f"rate_adj={rate_adj:.6f} clipped={clipped}")

            # Anomaly detection: state not RUNNING
            if "RUNNING" not in state.upper():
                msg = f"[{ts}] ANOMALY: State is {state} (expected RUNNING)"
                print(f"  *** {msg}")
                anomalies.append(msg)

            # Anomaly detection: buffer drain (level drops to 0 = capture starved)
            if buf == 0:
                msg = f"[{ts}] ANOMALY: Buffer level is 0 — capture starved"
                print(f"  *** {msg}")
                anomalies.append(msg)

            # Anomaly detection: buffer crash (drops >50% from peak)
            if buffer_history:
                peak_buf = max(buffer_history)
                if peak_buf > 0 and buf < peak_buf * 0.5:
                    msg = f"[{ts}] ANOMALY: Buffer level {buf} dropped >50% from peak {peak_buf}"
                    print(f"  *** {msg}")
                    anomalies.append(msg)

            # Anomaly detection: processing load > 85%
            if load > 85.0:
                msg = f"[{ts}] ANOMALY: Processing load {load:.1f}% > 85%"
                print(f"  *** {msg}")
                anomalies.append(msg)

            # Anomaly detection: clipping
            if clipped > initial_clipped:
                msg = f"[{ts}] ANOMALY: Clipped samples increased to {clipped}"
                print(f"  *** {msg}")
                anomalies.append(msg)

            remaining = args.duration - (time.monotonic() - start)
            if remaining > 0:
                time.sleep(min(args.interval, remaining))

    except KeyboardInterrupt:
        pass

    elapsed = time.monotonic() - start

    try:
        client.disconnect()
    except Exception:
        pass

    # Compute statistics
    if samples:
        loads = [s["load"] for s in samples]
        bufs = [s["buffer"] for s in samples]
        total_clipped = samples[-1]["clipped"] - (initial_clipped or 0)
        stats = {
            "duration": round(elapsed, 1),
            "samples": len(samples),
            "buffer_min": min(bufs),
            "buffer_max": max(bufs),
            "buffer_mean": round(sum(bufs) / len(bufs), 1),
            "load_min": round(min(loads), 1),
            "load_max": round(max(loads), 1),
            "load_mean": round(sum(loads) / len(loads), 1),
            "peak_load": round(peak_load, 1),
            "total_clipped": total_clipped,
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "verdict": "PASS" if len(anomalies) == 0 else "FAIL",
        }
    else:
        stats = {
            "duration": round(elapsed, 1),
            "samples": 0,
            "peak_load": 0.0,
            "total_clipped": 0,
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "verdict": "FAIL",
        }

    # Print summary
    print()
    print("=== CamillaDSP Monitor Summary ===")
    print(f"Duration: {stats['duration']}s ({stats.get('samples', 0)} samples)")
    if stats.get("samples", 0) > 0:
        print(f"Buffer level: min={stats['buffer_min']} max={stats['buffer_max']} "
              f"mean={stats['buffer_mean']}")
        print(f"Processing load: min={stats['load_min']}% max={stats['load_max']}% "
              f"mean={stats['load_mean']}%")
        print(f"Peak load: {stats['peak_load']}%")
        print(f"Clipped samples: {stats['total_clipped']}")
    print(f"Anomalies: {stats['anomaly_count']}")
    if anomalies:
        for a in anomalies:
            print(f"  {a}")
    print(f"Result: {stats['verdict']}")

    # Write JSON if requested
    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(stats, f, indent=2)
        print(f"JSON summary written to: {args.output_json}")

    sys.exit(0 if stats["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
