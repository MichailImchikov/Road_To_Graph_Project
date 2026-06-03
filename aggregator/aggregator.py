#!/usr/bin/env python3
"""Report aggregator - pulls data from collector, generates JSON/TXT/CSV."""

import requests
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
import logging

try:
    from config import config
except ImportError:
    class DummyConfig:
        COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', 'localhost')
        COLLECTOR_PORT = int(os.getenv('COLLECTOR_PORT', '8080'))
        OUTPUT_DIR = './output'
        LOG_LEVEL = 'INFO'
    config = DummyConfig()

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class AdjacentTask:
    task_id: str
    bandwidth_mbps: float
    direction: str


@dataclass
class TaskReport:
    task_id: str
    task_name: str
    node_id: str
    core_id: int
    cpu_load_percent: float
    memory_usage_mb: float
    instructions_per_sec: float
    memory_bandwidth_mbps: float
    adjacent_tasks: List[AdjacentTask]
    network_traffic_mbps: float


@dataclass
class NodeReport:
    node_id: str
    last_update: str
    total_cpu_load: float
    total_memory_usage_mb: float
    num_cores: int
    num_active_tasks: int
    tasks: List[TaskReport]


@dataclass
class SystemReport:
    report_type: str
    timestamp: str
    total_nodes: int
    total_tasks: int
    total_cpu_load_avg: float
    total_memory_usage_mb: float
    nodes: List[NodeReport]
    summary: Dict  # TODO: proper dataclass later


class ReportAggregator:
    def __init__(self, collector_host: str = None, collector_port: int = None):
        self.collector_host = collector_host or config.COLLECTOR_HOST
        self.collector_port = collector_port or config.COLLECTOR_PORT
        self.base_url = f"http://{self.collector_host}:{self.collector_port}"
    
    def fetch_raw_report(self) -> Optional[Dict]:
        url = f"{self.base_url}/report"
        try:
            logger.info(f"Fetching {url}...")
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            logger.error(f"Can't reach collector at {self.base_url}")
            return None
        except Exception as e:
            logger.error(f"Fetch failed: {e}")
            return None
    
    def fetch_and_save_report(self, output_file: str = None) -> Optional[str]:
        raw = self.fetch_raw_report()
        if not raw:
            return None
        
        if output_file is None:
            ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            output_file = f"{config.OUTPUT_DIR}/report_{ts}.json"
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved raw report: {output_file}")
        return output_file
    
    def process_report(self, raw_report: Dict) -> SystemReport:
        timestamp = datetime.utcnow().isoformat()
        
        nodes = []
        total_tasks = 0
        total_cpu = 0.0
        total_mem = 0.0
        
        for node_data in raw_report.get('nodes', []):
            nr = self._process_node(node_data)
            nodes.append(nr)
            total_tasks += nr.num_active_tasks
            total_cpu += nr.total_cpu_load
            total_mem += nr.total_memory_usage_mb
        
        n = len(nodes)
        avg_cpu = total_cpu / n if n > 0 else 0.0
        
        summary = {
            'total_nodes': n,
            'total_tasks': total_tasks,
            'avg_cpu_load_percent': round(avg_cpu, 2),
            'total_memory_usage_mb': round(total_mem, 2),
            'avg_tasks_per_node': round(total_tasks / n, 2) if n > 0 else 0,
            'high_load_tasks': self._find_high_load_tasks(nodes),
            'high_memory_tasks': self._find_high_memory_tasks(nodes),
            'high_network_tasks': self._find_high_network_tasks(nodes)
        }
        
        return SystemReport(
            report_type='system_profiling',
            timestamp=timestamp,
            total_nodes=n,
            total_tasks=total_tasks,
            total_cpu_load_avg=round(avg_cpu, 2),
            total_memory_usage_mb=round(total_mem, 2),
            nodes=nodes,
            summary=summary
        )
    
    def _process_node(self, node_data: Dict) -> NodeReport:
        tasks = [self._process_task(t) for t in node_data.get('tasks', [])]
        return NodeReport(
            node_id=node_data.get('node_id', 'unknown'),
            last_update=node_data.get('last_update', datetime.utcnow().isoformat()),
            total_cpu_load=node_data.get('total_cpu_load', 0.0),
            total_memory_usage_mb=node_data.get('total_memory_usage_mb', 0.0),
            num_cores=node_data.get('num_cores', 0),
            num_active_tasks=len(tasks),
            tasks=tasks
        )
    
    def _process_task(self, task_data: Dict) -> TaskReport:
        adj = [
            AdjacentTask(
                task_id=a.get('task_id', 'unknown'),
                bandwidth_mbps=a.get('bandwidth_mbps', 0.0),
                direction=a.get('direction', 'unknown')
            )
            for a in task_data.get('adjacent_tasks', [])
        ]
        return TaskReport(
            task_id=task_data.get('task_id', 'unknown'),
            task_name=task_data.get('task_name', 'unknown'),
            node_id=task_data.get('node_id', 'unknown'),
            core_id=task_data.get('core_id', 0),
            cpu_load_percent=task_data.get('cpu_load_percent', 0.0),
            memory_usage_mb=task_data.get('memory_usage_mb', 0.0),
            instructions_per_sec=task_data.get('instructions_per_sec', 0.0),
            memory_bandwidth_mbps=task_data.get('memory_bandwidth_mbps', 0.0),
            adjacent_tasks=adj,
            network_traffic_mbps=task_data.get('network_traffic_mbps', 0.0)
        )
    
    def _find_high_load_tasks(self, nodes: List[NodeReport], threshold: float = 80.0) -> List[Dict]:
        out = []
        for node in nodes:
            for t in node.tasks:
                if t.cpu_load_percent >= threshold:
                    out.append({'task_id': t.task_id, 'node_id': t.node_id,
                               'cpu_load_percent': t.cpu_load_percent, 'task_name': t.task_name})
        return sorted(out, key=lambda x: x['cpu_load_percent'], reverse=True)[:10]
    
    def _find_high_memory_tasks(self, nodes: List[NodeReport], threshold: float = 1000.0) -> List[Dict]:
        out = []
        for node in nodes:
            for t in node.tasks:
                if t.memory_usage_mb >= threshold:
                    out.append({'task_id': t.task_id, 'node_id': t.node_id,
                               'memory_usage_mb': t.memory_usage_mb, 'task_name': t.task_name})
        return sorted(out, key=lambda x: x['memory_usage_mb'], reverse=True)[:10]
    
    def _find_high_network_tasks(self, nodes: List[NodeReport], threshold: float = 100.0) -> List[Dict]:
        out = []
        for node in nodes:
            for t in node.tasks:
                if t.network_traffic_mbps >= threshold:
                    out.append({'task_id': t.task_id, 'node_id': t.node_id,
                               'network_traffic_mbps': t.network_traffic_mbps,
                               'adjacent_count': len(t.adjacent_tasks)})
        return sorted(out, key=lambda x: x['network_traffic_mbps'], reverse=True)[:10]


class ReportFormatter:
    @staticmethod
    def format_text_report(report: SystemReport) -> str:
        lines = []
        lines.append("=" * 80)
        lines.append("SYSTEM PROFILING REPORT")
        lines.append("=" * 80)
        lines.append(f"Generated: {report.timestamp}")
        lines.append(f"Nodes: {report.total_nodes} | Tasks: {report.total_tasks}")
        lines.append(f"Avg CPU: {report.total_cpu_load_avg:.1f}% | Total RAM: {report.total_memory_usage_mb:.0f} MB")
        lines.append("")
        
        # Highlights - plain text, no emojis
        if report.summary.get('high_load_tasks'):
            lines.append("[CPU] High-load tasks (>80%):")
            for t in report.summary['high_load_tasks'][:5]:
                lines.append(f"    {t['task_id']}: {t['cpu_load_percent']:.1f}%")
        
        if report.summary.get('high_memory_tasks'):
            lines.append("[MEM] High-memory tasks (>1GB):")
            for t in report.summary['high_memory_tasks'][:5]:
                lines.append(f"    {t['task_id']}: {t['memory_usage_mb']:.0f} MB")
        
        if report.summary.get('high_network_tasks'):
            lines.append("[NET] High-traffic tasks (>100 Mbps):")
            for t in report.summary['high_network_tasks'][:5]:
                lines.append(f"    {t['task_id']}: {t['network_traffic_mbps']:.1f} Mbps")
        
        lines.append("")
        
        # Per-node details
        for node in report.nodes:
            lines.append(f"--- Node: {node.node_id} ---")
            lines.append(f"CPU: {node.total_cpu_load:.1f}% | RAM: {node.total_memory_usage_mb:.0f} MB")
            lines.append(f"Tasks: {node.num_active_tasks}")
            for t in node.tasks[:3]:
                lines.append(f"  - {t.task_name}: CPU={t.cpu_load_percent:.1f}%, "
                           f"MemBW={t.memory_bandwidth_mbps:.2f} MB/s, "
                           f"Net={t.network_traffic_mbps:.2f} Mbps")
            if len(node.tasks) > 3:
                lines.append(f"  ... and {len(node.tasks) - 3} more")
            lines.append("")
        
        lines.append("=" * 80)
        return "\n".join(lines)
    
    @staticmethod
    def format_csv_report(report: SystemReport) -> str:
        lines = ["node_id,task_id,task_name,core_id,cpu_load,memory_mb,inst_per_sec,mem_bw_mbps,net_bw_mbps"]
        for node in report.nodes:
            for t in node.tasks:
                lines.append(
                    f"{node.node_id},{t.task_id},\"{t.task_name}\",{t.core_id},"
                    f"{t.cpu_load_percent},{t.memory_usage_mb},{t.instructions_per_sec},"
                    f"{t.memory_bandwidth_mbps},{t.network_traffic_mbps}"
                )
        return "\n".join(lines)


def generate_report(output_dir: str = None, 
                   collector_host: str = None, 
                   collector_port: int = None) -> Optional[str]:
    agg = ReportAggregator(collector_host, collector_port)
    
    raw = agg.fetch_raw_report()
    if not raw:
        logger.error("Failed to fetch report from collector")
        return None
    
    report = agg.process_report(raw)
    
    out_dir = output_dir or config.OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    
    ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    
    json_path = f"{out_dir}/report_{ts}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False)
    
    txt_path = f"{out_dir}/report_{ts}.txt"
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(ReportFormatter.format_text_report(report))
    
    csv_path = f"{out_dir}/report_{ts}.csv"
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write(ReportFormatter.format_csv_report(report))
    
    print(ReportFormatter.format_text_report(report))
    
    logger.info(f"Reports saved: {json_path}, {txt_path}, {csv_path}")
    return json_path


def main():
    print("Generating profiling report...")
    result = generate_report()
    if result:
        print(f"\n[OK] Done. JSON: {result}")
        return 0
    else:
        print("\n[FAIL] Report generation failed")
        return 1


if __name__ == '__main__':
    exit(main())
