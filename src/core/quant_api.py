#!/usr/bin/env python3
import os, zmq, json, time, logging, subprocess
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format='%(asctime)s [API] %(levelname)s %(message)s')
log = logging.getLogger(__name__)
app = Flask(__name__)
CORS(app)

ctx = zmq.Context()
push = ctx.socket(zmq.PUSH)
push.connect("tcp://127.0.0.1:5556")
signal_log = []

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat(), 'node': '192.168.0.18'})

@app.route('/signal', methods=['POST'])
def inject_signal():
    data = request.get_json()
    required = ['ticker', 'score', 'rvol', 'price', 'vwap', 'macd']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({'error': f'缺少字段: {missing}'}), 400
    data['injected_at'] = datetime.now().isoformat()
    data['source'] = 'api'
    push.send_json(data)
    signal_log.append(data)
    log.info(f"Injected signal: {data['ticker']}")
    return jsonify({'status': 'sent', 'ticker': data['ticker']})

@app.route('/signals', methods=['GET'])
def get_signals():
    return jsonify(signal_log[-50:])

@app.route('/nodes', methods=['GET'])
def get_nodes():
    nodes = {'main': '192.168.0.18', 'executor': '192.168.0.11',
             'compute': '192.168.0.143', 'vision': '192.168.0.15',
             'sentry': '192.168.0.101', 'courier': '192.168.0.102'}
    status = {}
    for name, ip in nodes.items():
        r = subprocess.run(['ping', '-c1', '-W1', ip], capture_output=True)
        status[name] = {'ip': ip, 'reachable': r.returncode == 0}
    return jsonify(status)

@app.route('/dispatcher/status', methods=['GET'])
def dispatcher_status():
    r = subprocess.run(['systemctl', 'is-active', 'quant-dispatcher'], capture_output=True, text=True)
    return jsonify({'status': r.stdout.strip()})

# ── Grafana SimpleJSON ──────────────────────────────────────
@app.route('/grafana', methods=['GET'])
def grafana_health():
    return 'OK', 200

@app.route('/grafana/search', methods=['POST'])
def grafana_search():
    return jsonify(['dispatcher_status', 'node_main', 'node_executor',
                    'node_compute', 'node_vision', 'node_sentry', 'node_courier', 'api_status'])

@app.route('/grafana/query', methods=['POST'])
def grafana_query():
    req = request.get_json()
    results = []
    now_ms = int(time.time() * 1000)
    for target in req.get('targets', []):
        t = target.get('target', '')
        if t == 'dispatcher_status':
            r = subprocess.run(['systemctl', 'is-active', 'quant-dispatcher'], capture_output=True, text=True)
            val = 1 if r.stdout.strip() == 'active' else 0
            results.append({'target': 'dispatcher', 'datapoints': [[val, now_ms]]})
        elif t == 'api_status':
            results.append({'target': 'api', 'datapoints': [[1, now_ms]]})
        elif t.startswith('node_'):
            node = t.replace('node_', '')
            nodes = {'main': '192.168.0.18', 'executor': '192.168.0.11',
                     'compute': '192.168.0.143', 'vision': '192.168.0.15',
                     'sentry': '192.168.0.101', 'courier': '192.168.0.102'}
            ip = nodes.get(node, '')
            r = subprocess.run(['ping', '-c1', '-W1', ip], capture_output=True)
            val = 1 if r.returncode == 0 else 0
            results.append({'target': node, 'datapoints': [[val, now_ms]]})
    return jsonify(results)

@app.route('/grafana/annotations', methods=['POST'])
def grafana_annotations():
    return jsonify([])


@app.route('/dashboard', methods=['GET'])
def dashboard():
    from flask import send_file
    import os
    path = os.path.join(os.path.dirname(__file__), 'dashboard.html')
    return send_file(path)

if __name__ == '__main__':
    log.info("QuantForce API starting on port 5800")
    app.run(host='0.0.0.0', port=5800, debug=False)
# 临时插入位置检查
