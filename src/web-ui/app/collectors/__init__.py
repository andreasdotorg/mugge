"""Real data collectors for the Pi Audio Workstation monitoring UI.

Four singleton collectors poll actual system sources on the Pi:
    - FilterChainCollector: filter-chain health via GraphManager RPC (D-040)
    - PcmStreamCollector: JACK ring buffer for binary PCM streaming
    - SystemCollector: CPU, memory, temperature, scheduling from /proc and /sys
    - PipeWireCollector: quantum/rate via pw-metadata, xruns via pw-cli (TK-245)

On macOS (development), collectors return fallback/mock data.
"""

from .filterchain_collector import FilterChainCollector
from .pcm_collector import PcmStreamCollector
from .pipewire_collector import PipeWireCollector
from .system_collector import SystemCollector

__all__ = [
    "FilterChainCollector",
    "PcmStreamCollector",
    "PipeWireCollector",
    "SystemCollector",
]
