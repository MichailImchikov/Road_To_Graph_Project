#!/usr/bin/env python3
# aggregator/aggregator.py - Генерация финального отчёта по системе

import requests
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
import logging

# Локальный импорт конфига
try:
    from config import config
except ImportError:
    class DummyConfig:
        COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', 'localhost')
        COLLECTOR_PORT = int(os.getenv('COLLECTOR_PORT', '8080'))
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
class AdjacentTask:
    """Смежная задача (для сетевого взаимодействия)"""
    task_id: str
    bandwidth_mbps: float
    direction: str  # 'inbound' или 'outbound'


@dataclass
class TaskReport:
    """Отчёт по одной задаче"""
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
    """Отчёт по одному узлу"""
    node_id: str
    last_update: str
    total_cpu_load: float
    total_memory_usage_mb: float
    num_cores: int
    num_active_tasks: int
    tasks: List[TaskReport]


@dataclass
class SystemReport:
    """Итоговый отчёт по всей системе"""
    report_type: str
    timestamp: str
    total_nodes: int
    total_tasks: int
    total_cpu_load_avg: float
    total_memory_usage_mb: float
    nodes: List[NodeReport]
    summary: Dict


class ReportAggregator:
    """Агрегатор отчётов от центрального сборщика"""
    
    def __init__(self, collector_host: str = None, collector_port: int = None):
        self.collector_host = collector_host or config.COLLECTOR_HOST
        self.collector_port = collector_port or config.COLLECTOR_PORT
        self.base_url = f"http://{self.collector_host}:{self.collector_port}"
    
    def fetch_raw_report(self) -> Optional[Dict]:
        """Получение сырого отчёта от коллектора"""
        url = f"{self.base_url}/report"
        
        try:
            logger.info(f"Запрос отчёта у {url}...")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            logger.error(f"Нет соединения с коллектором {self.base_url}")
            return None
        except requests.exceptions.Timeout:
            logger.error("Таймаут при получении отчёта")
            return None
        except Exception as e:
            logger.error(f"Ошибка получения отчёта: {e}")
            return None
    
    def fetch_and_save_report(self, output_file: str = None) -> Optional[str]:
        """Получение отчёта и сохранение в файл"""
        raw_report = self.fetch_raw_report()
        
        if not raw_report:
            logger.error("Не удалось получить отчёт")
            return None
        
        # Генерация имени файла если не указано
        if output_file is None:
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            output_file = f"{config.OUTPUT_DIR}/report_{timestamp}.json"
        
        # Создание директории
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        # Сохранение JSON
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(raw_report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Отчёт сохранён: {output_file}")
        return output_file
    
    def process_report(self, raw_report: Dict) -> SystemReport:
        """
        Обработка сырого отчёта и формирование структурированных данных
        """
        timestamp = datetime.utcnow().isoformat()
        
        nodes = []
        total_tasks = 0
        total_cpu_load_sum = 0.0
        total_memory_sum = 0.0
        
        # Обработка каждого узла
        for node_data in raw_report.get('nodes', []):
            node_report = self._process_node(node_data)
            nodes.append(node_report)
            
            total_tasks += node_report.num_active_tasks
            total_cpu_load_sum += node_report.total_cpu_load
            total_memory_sum += node_report.total_memory_usage_mb
        
        # Средняя загрузка по системе
        num_nodes = len(nodes)
        avg_cpu_load = total_cpu_load_sum / num_nodes if num_nodes > 0 else 0.0
        
        # Формирование сводки
        summary = {
            'total_nodes': num_nodes,
            'total_tasks': total_tasks,
            'avg_cpu_load_percent': round(avg_cpu_load, 2),
            'total_memory_usage_mb': round(total_memory_sum, 2),
            'avg_tasks_per_node': round(total_tasks / num_nodes, 2) if num_nodes > 0 else 0,
            'high_load_tasks': self._find_high_load_tasks(nodes),
            'high_memory_tasks': self._find_high_memory_tasks(nodes),
            'high_network_tasks': self._find_high_network_tasks(nodes)
        }
        
        report = SystemReport(
            report_type='system_profiling',
            timestamp=timestamp,
            total_nodes=num_nodes,
            total_tasks=total_tasks,
            total_cpu_load_avg=round(avg_cpu_load, 2),
            total_memory_usage_mb=round(total_memory_sum, 2),
            nodes=nodes,
            summary=summary
        )
        
        return report
    
    def _process_node(self, node_data: Dict) -> NodeReport:
        """Обработка данных одного узла"""
        tasks = []
        
        for task_data in node_data.get('tasks', []):
            task = self._process_task(task_data)
            tasks.append(task)
        
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
        """Обработка данных одной задачи"""
        adjacent_tasks = []
        
        for adj in task_data.get('adjacent_tasks', []):
            adjacent_tasks.append(AdjacentTask(
                task_id=adj.get('task_id', 'unknown'),
                bandwidth_mbps=adj.get('bandwidth_mbps', 0.0),
                direction=adj.get('direction', 'unknown')
            ))
        
        return TaskReport(
            task_id=task_data.get('task_id', 'unknown'),
            task_name=task_data.get('task_name', 'unknown'),
            node_id=task_data.get('node_id', 'unknown'),
            core_id=task_data.get('core_id', 0),
            cpu_load_percent=task_data.get('cpu_load_percent', 0.0),
            memory_usage_mb=task_data.get('memory_usage_mb', 0.0),
            instructions_per_sec=task_data.get('instructions_per_sec', 0.0),
            memory_bandwidth_mbps=task_data.get('memory_bandwidth_mbps', 0.0),
            adjacent_tasks=adjacent_tasks,
            network_traffic_mbps=task_data.get('network_traffic_mbps', 0.0)
        )
    
    def _find_high_load_tasks(self, nodes: List[NodeReport], threshold: float = 80.0) -> List[Dict]:
        """Найти задачи с высокой загрузкой CPU"""
        high_load = []
        
        for node in nodes:
            for task in node.tasks:
                if task.cpu_load_percent >= threshold:
                    high_load.append({
                        'task_id': task.task_id,
                        'node_id': task.node_id,
                        'cpu_load_percent': task.cpu_load_percent,
                        'task_name': task.task_name
                    })
        
        return sorted(high_load, key=lambda x: x['cpu_load_percent'], reverse=True)[:10]
    
    def _find_high_memory_tasks(self, nodes: List[NodeReport], threshold: float = 1000.0) -> List[Dict]:
        """Найти задачи с высоким потреблением памяти"""
        high_memory = []
        
        for node in nodes:
            for task in node.tasks:
                if task.memory_usage_mb >= threshold:
                    high_memory.append({
                        'task_id': task.task_id,
                        'node_id': task.node_id,
                        'memory_usage_mb': task.memory_usage_mb,
                        'task_name': task.task_name
                    })
        
        return sorted(high_memory, key=lambda x: x['memory_usage_mb'], reverse=True)[:10]
    
    def _find_high_network_tasks(self, nodes: List[NodeReport], threshold: float = 100.0) -> List[Dict]:
        """Найти задачи с высоким сетевым трафиком"""
        high_network = []
        
        for node in nodes:
            for task in node.tasks:
                if task.network_traffic_mbps >= threshold:
                    high_network.append({
                        'task_id': task.task_id,
                        'node_id': task.node_id,
                        'network_traffic_mbps': task.network_traffic_mbps,
                        'adjacent_count': len(task.adjacent_tasks)
                    })
        
        return sorted(high_network, key=lambda x: x['network_traffic_mbps'], reverse=True)[:10]


class ReportFormatter:
    """Форматирование отчётов для вывода"""
    
    @staticmethod
    def format_text_report(report: SystemReport) -> str:
        """Форматирование в текстовый вид"""
        lines = []
        lines.append("=" * 80)
        lines.append("ОТЧЁТ ПРОФИЛИРОВАНИЯ ВЫЧИСЛИТЕЛЬНОЙ СИСТЕМЫ")
        lines.append("=" * 80)
        lines.append(f"Время генерации: {report.timestamp}")
        lines.append(f"Всего узлов: {report.total_nodes}")
        lines.append(f"Всего задач: {report.total_tasks}")
        lines.append(f"Средняя загрузка CPU: {report.total_cpu_load_avg:.1f}%")
        lines.append(f"Общая память: {report.total_memory_usage_mb:.0f} MB")
        lines.append("")
        
        # Сводка
        lines.append("-" * 80)
        lines.append("СВОДКА")
        lines.append("-" * 80)
        
        if report.summary.get('high_load_tasks'):
            lines.append("\n🔴 Задачи с высокой загрузкой CPU (>80%):")
            for task in report.summary['high_load_tasks'][:5]:
                lines.append(f"  • {task['task_id']}: {task['cpu_load_percent']:.1f}%")
        
        if report.summary.get('high_memory_tasks'):
            lines.append("\n🟡 Задачи с высоким потреблением памяти (>1GB):")
            for task in report.summary['high_memory_tasks'][:5]:
                lines.append(f"  • {task['task_id']}: {task['memory_usage_mb']:.0f} MB")
        
        if report.summary.get('high_network_tasks'):
            lines.append("\n🔵 Задачи с высоким сетевым трафиком (>100 Mbps):")
            for task in report.summary['high_network_tasks'][:5]:
                lines.append(f"  • {task['task_id']}: {task['network_traffic_mbps']:.1f} Mbps")
        
        lines.append("")
        
        # Детали по узлам
        for node in report.nodes:
            lines.append("-" * 80)
            lines.append(f"УЗЕЛ: {node.node_id}")
            lines.append(f"Загрузка CPU: {node.total_cpu_load:.1f}%")
            lines.append(f"Использование памяти: {node.total_memory_usage_mb:.0f} MB")
            lines.append(f"Ядер: {node.num_cores}")
            lines.append(f"Активных задач: {node.num_active_tasks}")
            lines.append("")
            
            for task in node.tasks:
                lines.append(f"  Задача: {task.task_id}")
                lines.append(f"    Имя: {task.task_name}")
                lines.append(f"    Ядро: {task.core_id}")
                lines.append(f"    Загрузка CPU: {task.cpu_load_percent:.1f}%")
                lines.append(f"    Память: {task.memory_usage_mb:.1f} MB")
                lines.append(f"    Инструкций/сек: {task.instructions_per_sec:.0f}")
                lines.append(f"    Пропускная способность памяти: {task.memory_bandwidth_mbps:.2f} MB/s")
                
                if task.adjacent_tasks:
                    lines.append(f"    Смежные задачи ({len(task.adjacent_tasks)}):")
                    for adj in task.adjacent_tasks[:5]:
                        lines.append(
                            f"      → {adj.task_id} "
                            f"({adj.bandwidth_mbps:.2f} Mbps, {adj.direction})"
                        )
                
                lines.append(f"    Общий сетевой трафик: {task.network_traffic_mbps:.2f} Mbps")
                lines.append("")
            
            lines.append("")
        
        lines.append("=" * 80)
        lines.append("КОНЕЦ ОТЧЁТА")
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    @staticmethod
    def format_csv_report(report: SystemReport) -> str:
        """Форматирование в CSV вид"""
        lines = []
        
        # Заголовок
        lines.append("node_id,task_id,task_name,core_id,cpu_load_percent,memory_usage_mb,instructions_per_sec,memory_bandwidth_mbps,network_traffic_mbps")
        
        # Данные
        for node in report.nodes:
            for task in node.tasks:
                lines.append(
                    f"{node.node_id},"
                    f"{task.task_id},"
                    f'"{task.task_name}",'
                    f"{task.core_id},"
                    f"{task.cpu_load_percent},"
                    f"{task.memory_usage_mb},"
                    f"{task.instructions_per_sec},"
                    f"{task.memory_bandwidth_mbps},"
                    f"{task.network_traffic_mbps}"
                )
        
        return "\n".join(lines)


def generate_report(output_dir: str = None, 
                   collector_host: str = None, 
                   collector_port: int = None) -> Optional[str]:
    """
    Основная функция для генерации отчёта
    
    Args:
        output_dir: Директория для сохранения отчётов
        collector_host: Хост коллектора
        collector_port: Порт коллектора
    
    Returns:
        Путь к сохранённому файлу или None
    """
    # Создание агрегатора
    aggregator = ReportAggregator(collector_host, collector_port)
    
    # Получение сырого отчёта
    raw_report = aggregator.fetch_raw_report()
    
    if not raw_report:
        logger.error("Не удалось получить отчёт от коллектора")
        return None
    
    # Обработка отчёта
    system_report = aggregator.process_report(raw_report)
    
    # Определение директории вывода
    if output_dir is None:
        output_dir = config.OUTPUT_DIR
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Сохранение JSON
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    json_file = f"{output_dir}/report_{timestamp}.json"
    
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(asdict(system_report), f, indent=2, ensure_ascii=False)
    
    logger.info(f"JSON отчёт сохранён: {json_file}")
    
    # Сохранение TXT
    txt_file = f"{output_dir}/report_{timestamp}.txt"
    text_report = ReportFormatter.format_text_report(system_report)
    
    with open(txt_file, 'w', encoding='utf-8') as f:
        f.write(text_report)
    
    logger.info(f"TXT отчёт сохранён: {txt_file}")
    
    # Сохранение CSV
    csv_file = f"{output_dir}/report_{timestamp}.csv"
    csv_report = ReportFormatter.format_csv_report(system_report)
    
    with open(csv_file, 'w', encoding='utf-8') as f:
        f.write(csv_report)
    
    logger.info(f"CSV отчёт сохранён: {csv_file}")
    
    # Вывод в консоль
    print(text_report)
    
    return json_file


def main():
    """Точка входа"""
    print("=" * 60)
    print("ГЕНЕРАЦИЯ ОТЧЁТА ПРОФИЛИРОВАНИЯ")
    print("=" * 60)
    
    json_file = generate_report()
    
    if json_file:
        print("\n" + "=" * 60)
        print("✅ ОТЧЁТ УСПЕШНО СГЕНЕРИРОВАН")
        print("=" * 60)
        print(f"JSON: {json_file}")
        print(f"TXT:  {json_file.replace('.json', '.txt')}")
        print(f"CSV:  {json_file.replace('.json', '.csv')}")
        print("=" * 60)
        return 0
    else:
        print("\n" + "=" * 60)
        print("❌ ОШИБКА ГЕНЕРАЦИИ ОТЧЁТА")
        print("=" * 60)
        return 1


if __name__ == '__main__':
    exit(main())