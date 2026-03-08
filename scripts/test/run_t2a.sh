#!/bin/bash
/home/ela/audio-workstation-venv/bin/python3 /tmp/measure_latency_v2.py /etc/camilladsp/configs/test_t2a.yml T2a 5 > /tmp/t2a_output.log 2>&1
echo DONE > /tmp/t2a_done.flag
