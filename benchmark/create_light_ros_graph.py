#!/usr/bin/env python3
"""Generate lightweight ROS 2 graph for profiling experiments."""

import os
import subprocess
import time
import random
import pathlib
from typing import List, Tuple, Dict

# Config - tweak these for different load scenarios
NUM_NODES = 10
MIN_EDGES = 1
MAX_EDGES = 1
TARGET_BW_MBPS = 5
BASE_MEM_MB = 5
CPU_FACTOR = 0.02  # Empirical value, adjust for desired CPU load


def generate_test_graph(
    num_nodes: int = NUM_NODES,
    min_edges: int = MIN_EDGES,
    max_edges: int = MAX_EDGES
) -> List[Tuple[int, int]]:
    """Generate topology via pyrgg or fallback to pure Python."""
    print(f"Generating {num_nodes}-node graph...")
    edges = []

    # Try pyrgg first - supports both v1 and v2 APIs (annoying but necessary)
    try:
        try:
            from pyrgg import graph_gen  # type: ignore
        except ImportError:
            from pyrgg.functions import graph_gen  # type: ignore
            
        graph_gen(
            file_name="test_graph",
            vertex_number=num_nodes,
            min_edge=min_edges, max_edge=max_edges,
            weight=(1, 10), direct=1, self_loop=0, multigraph=0
        )
        
        # Parse .gr output - format is undocumented but stable in practice
        with open("test_graph.gr", "r") as f:
            for line in f.readlines()[2:]:  # Skip header
                parts = line.strip().split()
                if len(parts) >= 2:
                    edges.append((int(parts[0]), int(parts[1])))
        print(f"Pyrgg: {len(edges)} edges")
        
    except Exception as e:
        # Fallback: ring + random edges, zero dependencies
        print(f"Pyrgg failed ({e}), using builtin generator")
        
        # Start with ring to guarantee connectivity
        for i in range(1, num_nodes):
            edges.append((i, i + 1))
        edges.append((num_nodes, 1))
        
        existing = set(edges)
        # Arbitrary limit - enough for randomization without hanging
        for _ in range(num_nodes * 20):
            u, v = random.randint(1, num_nodes), random.randint(1, num_nodes)
            if u != v and (u, v) not in existing:
                if sum(1 for e in edges if e[0] == u) < max_edges:
                    edges.append((u, v))
                    existing.add((u, v))
        print(f"Builtin: {len(edges)} edges")

    return edges


def _calculate_msg_size(target_bw_mbps: float, freq_hz: int = 50) -> int:
    # Simple back-of-envelope calc, good enough for load testing
    bytes_per_sec = (target_bw_mbps * 1024 * 1024) / 8
    return max(100, int(bytes_per_sec / freq_hz))


def _build_node_script(
    node_id: int,
    neighbors: List[int],
    msg_size: int,
    memory_mb: float,
    cpu_factor: float
) -> str:
    """Generate worker node code via string template. Ugly but effective."""
    
    # Template with placeholders - safer than f-strings for code generation
    template = '''\
#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import math

class LightWorkerNode(Node):
    def __init__(self, node_id, neighbors, msg_size, memory_mb, cpu_factor):
        super().__init__('light_worker_' + str(node_id))
        self.node_id = node_id
        self.cpu_factor = cpu_factor
        
        # Memory hog - forces RSS allocation
        self._memory_hog = bytearray(int(memory_mb * 1024 * 1024))
        
        self._payload = String()
        self._payload.data = 'X' * msg_size
        self.pubs = {}
        
        for nb in neighbors:
            topic = f"light_topic_{node_id}_to_{nb}"
            pub = self.create_publisher(String, topic, 10)
            self.pubs[nb] = pub
            # Lambda captures neighbor via default arg - classic Python trick
            self.create_timer(0.2, lambda n=nb: self._tick(n))
        
        self.get_logger().info(f"Node {node_id} up (mem={memory_mb}MB, out={len(neighbors)})")

    def _tick(self, neighbor_id: int):
        try:
            self.pubs[neighbor_id].publish(self._payload)
        except Exception:
            pass  # Ignore publish errors - we're stress-testing, not production

    def _compute(self):
        # Crude CPU load simulation - empirical factor, not scientifically accurate
        limit = int(5000 * self.cpu_factor)
        for i in range(limit):
            _ = math.sin(i)

def main():
    rclpy.init()
    node = LightWorkerNode(__NODE_ID__, __NEIGHBORS__, __MSG_SIZE__, __MEMORY_MB__, __CPU_FACTOR__)
    
    try:
        while rclpy.ok():
            node._compute()
            rclpy.spin_once(node, timeout_sec=0.01)
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
'''
    
    # String replacement - not elegant but avoids template engine dependency
    # TODO: switch to Jinja2 if we need more complex templating
    return (template
        .replace('__NODE_ID__', str(node_id))
        .replace('__NEIGHBORS__', repr(neighbors))
        .replace('__MSG_SIZE__', str(msg_size))
        .replace('__MEMORY_MB__', str(memory_mb))
        .replace('__CPU_FACTOR__', str(cpu_factor))
    )


def _find_ros_setup() -> str:
    """Probe common ROS 2 install paths. Brittle but works on standard setups."""
    for distro in ['jazzy', 'humble', 'iron', 'rolling']:
        setup_path = f"/opt/ros/{distro}/setup.bash"
        if pathlib.Path(setup_path).exists():
            print(f"Found ROS 2: {distro}")
            return setup_path
    raise RuntimeError(
        "ROS 2 not found. Install Humble/Jazzy: "
        "https://docs.ros.org/en/jazzy/Installation.html"
    )


def launch_system():
    """Generate graph, create node scripts, launch processes."""
    
    edges = generate_test_graph()
    
    # Build adjacency list
    adjacency: Dict[int, List[int]] = {i: [] for i in range(1, NUM_NODES + 1)}
    for src, dst in edges:
        adjacency[src].append(dst)
    
    # Split target BW across edges - naive but sufficient for testing
    bw_per_edge = TARGET_BW_MBPS / len(edges) if edges else 1.0
    msg_size = _calculate_msg_size(bw_per_edge)
    
    # Detect ROS once upfront
    ros_setup = _find_ros_setup()
    
    processes = []
    print(f"Launching {NUM_NODES} nodes...")
    
    for node_id, neighbors in adjacency.items():
        mem_load = BASE_MEM_MB + random.randint(0, 10)  # Add noise
        
        script = _build_node_script(node_id, neighbors, msg_size, mem_load, CPU_FACTOR)
        filename = f"light_node_{node_id}.py"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(filename, 0o755)
        
        # Launch with ROS env - shell=True is ugly but necessary for sourcing setup.bash
        cmd = f"bash -c 'source {ros_setup} && python3 {filename}'"
        proc = subprocess.Popen(cmd, shell=True, start_new_session=True)
        processes.append((node_id, proc))
        print(f"  Node {node_id} started (PID {proc.pid})")
        time.sleep(0.1)  # Avoid log spam from concurrent startups
    
    print(f"\nLaunched: {NUM_NODES} nodes, {len(edges)} edges")
    print("Verify: ros2 node list | grep light_worker")
    print("Stop: Ctrl+C\n")
    
    # Wait for all nodes
    try:
        for _, proc in processes:
            proc.wait()
    except KeyboardInterrupt:
        print("\nStopping...")
        for _, proc in processes:
            proc.terminate()
        # Kill stragglers - pkill is blunt but effective
        subprocess.run(['pkill', '-f', 'light_node_\\d+\\.py'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Done.")


if __name__ == "__main__":
    launch_system()
