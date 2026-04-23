#!/usr/bin/env python3
# collector/collector.py - Центральный сервер для сбора метрик от агентов

from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
import threading
import logging
from dataclasses import dataclass, asdict, field

# Локальный импорт конфига
try:
    from config import config
except ImportError:
    class DummyConfig:
        COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', '0.0.0.0')
        COLLECTOR_PORT = int(os.getenv('COLLECTOR_PORT', '8080'))
        OUTPUT_DIR = './output'
        LOG_LEVEL = 'INFO'
        MAX_METRICS_HISTORY = 100  # Максимум записей в истории
    config = DummyConfig()

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


app = Flask(__name__)
CORS(app)  # Разрешить CORS для запросов с других узлов


# ═══════════════════════════════════════════════════════════════
# ХРАНИЛИЩЕ ДАННЫХ (в памяти)
# ═══════════════════════════════════════════════════════════════

class MetricsStore:
    """Хранилище метрик в памяти"""
    
    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self.lock = threading.Lock()
        
        # Метрики узлов (последние данные от каждого узла)
        self.node_metrics: Dict[str, Dict] = {}
        
        # Сетевые метрики (история по каждому узлу)
        self.network_metrics: Dict[str, List[Dict]] = {}
        
        # Временные метки последнего обновления
        self.last_update: Dict[str, datetime] = {}
    
    def add_node_metrics(self, node_id: str, data: Dict):
        """Добавление метрик узла"""
        with self.lock:
            self.node_metrics[node_id] = {
                'timestamp': datetime.utcnow().isoformat(),
                'data': data
            }
            self.last_update[node_id] = datetime.utcnow()
            logger.info(f"Получены метрики от узла {node_id}")
    
    def add_network_metrics(self, node_id: str, data: Dict):
        """Добавление сетевых метрик"""
        with self.lock:
            if node_id not in self.network_metrics:
                self.network_metrics[node_id] = []
            
            self.network_metrics[node_id].append({
                'timestamp': datetime.utcnow().isoformat(),
                'data': data
            })
            
            # Ограничение истории
            if len(self.network_metrics[node_id]) > self.max_history:
                self.network_metrics[node_id] = self.network_metrics[node_id][-self.max_history:]
            
            logger.debug(f"Получены сетевые метрики от узла {node_id}")
    
    def get_all_node_metrics(self) -> Dict[str, Dict]:
        """Получение всех метрик узлов"""
        with self.lock:
            return dict(self.node_metrics)
    
    def get_all_network_metrics(self) -> Dict[str, List[Dict]]:
        """Получение всех сетевых метрик"""
        with self.lock:
            return dict(self.network_metrics)
    
    def get_node_count(self) -> int:
        """Количество зарегистрированных узлов"""
        with self.lock:
            return len(self.node_metrics)
    
    def cleanup_stale_nodes(self, timeout_seconds: int = 300):
        """Удаление узлов, которые не присылали данные дольше timeout"""
        with self.lock:
            now = datetime.utcnow()
            stale_nodes = []
            
            for node_id, last_time in self.last_update.items():
                if (now - last_time).total_seconds() > timeout_seconds:
                    stale_nodes.append(node_id)
            
            for node_id in stale_nodes:
                del self.node_metrics[node_id]
                del self.last_update[node_id]
                logger.warning(f"Узел {node_id} помечен как неактивный")


# Глобальное хранилище
metrics_store = MetricsStore(max_history=config.MAX_METRICS_HISTORY)


# ═══════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.route('/health', methods=['GET'])
def health():
    """
    Проверка здоровья сервера
    
    Returns:
        JSON со статусом сервера
    """
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'nodes_registered': metrics_store.get_node_count(),
        'version': '1.0.0'
    }), 200


@app.route('/metrics', methods=['POST'])
def receive_node_metrics():
    """
    Приём метрик от агентов узлов
    
    Request Body:
        {
            "node_id": "node-1",
            "timestamp": "2024-03-30T10:30:00Z",
            "tasks": [...],
            "total_cpu_load": 45.5,
            "total_memory_usage_mb": 8192,
            ...
        }
    
    Returns:
        JSON со статусом приёма
    """
    try:
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
        
        data = request.json
        node_id = data.get('node_id')
        
        if not node_id:
            return jsonify({'error': 'node_id is required'}), 400
        
        # Валидация данных
        required_fields = ['tasks', 'total_cpu_load', 'total_memory_usage_mb']
        for field in required_fields:
            if field not in data:
                logger.warning(f"Отсутствует поле {field} в метриках от {node_id}")
        
        # Сохранение в хранилище
        metrics_store.add_node_metrics(node_id, data)
        
        return jsonify({
            'status': 'ok',
            'node_id': node_id,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    
    except Exception as e:
        logger.error(f"Ошибка приёма метрик: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/network', methods=['POST'])
def receive_network_metrics():
    """
    Приём сетевых метрик от агентов
    
    Request Body:
        {
            "node_id": "node-1",
            "timestamp": "2024-03-30T10:30:00Z",
            "flows": [...],
            "total_bandwidth_mbps": 125.5,
            ...
        }
    
    Returns:
        JSON со статусом приёма
    """
    try:
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
        
        data = request.json
        node_id = data.get('node_id')
        
        if not node_id:
            return jsonify({'error': 'node_id is required'}), 400
        
        # Сохранение в хранилище
        metrics_store.add_network_metrics(node_id, data)
        
        return jsonify({
            'status': 'ok',
            'node_id': node_id,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    
    except Exception as e:
        logger.error(f"Ошибка приёма сетевых метрик: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/report', methods=['GET'])
def get_aggregated_report():
    """
    Получение агрегированного отчёта по всей системе
    
    Это основной endpoint для aggregator.py
    
    Returns:
        JSON с объединёнными данными со всех узлов
    """
    try:
        report = generate_aggregated_report()
        return jsonify(report), 200
    
    except Exception as e:
        logger.error(f"Ошибка генерации отчёта: {e}")
        return jsonify({
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@app.route('/report/save', methods=['POST'])
def save_report():
    """
    Сохранение отчёта в файл на сервере
    
    Returns:
        JSON с путём к сохранённому файлу
    """
    try:
        report = generate_aggregated_report()
        
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{config.OUTPUT_DIR}/report_{timestamp}.json"
        
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Отчёт сохранён: {filename}")
        
        return jsonify({
            'status': 'ok',
            'filename': filename,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    
    except Exception as e:
        logger.error(f"Ошибка сохранения отчёта: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/nodes', methods=['GET'])
def get_nodes_list():
    """
    Получение списка зарегистрированных узлов
    
    Returns:
        JSON со списком узлов и их статусом
    """
    try:
        nodes = []
        node_metrics = metrics_store.get_all_node_metrics()
        
        for node_id, data in node_metrics.items():
            nodes.append({
                'node_id': node_id,
                'last_update': data['timestamp'],
                'tasks_count': len(data['data'].get('tasks', [])),
                'cpu_load': data['data'].get('total_cpu_load', 0),
                'memory_usage_mb': data['data'].get('total_memory_usage_mb', 0)
            })
        
        return jsonify({
            'total_nodes': len(nodes),
            'nodes': nodes,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    
    except Exception as e:
        logger.error(f"Ошибка получения списка узлов: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/metrics/<node_id>', methods=['GET'])
def get_node_metrics(node_id: str):
    """
    Получение метрик конкретного узла
    
    Args:
        node_id: Идентификатор узла
    
    Returns:
        JSON с метриками узла
    """
    try:
        node_metrics = metrics_store.get_all_node_metrics()
        
        if node_id not in node_metrics:
            return jsonify({
                'error': f'Node {node_id} not found',
                'available_nodes': list(node_metrics.keys())
            }), 404
        
        return jsonify(node_metrics[node_id]), 200
    
    except Exception as e:
        logger.error(f"Ошибка получения метрик узла {node_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/network/<node_id>', methods=['GET'])
def get_node_network_metrics(node_id: str):
    """
    Получение сетевых метрик конкретного узла
    
    Args:
        node_id: Идентификатор узла
    
    Returns:
        JSON с сетевыми метриками узла
    """
    try:
        network_metrics = metrics_store.get_all_network_metrics()
        
        if node_id not in network_metrics:
            return jsonify({
                'error': f'No network metrics for node {node_id}',
                'available_nodes': list(network_metrics.keys())
            }), 404
        
        return jsonify({
            'node_id': node_id,
            'history_count': len(network_metrics[node_id]),
            'latest': network_metrics[node_id][-1] if network_metrics[node_id] else None
        }), 200
    
    except Exception as e:
        logger.error(f"Ошибка получения сетевых метрик узла {node_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/stats', methods=['GET'])
def get_system_stats():
    """
    Получение статистики системы
    
    Returns:
        JSON со статистикой collector
    """
    try:
        node_metrics = metrics_store.get_all_node_metrics()
        network_metrics = metrics_store.get_all_network_metrics()
        
        total_tasks = sum(
            len(data['data'].get('tasks', []))
            for data in node_metrics.values()
        )
        
        total_cpu_load = sum(
            data['data'].get('total_cpu_load', 0)
            for data in node_metrics.values()
        )
        
        total_memory = sum(
            data['data'].get('total_memory_usage_mb', 0)
            for data in node_metrics.values()
        )
        
        return jsonify({
            'total_nodes': len(node_metrics),
            'total_tasks': total_tasks,
            'avg_cpu_load': round(total_cpu_load / len(node_metrics), 2) if node_metrics else 0,
            'total_memory_mb': round(total_memory, 2),
            'network_flows_total': sum(len(flows) for flows in network_metrics.values()),
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════

def generate_aggregated_report() -> Dict:
    """
    Генерация агрегированного отчёта по всем узлам
    
    Returns:
        Dict с объединёнными данными
    """
    timestamp = datetime.utcnow().isoformat()
    
    node_metrics = metrics_store.get_all_node_metrics()
    network_metrics = metrics_store.get_all_network_metrics()
    
    # Структура отчёта
    report = {
        'report_type': 'system_profiling',
        'timestamp': timestamp,
        'total_nodes': len(node_metrics),
        'nodes': []
    }
    
    # Обработка метрик по каждому узлу
    for node_id, node_data in node_metrics.items():
        node_report = {
            'node_id': node_id,
            'last_update': node_data['timestamp'],
            'total_cpu_load': node_data['data'].get('total_cpu_load', 0),
            'total_memory_usage_mb': node_data['data'].get('total_memory_usage_mb', 0),
            'num_cores': node_data['data'].get('num_cores', 0),
            'tasks': []
        }
        
        # Обработка задач
        for task in node_data['data'].get('tasks', []):
            task_info = {
                'task_id': task.get('task_id'),
                'task_name': task.get('task_name'),
                'core_id': task.get('core_id'),
                'cpu_load_percent': task.get('cpu_load_percent'),
                'memory_usage_mb': task.get('memory_usage_mb'),
                'instructions_per_sec': task.get('instructions_per_sec'),
                'memory_bandwidth_mbps': task.get('memory_bandwidth_mbps'),
                'adjacent_tasks': [],
                'network_traffic_mbps': 0
            }
            node_report['tasks'].append(task_info)
        
        report['nodes'].append(node_report)
    
    # Добавление сетевых связей между задачами
    add_network_connections(report, network_metrics)
    
    return report


def add_network_connections(report: Dict, network_metrics: Dict):
    """
    Добавление информации о сетевых соединениях между задачами
    
    Args:
        report: Отчёт для модификации
        network_metrics: Сетевые метрики от всех узлов
    """
    # Словарь для быстрого поиска задач
    task_map = {}
    for node in report['nodes']:
        for task in node['tasks']:
            task_map[task['task_id']] = task
    
    # Обработка сетевых потоков
    for node_id, network_data_list in network_metrics.items():
        if not network_data_list:
            continue
        
        # Берём последние данные
        latest = network_data_list[-1]['data']
        
        for flow in latest.get('flows', []):
            source_task_id = flow.get('source_task')
            dest_task_id = flow.get('dest_task')
            bandwidth = flow.get('bandwidth_mbps', 0)
            
            # Добавляем связь в обе задачи
            if source_task_id in task_map:
                task_map[source_task_id]['adjacent_tasks'].append({
                    'task_id': dest_task_id,
                    'bandwidth_mbps': bandwidth,
                    'direction': 'outbound'
                })
                task_map[source_task_id]['network_traffic_mbps'] += bandwidth
            
            if dest_task_id in task_map:
                task_map[dest_task_id]['adjacent_tasks'].append({
                    'task_id': source_task_id,
                    'bandwidth_mbps': bandwidth,
                    'direction': 'inbound'
                })
                task_map[dest_task_id]['network_traffic_mbps'] += bandwidth


def cleanup_task():
    """Фоновая задача для очистки устаревших узлов"""
    while True:
        try:
            metrics_store.cleanup_stale_nodes(timeout_seconds=300)
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")
        threading.Event().wait(60)  # Запуск каждые 60 секунд


# ═══════════════════════════════════════════════════════════════
# ЗАПУСК СЕРВЕРА
# ═══════════════════════════════════════════════════════════════

def main():
    """Точка входа"""
    logger.info("=" * 60)
    logger.info("ЗАПУСК ЦЕНТРАЛЬНОГО СБОРЩИКА МЕТРИК")
    logger.info("=" * 60)
    logger.info(f"Хост: {config.COLLECTOR_HOST}")
    logger.info(f"Порт: {config.COLLECTOR_PORT}")
    logger.info(f"Директория вывода: {config.OUTPUT_DIR}")
    logger.info("=" * 60)
    
    # Создание директории для вывода
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    
    # Запуск фоновой задачи очистки
    cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
    cleanup_thread.start()
    
    # Запуск Flask сервера
    app.run(
        host=config.COLLECTOR_HOST,
        port=config.COLLECTOR_PORT,
        threaded=True,
        debug=False
    )


if __name__ == '__main__':
    main()