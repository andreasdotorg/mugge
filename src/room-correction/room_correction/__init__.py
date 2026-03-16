"""
Room correction pipeline for Pi4 audio workstation.

Generates combined minimum-phase FIR filters that integrate crossover slopes
and room correction into a single convolution per output channel, deployed
to CamillaDSP.
"""

__version__ = "0.1.0"
