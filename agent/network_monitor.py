#!/usr/bin/env python3
# agent/network_monitor.py - Мониторинг сетевого трафика между задачами

import subprocess
import json
import re
import time
import socket
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
import requests
import logging

# Локальный импорт конфига
try:
    from config import config
except ImportError:
    class DummyConfig:
        NODE_ID = os.getenv('NODE_ID', socket.gethostname())
        COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', 'localhost')
        COLLECTOR_PORT = int(os.getenv('COLLECTOR_PORT', '8080'))
        NETWORK_INTERVAL = 5
        NETWORK_INTERFACE = os.getenv('NETWORK_INTERFACE', 'eth0')
        CAPTURE_FILTER = 'tcp or udp'
        NETWORK_THRESHOLD_MBPS = 0.1
        OUTPUT_DIR = './output'
        LOG_LEVEL = 'INFO'
    config = DummyConfig()

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class NetworkFlow:
    """Сетевой поток между двумя задачами"""
    source_node: str
    source_task: str
    source_ip: str
    source_port: int
    dest_node: str
    dest_task: str
    dest_ip: str
    dest_port: int
    protocol: str
    bytes_sent: int
    packets_sent: int
    bandwidth_mbps: float
    timestamp: str


@dataclass
class NetworkReport:
    """Отчёт по сетевому трафику"""
    node_id: str
    timestamp: str
    flows: List[NetworkFlow]
    total_bandwidth_mbps: float
    total_packets: int
    num_flows: int


class TSharkMonitor:
    """Обёртка над tshark для мониторинга сети"""
    
    def __init__(self, interface: str = None, capture_filter: str = None, duration: int = None):
        self.interface = interface or config.NETWORK_INTERFACE
        self.capture_filter = capture_filter or config.CAPTURE_FILTER
        self.capture_duration = duration or config.NETWORK_INTERVAL
    
    def check_tshark_available(self) -> bool:
        """Проверка доступности tshark"""
        try:
            result = subprocess.run(
                ['tshark', '--version'], 
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"tshark недоступен: {e}")
            return False
    
    def capture_traffic(self) -> str:
        """
        Захват сетевого трафика
        Возвращает вывод tshark в текстовом формате
        """
        try:
            cmd = [
                'sudo', 'tshark',
                '-i', self.interface,
                '-f', self.capture_filter,
                '-a', f'duration:{self.capture_duration}',
                '-q', '-z', 'conv,ip',
                '-n'  # Не разрешать имена (быстрее)
            ]
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.capture_duration + 10
            )
            return result.stdout
        
        except subprocess.TimeoutExpired:
            logger.error("Таймаут захвата трафика")
            return ""
        except Exception as e:
            logger.error(f"Ошибка захвата трафика: {e}")
            return ""
    
    def parse_conversations(self, output: str) -> List[Dict]:
        """
        Парсинг разговоров между IP-адресами
        Формат вывода tshark -z conv,ip:
        |192.168.1.1|<->|192.168.1.2|TCP|100|200|300|...
        """
        conversations = []
        
        for line in output.split('\n'):
            if '|' not in line or '<->' not in line:
                continue
            
            parts = line.split('|')
            if len(parts) >= 8:
                try:
                    conv = {
                        'ip1': parts[1],
                        'ip2': parts[3],
                        'protocol': parts[4],
                        'bytes_1_to_2': int(parts[5]) if parts[5].isdigit() else 0,
                        'bytes_2_to_1': int(parts[6]) if parts[6].isdigit() else 0,
                        'packets_1_to_2': int(parts[7]) if parts[7].isdigit() else 0,
                    }
                    conv['total_bytes'] = conv['bytes_1_to_2'] + conv['bytes_2_to_1']
                    conversations.append(conv)
                except (ValueError, IndexError) as e:
                    logger.debug(f"Ошибка парсинга строки: {e}")
        
        return conversations
    
    def get_port_mappings(self) -> Dict[str, Dict[int, str]]:
        """
        Получение соответствия портов и процессов
        Использует ss или netstat
        """
        port_map = {}
        
        try:
            result = subprocess.run(
                ['sudo', 'ss', '-tlnp'],
                capture_output=True, text=True, timeout=5
            )
            
            for line in result.stdout.split('\n'):
                if 'LISTEN' in line:
                    parts = line.split()
                    if len(parts) >= 6:
                        addr_port = parts[4]
                        if ':' in addr_port:
                            ip, port_str = addr_port.rsplit(':', 1)
                            try:
                                port = int(port_str)
                                proc_info = parts[-1]
                                if 'users:' in proc_info:
                                    match = re.search(r'\("([^"]+)"', proc_info)
                                    if match:
                                        if ip not in port_map:
                                            port_map[ip] = {}
                                        port_map[ip][port] = match.group(1)
                            except ValueError:
                                continue
        except Exception as e:
            logger.error(f"Ошибка получения маппинга портов: {e}")
        
        return port_map
    
    def calculate_bandwidth(self, bytes_total: int, duration: float) -> float:
        """Расчёт пропускной способности в Мбит/с"""
        if duration <= 0:
            return 0.0
        
        bits = bytes_total * 8
        mbps = (bits / duration) / 1_000_000
        return round(mbps, 2)


class NetworkProfiler:
    """Профайлер сетевого трафика"""
    
    def __init__(self):
        self.node_id = config.NODE_ID
        self.node_ip = self._get_node_ip()
        self.tshark = TSharkMonitor()
        self.collector_url = f"http://{config.COLLECTOR_HOST}:{config.COLLECTOR_PORT}/network"
    
    def _get_node_ip(self) -> str:
        """Получение IP адреса текущего узла"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return socket.gethostbyname(socket.gethostname())
    
    def identify_remote_node(self, ip: str) -> str:
        """
        Определение удалённого узла по IP
        В продакшене нужна таблица соответствия IP -> node_id
        """
        if ip == self.node_ip:
            return self.node_id
        else:
            # Эвристика: если IP вида 192.168.1.X, то node-X
            match = re.search(r'\.(\d+)$', ip)
            if match:
                return f"node-{match.group(1)}"
            return f"node-{ip.replace('.', '-')}"
    
    def collect_network_metrics(self) -> NetworkReport:
        """Сбор сетевых метрик"""
        timestamp = datetime.utcnow().isoformat()
        
        # Захват трафика
        logger.info("Захват сетевого трафика...")
        capture_output = self.tshark.capture_traffic()
        
        # Парсинг разговоров
        conversations = self.tshark.parse_conversations(capture_output)
        
        # Получение маппинга портов
        port_map = self.tshark.get_port_mappings()
        
        # Формирование потоков
        flows = []
        total_bandwidth = 0.0
        total_packets = 0
        
        for conv in conversations:
            # Пропускаем локальный трафик ниже порога
            if conv['total_bytes'] < 1000:  # 1KB порог
                continue
            
            bandwidth = self.tshark.calculate_bandwidth(
                conv['total_bytes'],
                self.tshark.capture_duration
            )
            
            if bandwidth < config.NETWORK_THRESHOLD_MBPS:
                continue
            
            # Определение задач по IP (упрощённо)
            source_task = f"task_{conv['ip1']}"
            dest_task = f"task_{conv['ip2']}"
            
            flow = NetworkFlow(
                source_node=self.node_id,
                source_task=source_task,
                source_ip=conv['ip1'],
                source_port=0,
                dest_node=self.identify_remote_node(conv['ip2']),
                dest_task=dest_task,
                dest_ip=conv['ip2'],
                dest_port=0,
                protocol=conv['protocol'],
                bytes_sent=conv['total_bytes'],
                packets_sent=conv['packets_1_to_2'],
                bandwidth_mbps=bandwidth,
                timestamp=timestamp
            )
            flows.append(flow)
            
            total_bandwidth += bandwidth
            total_packets += conv['packets_1_to_2']
        
        report = NetworkReport(
            node_id=self.node_id,
            timestamp=timestamp,
            flows=flows,
            total_bandwidth_mbps=round(total_bandwidth, 2),
            total_packets=total_packets,
            num_flows=len(flows)
        )
        
        logger.info(f"Сетевой отчёт: {len(flows)} потоков, {total_bandwidth:.2f} Mbps")
        return report
    
    def send_to_collector(self, report: NetworkReport) -> bool:
        """Отправка отчёта сборщику"""
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
            logger.warning("Нет связи с коллектором для сетевых метрик")
            return False
        except Exception as e:
            logger.error(f"Ошибка отправки сетевых метрик: {e}")
            return False
    
    def run_continuous(self):
        """Непрерывный мониторинг"""
        logger.info(f"Запуск сетевого мониторинга на {self.node_id}")
        
        while True:
            try:
                report = self.collect_network_metrics()
                self.send_to_collector(report)
            except KeyboardInterrupt:
                logger.info("Сетевой мониторинг остановлен")
                break
            except Exception as e:
                logger.error(f"Ошибка в сетевом мониторинге: {e}")
            
            time.sleep(config.NETWORK_INTERVAL)


def main():
    """Точка входа"""
    profiler = NetworkProfiler()
    
    if not profiler.tshark.check_tshark_available():
        logger.error("tshark недоступен. Установите: sudo apt install tshark")
        return 1
    
    try:
        profiler.run_continuous()
    except KeyboardInterrupt:
        logger.info("Мониторинг остановлен")
    
    return 0


if __name__ == '__main__':
    exit(main())