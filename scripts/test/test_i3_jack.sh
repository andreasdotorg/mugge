#!/bin/bash
# Test I3: jack_iodelay measurement through PipeWire JACK bridge
# CamillaDSP must already be running

echo "=== Test I3: jack_iodelay production path ==="
echo "CamillaDSP PID: $(pgrep -f camilladsp)"

# Start jack_iodelay in background
timeout 20 pw-jack jack_iodelay > /tmp/jack_iodelay_output.txt 2>&1 &
IODELAY_PID=$!
sleep 2

# Connect ports
echo "Connecting jack_iodelay:out -> Loopback playback FL..."
pw-jack jack_connect jack_iodelay:out "Loopback Analog Stereo:playback_FL" 2>&1
echo "  exit code: $?"

echo "Connecting USBStreamer capture AUX0 -> jack_iodelay:in..."
pw-jack jack_connect "USBStreamer 8ch Input:capture_AUX0" jack_iodelay:in 2>&1
echo "  exit code: $?"

# List connections to verify
echo
echo "Connections for jack_iodelay:"
pw-jack jack_lsp -c 2>&1 | grep -A5 jack_iodelay

# Wait for jack_iodelay to collect data
echo
echo "Waiting 15 seconds for jack_iodelay to measure..."
sleep 15

# Kill jack_iodelay
kill $IODELAY_PID 2>/dev/null
wait $IODELAY_PID 2>/dev/null

echo
echo "=== jack_iodelay output ==="
cat /tmp/jack_iodelay_output.txt
echo
echo "Done."
