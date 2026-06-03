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
    node = LightWorkerNode(3, [4], 1310, 9, 0.02)
    
    try:
        while rclpy.ok():
            node._compute()
            rclpy.spin_once(node, timeout_sec=0.01)
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
