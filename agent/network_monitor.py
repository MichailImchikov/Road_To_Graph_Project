#!/usr/bin/env python3
# agent/network_monitor.py - Мониторинг сетевого трафика ROS 2 топиков

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, ReliabilityPolicy
from std_msgs.msg import ByteMultiArray, String
import time
import socket
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
import requests
import logging
import threading
import re

# Локальный импорт конфига
try:
    from config import config
except ImportError:
    class DummyConfig:
        NODE_ID = os.getenv('NODE_ID', socket.gethostname())
        COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', 'localhost')
        COLLECTOR_PORT = int(os.getenv('COLLECTOR_PORT', '8080'))
        NETWORK_INTERVAL = 5
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


class ROS2TrafficMonitor(Node):
    """Мониторинг трафика ROS 2 топиков"""
    
    def __init__(self, node_id: str):
        super().__init__('ros2_traffic_monitor')
        self.node_id = node_id
        self.node_ip = self._get_node_ip()
        
        # Статистика по топикам
        self.topic_stats: Dict[str, Dict] = {}
        self.subscriptions = {}
        
        # Блокировка для потокобезопасности
        self.lock = threading.Lock()
        
        # Время начала измерения
        self.start_time = time.time()
        
        # Подписка на все топики с шаблоном light_topic_*
        self._discover_and_subscribe_topics()
        
        # Периодическая очистка статистики
        self.create_timer(10.0, self._clear_old_stats)
    
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
    
    def _discover_and_subscribe_topics(self):
        """Обнаружение и подписка на топики"""
        try:
            # Получаем список топиков
            topic_names_and_types = self.get_topic_names_and_types()
            
            for topic_name, topic_types in topic_names_and_types:
                # Подписываемся только на топики light_topic_*
                if 'light_topic' in topic_name:
                    self._subscribe_to_topic(topic_name, topic_types[0])
            
            logger.info(f"Подписался на {len(self.subscriptions)} ROS 2 топиков")
            
        except Exception as e:
            logger.error(f"Ошибка обнаружения топиков: {e}")
    
    def _subscribe_to_topic(self, topic_name: str, topic_type: str):
        """Подписка на конкретный топик"""
        try:
            # Определяем тип сообщения и подписываемся
            if topic_type == 'std_msgs/msg/ByteMultiArray':
                qos = QoSProfile(
                    depth=10,
                    reliability=ReliabilityPolicy.BEST_EFFORT
                )
                self.subscriptions[topic_name] = self.create_subscription(
                    ByteMultiArray,
                    topic_name,
                    lambda msg, tn=topic_name: self._callback(msg, tn),
                    qos
                )
            elif topic_type == 'std_msgs/msg/String':
                qos = QoSProfile(
                    depth=10,
                    reliability=ReliabilityPolicy.BEST_EFFORT
                )
                self.subscriptions[topic_name] = self.create_subscription(
                    String,
                    topic_name,
                    lambda msg, tn=topic_name: self._callback(msg, tn),
                    qos
                )
            else:
                logger.debug(f"Неподдерживаемый тип топика {topic_type} для {topic_name}")
                
        except Exception as e:
            logger.error(f"Ошибка подписки на {topic_name}: {e}")
    
    def _callback(self, msg, topic_name: str):
        """Обработка входящего сообщения"""
        try:
            # Определяем размер сообщения
            if hasattr(msg, 'data'):
                if isinstance(msg.data, (bytes, bytearray)):
                    msg_size = len(msg.data)
                elif isinstance(msg.data, str):
                    msg_size = len(msg.data.encode('utf-8'))
                elif isinstance(msg.data, list):
                    msg_size = len(msg.data)
                else:
                    msg_size = 0
            else:
                msg_size = 0
            
            # Обновляем статистику
            with self.lock:
                if topic_name not in self.topic_stats:
                    self.topic_stats[topic_name] = {
                        'bytes_received': 0,
                        'messages_received': 0,
                        'last_update': time.time()
                    }
                
                self.topic_stats[topic_name]['bytes_received'] += msg_size
                self.topic_stats[topic_name]['messages_received'] += 1
                self.topic_stats[topic_name]['last_update'] = time.time()
                
        except Exception as e:
            logger.debug(f"Ошибка в callback для {topic_name}: {e}")
    
    def _clear_old_stats(self):
        """Очистка устаревшей статистики"""
        current_time = time.time()
        with self.lock:
            # Удаляем топики, которые не обновлялись более 30 секунд
            stale_topics = [
                topic for topic, stats in self.topic_stats.items()
                if current_time - stats['last_update'] > 30
            ]
            for topic in stale_topics:
                del self.topic_stats[topic]
    
    def get_traffic_stats(self, duration: float = None) -> Dict[str, Dict]:
        """Получение статистики трафика"""
        if duration is None:
            duration = self.get_clock().now().seconds - self.start_time
        
        stats = {}
        with self.lock:
            for topic_name, data in self.topic_stats.items():
                # Извлекаем информацию о получателе из имени топика
                # Формат: /light_topic_X_to_Y
                match = re.search(r'light_topic_(\d+)_to_(\d+)', topic_name)
                if match:
                    sender_id = match.group(1)
                    receiver_id = match.group(2)
                else:
                    sender_id = "unknown"
                    receiver_id = "unknown"
                
                # Рассчитываем пропускную способность
                bytes_total = data['bytes_received']
                msgs_total = data['messages_received']
                
                bandwidth_mbps = 0.0
                if duration > 0 and bytes_total > 0:
                    bits = bytes_total * 8
                    bandwidth_mbps = (bits / duration) / 1_000_000
                
                stats[topic_name] = {
                    'sender': f"light_node_{sender_id}",
                    'receiver': f"light_node_{receiver_id}",
                    'bytes': bytes_total,
                    'messages': msgs_total,
                    'bandwidth_mbps': round(bandwidth_mbps, 4),
                    'duration': duration
                }
        
        return stats
    
    def destroy(self):
        """Очистка ресурсов"""
        for sub in self.subscriptions.values():
            self.destroy_subscription(sub)
        self.destroy_node()


class NetworkProfiler:
    """Профайлер сетевого трафика"""
    
    def __init__(self):
        self.node_id = config.NODE_ID
        self.node_ip = self._get_node_ip()
        self.collector_url = f"http://{config.COLLECTOR_HOST}:{config.COLLECTOR_PORT}/network"
        self.ros_monitor = None
    
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
    
    def initialize_ros_monitor(self):
        """Инициализация ROS 2 монитора"""
        try:
            if not rclpy.ok():
                rclpy.init()
            
            self.ros_monitor = ROS2TrafficMonitor(self.node_id)
            logger.info("ROS 2 traffic monitor initialized")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка инициализации ROS монитора: {e}")
            return False
    
    def collect_network_metrics(self) -> Optional[NetworkReport]:
        """Сбор сетевых метрик"""
        timestamp = datetime.utcnow().isoformat()
        
        if not self.ros_monitor:
            logger.warning("ROS монитор не инициализирован")
            return None
        
        # Обрабатываем события ROS для обновления статистики
        rclpy.spin_once(self.ros_monitor, timeout_sec=0.1)
        
        # Получаем статистику
        traffic_stats = self.ros_monitor.get_traffic_stats(
            duration=config.NETWORK_INTERVAL
        )
        
        # Формируем потоки
        flows = []
        total_bandwidth = 0.0
        total_packets = 0
        
        for topic_name, stats in traffic_stats.items():
            # Пропускаем потоки с нулевым трафиком
            if stats['bytes'] == 0:
                continue
            
            bandwidth = stats['bandwidth_mbps']
            
            # Пропускаем ниже порога
            if bandwidth < config.NETWORK_THRESHOLD_MBPS:
                continue
            
            flow = NetworkFlow(
                source_node=stats['sender'],
                source_task=stats['sender'],
                source_ip=self.node_ip,
                source_port=0,  # ROS 2 использует динамические порты
                dest_node=stats['receiver'],
                dest_task=stats['receiver'],
                dest_ip="0.0.0.0",  # Не определяем IP получателя
                dest_port=0,
                protocol="ROS2_DDS",
                bytes_sent=stats['bytes'],
                packets_sent=stats['messages'],
                bandwidth_mbps=bandwidth,
                timestamp=timestamp
            )
            flows.append(flow)
            
            total_bandwidth += bandwidth
            total_packets += stats['messages']
        
        report = NetworkReport(
            node_id=self.node_id,
            timestamp=timestamp,
            flows=flows,
            total_bandwidth_mbps=round(total_bandwidth, 2),
            total_packets=total_packets,
            num_flows=len(flows)
        )
        
        logger.info(f"Сетевой отчёт: {len(flows)} потоков, {total_bandwidth:.4f} Mbps")
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
        logger.info(f"Запуск сетевого мониторинга ROS 2 на {self.node_id}")
        
        if not self.initialize_ros_monitor():
            logger.error("Не удалось инициализировать ROS монитор")
            return
        
        try:
            while rclpy.ok():
                report = self.collect_network_metrics()
                if report:
                    self.send_to_collector(report)
                
                # Спим NETWORK_INTERVAL секунд
                time.sleep(config.NETWORK_INTERVAL)
                
        except KeyboardInterrupt:
            logger.info("Сетевой мониторинг остановлен")
        finally:
            if self.ros_monitor:
                self.ros_monitor.destroy()
            if rclpy.ok():
                rclpy.shutdown()


def main():
    """Точка входа"""
    profiler = NetworkProfiler()
    
    try:
        profiler.run_continuous()
    except KeyboardInterrupt:
        logger.info("Мониторинг остановлен")
    
    return 0


if __name__ == '__main__':
    exit(main())