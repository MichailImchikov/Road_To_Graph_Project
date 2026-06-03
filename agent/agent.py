#!/usr/bin/env python3
"""Profiling agent for ROS 2 computational graphs."""

import subprocess
import json
import socket
import time
import os
import re
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import requests
import logging

# ROS imports - optional, agent should work without them
try:
    import rclpy
    from rclpy.node import Node
    from .network_monitor import ROS2TrafficMonitor
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
    rclpy = Node = ROS2TrafficMonitor = None
    # Don't crash if ROS isn't installed, just disable network monitoring
    logging.basicConfig(level=logging.INFO)
    logging.warning("ROS 2 unavailable, skipping network metrics")

try:
    from config import config
except ImportError:
    # Fallback for local testing without config.py
    class DummyConfig:
        NODE_ID = os.getenv('NODE_ID', socket.gethostname())
        COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', '127.0.0.1')
        COLLECTOR_PORT = int(os.getenv('COLLECTOR_PORT', '8080'))
        PROFILING_INTERVAL = 10
        NETWORK_INTERVAL = 5
        LIKWID_GROUP = 'MEM'
        MEASUREMENT_DURATION = 2
        CPU_THRESHOLD_PERCENT = 1.0
        NETWORK_THRESHOLD_MBPS = 0.0
        NUM_CORES = os.cpu_count() or 4
        OUTPUT_DIR = './output'
        LOG_LEVEL = 'INFO'
        TARGET_PROCESS_PATTERN = 'light_node'
        REPORT_FILTER_PATTERN = ''
        NODE_NAME_PATTERN = r'light_node_(\d+)\.py'
        ROS_NAME_TEMPLATE = 'light_node_{}'
    config = DummyConfig()

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TaskMetrics:
    task_id: str
    task_name: str
    node_id: str
    core_id: int
    cpu_load_percent: float
    memory_usage_mb: float
    instructions_per_sec: float
    memory_bandwidth_mbps: float
    timestamp: str
    adjacent_tasks: List[Dict] = field(default_factory=list)
    network_traffic_mbps: float = 0.0


@dataclass
class NodeReport:
    node_id: str
    timestamp: str
    tasks: List[TaskMetrics]
    total_cpu_load: float
    total_memory_usage_mb: float
    num_cores: int
    num_active_tasks: int


class LikwidProfiler:
    """Wraps likwid-perfctr calls. Requires sudo for MSR access."""
    
    def __init__(self, group: str = None, duration: int = None):
        self.group = group or config.LIKWID_GROUP
        self.duration = duration or config.MEASUREMENT_DURATION

    def load_msr_module(self):
        try:
            # Might fail if already loaded or locked down - that's ok
            subprocess.run(['sudo', 'modprobe', 'msr'], check=True, capture_output=True)
        except Exception:
            pass  # Best effort, agent can still work with basic metrics

    def measure_core(self, core_id: int, pid: Optional[int] = None) -> Dict:
        try:
            # sudo required here due to kernel lockdown on modern distros
            cmd = ['sudo', '/usr/bin/likwid-perfctr', '-C', str(core_id), 
                   '-g', self.group, 'sleep', str(self.duration)]
            
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                  timeout=self.duration + 30)
            if result.returncode != 0:
                return self._empty_metrics(core_id)
            return self._parse_likwid_output(result.stdout, core_id)
            
        except (subprocess.TimeoutExpired, Exception):
            return self._empty_metrics(core_id)

    def _parse_likwid_output(self, output: str, core_id: int) -> Dict:
        metrics = {'core_id': core_id, 'instructions': 0, 'instructions_per_sec': 0,
                   'memory_bandwidth_mbps': 0, 'cache_hit_rate': 0, 'cpu_cycles': 0}
        try:
            for line in output.split('\n'):
                if 'INSTR_RETIRED_ANY' in line:
                    nums = re.findall(r'[\d,]+\.?\d*', line)
                    if nums: metrics['instructions'] = float(nums[-1].replace(',', ''))
                elif 'Memory bandwidth' in line:
                    nums = re.findall(r'[\d,]+\.?\d*', line)
                    if nums: metrics['memory_bandwidth_mbps'] = float(nums[-1].replace(',', ''))
                elif 'CPU_CLK_UNHALTED_CORE' in line:
                    nums = re.findall(r'[\d,]+\.?\d*', line)
                    if nums: metrics['cpu_cycles'] = float(nums[-1].replace(',', ''))
            
            if self.duration > 0 and metrics['instructions'] > 0:
                metrics['instructions_per_sec'] = metrics['instructions'] / self.duration
        except Exception:
            pass  # Silently ignore parse errors, return zeros
        return metrics

    def _empty_metrics(self, core_id: int) -> Dict:
        return {'core_id': core_id, 'instructions': 0, 'instructions_per_sec': 0,
                'memory_bandwidth_mbps': 0, 'cache_hit_rate': 0, 'cpu_cycles': 0}


class ProcessMonitor:
    """Collects basic system metrics from /proc and ps."""
    
    def get_all_processes(self) -> List[Dict]:
        processes = []
        try:
            result = subprocess.run(['ps', 'aux', '--sort=-%cpu'], 
                                  capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n')[1:50]:  # Top 50 is enough
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    try:
                        processes.append({
                            'pid': int(parts[1]), 'user': parts[0],
                            'cpu_percent': float(parts[2]), 'memory_percent': float(parts[3]),
                            'memory_rss_mb': float(parts[4]) / 1024, 'command': parts[10][:100]
                        })
                    except (ValueError, IndexError):
                        continue
        except Exception:
            pass
        return processes

    def get_cpu_load_per_core(self) -> List[float]:
        loads = []
        try:
            with open('/proc/stat', 'r') as f:
                for line in f:
                    if line.startswith('cpu') and line[3:4].isdigit():
                        parts = line.split()
                        if len(parts) >= 5:
                            user, nice, system, idle = map(int, parts[1:5])
                            total = user + nice + system + idle
                            if total > 0:
                                loads.append(((user + nice + system) / total) * 100)
        except Exception:
            loads = [0.0] * config.NUM_CORES
        return loads

    def get_memory_usage(self) -> Dict:
        try:
            with open('/proc/meminfo', 'r') as f:
                mem_info = {line.split()[0].rstrip(':'): float(line.split()[1])/1024 
                           for line in f if len(line.split()) >= 2}
            total = mem_info.get('MemTotal', 0)
            available = mem_info.get('MemAvailable', mem_info.get('MemFree', 0))
            used = total - available
            return {'total_mb': total, 'used_mb': used, 'available_mb': available,
                    'percent': (used/total*100) if total > 0 else 0}
        except Exception:
            return {'total_mb': 0, 'used_mb': 0, 'available_mb': 0, 'percent': 0}


class ProfilingAgent:
    def __init__(self):
        self.node_id = config.NODE_ID
        self.likwid = LikwidProfiler()
        self.process_monitor = ProcessMonitor()
        self.collector_url = f"http://{config.COLLECTOR_HOST}:{config.COLLECTOR_PORT}/metrics"
        self.running = False
        self.network_monitor = None
        self._init_ros_network_monitor()

    def _init_ros_network_monitor(self):
        if not ROS_AVAILABLE:
            return
        try:
            if not rclpy.ok():
                rclpy.init()
            self.network_monitor = ROS2TrafficMonitor(self.node_id)
        except Exception:
            # Non-critical, agent works without ROS metrics
            pass

    def initialize(self) -> bool:
        self.likwid.load_msr_module()
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        return True

    def collect_node_metrics(self) -> NodeReport:
        timestamp = datetime.now(timezone.utc).isoformat()
        cpu_loads = self.process_monitor.get_cpu_load_per_core()
        mem_usage = self.process_monitor.get_memory_usage()
        processes = self.process_monitor.get_all_processes()
        tasks = []

        # Filter to target processes only
        pattern = getattr(config, 'TARGET_PROCESS_PATTERN', None)
        if pattern and pattern.strip():
            filtered = [p for p in processes 
                       if p['cpu_percent'] >= config.CPU_THRESHOLD_PERCENT 
                       and pattern in p['command']]
        else:
            filtered = [p for p in processes 
                       if p['cpu_percent'] >= config.CPU_THRESHOLD_PERCENT]

        for core_idx, proc in enumerate(filtered):
            core_id = core_idx % config.NUM_CORES
            hw = self.likwid.measure_core(core_id, proc['pid'])
            
            tasks.append(TaskMetrics(
                task_id=f"{self.node_id}_{proc['pid']}", 
                task_name=proc['command'],
                node_id=self.node_id, core_id=core_id,
                cpu_load_percent=proc['cpu_percent'], 
                memory_usage_mb=proc['memory_rss_mb'],
                instructions_per_sec=hw['instructions_per_sec'],
                memory_bandwidth_mbps=hw['memory_bandwidth_mbps'],
                timestamp=timestamp, adjacent_tasks=[], network_traffic_mbps=0.0
            ))

        # Correlate ROS traffic if available
        if self.network_monitor and ROS_AVAILABLE:
            try:
                # Hack: spin a few times to drain the callback queue quickly
                for _ in range(10):
                    rclpy.spin_once(self.network_monitor, timeout_sec=0.05)
                
                traffic = self.network_monitor.get_stats(duration=config.PROFILING_INTERVAL)
                
                # Map process names to ROS node names (ugly but works)
                map_pat = getattr(config, 'NODE_NAME_PATTERN', r'light_node_(\d+)\.py')
                name_tpl = getattr(config, 'ROS_NAME_TEMPLATE', 'light_node_{}')
                
                task_map = {}
                for t in tasks:
                    m = re.search(map_pat, t.task_name)
                    if m:
                        nid = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                        task_map[name_tpl.format(nid)] = t
                
                for topic, stats in traffic.items():
                    bw = stats['bandwidth_mbps']
                    sender = task_map.get(stats['sender'])
                    receiver = task_map.get(stats['receiver'])
                    
                    if sender and bw > 0:
                        sender.network_traffic_mbps += bw
                        sender.adjacent_tasks.append({
                            'task_id': receiver.task_id if receiver else stats['receiver'],
                            'bandwidth_mbps': bw, 'direction': 'outbound'
                        })
                    if receiver and bw > 0:
                        receiver.network_traffic_mbps += bw
                        receiver.adjacent_tasks.append({
                            'task_id': sender.task_id if sender else stats['sender'],
                            'bandwidth_mbps': bw, 'direction': 'inbound'
                        })
            except Exception:
                # Network metrics are nice-to-have, don't crash the agent
                pass

        total_cpu = sum(cpu_loads)/len(cpu_loads) if cpu_loads else 0
        return NodeReport(
            node_id=self.node_id, timestamp=timestamp, tasks=tasks,
            total_cpu_load=round(total_cpu, 2),
            total_memory_usage_mb=round(mem_usage['used_mb'], 2),
            num_cores=config.NUM_CORES,
            num_active_tasks=len(tasks)
        )

    def send_to_collector(self, report: NodeReport) -> bool:
        try:
            # Manual serialization - asdict() was causing issues with nested dataclasses
            payload = {
                'node_id': report.node_id, 'timestamp': report.timestamp,
                'total_cpu_load': report.total_cpu_load,
                'total_memory_usage_mb': report.total_memory_usage_mb,
                'num_cores': report.num_cores, 'num_active_tasks': report.num_active_tasks,
                'tasks': []
            }
            for t in report.tasks:
                payload['tasks'].append({
                    'task_id': t.task_id, 'task_name': t.task_name,
                    'node_id': t.node_id, 'core_id': t.core_id,
                    'cpu_load_percent': t.cpu_load_percent,
                    'memory_usage_mb': t.memory_usage_mb,
                    'instructions_per_sec': t.instructions_per_sec,
                    'memory_bandwidth_mbps': t.memory_bandwidth_mbps,
                    'network_traffic_mbps': t.network_traffic_mbps,
                    'timestamp': t.timestamp, 'adjacent_tasks': t.adjacent_tasks
                })
            
            # Quick debug for first light_node match
            sample = next((x for x in payload['tasks'] if 'light_node_1' in x.get('task_name', '')), None)
            if sample:
                logger.debug(f"Sending {sample['task_name']}: traffic={sample['network_traffic_mbps']}")
            
            resp = requests.post(self.collector_url, json=payload, timeout=10,
                               headers={'Content-Type': 'application/json'})
            return resp.status_code == 200
            
        except requests.exceptions.ConnectionError:
            return False
        except Exception:
            return False

    def run(self):
        self.running = True
        while self.running:
            try:
                report = self.collect_node_metrics()
                self.send_to_collector(report)  # Fire and forget
                logger.info(f"{self.node_id}: {report.num_active_tasks} tasks, "
                           f"CPU: {report.total_cpu_load:.1f}%, RAM: {report.total_memory_usage_mb:.0f}MB")
                time.sleep(config.PROFILING_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception:
                # Log but keep running - one bad cycle shouldn't kill the agent
                time.sleep(5)

    def stop(self):
        self.running = False
        if self.network_monitor and ROS_AVAILABLE:
            try:
                self.network_monitor.destroy()
            except Exception:
                pass
        if rclpy and rclpy.ok():
            rclpy.shutdown()


def main():
    agent = ProfilingAgent()
    if not agent.initialize():
        return 1
    try:
        agent.run()
    except KeyboardInterrupt:
        agent.stop()
    return 0


if __name__ == '__main__':
    exit(main())
