#!/usr/bin/env python3
# agent/agent.py - Агент профилирования на каждом вычислительном узле

import subprocess
import json
import socket
import time
import os
import re
import threading
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
import requests
import logging

# ROS 2 импорты для мониторинга трафика
import rclpy
from rclpy.node import Node
from agent.network_monitor import ROS2TrafficMonitor

# Локальный импорт конфига
try:
    from config import config
except ImportError:
    class DummyConfig:
        NODE_ID = os.getenv('NODE_ID', socket.gethostname())
        COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', 'localhost')
        COLLECTOR_PORT = int(os.getenv('COLLECTOR_PORT', '8080'))
        PROFILING_INTERVAL = 10
        NETWORK_INTERVAL = 5
        LIKWID_GROUP = 'INST'
        MEASUREMENT_DURATION = 5
        CPU_THRESHOLD_PERCENT = 5.0
        NETWORK_THRESHOLD_MBPS = 0.1
        NUM_CORES = os.cpu_count() or 4
        OUTPUT_DIR = './output'
        LOG_LEVEL = 'INFO'
    config = DummyConfig()

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TaskMetrics:
    """Метрики одной задачи (процесса)"""
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
    """Отчёт по узлу"""
    node_id: str
    timestamp: str
    tasks: List[TaskMetrics]
    total_cpu_load: float
    total_memory_usage_mb: float
    num_cores: int
    num_active_tasks: int


class LikwidProfiler:
    """Обёртка над LIKWID для профилирования"""
    
    def __init__(self, group: str = None, duration: int = None):
        self.group = group or config.LIKWID_GROUP
        self.duration = duration or config.MEASUREMENT_DURATION
    
    def check_likwid_available(self) -> bool:
        """Проверка доступности LIKWID"""
        try:
            result = subprocess.run(
                ['likwid-topology'], 
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"LIKWID недоступен: {e}")
            return False
    
    def load_msr_module(self):
        """Загрузка модуля MSR ядра (требует sudo)"""
        try:
            subprocess.run(['sudo', 'modprobe', 'msr'], check=True)
            logger.info("Модуль msr загружен")
        except Exception as e:
            logger.warning(f"Не удалось загрузить msr: {e}")
    
    def measure_core(self, core_id: int, pid: Optional[int] = None) -> Dict:
        """
        Замер метрик для конкретного ядра
        Если pid указан - меряем конкретный процесс
        """
        try:
            cmd = [
                'likwid-perfctr',
                '-C', str(core_id),
                '-g', self.group,
                '-t', str(self.duration * 1000),
            ]
            
            if pid:
                cmd.extend(['-p', str(pid)])
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.duration + 10
            )
            
            return self._parse_likwid_output(result.stdout, core_id)
        
        except subprocess.TimeoutExpired:
            logger.error(f"Таймаут замера ядра {core_id}")
            return self._empty_metrics(core_id)
        except Exception as e:
            logger.error(f"Ошибка замера ядра {core_id}: {e}")
            return self._empty_metrics(core_id)
    
    def _parse_likwid_output(self, output: str, core_id: int) -> Dict:
        """Парсинг вывода LIKWID"""
        metrics = {
            'core_id': core_id,
            'instructions': 0,
            'instructions_per_sec': 0,
            'memory_bandwidth_mbps': 0,
            'cache_hit_rate': 0,
            'cpu_cycles': 0
        }
        
        for line in output.split('\n'):
            if 'INSTR_RETIRED' in line:
                try:
                    parts = line.split()
                    if parts:
                        val = parts[-1].replace(',', '.')
                        metrics['instructions'] = float(val)
                except (ValueError, IndexError):
                    pass
            
            elif 'CPU_CLK_UNHALTED_THREAD' in line:
                try:
                    parts = line.split()
                    if parts:
                        val = parts[-1].replace(',', '.')
                        metrics['cpu_cycles'] = float(val)
                except (ValueError, IndexError):
                    pass
            
            elif 'Memory bandwidth' in line or 'MEM' in line.upper():
                try:
                    match = re.search(r'([\d.]+)\s*(?:MB/s|MBps|MBit/s)?', line, re.I)
                    if match:
                        metrics['memory_bandwidth_mbps'] = float(match.group(1))
                except (ValueError, AttributeError):
                    pass
        
        if self.duration > 0 and metrics['instructions'] > 0:
            metrics['instructions_per_sec'] = metrics['instructions'] / self.duration
        
        return metrics
    
    def _empty_metrics(self, core_id: int) -> Dict:
        """Пустые метрики при ошибке"""
        return {
            'core_id': core_id,
            'instructions': 0,
            'instructions_per_sec': 0,
            'memory_bandwidth_mbps': 0,
            'cache_hit_rate': 0,
            'cpu_cycles': 0
        }


class ProcessMonitor:
    """Мониторинг процессов на узле"""
    
    def get_all_processes(self) -> List[Dict]:
        """Получить список всех процессов с метриками"""
        processes = []
        
        try:
            result = subprocess.run(
                ['ps', 'aux', '--sort=-%cpu'],
                capture_output=True, text=True, timeout=5
            )
            
            lines = result.stdout.split('\n')[1:]
            
            for line in lines[:50]:
                if not line.strip():
                    continue
                
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    try:
                        processes.append({
                            'pid': int(parts[1]),
                            'user': parts[0],
                            'cpu_percent': float(parts[2]),
                            'memory_percent': float(parts[3]),
                            'memory_rss_mb': float(parts[4]) / 1024,
                            'command': parts[10][:100]
                        })
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            logger.error(f"Ошибка получения процессов: {e}")
        
        return processes
    
    def get_cpu_load_per_core(self) -> List[float]:
        """Загрузка по каждому ядру (из /proc/stat)"""
        loads = []
        
        try:
            with open('/proc/stat', 'r') as f:
                lines = f.readlines()
            
            for line in lines:
                if line.startswith('cpu') and line[3:4].isdigit():
                    parts = line.split()
                    if len(parts) >= 5:
                        user = int(parts[1])
                        nice = int(parts[2])
                        system = int(parts[3])
                        idle = int(parts[4])
                        
                        total = user + nice + system + idle
                        if total > 0:
                            load = ((user + nice + system) / total) * 100
                            loads.append(load)
        except Exception as e:
            logger.error(f"Ошибка чтения загрузки CPU: {e}")
            loads = [0.0] * config.NUM_CORES
        
        return loads
    
    def get_memory_usage(self) -> Dict:
        """Использование памяти всем узлом (из /proc/meminfo)"""
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
            
            mem_info = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    value = float(parts[1]) / 1024
                    mem_info[key] = value
            
            total = mem_info.get('MemTotal', 0)
            available = mem_info.get('MemAvailable', mem_info.get('MemFree', 0))
            used = total - available
            
            return {
                'total_mb': total,
                'used_mb': used,
                'available_mb': available,
                'percent': (used / total * 100) if total > 0 else 0
            }
        except Exception as e:
            logger.error(f"Ошибка чтения памяти: {e}")
            return {'total_mb': 0, 'used_mb': 0, 'available_mb': 0, 'percent': 0}


class ProfilingAgent:
    """Основной агент профилирования"""
    
    def __init__(self):
        self.node_id = config.NODE_ID
        self.likwid = LikwidProfiler()
        self.process_monitor = ProcessMonitor()
        self.collector_url = f"http://{config.COLLECTOR_HOST}:{config.COLLECTOR_PORT}/metrics"
        self.running = False
        
        # Инициализация ROS 2 и сетевого монитора
        self.network_monitor = None
        self._init_ros_network_monitor()
    
    def _init_ros_network_monitor(self):
        """Инициализация ROS 2 монитора трафика"""
        try:
            if not rclpy.ok():
                rclpy.init()
            self.network_monitor = ROS2TrafficMonitor(self.node_id)
            logger.info("ROS 2 network monitor initialized")
        except Exception as e:
            logger.warning(f"Не удалось инициализировать ROS network monitor: {e}")
            self.network_monitor = None
    
    def initialize(self) -> bool:
        """Инициализация агента"""
        logger.info(f"Инициализация агента на узле {self.node_id}")
        
        if not self.likwid.check_likwid_available():
            logger.warning("LIKWID недоступен, будем использовать только ps")
        
        self.likwid.load_msr_module()
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        
        return True
    
    def collect_node_metrics(self) -> NodeReport:
        """Сбор метрик по всему узлу"""
        timestamp = datetime.utcnow().isoformat()
        
        cpu_loads = self.process_monitor.get_cpu_load_per_core()
        mem_usage = self.process_monitor.get_memory_usage()
        processes = self.process_monitor.get_all_processes()
        
        tasks = []
        core_idx = 0
        
        for proc in processes:
            if proc['cpu_percent'] < config.CPU_THRESHOLD_PERCENT:
                continue
            
            core_id = core_idx % config.NUM_CORES
            likwid_metrics = self.likwid.measure_core(core_id, proc['pid'])
            
            task = TaskMetrics(
                task_id=f"{self.node_id}_{proc['pid']}",
                task_name=proc['command'],
                node_id=self.node_id,
                core_id=core_id,
                cpu_load_percent=proc['cpu_percent'],
                memory_usage_mb=proc['memory_rss_mb'],
                instructions_per_sec=likwid_metrics['instructions_per_sec'],
                memory_bandwidth_mbps=likwid_metrics['memory_bandwidth_mbps'],
                timestamp=timestamp,
                adjacent_tasks=[],
                network_traffic_mbps=0.0
            )
            tasks.append(task)
            core_idx += 1
        
        # === ИНТЕГРАЦИЯ СЕТЕВЫХ МЕТРИК ===
        if self.network_monitor:
            try:
                rclpy.spin_once(self.network_monitor, timeout_sec=0.1)
                
                traffic_stats = self.network_monitor.get_traffic_stats(
                    duration=config.PROFILING_INTERVAL
                )
                
                task_map = {task.task_id: task for task in tasks}
                
                for topic_name, stats in traffic_stats.items():
                    sender = stats['sender']
                    receiver = stats['receiver']
                    bandwidth = stats['bandwidth_mbps']
                    
                    if bandwidth < config.NETWORK_THRESHOLD_MBPS:
                        continue
                    
                    if sender in task_map:
                        task_map[sender].adjacent_tasks.append({
                            'task_id': receiver,
                            'bandwidth_mbps': bandwidth,
                            'direction': 'outbound'
                        })
                        task_map[sender].network_traffic_mbps += bandwidth
                    
                    if receiver in task_map:
                        task_map[receiver].adjacent_tasks.append({
                            'task_id': sender,
                            'bandwidth_mbps': bandwidth,
                            'direction': 'inbound'
                        })
                        task_map[receiver].network_traffic_mbps += bandwidth
                        
            except Exception as e:
                logger.debug(f"Ошибка сбора сетевых метрик: {e}")
        # === КОНЕЦ ИНТЕГРАЦИИ ===
        
        total_cpu_load = sum(cpu_loads) / len(cpu_loads) if cpu_loads else 0
        
        report = NodeReport(
            node_id=self.node_id,
            timestamp=timestamp,
            tasks=tasks,
            total_cpu_load=round(total_cpu_load, 2),
            total_memory_usage_mb=round(mem_usage['used_mb'], 2),
            num_cores=config.NUM_CORES,
            num_active_tasks=len(tasks)
        )
        
        return report
    
    def send_to_collector(self, report: NodeReport) -> bool:
        """Отправка отчёта центральному сборщику"""
        try:
            data = asdict(report)
            response = requests.post(
                self.collector_url,
                json=data,
                timeout=10,
                headers={'Content-Type': 'application/json'}
            )
            return response.status_code == 200
        except requests.exceptions.ConnectionError:
            logger.warning("Нет связи с коллектором, сохраняем локально")
            self.save_locally(report)
            return False
        except Exception as e:
            logger.error(f"Ошибка отправки метрик: {e}")
            self.save_locally(report)
            return False
    
    def save_locally(self, report: NodeReport):
        """Сохранение локально при потере связи"""
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{config.OUTPUT_DIR}/metrics_backup_{self.node_id}_{timestamp}.json"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(asdict(report), f, indent=2, ensure_ascii=False)
            logger.info(f"Метрики сохранены локально: {filename}")
        except Exception as e:
            logger.error(f"Ошибка локального сохранения: {e}")
    
    def run(self):
        """Основной цикл работы агента"""
        logger.info(f"Запуск агента профилирования на {self.node_id}")
        self.running = True
        
        while self.running:
            try:
                report = self.collect_node_metrics()
                
                if not self.send_to_collector(report):
                    logger.warning("Не удалось отправить метрики")
                
                logger.info(
                    f"Узел {self.node_id}: "
                    f"{report.num_active_tasks} задач, "
                    f"CPU: {report.total_cpu_load:.1f}%, "
                    f"RAM: {report.total_memory_usage_mb:.0f}MB"
                )
                
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки")
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле профилирования: {e}")
            
            time.sleep(config.PROFILING_INTERVAL)
    
    def stop(self):
        """Остановка агента"""
        self.running = False
        
        # Очистка ROS 2 ресурсов
        if self.network_monitor:
            try:
                self.network_monitor.destroy()
            except:
                pass
        if rclpy.ok():
            rclpy.shutdown()
        
        logger.info("Агент остановлен")


def main():
    """Точка входа"""
    agent = ProfilingAgent()
    
    if not agent.initialize():
        logger.error("Не удалось инициализировать агент")
        return 1
    
    try:
        agent.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
        agent.stop()
    
    return 0


if __name__ == '__main__':
    exit(main())