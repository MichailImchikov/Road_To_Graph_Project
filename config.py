#!/usr/bin/env python3
# config.py

from dataclasses import dataclass
import socket
import os

@dataclass
class SystemConfig:
    NODE_ID: str = os.getenv('NODE_ID', socket.gethostname())
    COLLECTOR_HOST: str = os.getenv('COLLECTOR_HOST', 'localhost')
    COLLECTOR_PORT: int = int(os.getenv('COLLECTOR_PORT', '8080'))
    PROFILING_INTERVAL: int = 10
    NETWORK_INTERVAL: int = 5
    LIKWID_GROUP: str = 'INST'
    MEASUREMENT_DURATION: int = 5
    NETWORK_INTERFACE: str = os.getenv('NETWORK_INTERFACE', 'eth0')
    OUTPUT_DIR: str = './output'
    LOG_LEVEL: str = 'INFO'
    NUM_CORES: int = os.cpu_count() or 4

config = SystemConfig()