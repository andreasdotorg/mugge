"""Real data collectors for the Pi Audio Workstation monitoring UI.

Four singleton collectors poll actual system sources on the Pi:
    - CamillaDSPCollector: DSP levels and status via pycamilladsp
    - PcmStreamCollector: JACK ring buffer for binary PCM streaming
    - SystemCollector: CPU, memory, temperature from /proc and /sys
    - PipeWireCollector: PipeWire graph state from pw-top

On macOS (development), collectors return fallback/mock data.
"""

from .camilladsp_collector import CamillaDSPCollector
from .pcm_collector import PcmStreamCollector
from .pipewire_collector import PipeWireCollector
from .system_collector import SystemCollector

__all__ = [
    "CamillaDSPCollector",
    "PcmStreamCollector",
    "PipeWireCollector",
    "SystemCollector",
]
