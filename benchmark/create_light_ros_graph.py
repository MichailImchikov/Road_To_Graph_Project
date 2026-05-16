#!/usr/bin/env python3
# benchmark/create_light_ros_graph.py
# Пуленепробиваемый генератор (pyrgg + встроенный fallback для 5..150+ нод)

import os
import subprocess
import time
import random

# === НАСТРОЙКИ ===
NUM_NODES = 5             # Поменяй на 150 для продакшена
MIN_EDGES = 1    
MAX_EDGES = 2    
TARGET_BW_MBPS = 50 
BASE_MEM_MB = 20       
CPU_FACTOR = 0.05    

def generate_test_graph(num_nodes=NUM_NODES, min_edges=MIN_EDGES, max_edges=MAX_EDGES):
    """Генерация графа: pyrgg -> fallback (чистый Python)"""
    print(f" Генерация графа: {num_nodes} узлов...")
    edges = []

    # 1️⃣ Попытка использовать pyrgg (поддержка v1.x и v2.x)
    try:
        try:
            from pyrgg import graph_gen  # v1.x
        except ImportError:
            from pyrgg.functions import graph_gen  # v2.x
            
        graph_gen(
            file_name="test_graph",
            vertex_number=num_nodes,
            min_edge=min_edges, max_edge=max_edges,
            weight=(1, 10), direct=1, self_loop=0, multigraph=0
        )
        
        with open("test_graph.gr", "r") as f:
            for line in f.readlines()[2:]:  # Пропускаем заголовок
                parts = line.strip().split()
                if len(parts) >= 2:
                    edges.append((int(parts[0]), int(parts[1])))
                    
        print(f"✅ Pyrgg сгенерировал {len(edges)} связей.")
        
    except Exception as e:
        print(f"⚠️ Pyrgg недоступен ({e}). Использую встроенный генератор.")
        
        # 2️⃣ Встроенный генератор (работает для 5 и 150 нод, 0 зависимостей)
        # Гарантируем связность: базовый цикл 1->2->...->N->1
        for i in range(1, num_nodes):
            edges.append((i, i+1))
        edges.append((num_nodes, 1))
        
        # Добавляем случайные ребра до лимита max_edges на узел
        existing = set(edges)
        max_attempts = num_nodes * 20  # Защита от зависания
        attempts = 0
        
        while attempts < max_attempts:
            u = random.randint(1, num_nodes)
            v = random.randint(1, num_nodes)
            
            if u != v and (u, v) not in existing:
                # Проверяем лимит исходящих рёбер
                out_degree = sum(1 for e in edges if e[0] == u)
                if out_degree < max_edges:
                    edges.append((u, v))
                    existing.add((u, v))
            attempts += 1
            
        print(f"✅ Встроенный генератор создал {len(edges)} связей.")

    return edges

def create_node_script(node_id, neighbors, target_bw_mbps, memory_mb):
    """Генерация скрипта ноды через безопасный шаблон"""
    
    freq_hz = 50
    bytes_per_sec = (target_bw_mbps * 1024 * 1024) / 8
    msg_size = max(100, int(bytes_per_sec / freq_hz))
    
    # Шаблон БЕЗ f-строк. Маркеры __VAR__ заменяются через .replace()
    template = '''#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String  # ✅ Стабильный тип, никаких AssertionErrors
import math

class LightWorkerNode(Node):
    def __init__(self):
        name = 'light_worker_' + str(__NODE_ID__)
        super().__init__(name)
        self.node_id = __NODE_ID__
        
        # Алокация памяти (нагрузка на RAM)
        self.memory_hog = bytearray(int(__MEMORY_MB__ * 1024 * 1024))
        
        self.pubs = {}
        self.payload = String()
        self.payload.data = 'X' * __MSG_SIZE__
        
        for n in __NEIGHBORS__:
            # ✅ Простое сложение строк (ROS 2 не любит фигурные скобки в топиках)
            topic = "light_topic_" + str(self.node_id) + "_to_" + str(n)
            pub = self.create_publisher(String, topic, 10)
            self.pubs[n] = pub
            self.create_timer(0.2, lambda nb=n: self.tick(nb))
            
        self.get_logger().info("Node " + str(self.node_id) + " started. Mem: " + str(__MEMORY_MB__) + "MB")

    def tick(self, neighbor_id):
        try:
            self.pubs[neighbor_id].publish(self.payload)
        except Exception:
            pass

    def compute(self):
        # Нагрузка на CPU
        limit = int(5000 * __CPU_FACTOR__)
        for i in range(limit):
            math.sin(i)

def main():
    rclpy.init()
    node = LightWorkerNode()
    
    try:
        while rclpy.ok():
            node.compute()
            rclpy.spin_once(node, timeout_sec=0.01)
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
'''
    
    # Безопасная подстановка
    script_content = template.replace('__NODE_ID__', str(node_id))
    script_content = script_content.replace('__NEIGHBORS__', str(neighbors))
    script_content = script_content.replace('__MSG_SIZE__', str(msg_size))
    script_content = script_content.replace('__MEMORY_MB__', str(memory_mb))
    script_content = script_content.replace('__CPU_FACTOR__', str(CPU_FACTOR))
        
    filename = f"light_node_{node_id}.py"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(script_content)
    os.chmod(filename, 0o755)
    return filename

def launch_system():
    edges = generate_test_graph()
    
    adjacency = {i: [] for i in range(1, NUM_NODES + 1)}
    for u, v in edges:
        adjacency[u].append(v)
    
    bw_per_edge = TARGET_BW_MBPS / len(edges) if edges else 1
    
    processes = []
    print(f" Запуск {NUM_NODES} нод...")
    
    for node_id, neighbors in adjacency.items():
        mem_load = BASE_MEM_MB + random.randint(0, 10)
        script = create_node_script(node_id, neighbors, bw_per_edge, mem_load)
        
        cmd = f"bash -c 'source /opt/ros/humble/setup.bash && python3 {script}'"
        proc = subprocess.Popen(cmd, shell=True, start_new_session=True)
        processes.append((node_id, proc))
        print(f"   ✅ Нода {node_id} запущена (PID: {proc.pid})")
        time.sleep(0.5)
    
    print(f"\n✅ СИСТЕМА ЗАПУЩЕНА!")
    print("💡 Проверьте: ros2 node list")
    print("Нажмите Ctrl+C для остановки.\n")
    
    try:
        for _, proc in processes:
            proc.wait()
    except KeyboardInterrupt:
        print("\n🛑 Остановка системы...")
        for _, proc in processes:
            proc.terminate()
        subprocess.run(['pkill', '-f', 'light_node_\\d+\\.py'], stdout=subprocess.DEVNULL)
        print("Готово.")

if __name__ == "__main__":
    launch_system()