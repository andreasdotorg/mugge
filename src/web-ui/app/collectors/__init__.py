"""Real data collectors for the Pi Audio Workstation monitoring UI.

Five singleton collectors poll actual system sources on the Pi:
    - FilterChainCollector: filter-chain health via GraphManager RPC (D-040)
    - LevelsCollector: peak/RMS metering from pcm-bridge levels server
    - PcmStreamCollector: JACK ring buffer for binary PCM streaming
    - SystemCollector: CPU, memory, temperature, scheduling from /proc and /sys
    - PipeWireCollector: quantum/rate/xruns via GraphManager RPC (Phase 2a)

On macOS (development), collectors return fallback/mock data.
"""

from .filterchain_collector import FilterChainCollector
from .levels_collector import LevelsCollector
from .pcm_collector import PcmStreamCollector
from .pipewire_collector import PipeWireCollector
from .system_collector import SystemCollector

__all__ = [
    "FilterChainCollector",
    "LevelsCollector",
    "PcmStreamCollector",
    "PipeWireCollector",
    "SystemCollector",
]
