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
    limit = request.args.get('limit', 50, type=int)
    try:
        con = _sqlite3.connect(DB_PATH)
        con.row_factory = _sqlite3.Row
        rows = con.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        con.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/nodes', methods=['GET'])
def get_nodes():
    nodes = {'main': '192.168.0.18', 'executor': '192.168.0.11',
             'compute': '192.168.0.143', 
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
                    'node_compute', 'node_sentry', 'node_courier', 'api_status'])

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
                     'compute': '192.168.0.143', 
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


@app.route('/nodes/list', methods=['GET'])
def get_nodes_list():
    nodes = {'main': '192.168.0.18', 'executor': '192.168.0.11',
             'compute': '192.168.0.143', 
             'sentry': '192.168.0.101', 'courier': '192.168.0.102'}
    result = []
    for name, ip in nodes.items():
        r = subprocess.run(['ping', '-c1', '-W1', ip], capture_output=True)
        result.append({'node': name, 'ip': ip, 'reachable': 1 if r.returncode == 0 else 0})
    return jsonify(result)

@app.route('/dispatcher/stat', methods=['GET'])
def dispatcher_stat():
    r = subprocess.run(['systemctl', 'is-active', 'quant-dispatcher'], capture_output=True, text=True)
    val = 1 if r.stdout.strip() == 'active' else 0
    return jsonify([{'service': 'dispatcher', 'status': val}])


@app.route('/nodes/metrics', methods=['GET'])
def get_nodes_metrics():
    import urllib.request, re
    nodes = {
        'main':     ('192.168.0.18',  'metrics'),
        'executor': ('192.168.0.11',  'metrics'),
        'compute':  ('192.168.0.143', 'stats'),
        
        'sentry':   ('192.168.0.101', 'metrics'),
        'courier':  ('192.168.0.102', 'stats'),
    }
    result = []
    for name, (ip, mode) in nodes.items():
        try:
            with urllib.request.urlopen(f'http://{ip}:9100/{mode}', timeout=2) as r:
                raw = r.read()
            if mode == 'stats':
                data = json.loads(raw)
                cpu, mem = data['cpu'], data['mem']
            else:
                text = raw.decode()
                idle_vals = re.findall(r'node_cpu_seconds_total\{[^}]*mode="idle"[^}]*\}\s+([\d.e+]+)', text)
                all_vals  = re.findall(r'node_cpu_seconds_total\{[^}]*\}\s+([\d.e+]+)', text)
                idle = sum(float(x) for x in idle_vals)
                total = sum(float(x) for x in all_vals)
                cpu = round((1 - idle/total)*100, 1) if total else 0
                mem_total = float(re.search(r'node_memory_MemTotal_bytes\s+([\d.]+)', text).group(1))
                mem_avail = float(re.search(r'node_memory_MemAvailable_bytes\s+([\d.]+)', text).group(1))
                mem = round((1 - mem_avail/mem_total)*100, 1)
            result.append({'node': name, 'ip': ip, 'cpu': cpu, 'mem': mem})
        except Exception as e:
            result.append({'node': name, 'ip': ip, 'cpu': -1, 'mem': -1})
    return jsonify(result)


import sqlite3 as _sqlite3
DB_PATH = '/home/heng/QuantForce_Labs/data/signals.db'


@app.route('/signals/stat')
def signals_stat():
    try:
        con = _sqlite3.connect(DB_PATH)
        total  = con.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        passed = con.execute("SELECT COUNT(*) FROM signals WHERE result='PASS'").fetchone()[0]
        failed = con.execute("SELECT COUNT(*) FROM signals WHERE result='FAIL'").fetchone()[0]
        recent = con.execute(
            "SELECT ticker,result,ts FROM signals ORDER BY id DESC LIMIT 5"
        ).fetchall()
        con.close()
        pass_rate = round(passed/total*100,1) if total else 0
        return jsonify([
            {'metric': '总信号', 'value': total},
            {'metric': '通过',   'value': passed},
            {'metric': '过滤',   'value': failed},
            {'metric': '通过率%','value': pass_rate},
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

SERVICES = {
    'dispatcher':   '192.168.0.18',
    'ib-executor':  '192.168.0.11',
    'news-scanner': '192.168.0.143',
    'courier':      '192.168.0.102',
}

@app.route('/services/status')
def services_status():
    import urllib.request as _ur
    result = []
    # dispatcher — 本机检查进程
    import subprocess as _sp
    r = _sp.run(['pgrep','-f','signal_fusion.py'], capture_output=True)
    result.append({'service':'dispatcher 信号调度', 'host':'192.168.0.18',
                   'status':'UP' if r.returncode==0 else 'DOWN'})
    import socket as _sock
    for svc, host, port in [
        ('ib-executor 交易执行',  '192.168.0.11',  5558),
        ('news-scanner 新闻扫描', '192.168.0.143', 9100),
        ('compute 计算节点',      '192.168.0.143', 9100),
        ('sentry 哨兵节点',       '192.168.0.101', 9100),
        ('courier 信使节点',      '192.168.0.102', 9100),
        ('quant-api 数据接口',    '192.168.0.18',  5800),
    ]:
        try:
            s = _sock.create_connection((host, port), timeout=2)
            s.close()
            status = 'UP'
        except:
            status = 'DOWN'
        result.append({'service': svc, 'host': host, 'status': status})
    return jsonify(result)


@app.route('/signals/recent')
def signals_recent():
    try:
        con = _sqlite3.connect(DB_PATH)
        con.row_factory = _sqlite3.Row
        rows = con.execute(
            "SELECT id, substr(ts,1,19) as ts, ticker, result, score, rvol, price, COALESCE(llm_note,'-') as llm_note FROM signals ORDER BY id DESC LIMIT 20"
        ).fetchall()
        con.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/nodes/combined')
def nodes_combined():
    # 直接复用 nodes/metrics 逻辑
    with app.test_client() as c:
        resp = c.get('/nodes/metrics')
        return jsonify(resp.get_json())

    log.info("QuantForce API starting on port 5800")
# ── 交易监控端点 ──
TRADES_DB_PATH = '/home/heng/trading_system/data/trades.db'
TRADES_DB_REMOTE = '192.168.0.11'

def _fetch_trades_db():
    """从 .11 同步 trades.db 到本地临时目录"""
    import subprocess, os
    local = '/tmp/trades_mirror.db'
    result = subprocess.run(
        ['rsync', '-az', f'heng@{TRADES_DB_REMOTE}:/home/heng/trading_system/data/trades.db', local],
        capture_output=True, timeout=5
    )
    return local if os.path.exists(local) else None

@app.route('/trades/recent')
def trades_recent():
    try:
        db = _fetch_trades_db()
        if not db:
            return jsonify({"trades": [], "error": "trades.db not yet created (no closes yet)"})
        con = _sqlite3.connect(db)
        con.row_factory = _sqlite3.Row
        rows = con.execute(
            "SELECT * FROM trades ORDER BY ts DESC LIMIT 50"
        ).fetchall()
        con.close()
        return jsonify({"trades": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"trades": [], "error": str(e)}), 500

@app.route('/trades/stat')
def trades_stat():
    try:
        db = _fetch_trades_db()
        if not db:
            return jsonify({"total":0,"wins":0,"losses":0,"total_pnl":0.0,"win_rate":0.0,"avg_pnl":0.0,"error":"no data"})
        con = _sqlite3.connect(db)
        row = con.execute("""
            SELECT
                COUNT(*)                                    AS total,
                SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END)    AS wins,
                SUM(CASE WHEN pnl<=0 THEN 1 ELSE 0 END)   AS losses,
                ROUND(SUM(pnl),2)                          AS total_pnl,
                ROUND(AVG(pnl),2)                          AS avg_pnl
            FROM trades
        """).fetchone()
        con.close()
        total = row[0] or 0
        wins  = row[1] or 0
        return jsonify({
            "total": total, "wins": wins, "losses": row[2] or 0,
            "total_pnl": row[3] or 0.0, "avg_pnl": row[4] or 0.0,
            "win_rate": round(wins/total*100, 1) if total else 0.0
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/trades/position')
def trades_position():
    """实时持仓快照 — 从 .11 position_manager HTTP 或 snapshot 文件"""
    try:
        import urllib.request, json as _json
        url = 'http://192.168.0.11:6001/snapshot'
        with urllib.request.urlopen(url, timeout=3) as r:
            data = _json.loads(r.read())
        return jsonify(data)
    except Exception as e:
        return jsonify({"state": "UNKNOWN", "error": str(e)})


# ── tech_scanner 扫描状态 ──────────────────────────────
_scanner_status: dict = {}

@app.route('/scanner/status', methods=['POST'])
def scanner_status_post():
    data = request.get_json()
    node = data.get('node', 'unknown')
    data['updated_at'] = __import__('datetime').datetime.now().isoformat()
    _scanner_status[node] = data
    return jsonify({'status': 'ok'})

@app.route('/scanner/status', methods=['GET'])
def scanner_status_get():
    return jsonify(_scanner_status)

app.run(host='0.0.0.0', port=5800, debug=False)
