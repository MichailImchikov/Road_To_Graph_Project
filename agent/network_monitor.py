#!/usr/bin/env python3
"""ROS 2 traffic monitor - subscribes to graph topics and tracks bandwidth."""

import time
import socket
import os
import re
import logging
import threading
from typing import Dict, Optional

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String, ByteMultiArray
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
    rclpy = Node = String = ByteMultiArray = None
    logging.basicConfig(level=logging.INFO)
    logging.warning("ROS 2 not available, network monitoring disabled")

try:
    from config import config
except ImportError:
    class DummyConfig:
        NODE_ID = os.getenv('NODE_ID', socket.gethostname())
        LOG_LEVEL = 'INFO'
    config = DummyConfig()

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ROS2TrafficMonitor(Node):
    """Monitors ROS 2 topic traffic for profiling. Thread-safe."""
    
    def __init__(self, node_id: str):
        if not ROS_AVAILABLE:
            raise RuntimeError("ROS 2 not available")
        
        super().__init__('ros2_traffic_monitor')
        self.node_id = node_id
        self.topic_stats: Dict[str, Dict] = {}
        self._subscribed: set = set()
        self.lock = threading.Lock()
        
        # Discover new topics every 2s - might miss short-lived ones but good enough
        self.create_timer(2.0, self._discover_and_subscribe)

    def _discover_and_subscribe(self):
        try:
            for name, types in self.get_topic_names_and_types():
                # Only care about our test graph topics
                if 'light_topic' in name and name not in self._subscribed:
                    self._subscribe(name, types[0])
                    self._subscribed.add(name)
        except Exception:
            # Don't crash the whole agent if discovery fails
            pass

    def _subscribe(self, topic_name: str, topic_type: str):
        try:
            # Support both String and ByteMultiArray - ugly but covers our use case
            if topic_type == 'std_msgs/msg/String':
                self.create_subscription(String, topic_name, 
                                       lambda m, tn=topic_name: self._cb(m, tn), 
                                       100)  # QoS depth, arbitrary but works
            elif topic_type == 'std_msgs/msg/ByteMultiArray':
                self.create_subscription(ByteMultiArray, topic_name,
                                       lambda m, tn=topic_name: self._cb(m, tn),
                                       100)
        except Exception:
            # Subscription failed - maybe topic disappeared, will retry on next discovery
            pass

    def _cb(self, msg, topic_name: str):
        """Accumulate byte counts. Lock is held by caller."""
        try:
            # Handle both .data types - getattr with default for safety
            data = getattr(msg, 'data', b'')
            size = len(data) if isinstance(data, (bytes, str, list)) else 0
            
            with self.lock:
                if topic_name not in self.topic_stats:
                    self.topic_stats[topic_name] = {'bytes': 0, 'msgs': 0, 'ts': time.time()}
                self.topic_stats[topic_name]['bytes'] += size
                self.topic_stats[topic_name]['msgs'] += 1
                self.topic_stats[topic_name]['ts'] = time.time()
        except Exception:
            # Silently ignore callback errors - one bad message shouldn't break monitoring
            pass

    def get_stats(self, duration: Optional[float] = None) -> Dict[str, Dict]:
        """Return stats and reset counters. Thread-safe."""
        stats = {}
        calc_duration = duration if duration else 10.0  # Default window if not specified
        
        with self.lock:
            for topic, data in self.topic_stats.items():
                if data['msgs'] == 0:
                    continue
                
                # Parse topic name - assumes format /light_topic_<from>_to_<to>
                # TODO: make this more robust if topic naming changes
                m = re.search(r'light_topic_(\d+)_to_(\d+)', topic)
                sender = f'light_node_{m.group(1)}' if m else 'unknown'
                receiver = f'light_node_{m.group(2)}' if m else 'unknown'
                
                # Bandwidth in Mbps: bytes * 8 bits / seconds / 1e6
                bw = (data['bytes'] * 8) / calc_duration / 1_000_000 if data['bytes'] > 0 else 0.0
                
                stats[topic] = {
                    'sender': sender, 'receiver': receiver,
                    'bytes': data['bytes'], 'msgs': data['msgs'],
                    'bandwidth_mbps': round(bw, 4)
                }
            
            # Reset after reading - ensures each profiling interval is independent
            # This is intentional: we want per-interval bandwidth, not cumulative
            self.topic_stats = {}
            
        return stats
