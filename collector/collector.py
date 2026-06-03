#!/usr/bin/env python3
"""Flask collector for profiling metrics - receives from agents, serves reports."""

from flask import Flask, request, jsonify
from datetime import datetime, timezone
import logging
import threading
import os
import sys

# Logging: file + console, append mode so we don't lose history
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/collector.log', mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Config with fallback - agent should work even if config.py is missing
try:
    from config import config
except ImportError:
    class DummyConfig:
        REPORT_FILTER_PATTERN = ''
    config = DummyConfig()

# In-memory storage - thread-safe via lock
# TODO: consider Redis for multi-node collector deployment
_nodes = {}
_nodes_lock = threading.Lock()


@app.route('/health')
def health():
    with _nodes_lock:
        count = len(_nodes)
    return jsonify({
        'status': 'healthy',
        'nodes_registered': count,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'version': '1.1.0'
    })


@app.route('/metrics', methods=['POST'])
def receive_metrics():
    try:
        # force=True: agents sometimes send text/plain, Flask is flexible
        data = request.get_json(force=True, silent=False)
        if not data or 'node_id' not in data:
            logger.warning("Bad payload from agent")
            return jsonify({'error': 'Invalid payload'}), 400
        
        node_id = data['node_id']
        tasks = data.get('tasks', [])
        logger.info(f"Got {len(tasks)} tasks from {node_id}")
        
        # Atomic update under lock - simple but works for single-collector setup
        with _nodes_lock:
            _nodes[node_id] = {
                'node_id': node_id,
                'last_update': datetime.now(timezone.utc).isoformat(),
                'tasks': tasks,  # Store as-is, aggregator will process later
                'total_cpu_load': data.get('total_cpu_load', 0),
                'total_memory_usage_mb': data.get('total_memory_usage_mb', 0),
                'num_cores': data.get('num_cores', 0),
                'num_active_tasks': data.get('num_active_tasks', 0)
            }
        
        return jsonify({'status': 'ok', 'node_id': node_id}), 200
        
    except Exception as e:
        # Log full traceback for debugging, but don't expose internals to client
        logger.error(f"Metrics error: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Internal error'}), 500


@app.route('/report')
def get_report():
    try:
        # Filter via query param or config fallback
        filter_pat = request.args.get('filter', '').strip()
        if not filter_pat:
            filter_pat = getattr(config, 'REPORT_FILTER_PATTERN', '').strip()
        
        with _nodes_lock:
            result = []
            for nid, ndata in _nodes.items():
                tasks = ndata.get('tasks', [])
                
                # Simple substring filter - not regex, but good enough for now
                # TODO: add proper regex support if needed
                if filter_pat:
                    tasks = [t for t in tasks if filter_pat in t.get('task_name', '')]
                
                result.append({
                    'node_id': ndata['node_id'],
                    'last_update': ndata['last_update'],
                    'tasks': tasks,
                    'total_cpu_load': ndata['total_cpu_load'],
                    'total_memory_usage_mb': ndata['total_memory_usage_mb'],
                    'num_cores': ndata['num_cores'],
                    'num_active_tasks': len(tasks)  # Recalculate after filter
                })
        
        return jsonify({
            'nodes': result,
            'total_nodes': len(result),
            'report_type': 'system_profiling',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
    except Exception as e:
        logger.error(f"Report error: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Internal error'}), 500


@app.route('/nodes')
def list_nodes():
    """Quick endpoint to see which nodes are registered"""
    with _nodes_lock:
        ids = list(_nodes.keys())
    return jsonify({'nodes': ids, 'count': len(ids), 'timestamp': datetime.now(timezone.utc).isoformat()})


if __name__ == '__main__':
    logger.info("Collector starting on 127.0.0.1:8080")
    # threaded=True: handle multiple agents concurrently
    # debug=False: don't use in production, Flask reloader breaks with threads
    app.run(host='127.0.0.1', port=8080, debug=False, threaded=True)
