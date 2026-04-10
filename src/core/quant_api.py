#!/usr/bin/env python3
"""
quant_api.py — QuantForce Labs 数据接口
v1.2 | 2026-04-10 | .15退役，读PG，全节点metrics模式
"""
import os, json, time, logging, subprocess, re, socket
import urllib.request
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format='%(asctime)s [API] %(levelname)s %(message)s')
log = logging.getLogger(__name__)
app = Flask(__name__)
CORS(app)

# ── PostgreSQL ────────────────────────────────────────────────
def get_pg():
    return psycopg2.connect(
        host=os.getenv('PG_HOST','192.168.0.18'),
        port=os.getenv('PG_PORT','5432'),
        dbname=os.getenv('PG_DB','quantforce'),
        user=os.getenv('PG_USER','heng'),
        password=os.getenv('PG_PASS',''),
        cursor_factory=RealDictCursor
    )

# ── 节点列表（无 .15）────────────────────────────────────────
NODES = {
    'main':     '192.168.0.18',
    'executor': '192.168.0.11',
    'compute':  '192.168.0.143',
    'sentry':   '192.168.0.101',
    'courier':  '192.168.0.102',
}

# ── 基础端点 ─────────────────────────────────────────────────
@app.route('/health')
def health():
    return jsonify({'status':'ok','timestamp':datetime.now().isoformat(),'node':'192.168.0.18'})

@app.route('/signal', methods=['POST'])
def inject_signal():
    """手动注入信号到 signals_raw"""
    data = request.get_json()
    required = ['ticker','score','rvol','price']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({'error': f'缺少字段: {missing}'}), 400
    try:
        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO signals_raw (symbol,signal_type,confidence,source,pipeline,event_hash,expire_at,status,features)
                    VALUES (%s,'manual',%s,'api','quant_api',md5(%s::text),NOW()+INTERVAL '2 hours','pending','{}')
                    ON CONFLICT (event_hash) DO NOTHING
                """, (data['ticker'], min(data['score']/10,1.0), json.dumps(data)))
            conn.commit()
        return jsonify({'status':'sent','ticker':data['ticker']})
    except Exception as e:
        return jsonify({'error':str(e)}), 500

# ── 节点状态 ─────────────────────────────────────────────────
@app.route('/nodes')
@app.route('/nodes/list')
def get_nodes():
    result = []
    for name, ip in NODES.items():
        r = subprocess.run(['ping','-c1','-W1',ip], capture_output=True)
        result.append({'node':name,'ip':ip,'reachable': r.returncode==0})
    return jsonify(result)

@app.route('/nodes/metrics')
def get_nodes_metrics():
    result = []
    # 混合模式：.18/.11/.101 用 node_exporter metrics，.143/.102 用旧 stats JSON
    STATS_NODES = {'compute','courier'}
    for name, ip in NODES.items():
        try:
            if name in STATS_NODES:
                with urllib.request.urlopen(f'http://{ip}:9100/stats', timeout=2) as r:
                    data = json.loads(r.read())
                cpu, mem = data['cpu'], data['mem']
            else:
                with urllib.request.urlopen(f'http://{ip}:9100/metrics', timeout=2) as r:
                    text = r.read().decode()
                idle_vals = re.findall(r'node_cpu_seconds_total\{[^}]*mode="idle"[^}]*\}\s+([\d.e+]+)', text)
                all_vals  = re.findall(r'node_cpu_seconds_total\{[^}]*\}\s+([\d.e+]+)', text)
                idle  = sum(float(x) for x in idle_vals)
                total = sum(float(x) for x in all_vals)
                cpu = round((1 - idle/total)*100, 1) if total else 0
                mem_total = float(re.search(r'node_memory_MemTotal_bytes\s+([\d.e+]+)', text).group(1))
                mem_avail = float(re.search(r'node_memory_MemAvailable_bytes\s+([\d.e+]+)', text).group(1))
                mem = round((1 - mem_avail/mem_total)*100, 1)
            result.append({'node':name,'ip':ip,'cpu':cpu,'mem':mem})
        except:
            result.append({'node':name,'ip':ip,'cpu':-1,'mem':-1})
    return jsonify(result)

@app.route('/nodes/combined')
def nodes_combined():
    return get_nodes_metrics()

# ── 服务状态 ─────────────────────────────────────────────────
@app.route('/services/status')
def services_status():
    result = []
    # signal_fusion — 本机进程检查
    r = subprocess.run(['pgrep','-f','signal_fusion.py'], capture_output=True)
    result.append({'service':'dispatcher 信号调度','host':'192.168.0.18',
                   'status':'UP' if r.returncode==0 else 'DOWN'})
    # 其他服务 — TCP 端口检查
    for svc, host, port in [
        ('ib-executor 交易执行',  '192.168.0.11',  5558),
        ('news-scanner 新闻扫描', '192.168.0.143', 9100),
        ('compute 计算节点',      '192.168.0.143', 9100),
        ('sentry 哨兵节点',       '192.168.0.101', 9100),
        ('courier 信使节点',      '192.168.0.102', 9100),
        ('quant-api 数据接口',    '192.168.0.18',  5800),
    ]:
        try:
            s = socket.create_connection((host,port), timeout=2); s.close()
            status = 'UP'
        except:
            status = 'DOWN'
        result.append({'service':svc,'host':host,'status':status})
    return jsonify(result)

@app.route('/dispatcher/status')
def dispatcher_status():
    r = subprocess.run(['pgrep','-f','signal_fusion.py'], capture_output=True)
    return jsonify({'status':'active' if r.returncode==0 else 'inactive'})

@app.route('/dispatcher/stat')
def dispatcher_stat():
    r = subprocess.run(['pgrep','-f','signal_fusion.py'], capture_output=True)
    val = 1 if r.returncode==0 else 0
    return jsonify([{'service':'signal_fusion','status':val}])

# ── 信号统计（读PG）─────────────────────────────────────────
@app.route('/signals/stat')
def signals_stat():
    try:
        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as cnt FROM signals_raw")
                total = cur.fetchone()['cnt']
                cur.execute("SELECT COUNT(*) as cnt FROM signals_final WHERE status='executed'")
                passed = cur.fetchone()['cnt']
                cur.execute("SELECT COUNT(*) as cnt FROM signals_final WHERE status='filtered'")
                failed = cur.fetchone()['cnt']
        pass_rate = round(passed/total*100,1) if total else 0
        return jsonify([
            {'metric':'总信号', 'value':total},
            {'metric':'通过',   'value':passed},
            {'metric':'过滤',   'value':failed},
            {'metric':'通过率%','value':pass_rate},
        ])
    except Exception as e:
        return jsonify({'error':str(e)}), 500

@app.route('/signals/recent')
def signals_recent():
    try:
        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, to_char(created_at,'YYYY-MM-DD"T"HH24:MI:SS') as ts,
                           symbol as ticker,
                           CASE WHEN status='pending' THEN 'PENDING'
                                WHEN status='executed' THEN 'PASS'
                                ELSE 'FAIL' END as result,
                           COALESCE((features->>'score')::float, 0) as score,
                           COALESCE((features->>'rvol')::float, 0) as rvol,
                           COALESCE((features->>'price')::float, 0) as price,
                           '-' as llm_note
                    FROM signals_raw
                    ORDER BY id DESC LIMIT 20
                """)
                rows = cur.fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'error':str(e)}), 500

# ── 交易统计（读PG executions表）───────────────────────────
@app.route('/trades/stat')
def trades_stat():
    try:
        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN action='BUY' THEN 1 ELSE 0 END) as buys,
                           0 as wins, 0 as losses,
                           0.0 as total_pnl, 0.0 as avg_pnl
                    FROM executions
                """)
                row = cur.fetchone()
        return jsonify({
            'total': row['total'] or 0,
            'wins': 0, 'losses': 0,
            'total_pnl': 0.0, 'avg_pnl': 0.0,
            'win_rate': 0.0
        })
    except Exception as e:
        return jsonify({'total':0,'wins':0,'losses':0,'total_pnl':0.0,'win_rate':0.0,'avg_pnl':0.0})

@app.route('/trades/recent')
def trades_recent():
    try:
        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT to_char(ts,'YYYY-MM-DD"T"HH24:MI:SS') as ts,
                           symbol, action, qty, price, order_type,
                           ib_order_id, phi3_note, status
                    FROM executions ORDER BY ts DESC LIMIT 50
                """)
                rows = cur.fetchall()
        return jsonify({'trades':[dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'trades':[],'error':str(e)})

@app.route('/trades/position')
def trades_position():
    try:
        with urllib.request.urlopen('http://192.168.0.11:6001/snapshot', timeout=3) as r:
            return jsonify(json.loads(r.read()))
    except:
        return jsonify({'state':'UNKNOWN','positions':{}})

# ── Scanner 状态 ─────────────────────────────────────────────
_scanner_status: dict = {}

@app.route('/scanner/status', methods=['POST'])
def scanner_status_post():
    data = request.get_json()
    node = data.get('node','unknown')
    data['updated_at'] = datetime.now().isoformat()
    _scanner_status[node] = data
    return jsonify({'status':'ok'})

@app.route('/scanner/status', methods=['GET'])
def scanner_status_get():
    return jsonify(_scanner_status)

# ── Grafana SimpleJSON ────────────────────────────────────────
@app.route('/grafana')
def grafana_health():
    return 'OK', 200

@app.route('/grafana/search', methods=['POST'])
def grafana_search():
    return jsonify(['dispatcher_status','node_main','node_executor',
                    'node_compute','node_sentry','node_courier','api_status'])

@app.route('/grafana/query', methods=['POST'])
def grafana_query():
    req = request.get_json()
    results = []
    now_ms = int(time.time()*1000)
    for target in req.get('targets',[]):
        t = target.get('target','')
        if t == 'dispatcher_status':
            r = subprocess.run(['pgrep','-f','signal_fusion.py'], capture_output=True)
            val = 1 if r.returncode==0 else 0
            results.append({'target':'dispatcher','datapoints':[[val,now_ms]]})
        elif t == 'api_status':
            results.append({'target':'api','datapoints':[[1,now_ms]]})
        elif t.startswith('node_'):
            node = t.replace('node_','')
            ip = NODES.get(node,'')
            r = subprocess.run(['ping','-c1','-W1',ip], capture_output=True)
            val = 1 if r.returncode==0 else 0
            results.append({'target':node,'datapoints':[[val,now_ms]]})
    return jsonify(results)

@app.route('/grafana/annotations', methods=['POST'])
def grafana_annotations():
    return jsonify([])

if __name__ == '__main__':
    log.info("QuantForce API v1.2 starting on :5800")
    app.run(host='0.0.0.0', port=5800, debug=False)
