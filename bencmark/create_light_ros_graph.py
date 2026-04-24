#!/usr/bin/env python3
# benchmark/create_light_ros_graph.py
# Легкая версия генератора для проверки работоспособности системы

import os
import subprocess
import random
import time
from pyrgg import graph_gen

# === НАСТРОЙКИ ДЛЯ ТЕСТА (ЛЕГКАЯ НАГРУЗКА) ===
NUM_NODES = 5             # Всего 5 нод (вместо 150)
MIN_EDGES_PER_NODE = 1    # Минимум 1 связь
MAX_EDGES_PER_NODE = 2    # Максимум 2 связи
TARGET_BANDWIDTH_MBPS = 10 # Низкий трафик (10 Мбит/с суммарно)
BASE_MEMORY_MB = 20       # Мало памяти (20 МБ на ноду)
CPU_LOAD_FACTOR = 0.05    # Очень легкая нагрузка на CPU (чтобы не греть ноутбук)

def generate_test_graph():
    """Генерация маленького графа"""
    print(f"🎲 Генерация ТЕСТОВОГО графа: {NUM_NODES} узлов...")
    
    edges = []
    # Генерируем простой граф
    graph_gen(
        file_name="test_graph",
        nodes=NUM_NODES,
        min_edge=MIN_EDGES_PER_NODE,
        max_edge=MAX_EDGES_PER_NODE, 
        weight=False,
        direct=True,
        self_loop=False,
        multigraph=False,
        output_format="gr"
    )
    
    with open("test_graph.gr", "r") as f:
        lines = f.readlines()
        for line in lines[2:]:
            parts = line.strip().split()
            if len(parts) >= 2:
                u, v = int(parts[0]), int(parts[1])
                edges.append((u, v))
                
    print(f"✅ Сгенерировано {len(edges)} связей.")
    return edges

def create_node_script(node_id, neighbors, target_bw_mbps, memory_mb):
    """Создает скрипт ноды (аналогичный тяжелому, но с другими константами)"""
    
    freq_hz = 5.0  # Меньшая частота публикации (5 Гц)
    bytes_per_sec = (target_bw_mbps * 1024 * 1024) / 8
    msg_size_bytes = int(bytes_per_sec / freq_hz)
    
    # Минимальный размер сообщения 100 байт
    if msg_size_bytes < 100:
        msg_size_bytes = 100
        
    script_content = f'''#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import ByteMultiArray
import time
import random
import math

class LightWorkerNode(Node):
    def __init__(self, node_id, neighbors, msg_size, memory_mb):
        super().__init__('light_worker_{{node_id}}')
        self.node_id = node_id
        
        # Алокация памяти (меньше чем в тяжелой версии)
        self.memory_hog = bytearray(int(memory_mb * 1024 * 1024))
        
        # Подготовка данных
        self.pubs = {{}}
        self.fake_payload = ByteMultiArray()
        self.fake_payload.data = [random.randint(0, 255) for _ in range(msg_size)]
        
        for neighbor in neighbors:
            topic_name = f"light_topic_{{node_id}}_to_{{neighbor}}"
            pub = self.create_publisher(ByteMultiArray, topic_name, 10)
            self.pubs[neighbor] = pub
            self.create_timer(1.0/freq_hz, lambda n=neighbor: self.publish_tick(n))
            
        self.get_logger().info(f"Light Node {{node_id}} started. Mem: {{memory_mb}}MB")

    def publish_tick(self, neighbor_id):
        try:
            self.pubs[neighbor_id].publish(self.fake_payload)
        except Exception:
            pass

    def fake_compute(self):
        # Очень легкая нагрузка
        x = 0.0
        limit = int(5000 * {CPU_LOAD_FACTOR}) 
        for i in range(limit):
            x += math.sin(i) * 0.001

def main(args=None):
    rclpy.init(args=args)
    neighbors = {neighbors}
    msg_size = {msg_size_bytes}
    mem_mb = {memory_mb}
    
    node = LightWorkerNode({node_id}, neighbors, msg_size, mem_mb)
    
    while rclpy.ok():
        node.fake_compute()
        rclpy.spin_once(node, timeout_sec=0.01)
    
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    import math
    main()
'''
    
    filename = f"light_node_{node_id}.py"
    with open(filename, "w") as f:
        f.write(script_content)
    os.chmod(filename, 0o755)
    return filename

def launch_system():
    edges = generate_test_graph()
    
    adjacency = {i: [] for i in range(1, NUM_NODES + 1)}
    for u, v in edges:
        adjacency[u].append(v)
    
    bw_per_edge = TARGET_BANDWIDTH_MBPS / len(edges) if edges else 1
    
    processes = []
    print(f"🚀 Запуск ЛЕГКОЙ системы ({NUM_NODES} нод)...")
    
    for node_id, neighbors in adjacency.items():
        mem_load = BASE_MEMORY_MB + random.randint(0, 10)
        script = create_node_script(node_id, neighbors, bw_per_edge, mem_load)
        
        cmd = f"bash -c 'source /opt/ros/humble/setup.bash && python3 {script}'"
        proc = subprocess.Popen(cmd, shell=True, start_new_session=True)
        processes.append((node_id, proc))
        print(f"   Запущена легкая нода {node_id} (PID: {proc.pid})")
        time.sleep(0.5) # Пауза между стартом нод
    
    print(f"✅ ЛЕГКАЯ СИСТЕМА ЗАПУЩЕНА!")
    print("💡 Проверьте работу командой: ros2 node list")
    print("Нажмите Ctrl+C для остановки.")
    
    try:
        for _, proc in processes:
            proc.wait()
    except KeyboardInterrupt:
        print("\n🛑 Остановка легкой системы...")
        for node_id, proc in processes:
            proc.terminate()
        subprocess.run(['pkill', '-f', 'light_node_\\d+\\.py'])
        print("Система остановлена.")

if __name__ == "__main__":
    launch_system()