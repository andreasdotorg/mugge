"""Export synthetic room impulse responses as WAV files.

Generates one float32 WAV per CamillaDSP channel (8 total) using the
image-source room simulator.  The WAVs are consumed by a PipeWire
filter-chain convolver in the E2E test harness.

Channels 0-3 map to configured speakers (main_left, main_right, sub1,
sub2).  Channels 4-7 use a default fallback position, matching the
convention in MockSoundDevice.
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

# Allow running as a script from the mock/ directory or from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mock.room_simulator import generate_room_ir, load_room_config
from room_correction import dsp_utils

SAMPLE_RATE = dsp_utils.SAMPLE_RATE
N_CHANNELS = 8
SPEAKER_ORDER = ["main_left", "main_right", "sub1", "sub2"]
DEFAULT_SPEAKER_POS = [4.0, 5.0, 1.5]

_DEFAULT_ROOM_CONFIG_PATH = Path(__file__).parent / "room_config.yml"
_DEFAULT_OUTPUT_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "pi4audio-e2e"


def export_room_irs(
    output_dir: Path,
    room_config_path: Path = _DEFAULT_ROOM_CONFIG_PATH,
) -> list[Path]:
    """Generate and write room IR WAV files for all 8 channels.

    Returns a list of Paths to the written WAV files, ordered by channel.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    room_config = load_room_config(str(room_config_path))
    room = room_config.get("room", {})
    speakers = room_config.get("speakers", {})
    mic_pos = room_config.get("microphone", {}).get("position", [4.0, 3.0, 1.2])

    paths = []
    for ch in range(N_CHANNELS):
        if ch < len(SPEAKER_ORDER) and SPEAKER_ORDER[ch] in speakers:
            speaker_pos = speakers[SPEAKER_ORDER[ch]]["position"]
        else:
            speaker_pos = DEFAULT_SPEAKER_POS

        ir = generate_room_ir(
            speaker_pos=speaker_pos,
            mic_pos=mic_pos,
            room_dims=room.get("dimensions", [8.0, 6.0, 3.0]),
            wall_absorption=room.get("wall_absorption", 0.3),
            temperature=room.get("temperature", 22.0),
            room_modes=room_config.get("room_modes"),
            sr=SAMPLE_RATE,
        )

        wav_path = output_dir / f"room_ir_ch{ch}.wav"
        sf.write(str(wav_path), ir.astype(np.float32), SAMPLE_RATE, subtype="FLOAT")
        paths.append(wav_path)

    return paths


def main():
    parser = argparse.ArgumentParser(
        description="Export synthetic room IRs as WAV files for E2E testing."
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {_DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "-r", "--room-config", type=Path, default=_DEFAULT_ROOM_CONFIG_PATH,
        help=f"Room config YAML (default: {_DEFAULT_ROOM_CONFIG_PATH})",
    )
    args = parser.parse_args()

    paths = export_room_irs(args.output_dir, args.room_config)
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
