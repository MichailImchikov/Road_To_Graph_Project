#!/usr/bin/env python3
# ros_likwid_agent.py

import subprocess
import requests
import json
import re
import os
import socket
from datetime import datetime

COLLECTOR_URL = os.getenv('COLLECTOR_URL', 'http://localhost:8080/metrics')
NODE_ID = socket.gethostname()

def get_ros_nodes():
    """Получить список активных ROS 2 нод и их PID"""
    # Команда: ros2 node list --all
    result = subprocess.run(['ros2', 'node', 'list'], capture_output=True, text=True)
    node_names = [n.strip() for n in result.stdout.split('\n') if n.strip()]
    
    nodes_info = []
    for name in node_names:
        # Получаем PID процесса (ищем по имени процесса worker_node_X)
        # В реальном ROS2 имя процесса часто совпадает с именем ноды или скрипта
        pid_result = subprocess.run(['pgrep', '-f', name], capture_output=True, text=True)
        if pid_result.stdout.strip():
            pid = int(pid_result.stdout.strip().split()[0])
            nodes_info.append({'name': name, 'pid': pid})
            
    return nodes_info

def measure_likwid(pid):
    """Замер LIKWID для конкретного PID"""
    try:
        # Короткий замер (2 сек)
        cmd = ['likwid-perfctr', '-C', '0', '-g', 'INST', '-t', '2000', '-p', str(pid)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
        instr = 0
        for line in res.stdout.split('\n'):
            if 'INSTR_RETIRED' in line:
                val = line.split()[-1].replace(',', '.')
                instr = float(val)
                break
        
        # IPS = Instructions / 2 sec
        ips = instr / 2.0
        return ips
    except Exception as e:
        return 0.0

def measure_ros_traffic():
    """Замер трафика между нодами через ros2 topic"""
    # Получаем список топиков
    res = subprocess.run(['ros2', 'topic', 'list'], capture_output=True, text=True)
    topics = [t.strip() for t in res.stdout.split('\n') if t.strip()]
    
    flows = []
    for topic in topics:
        if topic.startswith('/data_'):
            # Парсим имя: /data_1_to_2 -> от 1 к 2
            match = re.search(r'data_(\d+)_to_(\d+)', topic)
            if match:
                src_node = f"worker_node_{match.group(1)}"
                dst_node = f"worker_node_{match.group(2)}"
                
                # Замер bandwidth (ros2 topic bw)
                # Внимание: эта команда работает несколько секунд
                bw_res = subprocess.run(['ros2', 'topic', 'bw', topic, '--window', '2'], 
                                        capture_output=True, text=True, timeout=5)
                
                bw_mbps = 0.0
                for line in bw_res.stdout.split('\n'):
                    if 'average' in line.lower():
                        # Пример: "average: 1.2 KB/s"
                        parts = line.split()
                        if len(parts) >= 2:
                            val = float(parts[1])
                            unit = parts[2]
                            if 'KB' in unit: val *= 8 / 1000 # KB/s -> Kbit/s -> Mbit/s (грубо)
                            elif 'MB' in unit: val *= 8
                            bw_mbps = val / 1000 # Перевод в Mbps
                
                if bw_mbps > 0:
                    flows.append({
                        'source_task': src_node,
                        'dest_task': dst_node,
                        'bandwidth_mbps': round(bw_mbps, 4)
                    })
    return flows

def send_report(tasks, flows):
    payload = {
        "node_id": NODE_ID,
        "timestamp": datetime.utcnow().isoformat(),
        "total_cpu_load": 0.0, # Можно добавить psutil
        "total_memory_usage_mb": 0.0,
        "num_cores": os.cpu_count(),
        "tasks": tasks,
        "network_flows": flows # Отдельное поле для flows, если collector поддерживает, или мапим в tasks
    }
    
    # Маппинг flows в adjacent_tasks внутри задач
    task_map = {t['task_id']: t for t in tasks}
    for flow in flows:
        if flow['source_task'] in task_map:
            task_map[flow['source_task']]['adjacent_tasks'].append({
                'task_id': flow['dest_task'],
                'bandwidth_mbps': flow['bandwidth_mbps'],
                'direction': 'outbound'
            })
            task_map[flow['source_task']]['network_traffic_mbps'] += flow['bandwidth_mbps']

    try:
        requests.post(COLLECTOR_URL, json=payload, timeout=5)
        print(f"✅ Отчет отправлен ({len(tasks)} задач, {len(flows)} потоков)")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

def main():
    print("🔍 ROS 2 + LIKWID Monitor запущен...")
    while True:
        ros_nodes = get_ros_nodes()
        tasks = []
        
        for node in ros_nodes:
            ips = measure_likwid(node['pid'])
            tasks.append({
                'task_id': node['name'],
                'task_name': node['name'],
                'core_id': 0,
                'cpu_load_percent': 0.0,
                'memory_usage_mb': 0.0,
                'instructions_per_sec': ips,
                'memory_bandwidth_mbps': 0.0,
                'adjacent_tasks': [],
                'network_traffic_mbps': 0.0
            })
        
        flows = measure_ros_traffic()
        
        if tasks:
            send_report(tasks, flows)
        
        time.sleep(10) # Интервал опроса

if __name__ == '__main__':
    import time
    main()