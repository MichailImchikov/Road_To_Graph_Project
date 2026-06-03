#!/usr/bin/env python3
# config.py

from dataclasses import dataclass
import socket
import os

@dataclass
class SystemConfig:
    # === Сеть ===
    NODE_ID: str = os.getenv('NODE_ID', socket.gethostname())
    COLLECTOR_HOST: str = os.getenv('COLLECTOR_HOST', '127.0.0.1')  # ✅ IPv4 надёжнее
    COLLECTOR_PORT: int = int(os.getenv('COLLECTOR_PORT', '8080'))
    
    # === Интервалы ===
    PROFILING_INTERVAL: int = 30
    NETWORK_INTERVAL: int = 5
    
    # === LIKWID ===
    LIKWID_GROUP: str = 'MEM'
    MEASUREMENT_DURATION: int = 2  # ✅ 2 сек вместо 5 для скорости
    
    # === Сеть/трафик ===
    NETWORK_INTERFACE: str = os.getenv('NETWORK_INTERFACE', 'eth0')
    NETWORK_THRESHOLD_MBPS: float = 0.0
    
    # === Пути ===
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
    LOG_LEVEL: str = 'INFO'
    
    # === Система ===
    NUM_CORES: int = os.cpu_count() or 4
    CPU_THRESHOLD_PERCENT: float = 1.0
    
    # === ШАГ 1: Фильтрация процессов ===
    # Профилировать только процессы, содержащие эту строку
    TARGET_PROCESS_PATTERN: str = 'light_node'
    
    # === ШАГ 2: Фильтрация отчёта ===
    # Если задано, в /report попадают только задачи с этой строкой в имени
    # Можно переопределить через ?filter=... в запросе
    REPORT_FILTER_PATTERN: str = ''  # '' = отдавать все
    
    # === ШАГ 3: Универсальный маппинг имён ===
    # Regex для извлечения ID ноды из имени процесса (группа 1 = ID)
    NODE_NAME_PATTERN: str = r'light_node_(\d+)\.py'
    # Шаблон для формирования имени в ROS-топиках
    ROS_NAME_TEMPLATE: str = 'light_node_{}'

# Экземпляр конфига
config = SystemConfig()
