#!/usr/bin/env python3
# scripts/collect_once.py - Однократный сбор метрик для оптимизации

import requests
import json
import os
import sys
from datetime import datetime
from typing import List, Dict

# Конфигурация
COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', 'localhost')
COLLECTOR_PORT = os.getenv('COLLECTOR_PORT', '8080')
OUTPUT_DIR = './output'

def fetch_report() -> Dict:
    """Получение отчёта от коллектора"""
    url = f"http://{COLLECTOR_HOST}:{COLLECTOR_PORT}/report"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Ошибка получения отчёта: {e}")
        return {}

def save_report(report: Dict) -> str:
    """Сохранение отчёта в файл"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"{OUTPUT_DIR}/optimization_input_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    return filename

def print_summary(report: Dict):
    """Вывод краткой сводки"""
    print("\n" + "=" * 60)
    print("СВОДКА ПО СИСТЕМЕ")
    print("=" * 60)
    
    total_nodes = report.get('total_nodes', 0)
    total_tasks = sum(
        len(node.get('tasks', []))
        for node in report.get('nodes', [])
    )
    
    print(f"Узлов: {total_nodes}")
    print(f"Задач: {total_tasks}")
    print(f"Время: {report.get('timestamp', 'N/A')}")
    print("=" * 60 + "\n")

def main():
    print("=" * 60)
    print("ОДНОКРАТНЫЙ СБОР МЕТРИК ДЛЯ ОПТИМИЗАЦИИ")
    print("=" * 60)
    
    report = fetch_report()
    
    if not report:
        print("❌ Не удалось получить отчёт")
        return 1
    
    print_summary(report)
    
    filename = save_report(report)
    
    print(f"✅ Отчёт сохранён: {filename}")
    print(f"\n📋 Следующий шаг:")
    print(f"   python3 optimizer/optimizer.py {filename}")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())