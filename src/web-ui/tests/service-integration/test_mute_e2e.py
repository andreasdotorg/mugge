"""E2E tests for US-091: Audio mute with dynamic gain node discovery.

Verifies mute/unmute against the real local-demo stack — no mocks.
The mute API sets all filter-chain gain nodes (linear builtin Mult params)
to 0.0; unmute restores the pre-mute values.

Signal flow in DJ mode:
    signal-gen -> convolver (gain nodes) -> level-bridge-sw (port 9100)

Mute zeroes the gain nodes, so level-bridge-sw should report silence.
Unmute restores them, so levels should return to non-zero.

Prerequisites:
    - ``nix run .#local-demo`` running
    - Tests use ensure_dj_mode fixture to guarantee signal flow

Usage:
    nix run .#test-e2e
"""

import time

import pytest


pytestmark = pytest.mark.service_integration

# Thresholds (dBFS).  level-bridge reports peak in dB.
# -100 dBFS is the established signal/silence boundary (test_audio_flow.py).
# In local-demo with a null sink, the noise floor is ~-120 dBFS (float32
# quantization).  -100 dBFS gives 20 dB margin above the noise floor.
# -60 dBFS is a "signal is healthy" threshold — signal-gen in DJ mode
# typically reads -20 to -40 dBFS through the convolver, so -60 dBFS
# gives 20-40 dB headroom while being clearly distinct from silence.
SILENCE_THRESHOLD_DB = -100.0
SIGNAL_THRESHOLD_DB = -60.0

# Settle time after mute/unmute for PipeWire to propagate gain changes.
GAIN_SETTLE_S = 2


class TestMuteSilencesOutput:
    """Mute via API -> level-bridge reports silence."""

    def test_mute_returns_ok(self, api_post):
        """POST /api/v1/audio/mute returns ok=true."""
        status, body = api_post("/api/v1/audio/mute")
        assert status == 200, f"Mute failed: {status} {body}"
        assert body.get("ok") is True, f"Mute not ok: {body}"

        # Cleanup: unmute so subsequent tests start clean
        api_post("/api/v1/audio/unmute")

    def test_mute_silences_level_bridge(self, ensure_dj_mode, api_post,
                                        read_levels, level_sw_port):
        """After mute, level-bridge-sw reports silence on all channels."""
        # Verify signal is flowing before mute
        pre_lines = read_levels(level_sw_port, count=3)
        assert len(pre_lines) >= 1, (
            f"No data from level-bridge-sw before mute on port {level_sw_port}")

        # Mute
        status, body = api_post("/api/v1/audio/mute")
        assert status == 200 and body.get("ok"), f"Mute failed: {body}"
        time.sleep(GAIN_SETTLE_S)

        # Read levels after mute — all peaks should be silence
        lines = read_levels(level_sw_port, count=3)
        assert len(lines) >= 1, "No data from level-bridge-sw after mute"

        for snapshot in lines:
            peak = snapshot.get("peak", [])
            if not peak:
                continue
            for i, p in enumerate(peak):
                assert p < SILENCE_THRESHOLD_DB, (
                    f"Channel {i} peak {p} dB >= {SILENCE_THRESHOLD_DB} dB "
                    f"after mute — expected silence"
                )

        # Cleanup: unmute
        api_post("/api/v1/audio/unmute")
        time.sleep(GAIN_SETTLE_S)


class TestUnmuteRestoresSignal:
    """Mute -> unmute -> level-bridge reports signal returns."""

    def test_unmute_restores_levels(self, audio_stimulus, api_post,
                                    read_levels, level_sw_port):
        """After unmute, level-bridge-sw reports non-zero peaks."""
        # Mute first
        status, body = api_post("/api/v1/audio/mute")
        assert status == 200 and body.get("ok"), f"Mute failed: {body}"
        time.sleep(GAIN_SETTLE_S)

        # Verify muted
        muted_lines = read_levels(level_sw_port, count=2)
        assert len(muted_lines) >= 1
        for snapshot in muted_lines:
            peak = snapshot.get("peak", [])
            if peak:
                assert all(p < SILENCE_THRESHOLD_DB for p in peak), (
                    f"Not silenced after mute: {peak}"
                )

        # Unmute
        status, body = api_post("/api/v1/audio/unmute")
        assert status == 200 and body.get("ok"), f"Unmute failed: {body}"
        time.sleep(GAIN_SETTLE_S)

        # Read levels — at least one channel should have signal
        lines = read_levels(level_sw_port, count=5)
        assert len(lines) >= 1, "No data from level-bridge-sw after unmute"

        has_signal = False
        for snapshot in lines:
            peak = snapshot.get("peak", [])
            if any(p > SIGNAL_THRESHOLD_DB for p in peak):
                has_signal = True
                break

        assert has_signal, (
            f"No signal detected after unmute — all peaks below "
            f"{SIGNAL_THRESHOLD_DB} dB. Snapshots: {lines}"
        )


class TestMuteIdempotency:
    """Double-mute and double-unmute are safe no-ops."""

    def test_double_mute_is_idempotent(self, ensure_dj_mode, api_post, api_get):
        """Muting twice returns ok with 'already muted' detail."""
        # First mute
        s1, b1 = api_post("/api/v1/audio/mute")
        assert s1 == 200 and b1.get("ok"), f"First mute failed: {b1}"

        # Second mute — should succeed with "already muted"
        s2, b2 = api_post("/api/v1/audio/mute")
        assert s2 == 200, f"Double mute failed: {s2} {b2}"
        assert b2.get("ok") is True
        assert "already" in b2.get("detail", "").lower(), (
            f"Expected 'already muted' detail, got: {b2}"
        )

        # Status should still show muted
        _, status_body = api_get("/api/v1/audio/mute-status")
        assert status_body.get("is_muted") is True

        # Cleanup
        api_post("/api/v1/audio/unmute")
        time.sleep(0.5)


class TestMuteStatusEndpoint:
    """GET /api/v1/audio/mute-status reflects correct state."""

    def test_initial_not_muted(self, api_post, api_get):
        """After unmute, status shows not muted."""
        # Ensure clean state — prior tests may have left system muted
        api_post("/api/v1/audio/unmute")
        time.sleep(0.5)

        status, body = api_get("/api/v1/audio/mute-status")
        assert status == 200
        assert body.get("is_muted") is False, f"Expected not muted: {body}"

    def test_status_after_mute(self, ensure_dj_mode, api_post, api_get):
        """After mute, status shows muted."""
        api_post("/api/v1/audio/mute")
        time.sleep(0.5)

        status, body = api_get("/api/v1/audio/mute-status")
        assert status == 200
        assert body.get("is_muted") is True, f"Expected muted: {body}"

        # Cleanup
        api_post("/api/v1/audio/unmute")
        time.sleep(0.5)

    def test_status_after_unmute(self, ensure_dj_mode, api_post, api_get):
        """After mute then unmute, status shows not muted."""
        api_post("/api/v1/audio/mute")
        time.sleep(0.5)
        api_post("/api/v1/audio/unmute")
        time.sleep(0.5)

        status, body = api_get("/api/v1/audio/mute-status")
        assert status == 200
        assert body.get("is_muted") is False, f"Expected not muted: {body}"
