#!/usr/bin/env python3
# create_heavy_ros_graph.py

import os
import subprocess
import random
import math
from pyrgg import graph_gen
import time

# === НАСТРОЙКИ ГРАФА ===
NUM_NODES = 150
MIN_EDGES_PER_NODE = 4
MAX_EDGES_PER_NODE = 10
TARGET_TOTAL_BANDWIDTH_MBPS = 6000  # Цель: 6000 Мбит/с
BASE_MEMORY_MB = 50                 # Базовая память ноды
MAX_EXTRA_MEMORY_MB = 200           # Доп. память для вариативности
CPU_LOAD_FACTOR = 1.0               # Коэффициент нагрузки CPU (подбирается экспериментально)

def generate_scaled_graph():
    """Генерация графа с контролем количества ребер"""
    print(f"🎲 Генерация графа: {NUM_NODES} узлов...")
    
    # Пытаемся сгенерировать граф, пока не получим нужное кол-во ребер
    edges = []
    attempts = 0
    while len(edges) < 500 or attempts > 10:
        file_name = "benchmark_graph"
        # Случайный разброс степени вершины для получения 500-1000 ребер
        avg_degree = random.randint(MIN_EDGES_PER_NODE, MAX_EDGES_PER_NODE)
        
        graph_gen(
            file_name=file_name,
            nodes=NUM_NODES,
            min_edge=1,
            max_edge=avg_degree, 
            weight=False,
            direct=True,
            self_loop=False,
            multigraph=False,
            output_format="gr"
        )
        
        edges = []
        with open(f"{file_name}.gr", "r") as f:
            lines = f.readlines()
            for line in lines[2:]:
                parts = line.strip().split()
                if len(parts) >= 2:
                    u, v = int(parts[0]), int(parts[1])
                    edges.append((u, v))
        attempts += 1

    print(f"✅ Сгенерировано {len(edges)} связей (попыток: {attempts}).")
    return edges

def calculate_bandwidth_per_edge(total_edges, target_mbps):
    """Расчет целевой пропускной способности на одно ребро"""
    # Добавляем случайный разброс ±20%
    base_bw = target_mbps / total_edges
    return base_bw

def create_node_script(node_id, neighbors, target_bw_mbps, memory_mb):
    """Создает скрипт ноды с конкретной нагрузкой по памяти и сети"""
    
    # Расчет параметров для цикла (CPU) и размера сообщения (Network)
    # Чтобы получить X Мбит/с, нужно слать Y байт каждые Z секунд
    # Допустим, частота публикации 10 Гц (каждые 0.1 сек)
    freq_hz = 10.0
    bytes_per_sec = (target_bw_mbps * 1024 * 1024) / 8
    msg_size_bytes = int(bytes_per_sec / freq_hz)
    
    # Ограничим минимальный размер сообщения, чтобы не слать пустоту
    if msg_size_bytes < 100:
        msg_size_bytes = 100
        # Если трафик маленький, можно снизить частоту, но для простоты оставим так
    
    # Создаем "мусорные" данные нужного размера
    # В реальном коде лучше генерировать один раз и переиспользовать буфер
    fake_data_var_name = f"data_buffer_{node_id}"
    
    script_content = f'''#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import ByteMultiArray, String
import time
import random
import sys

class HeavyWorkerNode(Node):
    def __init__(self, node_id, neighbors, msg_size, memory_mb):
        super().__init__('worker_{{node_id}}')
        self.node_id = node_id
        
        # 1. АЛОКАЦИЯ ПАМЯТИ (Fake Memory Load)
        # Создаем список байтов, занимающий ~memory_mb
        self.memory_hog = bytearray(int(memory_mb * 1024 * 1024))
        self.get_logger().info(f"Node {{node_id}} allocated {{memory_mb}} MB RAM")
        
        # 2. ПОДГОТОВКА СЕТИ
        self.pubs = {{}}
        # Буфер данных нужного размера (чтобы не аллоцировать каждый раз)
        self.fake_payload = ByteMultiArray()
        self.fake_payload.data = [random.randint(0, 255) for _ in range(msg_size)]
        
        for neighbor in neighbors:
            topic_name = f"topic_{{node_id}}_to_{{neighbor}}"
            # QoS для надежности при высокой нагрузке
            from rclpy.qos import QoSProfile, ReliabilityPolicy
            qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
            
            pub = self.create_publisher(ByteMultiArray, topic_name, qos)
            self.pubs[neighbor] = pub
            # Таймер на публикацию (10 Гц)
            self.create_timer(0.1, lambda n=neighbor: self.publish_tick(n))
        
        self.get_logger().info(f"Node {{node_id}} started. Neighbors: {{len(neighbors)}}, MsgSize: {{msg_size}}B")

    def publish_tick(self, neighbor_id):
        try:
            self.pubs[neighbor_id].publish(self.fake_payload)
        except Exception as e:
            pass # Игнорируем ошибки очереди DDS при перегрузке

    def fake_compute(self):
        # 3. ФЕЙКОВАЯ CPU НАГРУЗКА
        # Простые вычисления с плавающей точкой
        x = 0.0
        # Количество итераций подбирается экспериментально для загрузки 1 ядра
        limit = int(50000 * {CPU_LOAD_FACTOR}) 
        for i in range(limit):
            x += math.sin(i) * 0.001

def main(args=None):
    rclpy.init(args=args)
    neighbors = {neighbors}
    msg_size = {msg_size_bytes}
    mem_mb = {memory_mb}
    
    node = HeavyWorkerNode({node_id}, neighbors, msg_size, mem_mb)
    
    while rclpy.ok():
        node.fake_compute()
        rclpy.spin_once(node, timeout_sec=0.01)
    
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    import math
    main()
'''
    
    filename = f"node_{node_id}.py"
    with open(filename, "w") as f:
        f.write(script_content)
    os.chmod(filename, 0o755)
    return filename

def launch_system():
    edges = generate_scaled_graph()
    
    # Группировка связей
    adjacency = {i: [] for i in range(1, NUM_NODES + 1)}
    for u, v in edges:
        adjacency[u].append(v)
    
    # Расчет пропускной способности на ребро
    bw_per_edge = calculate_bandwidth_per_edge(len(edges), TARGET_TOTAL_BANDWIDTH_MBPS)
    
    processes = []
    print(f"🚀 Запуск {NUM_NODES} нод с нагрузкой...")
    print(f"   Целевой трафик: ~{TARGET_TOTAL_BANDWIDTH_MBPS} Мбит/с")
    print(f"   Трафик на ребро: ~{bw_per_edge:.2f} Мбит/с")
    
    for node_id, neighbors in adjacency.items():
        # Случайная память для разнообразия (от 50 до 250 МБ)
        mem_load = BASE_MEMORY_MB + random.randint(0, MAX_EXTRA_MEMORY_MB)
        
        # Если у ноды много исходящих, делим трафик между ними, чтобы сумма была целевой
        # Или считаем, что bw_per_edge - это трафик ОДНОГО ребра. 
        # Тогда общий трафик = кол-во ребер * bw_per_edge.
        # В данной логике мы задаем размер сообщения исходя из bw_per_edge.
        
        script = create_node_script(node_id, neighbors, bw_per_edge, mem_load)
        
        # Запуск
        cmd = f"bash -c 'source /opt/ros/humble/setup.bash && python3 {script}'"
        # start_new_session=True важно, чтобы процесс жил отдельно
        proc = subprocess.Popen(cmd, shell=True, start_new_session=True)
        processes.append((node_id, proc))
        
        if node_id % 20 == 0:
            print(f"   ... запущено {node_id} нод")
        time.sleep(0.1) # Небольшая задержка, чтобы не спамить DDS при старте
    
    print(f"✅ ВСЕ НОДЫ ЗАПУЩЕНЫ! ({len(processes)})")
    print("💡 Теперь запустите ros_likwid_agent.py в другом окне.")
    print("Нажмите Ctrl+C здесь для остановки всех нод.")
    
    try:
        for _, proc in processes:
            proc.wait()
    except KeyboardInterrupt:
        print("\n🛑 Остановка системы...")
        for node_id, proc in processes:
            try:
                proc.terminate()
            except:
                pass
        # Убиваем остатки
        subprocess.run(['pkill', '-f', 'node_\\d+\\.py'])
        print("Система остановлена.")

if __name__ == "__main__":
    launch_system()